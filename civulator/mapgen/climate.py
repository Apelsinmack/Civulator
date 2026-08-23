"""Temperature, moisture, and biome classification (design doc §4.4, D11).

    temperature = latitude curve (+1.2 equator -> -1.2 poles)
                  - elevation lapse
                  + low-frequency coherent wobble
    moisture    = low-frequency fBm (+ inert river bonus stub, P4 fills it)
    biome       = smoothed-field Whittaker (temperature x moisture), nearest-
                  rank percentile thresholds, one synchronous majority-filter
                  pass as the speckle safety net

"Smoothed-field" (§4.4) is read here as a property of the INPUT fields
(temperature/moisture are already low-frequency fBm/wobble -- few octaves,
coarse wavelength -- so the classification boundaries are inherently smooth
curves, not per-tile noise) rather than a separate blur step; the majority
filter is the explicit per-tile cleanup pass design doc rule 5 already
names. This is a documented interpretation, consistent with how
terrain_model.py documents its own non-literal readings of the design doc.
"""

import numpy as np

from .. import hexmath
from .noise import fbm
from .ranking import percentile_rank_field
from .seeding import STAGE_MOISTURE, STAGE_TEMPERATURE, stage_seed

# Canonical order for majority-vote tie-breaking (design doc §4.2 rule 6:
# "total sort keys everywhere") -- fixed and arbitrary-but-permanent, NOT
# derived from dict/Counter insertion order (which is a CPython guarantee,
# not something a future C++ twin can be expected to replicate the same way).
LAND_BASE_ORDER = ("Grassland", "Plains", "Desert", "Tundra", "Snow")

# Low-frequency by construction (design doc §4.4: "low-frequency coherent
# wobble"; "band boundaries meander" -- a handful of broad waves, not fine
# detail) -- a fixed small octave count rather than a config knob, the same
# reasoning as elevation.py's orogeny-mask octave count.
_TEMP_WOBBLE_OCTAVES = 3


def compute_temperature(x: np.ndarray, y: np.ndarray, width: int, master_seed: int,
                         elevation: np.ndarray, sea_level: float, p: dict) -> np.ndarray:
    """Latitude curve - elevation lapse + coherent wobble (design doc §4.4).

    The equator-peaked latitude curve avoids `cos` (banned in the
    deterministic path, design doc §4.2.9) via a quadratic ease instead: a
    smooth "hot at the equator, cold at both poles" shape built from
    `1 - t**2`, `t` = normalized distance from the middle row, exactly
    hitting the documented +1.2/-1.2 endpoints at the equator/poles.

    Row 0 and the last row are always the two poles (both cold): a
    rectangular map here represents equator-to-both-poles top-to-bottom,
    matching a Mercator-style world map, not a single pole-to-pole strip.
    """
    rows = x.shape[0]
    row_idx = np.arange(rows, dtype=np.float64).reshape(-1, 1)
    equator = (rows - 1) / 2.0
    half = equator if rows > 1 else 1.0
    t = np.abs(row_idx - equator) / half
    shaped = 1.0 - t * t
    latitude_curve = np.broadcast_to(-1.2 + 2.4 * shaped, x.shape)

    lapse = p["temp_lapse_rate"] * np.maximum(0.0, elevation - sea_level)

    wobble_seed = stage_seed(master_seed, STAGE_TEMPERATURE)
    wobble = fbm(x, y, width, wobble_seed, _TEMP_WOBBLE_OCTAVES, p["temp_wobble_wavelength"])

    return latitude_curve - lapse + p["temp_wobble_amp"] * wobble


def compute_raw_moisture(x: np.ndarray, y: np.ndarray, width: int, master_seed: int, p: dict) -> np.ndarray:
    """Low-frequency fBm moisture field (design doc §4.4, §5). "Raw" because
    the pinned DAG (§4.2 rule 2) computes this BEFORE rivers, which then
    (P4) derive flux from it and feed a bonus back into the post-river
    field `apply_river_moisture_bonus` produces.
    """
    moisture_seed = stage_seed(master_seed, STAGE_MOISTURE)
    return fbm(x, y, width, moisture_seed, p["moisture_octaves"], p["moisture_wavelength"])


