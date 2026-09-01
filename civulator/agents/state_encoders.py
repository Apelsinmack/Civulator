"""State encoders that convert raw game state to agent-specific tensor representations.

Each agent can use a different encoder, enabling experiments that compare
different state representations against each other.

Performance notes:
- Terrain layer is cached per episode (static)
- Unit/city layers are sparse-filled from entity lists (no full-grid loops)
- Built as numpy arrays, converted to torch tensor once at the end
"""

from abc import ABC, abstractmethod

import numpy as np
import torch

from .. import hexmath


def _clamp01(value):
    """Clamp a scalar (or numpy value) to [0, 1]."""
    return min(1.0, max(0.0, value))


class StateEncoder(ABC):
    """Abstract base class for state encoders."""

    @abstractmethod
    def encode(self, game_env, player_index, device=None):
        """Convert raw game state to a tensor for the network.

        Args:
            game_env: The GameEnvironment instance
            player_index: Index of the player whose perspective to encode
            device: Torch device to place the tensor on

        Returns:
            torch.Tensor of shape [depth, height, width]
        """

    @abstractmethod
    def get_depth(self, num_players):
        """Return the depth (channel count) of the output tensor."""


class BasicStateEncoder(StateEncoder):
    """The current encoder: cities, unit health, and movement per player.

    Tensor layout (d = 2 * num_players + 1):
        Layer 0: Current player's cities (100 at city tiles)
        Layer 1: Current player's unit health
        Layer 2: Current player's unit movement points
        Layer 3: Enemy 1 cities (-100)
        Layer 4: Enemy 1 unit health (negative)
        ... (repeat for additional enemies)
    """

    def get_depth(self, num_players):
        return 2 * num_players + 1

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        n, m = game_env.n, game_env.m
        num_players = len(game_env.players)
        d = self.get_depth(num_players)

        # Build as numpy, convert once
        state = np.zeros((d, n, m), dtype=np.float32)

        current_player = game_env.players[player_index]

        # Layer 0: Current player's cities
        for city in current_player.cities:
            i, j = city.coordinates
            state[0, i, j] = 100

        # Layer 1-2: Current player's unit health and movement
        for unit in current_player.units:
            i, j = unit.coordinates
            state[1, i, j] = unit.health
            state[2, i, j] = unit.movement_points

        # Enemy layers
        layer_index = 3
        for player in game_env.players:
            if player == current_player:
                continue
            for city in player.cities:
                i, j = city.coordinates
                state[layer_index, i, j] = -100
            for unit in player.units:
                i, j = unit.coordinates
                state[layer_index + 1, i, j] = -unit.health
            layer_index += 2

        return torch.from_numpy(state).to(device)


