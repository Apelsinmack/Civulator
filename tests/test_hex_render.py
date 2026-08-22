"""Tests for civulator.viz.hex_render (design doc §11 P2b, §7.5).

Covers the §7.5 renderer re-projection — the exact pointy-top brick-rectangle
formulas (hex_to_pixel/pixel_to_hex) and the PERMANENT adjacency-render
invariant the old flat-top-on-raw-axial-indices renderer violated for ~17%
of neighbor pairs (§7.5: "would have caught the original bug") — plus
terrain-layer compositing (tile_color) and the river-edge shared-edge
geometry (river_edge_endpoints). Actual pyray drawing calls (draw_hex,
draw_resource_marker, draw_river_edges) need a live GL context and are
exercised by the P2b smoke test, not here (§11 P2b item 8) — everything
tested below is a pure function.
"""

import math
import random

import pytest
import pyray as rl

from civulator import terrain_model as tm
from civulator.game.map import Map
from civulator.game.tile import Tile
from civulator.rng import PortableRNG
from civulator.viz.hex_render import (
    hex_to_pixel,
    pixel_to_hex,
    river_edge_endpoints,
    tile_color,
    wrap_camera_x,
    wrap_period,
    wrapped_draw_x,
)

_SQRT3 = math.sqrt(3)
_SIZE = 10.0


# --- (a) permanent adjacency-render invariant (§7.5) ------------------------


class TestAdjacencyRenderInvariant:
    """Every engine-adjacent pair must render sqrt(3)*size apart (mod P in x).

    The exact invariant design doc §7.5 calls out as one that "would have
    caught the original bug": the pre-0.6 renderer drew a column-skewed
    offset layout directly on raw axial indices without converting,
    measured at ~17%/~17% of neighbor pairs rendering non-adjacent at these
    same two sizes (Duel 24x12, Colossal 106x66).
    """

    @pytest.mark.parametrize("cols,rows", [(24, 12), (106, 66)])
    def test_every_adjacent_pair_is_sqrt3_size_apart(self, cols, rows):
        m = Map(rows, cols, rng=PortableRNG(42))
        m.generate_map(map_type="basic")  # random map, per the P2b task spec
        period = wrap_period(_SIZE, cols)

        checked = 0
        for r in range(rows):
            for c in range(cols):
                x1, y1 = hex_to_pixel(r, c, _SIZE, cols)
                for (ar, ac) in m.get_adjacent_coords((r, c)):
                    x2, y2 = hex_to_pixel(ar, ac, _SIZE, cols)
                    direct = math.hypot(x2 - x1, y2 - y1)
                    plus = math.hypot(x2 + period - x1, y2 - y1)
                    minus = math.hypot(x2 - period - x1, y2 - y1)
                    d = min(direct, plus, minus)
                    assert d == pytest.approx(_SQRT3 * _SIZE, abs=1e-6)
                    checked += 1
        # Sanity that the double loop actually exercised the grid (6 neighbors
        # per interior tile, fewer on the row edges where there's no wrap).
        assert checked >= rows * cols * 4


# --- (b) pixel_to_hex round-trip --------------------------------------------


class TestPixelToHexRoundTrip:
    @pytest.mark.parametrize("cols,rows", [(24, 12), (8, 16), (106, 66)])
    def test_exact_centers_round_trip(self, cols, rows):
        """hex_to_pixel then pixel_to_hex recovers (row, col) for every tile."""
        for r in range(rows):
            for c in range(cols):
                x, y = hex_to_pixel(r, c, _SIZE, cols)
                assert pixel_to_hex(x, y, _SIZE, rows, cols) == (r, c)

    @pytest.mark.parametrize("cols,rows", [(24, 12), (106, 66)])
    def test_jittered_interior_points_round_trip(self, cols, rows):
        """+/- 0.4 * inradius jitter (P2b task spec) still resolves to the
        same hex -- proves the O(1) cube-rounding inverse, not just
        exact-center luck."""
        rng = random.Random(f"pixel-to-hex-jitter-{cols}-{rows}")
        inradius = _SIZE * _SQRT3 / 2  # apothem of a circumradius-_SIZE hex
        for _ in range(1000):
            r = rng.randrange(rows)
            c = rng.randrange(cols)
            x, y = hex_to_pixel(r, c, _SIZE, cols)
            jx = x + rng.uniform(-0.4, 0.4) * inradius
            jy = y + rng.uniform(-0.4, 0.4) * inradius
            assert pixel_to_hex(jx, jy, _SIZE, rows, cols) == (r, c)

    def test_off_map_row_returns_none(self):
        assert pixel_to_hex(-1000, -1000, _SIZE, 8, 16) == (None, None)

    def test_click_wraps_on_column(self):
        """A pixel just left of hex (r, 0)'s center must resolve via q % cols,
        not to a negative/None column -- clicks on the wrapped strip (§7.5)."""
        cols, rows = 16, 8
        x, y = hex_to_pixel(3, 0, _SIZE, cols)
        r, c = pixel_to_hex(x - _SIZE * 0.3, y, _SIZE, rows, cols)
        assert r == 3
        assert 0 <= c < cols