def apply_river_moisture_bonus(moisture: np.ndarray, fresh_water: np.ndarray, bonus: float) -> np.ndarray:
    """River-bonus DAG slot (design doc §5) -- INERT in P3: `fresh_water` is
    always all-False (rivers are P4 scope, `MapData.fresh_water` is a clean
    stub), so this is a documented no-op until P4 populates it. Written as
    the real formula (not literally `return moisture`) so P4 only has to
    stop passing an all-False mask, not touch this function.
    """
    if not np.any(fresh_water):
        return moisture
    return moisture + bonus * fresh_water.astype(np.float64)


def classify_biomes(temperature: np.ndarray, moisture: np.ndarray, is_land: np.ndarray, p: dict):
    """(base_terrain, temp_rank, moisture_rank) via nearest-rank percentile
    thresholds on LAND tiles only (design doc §4.4, PW3 starting numbers).

    temp_rank/moisture_rank are percentile ranks (0-1) among land tiles
    (`ranking.percentile_rank_field`) -- both the design doc's percentile
    numbers (desert 0.36 / plains 0.56 "rainfall percentiles") and its
    temperature cutoffs (snow < 0.25, tundra < 0.30) are read AS
    percentiles here, a documented interpretation that makes both consistent
    under one "nearest-rank thresholds" discipline (design doc §4.2 rule 4)
    rather than the temperature numbers being on the raw -1.2..+1.2 scale
    (which the same 0.25/0.30 cutoffs would put at an implausibly high
    fraction of the map).

    Water tiles are left None (base_terrain for water comes from
    elevation.classify_water, a separate stage) and never enter the ranking
    (percentile_rank_field's `mask=is_land`) or the classification.
    """
    rows, cols = temperature.shape
    temp_rank = percentile_rank_field(temperature, is_land)
    moisture_rank = percentile_rank_field(moisture, is_land)

    base = np.full((rows, cols), None, dtype=object)
    if not np.any(is_land):
        return base, temp_rank, moisture_rank

    snow = is_land & (temp_rank < p["temp_snow_percentile"])
    tundra = is_land & ~snow & (temp_rank < p["temp_tundra_percentile"])
    warm = is_land & ~snow & ~tundra

    desert = warm & (moisture_rank < p["moisture_desert_percentile"])
    plains = warm & ~desert & (moisture_rank < p["moisture_plains_percentile"])
    grassland = warm & ~desert & ~plains

    base[snow] = "Snow"
    base[tundra] = "Tundra"
    base[desert] = "Desert"
    base[plains] = "Plains"
    base[grassland] = "Grassland"
    return base, temp_rank, moisture_rank


def _majority_vote(neighbor_terrains):
    """Terrain with >= 5 votes among up to 6 neighbors, else None. Ties
    (impossible to reach 5/6 with two terrains tied unless counts are e.g.
    5/1, which isn't a tie -- kept simple/defensive anyway) broken by
    `LAND_BASE_ORDER`, not dict/Counter iteration order.
    """
    if not neighbor_terrains:
        return None
    counts = {}
    for t in neighbor_terrains:
        counts[t] = counts.get(t, 0) + 1
    best, best_count = None, 0
    for name in LAND_BASE_ORDER:
        c = counts.get(name, 0)
        if c > best_count:
            best, best_count = name, c
    return best if best_count >= 5 else None


def majority_filter(base: np.ndarray, is_land: np.ndarray) -> np.ndarray:
    """ONE synchronous Jacobi pass (design doc §4.2 rule 5, §4.4): a land
    tile adopts its neighbors' base terrain if >= 5 of its (up to 6, land-
    only) neighbors agree on one value different from its own. Reads only
    from `base` (the pre-pass snapshot); land/water and relief are exempt
    by construction (only land tiles are visited, and this never touches
    a relief grid).
    """
    rows, cols = base.shape
    new_base = base.copy()
    for r in range(rows):
        for c in range(cols):
            if not is_land[r, c]:
                continue
            neighbor_terrains = [
                base[nr, nc]
                for nr, nc in hexmath.adjacent_coords((r, c), rows, cols)
                if is_land[nr, nc]
            ]
            winner = _majority_vote(neighbor_terrains)
            if winner is not None:
                new_base[r, c] = winner
    return new_base
