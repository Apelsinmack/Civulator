"""The Industrial Zone and what feeds it (v0.9.0 Q4, docs/districts_religion_design.md
section 5, section 11 rows 14-16, rulings R5 / C3 / C4): the strategic adjacency
row, the Workshop's value, the `regional_yield` effect and its one consumer, the
Dam, and the `regional_production` stat.

Every test names the property it protects and the change that breaks it.
Numbers are read from the registries and the parsed effect (the Workshop's
column from `unit_model.BUILDING_YIELDS`, the effect's amount and range from
`effects_of`, an adjacency row's amount from `DISTRICTS`), never written here;
nothing pins how many strategic resources or carriers exist.

Regional tests run on test_loyalty's `flat` board (8 x 40 Plains, one row of
cities, so the canonical distance between two cities is their column
difference) with districts linked by hand and the amenity bands neutralised
(the subject is production arithmetic, not the happiness band).
"""

import pytest

from civulator import district_model, terrain_model, unit_model
from civulator.district_model import DISTRICTS
from civulator.effects import KIND_REGIONAL_YIELD, effects_of
from civulator.game import amenities
from civulator.game.districts import District, adjacency_score, can_place_district
from civulator.game.housing import housing
from civulator.game.yields import city_yield
from civulator.terrain_model import resource_class, resources_of_class

from test_districts import board, far_site, make_city, neighbours, own, placeable_type, ring
from test_loyalty import city, flat, play_round
from test_resource_tiers import put

IZ = "Industrial Zone"
pytestmark = pytest.mark.usefixtures("neutral_amenities")

WORKSHOP = effects_of("building", "Workshop")[0]
REACH = WORKSHOP["range"]
PAID = WORKSHOP["yields"]["production"]  # int tenths of production


def _whole(tenths):
    """Whole production points a tenths amount adds to `city_yield` (floored)."""
    return tenths // 10


def link(env, owner, district_type, pos, complete=True):
    """Fixture only: link a District of `owner`'s by hand at `pos`."""
    district = District(district_type, owner.city_id, pos, complete=complete, cost=10)
    env.map.get_tile(pos).district = district
    owner.districts.append(district)
    return district


def carrier(env, seat, col, workshop=False, zone="complete"):
    """A city of `seat` at column `col` with an Industrial Zone two tiles east
    of it (`zone`: "complete", "placed" or None) and, with `workshop`, the
    Workshop in its buildings. Returns (city, zone tile)."""
    made = city(env, seat, col)
    tile = None
    if zone:
        tile = link(env, made, IZ, (made.coordinates[0], (col + 2) % env.m),
                    complete=zone == "complete").coordinates
    if workshop:
        made.buildings.append("Workshop")
    return made, tile


def production_gain(target, act):
    """The change of `target`'s `city_yield(production)` and of its
    `calculate_production` caused by `act()`."""
    env = target.player.game_env
    before = (city_yield(target, "production"), target.calculate_production(env))
    act()
    return (city_yield(target, "production") - before[0],
            target.calculate_production(env) - before[1])


def test_the_fixture_is_sound():
    """The effect under test pays production, at a whole number of points, to a
    positive reach, from a building that stands in the Industrial Zone. Breaks
    only if the carrier is re-tuned out of what these tests can observe."""
    assert PAID > 0 and PAID % 10 == 0 and REACH > 0
    assert unit_model.BUILDING_REQUIRES_DISTRICT["Workshop"] == IZ


# --- the Workshop's value (config, a declared rule change) ---------------------------


def test_the_workshop_adds_exactly_its_config_column_to_its_own_city():
    """A Workshop in a city with a complete Industrial Zone adds its
    `[buildings.Workshop] production` column to that city's production and
    nothing from its own regional effect (the carrier's city is never paid).
    Breaks if the value is a literal elsewhere, or the consumer pays the
    carrier's own city."""
    from civulator.config import CFG

    env = flat()
    home, _ = carrier(env, 0, 4)
    column = unit_model.BUILDING_YIELDS["production"]["Workshop"]
    assert column == round(10 * CFG["buildings"]["Workshop"]["production"])
    gain, _ = production_gain(home, lambda: home.buildings.append("Workshop"))
    assert gain == _whole(column)


# --- row 14 (R5): the neighbour's Aqueduct --------------------------------------------


