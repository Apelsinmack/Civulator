"""Sea trade (v0.9.0 Q6, docs/districts_religion_design.md §6.6, §11 rows
22-24, "v2 fixes" B6 and B8, "v3 fixes" L10): landmasses, sea reachability,
sea routes and the overseas yield jump.

Reference values are re-derived from config.toml (`CFG["trade"]`) and from
the canonical hex kernels (`mapgen.landmasses.find_landmasses` for what a
landmass is, `hexmath` through the Map for adjacency), never from
civulator/game/trade.py's own tables. No test pins how many districts,
techs or yields exist; each asserts the rule that every configured entry
obeys.

Worlds are built by hand on a Coast (or Ocean) board: islands are 3 x 4
blocks of Plains, a city stands on each, its Harbor on a water tile beside
it (placed through the engine's own `place_district`).
"""

import numpy as np
import pytest

from civulator import hexmath, mapgen
from civulator.config import CFG
from civulator.game import trade
from civulator.game.districts import ship_spawn_districts
from civulator.game.environment import GameEnvironment
from civulator.game.trade import (
    DURATION_TURNS,
    LAND_ROUTE,
    SEA_ROUTE,
    TRADER_UNIT,
    eligible_destinations,
    eligible_routes,
    pair_yields,
    parse_trade,
    route_kind,
    route_yields,
)
from civulator.district_model import DISTRICTS
from civulator.unit_model import UNIT_NAMES, YIELD_COLUMNS

from conftest import grant, stand
from test_districts import make_city, own, ring
from test_sea import OCEAN_TECHS, galley, set_base
from test_trade import _capacity_civics, city_at, only_civics, trade_board

ROWS = 8
ISLAND_ROWS = range(2, 5)
ISLAND_WIDTH = 4


# --- Fixtures ---------------------------------------------------------------------


def water_world(islands, m=40, fill="Coast"):
    """A trade board (all techs and civics known) of `fill` water with a
    Plains island at each `islands` column: rows 2-4, `ISLAND_WIDTH` wide."""
    env = trade_board(m=m)
    for r in range(ROWS):
        for c in range(m):
            set_base(env, (r, c), fill)
    for c0 in islands:
        for r in ISLAND_ROWS:
            for c in range(c0, c0 + ISLAND_WIDTH):
                set_base(env, (r, c % m), "Plains")
    for player in env.players:
        only_civics(player, _capacity_civics())
    return env


def island_city(env, c0, player_index=0):
    """A city on the island starting at column `c0`, at its middle."""
    return city_at(env, (3, c0 + 1), player_index=player_index)


def add_harbor(env, city, base="Coast", anywhere=False):
    """A complete Harbor for `city` on the first water tile of its rings 1-2
    the engine accepts (any tile if `anywhere`: a Lake carved out of land),
    that tile set to `base` ("Coast" or "Lake") first."""
    for pos in [*ring(env, city.coordinates, 1), *ring(env, city.coordinates, 2)]:
        if not anywhere and env.map.get_tile(pos).domain != "water":
            continue
        set_base(env, pos, base)
        own(env, city, pos)
        if env.place_district(city, "Harbor", pos):
            env.complete_district(city, city.districts[-1])
            return pos
    raise AssertionError("fixture: no Harbor could be placed")


def forget_ocean(env):
    """Nobody knows the `ocean_navigation` rule (before Cartography)."""
    for player in env.players:
        for tech in OCEAN_TECHS:
            if tech in player.techs:
                player.techs.remove(tech)


def pair(islands=(2, 12), m=40, fill="Coast", harbors=True, player_indices=(0, 1)):
    """(env, origin, destination): a city on each of two islands, Harbors
    unless told otherwise."""
    env = water_world(islands, m=m, fill=fill)
    origin = island_city(env, islands[0], player_indices[0])
    destination = island_city(env, islands[1], player_indices[1])
    if harbors:
        add_harbor(env, origin)
        add_harbor(env, destination)
    return env, origin, destination


def kind_of(env, origin, destination):
    return route_kind(origin, destination, origin.player, env)


