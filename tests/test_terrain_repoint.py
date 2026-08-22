"""Regressions for the P2a engine re-point (design doc §3, §7, §9, §11 P2a).

Every gameplay number now comes from the tile's composed layers instead of a
flat terrain string. These tests pin the behaviour changes that re-pointing
caused — the latent fixes of §9 that were inert or wrong before 0.6.
"""

import numpy as np
import torch

from civulator.agents.networks import get_valid_moves_mask
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.game.environment import STARTING_WARRIORS, GameEnvironment
from civulator.game.map import BLOCKED_COST
from civulator.game.unit import NUM_UNIT_SLOTS, RIVER_CROSSING_COST, WarriorUnit

from test_combat_range import make_flat_env, place


def _paint(env, coords, base, relief=None, feature=None):
    env.map.get_tile(coords).set_layers(base, relief=relief, feature=feature, map_ref=env.map)


# --- §9.7: defense follows the unit, not its spawn tile ---------------------


def test_defense_changes_when_a_unit_moves_onto_hills():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (4, 8))
    _paint(env, (4, 9), "Plains", relief="hills")

    on_flat = warrior.get_combat_strength(is_attacking=False)
    moved, pos = warrior.move((4, 9), env)

    assert moved and pos == (4, 9)
    assert warrior.get_combat_strength(is_attacking=False) == on_flat + 3


def test_defense_stacks_relief_and_feature_additively():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (4, 8))
    _paint(env, (4, 8), "Plains", relief="hills", feature="Woods")
    # hills (+3) + Woods (+3) — pre-0.6 this needed a hand-written special case
    assert warrior.get_combat_strength(is_attacking=False) == \
        warrior.get_base_combat_strength() + 6


# --- §9.8: city-produced units get terrain defense --------------------------


def test_city_produced_unit_gets_terrain_defense():
    env = make_flat_env()
    _paint(env, (3, 3), "Plains", relief="hills")
    city = env.found_city(env.players[0], (3, 3), "Highhold")

    assert city.complete_unit_production("Warrior", env) is True
    unit = env.players[0].units[-1]
    assert unit.coordinates == (3, 3)
    # Before 0.6 produced units carried terrain=None and never got a bonus.
    assert unit.get_combat_strength(is_attacking=False) == \
        unit.get_base_combat_strength() + 3


def test_city_production_skips_tiles_its_domain_cannot_enter():
    env = make_flat_env()
    city = env.found_city(env.players[0], (3, 3), "Lakeside")
    place(env, WarriorUnit, 0, (3, 3))  # centre taken, must spill to a neighbour

    adj = env.map.get_adjacent_coords((3, 3))
    for pos in adj:
        _paint(env, pos, "Ocean")
    _paint(env, adj[-1], "Plains")

    assert city.complete_unit_production("Warrior", env) is True
    assert env.players[0].units[-1].coordinates == adj[-1]


# --- §3: water is workable but not settleable -------------------------------


def test_water_is_worked_by_cities_but_cannot_be_settled():
    env = make_flat_env()
    city = env.found_city(env.players[0], (4, 7), "Harbour")
    for pos in env.map.get_adjacent_coords((4, 7)):
        _paint(env, pos, "Desert")
    _paint(env, (4, 8), "Lake")           # workable water: 2 food
    _paint(env, (3, 7), "Plains", relief="mountain")  # unworkable

    city.population = 6
    city.assign_tiles(env)

    assert (4, 8) in city.worked_tiles, "water is workable (§3)"
    assert (3, 7) not in city.worked_tiles, "impassable tiles are unworkable"
    assert env.can_found_city_at((4, 8)) is False, "water is not settleable"
    assert env.can_found_city_at((3, 7)) is False, "mountains are not settleable"


# --- §3.3 / §7.3: the masks gained a terrain filter -------------------------


def test_move_mask_excludes_mountain_and_water_destinations():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (4, 8))
    _paint(env, (4, 9), "Ocean")
    _paint(env, (3, 8), "Plains", relief="mountain")

    state = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)
    selected_pos = (4 * env.m + 8) * NUM_UNIT_SLOTS + warrior.slot
    mask = get_valid_moves_mask(state, selected_pos, env).reshape(env.n, env.m)

    assert mask[4, 9] == 0, "water is unofferable to a land unit"
    assert mask[3, 8] == 0, "mountains are unofferable"
    assert mask[5, 8] == 1, "ordinary land neighbour stays offerable"
    assert mask[4, 8] == 1, "own tile stays valid (fortify / found city)"


def test_engine_refuses_the_moves_the_mask_hides():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (4, 8))
    _paint(env, (4, 9), "Ocean")
    assert warrior.move((4, 9), env) == (False, (4, 8))


