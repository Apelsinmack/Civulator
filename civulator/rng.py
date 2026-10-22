"""Engine RNG — Philox-4x32-10 through the shared `philox32` kit (issue #128, Q0).

Replaces the PCG32 generator of issue #33. The block function is the kit's
`philox32_4x32_10` (Salmon et al., SC'11; gated by the kit on Random123's
known-answer vectors), whose C++/CUDA twin is `philox32.h` -- so a C++ or CUDA
subsystem draws the exact same words from the same seed without a port. This
file's *documented* stream layout and derived draws are the contract that
twin implements; tests/test_rng.py freezes them.

Stream layout (the kit's recommended one, specialised to one sequential stream):

    seed        = 64-bit unsigned integer (seed & (2^64 - 1))
    key         = (seed_lo, seed_hi)           = (seed & 0xFFFFFFFF, seed >> 32)
    counter     = (block, 0, STREAM_SALT, 0)   block = blocks drawn so far, from 0
    block words = philox32_4x32_10(counter, key)   -> four uint32 words w0..w3
    next_uint32() pops w0, w1, w2, w3 of block 0, then of block 1, ...
    seed(s)     resets block = 0 and drops the buffered words
    unseeded    construction takes the seed from os.urandom(8)

`block` is a uint32 counter word: one generator yields 2^34 words, after
which it raises rather than wrap and silently replay its own stream.

Derived draws (every one is a pure function of the word stream; none rejects
and redraws, so the number of words consumed never depends on the value):

    random()      = next_uint32() / 2^32             (32-bit resolution floats)
    randint(a,b)  = a + philox32_below(next_uint32(), b - a + 1)
                    where philox32_below(w, n) = (w * n) >> 32  (Lemire
                    multiply-shift; no modulo; ONE word per call)
    uniform(a,b)  = a + (b - a) * random()
    shuffle       = Fisher-Yates from the top: for i in len-1..1: j=randint(0,i)
    choices       = r = random() * total_weight, linear cumulative scan
                    (weights=None: population[randint(0, len-1)] per pick)
    next_uint64() = (next_uint32() << 32) | next_uint32()   (two words, high then low)

STREAM_SALT is the counter word that names this stream within the kit's
layout (the role `_SEQUENCE = 54` played for PCG32). Change it only with a
CHANGELOG entry: it moves every seeded world, roll and shuffle.
"""

import os

from philox32 import philox32_4x32_10, philox32_below

_MASK32 = 0xFFFFFFFF
_MASK64 = (1 << 64) - 1
STREAM_SALT = 0xC1171A70  # fixed stream selector; change only with a CHANGELOG entry
_WORDS_PER_BLOCK = 4


class PhiloxRNG:
    """Drop-in replacement for the subset of random.Random the engine uses."""

    def __init__(self, seed=None):
        self.seed(seed)

    def seed(self, seed=None):
        if seed is None:
            seed = int.from_bytes(os.urandom(8), "little")
        seed &= _MASK64
        self._key = (seed & _MASK32, seed >> 32)
        self._block = 0       # blocks drawn so far == the next counter value
        self._buffer = ()     # the current block's words
        self._buffer_pos = _WORDS_PER_BLOCK  # all popped: first draw refills

    def next_uint32(self):
        """Next uint32 of the stream (the contract's one primitive)."""
        if self._buffer_pos == _WORDS_PER_BLOCK:
            if self._block > _MASK32:
                raise OverflowError(
                    "PhiloxRNG stream exhausted (2^32 blocks drawn); reseed")
            self._buffer = philox32_4x32_10(
                (self._block, 0, STREAM_SALT, 0), self._key)
            self._block += 1
            self._buffer_pos = 0
        word = self._buffer[self._buffer_pos]
        self._buffer_pos += 1
        return word

    # --- Derived draws (specs in the module docstring; keep in sync with C++) ---

    def random(self):
        """Float in [0, 1) with 32-bit resolution."""
        return self.next_uint32() / 4294967296.0

    def next_uint64(self):
        """64-bit unsigned integer: two 32-bit draws, high bits first.

        The engine's ONE documented draw for the mapgen master seed (design
        doc §4.2.1, §11 P3): `Map.generate_map` calls this exactly once per
        map built, handing the result to `civulator.mapgen.generate` as its
        `seed` argument. Everything downstream of that point (stage seeds,
        octave seeds, per-tile hash rolls) is pure `mapgen.seeding.mix64`
        mixing of that one integer -- the engine RNG is never touched again
        during world synthesis.
        """
        high = self.next_uint32()
        low = self.next_uint32()
        return (high << 32) | low

    def uniform(self, a, b):
        return a + (b - a) * self.random()

    def randint(self, a, b):
        """Integer in [a, b] inclusive, like random.randint. One word."""
        return a + philox32_below(self.next_uint32(), b - a + 1)

    def shuffle(self, seq):
        for i in range(len(seq) - 1, 0, -1):
            j = self.randint(0, i)
            seq[i], seq[j] = seq[j], seq[i]

    def choices(self, population, weights=None, k=1):
        """Weighted sampling with replacement, like random.choices."""
        if weights is None:
            return [population[self.randint(0, len(population) - 1)] for _ in range(k)]
        total = float(sum(weights))
        result = []
        for _ in range(k):
            r = self.random() * total
            acc = 0.0
            pick = population[-1]  # guard against float edge at r == total
            for item, w in zip(population, weights):
                acc += w
                if r < acc:
                    pick = item
                    break
            result.append(pick)
        return result


# One release, then removed (with a CHANGELOG line): call sites still import
# the old name.
PortableRNG = PhiloxRNG
