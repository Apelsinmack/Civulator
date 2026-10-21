"""The one interpreter of `effects` lists (issue #116 P4, docs/progression_design.md
§3, §5 and "v2 fixes").

Any tech, civic, government, policy, building or district table may declare

    effects = [
        { kind = "production_percent", target = { unit = "Settler" }, percent = 50 },
        { kind = "combat_strength", applies_to = ["melee"], amount = 4 },
    ]

This module validates every such list at import and answers one question at
run time: which entries are in force for a player (and a city) right now
(`active_effects`). Each kind has exactly one consumer (`CONSUMERS`), which
reads its entries through `active_effects` and nothing else; a new kind is a
new schema here and one consumer, never a second reader of an old one.

Load order (v2 fixes, "Load order and config ownership"): research_model,
then unit_model / terrain_model / district_model, then THIS module, then
`civulator/game`. Validation reads the parsed specs of those registries --
never `CFG` -- and resolves every name an effect uses against them: a unit,
building, district, combat class, era, rule or resource that does not exist
raises. Nothing here imports `civulator.game` at module level; the one game
accessor it needs at run time (`game/districts.district_spec`, so a
synthetic district registry is the one every reader sees) is imported on
first use.

Scope. Every entry has `scope = "player" | "city"`: buildings and districts
default to "city" (the effect holds in that city only), every other source
to "player" (it holds in every city of the player, and for its units). A
policy, government, civic or tech may not declare "city" -- it has no city.

What is in force (`active_effects`, deterministic order, recomputed on every
call, never cached): the government's entries; the slotted policies that are
legal now (`policies_in_force`), in loadout order; the effects of every
known civic, then every known tech, in completion order; the player-scoped
entries of every building and every complete district (wonders are
districts, #116 P6) in the player's cities (`player.cities` order, then
`city.buildings` / `city.districts` order); and, when a city is given, that
city's city-scoped building entries and complete-district entries in the
same order.

Pure: reads parsed specs and live state; mutates nothing (the parse memo
below caches validated entries per raw list, never game state).
"""

from dataclasses import dataclass
from types import MappingProxyType

from . import district_model, research_model, unit_model

# --- Vocabulary -----------------------------------------------------------------

# Where an effects list may live.
SOURCE_TECH = "tech"
SOURCE_CIVIC = "civic"
SOURCE_GOVERNMENT = "government"
SOURCE_POLICY = "policy"
SOURCE_BUILDING = "building"
SOURCE_DISTRICT = "district"
SOURCES = (SOURCE_TECH, SOURCE_CIVIC, SOURCE_GOVERNMENT, SOURCE_POLICY,
           SOURCE_BUILDING, SOURCE_DISTRICT)
# Sources that stand in a city and may therefore hold a city-scoped effect.
_CITY_SOURCES = (SOURCE_BUILDING, SOURCE_DISTRICT)

SCOPE_PLAYER = "player"
SCOPE_CITY = "city"
SCOPES = (SCOPE_PLAYER, SCOPE_CITY)

# The closed set of kinds (design §3 as amended by v2 and §5.2).
KIND_CITY_YIELD = "city_yield"
KIND_PRODUCTION_PERCENT = "production_percent"
KIND_ADJACENCY_PERCENT = "adjacency_percent"
KIND_COMBAT_STRENGTH = "combat_strength"
KIND_CITY_RANGED_STRENGTH = "city_ranged_strength"
KIND_UNIT_MAINTENANCE_DELTA = "unit_maintenance_delta"
KIND_UPGRADE_COST_PERCENT = "upgrade_cost_percent"
KIND_PURCHASE_PERCENT = "purchase_percent"
KIND_FAITH_PURCHASE = "faith_purchase"
KIND_TRADE_ROUTE_CAPACITY = "trade_route_capacity"
KIND_ROUTE_YIELD = "route_yield"
KIND_LOYALTY = "loyalty"
KIND_GROWTH_PERCENT = "growth_percent"
KIND_POLICY_SLOTS = "policy_slots"
KIND_HOUSING_IF_DISTRICTS = "housing_if_districts"
KIND_HOUSING_WITH_BUILDING = "housing_with_building"
KIND_ENABLES = "enables"
KIND_FREE_UNITS = "free_units"
KIND_FREE_TECH = "free_tech"
KIND_FREE_CIVIC = "free_civic"
KIND_FREE_POPULATION = "free_population"

