"""Earthlike world generation (design doc §4, D10/D11, §11 P3/P4): the full
elevation -> water -> relief -> temperature -> moisture -> rivers -> biome ->
majority-filter -> feature -> floodplains/oasis -> resources pipeline,
assembled into one `MapData`.

Pinned DAG order (design doc §4.2 rule 2): elevation -> water/coast/lake ->
relief -> raw moisture -> rivers (flux from RAW moisture) -> moisture +
river bonus -> temperature -> biomes -> features -> floodplains/oasis ->
resources -> [starts: P5, still skipped]. Relief is produced alongside
elevation's land classification here (both come from the same nearest-rank
pass over the smoothed elevation field, design doc §4.3) rather than as a
separate DAG node.

Pure: numpy + stdlib + `civulator.hexmath`/`civulator.terrain_model` only
(via elevation.py/climate.py/features.py/rivers.py/resources.py) — no
`civulator.config` import. "params" are plain python values a caller
supplies explicitly (or omits, taking `DEFAULT_PARAMS`); `Map.generate_map`
is what reads config.toml and passes the result in (design doc §4.1:
"generate must be pure given its inputs — read config once at call
boundary, pass down" — the call boundary being the engine, not this module,
so tests can pin exact params without touching global config, design doc
§8/D21).
"""

import math

import numpy as np

from . import climate, elevation, features, resources, rivers
from .data import MapData

# Design doc E5: "minimum earthlike size is Duel (24x12) -- below it
# generate raises." Hardcoded (not read from config.toml's [map.sizes.duel])
# so this invariant holds for EVERY caller of earthlike.generate(), not only
# ones that go through Map.generate_map's config-reading path -- mapgen core
# takes no config dependency at all (see module docstring). Must be kept in
# sync by hand if Duel's preset ever changes size.
EARTHLIKE_MIN_ROWS = 12
EARTHLIKE_MIN_COLS = 24

# Every §4.3/§4.4 knob (design doc §11 P3 deliverable 2), mirrored in
# config.toml's [map.earthlike] (which overrides these via Map.generate_map's
# merge, the same "config overrides code defaults" pattern already used by
# environment.py's REWARDS / STARTING_WARRIORS). See the P3 implementation
# report for the reasoning behind each chosen number -- the design doc gives
# exact values for very few of these (H=1.0/offset=1.0/gain=2.0 for the
# ridged transform, and the biome percentiles/temperature cutoffs); the rest
# are this patch's own tuning, explicitly not claimed as "the" earthlike
# numbers.
DEFAULT_PARAMS = {
    "continent_wavelength": 3,
    "octaves": "auto",
    "mountain_wavelength": 5,
    "mountain_belt_percent": 0.35,
    "mountain_amp": 1.5,
    "warp_amp": 4.0,
    "warp_octaves": 3,
    "land_percent": 0.35,
    "mountain_percent": 0.08,
    "hill_percent": 0.20,
    "smooth_iterations": 3,
    "talus_slope": 0.08,
    "diffusion_coeff": 0.4,
    "lake_max_size": 12,
    "temp_wobble_amp": 0.3,
    "temp_wobble_wavelength": 4,
    "temp_lapse_rate": 0.8,
    "temp_snow_percentile": 0.25,
    "temp_tundra_percentile": 0.30,
    "moisture_wavelength": 5,
    "moisture_octaves": 4,
    "moisture_desert_percentile": 0.36,
    "moisture_plains_percentile": 0.56,
    "river_percent": 0.18,           # nearest-rank flux quantile that becomes river (design doc §5: "~0.15-0.20")
    "river_moisture_bonus": 0.1,     # added to moisture where river-adjacent, before biome classification
    "river_min_length": 2,           # rivers (connected junction-edge components) shorter than this are dropped
    "river_pd_epsilon": rivers.DEFAULT_PD_EPSILON,        # ε: Planchon-Darboux sink-fill step
    "river_altitude_jitter": rivers.DEFAULT_ALTITUDE_JITTER,  # δ: per-junction altitude jitter, δ << ε
    "feature_chance": {
        "woods": 0.35,
        "rainforest": 0.50,
        "marsh": 0.15,
        "ice": 0.70,
        "reef": 0.30,
        "oasis": 0.20,    # per-ELIGIBLE-tile roll (design doc §5: "~1% of land" is the resulting COUNT,
                           # not this probability -- eligible tiles are already a small subset of land;
                           # see the P4 report for the seed sweep this was tuned against)
    },
}


def _merge_params(params):
    merged = dict(DEFAULT_PARAMS)
    if params:
        for k, v in params.items():
            if k == "feature_chance":
                merged["feature_chance"] = {**DEFAULT_PARAMS["feature_chance"], **v}
            else:
                merged[k] = v
    return merged


