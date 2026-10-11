"""Issue #86 D1: the `[districts]` loader and the terrain_model `resources`
match key (docs/districts_design.md §1, §1.2, §8 and "v3 fixes")."""

import copy

import pytest

from civulator import district_model, terrain_model
from civulator.config import CFG


def _cfg():
    """A deep copy of the real [districts] table, to break one thing at a time."""
    return copy.deepcopy(CFG["districts"])


def _with_district(table, name="Probe"):
    cfg = _cfg()
    cfg[name] = table
    return cfg


def _probe(**extra):
    table = {"production_cost": 10, "cost_model": "progress"}
    table.update(extra)
    return table


# --- The real config ---------------------------------------------------------


def test_real_config_parses_and_every_row_is_well_formed():
    """Every configured district parses; each row has a positive int amount
    and per and exactly one known source kind. Breaks if a row is added to
    config.toml that the loader would have to skip or misread."""
    reg = district_model.parse_districts(CFG["districts"])
    assert reg.districts, "at least one district is configured"
    kinds = set(district_model.NEIGHBOUR_SOURCES) | set(district_model.ADJACENCY_TILE_TESTS)
    for spec in reg.districts.values():
        assert spec.adjacency_yield in district_model.ACCEPTED_YIELDS
        assert spec.cost_model in district_model.COST_MODELS
        for row in spec.adjacency:
            assert isinstance(row.amount, int) and row.amount > 0
            assert isinstance(row.per, int) and row.per > 0
            assert row.source.kind in kinds


def test_reserved_names_are_not_districts():
    """"City Center" and "any" are source words, never district names.
    Breaks if the reserved-name check is dropped."""
    for reserved in district_model.RESERVED_NAMES:
        assert reserved not in district_model.DISTRICTS
        with pytest.raises(ValueError):
            district_model.parse_districts(_with_district(_probe(), reserved))


def test_aqueduct_declares_its_water_housing_fields_in_tenths():
    """The Aqueduct's §6 fields are parsed through to_tenths (D2 applies them).
    Breaks if the fields are dropped or stored as raw floats."""
    spec = district_model.DISTRICTS["Aqueduct"]
    raw = CFG["districts"]["Aqueduct"]
    assert spec.water_housing_min == round(10 * raw["water_housing_min"])
    assert spec.water_housing_boost == round(10 * raw["water_housing_boost"])


# --- Validation: each bad input raises ---------------------------------------


@pytest.mark.parametrize("bad", [
    # unknown district key
    _probe(colour="red"),
    # bad cost model / yield
    _probe(cost_model="cheap"),
    _probe(adjacency_yield="happiness"),
    # amount / per must be positive ints
    _probe(adjacency=[{"amount": 0, "district": "any"}]),
    _probe(adjacency=[{"amount": 1.5, "district": "any"}]),
    _probe(adjacency=[{"amount": True, "district": "any"}]),
    _probe(adjacency=[{"amount": 1, "per": 0, "district": "any"}]),
    _probe(adjacency=[{"district": "any"}]),
    # one source, exactly
    _probe(adjacency=[{"amount": 1}]),
    _probe(adjacency=[{"amount": 1, "district": "any", "improvement": ["Mine"]}]),
    _probe(adjacency=[{"amount": 1, "wonder": ["Stonehenge"]}]),
    # names must exist
    _probe(adjacency=[{"amount": 1, "terrain": {"features": ["Volcano"]}}]),
    _probe(adjacency=[{"amount": 1, "terrain": {"bases": ["Lava"]}}]),
    _probe(adjacency=[{"amount": 1, "terrain": {"resources": ["Iron"]}}]),
    _probe(adjacency=[{"amount": 1, "improvement": ["Lumber Mill"]}]),
    _probe(adjacency=[{"amount": 1, "district": ["Dam"]}]),
    # unknown `on` key inside a terrain source / the tile's own `on`
    _probe(adjacency=[{"amount": 1, "terrain": {"appeal": ["high"]}}]),
    _probe(on={"bases": ["Plains"], "elevation": ["high"]}),
    # tile tests take only `true`, and only where they belong
    _probe(adjacency=[{"amount": 1, "river_on_tile": False}]),
    _probe(adjacency=[{"amount": 1, "river_edge_not_shared_with_center": True}]),
    _probe(requires_adjacent=[{"river_on_tile": True}]),
    # limits
    _probe(max_per_city=0),
    _probe(max_per_player=0),
])
def test_a_malformed_district_table_raises_at_load(bad):
    """A row naming a missing terrain, improvement or district, a second
    source, an unknown key or a non-positive amount raises at load. Breaks
    if any validation step is skipped, so a dropped Civ 6 row could sit in
    config pointing at nothing."""
    with pytest.raises(ValueError):
        district_model.parse_districts(_with_district(bad))