def open_route(env, origin, destination):
    trader = stand(env, TRADER_UNIT, origin.player.player_index, origin.coordinates)
    assert env.establish_trade_route(trader, destination), "fixture: the route must open"
    return origin.player.routes[-1]


# --- Landmasses (B8) ------------------------------------------------------------------


def test_landmass_id_partitions_land_exactly_as_the_mapgen_kernel_does():
    """On generated worlds `Map.landmass_id` groups the tiles into the same
    components `mapgen.landmasses.find_landmasses` finds on the same terrain,
    water has no landmass, and two tiles share an id exactly when the kernel
    puts them in one component. Breaks if the Map grows its own flood fill
    (a second definition of a landmass) or the labelling drops a tile."""
    for seed in (1, 2, 3):
        env = GameEnvironment().reset(seed=seed)
        game_map = env.map
        base = np.empty((game_map.n, game_map.m), dtype=object)
        for r in range(game_map.n):
            for c in range(game_map.m):
                base[r, c] = game_map.tiles[r, c].base_terrain
        components = mapgen.landmasses.find_landmasses(base, game_map.n, game_map.m)
        assert components, "fixture: the world has land"
        ids = [{game_map.landmass_id(pos) for pos in component} for component in components]
        assert all(len(group) == 1 and None not in group for group in ids)
        assert len({next(iter(group)) for group in ids}) == len(components)
        on_land = {pos for component in components for pos in component}
        for r in range(game_map.n):
            for c in range(game_map.m):
                if (r, c) not in on_land:
                    assert game_map.landmass_id((r, c)) is None


def test_landmass_id_follows_canonical_adjacency_with_wrap():
    """Two land tiles on opposite edges of the cylinder, adjacent through the
    wrap, share a landmass; a water gap separates others. Breaks if the
    labelling forgets the wrap or adjacency is hand-rolled."""
    env = water_world([], m=16)
    left, right = (3, 0), (3, 15)
    assert right in hexmath.adjacent_coords(left, ROWS, 16), "fixture: wrap neighbours"
    for pos in (left, right):
        set_base(env, pos, "Plains")
    set_base(env, (3, 7), "Plains")
    assert env.map.landmass_id(left) == env.map.landmass_id(right) is not None
    assert env.map.landmass_id((3, 7)) not in (None, env.map.landmass_id(left))


def test_landmass_labels_refresh_when_the_terrain_epoch_moves():
    """Filling the water gap between two islands merges their ids at once,
    flooding a land tile removes it from its island. Breaks if the cache
    ignores `terrain_epoch`."""
    env = water_world([2, 8], m=40)
    a, b = (3, 3), (3, 9)
    assert env.map.landmass_id(a) != env.map.landmass_id(b)
    for c in range(6, 8):
        set_base(env, (3, c), "Plains")
    assert env.map.landmass_id(a) == env.map.landmass_id(b)
    set_base(env, a, "Coast")
    assert env.map.landmass_id(a) is None


# --- Water reachability (B6) ----------------------------------------------------------


def corridor_world():
    """All Plains; row 3 holds a straight water corridor columns 2-10 (Coast),
    8 steps from end to end. Returns (env, west end, east end)."""
    env = trade_board(m=16)
    for c in range(2, 11):
        set_base(env, (3, c), "Coast")
    return env, (3, 2), (3, 10)


def test_water_distance_counts_tiles_and_honours_the_range():
    """The corridor's length is its tile steps; a limit one short finds
    nothing. Breaks if the BFS counts cost instead of tiles or ignores
    `max_steps`."""
    env, west, east = corridor_world()
    assert env.map.water_distance(west, east, "coast", 30) == 8
    assert env.map.water_reachable(west, east, "coast", 8)
    assert not env.map.water_reachable(west, east, "coast", 7)
    assert env.map.water_distance(west, west, "coast", 30) == 0


