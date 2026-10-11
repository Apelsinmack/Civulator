"""Issue #86 D1: district adjacency, placement, cost and the engine path that
places a district (docs/districts_design.md §1-§4, §7 and "v3 fixes").

Boards are the all-Plains fixture of test_combat_range, rivers cleared, so
every adjacency source in a test is one the test put there.
"""

import inspect
import re
from types import SimpleNamespace

import pytest

from civulator import district_model, terrain_model
from civulator.agents.state_encoders import SettleSiteStateEncoder
from civulator.config import CFG
from civulator.game import districts as districts_mod
from civulator.game import environment as environment_mod
from civulator.game.districts import (
    District,
    adjacency_score,
    can_place_district,
    district_cost,
)
from civulator.game.environment import GameEnvironment
from civulator.game.territory import NEUTRAL
from civulator.game.unit import WarriorUnit

from test_combat_range import make_flat_env, place

DISTRICTS = district_model.DISTRICTS
CENTRE = (3, 5)


# --- Fixtures ------------------------------------------------------------------


def board():
    env = make_flat_env()
    env.map.rivers.clear()
    env.map.terrain_epoch += 1
    return env


def make_city(env, coords=CENTRE, player_index=0, population=1):
    city = env.create_city(env.players[player_index], coords, "C")
    city.population = population
    return city


def own(env, city, pos):
    """Give `pos` to `city` (fixture only: through the Map's own writers)."""
    owner = env.map.owner_id_at(pos)
    if owner == city.city_id:
        return
    if owner == NEUTRAL:
        env.map.claim(pos, city)
    else:
        env.map.transfer(pos, env.city_by_id[owner], city)


def ring(env, centre, d):
    return sorted(env.map.get_ring_coords(centre, d)[d])


def neighbours(env, pos):
    return list(env.map.get_adjacent_coords(pos))


def far_site(env, city):
    """A tile at distance 2 from the centre, owned by the city."""
    pos = ring(env, city.coordinates, 2)[0]
    own(env, city, pos)
    return pos


def near_site(env, city):
    """A tile adjacent to the centre (owned by founding)."""
    return ring(env, city.coordinates, 1)[0]


def placeable_type():
    """A configured land district with no rule of its own beyond the general
    ones, that takes a population slot."""
    for name, spec in DISTRICTS.items():
        if (spec.on is None and spec.adjacent_to_city_center is None
                and not spec.requires_adjacent and spec.counts_toward_limit
                and spec.max_per_player is None):
            return name
    pytest.skip("no plain land district configured")


def plain_types(n):
    names = [n_ for n_, s in DISTRICTS.items()
             if s.on is None and s.adjacent_to_city_center is None
             and not s.requires_adjacent and s.counts_toward_limit
             and s.max_per_player is None]
    if len(names) < n:
        pytest.skip(f"needs {n} plain land districts")
    return names[:n]


def type_with(predicate):
    for name, spec in DISTRICTS.items():
        if predicate(spec):
            return name
    pytest.skip("no configured district has this rule")


def row_for(district_type, kind, value=None):
    for row in DISTRICTS[district_type].adjacency:
        if row.source.kind == kind and (value is None or row.source.value == value
                                        or (isinstance(row.source.value, tuple)
                                            and value in row.source.value)):
            return row
    pytest.skip(f"{district_type} has no {kind} {value} row")


# --- Adjacency (§1.1) -----------------------------------------------------------


def _synthetic(monkeypatch, rows):
    cfg = {
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Probe": {"production_cost": 10, "adjacency": rows},
        "Marker": {"production_cost": 10},
    }
    reg = district_model.parse_districts(cfg)
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    return reg


