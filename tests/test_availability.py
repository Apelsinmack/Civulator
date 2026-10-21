"""Issue #116 P2, P4: what a player and a city may build (docs/progression_design.md
§4.1, §5, §6.2, "v2 fixes"; §14 rows "An item with requires_tech is refused
...", "A requires_* naming nothing raises at load", "With every tech known
..."). P4 adds the civic and government-tier gates on the same paths.

One test per build path that must read `player_can_build` /
`city_can_build_building`: the build mask, `produce_unit` /
`produce_building`, `can_player_build_improvement_at` and the Worker (the
district path is `test_districts.py::test_a_district_is_refused_until_its_
tech_is_known`). Every test iterates over whatever is configured; none pins
which items are gated or by what.
"""

import pytest

from civulator import district_model, terrain_model, unit_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.config import CFG
from civulator.game.availability import (
    KINDS,
    NO_GOVERNMENT_TIER,
    city_can_build_building,
    government_tier,
    player_can_build,
    required_civic,
    required_tech,
)
from civulator.game.city import City
from civulator.game.districts import District
from civulator.game.territory import NEUTRAL
from civulator.game.unit import WorkerUnit
from civulator.research_model import CIVIC_ORDER, CIVICS, GOVERNMENTS, TECH_ORDER, TECHS

from conftest import grant, grant_all, grant_civic
from test_combat_range import make_flat_env, place

CENTRE = (3, 4)


def _env_and_city():
    env = make_flat_env()
    env.map.rivers.clear()
    env.map.terrain_epoch += 1
    city = env.create_city(env.players[0], CENTRE, "C")
    city.population = 3  # the Settler's population gate is not under test
    return env, city


def _kind(option):
    return "building" if option in City.BUILDING_COSTS else "unit"


def _site(env, city, index):
    """An owned tile at distance 2 from the centre (fixture only)."""
    pos = sorted(env.map.get_ring_coords(city.coordinates, 2)[2])[index]
    if env.map.owner_id_at(pos) == NEUTRAL:
        env.map.claim(pos, city)
    return pos


def _put_district(env, city, district_type, complete=True, index=0):
    """Fixture only: link a district by hand, bypassing placement rules (the
    rule under test is availability, not placement)."""
    pos = _site(env, city, index)
    district = District(district_type, city.city_id, pos, complete=complete, cost=1)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def _adopt_tier(env, player, tier):
    """Adopt the first configured government of at least `tier` (granting its
    civic): fixture for a `requires_government_tier` (#116 P4)."""
    name = next(n for n, g in GOVERNMENTS.items() if g.tier >= tier)
    grant_civic(player, GOVERNMENTS[name].requires_civic)
    assert env.set_government(player, name)


def _satisfy_non_tech_requirements(env, city, building):
    """Give `city` the complete district and the building chain `building`
    requires, its owner the building's civic and a government of its tier
    (#116 P4), so only research can still refuse it."""
    district = unit_model.BUILDING_REQUIRES_DISTRICT.get(building)
    if district is not None:
        _put_district(env, city, district)
    civic = unit_model.BUILDING_REQUIRES_CIVIC.get(building)
    if civic is not None:
        grant_civic(city.player, civic)
    tier = unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER.get(building)
    if tier is not None and government_tier(city.player) < tier:
        _adopt_tier(env, city.player, tier)
    needed = unit_model.BUILDING_REQUIRES_BUILDING.get(building)
    while needed is not None:
        city.buildings.append(needed)
        needed = unit_model.BUILDING_REQUIRES_BUILDING.get(needed)


def _gated_options():
    return [o for o in BUILD_OPTIONS if required_tech(_kind(o), o) is not None]


def _without(tech):
    return [t for t in TECH_ORDER if t != tech]


# --- (a) every build path refuses an unresearched item -------------------------


