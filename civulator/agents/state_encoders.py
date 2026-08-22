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

from ..game.terrain import Terrain


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
    MAX_TERRAIN_COST = 3.0

    def __init__(self, fog_of_war=None):
        if fog_of_war is None:
            from ..config import CFG
            fog_of_war = CFG.get("training", {}).get("fog_of_war", False)
        self.fog_of_war = fog_of_war
        self._terrain_cache = None  # Cached terrain layer (static per episode)
        self._terrain_cache_id = None  # Map object id for cache invalidation

    def get_depth(self, num_players):
        return 27 if self.fog_of_war else 25

    def _get_terrain_layer(self, game_env):
        """Return cached terrain cost layer, rebuilding only on new episode."""
        map_id = id(game_env.map)
        if self._terrain_cache is not None and self._terrain_cache_id == map_id:
            return self._terrain_cache

        n, m = game_env.n, game_env.m
        terrain = np.zeros((n, m), dtype=np.float32)
        for i in range(n):
            for j in range(m):
                tile = game_env.map.tiles[i, j]
                if tile is not None:
                    cost = Terrain.MOVEMENT_COSTS.get(tile.terrain_type, 1)
                    terrain[i, j] = min(cost, self.MAX_TERRAIN_COST) / self.MAX_TERRAIN_COST
        self._terrain_cache = terrain
        self._terrain_cache_id = map_id
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
        tile = game_env.map.tiles[i, j]
        terrain_bonus = Terrain.DEFENSE_MODIFIERS.get(tile.terrain_type, 0) if tile else 0
        state[ch_stats + 5, i, j] = (fort_bonus + terrain_bonus) / self.MAX_DEFENSE_BONUS

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        n, m = game_env.n, game_env.m
        state = np.zeros((self.get_depth(len(game_env.players)), n, m), dtype=np.float32)

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