# --- camera-wrap helpers (§7.5 camera/seam policy) --------------------------


class TestCameraWrapHelpers:
    def test_wrap_camera_x_wraps_positive_overshoot(self):
        period = wrap_period(_SIZE, 20)
        camera = rl.Camera2D()
        camera.target = rl.Vector2(period * 2.3, 0)
        wrap_camera_x(camera, _SIZE, 20)
        assert 0 <= camera.target.x < period

    def test_wrap_camera_x_wraps_negative(self):
        period = wrap_period(_SIZE, 20)
        camera = rl.Camera2D()
        camera.target = rl.Vector2(-15, 0)
        wrap_camera_x(camera, _SIZE, 20)
        assert 0 <= camera.target.x < period

    def test_wrapped_draw_x_picks_the_nearest_copy(self):
        period = wrap_period(_SIZE, 20)
        x = 0.05 * period  # near the left edge of the canonical [0, P) strip
        camera_x = 1.5 * period  # camera has panned a period and a half over
        # x's own copy is 1.45P away; the +1 copy (x + period) is only 0.45P
        # away -- wrapped_draw_x must pick that shifted copy, not raw x.
        assert wrapped_draw_x(x, camera_x, _SIZE, 20) == pytest.approx(x + period)

    def test_wrapped_draw_x_leaves_x_when_already_nearest(self):
        period = wrap_period(_SIZE, 20)
        x = period / 2
        assert wrapped_draw_x(x, x + 3, _SIZE, 20) == pytest.approx(x)


# --- (c) terrain compositing -------------------------------------------------


class TestTileColor:
    def test_distinct_colors_for_representative_layers(self):
        """A representative sweep of base/relief/feature combos must not all
        collapse onto the same color -- a coarse check that compositing
        actually composites."""
        samples = [
            Tile(0, 0, "Grassland"),
            Tile(0, 0, "Plains"),
            Tile(0, 0, "Desert"),
            Tile(0, 0, "Tundra"),
            Tile(0, 0, "Snow"),
            Tile(0, 0, "Coast"),
            Tile(0, 0, "Lake"),
            Tile(0, 0, "Ocean"),
            Tile(0, 0, "Grassland", relief="hills"),
            Tile(0, 0, "Grassland", relief="mountain"),
            Tile(0, 0, "Grassland", feature="Woods"),
            Tile(0, 0, "Plains", feature="Rainforest"),
            Tile(0, 0, "Grassland", feature="Marsh"),
            Tile(0, 0, "Desert", feature="Floodplains"),
            Tile(0, 0, "Desert", feature="Oasis"),
            Tile(0, 0, "Coast", feature="Reef"),
            Tile(0, 0, "Coast", feature="Ice"),
        ]
        colors = [(c.r, c.g, c.b) for c in (tile_color(t) for t in samples)]
        assert len(set(colors)) == len(colors), colors

    def test_relief_and_feature_actually_change_the_base_color(self):
        flat = tile_color(Tile(0, 0, "Grassland"))
        hills = tile_color(Tile(0, 0, "Grassland", relief="hills"))
        mountain = tile_color(Tile(0, 0, "Grassland", relief="mountain"))
        woods = tile_color(Tile(0, 0, "Grassland", feature="Woods"))
        assert (flat.r, flat.g, flat.b) != (hills.r, hills.g, hills.b)
        assert (flat.r, flat.g, flat.b) != (mountain.r, mountain.g, mountain.b)
        assert (flat.r, flat.g, flat.b) != (woods.r, woods.g, woods.b)

    def test_never_raises_across_all_valid_layer_combinations(self):
        """Exhaustive sweep of base x relief x feature x resource, filtered to
        the combinations terrain_model.validate() actually accepts (the same
        `on`-matrix the generator and painter place through) -- tile_color
        must handle every one of them without raising."""
        checked = 0
        for base in tm.BASE_TABLE:
            for relief in tm.RELIEF_TABLE:
                for feature in list(tm.FEATURE_TABLE) + [None]:
                    for resource in list(tm.RESOURCE_TABLE) + [None]:
                        try:
                            tm.validate(base, relief=relief, feature=feature, resource=resource)
                        except ValueError:
                            continue
                        tile = Tile(0, 0, base, relief=relief, feature=feature, resource=resource)
                        color = tile_color(tile)
                        assert 0 <= color.r <= 255
                        assert 0 <= color.g <= 255
                        assert 0 <= color.b <= 255
                        assert color.a == 255
                        checked += 1
        assert checked > 20  # sanity: the enumeration actually found valid combos

    def test_unknown_base_terrain_falls_back_instead_of_raising(self):
        """Defensive fallback for a config typo -- never crash the render loop."""
        tile = Tile(0, 0, "Grassland")
        tile.base_terrain = "NotATerrain"  # bypass set_layers' validation on purpose
        color = tile_color(tile)
        assert isinstance(color.r, int)