def test_the_build_mask_refuses_every_gated_option_until_its_tech_is_known():
    """For every build option with a `requires_tech`, with every other
    requirement met and every OTHER tech known, the mask refuses it; with
    its tech, it offers it. Breaks if the mask skips player_can_build (the
    mask invariant, #51: an unresearched option must never be offered)."""
    assert _gated_options(), "fixture: some build option is tech-gated"
    for option in _gated_options():
        env, city = _env_and_city()
        if _kind(option) == "building":
            _satisfy_non_tech_requirements(env, city, option)
        tech = required_tech(_kind(option), option)
        city.player.techs[:] = _without(tech)
        idx = BUILD_OPTIONS.index(option)
        assert get_valid_build_mask(city)[idx] == 0.0, option
        city.player.techs.append(tech)
        assert get_valid_build_mask(city)[idx] == 1.0, option


def test_production_refuses_every_gated_option_until_its_tech_is_known():
    """produce_unit / produce_building return False and leave production
    unchanged for an item whose tech the owner lacks, and accept it once the
    tech is known. Breaks if a production path skips player_can_build."""
    for option in _gated_options():
        env, city = _env_and_city()
        kind = _kind(option)
        if kind == "building":
            _satisfy_non_tech_requirements(env, city, option)
        produce = city.produce_building if kind == "building" else city.produce_unit
        tech = required_tech(kind, option)
        city.player.techs[:] = _without(tech)
        before = dict(city.current_production)
        assert produce(option) is False, option
        assert city.current_production == before
        city.player.techs.append(tech)
        assert produce(option) is True, option
        assert option in city.current_production.values()


def _improvement_terrain(name):
    """A (base, relief) on which improvement `name` may stand, from the
    terrain tables and its `on` constraint; None if there is none."""
    on = terrain_model.improvement_on(name)
    if on is None:
        return None
    for base in terrain_model.BASE_TABLE:
        for relief in terrain_model.RELIEF_TABLE:
            if terrain_model.RELIEF_TABLE[relief].get("impassable"):
                continue
            try:
                terrain_model.validate(base, relief=relief)
            except ValueError:
                continue
            if terrain_model.matches(on, base, relief, None):
                return base, relief
    return None


def _painted(env, pos, name):
    base, relief = _improvement_terrain(name)
    env.map.get_tile(pos).set_layers(base, relief=relief, map_ref=env.map)
    return pos


def _buildable_improvements():
    names = [n for n in sorted(terrain_model.IMPROVEMENT_NAMES) if _improvement_terrain(n)]
    assert names, "fixture: some improvement can stand on some terrain"
    return names


def test_a_player_builds_an_improvement_only_on_its_own_tile_with_its_tech():
    """can_player_build_improvement_at: on a tile one of the player's cities
    owns, refused while the improvement's tech is unknown and allowed once
    known; on a neutral tile or another player's tile, refused even with
    every tech -- while the tile predicate can_build_improvement_at stays
    player-blind. Breaks if the player check drops ownership or the tech."""
    for name in _buildable_improvements():
        env, city = _env_and_city()
        player, other = env.players[0], env.players[1]
        own_tile = _painted(env, sorted(env.map.get_ring_coords(CENTRE, 1)[1])[0], name)
        tech = required_tech("improvement", name)
        if tech is not None:
            player.techs[:] = _without(tech)
            assert not env.can_player_build_improvement_at(player, own_tile, name), name
            assert env.can_build_improvement_at(own_tile, name), "tile predicate is player-blind"
        grant_all(player)
        assert env.can_player_build_improvement_at(player, own_tile, name), name

        neutral = _painted(env, (7, 12), name)
        assert env.map.owner_id_at(neutral) == NEUTRAL
        assert env.can_build_improvement_at(neutral, name)
        assert not env.can_player_build_improvement_at(player, neutral, name), name

        foreign = env.create_city(other, (3, 12), "F")
        theirs = _painted(env, sorted(env.map.get_ring_coords(foreign.coordinates, 1)[1])[0], name)
        assert env.map.owner_id_at(theirs) == foreign.city_id
        assert not env.can_player_build_improvement_at(player, theirs, name), name


