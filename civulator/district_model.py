"""Pure interpreter for the `[districts]` config (issue #86, docs/districts_design.md).

The only module that reads `CFG["districts"]`, mirroring unit_model.py /
terrain_model.py: parse once at import, validate strictly, hand back plain
immutable values. A new district is a new config table, never code.

Validation (design §1.2 and "v3 fixes", config loading):
- scalars and sub-tables are split; unknown keys anywhere raise;
- "City Center" and "any" are reserved and no district may take them;
- every adjacency row / `requires_adjacent` entry has exactly one source, and
  every name it uses exists (terrain through terrain_model.validate_on_table,
  improvements through terrain_model.IMPROVEMENT_NAMES, districts through
  this registry);
- `amount` and `per` are positive ints; `adjacency_yield` is one of
  ACCEPTED_YIELDS; housing values and the optional flat yield columns
  (unit_model.YIELD_COLUMNS, issue #116) go through unit_model.to_tenths;
- `requires_tech` names a tech (research_model, #116 P2), `requires_civic`
  a civic (#116 P4), `maintenance` is a non-negative multiple of 0.1
  (tenths);
- `effects` is kept raw (a list; #116 P4) and validated by
  civulator/effects.py, which loads after this registry;
- every `[buildings.*] requires_district` (parsed by unit_model, which loads
  before this registry) names a district of this registry.

Imports only config / research_model / terrain_model / unit_model: no
civulator.game.
"""

from dataclasses import dataclass

from .config import CFG
from . import terrain_model
from .research_model import validate_civic_name, validate_tech_name
from .unit_model import BUILDING_REQUIRES_DISTRICT, YIELD_COLUMNS, to_tenths

CITY_CENTER = "City Center"
ANY_DISTRICT = "any"
RESERVED_NAMES = frozenset({CITY_CENTER, ANY_DISTRICT})

ACCEPTED_YIELDS = ("culture", "production", "science", "gold", "faith", "none")
COST_MODELS = ("discounted", "progress", "fixed")

# Source kinds (design §1.2). Neighbour sources count matching neighbours;
# tile tests are true once or not at all, from the district's own tile.
NEIGHBOUR_SOURCES = ("terrain", "improvement", "district")
ADJACENCY_TILE_TESTS = ("river_on_tile",)
REQUIREMENT_TILE_TESTS = ("river_edge_not_shared_with_center",)

_SCALAR_KEYS = frozenset({
    "population_per_district", "cost_progress_factor",
    "removable_features", "allowed_features",
})
_DISTRICT_KEYS = frozenset({
    "production_cost", "cost_model", "discount_percent", "counts_toward_limit",
    "max_per_city", "max_per_player", "adjacency_yield", "adjacency", "on",
    "adjacent_to_city_center", "requires_adjacent",
    "housing", "water_housing_min", "water_housing_boost",
    *YIELD_COLUMNS,
    "requires_tech", "requires_civic", "maintenance",  # #116 P2
    "effects",  # #116 P4
})

# What a registry entry is (progression design §9.1). Every configured entry
# is a "district" until #116 P6 adds the `kind` column and its wonders; the
# field exists now so that readers (specialty districts, the effects
# interpreter) are written against it once.
KIND_DISTRICT = "district"
KIND_WONDER = "wonder"
KINDS = (KIND_DISTRICT, KIND_WONDER)


@dataclass(frozen=True)
class Source:
    """One source (design §1.2): `kind` is a NEIGHBOUR_SOURCES or tile-test
    name; `value` is the terrain mapping, a tuple of names, "any", or True."""

    kind: str
    value: object


@dataclass(frozen=True)
class AdjacencyRow:
    """`amount` per `per` matching neighbours (floored per row)."""

    amount: int
    per: int
    source: Source


@dataclass(frozen=True)
class DistrictSpec:
    name: str
    production_cost: int
    cost_model: str
    discount_percent: int
    counts_toward_limit: bool
    max_per_city: int
    max_per_player: object  # int or None (unlimited)
    adjacency_yield: str
    adjacency: tuple  # of AdjacencyRow
    on: object  # terrain mapping / list, or None = land
    adjacent_to_city_center: object  # True / False / None (either)
    requires_adjacent: tuple  # of Source; empty = no requirement
    housing: int  # tenths
    water_housing_min: object  # tenths or None
    water_housing_boost: object  # tenths or None
    # Flat per-turn yields of the complete district (issue #116): every name in
    # unit_model.YIELD_COLUMNS -> int tenths, 0 when the column is absent.
    # Read by game/yields.py city_yield; separate from the adjacency yield.
    yield_columns: dict
    # Availability (#116 P2, P4): the tech and the civic the owner must know
    # to place it (None = ungated); gold upkeep per turn in int tenths, paid
    # for a complete district in the owner's economy phase (game/maintenance.py,
    # #116 P5).
    requires_tech: object = None
    requires_civic: object = None
    maintenance: int = 0
    # The raw `effects` list (#116 P4), validated by civulator/effects.py;
    # city scope by default. Empty when absent.
    effects: tuple = ()
    # KIND_DISTRICT for every entry until #116 P6 configures wonders.
    kind: str = KIND_DISTRICT


