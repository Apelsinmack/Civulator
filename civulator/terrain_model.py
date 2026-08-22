"""Pure interpreter for the composable terrain model (design doc §3, §3.1).

A tile's gameplay properties are the additive sum of its layers' contributions:
`base_terrain x relief x feature(<=1) x resource(<=1)`. This module is the one
place that sums those contributions (`compose`) and the one place that checks
whether a layer is allowed to sit on a given base/relief/feature combination
(`check_on`, `validate`) — design doc D7: "one `on`-matrix evaluator ... Tile
enforces through it, the generator chooses placements via it, the painter
places through Tile."

Imports only civulator.config: no civulator.game / civulator.agents /
civulator.viz. This is what lets the (pure) future mapgen package and the
(impure) game engine share one implementation instead of two (design doc §0
decision E1) — mapgen cannot import game/, and game/ must not import
torch/matplotlib-adjacent code, but both may import this.

Config schema (config.toml, added in P1 alongside the still-live legacy
tables — see docs/terrain_model_design.md §3.1 and §11 P1):

    [terrain.base.Grassland]
    yields = [2, 0]        # [food, production], additive, clamped >= 0 on the total
    movement = 1            # additive
    defense = 0              # additive, no cap
    los = [0, 0]            # [obstacle, vantage], additive
    domain = "land"          # "land" | "water" — base terrain only

    [terrain.relief.mountain]
    impassable = true        # the only source of the impassable flag (D6)
    los = [3, 0]

    [terrain.feature.Woods]
    yields = [0, 1]
    on = { bases = ["Plains", "Grassland", "Tundra"], relief = ["flat", "hills"] }

    [terrain.resource.Deer]
    on = [ { features = ["Woods"] }, { bases = ["Tundra"] } ]   # OR of AND-of-OR groups

`on` is either a single mapping (its `bases`/`relief`/`features` keys are each
an OR-list, and the keys present are AND-ed together — a present key that is
missing from the combination fails the match; an absent key is unconstrained)
or a list of such mappings, valid if ANY of them matches (needed for
placements that are a true disjunction across dimensions, e.g. Deer's "Woods
or Tundra" — a single AND-of-ORs mapping cannot express that; see the P1
implementation report for this as a documented interpretation of §3.2, not a
literal spec quote). A missing `relief` in a combination is treated as "flat"
for `on` matching (matches the intuitive reading of Tile.set_layers(relief=None)
as "flat"); a missing `feature` is treated as the literal string "none" (matching
the `features = ["none", ...]` convention shown in the Wheat example above).
"""

from dataclasses import dataclass

from .config import CFG

_TERRAIN_CFG = CFG.get("terrain", {})

BASE_TABLE = _TERRAIN_CFG.get("base", {})
RELIEF_TABLE = _TERRAIN_CFG.get("relief", {})
FEATURE_TABLE = _TERRAIN_CFG.get("feature", {})
RESOURCE_TABLE = _TERRAIN_CFG.get("resource", {})

_LAYER_TABLES = {
    "base": BASE_TABLE,
    "relief": RELIEF_TABLE,
    "feature": FEATURE_TABLE,
    "resource": RESOURCE_TABLE,
}

_UNSET_RELIEF = "flat"
_UNSET_FEATURE = "none"


@dataclass(frozen=True)
class ComposedProperties:
    """The additive result of composing a tile's layers (§3.1). Immutable.

    Attributes:
        yields: (food, production) tuple, each clamped >= 0.
        movement: additive movement cost (float/int).
        defense: additive defense modifier, no cap (float/int).
        los: (obstacle, vantage) tuple, additive.
        domain: "land" | "water" — taken from the base terrain only.
        impassable: True iff the relief layer sets the impassable flag
            (mountain) — the only source of impassability (design doc D6).
    """

    yields: tuple
    movement: float
    defense: float
    los: tuple
    domain: str
    impassable: bool


