"""Issue #116 P1: city yields and player pools (docs/progression_design.md
§2.1-§2.2, "v2 fixes", §14 rows 1-4).

Reference values are re-derived here from config.toml and `Tile.yields`,
never from civulator/game/yields.py, so a drift in the one computation shows
up as a mismatch against the rule it implements. No test pins which
buildings or districts exist or what they declare: each asserts the rule
every configured one obeys.
"""

import inspect

import pytest

from civulator import district_model, unit_model
from civulator.config import CFG
from civulator.game import districts as districts_mod
from civulator.game import yields as yields_mod
from civulator.game.culture import culture
from civulator.game.districts import District, adjacency_score
from civulator.game.loyalty import loyalty_percent
from civulator.game.yields import city_yield

from test_districts import board, make_city, neighbours, own, plain_types


# v0.9.0 Q2: this module pins other rules' exact arithmetic, not the amenity band.
pytestmark = pytest.mark.usefixtures("neutral_amenities")

POOL_YIELDS = ("science", "culture", "gold", "faith")      # int tenths
TILE_YIELDS = ("food", "production")                       # whole points
ALL_YIELDS = POOL_YIELDS + TILE_YIELDS
CAPITAL_SITE, CITY_SITE = (3, 3), (3, 11)


def _tenths(x):
    return round(10 * x)


def _column(table, name):
    """A config column in city_yield's unit: tenths for the pool yields,
    whole points for food and production."""
    value = table.get(name, 0)
    return _tenths(value) if name in POOL_YIELDS else value


def _tiles(env, city, index):
    """v0.7's tile sum: the centre plus every worked tile (`Tile.yields`)."""
    total = env.map.get_tile(city.coordinates).yields[index]
    return total + sum(env.map.get_tile(p).yields[index] for p in city.worked_tiles)


def _v07(env, city):
    """v0.7's culture, food and production of a city, from config and tiles:
    culture = base + per_pop * pop + building culture columns (tenths)."""
    culture_tenths = (_tenths(CFG["culture"]["base"])
                      + _tenths(CFG["culture"]["per_pop"]) * city.population
                      + sum(_tenths(CFG["buildings"][b].get("culture", 0)) for b in city.buildings))
    return {"culture": culture_tenths, "food": _tiles(env, city, 0),
            "production": _tiles(env, city, 1)}


def _yields(city):
    return {name: city_yield(city, name) for name in ALL_YIELDS}


def _varied_board():
    """Plains board, rivers cleared, with mixed tiles around both sites so
    the tile terms are not all equal."""
    env = board()
    for site in (CAPITAL_SITE, CITY_SITE):
        nbs = neighbours(env, site)
        env.map.get_tile(nbs[0]).set_layers("Grassland", map_ref=env.map)
        env.map.get_tile(nbs[1]).set_layers("Plains", relief="hills", map_ref=env.map)
    return env


def _capital_and_city(env, population=3):
    """Player 0's capital (it holds the Palace) and a second, non-capital
    city on an identical neighbourhood, both at `population`."""
    capital = make_city(env, CAPITAL_SITE, population=population)
    city = make_city(env, CITY_SITE, population=population)
    for c in (capital, city):
        c.assign_tiles(env)
    assert "Palace" in capital.buildings and "Palace" not in city.buildings
    return capital, city


def _put(env, city, name, pos, complete):
    """Fixture only: link a District by hand (bypasses placement rules)."""
    district = District(name, city.city_id, pos, complete=complete, cost=10)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def _pools(player):
    return {y: getattr(player, y) for y in POOL_YIELDS}


# --- §14 row 1: v0.7 identity and the Palace ---------------------------------


def test_a_plain_non_capital_city_yields_exactly_v07_culture_food_and_production():
    """A non-capital city with no district, wonder, route or effect, holding
    only buildings that declare no new yield column, yields v0.7's culture,
    food and production exactly (production through calculate_production,
    with its floor of 1). Breaks if the city_yield refactor changes a v0.7
    number."""
    new_columns = ("science", "gold", "faith", "food", "production")
    old_style = [b for b, t in CFG["buildings"].items()
                 if b != "Palace" and not any(t.get(c) for c in new_columns)]
    for buildings in ([], old_style):
        env = _varied_board()
        _, city = _capital_and_city(env)
        city.buildings.extend(buildings)
        v07 = _v07(env, city)
        assert culture(city) == city_yield(city, "culture") == v07["culture"]
        assert city.calculate_food(env) == city_yield(city, "food") == v07["food"]
        assert city_yield(city, "production") == v07["production"]
        assert city.calculate_production(env) == max(1, v07["production"])


