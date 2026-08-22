"""Pure hex geometry kernels — axial (q, r) coordinates on a cylindrical map.

No imports from civulator.game, civulator.agents, or civulator.viz: this module
is imported by both the engine (civulator.game.map.Map delegates to it) and by
the future civulator.mapgen package, which cannot import game/ at all (design
doc docs/terrain_model_design.md, §0 decision E1). Coordinates are (row, col)
tuples throughout, matching the engine's storage convention: row = r, col = q
(project CLAUDE.md: "Axial (q, r) coordinates only, stored as (row=r, col=q)").

Distance = max(|dq|, |dr|, |dq + dr|) with cylindrical wrapping on q (columns).

The functions here are lifted verbatim from the pre-0.6 civulator.game.map.Map
methods of the same purpose (HEX_DIRECTIONS, distance_function,
get_adjacent_coords) — parameterized by `width`/`rows` instead of a bound
`self.m`/`self.n` so they have no dependency on Map. Behavior is unchanged;
see tests/test_hexmath.py for the equivalence proof against the original Map
formulas.
"""

import math

# Axial hex directions — same for every tile, no even/odd branching.
HEX_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]

_SQRT3 = math.sqrt(3)


def distance(p1, p2, width):
    """Hex distance between two (row, col) points, cylindrical-wrapped on col.

    d = max(|dq|, |dr|, |dq + dr|), where dq picks whichever of the direct or
    wrapped column delta is shorter (the cylinder's q-axis wrap).

    Args:
        p1, p2: (row, col) coordinate pairs.
        width: number of columns in the map (the wrap period).
    """
    dq_direct = p2[1] - p1[1]
    if dq_direct > 0:
        dq_wrapped = dq_direct - width
    else:
        dq_wrapped = dq_direct + width
    dq = dq_direct if abs(dq_direct) <= abs(dq_wrapped) else dq_wrapped

    dr = p2[0] - p1[0]
    return max(abs(dq), abs(dr), abs(dq + dr))


def adjacent_coords(coords, rows, width):
    """Coordinates of all adjacent tiles (axial hex + cylindrical wrap on col).

    Off the top/bottom row edge is excluded (no wrap on rows); off the
    left/right column edge wraps via modulo `width`.

    Args:
        coords: (row, col) coordinate pair.
        rows: number of rows in the map (no wrap on this axis).
        width: number of columns in the map (the wrap period).
    """
    row, col = coords
    result = []
    for dr, dc in HEX_DIRECTIONS:
        new_row = row + dr
        new_col = (col + dc) % width
        if 0 <= new_row < rows:
            result.append((new_row, new_col))
    return result


def hex_center(coords, width):
    """Axial-to-Cartesian center of a hex, for periodic-lattice sampling.

    x = q + r/2, wrapped to [0, width); y = r * sqrt(3)/2 (design doc §4.2,
    §7.5). q is the column, r is the row (coords = (row, col) = (r, q)).
    Consumed by the future noise pipeline (mapgen) and renderer; nothing in
    P1 calls it yet.

    Args:
        coords: (row, col) coordinate pair.
        width: number of columns in the map (the x-period).

    Returns:
        (x, y) tuple of floats.
    """
    row, col = coords
    r, q = row, col
    x = (q + r / 2) % width
    y = r * _SQRT3 / 2
    return x, y