# --- §3.3 / §3.4: per-domain cost grids, cached by terrain epoch ------------


def test_cost_grid_is_cached_and_invalidated_by_set_layers():
    env = make_flat_env()
    grid = env.map._build_cost_grid("land")
    assert env.map._build_cost_grid("land") is grid, "unchanged terrain reuses the grid"

    _paint(env, (2, 2), "Plains", relief="mountain")

    rebuilt = env.map._build_cost_grid("land")
    assert rebuilt is not grid, "set_layers bumps terrain_epoch, dropping the cache"
    assert grid[2, 2] == 1
    assert rebuilt[2, 2] >= BLOCKED_COST


def test_cost_grid_is_per_domain():
    env = make_flat_env()
    _paint(env, (2, 2), "Coast")

    land = env.map._build_cost_grid("land")
    water = env.map._build_cost_grid("water")

    assert land[2, 2] >= BLOCKED_COST and water[2, 2] == 1
    assert land[3, 3] == 1 and water[3, 3] >= BLOCKED_COST


def test_pathfinder_routes_around_water():
    env = make_flat_env()
    for row in range(env.n):
        _paint(env, (row, 9), "Ocean")

    path = env.map.path_finder((4, 8), (4, 10), domain="land")

    assert path, "a land route around the cylinder exists"
    assert all(int(step[1]) != 9 for step in path), "no step through the water wall"


# --- §9.9 / §9.10: config keys that used to be dead or hardcoded ------------


def test_river_crossing_cost_comes_from_config():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (4, 8))
    env.map.add_river((4, 8), (4, 9))

    before = warrior.movement_points
    warrior.move((4, 9), env)
    assert warrior.movement_points == before - (1 + RIVER_CROSSING_COST)


def test_starting_warriors_and_spawn_tiles_respect_the_domain_check():
    env = GameEnvironment(24, 48, num_players=4)
    for seed in range(5):
        env.reset(seed=seed)
        for player in env.players:
            assert len(player.units) <= STARTING_WARRIORS
            for unit in player.units:
                assert unit.can_enter(env.map.get_tile(unit.coordinates)), \
                    f"seed {seed}: {unit.unit_type} spawned on terrain it cannot enter"


# --- §9.6: improvement validity is config-driven ----------------------------


def test_improvement_validity_reads_the_on_constraints():
    env = make_flat_env()
    _paint(env, (1, 1), "Plains", relief="hills")
    _paint(env, (1, 2), "Coast")
    _paint(env, (1, 3), "Desert", feature="Floodplains")

    assert env.can_build_improvement_at((1, 1), "Mine") is True
    assert env.can_build_improvement_at((0, 0), "Mine") is False   # flat Plains
    assert env.can_build_improvement_at((0, 0), "Farm") is True
    assert env.can_build_improvement_at((1, 3), "Farm") is True    # Floodplains branch
    assert env.can_build_improvement_at((1, 2), "Fishing Boats") is True
    assert env.can_build_improvement_at((0, 0), "Fishing Boats") is False
    assert env.can_build_improvement_at((0, 0), "Teleporter") is False


# --- §7 / E6: encoder value semantics ---------------------------------------


def test_encoder_cost_channel_saturates_only_on_impassable():
    env = make_flat_env()
    _paint(env, (0, 0), "Plains", relief="mountain")
    _paint(env, (0, 1), "Plains", relief="hills", feature="Woods")  # cost 3
    _paint(env, (0, 2), "Ocean")

    state = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)

    assert state[24, 0, 0] == 1.0, "impassable pins to the max (E6)"
    assert np.isclose(state[24, 0, 1].item(), 0.75), "costliest passable composite"
    assert np.isclose(state[24, 0, 2].item(), 0.25), "water is cheap, not saturated"


def test_encoder_terrain_layer_rebuilds_after_a_terrain_edit():
    env = make_flat_env()
    enc = EnhancedStateEncoder(fog_of_war=False)
    before = enc.encode(env, 0)[24, 0, 0].item()

    _paint(env, (0, 0), "Plains", relief="mountain")

    assert enc.encode(env, 0)[24, 0, 0].item() != before


def test_encoder_defense_channel_matches_the_engine():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (4, 8))
    _paint(env, (4, 8), "Plains", relief="hills", feature="Woods")

    state = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)
    encoded = state[10, 4, 8].item() * EnhancedStateEncoder.MAX_DEFENSE_BONUS
    engine = warrior.get_combat_strength(False) - warrior.get_base_combat_strength()

    assert np.isclose(encoded, engine)
    assert torch.all(state[10] <= 1.0), "the defense normalizer clamps at 1.0"
