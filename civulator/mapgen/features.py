"""Feature placement WITHOUT river-dependent features (design doc §4.2.2,
§4.4, §11 P3): Woods, Rainforest, Marsh, Ice, Reef. Floodplains/Oasis are
river-dependent (P4) and resources are P5 — both leave clean stage stubs
(no-ops here; see earthlike.py).

Every placement goes through TWO gates, in order:
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
"""

import numpy as np

from ..terrain_model import check_on
from .seeding import (
    PURPOSE_ICE,
    PURPOSE_MARSH,
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
