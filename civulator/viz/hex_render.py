"""Shared raylib hex-grid rendering helpers.

Extracted from scripts/watch.py and scripts/scenario_painter.py (GitHub issue
#27) — scenario_painter.py was originally forked from watch.py and had
re-implemented the same hex math and drawing code. This module is the single
home for that shared, tool-agnostic rendering code so future raylib-based
tools (e.g. the Order Recorder) can reuse it instead of forking it again.

Coordinate convention: axial (row, col) storage is unchanged, but the
PROJECTION is not (design doc §11 P2b, §7.5 amendment D24) — the pre-0.6
column-skewed "offset" grid rendered ~17% of neighbor pairs as visually
non-adjacent, a bug this patch fixes. The screen now shows a pointy-top
BRICK RECTANGLE: axial converted to odd-r offset, offset column taken mod
`wrap_w` — legal only because the map wraps on col (the cylinder quotient's
gauge freedom). `hex_to_pixel`/`pixel_to_hex` take the map's column count as
a required `wrap_w`/`cols` argument; passing the wrong value silently breaks
the adjacency-render invariant (tests/test_hex_render.py). Scrolling views
(watch.py) additionally need `wrap_camera_x`/`wrapped_draw_x` to handle the
column-wrap seam — see their docstrings.

This module may depend on pyray/numpy but must stay viz-only: it must never
be imported by civulator.game or civulator.agents, and must never import
torch.
"""

import math
import os

import pyray as rl

_S3 = math.sqrt(3)


# =====================================================================
# Projection (design doc §7.5, D24): axial (row, col) <-> pointy-top brick
# rectangle pixel coordinates. Storage stays axial; only the display changes.
# =====================================================================


def wrap_period(size, wrap_w):
    """World pixel width P = sqrt(3) * size * wrap_w (§7.5) — the column-wrap period.

    The single source of the period formula; shared by the camera-wrap
    helpers, the river-edge primitive, and their tests.
    """
    return _S3 * size * wrap_w


