"""Bonus resource placement (design doc §3.2, §5, §11 P4 deliverable 5).

Per-tile hash rolls gated by the `on` evaluator (design doc D7), the same
coordinate-hashed discipline as features.py (D19). Unlike Oasis, resources
carry no inter-tile exclusion rule (no "no adjacent resource" constraint
anywhere in §3.2), so this stage IS fully order-free/coordinate-hashed — the
D19 default case, not an exception like features.place_oasis.

Placement order (`RESOURCE_ORDER`, design doc §3.2's own table order) is
fixed and matters: a tile keeps at most one resource, so tiles that
structurally qualify for MORE than one resource are resolved by first
match (structural `on` pass + successful hash roll) in this order. Real
overlaps this resolves (verified against the `on` tables in config.toml):
  - Rice vs Cattle: both match {Grassland, flat, no feature} (Rice's `on`
    additionally allows Marsh, Cattle doesn't) -- Wheat/Rice/Cattle/Sheep/
    Stone/Deer/Bananas/Fish is the declared order, so Rice is offered the
    tile before Cattle.
  - Stone vs Cattle/Rice: Stone's `on` allows flat OR hills on Grassland,
    so it also overlaps the flat case both of those cover.
  - Stone vs Sheep: both match {Grassland, hills, no feature}.
  - Sheep vs Deer: both match {Tundra, hills, no feature} (Sheep via its
    any-base+hills rule; Deer via its bases=["Tundra"] branch, which has no
    relief constraint so it matches Tundra at any relief).
Fish (water-only) and Bananas (Rainforest-only) are structurally disjoint
from every other resource, so their position in the order is arbitrary.
"""

import numpy as np

from ..terrain_model import RESOURCE_TABLE, check_on
from .seeding import (
    PURPOSE_RESOURCE_BANANAS,
    PURPOSE_RESOURCE_CATTLE,
    PURPOSE_RESOURCE_DEER,
    PURPOSE_RESOURCE_FISH,
    PURPOSE_RESOURCE_RICE,
    PURPOSE_RESOURCE_SHEEP,
    PURPOSE_RESOURCE_STONE,
    PURPOSE_RESOURCE_WHEAT,
    STAGE_RESOURCES,
    stage_seed,
    tile_roll01,
)

# (resource name, purpose id) — order is append-only and permanent (module
# docstring): reordering this list would silently change every world's
# resource placement on tiles with more than one structurally-eligible
# resource, and purpose ids must stay stable per seeding.py's own rule.
RESOURCE_ORDER = [
    ("Wheat", PURPOSE_RESOURCE_WHEAT),
    ("Rice", PURPOSE_RESOURCE_RICE),
    ("Cattle", PURPOSE_RESOURCE_CATTLE),
    ("Sheep", PURPOSE_RESOURCE_SHEEP),
    ("Stone", PURPOSE_RESOURCE_STONE),
    ("Deer", PURPOSE_RESOURCE_DEER),
    ("Bananas", PURPOSE_RESOURCE_BANANAS),
    ("Fish", PURPOSE_RESOURCE_FISH),
]


def place_resources(base_terrain, relief, feature, master_seed, rows, cols):
    """(rows, cols) object array of resource-name-or-None (design doc §3.2,
    §11 P4 deliverable 5).

    Each resource's `chance` (per-tile hash-roll probability, design doc
    §4.2 rule 3) is read from `terrain_model.RESOURCE_TABLE[name]["chance"]`
    — i.e. `[terrain.resource.<Name>].chance` in config.toml, alongside
    that resource's `on`/`yields` (P4 deliverable 5: "per-resource `chance`
    key added to [terrain.resource.*]"), NOT threaded through earthlike's
    `params` dict the way feature_chance is — resources' placement rule
    already lives entirely in terrain_model's tables (D7), so its
    probability belongs there too, one lookup, not two config homes for one
    resource.
    """
    resource = np.full((rows, cols), None, dtype=object)
    seed = stage_seed(master_seed, STAGE_RESOURCES)

    for name, purpose_id in RESOURCE_ORDER:
        chance = RESOURCE_TABLE.get(name, {}).get("chance", 0.0)
        if chance <= 0:
            continue
        for r in range(rows):
            for c in range(cols):
                if resource[r, c] is not None:
                    continue
                base = base_terrain[r, c]
                if base is None:
                    continue
                if not check_on("resource", name, base, relief[r, c], feature[r, c]):
                    continue
                if tile_roll01(seed, r, c, purpose_id) < chance:
                    resource[r, c] = name

    return resource
