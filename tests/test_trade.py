"""Issue #116 P5: trade routes (docs/progression_design.md §7.4, §13, "v2
fixes"; §14 rows "A trade route needs a Trader, a destination within range,
and free capacity ...", the Trader default and determinism).

Reference values are re-derived from config.toml (`CFG["trade"]`, the
district registry's own definition of a specialty district, the effects
interpreter for what is configured) and from the canonical hex kernels,
never from civulator/game/trade.py's tables. No test pins which districts,
civics or buildings exist, which yields a table gives, or how many routes a
game opens: each asserts the rule every configured entry obeys.
"""

import copy

import numpy as np
import pytest

from civulator import district_model, research_model, unit_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.config import CFG
from civulator.district_model import CITY_CENTER
from civulator.effects import KIND_TRADE_ROUTE_CAPACITY, SCOPE_CITY, effects_of
from civulator.game.districts import District
from civulator.game.environment import GameEnvironment
from civulator.game.trade import (
    DURATION_TURNS,
    ROUTE_RANGE,
    TRADER_UNIT,
    TradeRoute,
    eligible_destinations,
    expire_routes,
    parse_trade,
    route_capacity,
)
from civulator.game.yields import city_yield
from civulator.unit_model import YIELD_COLUMNS

from conftest import grant_all, stand, synthetic_government, synthetic_policy
from test_combat_range import make_flat_env
from test_districts import ring

POOL_YIELDS = unit_model.POOL_YIELDS        # city_yield in tenths
QUIET = next(c for c in research_model.CIVIC_ORDER if not research_model.CIVICS[c].effects)


# --- Fixtures ---------------------------------------------------------------------


def trade_board(m=16):
    """All-Plains board (rivers cleared), two players who know both trees."""
    env = make_flat_env(n=8, m=m)
    env.map.rivers.clear()
    env.map.terrain_epoch += 1
    for player in env.players:
        grant_all(player)
    return env


def city_at(env, coords, player_index=0):
    return env.create_city(env.players[player_index], coords, "C")


def _capacity_civics():
    names = [c for c in research_model.CIVIC_ORDER
             if any(e.kind == KIND_TRADE_ROUTE_CAPACITY for e in effects_of("civic", c))]
    assert names, "fixture: a civic grants the base route capacity"
    return names


def _capacity_buildings():
    names = [b for b in sorted(unit_model.BUILDING_NAMES)
             if any(e.kind == KIND_TRADE_ROUTE_CAPACITY and e.scope == SCOPE_CITY
                    for e in effects_of("building", b))]
    assert len(names) >= 2, "fixture: two buildings give route capacity (Market, Lighthouse)"
    return names


def _base_capacity():
    return sum(e["amount"] for c in _capacity_civics() for e in effects_of("civic", c)
               if e.kind == KIND_TRADE_ROUTE_CAPACITY)


def only_civics(player, names):
    """Exactly these civics, no government, no card."""
    player.civics[:] = list(names)
    player.government = None
    player.policies = []


def _is_specialty(name):
    spec = district_model.DISTRICTS[name]
    return spec.kind == district_model.KIND_DISTRICT and spec.counts_toward_limit


def _put(env, city, district_type, pos, complete=True):
    district = District(district_type, city.city_id, pos, complete=complete, cost=1)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def _table_yields(kind, destination):
    """Design §7.4 from config: whole points per yield, the `kind` table's
    entries for the centre and each complete specialty district."""
    table = CFG["trade"][kind]
    names = [CITY_CENTER] + [d.type for d in destination.districts
                             if d.complete and _is_specialty(d.type)]
    out = dict.fromkeys(YIELD_COLUMNS, 0)
    for name in names:
        for yield_name, amount in table.get(name, {}).items():
            out[yield_name] += amount
    return out


def _in_city_yield_units(whole):
    """Whole points -> what city_yield reports (tenths for the pool yields)."""
    return {y: (10 * v if y in POOL_YIELDS else v) for y, v in whole.items()}


def _yields(city):
    return {y: city_yield(city, y) for y in YIELD_COLUMNS}


def _traders(player):
    return [u for u in player.units if u.unit_type == TRADER_UNIT]


# --- Capacity -------------------------------------------------------------------------