# The one consumer of each kind (design §3, "consumed by"). The kinds wired in
# #116 P4 name their reader; the others are validated now and name the patch
# whose consumer reads them -- each has a documented stub where it will live.
CONSUMERS = {
    KIND_CITY_YIELD: "game/yields.py city_yield (food and production reach "
                     "calculate_food / calculate_production through it)",
    KIND_PRODUCTION_PERCENT: "game/city.py City.calculate_production",
    KIND_ADJACENCY_PERCENT: "game/yields.py city_yield -> district_yields(percent_by_district)",
    KIND_COMBAT_STRENGTH: "game/unit.py Unit.get_combat_strength / get_ranged_strength; "
                          "game/city.py City.get_combat_strength (applies_to city)",
    KIND_CITY_RANGED_STRENGTH: "game/city.py City.get_ranged_strength",
    KIND_UPGRADE_COST_PERCENT: "game/upgrades.py upgrade_cost (_upgrade_cost_percent)",
    KIND_POLICY_SLOTS: "effects.slot_counts",
    KIND_HOUSING_IF_DISTRICTS: "game/housing.py housing",
    KIND_HOUSING_WITH_BUILDING: "game/housing.py housing",
    KIND_ENABLES: "effects.rule_enabled (flanking: Unit.get_combat_strength)",
    KIND_UNIT_MAINTENANCE_DELTA: "#116 P5: maintenance (GameEnvironment._unit_maintenance_delta stub)",
    KIND_PURCHASE_PERCENT: "#116 P5: purchase_cost (GameEnvironment._purchase_percent stub)",
    KIND_FAITH_PURCHASE: "#116 P5: can_purchase (GameEnvironment._faith_purchase_categories stub)",
    KIND_TRADE_ROUTE_CAPACITY: "#116 P5: route_capacity (GameEnvironment._route_capacity_bonus stub)",
    KIND_ROUTE_YIELD: "#116 P5: the route term of city_yield (game/yields.py _route_yield stub)",
    KIND_LOYALTY: "#116 P7: loyalty_sources (game/yields.py _loyalty_sources stub)",
    KIND_GROWTH_PERCENT: "#116 P6: the growth bucket (City._growth_percent stub)",
    KIND_FREE_UNITS: "#116 P6: complete_district one-shots (GameEnvironment._one_shot_effects stub)",
    KIND_FREE_TECH: "#116 P6: complete_district one-shots (GameEnvironment._one_shot_effects stub)",
    KIND_FREE_CIVIC: "#116 P6: complete_district one-shots (GameEnvironment._one_shot_effects stub)",
    KIND_FREE_POPULATION: "#116 P6: complete_district one-shots (GameEnvironment._one_shot_effects stub)",
}
KINDS = tuple(CONSUMERS)
# Kinds validated in P4 whose consumer lands later (the stubs above).
DEFERRED_KINDS = frozenset({
    KIND_UNIT_MAINTENANCE_DELTA, KIND_PURCHASE_PERCENT, KIND_FAITH_PURCHASE,
    KIND_TRADE_ROUTE_CAPACITY, KIND_ROUTE_YIELD, KIND_LOYALTY, KIND_GROWTH_PERCENT,
    KIND_FREE_UNITS, KIND_FREE_TECH, KIND_FREE_CIVIC, KIND_FREE_POPULATION,
})
# One-shot kinds fire once when a wonder completes (design §3, §9.3), so they
# belong on district-registry entries only.
ONE_SHOT_KINDS = frozenset({KIND_FREE_UNITS, KIND_FREE_TECH, KIND_FREE_CIVIC,
                            KIND_FREE_POPULATION})
# Kinds whose consumer takes no city: a city-scoped entry would never be read.
_PLAYER_ONLY_KINDS = frozenset({KIND_POLICY_SLOTS, KIND_ENABLES})

# The rules an `enables` effect may switch on, each gated where it is applied.
RULE_FLANKING = "flanking"  # #59, Unit.get_combat_strength
RULES = (RULE_FLANKING,)

