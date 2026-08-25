"""Tests for TerrainAwareStateEncoder (issue #40).

Oracle points below are numbered to match docs/terrain_encoder_design.md's
"Oracle (gate for auto-merge)" section exactly, so each test traces back to
its requirement:

1. Prefix bit-identity (fog on AND off) against EnhancedStateEncoder.
2. One-hot exclusivity + coverage (base/feature/relief).
3. River losslessness (owned-edge channels reconstruct Map.rivers exactly).
4. Water access ordinal (fresh / coastal / inland / oasis / lake-adjacent).
5. Scalar channels in [0,1]; spot-check a known composite against
   terrain_model.compose.
6. Fog: terrain block zero on unexplored tiles, intact on explored.
7. Determinism: same seed -> identical tensor; cache invalidates on
   Tile.set_layers (terrain_epoch bump).
"""

import numpy as np
import pytest
import torch

from civulator import hexmath
from civulator.agents.state_encoders import (
    EnhancedStateEncoder,
    TerrainAwareStateEncoder,
    get_encoder,
)
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.mapgen.starts import StartPlacementError
from civulator.terrain_model import compose

from test_combat_range import make_flat_env

# --- Shared fixture: a real generated world (design doc oracle 1: "on a
# generated world") -----------------------------------------------------

_DUEL_N, _DUEL_M, _DUEL_PLAYERS = resolve_size_and_players(size="duel")


def _generated_env(seed, max_tries=8):
    """A real earthlike-generated duel-size world, with a small deterministic
    seed-skip retry (mirrors GameEnvironment.reset's own unseeded-resample
    idea) so an occasional unplaceable seed (~2% per design doc D26) can't
    make this fixture flaky.
    """
    for attempt in range(max_tries):
        try:
            # GameEnvironment.__init__ itself draws an (unseeded) map at
            # construction time -- that draw can also fail start placement,
            # so it must be inside the retry's try, not just env.reset().
            env = GameEnvironment(_DUEL_N, _DUEL_M, num_players=_DUEL_PLAYERS, map_type="earthlike")
            env.reset(seed=seed + attempt)
            return env
        except StartPlacementError:
            continue
    raise RuntimeError(f"could not generate a duel-size world near seed={seed}")


# Absolute channel offsets in the no-fog (depth 52) output. The 27-channel
# terrain block starts right after the parent's 25 no-fog channels.
PARENT_DEPTH_NO_FOG = 25
PARENT_DEPTH_FOG = 27
T = PARENT_DEPTH_NO_FOG  # terrain block base offset (no fog)


# --- 1. Prefix bit-identity --------------------------------------------

@pytest.mark.parametrize("fog", [False, True])
def test_prefix_bit_identical_to_parent(fog):
    env = _generated_env(seed=777)
    parent = EnhancedStateEncoder(fog_of_war=fog)
    child = TerrainAwareStateEncoder(fog_of_war=fog)

    parent_out = parent.encode(env, 0)
    child_out = child.encode(env, 0)

    parent_depth = parent.get_depth(len(env.players))
    assert child_out.shape[0] == parent_depth + 27
    assert torch.equal(child_out[:parent_depth], parent_out), \
        "terrain-aware prefix must be bit-identical to the parent encoder"


# --- 2. One-hot exclusivity + coverage ----------------------------------

def test_base_feature_relief_onehot_exclusivity_and_coverage():
    env = _generated_env(seed=778)
    enc = TerrainAwareStateEncoder(fog_of_war=False)
    state = enc.encode(env, 0).numpy()

    base_block = state[T:T + 8]
    relief_block = state[T + 8:T + 10]
    feature_block = state[T + 10:T + 17]

    for i in range(env.n):
        for j in range(env.m):
            tile = env.map.tiles[i, j]

            base_sum = base_block[:, i, j].sum()
            assert base_sum == 1.0, f"tile ({i},{j}) base one-hot sum={base_sum}"
            assert base_block[enc._base_index[tile.base_terrain], i, j] == 1.0

            feature_sum = feature_block[:, i, j].sum()
            assert feature_sum in (0.0, 1.0), f"tile ({i},{j}) feature sum={feature_sum}"
            if tile.feature is not None:
                assert feature_block[enc._feature_index[tile.feature], i, j] == 1.0
            else:
                assert feature_sum == 0.0

            hills_flag, mountain_flag = relief_block[:, i, j]
            if tile.relief == "hills":
                assert hills_flag == 1.0 and mountain_flag == 0.0
            elif tile.relief == "mountain":
                assert mountain_flag == 1.0 and hills_flag == 0.0
            else:
                assert hills_flag == 0.0 and mountain_flag == 0.0