def test_science_gold_faith_of_a_plain_city_follow_their_base_and_per_pop_tables():
    """A city with no sources yields `[<name>] base + per_pop * population`
    of science, gold and faith, in int tenths. Breaks if a table is not read
    or a scalar is hardcoded."""
    env = _varied_board()
    _, city = _capital_and_city(env)
    for pop in (1, 4):
        city.population = pop
        for name in ("science", "gold", "faith"):
            expected = _tenths(CFG[name]["base"]) + _tenths(CFG[name]["per_pop"]) * pop
            assert city_yield(city, name) == expected
            assert type(city_yield(city, name)) is int


def test_the_capital_differs_from_an_identical_city_by_exactly_the_palace_columns():
    """Two cities on identical ground: the one holding the Palace yields
    more of each yield by exactly the Palace's column, through every
    consumer. Breaks if a Palace yield is lost, doubled, or read by name."""
    palace = CFG["buildings"]["Palace"]
    assert any(palace.get(name) for name in ALL_YIELDS), "fixture: the Palace declares a yield"
    env = _varied_board()
    capital, city = _capital_and_city(env)
    assert _tiles(env, capital, 1) == _tiles(env, city, 1), "fixture: identical ground"
    for name in ALL_YIELDS:
        assert city_yield(capital, name) - city_yield(city, name) == _column(palace, name), name
    assert (capital.calculate_production(env)
            == max(1, _v07(env, capital)["production"] + _column(palace, "production")))
    assert capital.calculate_food(env) == _v07(env, capital)["food"] + _column(palace, "food")


def test_every_building_adds_exactly_its_declared_columns():
    """For every configured building, holding it changes each of the six
    yields by exactly its column (0 when absent): Granary food, Monument
    culture, the Palace's science/gold/production alike. Breaks if a column
    is ignored, a unit (tenths vs whole points) is wrong, or a building is
    special-cased."""
    for name, table in CFG["buildings"].items():
        env = _varied_board()
        _, city = _capital_and_city(env)
        before = _yields(city)
        city.buildings.append(name)
        after = _yields(city)
        assert {y: after[y] - before[y] for y in ALL_YIELDS} == {
            y: _column(table, y) for y in ALL_YIELDS}, name


def test_building_columns_are_parsed_into_tenths():
    """unit_model's BUILDING_<YIELD> dicts hold every nonzero column of every
    building in int tenths. Breaks if a column is not parsed or not scaled."""
    for name, table in CFG["buildings"].items():
        for y in ALL_YIELDS:
            parsed = unit_model.BUILDING_YIELDS[y].get(name, 0)
            assert parsed == _tenths(table.get(y, 0)), (name, y)
            assert type(parsed) is int


def test_unknown_yield_name_raises():
    """Breaks if city_yield silently returns 0 for a misspelt yield."""
    env = _varied_board()
    _, city = _capital_and_city(env)
    with pytest.raises(ValueError):
        city_yield(city, "sciense")


def test_a_pool_yield_table_must_hold_exactly_base_and_per_pop(monkeypatch):
    """`[science]` / `[gold]` / `[faith]` / `[culture]` are read strictly: an
    unknown or missing key raises at load. Breaks if a typo is ignored."""
    for name in POOL_YIELDS:
        good = dict(CFG[name])
        monkeypatch.setitem(CFG, name, {**good, "per_citizen": 1})
        with pytest.raises(ValueError):
            unit_model._pool_yield_table(name)
        monkeypatch.setitem(CFG, name, {"base": good["base"]})
        with pytest.raises(ValueError):
            unit_model._pool_yield_table(name)
        monkeypatch.setitem(CFG, name, good)
        assert unit_model._pool_yield_table(name) == (
            _tenths(good["base"]), _tenths(good["per_pop"]))


# --- §14 row 2: no name in the one computation --------------------------------


def test_yields_module_names_no_building_district_or_wonder():
    """civulator/game/yields.py contains no configured building, district,
    wonder (wonders are district-registry entries), policy, government or
    civic name (#116 P4 adds the last three): every source is a column or an
    effect. Breaks if a source is special-cased in code."""
    from civulator import research_model

    source = inspect.getsource(yields_mod)
    names = (set(CFG["buildings"]) | set(unit_model.BUILDING_COSTS)
             | set(district_model.DISTRICTS) | set(research_model.POLICIES)
             | set(research_model.GOVERNMENTS) | set(research_model.CIVICS))
    assert names, "fixture: something is configured"
    assert [n for n in sorted(names) if n in source] == []


