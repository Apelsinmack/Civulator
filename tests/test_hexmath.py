"""Equivalence tests for civulator.hexmath (design doc §11 P1).

hexmath.distance / hexmath.adjacent_coords were lifted from the pre-0.6
civulator.game.map.Map.distance_function / Map.get_adjacent_coords, only
parameterized by width/rows instead of a bound self.m/self.n. This file
proves that lift is behavior-identical two ways:

1. Against a REFERENCE implementation copied verbatim from the pre-refactor
   Map methods (not imported from hexmath — an independent transcription, so
   this isn't just testing hexmath against itself).
2. Against the live Map.distance_function / Map.get_adjacent_coords, which
   now delegate to hexmath — proving the delegation wiring itself.
"""

import math
import random

import pytest

from civulator import hexmath
from civulator.game.map import Map
from civulator.game.map import HEX_DIRECTIONS as MAP_HEX_DIRECTIONS

# --- Reference implementation: verbatim transcription of the pre-0.6 Map methods ---

_REFERENCE_HEX_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def _reference_distance(p1, p2, width):
    """Copied verbatim from the pre-0.6 civulator.game.map.Map.distance_function."""
    dq_direct = p2[1] - p1[1]
    if dq_direct > 0:
        dq_wrapped = dq_direct - width
    else:
        dq_wrapped = dq_direct + width
    dq = dq_direct if abs(dq_direct) <= abs(dq_wrapped) else dq_wrapped

    dr = p2[0] - p1[0]
    return max(abs(dq), abs(dr), abs(dq + dr))


def _reference_adjacent_coords(coords, rows, width):
    """Copied verbatim from the pre-0.6 civulator.game.map.Map.get_adjacent_coords."""
    row, col = coords
    result = []
    for dr, dc in _REFERENCE_HEX_DIRECTIONS:
        new_row = row + dr
        new_col = (col + dc) % width
        if 0 <= new_row < rows:
            result.append((new_row, new_col))
    return result


# Map sizes to sweep: small/odd/tiny (stresses wrap), plus realistic sizes.
_SIZES = [(6, 6), (8, 16), (12, 24), (24, 48)]


def _random_pairs(rows, width, n, rng):
    pairs = []
    for _ in range(n):
        p1 = (rng.randrange(rows), rng.randrange(width))
        p2 = (rng.randrange(rows), rng.randrange(width))
        pairs.append((p1, p2))
    return pairs


class TestHexDirections:
    def test_matches_reference(self):
        assert hexmath.HEX_DIRECTIONS == _REFERENCE_HEX_DIRECTIONS

    def test_map_reexports_same_object(self):
        """civulator.agents.networks imports HEX_DIRECTIONS from civulator.game.map —
        must keep resolving to hexmath's list, not a second copy."""
        assert MAP_HEX_DIRECTIONS is hexmath.HEX_DIRECTIONS


class TestDistanceEquivalence:
    @pytest.mark.parametrize("rows,width", _SIZES)
    def test_matches_reference_random(self, rows, width):
        rng = random.Random(f"distance-{rows}-{width}")
        for p1, p2 in _random_pairs(rows, width, 50, rng):
            assert hexmath.distance(p1, p2, width) == _reference_distance(p1, p2, width)

    @pytest.mark.parametrize("rows,width", _SIZES)
    def test_matches_live_map(self, rows, width):
        m = Map(rows, width)
        rng = random.Random(f"distance-map-{rows}-{width}")
        for p1, p2 in _random_pairs(rows, width, 50, rng):
            assert hexmath.distance(p1, p2, width) == m.distance_function(p1, p2)

    def test_known_values(self):
        # Distance to self is zero.
        assert hexmath.distance((3, 3), (3, 3), 8) == 0
        # Each of the 6 axial neighbors is at distance 1.
        for dr, dc in hexmath.HEX_DIRECTIONS:
            assert hexmath.distance((5, 5), (5 + dr, 5 + dc), 16) == 1

    def test_wrap_shorter_than_direct(self):
        # width=8: column 0 to column 7 is distance 7 direct, but 1 via wrap.
        assert hexmath.distance((0, 0), (0, 7), 8) == 1
        assert hexmath.distance((0, 7), (0, 0), 8) == 1

    def test_no_wrap_on_rows(self):
        # Row axis never wraps — going "off the top" is not shortened.
        assert hexmath.distance((0, 0), (5, 0), 6) == 5


class TestAdjacentCoordsEquivalence:
    @pytest.mark.parametrize("rows,width", _SIZES)
    def test_matches_reference_random(self, rows, width):
        rng = random.Random(f"adjacent-{rows}-{width}")
        for coord in _random_pairs(rows, width, 50, rng):
            p = coord[0]  # reuse one of the pair as a single coordinate
            assert hexmath.adjacent_coords(p, rows, width) == _reference_adjacent_coords(
                p, rows, width
            )

    @pytest.mark.parametrize("rows,width", _SIZES)
    def test_matches_live_map(self, rows, width):
        m = Map(rows, width)
        rng = random.Random(f"adjacent-map-{rows}-{width}")
        for coord in _random_pairs(rows, width, 50, rng):
            p = coord[0]
            assert hexmath.adjacent_coords(p, rows, width) == m.get_adjacent_coords(p)

    def test_known_values_interior(self):
        # Interior tile: all 6 directions land in-bounds.
        assert hexmath.adjacent_coords((3, 3), 8, 16) == [
            (4, 3), (4, 2), (3, 2), (2, 3), (2, 4), (3, 4),
        ]

    def test_top_row_excludes_off_map_rows(self):
        # Row 0: directions with dr=-1 go off-map and are dropped (no row wrap).
        coords = hexmath.adjacent_coords((0, 3), 8, 16)
        assert all(0 <= r < 8 for r, c in coords)
        assert len(coords) == 4  # only the 4 directions with dr in {0, 1}

    def test_column_wraps(self):
        # Column wraps cylindrically: col 0's "west" neighbors land at width-1.
        coords = hexmath.adjacent_coords((3, 0), 8, 16)
        cols = {c for r, c in coords}
        assert 15 in cols  # (0, -1) % 16 == 15


class TestHexCenter:
    def test_origin(self):
        x, y = hexmath.hex_center((0, 0), 10)
        assert x == 0
        assert y == 0

    def test_row_offset_half_step(self):
        # row=1, col=0: x = (0 + 1/2) % width, y = sqrt(3)/2
        x, y = hexmath.hex_center((1, 0), 10)
        assert math.isclose(x, 0.5)
        assert math.isclose(y, math.sqrt(3) / 2)

    def test_wraps_to_width_period(self):
        # col=9 on a width-5 map: q + r/2 = 9, wrapped mod 5 == 4.
        x, y = hexmath.hex_center((0, 9), 5)
        assert math.isclose(x, 4.0)
        assert y == 0

    def test_x_always_in_period(self):
        rng = random.Random("hex-center-period")
        width = 24
        for _ in range(100):
            coords = (rng.randrange(-50, 50), rng.randrange(-50, 50))
            x, _ = hexmath.hex_center(coords, width)
            assert 0 <= x < width