# `combat_strength` applies_to: the six fighting classes, every unit, or the city.
APPLIES_ALL = "all"
APPLIES_CITY = "city"
COMBAT_STRENGTH_CLASSES = tuple(c for c in unit_model.COMBAT_CLASSES
                                if c not in ("support", "civilian"))
_APPLIES_TO = (*COMBAT_STRENGTH_CLASSES, APPLIES_ALL, APPLIES_CITY)

# Categories a `faith_purchase` effect unlocks (consumed by #116 P5).
FAITH_PURCHASE_CATEGORIES = ("land_military",)

# What a production item is, for a `production_percent` target.
ITEM_UNIT = "unit"
ITEM_BUILDING = "building"
ITEM_KINDS = (ITEM_UNIT, ITEM_BUILDING, *district_model.KINDS)
_TARGET_KEYS = ("unit", "unit_class", "unit_era", "building", "in_district",
                "district", "kind")


@dataclass(frozen=True)
class Effect:
    """One validated `effects` entry. `attrs` holds its normalised attributes
    (yields and housing in int tenths, name lists as tuples); index it like a
    mapping (`effect["percent"]`). `source` is (source kind, source name)."""

    kind: str
    scope: str
    source: tuple
    attrs: MappingProxyType

    def __getitem__(self, key):
        return self.attrs[key]

    def get(self, key, default=None):
        return self.attrs.get(key, default)


# --- Attribute validators ------------------------------------------------------------


def _int(value, where):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an int, got {value!r}")
    return value


def _positive_int(value, where):
    if _int(value, where) <= 0:
        raise ValueError(f"{where} must be positive, got {value!r}")
    return value


def _non_negative_int(value, where):
    if _int(value, where) < 0:
        raise ValueError(f"{where} must be >= 0, got {value!r}")
    return value


def _bool(value, where):
    if not isinstance(value, bool):
        raise ValueError(f"{where} must be true or false, got {value!r}")
    return value