# --- 3. River losslessness -----------------------------------------------

def test_river_owned_edge_channels_reconstruct_map_rivers_exactly():
    env = make_flat_env(n=9, m=18)
    center = (4, 8)
    # Add a river on all 6 directions out of `center` -- exercises both the
    # 3 owned directions and the 3 mirrored-via-neighbor directions (map.py's
    # RIVER_EDGE_DIRECTIONS split).
    for dr, dc in hexmath.HEX_DIRECTIONS:
        neighbor = (center[0] + dr, (center[1] + dc) % env.m)
        env.map.add_river(center, neighbor)

    enc = TerrainAwareStateEncoder(fog_of_war=False)
    state = enc.encode(env, 0).numpy()
    river_block = state[T + 18:T + 21]

    reconstructed = set()
    for i in range(env.n):
        for j in range(env.m):
            for k in range(3):
                if river_block[k, i, j] > 0:
                    dr, dc = hexmath.HEX_DIRECTIONS[k]
                    ni, nj = i + dr, (j + dc) % env.m
                    if 0 <= ni < env.n:
                        edge = tuple(sorted([(i, j), (ni, nj)]))
                        reconstructed.add(edge)

    expected = set(env.map.rivers.keys())
    assert reconstructed == expected


# --- 4. Water access ordinal --------------------------------------------

def test_water_access_ordinal_cases():
    env = make_flat_env(n=10, m=20)

    inland = (1, 1)  # left untouched: no water/river/oasis anywhere nearby

    coastal = (1, 10)
    coastal_water_neighbor = (
        coastal[0] + hexmath.HEX_DIRECTIONS[0][0],
        (coastal[1] + hexmath.HEX_DIRECTIONS[0][1]) % env.m,
    )
    env.map.get_tile(coastal_water_neighbor).set_layers("Ocean", map_ref=env.map)

    river_adjacent = (4, 1)
    river_neighbor = (
        river_adjacent[0] + hexmath.HEX_DIRECTIONS[0][0],
        (river_adjacent[1] + hexmath.HEX_DIRECTIONS[0][1]) % env.m,
    )
    env.map.add_river(river_adjacent, river_neighbor)

    oasis = (4, 10)
    env.map.get_tile(oasis).set_layers("Desert", relief=None, feature="Oasis", map_ref=env.map)

    lake_adjacent = (7, 1)
    lake_neighbor = (
        lake_adjacent[0] + hexmath.HEX_DIRECTIONS[0][0],
        (lake_adjacent[1] + hexmath.HEX_DIRECTIONS[0][1]) % env.m,
    )
    env.map.get_tile(lake_neighbor).set_layers("Lake", map_ref=env.map)

    enc = TerrainAwareStateEncoder(fog_of_war=False)
    state = enc.encode(env, 0).numpy()
    water_access = state[T + 21]

    assert water_access[inland] == pytest.approx(0.0), "isolated inland tile"
    assert water_access[coastal] == pytest.approx(0.5), "ocean-adjacent (not fresh) land tile"
    assert water_access[river_adjacent] == pytest.approx(1.0), "river-adjacent tile is fresh"
    assert water_access[oasis] == pytest.approx(1.0), "oasis tile is fresh"
    assert water_access[lake_adjacent] == pytest.approx(1.0), \
        "lake-adjacent tile is fresh, NOT the 0.5 generic-water-neighbor value"


