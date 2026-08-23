"""Map-quality metrics (design doc §4.1, §10, Systems (b)): every §10
map-quality oracle measures through this module rather than each test
reinventing its own metric. Diagnostic/measurement code, not generation —
unlike noise.py/elevation.py/climate.py/features.py/earthlike.py/basic.py,
this module is NOT held to the §4.2.9 FP discipline (no reductions/
transcendentals): a metric doesn't affect what world gets generated, only
reports on one already generated, so `np.mean`/`np.corrcoef`/etc. are fine
here — nothing here needs to be bit-portable to a future C++ twin (only
`MapData`'s fingerprint does, per D22).
"""

import numpy as np

from .. import hexmath

WATER_BASES = ("Coast", "Lake", "Ocean")

# The three hex axis directions (design doc §10: "+q, +r, +(q-r) in axial,
# computed via hexmath"), as (delta_row, delta_col) pairs picked from
# hexmath.HEX_DIRECTIONS (project convention: coords are (row, col) =
# (r, q)). Each is one direction of an opposite pair; autocorrelation
# along a direction and its opposite are the same statistic, so only one
# per axis is needed. Verified against HEX_DIRECTIONS' cube-coordinate
# deltas (Δs = -Δq-Δr): (0,1)/(0,-1) have Δr=0 ("+q" axis, s and r both
# constant-ish... concretely r fixed); (1,0)/(-1,0) have Δq=0 ("+r" axis);
# (-1,1)/(1,-1) have Δs=0, i.e. q-r changes by ±2 while s is fixed ("+(q-r)"
# axis) — the third axis design doc §10 names explicitly.
HEX_AXES = {
    "+q": (0, 1),
    "+r": (1, 0),
    "+(q-r)": (-1, 1),
}


def is_land_mask(base_terrain: np.ndarray) -> np.ndarray:
    """(rows, cols) bool: True where `base_terrain` is a land base (not one
    of Coast/Lake/Ocean). Convenience shared by every stats function below.
    """
    return ~np.isin(base_terrain, WATER_BASES)


def _directional_autocorrelation(field: np.ndarray, direction) -> float:
    """Pearson correlation between `field` and its lag-1 neighbor in
    `direction` (a (delta_row, delta_col) pair), over every tile pair where
    both ends are in-bounds (design doc §10 isotropy metric). Column wrap
    via `np.roll` (matches the cylinder); row edges (no wrap) are excluded
    rather than letting `np.roll` wrap them.
    """
    field = np.asarray(field, dtype=np.float64)
    rows, cols = field.shape
    dr, dc = direction
    neighbor = np.roll(field, shift=(-dr, -dc), axis=(0, 1))

    valid = np.ones((rows, cols), dtype=bool)
    if dr > 0:
        valid[rows - dr:, :] = False
    elif dr < 0:
        valid[: -dr, :] = False

    a = field[valid]
    b = neighbor[valid]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 1.0  # degenerate (constant field): treat as perfectly self-similar
    return float(np.corrcoef(a, b)[0, 1])


def isotropy_ratio(field: np.ndarray):
    """(max_pairwise_ratio, {axis_name: |autocorrelation|}) (design doc §10):
    directional autocorrelation of `field` along the three hex axes, and
    the ratio of the largest to the smallest |correlation|. Near 1.0 means
    isotropic (no directional bias); large means anisotropic — the exact
    signature issue #13's raw-(q,r) sampling produced (~1.73x/sqrt(3)
    stretch along one diagonal). `field` is typically a land/water bool
    grid or a continuous elevation-like field — this function only cares
    that it is a (rows, cols) array of numbers.
    """
    field = np.asarray(field, dtype=np.float64)
    correlations = {
        name: abs(_directional_autocorrelation(field, direction))
        for name, direction in HEX_AXES.items()
    }
    values = list(correlations.values())
    lo = min(values)
    ratio = (max(values) / lo) if lo > 1e-9 else float("inf")
    return ratio, correlations


def terrain_mix_fractions(map_data) -> dict:
    """Land/water/mountain/hill fractions (design doc §10 "terrain mix"):
    mountain/hill are reported AS FRACTIONS OF LAND (matching how
    `land_percent`/`mountain_percent`/`hill_percent` are defined, design
    doc §4.3), alongside the raw counts nearest-rank exactness tests
    compare against (`round(fraction * land_count)`).
    """
    base = map_data.base_terrain
    relief = map_data.relief
    rows, cols = base.shape
    total = rows * cols

    is_land = is_land_mask(base)
    land_count = int(is_land.sum())
    mountain_count = int(np.sum((relief == "mountain") & is_land))
    hill_count = int(np.sum((relief == "hills") & is_land))

    return {
        "total": total,
        "land_count": land_count,
        "land_fraction": land_count / total,
        "water_fraction": (total - land_count) / total,
        "mountain_count": mountain_count,
        "hill_count": hill_count,
        "mountain_fraction_of_land": (mountain_count / land_count) if land_count else 0.0,
        "hill_fraction_of_land": (hill_count / land_count) if land_count else 0.0,
    }


def climate_band_rows(rows: int, band_rows: int = None):
    """(polar_rows, equatorial_rows) index lists (design doc §10 "climate"
    oracle). `band_rows` defaults to `max(1, rows // 6)`, a bandwidth that
    scales with map size instead of a fixed row count. Poles are the top+
    bottom `band_rows` rows (design doc §4.4: both edges are cold); the
    equator is the middle `band_rows` rows.
    """
    band = band_rows if band_rows is not None else max(1, rows // 6)
    polar_rows = list(range(0, band)) + list(range(max(0, rows - band), rows))
    mid = (rows - 1) / 2.0
    half = max(1, band // 2)
    lo = max(0, int(round(mid - half)))
    hi = min(rows - 1, int(round(mid + half)))
    equatorial_rows = list(range(lo, hi + 1))
    return polar_rows, equatorial_rows


def climate_band_terrains(map_data, band_rows: int = None) -> dict:
    """{"polar": {base_terrain,...}, "equatorial": {...}, "polar_rows": [...],
    "equatorial_rows": [...]} (design doc §10 "climate" oracle): the
    distinct base terrains seen in the polar vs equatorial row bands (see
    `climate_band_rows`) of one generated world.
    """
    base = map_data.base_terrain
    rows, cols = base.shape
    polar_rows, equatorial_rows = climate_band_rows(rows, band_rows)

    polar = {base[r, c] for r in polar_rows for c in range(cols)}
    equatorial = {base[r, c] for r in equatorial_rows for c in range(cols)}
    return {
        "polar": polar,
        "equatorial": equatorial,
        "polar_rows": polar_rows,
        "equatorial_rows": equatorial_rows,
    }