def test_capacity_is_the_civic_base_plus_one_per_city_with_a_capacity_building():
    """route_capacity: 0 with nothing; the capacity civic's amount (Foreign
    Trade's 1) once known; +1 for a city holding a capacity building, still
    +1 when the same city holds two (Civ 6: Market and Lighthouse in one city
    add 1), +1 more for a second city holding one. Breaks if a building's
    capacity is summed within a city, a city's is lost, or the civic base is
    not read."""
    env = trade_board()
    player = env.players[0]
    first, second = city_at(env, (3, 3)), city_at(env, (3, 11))
    only_civics(player, [])
    assert route_capacity(player) == 0
    only_civics(player, _capacity_civics())
    base = _base_capacity()
    assert base >= 1 and route_capacity(player) == base
    one, other = _capacity_buildings()[:2]
    first.buildings.append(one)
    assert route_capacity(player) == base + 1
    first.buildings.append(other)
    assert route_capacity(player) == base + 1, "one city counts once"
    second.buildings.append(other)
    assert route_capacity(player) == base + 2


# --- Eligibility -------------------------------------------------------------------------


def _wide_board():
    """A 40-wide board: an origin, a city at exactly ROUTE_RANGE, one beyond,
    and two more of the origin's owner nearby."""
    env = trade_board(m=40)
    origin = city_at(env, (3, 2))
    at_range = city_at(env, (3, 2 + ROUTE_RANGE), player_index=1)
    beyond = city_at(env, (0, 3 + ROUTE_RANGE), player_index=1)
    near = city_at(env, (3, 8))
    home = city_at(env, (0, 5))
    distance = env.distance_function
    assert distance(origin.coordinates, at_range.coordinates) == ROUTE_RANGE
    assert distance(origin.coordinates, beyond.coordinates) == ROUTE_RANGE + 1
    return env, origin, at_range, beyond, near, home


def test_destinations_are_every_other_city_in_range_in_city_id_order():
    """A Trader on an own city centre may go to every other city, of any
    owner, within `[trade] range` hexes by the canonical wrap distance --
    the boundary included, one hex more excluded -- listed in city-id order;
    off an own centre it may go nowhere. Breaks if the range is off by one,
    the distance is not the wrap kernel's, or the origin lists itself."""
    env, origin, at_range, beyond, near, home = _wide_board()
    trader = stand(env, TRADER_UNIT, 0, origin.coordinates)
    expected = [env.city_by_id[i] for i in sorted(env.city_by_id)
                if env.city_by_id[i] is not origin
                and env.distance_function(origin.coordinates,
                                          env.city_by_id[i].coordinates) <= ROUTE_RANGE]
    assert at_range in expected and beyond not in expected
    assert eligible_destinations(trader, env) == expected
    off_centre = stand(env, TRADER_UNIT, 0, ring(env, origin.coordinates, 2)[0])
    assert eligible_destinations(off_centre, env) == []
    on_foreign = stand(env, TRADER_UNIT, 0, at_range.coordinates)
    assert eligible_destinations(on_foreign, env) == []


def test_one_route_of_a_player_per_pair_of_cities_either_way():
    """A route of this player between two cities makes each ineligible from
    the other, in both directions; another player's route between the same
    two cities does not. Breaks if pair uniqueness is one-directional or
    reads other players' routes."""
    env, origin, at_range, beyond, near, home = _wide_board()
    player = env.players[0]
    player.routes.append(TradeRoute(origin.city_id, near.city_id, 0, DURATION_TURNS))
    env.players[1].routes.append(TradeRoute(at_range.city_id, origin.city_id, 1, DURATION_TURNS))
    from_origin = stand(env, TRADER_UNIT, 0, origin.coordinates)
    from_near = stand(env, TRADER_UNIT, 0, near.coordinates)
    assert near not in eligible_destinations(from_origin, env)
    assert origin not in eligible_destinations(from_near, env)
    assert at_range in eligible_destinations(from_origin, env), "player 1's route is its own"
    assert home in eligible_destinations(from_near, env)


# --- Establishing a route -------------------------------------------------------------------------


def _route_board():
    env = trade_board()
    player = env.players[0]
    only_civics(player, _capacity_civics())
    origin = city_at(env, (3, 3))
    destination = city_at(env, (3, 10), player_index=1)
    trader = stand(env, TRADER_UNIT, 0, origin.coordinates)
    return env, player, origin, destination, trader


