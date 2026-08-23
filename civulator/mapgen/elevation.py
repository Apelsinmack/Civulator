"""Elevation pipeline (design doc §4.3, D10): warp -> continentalness +
orogeny_mask x ridged -> talus smoothing -> nearest-rank thresholds ->
water classification (Coast/Lake/Ocean) -> relief.

    warp field (1 stage, periodic)
        |-> continentalness fBm (2-3 big features)
        |-> ridged multifractal (mountain field)
        |-> orogeny mask (low-freq, nearest-rank)
    E = continentalness + mountain_amp * orogeny_mask * ridged
    E -> talus smoothing (3 synchronous Jacobi iterations)
    E -> nearest-rank thresholds: sea level (land_percent of whole map),
         mountain/hill (percent OF LAND, cumulative)
    water tiles -> Coast (>=1 land neighbor) / Lake (connected component
         size <= lake_max_size) / Ocean, via order-independent flood fill
"""

import numpy as np

from .. import hexmath
from .noise import domain_warp, fbm, ridged_multifractal
from .ranking import nearest_rank_threshold, round_log2
from .seeding import STAGE_CONTINENTALNESS, STAGE_OROGENY_MASK, STAGE_RIDGED, STAGE_WARP, stage_seed

# The orogeny mask is deliberately low-frequency by construction (design doc
# §4.3: "orogeny mask: low-freq") -- a small, fixed octave count rather than
# a config knob, since "low-freq" is closer to an algorithmic property of
# what an orogeny mask IS (a few broad belt regions) than a tunable detail
# level. `mountain_wavelength` (config) still controls ITS scale.
_OROGENY_OCTAVES = 2


def resolve_octaves(width: int, octaves_param) -> int:
    """`clamp(round(log2(width)) - 2, 3, 9)` when `octaves_param == "auto"`
    (design doc §4.3: "Musgrave: useful octaves = log2(width) - 2"),
    else the given int verbatim. Pure integer arithmetic (`ranking.round_log2`)
    -- no `math.log2` anywhere (design doc §4.2.9 FP discipline).
    """
    if octaves_param == "auto":
        return max(3, min(9, round_log2(width) - 2))
    return int(octaves_param)


def compute_raw_elevation(x: np.ndarray, y: np.ndarray, width: int, master_seed: int, p: dict) -> np.ndarray:
    """E, BEFORE talus smoothing: warp -> continentalness + amp*orogeny*ridged.

    `x`, `y`: (rows, cols) hex-center coordinate arrays (civulator.hexmath
    convention). `p`: resolved earthlike params (see earthlike.py
    DEFAULT_PARAMS for every key read here).
    """
    warp_seed = stage_seed(master_seed, STAGE_WARP)
    wx, wy = domain_warp(x, y, width, warp_seed, amp=p["warp_amp"], octaves=p["warp_octaves"])

    octaves = resolve_octaves(width, p["octaves"])

    cont_seed = stage_seed(master_seed, STAGE_CONTINENTALNESS)
    continentalness = fbm(wx, wy, width, cont_seed, octaves, p["continent_wavelength"])

    ridged_seed = stage_seed(master_seed, STAGE_RIDGED)
    ridged = ridged_multifractal(wx, wy, width, ridged_seed, octaves, p["continent_wavelength"])

    orogeny_seed = stage_seed(master_seed, STAGE_OROGENY_MASK)
    orogeny_field = fbm(wx, wy, width, orogeny_seed, _OROGENY_OCTAVES, p["mountain_wavelength"])
    orogeny_cut = nearest_rank_threshold(
        orogeny_field, np.ones_like(orogeny_field, dtype=bool), p["mountain_belt_percent"]
    )
    orogeny_mask = (orogeny_field >= orogeny_cut).astype(np.float64)

    return continentalness + p["mountain_amp"] * orogeny_mask * ridged


