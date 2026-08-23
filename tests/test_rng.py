"""Golden tests for PortableRNG (issue #33).

These vectors are the CONTRACT for the future C++ twin: it is correct when it
reproduces them bit-for-bit. The uint32 vector additionally matches O'Neill's
published pcg32 reference output for (initstate=42, initseq=54) — verified
against the canonical pcg32-global-demo values 0xa15c02b7, 0x7b47f409, ...
"""


from civulator.rng import PortableRNG
from civulator.game.environment import GameEnvironment


def test_uint32_matches_pcg32_reference():
    r = PortableRNG(42)
    assert [r._next_uint32() for _ in range(6)] == [
        2707161783, 2068313097, 3122475824, 2211639955, 3215226955, 3421331566,
    ]


def test_next_uint64_combines_two_uint32_draws_high_first():
    """next_uint64() (design doc §4.2.1, added P3 for the mapgen master-seed
    draw) is exactly (first_uint32 << 32) | second_uint32 — derived from the
    same frozen seed=42 vector `test_uint32_matches_pcg32_reference` pins."""
    r = PortableRNG(42)
    assert r.next_uint64() == (2707161783 << 32) | 2068313097

    # And it really does consume two draws from the shared stream (a
    # subsequent _next_uint32() continues where next_uint64() left off).
    r2 = PortableRNG(42)
    r2._next_uint32()
    r2._next_uint32()
    assert r2._next_uint32() == 3122475824


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


def test_engine_world_is_frozen_across_versions():
    """A seeded world's fingerprint must never change silently — scenario files
    depend on it (terrain is rebuilt from the stored seed + pinned params). If
    this test fails, a CHANGELOG entry and version bump are REQUIRED, and
    existing scenario terrain is invalidated.

    Re-baselined at the v0.6.0 P8 ceremony (Erik-inspected, 2026-08-23) onto
    Duel earthlike — the engine-level wiring guard over the same contract the
    MapData golden (tests/test_mapgen_golden.py) seals in full. Params are
    passed pinned (P7's mapgen_params), so config knob tuning can never break
    this test — only a genuine generator or engine-wiring change can.
    """
    from test_mapgen_golden import PINNED_PARAMS

    env = GameEnvironment(12, 24, num_players=2, map_type="earthlike",
                          mapgen_params=PINNED_PARAMS).reset(seed=42)
    m = env.map
    assert [m.tiles[0, j].label for j in range(24)] == [
        "Coast, Ice", "Snow", "Snow", "Snow", "Plains", "Snow", "Coast, Ice",
        "Ocean, Ice", "Ocean, Ice", "Ocean", "Coast, Ice", "Coast, Ice",
        "Desert", "Snow (Hills)", "Snow", "Coast", "Ocean", "Ocean, Ice",
        "Ocean", "Ocean, Ice", "Ocean, Ice", "Ocean", "Ocean, Ice", "Ocean, Ice",
    ], "seeded world changed — scenario seeds are now invalid; bump version + CHANGELOG"
    assert [m.tiles[6, j].label for j in range(24)] == [
        "Grassland", "Grassland", "Snow (Hills)", "Desert (Hills)",
        "Snow (Hills)", "Plains", "Grassland (Hills), Woods", "Plains",
        "Tundra (Hills)", "Snow (Mountain)", "Coast, Ice", "Ocean", "Ocean",
        "Ocean, Ice", "Coast, Ice", "Coast", "Ocean, Ice", "Ocean, Ice",
        "Ocean", "Ocean, Ice", "Ocean, Ice", "Coast, Ice", "Grassland", "Grassland",
    ]
    assert sorted(m.starts) == [(7, 5), (7, 23)]
    assert len(m.rivers) == 88
    assert sum(1 for i in range(12) for j in range(24) if m.tiles[i, j].resource) == 14
