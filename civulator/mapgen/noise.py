"""Periodic-lattice Perlin gradient noise (design doc §4.2, D9) — the only
noise source in mapgen (project CLAUDE.md canonical-systems rule, once
written). Fixes the pre-0.6 prototype's three compounding artifact sources
(§4.2 intro): value noise's axis-aligned bias, raw (q, r) sampling's 1.73x
ENE stretch (issue #13), and seam-blending (worst tiling technique).

The fix, in order:
  * Perlin GRADIENT noise (2002 scheme: hash -> fixed gradient table, quintic
    fade), not value noise.
  * Sampled at hex CARTESIAN centers (civulator.hexmath.hex_center: x = q +
    r/2, y = r*sqrt(3)/2) instead of raw (q, r) -- this is what makes the
    noise field isotropic on the hex grid instead of stretched.
  * Exact periodicity by PERIODIC LATTICE HASHING: the integer lattice
    x-coordinate is wrapped `mod P_k` *inside the hash itself* for every
    octave, so f(x) == f(x + width) for all real x -- no seam, no blending,
    no trig needed to detect "am I near the seam".

Every function here is vectorized over whatever numpy array shape the
caller passes for (x, y) -- there is no separate scalar code path, so the
single-point and whole-grid results can never disagree with each other.
Only elementwise numpy arithmetic is used (design doc §4.2.9: elementwise
ops are fine, reductions and libm transcendentals are not) -- octave/stage
loops are plain Python `for` loops of length 2-9 wrapping ONE vectorized
call each, never a per-tile Python loop.

Determinism (design doc §4.2 rules 7/9): integer hashing is exact by
construction (masked Python/numpy integer arithmetic only, wraps exactly
like C's uint32_t/uint64_t). The float layer (fade/lerp/gradient-dot) is
plain +,-,*,/ and `np.floor`/`np.mod` -- no pow/exp/log/cos/sin anywhere in
this module. `math.floor`-equivalent (`np.floor`) and modulo are exact
IEEE754 operations, not "transcendentals" in the platform-drift sense the
design doc rule 7 warns about.
"""

import numpy as np

from .seeding import mix64, octave_seed

_MASK32 = np.uint64(0xFFFFFFFF)
_MASK64 = np.uint64(0xFFFFFFFFFFFFFFFF)

# --- lowbias32 (Chris Wellons' "Hash Prospector" lowbias32; public domain) --
# The nested hash `hash(wrapped_ix + hash(iy + hash(octave_seed)))` (§4.2)
# calls this three times per lattice corner.

_LB_C1 = np.uint64(0x7FEB352D)
_LB_C2 = np.uint64(0x846CA68B)


def lowbias32(x):
    """32-bit avalanche hash, vectorized. `x`: python int or ndarray (any int
    dtype, any sign -- masked to 32 bits first via 2's-complement reinterpret).
    Returns an ndarray of dtype uint64 holding values in [0, 2**32)."""
    x = np.asarray(x)
    if x.dtype.kind == "i":  # signed: reinterpret negatives as 2's-complement uint64 first
        x = x.astype(np.int64).astype(np.uint64)
    else:
        x = x.astype(np.uint64)
    x = x & _MASK32
    x = (x ^ (x >> np.uint64(16))) & _MASK32
    x = (x * _LB_C1) & _MASK32
    x = (x ^ (x >> np.uint64(15))) & _MASK32
    x = (x * _LB_C2) & _MASK32
    x = (x ^ (x >> np.uint64(16))) & _MASK32
    return x


def _lattice_hash(wrapped_ix, iy, seed):
    """`hash(wrapped_ix + hash(iy + hash(octave_seed)))` (§4.2), vectorized.

    `wrapped_ix`, `iy`: int64 ndarrays (`wrapped_ix` already reduced mod
    P_k by the caller; `iy` is NOT wrapped -- rows never wrap, design doc
    §4.2/§4.3). `seed`: a python int (the octave seed from
    `seeding.octave_seed`, a full 64-bit mix64 output) -- truncated to its
    low 32 bits before entering this 32-bit hash chain. mix64's avalanche
    already mixes both halves of its output thoroughly, so the low 32 bits
    alone carry no less seed-dependent entropy than the full 64; this
    truncation is a documented interpretation of "hash(octave_seed)" (§4.2),
    which does not itself specify how a 64-bit seed enters a 32-bit hash.
    """
    seed32 = int(seed) & 0xFFFFFFFF
    h_seed = int(lowbias32(np.uint64(seed32))[()])  # scalar: hash(octave_seed)

    iy_u = iy.astype(np.int64).astype(np.uint64) & _MASK32
    h = lowbias32((iy_u + np.uint64(h_seed)) & _MASK32)  # hash(iy + hash(seed))

    ix_u = wrapped_ix.astype(np.int64).astype(np.uint64) & _MASK32
    h = lowbias32((ix_u + h) & _MASK32)  # hash(wrapped_ix + hash(iy + hash(seed)))
    return h


