"""GameEnvironment -- the main game simulation interface."""

import logging

import numpy as np

from .map import Map
from .. import hexmath, mapgen
from ..mapgen.starts import StartPlacementError
from ..rng import PortableRNG
from ..effects import (
    KIND_FREE_CIVIC,
    KIND_FREE_POPULATION,
    KIND_FREE_TECH,
    KIND_FREE_UNITS,
    loadout_is_legal,
    one_shot_effects,
    slot_counts,
)
from ..research_model import (
    CIVICS,
    GOVERNMENTS,
    TECHS,
    is_available,
    scaled_civic_cost,
    scaled_tech_cost,
)
from ..terrain_model import can_enter, improvement_on, matches
from .player import Player
from .city import City
from .availability import player_can_build
from .city import _create_unit
from .defaults import (
    default_civic, default_government, default_loadout, default_research, default_trade,
    default_workers,
)
from .districts import (
    YIELD_NAMES as DISTRICT_YIELD_NAMES, District, can_place_district, district_cost,
    is_wonder,
)
from ..district_model import (
    CONSOLATION_PERCENT as WONDER_CONSOLATION_PERCENT,
    REMOVABLE_FEATURES as DISTRICT_REMOVABLE_FEATURES,
)
from . import loyalty, territory
from .victory import game_over
from .territory import (
    FOUNDING_RING, NEUTRAL, border_cost_function, choose_claim_tile,
    run_border_phase,
)
from .maintenance import disband_candidate, maintenance_due, unit_maintenance_delta, unit_upkeep
from .purchasing import ITEM_UNIT, can_purchase, purchase_cost, spend
from .trade import (
    DURATION_TURNS as TRADE_DURATION_TURNS,
    TRADER_UNIT,
    TradeRoute,
    eligible_destinations,
    end_routes_touching,
    expire_routes,
    origin_city,
    route_capacity,
)
from .unit import WarriorUnit, WorkerUnit, calculate_damage, movement_domain
from .upgrades import can_upgrade, upgrade_cost, upgrade_target
from ..config import CFG
from ..unit_model import CAPITAL_BUILDING

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
        # PhiloxRNG (philox32 kit, civulator/rng.py; PortableRNG is its alias
        # for one release) so a C++/CUDA twin can reproduce the identical
        # stream (issues #33, #128).
        self.rng = PortableRNG(seed)

        # Border cost curve (borders design §3.1), read from
        # [territory.border_cost] at construction: cost(n) -> int tenths.
        self.border_cost = border_cost_function(CFG["territory"]["border_cost"])

        # Initialize map and players. Construction follows the same
        # unseeded-resample policy as reset (design doc D26, see reset's
        # docstring): a pinned seed is loyal — it either works or raises
        # unchanged — while an unseeded construction has no seed to be loyal
        # to, so an unplaceable world (~2% of master seeds) is resampled
        # with logged bounded retries instead of crashing the caller
        # (evaluate.py / run_baseline.py both construct unseeded throwaway
        # worlds that per-episode seeded resets immediately replace).
        self.map = Map(self.n, self.m, rng=self.rng)
        self._reset_city_registry()
        if seed is not None:
            self.map.generate_map(self.map_type, num_players=self.num_players, params=mapgen_params)
        else:
            last_error = None
            for attempt in range(1, MAX_WORLD_RETRIES + 1):
                try:
                    self.map.generate_map(
                        self.map_type, num_players=self.num_players, params=mapgen_params
                    )
                    last_error = None
                    break
                except StartPlacementError as exc:
                    last_error = exc
                    logger.warning(
                        "unseeded construction: world generation failed start "
                        "placement (master seed=%s, attempt %d/%d): %s",
                        self.map.last_master_seed, attempt, MAX_WORLD_RETRIES, exc,
                    )
            if last_error is not None:
                raise StartPlacementError(
                    f"unseeded construction: exhausted {MAX_WORLD_RETRIES} world "
                    f"retries (design doc D26, config [map] max_world_retries) "
                    f"— every attempt failed start placement; last failure: "
                    f"{last_error}"
                ) from last_error

        for i in range(self.num_players):
            player = Player(f"Player {i+1}", i, self)
            self.players.append(player)

        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]
        self.episode_stats = self._fresh_episode_stats()

    def _reset_city_registry(self):
        """Fresh per-environment city ids (borders design §2): called with
        every new Map, i.e. in the constructor and in every reset attempt,
        unseeded retries included. Never process-global, so two same-seed
        environments in one process produce identical ownership grids."""
        self.city_by_id = {}
        self._next_city_id = 0

    def _fresh_episode_stats(self):
        """Per-player episode counters (issue #48 statistics wish, Erik
        2026-09-02): pure bookkeeping, reset with every episode. The eval
        harness reads these after each game; nothing in the engine or the
        agents ever reads them back."""
        return {
            i: {
                "kills": 0,
                "losses": 0,
                "damage_dealt": 0.0,
                "cities_founded": 0,
                "cities_captured": 0,
                # Loyalty flips (#116 P7): cities this player lost / gained
                # at round end without a fight (GameEnvironment._flip_city).
                # A flip is never counted in cities_captured.
                "cities_flipped_out": 0,
                "cities_flipped_in": 0,
                "civilians_captured": 0,
                "tiles_claimed_by_culture": 0,
                "culture_produced": 0,  # int tenths of a culture point
                # The other three pool yields, int tenths, same guard (#116 P1)
                "science_produced": 0,
                "gold_produced": 0,
                "faith_produced": 0,
                "growth_slowed_turns": 0,  # city-turns, positive net, band < 100 % (#88)
                "techs_researched": 0,  # completed techs (#116 P2)
                "civics_researched": 0,  # completed civics (#116 P4)
                "units_upgraded": 0,  # units upgraded into their next type (#116 P3)
                # Gold (#116 P5): upkeep actually paid from the treasury (int
                # tenths), units disbanded by bankruptcy, the gold and faith
                # spent on purchases (int tenths), trade routes opened.
                "gold_maintenance": 0,
                "units_disbanded": 0,
                "gold_spent_purchases": 0,
                "faith_spent_purchases": 0,
                "trade_routes_established": 0,
                # Improvements a Worker built (#116 P8): counted by
                # WorkerUnit.build_improvement, the one player build path.
                "improvements_built": 0,
                # Wonders (#116 P6): wonders this player completed, and its
                # placed copies removed because another city completed one.
                "wonders_completed": 0,
                "wonder_races_lost": 0,
                # Summed adjacency score per yield, per city-round (#86 s5)
                **{f"district_yield_{y}": 0 for y in DISTRICT_YIELD_NAMES},
            }
            for i in range(self.num_players)
        }

    def episode_stats_snapshot(self, player_index):
        """Copy of one player's episode counters plus the live
        `tiles_owned` (a count read from the ownership grid, not an
        accumulating counter — so it is only meaningful when read, e.g. at
        episode end; a sum over games is the total of end-of-game holdings).
        """
        stats = dict(self.episode_stats[player_index])
        stats["tiles_owned"] = self.map.owned_tile_count(player_index)
        return stats

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
        self.episode_stats = self._fresh_episode_stats()
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
        self._reset_city_registry()
        self.map.generate_map(self.map_type, num_players=self.num_players)

        # Reset or recreate players
        if recreate_players:
            self.players = []
            for i in range(self.num_players):
                player = Player(f"Player {i+1}", i, self)
                self.players.append(player)
        else:
            for player in self.players:
                player.reset_state()

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
                    self.episode_stats[self.current_player.player_index]["cities_founded"] += 1
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

        # An order aimed at an enemy city is an attack on the city (issue
        # #84). A city with a garrison still resolves against the garrison —
        # the branch above already returned in that case. At 0 health the
        # city is no longer a target but an objective: the order falls
        # through to movement, and moving in captures it.
        enemy_city = self._get_enemy_city_at(order_pos)
        if enemy_city is not None and enemy_city.health > 0:
            reward = self._execute_attack(selected_unit, enemy_city)
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
            reward += self._capture_city(selected_unit, tile.city)

        # Movement changes what the player can see
        self.update_exploration(self.current_player.player_index)

        self._check_game_end()
        return self, reward, self.done

    def _get_enemy_city_at(self, coordinates):
        """The enemy city standing on `coordinates`, or None (issue #84)."""
        tile = self.map.get_tile(coordinates)
        if tile is None or tile.city is None:
            return None
        return tile.city if tile.city.player != self.current_player else None

    def _capture_city(self, unit, city):
        """Take `city` for `unit`'s player if the rules allow. Returns reward.

        The single capture gate (issue #84). Capture requires the city to be
        at 0 health and the occupying unit to be able to hold it
        (`Unit.can_capture_city`) — a ranged unit reduces a city but never
        owns it. `Unit.move` already refuses to enter a tile that fails
        either test, so this is the second lock on the same door rather than
        the only one; both exist because the melee move-in inside
        `_execute_attack` bypasses `Unit.move` entirely.
        """
        if city.health > 0 or not unit.can_capture_city():
            return 0
        city.set_owner(unit.player)
        self.episode_stats[unit.player.player_index]["cities_captured"] += 1
        return REWARDS["capture_city"]

    def _get_enemy_unit_at(self, coordinates):
        """Get an enemy unit at the given position, or None."""
        units = self.get_units_at(coordinates)
        for unit in units:
            if unit.player != self.current_player:
                return unit
        return None

    def _execute_attack(self, attacker, defender):
        """Execute combat between attacker and defender. Returns reward.

        `defender` is a Unit or a City (issue #84) — the one path all damage
        flows through, cities included. Ranged units (Slinger, Archer,
        Catapult) attack at range; their own attack() validates distance and
        line of sight. Melee units must be adjacent.

        A city is never killed here: `Unit.attack` floors its health at 0 and
        returns target_killed False, so the kill/capture-civilian/move-in
        block below is unit-only by construction. Reducing a city to 0 does
        not take it — a melee land unit must then move in (see
        `_capture_city`).
        """
        reward = 0
        is_ranged = attacker.get_base_ranged_strength() > 0

        # Melee units must be adjacent; ranged units handle range in their attack()
        adj_coords = self.map.get_adjacent_coords(attacker.coordinates)
        if not is_ranged and defender.coordinates not in adj_coords:
            return REWARDS["invalid_action"]

        # Episode-stat attribution: grab both indices BEFORE any mutation
        # (civilian capture reassigns defender.player below).
        atk_idx = attacker.player.player_index
        def_idx = defender.player.player_index

        damage_dealt, damage_received, target_killed, attacker_killed = \
            attacker.attack(defender, self)

        # attack() returns (0,0,False,False) if out of range — treat as invalid
        if damage_dealt == 0 and not target_killed:
            return REWARDS["invalid_action"]

        # Attacking always consumes all movement points
        attacker.movement_points = 0

        # Reward for damage dealt
        reward += damage_dealt * REWARDS["damage_per_hp"]
        self.episode_stats[atk_idx]["damage_dealt"] += damage_dealt
        self.episode_stats[def_idx]["damage_dealt"] += damage_received

        if target_killed:
            reward += REWARDS["kill"]
            self.episode_stats[atk_idx]["kills"] += 1
            self.episode_stats[def_idx]["losses"] += 1
            # Capture civilian units instead of killing them: the class
            # `civilian` (Settler, Worker, Trader), never a list of names (#116 P3)
            if defender.is_civilian() and not attacker_killed:
                defender.player.remove_unit(defender)
                defender.player = self.current_player
                self.current_player.units.append(defender)
                reward += REWARDS["capture_civilian"]
                self.episode_stats[atk_idx]["civilians_captured"] += 1
            else:
                self.delete_unit(defender)
            # Only melee attackers move into the vacated tile — and not into
            # a city that is still standing (issue #84). Killing the garrison
            # of a healthy city leaves the attacker where it is; the city
            # itself must be beaten down first.
            if (
                not is_ranged
                and not attacker_killed
                and not attacker.enemy_city_blocks(defender.coordinates, self)
            ):
                self.move_unit(attacker, defender.coordinates)
                # Check city capture
                tile = self.map.get_tile(attacker.coordinates)
                if tile and tile.city and tile.city.player != self.current_player:
                    reward += self._capture_city(attacker, tile.city)

        if attacker_killed:
            reward += REWARDS["unit_lost"]
            self.episode_stats[atk_idx]["losses"] += 1
            self.episode_stats[def_idx]["kills"] += 1
            self.delete_unit(attacker)

        return reward

    # --- Zone of control and siege (issue #84) ---

    def tile_under_zone_of_control(self, coordinates, player):
        """Whether `player` exerts zone of control over `coordinates`.

        A tile is under a player's ZoC when it is adjacent to one of that
        player's ZoC-projecting units (`Unit.projects_zone_of_control`) and
        no river runs along the shared edge -- ZoC does not cross a river,
        the same edge test `Unit.step_cost` uses for the crossing surcharge.

        Adjacency comes from `Map.get_adjacent_coords`, i.e. the canonical
        hex kernels, wrap included; no neighbour arithmetic is written here.

        This is the ONLY thing ZoC does in this engine. It has no movement
        effect (in Civ, entering an enemy ZoC ends movement) -- that rule is
        deliberately out of scope and is named as missing in the CHANGELOG.
        """
        for adj in self.map.get_adjacent_coords(coordinates):
            for unit in self.get_units_at(adj):
                if unit.player is not player:
                    continue
                if not unit.projects_zone_of_control():
                    continue
                if self.is_river_between(adj, coordinates):
                    continue
                return True
        return False

    def is_city_under_siege(self, city):
        """Whether `city` is besieged, and so does not repair (issue #84).

        Civ 6: the city centre is under siege when all 6 tiles around it are
        occupied by enemy units, under enemy zone of control, or impassable.
        "Impassable" here means no land unit could stand there -- mountains
        and, since there are no naval units, water. That makes a coastal city
        besiegeable from land alone, which diverges from Civ 6 (where a
        blockade needs ships) and is named in the CHANGELOG.

        One guard the wording alone does not give: at least one ring tile
        must actually be held or controlled by an enemy. Without it a city
        ringed by mountains would be permanently besieged by nobody and would
        never heal.
        """
        ring = self.map.get_adjacent_coords(city.coordinates)
        if not ring:
            return False

        enemies = [p for p in self.players if p is not city.player]
        contested = False
        for pos in ring:
            if not can_enter("land", self.map.get_tile(pos)):
                continue  # nobody has to hold a tile nobody can stand on
            if any(u.player is not city.player for u in self.get_units_at(pos)):
                contested = True
                continue
            if any(self.tile_under_zone_of_control(pos, p) for p in enemies):
                contested = True
                continue
            return False
        return contested

    # --- City ranged attack (issue #84) ---

    def city_ranged_attack(self, city):
        """Fire `city`'s ranged strike at the best target in reach.

        Returns the unit that was shot, or None.

        Automatic, once at the start of its owner's turn (`Player.start_turn`)
        rather than an order the agent gives. Civ 6 makes it a player order,
        but the action space here selects a UNIT and names a tile; giving a
        city an order would change that action space, which is exactly the
        kind of change #82/#84 keep separate. Automatic firing is the only
        way this rule is reachable at all -- an unreachable rule is what
        issue #84 is about (CHANGELOG names the divergence).

        Damage goes through the canonical `calculate_damage` and takes no
        counterattack, like any ranged attack. Range and line of sight use
        the canonical hex distance and `Map.check_line_of_sight`.
        """
        if not city.can_make_ranged_attack():
            return None

        target = self._bombard_target(city)
        if target is None:
            return None

        owner_idx = city.player.player_index
        damage = calculate_damage(
            city.get_ranged_strength(),
            target.get_combat_strength(False, city),
            rng=getattr(self, "rng", None),
        )
        target.health -= damage
        self.episode_stats[owner_idx]["damage_dealt"] += damage

        if target.health <= 0:
            self.episode_stats[owner_idx]["kills"] += 1
            self.episode_stats[target.player.player_index]["losses"] += 1
            self.delete_unit(target)

        return target

    def _bombard_target(self, city):
        """The enemy unit a city shoots at: the weakest one in range and in
        sight, ties broken by coordinates so the choice is reproducible."""
        best = None
        best_key = None
        for player in self.players:
            if player is city.player:
                continue
            for unit in player.units:
                if self.map.distance_function(city.coordinates, unit.coordinates) > city.get_range():
                    continue
                if not self.check_line_of_sight(city.coordinates, unit.coordinates):
                    continue
                key = (unit.health, unit.coordinates[0], unit.coordinates[1], unit.slot)
                if best_key is None or key < best_key:
                    best, best_key = unit, key
        return best

    def _check_game_end(self):
        """Check if the game should end (all units spent, a win, turn limit)."""
        # Auto-advance if all units spent
        if self.current_player.units:
            all_units_moved = all(u.movement_points == 0 for u in self.current_player.units)
            if all_units_moved:
                self.next_turn()
        else:
            # Player has no units left, end their turn
            self.next_turn()

        self._update_done()

    def _update_done(self):
        """The engine's one end-of-game test (#116 P7, P9): `victory.game_over`
        -- at most one living player (a player dies in `Player.end_turn` once
        it holds no city -- after a capture or a loyalty flip alike), a living
        player holding every Palace in the game (domination), or the turn cap
        passed. Called from `_check_game_end` (every step that can capture a
        city) and from `next_turn` (after the loyalty phase, so a flip can
        end the game in its own round); `victory.determine_outcome` is the
        verdict on the same rules. Sets `done`; never clears it."""
        if game_over(self):
            self.done = True

    def next_turn(self):
        """Advance to the next player's turn.

        On the wrap to player 0 the round ends (progression design "v2
        fixes", Turn order; CLAUDE.md, Round-end phases): `_border_phase`,
        then `_loyalty_phase`, then the end-of-game test, then `turn_counter
        += 1` -- every round-end rule computed from the state at the start of
        its phase, in city-id order, so turn order cannot decide it."""
        self.current_player.end_turn()

        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.current_player = self.players[self.current_player_index]

        if self.current_player_index == 0:
            self._border_phase()
            self._loyalty_phase()
            self._update_done()  # the round-end verdict: a flip can end the game
            self.turn_counter += 1

        self.current_player.start_turn()

        self._update_done()

    def _border_phase(self):
        """The round-end border phase (borders design §3.3): every existing
        city, whoever owns it, resolves this round's culture claims in
        crossing-time order. Runs only from `next_turn`, on the wrap to
        player 0 and before `turn_counter += 1`, so turn order cannot decide
        a contest. Each claim re-runs `assign_tiles` for the claiming city
        (culture claims take only neutral tiles, so no city loses one)."""
        cities = [self.city_by_id[city_id] for city_id in sorted(self.city_by_id)]
        claims = run_border_phase(
            self.map, cities, self.border_cost, self.rng,
            on_claim=lambda city, pos: city.assign_tiles(self),
        )
        for city_id, _ in claims:
            player_index = self.city_by_id[city_id].player.player_index
            self.episode_stats[player_index]["tiles_claimed_by_culture"] += 1

    def _loyalty_phase(self):
        """The round-end loyalty phase (#116 P7, progression design §8.3 and
        "v2 fixes"), run only from `next_turn`, after `_border_phase` and
        before the end-of-game test and `turn_counter += 1` -- the border
        phase's discipline (borders design §3.3): every existing city takes
        part, whoever owns it, and everything is computed from the state at
        the start of the phase, so neither turn order nor a city founded late
        in the round decides anything. Integers only; no RNG.

        1. Every city's `loyalty.loyalty_delta`, in `city_by_id` order, before
           any city changes.
        2. Each city's loyalty becomes `loyalty.clamp(loyalty + delta)`.
        3. For every city now at `loyalty.LOYALTY_MIN`, its
           `loyalty.largest_foreign_presser` -- still the phase-start state,
           since pressure reads population, distance and owners, never
           loyalty.
        4. Those with a presser flip, in city-id order, through `_flip_city`;
           a city nobody else presses stays at the floor with its owner.
        """
        cities = [self.city_by_id[city_id] for city_id in sorted(self.city_by_id)]
        deltas = [loyalty.loyalty_delta(city, self) for city in cities]
        for city, delta in zip(cities, deltas):
            city.loyalty = loyalty.clamp(city.loyalty + delta)
        flips = [(city, loyalty.largest_foreign_presser(city, self))
                 for city in cities if city.loyalty == loyalty.LOYALTY_MIN]
        for city, new_player in flips:
            if new_player is not None:
                self._flip_city(city, new_player)

    def _flip_city(self, city, new_player):
        """`city` revolts and joins `new_player` (#116 P7, design §8.5): the
        loyalty door to `City.set_owner`, beside `_capture_city`'s door of
        force. The old owner's units on the centre tile are deleted (through
        `delete_unit`, each counted in its `losses`), then `set_owner` moves
        the city with its tiles, districts and wonders, resets its loyalty to
        `[loyalty] captured`, ends every trade route touching it and drops
        the old owner's queued units for it. `episode_stats` counts
        `cities_flipped_out` for the old owner and `cities_flipped_in` for
        the new one (never `cities_captured`).

        No reward: the flip happens at round end, where no step returns one
        (whether the training objective should see flips is Erik's call).
        A player left without a city is eliminated by today's path, as after
        a capture: it plays one more turn and dies in `Player.end_turn`."""
        old_player = city.player
        garrison = [unit for unit in self.get_units_at(city.coordinates)
                    if unit.player is old_player]
        for unit in garrison:
            self.delete_unit(unit)
            self.episode_stats[old_player.player_index]["losses"] += 1
        city.set_owner(new_player)
        self.episode_stats[old_player.player_index]["cities_flipped_out"] += 1
        self.episode_stats[new_player.player_index]["cities_flipped_in"] += 1

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

    def can_found_city_at(self, coordinates, player):
        """Settleable (§3) for `player`: land domain, not impassable, free of
        a city, spaced out, and not owned by another player (borders design
        §2.2). Founding on a tile `player` already owns is allowed; the tile
        moves to the new city. A district tile is never settleable (#86)."""
        tile = self.map.get_tile(coordinates)
        if not tile or tile.city or tile.district is not None:
            return False
        if tile.domain != "land" or tile.impassable:
            return False

        owner_id = self.map.owner_id_at(tile.coordinates)
        if owner_id != NEUTRAL and self.city_by_id[owner_id].player is not player:
            return False

        # Minimum distance from other cities
        for other in self.players:
            for city in other.cities:
                distance = self.map.distance_function(coordinates, city.coordinates)
                if distance < MIN_CITY_DISTANCE:
                    return False
        return True

    def found_city(self, player, coordinates, name="New City"):
        """Found a new city at the specified coordinates, if the rules allow."""
        if not self.can_found_city_at(coordinates, player):
            return None
        return self.create_city(player, coordinates, name)

    def create_city(self, player, coordinates, name="New City"):
        """The ONLY way a city comes into existence (borders design §2.1).

        Assigns the per-environment id, sets the centre, makes the founding
        claim, and runs `assign_tiles` for every city whose tiles changed. No
        placement-rule check: `found_city` and `SettlerUnit.found_city` check
        `can_found_city_at` first; the painted-scenario fallback
        (`recording._place_city`) deliberately does not.
        """
        tile = self.map.get_tile(coordinates)
        if tile is None:
            raise ValueError(f"create_city: {coordinates} is off the map")
        if tile.city is not None:
            raise ValueError(f"create_city: a city already stands on {tile.coordinates}")
        if tile.district is not None:
            raise ValueError(f"create_city: a district stands on {tile.coordinates}")

        city = City(player, tile.coordinates, name)
        city.city_id = self._next_city_id
        self._next_city_id += 1
        self.city_by_id[city.city_id] = city
        tile.set_city(city)
        player.cities.append(city)
        if not player.palace_granted:
            city.buildings.append(CAPITAL_BUILDING)  # the Palace (#88, [city] capital_building)
            player.palace_granted = True

        changed = {city.city_id} | self._founding_claim(city)
        for city_id in sorted(changed):
            self.city_by_id[city_id].assign_tiles(self)
        return city

    def _founding_claim(self, city):
        """Borders design §2.1. The centre (taken from whichever city owned
        it), every neutral tile of rings 1..`[territory] founding_ring`, and
        one §3.2 replacement per ring tile owned by another player, claimed
        one at a time (shortfall accepted). Ring tiles owned by another of
        the same player's cities stay with that city. Returns the ids of the
        OTHER cities that lost a tile.

        Draws RNG only through `choose_claim_tile`, i.e. only for
        replacements with a tie; at reset capitals are min_city_distance
        apart, so nothing is blocked and no RNG is drawn.
        """
        game_map = self.map
        changed = set()
        centre = city.coordinates
        previous = game_map.owner_id_at(centre)
        if previous == NEUTRAL:
            game_map.claim(centre, city)
        else:
            game_map.transfer(centre, self.city_by_id[previous], city)
            changed.add(previous)

        blocked = 0
        for ring in game_map.get_ring_coords(centre, FOUNDING_RING)[1:]:
            for pos in ring:
                owner_id = game_map.owner_id_at(pos)
                if owner_id == NEUTRAL:
                    game_map.claim(pos, city)
                elif self.city_by_id[owner_id].player is not city.player:
                    blocked += 1

        for _ in range(blocked):
            pos = choose_claim_tile(game_map, city, self.rng)
            if pos is None:
                break
            game_map.claim(pos, city)
        return changed

    def remove_city(self, city):
        """The ONLY way a city ceases to exist without being captured
        (borders design §2.3): its tiles become neutral and its districts
        are deleted with it (issue #86), each through `_remove_district`.
        Every trade route touching it ends (#116 P5,
        `trade.end_routes_touching`): a route from another city returns its
        Trader there, one from this city is lost."""
        for district in list(city.districts):
            self._remove_district(city, district)
        for pos in self.map.tiles_of_city(city.city_id):
            self.map.release(pos, city)
        tile = self.map.get_tile(city.coordinates)
        if tile is not None and tile.city is city:
            tile.set_city(None)
        if city in city.player.cities:
            city.player.cities.remove(city)
        self.city_by_id.pop(city.city_id, None)
        city.worked_tiles = []
        end_routes_touching(self, city.city_id)

    def swap_tile(self, coordinates, to_city):
        """Move an owned tile between two cities of the same player (borders
        design §5). Valid only if the tile is owned by another city of
        `to_city`'s player, lies within `to_city`'s `[territory]
        work_radius`, and is neither its current owner's centre nor adjacent
        to it, and holds no district (issue #86: a district tile always
        belongs to its district's city). Free and instant; both cities re-run
        `assign_tiles`. Returns True if the swap happened.
        """
        tile = self.map.get_tile(coordinates)
        if tile is None or self.city_by_id.get(to_city.city_id) is not to_city:
            return False
        if tile.district is not None:
            return False
        coords = tile.coordinates
        owner_id = self.map.owner_id_at(coords)
        if owner_id == NEUTRAL or owner_id == to_city.city_id:
            return False
        from_city = self.city_by_id[owner_id]
        if from_city.player is not to_city.player:
            return False
        if self.map.distance_function(coords, to_city.coordinates) > territory.WORK_RADIUS:
            return False
        if coords == from_city.coordinates or coords in self.map.get_adjacent_coords(from_city.coordinates):
            return False
        self.map.transfer(coords, from_city, to_city)
        from_city.assign_tiles(self)
        to_city.assign_tiles(self)
        return True

    # --- Districts (issue #86, docs/districts_design.md §3) ---

    def place_district(self, city, district_type, coordinates):
        """Place a district (Civ 6's first step). The only writer of
        `Tile.district` / `City.districts` besides `remove_city`.

        Checks `can_place_district`, then creates the District with its cost
        locked, links it from the tile and the city, clears the tile's
        improvements and (in one `set_layers` call, only when there is
        something to clear) a removable feature and its bonus resource, bumps
        `Map.district_epoch`, re-runs `assign_tiles` and points the city's
        production at it. Returns True if placed.
        """
        if self.city_by_id.get(city.city_id) is not city:
            return False
        if not can_place_district(city, district_type, coordinates):
            return False
        tile = self.map.get_tile(coordinates)
        district = District(
            type=district_type,
            city_id=city.city_id,
            coordinates=tile.coordinates,
            complete=False,
            cost=district_cost(city.player, district_type),
        )
        tile.district = district
        city.districts.append(district)

        tile.clear_improvements(map_ref=self.map)
        feature = None if tile.feature in DISTRICT_REMOVABLE_FEATURES else tile.feature
        if feature != tile.feature or tile.resource is not None:
            tile.set_layers(tile.base_terrain, relief=tile.relief, feature=feature,
                            resource=None, map_ref=self.map)
        self.map.district_epoch += 1
        city.assign_tiles(self)
        city.current_production = {"type": "district", "district_type": district_type}
        return True

    def _remove_district(self, city, district):
        """Delete one placed district of `city` (#116 P6): the tile's link is
        freed, the district leaves `city.districts`, `Map.district_epoch`
        bumps and the city re-runs `assign_tiles` (the tile is workable
        again). With `place_district` the only writer of `Tile.district` /
        `City.districts`; called for a lost wonder race and by `remove_city`.
        Touches nothing else: the caller settles production and refunds."""
        tile = self.map.get_tile(district.coordinates)
        if tile is not None and tile.district is district:
            tile.district = None
        city.districts = [d for d in city.districts if d is not district]
        self.map.district_epoch += 1
        city.assign_tiles(self)

    def complete_district(self, city, district):
        """The one place a district finishes (progression design §9.3,
        Systems): marks `district` complete and clears the city's production.
        Called by `City.process_turn` once the locked cost is paid; the
        payment stays there.

        When the district is a wonder (#116 P6, design §9.1-§9.3, "v2 fixes"
        Wonders), it then settles the race (`_settle_wonder_race`: every other
        placed copy is removed, its city refunded `[wonders]
        consolation_percent` of that copy's locked cost) and counts
        `episode_stats["wonders_completed"]`. Every completion then fires the
        district's one-shot effects (`_one_shot_effects`; only wonder tables
        may carry them) -- exactly once, because this is the only completion
        path and a second call raises; never on capture (`set_owner` moves a
        complete district as it is) or on load. When a free civic was
        granted or the owner's policy slots changed (a `policy_slots`
        wonder), the government and loadout defaults re-run for the owner.

        Raises ValueError for a district that is not the city's or is
        already complete, so nothing can complete twice.
        """
        if not any(d is district for d in city.districts):
            raise ValueError(f"complete_district: {district.type} is not a district of {city.name}")
        if district.complete:
            raise ValueError(f"complete_district: {district.type} at {district.coordinates} is already complete")
        player = city.player
        slots_before = slot_counts(player)
        district.complete = True
        city.current_production = None
        if is_wonder(district.type):
            self._settle_wonder_race(city, district)
            self.episode_stats[player.player_index]["wonders_completed"] += 1
        civic_granted = self._one_shot_effects(city, district)
        if civic_granted or slot_counts(player) != slots_before:
            self._government_and_loadout_defaults(player, refit=True)

    def _settle_wonder_race(self, city, wonder):
        """`wonder` just completed in `city`: remove every other placed copy
        of its type, in every city in `city_by_id` order (the race is decided
        inside the completing player's turn, so turn order decides a
        same-round tie -- accepted, design "v2 fixes"). Each removed copy
        refunds `[wonders] consolation_percent` of its locked cost (integer
        floor) into its city's `production` pool, its city's
        `current_production` is cleared if it pointed at that wonder, and its
        owner's `episode_stats["wonder_races_lost"]` counts it. Removal goes
        through `_remove_district`."""
        for city_id in sorted(self.city_by_id):
            other = self.city_by_id[city_id]
            copies = [d for d in other.districts if d.type == wonder.type and d is not wonder]
            for copy in copies:
                if other.current_production == {"type": "district", "district_type": copy.type}:
                    other.current_production = None
                self._remove_district(other, copy)
                other.production += copy.cost * WONDER_CONSOLATION_PERCENT // 100
                self.episode_stats[other.player.player_index]["wonder_races_lost"] += 1

    def _one_shot_effects(self, city, district):
        """Fire the one-shot effects of `district` (design §3, §9.3; their one
        consumer), in config order, for its city's owner -- called only by
        `complete_district`:

        - `free_units`: each unit through `City.place_or_queue_unit` (queued
          in `Player.queued_units` when the city has no room);
        - `free_tech` / `free_civic`: `count` times, the current tech / civic
          (or the engine default's pick) completes at once, at no cost,
          outside the one-per-turn rule (`_grant_tech` / `_grant_civic`,
          which share their completion step with `resolve_research` /
          `resolve_civic`); nothing when the tree is exhausted;
        - `free_population`: `amount` added to the city -- to every city of
          the owner with `all_cities` -- each re-running `assign_tiles`.

        Returns True if a civic was granted (the caller re-runs the loadout
        default)."""
        player = city.player
        civic_granted = False
        for effect in one_shot_effects(district.type):
            if effect.kind == KIND_FREE_UNITS:
                for unit_type, count in effect["units"]:
                    for _ in range(count):
                        city.place_or_queue_unit(unit_type, self)
            elif effect.kind == KIND_FREE_TECH:
                for _ in range(effect["count"]):
                    self._grant_tech(player)
            elif effect.kind == KIND_FREE_CIVIC:
                for _ in range(effect["count"]):
                    civic_granted = self._grant_civic(player) is not None or civic_granted
            elif effect.kind == KIND_FREE_POPULATION:
                for grown in (list(player.cities) if effect["all_cities"] else [city]):
                    grown.population += effect["amount"]
                    grown.assign_tiles(self)
        return civic_granted

    # --- Improvements ---

    def can_build_improvement_at(self, coordinates, improvement_type):
        """The TILE predicate: `improvement_type` may stand on this tile (no
        city, no district, not already there, its `on` constraint met --
        the same `on` formalism as terrain layers, design doc §3.1, §9.6,
        read through `terrain_model.improvement_on`). Knows nothing of
        players; `can_player_build_improvement_at` adds them."""
        tile = self.map.get_tile(coordinates)
        if not tile or tile.city or improvement_type in tile.improvements:
            return False
        if tile.district is not None:  # issue #86
            return False

        on = improvement_on(improvement_type)
        if on is None:
            return False
        return matches(on, tile.base_terrain, tile.relief, tile.feature)

    def player_owns_tile(self, player, coordinates):
        """Whether `coordinates` lies in the territory of one of `player`'s
        cities (`Map.owner_city`): the one ownership test of the build and
        upgrade rules (`can_player_build_improvement_at`, `upgrade_unit`)."""
        owner_id = self.map.owner_id_at(coordinates)
        return owner_id != NEUTRAL and self.city_by_id[owner_id].player is player

    def can_player_build_improvement_at(self, player, coordinates, improvement_type):
        """Whether `player` may build `improvement_type` on this tile now
        (#116 P2, progression design "v2 fixes"): the tile is owned by one of
        the player's cities (`Map.owner_city`), the player `player_can_build`
        it (its `requires_tech`), and the tile predicate holds."""
        tile = self.map.get_tile(coordinates)
        if tile is None or not self.player_owns_tile(player, tile.coordinates):
            return False
        if not player_can_build(player, "improvement", improvement_type):
            return False
        return self.can_build_improvement_at(tile.coordinates, improvement_type)

    def build_improvement(self, coordinates, improvement_type):
        """Build an improvement on the specified tile (the tile predicate
        only; a player's build goes through `can_player_build_improvement_at`
        first, as `WorkerUnit.build_improvement` does). Bumps the terrain
        epoch: the tile's yields changed (#116 P2).

        One improvement per tile (#126, Erik 2026-10-22): a build REPLACES
        whatever stands on the tile, so a Farm laid on iron before Mining can
        become a Mine later. Any replacement is allowed; the tile predicate
        refuses only the improvement already there."""
        if not self.can_build_improvement_at(coordinates, improvement_type):
            return False
        tile = self.map.get_tile(coordinates)
        tile.clear_improvements(map_ref=self.map)
        tile.add_improvement(improvement_type, map_ref=self.map)
        return True

    # --- Research (#116 P2, docs/progression_design.md §4.3) ---

    def set_research(self, player, tech):
        """Choose `tech` as `player`'s current research. Refused (False,
        nothing changed) unless it is a tech the player does not know and
        every prerequisite is known. Switching loses nothing: the pool is one
        number, not per-tech progress (design §4.3)."""
        if not is_available(TECHS, tech, player.techs):
            return False
        player.current_tech = tech
        return True

    def resolve_research(self, player):
        """Research for one turn of `player`'s: with no current tech, the
        engine default picks one (`defaults.default_research`); then, if the
        science pool (tenths) holds 10 * the scaled cost, pay it, append the
        tech to `player.techs`, clear `current_tech` and count it in
        `episode_stats["techs_researched"]`. At most one tech per call, so
        one per turn (Civ 6); the overflow stays in the pool. Returns the
        tech completed, or None."""
        tech = self._research_target(player)
        if tech is None:
            return None  # every tech is known
        cost = 10 * scaled_tech_cost(tech)
        if player.science < cost:
            return None
        player.science -= cost
        self._complete_tech(player, tech)
        return tech

    def _research_target(self, player):
        """`player.current_tech`, set first to the engine default's pick
        (`defaults.default_research`) when none is chosen; None once every
        tech is known."""
        if player.current_tech is None:
            player.current_tech = default_research(player)
        return player.current_tech

    def _complete_tech(self, player, tech):
        """The one completion step of a tech: append it to `player.techs`,
        clear `current_tech`, count it in `episode_stats["techs_researched"]`.
        `resolve_research` pays first; a free tech does not."""
        player.techs.append(tech)
        player.current_tech = None
        self.episode_stats[player.player_index]["techs_researched"] += 1

    def _grant_tech(self, player):
        """A free tech (#116 P6, the `free_tech` one-shot): the current tech,
        or the default's pick, completes now at no cost -- the science pool
        is untouched and the turn's own research still resolves in the
        economy phase. Returns the tech, or None when every tech is known."""
        tech = self._research_target(player)
        if tech is not None:
            self._complete_tech(player, tech)
        return tech

    # --- Civics, governments, policies (#116 P4, docs/progression_design.md §5) ---

    def set_civic(self, player, civic):
        """Choose `civic` as `player`'s current civic. Refused (False, nothing
        changed) unless it is a civic the player does not know and every
        prerequisite is known. Switching loses nothing: the culture pool is
        one number (design §5.1, mirroring `set_research`)."""
        if not is_available(CIVICS, civic, player.civics):
            return False
        player.current_civic = civic
        return True

    def resolve_civic(self, player):
        """Civics for one turn of `player`'s, the research rule on the culture
        pool: with no current civic, the engine default picks one
        (`defaults.default_civic`); then, if `player.culture` (tenths) holds
        10 * the scaled cost, pay it, append the civic to `player.civics`,
        clear `current_civic` and count it in
        `episode_stats["civics_researched"]`. At most one civic per call, so
        one per turn; the overflow stays in the pool. Returns the civic
        completed, or None."""
        civic = self._civic_target(player)
        if civic is None:
            return None  # every civic is known
        cost = 10 * scaled_civic_cost(civic)
        if player.culture < cost:
            return None
        player.culture -= cost
        self._complete_civic(player, civic)
        return civic

    def _civic_target(self, player):
        """`player.current_civic`, set first to the engine default's pick
        (`defaults.default_civic`) when none is chosen; None once every civic
        is known."""
        if player.current_civic is None:
            player.current_civic = default_civic(player)
        return player.current_civic

    def _complete_civic(self, player, civic):
        """The one completion step of a civic: append it to `player.civics`,
        clear `current_civic`, count it in
        `episode_stats["civics_researched"]`. `resolve_civic` pays first; a
        free civic does not."""
        player.civics.append(civic)
        player.current_civic = None
        self.episode_stats[player.player_index]["civics_researched"] += 1

    def _grant_civic(self, player):
        """A free civic (#116 P6, the `free_civic` one-shot): the current
        civic, or the default's pick, completes now at no cost -- the culture
        pool is untouched and the turn's own civic still resolves in the
        economy phase. Returns the civic, or None when every civic is known."""
        civic = self._civic_target(player)
        if civic is not None:
            self._complete_civic(player, civic)
        return civic

    def set_government(self, player, name):
        """Adopt government `name` for `player`. Refused (False, nothing
        changed) unless it is a configured government whose civic the player
        knows. No anarchy and no switching cost (design §5.2). When the
        adoption changes the player's policy slots, the loadout is re-fitted
        at once by the engine default (`defaults.default_loadout`), so a
        loadout is legal after every government change."""
        spec = GOVERNMENTS.get(name) if isinstance(name, str) else None
        if spec is None or spec.requires_civic not in player.civics:
            return False
        before = slot_counts(player)
        player.government = name
        if slot_counts(player) != before:
            player.policies = default_loadout(player)
        return True

    def set_policies(self, player, names):
        """Slot exactly the policy cards `names`, in that order. Refused
        (False, nothing changed) unless the loadout is legal now
        (`effects.loadout_is_legal`): every card exists, is unlocked and not
        obsolete, none appears twice, and together they fit the slots --
        each card in a slot of its type or a wildcard slot (design §5.3)."""
        names = list(names)
        if not loadout_is_legal(player, names):
            return False
        player.policies = names
        return True

    def _government_and_loadout_defaults(self, player, refit):
        """The engine defaults of design §13 (no agent chooses yet, #99): adopt
        `defaults.default_government` when it names one (set_government
        re-fits the loadout if the slots change), and re-run
        `defaults.default_loadout` when `refit`: a civic completed this turn
        -- the one event that unlocks a card or makes one obsolete -- or
        (from `complete_district`, #116 P6) a wonder granted a civic or
        changed the policy slots."""
        choice = default_government(player)
        if choice is not None:
            self.set_government(player, choice)
        if refit:
            player.policies = default_loadout(player)

    # --- Gold: maintenance and bankruptcy (#116 P5, docs/progression_design.md §7.1-§7.2) ---

    def _pay_maintenance(self, player):
        """Deduct this turn's upkeep from the treasury (int tenths):
        `maintenance.maintenance_due` -- every unit's (its column plus the
        summed `unit_maintenance_delta`, floored at 0 per unit), every
        building's and every complete district's. Returns what was due."""
        due = maintenance_due(player)
        player.gold -= due
        return due

    def _resolve_bankruptcy(self, player):
        """While the treasury is negative and a unit with positive upkeep
        remains, disband `maintenance.disband_candidate` (the highest upkeep,
        the lowest `player.units` index among equals) through `delete_unit`;
        a disbanded unit does not pay this turn's upkeep, so its upkeep goes
        back into the treasury, and nothing else is refunded. Then the
        treasury is floored at 0. Each disbanded unit counts in
        `episode_stats["units_disbanded"]`. Returns the units disbanded."""
        delta = unit_maintenance_delta(player)
        disbanded = []
        while player.gold < 0:
            unit = disband_candidate(player, delta)
            if unit is None:
                break
            upkeep = unit_upkeep(unit, delta)
            self.delete_unit(unit)
            player.gold += upkeep
            disbanded.append(unit)
            self.episode_stats[player.player_index]["units_disbanded"] += 1
        if player.gold < 0:
            player.gold = 0
        return disbanded

    # --- Purchasing (#116 P5, docs/progression_design.md §7.3) ---

    def purchase(self, city, kind, name, resource):
        """The current player buys the `kind` ("unit" | "building") item
        `name` with `resource` ("gold" | "faith") in `city`, one of its own.
        Refused (False, nothing changed) unless `purchasing.can_purchase`
        holds: the item is purchasable with that resource (its `purchasable`
        column, or faith for a unit whose faith category a `faith_purchase`
        effect in force unlocks), the city could start it (`City.
        can_produce_unit` / `city_can_build_building`, a building not
        already owned) and the pool covers 10 x `purchase_cost` (tenths).

        On success the price leaves the pool; a unit is placed by
        `complete_unit_production`, or queued in `Player.queued_units` when
        the city has no room (`City.place_or_queue_unit`); a building is
        appended to `city.buildings` exactly as a produced one, and if the
        city was producing that building its production item is cleared (the
        production pool is kept, as on any switch). The only instant-
        completion path. No engine default and no agent action calls this
        yet (#99): an ACCEPTED GAP."""
        player = self.current_player
        if self.city_by_id.get(getattr(city, "city_id", None)) is not city:
            return False
        if not can_purchase(player, city, kind, name, resource):
            return False
        price = 10 * purchase_cost(player, kind, name, resource)
        spend(player, resource, price)
        if kind == ITEM_UNIT:
            city.place_or_queue_unit(name, self)
        else:
            city.buildings.append(name)
            if city.current_production == {"type": "building", "building_type": name}:
                city.current_production = None
        self.episode_stats[player.player_index][f"{resource}_spent_purchases"] += price
        return True

    # --- Trade routes (#116 P5, docs/progression_design.md §7.4) ---

    def establish_trade_route(self, trader, destination_city):
        """Open a trade route with `trader` from the own city centre it stands
        on (the origin) to `destination_city`. Refused (False, nothing
        changed) unless `trader` is a live unit of the trade type (`[trade]
        unit`) on one of its owner's city centres, the destination is among
        `trade.eligible_destinations` (another city within range, no route of
        this player between the pair) and a route slot is free
        (`len(routes) < trade.route_capacity`). On success the Trader is
        consumed (`delete_unit`) and a `TradeRoute` of `[trade]
        duration_turns` turns is appended to its owner's `routes`;
        `episode_stats["trade_routes_established"]` counts it."""
        player = trader.player
        if trader.unit_type != TRADER_UNIT or trader not in player.units:
            return False
        origin = origin_city(trader, self)
        if origin is None:
            return False
        if not any(city is destination_city for city in eligible_destinations(trader, self)):
            return False
        if len(player.routes) >= route_capacity(player):
            return False
        self.delete_unit(trader)
        player.routes.append(TradeRoute(
            origin_city_id=origin.city_id,
            destination_city_id=destination_city.city_id,
            player_index=player.player_index,
            turns_left=TRADE_DURATION_TURNS,
        ))
        self.episode_stats[player.player_index]["trade_routes_established"] += 1
        return True

    def economy_phase(self, player):
        """The player's economy phase (progression design, "v2 fixes", turn
        order): runs once per own turn from `Player.start_turn`, after every
        city has accrued and before the city ranged strike. The only place
        timed gold leaves the treasury and the only place a tech or a civic
        completes. The full order, one step per rule:

        1. maintenance -- `_pay_maintenance` (#116 P5)
        2. bankruptcy -- `_resolve_bankruptcy` (#116 P5); what the two steps
           took from the treasury counts in `episode_stats["gold_maintenance"]`
        3. research -- `resolve_research` (#116 P2)
        4. civics -- `resolve_civic` (#116 P4)
        5. government and loadout defaults -- `_government_and_loadout_defaults`
           (#116 P4)
        6. route expiry and Trader return -- `trade.expire_routes` (#116 P5)
        7. Trader auto-send -- `defaults.default_trade` (#116 P5)
        8. Worker default -- `defaults.default_workers` (#116 P8), after
           `_remove_spent_workers` (#127)

        Steps 1-8 exist; a later patch inserts its steps at their place here.
        """
        treasury = player.gold
        self._pay_maintenance(player)
        self._resolve_bankruptcy(player)
        self.episode_stats[player.player_index]["gold_maintenance"] += max(0, treasury - player.gold)
        self.resolve_research(player)
        civic = self.resolve_civic(player)
        self._government_and_loadout_defaults(player, refit=civic is not None)
        expire_routes(player, self)
        default_trade(player, self)
        self._remove_spent_workers(player)
        default_workers(player, self)

    def _remove_spent_workers(self, player):
        """Remove every Worker of `player` with no build charge left (#127).
        A build removes the Worker that spends its last charge; this catches
        the one left at 0 by losing a live `build_charges` source (a
        captured Pyramids), so no Worker lingers that can never build."""
        for unit in [u for u in player.units if isinstance(u, WorkerUnit)]:
            if unit.charges_left() <= 0:
                self.delete_unit(unit)

    # --- Upgrades (#116 P3, docs/progression_design.md §6.4) ---

    def upgrade_unit(self, unit):
        """Upgrade `unit` into its `upgrades_to` type, paying
        `upgrade_cost(unit)` gold. Refused (False, nothing changed) unless
        `can_upgrade` holds: an upgrade exists and its owner may build the
        target (`player_can_build`), the unit stands on a tile of one of its
        owner's cities, has all its movement and has not acted this turn, and
        the treasury (int tenths) covers the price.

        The unit OBJECT is replaced, through `_create_unit`, at the same index
        of `player.units` and the same place in its tile's stack, so its slot
        and every ordering that reads `player.units` ("oldest first") are
        kept. Health carries over; the new unit has spent its movement, is
        unfortified and counts as having acted (Civ 6: no upgrade-and-move in
        one turn). `episode_stats[...]["units_upgraded"]` counts it.

        No engine default and no agent action calls this yet: dormant until
        #99, like `swap_tile` -- an ACCEPTED GAP recorded in the CHANGELOG.
        The only way a unit changes type.
        """
        if not can_upgrade(self, unit):
            return False
        player = unit.player
        cost = upgrade_cost(unit)
        upgraded = _create_unit(upgrade_target(unit), player, unit.coordinates)
        upgraded.health = unit.health
        upgraded.movement_points = 0
        upgraded.fortification = 0
        upgraded.has_acted = True

        player.units[player.units.index(unit)] = upgraded
        stack = self.map.get_tile(unit.coordinates).units
        stack[stack.index(unit)] = upgraded
        player.gold -= 10 * cost  # the treasury is in tenths
        self.episode_stats[player.player_index]["units_upgraded"] += 1
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
