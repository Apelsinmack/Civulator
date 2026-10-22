"""Amenities (v0.9.0 Q2, docs/districts_religion_design.md §3, §11 rows 6-9, "v2
fixes" and "v3 fixes" L7): need, supply, luxuries, the bands and their three
readers, the `amenity` effect kind, the Arena, and the access-aware Worker
default that makes luxuries happen in agentless games.

Every test names the property it protects and the change that breaks it.
Needs, columns, bands and carriers are read from `game/amenities.py`, the
registries and the parsed effects; a test that needs a particular table
patches `amenities.BANDS` (or the divisor) for its own duration, so no test
pins which content carries amenities, or how many sources there are -- except
the three carriers the design names (Colosseum, Classical Republic, Retainers),
which the carrier tests name on purpose.

Boards are flat Plains rows (test_loyalty's `flat`); along one row the
canonical distance between two cities is their column difference.
"""

import os
import subprocess
import sys

import pytest

from civulator import district_model, terrain_model, unit_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.config import CFG
from civulator.district_model import DISTRICTS
from civulator.effects import KIND_AMENITY, effects_of, parse_effect
from civulator.game import amenities, city as city_module, loyalty
from civulator.game.amenities import AmenityBand, band_row, need, parse_amenities, parse_bands
from civulator.game.availability import city_can_build_building
from civulator.game.city import City
from civulator.game.defaults import worker_target
from civulator.game.districts import district_spec
from civulator.game.improvements import access_walk_bonus, best_improvement
from civulator.game.loyalty import loyalty_delta
from civulator.game.yields import city_yield
from civulator import research_model

from conftest import grant_all, grant_civic, stand, synthetic_government, synthetic_improvements
from test_loyalty import ROW, city, flat, fighter, play_round, put_district
from test_districts import board, make_city, own, ring

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)

# One row catching everything: no band, whatever the surplus.
NEUTRAL = parse_bands([[0, 0, 100, 0]])


def neutral(monkeypatch):
    """The amenity band table that changes nothing, for tests whose subject
    is not the band."""
    monkeypatch.setattr(amenities, "BANDS", NEUTRAL)


def bands(monkeypatch, *rows):
    monkeypatch.setattr(amenities, "BANDS", parse_bands([list(r) for r in rows]))


# --- the table and its parser -----------------------------------------------------------------


def test_the_configured_table_parses_and_its_bands_follow_the_config_not_the_code():
    """`[amenities]` parses; the module-level rows are exactly the parsed
    config rows. Breaks if a band or key is hardcoded in `amenities.py`."""
    rules = parse_amenities(CFG["amenities"])
    assert amenities.BANDS == rules.bands and amenities.RULES == rules
    assert rules.need_divisor >= 1 and rules.free_first >= 0


@pytest.mark.parametrize("bad", [
    [],                                         # empty
    [[0, 0, 100]],                              # three columns (the loyalty shape)
    [[0, 0, 100, 0, 0]],                        # five columns
    [[0, 0, 100, 0.5]],                         # not an int
    [[0, True, 100, 0]],                        # a bool is not an int
    [[0, 0, -1, 0]],                            # negative growth
    [[0, -101, 100, 0]],                        # a yield below -100 %
    [[3, 0, 100, 0], [3, 0, 100, 0]],           # equal mins
    [[0, 0, 100, 0], [3, 0, 100, 0]],           # ascending mins
    "not a list",
])
def test_a_malformed_band_table_raises_at_load(bad):
    """The `loyalty.parse_bands` contract, widened: non-empty, four int
    columns, strictly descending mins, no growth below 0, no yield below
    -100 %. Breaks if the sibling parser drops a check (a mis-ordered table
    would silently change which band wins)."""
    with pytest.raises(ValueError):
        parse_bands(bad)


def test_the_parser_allows_what_a_happiness_table_needs_and_loyalty_bands_do_not():
    """Negative mins, negative yield percents and negative loyalty are legal
    here. Breaks if the parser is the loyalty one (mins 0..maximum, three
    columns, non-negative percents)."""
    rows = parse_bands([[2, 10, 100, 1], [-3, -20, 50, -2]])
    assert rows[1] == AmenityBand(-3, -20, 50, -2)
    with pytest.raises(ValueError):
        loyalty.parse_bands([[-3, -20, 50]], 100)


@pytest.mark.parametrize("key", ["need_divisor", "free_first", "luxury_cities", "bands"])
def test_a_missing_or_unknown_amenities_key_raises(key):
    """Every key is required and none is optional or extra. Breaks if the
    table loads with a default or ignores a typo."""
    cfg = {k: v for k, v in CFG["amenities"].items() if k != key}
    with pytest.raises(ValueError, match="missing"):
        parse_amenities(cfg)
    with pytest.raises(ValueError, match="unknown"):
        parse_amenities({**CFG["amenities"], "typo": 1})


