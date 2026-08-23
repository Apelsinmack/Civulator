"""Deterministic integer seed mixing (design doc §4.2.1, §4.2 rule 1).

Every random-ish decision inside mapgen — which octave a noise sample belongs
to, which per-tile hash roll decides a feature — traces back to exactly ONE
external input: the `master_seed` uint64 that `civulator.rng.PortableRNG`
draws once at the engine boundary (`Map.generate_map`; see its module
docstring). From there, mapgen never touches PortableRNG or any other
stream-based RNG again — everything is pure integer mixing of
(master_seed, small integer id), which is what makes stage order and octave
order irrelevant to the result (D19/D20): mixing is a pure function, not a
draw from shared mutable state.

`mix64` is the splitmix64 FINALIZER (the scrambling half of splitmix64, not
its state-increment loop) applied to a base value that has been advanced by
`b` conceptual splitmix64 steps at once: splitmix64's generator advances
state by a fixed golden-ratio increment (`_GAMMA`) each call and finalizes
the result, so `state + b * _GAMMA` is exactly "the state after b calls",
and running the finalizer on it gives "the b-th output" in one step — this
is a real property of splitmix64, not an arbitrary combination. Addition
(mod 2**64) replaces XOR specifically because the design doc calls out XOR
as unsafe here (§4.2 rule 1): sequential seed sweeps (seed=1,2,3,...) XORed
against a small constant stage_id would preserve most of the input's bit
pattern in the output, giving adjacent seeds suspiciously related stage
seeds. Addition-then-finalize does not have that problem (the finalizer's
avalanche mixes the sum thoroughly).

Pure integer arithmetic throughout (masked to 64 bits after every op, the
same way C's uint64_t wraps) — no floats, no libm, fully portable to a
future C++ twin (design doc §4.2 rule 7/9, D22).
"""

_MASK64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15  # splitmix64's golden-ratio state increment
_C1 = 0xBF58476D1CE4E5B9
_C2 = 0x94D049BB133111EB


def mix64(a: int, b: int) -> int:
    """Deterministic 64-bit mix of two integers — the ONLY seed/hash primitive.

    `stage_seed = mix64(master_seed, stage_id)`; `octave_seed =
    mix64(stage_seed, octave_index)` (design doc §4.2.1). Also reused,
    chained, as the per-tile hash roll primitive (see `tile_roll01` below)
    and inside `noise.py`'s lattice hash.

    Both arguments are treated as arbitrary Python ints (may be negative or
    exceed 64 bits — masked to 64 bits before mixing), so callers never need
    to pre-mask coordinates or ids themselves.
    """
    z = (a + b * _GAMMA) & _MASK64
    z = ((z ^ (z >> 30)) * _C1) & _MASK64
    z = ((z ^ (z >> 27)) * _C2) & _MASK64
    z ^= z >> 31
    return z


def stage_seed(master_seed: int, stage_id: int) -> int:
    """Seed for one DAG stage (design doc §4.2 rule 1). `stage_id` from `STAGE_IDS`."""
    return mix64(master_seed, stage_id)


def octave_seed(stage_seed_: int, octave_index: int) -> int:
    """Seed for one octave within a stage (design doc §4.2 rule 1)."""
    return mix64(stage_seed_, octave_index)


def tile_roll01(stage_seed_: int, row: int, col: int, purpose_id: int) -> float:
    """Per-tile coordinate-hashed uniform float in [0, 1) (design doc §4.2 rule 3).

    `hash(stage_seed, r, q, purpose) < threshold` — every independent
    per-tile stochastic decision (feature chance, oasis, resource
    placement) reads this instead of drawing from a stream: order-free,
    insertion-stable, identical regardless of which tiles were visited
    first (D19). Chains `mix64` three times (row, then col, then purpose)
    the same way `noise.py`'s lattice hash nests hash(x + hash(y + hash(seed))).

    Exact division by 2**64 (a power of two) is exact in IEEE754 on every
    platform — no rounding-mode sensitivity.
    """
    h = mix64(stage_seed_, row)
    h = mix64(h, col)
    h = mix64(h, purpose_id)
    return h / 18446744073709551616.0  # 2**64


# --- Permanent stage/purpose id tables -------------------------------------
#
# Design doc §4.2 rule 1's pinned DAG order is documented here for reference;
# the actual DAG execution order lives in earthlike.py (Python already
# pins call order deterministically — these integers exist only so
# `mix64(master_seed, stage_id)` gives each stage an independent seed, not
# to encode ordering). IDs are permanent once assigned — never renumber or
# reuse one; append new stages (P4/P5: rivers, floodplains/oasis, resources,
# starts, river-moisture-bonus) at the next free integer. Renumbering would
# silently change every world generated from every seed.
STAGE_WARP = 0
STAGE_CONTINENTALNESS = 1
STAGE_OROGENY_MASK = 2
STAGE_RIDGED = 3
STAGE_MOISTURE = 4
STAGE_TEMPERATURE = 5
STAGE_FEATURES = 6
STAGE_BASIC_BASE = 7          # the "basic" generator's own per-tile base pick
STAGE_BASIC_FEATURES = 8      # the "basic" generator's own feature rolls
STAGE_RIVERS = 9              # P4: corner-junction altitude jitter (design doc §5)
STAGE_RESOURCES = 10          # P4: bonus resource placement (design doc §3.2, §11 P4)
# Next free id for P5: 11 (starts). Floodplains carries no randomness at all
# (design doc §5: "deterministic, no RNG") so it never needed a stage id;
# Oasis reuses STAGE_FEATURES (see PURPOSE_OASIS below) rather than taking
# a stage id of its own, per this table's own pre-existing reservation.

# Purpose ids for tile_roll01 within STAGE_FEATURES — permanent, same rule.
PURPOSE_WOODS = 0
PURPOSE_RAINFOREST = 1
PURPOSE_MARSH = 2
PURPOSE_ICE = 3
PURPOSE_REEF = 4
PURPOSE_OASIS = 5             # P4: oasis is a feature (§3), so it rolls in this stage too
# Next free id within STAGE_FEATURES: 6

# Purpose ids for tile_roll01 within STAGE_RIVERS — permanent, same rule.
# Two ids (not one): a junction's N-corner and S-corner jitter draws must be
# independent rolls, or every tile's N and S corner would jitter identically
# whenever they happened to share a (row, col) hash input coincidentally.
PURPOSE_JUNCTION_JITTER_N = 0
PURPOSE_JUNCTION_JITTER_S = 1
# Next free id within STAGE_RIVERS: 2

# Purpose ids for tile_roll01 within STAGE_RESOURCES — permanent, same rule.
# Order mirrors design doc §3.2's table and mapgen/resources.py's
# RESOURCE_ORDER exactly; append-only (see resources.py module docstring).
PURPOSE_RESOURCE_WHEAT = 0
PURPOSE_RESOURCE_RICE = 1
PURPOSE_RESOURCE_CATTLE = 2
PURPOSE_RESOURCE_SHEEP = 3
PURPOSE_RESOURCE_STONE = 4
PURPOSE_RESOURCE_DEER = 5
PURPOSE_RESOURCE_BANANAS = 6
PURPOSE_RESOURCE_FISH = 7
# Next free id within STAGE_RESOURCES: 8

# Purpose ids for tile_roll01 within STAGE_BASIC_FEATURES.
PURPOSE_BASIC_WOODS = 0
PURPOSE_BASIC_RAINFOREST = 1