@dataclass(frozen=True)
class DistrictRegistry:
    population_per_district: int
    cost_progress_factor: int
    removable_features: frozenset
    allowed_features: frozenset
    districts: dict  # name -> DistrictSpec, in config order


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} must be a positive int, got {value!r}")
    return value


def _non_negative_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{what} must be a non-negative int, got {value!r}")
    return value


def _bool(value, what):
    if not isinstance(value, bool):
        raise ValueError(f"{what} must be true or false, got {value!r}")
    return value


def _feature_names(names, what):
    if not isinstance(names, list):
        raise ValueError(f"{what} must be a list")
    missing = [n for n in names if n not in terrain_model.FEATURE_TABLE]
    if missing:
        raise ValueError(f"{what} names unknown features {missing}")
    return frozenset(names)


def _parse_source(entry, where, district_names, tile_tests):
    """Exactly one source key in `entry` (other keys already removed)."""
    kinds = [k for k in entry if k in NEIGHBOUR_SOURCES or k in tile_tests]
    unknown = set(entry) - set(kinds)
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
    if len(kinds) != 1:
        raise ValueError(f"{where}: needs exactly one source, got {kinds}")
    kind = kinds[0]
    value = entry[kind]
    if kind == "terrain":
        terrain_model.validate_on_table(value, where, allow_resources=True, check_names=True)
        return Source(kind, value)
    if kind == "improvement":
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where}: improvement must be a non-empty list")
        missing = [n for n in value if n not in terrain_model.IMPROVEMENT_NAMES]
        if missing:
            raise ValueError(f"{where}: unknown improvement(s) {missing}")
        return Source(kind, tuple(value))
    if kind == "district":
        if value == ANY_DISTRICT:
            return Source(kind, ANY_DISTRICT)
        if not isinstance(value, list) or not value:
            raise ValueError(f"{where}: district must be \"any\" or a non-empty list")
        missing = [n for n in value if n != CITY_CENTER and n not in district_names]
        if missing:
            raise ValueError(f"{where}: unknown district(s) {missing}")
        return Source(kind, tuple(value))
    # tile test
    if value is not True:
        raise ValueError(f"{where}: {kind} must be true")
    return Source(kind, True)


def _parse_row(row, where, district_names):
    if not isinstance(row, dict):
        raise ValueError(f"{where}: row must be a table")
    rest = dict(row)
    if "amount" not in rest:
        raise ValueError(f"{where}: row needs `amount`")
    amount = _positive_int(rest.pop("amount"), f"{where} amount")
    per = _positive_int(rest.pop("per", 1), f"{where} per")
    source = _parse_source(rest, where, district_names, ADJACENCY_TILE_TESTS)
    return AdjacencyRow(amount, per, source)


def _optional_tenths(table, key, where):
    if key not in table:
        return None
    return to_tenths(table[key], f"{where} {key}")


