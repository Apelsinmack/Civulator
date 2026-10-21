"""Pure interpreter for unit stat and combat config tables (issue #64).

Mirrors civulator/terrain_model.py's pattern: one module that reads its
config.toml tables once at import and hands back plain dicts/values, rather
than every call site reaching into CFG itself. `get_combat_strength` runs
several times per attack and mask building touches unit data on a hot path,
so — same discipline as RIVER_CROSSING_COST in game/unit.py — nothing here
is looked up from CFG per call.

Config schema (config.toml):

    [units.Warrior]
    max_movement = 2
    combat_strength = 20
    ranged_strength = 0
    range = 1
    production_cost = 40

    [combat]
    class_bonuses = [ { unit = "melee", target = "anti_cavalry", amount = 5, strength = "combat" }, ... ]
    ...

This module is the only interpreter of `[units.*]` / `[combat]` / `[city]`
health+defense / `[buildings.*]` / the per-city yield tables `[science]`,
`[culture]`, `[gold]`, `[faith]` (issue #116): civulator/game/unit.py and
civulator/game/city.py import
from it and must not read those CFG tables directly, and no new hardcoded
combat number should appear anywhere else (CLAUDE.md canonical-systems
table). `NUM_UNIT_SLOTS`/`UNIT_SLOT` and `MOVEMENT_DOMAIN` are deliberately
NOT here — see the comments on those tables in game/unit.py for why.

Availability columns (#116 P2, progression design "v2 fixes", load order):
this module parses `requires_tech` and `requires_civic` on units and
buildings and `requires_district`, `requires_building`,
`requires_government_tier`, `maintenance` and `purchasable` on buildings
(#116 P4 validates the civic and government columns and adds
`purchasable`). A `requires_tech` / `requires_civic` /
`requires_government_tier` is checked against `research_model`, which loads
first; a `requires_district` names the district registry, which loads after
this module, so `district_model` checks those names against itself. A
building's `effects` list is kept raw here and validated by
`civulator/effects.py`, which loads after every registry. Unknown keys in a
`[units.*]` or `[buildings.*]` table raise.

Combat classes, upgrades and unit prices (#116 P3, progression design §6 and
"v2 fixes"): every `[units.*]` table declares `combat_class` and `era` (both
required) and `maintenance` (required; gold per turn, stored in tenths like
`BUILDING_MAINTENANCE`); `purchasable` (default `["gold"]`) and `upgrades_to`
are optional. `[combat] class_bonuses` is a list of class-pair rows replacing
the three name-keyed constants (`anti_cavalry_bonus`,
`melee_vs_spearman_bonus`, `archer_vs_horseman_penalty`): see
`parse_class_bonuses`. `[gold] upgrade_per_production` / `upgrade_base` price
an upgrade (`base_upgrade_cost`). This module is the only reader of all of it.

Purchasing (#116 P5, design §7.3): `[gold] purchase_multiplier` and `[faith]
purchase_multiplier` (`PURCHASE_MULTIPLIER`) price a purchase with that
resource, and `faith_category(unit)` names the faith-purchase category a
`faith_purchase` effect unlocks a unit by (`land_military`: every fighting
combat class). civulator/game/purchasing.py consumes both.

tests/test_unit_config_identity.py is the bit-identity gate for #64 and #116
P3: it pins every value below, and every existing unit pairing's combat and
ranged strength, as hardcoded literals, independent of this module and of
config.toml, so these moves are provably refactors and not balance changes.
"""

from typing import NamedTuple

from .config import CFG
from .research_model import (
    ERAS,
    validate_civic_name,
    validate_government_tier,
    validate_tech_name,
)

_UNITS_CFG = CFG.get("units", {})
_COMBAT_CFG = CFG.get("combat", {})
_CITY_CFG = CFG.get("city", {})

# --- The five per-unit-type data tables (game/unit.py Unit class attrs) ---

