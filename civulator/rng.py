"""Portable deterministic RNG — identical streams reproducible in C++ (issue #33).

Replaces random.Random (Mersenne Twister) inside the engine so that ported C++
subsystems can draw the exact same random stream from the same seed. The
algorithm is PCG-XSH-RR 64/32, O'Neill's minimal reference pcg32:

    step:   state' = state * 6364136223846793005 + inc          (mod 2^64)
    output (from the PRE-step state):
            xorshifted = ((state >> 18) ^ state) >> 27          (32-bit)
            rot        = state >> 59
            out        = rotr32(xorshifted, rot)

    seeding (initstate=seed, initseq=SEQUENCE):
            state = 0; inc = (initseq << 1) | 1; step(); state += seed; step()

The C++ twin must implement this file's *documented* derived draws too:
    random()      = next_uint32() / 2^32            (32-bit resolution floats)
    randint(a,b)  = a + next_uint32() % (b - a + 1) (modulo; bias accepted)
    uniform(a,b)  = a + (b - a) * random()
    shuffle       = Fisher-Yates from the top: for i in len-1..1: j=randint(0,i)
    choices       = r = random() * total_weight, linear cumulative scan
    next_uint64() = (next_uint32() << 32) | next_uint32()   (two draws, high then low)

tests/test_rng.py freezes golden output vectors — the C++ twin is correct when
it reproduces them bit-for-bit.
"""

import os

_MASK64 = (1 << 64) - 1
_MULT = 6364136223846793005
_SEQUENCE = 54  # fixed stream selector; change only with a CHANGELOG entry


class PortableRNG:
    """Drop-in replacement for the subset of random.Random the engine uses."""

    def __init__(self, seed=None):
        self.seed(seed)

    def seed(self, seed=None):
        if seed is None:
            seed = int.from_bytes(os.urandom(8), "little")
        self._state = 0
        self._inc = ((_SEQUENCE << 1) | 1) & _MASK64
        self._next_uint32()
        self._state = (self._state + (seed & _MASK64)) & _MASK64
        self._next_uint32()

    def _next_uint32(self):
        oldstate = self._state
        self._state = (oldstate * _MULT + self._inc) & _MASK64
        xorshifted = (((oldstate >> 18) ^ oldstate) >> 27) & 0xFFFFFFFF
        rot = oldstate >> 59
        return ((xorshifted >> rot) | (xorshifted << ((-rot) & 31))) & 0xFFFFFFFF

    # --- Derived draws (specs in the module docstring; keep in sync with C++) ---

    def random(self):
        """Float in [0, 1) with 32-bit resolution."""
        return self._next_uint32() / 4294967296.0

    def next_uint64(self):
        """64-bit unsigned integer: two 32-bit draws, high bits first.

        The engine's ONE documented draw for the mapgen master seed (design
        doc §4.2.1, §11 P3): `Map.generate_map` calls this exactly once per
        map built, handing the result to `civulator.mapgen.generate` as its
        `seed` argument. Everything downstream of that point (stage seeds,
        octave seeds, per-tile hash rolls) is pure `mapgen.seeding.mix64`
        mixing of that one integer — PortableRNG is never touched again
        during world synthesis.
        """
        high = self._next_uint32()
        low = self._next_uint32()
        return (high << 32) | low

    def uniform(self, a, b):
        return a + (b - a) * self.random()

    def randint(self, a, b):
        """Integer in [a, b] inclusive, like random.randint."""
        return a + self._next_uint32() % (b - a + 1)

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