def test_water_reachability_ignores_units():
    """A ship parked on the corridor's only tile of that column does not
    change the answer, though `path_finder` (which routes around occupied
    tiles) now fails -- the contrast that makes this test mean something.
    Breaks if reachability reads unit positions (a route would flicker with
    a parked ship, design B6)."""
    env, west, east = corridor_world()
    before = env.map.water_distance(west, east, "coast", 30)
    stand(env, galley(), 1, (3, 6))
    assert len(env.map.path_finder(west, east, domain="coast")) == 0, "fixture: the ship blocks A*"
    env.map.terrain_epoch += 1          # force a recomputation with the ship in place
    assert env.map.water_distance(west, east, "coast", 30) == before == 8


def test_water_reachability_honours_the_domain():
    """An Ocean tile in the corridor blocks the "coast" domain and not the
    "water" domain; the lengths agree where both find a path. Breaks if the
    BFS ignores `deep` (Q5's `can_enter`) or reads one domain for both."""
    env, west, east = corridor_world()
    set_base(env, (3, 6), "Ocean")
    assert env.map.water_distance(west, east, "coast", 30) is None
    assert env.map.water_distance(west, east, "water", 30) == 8


def test_water_reachability_refreshes_when_the_terrain_epoch_moves():
    """Filling a corridor tile cuts the path, restoring it reopens it.
    Breaks if the BFS cache ignores `terrain_epoch`."""
    env, west, east = corridor_world()
    assert env.map.water_reachable(west, east, "coast", 30)
    set_base(env, (3, 5), "Plains")
    assert not env.map.water_reachable(west, east, "coast", 30)
    set_base(env, (3, 5), "Coast")
    assert env.map.water_reachable(west, east, "coast", 30)


def test_water_reachability_wraps_around_the_cylinder():
    """A corridor crossing the seam is one path. Breaks if the BFS forgets
    the wrap (canonical adjacency is hexmath's)."""
    env = trade_board(m=16)
    for c in (14, 15, 0, 1):
        set_base(env, (3, c), "Coast")
    assert env.map.water_distance((3, 14), (3, 1), "coast", 30) == 3


# --- Route kind ------------------------------------------------------------------------


def test_a_pair_with_harbors_and_a_coast_path_is_a_sea_route_across_landmasses():
    """Two Harbors joined by a coast path within `sea_range` make a sea
    route, overseas because the centres lie on different landmasses.
    Breaks if the route test skips the Harbor, the water path or the
    landmass comparison."""
    env, origin, destination = pair()
    assert env.map.landmass_id(origin.coordinates) != env.map.landmass_id(destination.coordinates)
    assert kind_of(env, origin, destination) == (SEA_ROUTE, True)


def test_without_harbors_the_same_pair_is_a_land_pair_and_never_overseas():
    """The pair of the previous test without its Harbors is a land pair
    (within `range`), and a land pair across a strait is not overseas --
    today's yield. Breaks if the overseas flag leaks to land routes (B6)."""
    env, origin, destination = pair(harbors=False)
    assert kind_of(env, origin, destination) == (LAND_ROUTE, False)
    env, origin, destination = pair()
    for city in (origin, destination):          # one Harbor is not enough either
        harbor = ship_spawn_districts(city)[0]
        city.districts.remove(harbor)
        env.map.get_tile(harbor.coordinates).district = None
        assert kind_of(env, origin, destination) == (LAND_ROUTE, False)
        city.districts.append(harbor)
        env.map.get_tile(harbor.coordinates).district = harbor


def test_a_harbor_that_is_not_complete_does_not_count():
    """Only a COMPLETE `ship_spawn` district terminates a sea route. Breaks
    if the route test reads districts under construction."""
    env, origin, destination = pair()
    ship_spawn_districts(destination)[0].complete = False
    assert kind_of(env, origin, destination) == (LAND_ROUTE, False)