def test_establishing_a_route_consumes_the_trader_and_records_the_route():
    """With a Trader on an own centre, an eligible destination and a free
    slot, the Trader leaves the player and its tile and one route of
    `[trade] duration_turns` turns is recorded for its owner; the counter
    counts it. Breaks if the Trader survives, the record is wrong or the
    route is not counted."""
    env, player, origin, destination, trader = _route_board()
    assert env.establish_trade_route(trader, destination) is True
    assert trader not in player.units and trader not in env.get_units_at(origin.coordinates)
    assert player.routes == [TradeRoute(origin.city_id, destination.city_id,
                                        player.player_index, DURATION_TURNS)]
    assert env.episode_stats[0]["trade_routes_established"] == 1


def _route_state(env):
    return ([(list(p.routes), [(u.unit_type, u.coordinates) for u in p.units]) for p in env.players],
            {i: dict(s) for i, s in env.episode_stats.items()})


@pytest.mark.parametrize("case", ["not a trader", "off the centre", "to its own origin",
                                  "out of range", "pair already linked", "no free slot"])
def test_a_refused_route_changes_nothing(case):
    """Each precondition refuses on its own: a unit not of the trade type,
    a Trader off an own centre, the origin as destination, a city out of
    range, a pair already linked, no free slot. Nothing moves. Breaks if
    establish_trade_route skips a rule or half-applies."""
    env, player, origin, destination, trader = _route_board()
    unit, target = trader, destination
    if case == "not a trader":
        env.delete_unit(trader)
        unit = stand(env, "Warrior", 0, origin.coordinates)
    elif case == "off the centre":
        env.move_unit(trader, ring(env, origin.coordinates, 1)[0])
    elif case == "to its own origin":
        target = origin
    elif case == "out of range":
        env = trade_board(m=40)
        only_civics(env.players[0], _capacity_civics())
        origin = city_at(env, (3, 2))
        target = city_at(env, (3, 3 + ROUTE_RANGE), player_index=1)
        unit = stand(env, TRADER_UNIT, 0, origin.coordinates)
    elif case == "pair already linked":
        player.routes.append(TradeRoute(origin.city_id, destination.city_id, 0, 1))
        origin.buildings.append(_capacity_buildings()[0])  # a slot stays free
        assert route_capacity(player) > len(player.routes)
    elif case == "no free slot":
        only_civics(player, [])
    before = _route_state(env)
    assert env.establish_trade_route(unit, target) is False
    assert _route_state(env) == before


# --- Yields ---------------------------------------------------------------------------------


def _dressed_destination(env, coords, player_index):
    """A city holding every configured district complete except one specialty
    district left unfinished (so the table's specialty and non-specialty
    entries, and an unfinished one, are all exercised)."""
    city = city_at(env, coords, player_index)
    sites = sorted(set(ring(env, coords, 1)) | set(ring(env, coords, 2)))
    names = list(district_model.DISTRICTS)
    specialty = [n for n in names if _is_specialty(n)]
    assert specialty and any(not _is_specialty(n) for n in names), "fixture"
    for index, name in enumerate(names):
        _put(env, city, name, sites[index], complete=(name != specialty[0]))
    return city


@pytest.mark.parametrize("international", [False, True])
def test_a_route_yields_its_origin_exactly_the_destination_table(international):
    """A route adds to its ORIGIN's city_yield, for every yield, exactly the
    `[trade.domestic]` (same owner) or `[trade.international]` entries of
    the destination's centre and its complete specialty districts -- an
    unfinished district and a non-specialty one add nothing -- in tenths for
    the pool yields and whole points for food and production; the
    destination's own yields do not move. Breaks if a table entry is lost,
    the wrong table is read, the destination gains, or units are mixed."""
    env = trade_board()
    player = env.players[0]
    only_civics(player, [])
    origin = city_at(env, (3, 3))
    origin.assign_tiles(env)
    destination = _dressed_destination(env, (3, 10), 1 if international else 0)
    kind = "international" if international else "domestic"
    expected = _in_city_yield_units(_table_yields(kind, destination))
    assert any(expected.values()), "fixture: the table yields something"
    before, before_destination = _yields(origin), _yields(destination)
    player.routes.append(TradeRoute(origin.city_id, destination.city_id, 0, DURATION_TURNS))
    after = _yields(origin)
    assert {y: after[y] - before[y] for y in YIELD_COLUMNS} == expected
    assert _yields(destination) == before_destination


