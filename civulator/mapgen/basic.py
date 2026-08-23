"""The "basic" generator (design doc §4.1, §11 P3): iid per-tile terrain,
independent relief/feature rolls, ALL coordinate-hashed — never a stream
draw (D19). REPLACES the P2a interim shim that used to live in
`Map.generate_map` (`_LEGACY_TERRAIN_LAYERS` + `self.rng.choices`/`.random()`
stream draws): same weighted-terrain-category table and base/relief mapping,
same woods/rainforest bonus-feature logic, now driven by per-tile hashes
instead of a shared mutable RNG stream, and validated through
`terrain_model.check_on` (the same evaluator earthlike/painter/engine use)
instead of ad hoc `if` checks.

Content changes as a result (different tiles for the same seed) — expected
and documented (design doc §11 P3: "basic worlds change content; that is
expected, the golden is xfail"). No water, no rivers, no regular-stage
resources: `basic` stays the deliberately simple option small tests reach
for (design doc E5), same as it was pre-0.6.

Starts (design doc §6, §11 P5) are the one exception to "no resources":
`civulator.mapgen` §4.1 explicitly gives basic "the same starts stage" as
earthlike, and start normalization (§6.4) may place a FEW additive bonus
resources near a weak start -- so a basic world can carry a handful of
resources even though `resources.place_resources()` itself never runs here.
"""

import numpy as np

from ..terrain_model import check_on
from .data import MapData
from .seeding import (
    PURPOSE_BASIC_RAINFOREST,
    PURPOSE_BASIC_WOODS,
    STAGE_BASIC_BASE,
    STAGE_BASIC_FEATURES,
    stage_seed,
    tile_roll01,
)
from . import starts

# (base, relief, feature) per legacy weighted-terrain-category name — lifted
# verbatim from the deleted `civulator.game.map._LEGACY_TERRAIN_LAYERS`.
_LEGACY_LAYERS = {
    "Plains": ("Plains", "flat", None),
    "Grassland": ("Grassland", "flat", None),
    "Desert": ("Desert", "flat", None),
    "Tundra": ("Tundra", "flat", None),
    "Hills": ("Plains", "hills", None),
    "Woods": ("Grassland", "flat", "Woods"),
    "Mountain": ("Plains", "mountain", None),
}

DEFAULT_TERRAIN_WEIGHTS = {
    "Plains": 0.30, "Grassland": 0.30, "Desert": 0.10, "Tundra": 0.10,
    "Hills": 0.10, "Woods": 0.05, "Mountain": 0.05,
}
DEFAULT_FEATURE_CHANCE = {"woods": 0.2, "rainforest": 0.1}


def _merge_params(params):
    p = {
        "terrain_weights": dict(DEFAULT_TERRAIN_WEIGHTS),
        "feature_chance": dict(DEFAULT_FEATURE_CHANCE),
    }
    if params:
        if "terrain_weights" in params:
            p["terrain_weights"] = dict(params["terrain_weights"])
        if "feature_chance" in params:
            p["feature_chance"] = {**DEFAULT_FEATURE_CHANCE, **params["feature_chance"]}
    return p


def _cumulative_weights(weights_dict):
    """[(name, cumulative_upper_bound), ...] — a fixed-order (dict insertion
    order, i.e. config/table declaration order — permanent once config is
    loaded, not a numpy/CPython-version-dependent detail) cumulative table
    for the per-tile roll to walk. The last bound is pinned to 1.0 exactly
    so a roll arbitrarily close to 1.0 (tile_roll01 is strictly < 1.0, but
    floating-point summation of the individual fractions could undershoot
    1.0 by a ULP or two) always lands in the final bucket rather than
    falling through unmatched.
    """
    names = list(weights_dict.keys())
    total = float(sum(weights_dict.values()))
    cum = []
    acc = 0.0
    for name in names:
        acc += weights_dict[name] / total
        cum.append((name, acc))
    cum[-1] = (cum[-1][0], 1.0)
    return cum


def generate(seed: int, size, num_players: int = 2, params: dict = None) -> MapData:
    """The basic generator (design doc §4.1, §11 P3), same `generate`
    contract as `earthlike.generate` (positional args, `MapData` return).
    No minimum size (design doc test (h): "basic at 8x16 works").
    """
    rows, cols = int(size[0]), int(size[1])
    p = _merge_params(params)
    master_seed = int(seed)

    cum_weights = _cumulative_weights(p["terrain_weights"])
    base_seed = stage_seed(master_seed, STAGE_BASIC_BASE)
    feature_seed = stage_seed(master_seed, STAGE_BASIC_FEATURES)
    woods_chance = p["feature_chance"]["woods"]
    rainforest_chance = p["feature_chance"]["rainforest"]

    base = np.empty((rows, cols), dtype=object)
    relief = np.full((rows, cols), "flat", dtype=object)
    feature = np.full((rows, cols), None, dtype=object)

    for r in range(rows):
        for c in range(cols):
            roll = tile_roll01(base_seed, r, c, 0)
            legacy_name = cum_weights[-1][0]
            for name, upper in cum_weights:
                if roll < upper:
                    legacy_name = name
                    break

            b, rl, feat = _LEGACY_LAYERS.get(legacy_name, (legacy_name, "flat", None))
            base[r, c] = b
            relief[r, c] = rl
            feature[r, c] = feat

            # Bonus woods/rainforest rolls — same eligibility gate as the
            # deleted shim: only a DIRECT Plains/Grassland/Tundra draw is
            # eligible (a "Woods"/"Hills"/"Mountain" draw already has its
            # feature/relief decided and is not rerolled).
            woods_roll = tile_roll01(feature_seed, r, c, PURPOSE_BASIC_WOODS)
            rainforest_roll = tile_roll01(feature_seed, r, c, PURPOSE_BASIC_RAINFOREST)
            if legacy_name in ("Plains", "Grassland", "Tundra") and woods_roll < woods_chance:
                if check_on("feature", "Woods", b, rl, None):
                    feature[r, c] = "Woods"
            elif legacy_name in ("Plains", "Grassland") and rainforest_roll < rainforest_chance:
                if check_on("feature", "Rainforest", b, rl, None):
                    feature[r, c] = "Rainforest"

    resource = np.full((rows, cols), None, dtype=object)
    fresh_water = np.zeros((rows, cols), dtype=bool)  # never true for basic -- no rivers/Lake/Oasis

    # --- starting locations (design doc §6, §11 P5): "same starts stage" as
    # earthlike (design doc §4.1) -- fertility/regions/placement are all
    # domain-only, so an all-land basic board works unmodified; only the
    # fresh-water/coastal fertility bonuses are structurally always 0 here.
    starts_params = (params or {}).get("starts")
    start_list, resource = starts.generate_starts(
        base, relief, feature, resource, fresh_water,
        int(num_players), rows, cols, params=starts_params,
    )

    gen_params = {
        "seed": master_seed,
        "rows": rows,
        "cols": cols,
        "num_players": int(num_players),
        "map_type": "basic",
        "basic": dict(p),
        "starts": starts.merge_params(starts_params),
    }
    return MapData(
        base_terrain=base,
        relief=relief,
        feature=feature,
        resource=resource,
        rivers={},  # dict, matching earthlike's type (design doc §5, P4) -- never non-empty for basic
        fresh_water=fresh_water,
        starts=start_list,
        params=gen_params,
    )
