"""Tests for civulator.mapgen.noise (design doc §4.2, D9, §11 P3).

Exact periodicity is THE property issue #13 needed and the pre-0.6
prototype's seam-blending never gave (design doc §4.2: "no seam, no trig"):
f(x) must equal f(x + width) bit-for-bit, not merely "close", for every
octave and at odd widths — periodic-lattice hashing is either exact or it
has a seam.
"""

import math

import numpy as np
import pytest

from civulator import hexmath
from civulator.mapgen import noise, seeding

SEED = seeding.mix64(20260822, 1)

# Realistic sample coordinates: half-integer hex centers over several rows,
# spanning multiple copies of the world width in both directions — this is
# the actual coordinate convention (civulator.hexmath.hex_center) mapgen
# samples at, not arbitrary floats (see this file's own note on why
# non-half-integer test inputs are the wrong thing to assert bit-exactness
# against: floating point addition of an irrational-valued x is not exact
# to begin with, regardless of what noise.py does with it).
def _hex_grid(width, rows=9, col_span=2):
    qs = np.arange(-col_span * width, col_span * width)
    rs = np.arange(-rows, rows + 1)
    Q, R = np.meshgrid(qs, rs)
    x = Q + R / 2.0
    y = R * math.sqrt(3) / 2.0
    return x, y


WIDTHS = [24, 48, 17, 5, 3, 106]  # includes odd (17, 5, 3) and the two live map widths


class TestPerlin2dPeriodicity:
    @pytest.mark.parametrize("width", WIDTHS)
    @pytest.mark.parametrize("k_widths", [1, 2, 3, -1, -2])
    def test_exact_periodicity_single_octave(self, width, k_widths):
        x, y = _hex_grid(width)
        a = noise.perlin2d(x, y, width, period=4, seed=SEED)
        b = noise.perlin2d(x + k_widths * width, y, width, period=4, seed=SEED)
        assert np.array_equal(a, b)

    @pytest.mark.parametrize("width", WIDTHS)
    def test_exact_periodicity_never_wraps_y(self, width):
        """Rows never wrap (design doc §4.2/§4.3) — shifting y by the map's
        height must NOT reproduce the same field (a real, if weak, check
        that periodicity is x-only, not accidentally biaxial)."""
        x, y = _hex_grid(width, rows=6)
        a = noise.perlin2d(x, y, width, period=4, seed=SEED)
        b = noise.perlin2d(x, y + 1000.0, width, period=4, seed=SEED)
        assert not np.array_equal(a, b)


class TestFbmAndRidgedPeriodicity:
    @pytest.mark.parametrize("width", WIDTHS)
    @pytest.mark.parametrize("octaves", [1, 3, 6])
    def test_fbm_exact_periodicity_every_octave_count(self, width, octaves):
        x, y = _hex_grid(width)
        a = noise.fbm(x, y, width, SEED, octaves, base_period=3)
        b = noise.fbm(x + width, y, width, SEED, octaves, base_period=3)
        assert np.array_equal(a, b)

    @pytest.mark.parametrize("width", WIDTHS)
    def test_ridged_multifractal_exact_periodicity(self, width):
        x, y = _hex_grid(width)
        a = noise.ridged_multifractal(x, y, width, SEED, octaves=5, base_period=3)
        b = noise.ridged_multifractal(x + 2 * width, y, width, SEED, octaves=5, base_period=3)
        assert np.array_equal(a, b)

    @pytest.mark.parametrize("width", WIDTHS)
    def test_sampling_noise_at_the_warped_point_is_exactly_periodic(self, width):
        """design doc §4.3.1: "warp field wraps identically" — the property
        that actually matters (every real caller, elevation.py, immediately
        samples further noise at domain_warp's output): a noise field
        sampled at warp(x + width, y) equals the same field sampled at
        warp(x, y), bit-for-bit. (domain_warp's own raw (x', y') output is
        only guaranteed congruent mod width, not literally offset by
        (width, 0) — (a+b)+c vs (a+c)+b can differ by a float rounding ULP,
        so asserting exact "+width" on the raw warped coordinate would be
        testing float-addition associativity, not periodicity.)
        """
        x, y = _hex_grid(width)
        wx, wy = noise.domain_warp(x, y, width, SEED, amp=4.0, octaves=3)
        wx2, wy2 = noise.domain_warp(x + width, y, width, SEED, amp=4.0, octaves=3)

        sample_seed = seeding.mix64(SEED, 99)
        a = noise.perlin2d(wx, wy, width, period=5, seed=sample_seed)
        b = noise.perlin2d(wx2, wy2, width, period=5, seed=sample_seed)
        assert np.array_equal(a, b)


class TestContinuityAcrossTheSeam:
    """No jump discontinuity exactly at the wrap boundary (design doc §4.2:
    "no seam" — as opposed to seam-BLENDING, which papers over a real jump).
    Small steps in x must produce small steps in the field, including steps
    that straddle x=0/x=width.
    """

    @pytest.mark.parametrize("width", [24, 17, 48])
    def test_small_steps_across_the_seam_give_small_deltas(self, width):
        eps = 1e-4
        y = np.array([0.0, 3 * math.sqrt(3) / 2])
        for base_x in (0.0, width):  # the seam sits at every integer multiple of width
            x_minus = np.array([base_x - eps, base_x - eps])
            x_plus = np.array([base_x + eps, base_x + eps])
            f_minus = noise.fbm(x_minus, y, width, SEED, octaves=4, base_period=3)
            f_plus = noise.fbm(x_plus, y, width, SEED, octaves=4, base_period=3)
            assert np.all(np.abs(f_plus - f_minus) < 0.01), (
                f"width={width}: noise jumps by more than a step-sized amount across the seam"
            )


class TestHexCoordsMatchHexmath:
    """`earthlike._hex_coords` is a vectorized mirror of
    `civulator.hexmath.hex_center` (design doc §4.2: "hex-center sampling ...
    from hexmath") — this pins the two to agree instead of trusting a
    comment. x is compared mod width since `_hex_coords` deliberately
    doesn't pre-wrap (perlin2d wraps internally; hex_center does it eagerly)
    — both describe the same point on the cylinder.
    """

    @pytest.mark.parametrize("rows,cols", [(12, 24), (24, 48), (16, 17)])
    def test_matches_hexmath_hex_center(self, rows, cols):
        from civulator.mapgen.earthlike import _hex_coords

        x, y = _hex_coords(rows, cols)
        rng_points = [(r, c) for r in (0, rows // 2, rows - 1) for c in (0, cols // 3, cols - 1)]
        for r, c in rng_points:
            expected_x, expected_y = hexmath.hex_center((r, c), cols)
            assert math.isclose(x[r, c] % cols, expected_x, abs_tol=1e-9)
            assert math.isclose(y[r, c], expected_y, abs_tol=1e-9)