def _match(on, base, relief, feature):
    """True if one `on` mapping (bases/relief/features, each an OR-list) is satisfied."""
    relief_key = relief if relief is not None else _UNSET_RELIEF
    feature_key = feature if feature is not None else _UNSET_FEATURE

    if "bases" in on and base not in on["bases"]:
        return False
    if "relief" in on and relief_key not in on["relief"]:
        return False
    if "features" in on and feature_key not in on["features"]:
        return False
    return True


def check_on(layer_kind, layer_name, base, relief, feature):
    """Evaluate the `on` placement constraint for one layer table entry.

    Args:
        layer_kind: "base" | "relief" | "feature" | "resource".
        layer_name: the table key, e.g. "Woods", "Wheat".
        base, relief, feature: the candidate combination to test (relief/feature
            may be None; see module docstring for how None is matched).

    Returns:
        True if `layer_name` has no `on` entry (unconstrained) or if the given
        combination satisfies it (any group, if `on` is a list of groups).
    """
    table = _LAYER_TABLES[layer_kind]
    entry = table.get(layer_name, {})
    on = entry.get("on")
    if not on:
        return True
    if isinstance(on, dict):
        return _match(on, base, relief, feature)
    return any(_match(group, base, relief, feature) for group in on)


def validate(base, relief=None, feature=None, resource=None):
    """Raise ValueError if this layer combination is unknown or violates an `on` constraint.

    Checks relief (if given) against base; feature (if given) against
    base+relief; resource (if given) against base+relief+feature — exactly
    the placement matrix of design doc §3.1. Does not compose values; call
    compose() separately (Tile.set_layers does both).
    """
    if base not in BASE_TABLE:
        raise ValueError(f"Unknown base terrain: {base!r}")

    if relief is not None:
        if relief not in RELIEF_TABLE:
            raise ValueError(f"Unknown relief: {relief!r}")
        if not check_on("relief", relief, base, relief, feature):
            raise ValueError(f"Relief {relief!r} is not valid on base {base!r}")

    if feature is not None:
        if feature not in FEATURE_TABLE:
            raise ValueError(f"Unknown feature: {feature!r}")
        if not check_on("feature", feature, base, relief, feature):
            raise ValueError(
                f"Feature {feature!r} is not valid on base={base!r} relief={relief!r}"
            )

    if resource is not None:
        if resource not in RESOURCE_TABLE:
            raise ValueError(f"Unknown resource: {resource!r}")
        if not check_on("resource", resource, base, relief, feature):
            raise ValueError(
                f"Resource {resource!r} is not valid on base={base!r} "
                f"relief={relief!r} feature={feature!r}"
            )


def compose(base, relief=None, feature=None, resource=None):
    """Sum the layers' contributions into one ComposedProperties bundle (§3.1).

    Does not validate `on` constraints — call validate() first if the
    combination might be invalid (Tile.set_layers calls both, in that order).
    Unknown layer names raise KeyError (validate() gives the friendlier message).
    """
    entries = [BASE_TABLE[base]]
    if relief is not None:
        entries.append(RELIEF_TABLE[relief])
    if feature is not None:
        entries.append(FEATURE_TABLE[feature])
    if resource is not None:
        entries.append(RESOURCE_TABLE[resource])

    food = production = 0
    movement = defense = 0
    obstacle = vantage = 0
    for entry in entries:
        y = entry.get("yields", (0, 0))
        food += y[0]
        production += y[1]
        movement += entry.get("movement", 0)
        defense += entry.get("defense", 0)
        los = entry.get("los", (0, 0))
        obstacle += los[0]
        vantage += los[1]

    food = max(0, food)
    production = max(0, production)

    domain = BASE_TABLE[base].get("domain", "land")
    impassable = bool(RELIEF_TABLE[relief].get("impassable", False)) if relief is not None else False

    return ComposedProperties(
        yields=(food, production),
        movement=movement,
        defense=defense,
        los=(obstacle, vantage),
        domain=domain,
        impassable=impassable,
    )