def test_a_worker_builds_only_what_its_owner_may():
    """WorkerUnit.build_improvement goes through
    can_player_build_improvement_at: without the tech, nothing is built and
    the Worker keeps its movement; with it, the improvement stands and the
    Worker's movement is spent. Breaks if the Worker calls the tile
    predicate alone."""
    gated = [n for n in _buildable_improvements() if required_tech("improvement", n)]
    assert gated, "fixture: some improvement is tech-gated"
    for name in gated:
        env, city = _env_and_city()
        pos = _painted(env, sorted(env.map.get_ring_coords(CENTRE, 1)[1])[0], name)
        worker = place(env, WorkerUnit, 0, pos)
        moves = worker.movement_points
        tech = required_tech("improvement", name)
        city.player.techs[:] = _without(tech)
        assert worker.build_improvement(name, env) is False
        assert env.map.get_tile(pos).improvements == [] and worker.movement_points == moves
        city.player.techs.append(tech)
        assert worker.build_improvement(name, env) is True
        assert name in env.map.get_tile(pos).improvements and worker.movement_points == 0


# --- Building requirements beyond research -------------------------------------------


def test_a_building_needs_a_complete_required_district_and_its_required_building():
    """city_can_build_building, the mask and produce_building refuse a
    building whose `requires_district` is absent or only placed, or whose
    `requires_building` the city lacks, even with every tech known; with a
    complete district and the building chain owned they accept it. Breaks
    if a placed district counts or the prerequisite building is ignored."""
    with_district = sorted(unit_model.BUILDING_REQUIRES_DISTRICT)
    with_building = sorted(unit_model.BUILDING_REQUIRES_BUILDING)
    assert with_district or with_building, "fixture: some building has such a requirement"
    for name in sorted(set(with_district) | set(with_building)):
        env, city = _env_and_city()
        grant_all(city.player)
        tier = unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER.get(name)
        if tier is not None:
            _adopt_tier(env, city.player, tier)
        idx = BUILD_OPTIONS.index(name) if name in BUILD_OPTIONS else None

        def refused():
            assert not city_can_build_building(city, name), name
            assert city.produce_building(name) is False, name
            if idx is not None:
                assert get_valid_build_mask(city)[idx] == 0.0, name

        district = unit_model.BUILDING_REQUIRES_DISTRICT.get(name)
        if district is not None:
            refused()
            placed = _put_district(env, city, district, complete=False)
            refused()
            placed.complete = True
        needed = unit_model.BUILDING_REQUIRES_BUILDING.get(name)
        if needed is not None:
            refused()
            _satisfy_non_tech_requirements(env, city, needed)
            city.buildings.append(needed)
        assert city_can_build_building(city, name), name
        if idx is not None:
            assert get_valid_build_mask(city)[idx] == 1.0, name
        assert city.produce_building(name) is True, name


def test_the_mask_never_offers_an_option_production_would_refuse():
    """For every option, in research states from nothing to the whole tree
    and with and without a complete district of every type, an option the
    mask offers is accepted by produce_unit / produce_building. Breaks if
    the mask and production read different predicates (train/play skew)."""
    for known in range(0, len(TECH_ORDER) + 1, 3):
        for with_districts in (False, True):
            env, city = _env_and_city()
            city.player.techs[:] = TECH_ORDER[:known]
            if with_districts:
                for i, district in enumerate(district_model.DISTRICTS):
                    _put_district(env, city, district, index=i)
            mask = get_valid_build_mask(city)
            for idx, option in enumerate(BUILD_OPTIONS):
                if mask[idx] == 1.0:
                    produce = (city.produce_building if _kind(option) == "building"
                               else city.produce_unit)
                    assert produce(option) is True, (option, known, with_districts)


# --- (e) with every tech known, every gated item is available ------------------------


