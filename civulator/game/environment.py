"""GameEnvironment -- the main game simulation interface."""

import logging

import numpy as np

from .map import Map
from .. import hexmath, mapgen
from ..mapgen.starts import StartPlacementError
from ..rng import PortableRNG
from ..terrain_model import can_enter, matches
from .player import Player
from .city import City
from .unit import WarriorUnit, movement_domain
from ..config import CFG

logger = logging.getLogger(__name__)

# Reward values: config.toml [training.rewards] overrides these defaults
# (same merge pattern as Terrain tables).
_DEFAULT_REWARDS = {
    "invalid_action": -1,
    "fortify": 0,
    "damage_per_hp": 0.1,
    "kill": 10,
    "unit_lost": -10,
    "capture_civilian": 15,
    "capture_city": 20,
    "found_city": 15,
    # Terminal rewards (issue #46) — delivered by the trainer at episode end.
    "win": 0,
    "loss": 0,
    "draw": 0,
    # Potential-based proximity shaping (issue #46). Defaults are neutral:
    # weight 0 disables shaping entirely; radius 0 means auto (cols//2 + 1).
    "proximity_weight": 0.0,
    "proximity_radius": 0,
}
REWARDS = {**_DEFAULT_REWARDS, **CFG.get("training", {}).get("rewards", {})}

# Discount used in the shaping term gamma*Phi(s') - Phi(s) — must match the
# agent's discount for the policy-invariance guarantee (Ng et al. 1999).
GAMMA = CFG.get("training", {}).get("gamma", 0.9)

_GAME_CFG = CFG.get("game", {})
STARTING_WARRIORS = _GAME_CFG.get("starting_warriors", 3)
MIN_CITY_DISTANCE = _GAME_CFG.get("min_city_distance", 3)

# `[map] type` is now a real, read key (design doc E5) — the constructor's
# `map_type=None` resolves to THIS, not a hardcoded literal, so config.toml
# is what "silently decides what painter/recorder/tests get" (E5's own
# framing of the pre-0.6 problem) rather than a value baked into this file.
# Tests/tools that need a specific generator (most do, at sub-Duel sizes)
# pass `map_type=` explicitly and are unaffected by this default.
_MAP_CFG = CFG.get("map", {})
DEFAULT_MAP_TYPE = _MAP_CFG.get("type", "earthlike")

# Size presets (design doc D14/§6, §11 P5) — `[map.sizes.*]` is the only
# source of dimensions and default player counts (project CLAUDE.md Systems
# table row); `[map] size` selects among them.
_SIZES_CFG = _MAP_CFG.get("sizes", {})
DEFAULT_SIZE_NAME = _MAP_CFG.get("size", "standard")

# Unseeded-reset resample policy (design doc D26, §11 P7.5): bound on how
# many fresh worlds `reset()` (no explicit seed) will try before giving up
# and raising. `reset(seed=N)` never consults this — an explicit seed always
# propagates StartPlacementError unchanged, on the first and only attempt.
MAX_WORLD_RETRIES = _MAP_CFG.get("max_world_retries", 10)


def resolve_size_and_players(size=None, num_players=None):
    """(rows, cols, num_players) resolved through `[map.sizes.*]` (design
    doc D14/§6, §11 P5 deliverable 3) — GameEnvironment's own "read config
    once at the call boundary" moment, mirroring `Map.generate_map`'s and
    the mapgen preview CLI's `_resolve_cli_size` (same table, same
    `mapgen.resolve_size` lookup — one preset table, a few thin
    call-boundary readers, never a second copy of the resolution logic).

    Args:
        size: a preset name (e.g. "duel"), or None -> `[map] size`
            (config default "standard").
        num_players: an explicit override, or None -> the resolved
            preset's own `default_players`.

    `GameEnvironment.__init__` calls this whenever n/m/num_players are
    omitted; the five run scripts P5 repoints (watch/train/train_shared/
    train_shared_large/replay) call it directly so their num_players
    fallbacks stop diverging (today: 2 vs 8, design doc §6 table).
    """
    name = size if size is not None else DEFAULT_SIZE_NAME
    rows, cols = mapgen.resolve_size(name, _SIZES_CFG)
    if num_players is None:
        num_players = _SIZES_CFG.get(name, {}).get("default_players", 2)
    return rows, cols, int(num_players)


