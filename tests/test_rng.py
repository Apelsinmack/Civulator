"""Golden tests for PhiloxRNG (issue #33 PCG32 -> issue #128 Q0 philox32).

The word-stream test pins the *layout* (key, counter, salt, buffering) against
the kit's own block function; the derived-draw vectors are the CONTRACT for a
future C++/CUDA twin built on philox32.h: it is correct when it reproduces them
bit-for-bit. Each test's docstring names the property and the change that must
break it.
"""

import math

import pytest
from philox32 import philox32_4x32_10, philox32_below

from civulator.rng import STREAM_SALT, PhiloxRNG, PortableRNG
from civulator.game.environment import GameEnvironment


def _expected_words(seed, n):
    """The stream by definition (module docstring layout), computed straight
    from the kit's block function -- no copied numbers."""
    key = (seed & 0xFFFFFFFF, (seed >> 32) & 0xFFFFFFFF)
    words = []
    block = 0
    while len(words) < n:
        words.extend(philox32_4x32_10((block, 0, STREAM_SALT, 0), key))
        block += 1
    return words[:n]


@pytest.mark.parametrize("seed", [0, 42, 2**32 + 7, 2**64 - 1])
def test_word_stream_is_philox_blocks_on_the_documented_layout(seed):
    """Property: next_uint32() yields w0..w3 of block 0, then block 1, ... of
    philox32_4x32_10((block, 0, STREAM_SALT, 0), (seed_lo, seed_hi)). Breaks
    if the counter/key layout, word order, buffering or salt drifts (a drifted
    layout silently forks every consumer's stream from the C++ twin's)."""
    r = PhiloxRNG(seed)
    assert [r.next_uint32() for _ in range(11)] == _expected_words(seed, 11)


def test_seed_is_taken_modulo_2_64():
    """Property: only the low 64 bits of the seed matter (key = two words).
    Breaks if a seed wider than 64 bits (or negative) raises or aliases
    differently than the documented `seed & (2^64 - 1)`."""
    assert PhiloxRNG(-1).next_uint32() == PhiloxRNG(2**64 - 1).next_uint32()
    assert PhiloxRNG(2**64 + 5).next_uint32() == PhiloxRNG(5).next_uint32()


def test_portable_rng_alias_is_philoxrng():
    """Property: old call sites that import PortableRNG get the new engine RNG
    (one-release alias). Breaks when the alias is removed or re-pointed before
    its CHANGELOG line says so."""
    assert PortableRNG is PhiloxRNG


def test_unseeded_generators_differ():
    """Property: unseeded construction draws from os.urandom, so two
    generators do not share a stream. Breaks if the default seed becomes a
    constant."""
    assert [PhiloxRNG().next_uint32() for _ in range(2)] !=         [PhiloxRNG().next_uint32() for _ in range(2)]


def test_next_uint64_combines_two_uint32_draws_high_first():
    """Property: next_uint64() is exactly (first_word << 32) | second_word and
    consumes two words (the mapgen master-seed draw, design doc §4.2.1).
    Breaks if the word order swaps or it consumes a different count."""
    w = _expected_words(42, 3)
    r = PhiloxRNG(42)
    assert r.next_uint64() == (w[0] << 32) | w[1]
    assert r.next_uint32() == w[2]


def test_one_word_per_random_and_randint_and_block_advances_by_ceil_quarter():
    """Property: random() and randint() consume exactly one word each, so the
    stream is accountable -- after n draws the block counter is ceil(n/4).
    Breaks if a rejection loop (or any value-dependent redraw) is introduced
    into a derived draw."""
    for n in range(1, 14):
        for draw in (lambda r: r.random(), lambda r: r.randint(1, 6),
                     lambda r: r.randint(0, 2**31 + 12345)):
            r = PhiloxRNG(11)
            for _ in range(n):
                draw(r)
            assert r._block == math.ceil(n / 4)
    # ... and the draws consume the words in order, one each
    w = _expected_words(11, 5)
    r = PhiloxRNG(11)
    assert [r.random() for _ in range(5)] == [x / 2**32 for x in w]
    r.seed(11)
    assert [r.randint(0, 99) for _ in range(5)] == [philox32_below(x, 100) for x in w]


def test_derived_draws_are_frozen():
    """Property: the derived draws (random, randint, shuffle, choices) map the
    word stream the way the module docstring says, frozen as the C++ twin's
    oracle. Breaks if any mapping (Lemire randint, Fisher-Yates direction,
    cumulative scan) changes. Regenerated once at the v0.9.0 Q0 migration."""
    r = PhiloxRNG(42)
    assert [round(r.random(), 10) for _ in range(3)] == [
        0.1132941307, 0.4870336389, 0.0559803224,
    ]

    r.seed(123)
    assert [r.randint(1, 10) for _ in range(8)] == [9, 1, 3, 8, 9, 8, 3, 8]

    r.seed(7)
    lst = list(range(8))
    r.shuffle(lst)
    assert lst == [4, 0, 7, 5, 6, 1, 3, 2]

    r.seed(99)
    assert r.choices(["a", "b", "c"], weights=[1, 2, 7], k=6) == [
        "a", "c", "c", "c", "c", "c",
    ]