def test_route_yield_effects_add_per_route_and_international_only_abroad(monkeypatch):
    """Two `route_yield` cards -- one for every route, one international_only
    -- with one domestic and one international route from the same city:
    the first adds its yields once per route, the second once (the
    international route only); nothing else moves. Breaks if
    international_only is ignored or the effect is applied per city."""
    env = trade_board()
    player = env.players[0]
    origin = city_at(env, (3, 3))
    domestic = city_at(env, (6, 8))
    abroad = city_at(env, (0, 12), player_index=1)
    for target in (domestic, abroad):
        player.routes.append(TradeRoute(origin.city_id, target.city_id, 0, DURATION_TURNS))
    player.civics[:] = [QUIET]
    synthetic_government(monkeypatch, "Synthetic Government", {"wildcard": 2}, requires_civic=QUIET)
    assert env.set_government(player, "Synthetic Government")
    assert env.set_policies(player, [])
    before = _yields(origin)
    synthetic_policy(monkeypatch, "Every Route", [{"kind": "route_yield", "gold": 2}],
                     requires_civic=QUIET)
    synthetic_policy(monkeypatch, "Abroad", [{"kind": "route_yield", "culture": 1,
                                              "international_only": True}], requires_civic=QUIET)
    assert env.set_policies(player, ["Every Route", "Abroad"])
    after = _yields(origin)
    moved = {y: after[y] - before[y] for y in YIELD_COLUMNS if after[y] != before[y]}
    assert moved == {"gold": 2 * 20, "culture": 10}


# --- Expiry and the end of routes ---------------------------------------------------------------


def test_a_route_lasts_duration_turns_then_its_trader_returns_to_the_origin():
    """A new route survives `[trade] duration_turns` - 1 expiry steps and
    ends on the next, returning a Trader to its origin (here: the free
    centre). Breaks if a route ends early or late, or its Trader is lost."""
    env, player, origin, destination, trader = _route_board()
    assert env.establish_trade_route(trader, destination)
    for _ in range(DURATION_TURNS - 1):
        assert expire_routes(player, env) == []
    assert len(player.routes) == 1 and player.routes[0].turns_left == 1
    ended = expire_routes(player, env)
    assert len(ended) == 1 and player.routes == []
    assert [u.coordinates for u in _traders(player)] == [origin.coordinates]


def test_an_ended_route_is_reopened_by_the_trader_default_in_the_same_phase():
    """E2E through the economy phase: a route in its last turn expires, its
    Trader reappears on the origin's centre and the engine default sends it
    out again at once, so trade stays live without an agent. Breaks if
    expiry runs after the default or the returned Trader idles."""
    env, player, origin, destination, trader = _route_board()
    assert env.establish_trade_route(trader, destination)
    player.routes[0].turns_left = 1
    env.economy_phase(player)
    assert len(player.routes) == 1 and player.routes[0].turns_left == DURATION_TURNS
    assert _traders(player) == []
    assert env.episode_stats[0]["trade_routes_established"] == 2


def test_a_returning_trader_with_no_room_is_queued():
    """An ending route whose origin has no free tile queues its Trader as
    `(city_id, unit_type)` instead of losing it. Breaks if the return
    bypasses the queue."""
    env, player, origin, destination, trader = _route_board()
    assert env.establish_trade_route(trader, destination)
    stand(env, "Warrior", 0, origin.coordinates)
    for pos in env.map.get_adjacent_coords(origin.coordinates):
        stand(env, "Warrior", 1, pos)
    player.routes[0].turns_left = 1
    expire_routes(player, env)
    assert player.routes == [] and _traders(player) == []
    assert player.queued_units == [(origin.city_id, TRADER_UNIT)]