def _tenths(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number, got {value!r}")
    return unit_model.to_tenths(value, where)


def _names(value, known, label, where):
    """A name or a non-empty list of distinct names, each in `known` -> tuple."""
    names = [value] if isinstance(value, str) else value
    if (not isinstance(names, list) or not names
            or not all(isinstance(n, str) for n in names) or len(set(names)) != len(names)):
        raise ValueError(f"{where} must be a {label} or a list of distinct {label}s, got {value!r}")
    missing = [n for n in names if n not in known]
    if missing:
        raise ValueError(f"{where} names no {label}: {missing}")
    return tuple(names)


def _name(value, known, label, where):
    if not isinstance(value, str) or value not in known:
        raise ValueError(f"{where} names no {label}: {value!r}")
    return value


def _keys(raw, allowed, required, where):
    unknown = set(raw) - set(allowed)
    if unknown:
        raise ValueError(f"{where}: unknown attribute(s) {sorted(unknown)}")
    missing = set(required) - set(raw)
    if missing:
        raise ValueError(f"{where}: missing attribute(s) {sorted(missing)}")


# --- One parser per kind (raw attributes -> normalised dict) -------------------------


def _yield_map(raw, where):
    """The yield attributes of `raw` -> {yield: tenths}; at least one."""
    yields = {name: _tenths(raw[name], f"{where} {name}")
              for name in unit_model.YIELD_COLUMNS if name in raw}
    if not yields:
        raise ValueError(f"{where}: names no yield of {unit_model.YIELD_COLUMNS}")
    return yields


def _parse_city_yield(raw, where, ctx):
    _keys(raw, (*unit_model.YIELD_COLUMNS, "capital_only", "per_district"), (), where)
    return {"yields": MappingProxyType(_yield_map(raw, where)),
            "capital_only": _bool(raw.get("capital_only", False), f"{where} capital_only"),
            "per_district": _bool(raw.get("per_district", False), f"{where} per_district")}


def _parse_target(target, where, ctx):
    """A `production_percent` target: a table of _TARGET_KEYS, every key a
    condition the produced item must meet. Raises if a name is unknown or
    the conditions exclude every kind of item (e.g. a unit class AND a
    building)."""
    if not isinstance(target, dict) or not target:
        raise ValueError(f"{where} must be a non-empty table of {_TARGET_KEYS}")
    _keys(target, _TARGET_KEYS, (), where)
    districts = ctx["districts"]
    out, kinds = {}, set(ITEM_KINDS)
    if "unit" in target:
        out["unit"] = _names(target["unit"], unit_model.UNIT_NAMES, "unit", f"{where} unit")
        kinds &= {ITEM_UNIT}
    if "unit_class" in target:
        out["unit_class"] = _names(target["unit_class"], unit_model.COMBAT_CLASSES,
                                   "combat class", f"{where} unit_class")
        kinds &= {ITEM_UNIT}
    if "unit_era" in target:
        out["unit_era"] = _names(target["unit_era"], research_model.ERAS, "era",
                                 f"{where} unit_era")
        kinds &= {ITEM_UNIT}
    if "building" in target:
        out["building"] = _names(target["building"], unit_model.BUILDING_NAMES, "building",
                                 f"{where} building")
        kinds &= {ITEM_BUILDING}
    if "in_district" in target:
        out["in_district"] = _names(target["in_district"], districts, "district",
                                    f"{where} in_district")
        kinds &= {ITEM_BUILDING}
    if "district" in target:
        out["district"] = _names(target["district"], districts, "district", f"{where} district")
        kinds &= {districts[d].kind for d in out["district"]}
    if "kind" in target:
        out["kind"] = _name(target["kind"], ITEM_KINDS, "item kind", f"{where} kind")
        kinds &= {out["kind"]}
    if not kinds:
        raise ValueError(f"{where}: the conditions {sorted(target)} exclude every item")
    return MappingProxyType(out)


def _parse_production_percent(raw, where, ctx):
    _keys(raw, ("target", "percent"), ("target", "percent"), where)
    return {"target": _parse_target(raw["target"], f"{where} target", ctx),
            "percent": _int(raw["percent"], f"{where} percent")}


def _parse_adjacency_percent(raw, where, ctx):
    _keys(raw, ("district", "percent"), ("district", "percent"), where)
    district = _name(raw["district"], ctx["districts"], "district", f"{where} district")
    if ctx["districts"][district].adjacency_yield == "none":
        raise ValueError(f"{where}: district {district!r} has no adjacency yield")
    return {"district": district, "percent": _int(raw["percent"], f"{where} percent")}


def _parse_combat_strength(raw, where, ctx):
    _keys(raw, ("applies_to", "amount"), ("applies_to", "amount"), where)
    return {"applies_to": _names(raw["applies_to"], _APPLIES_TO, "combat strength target",
                                 f"{where} applies_to"),
            "amount": _int(raw["amount"], f"{where} amount")}


def _amount_only(check):
    def parse(raw, where, ctx):
        _keys(raw, ("amount",), ("amount",), where)
        return {"amount": check(raw["amount"], f"{where} amount")}
    return parse


def _percent_only(raw, where, ctx):
    _keys(raw, ("percent",), ("percent",), where)
    return {"percent": _int(raw["percent"], f"{where} percent")}


def _parse_purchase_percent(raw, where, ctx):
    _keys(raw, ("resource", "percent"), ("resource", "percent"), where)
    return {"resource": _name(raw["resource"], unit_model.PURCHASE_RESOURCES, "resource",
                              f"{where} resource"),
            "percent": _int(raw["percent"], f"{where} percent")}


def _parse_faith_purchase(raw, where, ctx):
    _keys(raw, ("categories",), ("categories",), where)
    return {"categories": _names(raw["categories"], FAITH_PURCHASE_CATEGORIES,
                                 "faith-purchase category", f"{where} categories")}


def _parse_route_yield(raw, where, ctx):
    _keys(raw, (*unit_model.YIELD_COLUMNS, "international_only"), (), where)
    return {"yields": MappingProxyType(_yield_map(raw, where)),
            "international_only": _bool(raw.get("international_only", False),
                                        f"{where} international_only")}


def _parse_loyalty(raw, where, ctx):
    _keys(raw, ("amount", "range", "requires_garrison", "per_population"), ("amount",), where)
    return {"amount": _int(raw["amount"], f"{where} amount"),
            "range": _non_negative_int(raw.get("range", 0), f"{where} range"),
            "requires_garrison": _bool(raw.get("requires_garrison", False),
                                       f"{where} requires_garrison"),
            "per_population": _bool(raw.get("per_population", False), f"{where} per_population")}


def _parse_policy_slots(raw, where, ctx):
    _keys(raw, research_model.POLICY_TYPES, (), where)
    if not raw:
        raise ValueError(f"{where}: names no slot type of {research_model.POLICY_TYPES}")
    return {"slots": MappingProxyType({
        t: _non_negative_int(raw.get(t, 0), f"{where} {t}") for t in research_model.POLICY_TYPES
    })}


def _parse_housing_if_districts(raw, where, ctx):
    _keys(raw, ("amount", "min_districts"), ("amount", "min_districts"), where)
    return {"amount": _tenths(raw["amount"], f"{where} amount"),
            "min_districts": _non_negative_int(raw["min_districts"], f"{where} min_districts")}


def _parse_housing_with_building(raw, where, ctx):
    _keys(raw, ("building", "amount"), ("building", "amount"), where)
    return {"building": _name(raw["building"], unit_model.BUILDING_NAMES, "building",
                              f"{where} building"),
            "amount": _tenths(raw["amount"], f"{where} amount")}


def _parse_enables(raw, where, ctx):
    _keys(raw, ("rules",), ("rules",), where)
    if not isinstance(raw["rules"], list):
        raise ValueError(f"{where} rules must be a list, got {raw['rules']!r}")
    return {"rules": _names(raw["rules"], RULES, "rule", f"{where} rules")}


def _parse_free_units(raw, where, ctx):
    _keys(raw, ("units",), ("units",), where)
    rows = raw["units"]
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{where} units must be a non-empty list of {{ unit, count }}")
    parsed = []
    for i, row in enumerate(rows):
        at = f"{where} units[{i}]"
        if not isinstance(row, dict):
            raise ValueError(f"{at} must be a table {{ unit, count }}")
        _keys(row, ("unit", "count"), ("unit", "count"), at)
        parsed.append((_name(row["unit"], unit_model.UNIT_NAMES, "unit", f"{at} unit"),
                       _positive_int(row["count"], f"{at} count")))
    return {"units": tuple(parsed)}


def _parse_count(raw, where, ctx):
    _keys(raw, ("count",), ("count",), where)
    return {"count": _positive_int(raw["count"], f"{where} count")}


def _parse_free_population(raw, where, ctx):
    _keys(raw, ("amount", "all_cities"), ("amount",), where)
    return {"amount": _positive_int(raw["amount"], f"{where} amount"),
            "all_cities": _bool(raw.get("all_cities", False), f"{where} all_cities")}


_PARSERS = {
    KIND_CITY_YIELD: _parse_city_yield,
    KIND_PRODUCTION_PERCENT: _parse_production_percent,
    KIND_ADJACENCY_PERCENT: _parse_adjacency_percent,
    KIND_COMBAT_STRENGTH: _parse_combat_strength,
    KIND_CITY_RANGED_STRENGTH: _amount_only(_int),
    KIND_UNIT_MAINTENANCE_DELTA: _amount_only(_int),
    KIND_UPGRADE_COST_PERCENT: _percent_only,
    KIND_PURCHASE_PERCENT: _parse_purchase_percent,
    KIND_FAITH_PURCHASE: _parse_faith_purchase,
    KIND_TRADE_ROUTE_CAPACITY: _amount_only(_positive_int),
    KIND_ROUTE_YIELD: _parse_route_yield,
    KIND_LOYALTY: _parse_loyalty,
    KIND_GROWTH_PERCENT: _percent_only,
    KIND_POLICY_SLOTS: _parse_policy_slots,
    KIND_HOUSING_IF_DISTRICTS: _parse_housing_if_districts,
    KIND_HOUSING_WITH_BUILDING: _parse_housing_with_building,
    KIND_ENABLES: _parse_enables,
    KIND_FREE_UNITS: _parse_free_units,
    KIND_FREE_TECH: _parse_count,
    KIND_FREE_CIVIC: _parse_count,
    KIND_FREE_POPULATION: _parse_free_population,
}
assert set(_PARSERS) == set(KINDS), "every kind has one parser and one consumer"


def default_scope(source_kind):
    """"city" for buildings and districts, "player" for every other source."""
    return SCOPE_CITY if source_kind in _CITY_SOURCES else SCOPE_PLAYER


def parse_effect(entry, source_kind, source_name, districts=None):
    """Validate one raw entry of `source_kind` table `source_name` -> Effect.

    Raises ValueError on: an unknown kind or source; an unknown, missing or
    malformed attribute; a name that is no unit, building, district, class,
    era, rule or resource; `scope = "city"` on a source that stands in no
    city (policy, government, civic, tech) or on a kind whose consumer takes
    no city; a `city_yield` effect on a building (a building says it with a
    column); a `policy_slots` effect on a policy (a card cannot change the
    slots it is fitted into); a one-shot kind anywhere but on a district
    (wonder) table. `districts` is the registry names resolve against
    (default: district_model.DISTRICTS).
    """
    if source_kind not in SOURCES:
        raise ValueError(f"unknown effect source {source_kind!r}, expected one of {SOURCES}")
    where = f"[{source_kind} {source_name}] effect {entry!r}"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} must be a table")
    kind = entry.get("kind")
    if kind not in _PARSERS:
        raise ValueError(f"{where}: unknown kind {kind!r}, expected one of {KINDS}")
    scope = entry.get("scope", default_scope(source_kind))
    if scope not in SCOPES:
        raise ValueError(f"{where}: scope {scope!r} not in {SCOPES}")
    if scope == SCOPE_CITY and source_kind not in _CITY_SOURCES:
        raise ValueError(f"{where}: a {source_kind} has no city; scope must be \"player\"")
    if scope == SCOPE_CITY and kind in _PLAYER_ONLY_KINDS:
        raise ValueError(f"{where}: {kind} is read for the player only; scope must be \"player\"")
    if kind == KIND_CITY_YIELD and source_kind == SOURCE_BUILDING:
        raise ValueError(f"{where}: a building declares yields as columns, not city_yield effects")
    if kind == KIND_POLICY_SLOTS and source_kind == SOURCE_POLICY:
        raise ValueError(f"{where}: a policy card cannot change the policy slots")
    if kind in ONE_SHOT_KINDS and source_kind != SOURCE_DISTRICT:
        raise ValueError(f"{where}: {kind} fires once on a wonder's completion; "
                         f"it belongs on a district-registry table")
    raw = {k: v for k, v in entry.items() if k not in ("kind", "scope")}
    ctx = {"districts": district_model.DISTRICTS if districts is None else districts}
    attrs = _PARSERS[kind](raw, where, ctx)
    return Effect(kind=kind, scope=scope, source=(source_kind, source_name),
                  attrs=MappingProxyType(attrs))


