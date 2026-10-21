"""Issue #116 P5: gold -- maintenance, bankruptcy, purchasing and the queued
units it revives (docs/progression_design.md §7.1-§7.3, §10.1, "v2 fixes";
§14 rows "Maintenance is deducted once per owner turn ..." and "Purchase
costs production_cost * multiplier ...").

Reference values are re-derived here from config.toml (`CFG`), never from
civulator/game/maintenance.py or purchasing.py, so a drift in the one
computation shows up as a mismatch against the rule it implements. No test
pins which units, buildings or districts exist, what they cost or how many
there are: each asserts the rule every configured one obeys. Boards are the
all-Plains fixture of test_districts (both players know both trees).
"""

import pytest

from civulator import district_model, research_model, unit_model
from civulator.config import CFG
from civulator.effects import (
    KIND_FAITH_PURCHASE,
    KIND_PURCHASE_PERCENT,
    SCOPE_PLAYER,
    SOURCE_BUILDING,
    SOURCE_GOVERNMENT,
    active_effects,
    effects_of,
)
from civulator.game.city import City
from civulator.game.districts import District
from civulator.game.maintenance import maintenance_due
from civulator.game.purchasing import purchase_cost
from civulator.game.trade import TRADER_UNIT
from civulator.game.yields import city_yield
from civulator.game.housing import housing

from conftest import stand, synthetic_government, synthetic_policy
from test_districts import board, make_city, ring

# A civic with no effects of its own: what the synthetic cards unlock with.
QUIET = next(c for c in research_model.CIVIC_ORDER if not research_model.CIVICS[c].effects)
GOVERNMENT = "Synthetic Government"
RESOURCES = unit_model.PURCHASE_RESOURCES


# --- Fixtures ---------------------------------------------------------------------


def _tenths(value):
    return round(10 * value)


def _column_upkeep(table):
    """A config table's `maintenance` in tenths of gold (absent = 0)."""
    return _tenths(table.get("maintenance", 0))


def _expected_due(player, delta=0):
    """Design §7.1 from config: every unit's column plus 10 * delta, floored
    at 0 per unit; every building's column; every COMPLETE district's."""
    due = sum(max(0, _column_upkeep(CFG["units"][u.unit_type]) + 10 * delta)
              for u in player.units)
    for city in player.cities:
        due += sum(_column_upkeep(CFG["buildings"][b]) for b in city.buildings)
        due += sum(_column_upkeep(CFG["districts"][d.type]) for d in city.districts if d.complete)
    return due


def _put(env, city, district_type, pos, complete=True):
    """Fixture only: link a District by hand (the rule under test is upkeep,
    not placement)."""
    district = District(district_type, city.city_id, pos, complete=complete, cost=1)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def _free_tiles(env, count):
    """`count` distinct tiles holding no city, district or unit, in (row, col)
    order."""
    tiles = []
    for row in range(env.n):
        for col in range(env.m):
            tile = env.map.get_tile((row, col))
            if tile.city is None and tile.district is None and not tile.units:
                tiles.append((row, col))
    assert len(tiles) >= count, "fixture: the board has room"
    return tiles[:count]


def _stand_all(env, player_index, unit_types):
    """A unit of each of `unit_types`, in order, each on its own free tile."""
    return [stand(env, t, player_index, pos)
            for t, pos in zip(unit_types, _free_tiles(env, len(unit_types)))]


def _no_effects(player):
    """No civic, no government, no card: no effect of any kind in force
    (techs carry none), so the bare columns decide."""
    player.civics[:] = []
    player.government = None
    player.policies = []


def _slot_cards(monkeypatch, env, player, cards):
    """Exactly the synthetic cards `cards` (one list of effect entries each)
    in force for `player`, under a synthetic government with a wildcard slot
    per card, unlocked by QUIET."""
    player.civics[:] = [QUIET]
    synthetic_government(monkeypatch, GOVERNMENT, {"wildcard": max(1, len(cards))},
                         requires_civic=QUIET)
    assert env.set_government(player, GOVERNMENT)
    names = []
    for index, entries in enumerate(cards):
        name = f"Synthetic Card {index}"
        synthetic_policy(monkeypatch, name, entries, requires_civic=QUIET)
        names.append(name)
    assert env.set_policies(player, names)