# --- 5. Scalar channels in [0,1]; composite spot-check -------------------

def test_scalar_channels_bounded_and_hills_woods_defense_matches_compose():
    env = _generated_env(seed=779)
    enc = TerrainAwareStateEncoder(fog_of_war=False)

    pos = (1, 1)
    env.map.get_tile(pos).set_layers("Grassland", relief="hills", feature="Woods", map_ref=env.map)

    state = enc.encode(env, 0).numpy()

    for offset in (22, 23, 24, 25, 26):
        channel = state[T + offset]
        assert channel.min() >= -1e-6, f"channel +{offset} has a value below 0"
        assert channel.max() <= 1.0 + 1e-6, f"channel +{offset} has a value above 1"

    composed = compose("Grassland", relief="hills", feature="Woods")
    expected_defense = min(1.0, max(0.0, composed.defense / enc.max_defense))
    assert state[T + 22, pos[0], pos[1]] == pytest.approx(expected_defense)
    # hills (+3) + Woods (+3) is the config's own max-defense composite, so
    # this also pins the normalization derivation to a concrete, saturating case.
    assert expected_defense == pytest.approx(1.0)


# --- 6. Fog -----------------------------------------------------------

def test_fog_zeroes_terrain_block_outside_explored_and_keeps_it_inside():
    env = _generated_env(seed=780)
    enc = TerrainAwareStateEncoder(fog_of_war=True)
    state = enc.encode(env, 0).numpy()

    terrain_block = state[PARENT_DEPTH_FOG:]
    explored = env.get_explored_mask(0)

    assert (~explored).any(), "fixture needs at least one unexplored tile"
    assert explored.any(), "fixture needs at least one explored tile"

    unexplored_coords = np.argwhere(~explored)
    for i, j in unexplored_coords:
        assert np.all(terrain_block[:, i, j] == 0.0), \
            f"unexplored tile ({i},{j}) must have a fully zeroed terrain block"

    explored_coords = np.argwhere(explored)
    assert any(terrain_block[:, i, j].any() for i, j in explored_coords), \
        "at least one explored tile must carry real terrain signal (base one-hot always fires)"


# --- 7. Determinism + cache invalidation --------------------------------

def test_same_seed_gives_identical_tensor():
    env1 = _generated_env(seed=4242)
    env2 = _generated_env(seed=4242)
    out1 = TerrainAwareStateEncoder(fog_of_war=False).encode(env1, 0)
    out2 = TerrainAwareStateEncoder(fog_of_war=False).encode(env2, 0)
    assert torch.equal(out1, out2)


def test_terrain_block_cache_invalidates_on_set_layers():
    env = _generated_env(seed=4243)
    enc = TerrainAwareStateEncoder(fog_of_war=False)
    block_before = enc._get_terrain_block(env)
    assert enc._get_terrain_block(env) is block_before, "unchanged terrain reuses the cached block"

    pos = (0, 0)
    old_base = env.map.tiles[pos].base_terrain
    new_base = "Desert" if old_base != "Desert" else "Tundra"
    env.map.get_tile(pos).set_layers(new_base, map_ref=env.map)

    block_after = enc._get_terrain_block(env)
    assert block_after is not block_before, "set_layers bumps terrain_epoch, dropping the cache"
    assert not np.array_equal(block_before[:, 0, 0], block_after[:, 0, 0])


# --- Registry + depth sanity (deliverable 2, not one of the 7 oracle points
# but exercises the wiring the rest of this suite relies on) ---------------

def test_get_depth_no_fog_and_fog():
    assert TerrainAwareStateEncoder(fog_of_war=False).get_depth(2) == 52
    assert TerrainAwareStateEncoder(fog_of_war=True).get_depth(2) == 54


def test_get_encoder_registry():
    assert isinstance(get_encoder("enhanced"), EnhancedStateEncoder)
    assert isinstance(get_encoder("terrain_aware"), TerrainAwareStateEncoder)
    with pytest.raises(ValueError):
        get_encoder("nonexistent")