MAX_MOVEMENT = {name: table["max_movement"] for name, table in _UNITS_CFG.items()}
BASE_COMBAT_STRENGTH = {name: table["combat_strength"] for name, table in _UNITS_CFG.items()}
BASE_RANGED_STRENGTH = {name: table["ranged_strength"] for name, table in _UNITS_CFG.items()}
RANGE_VALUES = {name: table["range"] for name, table in _UNITS_CFG.items()}
PRODUCTION_COST = {name: table["production_cost"] for name, table in _UNITS_CFG.items()}

# --- Combat formula / modifier constants (get_combat_strength, get_ranged_strength,
# calculate_damage, heal — game/unit.py) ---

# The class-pair modifiers that used to live here as three name-keyed
# constants are `CLASS_BONUSES` below (#116 P3); the siege class is
# `SIEGE_CLASS` below, derived from `combat_class`. The siege class is exempt
# from RANGED_CITY_PENALTY — breaking fortifications is what the class is for.
RANGED_CITY_PENALTY = _COMBAT_CFG["ranged_city_penalty"]
FORTIFICATION_BONUS = _COMBAT_CFG["fortification_bonus"]  # index by fortification level - 1
HP_PENALTY_COEFFICIENT = _COMBAT_CFG["hp_penalty_coefficient"]
DAMAGE_BASE = _COMBAT_CFG["damage_base"]
DAMAGE_EXPONENT_COEFFICIENT = _COMBAT_CFG["damage_exponent_coefficient"]
DAMAGE_ROLL_MIN = _COMBAT_CFG["damage_roll_min"]
DAMAGE_ROLL_MAX = _COMBAT_CFG["damage_roll_max"]
HEAL_FORTIFIED = _COMBAT_CFG["heal_fortified"]
HEAL_NORMAL = _COMBAT_CFG["heal_normal"]
# Per flanking unit adjacent to the defender (issue #59); 0 disables the rule.
FLANKING_BONUS = _COMBAT_CFG["flanking_bonus"]
# Whether ranged units project zone of control (issue #84); Civ 6 says no.
ZOC_FROM_RANGED = _COMBAT_CFG["zone_of_control_from_ranged"]

# --- City combat numbers (game/city.py City.__init__) ---

CITY_HEALTH = _CITY_CFG["health"]
CITY_DEFENSE_STRENGTH = _CITY_CFG["defense_strength"]

# City ranged attack and repair (issue #84). CITY_RANGED_BUILDING names the
# [buildings.*] entry that unlocks the bombard -- Civ 6 gates it on Walls, and
# a garrison alone does not unlock it.
CITY_RANGED_BUILDING = _CITY_CFG["ranged_building"]
# The building that marks a player's capital (#88; `[city] capital_building`):
# granted by GameEnvironment.create_city, read by `capital_only` effects
# (#116 P4). Validated against [buildings.*] below.
CAPITAL_BUILDING = _CITY_CFG["capital_building"]
CITY_RANGED_STRENGTH = _CITY_CFG["ranged_strength"]
CITY_RANGED_RANGE = _CITY_CFG["ranged_range"]
CITY_HEAL_PER_TURN = _CITY_CFG["heal_per_turn"]

# --- Buildings (issue #7) ---
#
# `City.BUILDING_COSTS` is an alias of BUILDING_COSTS below and
# `City.get_combat_strength` sums BUILDING_DEFENSE_BONUS over the buildings a
# city owns, so a building's price and its defensive effect are one entry in
# config.toml rather than a cost dict in city.py and a chain of `if building ==
# ...` literals a few lines under it.

_BUILDINGS_CFG = CFG.get("buildings", {})

# Only buildings that declare `production_cost` are producible (#88: the Palace
# is granted, never built).
BUILDING_COSTS = {
    name: table["production_cost"]
    for name, table in _BUILDINGS_CFG.items()
    if "production_cost" in table
}