def test_the_sea_range_bounds_sea_routes_and_land_range_still_bounds_land_ones():
    """Harbors further apart by water than `sea_range` (and by land than
    `range`) leave no route at all, though the water does connect them (a
    longer limit finds the path): it is the range that refuses. Breaks if
    `sea_range` is not read or the pair gets a kind from nowhere."""
    m = 2 * (trade.SEA_RANGE + 12)
    far = m // 2 - 2                     # near the antipode on the cylinder
    env, origin, destination = pair(islands=(2, far), m=m)
    harbors = [ship_spawn_districts(c)[0].coordinates for c in (origin, destination)]
    assert env.distance_function(origin.coordinates, destination.coordinates) > trade.ROUTE_RANGE
    assert env.map.water_reachable(*harbors, "coast", m)
    assert not env.map.water_reachable(*harbors, "coast", trade.SEA_RANGE)
    assert kind_of(env, origin, destination) == (None, False)
    env, origin, destination = pair(islands=(2, far), m=m, harbors=False)
    assert kind_of(env, origin, destination) == (None, False)


def test_a_pair_reachable_by_land_and_by_sea_is_a_sea_route():
    """Two Harbors within land `range` AND joined by water are a sea route
    (so a strait rewards the Harbor pair); the land rule applies only when
    sea fails. Breaks if the land test runs first."""
    env, origin, destination = pair(islands=(2, 7))
    assert env.distance_function(origin.coordinates, destination.coordinates) <= trade.ROUTE_RANGE
    assert kind_of(env, origin, destination)[0] == SEA_ROUTE


def test_an_ocean_only_path_needs_ocean_navigation():
    """With the Harbors on Coast tiles in an Ocean sea, the sea route exists
    only once the owner knows the `ocean_navigation` rule; before it, the
    pair far beyond land range is no route and a near pair falls back to
    land. Breaks if the route test uses a fixed domain instead of the
    owner's naval domain."""
    env, origin, destination = pair(islands=(2, 22), m=60, fill="Ocean")
    assert env.distance_function(origin.coordinates, destination.coordinates) > trade.ROUTE_RANGE
    assert kind_of(env, origin, destination) == (SEA_ROUTE, True)
    forget_ocean(env)
    assert kind_of(env, origin, destination) == (None, False)
    near_env, near_a, near_b = pair(islands=(2, 10), m=60, fill="Ocean")
    forget_ocean(near_env)
    assert kind_of(near_env, near_a, near_b) == (LAND_ROUTE, False)
    grant(near_env.players[0], *OCEAN_TECHS)
    assert kind_of(near_env, near_a, near_b) == (SEA_ROUTE, True)


def test_the_origin_owners_navigation_decides_not_the_destinations():
    """Cartography is read from the route's OWNER: player 0 knowing the
    ocean rule and player 1 not still gets the sea route 0 -> 1, and the
    reverse does not. Breaks if the domain is read from the destination."""
    env, origin, destination = pair(islands=(2, 22), m=60, fill="Ocean")
    forget_ocean(env)
    grant(env.players[0], *OCEAN_TECHS)
    assert kind_of(env, origin, destination)[0] == SEA_ROUTE
    assert kind_of(env, destination, origin)[0] is None


def test_a_harbor_on_a_lake_ends_no_sea_route():
    """Harbors on two different Lakes have no water path to each other: the
    pair falls back to land rules, not overseas. Breaks if a Lake Harbor
    counts as a sea terminal without a water path."""
    env = trade_board(m=40)
    a, b = city_at(env, (3, 3)), city_at(env, (3, 12), player_index=1)
    add_harbor(env, a, base="Lake", anywhere=True)
    add_harbor(env, b, base="Lake", anywhere=True)
    assert kind_of(env, a, b) == (LAND_ROUTE, False)


def test_two_harbors_on_one_lake_are_a_sea_route_but_never_overseas():
    """A shared Lake is a water path; both cities lie on one landmass, so
    the route is a sea route and not overseas. Breaks if the overseas test
    is path-based or the Lake is not in the water domain."""
    env = trade_board(m=40)
    for c in range(5, 9):
        set_base(env, (3, c), "Lake")
    a, b = city_at(env, (3, 3)), city_at(env, (3, 10), player_index=1)
    for city, pos in ((a, (3, 5)), (b, (3, 8))):
        own(env, city, pos)
        assert env.place_district(city, "Harbor", pos), "fixture: the Lake Harbor is placeable"
        env.complete_district(city, city.districts[-1])
    assert kind_of(env, a, b) == (SEA_ROUTE, False)