def _three_routes():
    """Player A: cities a1, a2; player B: city b1. Routes: A a1->a2 and
    a1->b1; B b1->a2. No unit stands anywhere."""
    env = trade_board()
    a, b = env.players
    a1, a2 = city_at(env, (3, 2)), city_at(env, (3, 7))
    b1 = city_at(env, (3, 12), player_index=1)
    a.routes += [TradeRoute(a1.city_id, a2.city_id, 0, 5), TradeRoute(a1.city_id, b1.city_id, 0, 5)]
    b.routes.append(TradeRoute(b1.city_id, a2.city_id, 1, 5))
    return env, a, b, a1, a2, b1


def test_a_change_of_hands_ends_every_route_touching_the_city():
    """When a city changes hands (`City.set_owner`) every route of any
    player starting or ending there ends: whoever still holds a route's
    origin gets its Trader back there; a route whose origin was the city is
    simply removed; routes not touching it run on. Breaks if a side's route
    survives, a Trader is lost or duplicated, or the wrong player gets it."""
    env, a, b, a1, a2, b1 = _three_routes()
    a2.set_owner(b)
    assert a.routes == [TradeRoute(a1.city_id, b1.city_id, 0, 5)]
    assert b.routes == []
    assert [u.coordinates for u in _traders(a)] == [a1.coordinates]
    assert [u.coordinates for u in _traders(b)] == [b1.coordinates]

    a1.set_owner(b)  # the origin of A's last route
    assert a.routes == [] and b.routes == []
    assert len(_traders(a)) == 1 and len(_traders(b)) == 1, "nobody gains a Trader"


def test_a_capture_through_the_engine_ends_the_routes_touching_the_city():
    """E2E: a melee unit walking into a beaten city (the #84 capture path,
    `_capture_city` -> `set_owner`) ends the routes touching it, exactly as
    above. Breaks if the capture path changes hands without the hook."""
    env, a, b, a1, a2, b1 = _three_routes()
    env.current_player, env.current_player_index = b, 1
    stand(env, "Warrior", 1, (6, 6))  # an idle unit, so the turn does not roll over
    raider = stand(env, "Warrior", 1, ring(env, a2.coordinates, 1)[0])
    a2.health = 0
    r, c = raider.coordinates
    env.step([np.array([r, c, raider.slot]), np.array(list(a2.coordinates))])
    assert a2.player is b
    assert a.routes == [TradeRoute(a1.city_id, b1.city_id, 0, 5)] and b.routes == []


def test_removing_a_city_ends_its_routes():
    """`remove_city` ends every route touching the city: a route from
    another city returns its Trader there, a route from the removed city
    is lost. Breaks if a route outlives its city."""
    env, a, b, a1, a2, b1 = _three_routes()
    env.remove_city(a2)
    assert a.routes == [TradeRoute(a1.city_id, b1.city_id, 0, 5)] and b.routes == []
    assert [u.coordinates for u in _traders(a)] == [a1.coordinates]
    assert [u.coordinates for u in _traders(b)] == [b1.coordinates]
    env.remove_city(a1)
    assert a.routes == []


# --- The Trader default ----------------------------------------------------------------------


def _default_board():
    """Player 0 knows only the capacity civic; its origin holds a Trader;
    destinations of differing worth from the config tables."""
    env = trade_board()
    player = env.players[0]
    only_civics(player, _capacity_civics())
    only_civics(env.players[1], [])
    origin = city_at(env, (3, 3))
    trader = stand(env, TRADER_UNIT, 0, origin.coordinates)
    cities = [city_at(env, (0, 8)), city_at(env, (6, 8), player_index=1),
              city_at(env, (3, 12), player_index=1)]
    specialty = [n for n in district_model.DISTRICTS if _is_specialty(n)]
    _put(env, cities[0], specialty[0], ring(env, cities[0].coordinates, 1)[0])
    _put(env, cities[2], specialty[-1], ring(env, cities[2].coordinates, 1)[0])
    return env, player, origin, trader, cities


def _worth(player, destination):
    kind = "domestic" if destination.player is player else "international"
    return sum(_table_yields(kind, destination).values())