def test_each_row_is_floored_on_its_own_then_summed(monkeypatch):
    """floor(count / per) * amount per row, rows summed afterwards. Breaks if
    counts are summed before flooring (one Mine + one Woods would then give 1)."""
    _synthetic(monkeypatch, [
        {"amount": 3, "per": 2, "terrain": {"features": ["Woods"]}},
        {"amount": 1, "per": 2, "improvement": ["Mine"]},
    ])
    env = board()
    pos = (4, 8)
    nbs = neighbours(env, pos)
    env.map.get_tile(nbs[0]).set_layers("Plains", feature="Woods", map_ref=env.map)
    env.map.get_tile(nbs[1]).add_improvement("Mine")
    assert adjacency_score("Probe", pos, env.map) == 0
    env.map.get_tile(nbs[2]).set_layers("Plains", feature="Woods", map_ref=env.map)
    assert adjacency_score("Probe", pos, env.map) == 3
    env.map.get_tile(nbs[3]).set_layers("Plains", feature="Woods", map_ref=env.map)
    assert adjacency_score("Probe", pos, env.map) == 3  # floor(3/2) * 3
    env.map.get_tile(nbs[4]).add_improvement("Mine")
    assert adjacency_score("Probe", pos, env.map) == 4


def test_industrial_zone_next_to_one_mine_and_one_district_scores_zero():
    """Civ 6's own example of per-row flooring. Breaks if rows are summed
    before flooring."""
    mine = row_for("Industrial Zone", "improvement", "Mine")
    generic = row_for("Industrial Zone", "district", "any")
    assert mine.per > 1 and generic.per > 1, "fixture: both rows are 'per 2'"
    env = board()
    city = make_city(env)
    pos = ring(env, CENTRE, 2)[0]
    # exactly one adjacent district: the city centre must not be adjacent.
    assert CENTRE not in neighbours(env, pos)
    nbs = [n for n in neighbours(env, pos) if env.map.distance_function(n, CENTRE) >= 2]
    env.map.get_tile(nbs[0]).add_improvement("Mine")
    env.map.get_tile(nbs[1]).district = District("Encampment", city.city_id, nbs[1])
    assert adjacency_score("Industrial Zone", pos, env.map) == 0