def test_route_kind_reads_terrain_not_units():
    """A fleet in the strait leaves the kind unchanged. Breaks if the route
    kind uses `path_finder` (design B6)."""
    env, origin, destination = pair(islands=(2, 8))
    before = kind_of(env, origin, destination)
    for pos in ring(env, origin.coordinates, 2):
        if env.map.get_tile(pos).domain == "water" and not env.get_units_at(pos):
            stand(env, galley(), 1, pos)
    assert kind_of(env, origin, destination) == before == (SEA_ROUTE, True)


def test_eligible_destinations_has_land_and_sea_cities_in_city_id_order():
    """A Trader's destinations are the cities with any kind -- land-reachable
    or sea-reachable -- in city-id order, minus linked pairs; the cities
    out of both ranges are absent. Breaks if only land cities are listed,
    the order follows something else, or the one-route-per-pair rule goes."""
    env, origin, destination = pair(islands=(2, 22), m=60)
    near = city_at(env, (6, 10), player_index=1)          # land range of the origin
    out_of_reach = city_at(env, (1, 40), player_index=1)  # beyond land, no Harbor
    trader = stand(env, TRADER_UNIT, 0, origin.coordinates)
    found = eligible_destinations(trader, env)
    assert near in found and destination in found and out_of_reach not in found
    assert [c.city_id for c in found] == sorted(c.city_id for c in found)
    assert [(c, k) for c, k, _ in eligible_routes(trader, env)
            if c is destination] == [(destination, SEA_ROUTE)]
    origin.player.routes.append(trade.TradeRoute(destination.city_id, origin.city_id,
                                                 0, 5))   # either direction links the pair
    assert destination not in eligible_destinations(trader, env)


# --- The overseas jump ------------------------------------------------------------------


def reference_yields(player, destination):
    """The `[trade]` table entry for the destination's centre and its
    complete specialty districts, int tenths, straight from config."""
    table = CFG["trade"]["domestic" if destination.player is player else "international"]
    names = ["City Center"] + [d.type for d in destination.districts if d.complete
                               and DISTRICTS[d.type].kind == "district"
                               and DISTRICTS[d.type].counts_toward_limit]
    out = dict.fromkeys(YIELD_COLUMNS, 0)
    for name in names:
        for yield_name, amount in table.get(name, {}).items():
            out[yield_name] += 10 * amount
    return out