def to_tenths(value, what):
    """Convert a human-readable culture value to integer tenths (issue #87).

    Culture is stored and summed as int tenths so comparisons are exact on
    every machine. A value that is not a multiple of 0.1 raises.
    """
    tenths = round(10 * value)
    if abs(10 * value - tenths) > 1e-9:
        raise ValueError(f"{what} = {value!r} is not a multiple of 0.1")
    return int(tenths)


# --- City yields (issue #116 P1, docs/progression_design.md §2.1) ---
#
# The six yield columns a [buildings.*] table may declare (district tables
# declare the same columns, parsed by district_model). Every value is int
# tenths, food and production included; civulator/game/yields.py (city_yield,
# the one consumer) turns food and production into whole points.
YIELD_COLUMNS = ("science", "culture", "gold", "faith", "food", "production")
# The four yields with a player pool and a `[<name>] base / per_pop` table.
POOL_YIELDS = ("science", "culture", "gold", "faith")


def _building_column(column):
    """name -> int tenths for every building declaring a nonzero `column`."""
    return {
        name: to_tenths(table[column], f"[buildings.{name}] {column}")
        for name, table in _BUILDINGS_CFG.items()
        if table.get(column)
    }


# Culture sources (issue #87 s1); the other five columns follow the same
# pattern (#116). Absent column = 0.
BUILDING_CULTURE = _building_column("culture")
BUILDING_SCIENCE = _building_column("science")
BUILDING_GOLD = _building_column("gold")
BUILDING_FAITH = _building_column("faith")
BUILDING_FOOD = _building_column("food")
BUILDING_PRODUCTION = _building_column("production")
BUILDING_YIELDS = {
    "science": BUILDING_SCIENCE,
    "culture": BUILDING_CULTURE,
    "gold": BUILDING_GOLD,
    "faith": BUILDING_FAITH,
    "food": BUILDING_FOOD,
    "production": BUILDING_PRODUCTION,
}

# Housing sources (issue #88 s1): same pattern; [improvements.*] housing is
# parsed by terrain_model.IMPROVEMENT_HOUSING. Values are int tenths.
BUILDING_HOUSING = {
    name: to_tenths(table["housing"], f"[buildings.{name}] housing")
    for name, table in _BUILDINGS_CFG.items()
    if table.get("housing")
}

_HOUSING_CFG = CFG["housing"]
HOUSING_WATER_FRESH = to_tenths(_HOUSING_CFG["water_fresh"], "[housing] water_fresh")
HOUSING_WATER_COASTAL = to_tenths(_HOUSING_CFG["water_coastal"], "[housing] water_coastal")
HOUSING_WATER_DRY = to_tenths(_HOUSING_CFG["water_dry"], "[housing] water_dry")
HOUSING_IMPROVEMENT_RADIUS = _HOUSING_CFG["improvement_radius"]


def parse_growth_bands(bands):
    """[[min, percent], ...] -> tuple of (min_tenths, int percent).

    Raises on a non-int percent or mins that are not strictly descending, so a
    mis-ordered table cannot silently change which band wins (issue #88 s2)."""
    parsed = []
    for band in bands:
        low, percent = band
        if isinstance(percent, bool) or not isinstance(percent, int):
            raise ValueError(f"[housing] growth_bands percent must be an int, got {percent!r}")
        parsed.append((to_tenths(low, "[housing] growth_bands min"), percent))
    for (a, _), (b, _) in zip(parsed, parsed[1:]):
        if not a > b:
            raise ValueError("[housing] growth_bands mins must be strictly descending")
    return tuple(parsed)


HOUSING_GROWTH_BANDS = parse_growth_bands(_HOUSING_CFG["growth_bands"])


def growth_percent(margin_tenths, bands=None):
    """Percent of a positive food surplus that counts toward growth, for a
    housing-minus-population margin in tenths. First matching band wins; no
    match is 0 (the hard cap)."""
    for low, percent in (HOUSING_GROWTH_BANDS if bands is None else bands):
        if margin_tenths >= low:
            return percent
    return 0