def test_the_band_of_a_surplus_is_the_first_match_and_the_last_row_catches_every_deficit(monkeypatch):
    """With a synthetic table: a surplus on a row's min takes that row, one
    between mins takes the row below, and a deficit below every min -- however
    deep -- takes the last row. Breaks if the lookup ever returns nothing for
    a very low surplus or prefers a later match to an earlier one."""
    bands(monkeypatch, (5, 20, 100, 1), (0, 0, 100, 0), (-2, -10, 85, -1), (-4, -30, 40, -3))
    assert band_row(9).yield_percent == 20 and band_row(5).yield_percent == 20
    assert band_row(4).yield_percent == 0 and band_row(0).yield_percent == 0
    assert band_row(-1).growth_percent == 85 and band_row(-2).growth_percent == 85
    assert band_row(-3).loyalty == -3 and band_row(-4).loyalty == -3
    assert band_row(-10 ** 6) == amenities.BANDS[-1]


def test_every_configured_row_is_reachable_at_its_own_min():
    """For the configured table, a surplus equal to a row's min lands on that
    row, and one far below every min on the last. Breaks if the rows are
    shadowed (not descending) or the fallback is not the last row."""
    for row in amenities.BANDS:
        assert band_row(row.min) == row
    assert band_row(amenities.BANDS[-1].min - 1000) == amenities.BANDS[-1]


# --- need -----------------------------------------------------------------------------------