def test_reseed_replays_stream():
    """Property: seed(s) restarts the identical stream, including from the
    middle of a block (block counter and buffer both reset). Breaks if the
    buffer or block count survives a reseed."""
    r = PhiloxRNG(5)
    first = [r.next_uint32() for _ in range(6)]
    r.seed(5)
    assert [r.next_uint32() for _ in range(6)] == first
    r.seed(5)
    r.next_uint32()  # leave a part-consumed block buffered
    r.seed(5)
    assert [r.next_uint32() for _ in range(6)] == first


def test_same_seed_same_stream_different_seed_different_stream():
    """Property: a seed fully determines the stream, and distinct seeds
    (including ones differing only in the high word) give distinct streams.
    Breaks if state leaks between instances or the high seed word is ignored."""
    a, b = PhiloxRNG(9), PhiloxRNG(9)
    assert [a.next_uint32() for _ in range(9)] == [b.next_uint32() for _ in range(9)]
    assert PhiloxRNG(9).next_uint32() != PhiloxRNG(9 + 2**32).next_uint32()


def test_randint_bounds_and_shuffle_permutation():
    """Property: randint(a, b) stays in [a, b] and reaches both ends;
    shuffle is a permutation. Breaks if a mapping goes out of range or drops
    or duplicates an element."""
    r = PhiloxRNG(1)
    draws = [r.randint(3, 5) for _ in range(200)]
    assert set(draws) == {3, 4, 5}
    assert all(r.randint(7, 7) == 7 for _ in range(10))

    lst = list(range(20))
    r.shuffle(lst)
    assert sorted(lst) == list(range(20))


def test_choices_honours_zero_weights():
    """Property: an item with weight 0 is never drawn. Breaks if the
    cumulative scan can select a zero-width slot."""
    r = PhiloxRNG(3)
    picks = r.choices(["a", "b", "c"], weights=[0, 5, 0], k=300)
    assert set(picks) == {"b"}
    picks = r.choices(["a", "b", "c"], weights=[3, 0, 1], k=300)
    assert "b" not in picks


def test_stream_exhaustion_raises_rather_than_wrap():
    """Property: after 2^32 blocks the generator raises instead of silently
    replaying block 0. Breaks if the counter is masked/wrapped."""
    r = PhiloxRNG(1)
    r._block = 2**32
    with pytest.raises(OverflowError):
        r.next_uint32()


def test_engine_world_is_frozen_across_versions():
    """A seeded world's fingerprint must never change silently -- scenario files
    depend on it (terrain is rebuilt from the stored seed + pinned params). If
    this test fails, a CHANGELOG entry and version bump are REQUIRED, and
    existing scenario terrain is invalidated.

    Property: GameEnvironment.reset(seed) draws its one mapgen master seed from
    the engine RNG (PhiloxRNG(seed).next_uint64()) and builds a world that is a
    pure function of it. Breaks if the RNG stream, the master-seed draw's
    position, or the engine's mapgen wiring changes.

    Re-baselined at the v0.9.0 Q0 migration (PCG32 -> philox32, #128): the
    master seed is now PhiloxRNG(42).next_uint64(), so this Duel earthlike
    world is a different world than the v0.6.0-ceremony one it replaced. The
    MapData golden (tests/test_mapgen_golden.py) calls the generator directly
    with seed 42 and so did NOT move. Params are passed pinned (P7's
    mapgen_params), so config knob tuning can never break this test -- only a
    genuine generator, RNG or engine-wiring change can.
    """
    from test_mapgen_golden import PINNED_PARAMS

    env = GameEnvironment(12, 24, num_players=2, map_type="earthlike",
                          mapgen_params=PINNED_PARAMS).reset(seed=42)
    m = env.map
    assert m.mapgen_params["seed"] == PhiloxRNG(42).next_uint64()
    assert [m.tiles[0, j].label for j in range(24)] == [
        "Ocean, Ice", "Ocean", "Ocean, Ice", "Ocean, Ice", "Ocean", "Ocean, Ice",
        "Ocean, Ice", "Ocean", "Ocean, Ice", "Ocean", "Coast", "Snow", "Snow",
        "Snow", "Snow", "Snow", "Snow", "Tundra", "Lake", "Lake", "Lake", "Lake",
        "Snow", "Coast, Ice",
    ], "seeded world changed -- scenario seeds are now invalid; bump version + CHANGELOG"
    assert [m.tiles[6, j].label for j in range(24)] == [
        "Ocean, Ice", "Ocean, Ice", "Ocean", "Ocean, Ice", "Coast, Ice",
        "Tundra (Hills)", "Snow (Mountain)", "Plains", "Tundra (Hills)",
        "Desert, Oasis", "Desert (Hills)", "Snow (Hills)", "Lake",
        "Snow (Mountain)", "Snow (Mountain)", "Snow (Hills)", "Desert",
        "Grassland, Woods", "Grassland", "Grassland", "Grassland (Mountain)",
        "Grassland (Hills)", "Coast", "Ocean, Ice",
    ]
    assert sorted(m.starts) == [(5, 6), (7, 19)]
    assert len(m.rivers) == 84
    assert sum(1 for i in range(12) for j in range(24) if m.tiles[i, j].resource) == 5