# Keys a pool table holds beside `base` / `per_pop`, read by this module itself:
# `[gold]` carries the unit-upgrade price (#116 P3, see base_upgrade_cost);
# `[gold]` and `[faith]` the purchase multiplier (#116 P5, PURCHASE_MULTIPLIER).
_POOL_TABLE_EXTRA_KEYS = {
    "gold": ("upgrade_per_production", "upgrade_base", "purchase_multiplier"),
    "faith": ("purchase_multiplier",),
}


def _pool_yield_table(name):
    """(base, per_pop) of `[<name>]` in int tenths; exactly those two keys
    plus the ones `_POOL_TABLE_EXTRA_KEYS` declares for that table."""
    table = CFG[name]
    keys = {"base", "per_pop", *_POOL_TABLE_EXTRA_KEYS.get(name, ())}
    if set(table) != keys:
        raise ValueError(f"[{name}] must have exactly the keys {sorted(keys)}, got {sorted(table)}")
    return (to_tenths(table["base"], f"[{name}] base"),
            to_tenths(table["per_pop"], f"[{name}] per_pop"))


# Per-city yield scalars (#87 culture; #116 science, gold, faith): a city
# yields base + per_pop * population of each, before its sources.
CULTURE_BASE, CULTURE_PER_POP = _pool_yield_table("culture")
SCIENCE_BASE, SCIENCE_PER_POP = _pool_yield_table("science")
GOLD_BASE, GOLD_PER_POP = _pool_yield_table("gold")
FAITH_BASE, FAITH_PER_POP = _pool_yield_table("faith")
YIELD_BASE = {"science": SCIENCE_BASE, "culture": CULTURE_BASE,
              "gold": GOLD_BASE, "faith": FAITH_BASE}
YIELD_PER_POP = {"science": SCIENCE_PER_POP, "culture": CULTURE_PER_POP,
                 "gold": GOLD_PER_POP, "faith": FAITH_PER_POP}

BUILDING_DEFENSE_BONUS = {
    name: table["defense_bonus"]
    for name, table in _BUILDINGS_CFG.items()
    if table.get("defense_bonus")
}


# --- Availability columns (#116 P2, docs/progression_design.md §4.1, §6.2) ---
#
# Every key a table may carry: a typo in a gating column (`requires_techs`)
# must raise rather than silently leave the item ungated. A later patch
# adding a column adds it here, as district_model's _DISTRICT_KEYS.
UNIT_KEYS = frozenset({
    "max_movement", "combat_strength", "ranged_strength", "range",
    "production_cost", "requires_tech", "requires_civic",
    "combat_class", "era", "maintenance", "purchasable", "upgrades_to",
})
BUILDING_KEYS = frozenset({
    "production_cost", "defense_bonus", "housing", *YIELD_COLUMNS,
    "requires_tech", "requires_district", "requires_building",
    "requires_civic", "requires_government_tier", "maintenance",
    "purchasable", "effects",  # #116 P4
})


def _check_keys(tables, allowed, table_name):
    for name, table in tables.items():
        unknown = set(table) - allowed
        if unknown:
            raise ValueError(f"[{table_name}.{name}]: unknown key(s) {sorted(unknown)}")


def _name_column(tables, column, table_name):
    """name -> the string `column` of every table declaring it."""
    out = {}
    for name, table in tables.items():
        if column in table:
            value = table[column]
            if not isinstance(value, str) or not value:
                raise ValueError(f"[{table_name}.{name}] {column} must be a name, got {value!r}")
            out[name] = value
    return out


def parse_unit_gates(units_cfg):
    """`[units.*]` availability columns -> (requires_tech, requires_civic),
    each name -> value for the units declaring it. `requires_tech` must name a
    tech and `requires_civic` a civic (#116 P4)."""
    _check_keys(units_cfg, UNIT_KEYS, "units")
    requires_tech = {
        name: validate_tech_name(tech, f"[units.{name}]")
        for name, tech in _name_column(units_cfg, "requires_tech", "units").items()
    }
    requires_civic = {
        name: validate_civic_name(civic, f"[units.{name}]")
        for name, civic in _name_column(units_cfg, "requires_civic", "units").items()
    }
    return requires_tech, requires_civic