# --- (d) river-edge primitive ------------------------------------------------


class TestRiverEdgeEndpoints:
    def test_segment_is_the_perpendicular_bisector_of_the_two_centers(self):
        """For every hex-adjacent pair on a small wrapped map (including ones
        straddling the column-wrap seam): the segment's own midpoint equals
        the midpoint of the two tiles' rendered centers (after k-shift
        normalization), its direction is perpendicular to the centers'
        connecting line, and its length equals the hex edge length (`size`,
        since a regular hexagon's edge length equals its circumradius)."""
        wrap_w, rows = 16, 8
        m = Map(rows, wrap_w)
        period = wrap_period(_SIZE, wrap_w)

        checked = 0
        for r in range(rows):
            for c in range(wrap_w):
                for (ar, ac) in m.get_adjacent_coords((r, c)):
                    (x1, y1), (x2, y2) = river_edge_endpoints((r, c), (ar, ac), _SIZE, wrap_w)

                    cx1, cy1 = hex_to_pixel(r, c, _SIZE, wrap_w)
                    cx2, cy2 = hex_to_pixel(ar, ac, _SIZE, wrap_w)
                    # Normalize tile2's center to the copy nearest tile1's --
                    # the same k-shift-nearest rule the primitive itself uses
                    # to handle pairs that straddle the seam.
                    cx2 = min((cx2 + k * period for k in (-1, 0, 1)), key=lambda x: abs(x - cx1))

                    seg_mid = ((x1 + x2) / 2, (y1 + y2) / 2)
                    centers_mid = ((cx1 + cx2) / 2, (cy1 + cy2) / 2)
                    assert seg_mid[0] == pytest.approx(centers_mid[0], abs=1e-9)
                    assert seg_mid[1] == pytest.approx(centers_mid[1], abs=1e-9)

                    seg_dx, seg_dy = x2 - x1, y2 - y1
                    ctr_dx, ctr_dy = cx2 - cx1, cy2 - cy1
                    dot = seg_dx * ctr_dx + seg_dy * ctr_dy  # 0 iff perpendicular
                    assert dot == pytest.approx(0, abs=1e-6)
                    assert math.hypot(seg_dx, seg_dy) == pytest.approx(_SIZE, abs=1e-9)
                    checked += 1
        assert checked >= rows * wrap_w * 4

    def test_hand_built_map_add_river_edges(self):
        """End-to-end with the real Map.add_river API (§7.5 item 4: 'unit-test
        with hand-added Map.add_river edges'), including one edge that
        straddles the column-wrap seam (col 0 <-> col wrap_w-1)."""
        wrap_w, rows = 10, 6
        m = Map(rows, wrap_w)
        m.add_river((2, 3), (2, 4))            # ordinary interior edge
        m.add_river((3, 0), (3, wrap_w - 1))    # seam-straddling edge

        assert len(m.rivers) == 2
        for coords1, coords2 in m.rivers:
            (x1, y1), (x2, y2) = river_edge_endpoints(coords1, coords2, _SIZE, wrap_w)
            # A short, well-defined segment -- not a spurious line stretching
            # across the map, which is what a naive (non-k-shifted) endpoint
            # computation would produce for the seam-straddling edge.
            assert math.hypot(x2 - x1, y2 - y1) == pytest.approx(_SIZE, abs=1e-9)
