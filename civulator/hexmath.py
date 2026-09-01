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

import numpy as np

# Axial hex directions — same for every tile, no even/odd branching.
HEX_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]

_SQRT3 = math.sqrt(3)


def distance(p1, p2, width):
    """Hex distance between two (row, col) points, cylindrical-wrapped on col.

    d = max(|dq|, |dr|, |dq + dr|), where dq picks whichever of the direct or
    wrapped column delta is shorter (the cylinder's q-axis wrap).

    Accepts scalars OR numpy arrays: each of p1/p2 is a (row, col) pair whose
    components may be ints or broadcastable ndarrays — e.g. a whole grid
    against one point, or grid x cities via broadcasting — returning the
    elementwise distances. The array branch mirrors the scalar comparisons
    exactly (tests/test_hexmath.py pins elementwise equality), and the
    scalar path is untouched pure Python so hot per-tile callers pay no
    numpy overhead.

    Args:
        p1, p2: (row, col) coordinate pairs (int or broadcastable ndarray
            components).
        width: number of columns in the map (the wrap period).
    """
    r1, q1 = p1[0], p1[1]
    r2, q2 = p2[0], p2[1]

    if any(isinstance(v, np.ndarray) for v in (r1, q1, r2, q2)):
        dq_direct = np.asarray(q2) - np.asarray(q1)
        dq_wrapped = np.where(dq_direct > 0, dq_direct - width, dq_direct + width)
        dq = np.where(np.abs(dq_direct) <= np.abs(dq_wrapped), dq_direct, dq_wrapped)
        dr = np.asarray(r2) - np.asarray(r1)
        return np.maximum(np.abs(dq), np.maximum(np.abs(dr), np.abs(dq + dr)))

    dq_direct = q2 - q1
    if dq_direct > 0:
        dq_wrapped = dq_direct - width
    else:
        dq_wrapped = dq_direct + width
    dq = dq_direct if abs(dq_direct) <= abs(dq_wrapped) else dq_wrapped

    dr = r2 - r1
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


def hex_rings(center, max_radius, rows, width):
    """[ring_0, ring_1, ..., ring_max_radius] -- (row, col) coordinates at
    EXACTLY hex distance k from `center`, for k = 0..max_radius. ring_0 is
    always `[center]`. Honors row bounds (no wrap: a ring near the top/bottom
    edge has fewer than the usual 6*k members) and column wrap (cylindrical,
    via `adjacent_coords`) — design doc §6 (start fertility rings) and P5's
    ring-2 warrior-spawn spillover both need exactly this shape.

    Computed by BFS layer-by-layer from `center` using ONLY `adjacent_coords`
    (never a hand-derived "6*k ring" formula, which would need its own
    boundary-clipping logic to stay correct near row edges) -- in an
    unweighted graph, BFS layer k IS the distance-k set, by construction, so
    this is correct near edges/wrap for free. Each ring is returned sorted
    by (row, col): a fixed, deterministic enumeration order (design doc
    §4.2 rule 6 "total sort keys everywhere") that callers needing a stable
    walk (fertility scoring, start normalization's fixed ring-1-then-ring-2
    search) can rely on without re-sorting.

    Args:
        center: (row, col) coordinate pair.
        max_radius: highest ring index to compute (>= 0).
        rows: number of rows in the map (no wrap on this axis).
        width: number of columns in the map (the wrap period).
    """
    rings = [[center]]
    visited = {center}
    frontier = [center]
    for _ in range(max_radius):
        next_frontier = []
        seen_this_layer = set()
        for tile in frontier:
            for neighbor in adjacent_coords(tile, rows, width):
                if neighbor not in visited and neighbor not in seen_this_layer:
                    seen_this_layer.add(neighbor)
                    next_frontier.append(neighbor)
        next_frontier.sort()
        rings.append(next_frontier)
        visited.update(next_frontier)
        frontier = next_frontier
    return rings


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