class EnhancedStateEncoder(StateEncoder):
    """Rich state encoder with unit class one-hot, stats, terrain, and cities.

    Relationship-based encoding: own units get full detail, enemy units get
    full detail from opponent's perspective. Scales to N players by merging
    all enemies into the same enemy channels (2-player) or using
    own/ally/neutral/enemy groupings (future N-player).

    Tensor layout (25 channels for 2-player):
        Channels 0-4:   Own unit class one-hot (melee/spear/ranged/cavalry/siege)
        Channels 5-10:  Own unit stats (HP, melee_str, ranged_str, range, movement, defense_bonus)
        Channels 11-15: Enemy unit class one-hot
        Channels 16-21: Enemy unit stats
        Channel 22:     Own cities (1 at city tile)
        Channel 23:     Enemy cities (1 at city tile)
        Channel 24:     Terrain movement cost (normalized, cached per episode)

    Fog of war (config.toml [training] fog_of_war, or fog_of_war= kwarg):
        When on, the encoder applies the engine's perception masks — three
        knowledge states: visible / explored-but-fogged / hidden:
        - enemy units only where currently visible (units move)
        - enemy cities and terrain only where ever explored (they don't move)
        - two extra channels so the network can tell "empty" from "unseen":
            Channel 25: currently visible mask
            Channel 26: explored (fog memory) mask
        Depth becomes 27. When off (default), output is identical to the
        pre-fog encoder (depth 25).
    """

    CLASS_INDEX = {
        "Warrior": 0, "Swordsman": 0, "Spearman": 1,
        "Archer": 2, "Horseman": 3, "Catapult": 4,
        "Settler": -1, "Worker": -1,
    }

    MAX_MELEE_STR = 50.0
    MAX_RANGED_STR = 50.0
    MAX_RANGE = 2.0
    MAX_MOVEMENT = 4.0
    MAX_DEFENSE_BONUS = 12.0
    # v0.6 (design doc E6): 3 -> 4 so that saturation (1.0) again means
    # "impassable" and nothing else — the costliest passable composite
    # (hills + Woods = 3) now sits at 0.75. At the old clamp forested hills
    # aliased mountains and oceans, which is fatal on water worlds.
    MAX_TERRAIN_COST = 4.0

    def __init__(self, fog_of_war=None):
        if fog_of_war is None:
            from ..config import CFG
            fog_of_war = CFG.get("training", {}).get("fog_of_war", False)
        self.fog_of_war = fog_of_war
        self._terrain_cache = None  # Cached terrain layer (static per episode)
        self._terrain_cache_key = None  # (map_uid, terrain_epoch) — design doc §3.4

    def get_depth(self, num_players):
        return self._own_depth()

    def _own_depth(self):
        """EnhancedStateEncoder's own channel count (25/27), independent of
        the PUBLIC get_depth() a subclass (e.g. TerrainAwareStateEncoder)
        may override to report a larger total. encode() below sizes its
        array via this, not get_depth() — calling self.get_depth() there
        would dynamically dispatch to the SUBCLASS's override when invoked
        through super().encode(), inflating the parent's own array before
        the subclass even appends its block (a template-method footgun:
        the "unchanged prefix" contract in docs/terrain_encoder_design.md
        depends on this staying un-overridden).
        """
        return 27 if self.fog_of_war else 25

    def _get_terrain_layer(self, game_env):
        """Return the cached terrain cost layer, rebuilt when the terrain changes.

        Keyed on (map_uid, terrain_epoch) per design doc §3.4: id(map) could
        alias a recycled object after GC, and terrain edits (Tile.set_layers)
        must invalidate.
        """
        key = (game_env.map.map_uid, game_env.map.terrain_epoch)
        if self._terrain_cache is not None and self._terrain_cache_key == key:
            return self._terrain_cache

        n, m = game_env.n, game_env.m
        terrain = np.zeros((n, m), dtype=np.float32)
        for i in range(n):
            for j in range(m):
                tile = game_env.map.tiles[i, j]
                if tile is not None:
                    # Impassable pins to the max, so 1.0 is unique to it (E6)
                    cost = self.MAX_TERRAIN_COST if tile.impassable else tile.movement_cost
                    terrain[i, j] = min(cost, self.MAX_TERRAIN_COST) / self.MAX_TERRAIN_COST
        self._terrain_cache = terrain
        self._terrain_cache_key = key
        return terrain

    def _encode_unit(self, state, unit, ch_class, ch_stats, game_env):
        """Write one unit's data into the state array."""
        i, j = unit.coordinates
        cls_idx = self.CLASS_INDEX.get(unit.unit_type, -1)
        if cls_idx >= 0:
            state[ch_class + cls_idx, i, j] = 1.0
        state[ch_stats, i, j] = unit.health / 100.0
        state[ch_stats + 1, i, j] = unit.get_base_combat_strength() / self.MAX_MELEE_STR
        state[ch_stats + 2, i, j] = unit.get_base_ranged_strength() / self.MAX_RANGED_STR
        state[ch_stats + 3, i, j] = unit.get_range() / self.MAX_RANGE
        state[ch_stats + 4, i, j] = unit.movement_points / self.MAX_MOVEMENT
        # Defense bonus
        fort_bonus = 0
        if unit.fortification == 1:
            fort_bonus = 3
        elif unit.fortification >= 2:
            fort_bonus = 6
        # Composed defense of the tile the unit is standing on RIGHT NOW —
        # the engine reads the same number (design doc E6 / §9.7-8; before 0.6
        # both sides used a spawn-time terrain snapshot). Clamped at 1.0:
        # hills + Woods + full fortification is exactly MAX_DEFENSE_BONUS.
        tile = game_env.map.tiles[i, j]
        terrain_bonus = tile.defense_bonus if tile else 0
        state[ch_stats + 5, i, j] = min(
            (fort_bonus + terrain_bonus) / self.MAX_DEFENSE_BONUS, 1.0
        )

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        n, m = game_env.n, game_env.m
        state = np.zeros((self._own_depth(), n, m), dtype=np.float32)

        current_player = game_env.players[player_index]

        if self.fog_of_war:
            visible = game_env.get_visibility_mask(player_index)
            # Union for robustness on hand-built envs that never called
            # update_exploration; explored always contains visible
            explored = game_env.get_explored_mask(player_index) | visible
        else:
            visible = explored = None

        # Own units (ch 0-4 class, ch 5-10 stats)
        for unit in current_player.units:
            self._encode_unit(state, unit, 0, 5, game_env)

        # Enemy units (ch 11-15 class, ch 16-21 stats) — units move, so under
        # fog they exist only where currently visible
        for player in game_env.players:
            if player == current_player:
                continue
            for unit in player.units:
                if visible is not None and not visible[unit.coordinates]:
                    continue
                self._encode_unit(state, unit, 11, 16, game_env)

        # Own cities (ch 22)
        for city in current_player.cities:
            i, j = city.coordinates
            state[22, i, j] = 1.0

        # Enemy cities (ch 23) — cities don't move, so under fog they are
        # remembered wherever the player has ever explored
        for player in game_env.players:
            if player == current_player:
                continue
            for city in player.cities:
                i, j = city.coordinates
                if explored is not None and not explored[i, j]:
                    continue
                state[23, i, j] = 1.0

        # Terrain (ch 24) — cached per episode; under fog only where explored
        terrain = self._get_terrain_layer(game_env)
        if explored is not None:
            state[24] = terrain * explored
            state[25] = visible.astype(np.float32)
            state[26] = explored.astype(np.float32)
        else:
            state[24] = terrain

        return torch.from_numpy(state).to(device)