@pytest.mark.parametrize("owner", ["same city", "another city of the player", "another player"])
def test_any_aqueduct_next_to_an_industrial_zone_counts_whoever_owns_it(owner):
    """The named `district = ["Aqueduct"]` row counts an adjacent Aqueduct of
    this city, of a neighbour city of the same player, or of a city of another
    player alike -- the two-cities-one-river minigame (R5). Breaks if
    `_neighbour_matches` starts reading the owner."""
    env = flat()
    row = next(r for r in DISTRICTS[IZ].adjacency
               if r.source.kind == "district" and r.source.value == ("Aqueduct",))
    mine = city(env, 0, 10)
    pos = (4, 14)
    base = adjacency_score(IZ, pos, env.map)
    holder = {"same city": lambda: mine, "another city of the player": lambda: city(env, 0, 20),
              "another player": lambda: city(env, 1, 20)}[owner]()
    aside = env.map.get_adjacent_coords(pos)[0]
    link(env, holder, "Aqueduct", aside)
    assert adjacency_score(IZ, pos, env.map) == base + row.amount


# --- row 15: the strategic adjacency row ------------------------------------------------


def strategic_row():
    return next(r for r in DISTRICTS[IZ].adjacency
                if r.source.kind == "terrain" and "resources" in r.source.value)


def test_the_industrial_zone_declares_the_class_form_of_the_strategic_row():
    """The row names the class `strategic`, not a list of resources, so a new
    strategic resource scores with no edit. Breaks if the row is spelled with
    resource names."""
    assert list(strategic_row().source.value["resources"]) == ["strategic"]


@pytest.mark.parametrize("resource", resources_of_class("strategic"))
def test_each_adjacent_strategic_resource_counts_once(resource):
    """One adjacent tile carrying any member of the strategic class adds the
    row's amount, once. Breaks if the class match in `matches` breaks, or the
    row counts a tile twice."""
    env = board()
    pos = (4, 8)
    base = adjacency_score(IZ, pos, env.map)
    put(env, neighbours(env, pos)[0], resource)
    assert adjacency_score(IZ, pos, env.map) == base + strategic_row().amount


def test_adjacent_strategic_tiles_count_one_each_and_other_classes_never():
    """Each adjacent strategic tile adds the amount (two tiles of the same
    resource add it twice); a luxury or a bonus resource beside them adds
    nothing. Breaks if the row counts per resource name instead of per tile,
    or matches a class other than strategic."""
    env = board()
    pos = (4, 8)
    nbs = neighbours(env, pos)
    base = adjacency_score(IZ, pos, env.map)
    strategic = list(resources_of_class("strategic"))
    for i in range(3):
        put(env, nbs[i], strategic[i % len(strategic)] if i < 2 else strategic[0])
    assert adjacency_score(IZ, pos, env.map) == base + 3 * strategic_row().amount
    others = [n for n in terrain_model.RESOURCE_TABLE if resource_class(n) != "strategic"]
    assert any(resource_class(n) == "luxury" for n in others)
    for i, name in enumerate(others[:3]):
        put(env, nbs[3 + i], name)
    assert adjacency_score(IZ, pos, env.map) == base + 3 * strategic_row().amount


# --- the Dam (C4) -----------------------------------------------------------------------


def dam_world():
    """A board, a city with a Floodplains tile at distance 2 that has a river
    edge; returns (env, city, site)."""
    env = board()
    owner = make_city(env, (3, 4))
    site = far_site(env, owner)
    env.map.get_tile(site).set_layers("Desert", relief="flat", feature="Floodplains",
                                      map_ref=env.map)
    env.map.add_river(site, neighbours(env, site)[0])
    return env, owner, site


def test_the_dam_declares_what_the_design_says():
    """The Dam is a plain district table that takes no population slot, one per
    city, with a housing and an amenity column and no adjacency of its own, on
    a Floodplains tile with a river. Breaks if it is turned into a wonder or a
    limit-counting district, or gains adjacency."""
    spec = DISTRICTS["Dam"]
    assert spec.kind == district_model.KIND_DISTRICT
    assert not spec.counts_toward_limit and spec.max_per_city == 1
    assert spec.adjacency == () and spec.adjacency_yield == "none"
    assert spec.housing > 0 and spec.amenity > 0
    assert spec.on == {"features": ["Floodplains"]}
    assert any(s.kind == "river_on_tile" for s in spec.requires_adjacent)


def test_the_dam_places_only_on_floodplains_with_a_river_edge():
    """Floodplains plus a river along an edge is placeable; the same tile
    without the river, or a river tile without Floodplains, is refused. Breaks
    if `on` or the river requirement is dropped from the table or the loader."""
    env, owner, site = dam_world()
    assert can_place_district(owner, "Dam", site)

    dry, _, dry_site = dam_world()
    dry.map.rivers.clear()
    dry.map.terrain_epoch += 1
    assert not can_place_district(dry.city_by_id[0], "Dam", dry_site)

    plain, plain_owner, plain_site = dam_world()
    plain.map.get_tile(plain_site).set_layers("Plains", map_ref=plain.map)
    assert not can_place_district(plain_owner, "Dam", plain_site)