def parse_effects(entries, source_kind, source_name, districts=None):
    """Validate a raw `effects` list -> tuple of Effect, in list order."""
    if not isinstance(entries, (list, tuple)):
        raise ValueError(f"[{source_kind} {source_name}] effects must be a list")
    return tuple(parse_effect(e, source_kind, source_name, districts) for e in entries)


# --- Registry access (read at call time, so a patched registry is the one seen) ----

# (source kind, name) -> (the raw list object, its parsed tuple). A parse memo,
# not game state: an entry is reused only while the raw list is the very same
# object, so a registry patched with a synthetic spec is re-validated.
_PARSED = {}
_districts_module = None


def _districts():
    """`civulator.game.districts`, imported on first use: the game layer loads
    after this module, and its `district_spec` is the one registry accessor."""
    global _districts_module
    if _districts_module is None:
        from .game import districts as module
        _districts_module = module
    return _districts_module


def _raw(source_kind, name):
    if source_kind == SOURCE_TECH:
        return research_model.TECHS[name].effects
    if source_kind == SOURCE_CIVIC:
        return research_model.CIVICS[name].effects
    if source_kind == SOURCE_GOVERNMENT:
        return research_model.GOVERNMENTS[name].effects
    if source_kind == SOURCE_POLICY:
        return research_model.POLICIES[name].effects
    if source_kind == SOURCE_BUILDING:
        return unit_model.BUILDING_EFFECTS.get(name, ())
    if source_kind == SOURCE_DISTRICT:
        return _districts().district_spec(name).effects
    raise ValueError(f"unknown effect source {source_kind!r}")