def test_with_every_tech_known_every_gated_item_is_available():
    """Every unit, building, district and improvement is available to a
    player who knows both trees; every costed building is buildable by a
    city holding its complete district and its building chain under a
    government of its tier; and every `requires_*` a building declares
    names something a city can hold. Breaks on a dead node or an
    unreachable item (design §14)."""
    env, city = _env_and_city()
    player = grant_all(city.player)
    items = {
        "unit": unit_model.UNIT_NAMES,
        "building": unit_model.BUILDING_NAMES,
        "district": district_model.DISTRICTS,
        "improvement": terrain_model.IMPROVEMENT_NAMES,
    }
    assert set(items) == set(KINDS)
    for kind, names in items.items():
        for name in names:
            assert player_can_build(player, kind, name), (kind, name)
            tech = required_tech(kind, name)
            assert tech is None or tech in TECHS
            civic = required_civic(kind, name)
            assert civic is None or civic in CIVICS
    for name in unit_model.BUILDING_COSTS:
        env, city = _env_and_city()
        grant_all(city.player)
        _satisfy_non_tech_requirements(env, city, name)
        assert city_can_build_building(city, name), name
    for name, needed in unit_model.BUILDING_REQUIRES_BUILDING.items():
        assert needed in unit_model.BUILDING_COSTS, f"{name} needs an unbuildable {needed}"


def test_an_unknown_name_or_kind_is_never_available():
    """player_can_build answers False for a name that is not configured, and
    raises for a kind that does not exist. Breaks if a typo'd name reads as
    'ungated'."""
    env, city = _env_and_city()
    grant_all(city.player)
    for kind in KINDS:
        assert player_can_build(city.player, kind, "Teleporter") is False
    assert city_can_build_building(city, "Teleporter") is False
    with pytest.raises(ValueError):
        player_can_build(city.player, "wonder_of_the_world", "Pyramids")


# --- (b) a requirement naming nothing raises at load --------------------------------


def _units(**extra):
    table = dict(CFG["units"]["Warrior"])
    table.update(extra)
    return {"Probe": table}


def _buildings(**extra):
    tables = {"Base": {"production_cost": 10}, "Probe": {"production_cost": 10}}
    tables["Probe"].update(extra)
    return tables


@pytest.mark.parametrize("parse", [
    lambda: unit_model.parse_unit_gates(_units(requires_tech="Alchemy")),
    lambda: unit_model.parse_unit_gates(_units(requires_techs=TECH_ORDER[0])),     # typo'd key
    lambda: unit_model.parse_building_gates(_buildings(requires_tech="Alchemy")),
    lambda: unit_model.parse_building_gates(_buildings(requires_building="Nowhere")),
    lambda: unit_model.parse_building_gates(_buildings(requires_building="Probe")),  # itself
    lambda: unit_model.parse_building_gates({
        "A": {"production_cost": 1, "requires_building": "B"},
        "B": {"production_cost": 1, "requires_building": "A"}}),                    # a loop
    lambda: unit_model.parse_building_gates(_buildings(requires_district=3)),
    lambda: unit_model.parse_building_gates(_buildings(maintenance=-1)),
    lambda: unit_model.parse_building_gates(_buildings(maintenance=0.25)),
    lambda: unit_model.parse_building_gates(_buildings(requires_distrct="Campus")),  # typo'd key
    lambda: district_model.validate_building_districts(
        {"Probe": "Nowhere"}, district_model.DISTRICTS),
    lambda: district_model.parse_districts({
        **{k: v for k, v in CFG["districts"].items() if not isinstance(v, dict)},
        "Probe": {"production_cost": 10, "requires_tech": "Alchemy"}}),
    lambda: district_model.parse_districts({
        **{k: v for k, v in CFG["districts"].items() if not isinstance(v, dict)},
        "Probe": {"production_cost": 10, "maintenance": -1}}),
    lambda: terrain_model.parse_improvements({"Probe": {"requires_tech": "Alchemy"}}),
    lambda: terrain_model.parse_improvements({"Probe": {"requires_techs": TECH_ORDER[0]}}),
    # #116 P4: the civic and government-tier columns name real things
    lambda: unit_model.parse_unit_gates(_units(requires_civic="Some Civic")),
    lambda: unit_model.parse_building_gates(_buildings(requires_civic="Some Civic")),
    lambda: unit_model.parse_building_gates(_buildings(requires_government_tier=-1)),
    lambda: unit_model.parse_building_gates(_buildings(requires_government_tier=True)),
    lambda: unit_model.parse_building_gates(_buildings(requires_government_tier=1.5)),
    lambda: unit_model.parse_building_gates(_buildings(
        requires_government_tier=1 + max(g.tier for g in GOVERNMENTS.values()))),
    lambda: unit_model.parse_building_gates(_buildings(purchasable=["gems"])),
    lambda: unit_model.parse_building_gates(_buildings(purchasable=["gold", "gold"])),
    lambda: unit_model.parse_building_gates(_buildings(effects={"kind": "x"})),
    lambda: district_model.parse_districts({
        **{k: v for k, v in CFG["districts"].items() if not isinstance(v, dict)},
        "Probe": {"production_cost": 10, "requires_civic": "Some Civic"}}),
])
def test_a_requirement_naming_nothing_raises_at_load(parse):
    """A `requires_tech`, `requires_building` or `requires_district` that
    names nothing, a looping building chain, a bad maintenance, or a
    misspelt column raises in the owning loader. Breaks if validation is
    skipped and the item is silently ungated or unbuildable."""
    with pytest.raises(ValueError):
        parse()