# Improvement placement rules — the same `on` formalism as terrain layers
# (design doc §3.1, §9.6), replacing the hardcoded terrain lists this file
# used to carry. An improvement with no `on` entry is buildable nowhere.
IMPROVEMENTS = CFG.get("improvements", {})


class GameEnvironment:
    """Manages the game state and interactions between players, units, and the map.

    This is the central Gym-like interface:
        env.reset() -> raw game state
        env.step(action) -> (raw_state, reward, done, info)
    """

    def __init__(self, n=None, m=None, num_players=None, map_type=None, seed=None, size=None,
                 mapgen_params=None):
        """
        Args:
            n, m: Map rows/cols. Either may be omitted (None) to take the
                `size` preset's dimension instead (design doc D14/§6, §11
                P5) — explicit values always override the preset
                (`resolve_size_and_players`'s own contract).
            num_players: Player count, or None to take the resolved
                preset's `default_players`.
            size: A `[map.sizes.*]` preset name, or None for `[map] size`
                (config default "standard"). Ignored for any dimension/
                num_players given explicitly.
            mapgen_params: manifest-pinned flat generator params (design doc
                §8, §11 P7) — passed straight through to `Map.generate_map`,
                which then never reads live config.toml for this world. None
                (default) generates an ordinary brand-new world from
                config.toml, as always. `civulator.tools.recording.
                build_env_from_scenario` is the one caller that supplies
                this, extracted from a scenario's manifest.
        """
        preset_rows, preset_cols, resolved_players = resolve_size_and_players(size, num_players)
        self.n = n if n is not None else preset_rows
        self.m = m if m is not None else preset_cols
        self.num_players = resolved_players
        self.map_type = map_type if map_type is not None else DEFAULT_MAP_TYPE
        self.turn_counter = 1
        self.max_turns = 1000
        self.done = False
        self.players = []

        # All engine randomness (map gen, starting locations, damage rolls)
        # draws from this instance — reset(seed=...) reproduces a world exactly.
        # PortableRNG (PCG32, civulator/rng.py) so a C++ engine twin can
        # reproduce the identical stream (issue #33).
        self.rng = PortableRNG(seed)

        # Initialize map and players
        self.map = Map(self.n, self.m, rng=self.rng)
        self.map.generate_map(self.map_type, num_players=self.num_players, params=mapgen_params)

        for i in range(self.num_players):
            player = Player(f"Player {i+1}", i, self)
            self.players.append(player)

        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]

    def reset(self, num_players=None, seed=None):
        """Reset the game for a new episode.

        Args:
            num_players: Optionally change the player count.
            seed: If given, reseeds the engine RNG — the resulting map,
                starting locations, and all subsequent randomness are
                exactly reproducible.

        Returns:
            self: The reset game environment (agents extract what they need).

        Unseeded-reset resample policy (design doc D26, §11 P7.5): a single
        `_reset_attempt` builds one candidate world and seats every player on
        it, raising `StartPlacementError` on any contract violation (mapgen's
        own retry ladder exhausted, or — defensively — a delivered start that
        somehow still fails downstream). `seed=N` runs that attempt exactly
        ONCE and lets the exception propagate unchanged: reproducibility
        means a specific seed either works or fails loudly, never silently
        becomes a DIFFERENT world. Unseeded resets have no specific seed to
        be loyal to, so a bad world is worth resampling — `reset()` retries
        with the engine RNG's own continuing stream (each `_reset_attempt`
        draws its own fresh master seed via `Map.generate_map`, design doc
        §4.2.1), logging a warning per failure, bounded by
        `MAX_WORLD_RETRIES` (config `[map] max_world_retries`).
        """
        if num_players is not None:
            self.num_players = num_players
        if seed is not None:
            self.rng.seed(seed)

        self.turn_counter = 1
        self.done = False
        recreate_players = num_players is not None

        if seed is not None:
            self._reset_attempt(recreate_players)
        else:
            last_error = None
            for attempt in range(1, MAX_WORLD_RETRIES + 1):
                try:
                    self._reset_attempt(recreate_players)
                    last_error = None
                    break
                except StartPlacementError as exc:
                    last_error = exc
                    logger.warning(
                        "unseeded reset: world generation failed start placement "
                        "(master seed=%s, attempt %d/%d): %s",
                        self.map.last_master_seed, attempt, MAX_WORLD_RETRIES, exc,
                    )
            if last_error is not None:
                raise StartPlacementError(
                    f"unseeded reset: exhausted {MAX_WORLD_RETRIES} world "
                    f"retries (design doc D26, config [map] max_world_retries) "
                    f"— every attempt failed start placement; last failure: "
                    f"{last_error}"
                ) from last_error

        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]

        # Initial exploration: everyone knows their starting surroundings
        for i in range(len(self.players)):
            self.update_exploration(i)

        return self

    def _reset_attempt(self, recreate_players):
        """One attempt at building a world and seating every player on a
        capital + starting warriors (design doc §6.5/D26) — `reset()`'s
        single retried unit of work. Raises `StartPlacementError` on any
        contract violation and never partially commits across attempts: it
        always starts by building a brand-new `Map` (and, when
        `recreate_players`, brand-new `Player`s), so a raise here leaves
        only THIS attempt's state behind for `reset()` to either propagate
        (seeded) or discard by trying again from scratch (unseeded).
        """
        # Regenerate map
        self.map = Map(self.n, self.m, rng=self.rng)
        self.map.generate_map(self.map_type, num_players=self.num_players)

        # Reset or recreate players
        if recreate_players:
            self.players = []
            for i in range(self.num_players):
                player = Player(f"Player {i+1}", i, self)
                self.players.append(player)
        else:
            for player in self.players:
                player.units = []
                player.cities = []
                player.queued_units = []
                player.is_dead = False
                player.gold = 0
                player.science = 0
                player.culture = 0
                player.technologies = []
                player.policies = []
                player.explored = None

        # Starting locations come from mapgen (design doc §6, D13, §11 P5):
        # `self.map.starts` is `MapData.starts`, verbatim — fertility-scored,
        # region-balanced, d_min-spaced, and additively normalized already
        # (mapgen/starts.py). Players are assigned to starts via the engine
        # RNG shuffle (unchanged from before P5). reset() never re-rolls or
        # searches for a placement itself (design doc §3.3/§9.10: "trust
        # starts" — the old silent random-retry loop that could still leave
        # a player capital-less, issue #1, is gone by construction: mapgen
        # guarantees every delivered start is settleable before handing it
        # over, so the only remaining failure mode is a contract violation,
        # which raises instead of silently degrading). D26 amendment: that
        # raise now optionally triggers a WHOLE-WORLD resample one level up
        # in `reset()`, rather than always being fatal.
        starts = list(self.map.starts)
        if len(starts) != self.num_players:
            raise StartPlacementError(
                f"mapgen delivered {len(starts)} start(s) for {self.num_players} "
                f"player(s) — contract violation (design doc §6.5): "
                f"MapData.starts must carry exactly one start per player"
            )
        self.rng.shuffle(starts)

        warrior_domain = movement_domain("Warrior")
        for i, player in enumerate(self.players):
            start = starts[i]

            city = self.found_city(player, start, f"{player.name}'s Capital")
            if city is None:
                raise StartPlacementError(
                    f"delivered start {start} for {player.name} failed found_city "
                    f"— contract violation (design doc §6.5): mapgen's own "
                    f"settleability/min-distance guarantees should make this "
                    f"unreachable"
                )

            # Place starting warriors through the canonical terrain-domain
            # check (§3.3, §9.10), ring-1 first and spilling into ring-2 if
            # ring-1 lacks room (design doc §6.5) — `is_start_eligible`'s
            # own ">= 3 passable ring-1 tiles" guarantee (mapgen/starts.py)
            # makes ring-2 spillover a defensive path in practice, not a
            # routine one.
            _, ring1, ring2 = self.map.get_ring_coords(start, 2)
            warriors_placed = 0
            for pos in ring1 + ring2:
                if warriors_placed >= STARTING_WARRIORS:
                    break
                if not can_enter(warrior_domain, self.map.get_tile(pos)):
                    continue
                if self.is_valid_position(pos) and not self.is_occupied(pos):
                    unit = WarriorUnit(player, pos)
                    player.units.append(unit)
                    self.add_unit_to_tile(unit, pos)
                    warriors_placed += 1

    def step(self, action_matrix):
        """Execute an action in the game environment.

        Interprets select + order as a player would with two mouse clicks:
        - Select own unit, order to empty tile → move
        - Select own unit, order to same tile → fortify
        - Select own unit, order to enemy unit → attack
        - Select own unit, order to enemy city (no unit) → move and capture

        The returned reward includes the potential-based proximity shaping
        term gamma*Phi(s') - Phi(s) for the ACTING player (issue #46) —
        pinned at entry because _check_game_end can auto-advance the turn,
        changing current_player mid-step. Phi(terminal) := 0 by convention.
        With [training.rewards] proximity_weight = 0 the term is exactly 0
        and rewards are byte-identical to the pre-#46 behavior.

        Args:
            action_matrix: [select_position, order_position] as numpy arrays
                select_position can be (row, col) or (row, col, slot)

        Returns:
            tuple: (self, reward, done)
        """
        acting_player = self.current_player
        phi_before = self._proximity_potential(acting_player)
        _, reward, done = self._step_inner(action_matrix)
        phi_after = 0.0 if done else self._proximity_potential(acting_player)
        reward += GAMMA * phi_after - phi_before
        return self, reward, done

    def _proximity_potential(self, player):
        """Phi(s) = weight * sum over own military units of max(0, R - d).

        d = wrap hex distance to the nearest enemy city (canonical
        hexmath.distance); military = base combat strength > 0, so Settlers
        and Workers are never pulled toward danger. R = proximity_radius,
        or cols//2 + 1 when the config value is 0 (auto — scales with the
        map preset). weight 0 short-circuits to 0.0 (shaping disabled).
        """
        weight = REWARDS["proximity_weight"]
        if weight == 0:
            return 0.0
        radius = REWARDS["proximity_radius"] or (self.m // 2 + 1)
        enemy_cities = [
            city.coordinates
            for p in self.players
            if p is not player
            for city in p.cities
        ]
        if not enemy_cities:
            return 0.0
        total = 0.0
        for unit in player.units:
            if unit.get_base_combat_strength() <= 0:
                continue
            d = min(
                hexmath.distance(unit.coordinates, c, self.m)
                for c in enemy_cities
            )
            total += max(0, radius - d)
        return weight * total

    def _step_inner(self, action_matrix):
        reward = 0
        select_pos = tuple(action_matrix[0])
        order_pos = tuple(action_matrix[1])

        # End turn action
        if select_pos[0] == self.n:
            self.current_player.end_turn()
            self.next_turn()
            return self, 0, self.done

        # Find the selected unit — slot-aware if provided
        if len(select_pos) == 3:
            row, col, slot = select_pos
            selected_unit = self.get_unit_in_slot((row, col), slot, self.current_player)
        else:
            # Legacy 2-tuple: find first own unit at position
            selected_unit = None
            for unit in self.current_player.units:
                if unit.coordinates == select_pos:
                    selected_unit = unit
                    break

        if not selected_unit:
            return self, REWARDS["invalid_action"], self.done

        if selected_unit.movement_points <= 0:
            return self, REWARDS["invalid_action"], self.done

        # Select same tile: fortify, or found city if settler.
        # Compare positions only — select_pos may carry a third slot element.
        if select_pos[:2] == order_pos[:2]:
            if selected_unit.unit_type == "Settler":
                city = selected_unit.found_city(self)
                if city:
                    city.assign_tiles(self)
                    return self, REWARDS["found_city"], self.done
                else:
                    return self, REWARDS["invalid_action"], self.done  # Invalid location
            success = selected_unit.fortify()
            return self, (REWARDS["fortify"] if success else REWARDS["invalid_action"]), self.done

        # Check if order targets an enemy unit → attack
        enemy_unit = self._get_enemy_unit_at(order_pos)
        if enemy_unit is not None:
            reward = self._execute_attack(selected_unit, enemy_unit)
            self.update_exploration(self.current_player.player_index)
            self._check_game_end()
            return self, reward, self.done

        # Otherwise → movement
        moved, final_pos = selected_unit.move(order_pos, self)

        if not moved:
            return self, REWARDS["invalid_action"], self.done

        # Check if we captured a city
        tile = self.map.get_tile(final_pos)
        if tile and tile.city and tile.city.player != self.current_player:
            tile.city.set_owner(self.current_player)
            reward += REWARDS["capture_city"]

        # Movement changes what the player can see
        self.update_exploration(self.current_player.player_index)

        self._check_game_end()
        return self, reward, self.done

    def _get_enemy_unit_at(self, coordinates):
        """Get an enemy unit at the given position, or None."""
        units = self.get_units_at(coordinates)
        for unit in units:
            if unit.player != self.current_player:
                return unit
        return None

    def _execute_attack(self, attacker, defender):
        """Execute combat between attacker and defender. Returns reward.

        Ranged units (Archer, Catapult) can attack at range — their own
        attack() method validates distance and line of sight.
        Melee units must be adjacent.
        """
        reward = 0
        is_ranged = attacker.get_base_ranged_strength() > 0

        # Melee units must be adjacent; ranged units handle range in their attack()
        adj_coords = self.map.get_adjacent_coords(attacker.coordinates)
        if not is_ranged and defender.coordinates not in adj_coords:
            return REWARDS["invalid_action"]

        damage_dealt, damage_received, target_killed, attacker_killed = \
            attacker.attack(defender, self)

        # attack() returns (0,0,False,False) if out of range — treat as invalid
        if damage_dealt == 0 and not target_killed:
            return REWARDS["invalid_action"]

        # Attacking always consumes all movement points
        attacker.movement_points = 0

        # Reward for damage dealt
        reward += damage_dealt * REWARDS["damage_per_hp"]

        if target_killed:
            reward += REWARDS["kill"]
            # Capture civilian units (Settler, Worker) instead of killing them
            if defender.unit_type in ("Settler", "Worker") and not attacker_killed:
                defender.player.remove_unit(defender)
                defender.player = self.current_player
                self.current_player.units.append(defender)
                reward += REWARDS["capture_civilian"]
            else:
                self.delete_unit(defender)
            # Only melee attackers move into the vacated tile
            if not is_ranged and not attacker_killed:
                self.move_unit(attacker, defender.coordinates)
                # Check city capture
                tile = self.map.get_tile(attacker.coordinates)
                if tile and tile.city and tile.city.player != self.current_player:
                    tile.city.set_owner(self.current_player)
                    reward += REWARDS["capture_city"]

        if attacker_killed:
            reward += REWARDS["unit_lost"]
            self.delete_unit(attacker)

        return reward

    def _check_game_end(self):
        """Check if the game should end (all units spent, player eliminated, turn limit)."""
        # Auto-advance if all units spent
        if self.current_player.units:
            all_units_moved = all(u.movement_points == 0 for u in self.current_player.units)
            if all_units_moved:
                self.next_turn()
        else:
            # Player has no units left, end their turn
            self.next_turn()

        alive_players = [p for p in self.players if not p.is_dead]
        if len(alive_players) <= 1:
            self.done = True

        if self.turn_counter > self.max_turns:
            self.done = True

    def next_turn(self):
        """Advance to the next player's turn."""
        self.current_player.end_turn()

        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.current_player = self.players[self.current_player_index]

        if self.current_player_index == 0:
            self.turn_counter += 1

        self.current_player.start_turn()

        alive_players = [p for p in self.players if not p.is_dead]
        if len(alive_players) <= 1:
            self.done = True

        if self.turn_counter > self.max_turns:
            self.done = True

    # --- Perception (fog of war) ---
    # The engine owns the truth about what each player can see; encoders
    # decide whether/how to apply it (config.toml [training] fog_of_war).

    def get_visibility_mask(self, player_index):
        """(n, m) bool array: tiles currently visible to the player.

        Union of line-of-sight from every unit and city the player owns
        (cities have eyes too). Cheap after warm-up: per-tile visibility is
        cached on the Map because terrain is static within an episode.
        """
        mask = np.zeros((self.n, self.m), dtype=bool)
        player = self.players[player_index]
        for entity in list(player.units) + list(player.cities):
            for r, q in self.map.visible_from(entity.coordinates):
                mask[r, q] = True
        return mask

    def get_explored_mask(self, player_index):
        """(n, m) bool array: tiles the player has ever seen (fog memory)."""
        explored = self.players[player_index].explored
        if explored is None or explored.shape != (self.n, self.m):
            return np.zeros((self.n, self.m), dtype=bool)
        return explored

    def update_exploration(self, player_index):
        """Fold current visibility into the player's explored memory.

        Returns the current visibility mask.
        """
        vis = self.get_visibility_mask(player_index)
        player = self.players[player_index]
        if player.explored is None or player.explored.shape != (self.n, self.m):
            player.explored = vis.copy()
        else:
            player.explored |= vis
        return vis

    # --- Tile query helpers ---

    def is_river_between(self, coords1, coords2):
        return self.map.has_river_between(coords1, coords2)

    def check_line_of_sight(self, from_coords, to_coords):
        return self.map.check_line_of_sight(from_coords, to_coords)

    def is_valid_position(self, coordinates):
        return self.map.get_tile(coordinates) is not None

    def is_occupied(self, coordinates):
        tile = self.map.get_tile(coordinates)
        return tile is not None and len(tile.units) > 0

    def is_slot_occupied(self, coordinates, slot, player=None):
        """Check if a specific unit slot is occupied at coordinates.

        Args:
            coordinates: Tile position
            slot: Unit slot index (0=military, 1=civilian, 2=siege support, 3=great person)
            player: If given, only check units belonging to this player
        """
        units = self.get_units_at(coordinates)
        for u in units:
            if u.slot == slot:
                if player is None or u.player == player:
                    return True
        return False

    def get_unit_in_slot(self, coordinates, slot, player=None):
        """Get the unit in a specific slot at coordinates, or None."""
        units = self.get_units_at(coordinates)
        for u in units:
            if u.slot == slot:
                if player is None or u.player == player:
                    return u
        return None

    def get_units_at(self, coordinates):
        tile = self.map.get_tile(coordinates)
        return tile.units if tile else []

    # --- Unit management ---

    def add_unit_to_tile(self, unit, coordinates):
        tile = self.map.get_tile(coordinates)
        if tile:
            tile.add_unit(unit)
            unit.coordinates = coordinates

    def remove_unit_from_tile(self, unit, coordinates):
        tile = self.map.get_tile(coordinates)
        if tile:
            tile.remove_unit(unit)

    def move_unit(self, unit, new_coordinates):
        self.remove_unit_from_tile(unit, unit.coordinates)
        self.add_unit_to_tile(unit, new_coordinates)

    def delete_unit(self, unit):
        """Delete a unit from the game entirely."""
        self.remove_unit_from_tile(unit, unit.coordinates)
        unit.player.remove_unit(unit)

    # --- City management ---

    def can_found_city_at(self, coordinates):
        """Settleable (§3): land domain, not impassable, free of a city, spaced out."""
        tile = self.map.get_tile(coordinates)
        if not tile or tile.city:
            return False
        if tile.domain != "land" or tile.impassable:
            return False

        # Minimum distance from other cities
        for player in self.players:
            for city in player.cities:
                distance = self.map.distance_function(coordinates, city.coordinates)
                if distance < MIN_CITY_DISTANCE:
                    return False
        return True

    def found_city(self, player, coordinates, name="New City"):
        """Found a new city at the specified coordinates."""
        if not self.can_found_city_at(coordinates):
            return None

        city = City(player, coordinates, name)
        tile = self.map.get_tile(coordinates)
        tile.set_city(city)
        player.cities.append(city)
        city.assign_tiles(self)
        return city

    def add_city(self, city):
        """Add a city to the map (used by SettlerUnit.found_city)."""
        tile = self.map.get_tile(city.coordinates)
        if tile:
            tile.set_city(city)

    # --- Improvements ---

    def can_build_improvement_at(self, coordinates, improvement_type):
        tile = self.map.get_tile(coordinates)
        if not tile or tile.city or improvement_type in tile.improvements:
            return False

        entry = IMPROVEMENTS.get(improvement_type)
        if entry is None or "on" not in entry:
            return False
        return matches(entry["on"], tile.base_terrain, tile.relief, tile.feature)

    def build_improvement(self, coordinates, improvement_type):
        """Build an improvement on the specified tile."""
        if not self.can_build_improvement_at(coordinates, improvement_type):
            return False
        tile = self.map.get_tile(coordinates)
        tile.add_improvement(improvement_type)
        return True

    # --- Pathfinding wrappers ---

    def path_finder(self, start, destination, domain="land"):
        return self.map.path_finder(start, destination, domain=domain)

    def distance_function(self, p1, p2):
        return self.map.distance_function(p1, p2)

    # --- Debug ---

    def debug_units_locations(self):
        """Print the locations of all units for debugging."""
        print("\nDEBUG: Unit Locations")
        for player_idx, player in enumerate(self.players):
            print(f"Player {player_idx + 1} ({player.name}) units:")
            for unit_idx, unit in enumerate(player.units):
                print(
                    f"  Unit {unit_idx}: {unit.unit_type} at {unit.coordinates} "
                    f"with {unit.movement_points} MP"
                )
                tile_units = self.get_units_at(unit.coordinates)
                if unit not in tile_units:
                    print(f"    WARNING: Unit not found at its tile!")
                if len(tile_units) > 1:
                    print(f"    WARNING: {len(tile_units)} units stacked at {unit.coordinates}")