def _purchasable(table, where):
    """A `purchasable` column -> tuple of PURCHASE_RESOURCES, default
    `("gold",)`; `[]` = never bought. Distinct entries only."""
    resources = table.get("purchasable", ["gold"])
    if (not isinstance(resources, list)
            or any(r not in PURCHASE_RESOURCES for r in resources)
            or len(set(resources)) != len(resources)):
        raise ValueError(
            f"{where}: purchasable must be a list of distinct entries of {PURCHASE_RESOURCES}, "
            f"got {resources!r}")
    return tuple(resources)


def parse_building_gates(buildings_cfg):
    """`[buildings.*]` availability columns -> a dict of name -> value maps:
    `requires_tech` (a tech), `requires_district` (a district name, checked by
    district_model), `requires_building` (another configured building; the
    chain may not loop back), `requires_civic` (a civic) and
    `requires_government_tier` (an int some government reaches; #116 P4),
    `maintenance` (int tenths of gold per turn), `purchasable` (every
    building, default `("gold",)`) and `effects` (the raw list, for every
    building declaring one; effects.py validates it)."""
    _check_keys(buildings_cfg, BUILDING_KEYS, "buildings")
    requires_tech = {
        name: validate_tech_name(tech, f"[buildings.{name}]")
        for name, tech in _name_column(buildings_cfg, "requires_tech", "buildings").items()
    }
    requires_building = _name_column(buildings_cfg, "requires_building", "buildings")
    for name, other in requires_building.items():
        if other not in buildings_cfg:
            raise ValueError(f"[buildings.{name}] requires_building {other!r} is not a building")
        seen = {name}
        while other is not None:
            if other in seen:
                raise ValueError(f"[buildings.{name}] requires_building loops back through {other!r}")
            seen.add(other)
            other = requires_building.get(other)
    maintenance = {}
    for name, table in buildings_cfg.items():
        if "maintenance" in table:
            tenths = to_tenths(table["maintenance"], f"[buildings.{name}] maintenance")
            if tenths < 0:
                raise ValueError(f"[buildings.{name}] maintenance must be >= 0")
            if tenths:
                maintenance[name] = tenths
    return {
        "requires_tech": requires_tech,
        "requires_district": _name_column(buildings_cfg, "requires_district", "buildings"),
        "requires_building": requires_building,
        "requires_civic": {
            name: validate_civic_name(civic, f"[buildings.{name}]")
            for name, civic in _name_column(buildings_cfg, "requires_civic", "buildings").items()
        },
        "requires_government_tier": {
            name: validate_government_tier(table["requires_government_tier"], f"[buildings.{name}]")
            for name, table in buildings_cfg.items() if "requires_government_tier" in table
        },
        "maintenance": maintenance,
        "purchasable": {name: _purchasable(table, f"[buildings.{name}]")
                        for name, table in buildings_cfg.items()},
        "effects": {name: _raw_effects(table, f"[buildings.{name}]")
                    for name, table in buildings_cfg.items() if "effects" in table},
    }


def _raw_effects(table, where):
    effects = table["effects"]
    if not isinstance(effects, list):
        raise ValueError(f"{where}: effects must be a list, got {effects!r}")
    return tuple(effects)


# --- Combat classes, prices and upgrades (#116 P3, docs/progression_design.md §6) ---

# The classes a unit may declare. `support` (siege support) and `civilian` have
# no attack; the encoder gives both no class channel.
COMBAT_CLASSES = ("melee", "anti_cavalry", "ranged", "light_cavalry",
                  "heavy_cavalry", "siege", "support", "civilian")