def effects_of(source_kind, name):
    """The validated effects of one source (a tuple of Effect, in config
    order). Raises KeyError for a name the registry does not hold."""
    raw = _raw(source_kind, name)
    if not raw:
        return ()
    hit = _PARSED.get((source_kind, name))
    if hit is not None and hit[0] is raw:
        return hit[1]
    # Names resolve against the live registry (`districts.DISTRICTS`, which a
    # test may patch with a synthetic one), as every other reader does.
    parsed = parse_effects(raw, source_kind, name, _districts().DISTRICTS)
    _PARSED[(source_kind, name)] = (raw, parsed)
    return parsed


def _validate_registries():
    """Load-time validation of every configured effects list (design §3:
    junk raises at load, never at first use)."""
    for source_kind, names in (
        (SOURCE_TECH, research_model.TECHS),
        (SOURCE_CIVIC, research_model.CIVICS),
        (SOURCE_GOVERNMENT, research_model.GOVERNMENTS),
        (SOURCE_POLICY, research_model.POLICIES),
        (SOURCE_BUILDING, unit_model.BUILDING_EFFECTS),
    ):
        for name in names:
            raw = _raw(source_kind, name)
            if raw:
                _PARSED[(source_kind, name)] = (raw, parse_effects(raw, source_kind, name))
    for name, spec in district_model.DISTRICTS.items():
        if spec.effects:
            parse_effects(spec.effects, SOURCE_DISTRICT, name)