def test_the_real_requirements_parse_and_name_real_items():
    """The configured gates parse and resolve: every requires_tech is a
    tech, every requires_district a district, every requires_building a
    building. Breaks if config.toml gains a dangling name."""
    for table in (unit_model.UNIT_REQUIRES_TECH, unit_model.BUILDING_REQUIRES_TECH,
                  terrain_model.IMPROVEMENT_REQUIRES_TECH):
        assert all(t in TECHS for t in table.values())
    assert all(s.requires_tech is None or s.requires_tech in TECHS
               for s in district_model.DISTRICTS.values())
    assert all(d in district_model.DISTRICTS
               for d in unit_model.BUILDING_REQUIRES_DISTRICT.values())
    assert all(b in unit_model.BUILDING_NAMES
               for b in unit_model.BUILDING_REQUIRES_BUILDING.values())


def test_civic_and_government_columns_parse_when_they_name_real_things():
    """`requires_civic` (units, buildings, districts) names a civic and
    `requires_government_tier` (buildings) a tier some government reaches;
    both are kept as declared (#116 P4; P2 accepted them raw). Breaks if a
    loader drops the columns."""
    civic = CIVIC_ORDER[-1]
    tier = max(g.tier for g in GOVERNMENTS.values())
    _, civics = unit_model.parse_unit_gates(_units(requires_civic=civic))
    assert civics == {"Probe": civic}
    gates = unit_model.parse_building_gates(
        _buildings(requires_civic=civic, requires_government_tier=tier))
    assert gates["requires_civic"] == {"Probe": civic}
    assert gates["requires_government_tier"] == {"Probe": tier}
    reg = district_model.parse_districts({
        **{k: v for k, v in CFG["districts"].items() if not isinstance(v, dict)},
        "Probe": {"production_cost": 10, "requires_civic": civic}})
    assert reg.districts["Probe"].requires_civic == civic


# --- (k) civic and government-tier gates on every build path (#116 P4) ---------------


def _civic_gated(kind_names):
    return [(kind, name) for kind, names in kind_names for name in names
            if required_civic(kind, name) is not None]


def test_every_civic_gate_refuses_until_the_civic_is_known_on_mask_and_production():
    """For every unit and building with a `requires_civic`, with every tech
    known, every other requirement met and every OTHER civic known, the
    build mask (when it is an option) and produce_unit / produce_building
    refuse it; with its civic they accept it. Breaks if a build path skips
    the civic in player_can_build (the mask invariant, #51)."""
    gated = _civic_gated([("unit", sorted(unit_model.UNIT_NAMES)),
                          ("building", sorted(unit_model.BUILDING_COSTS))])
    assert gated, "fixture: some unit or building is civic-gated"
    for kind, name in gated:
        env, city = _env_and_city()
        grant_all(city.player)
        if kind == "building":
            _satisfy_non_tech_requirements(env, city, name)
        civic = required_civic(kind, name)
        city.player.civics.remove(civic)
        produce = city.produce_building if kind == "building" else city.produce_unit
        idx = BUILD_OPTIONS.index(name) if name in BUILD_OPTIONS else None
        before = dict(city.current_production)
        assert not player_can_build(city.player, kind, name), name
        if idx is not None:
            assert get_valid_build_mask(city)[idx] == 0.0, name
        assert produce(name) is False and city.current_production == before, name
        city.player.civics.append(civic)
        if idx is not None:
            assert get_valid_build_mask(city)[idx] == 1.0, name
        assert produce(name) is True, name