# The resources a unit or building may be bought with (#116 P5: each has a
# `purchase_multiplier` in its pool table and a Player pool of the same name).
PURCHASE_RESOURCES = ("gold", "faith")
# Which strength a [combat] class_bonuses row modifies: `Unit.get_combat_strength`
# reads the STRENGTH_COMBAT rows, `Unit.get_ranged_strength` the STRENGTH_RANGED
# ones. Named so the combat code carries no string literal of its own.
STRENGTH_COMBAT = "combat"
STRENGTH_RANGED = "ranged"
STRENGTH_KINDS = (STRENGTH_COMBAT, STRENGTH_RANGED)
_CLASS_BONUS_KEYS = frozenset({"unit", "target", "amount", "strength"})


class ClassBonus(NamedTuple):
    """One validated `[combat] class_bonuses` row. `unit` and `target` are a
    combat class or a single unit type name."""
    unit: str
    target: str
    amount: int
    strength: str


def _unit_name_or_class(value, unit_names, where):
    if not isinstance(value, str) or value not in (*COMBAT_CLASSES, *unit_names):
        raise ValueError(
            f"{where}: {value!r} is neither a combat class {COMBAT_CLASSES} nor a unit type"
        )
    return value


def parse_unit_columns(units_cfg):
    """`[units.*]` class, era, price and upgrade columns -> a dict of maps:

    - `combat_class`: name -> one of COMBAT_CLASSES (required on every unit);
    - `era`: name -> one of research_model.ERAS (required);
    - `maintenance`: name -> int tenths of gold per turn, nonzero entries only
      (required on every unit, so a forgotten price is a load error and not a
      silently free unit; >= 0);
    - `purchasable`: name -> tuple of PURCHASE_RESOURCES (default `("gold",)`);
    - `upgrades_to`: name -> the unit type it upgrades into, for the units
      declaring one (a configured unit other than itself; chains may not loop).

    A unit type may not share a name with a combat class: a `class_bonuses`
    row names either, and a clash would be ambiguous.
    """
    _check_keys(units_cfg, UNIT_KEYS, "units")
    combat_class, era, maintenance, purchasable, upgrades_to = {}, {}, {}, {}, {}
    for name, table in units_cfg.items():
        where = f"[units.{name}]"
        if name in COMBAT_CLASSES:
            raise ValueError(f"{where}: a unit type may not be named like a combat class")
        for column in ("combat_class", "era", "maintenance"):
            if column not in table:
                raise ValueError(f"{where}: `{column}` is required")
        if table["combat_class"] not in COMBAT_CLASSES:
            raise ValueError(
                f"{where}: combat_class {table['combat_class']!r} not in {COMBAT_CLASSES}")
        combat_class[name] = table["combat_class"]
        if table["era"] not in ERAS:
            raise ValueError(f"{where}: era {table['era']!r} not in {ERAS}")
        era[name] = table["era"]
        tenths = to_tenths(table["maintenance"], f"{where} maintenance")
        if tenths < 0:
            raise ValueError(f"{where}: maintenance must be >= 0")
        if tenths:
            maintenance[name] = tenths
        purchasable[name] = _purchasable(table, where)
    upgrades_to = _name_column(units_cfg, "upgrades_to", "units")
    for name, target in upgrades_to.items():
        if target not in units_cfg:
            raise ValueError(f"[units.{name}] upgrades_to {target!r} is not a unit type")
        seen = {name}
        while target is not None:
            if target in seen:
                raise ValueError(f"[units.{name}] upgrades_to loops back through {target!r}")
            seen.add(target)
            target = upgrades_to.get(target)
    return {"combat_class": combat_class, "era": era, "maintenance": maintenance,
            "purchasable": purchasable, "upgrades_to": upgrades_to}


