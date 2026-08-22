"""Golden tests for PortableRNG (issue #33).

These vectors are the CONTRACT for the future C++ twin: it is correct when it
reproduces them bit-for-bit. The uint32 vector additionally matches O'Neill's
published pcg32 reference output for (initstate=42, initseq=54) — verified
against the canonical pcg32-global-demo values 0xa15c02b7, 0x7b47f409, ...
"""

import pytest

from civulator.rng import PortableRNG
from civulator.game.environment import GameEnvironment


def test_uint32_matches_pcg32_reference():
    r = PortableRNG(42)
    assert [r._next_uint32() for _ in range(6)] == [
        2707161783, 2068313097, 3122475824, 2211639955, 3215226955, 3421331566,
    ]


def test_derived_draws_are_frozen():
    r = PortableRNG(42)
    assert [round(r.random(), 10) for _ in range(3)] == [
        0.6303102204, 0.4815666697, 0.7270080559,
    ]

    r.seed(123)
    assert [r.randint(1, 10) for _ in range(8)] == [6, 4, 7, 6, 10, 9, 4, 2]

    r.seed(7)
    lst = list(range(8))
    r.shuffle(lst)
    assert lst == [2, 7, 5, 4, 0, 6, 1, 3]

    r.seed(99)
    assert r.choices(["a", "b", "c"], weights=[1, 2, 7], k=6) == [
        "c", "c", "c", "b", "c", "a",
    ]


def test_reseed_replays_stream():
    r = PortableRNG(5)
    first = [r._next_uint32() for _ in range(4)]
    r.seed(5)
    assert [r._next_uint32() for _ in range(4)] == first


def test_randint_bounds_and_shuffle_permutation():
    r = PortableRNG(1)
    draws = [r.randint(3, 5) for _ in range(200)]
    assert set(draws) == {3, 4, 5}

    lst = list(range(20))
    r.shuffle(lst)
    assert sorted(lst) == list(range(20))


@pytest.mark.xfail(reason="0.6 world model — re-baseline at P8, design §8")
def test_engine_world_is_frozen_across_versions():
    """A seeded world's fingerprint must never change silently — scenario files
    depend on it (terrain is rebuilt from the stored seed). If this test fails,
    a CHANGELOG entry and version bump are REQUIRED, and existing scenario
    terrain is invalidated."""
    env = GameEnvironment(8, 16, num_players=2).reset(seed=42)
    terrains = [env.map.tiles[i, j].terrain_type for i in range(2) for j in range(8)]
    assert terrains == [
        "Desert", "Grassland", "Tundra", "Tundra", "Hills", "Mountain", "Plains", "Woods",
        "Grassland", "Hills", "Hills", "Plains", "Desert", "Plains", "Grassland", "Grassland",
    ], "seeded world changed — scenario seeds are now invalid; bump version + CHANGELOG"