@pytest.mark.parametrize("divisor, free", [(2, 0), (2, 2), (3, 0), (1, 1)])
def test_need_is_the_ceiling_of_population_over_the_divisor_minus_the_free_citizens(
        monkeypatch, divisor, free):
    """need = max(0, ceil(pop / divisor) - free_first), for any population.
    Breaks if it rounds down, ignores `free_first`, or goes negative."""
    monkeypatch.setattr(amenities, "NEED_DIVISOR", divisor)
    monkeypatch.setattr(amenities, "FREE_FIRST", free)
    env = flat()
    home = city(env, 0, 10)
    for pop in range(1, 12):
        home.population = pop
        assert need(home) == max(0, -(-pop // divisor) - free)


def test_a_size_one_city_needs_one_amenity_at_the_gs_defaults(monkeypatch):
    """Civ 6 GS: ceil(1 / 2) = 1 with no free citizens. Breaks if the need of a
    size-1 city rounds to 0 (integer division instead of ceiling)."""
    monkeypatch.setattr(amenities, "NEED_DIVISOR", 2)
    monkeypatch.setattr(amenities, "FREE_FIRST", 0)
    env = flat()
    assert need(city(env, 0, 10, population=1)) == 1


# --- supply: columns -------------------------------------------------------------------------


def test_every_building_with_an_amenity_column_adds_exactly_that_column():
    """Over the registry: appending a building to a city raises its column
    supply by its `amenity` column. Breaks if a building's column is not read
    (or is read twice)."""
    assert unit_model.BUILDING_AMENITY, "fixture: the config carries amenity buildings"
    env = flat()
    home = city(env, 0, 10)
    for name, points in unit_model.BUILDING_AMENITY.items():
        before = amenities.column_supply(home)
        home.buildings.append(name)
        assert amenities.column_supply(home) - before == points, name
        home.buildings.remove(name)


def test_every_district_with_an_amenity_column_adds_it_when_complete_and_not_before():
    """Over the registry (wonders included): a complete district adds its
    `amenity` column, an incomplete one nothing. Breaks if incomplete
    districts count or a wonder's column is skipped."""
    tabled = [n for n, spec in DISTRICTS.items() if spec.amenity]
    assert tabled, "fixture: the config carries amenity districts"
    env = flat()
    home = city(env, 0, 10)
    for name in tabled:
        before = amenities.column_supply(home)
        district = put_district(env, home, name, complete=False)
        assert amenities.column_supply(home) == before, name
        district.complete = True
        assert amenities.column_supply(home) - before == DISTRICTS[name].amenity, name
        home.districts.remove(district)
        env.map.get_tile(district.coordinates).district = None


def test_the_palace_is_an_amenity_and_a_plain_city_has_none():
    """Civ 6 GS: the capital's Palace gives +1. Breaks if the Palace loses its
    column or a city with no source reports any supply."""
    env = flat()
    capital = city(env, 0, 10, palace=True)
    plain = city(env, 1, 20)
    assert amenities.column_supply(capital) == unit_model.BUILDING_AMENITY[
        unit_model.CAPITAL_BUILDING] >= 1
    assert amenities.supply(plain, env) == 0


# --- supply: effects ---------------------------------------------------------------------------


def _amenity_entries(source_kind, name):
    return [e for e in effects_of(source_kind, name) if e.kind == KIND_AMENITY]


def test_the_colosseum_pays_its_owners_cities_within_its_range_and_not_one_further():
    """The Colosseum's `amenity` effect reaches the owner's cities at canonical
    distance <= its `range` (its own city included), and not one tile beyond
    nor another player's city. Breaks if the range is ignored, off by one,
    unbounded, or the effect bypasses `active_effects`' source city."""
    entries = _amenity_entries("district", "Colosseum")
    assert entries, "the design's carrier"
    reach, amount = entries[0]["range"], sum(e["amount"] for e in entries)
    assert reach > 0
    env = flat(m=60)
    holder = city(env, 0, 10)
    put_district(env, holder, "Colosseum")
    inside = city(env, 0, 10 + reach)
    outside = city(env, 0, 10 + reach + 1)
    foreign = city(env, 1, 10 + 4)     # another player's city, well within range
    assert env.map.distance_function(holder.coordinates, inside.coordinates) == reach
    assert amenities.effect_supply(holder, env) == amount
    assert amenities.effect_supply(inside, env) == amount
    assert amenities.effect_supply(outside, env) == 0
    assert amenities.effect_supply(foreign, env) == 0


def test_the_colosseum_also_pays_loyalty_in_the_same_range():
    """Design §3.3: the Colosseum carries a `loyalty` +N `range` effect beside
    its amenity (R&F/GS). Breaks if the loyalty entry is dropped when the
    amenity one is added."""
    kinds = {e.kind: e for e in effects_of("district", "Colosseum")}
    assert kinds["loyalty"]["range"] == kinds[KIND_AMENITY]["range"] > 0


def test_a_min_districts_effect_needs_that_many_complete_specialty_districts():
    """Classical Republic's `amenity` effect holds in a city with at least
    `min_districts` complete specialty districts and not in one with fewer
    (an incomplete district does not count). Breaks if the threshold is
    ignored, off by one, or counts incomplete or wonder districts."""
    entries = _amenity_entries("government", "Classical Republic")
    assert entries, "the design's carrier"
    need_districts, amount = entries[0]["min_districts"], sum(e["amount"] for e in entries)
    assert need_districts >= 1
    specialty = next(n for n, s in DISTRICTS.items()
                     if s.kind == district_model.KIND_DISTRICT and s.counts_toward_limit)
    env = flat()
    home = city(env, 0, 10)
    env.players[0].government = "Classical Republic"
    assert amenities.effect_supply(home, env) == 0
    for k in range(need_districts):
        put_district(env, home, specialty, col_offset=2 + k, complete=False)
    assert amenities.effect_supply(home, env) == 0
    for district in home.districts:
        district.complete = True
    assert amenities.effect_supply(home, env) == amount
    assert amenities.effect_supply(city(env, 0, 30), env) == 0, "a city with none gets none"


def test_retainers_pay_only_a_garrisoned_city(monkeypatch):
    """Retainers (a military card behind Civil Service) give +N amenity with
    `requires_garrison`: in force through the real slotting path, it pays the
    city while a fighting unit of its owner stands on the centre and nothing
    when it does not. Breaks if the garrison condition is ignored or reads
    anything but `loyalty.is_garrisoned`."""
    spec = research_model.POLICIES["Retainers"]
    assert spec.type == "military" and spec.requires_civic == "Civil Service"
    entries = _amenity_entries("policy", "Retainers")
    assert entries and entries[0]["requires_garrison"]
    env = flat()
    home = city(env, 0, 10)
    player = env.players[0]
    grant_civic(player, "Civil Service")
    synthetic_government(monkeypatch, "Test Garrison Gov", {"military": 1},
                         requires_civic="Civil Service")
    assert env.set_government(player, "Test Garrison Gov")
    assert env.set_policies(player, ["Retainers"])
    assert amenities.effect_supply(home, env) == 0
    stand(env, fighter(), 0, home.coordinates)
    assert loyalty.is_garrisoned(home, env)
    assert amenities.effect_supply(home, env) == entries[0]["amount"]
    assert amenities.effect_supply(city(env, 0, 30), env) == 0


@pytest.mark.parametrize("entry, source, scope_player, ok", [
    ({"kind": "amenity", "amount": 1}, "policy", None, True),
    ({"kind": "amenity", "amount": 1, "min_districts": 2}, "government", None, True),
    ({"kind": "amenity", "amount": 1, "requires_garrison": True}, "policy", None, True),
    ({"kind": "amenity", "amount": 2, "range": 6}, "district", "player", True),
    ({"kind": "amenity", "amount": 2, "range": 6}, "policy", None, False),        # range needs a city
    ({"kind": "amenity", "amount": 2, "range": 6, "scope": "city"}, "district", None, False),
    ({"kind": "amenity", "amount": 1}, "building", None, False),                  # flat: the column
    ({"kind": "amenity", "amount": 1.5}, "policy", None, False),                  # whole points
    ({"kind": "amenity", "amount": 1, "range": -1}, "district", "player", False),
    ({"kind": "amenity", "amount": 1, "min_districts": -1}, "government", None, False),
    ({"kind": "amenity"}, "policy", None, False),                                 # amount required
    ({"kind": "amenity", "amount": 1, "typo": 1}, "policy", None, False),
])
def test_the_amenity_parser_mirrors_the_loyalty_kinds_attributes(entry, source, scope_player, ok):
    """`amenity` takes amount, range, min_districts, requires_garrison; `range`
    measures from a city holding a player-scoped building or district; a flat
    entry of a building's own city is the `amenity` column. Breaks if the
    parser accepts junk or loses the loyalty kind's reach rule."""
    raw = dict(entry)
    if scope_player and "scope" not in raw:
        raw["scope"] = scope_player
    if ok:
        parsed = parse_effect(raw, source, "Probe")
        assert parsed.kind == KIND_AMENITY and parsed["range"] >= 0
    else:
        with pytest.raises(ValueError):
            parse_effect(raw, source, "Probe")


# --- luxuries (L7) -------------------------------------------------------------------------------


def _luxury_board(monkeypatch, populations, luxuries, serves):
    """A neutral-band board with one city per entry of `populations` (ids in
    that order), `serves` as `luxury_cities`, and `luxuries` as the access
    list of every player."""
    neutral(monkeypatch)
    monkeypatch.setattr(amenities, "LUXURY_CITIES", serves)
    monkeypatch.setattr(amenities, "accessible_resources",
                        lambda player, env, cls=None: tuple(luxuries))
    env = flat(m=60)
    cities = [city(env, 0, 6 * i + 6, population=pop) for i, pop in enumerate(populations)]
    return env, cities


def test_the_fifth_city_gets_the_second_luxury_greedily(monkeypatch):
    """L7: luxuries in order, each to the cities with the largest CURRENT
    deficit counting luxuries already assigned. With N+1 equal cities and two
    luxuries the first goes to ids 0..N-1, the second to city N first (it has
    the largest deficit now) and then to ids 0..N-2. Breaks if both luxuries
    pick the same N cities (a static ranking), or ties are not by id."""
    serves = 3
    env, cities = _luxury_board(monkeypatch, [4] * (serves + 1), ["Wine", "Silk"], serves)
    shares = amenities.luxury_shares(env.players[0], env)
    ids = [c.city_id for c in cities]
    assert shares[ids[serves]] == 1, "the fifth city is served by the second luxury"
    assert [shares[i] for i in ids[:serves - 1]] == [2] * (serves - 1)
    assert shares[ids[serves - 1]] == 1
    assert sum(shares.values()) == 2 * serves


def test_a_luxury_serves_at_most_luxury_cities_neediest_first_ties_by_id(monkeypatch):
    """One luxury, more cities than it serves: it goes to the largest
    deficits (population here), equal deficits by city id. Breaks if it serves
    more than `luxury_cities`, the biggest cities are skipped, or ties are
    broken by anything but id."""
    env, cities = _luxury_board(monkeypatch, [2, 8, 8, 8, 8, 2], ["Wine"], 3)
    shares = amenities.luxury_shares(env.players[0], env)
    ids = [c.city_id for c in cities]
    assert set(shares) == {ids[1], ids[2], ids[3]} and set(shares.values()) == {1}


def test_the_assignment_does_not_depend_on_the_order_of_the_players_cities(monkeypatch):
    """Cities are visited in city-id order, whatever order the player lists
    them. Breaks if the assignment iterates `player.cities` as given."""
    env, cities = _luxury_board(monkeypatch, [4] * 5, ["Wine", "Silk"], 3)
    first = amenities.luxury_shares(env.players[0], env)
    env.players[0].cities.reverse()
    assert amenities.luxury_shares(env.players[0], env) == first


def test_luxury_supply_shows_in_a_cities_surplus_and_a_better_supplied_city_is_passed_over(monkeypatch):
    """The share is part of `supply`, and the deficit counts supply from other
    sources: a city already covered by a column is served after one that is
    not. Breaks if the luxury ignores columns/effects when ranking."""
    env, (a, b) = _luxury_board(monkeypatch, [4, 4], ["Wine"], 1)
    a.buildings.append(next(iter(unit_model.BUILDING_AMENITY)))   # a has a column, b has not
    assert amenities.luxury_shares(env.players[0], env) == {b.city_id: 1}
    assert amenities.supply(b, env) == 1 and amenities.surplus(b, env) == 1 - need(b)


def test_two_copies_of_one_luxury_count_once_and_a_second_kind_counts_again():
    """Real access: Wine on two city centres of one player is one Wine (one
    share), Silk beside it makes two. Breaks if the assignment counts tiles or
    copies instead of distinct luxuries."""
    wine, silk = [n for n in terrain_model.RESOURCE_TABLE
                  if terrain_model.resource_class(n) == "luxury"][:2]
    env = flat(m=60)
    cities = [city(env, 0, 6 * i + 6, population=4) for i in range(3)]
    for c, resource in zip(cities[:2], (wine, wine)):
        env.map.get_tile(c.coordinates).set_layers("Plains", relief="flat", resource=resource,
                                                   map_ref=env.map)
    shares = amenities.luxury_shares(env.players[0], env)
    assert sum(shares.values()) == min(len(cities), CFG["amenities"]["luxury_cities"])
    env.map.get_tile(cities[2].coordinates).set_layers("Plains", relief="flat", resource=silk,
                                                       map_ref=env.map)
    assert sum(amenities.luxury_shares(env.players[0], env).values()) == 2 * len(cities) \
        if CFG["amenities"]["luxury_cities"] >= len(cities) else True


def test_a_player_without_a_luxury_assigns_nothing():
    """No access, no share (and no work). Breaks if shares are invented."""
    env = flat()
    city(env, 0, 10)
    assert amenities.luxury_shares(env.players[0], env) == {}


# --- the three readers ---------------------------------------------------------------------


def test_the_amenity_percent_applies_after_the_loyalty_percent_to_the_pool_yields(monkeypatch):
    """city_yield(culture) = (raw * loyalty% // 100) * (100 + amenity%) // 100,
    in that order, both floored in tenths. The numbers are chosen so the
    swapped order gives another answer. Breaks if the order changes, a step is
    skipped, or the floor moves to the end."""
    env = flat()
    home = city(env, 0, 10, population=1)
    neutral(monkeypatch)
    monkeypatch.setattr(loyalty, "BANDS", loyalty.parse_bands([[0, 100, 100]], 100))
    raw = city_yield(home, "culture")
    monkeypatch.setattr(loyalty, "BANDS", loyalty.parse_bands([[0, 75, 100]], 100))
    bands(monkeypatch, (0, 20, 100, 0))
    expected = (raw * 75 // 100) * 120 // 100
    assert expected != (raw * 120 // 100) * 75 // 100, "fixture: the order is observable"
    assert city_yield(home, "culture") == expected


@pytest.mark.parametrize("name", ["science", "culture", "gold", "faith"])
def test_every_pool_yield_is_scaled_by_the_amenity_percent(monkeypatch, name):
    """A -40 % band lowers (and a +20 % raises) each of the four pool yields
    that is nonzero for the city; none ignores it. Breaks if a yield is
    left out of the scaling."""
    env = flat()
    home = city(env, 0, 10, population=5)
    home.buildings.extend(b for b, columns in unit_model.BUILDING_YIELDS[name].items()
                          if columns > 0)
    neutral(monkeypatch)
    raw = city_yield(home, name)
    assert raw >= 10, f"fixture: {name} is {raw} tenths for this city"
    bands(monkeypatch, (0, 20, 100, 0))
    assert city_yield(home, name) == raw * 120 // 100
    bands(monkeypatch, (0, -40, 100, 0))
    assert city_yield(home, name) == raw * 60 // 100


def test_food_and_city_yield_production_are_never_scaled_by_amenities(monkeypatch):
    """Food is never scaled (Civ 6), and production's amenity percent is applied
    in `City.calculate_production`, not in `city_yield`. Breaks if the percent
    leaks into either `city_yield` value."""
    env = flat()
    home = city(env, 0, 10, population=5)
    neutral(monkeypatch)
    food, production = city_yield(home, "food"), city_yield(home, "production")
    bands(monkeypatch, (0, -40, 100, 0))
    assert city_yield(home, "food") == food
    assert city_yield(home, "production") == production
    assert home.calculate_food(env) == food


def test_production_takes_the_amenity_percent_in_calculate_production_after_loyalty(monkeypatch):
    """calculate_production = max(1, (base * (100 + production%) // 100 *
    loyalty% // 100) * (100 + amenity%) // 100) -- the amenity step last. The
    base is pinned at 10 so the swapped order differs (8 vs 9). Breaks if the
    amenity percent comes before loyalty, is applied in city_yield instead
    (twice), or the floor of 1 is lost."""
    env = flat()
    home = city(env, 0, 10, population=5)
    monkeypatch.setattr(city_module, "city_yield", lambda c, name: 10)
    monkeypatch.setattr(loyalty, "BANDS", loyalty.parse_bands([[0, 75, 100]], 100))
    monkeypatch.setattr(City, "production_percent", lambda self: 0)
    bands(monkeypatch, (0, 20, 100, 0))
    assert (10 * 75 // 100) * 120 // 100 != (10 * 120 // 100) * 75 // 100
    assert home.calculate_production(env) == (10 * 75 // 100) * 120 // 100
    bands(monkeypatch, (0, -100, 100, 0))
    assert home.calculate_production(env) == 1, "a city can always build, slowly"


def test_growth_multiplies_once_beside_the_housing_and_loyalty_shares(monkeypatch):
    """growth_bucket_gain = food * housing% * loyalty share * (100 + effects)
    * amenity growth% // 10**6, one floor. At full loyalty and a 85 % band, 7
    food at the 100 % housing band is 7 * 100 * 85 // 100 = 595 hundredths
    (not 504, which a second application gives). Breaks if the band
    multiplies twice, floors early, or is skipped."""
    env = flat()
    home = city(env, 0, 10, population=3)
    assert home.loyalty == loyalty.MAXIMUM
    neutral(monkeypatch)
    assert home.growth_bucket_gain(7, 100) == 7 * 100
    bands(monkeypatch, (0, 0, 85, 0))
    assert home.growth_bucket_gain(7, 100) == 7 * 100 * 85 // 100 == 595
    assert home.growth_bucket_gain(3, 25) == 3 * 25 * 100 * 100 * 85 // 10 ** 6
    monkeypatch.setattr(loyalty, "BANDS", loyalty.parse_bands([[0, 100, 50]], 100))
    assert home.growth_bucket_gain(7, 100) == 7 * 100 * 50 * 85 * 100 // 10 ** 6


def test_a_cities_loyalty_delta_carries_the_loyalty_column_of_its_amenity_band(monkeypatch):
    """loyalty_delta(city) = (the same delta under a neutral table) + the band
    row's loyalty column, whatever the row. Breaks if the term is missing,
    doubled, or read from a different band than the yields use."""
    env = flat()
    home = city(env, 0, 10, population=4)
    neutral(monkeypatch)
    base = loyalty_delta(home, env)
    for column in (-4, -1, 0, 1, 3):
        bands(monkeypatch, (0, 0, 100, column))
        assert loyalty_delta(home, env) == base + column
        assert amenities.loyalty_term(home, env) == column


def test_an_unhappy_city_and_a_content_one_land_in_different_bands_end_to_end():
    """With the real config: a big city with no amenity sits in a deficit band
    (yields and growth cut, loyalty column negative) and the same city with
    enough supply sits at or above the content row. Breaks if surplus is not
    what picks the band."""
    env = flat()
    home = city(env, 0, 10, population=9)
    assert amenities.surplus(home, env) == -need(home)
    low = band_row(amenities.surplus(home, env))
    assert low.yield_percent < 0 and low.growth_percent < 100 and low.loyalty < 0
    home.buildings.extend([n for n, p in unit_model.BUILDING_AMENITY.items()] * need(home))
    assert amenities.surplus(home, env) >= 0
    assert band_row(amenities.surplus(home, env)).yield_percent >= 0


# --- Arena and the Entertainment Complex --------------------------------------------------------


def test_the_arena_needs_its_civic_and_a_complete_entertainment_complex_through_the_one_predicate():
    """The Arena is offered by `city_can_build_building` and the build mask only
    with its civic AND a complete district of its `requires_district`, and
    producing it is refused otherwise. Breaks if a gate lives in one caller
    only, or an incomplete district suffices."""
    district = unit_model.BUILDING_REQUIRES_DISTRICT["Arena"]
    civic = unit_model.BUILDING_REQUIRES_CIVIC["Arena"]
    assert district in DISTRICTS and unit_model.BUILDING_AMENITY["Arena"] > 0
    env = flat()
    home = city(env, 0, 10)
    index = BUILD_OPTIONS.index("Arena")

    def offered():
        mask = get_valid_build_mask(home)
        assert bool(mask[index]) == city_can_build_building(home, "Arena")
        return city_can_build_building(home, "Arena")

    assert not offered() and not home.produce_building("Arena")
    grant_civic(env.players[0], civic)
    assert not offered(), "the civic alone is not enough"
    built = put_district(env, home, district, complete=False)
    assert not offered(), "an incomplete district is not enough"
    built.complete = True
    assert offered() and home.produce_building("Arena")


def test_the_arena_raises_the_cities_supply_by_its_column_when_built():
    """Completing the Arena adds its `amenity` column to the city's supply and
    to no other city's. Breaks if the building's column is not wired to
    supply."""
    env = flat()
    home, other = city(env, 0, 10), city(env, 0, 30)
    before = (amenities.supply(home, env), amenities.supply(other, env))
    home.buildings.append("Arena")
    assert amenities.supply(home, env) - before[0] == unit_model.BUILDING_AMENITY["Arena"]
    assert amenities.supply(other, env) == before[1]


def test_the_arena_is_appended_to_the_build_options():
    """The build list stays append-only (an archived build head keeps its
    meaning): the Arena sits after the options that existed before Q2.
    Breaks if it is inserted rather than appended."""
    assert BUILD_OPTIONS.index("Arena") > BUILD_OPTIONS.index("Worker")


# --- stats -----------------------------------------------------------------------------------


def test_round_end_stats_count_unhappy_city_rounds_and_average_the_surplus(monkeypatch):
    """`_amenity_stats` adds one `cities_unhappy_rounds` per city with a surplus
    below 0 and sets `amenity_surplus_mean` to the mean over rounds of each
    round's mean city surplus, in int tenths. Breaks if the unit changes, the
    mean is over cities only, or a round without a deficit is not counted."""
    neutral(monkeypatch)
    env = flat()
    a, b = city(env, 0, 10, population=1), city(env, 0, 30, population=5)
    s1 = [amenities.surplus(c, env) for c in (a, b)]
    env._amenity_stats()
    stats = env.episode_stats[0]
    assert stats["cities_unhappy_rounds"] == sum(v < 0 for v in s1)
    assert stats["amenity_surplus_mean"] == 10 * sum(s1) // 2
    a.population = 9
    s2 = [amenities.surplus(c, env) for c in (a, b)]
    env._amenity_stats()
    assert stats["cities_unhappy_rounds"] == sum(v < 0 for v in s1) + sum(v < 0 for v in s2)
    assert stats["amenity_surplus_mean"] == (10 * sum(s1) // 2 + 10 * sum(s2) // 2) // 2
    assert env.episode_stats[1]["cities_unhappy_rounds"] == 0, "a player with no city is not counted"


def test_the_stats_are_written_by_real_rounds():
    """Play rounds through `next_turn`: the two stats move for a player with an
    unhappy city, and a fresh episode starts them at zero. Breaks if
    `next_turn` stops calling the round-end bookkeeping or `reset` forgets to
    clear the accumulators."""
    env = flat()
    city(env, 0, 10, population=9)
    city(env, 1, 30, population=1)
    for _ in range(3):
        play_round(env)
    assert env.episode_stats[0]["cities_unhappy_rounds"] == 3
    assert env.episode_stats[0]["amenity_surplus_mean"] < 0
    fresh = env._fresh_episode_stats()
    assert fresh[0]["cities_unhappy_rounds"] == 0 and fresh[0]["amenity_surplus_mean"] == 0
    assert env._amenity_rounds == {0: [0, 0], 1: [0, 0]}


# --- the access-aware Worker default ----------------------------------------------------------


PLAINS = {"bases": ["Plains"], "relief": ["flat"]}


def _luxury_with_improver():
    """(resource, improvement) of a configured luxury: the first one whose
    `improved_by` improvement is a plain-land one."""
    for name in terrain_model.RESOURCE_TABLE:
        if terrain_model.resource_class(name) == "luxury":
            improvers = terrain_model.RESOURCE_IMPROVED_BY[name]
            if improvers:
                return name, improvers[0]
    raise AssertionError("fixture: no luxury has an improver")


def _put_resource(env, pos, resource):
    env.map.get_tile(pos).set_layers("Plains", relief="flat", resource=resource, map_ref=env.map)


def test_among_equal_gains_the_improvement_that_grants_the_resource_wins():
    """Two improvements of equal gain, the one in the tile's resource's
    `improved_by` second in config order: on the resource tile the Worker
    builds that one, on a plain tile the first in config order. Breaks if the
    tie goes to config order alone (the pre-Q2 default) or the grant counts
    for tiles without the resource."""
    resource, improver = _luxury_with_improver()
    tables = {"Aaa": {"food": 1, "on": PLAINS}, improver: {"food": 1, "on": PLAINS}}
    with synthetic_improvements(tables):
        env = board()
        city = make_city(env, (3, 4))
        a, b = ring(env, (3, 4), 1)[:2]
        _put_resource(env, a, resource)
        assert best_improvement(env.players[0], a, env) == improver
        assert best_improvement(env.players[0], b, env) == "Aaa"


def test_a_larger_gain_still_beats_the_grant():
    """The grant is a tie-break, not a trump: an improvement with a larger gain
    is built even when another one grants the resource. Breaks if access
    outranks yield."""
    resource, improver = _luxury_with_improver()
    tables = {"Big": {"food": 2, "on": PLAINS}, improver: {"food": 1, "on": PLAINS}}
    with synthetic_improvements(tables):
        env = board()
        make_city(env, (3, 4))
        a = ring(env, (3, 4), 1)[0]
        _put_resource(env, a, resource)
        assert best_improvement(env.players[0], a, env) == "Big"


def test_the_worker_heads_for_a_resource_it_lacks_before_an_equally_near_plain_tile(monkeypatch):
    """Two open tiles at the same distance, the plain one first by coordinates:
    the Worker targets the tile whose build grants a resource its owner has no
    access to, and with the bonus at 0 it targets the plain one; once the owner
    has the resource (a centre on it) the bonus is gone. Breaks if the walk
    ignores access, the bonus is not read from config, or an access already
    held still pulls."""
    resource, improver = _luxury_with_improver()
    tables = {"Plain": {"food": 1, "on": PLAINS}, improver: {"food": 1, "on": PLAINS}}
    with synthetic_improvements(tables):
        env = board()
        city = make_city(env, (3, 4))
        player = env.players[0]
        r1 = ring(env, (3, 4), 1)
        # Two tiles of the ring equally far from the worker, the resource on the later one.
        worker_at = ring(env, (3, 4), 3)[0]
        by_distance = sorted(r1, key=lambda p: (env.distance_function(worker_at, p), p))
        near, far = by_distance[0], by_distance[1]
        keep = {near, far, tuple(city.coordinates)}
        for p in env.map.tiles_of_city(city.city_id):
            if p not in keep:
                env.map.get_tile(p).add_improvement("Plain", map_ref=env.map)
        resource_tile = max(near, far)
        plain_tile = min(near, far)
        _put_resource(env, resource_tile, resource)
        worker = stand(env, "Worker", 0, worker_at)
        d_res = env.distance_function(worker_at, resource_tile)
        d_plain = env.distance_function(worker_at, plain_tile)
        assert access_walk_bonus(player, resource_tile, env) == terrain_bonus()
        assert access_walk_bonus(player, plain_tile, env) == 0
        from civulator.game import improvements
        monkeypatch.setattr(improvements, "ACCESS_BONUS", 1 + abs(d_res - d_plain))
        assert worker_target(worker, env) == resource_tile
        monkeypatch.setattr(improvements, "ACCESS_BONUS", 0)
        assert worker_target(worker, env) == min(
            (resource_tile, plain_tile), key=lambda p: (env.distance_function(worker_at, p), p))
        monkeypatch.setattr(improvements, "ACCESS_BONUS", 1 + abs(d_res - d_plain))
        # Access held: a centre standing on the same resource elsewhere removes the pull.
        env.map.get_tile(city.coordinates).set_layers("Plains", relief="flat", resource=resource,
                                                      map_ref=env.map)
        assert access_walk_bonus(player, resource_tile, env) == 0


def terrain_bonus():
    from civulator.game import improvements
    return improvements.ACCESS_BONUS


def test_the_access_bonus_is_a_validated_config_scalar():
    """`[worker_default] access_bonus` is a non-negative int and nothing else
    lives in the table. Breaks if the scalar is hardcoded or junk loads."""
    from civulator.game.improvements import _access_bonus
    assert _access_bonus(CFG) == CFG["worker_default"]["access_bonus"] >= 0
    for bad in ({"worker_default": {"access_bonus": -1}}, {"worker_default": {"access_bonus": 1.5}},
                {"worker_default": {"access_bonus": 1, "extra": 2}}, {}):
        with pytest.raises(ValueError):
            _access_bonus(bad)


# --- determinism ----------------------------------------------------------------------------


GAME = '''
import sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
from conftest import grant_all
from civulator.game.environment import GameEnvironment


def play(seed, rounds):
    """Two players who know everything, two Workers each, a Palace and any
    luxury the world gives them, left to the engine for `rounds` rounds: the
    improvements standing, and the amenity stats and luxury counts."""
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for player in env.players:
        grant_all(player)
        for _ in range(2):
            assert player.cities[0].complete_unit_production("Worker", env)
    for _ in range(2 * rounds):
        env.next_turn()
    standing = [(int(t.row), int(t.column), tuple(t.improvements))
                for t in env.map.tiles.flat if t.improvements]
    stats = [(env.episode_stats[i]["amenity_surplus_mean"], env.episode_stats[i]["cities_unhappy_rounds"],
              env.episode_stats[i]["luxuries_accessible"]) for i in range(2)]
    return standing, stats
'''
SEED, ROUNDS = 11, 12


def _play_here(seed=SEED, rounds=ROUNDS):
    namespace = {}
    exec(GAME.format(root=ROOT_DIR, tests=TESTS_DIR), namespace)
    return namespace["play"](seed, rounds)


def test_two_same_seed_games_have_identical_amenity_stats_and_improvements():
    """Two games from one seed end with the same improvements and the same
    amenity stats, and the game is live (the Workers built something and the
    stats are written). Breaks if the assignment or the Worker's new ranking depends on anything
    but state."""
    first = _play_here()
    assert first == _play_here()
    assert first[0] and all(isinstance(v, int) for row in first[1] for v in row)


@pytest.mark.parametrize("hash_seed", ["1", "2"])
def test_amenities_and_the_worker_ranking_do_not_depend_on_the_hash_seed(hash_seed):
    """A fresh process with another PYTHONHASHSEED reproduces the same
    improvements and amenity stats from the same seed. Breaks if luxuries are
    assigned from a set, or the access tie-break iterates a hash-ordered
    container."""
    code = GAME.format(root=ROOT_DIR, tests=TESTS_DIR) + f"print(play({SEED}, {ROUNDS}))\n"
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONHASHSEED": hash_seed}, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == str(_play_here())