_validate_registries()


# --- Policy loadouts and slots (design §5.3-§5.4) -------------------------------------


def card_available(player, name):
    """Whether policy card `name` may be slotted by `player` now: it exists,
    its civic is known, and its `obsolete_with` civic (if any) is not."""
    spec = research_model.POLICIES.get(name)
    if spec is None or spec.requires_civic not in player.civics:
        return False
    return spec.obsolete_with is None or spec.obsolete_with not in player.civics


def fits_slots(card_types, counts):
    """Whether cards of `card_types` (a list of POLICY_TYPES entries) fit
    `counts` (slot type -> number): each typed card in a slot of its type or
    a wildcard slot, each wildcard card in a wildcard slot."""
    wildcard = research_model.POLICY_WILDCARD
    demand = sum(1 for t in card_types if t == wildcard)
    for slot_type in research_model.POLICY_TYPES:
        if slot_type != wildcard:
            demand += max(0, sum(1 for t in card_types if t == slot_type) - counts[slot_type])
    return demand <= counts[wildcard]


def slot_counts(player):
    """Slot type -> number of policy slots `player` has: the government's
    `policy_slots` effect plus every other `policy_slots` effect in force
    (civics, techs, wonders -- never a policy, which the loader refuses).
    The one consumer of `policy_slots`."""
    counts = dict.fromkeys(research_model.POLICY_TYPES, 0)
    for effect in _gather(player, None, KIND_POLICY_SLOTS, policies=()):
        for slot_type, number in effect["slots"].items():
            counts[slot_type] += number
    return counts


def policies_in_force(player, names=None):
    """The cards of `names` (default: `player.policies`) that are legal now,
    in their order: available (`card_available`), not a repeat, and fitting
    `slot_counts` together with the cards kept before them -- so when slots
    shrink, the newest-slotted card is the one that falls out. Only these
    cards' effects are in force (`active_effects`)."""
    names = player.policies if names is None else names
    if not names:
        return []
    counts = slot_counts(player)
    kept, types = [], []
    for name in names:
        if name in kept or not card_available(player, name):
            continue
        card_type = research_model.POLICIES[name].type
        if fits_slots(types + [card_type], counts):
            kept.append(name)
            types.append(card_type)
    return kept


def loadout_is_legal(player, names):
    """Whether `names` is a legal loadout for `player` now: every card exists,
    is unlocked and not obsolete, none appears twice, and together they fit
    the slots. The check `GameEnvironment.set_policies` applies."""
    names = list(names)
    return len(set(names)) == len(names) and policies_in_force(player, names) == names