def test_the_dam_needs_its_tech():
    """Without the tech named by `requires_tech` the Dam is refused; with it,
    placeable. Breaks if the Dam stops being gated by research."""
    env, owner, site = dam_world()
    tech = DISTRICTS["Dam"].requires_tech
    assert tech is not None
    owner.player.techs.remove(tech)
    assert not can_place_district(owner, "Dam", site)
    owner.player.techs.append(tech)
    assert can_place_district(owner, "Dam", site)


def test_the_dam_takes_no_population_slot_and_is_one_per_city():
    """A city whose population slots are all used still places its Dam, the Dam
    uses no slot (a plain district is still refused afterwards), and a second
    Dam in the same city is refused. Breaks if `counts_toward_limit` or
    `max_per_city` changes."""
    env, owner, site = dam_world()
    plain = placeable_type()
    first, second = ring(env, owner.coordinates, 1)[:2]
    assert env.place_district(owner, plain, first)
    assert not can_place_district(owner, plain, second), "the one slot is used"
    assert can_place_district(owner, "Dam", site)
    assert env.place_district(owner, "Dam", site)
    assert not can_place_district(owner, plain, second), "the Dam took no slot"
    again = [p for p in ring(env, owner.coordinates, 2) if p != site][0]
    own(env, owner, again)
    env.map.get_tile(again).set_layers("Desert", relief="flat", feature="Floodplains",
                                       map_ref=env.map)
    env.map.add_river(again, neighbours(env, again)[0])
    assert not can_place_district(owner, "Dam", again), "one Dam per city"


def test_a_complete_dam_adds_its_housing_and_amenity_columns_and_an_unfinished_one_nothing():
    """Housing and amenity supply rise by exactly the Dam's `housing` /
    `amenity` columns when it completes, and not before. Breaks if the columns
    are not read by the housing and amenity readers, or are read while the
    district is unfinished."""
    env, owner, site = dam_world()
    spec = DISTRICTS["Dam"]
    h0, a0 = housing(owner), amenities.supply(owner, env)
    assert env.place_district(owner, "Dam", site)
    assert (housing(owner), amenities.supply(owner, env)) == (h0, a0)
    env.complete_district(owner, owner.districts[-1])
    assert housing(owner) == h0 + spec.housing
    assert amenities.supply(owner, env) == a0 + spec.amenity


def test_an_adjacent_dam_adds_the_industrial_zones_dam_row():
    """An Industrial Zone beside a Dam (placed or complete) scores the Dam row's
    amount more. Breaks if the row is dropped from the Industrial Zone table."""
    env = board()
    row = next(r for r in DISTRICTS[IZ].adjacency
               if r.source.kind == "district" and r.source.value == ("Dam",))
    owner = make_city(env, (3, 4))
    pos = (4, 8)
    base = adjacency_score(IZ, pos, env.map)
    link(env, owner, "Dam", neighbours(env, pos)[0], complete=False)
    assert adjacency_score(IZ, pos, env.map) == base + row.amount


# --- row 16: regional_yield ---------------------------------------------------------------


def test_workshop_pays_another_own_city_within_range_of_the_zone_tile():
    """A target city of the owner within `range` of the Industrial Zone's TILE
    gains the effect's production through `city_yield` and through
    `calculate_production`; one a tile beyond does not; a city within range of
    the carrier's CENTRE but beyond range of the zone tile does not. Breaks if
    the origin is the carrier city, the range is off by one, or production
    does not reach `calculate_production`."""
    env = flat()
    home, zone = carrier(env, 0, 10)
    targets = {"inside": city(env, 0, zone[1] + REACH),
               "outside": city(env, 0, zone[1] + REACH + 1),
               "centre only": city(env, 0, home.coordinates[1] - REACH)}
    assert env.map.distance_function(targets["centre only"].coordinates, home.coordinates) <= REACH
    assert env.map.distance_function(targets["centre only"].coordinates, zone) > REACH
    assert env.map.distance_function(targets["inside"].coordinates, home.coordinates) > REACH
    before = {n: (city_yield(t, "production"), t.calculate_production(env))
              for n, t in targets.items()}
    home.buildings.append("Workshop")
    after = {n: (city_yield(t, "production"), t.calculate_production(env))
             for n, t in targets.items()}
    assert after["inside"][0] - before["inside"][0] == _whole(PAID)
    assert after["inside"][1] - before["inside"][1] == _whole(PAID)
    assert after["outside"] == before["outside"]
    assert after["centre only"] == before["centre only"]


