"""Shared raylib hex-grid rendering helpers.

Extracted from scripts/watch.py and scripts/scenario_painter.py (GitHub issue
#27) — scenario_painter.py was originally forked from watch.py and had
re-implemented the same hex math and drawing code. This module is the single
home for that shared, tool-agnostic rendering code so future raylib-based
tools (e.g. the Order Recorder) can reuse it instead of forking it again.

Coordinate convention (unchanged from the original scripts, do not "fix"):
axial hex coordinates stored as (row, col), rendered on a column-skewed
("offset") pixel grid via hex_to_pixel/pixel_to_hex below.

This module may depend on pyray/numpy but must stay viz-only: it must never
be imported by civulator.game or civulator.agents, and must never import
torch.
"""

import math
import os

import pyray as rl


# Terrain fill colors, keyed by Tile.terrain_type. Identical in both source
# scripts prior to extraction (no divergence to reconcile).
TERRAIN_COLORS = {
    "Plains":      rl.Color(180, 200, 100, 255),
    "Grassland":   rl.Color(100, 180, 80, 255),
    "Desert":      rl.Color(220, 200, 140, 255),
    "Tundra":      rl.Color(180, 200, 210, 255),
    "Snow":        rl.Color(240, 240, 250, 255),
    "Hills":       rl.Color(140, 160, 90, 255),
    "Woods":       rl.Color(60, 120, 50, 255),
    "Rainforest":  rl.Color(30, 100, 40, 255),
    "Marsh":       rl.Color(100, 130, 100, 255),
    "Floodplains": rl.Color(160, 190, 100, 255),
    "Mountain":    rl.Color(120, 110, 100, 255),
    "Ocean":       rl.Color(40, 80, 160, 255),
    "Coast":       rl.Color(80, 140, 200, 255),
    "Lake":        rl.Color(60, 120, 190, 255),
}


def hex_to_pixel(row, col, size):
    """Convert axial hex (row, col) to pixel center, with offset for skewed grid."""
    w = size * 2
    h = size * math.sqrt(3)
    x = col * w * 0.75 + size
    y = row * h + (col % 2) * h * 0.5 + size
    return x, y


def pixel_to_hex(px, py, size, rows, cols):
    """Find the hex (row, col) whose center is closest to a pixel position.

    Brute-force nearest-center search over the full grid (O(rows*cols)), as
    in the original scenario_painter.py implementation. `rows`/`cols` bound
    the search to the caller's map size (watch.py had no equivalent function
    since it never needed pixel->hex picking).

    Returns (None, None) if no hex center is reasonably close to (px, py).
    """
    best_r, best_c = 0, 0
    best_dist = float("inf")
    for r in range(rows):
        for c in range(cols):
            cx, cy = hex_to_pixel(r, c, size)
            d = (px - cx) ** 2 + (py - cy) ** 2
            if d < best_dist:
                best_dist = d
                best_r, best_c = r, c
    # Only match if reasonably close
    if best_dist < (size * size * 1.5):
        return best_r, best_c
    return None, None


def draw_hex(cx, cy, size, color):
    """Draw a filled hexagon at pixel center."""
    points = []
    for i in range(6):
        angle = math.radians(60 * i)
        px = cx + size * math.cos(angle)
        py = cy + size * math.sin(angle)
        points.append((px, py))

    # Draw as triangles (fan from center)
    for i in range(6):
        j = (i + 1) % 6
        rl.draw_triangle(
            rl.Vector2(cx, cy),
            rl.Vector2(points[i][0], points[i][1]),
            rl.Vector2(points[j][0], points[j][1]),
            color,
        )


def draw_hex_outline(cx, cy, size, color):
    """Draw hex border."""
    for i in range(6):
        a1 = math.radians(60 * i)
        a2 = math.radians(60 * (i + 1))
        rl.draw_line(
            int(cx + size * math.cos(a1)), int(cy + size * math.sin(a1)),
            int(cx + size * math.cos(a2)), int(cy + size * math.sin(a2)),
            color,
        )


def make_camera(map_rows, map_cols, hex_size, screen_w, screen_h, zoom=1.0):
    """Create a Camera2D centered on a hex map laid out via hex_to_pixel.

    Both scripts built their Camera2D this way, differing only in the
    starting `zoom` (watch.py: 0.5, scenario_painter.py: 1.0) — callers pass
    their own value so behavior is unchanged.
    """
    camera = rl.Camera2D()
    camera.target = rl.Vector2(map_cols * hex_size * 0.75, map_rows * hex_size * 0.87)
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