def test_an_overseas_route_yields_every_yield_times_the_percent_floored_in_tenths():
    """With the pair across the sea, every yield of the route is the plain
    pair yield times (100 + percent) / 100 floored in tenths, at the
    configured percent and at percents that make the floor bite; percent 0
    switches the jump off. Breaks if the multiplier skips a yield, rounds to
    nearest or changes the land yield."""
    env, origin, destination = pair()
    player = origin.player
    plain = pair_yields(player, origin, destination, False)
    assert plain == reference_yields(player, destination), "the plain yield is the config table's"
    assert any(plain.values()), "fixture: a yield to multiply"
    percent = CFG["trade"]["overseas_percent"]
    jumped = pair_yields(player, origin, destination, True)
    assert jumped == {y: v * (100 + percent) // 100 for y, v in plain.items()}
    for odd in (0, 1, 55, 250):
        saved, trade.OVERSEAS_PERCENT = trade.OVERSEAS_PERCENT, odd
        try:
            assert pair_yields(player, origin, destination, True) == {
                y: v * (100 + odd) // 100 for y, v in plain.items()}
        finally:
            trade.OVERSEAS_PERCENT = saved
    assert pair_yields(player, origin, destination, False) == plain


def test_a_route_yields_what_its_stored_flag_says():
    """`route_yields` multiplies exactly the routes opened overseas: the sea
    route across the strait doubles, a land route between the same cities
    without Harbors does not. Breaks if the multiplier moves out of
    `pair_yields`, or the stored flag is ignored."""
    env, origin, destination = pair()
    route = open_route(env, origin, destination)
    assert (route.kind, route.overseas) == (SEA_ROUTE, True)
    plain = pair_yields(origin.player, origin, destination, False)
    percent = CFG["trade"]["overseas_percent"]
    assert route_yields(route, env) == {y: v * (100 + percent) // 100 for y, v in plain.items()}

    env, origin, destination = pair(harbors=False)
    route = open_route(env, origin, destination)
    assert (route.kind, route.overseas) == (LAND_ROUTE, False)
    assert route_yields(route, env) == pair_yields(origin.player, origin, destination, False)


def test_the_trader_default_picks_the_overseas_route_when_it_pays_most():
    """Among a land destination of a given base value and an overseas one
    of a lower base value, the default sends the Trader overseas exactly
    when the multiplier lifts it past the land one -- the candidate's flag
    goes through the same `pair_yields` a live route reads. Breaks if
    `best_destination` ranks without the flag (design B6: the default must
    find the overseas route)."""
    from civulator.game.defaults import best_destination

    env, origin, overseas = pair()
    # An extra patch of land within land range, a Harbor-less city of the
    # same player on it (a domestic destination).
    for pos in [(6, 8), *env.map.get_adjacent_coords((6, 8))]:
        set_base(env, pos, "Plains")
    land = city_at(env, (6, 8), player_index=0)
    trader = stand(env, TRADER_UNIT, 0, origin.coordinates)
    routes = {c: (k, o) for c, k, o in eligible_routes(trader, env)}
    assert routes[overseas] == (SEA_ROUTE, True)
    land_total = sum(pair_yields(origin.player, origin, land, routes[land][1]).values())
    base_total = sum(pair_yields(origin.player, origin, overseas, False).values())
    assert base_total > 0
    needed = (100 * land_total) // base_total + 101       # strictly above the land route
    saved = trade.OVERSEAS_PERCENT
    try:
        trade.OVERSEAS_PERCENT = needed
        assert best_destination(trader, env) is overseas
        trade.OVERSEAS_PERCENT = 0
        expected = max((land, overseas), key=lambda c: (
            sum(pair_yields(origin.player, origin, c, False).values()), -c.city_id))
        assert best_destination(trader, env) is expected
    finally:
        trade.OVERSEAS_PERCENT = saved


# --- Establishment fixes kind and flag ---------------------------------------------------


def test_the_kind_and_flag_are_fixed_at_establishment_and_new_routes_may_differ():
    """A route opened over land (the sea path was Ocean-only, Cartography
    unknown) stays a land route when its owner learns Cartography, and keeps
    its yield; a route opened as a sea route stays one and overseas when its
    water path is later filled in. A NEW route over the same pair would be
    decided afresh. Breaks if the kind or flag is recomputed live."""
    env, origin, destination = pair(islands=(2, 10), m=60, fill="Ocean")
    forget_ocean(env)
    route = open_route(env, origin, destination)
    assert (route.kind, route.overseas) == (LAND_ROUTE, False)
    before = route_yields(route, env)
    grant(env.players[0], *OCEAN_TECHS)
    assert kind_of(env, origin, destination) == (SEA_ROUTE, True), "a new route would differ"
    assert (route.kind, route.overseas) == (LAND_ROUTE, False)
    assert route_yields(route, env) == before

    env, origin, destination = pair(islands=(2, 10), m=60)
    route = open_route(env, origin, destination)
    assert (route.kind, route.overseas) == (SEA_ROUTE, True)
    before = route_yields(route, env)
    harbor = ship_spawn_districts(origin)[0].coordinates
    for pos in env.map.get_adjacent_coords(harbor):
        if env.map.get_tile(pos).domain == "water" and pos != harbor:
            set_base(env, pos, "Plains")
    set_base(env, harbor, "Plains")
    assert (route.kind, route.overseas) == (SEA_ROUTE, True)
    assert route_yields(route, env) == before


def test_the_sea_counters_count_routes_by_kind_and_player():
    """`episode_stats` counts every route, the sea ones and the overseas
    ones per player: a sea route across the strait adds to all three, a land
    route only to the first. Breaks if a counter is missing, shared between
    players or bumped for the wrong kind."""
    env, origin, destination = pair()
    assert all(env.episode_stats[i][key] == 0 for i in range(2)
               for key in ("trade_routes_established", "sea_routes", "overseas_routes"))
    open_route(env, origin, destination)
    stats = env.episode_stats[0]
    assert (stats["trade_routes_established"], stats["sea_routes"], stats["overseas_routes"]) == (1, 1, 1)
    assert env.episode_stats[1]["sea_routes"] == env.episode_stats[1]["overseas_routes"] == 0

    env, origin, destination = pair(harbors=False)
    open_route(env, origin, destination)
    stats = env.episode_stats[0]
    assert (stats["trade_routes_established"], stats["sea_routes"], stats["overseas_routes"]) == (1, 0, 0)


def test_a_sea_route_ends_when_a_city_changes_hands_like_any_route():
    """`end_routes_touching` is unchanged: capturing the destination of a
    sea route removes it and returns the Trader. Breaks if sea routes escape
    the hook."""
    env, origin, destination = pair()
    route = open_route(env, origin, destination)
    destination.set_owner(origin.player)
    assert route not in origin.player.routes
    assert [u for u in origin.player.units if u.unit_type == TRADER_UNIT]


def test_the_same_world_opens_the_same_sea_routes():
    """Two identical worlds run through the economy phase open the same
    routes with the same kind and flag; the default needs no randomness.
    Breaks if route_kind or the default depends on set order or RNG."""
    records = []
    for _ in range(2):
        env, origin, destination = pair()
        stand(env, TRADER_UNIT, 0, origin.coordinates)
        env.economy_phase(env.players[0])
        records.append([(r.origin_city_id, r.destination_city_id, r.kind, r.overseas, r.turns_left)
                        for p in env.players for r in p.routes])
    assert records[0] == records[1] != []


# --- Config and the Oligarchy -----------------------------------------------------------


def test_the_new_trade_keys_are_required_and_validated():
    """`[trade]` without `sea_range` or `overseas_percent` is refused, a
    non-positive range and a negative percent too; 0 percent is allowed
    (the jump off). Breaks if the keys become optional or unchecked."""
    from civulator.district_model import DISTRICTS as district_names

    good = dict(CFG["trade"])
    parse_trade(good, district_names, UNIT_NAMES)
    for key in ("sea_range", "overseas_percent"):
        bad = {k: v for k, v in good.items() if k != key}
        with pytest.raises(ValueError):
            parse_trade(bad, district_names, UNIT_NAMES)
    for key, value in (("sea_range", 0), ("overseas_percent", -1), ("sea_range", True),
                       ("overseas_percent", 1.5)):
        with pytest.raises(ValueError):
            parse_trade({**good, key: value}, district_names, UNIT_NAMES)
    assert parse_trade({**good, "overseas_percent": 0}, district_names, UNIT_NAMES).overseas_percent == 0


def test_oligarchy_strengthens_naval_melee_as_it_does_land_melee():
    """Under Oligarchy a naval melee ship fights with the same bonus the
    government gives a land melee unit (Civ 6: melee, anti-cavalry AND naval
    melee); without a government neither has it. Breaks if the government's
    scope drops `naval_melee`."""
    env = trade_board()
    player = env.players[0]
    ship = stand(env, galley(), 0, (3, 3))
    warrior = stand(env, "Warrior", 0, (5, 5))
    player.government = None
    base_ship, base_warrior = ship.get_combat_strength(), warrior.get_combat_strength()
    player.government = "Oligarchy"
    gain_ship = ship.get_combat_strength() - base_ship
    gain_warrior = warrior.get_combat_strength() - base_warrior
    assert gain_warrior > 0 and gain_ship == gain_warrior