# --- What is in force -------------------------------------------------------------------


def _gather(player, city, kind, policies):
    out = []

    def take(source_kind, name, scope):
        for effect in effects_of(source_kind, name):
            if effect.scope == scope and (kind is None or effect.kind == kind):
                out.append(effect)

    if player.government is not None:
        take(SOURCE_GOVERNMENT, player.government, SCOPE_PLAYER)
    for name in policies:
        take(SOURCE_POLICY, name, SCOPE_PLAYER)
    for name in player.civics:
        take(SOURCE_CIVIC, name, SCOPE_PLAYER)
    for name in player.techs:
        take(SOURCE_TECH, name, SCOPE_PLAYER)
    for owned in player.cities:
        for building in owned.buildings:
            take(SOURCE_BUILDING, building, SCOPE_PLAYER)
        for district in owned.districts:
            if district.complete:
                take(SOURCE_DISTRICT, district.type, SCOPE_PLAYER)
    if city is not None:
        for building in city.buildings:
            take(SOURCE_BUILDING, building, SCOPE_CITY)
        for district in city.districts:
            if district.complete:
                take(SOURCE_DISTRICT, district.type, SCOPE_CITY)
    return out


def active_effects(player, city=None, kind=None):
    """The effect entries in force for `player` (and, given, `city`, one of
    its cities), in the deterministic order of the module docstring,
    optionally only those of `kind`. A list of Effect; empty for no player.
    Pure: recomputed on every call, never cached."""
    if player is None:
        return []
    if kind is not None and kind not in _PARSERS:
        raise ValueError(f"unknown effect kind {kind!r}")
    return _gather(player, city, kind, policies_in_force(player))


def percent_sum(entries):
    """The summed `percent` of `entries`: effects of one kind are summed and
    then applied once with one floor (v2 fixes, N3), never compounded."""
    return sum(effect["percent"] for effect in entries)


def rule_enabled(player, rule):
    """Whether `rule` (one of RULES) is switched on for `player` by an
    `enables` effect in force. The one consumer of `enables`."""
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}, expected one of {RULES}")
    return any(rule in effect["rules"]
               for effect in active_effects(player, kind=KIND_ENABLES))


def combat_strength_amounts(player, applies, city=None):
    """The amounts, in order, of the `combat_strength` effects in force for
    `player` that apply to `applies`: a combat class (matched by that class
    or APPLIES_ALL) or APPLIES_CITY (then pass the `city`, so its own
    city-scoped entries count). The caller adds them one by one, like the
    class bonuses (`unit_model.class_bonus_amounts`)."""
    if applies is None:
        return []
    wanted = (applies,) if applies == APPLIES_CITY else (applies, APPLIES_ALL)
    return [effect["amount"]
            for effect in active_effects(player, city, KIND_COMBAT_STRENGTH)
            if any(a in effect["applies_to"] for a in wanted)]


def target_matches(target, item_kind, name):
    """Whether a `production_percent` target holds for the item being
    produced: `item_kind` one of ITEM_KINDS (a district-registry entry's
    `kind` for a district or wonder), `name` its type. Every condition the
    target names must hold."""
    if "kind" in target and target["kind"] != item_kind:
        return False
    if item_kind == ITEM_UNIT:
        if "unit" in target and name not in target["unit"]:
            return False
        if "unit_class" in target and unit_model.COMBAT_CLASS.get(name) not in target["unit_class"]:
            return False
        if "unit_era" in target and unit_model.UNIT_ERA.get(name) not in target["unit_era"]:
            return False
        return not any(k in target for k in ("building", "in_district", "district"))
    if item_kind == ITEM_BUILDING:
        if "building" in target and name not in target["building"]:
            return False
        if ("in_district" in target
                and unit_model.BUILDING_REQUIRES_DISTRICT.get(name) not in target["in_district"]):
            return False
        return not any(k in target for k in ("unit", "unit_class", "unit_era", "district"))
    if "district" in target and name not in target["district"]:
        return False
    return not any(k in target for k in ("unit", "unit_class", "unit_era", "building",
                                         "in_district"))