def test_regional_yield_wraps_around_the_cylinder():
    """Range is the canonical wrap distance: a target across the seam, within
    range of the zone tile, is paid. Breaks if the consumer uses a flat column
    difference."""
    env = flat()
    home, zone = carrier(env, 0, env.m - 3)  # zone tile at column env.m - 1
    target = city(env, 0, (zone[1] + REACH) % env.m)
    assert abs(target.coordinates[1] - zone[1]) > REACH, "the straight difference is out of range"
    gain, _ = production_gain(target, lambda: home.buildings.append("Workshop"))
    assert gain == _whole(PAID)


def test_regional_yield_never_pays_a_foreign_city():
    """A city of another player in range gains nothing from my Workshop, and my
    cities gain nothing from a foreign Workshop. Breaks if the consumer reads
    cities by position instead of by owner."""
    env = flat()
    mine, _ = carrier(env, 0, 10)
    foreign_target = city(env, 1, 14)
    foreign_home, _ = carrier(env, 1, 24)
    my_target = city(env, 0, 28)
    gain_foreign, _ = production_gain(foreign_target, lambda: mine.buildings.append("Workshop"))
    gain_mine, _ = production_gain(my_target, lambda: foreign_home.buildings.append("Workshop"))
    assert gain_foreign == 0 and gain_mine == 0


def test_regional_yield_takes_the_max_over_carriers_never_a_sum():
    """A city within reach of two Workshops is paid the effect's amount once.
    Breaks if the consumer sums."""
    env = flat()
    one, _ = carrier(env, 0, 10)
    two, _ = carrier(env, 0, 18)
    target = city(env, 0, 14)
    first, _ = production_gain(target, lambda: one.buildings.append("Workshop"))
    second, _ = production_gain(target, lambda: two.buildings.append("Workshop"))
    assert first == _whole(PAID)
    assert second == 0


def test_two_workshops_in_reach_of_each_other_pay_each_one_amount():
    """Each of two carriers in range of the other gains its own Workshop column
    plus the effect's amount once (from the other), never twice and never
    from itself. Breaks if a carrier is paid by its own effect, or the pair
    sums."""
    env = flat()
    one, _ = carrier(env, 0, 10)
    two, _ = carrier(env, 0, 14)
    column = unit_model.BUILDING_YIELDS["production"]["Workshop"]
    before = [city_yield(c, "production") for c in (one, two)]
    one.buildings.append("Workshop")
    two.buildings.append("Workshop")
    after = [city_yield(c, "production") for c in (one, two)]
    assert [a - b for a, b in zip(after, before)] == [_whole(column + PAID)] * 2


def test_regional_yield_pays_nothing_without_a_complete_zone_and_a_built_workshop():
    """An unbuilt Workshop, an unfinished Industrial Zone, and a Workshop whose
    zone is gone pay nothing. Breaks if the carrier's tile is taken from
    anything but a complete district, or the building is not required."""
    env = flat()
    target = city(env, 0, 14)
    unbuilt, _ = carrier(env, 0, 10)
    assert production_gain(target, lambda: None) == (0, 0)

    env = flat()
    target = city(env, 0, 14)
    placed, _ = carrier(env, 0, 10, zone="placed")
    gain, _ = production_gain(target, lambda: placed.buildings.append("Workshop"))
    assert gain == 0

    env = flat()
    target = city(env, 0, 14)
    gone, _ = carrier(env, 0, 10, zone=None)
    gain, _ = production_gain(target, lambda: gone.buildings.append("Workshop"))
    assert gain == 0


def test_regional_stat_counts_what_the_owners_cities_were_paid_each_round():
    """`episode_stats["regional_production"]` grows, per round, by the tenths
    the owner's cities are paid by regional effects (one amount per paid city,
    the carrier's own city not among them), and a player with no paid city
    stays at 0. Breaks if the stat pays the carrier, the foreign player, or is
    not accumulated per round."""
    env = flat()
    home, _ = carrier(env, 0, 10, workshop=True)
    paid = [city(env, 0, 14), city(env, 0, 18)]
    city(env, 1, 30)
    play_round(env)
    first = env.episode_stats[0]["regional_production"]
    assert first == PAID * len(paid)
    assert env.episode_stats[1]["regional_production"] == 0
    play_round(env)
    assert env.episode_stats[0]["regional_production"] == 2 * first
    assert home in env.players[0].cities


def test_the_kind_has_its_one_consumer_named():
    """`regional_yield` is a closed kind whose consumer is the regional term
    of `city_yield`. Breaks if the kind is added without a consumer entry or
    the entry points elsewhere."""
    from civulator.effects import CONSUMERS

    assert "yields.py city_yield" in CONSUMERS[KIND_REGIONAL_YIELD]