def _upkeep_of(unit_type):
    return _column_upkeep(CFG["units"][unit_type])


def _maintained_types():
    """Unit types with a positive upkeep column, in name order."""
    names = sorted(n for n in unit_model.UNIT_NAMES if _upkeep_of(n) > 0)
    assert len({_upkeep_of(n) for n in names}) >= 2, "fixture: two upkeep levels exist"
    return names


def _free_types():
    names = sorted(n for n in unit_model.UNIT_NAMES
                   if _upkeep_of(n) == 0 and n != TRADER_UNIT)
    assert names, "fixture: some unit is free"
    return names


# --- §7.1 Maintenance ----------------------------------------------------------------


def test_maintenance_is_every_unit_building_and_complete_district_column():
    """With no effect in force, one economy phase takes exactly the summed
    `maintenance` columns of the player's units, its cities' buildings and
    their COMPLETE districts (a placed, unfinished one owes nothing) from
    the treasury, and `gold_maintenance` records it. Breaks if a column is
    skipped, an unfinished district pays, or the tenths are mis-scaled."""
    env = board()
    player = env.players[0]
    _no_effects(player)
    capital = make_city(env, (3, 4))
    other = make_city(env, (3, 11))
    _stand_all(env, 0, sorted(unit_model.UNIT_NAMES))
    other.buildings.extend(n for n in CFG["buildings"] if n in unit_model.BUILDING_COSTS)
    sites = ring(env, capital.coordinates, 2)
    for index, name in enumerate(district_model.DISTRICTS):
        _put(env, capital, name, sites[index])
    unfinished = _put(env, other, next(iter(district_model.DISTRICTS)),
                      ring(env, other.coordinates, 2)[0], complete=False)
    expected = _expected_due(player)
    assert sum(_column_upkeep(CFG["districts"][d.type]) for d in capital.districts) > 0
    assert _column_upkeep(CFG["districts"][unfinished.type]) > 0, "fixture: it would pay"
    assert any(_column_upkeep(CFG["buildings"][b]) for b in other.buildings)
    assert any(_upkeep_of(u.unit_type) for u in player.units)

    assert maintenance_due(player) == expected
    player.gold = 10 ** 6
    env.economy_phase(player)
    assert player.gold == 10 ** 6 - expected
    assert env.episode_stats[0]["gold_maintenance"] == expected
    assert env.episode_stats[0]["units_disbanded"] == 0
    assert type(env.episode_stats[0]["gold_maintenance"]) is int


@pytest.mark.parametrize("deltas", [[-1], [-1, -1], [2], [-1, 3]])
def test_maintenance_delta_effects_are_summed_and_each_unit_floors_at_zero(monkeypatch, deltas):
    """The `unit_maintenance_delta` cards in force are summed into one whole-
    gold delta per unit, and no unit's upkeep falls below 0: due = sum of
    max(0, column + 10 * sum(deltas)). Breaks if the delta is applied per
    card, unscaled, to buildings, or allowed to make a unit pay the player."""
    env = board()
    player = env.players[0]
    _stand_all(env, 0, sorted(unit_model.UNIT_NAMES))
    _slot_cards(monkeypatch, env, player,
                [[{"kind": "unit_maintenance_delta", "amount": d}] for d in deltas])
    delta = sum(deltas)
    assert maintenance_due(player) == _expected_due(player, delta)
    if delta < 0:
        assert any(_upkeep_of(u.unit_type) + 10 * delta < 0 for u in player.units), \
            "fixture: some unit hits the floor"


def test_maintenance_is_paid_once_per_own_turn():
    """Over R full rounds of play, each player pays its upkeep exactly R
    times -- once per own turn, in its economy phase, never in the other
    player's. Breaks if maintenance runs per city, per round or in both
    players' turns."""
    env = board()
    for player in env.players:
        _no_effects(player)
    make_city(env, (3, 4), player_index=0)
    make_city(env, (3, 12), player_index=1)
    _stand_all(env, 0, _maintained_types())
    for player in env.players:
        player.gold = 10 ** 6
    bills = [_expected_due(p) for p in env.players]
    assert bills[0] > 0, "fixture: player 0 owes upkeep"
    rounds = 3
    for _ in range(2 * rounds):
        env.next_turn()
    for index, bill in enumerate(bills):
        assert env.episode_stats[index]["gold_maintenance"] == rounds * bill


