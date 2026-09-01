"""CityDistanceStateEncoder (issue #48): the nearest-enemy-city proximity
channel appended after the unchanged Enhanced prefix.

Mirrors test_terrain_encoder.py's contract structure:
1. Prefix bit-identity — channels 0..24 equal EnhancedStateEncoder's output.
2. Field correctness — proximity = 1 - d/D against canonical hexmath.distance,
   including across the cylindrical seam and nearest-of-several-cities.
3. Edge cases — no enemy cities (all zeros), depth (26 fogless).
4. Cache invalidation — capturing the enemy's only city zeroes the field on
   the next encode (the cache keys on the enemy-city coordinate set, NOT the
   terrain epoch: city ownership is not terrain).
"""

import numpy as np
import pytest
import torch

from civulator import hexmath
from civulator.agents.state_encoders import (
    CityDistanceStateEncoder,
    EnhancedStateEncoder,
)
from civulator.game.unit import WarriorUnit

from test_combat_range import make_flat_env, place


def fogless():
    return CityDistanceStateEncoder(fog_of_war=False)


def env_with_enemy_city(city_pos=(4, 8)):
    env = make_flat_env()  # 8x16, all Plains
    city = env.found_city(env.players[1], city_pos, "Enemy City")
    assert city is not None
    return env


def proximity(env, tile, cities):
    d_max = env.m // 2 + env.n - 1
    d = min(hexmath.distance(tile, c, env.m) for c in cities)
    return 1.0 - d / d_max


def test_depth_is_enhanced_plus_one():
    assert fogless().get_depth(2) == 26
    assert EnhancedStateEncoder(fog_of_war=False).get_depth(2) == 25


def test_prefix_bit_identical_to_enhanced():
    env = env_with_enemy_city()
    place(env, WarriorUnit, 0, (2, 3))
    place(env, WarriorUnit, 1, (6, 10))
    enhanced = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)
    combined = fogless().encode(env, 0)
    assert combined.shape[0] == 26
    assert torch.equal(combined[:25], enhanced)


def test_field_values_match_canonical_distance():
    city = (4, 8)
    env = env_with_enemy_city(city)
    state = fogless().encode(env, 0).numpy()
    field = state[25]

    assert field[4, 8] == pytest.approx(1.0)          # the city tile itself
    assert field[4, 5] == pytest.approx(proximity(env, (4, 5), [city]))  # d=3
    assert field[0, 0] == pytest.approx(proximity(env, (0, 0), [city]))
    # Across the seam: (4, 15) -> (4, 8) is distance 7 direct, not 9+.
    assert field[4, 15] == pytest.approx(proximity(env, (4, 15), [city]))
    # Gradient is nonzero everywhere: no two adjacent tiles on the straight
    # row toward the city share a value.
    assert field[4, 5] > field[4, 4] > field[4, 3]


def test_nearest_of_several_cities_wins():
    env = env_with_enemy_city((4, 8))
    second = env.found_city(env.players[1], (0, 1), "Second City")
    assert second is not None
    state = fogless().encode(env, 0).numpy()
    cities = [(4, 8), (0, 1)]
    assert state[25][0, 2] == pytest.approx(proximity(env, (0, 2), cities))
    assert state[25][4, 6] == pytest.approx(proximity(env, (4, 6), cities))


def test_no_enemy_cities_means_all_zeros():
    env = make_flat_env()
    place(env, WarriorUnit, 0, (2, 3))
    state = fogless().encode(env, 0).numpy()
    assert not state[25].any()


def test_capture_invalidates_cache():
    env = env_with_enemy_city((4, 8))
    encoder = fogless()
    first = encoder.encode(env, 0).numpy()
    assert first[25].any()

    # Capture: ownership flips, terrain untouched — the field must still react.
    env.map.get_tile((4, 8)).city.set_owner(env.players[0])
    second = encoder.encode(env, 0).numpy()
    assert not second[25].any(), "captured city still radiates as enemy"
    # And from the OTHER player's perspective it now does radiate.
    other = encoder.encode(env, 1).numpy()
    assert other[25][4, 8] == pytest.approx(1.0)