def test_the_default_sends_an_idle_trader_to_the_most_valuable_destination():
    """In the economy phase a Trader on an own centre, with all its movement
    and not having acted, is sent where the route would yield its origin
    the most (all yields counted alike, from the tables), ties to the lower
    city id. Breaks if the default picks by another measure, ignores ties,
    or uses randomness."""
    env, player, origin, trader, cities = _default_board()
    best = min(cities, key=lambda c: (-_worth(player, c), c.city_id))
    env.economy_phase(player)
    assert [(r.origin_city_id, r.destination_city_id) for r in player.routes] == [
        (origin.city_id, best.city_id)]

    env, player, origin, trader, cities = _default_board()
    for city in cities:  # every destination worth the same: the lowest id wins
        for district in list(city.districts):
            env.map.get_tile(district.coordinates).district = None
        city.districts.clear()
        if city.player is not player:
            city.set_owner(player)
    env.economy_phase(player)
    assert player.routes[0].destination_city_id == min(c.city_id for c in cities)


@pytest.mark.parametrize("why", ["moved", "acted", "no free slot"])
def test_the_default_leaves_a_trader_that_moved_acted_or_has_no_slot(why):
    """A Trader without its full movement, one that has acted, or any Trader
    when every slot is taken stays where it is. Breaks if the default sends
    a Trader the rules say waits."""
    env, player, origin, trader, cities = _default_board()
    if why == "moved":
        trader.movement_points -= 1
    elif why == "acted":
        trader.has_acted = True
    else:
        only_civics(player, [])
    env.economy_phase(player)
    assert player.routes == [] and trader in player.units
    assert trader.coordinates == origin.coordinates


def _expected_step(env, trader):
    """One step toward the nearest own centre, from the canonical kernels:
    the adjacent tile with no foreign unit, strictly nearer, nearest first,
    ties by (row, col)."""
    here = tuple(trader.coordinates)
    target = min((tuple(c.coordinates) for c in trader.player.cities),
                 key=lambda p: (env.distance_function(here, p), p))
    now = env.distance_function(here, target)
    options = [tuple(p) for p in env.map.get_adjacent_coords(here)
               if not any(u.player is not trader.player for u in env.get_units_at(p))
               and env.distance_function(p, target) < now]
    return min(options, key=lambda p: (env.distance_function(p, target), p))


# Off the origin's axes, so two neighbours are equally nearer (the tie-break
# and the foreign-unit rule are both exercised).
STRAY = (6, 1)


def test_the_default_walks_a_stray_trader_one_step_toward_the_nearest_own_centre():
    """A Trader off every own centre moves one step, through Unit.move, to
    the adjacent tile nearest the nearest own centre (ties by coordinates),
    never onto a foreign unit; it opens no route that turn. Breaks if it
    jumps, wanders, steps onto an enemy or uses path_finder."""
    env, player, origin, trader, cities = _default_board()
    env.move_unit(trader, STRAY)
    start = env.distance_function(trader.coordinates, origin.coordinates)
    first = _expected_step(env, trader)
    env.economy_phase(player)
    assert trader.coordinates == first
    assert env.distance_function(trader.coordinates, origin.coordinates) == start - 1
    assert player.routes == []

    env, player, origin, trader, cities = _default_board()
    env.move_unit(trader, STRAY)
    blocked = _expected_step(env, trader)
    nearer = [p for p in env.map.get_adjacent_coords(STRAY)
              if env.distance_function(p, origin.coordinates)
              < env.distance_function(STRAY, origin.coordinates)]
    assert len(nearer) >= 2, "fixture: two neighbours are nearer"
    stand(env, "Warrior", 1, blocked)
    second = _expected_step(env, trader)
    assert second != blocked
    env.economy_phase(player)
    assert trader.coordinates == second


def _seeded_trade_game(seed, rounds):
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for player in env.players:
        grant_all(player)
        stand(env, TRADER_UNIT, player.player_index, player.cities[0].coordinates)
    trail = []
    for _ in range(2 * rounds):
        env.next_turn()
        trail.append([[(r.origin_city_id, r.destination_city_id, r.turns_left) for r in p.routes]
                      for p in env.players])
    return env, trail


def test_two_same_seed_games_open_identical_routes():
    """Two games from one seed with no agent choice open the same routes, in
    the same turns, and count the same; at least one route opens (the
    default is live). Breaks if the Trader default or route bookkeeping
    depends on set/dict iteration or randomness."""
    env_a, trail_a = _seeded_trade_game(11, DURATION_TURNS + 4)
    env_b, trail_b = _seeded_trade_game(11, DURATION_TURNS + 4)
    assert trail_a == trail_b
    counts = [env_a.episode_stats[i]["trade_routes_established"] for i in range(2)]
    assert counts == [env_b.episode_stats[i]["trade_routes_established"] for i in range(2)]
    assert sum(counts) > 0