def talus_smooth(elevation: np.ndarray, iterations: int, talus_slope: float, diffusion_coeff: float) -> np.ndarray:
    """3 (or `iterations`) synchronous Jacobi passes (design doc §4.2 rule 5):
    every tile whose neighbor differs by more than `talus_slope` diffuses
    a `diffusion_coeff` share of the excess toward that neighbor, all read
    from the SAME snapshot and written to a fresh grid each pass (never
    reads a value another tile already updated this pass).

    Neighbor sums are in `hexmath.HEX_DIRECTIONS`' fixed order (design doc
    "pinned-order neighbor sums"). Column wrap via `np.roll` (exact, matches
    the cylinder); row edges (which never wrap) are masked out of the sum
    rather than letting `np.roll` silently wrap them too.
    """
    rows, cols = elevation.shape
    current = elevation.astype(np.float64).copy()
    for _ in range(iterations):
        delta = np.zeros_like(current)
        for dr, dc in hexmath.HEX_DIRECTIONS:
            neighbor = np.roll(current, shift=(-dr, -dc), axis=(0, 1))
            valid = np.ones((rows, cols), dtype=bool)
            if dr > 0:
                valid[rows - dr:, :] = False
            elif dr < 0:
                valid[: -dr, :] = False

            diff = neighbor - current
            excess = np.where(diff > talus_slope, diff - talus_slope, 0.0)
            excess = np.where(diff < -talus_slope, diff + talus_slope, excess)
            delta += np.where(valid, diffusion_coeff * excess, 0.0)
        current = current + delta
    return current


def classify_land_and_relief(elevation: np.ndarray, land_percent: float,
                              mountain_percent: float, hill_percent: float):
    """(is_land, relief_grid, sea_level) via nearest-rank thresholds
    (design doc §4.3: sea level is `land_percent` OF THE WHOLE MAP;
    mountain/hill percents are OF LAND).

    Mountain and hill cuts come from ONE ranking of land-tile elevations
    with cumulative fractions (mountain_percent, then
    mountain_percent+hill_percent) rather than re-ranking a shrunk subset
    after removing mountains -- so "hill_percent of land" means exactly
    that (a fixed fraction of ALL land), not "of land that isn't already
    mountain". This is a documented interpretation: the design doc gives
    both percents as independent "of land" fractions without spelling out
    whether they're cumulative or of a shrinking pool; cumulative-from-one-
    ranking is what makes both readings agree.
    """
    rows, cols = elevation.shape
    whole = np.ones((rows, cols), dtype=bool)
    sea_level = nearest_rank_threshold(elevation, whole, land_percent)
    is_land = elevation >= sea_level

    relief = np.full((rows, cols), "flat", dtype=object)
    if np.any(is_land):
        mountain_cut = nearest_rank_threshold(elevation, is_land, mountain_percent)
        hill_cut = nearest_rank_threshold(elevation, is_land, mountain_percent + hill_percent)
        is_mountain = is_land & (elevation >= mountain_cut)
        is_hill = is_land & ~is_mountain & (elevation >= hill_cut)
        relief[is_mountain] = "mountain"
        relief[is_hill] = "hills"

    return is_land, relief, sea_level


def _water_components(is_water: np.ndarray):
    """Connected components of water tiles (6-connectivity, hexmath
    adjacency, cylindrical col wrap) as a list of [(row, col), ...] lists.
    Plain BFS flood fill: membership is a property of the graph, not of
    traversal order (design doc §4.3: "flood fill -- component-based,
    order-independent") -- which tile a component's scan happens to start
    from never changes which tiles end up in it.
    """
    rows, cols = is_water.shape
    visited = np.zeros((rows, cols), dtype=bool)
    components = []
    for r in range(rows):
        for c in range(cols):
            if not is_water[r, c] or visited[r, c]:
                continue
            comp = []
            stack = [(r, c)]
            visited[r, c] = True
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nb in hexmath.adjacent_coords(cur, rows, cols):
                    nr, nc = nb
                    if is_water[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        stack.append(nb)
            components.append(comp)
    return components


def classify_water(is_land: np.ndarray, lake_max_size: int) -> np.ndarray:
    """(rows, cols) object array, None on land, else "Coast"/"Lake"/"Ocean"
    (design doc §4.3): Lake = connected water component with
    <= lake_max_size tiles; Coast = any other water tile with >= 1 land
    neighbor; Ocean = the rest. An all-land world (is_land all True)
    returns an all-None grid with zero Coast/Ocean/Lake tiles, by
    construction (no water tiles to classify) -- design doc §11 P3 test (g).
    """
    rows, cols = is_land.shape
    is_water = ~is_land
    base = np.full((rows, cols), None, dtype=object)

    for comp in _water_components(is_water):
        if len(comp) <= lake_max_size:
            for (r, c) in comp:
                base[r, c] = "Lake"
        else:
            for (r, c) in comp:
                has_land_neighbor = any(
                    is_land[nr, nc] for nr, nc in hexmath.adjacent_coords((r, c), rows, cols)
                )
                base[r, c] = "Coast" if has_land_neighbor else "Ocean"

    return base