# --- §7.2 Bankruptcy -----------------------------------------------------------------


def _bankruptcy_roster():
    """Unit types in a fixed order mixing free units, every upkeep level and
    a repeated highest level (so the lowest-index tie-break is exercised)."""
    maintained = sorted(_maintained_types(), key=lambda n: (_upkeep_of(n), n))
    top = maintained[-1]
    return [maintained[0], top, _free_types()[0], maintained[len(maintained) // 2], top,
            maintained[0]]


def _expected_disbands(upkeeps, gold_after_bill):
    """Design §7.2 from first principles: disband in order of (highest
    upkeep, lowest index), each returning its own upkeep, while the treasury
    is negative and a unit with positive upkeep remains."""
    order = sorted((i for i, u in enumerate(upkeeps) if u > 0), key=lambda i: (-upkeeps[i], i))
    gone, gold = [], gold_after_bill
    for index in order:
        if gold >= 0:
            break
        gone.append(index)
        gold += upkeeps[index]
    return gone, max(0, gold)


@pytest.mark.parametrize("deficit", ["one tenth", "two units", "everyone"])
def test_bankruptcy_disbands_highest_upkeep_then_lowest_index_until_solvent(monkeypatch, deficit):
    """A treasury negative after maintenance disbands units one at a time --
    the highest upkeep first, the lowest `player.units` index among equals,
    each disbanded unit not paying its upkeep -- until the treasury is >= 0,
    then floors it at 0; `units_disbanded` counts them and the survivors
    keep their order. Breaks if the order depends on iteration order,
    disbanding overshoots, or the treasury ends an economy phase negative."""
    env = board()
    player = env.players[0]
    _no_effects(player)
    units = _stand_all(env, 0, _bankruptcy_roster())
    upkeeps = [_upkeep_of(u.unit_type) for u in units]
    bill = sum(upkeeps)
    top = max(upkeeps)
    shortfall = {"one tenth": 1, "two units": top + 1, "everyone": 10 * bill}[deficit]
    player.gold = bill - shortfall
    gone, final = _expected_disbands(upkeeps, -shortfall)
    assert gone, "fixture: something must go"
    deleted = []
    original = env.delete_unit
    monkeypatch.setattr(env, "delete_unit", lambda unit: (deleted.append(unit), original(unit)))

    env.economy_phase(player)
    assert deleted == [units[i] for i in gone], "disbanded through delete_unit, in this order"
    assert player.units == [u for i, u in enumerate(units) if i not in gone]
    for i in gone:
        assert units[i] not in env.get_units_at(units[i].coordinates), "off its tile too"
    assert player.gold == final >= 0
    assert env.episode_stats[0]["units_disbanded"] == len(gone)
    if deficit == "two units":
        tied = [i for i, u in enumerate(upkeeps) if u == top]
        assert len(tied) >= 2 and gone[0] == tied[0], "the lower index goes first"
    if deficit == "everyone":
        assert all(_upkeep_of(u.unit_type) == 0 for u in player.units)


def test_the_treasury_is_floored_at_zero_when_no_unit_can_be_disbanded():
    """Buildings and districts that cost more than the treasury holds, and
    only free units: nothing is disbanded and the treasury ends at 0, never
    negative. Breaks if bankruptcy disbands a free unit or leaves debt."""
    env = board()
    player = env.players[0]
    _no_effects(player)
    city = make_city(env, (3, 4))
    city.buildings.extend(n for n in CFG["buildings"]
                          if n in unit_model.BUILDING_COSTS and _column_upkeep(CFG["buildings"][n]))
    units = _stand_all(env, 0, _free_types())
    assert _expected_due(player) > 0
    player.gold = _expected_due(player) - 1
    env.economy_phase(player)
    assert player.gold == 0
    assert player.units == units
    assert env.episode_stats[0]["units_disbanded"] == 0


def test_a_player_with_only_free_units_and_no_gold_is_untouched():
    """Free units, no upkeep anywhere, an empty treasury: the economy phase
    takes nothing and disbands nothing. Breaks if a free unit is ever
    charged or a zero treasury alone triggers bankruptcy."""
    env = board()
    player = env.players[0]
    _no_effects(player)
    make_city(env, (3, 4))
    units = _stand_all(env, 0, _free_types())
    places = [u.coordinates for u in units]
    assert _expected_due(player) == 0
    player.gold = 0
    env.economy_phase(player)
    assert player.gold == 0
    assert player.units == units and [u.coordinates for u in units] == places
    assert env.episode_stats[0]["units_disbanded"] == 0
    assert env.episode_stats[0]["gold_maintenance"] == 0


# --- §7.3 Purchasing: the price -------------------------------------------------------------


def _priced_items():
    units = [("unit", n, CFG["units"][n]["production_cost"]) for n in sorted(unit_model.UNIT_NAMES)]
    buildings = [("building", n, t["production_cost"]) for n, t in CFG["buildings"].items()
                 if "production_cost" in t]
    return units + buildings


def test_the_price_is_production_cost_times_the_resource_multiplier():
    """With no effect in force, every unit and costed building costs
    `production_cost * [<resource>] purchase_multiplier` of gold and of
    faith (Civ 6: 4x and 2x), whole points; an item without a production
    cost has no price. Breaks if a multiplier is not read or is hardcoded."""
    env = board()
    player = env.players[0]
    _no_effects(player)
    for kind, name, cost in _priced_items():
        for resource in RESOURCES:
            expected = cost * CFG[resource]["purchase_multiplier"]
            assert purchase_cost(player, kind, name, resource) == expected, (name, resource)
    unpriced = [n for n, t in CFG["buildings"].items() if "production_cost" not in t]
    assert unpriced, "fixture: some building is granted, never built"
    for name in unpriced:
        assert purchase_cost(player, "building", name, "gold") is None


@pytest.mark.parametrize("cards", [
    [[{"kind": "purchase_percent", "resource": "gold", "percent": -20}]],
    [[{"kind": "purchase_percent", "resource": "gold", "percent": -20}],
     [{"kind": "purchase_percent", "resource": "gold", "percent": -30}]],
    [[{"kind": "purchase_percent", "resource": "faith", "percent": 15}]],
    [[{"kind": "purchase_percent", "resource": "gold", "percent": -150}]],
])
def test_purchase_percent_effects_are_summed_and_applied_once_to_their_resource(monkeypatch,
                                                                                cards):
    """The `purchase_percent` cards in force for a resource are summed and
    applied once: price = cost * multiplier * (100 + sum) // 100, floored at
    0; the other resource's price does not move. Breaks if the percents
    compound, leak across resources, or a price goes negative."""
    env = board()
    player = env.players[0]
    _slot_cards(monkeypatch, env, player, cards)
    percent = {r: sum(e["percent"] for card in cards for e in card if e["resource"] == r)
               for r in RESOURCES}
    for kind, name, cost in _priced_items():
        for resource in RESOURCES:
            multiplier = CFG[resource]["purchase_multiplier"]
            expected = max(0, cost * multiplier * (100 + percent[resource]) // 100)
            assert purchase_cost(player, kind, name, resource) == expected, (name, resource)


# --- §7.3 Purchasing: refusals change nothing ------------------------------------------------


def _state(env):
    """Everything a purchase could touch."""
    return (
        [(p.gold, p.faith, [id(u) for u in p.units], [(u.unit_type, u.coordinates) for u in p.units],
          list(p.queued_units)) for p in env.players],
        [(c.city_id, list(c.buildings), dict(c.current_production or {}), c.production)
         for _, c in sorted(env.city_by_id.items())],
        {i: dict(s) for i, s in env.episode_stats.items()},
    )


def _gold_only_building():
    """A costed, purchasable-with-gold-only building with no district,
    building or government requirement (so a fresh city can take it)."""
    for name in sorted(unit_model.BUILDING_COSTS):
        if (unit_model.BUILDING_PURCHASABLE[name] == ("gold",)
                and name not in unit_model.BUILDING_REQUIRES_DISTRICT
                and name not in unit_model.BUILDING_REQUIRES_BUILDING
                and name not in unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER):
            return name
    pytest.skip("no plain gold-purchasable building configured")


def _unbuyable_building():
    for name in sorted(unit_model.BUILDING_COSTS):
        if (unit_model.BUILDING_PURCHASABLE[name] == ()
                and name not in unit_model.BUILDING_REQUIRES_DISTRICT
                and name not in unit_model.BUILDING_REQUIRES_BUILDING
                and name not in unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER):
            return name
    pytest.skip("no plain never-purchasable building configured")


def _land_military_unit(gated=False):
    """A land military unit buyable with gold but not listed for faith;
    with `gated`, one that needs a tech."""
    for name in sorted(unit_model.UNIT_NAMES):
        if (unit_model.faith_category(name) is not None
                and unit_model.UNIT_PURCHASABLE[name] == ("gold",)
                and (name in unit_model.UNIT_REQUIRES_TECH) == gated):
            return name
    pytest.skip("no such unit configured")


def _purchase_board():
    """Player 0 (the current player, both trees known, no government) with a
    city of population 3 and full pools; player 1 with a city of its own."""
    env = board()
    assert env.current_player is env.players[0]
    capital = make_city(env, (0, 8))
    city = make_city(env, (4, 3), population=3)
    foreign = make_city(env, (4, 12), player_index=1, population=3)
    for player in env.players:
        player.gold = player.faith = 10 ** 6
    return env, capital, city, foreign


def _refusal(case):
    """(env, city, kind, name, resource) where exactly the rule `case` fails."""
    env, _, city, foreign = _purchase_board()
    player = env.players[0]
    building = _gold_only_building()
    unit = _land_military_unit()
    if case == "unaffordable by one tenth":
        player.gold = 10 * purchase_cost(player, "building", building, "gold") - 1
        return env, city, "building", building, "gold"
    if case == "not purchasable":
        return env, city, "building", _unbuyable_building(), "gold"
    if case == "not available":
        gated = _land_military_unit(gated=True)
        player.techs.remove(unit_model.UNIT_REQUIRES_TECH[gated])
        return env, city, "unit", gated, "gold"
    if case == "wrong resource":
        return env, city, "building", building, "faith"
    if case == "faith without the category unlocked":
        assert not any(active_effects(player, city, KIND_FAITH_PURCHASE)), "fixture"
        return env, city, "unit", unit, "faith"
    if case == "building owned":
        city.buildings.append(building)
        return env, city, "building", building, "gold"
    if case == "foreign city":
        return env, foreign, "building", building, "gold"
    if case == "not an item kind":
        return env, city, "district", next(iter(district_model.DISTRICTS)), "gold"
    if case == "not a resource":
        return env, city, "building", building, "culture"
    raise AssertionError(case)


REFUSALS = ["unaffordable by one tenth", "not purchasable", "not available", "wrong resource",
            "faith without the category unlocked", "building owned", "foreign city",
            "not an item kind", "not a resource"]


@pytest.mark.parametrize("case", REFUSALS)
def test_a_refused_purchase_changes_nothing(case):
    """Each rule of §7.3 refuses on its own (every other rule met): purchase
    returns False and no pool, unit, queue, building, production item or
    counter moves. Breaks if a rule is skipped (the purchase goes through)
    or a refusal half-applies."""
    env, city, kind, name, resource = _refusal(case)
    before = _state(env)
    assert env.purchase(city, kind, name, resource) is False
    assert _state(env) == before


def test_the_refusal_cases_are_one_rule_away_from_a_purchase():
    """Fixture guard for the refusal table: the baseline item of each case
    is buyable when its one failing rule is lifted. Breaks if a refusal
    case is refused for some other reason than the one it names."""
    env, _, city, _ = _purchase_board()
    assert env.purchase(city, "building", _gold_only_building(), "gold") is True
    env, _, city, _ = _purchase_board()
    assert env.purchase(city, "unit", _land_military_unit(gated=True), "gold") is True
    env, _, city, _ = _purchase_board()
    player = env.players[0]
    player.gold = 10 * purchase_cost(player, "building", _gold_only_building(), "gold")
    assert env.purchase(city, "building", _gold_only_building(), "gold") is True
    assert player.gold == 0


# --- §7.3 Purchasing: what a purchase makes ---------------------------------------------------


def test_a_purchased_unit_is_placed_through_complete_unit_production(monkeypatch):
    """Buying a unit pays 10 x the price from the pool, counts it in
    `<resource>_spent_purchases`, and places the unit by the city's
    `complete_unit_production` (here: on the free centre). Breaks if a
    purchase creates units by another path or charges the wrong amount."""
    env, _, city, _ = _purchase_board()
    player = env.players[0]
    unit = _land_military_unit()
    calls = []
    original = City.complete_unit_production

    def spy(self, unit_type, game_env):
        calls.append((self, unit_type))
        return original(self, unit_type, game_env)

    monkeypatch.setattr(City, "complete_unit_production", spy)
    price = 10 * purchase_cost(player, "unit", unit, "gold")
    assert env.purchase(city, "unit", unit, "gold") is True
    assert calls == [(city, unit)]
    assert player.gold == 10 ** 6 - price
    assert env.episode_stats[0]["gold_spent_purchases"] == price
    assert env.episode_stats[0]["faith_spent_purchases"] == 0
    bought = [u for u in player.units if u.unit_type == unit]
    assert len(bought) == 1 and bought[0].coordinates == city.coordinates
    assert player.queued_units == []


def test_a_purchased_item_is_indistinguishable_from_a_built_one():
    """Twin cities on identical ground: one buys a building and a unit, the
    other produces them. The buildings lists, every yield, housing and
    defence match, and the units match in class, health, movement, slot and
    place relative to their city. Breaks if a purchase marks or shortcuts
    what it makes."""
    env, _, bought_in, _ = _purchase_board()
    built_in = make_city(env, (4, 7), population=3)
    for city in (bought_in, built_in):
        city.assign_tiles(env)
        city.current_production = None
    building, unit = _gold_only_building(), _land_military_unit()
    assert env.purchase(bought_in, "building", building, "gold")
    assert built_in.produce_building(building)
    built_in.production = built_in.get_building_cost(building)
    for city in (bought_in, built_in):  # the same turn for both twins
        city.process_turn(env)
    assert bought_in.population == built_in.population, "fixture: identical ground"
    assert bought_in.buildings == built_in.buildings
    for name in unit_model.YIELD_COLUMNS:
        assert city_yield(bought_in, name) == city_yield(built_in, name), name
    assert housing(bought_in) == housing(built_in)
    assert bought_in.get_combat_strength() == built_in.get_combat_strength()

    player = env.players[0]
    assert env.purchase(bought_in, "unit", unit, "gold")
    assert built_in.produce_unit(unit)
    built_in.production = built_in.get_unit_cost(unit)
    built_in.process_turn(env)
    a, b = ([u for u in player.units if u.unit_type == unit and u.coordinates == c.coordinates]
            for c in (bought_in, built_in))
    assert len(a) == len(b) == 1
    a, b = a[0], b[0]
    for attribute in ("unit_type", "health", "movement_points", "fortification", "has_acted",
                      "slot"):
        assert getattr(a, attribute) == getattr(b, attribute), attribute
    assert type(a) is type(b)


def test_buying_the_building_in_production_clears_the_item_and_keeps_the_pool():
    """A city producing building X that buys X holds it once: its production
    item is cleared (the pool is kept, as on any switch), so it never
    completes a second X. Breaks if the bought building is built again."""
    env, _, city, _ = _purchase_board()
    building = _gold_only_building()
    assert city.produce_building(building)
    city.production = 7
    assert env.purchase(city, "building", building, "gold")
    assert city.current_production is None and city.production == 7
    city.production = city.get_building_cost(building)
    city.process_turn(env)
    assert city.buildings.count(building) == 1


def _faith_governments():
    names = [g for g in research_model.GOVERNMENTS
             if any(e.kind == KIND_FAITH_PURCHASE for e in effects_of(SOURCE_GOVERNMENT, g))]
    assert names, "fixture: some government unlocks faith purchases"
    return names


@pytest.mark.parametrize("government", _faith_governments())
def test_faith_buys_a_land_military_unit_under_a_government_that_unlocks_it(government):
    """Under a government with a `faith_purchase` effect (Theocracy), a land
    military unit not listed for faith may be bought with faith, at cost *
    faith multiplier scaled by the faith `purchase_percent` effects in force
    (Theocracy's -15 %); without that government it is refused. Breaks if
    the category is not consumed or the government's discount is lost."""
    env, _, city, _ = _purchase_board()
    player = env.players[0]
    unit = _land_military_unit()
    assert env.purchase(city, "unit", unit, "faith") is False
    assert env.set_government(player, government)
    percent = sum(e["percent"] for e in active_effects(player, kind=KIND_PURCHASE_PERCENT)
                  if e["resource"] == "faith")
    expected = (CFG["units"][unit]["production_cost"] * CFG["faith"]["purchase_multiplier"]
                * (100 + percent) // 100)
    assert purchase_cost(player, "unit", unit, "faith") == expected
    assert env.purchase(city, "unit", unit, "faith") is True
    assert player.faith == 10 ** 6 - 10 * expected
    assert env.episode_stats[0]["faith_spent_purchases"] == 10 * expected


def _faith_buildings():
    names = [b for b in sorted(unit_model.BUILDING_NAMES)
             if any(e.kind == KIND_FAITH_PURCHASE for e in effects_of(SOURCE_BUILDING, b))]
    assert names, "fixture: some building unlocks faith purchases"
    return names


@pytest.mark.parametrize("building", _faith_buildings())
def test_a_faith_purchase_building_unlocks_faith_purchases_in_every_city(building):
    """The Grand Master's Chapel's `faith_purchase` effect is player-scoped
    (Civ 6: empire-wide; the P4 report's one-word fix): held in one city,
    it lets another city of the same player buy a land military unit with
    faith; without it that purchase is refused. Breaks if the effect falls
    back to city scope or the category is read from the wrong city."""
    assert all(e.scope == SCOPE_PLAYER for e in effects_of(SOURCE_BUILDING, building)
               if e.kind == KIND_FAITH_PURCHASE)
    env, capital, city, _ = _purchase_board()
    unit = _land_military_unit()
    assert env.purchase(city, "unit", unit, "faith") is False
    capital.buildings.append(building)
    assert env.purchase(city, "unit", unit, "faith") is True


# --- Queued units (v2 fixes: revived for units that cannot be placed) --------------------------


def _blocked(env, city):
    """A friendly unit on the centre and a foreign one on every neighbour,
    so `complete_unit_production` cannot place anything here."""
    stand(env, _free_types()[0], city.player.player_index, city.coordinates)
    return [stand(env, _free_types()[0], 1 - city.player.player_index, pos)
            for pos in env.map.get_adjacent_coords(city.coordinates)]


def test_a_purchased_unit_with_no_room_is_queued_and_placed_at_turn_start():
    """A unit bought in a city with no free tile is paid for and queued as
    `(city_id, unit_type)`; at the owner's next turn start, once a
    neighbour is free, it is placed there and leaves the queue. Breaks if a
    blocked purchase is lost, placed off the rules, or never placed."""
    env, _, city, _ = _purchase_board()
    player = env.players[0]
    unit = _land_military_unit()
    blockers = _blocked(env, city)
    price = 10 * purchase_cost(player, "unit", unit, "gold")
    assert env.purchase(city, "unit", unit, "gold") is True
    assert player.queued_units == [(city.city_id, unit)]
    assert player.gold == 10 ** 6 - price
    assert not [u for u in player.units if u.unit_type == unit]

    player.start_turn()
    assert player.queued_units == [(city.city_id, unit)], "still no room"
    freed = blockers[0].coordinates
    env.delete_unit(blockers[0])
    player.start_turn()
    assert player.queued_units == []
    placed = [u for u in player.units if u.unit_type == unit]
    assert len(placed) == 1 and placed[0].coordinates == freed


def test_queued_units_are_dropped_with_their_city():
    """When a city changes hands (`City.set_owner`) its old owner's queued
    entries for it are dropped -- the new owner inherits none -- and an
    entry whose city its player no longer holds is dropped at turn start
    without making a unit; entries for other cities stay. Breaks if a lost
    city still delivers units, or to the wrong player."""
    env, capital, city, _ = _purchase_board()
    player, other = env.players
    unit = _land_military_unit()
    player.queued_units = [(city.city_id, unit), (capital.city_id, unit)]
    other_queue = list(other.queued_units)
    city.set_owner(other)
    assert player.queued_units == [(capital.city_id, unit)]
    assert other.queued_units == other_queue

    player.queued_units.append((city.city_id, unit))
    counts = [len([u for u in p.units if u.unit_type == unit]) for p in env.players]
    player.place_queued_units()
    assert (city.city_id, unit) not in player.queued_units
    after = [len([u for u in p.units if u.unit_type == unit]) for p in env.players]
    assert after == [counts[0] + 1, counts[1]], "only the capital's entry is placed"