# --- §14 row 3: districts reach their consumer --------------------------------


def test_every_configured_district_raises_exactly_its_adjacency_yield(monkeypatch):
    """For every configured district with an adjacency yield (Theater
    Square culture, Campus science, Holy Site faith, Commercial Hub and
    Harbor gold, Industrial Zone production, and any later one): complete,
    it raises that yield by exactly its adjacency score -- x10 for the tenths
    yields, whole points for production, through culture() and
    calculate_production too -- and no other yield; incomplete, nothing.
    The score is pinned here (the scorer is test_districts' subject). Breaks
    if a district yield reaches the wrong consumer, is double-counted, or
    counts while incomplete."""
    score = 4
    monkeypatch.setattr(districts_mod, "adjacency_score", lambda t, c, m, player=None: score)
    typed = [(n, s.adjacency_yield) for n, s in district_model.DISTRICTS.items()
             if s.adjacency_yield != "none"]
    if not typed:
        pytest.skip("no configured district has an adjacency yield")
    for name, yield_name in typed:
        env = _varied_board()
        _, city = _capital_and_city(env)
        before = _yields(city)
        culture_before, production_before = culture(city), city.calculate_production(env)
        district = _put(env, city, name, (6, 7), complete=False)
        assert _yields(city) == before, f"{name}: incomplete counts"
        district.complete = True
        gain = 10 * score if yield_name in POOL_YIELDS else score
        expected = {y: before[y] + (gain if y == yield_name else 0) for y in ALL_YIELDS}
        assert _yields(city) == expected, name
        assert culture(city) - culture_before == expected["culture"] - before["culture"]
        assert (city.calculate_production(env) - production_before
                == expected["production"] - before["production"])


def test_a_placed_and_completed_district_feeds_its_city_through_the_real_scorer():
    """End to end, nothing on the yield path patched: two districts placed
    through place_district and finished through the production pool; the
    yield each one names grows by exactly 10 x (1 x for production) its live
    adjacency score, and the next round's pools by exactly the city's
    yields. Breaks if the engine path (place, pay, complete, accrue) loses
    the district term."""
    candidates = plain_types(2)
    env = board()
    city = make_city(env, (3, 5), population=4)
    # Hold the population steady (food is not under test here): the yields
    # compared before and after completion are then at the same population.
    city.calculate_food = lambda game_env: 2 * city.population
    first_site = sorted(env.map.get_ring_coords(city.coordinates, 1)[1])[0]
    second_site = next(n for n in sorted(neighbours(env, first_site))
                       if env.map.distance_function(n, city.coordinates) == 2)
    own(env, city, second_site)
    for name, site in zip(candidates, (first_site, second_site)):
        assert env.place_district(city, name, site), name
    before = _yields(city)
    for _ in candidates:
        city.production = 10_000
        city.produce_district(next(d.type for d in city.districts if not d.complete))
        env.turn_counter += 1
        city.process_turn(env)
    assert all(d.complete for d in city.districts)
    expected = dict(before)
    for d in city.districts:
        yield_name = district_model.DISTRICTS[d.type].adjacency_yield
        if yield_name != "none":
            score = adjacency_score(d.type, d.coordinates, env.map)
            expected[yield_name] += 10 * score if yield_name in POOL_YIELDS else score
    if expected == before:
        pytest.skip("configured adjacency gives these two districts no yield here")
    assert _yields(city) == expected

    pools = _pools(city.player)
    env.turn_counter += 1
    city.process_turn(env)
    assert {y: _pools(city.player)[y] - pools[y] for y in POOL_YIELDS} == {
        y: expected[y] for y in POOL_YIELDS}


def test_district_flat_yield_columns_are_parsed_into_tenths_and_added_when_complete(monkeypatch):
    """A district table may declare any of the six yield columns; they are
    stored in tenths and added to the city's yield once the district is
    complete. Breaks if a column is rejected, unscaled, or counted while
    incomplete."""
    cfg = {
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Flat Yields": {"production_cost": 10, "science": 1.5, "gold": 3,
                        "faith": 0.5, "culture": 2, "food": 1, "production": 2},
    }
    reg = district_model.parse_districts(cfg)
    assert reg.districts["Flat Yields"].yield_columns == {
        "science": 15, "gold": 30, "faith": 5, "culture": 20, "food": 10, "production": 20}
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    env = _varied_board()
    _, city = _capital_and_city(env)
    before = _yields(city)
    district = _put(env, city, "Flat Yields", (6, 7), complete=False)
    assert _yields(city) == before
    district.complete = True
    after = _yields(city)
    assert {y: after[y] - before[y] for y in ALL_YIELDS} == {
        "science": 15, "gold": 30, "faith": 5, "culture": 20, "food": 1, "production": 2}


