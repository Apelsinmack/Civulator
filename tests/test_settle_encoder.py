"""SettleSiteStateEncoder ("settle", 54ch): where a city may legally be
founded, as a state channel (issue #8).

The channel must agree with `GameEnvironment.can_found_city_at` exactly —
it exists so an agent can see the settling rule instead of discovering it by
trial — and its cache must invalidate when a city appears, since founding
one is precisely what changes the legal set.
"""

import numpy as np
import torch

from civulator.agents.state_encoders import (
    FullStateEncoder,
    SettleSiteStateEncoder,
)
from civulator.game.environment import MIN_CITY_DISTANCE
from civulator.game.unit import WarriorUnit

from test_combat_range import make_flat_env, place

SETTLE_CH = 53  # appended after the 53-channel `full` prefix


def fogless():
    return SettleSiteStateEncoder(fog_of_war=False)


def test_depth_is_full_plus_one():
    assert fogless().get_depth(2) == 54
    assert FullStateEncoder(fog_of_war=False).get_depth(2) == 53


def test_prefix_is_bit_identical_to_full():
    env = make_flat_env()
    assert env.found_city(env.players[1], (4, 8), "Enemy") is not None
    place(env, WarriorUnit, 0, (2, 2))

    combined = fogless().encode(env, 0)
    assert combined.shape[0] == 54
    assert torch.equal(combined[:53], FullStateEncoder(fog_of_war=False).encode(env, 0))


def test_channel_agrees_with_can_found_city_at_everywhere():
    """The whole point: the channel IS the rule, not an approximation."""
    env = make_flat_env()
    assert env.found_city(env.players[0], (4, 4), "Mine") is not None
    assert env.found_city(env.players[1], (2, 12), "Theirs") is not None

    layer = fogless().encode(env, 0).numpy()[SETTLE_CH]
    for i in range(env.n):
        for j in range(env.m):
            assert bool(layer[i, j]) == env.can_found_city_at((i, j)), (i, j)


def test_ring_around_a_city_is_excluded():
    env = make_flat_env()
    assert env.found_city(env.players[0], (4, 4), "Mine") is not None
    layer = fogless().encode(env, 0).numpy()[SETTLE_CH]

    assert layer[4, 4] == 0.0                      # the city tile itself
    for d in range(1, MIN_CITY_DISTANCE):          # everything inside the ring
        assert layer[4, 4 + d] == 0.0
    assert layer[4, 4 + MIN_CITY_DISTANCE] == 1.0  # the first legal tile out


def test_cache_invalidates_when_a_city_is_founded():
    """Cities change the legal set, and founding one is the common case —
    a stale cache would teach the agent a rule that is no longer true."""
    env = make_flat_env()
    encoder = fogless()

    before = encoder.encode(env, 0).numpy()[SETTLE_CH].copy()
    assert before[4, 4] == 1.0

    assert env.found_city(env.players[0], (4, 4), "New") is not None
    after = encoder.encode(env, 0).numpy()[SETTLE_CH]

    assert after[4, 4] == 0.0
    assert after.sum() < before.sum()


def test_water_and_impassable_tiles_are_never_settleable():
    env = make_flat_env()
    env.map.tiles[0, 0].set_layers("Ocean", map_ref=env.map)
    env.map.tiles[0, 1].set_layers("Grassland", relief="mountain", map_ref=env.map)

    layer = fogless().encode(env, 0).numpy()[SETTLE_CH]
    assert layer[0, 0] == 0.0
    assert layer[0, 1] == 0.0
    assert np.any(layer > 0), "a flat Plains board should have legal sites"