def test_every_government_tier_gate_refuses_below_the_tier_and_without_a_government():
    """For every building with a `requires_government_tier`, with both trees
    known and every other requirement met: refused with no government
    (below every tier) and under every government of a lower tier, by the
    mask and by produce_building; accepted under every government of that
    tier or above. Breaks if the tier is not read, read from the wrong
    government, or compared the wrong way."""
    gated = sorted(unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER)
    assert gated, "fixture: some building is gated on a government tier"
    for name in gated:
        tier = unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER[name]
        env, city = _env_and_city()
        grant_all(city.player)
        _satisfy_non_tech_requirements(env, city, name)
        idx = BUILD_OPTIONS.index(name) if name in BUILD_OPTIONS else None
        city.player.government = None
        assert government_tier(city.player) == NO_GOVERNMENT_TIER < tier
        for government, spec in [(None, None), *GOVERNMENTS.items()]:
            if government is not None:
                assert env.set_government(city.player, government)
            allowed = spec is not None and spec.tier >= tier
            assert city_can_build_building(city, name) is allowed, (name, government)
            if idx is not None:
                assert get_valid_build_mask(city)[idx] == float(allowed), (name, government)
            if not allowed:
                assert city.produce_building(name) is False, (name, government)
        assert city.produce_building(name) is True, name


def test_the_mask_never_offers_an_option_production_would_refuse_across_civics():
    """For civic states from none to the whole tree (every tech known), with
    and without every district, an offered option is accepted by
    production. Breaks if mask and production read different civic gates."""
    for known in range(0, len(CIVIC_ORDER) + 1, 4):
        for with_districts in (False, True):
            env, city = _env_and_city()
            city.player.techs[:] = TECH_ORDER
            city.player.civics[:] = CIVIC_ORDER[:known]
            if with_districts:
                for i, district in enumerate(district_model.DISTRICTS):
                    _put_district(env, city, district, index=i)
            mask = get_valid_build_mask(city)
            for idx, option in enumerate(BUILD_OPTIONS):
                if mask[idx] == 1.0:
                    produce = (city.produce_building if _kind(option) == "building"
                               else city.produce_unit)
                    assert produce(option) is True, (option, known, with_districts)


def test_purchasable_is_parsed_for_every_building():
    """Every building carries a purchasable tuple (default gold), and the
    configured column is honoured exactly. Breaks if the column is dropped
    or the default changes silently."""
    assert set(unit_model.BUILDING_PURCHASABLE) == set(unit_model.BUILDING_NAMES)
    for name, table in CFG["buildings"].items():
        assert unit_model.BUILDING_PURCHASABLE[name] == tuple(table.get("purchasable", ["gold"]))


def test_maintenance_is_parsed_into_tenths_and_stored():
    """Building and district `maintenance` columns are int tenths of gold
    per turn (the treasury's unit), absent = 0, for P5 to deduct. Breaks if
    the column is dropped or stored unscaled."""
    for name, table in CFG["buildings"].items():
        assert unit_model.BUILDING_MAINTENANCE.get(name, 0) == round(10 * table.get("maintenance", 0))
    for name, table in CFG["districts"].items():
        if isinstance(table, dict):
            spec = district_model.DISTRICTS[name]
            assert spec.maintenance == round(10 * table.get("maintenance", 0))
            assert type(spec.maintenance) is int