def _parse_district(name, table, district_names):
    where = f"[districts.{name}]"
    if not isinstance(table, dict):
        raise ValueError(f"{where} must be a table")
    unknown = set(table) - _DISTRICT_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
    if "production_cost" not in table:
        raise ValueError(f"{where}: production_cost is required")
    cost_model = table.get("cost_model", "progress")
    if cost_model not in COST_MODELS:
        raise ValueError(f"{where}: cost_model {cost_model!r} not in {COST_MODELS}")
    discount = _non_negative_int(table.get("discount_percent", 0), f"{where} discount_percent")
    if discount > 100:
        raise ValueError(f"{where}: discount_percent > 100")
    adjacency_yield = table.get("adjacency_yield", "none")
    if adjacency_yield not in ACCEPTED_YIELDS:
        raise ValueError(f"{where}: adjacency_yield {adjacency_yield!r} not in {ACCEPTED_YIELDS}")
    max_per_player = table.get("max_per_player")
    if max_per_player is not None:
        _positive_int(max_per_player, f"{where} max_per_player")
    adjacent_to_center = table.get("adjacent_to_city_center")
    if adjacent_to_center is not None:
        _bool(adjacent_to_center, f"{where} adjacent_to_city_center")
    on = table.get("on")
    if on is not None:
        terrain_model.validate_on_table(on, f"{where} on", allow_resources=True, check_names=True)
    rows = table.get("adjacency", [])
    if not isinstance(rows, list):
        raise ValueError(f"{where}: adjacency must be a list of rows")
    requires = table.get("requires_adjacent", [])
    if not isinstance(requires, list):
        raise ValueError(f"{where}: requires_adjacent must be a list")
    return DistrictSpec(
        name=name,
        production_cost=_positive_int(table["production_cost"], f"{where} production_cost"),
        cost_model=cost_model,
        discount_percent=discount,
        counts_toward_limit=_bool(table.get("counts_toward_limit", True),
                                  f"{where} counts_toward_limit"),
        max_per_city=_positive_int(table.get("max_per_city", 1), f"{where} max_per_city"),
        max_per_player=max_per_player,
        adjacency_yield=adjacency_yield,
        adjacency=tuple(
            _parse_row(row, f"{where} adjacency[{i}]", district_names)
            for i, row in enumerate(rows)
        ),
        on=on,
        adjacent_to_city_center=adjacent_to_center,
        requires_adjacent=tuple(
            _parse_source(dict(entry), f"{where} requires_adjacent[{i}]",
                          district_names, REQUIREMENT_TILE_TESTS)
            for i, entry in enumerate(requires)
        ),
        housing=_optional_tenths(table, "housing", where) or 0,
        water_housing_min=_optional_tenths(table, "water_housing_min", where),
        water_housing_boost=_optional_tenths(table, "water_housing_boost", where),
        yield_columns={c: _optional_tenths(table, c, where) or 0 for c in YIELD_COLUMNS},
        requires_tech=(validate_tech_name(table["requires_tech"], where)
                       if "requires_tech" in table else None),
        requires_civic=(validate_civic_name(table["requires_civic"], where)
                        if "requires_civic" in table else None),
        maintenance=_maintenance(table, where),
        effects=_effects(table, where),
    )


def _effects(table, where):
    effects = table.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError(f"{where}: effects must be a list, got {effects!r}")
    return tuple(effects)


def _maintenance(table, where):
    tenths = _optional_tenths(table, "maintenance", where) or 0
    if tenths < 0:
        raise ValueError(f"{where}: maintenance must be >= 0")
    return tenths


def parse_districts(cfg):
    """Parse and validate one `[districts]` table; raises ValueError on any
    unknown key, missing name or malformed value."""
    scalars = {k: v for k, v in cfg.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in cfg.items() if isinstance(v, dict)}
    unknown = set(scalars) - _SCALAR_KEYS
    if unknown:
        raise ValueError(f"[districts]: unknown key(s) {sorted(unknown)}")
    missing = _SCALAR_KEYS - set(scalars)
    if missing:
        raise ValueError(f"[districts]: missing key(s) {sorted(missing)}")
    reserved = RESERVED_NAMES & set(tables)
    if reserved:
        raise ValueError(f"[districts]: reserved name(s) {sorted(reserved)}")
    names = frozenset(tables)
    return DistrictRegistry(
        population_per_district=_positive_int(
            scalars["population_per_district"], "[districts] population_per_district"),
        cost_progress_factor=_non_negative_int(
            scalars["cost_progress_factor"], "[districts] cost_progress_factor"),
        removable_features=_feature_names(
            scalars["removable_features"], "[districts] removable_features"),
        allowed_features=_feature_names(
            scalars["allowed_features"], "[districts] allowed_features"),
        districts={name: _parse_district(name, table, names) for name, table in tables.items()},
    )


def validate_building_districts(requires_district, districts):
    """Raise ValueError unless every `[buildings.*] requires_district` value
    (building -> district name) names a district of `districts`."""
    for building, district in requires_district.items():
        if district not in districts:
            raise ValueError(
                f"[buildings.{building}] requires_district {district!r} is not a district"
            )


REGISTRY = parse_districts(CFG["districts"])
validate_building_districts(BUILDING_REQUIRES_DISTRICT, REGISTRY.districts)

DISTRICTS = REGISTRY.districts
POPULATION_PER_DISTRICT = REGISTRY.population_per_district
COST_PROGRESS_FACTOR = REGISTRY.cost_progress_factor
REMOVABLE_FEATURES = REGISTRY.removable_features
ALLOWED_FEATURES = REGISTRY.allowed_features
# The configured `discounted` types, in config order (A of design §4.1 is its length).
DISCOUNTED_TYPES = tuple(n for n, s in DISTRICTS.items() if s.cost_model == "discounted")