def test_unknown_scalar_and_feature_list_names_raise():
    """[districts] scalars are a closed set and their feature lists name real
    features. Breaks if the scalar/sub-table split stops checking keys."""
    cfg = _cfg()
    cfg["districts_per_era"] = 2
    with pytest.raises(ValueError):
        district_model.parse_districts(cfg)
    cfg = _cfg()
    cfg["removable_features"] = ["Jungle"]
    with pytest.raises(ValueError):
        district_model.parse_districts(cfg)


def test_a_valid_probe_district_parses_with_defaults():
    """Defaults: one per city, counts toward the limit, no yield, land only.
    Breaks if a default changes silently."""
    reg = district_model.parse_districts(_with_district(_probe()))
    spec = reg.districts["Probe"]
    assert spec.max_per_city == 1
    assert spec.counts_toward_limit is True
    assert spec.max_per_player is None
    assert spec.adjacency_yield == "none"
    assert spec.on is None
    assert spec.adjacency == () and spec.requires_adjacent == ()


# --- terrain_model: the `resources` key and the accessors ---------------------


def test_resources_key_matches_names_and_any_but_not_no_resource():
    """`resources` is an OR-list of names or "any"; "any" needs some
    resource. Breaks if None is treated as a match or "any" is read as a name."""
    on = {"resources": ["any"]}
    assert terrain_model.matches(on, "Coast", resource="Fish")
    assert not terrain_model.matches(on, "Coast", resource=None)
    named = {"bases": ["Coast"], "resources": ["Fish"]}
    assert terrain_model.matches(named, "Coast", resource="Fish")
    assert not terrain_model.matches(named, "Coast", resource="Wheat")
    assert not terrain_model.matches(named, "Plains", resource="Fish")


def test_resources_key_without_a_resource_raises():
    """Evaluating a `resources` constraint without passing a resource raises.
    Breaks if `matches` silently ignores keys it was not given values for."""
    with pytest.raises(ValueError):
        terrain_model.matches({"resources": ["any"]}, "Coast")
    with pytest.raises(ValueError):
        terrain_model.matches([{"bases": ["Plains"]}, {"resources": ["Fish"]}], "Coast")


def test_mappings_without_resources_behave_as_before():
    """Existing callers pass no resource and keep their results. Breaks if
    the new parameter changes what an old mapping means."""
    on = [{"bases": ["Plains"], "relief": ["flat"], "features": ["none"]}]
    assert terrain_model.matches(on, "Plains")
    assert terrain_model.matches(on, "Plains", resource=None)
    assert not terrain_model.matches(on, "Plains", "hills")
    assert terrain_model.matches(None, "Ocean")


def test_on_tables_reject_unknown_keys_and_resources_in_layers(monkeypatch):
    """Layer and improvement `on` tables reject `resources` and unknown keys
    at load. Breaks if the load-time check is removed."""
    with pytest.raises(ValueError):
        terrain_model.validate_on_table({"resources": ["Fish"]}, "layer")
    with pytest.raises(ValueError):
        terrain_model.validate_on_table({"feature": ["Woods"]}, "layer")
    assert terrain_model.validate_on_table({"resources": ["Fish"]}, "d", allow_resources=True)

    monkeypatch.setitem(terrain_model.FEATURE_TABLE["Woods"], "on", {"resources": ["Deer"]})
    with pytest.raises(ValueError):
        terrain_model._validate_config_on_tables()
    monkeypatch.undo()
    monkeypatch.setitem(CFG["improvements"]["Farm"], "on", {"base": ["Plains"]})
    with pytest.raises(ValueError):
        terrain_model._validate_config_on_tables()


def test_resource_class_and_improvement_names_reflect_config():
    """The two accessors read config, never a second copy. Breaks if a
    caller-side table drifts from config.toml."""
    for name, entry in terrain_model.RESOURCE_TABLE.items():
        assert terrain_model.resource_class(name) == entry["class"]
    assert terrain_model.IMPROVEMENT_NAMES == frozenset(CFG["improvements"])
