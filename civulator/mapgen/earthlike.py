"""Earthlike world generation (design doc §4, D10/D11, §11 P3/P4): the full
elevation -> water -> relief -> temperature -> moisture -> rivers -> biome ->
majority-filter -> feature -> floodplains/oasis -> resources pipeline,
assembled into one `MapData`.

Pinned DAG order (design doc §4.2 rule 2): elevation -> water/coast/lake ->
relief -> raw moisture -> rivers (flux from RAW moisture) -> moisture +
river bonus -> temperature -> biomes -> features -> floodplains/oasis ->
resources -> starts (design doc §6, §11 P5: fertility -> regions -> d_min
placement -> additive normalization; see mapgen/starts.py). Relief is produced alongside
elevation's land classification here (both come from the same nearest-rank
pass over the smoothed elevation field, design doc §4.3) rather than as a
separate DAG node.

**Split elevation (D25, §4.3 amendment, P7.5)**: "elevation" here is two
talus-smoothed fields sharing one set of warp/continentalness/ridged/
orogeny components (`elevation.compute_elevation_components` +
`elevation.combine_elevation`, called once and twice respectively) rather
than one — E_sea (land/sea/coast/lake) and E_relief (mountain/hill relief,
river junction altitudes, temperature's lapse term). The pinned STAGE order
above is unchanged; only what "the elevation stage" hands downstream
stages changed. See the D25 comments at each call site below for exactly
which field feeds what and why.

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

from . import climate, elevation, features, resources, rivers, starts
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
    # Split elevation (D25, docs/terrain_model_design.md §4.3): the single
    # "mountain_amp" knob became two, one per elevation field
    # (elevation.combine_elevation's `amp` argument) --
    #   mountain_amp_coast: contributes to E_sea, the field that drives
    #     is_land/sea_level/water_base (Coast/Lake/Ocean) ONLY. Default 0.0
    #     degenerates E_sea to pure continentalness (floating-point-exact,
    #     see elevation.combine_elevation) -- measured (P6 sweep) to turn
    #     24-79 fragmented fingers into 3-5 round continents. >0.0 restores
    #     the pre-D25 behavior of mountains also reshaping the coastline.
    #   mountain_amp_relief: contributes to E_relief, the field that drives
    #     ONLY the mountain/hill nearest-rank relief cuts (over E_sea's land
    #     mask) plus river junction altitudes and temperature's lapse term
    #     (both re-pointed to E_relief at their call sites in generate()
    #     below -- see the comments there for why). 1.5 is the ORIGINAL
    #     single-field mountain_amp value, unchanged.
    "mountain_amp_coast": 0.0,
    "mountain_amp_relief": 1.5,
    "warp_amp": 4.0,
    "warp_octaves": 3,
    # D25: 0.35 -> 0.45 -- measured (P6 sweep, confirmed on the shipped P7.5
    # split-elevation code) to cut start-placement failure from 27.7% to
    # ~2% by producing fewer, larger, rounder landmasses. Only meaningful
    # together with the split above: raising land_percent alone at the OLD
    # single mountain_amp=1.5 does not fix the fragmentation (see the P7.5
    # report's sweep table) -- it's the coastline field losing the ridged
    # signal that actually rounds the continents out.
    "land_percent": 0.45,
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

    # --- elevation: shared components ONCE, split combine TWICE (D25/§4.3
    # amendment) ---------------------------------------------------------
    # E_sea drives is_land/sea_level/water_base (Coast/Lake/Ocean) ONLY.
    # E_relief drives the mountain/hill relief cut (over E_sea's own land
    # mask) and is ALSO the field threaded to every other continuous-
    # elevation consumer below (river junction altitudes, temperature's
    # lapse term) -- see those call sites for why. Both are talus-smoothed
    # independently (each is a real elevation field in its own right, not
    # a derived overlay) from the SAME warp/continentalness/ridged/orogeny
    # components, computed once here rather than twice.
    continentalness, orogeny_mask, ridged = elevation.compute_elevation_components(
        x, y, cols, master_seed, p
    )
    raw_sea = elevation.combine_elevation(continentalness, orogeny_mask, ridged, p["mountain_amp_coast"])
    E_sea = elevation.talus_smooth(raw_sea, p["smooth_iterations"], p["talus_slope"], p["diffusion_coeff"])

    raw_relief = elevation.combine_elevation(continentalness, orogeny_mask, ridged, p["mountain_amp_relief"])
    E_relief = elevation.talus_smooth(
        raw_relief, p["smooth_iterations"], p["talus_slope"], p["diffusion_coeff"]
    )

    is_land, relief, sea_level = elevation.classify_land_and_relief(
        E_sea, E_relief, p["land_percent"], p["mountain_percent"], p["hill_percent"]
    )
    water_base = elevation.classify_water(is_land, p["lake_max_size"])

    # --- raw moisture -> rivers (flux from RAW moisture, §5) -> river bonus -> temperature (§4.4) ---
    raw_moisture = climate.compute_raw_moisture(x, y, cols, master_seed, p)
    # River junction altitudes read E_relief, not E_sea (D25 task brief:
    # "rivers should source in the mountain belts" -- also the numerically
    # consistent choice, since rivers.py's own module docstring calibrates
    # river_pd_epsilon/river_altitude_jitter against "amp default 1.5"'s
    # O(1) field magnitude, which IS E_relief, not E_sea).
    river_edges = rivers.generate_rivers(E_relief, water_base, raw_moisture, master_seed, p, rows, cols)
    # river_touch: the narrower, EARLIER-available "river-adjacent" mask
    # (rivers.river_adjacent_mask docstring) -- NOT yet the full §5
    # fresh_water definition, which needs Oasis (placed much later below).
    river_touch = rivers.river_adjacent_mask(river_edges, rows, cols)
    moisture = climate.apply_river_moisture_bonus(raw_moisture, river_touch, p["river_moisture_bonus"])
    # Temperature's lapse term also reads E_relief, not E_sea -- a D25
    # judgment call documented beyond the letter of the task brief (which
    # names only rivers): E_sea carries no ridged signal at all under the
    # default mountain_amp_coast=0.0, so leaving the lapse term on E_sea
    # would make every mountain/hill tile's lapse near-zero -- relief that
    # is visibly alpine but climatically indistinguishable from the plain
    # beside it. `sea_level` itself stays E_sea's own single nearest-rank
    # scalar threshold either way (never recomputed against E_relief) --
    # only WHICH continuous field pairs with that one scalar changes.
    temperature = climate.compute_temperature(x, y, cols, master_seed, E_relief, sea_level, p)

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

    # --- starting locations (§6, §11 P5): fertility -> regions -> d_min
    # placement -> additive normalization. Runs LAST (pinned DAG, §4.2 rule
    # 2) against the finished grids -- normalization may add a FEW more
    # bonus resources on top of what resources.place_resources() just
    # placed, so `resource` is reassigned to the value generate_starts()
    # returns, not the pre-normalization grid above.
    #
    # Read from the CALLER'S OWN `params` (not `p`, earthlike's own merged
    # dict) -- "starts" is a foreign key as far as earthlike's own
    # DEFAULT_PARAMS is concerned (design doc §6 is a different section
    # from earthlike's §4.3/§4.4), so keeping it out of `p` avoids it
    # echoing twice inside gen_params["earthlike"] below.
    starts_params = (params or {}).get("starts")
    start_list, resource = starts.generate_starts(
        base_terrain, relief, feature, resource, fresh_water,
        int(num_players), rows, cols, params=starts_params,
    )

    gen_params = {
        "seed": master_seed,
        "rows": rows,
        "cols": cols,
        "num_players": int(num_players),
        "map_type": "earthlike",
        "earthlike": dict(p),
        "starts": starts.merge_params(starts_params),
    }

    return MapData(
        base_terrain=base_terrain,
        relief=relief,
        feature=feature,
        resource=resource,
        rivers=river_edges,
        fresh_water=fresh_water,
        starts=start_list,
        params=gen_params,
    )
