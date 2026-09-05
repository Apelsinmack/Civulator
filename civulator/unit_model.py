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
health+defense: civulator/game/unit.py and civulator/game/city.py import
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

# --- City combat numbers (game/city.py City.__init__) ---

CITY_HEALTH = _CITY_CFG["health"]
CITY_DEFENSE_STRENGTH = _CITY_CFG["defense_strength"]