def parse_class_bonuses(rows, unit_names):
    """`[combat] class_bonuses` -> a tuple of ClassBonus, in config order.

    Each row is exactly `{ unit, target, amount, strength }`: `unit` and
    `target` name a combat class or a configured unit type, `amount` is an int
    (negative = penalty), `strength` is one of STRENGTH_KINDS. A malformed row
    raises, so a typo cannot silently drop a modifier.
    """
    if not isinstance(rows, list):
        raise ValueError("[combat] class_bonuses must be a list of rows")
    parsed = []
    for index, row in enumerate(rows):
        where = f"[combat] class_bonuses[{index}]"
        if not isinstance(row, dict) or set(row) != _CLASS_BONUS_KEYS:
            raise ValueError(f"{where} must have exactly the keys {sorted(_CLASS_BONUS_KEYS)}")
        amount = row["amount"]
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise ValueError(f"{where}: amount must be an int, got {amount!r}")
        if row["strength"] not in STRENGTH_KINDS:
            raise ValueError(f"{where}: strength {row['strength']!r} not in {STRENGTH_KINDS}")
        parsed.append(ClassBonus(
            unit=_unit_name_or_class(row["unit"], unit_names, f"{where} unit"),
            target=_unit_name_or_class(row["target"], unit_names, f"{where} target"),
            amount=amount,
            strength=row["strength"],
        ))
    return tuple(parsed)


# The unit types and buildings that exist (#116 P2): the one accessor for
# "is this a configured unit / building", so availability never re-reads CFG.
UNIT_NAMES = frozenset(_UNITS_CFG)
BUILDING_NAMES = frozenset(_BUILDINGS_CFG)

_UNIT_COLUMNS = parse_unit_columns(_UNITS_CFG)
# The one class registry (#116 P3): unit type -> combat class. Every combat
# rule that used to name units reads this instead.
COMBAT_CLASS = _UNIT_COLUMNS["combat_class"]
UNIT_ERA = _UNIT_COLUMNS["era"]
# Gold per turn in int tenths (the treasury's unit), nonzero entries only,
# like BUILDING_MAINTENANCE; deducted in the owner's economy phase
# (civulator/game/maintenance.py, #116 P5).
UNIT_MAINTENANCE = _UNIT_COLUMNS["maintenance"]
UNIT_PURCHASABLE = _UNIT_COLUMNS["purchasable"]
UPGRADES_TO = _UNIT_COLUMNS["upgrades_to"]

# Unit types in the siege class (issue #66): derived from `combat_class`, no
# longer a boolean column of its own (#116 P3).
SIEGE_CLASS = frozenset(name for name, cls in COMBAT_CLASS.items() if cls == "siege")

# --- Faith-purchase categories (#116 P5, design §3, §7.3, §10.1) ---
#
# The categories a `faith_purchase` effect may unlock (effects.py validates
# its `categories` against this tuple). `land_military` = every unit of a
# fighting combat class -- all but `support` and `civilian` (every unit is a
# land unit here; Civ 6: "land military units").
FAITH_CATEGORY_LAND_MILITARY = "land_military"
FAITH_CATEGORIES = (FAITH_CATEGORY_LAND_MILITARY,)
_LAND_MILITARY_CLASSES = frozenset(c for c in COMBAT_CLASSES if c not in ("support", "civilian"))


def faith_category(unit_type):
    """The faith-purchase category of `unit_type`: FAITH_CATEGORY_LAND_MILITARY
    for a unit of a fighting class (melee, anti_cavalry, ranged,
    light_cavalry, heavy_cavalry, siege), None otherwise (and for a name that
    is no unit). Read by civulator/game/purchasing.py."""
    if COMBAT_CLASS.get(unit_type) in _LAND_MILITARY_CLASSES:
        return FAITH_CATEGORY_LAND_MILITARY
    return None

# `[combat] class_bonuses` (see parse_class_bonuses and config.toml): the
# class-pair modifiers `Unit.get_combat_strength` / `get_ranged_strength` read.
CLASS_BONUSES = parse_class_bonuses(_COMBAT_CFG["class_bonuses"], UNIT_NAMES)


def _matches(spec, unit_type):
    """Whether a class_bonuses `unit`/`target` entry names `unit_type`, by its
    own name or by its combat class. `COMBAT_CLASS` is read at call time."""
    return spec == unit_type or spec == COMBAT_CLASS.get(unit_type)