class TerrainAwareStateEncoder(EnhancedStateEncoder):
    """EnhancedStateEncoder plus a 27-channel terrain block (design doc
    `docs/terrain_encoder_design.md`, issue #40).

    The parent's channel block (0..24 no-fog / 0..26 fog) is the UNCHANGED
    PREFIX -- bit-identical to EnhancedStateEncoder.encode() output; the
    terrain block below is appended after it.

    Terrain block -- 27 channels, offsets relative to the block start:
        +0..+7   Base terrain one-hot (BASE_ORDER, pinned)
        +8..+9   Relief: hills, mountain (flat = both 0)
        +10..+16 Feature one-hot (FEATURE_ORDER, pinned; none = all 0)
        +17      Resource presence (1.0 if tile.resource is not None)
        +18..+20 River on owned edge (Map._river_flags_grid() bits 0..2,
                  hexmath.HEX_DIRECTIONS[:3] -- the canonical owned-edge
                  convention)
        +21      Water access ordinal: 1.0 fresh (Map._fresh_water_grid());
                  else 0.5 if any hex neighbor (hexmath.adjacent_coords) has
                  water domain; else 0.0
        +22      Composed defense: tile.defense_bonus / max_defense, [0,1]
        +23..+24 Composed yields: food / max_food, production / max_production, [0,1]
        +25..+26 Composed LoS: obstacle / max_obstacle, vantage / max_vantage, [0,1]

    Depth: 25+27 = 52 (no fog), 27+27 = 54 (fog).

    Normalization: each scalar max is DERIVED from the config terrain tables
    (never hand-tuned) as the sum of per-table maxima -- max over base
    entries + max over relief + max over feature + max over resource,
    missing keys contributing 0 -- floored at 1.0. Deterministic given
    config; the manifest already pins config per run.

    Caching: the whole 27-channel block is static per (map_uid,
    terrain_epoch) and cached exactly like the parent's _get_terrain_layer
    (design doc §3.4). Under fog, the entire cached block is multiplied by
    the `explored` mask (same rule the parent applies to its own terrain
    channel) -- the parent's visible/explored mask channels keep their
    existing positions inside the prefix.
    """

    # Pinned order (design doc): __init__ verifies every base/feature in
    # config's tables is covered here -- unknown values raise, never silence.
    BASE_ORDER = ["Grassland", "Plains", "Desert", "Tundra", "Snow", "Coast", "Lake", "Ocean"]
    FEATURE_ORDER = ["Woods", "Rainforest", "Marsh", "Floodplains", "Oasis", "Reef", "Ice"]
    TERRAIN_BLOCK_DEPTH = 27

    def __init__(self, fog_of_war=None):
        super().__init__(fog_of_war=fog_of_war)

        from ..terrain_model import BASE_TABLE, FEATURE_TABLE, RELIEF_TABLE, RESOURCE_TABLE

        missing_bases = set(BASE_TABLE) - set(self.BASE_ORDER)
        if missing_bases:
            raise ValueError(
                f"TerrainAwareStateEncoder.BASE_ORDER does not cover config "
                f"base terrain(s): {sorted(missing_bases)}"
            )
        missing_features = set(FEATURE_TABLE) - set(self.FEATURE_ORDER)
        if missing_features:
            raise ValueError(
                f"TerrainAwareStateEncoder.FEATURE_ORDER does not cover config "
                f"feature(s): {sorted(missing_features)}"
            )

        self._base_index = {name: i for i, name in enumerate(self.BASE_ORDER)}
        self._feature_index = {name: i for i, name in enumerate(self.FEATURE_ORDER)}

        tables = (BASE_TABLE, RELIEF_TABLE, FEATURE_TABLE, RESOURCE_TABLE)
        self.max_defense = self._table_max_sum(tables, lambda e: e.get("defense", 0))
        self.max_food = self._table_max_sum(tables, lambda e: e.get("yields", (0, 0))[0])
        self.max_production = self._table_max_sum(tables, lambda e: e.get("yields", (0, 0))[1])
        self.max_obstacle = self._table_max_sum(tables, lambda e: e.get("los", (0, 0))[0])
        self.max_vantage = self._table_max_sum(tables, lambda e: e.get("los", (0, 0))[1])

        self._terrain_block_cache = None
        self._terrain_block_cache_key = None  # (map_uid, terrain_epoch) — design doc §3.4

    @staticmethod
    def _table_max_sum(tables, extractor):
        """Sum of each table's per-entry maximum (design doc "Normalization"):
        an empty table or all-missing-key entries contribute 0 to the sum
        (via `extractor`'s own .get default); the final sum is floored at 1.0.
        """
        total = 0
        for table in tables:
            values = [extractor(entry) for entry in table.values()]
            if values:
                total += max(values)
        return max(1.0, total)

    def get_depth(self, num_players):
        return super().get_depth(num_players) + self.TERRAIN_BLOCK_DEPTH

    def _get_terrain_block(self, game_env):
        """Return the cached 27-channel terrain block, rebuilt when the
        terrain changes -- same (map_uid, terrain_epoch) cache pattern as
        the parent's _get_terrain_layer (design doc §3.4).
        """
        key = (game_env.map.map_uid, game_env.map.terrain_epoch)
        if self._terrain_block_cache is not None and self._terrain_block_cache_key == key:
            return self._terrain_block_cache

        n, m = game_env.n, game_env.m
        block = np.zeros((self.TERRAIN_BLOCK_DEPTH, n, m), dtype=np.float32)
        river_flags = game_env.map._river_flags_grid()
        fresh = game_env.map._fresh_water_grid()

        for i in range(n):
            for j in range(m):
                tile = game_env.map.tiles[i, j]
                if tile is None:
                    continue

                base_idx = self._base_index.get(tile.base_terrain)
                if base_idx is None:
                    raise ValueError(
                        f"TerrainAwareStateEncoder: unknown base terrain "
                        f"{tile.base_terrain!r} at ({i}, {j}) — not in BASE_ORDER"
                    )
                block[base_idx, i, j] = 1.0

                if tile.relief == "hills":
                    block[8, i, j] = 1.0
                elif tile.relief == "mountain":
                    block[9, i, j] = 1.0

                if tile.feature is not None:
                    feature_idx = self._feature_index.get(tile.feature)
                    if feature_idx is None:
                        raise ValueError(
                            f"TerrainAwareStateEncoder: unknown feature "
                            f"{tile.feature!r} at ({i}, {j}) — not in FEATURE_ORDER"
                        )
                    block[10 + feature_idx, i, j] = 1.0

                if tile.resource is not None:
                    block[17, i, j] = 1.0

                flags = river_flags[i, j]
                block[18, i, j] = 1.0 if flags & 1 else 0.0
                block[19, i, j] = 1.0 if flags & 2 else 0.0
                block[20, i, j] = 1.0 if flags & 4 else 0.0

                if fresh[i, j]:
                    water_access = 1.0
                else:
                    water_access = 0.0
                    for neighbor in hexmath.adjacent_coords((i, j), n, m):
                        neighbor_tile = game_env.map.get_tile(neighbor)
                        if neighbor_tile is not None and neighbor_tile.domain == "water":
                            water_access = 0.5
                            break
                block[21, i, j] = water_access

                block[22, i, j] = _clamp01(tile.defense_bonus / self.max_defense)
                food, production = tile.yields
                block[23, i, j] = _clamp01(food / self.max_food)
                block[24, i, j] = _clamp01(production / self.max_production)
                obstacle, vantage = tile.los
                block[25, i, j] = _clamp01(obstacle / self.max_obstacle)
                block[26, i, j] = _clamp01(vantage / self.max_vantage)

        self._terrain_block_cache = block
        self._terrain_block_cache_key = key
        return block

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        parent_state = super().encode(game_env, player_index, device=device)

        terrain_block = self._get_terrain_block(game_env)
        if self.fog_of_war:
            visible = game_env.get_visibility_mask(player_index)
            explored = game_env.get_explored_mask(player_index) | visible
            terrain_block = terrain_block * explored[np.newaxis, :, :].astype(np.float32)

        terrain_tensor = torch.from_numpy(terrain_block).to(device)
        return torch.cat([parent_state, terrain_tensor], dim=0)


