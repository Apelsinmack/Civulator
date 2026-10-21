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
    anti_cavalry_bonus = 10
    ...

This module is the only interpreter of `[units.*]` / `[combat]` / `[city]`
health+defense / `[buildings.*]` / the per-city yield tables `[science]`,
`[culture]`, `[gold]`, `[faith]` (issue #116): civulator/game/unit.py and
civulator/game/city.py import
from it and must not read those CFG tables directly, and no new hardcoded
combat number should appear anywhere else (CLAUDE.md canonical-systems
table). `NUM_UNIT_SLOTS`/`UNIT_SLOT` and `MOVEMENT_DOMAIN` are deliberately
NOT here — see the comments on those tables in game/unit.py for why.

tests/test_unit_config_identity.py is the bit-identity gate for #64: it
pins every value below as a hardcoded literal, independent of this module
and of config.toml, so this move is provably a refactor and not a balance
change.
"""

from .config import CFG

_UNITS_CFG = CFG.get("units", {})
_COMBAT_CFG = CFG.get("combat", {})
_CITY_CFG = CFG.get("city", {})

# --- The five per-unit-type data tables (game/unit.py Unit class attrs) ---

MAX_MOVEMENT = {name: table["max_movement"] for name, table in _UNITS_CFG.items()}
BASE_COMBAT_STRENGTH = {name: table["combat_strength"] for name, table in _UNITS_CFG.items()}
BASE_RANGED_STRENGTH = {name: table["ranged_strength"] for name, table in _UNITS_CFG.items()}
RANGE_VALUES = {name: table["range"] for name, table in _UNITS_CFG.items()}
PRODUCTION_COST = {name: table["production_cost"] for name, table in _UNITS_CFG.items()}

# Unit types in the siege class (issue #66). Optional `siege_class` key in a
# `[units.*]` table; absent means false. The siege class is exempt from
# RANGED_CITY_PENALTY below — breaking fortifications is what the class is for.
SIEGE_CLASS = frozenset(
    name for name, table in _UNITS_CFG.items() if table.get("siege_class", False)
)

# --- Combat formula / modifier constants (get_combat_strength, get_ranged_strength,
# calculate_damage, heal — game/unit.py) ---

ANTI_CAVALRY_BONUS = _COMBAT_CFG["anti_cavalry_bonus"]
MELEE_VS_SPEARMAN_BONUS = _COMBAT_CFG["melee_vs_spearman_bonus"]
RANGED_CITY_PENALTY = _COMBAT_CFG["ranged_city_penalty"]
ARCHER_VS_HORSEMAN_PENALTY = _COMBAT_CFG["archer_vs_horseman_penalty"]
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


def _pool_yield_table(name):
    """(base, per_pop) of `[<name>]` in int tenths; exactly those two keys."""
    table = CFG[name]
    keys = {"base", "per_pop"}
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