# --- fixed 2D gradient table (8 entries, integer -- no trig, §4.2.9) --------
# Perlin's own reference implementation does not normalize gradients either
# (D9: "2002 scheme"); using plain integer directions keeps this module
# transcendental-free even at "setup" (there is no setup step to speak of --
# these are literal constants) and bit-identical across platforms by
# construction, which a normalized (sqrt-involving) table would not be.
_GRAD_X = np.array([1, -1, 0, 0, 1, -1, 1, -1], dtype=np.float64)
_GRAD_Y = np.array([0, 0, 1, -1, 1, 1, -1, -1], dtype=np.float64)


def _fade(t):
    """Quintic fade (Perlin 2002): 6t^5 - 15t^4 + 10t^3. Pure polynomial."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def perlin2d(x, y, width, period, seed):
    """Periodic 2D Perlin gradient noise at hex-Cartesian (x, y) (design doc §4.2).

    `x`, `y`: ndarrays of any shape (broadcastable together), in hex-center
    units (civulator.hexmath.hex_center convention: x spans one world-wrap
    per `width` units; y is unwrapped). Real-valued and unbounded -- domain
    warp may push them outside [0, width) and this function handles that
    correctly (the wrap happens *inside* the hash on the lattice-space
    integer coordinate, not on the input).

    `width`: the map's column count -- the x-period in hex-center units
    (hexmath's convention). `period`: P_k, the integer number of lattice
    cells spanning one `width` (so periodicity in RESULT-space is exact:
    perlin2d(x, ...) == perlin2d(x + width, ...) for every real x, because
    `width` hex-center units always map to exactly `period` lattice cells,
    an integer, and the lattice hash wraps on exactly that integer).
    `seed`: this octave's seed (an int from `seeding.octave_seed`).

    Returns an ndarray the shape of (broadcast of) x, y. Values are not
    strictly bounded to [-1, 1] (unnormalized gradients, standard for this
    scheme) but are centered near zero and typically within it.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    # Wrap x into [0, width) BEFORE scaling to lattice space: x and x+k*width
    # must reach the exact same lattice cell/fraction bit-for-bit (design doc
    # §4.2's "periodicity holds for all real x" is an EXACT contract, tested
    # by tests/... noise periodicity). Scaling by period/width first and
    # relying on (x+width)*period/width == x*period/width + period would
    # only hold up to float rounding -- np.mod's IEEE754 remainder is exact,
    # so doing it first removes the width-multiple before any multiplication
    # can introduce drift. y is never wrapped (rows never wrap).
    x = np.mod(x, width)
    scale = period / width
    lx = x * scale
    ly = y * scale

    ix0f = np.floor(lx)
    iy0f = np.floor(ly)
    fx = lx - ix0f
    fy = ly - iy0f

    ix0 = ix0f.astype(np.int64)
    iy0 = iy0f.astype(np.int64)
    ix1 = ix0 + 1
    iy1 = iy0 + 1

    wix0 = np.mod(ix0, period)
    wix1 = np.mod(ix1, period)

    def grad_dot(wix, iy, dx, dy):
        h = _lattice_hash(wix, np.broadcast_to(iy, wix.shape), seed)
        idx = (h & np.uint64(7)).astype(np.int64)
        return _GRAD_X[idx] * dx + _GRAD_Y[idx] * dy

    n00 = grad_dot(wix0, iy0, fx, fy)
    n10 = grad_dot(wix1, iy0, fx - 1.0, fy)
    n01 = grad_dot(wix0, iy1, fx, fy - 1.0)
    n11 = grad_dot(wix1, iy1, fx - 1.0, fy - 1.0)

    u = _fade(fx)
    v = _fade(fy)

    nx0 = n00 + u * (n10 - n00)
    nx1 = n01 + u * (n11 - n01)
    return nx0 + v * (nx1 - nx0)


def fbm(x, y, width, seed, octaves, base_period, lacunarity=2, gain=0.5):
    """Fractal Brownian motion: sum of `octaves` Perlin layers (design doc §4.2).

    Per-octave integer period `P_k = base_period * lacunarity**k` (lacunarity
    exactly 2 per the design default; kept as a parameter since nothing in
    the math requires 2, callers should pass config's value). Amplitude
    halves each octave (`gain=0.5`, the fBm default). Each octave draws its
    own seed via `seeding.octave_seed(seed, k)` (§4.2 rule 1) -- octaves are
    independent noise fields, not phase-shifted copies of one field.

    `octaves`/`lacunarity`/`gain` are plain python ints/floats -- `**` here
    is called on small python ints at most `octaves` (<=9) times per call,
    not per-tile (this function IS the per-field call; the per-tile cost is
    the vectorized numpy work inside perlin2d) -- consistent with design doc
    §4.2.9's "no pow in the per-tile path" (the exponentiation happens once
    per octave per call, amortized over every tile in `x`/`y` at once).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    total = np.zeros(np.broadcast_shapes(x.shape, y.shape), dtype=np.float64)
    amplitude = 1.0
    period = base_period
    for k in range(octaves):
        total = total + amplitude * perlin2d(x, y, width, period, octave_seed(seed, k))
        amplitude *= gain
        period *= lacunarity
    return total


def ridged_spectral_weights(octaves, H=1.0, lacunarity=2):
    """Precompute `freq_k ** -H` for k in [0, octaves) (design doc §4.2.7).

    Called ONCE per ridged-noise field (setup), never per-tile -- the design
    doc explicitly carves this out ("spectral weights precomputed at stage
    setup... no pow in per-tile path"). With the default H=1.0/lacunarity=2,
    freq_k = 2**k and its reciprocal are exact powers of two -- exactly
    representable and exactly divided in IEEE754 on every platform, so even
    though this uses `**`, the DEFAULT-config result is still bit-exact
    cross-platform. Arbitrary H remains legal (the design doc's own
    allowance) but is then only as portable as `pow` is at setup time.
    """
    return [float(lacunarity) ** (-H * k) for k in range(octaves)]


def ridged_multifractal(x, y, width, seed, octaves, base_period,
                         offset=1.0, gain=2.0, H=1.0, lacunarity=2):
    """Musgrave ridged multifractal (design doc §4.3, §4.2.7).

    Per-octave: signal = (offset - |noise|)^2, then weighted by both (a) a
    gain-scaled carry-over of the PREVIOUS octave's signal (clamped to
    [0, 1] -- this is what gives ridged noise its connected ridge-line
    look, octaves near an existing ridge get amplified) and (b) the
    precomputed spectral weight `freq_k**-H`. Reference: Musgrave,
    "Texturing and Modeling: A Procedural Approach" -- this is the standard
    published algorithm, not a novel one.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    weights = ridged_spectral_weights(octaves, H=H, lacunarity=lacunarity)

    period = base_period
    n = perlin2d(x, y, width, period, octave_seed(seed, 0))
    signal = offset - np.abs(n)
    signal = signal * signal
    result = signal * weights[0]
    prev_signal = signal

    for k in range(1, octaves):
        period *= lacunarity
        w = np.clip(gain * prev_signal, 0.0, 1.0)
        n = perlin2d(x, y, width, period, octave_seed(seed, k))
        signal = offset - np.abs(n)
        signal = signal * signal
        signal = signal * w
        result = result + signal * weights[k]
        prev_signal = signal

    return result


def domain_warp(x, y, width, seed, amp, octaves, base_period=2, lacunarity=2, gain=0.5):
    """One-stage domain warp (design doc §4.3.1): displace (x, y) by two
    independent low-octave fBm fields before the caller samples "real" noise
    at the result. `seed` is split via mix64 into two channel seeds so dx
    and dy are decorrelated (not the same field twice).

    "warp field wraps identically" (§4.3.1): dx/dy are ordinary `fbm` calls
    using the SAME lattice-periodicity machinery as every other field, so
    sampling further noise at the warped point is exactly periodic in x —
    whatever calls `domain_warp` next and then samples noise at its output
    (every caller in elevation.py) sees `f(warp(x + width, y)) ==
    f(warp(x, y))` bit-for-bit.

    x is wrapped into [0, width) BEFORE adding the offset (not after) for
    the same reason `perlin2d` wraps before scaling: `x` and `x + width`
    must reach the identical warped point, and relying on
    `(x+width) + amp*dx == (x+amp*dx) + width` would only hold up to float
    rounding (addition is not perfectly associative) -- wrapping first
    removes the width-multiple before it can introduce that drift. The
    result is congruent to `x + amp*dx` mod width, which is all any
    downstream noise call (itself periodic mod width) can observe.

    Returns (x', y') = (wrap(x) + amp*dx, y + amp*dy).
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    seed_x = mix64(seed, 0)
    seed_y = mix64(seed, 1)
    dx = fbm(x, y, width, seed_x, octaves, base_period, lacunarity=lacunarity, gain=gain)
    dy = fbm(x, y, width, seed_y, octaves, base_period, lacunarity=lacunarity, gain=gain)
    return np.mod(x, width) + amp * dx, y + amp * dy