def test_city_centre_and_placed_unfinished_district_count_as_districts():
    """The generic "any" source counts the city centre and placed (incomplete)
    districts, whoever owns them. Breaks if either is dropped from the source."""
    name = type_with(lambda s: any(r.source.kind == "district" and r.source.value == "any"
                                   for r in s.adjacency))
    row = row_for(name, "district", "any")
    env = board()
    city = make_city(env, (3, 3), population=4)
    pos = near_site(env, city)
    alone = adjacency_score(name, pos, env.map)
    # a placed, incomplete district next to `pos`, not adjacent to the centre
    other = next(n for n in neighbours(env, pos)
                 if env.map.distance_function(n, city.coordinates) == 2)
    own(env, city, other)
    builder = type_with(lambda s: s.on is None and s.adjacent_to_city_center is not True
                        and not s.requires_adjacent)
    assert env.place_district(city, builder, other)
    assert env.map.get_tile(other).district.complete is False
    with_district = adjacency_score(name, pos, env.map)
    # centre + one district = 2 neighbours for the generic row
    assert with_district - alone == (2 // row.per - 1 // row.per) * row.amount

    # a foreign district counts too
    foreign = make_city(env, (3, 10), player_index=1)
    fpos = (3, 8)
    own(env, foreign, fpos)
    assert env.place_district(foreign, builder, fpos)
    probe = (3, 7)
    assert fpos in neighbours(env, probe)
    counted = sum(1 for n in neighbours(env, probe)
                  if env.map.get_tile(n).district or env.map.get_tile(n).city)
    assert adjacency_score(name, probe, env.map) >= (counted // row.per) * row.amount
    assert counted >= 1


def test_no_terrain_improvement_or_district_name_appears_in_districts_py():
    """Sources are matched through terrain_model / config names only. Breaks
    if a terrain, improvement or district name is written into the code."""
    source = inspect.getsource(districts_mod)
    names = (set(terrain_model.BASE_TABLE) | set(terrain_model.RELIEF_TABLE)
             | set(terrain_model.FEATURE_TABLE) | set(terrain_model.RESOURCE_TABLE)
             | set(terrain_model.IMPROVEMENT_NAMES) | set(DISTRICTS))
    quoted = set(re.findall(r'"([^"\n]+)"', source)) | set(re.findall(r"'([^'\n]+)'", source))
    assert not (quoted & names)


def test_river_on_tile_source_is_counted_once():
    """`river_on_tile` is a tile test: one river edge or three give the same
    score. Breaks if it is counted per neighbour."""
    name = type_with(lambda s: any(r.source.kind == "river_on_tile" for r in s.adjacency))
    row = row_for(name, "river_on_tile")
    env = board()
    pos = (4, 8)
    base = adjacency_score(name, pos, env.map)
    nbs = neighbours(env, pos)
    env.map.add_river(pos, nbs[0])
    assert adjacency_score(name, pos, env.map) == base + row.amount
    env.map.add_river(pos, nbs[1])
    env.map.add_river(pos, nbs[2])
    assert adjacency_score(name, pos, env.map) == base + row.amount


def test_resource_source_counts_only_tiles_with_a_matching_resource():
    """A `resources` row counts neighbours carrying a matching resource,
    through terrain_model.matches. Breaks if the resource is not passed."""
    name = type_with(lambda s: any(r.source.kind == "terrain" and "resources" in r.source.value
                                   for r in s.adjacency))
    row = next(r for r in DISTRICTS[name].adjacency
               if r.source.kind == "terrain" and "resources" in r.source.value)
    env = board()
    pos = (4, 8)
    nbs = neighbours(env, pos)
    for n in nbs[:2]:
        env.map.get_tile(n).set_layers("Coast", map_ref=env.map)
    base = adjacency_score(name, pos, env.map)
    env.map.get_tile(nbs[0]).set_layers("Coast", resource="Fish", map_ref=env.map)
    assert adjacency_score(name, pos, env.map) == base + (1 // row.per) * row.amount


# --- Placement (§2) -----------------------------------------------------------


def test_general_placement_rules_each_refuse():
    """Unowned, beyond radius, centre, district-occupied, next to another
    city's centre (own or foreign), mountain, water and a foreign unit each
    refuse placement; the base case is accepted. Breaks if any general rule is
    dropped."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4), population=1)
    site = far_site(env, city)
    assert can_place_district(city, t, site)

    # unowned
    env.map.release(site, city)
    assert not can_place_district(city, t, site)
    own(env, city, site)

    # beyond the work radius, though owned
    far = ring(env, city.coordinates, 4)[0]
    own(env, city, far)
    assert not can_place_district(city, t, far)

    # the centre itself
    assert not can_place_district(city, t, city.coordinates)

    # mountain / water
    tile = env.map.get_tile(site)
    tile.set_layers("Plains", relief="mountain", map_ref=env.map)
    assert not can_place_district(city, t, site)
    tile.set_layers("Coast", map_ref=env.map)
    assert not can_place_district(city, t, site)
    tile.set_layers("Plains", map_ref=env.map)
    assert can_place_district(city, t, site)

    # a foreign unit refuses, an own unit does not
    unit = place(env, WarriorUnit, 1, site)
    assert not can_place_district(city, t, site)
    env.remove_unit_from_tile(unit, site)
    place(env, WarriorUnit, 0, site)
    assert can_place_district(city, t, site)


def test_a_tile_next_to_another_city_centre_is_refused():
    """Not adjacent to ANOTHER city's centre, own or foreign. Breaks if the
    rule only looks at foreign cities or is dropped."""
    t = placeable_type()
    for other_player in (0, 1):
        env = board()
        city = make_city(env, (3, 4))
        site = far_site(env, city)
        assert can_place_district(city, t, site)
        spot = next(n for n in neighbours(env, site)
                    if env.map.distance_function(n, city.coordinates) == 3)
        make_city(env, spot, player_index=other_player)
        own(env, city, site)
        assert not can_place_district(city, t, site)


def test_a_tile_holding_a_district_refuses_another():
    """One district per tile. Breaks if the occupied check is dropped."""
    a, b = plain_types(2)
    env = board()
    city = make_city(env, (3, 4), population=1 + district_model.POPULATION_PER_DISTRICT)
    site = far_site(env, city)
    assert env.place_district(city, a, site)
    assert not can_place_district(city, b, site)
    other = ring(env, city.coordinates, 2)[1]
    own(env, city, other)
    assert can_place_district(city, b, other)


def test_features_are_allowed_exactly_when_removable_or_allowed():
    """A feature blocks placement unless it is in removable_features or
    allowed_features. Breaks if the feature rule is dropped or inverted."""
    land = placeable_type()
    water = type_with(lambda s: s.on is not None)
    for feature in terrain_model.FEATURE_TABLE:
        combo = None
        for base, spec in terrain_model.BASE_TABLE.items():
            for relief in ("flat", "hills"):
                try:
                    terrain_model.validate(base, relief=relief, feature=feature)
                except ValueError:
                    continue
                combo = (base, relief)
                break
            if combo:
                break
        assert combo, f"fixture: no valid tile for {feature}"
        env = board()
        city = make_city(env, (3, 4))
        site = near_site(env, city) if combo[0] in ("Coast", "Lake", "Ocean") else far_site(env, city)
        tile = env.map.get_tile(site)
        tile.set_layers(combo[0], relief=combo[1], map_ref=env.map)
        dtype = water if tile.is_water() else land
        if not can_place_district(city, dtype, site):
            continue  # this base is not a site for any probe district (e.g. Ocean)
        tile.set_layers(combo[0], relief=combo[1], feature=feature, map_ref=env.map)
        expected = feature in (district_model.REMOVABLE_FEATURES
                               | district_model.ALLOWED_FEATURES)
        assert can_place_district(city, dtype, site) == expected, feature


def test_only_bonus_resources_allow_placement(monkeypatch):
    """A bonus resource allows placement; any other class refuses. Breaks if
    the resource-class rule is dropped."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    env.map.get_tile(site).set_layers("Grassland", resource="Stone", map_ref=env.map)
    assert terrain_model.resource_class("Stone") == "bonus"
    assert can_place_district(city, t, site)
    monkeypatch.setitem(terrain_model.RESOURCE_TABLE["Stone"], "class", "luxury")
    assert not can_place_district(city, t, site)


def test_population_slots_limit_placed_districts():
    """1 + floor((pop - 1) / population_per_district) slot districts per city,
    counting placed (incomplete) ones; non-slot districts do not use a slot.
    Breaks if the formula or the counts_toward_limit flag is ignored."""
    a, b = plain_types(2)
    ppd = district_model.POPULATION_PER_DISTRICT
    env = board()
    city = make_city(env, (3, 4), population=1)
    s1, s2 = ring(env, city.coordinates, 2)[:2]
    own(env, city, s1)
    own(env, city, s2)
    assert env.place_district(city, a, s1)
    assert not can_place_district(city, b, s2)
    city.population = ppd  # still one slot
    assert not can_place_district(city, b, s2)
    city.population = ppd + 1
    assert can_place_district(city, b, s2)
    # the limit binds placement only: a placed district stays after pop loss
    city.population = 1
    assert len(city.districts) == 1


def test_non_slot_district_ignores_the_population_limit():
    """A `counts_toward_limit = false` district needs no free slot. Breaks if
    every district is counted."""
    free = type_with(lambda s: not s.counts_toward_limit)
    a = placeable_type()
    env = board()
    city = make_city(env, (3, 4), population=1)
    assert env.place_district(city, a, far_site(env, city))
    # build a site that satisfies `free`'s own rules: use a lake neighbour
    site = near_site(env, city)
    lake = next(n for n in neighbours(env, site)
                if n != city.coordinates and n not in neighbours(env, city.coordinates))
    env.map.get_tile(lake).set_layers("Lake", map_ref=env.map)
    assert can_place_district(city, free, site)


def test_max_per_city_and_max_per_player():
    """A second of the same type in one city is refused, and a
    max_per_player type is refused in a second city of the same player.
    Breaks if either limit is dropped."""
    a = placeable_type()
    env = board()
    city = make_city(env, (3, 4), population=10)
    s1, s2 = ring(env, city.coordinates, 2)[:2]
    own(env, city, s1)
    own(env, city, s2)
    assert env.place_district(city, a, s1)
    if DISTRICTS[a].max_per_city == 1:
        assert not can_place_district(city, a, s2)

    capped = type_with(lambda s: s.max_per_player is not None and s.on is None
                       and s.adjacent_to_city_center is None and not s.requires_adjacent)
    limit = DISTRICTS[capped].max_per_player
    env = board()
    cities = [make_city(env, (3, 3 + 6 * i), population=10) for i in range(limit + 1)]
    for c in cities[:limit]:
        assert env.place_district(c, capped, far_site(env, c))
    assert not can_place_district(cities[limit], capped, far_site(env, cities[limit]))
    # another player is not limited by this one
    rival = make_city(env, (7, 6), player_index=1, population=10)
    site = next(p for p in ring(env, rival.coordinates, 1) if p[0] < 8)
    assert can_place_district(rival, capped, site)


def test_aqueduct_needs_the_centre_and_a_qualifying_neighbour():
    """Aqueduct: adjacent to the centre, plus a lake, oasis, mountain or a
    river on an edge NOT shared with the centre. Breaks if the Aqueduct rule
    drifts (e.g. the centre's river edge qualifies)."""
    t = type_with(lambda s: s.adjacent_to_city_center is True and s.requires_adjacent)
    env = board()
    city = make_city(env, (3, 4))
    site = near_site(env, city)
    assert not can_place_district(city, t, site)  # nothing qualifying

    # the river on the shared edge does not qualify
    env.map.add_river(site, city.coordinates)
    assert not can_place_district(city, t, site)
    # a river on another edge does
    other = next(n for n in neighbours(env, site) if n != city.coordinates)
    env.map.add_river(site, other)
    assert can_place_district(city, t, site)
    env.map.rivers.clear()
    env.map.terrain_epoch += 1

    outer = next(n for n in neighbours(env, site)
                 if n != city.coordinates and n not in neighbours(env, city.coordinates))
    for layers in ({"base": "Lake"}, {"base": "Desert", "feature": "Oasis"},
                   {"base": "Plains", "relief": "mountain"}):
        tile = env.map.get_tile(outer)
        tile.set_layers(layers["base"], relief=layers.get("relief"),
                        feature=layers.get("feature"), map_ref=env.map)
        assert can_place_district(city, t, site), layers
        tile.set_layers("Plains", map_ref=env.map)
    assert not can_place_district(city, t, site)

    # not adjacent to the centre: refused even next to a lake
    far = far_site(env, city)
    lake = next(n for n in neighbours(env, far)
                if env.map.distance_function(n, city.coordinates) == 3)
    env.map.get_tile(lake).set_layers("Lake", map_ref=env.map)
    assert not can_place_district(city, t, far)


def test_harbor_on_coast_or_lake_next_to_land_not_on_reef():
    """Harbor: its own `on` (Coast/Lake), adjacent to land, never on Reef.
    Breaks if the district's `on` or requires_adjacent is ignored."""
    t = type_with(lambda s: s.on is not None)
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    tile = env.map.get_tile(site)
    assert not can_place_district(city, t, site)  # land
    for base in ("Coast", "Lake"):
        tile.set_layers(base, map_ref=env.map)
        assert can_place_district(city, t, site), base
    tile.set_layers("Ocean", map_ref=env.map)
    assert not can_place_district(city, t, site)
    tile.set_layers("Coast", feature="Reef", map_ref=env.map)
    assert not can_place_district(city, t, site)
    # surrounded by water: no land neighbour
    tile.set_layers("Coast", map_ref=env.map)
    for n in neighbours(env, site):
        if env.map.get_tile(n).city is None:
            env.map.get_tile(n).set_layers("Ocean", map_ref=env.map)
    if all(env.map.get_tile(n).is_water() for n in neighbours(env, site)):
        assert not can_place_district(city, t, site)
    # a mountain neighbour counts as land
    n0 = neighbours(env, site)[0]
    env.map.get_tile(n0).set_layers("Plains", relief="mountain", map_ref=env.map)
    assert can_place_district(city, t, site)


def test_encampment_may_not_touch_the_centre():
    """`adjacent_to_city_center = false` forbids a ring-1 tile. Breaks if the
    flag is read as 'either'."""
    t = type_with(lambda s: s.adjacent_to_city_center is False)
    env = board()
    city = make_city(env, (3, 4))
    assert not can_place_district(city, t, near_site(env, city))
    assert can_place_district(city, t, far_site(env, city))


# --- Placing: clearing, epochs, never worked, production -----------------------


def test_placing_clears_removable_feature_bonus_resource_and_improvements():
    """One set_layers call clears a removable feature with its resource (Deer
    needs its Woods), improvements are emptied, the terrain and district
    epochs bump. Breaks if layers are mutated without set_layers(map_ref=...)
    or the feature is cleared alone (validate would raise)."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    tile = env.map.get_tile(site)
    tile.set_layers("Plains", feature="Woods", resource="Deer", map_ref=env.map)
    tile.add_improvement("Camp")
    terrain, district = env.map.terrain_epoch, env.map.district_epoch
    assert env.place_district(city, t, site)
    assert tile.feature is None and tile.resource is None and tile.improvements == []
    assert env.map.terrain_epoch > terrain
    assert env.map.district_epoch > district
    assert tile.district is city.districts[-1]
    assert tile.district.city_id == city.city_id and tile.district.coordinates == site


def test_placing_keeps_an_allowed_feature_and_touches_no_layer_when_bare():
    """Allowed features stay (Floodplains); a bare tile's layers are not
    rewritten, so the terrain epoch stays. Breaks if every placement calls
    set_layers or clears allowed features."""
    t = placeable_type()
    kept = sorted(district_model.ALLOWED_FEATURES)
    env = board()
    city = make_city(env, (3, 4), population=10)
    s1, s2 = ring(env, city.coordinates, 2)[:2]
    own(env, city, s1)
    own(env, city, s2)
    terrain = env.map.terrain_epoch
    assert env.place_district(city, t, s1)
    assert env.map.terrain_epoch == terrain
    if kept:
        other = next(n for n, s in DISTRICTS.items() if n != t and s.on is None
                     and s.adjacent_to_city_center is None and not s.requires_adjacent)
        tile = env.map.get_tile(s2)
        combo = next(b for b in terrain_model.BASE_TABLE
                     if terrain_model.check_on("feature", kept[0], b, "flat", None))
        tile.set_layers(combo, feature=kept[0], map_ref=env.map)
        assert env.place_district(city, other, s2)
        assert tile.feature == kept[0]


def test_a_worked_tile_is_released_on_placement_and_never_worked_again():
    """place_district re-runs assign_tiles; assign_tiles never picks a district
    tile, placed or complete. Breaks if either step ignores districts."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4), population=1)
    site = far_site(env, city)
    env.map.get_tile(site).set_layers("Grassland", resource="Cattle", map_ref=env.map)
    city.assign_tiles(env)
    assert city.worked_tiles == [site]
    assert env.place_district(city, t, site)
    assert site not in city.worked_tiles
    env.map.get_tile(site).district.complete = True
    city.population = len(env.map.tiles_of_city(city.city_id)) + 5
    city.assign_tiles(env)
    assert site not in city.worked_tiles


def test_placement_sets_district_production_and_process_turn_survives():
    """Placing points production at the district; process_turn copes with it
    (D1 leaves it unbuilt; D2 completes it). Breaks if a district production
    dict crashes the turn."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    assert env.place_district(city, t, far_site(env, city))
    assert city.current_production == {"type": "district", "district_type": t}
    for _ in range(3):
        env.turn_counter += 1
        city.process_turn(env)


def test_failed_placement_mutates_nothing():
    """A refused placement leaves tile, city and epochs untouched. Breaks if
    place_district writes before checking."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    before = (env.map.terrain_epoch, env.map.district_epoch, list(city.districts),
              dict(city.current_production))
    assert not env.place_district(city, t, city.coordinates)
    assert not env.place_district(city, "No Such District", far_site(env, city))
    assert (env.map.terrain_epoch, env.map.district_epoch, list(city.districts),
            dict(city.current_production)) == before


# --- Refusal paths and caches -----------------------------------------------------


def test_a_district_tile_hosts_no_city_improvement_or_swap(monkeypatch):
    """can_found_city_at, create_city, can_build_improvement_at and swap_tile
    all refuse a district tile, and it stays owned by its city. Breaks if any
    of them ignores districts."""
    monkeypatch.setattr(environment_mod, "MIN_CITY_DISTANCE", 1)
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    control = ring(env, city.coordinates, 2)[1]
    own(env, city, control)
    assert env.can_found_city_at(site, city.player)
    assert env.can_build_improvement_at(site, "Farm")
    assert env.place_district(city, t, site)

    assert not env.can_found_city_at(site, city.player)
    assert not env.can_found_city_at(site, env.players[1])
    with pytest.raises(ValueError):
        env.create_city(city.player, site, "Nope")
    assert not env.can_build_improvement_at(site, "Farm")
    assert env.can_build_improvement_at(control, "Farm")

    spot = next(p for p in ring(env, site, 2)
                if env.map.distance_function(p, city.coordinates) >= 3
                and env.map.owner_id_at(p) == NEUTRAL)
    second = make_city(env, spot)
    assert not env.swap_tile(site, second)
    # control: an ordinary owned tile at the same kind of spot does swap
    swappable = next(
        p for p in env.map.tiles_of_city(city.city_id)
        if p != site and env.map.get_tile(p).district is None
        and env.map.distance_function(p, city.coordinates) >= 2
        and env.map.distance_function(p, second.coordinates) <= 3
    )
    assert env.swap_tile(swappable, second)
    assert env.map.owner_id_at(site) == city.city_id
    assert env.map.get_tile(site).district.city_id == env.map.owner_id_at(site)


def test_settle_layer_sees_a_district_on_a_bare_tile(monkeypatch):
    """A district on a featureless, resourceless tile changes neither terrain
    nor territory, yet the settle layer must drop the tile. Breaks if the
    settle cache key misses district_epoch."""
    monkeypatch.setattr(environment_mod, "MIN_CITY_DISTANCE", 1)
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    encoder = SettleSiteStateEncoder(fog_of_war=False)
    assert encoder._get_settle_layer(env, 0)[site] == 1.0
    terrain, territory = env.map.terrain_epoch, env.map.territory_epoch
    assert env.place_district(city, t, site)
    assert (env.map.terrain_epoch, env.map.territory_epoch) == (terrain, territory)
    assert encoder._get_settle_layer(env, 0)[site] == 0.0


def test_remove_city_clears_its_districts():
    """remove_city deletes both references and bumps district_epoch. Breaks if
    district references outlive their city."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    assert env.place_district(city, t, site)
    epoch = env.map.district_epoch
    env.remove_city(city)
    assert env.map.get_tile(site).district is None
    assert city.districts == []
    assert env.map.district_epoch > epoch


# --- Cost (§4, v3 one integer rule) ------------------------------------------------


def _player_with_completed(types):
    city = SimpleNamespace(districts=[District(t, 0, (0, i), complete=True)
                                      for i, t in enumerate(types)])
    return SimpleNamespace(cities=[city])


def test_discount_follows_the_integer_rule_a9_b10(monkeypatch):
    """A = 9, B = 10: a type held once is discounted, twice is not
    (count_T * A < B). Breaks on real division or a different rounding order."""
    disc = [n for n, s in DISTRICTS.items() if s.cost_model == "discounted"]
    t = disc[0]
    nine = tuple(disc + [f"pad{i}" for i in range(9 - len(disc))])[:9]
    monkeypatch.setattr(districts_mod, "DISCOUNTED_TYPES", nine)
    spec = DISTRICTS[t]
    others = [n for n in disc if n != t]
    full = spec.production_cost
    cheap = full * (100 - spec.discount_percent) // 100

    held_once = _player_with_completed([t] + [others[i % len(others)] for i in range(9)])
    assert district_cost(held_once, t) == cheap
    held_twice = _player_with_completed([t, t] + [others[i % len(others)] for i in range(8)])
    assert district_cost(held_twice, t) == full
    # B < A: never discounted
    few = _player_with_completed(others[:3])
    assert district_cost(few, t) == full


def test_discount_needs_completed_discounted_districts_only():
    """Incomplete districts and non-discounted types do not count toward B;
    a non-discounted type is never discounted. Breaks if placed districts or
    other cost models feed the rule."""
    a = len(district_model.DISCOUNTED_TYPES)
    disc = list(district_model.DISCOUNTED_TYPES)
    progress = type_with(lambda s: s.cost_model == "progress")
    t = disc[0]
    others = disc[1:] or disc
    types = [others[i % len(others)] for i in range(a + 1)]
    player = _player_with_completed(types)
    spec = DISTRICTS[t]
    assert district_cost(player, t) == spec.production_cost * (100 - spec.discount_percent) // 100
    for d in player.cities[0].districts:
        d.complete = False
    assert district_cost(player, t) == spec.production_cost
    player = _player_with_completed([progress] * (a + 1))
    assert district_cost(player, t) == spec.production_cost
    assert district_cost(_player_with_completed(types), progress) == \
        DISTRICTS[progress].production_cost


def test_escalation_is_integer_and_fixed_never_scales(monkeypatch):
    """escalated = base * (den + factor * num) // den; "fixed" is the base.
    Breaks if float arithmetic or scaling of fixed creeps in."""
    assert districts_mod.game_progress(None) == (0, 1)
    monkeypatch.setattr(districts_mod, "game_progress", lambda player: (1, 7))
    factor = district_model.COST_PROGRESS_FACTOR
    player = _player_with_completed([])
    for name, spec in DISTRICTS.items():
        expected = spec.production_cost * (7 + factor * 1) // 7
        assert district_cost(player, name) == expected
    reg = district_model.parse_districts({
        **{k: v for k, v in CFG["districts"].items() if not isinstance(v, dict)},
        "Port": {"production_cost": 50, "cost_model": "fixed"},
    })
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    assert district_cost(player, "Port") == 50


def test_cost_is_locked_at_placement():
    """The cost is stored on the District when placed and not recomputed.
    Breaks if the cost is read live from district_cost later."""
    t = district_model.DISCOUNTED_TYPES[0]
    if DISTRICTS[t].on is not None or DISTRICTS[t].requires_adjacent \
            or DISTRICTS[t].adjacent_to_city_center:
        t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    assert env.place_district(city, t, far_site(env, city))
    locked = city.districts[-1].cost
    assert locked == DISTRICTS[t].production_cost
    others = [n for n in district_model.DISCOUNTED_TYPES if n != t]
    for i in range(len(district_model.DISCOUNTED_TYPES) + 1):
        city.districts.append(District(others[i % len(others)], city.city_id, (7, i),
                                       complete=True))
    assert district_cost(city.player, t) < DISTRICTS[t].production_cost
    assert city.districts[0].cost == locked


# --- Determinism -------------------------------------------------------------------


def _place_everything(seed):
    env = GameEnvironment(8, 16, num_players=2, map_type="basic")
    env.reset(seed=seed)
    for player in env.players:
        for city in player.cities:
            city.population = 10
            for pos in env.map.tiles_of_city(city.city_id):
                for name in DISTRICTS:
                    env.place_district(city, name, pos)
    return [
        (d.type, d.city_id, d.coordinates, d.cost, d.complete,
         adjacency_score(d.type, d.coordinates, env.map))
        for player in env.players for city in player.cities for d in city.districts
    ]


def test_same_seed_same_actions_give_identical_districts():
    """A seeded world with the same placement sequence reproduces districts,
    costs and scores exactly. Breaks if anything depends on set iteration or
    an unseeded source."""
    first = _place_everything(31)
    assert first, "fixture: something was placed"
    assert first == _place_everything(31)
