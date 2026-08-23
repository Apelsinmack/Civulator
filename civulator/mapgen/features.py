"""Feature placement (design doc §4.2.2, §4.4, §5, §11 P3/P4): Woods,
Rainforest, Marsh, Ice, Reef (climate-gated, P3) plus Floodplains and Oasis
(river-dependent, P4 — `apply_floodplains`/`place_oasis` below; resources
are a separate layer, see mapgen/resources.py).

Climate-gated placement (`place_features`) goes through TWO gates, in order:
  1. Structural validity: `terrain_model.check_on` — the SAME `on`-matrix
     evaluator the engine, painter, and Tile.set_layers use (design doc D7:
     "the generator chooses placements via it") — never a hand-rolled
     parallel check of base/relief lists.
  2. Climate gate: this module's own temp_rank/moisture_rank bands (design
     doc §4.4: "Woods temperate, Rainforest hot+wet Plains, Marsh wet flat
     Grassland, Ice polar water, Reef warm Coast") — the `on` evaluator has
     no notion of climate, so these numeric bands are a documented
     interpretation of the doc's qualitative words, chosen to be mutually
     workable (see the per-feature comments below) rather than quoted from
     the design doc, which does not give exact numbers here.

Then a per-tile coordinate hash roll (design doc §4.2 rule 3): a tile that
passes both gates gets the feature iff
`tile_roll01(stage_seed, r, q, purpose) < feature_chance`.

Placement order (Ice, Reef, Rainforest, Marsh, Woods) is fixed and matters:
a tile keeps at most one feature (§3), and Rainforest/Marsh's narrower
climate bands go before Woods' broader one so Woods cannot claim a tile a
more specific feature would otherwise have been eligible for. Ice/Reef only
ever compete with each other (both Coast-eligible; their temp_rank bands
don't overlap) and never with a land feature.

Floodplains and Oasis run LATER, after rivers exist (design doc §4.2 rule 2
DAG: "... biomes -> features -> floodplains/oasis -> resources"), each as
its own function below — see their docstrings.
"""

import numpy as np

from .. import hexmath
from ..terrain_model import BASE_TABLE, check_on
from .seeding import (
    PURPOSE_ICE,
    PURPOSE_MARSH,
    PURPOSE_OASIS,
    PURPOSE_RAINFOREST,
    PURPOSE_REEF,
    PURPOSE_WOODS,
    STAGE_FEATURES,
    stage_seed,
    tile_roll01,
)

# Climate gate thresholds on temp_rank/moisture_rank (0-1, this module's own
# convention — see module docstring). Chosen defaults, reported as such.
_ICE_TEMP_MAX = 0.15
_REEF_TEMP_MIN = 0.60
_RAINFOREST_TEMP_MIN = 0.65
_RAINFOREST_MOISTURE_MIN = 0.65
_MARSH_MOISTURE_MIN = 0.75
_WOODS_TEMP_MIN = 0.20
_WOODS_TEMP_MAX = 0.85

# (feature_name, purpose_id, chance_key, climate_gate) — climate_gate(r, c)
# reads temp_rank/moisture_rank at (r, c); structural validity is checked
# separately via terrain_model.check_on for every candidate tile.
def _feature_specs(temp_rank, moisture_rank):
    return [
        ("Ice", PURPOSE_ICE, "ice",
         lambda r, c: temp_rank[r, c] < _ICE_TEMP_MAX),
        ("Reef", PURPOSE_REEF, "reef",
         lambda r, c: temp_rank[r, c] > _REEF_TEMP_MIN),
        ("Rainforest", PURPOSE_RAINFOREST, "rainforest",
         lambda r, c: temp_rank[r, c] > _RAINFOREST_TEMP_MIN
                       and moisture_rank[r, c] > _RAINFOREST_MOISTURE_MIN),
        ("Marsh", PURPOSE_MARSH, "marsh",
         lambda r, c: moisture_rank[r, c] > _MARSH_MOISTURE_MIN),
        ("Woods", PURPOSE_WOODS, "woods",
         lambda r, c: _WOODS_TEMP_MIN <= temp_rank[r, c] <= _WOODS_TEMP_MAX),
    ]


