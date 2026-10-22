"""Pure interpreter for the composable terrain model (design doc §3, §3.1).

A tile's gameplay properties are the additive sum of its layers' contributions:
`base_terrain x relief x feature(<=1) x resource(<=1)`. This module is the one
place that sums those contributions (`compose`) and the one place that checks
whether a layer is allowed to sit on a given base/relief/feature combination
(`matches` / `check_on` / `validate`) — design doc D7: "one `on`-matrix
evaluator ... Tile enforces through it, the generator chooses placements via
it, the painter places through Tile." It also holds the canonical
terrain-domain passability check (`can_enter`, §3.3/D8), which every mover —
units, spawns, the A* cost-grid builder, the action masks — goes through.

Imports only civulator.config and the two pure interpreters it builds on
(unit_model's `to_tenths`, research_model's tech names, #116 P2): no
civulator.game / civulator.agents / civulator.viz. This is what lets the (pure) future mapgen package and the
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
from .research_model import validate_tech_name
from .unit_model import UNIT_REQUIRES_RESOURCE, to_tenths

_TERRAIN_CFG = CFG.get("terrain", {})

BASE_TABLE = _TERRAIN_CFG.get("base", {})
RELIEF_TABLE = _TERRAIN_CFG.get("relief", {})
FEATURE_TABLE = _TERRAIN_CFG.get("feature", {})
RESOURCE_TABLE = _TERRAIN_CFG.get("resource", {})

# Improvement housing (issue #88): optional `housing` column of each
# [improvements.*] table, in int tenths. This module is the one interpreter of
# tile gameplay numbers; civulator/game/housing.py reads this table.
IMPROVEMENT_HOUSING = {
    name: to_tenths(table["housing"], f"[improvements.{name}] housing")
    for name, table in CFG.get("improvements", {}).items()
    if table.get("housing")
}

# Every configured improvement name (issue #86): the one accessor for
# "does this improvement exist", so no other module re-reads
# CFG["improvements"] to validate a name. IMPROVEMENT_ORDER is the same names
# in config order (#116 P8): a frozenset of strings iterates in a
# hash-seed-dependent order, so "ties by config order" reads the tuple.
IMPROVEMENT_ORDER = tuple(CFG.get("improvements", {}))
IMPROVEMENT_NAMES = frozenset(IMPROVEMENT_ORDER)

# --- Improvement gates and yields (issue #116 P2, progression design "v2 fixes") ---

# Every key an [improvements.*] table may carry; a typo raises at load.
IMPROVEMENT_KEYS = frozenset({"on", "housing", "requires_tech", "food", "production", "gold"})
# The tile yields an improvement may add, in whole points.
IMPROVEMENT_YIELD_COLUMNS = ("food", "production", "gold")


def parse_improvements(tables):
    """`[improvements.*]` -> (on, requires_tech, yields), each keyed by name.

    `on`: the placement constraint of every improvement declaring one (an
    improvement without `on` is buildable nowhere). `requires_tech`: a tech
    name, checked against research_model. `yields`: name -> {food,
    production, gold} in whole non-negative points, for every improvement
    (0 when a column is absent). Unknown keys raise.
    """
    on, requires_tech, yields = {}, {}, {}
    for name, table in tables.items():
        where = f"[improvements.{name}]"
        unknown = set(table) - IMPROVEMENT_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        if "on" in table:
            on[name] = table["on"]
        if "requires_tech" in table:
            requires_tech[name] = validate_tech_name(table["requires_tech"], where)
        columns = {}
        for column in IMPROVEMENT_YIELD_COLUMNS:
            value = table.get(column, 0)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{where} {column} must be a non-negative int, got {value!r}")
            columns[column] = value
        yields[name] = columns
    return on, requires_tech, yields


_IMPROVEMENT_ON, IMPROVEMENT_REQUIRES_TECH, IMPROVEMENT_YIELDS = parse_improvements(
    CFG.get("improvements", {})
)


def improvement_on(name):
    """The `on` placement constraint of improvement `name`, or None when it
    is buildable nowhere (unknown, or no `on` entry). The one accessor
    `GameEnvironment.can_build_improvement_at` reads."""
    return _IMPROVEMENT_ON.get(name)

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


# Sentinel for "the caller did not pass a resource" (districts design v3
# fixes): a `resources` constraint evaluated without one raises instead of
# silently passing. `None` stays the explicit "this tile has no resource".
_NOT_GIVEN = object()

# The keys an `on` mapping may carry. `resources` (issue #86) is accepted only
# where the caller evaluates it with a resource -- district rules -- and is
# rejected at load in layer and improvement tables (validate_on_table).
ON_KEYS = frozenset({"bases", "relief", "features"})
ON_KEYS_WITH_RESOURCES = ON_KEYS | {"resources"}

# `resources = ["any"]` matches any resource (but not "no resource").
ANY_RESOURCE = "any"

# The resource classes (v0.9.0 Q1, districts_religion_design "v2 fixes" B1).
# A class name in an `on` mapping's `resources` list matches every resource of
# that class; a resource may therefore never be named like a class.
RESOURCE_CLASSES = ("bonus", "luxury", "strategic")


def _match(on, base, relief, feature, resource=_NOT_GIVEN):
    """True if one `on` mapping (bases/relief/features/resources, each an OR-list) is satisfied."""
    relief_key = relief if relief is not None else _UNSET_RELIEF
    feature_key = feature if feature is not None else _UNSET_FEATURE

    if "bases" in on and base not in on["bases"]:
        return False
    if "relief" in on and relief_key not in on["relief"]:
        return False
    if "features" in on and feature_key not in on["features"]:
        return False
    if "resources" in on:
        if resource is _NOT_GIVEN:
            raise ValueError(
                f"`on` mapping {on!r} constrains `resources` but no resource was passed"
            )
        if resource is None:
            return False
        listed = on["resources"]
        if (ANY_RESOURCE not in listed and resource not in listed
                and resource_class(resource) not in listed):
            return False
    return True


def matches(on, base, relief=None, feature=None, resource=_NOT_GIVEN):
    """Evaluate any `on` constraint against a base/relief/feature(/resource) combination.

    The single `on`-matrix evaluator (design doc D7). Terrain layers reach it
    through check_on(); non-layer consumers that carry their own `on` tables —
    improvements, `[improvements.*]` in config.toml, per §3.1, and district
    rules (issue #86) — call this directly.

    Args:
        on: a mapping (bases/relief/features/resources OR-lists, AND-ed) or a
            list of mappings (valid if ANY matches). Falsy means unconstrained.
        resource: the tile's resource name, or None for none. Must be passed
            whenever `on` may carry a `resources` key: evaluating such a
            mapping without it raises ValueError (no silent pass).
    """
    if not on:
        return True
    if isinstance(on, dict):
        return _match(on, base, relief, feature, resource)
    return any(_match(group, base, relief, feature, resource) for group in on)


def validate_on_table(on, where, allow_resources=False, check_names=False):
    """Load-time check of one `on` value (a mapping or a list of mappings).

    Unknown keys raise; `resources` raises unless `allow_resources`. With
    `check_names`, every listed name must exist in its table ("none" is a
    valid feature, "any" and a class name -- RESOURCE_CLASSES -- valid
    resources). Returns `on` unchanged.
    """
    allowed = ON_KEYS_WITH_RESOURCES if allow_resources else ON_KEYS
    groups = [on] if isinstance(on, dict) else on
    if not isinstance(groups, list):
        raise ValueError(f"{where}: `on` must be a mapping or a list of mappings, got {on!r}")
    known = {
        "bases": set(BASE_TABLE),
        "relief": set(RELIEF_TABLE),
        "features": set(FEATURE_TABLE) | {_UNSET_FEATURE},
        "resources": set(RESOURCE_TABLE) | {ANY_RESOURCE} | set(RESOURCE_CLASSES),
    }
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError(f"{where}: `on` group must be a mapping, got {group!r}")
        unknown = set(group) - allowed
        if unknown:
            raise ValueError(f"{where}: unknown `on` key(s) {sorted(unknown)}")
        for key, names in group.items():
            if not isinstance(names, list):
                raise ValueError(f"{where}: `on` key {key!r} must be a list, got {names!r}")
            if check_names:
                missing = [n for n in names if n not in known[key]]
                if missing:
                    raise ValueError(f"{where}: `on` {key} names unknown {missing}")
    return on


def resource_class(name):
    """The `class` of a resource (one of RESOURCE_CLASSES). Unknown names
    raise KeyError. The one accessor for resource class (issue #86)."""
    return RESOURCE_TABLE[name]["class"]


# --- Resource columns (v0.9.0 Q1, districts_religion_design §2.1, "v2 fixes" B2) ---

# Every key a [terrain.resource.*] table may carry; a typo raises at load.
RESOURCE_KEYS = frozenset({"class", "on", "yields", "chance",
                           "improved_by", "reveals", "frequency"})
# The columns only a strategic or luxury resource declares (a bonus resource
# grants nothing, so it names no improvement, tech or tiered-stage weight).
_TIERED_ONLY_KEYS = ("improved_by", "reveals", "frequency")


def parse_resources(tables):
    """`[terrain.resource.*]` -> (improved_by, reveals, frequency), each keyed
    by name. Raises at load on: an unknown key, an unknown class, a resource
    named like a class (or "any"), a tiered-only column on a bonus resource,
    a strategic/luxury resource without `improved_by` / `frequency`, an
    unknown improvement in `improved_by`, an unknown tech in `reveals`, a
    non-positive or non-int `frequency`.

    `improved_by`: name -> tuple of improvement names (every resource; empty
    for bonus). `reveals`: name -> tech name or None. `frequency`: name ->
    positive int for every strategic/luxury resource.
    """
    improved_by, reveals, frequency = {}, {}, {}
    for name, table in tables.items():
        where = f"[terrain.resource.{name}]"
        unknown = set(table) - RESOURCE_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        if name in RESOURCE_CLASSES or name == ANY_RESOURCE:
            raise ValueError(f"{where}: a resource may not be named like a class or 'any'")
        cls = table.get("class")
        if cls not in RESOURCE_CLASSES:
            raise ValueError(f"{where}: class must be one of {RESOURCE_CLASSES}, got {cls!r}")
        if cls == "bonus":
            declared = [k for k in _TIERED_ONLY_KEYS if k in table]
            if declared:
                raise ValueError(f"{where}: a bonus resource declares none of {declared}")
            improved_by[name] = ()
            reveals[name] = None
            continue
        names = table.get("improved_by")
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ValueError(f"{where}: improved_by must be a list of improvement names, got {names!r}")
        missing = [n for n in names if n not in IMPROVEMENT_NAMES]
        if missing:
            raise ValueError(f"{where}: improved_by names unknown improvement(s) {missing}")
        improved_by[name] = tuple(names)
        reveals[name] = (validate_tech_name(table["reveals"], f"{where} reveals")
                         if "reveals" in table else None)
        weight = table.get("frequency")
        if isinstance(weight, bool) or not isinstance(weight, int) or weight < 1:
            raise ValueError(f"{where}: frequency must be a positive int, got {weight!r}")
        frequency[name] = weight
    return improved_by, reveals, frequency


RESOURCE_IMPROVED_BY, RESOURCE_REVEALS, RESOURCE_FREQUENCY = parse_resources(RESOURCE_TABLE)


def resources_of_class(cls):
    """Every resource of class `cls`, in config order (a tuple: config order is
    the only tie-break order -- never iterate a set of names)."""
    if cls not in RESOURCE_CLASSES:
        raise ValueError(f"unknown resource class {cls!r}, expected one of {RESOURCE_CLASSES}")
    return tuple(name for name in RESOURCE_TABLE if RESOURCE_TABLE[name]["class"] == cls)


def _validate_unit_resource_gates(gates=None):
    """Load-time: every `[units.*] requires_resource` (`gates`, default
    unit_model's parse) names a strategic resource (v0.9.0 Q1). Lives here,
    not in unit_model, because unit_model loads first and this module owns
    [terrain.resource.*]."""
    for unit, name in (UNIT_REQUIRES_RESOURCE if gates is None else gates).items():
        if name not in RESOURCE_TABLE or RESOURCE_TABLE[name]["class"] != "strategic":
            raise ValueError(
                f"[units.{unit}] requires_resource must name a strategic resource, got {name!r}"
            )


_validate_unit_resource_gates()


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
    entry = _LAYER_TABLES[layer_kind].get(layer_name, {})
    return matches(entry.get("on"), base, relief, feature)


def can_enter(domain, tile):
    """Canonical terrain-domain passability check (design doc §3.3, D8).

    Answers "does this terrain admit a unit of this movement domain" — domain
    match plus the impassable flag. Occupancy (unit slots) is a separate
    concern and is NOT considered here.

    `tile` is anything carrying composed `.domain` / `.impassable` — a Tile or
    a ComposedProperties. A missing tile (off-map) admits nobody.
    """
    if tile is None:
        return False
    return tile.domain == domain and not tile.impassable


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
        # Water is always flat (§3) — a domain rule rather than an `on` list, so
        # that a future water base terrain inherits it without being enumerated.
        if relief != "flat" and BASE_TABLE[base].get("domain") == "water":
            raise ValueError(
                f"Relief {relief!r} is not valid on water base {base!r} — water is always flat"
            )
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


def _validate_config_on_tables():
    """Load-time: every layer and improvement `on` table rejects unknown keys
    and `resources` (issue #86, districts design v3 fixes)."""
    for kind, table in _LAYER_TABLES.items():
        for name, entry in table.items():
            if "on" in entry:
                validate_on_table(entry["on"], f"[terrain.{kind}.{name}]")
    for name, entry in CFG.get("improvements", {}).items():
        if "on" in entry:
            validate_on_table(entry["on"], f"[improvements.{name}]")


_validate_config_on_tables()