class CityDistanceStateEncoder(EnhancedStateEncoder):
    """EnhancedStateEncoder plus ONE appended channel: a proximity field to
    the nearest enemy city (issue #48).

    Why: the FullyConv Q-network's receptive field is ~3 hexes, while duel
    capitals sit ~12 apart — enemy cities (a single 1.0 on channel 23) are
    architecturally invisible from afar, so directed marching is not
    representable. This channel injects that global information per-tile:
    even a radius-1 network can then read which neighbor tile is closer to
    the enemy. Pairs with the #46 proximity shaping (same canonical
    hexmath.distance, plain hex distance — deliberately NOT path distance).

    Channel (appended after the parent's prefix, which stays bit-identical
    to EnhancedStateEncoder.encode() — same contract as terrain_aware):
        +0  proximity = 1 - d/D, where d = wrap hex distance to the nearest
            enemy city and D = cols//2 + rows - 1 (the maximum possible
            distance on the cylinder). Unclipped by design: the gradient is
            nonzero EVERYWHERE, so there is no far-field blindness. 1.0 on
            the city tile itself; all zeros when the enemy has no cities.

    Depth: 25+1 = 26 (no fog), 27+1 = 28 (fog).

    Fog: the field is computed from the same enemy-city set the parent's
    channel 23 shows — under fog only explored cities count (cities don't
    move, so explored = remembered). Fogged fields are computed uncached
    (the explored mask would have to join the cache key); fogless fields
    are cached on (map_uid, enemy-city coordinate set) — cities change only
    on found/capture, so this is effectively free (issue #48/#32: Python
    until the profiler objects).
    """

    CITY_DISTANCE_DEPTH = 1

    def __init__(self, fog_of_war=None):
        super().__init__(fog_of_war=fog_of_war)
        self._distance_cache = None
        self._distance_cache_key = None  # (map_uid, sorted enemy-city coords)

    def get_depth(self, num_players):
        return super().get_depth(num_players) + self.CITY_DISTANCE_DEPTH

    def _distance_field(self, game_env, enemy_city_coords):
        """Proximity field over the whole grid for the given city set.

        Calls the canonical hexmath.distance per (tile, city) pair — the
        hex-distance formula is never reimplemented here (the #24 lesson);
        at <=(rows*cols*n_cities) O(1) calls behind a cache, cost is nil.
        """
        n, m = game_env.n, game_env.m
        field = np.zeros((n, m), dtype=np.float32)
        if not enemy_city_coords:
            return field
        d_max = float(m // 2 + n - 1)
        for i in range(n):
            for j in range(m):
                d = min(
                    hexmath.distance((i, j), c, m) for c in enemy_city_coords
                )
                field[i, j] = 1.0 - d / d_max
        return field

    def _get_city_distance_layer(self, game_env, player_index, explored):
        current_player = game_env.players[player_index]
        coords = sorted(
            city.coordinates
            for player in game_env.players
            if player is not current_player
            for city in player.cities
        )
        if explored is not None:
            # Fog: only remembered (explored) enemy cities exist for this
            # player — mask-dependent, computed uncached (see class docstring).
            coords = [c for c in coords if explored[c]]
            return self._distance_field(game_env, coords)

        key = (game_env.map.map_uid, tuple(coords))
        if self._distance_cache is not None and self._distance_cache_key == key:
            return self._distance_cache
        field = self._distance_field(game_env, coords)
        self._distance_cache = field
        self._distance_cache_key = key
        return field

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        parent_state = super().encode(game_env, player_index, device=device)

        if self.fog_of_war:
            visible = game_env.get_visibility_mask(player_index)
            explored = game_env.get_explored_mask(player_index) | visible
        else:
            explored = None
        field = self._get_city_distance_layer(game_env, player_index, explored)

        field_tensor = torch.from_numpy(field[np.newaxis, :, :]).to(device)
        return torch.cat([parent_state, field_tensor], dim=0)


# --- Encoder registry (design doc `docs/terrain_encoder_design.md` #40) -----
#
# "State encoders are selected by name via state_encoders.get_encoder();
# scripts and the trainer never instantiate encoder classes directly." Kept
# open to "basic" (no fog_of_war concept) alongside the two names the design
# doc pins, so existing "basic"/"enhanced" callers (DQNAgent, scripts/train.py
# et al.) can route through the same registry without a behavior change.
_ENCODER_REGISTRY = {
    "basic": BasicStateEncoder,
    "enhanced": EnhancedStateEncoder,
    "terrain_aware": TerrainAwareStateEncoder,
    "city_distance": CityDistanceStateEncoder,
}


def get_encoder(name, fog_of_war=None):
    """Instantiate a state encoder by name (the project's canonical registry).

    Args:
        name: one of "basic", "enhanced", "terrain_aware", "city_distance".
        fog_of_war: forwarded to encoders that accept it (enhanced,
            terrain_aware, city_distance); None lets them fall back to
            config.toml [training] fog_of_war. Ignored for "basic" (no fog
            concept).

    Raises:
        ValueError: unknown name -- never silently falls back (e.g. to
            "basic"), matching the "unknown terrain -> error" philosophy
            elsewhere in this module.
    """
    cls = _ENCODER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown state encoder {name!r}; known encoders: "
            f"{sorted(_ENCODER_REGISTRY)}"
        )
    if cls is BasicStateEncoder:
        return cls()
    return cls(fog_of_war=fog_of_war)