def class_bonus_amounts(strength, unit_type, target_type):
    """The amounts, in config order, of every `strength` (STRENGTH_COMBAT or
    STRENGTH_RANGED) row of CLASS_BONUSES that applies to `unit_type` acting against
    `target_type`. The caller adds them one by one, so the float arithmetic is
    the same as applying the modifiers sequentially, as before #116 P3."""
    return [
        row.amount
        for row in CLASS_BONUSES
        if row.strength == strength
        and _matches(row.unit, unit_type)
        and _matches(row.target, target_type)
    ]


# --- Unit upgrades (#116 P3, docs/progression_design.md §6.4) ---

UPGRADE_PER_PRODUCTION = CFG["gold"]["upgrade_per_production"]
UPGRADE_BASE = CFG["gold"]["upgrade_base"]
for _key, _value in (("upgrade_per_production", UPGRADE_PER_PRODUCTION),
                     ("upgrade_base", UPGRADE_BASE)):
    if isinstance(_value, bool) or not isinstance(_value, int) or _value < 0:
        raise ValueError(f"[gold] {_key} must be a whole number >= 0, got {_value!r}")


# --- Purchasing (#116 P5, docs/progression_design.md §7.3) ---

# resource -> how many of it one production point costs (Civ 6: gold 4,
# faith 2). One entry per PURCHASE_RESOURCES name; whole numbers >= 1.
PURCHASE_MULTIPLIER = {resource: CFG[resource]["purchase_multiplier"]
                       for resource in PURCHASE_RESOURCES}
for _resource, _value in PURCHASE_MULTIPLIER.items():
    if isinstance(_value, bool) or not isinstance(_value, int) or _value < 1:
        raise ValueError(f"[{_resource}] purchase_multiplier must be a whole number >= 1, "
                         f"got {_value!r}")


def base_upgrade_cost(unit_type):
    """Whole gold to upgrade a `unit_type` into its `upgrades_to`, before any
    effect: `upgrade_per_production * (target cost - unit cost) + upgrade_base`
    (a target no dearer than the unit adds only the base). None when the unit
    has no upgrade. Civ 6 states no formula; this reproduces its one data
    point, Slinger -> Archer = 60 gold (35 -> 60 production)."""
    target = UPGRADES_TO.get(unit_type)
    if target is None:
        return None
    gap = max(0, PRODUCTION_COST[target] - PRODUCTION_COST[unit_type])
    return UPGRADE_PER_PRODUCTION * gap + UPGRADE_BASE

UNIT_REQUIRES_TECH, UNIT_REQUIRES_CIVIC = parse_unit_gates(_UNITS_CFG)
_BUILDING_GATES = parse_building_gates(_BUILDINGS_CFG)
BUILDING_REQUIRES_TECH = _BUILDING_GATES["requires_tech"]
BUILDING_REQUIRES_DISTRICT = _BUILDING_GATES["requires_district"]
BUILDING_REQUIRES_BUILDING = _BUILDING_GATES["requires_building"]
BUILDING_REQUIRES_CIVIC = _BUILDING_GATES["requires_civic"]
BUILDING_REQUIRES_GOVERNMENT_TIER = _BUILDING_GATES["requires_government_tier"]
# Gold per turn in int tenths (the treasury's unit), nonzero entries only;
# deducted in the owner's economy phase (civulator/game/maintenance.py, #116 P5).
BUILDING_MAINTENANCE = _BUILDING_GATES["maintenance"]
# Resources each building may be bought with (#116 P4, design §7.3): every
# configured building, default ("gold",), () = never bought. Read by
# civulator/game/purchasing.py (#116 P5).
BUILDING_PURCHASABLE = _BUILDING_GATES["purchasable"]
# Raw `effects` lists (building -> tuple of dicts), for the buildings that
# declare one; validated and interpreted only by civulator/effects.py.
BUILDING_EFFECTS = _BUILDING_GATES["effects"]

if CAPITAL_BUILDING not in BUILDING_NAMES:
    raise ValueError(f"[city] capital_building {CAPITAL_BUILDING!r} is not a building")