def _hex_coords(rows: int, cols: int):
    """(x, y) hex-Cartesian coordinate grids, shape (rows, cols).

    Vectorized mirror of `civulator.hexmath.hex_center` (x = q + r/2,
    y = r*sqrt(3)/2) — deliberately NOT calling it per-tile in a python
    loop (hex_center is a pure scalar convenience; this is the same
    formula, elementwise, and tests/test_mapgen_noise.py checks the two
    agree at a sample of points). `x` is left un-wrapped here (hex_center
    itself takes `% width`) since every noise function wraps internally
    (noise.py's `perlin2d`) — wrapping twice would be redundant, not wrong.
    """
    row_idx, col_idx = np.meshgrid(
        np.arange(rows, dtype=np.float64), np.arange(cols, dtype=np.float64), indexing="ij"
    )
    x = col_idx + row_idx / 2.0
    # math.sqrt, not `3 ** 0.5`: IEEE754 mandates sqrt be correctly rounded
    # (portable by spec), but does NOT mandate that for the general `pow`
    # `**` routes through — the same distinction design doc §4.2.9 draws
    # between banning pow/exp/log/cos/sin and not banning +,-,*,/. A single
    # scalar constant (computed once, not per-tile), but there is no reason
    # to take the less-portable path when the more-portable one is this
    # cheap — `hexmath.py`/`viz/hex_render.py` already use `math.sqrt(3)`
    # for the identical constant.
    y = row_idx * math.sqrt(3.0) / 2.0
    return x, y


def generate(seed: int, size, num_players: int = 2, params: dict = None) -> MapData:
    """The earthlike generator (design doc §4, §11 P3/P4). `size` = (rows,
    cols), already resolved (see `data.resolve_size` for preset-name
    support at the engine/CLI boundary). Raises ValueError below Duel size
    (E5).
    """
    rows, cols = int(size[0]), int(size[1])
    if rows < EARTHLIKE_MIN_ROWS or cols < EARTHLIKE_MIN_COLS:
        raise ValueError(
            f"earthlike map {rows}x{cols} (rows x cols) is below the minimum "
            f"{EARTHLIKE_MIN_ROWS}x{EARTHLIKE_MIN_COLS} (Duel, design doc E5)"
        )

    p = _merge_params(params)
    master_seed = int(seed)
    x, y = _hex_coords(rows, cols)

    # --- elevation -> water/coast/lake -> relief (design doc §4.3) ---
    raw_elevation = elevation.compute_raw_elevation(x, y, cols, master_seed, p)
    smoothed = elevation.talus_smooth(
        raw_elevation, p["smooth_iterations"], p["talus_slope"], p["diffusion_coeff"]
    )
    is_land, relief, sea_level = elevation.classify_land_and_relief(
        smoothed, p["land_percent"], p["mountain_percent"], p["hill_percent"]
    )
    water_base = elevation.classify_water(is_land, p["lake_max_size"])

    # --- raw moisture -> rivers (flux from RAW moisture, §5) -> river bonus -> temperature (§4.4) ---
    raw_moisture = climate.compute_raw_moisture(x, y, cols, master_seed, p)
    river_edges = rivers.generate_rivers(smoothed, water_base, raw_moisture, master_seed, p, rows, cols)
    # river_touch: the narrower, EARLIER-available "river-adjacent" mask
    # (rivers.river_adjacent_mask docstring) -- NOT yet the full §5
    # fresh_water definition, which needs Oasis (placed much later below).
    river_touch = rivers.river_adjacent_mask(river_edges, rows, cols)
    moisture = climate.apply_river_moisture_bonus(raw_moisture, river_touch, p["river_moisture_bonus"])
    temperature = climate.compute_temperature(x, y, cols, master_seed, smoothed, sea_level, p)

    # --- biomes -> majority filter (§4.4, §4.2 rule 5) ---
    land_base, temp_rank, moisture_rank = climate.classify_biomes(temperature, moisture, is_land, p)
    land_base = climate.majority_filter(land_base, is_land)

    base_terrain = np.where(is_land, land_base, water_base)

    # --- climate-gated features, then river-dependent floodplains/oasis (§4.4, §5) ---
    feature = features.place_features(
        base_terrain, relief, temp_rank, moisture_rank, master_seed, p["feature_chance"]
    )
    feature = features.apply_floodplains(base_terrain, relief, feature, river_touch, rows, cols)
    feature = features.place_oasis(
        base_terrain, relief, feature, river_touch, master_seed, p["feature_chance"]["oasis"], rows, cols
    )

    # --- bonus resources (§3.2) ---
    resource = resources.place_resources(base_terrain, relief, feature, master_seed, rows, cols)

    # --- fresh water: the FULL §5 definition, now that base_terrain/feature
    # are finished (needs Oasis, just placed above) ---
    fresh_water = rivers.fresh_water_mask(river_edges, base_terrain, feature, rows, cols)

    gen_params = {
        "seed": master_seed,
        "rows": rows,
        "cols": cols,
        "num_players": int(num_players),
        "map_type": "earthlike",
        "earthlike": dict(p),
    }

    return MapData(
        base_terrain=base_terrain,
        relief=relief,
        feature=feature,
        resource=resource,
        rivers=river_edges,
        fresh_water=fresh_water,
        starts=[],
        params=gen_params,
    )