def place_features(base: np.ndarray, relief: np.ndarray, temp_rank: np.ndarray,
                    moisture_rank: np.ndarray, master_seed: int, feature_chance: dict) -> np.ndarray:
    """(rows, cols) object array of feature-name-or-None (design doc §4.4).

    `feature_chance`: dict with keys "woods"/"rainforest"/"marsh"/"ice"/"reef"
    (design doc §11 P3 deliverable 2's `[map.earthlike.feature_chance]`).
    """
    rows, cols = base.shape
    feature = np.full((rows, cols), None, dtype=object)
    seed = stage_seed(master_seed, STAGE_FEATURES)

    for name, purpose_id, chance_key, climate_gate in _feature_specs(temp_rank, moisture_rank):
        chance = feature_chance[chance_key]
        if chance <= 0:
            continue
        for r in range(rows):
            for c in range(cols):
                if feature[r, c] is not None:
                    continue
                b, rl = base[r, c], relief[r, c]
                if b is None:
                    continue
                if not check_on("feature", name, b, rl, None):
                    continue
                if not climate_gate(r, c):
                    continue
                if tile_roll01(seed, r, c, purpose_id) < chance:
                    feature[r, c] = name

    return feature


def apply_floodplains(base_terrain, relief, feature, river_touch, rows, cols):
    """Floodplains (design doc §5, D12, §11 P4 deliverable 3): deterministic,
    NO RNG at all — every FLAT Desert tile touching a river edge becomes
    Floodplains. Must run after rivers exist: `river_touch` is
    `rivers.river_adjacent_mask(rivers, rows, cols)` — the SAME mask that
    already fed the river moisture bonus (design doc §5), computed once and
    reused here rather than re-derived.

    The `on` constraint (`[terrain.feature.Floodplains]` = `{bases:
    ["Desert"], relief: ["flat"]}`, config.toml) is what encodes "flat
    Desert" here; river-adjacency is the spatial half of §3's "Floodplains
    on flat Desert along rivers" the per-tile `on` evaluator alone cannot
    express (see that config entry's own comment). A tile that already
    carries a feature (impossible here in practice — no climate feature can
    land on Desert — but checked anyway, defensively, same as every other
    placement function in this module) is skipped.
    """
    new_feature = feature.copy()
    for r in range(rows):
        for c in range(cols):
            if not river_touch[r, c]:
                continue
            if new_feature[r, c] is not None:
                continue
            base = base_terrain[r, c]
            if base is None:
                continue
            if check_on("feature", "Floodplains", base, relief[r, c], None):
                new_feature[r, c] = "Floodplains"
    return new_feature


def place_oasis(base_terrain, relief, feature, river_touch, master_seed, oasis_chance, rows, cols):
    """Oasis (design doc §5, §11 P4 deliverable 4): eligibility = the `on`
    constraint + no river edge on the tile + no adjacent water tile + no
    adjacent Oasis/Floodplains — computed AFTER floodplains settle (`feature`
    passed in already carries every Floodplains placement).

    UNLIKE every other per-tile stochastic decision in mapgen (D19:
    coordinate-hashed, order-free), this ONE stage is deliberately
    SEQUENTIAL: "no adjacent Oasis" depends on which nearby tiles already
    became an Oasis, which depends on scan order. Scan order is pinned to
    row-major ascending (row then column) — fixed and documented, so the
    result is still fully deterministic (just not order-INDEPENDENT the way
    D19's default case is) — design doc P4 deliverable 4: "this one stage
    is sequential-by-necessity for the no-adjacent-oasis rule; scan order
    pinned."

    "No adjacent water tile" reads terrain_model.BASE_TABLE's `domain`
    (§3.3) rather than a hardcoded Coast/Lake/Ocean list, so it can never
    drift from the single land/water source of truth.
    """
    new_feature = feature.copy()
    seed = stage_seed(master_seed, STAGE_FEATURES)

    water_bases = [name for name, entry in BASE_TABLE.items() if entry.get("domain") == "water"]
    is_water = np.isin(base_terrain, water_bases)

    for r in range(rows):
        for c in range(cols):
            if new_feature[r, c] is not None:
                continue
            if river_touch[r, c]:
                continue
            base = base_terrain[r, c]
            if base is None:
                continue
            if not check_on("feature", "Oasis", base, relief[r, c], None):
                continue
            neighbor_coords = hexmath.adjacent_coords((r, c), rows, cols)
            if any(is_water[nr, nc] for nr, nc in neighbor_coords):
                continue
            if any(new_feature[nr, nc] in ("Oasis", "Floodplains") for nr, nc in neighbor_coords):
                continue
            if tile_roll01(seed, r, c, PURPOSE_OASIS) < oasis_chance:
                new_feature[r, c] = "Oasis"

    return new_feature
