"""The one landmass definition (v0.9.0 Q6, docs/districts_religion_design.md
"v2 fixes" B8): a landmass is a connected component of LAND-DOMAIN tiles
under canonical hex adjacency with cylindrical wrap.

Pure: numpy + `civulator.hexmath` + `civulator.terrain_model`. Mapgen's
region division (`starts.divide_into_regions`) and the engine's
`Map.landmass_id` (sea trade's overseas test) both call `find_landmasses`;
there is no second definition. Land membership is DOMAIN, not passability or
settleability -- a mountain occupies space inside a continent and can bridge
two grassland areas into one landmass (terrain design §3: domain separates
land from water; impassable is an orthogonal flag).
"""

import numpy as np

from .. import hexmath
from ..terrain_model import BASE_TABLE


def find_landmasses(base_terrain, rows, cols):
    """List of landmasses: each a sorted list of (row, col) land tiles
    (design doc §6.2: "connected land component; hexmath adjacency with
    wrap"). Flood fill (BFS). The list is ordered by each component's first
    tile in row-major scan, so index == a stable landmass id for a given
    grid; the CALLER (`starts.divide_into_regions`) imposes its own
    fertility-based processing order -- finding components has no natural
    "player order" of its own.
    """
    domain_land = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            domain_land[r, c] = BASE_TABLE.get(base_terrain[r, c], {}).get("domain") == "land"

    visited = np.zeros((rows, cols), dtype=bool)
    landmasses = []
    for r in range(rows):
        for c in range(cols):
            if not domain_land[r, c] or visited[r, c]:
                continue
            component = []
            stack = [(r, c)]
            visited[r, c] = True
            while stack:
                tr, tc = stack.pop()
                component.append((tr, tc))
                for nr, nc in hexmath.adjacent_coords((tr, tc), rows, cols):
                    if domain_land[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            component.sort()
            landmasses.append(component)
    return landmasses