# --- The build mask and production (the Trader rule) -------------------------------------


def test_the_trader_is_offered_and_produced_exactly_while_a_route_slot_is_free():
    """Across states of capacity, routes and standing Traders, the build mask
    offers the Trader, produce_unit accepts it and purchase buys it exactly
    when capacity > routes + Traders (the capacity derived from config).
    Breaks if the mask and production disagree, or a Trader that could never
    be sent is offered (the mask invariant, #51)."""
    env = trade_board()
    player = env.players[0]
    only_civics(player, _capacity_civics())
    city = city_at(env, (3, 3))
    other = city_at(env, (3, 10), player_index=1)
    city.population = 3
    player.gold = 10 ** 6
    index = BUILD_OPTIONS.index(TRADER_UNIT)
    capacity_building = _capacity_buildings()[0]

    def check():
        capacity = _base_capacity() + (1 if capacity_building in city.buildings else 0)
        free = capacity > len(player.routes) + len(_traders(player))
        assert get_valid_build_mask(city)[index] == float(free)
        before = dict(city.current_production)
        assert city.produce_unit(TRADER_UNIT) is free
        if not free:
            assert city.current_production == before
        city.current_production = {"type": "unit", "unit_type": "Warrior"}
        return free

    assert check() is True
    standing = stand(env, TRADER_UNIT, 0, ring(env, city.coordinates, 1)[0])
    assert check() is False
    assert env.purchase(city, "unit", TRADER_UNIT, "gold") is False
    env.delete_unit(standing)
    player.routes.append(TradeRoute(city.city_id, other.city_id, 0, DURATION_TURNS))
    assert check() is False
    city.buildings.append(capacity_building)
    assert check() is True
    assert env.purchase(city, "unit", TRADER_UNIT, "gold") is True
    assert check() is False


# --- The [trade] tables -----------------------------------------------------------------------


@pytest.mark.parametrize("damage", [
    ("domestic", "Atlantis", {"food": 1}),
    ("international", "Atlantis", {"gold": 3}),
    ("domestic", CITY_CENTER, {"food": 1.5}),
    ("domestic", CITY_CENTER, {"food": -1}),
    ("domestic", CITY_CENTER, {"happiness": 1}),
    ("international", CITY_CENTER, {}),
])
def test_a_malformed_trade_table_raises_at_load(damage):
    """A `[trade.*]` entry naming neither a district nor "City Center", a
    yield that is not whole and non-negative, an unknown yield or an empty
    entry raises. Breaks if a typo'd district silently adds nothing."""
    kind, name, entry = damage
    cfg = copy.deepcopy(CFG["trade"])
    cfg[kind][name] = entry
    with pytest.raises(ValueError):
        parse_trade(cfg, district_model.DISTRICTS, unit_model.UNIT_NAMES)


@pytest.mark.parametrize("key, value", [("unit", "Galleon"), ("range", 0),
                                        ("duration_turns", 2.5), ("speed", 1)])
def test_the_trade_scalars_are_read_strictly(key, value):
    """`[trade]` has exactly its keys; the unit must be a unit type, range and
    duration positive whole numbers. Breaks if a bad scalar loads."""
    cfg = copy.deepcopy(CFG["trade"])
    cfg[key] = value
    with pytest.raises(ValueError):
        parse_trade(cfg, district_model.DISTRICTS, unit_model.UNIT_NAMES)


def test_the_configured_trade_tables_name_real_districts():
    """The real `[trade]` parses, every entry names a district or the city
    centre, and both tables give the centre something (a route always
    yields). Breaks if config.toml gains an entry the rule cannot read."""
    parsed = parse_trade(CFG["trade"], district_model.DISTRICTS, unit_model.UNIT_NAMES)
    for kind, table in parsed.tables.items():
        for name in table:
            assert name == CITY_CENTER or name in district_model.DISTRICTS, (kind, name)
        assert any(table[CITY_CENTER].values()), kind
    assert parsed.unit in unit_model.UNIT_NAMES