def hex_to_pixel(row, col, size, wrap_w):
    """Axial (row, col) -> pixel center on the pointy-top brick rectangle.

    Design doc §7.5 (D24) drop-in formula, used exactly as verified there:
    convert axial to odd-r offset (`col_off`), then odd-r-offset to
    pointy-top pixel. Taking `col_off % wrap_w` is what turns the true axial
    embedding (a parallelogram leaning across H/2 columns) into an on-screen
    RECTANGLE — legal only because the map wraps on col (the cylinder
    quotient's gauge freedom, §7.5 finding 1).

    `wrap_w` MUST be the map's column count (the same value passed to
    pixel_to_hex/Map.get_adjacent_coords as `cols`/`width`) — a mismatch
    silently breaks the adjacency-render invariant.
    """
    col_off = (col + (row - (row & 1)) // 2) % wrap_w
    x = _S3 * size * (col_off + 0.5 * (row & 1)) + _S3 * 0.5 * size
    y = 1.5 * size * row + size
    return x, y


def pixel_to_hex(px, py, size, rows, cols):
    """Pixel position -> axial (row, col). Exact O(1) inverse of hex_to_pixel.

    Design doc §7.5 (D24): fractional axial from the inverse pointy-top
    formula, cube rounding to the nearest hex, `q % cols` to resolve clicks
    on wrapped strips for free. Replaces the old per-frame O(rows*cols)
    nearest-hex-center scan.

    `cols` is the same wrap width hex_to_pixel calls `wrap_w`. Returns
    (None, None) if the picked row is off-map (rows never wrap).
    """
    x = px - _S3 * 0.5 * size
    y = py - size
    qf = (_S3 / 3 * x - y / 3) / size
    rf = (2 / 3 * y) / size
    sf = -qf - rf
    q, r, s_ = round(qf), round(rf), round(sf)
    dq, dr, ds = abs(q - qf), abs(r - rf), abs(s_ - sf)
    if dq > dr and dq > ds:
        q = -r - s_
    elif dr > ds:
        r = -q - s_
    return (r, q % cols) if 0 <= r < rows else (None, None)


def draw_hex(cx, cy, size, color):
    """Draw a filled hexagon at pixel center.

    Pointy-top vertices (§7.5: angle = 60*i + 30, was 60*i for the old
    flat-top art — sprites are unrotated centered icons, so no art changes).

    Fan winding (design doc §11 P3 finding, discovered by the mapgen
    preview CLI's smoke test): pyray/raylib 5.5's `draw_triangle` culls
    triangles with a positive (center, p[i], p[j]) signed area in screen
    pixel space (x right, y DOWN) — which every triangle in this fan has,
    since `points` walks strictly increasing angles (p[j] is always 60
    degrees further around than p[i]). The fill was silently invisible
    (only `draw_hex_outline`'s lines ever showed) in every tool that calls
    this — painter, recorder, watch, and the new mapgen preview — until the
    mapgen CLI's screenshot smoke test actually inspected a rendered image
    instead of only checking for "no exception". Passing (center, p[j],
    p[i]) — the reverse order — flips the sign and renders correctly;
    verified with a solid-fill screenshot before/after.
    """
    points = []
    for i in range(6):
        angle = math.radians(60 * i + 30)
        px = cx + size * math.cos(angle)
        py = cy + size * math.sin(angle)
        points.append((px, py))

    # Draw as triangles (fan from center) — (center, p[j], p[i]) order, not
    # (center, p[i], p[j]): see the winding note above.
    for i in range(6):
        j = (i + 1) % 6
        rl.draw_triangle(
            rl.Vector2(cx, cy),
            rl.Vector2(points[j][0], points[j][1]),
            rl.Vector2(points[i][0], points[i][1]),
            color,
        )


def draw_hex_outline(cx, cy, size, color):
    """Draw hex border (pointy-top vertices, §7.5: angle = 60*i + 30)."""
    for i in range(6):
        a1 = math.radians(60 * i + 30)
        a2 = math.radians(60 * (i + 1) + 30)
        rl.draw_line(
            int(cx + size * math.cos(a1)), int(cy + size * math.sin(a1)),
            int(cx + size * math.cos(a2)), int(cy + size * math.sin(a2)),
            color,
        )


def make_camera(map_rows, map_cols, hex_size, screen_w, screen_h, zoom=1.0):
    """Create a Camera2D centered on a hex map laid out via hex_to_pixel.

    Center = the true bounding-box midpoint of the pointy-top brick
    rectangle (§7.5 drop-in formula), not the old flat-top approximation
    (map_cols*size*0.75, map_rows*size*0.87 — numbers with no geometric
    meaning under the current projection).

    Both scripts built their Camera2D this way, differing only in the
    starting `zoom` (watch.py: 0.5, scenario_painter.py: 1.0) — callers pass
    their own value so behavior is unchanged.
    """
    camera = rl.Camera2D()
    center_x = (_S3 * hex_size * (map_cols + 0.5)) / 2
    center_y = (1.5 * hex_size * (map_rows - 1) + 2 * hex_size) / 2
    camera.target = rl.Vector2(center_x, center_y)
    camera.offset = rl.Vector2(screen_w / 2, screen_h / 2)
    camera.rotation = 0.0
    camera.zoom = zoom
    return camera


def update_camera_zoom_pan(camera, zoom_step=0.05, zoom_min=0.1, zoom_max=3.0):
    """Apply mouse-wheel zoom and right-mouse-drag pan to a hex-map camera.

    Both scripts implemented this identically apart from the zoom step/range
    constants (watch.py: step 0.05, range [0.1, 3.0]; scenario_painter.py:
    step 0.1, range [0.3, 3.0]) — callers pass their own values so behavior
    is unchanged.
    """
    wheel = rl.get_mouse_wheel_move()
    if wheel != 0:
        camera.zoom += wheel * zoom_step
        camera.zoom = max(zoom_min, min(camera.zoom, zoom_max))

    if rl.is_mouse_button_down(rl.MOUSE_BUTTON_RIGHT):
        delta = rl.get_mouse_delta()
        camera.target.x -= delta.x / camera.zoom
        camera.target.y -= delta.y / camera.zoom


# =====================================================================
# Camera-wrap helpers (§7.5 camera/seam policy): for SCROLLING views only
# (watch.py, the future mapgen preview CLI). Painter/recorder show the whole
# board at once and need none of this — "nothing special", per the doc.
# =====================================================================


def wrap_camera_x(camera, size, wrap_w):
    """Wrap camera.target.x into [0, P) after panning (§7.5 camera/seam policy).

    P = wrap_period(size, wrap_w). Call once per frame, after
    update_camera_zoom_pan, on a scrolling view — so panning past the seam
    re-enters from the other side instead of drifting into unmapped space.
    Mutates `camera` in place and also returns the wrapped value.
    """
    period = wrap_period(size, wrap_w)
    camera.target.x = camera.target.x % period
    return camera.target.x


def wrapped_draw_x(x, camera_x, size, wrap_w):
    """The k*P copy (k in {-1, 0, +1}) of a raw hex_to_pixel x nearest the camera.

    `x` is already in [0, P) (hex_to_pixel takes the offset column mod
    wrap_w internally). Scrolling views draw each tile/unit at this shifted
    x so tiles near the camera render in whichever copy is actually on
    screen (§7.5 camera/seam policy) — otherwise everything on the far side
    of the canonical [0, P) strip vanishes the moment the camera crosses the
    seam.

    ONE copy only, which is enough while the viewport is no wider than one
    wrap period; wider than that the world cannot tile the screen and the
    strip visibly jumps by P when the nearest-copy choice flips. Views that
    must stay continuous at any zoom use `wrap_copies_x` (issue #52).
    """
    period = wrap_period(size, wrap_w)
    best = x
    best_dist = abs(x - camera_x)
    for k in (-1, 1):
        shifted = x + k * period
        d = abs(shifted - camera_x)
        if d < best_dist:
            best_dist = d
            best = shifted
    return best


# A viewport wider than this many wrap periods is treated as a mistake rather
# than drawn: at that zoom the whole world is a few pixels wide, and the copy
# loop would grow without bound.
MAX_WRAP_COPIES = 64


def wrap_copies_x(x, camera_x, size, wrap_w, view_half_width):
    """EVERY k*P copy of a raw hex_to_pixel x that lands inside the viewport.

    The general form of `wrapped_draw_x` (issue #52): a scrolling view whose
    viewport is wider than one wrap period P needs the world drawn several
    times side by side, or a bare gap band appears and the map jumps by P
    when the nearest-copy choice flips. Drawing every visible copy makes
    east/west scrolling cycle continuously at any zoom.

    Args:
        x: raw x from `hex_to_pixel` (already in [0, P)).
        camera_x: `camera.target.x` — the world x at the camera's focus.
        size, wrap_w: as everywhere else (hex outer radius, map column count).
        view_half_width: half the visible world width, i.e.
            `screen_w / (2 * camera.zoom)`. One hex width of margin is added
            internally so tiles straddling the screen edge are not culled.

    Returns:
        list of x positions, nearest-first. Empty when the tile is off
        screen entirely — callers may treat that as free culling.
    """
    period = wrap_period(size, wrap_w)
    margin = _S3 * size
    half = view_half_width + margin
    k_lo = math.ceil((camera_x - half - x) / period)
    k_hi = math.floor((camera_x + half - x) / period)
    if k_hi - k_lo + 1 > MAX_WRAP_COPIES:
        # Absurd zoom-out: fall back to the single nearest copy rather than
        # emitting thousands of draws.
        return [wrapped_draw_x(x, camera_x, size, wrap_w)]
    copies = [x + k * period for k in range(k_lo, k_hi + 1)]
    copies.sort(key=lambda cx: abs(cx - camera_x))
    return copies


# =====================================================================
# Terrain compositing (design doc §7.5/P2b item 3): replaces the old flat
# TERRAIN_COLORS dict, which was keyed on the now-removed Tile.terrain_type.
# Hues are seeded from that dict plus the archived map_generator_prototype.py
# TERRAIN_COLORS (base + feature-overlay hex values) — reused in spirit, not
# copied verbatim, since neither table had a relief/feature COMPOSITING rule
# to lift.
# =====================================================================

# Base hue per base_terrain.
_BASE_COLORS = {
    "Grassland": (100, 180, 80),
    "Plains":    (180, 200, 100),
    "Desert":    (220, 200, 140),
    "Tundra":    (180, 200, 210),
    "Snow":      (240, 240, 250),
    "Coast":     (80, 140, 200),
    "Lake":      (60, 120, 190),
    "Ocean":     (40, 80, 160),
}
_FALLBACK_COLOR = (130, 130, 130)  # unknown base_terrain (config typo) -- not a crash

_HILLS_DARKEN = 0.85  # relief hills: darken ~15%
_MOUNTAIN_TINT = (110, 100, 95)
_MOUNTAIN_BLEND = 0.6  # relief mountain: strong shade, distinct from its base

# feature -> (tint RGB, blend fraction). Woods/Rainforest darken toward green;
# Marsh/Floodplains/Oasis/Reef/Ice each get their own distinct tint.
_FEATURE_TINTS = {
    "Woods":       ((40, 100, 40), 0.45),
    "Rainforest":  ((20, 90, 30), 0.60),
    "Marsh":       ((90, 110, 90), 0.50),
    "Floodplains": ((170, 195, 110), 0.40),
    "Oasis":       ((60, 170, 130), 0.55),
    "Reef":        ((60, 200, 190), 0.55),
    "Ice":         ((225, 240, 250), 0.60),
}

_RESOURCE_DOT_COLOR = rl.Color(255, 215, 60, 255)
_RESOURCE_DOT_OUTLINE = rl.Color(25, 20, 0, 220)


def _blend(rgb, target, amount):
    r, g, b = rgb
    tr, tg, tb = target
    return (r + (tr - r) * amount, g + (tg - g) * amount, b + (tb - b) * amount)


def _clamp255(v):
    return max(0, min(255, int(round(v))))


def tile_color(tile):
    """Composite fill color for one tile: base x relief x feature (§7.5 P2b).

    Replaces the old TERRAIN_COLORS.get(tile.terrain_type, ...) lookup —
    Tile.terrain_type is gone; this reads the composable layers directly.
    Resources are deliberately NOT folded in here (see draw_resource_marker):
    a resource is a small overlay glyph, not a base-color change, so the
    terrain underneath stays legible.

    Order: base hue -> relief modifier (hills darken ~15%; mountain shades
    strongly toward a distinct rock tone, regardless of base) -> feature
    tint (Woods/Rainforest darken toward green; Marsh/Floodplains/Oasis/
    Reef/Ice each a distinct tint). Never raises: an unrecognized layer
    value (e.g. a config typo) falls back to a neutral gray / leaves the
    color unmodified rather than crashing the render loop.

    Returns an rl.Color.
    """
    rgb = _BASE_COLORS.get(tile.base_terrain, _FALLBACK_COLOR)

    if tile.relief == "hills":
        rgb = tuple(c * _HILLS_DARKEN for c in rgb)
    elif tile.relief == "mountain":
        rgb = _blend(rgb, _MOUNTAIN_TINT, _MOUNTAIN_BLEND)

    if tile.feature is not None:
        tint = _FEATURE_TINTS.get(tile.feature)
        if tint is not None:
            rgb = _blend(rgb, tint[0], tint[1])

    r, g, b = (_clamp255(c) for c in rgb)
    return rl.Color(r, g, b, 255)


def draw_resource_marker(cx, cy, size, tile):
    """Small centered dot marking `tile.resource`, drawn after draw_hex (§7.5).

    A generic marker rather than per-resource art: 0.6 ships bonus-tier
    resources as gameplay content only (design doc §3.2) — distinguishing
    them visually per-resource is out of this patch's scope. No-op if the
    tile carries no resource.
    """
    if tile.resource is None:
        return
    radius = max(2.0, size * 0.16)
    rl.draw_circle(int(cx), int(cy), radius + 1, _RESOURCE_DOT_OUTLINE)
    rl.draw_circle(int(cx), int(cy), radius, _RESOURCE_DOT_COLOR)


# =====================================================================
# Start-position markers (design doc §11 P7.5): the mapgen preview CLI's
# own overlay for `MapData.starts` -- Erik inspects start fairness at the
# P8 ceremony, so these need to read as clearly distinct from a resource
# dot at a glance, not just on close inspection.
# =====================================================================

_START_RING_COLOR = rl.Color(255, 255, 255, 255)       # bold white ring
_START_RING_HOLE_COLOR = rl.Color(20, 20, 20, 235)      # near-black hole -> crisp ring silhouette
_START_FLAG_COLOR = rl.Color(230, 30, 40, 255)          # high-contrast red flag -- distinct from the gold resource dot


def draw_start_marker(cx, cy, size):
    """Bold ring + small flag marking one `MapData.starts` position (design
    doc §11 P7.5 preview CLI: "distinct markers... clearly different from
    the gold resource dots"). Deliberately much larger/bolder than
    `draw_resource_marker`'s small dot: a ring (rendered as a large filled
    circle with a near-black circle punched out of its center -- the same
    two-circle idiom `draw_resource_marker` already uses, so this adds no
    new draw_* primitive) plus a small flag on a pole above it.

    Triangle vertex winding matters here (see `draw_hex`'s docstring:
    raylib 5.5 silently culls the "wrong" winding instead of erroring) --
    the order below was confirmed visible with a standalone smoke-test
    render before landing here, the same way `draw_hex`'s own winding fix
    was originally found.
    """
    outer = max(3.0, size * 0.62)
    inner = max(1.5, size * 0.38)
    rl.draw_circle(int(cx), int(cy), outer, _START_RING_COLOR)
    rl.draw_circle(int(cx), int(cy), inner, _START_RING_HOLE_COLOR)

    ring_top = cy - outer
    flag_h = size * 0.9
    pole_top = ring_top - flag_h
    pole_bottom = ring_top - flag_h * 0.35
    rl.draw_line_ex(rl.Vector2(cx, cy), rl.Vector2(cx, pole_bottom), 2.0, _START_FLAG_COLOR)
    rl.draw_triangle(
        rl.Vector2(cx, pole_top),
        rl.Vector2(cx, pole_bottom),
        rl.Vector2(cx + size * 0.55, ring_top - flag_h * 0.65),
        _START_FLAG_COLOR,
    )


# =====================================================================
# River-edge primitive (design doc §5, §7.5 item 4). Rivers don't generate
# until patch P4 — this primitive is wired into painter/recorder/watch now
# so P4's rivers appear automatically; tests hand-build edges via
# Map.add_river.
# =====================================================================

RIVER_COLOR = rl.Color(70, 130, 220, 255)


def river_edge_endpoints(coords1, coords2, size, wrap_w):
    """Pixel endpoints of the segment along the shared edge of two adjacent tiles.

    `coords1`/`coords2` must be hex-adjacent (as returned by
    Map.get_adjacent_coords / stored in Map.rivers) — the shared-edge
    geometry assumes it. Two regular hexagons that share an edge have that
    edge centered at the midpoint of their rendered centers, perpendicular
    to the line between them, with length `size` (a regular hexagon's edge
    length equals its circumradius).

    Handles the column-wrap seam: picks whichever of the three k in
    {-1, 0, +1} P-shifted copies of tile2's center is nearest tile1's, so a
    river crossing the seam still renders as one short segment instead of a
    spurious line stretching across the map (same k-shift-nearest rule as
    wrapped_draw_x, §7.5 seam policy).

    Returns ((x1, y1), (x2, y2)).
    """
    cx1, cy1 = hex_to_pixel(coords1[0], coords1[1], size, wrap_w)
    cx2, cy2 = hex_to_pixel(coords2[0], coords2[1], size, wrap_w)
    cx2 = wrapped_draw_x(cx2, cx1, size, wrap_w)

    mx, my = (cx1 + cx2) / 2, (cy1 + cy2) / 2
    dx, dy = cx2 - cx1, cy2 - cy1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return (mx, my), (mx, my)
    ux, uy = dx / dist, dy / dist
    px, py = -uy, ux
    half = size / 2
    return (mx - px * half, my - py * half), (mx + px * half, my + py * half)


def draw_river_edges(map_obj, size, wrap_w, color=RIVER_COLOR, thickness=3.0,
                     camera_x=None, view_half_width=None):
    """Draw every Map.rivers edge as a segment along the tiles' shared edge (§7.5).

    `camera_x`, if given (scrolling views only), additionally shifts each
    drawn segment by whichever k*P copy lands nearest the camera — the same
    rule wrapped_draw_x applies to tiles, so a river near the seam renders
    in the copy actually on screen. Painter/recorder (fully visible boards)
    call this with `camera_x=None`.

    `view_half_width` (issue #52) switches to `wrap_copies_x`, drawing the
    segment in EVERY visible copy — required for continuous cycling scroll,
    and it must be passed wherever tiles are drawn that way, or rivers
    vanish from every copy but one.
    """
    for coords1, coords2 in map_obj.rivers:
        (x1, y1), (x2, y2) = river_edge_endpoints(coords1, coords2, size, wrap_w)
        if camera_x is None:
            rl.draw_line_ex(rl.Vector2(x1, y1), rl.Vector2(x2, y2), thickness, color)
            continue
        if view_half_width is None:
            shifts = [wrapped_draw_x(x1, camera_x, size, wrap_w) - x1]
        else:
            shifts = [cx - x1 for cx in
                      wrap_copies_x(x1, camera_x, size, wrap_w, view_half_width)]
        for shift in shifts:
            rl.draw_line_ex(rl.Vector2(x1 + shift, y1),
                            rl.Vector2(x2 + shift, y2), thickness, color)


def load_sprites(sprite_files, art_dir):
    """Load a {name: filename} map of PNGs from art_dir into raylib textures.

    Filenames that don't exist under art_dir are silently skipped (as in
    scenario_painter.py's original PainterState.load_sprites), so callers
    should fall back to a non-sprite drawing path for missing entries.
    """
    sprites = {}
    for name, filename in sprite_files.items():
        path = os.path.join(art_dir, filename)
        if os.path.exists(path):
            sprites[name] = rl.load_texture(path.encode())
    return sprites


def unload_sprites(sprites):
    """Unload every texture in a {name: texture} map returned by load_sprites."""
    for tex in sprites.values():
        rl.unload_texture(tex)
