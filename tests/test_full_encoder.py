"""FullStateEncoder ("full", 53ch): TerrainAware prefix + the city-distance
proximity channel appended last (the 2026-09-02 kitchen-sink encoder).

Contracts:
1. Depth: 52 + 1 = 53 fogless.
2. Prefix bit-identity — channels 0..51 equal TerrainAwareStateEncoder's
   output (which itself pins its own 0..24 prefix to Enhanced).
3. The last channel equals CityDistanceStateEncoder's field channel exactly
   (one field implementation, two positions).
"""

import torch

from civulator.agents.state_encoders import (
    CityDistanceStateEncoder,
    FullStateEncoder,
    TerrainAwareStateEncoder,
)
from civulator.game.unit import WarriorUnit

from test_combat_range import make_flat_env, place


def build_env():
    env = make_flat_env()
    assert env.found_city(env.players[1], (4, 8), "Enemy City") is not None
    place(env, WarriorUnit, 0, (4, 4))
    place(env, WarriorUnit, 1, (2, 10))
    return env


def test_depth_is_terrain_aware_plus_one():
    assert FullStateEncoder(fog_of_war=False).get_depth(2) == 53


def test_prefix_and_field_channels_bit_identical():
    env = build_env()
    full = FullStateEncoder(fog_of_war=False).encode(env, 0)
    terrain = TerrainAwareStateEncoder(fog_of_war=False).encode(env, 0)
    distance = CityDistanceStateEncoder(fog_of_war=False).encode(env, 0)

    assert full.shape[0] == 53
    assert torch.equal(full[:52], terrain)
    assert torch.equal(full[52], distance[25])
    assert full[52].max() == 1.0  # the enemy-city tile itself