def test_configured_district_specs_carry_their_flat_columns_in_tenths():
    """Every configured district spec carries all six columns (0 when not
    declared), equal to its config table in tenths. Breaks if the parser
    drops or mis-scales a column."""
    for name, spec in district_model.DISTRICTS.items():
        table = CFG["districts"][name]
        assert spec.yield_columns == {y: _tenths(table.get(y, 0)) for y in ALL_YIELDS}, name


# --- §14 row 4: pools ----------------------------------------------------------


def test_pools_grow_by_the_sum_of_the_owners_city_yields_once_per_round():
    """At its owner's turn start each city adds its science, culture, gold
    and faith (int tenths) to the owner's pools and to episode_stats
    (<name>_produced); a second turn start in the same round adds nothing,
    the next round adds again. Breaks if the once-per-round guard is lost,
    a pool is skipped or a stat diverges from its pool."""
    env = _varied_board()
    capital = make_city(env, CAPITAL_SITE, population=1)
    city = make_city(env, CITY_SITE, population=1)
    city.buildings.append("Monument")
    player = capital.player
    expected = {y: city_yield(capital, y) + city_yield(city, y) for y in POOL_YIELDS}
    assert all(expected[y] > 0 for y in ("science", "culture", "gold")), "fixture"
    stats = env.episode_stats[player.player_index]
    keys = {y: f"{y}_produced" for y in POOL_YIELDS}

    before, stats_before = _pools(player), {y: stats[keys[y]] for y in POOL_YIELDS}
    env.turn_counter += 1
    player.start_turn()
    assert {y: _pools(player)[y] - before[y] for y in POOL_YIELDS} == expected
    assert {y: stats[keys[y]] - stats_before[y] for y in POOL_YIELDS} == expected
    assert all(type(v) is int for v in _pools(player).values())
    assert all(type(stats[k]) is int for k in keys.values())

    player.start_turn()                                   # same round
    assert {y: _pools(player)[y] - before[y] for y in POOL_YIELDS} == expected

    env.turn_counter += 1
    player.start_turn()
    assert {y: _pools(player)[y] - before[y] for y in POOL_YIELDS} == {
        y: 2 * expected[y] for y in POOL_YIELDS}


def test_a_city_captured_mid_round_accrues_once_that_round():
    """A city that accrued for its old owner and changes hands in the same
    round adds nothing more that round; from the next round its yields go
    to the new owner only -- what it yields then, at the loyalty band a
    change of hands leaves it in (#116 P7: `set_owner` resets loyalty to
    `[loyalty] captured`, restated from "== the yields before capture").
    Breaks if capture resets the round stamp or a city accrues twice in one
    round."""
    env = _varied_board()
    old, new = env.players
    make_city(env, (3, 14), player_index=1)               # the new owner's capital
    city = make_city(env, CAPITAL_SITE, population=1)     # the old owner's capital
    env.turn_counter += 1
    city.process_turn(env)
    yields_now = {y: city_yield(city, y) for y in POOL_YIELDS}
    old_pools, new_pools = _pools(old), _pools(new)
    city.set_owner(new)
    yields_captured = {y: city_yield(city, y) for y in POOL_YIELDS}
    assert yields_captured == {y: yields_now[y] * loyalty_percent(city) // 100
                               for y in POOL_YIELDS}, "only the loyalty band changed"
    city.process_turn(env)                                # same round, new owner
    assert _pools(old) == old_pools and _pools(new) == new_pools
    env.turn_counter += 1
    city.process_turn(env)
    assert _pools(old) == old_pools
    assert {y: _pools(new)[y] - new_pools[y] for y in POOL_YIELDS} == yields_captured


def test_pool_stat_keys_are_declared_ints_beside_culture_produced():
    """science/gold/faith_produced exist from the first turn for every seat,
    as ints, like culture_produced. Breaks if a key is created lazily (a
    KeyError at the first accrual) or as a float."""
    env = board()
    for stats in env.episode_stats.values():
        for y in POOL_YIELDS:
            assert type(stats[f"{y}_produced"]) is int
