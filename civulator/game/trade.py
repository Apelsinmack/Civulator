"""Trade routes (issue #116 P5, docs/progression_design.md §7.4, §13 and "v2 fixes").

The only interpreter of `[trade]` in config.toml and the only route state:

- a `TradeRoute(origin_city_id, destination_city_id, player_index,
  turns_left)` lives in its owner's `Player.routes`; it is created only by
  `GameEnvironment.establish_trade_route` (which consumes a Trader standing on
  the origin's centre), counted down and ended by `expire_routes` in the
  owner's economy phase, and ended early by `end_routes_touching` when either
  city changes hands (`City.set_owner`) or is removed
  (`GameEnvironment.remove_city`);
- `route_capacity(player)` -- how many routes the player may run: the
  `trade_route_capacity` effects in force, a building's counted once per city
  (Civ 6: a city with a Market and a Lighthouse adds 1, not 2). The Foreign
  Trade civic's effect is the base capacity of 1;
- `route_yields(route, env)` -- what a route yields its ORIGIN per turn, in
  int tenths per yield (the unit `city_yield` sums in): the `[trade.domestic]`
  or `[trade.international]` entry of the destination's centre and of each of
  its complete specialty districts (`specialty_districts`, the one
  definition), plus the `route_yield` effects in force (`international_only`
  honoured). The route term of `city_yield` reads it; the destination's
  owner gets nothing (Civ 6);
- `eligible_destinations(trader, env)` -- the cities a Trader on an own city
  centre may open a route to: any other city within `[trade] range` hexes
  (canonical wrap distance) with no route of its player between the pair in
  either direction, in city-id order.

The unit that makes routes is named once, as `[trade] unit` (like `[city]
capital_building`), so no code here names it. A route has no path on the
map, no plunder and no round-trip arithmetic (design §7.4).

Imports no `civulator.game` module but `districts` (the registry accessor);
cities and the environment arrive as arguments.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import NamedTuple

from ..config import CFG
from ..district_model import CITY_CENTER, DISTRICTS as _CONFIGURED_DISTRICTS
from ..effects import (
    KIND_ROUTE_YIELD,
    KIND_TRADE_ROUTE_CAPACITY,
    SCOPE_CITY,
    SOURCE_BUILDING,
    active_effects,
)
from ..unit_model import UNIT_NAMES, YIELD_COLUMNS
from .districts import specialty_districts

DOMESTIC = "domestic"
INTERNATIONAL = "international"
ROUTE_KINDS = (DOMESTIC, INTERNATIONAL)
_TRADE_KEYS = frozenset({"unit", "range", "duration_turns", *ROUTE_KINDS})


class TradeConfig(NamedTuple):
    """The parsed `[trade]` table. `tables[kind][name]` maps a yield to whole
    points, for `kind` in ROUTE_KINDS and `name` a district or CITY_CENTER."""

    unit: str
    route_range: int
    duration_turns: int
    tables: MappingProxyType


def _positive_int(value, where):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{where} must be a positive whole number, got {value!r}")
    return value


def _route_table(table, where, district_names):
    """One `[trade.<kind>]` table -> name -> {yield: whole points}. Every name
    is a district of the registry or CITY_CENTER; every entry a non-empty
    table of YIELD_COLUMNS with whole, non-negative values."""
    if not isinstance(table, dict):
        raise ValueError(f"{where} must be a table of districts")
    out = {}
    for name, entry in table.items():
        if name != CITY_CENTER and name not in district_names:
            raise ValueError(f"{where}: {name!r} is neither a district nor {CITY_CENTER!r}")
        at = f"{where}.{name}"
        if not isinstance(entry, dict) or not entry:
            raise ValueError(f"{at} must be a non-empty table of {YIELD_COLUMNS}")
        unknown = set(entry) - set(YIELD_COLUMNS)
        if unknown:
            raise ValueError(f"{at}: unknown yield(s) {sorted(unknown)}")
        for name_, value in entry.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{at} {name_} must be a whole number >= 0, got {value!r}")
        out[name] = MappingProxyType({y: entry[y] for y in YIELD_COLUMNS if y in entry})
    return MappingProxyType(out)


def parse_trade(cfg, district_names, unit_names):
    """`[trade]` -> TradeConfig. Exactly the keys `unit` (a unit type),
    `range`, `duration_turns` (positive whole numbers), `domestic` and
    `international` (see `_route_table`); anything else raises."""
    if not isinstance(cfg, dict) or set(cfg) != _TRADE_KEYS:
        got = sorted(cfg) if isinstance(cfg, dict) else cfg
        raise ValueError(f"[trade] must have exactly the keys {sorted(_TRADE_KEYS)}, got {got}")
    unit = cfg["unit"]
    if unit not in unit_names:
        raise ValueError(f"[trade] unit {unit!r} is not a unit type")
    return TradeConfig(
        unit=unit,
        route_range=_positive_int(cfg["range"], "[trade] range"),
        duration_turns=_positive_int(cfg["duration_turns"], "[trade] duration_turns"),
        tables=MappingProxyType({
            kind: _route_table(cfg[kind], f"[trade.{kind}]", district_names)
            for kind in ROUTE_KINDS
        }),
    )


_TRADE = parse_trade(CFG["trade"], _CONFIGURED_DISTRICTS, UNIT_NAMES)
TRADER_UNIT = _TRADE.unit            # the unit type that makes a route
ROUTE_RANGE = _TRADE.route_range     # hexes, canonical wrap distance
DURATION_TURNS = _TRADE.duration_turns
ROUTE_TABLES = _TRADE.tables


@dataclass
class TradeRoute:
    """One route of player `player_index`, from its city `origin_city_id` to
    the city `destination_city_id`, for `turns_left` more of its owner's
    economy phases."""

    origin_city_id: int
    destination_city_id: int
    player_index: int
    turns_left: int


# --- Capacity --------------------------------------------------------------------


def route_capacity(player):
    """How many routes `player` may run at once: the summed `amount` of the
    `trade_route_capacity` effects in force, except that the building-sourced
    ones count once per city -- the largest of them in that city (Civ 6: a
    Market and a Lighthouse in one city add 1). The one consumer of the kind;
    the Foreign Trade civic's effect is the base 1, a wonder's (#116 P6)
    counts like a civic's."""
    total = 0
    for effect in active_effects(player, kind=KIND_TRADE_ROUTE_CAPACITY):
        if effect.source[0] != SOURCE_BUILDING:
            total += effect["amount"]
    for city in player.cities:
        building_amounts = []
        for effect in active_effects(player, city, KIND_TRADE_ROUTE_CAPACITY):
            if effect.source[0] == SOURCE_BUILDING:
                if effect.source[1] in city.buildings:
                    building_amounts.append(effect["amount"])
            elif effect.scope == SCOPE_CITY:
                total += effect["amount"]
        total += max(building_amounts, default=0)
    return total


def traders(player):
    """`player`'s units of the trade unit type, in `player.units` order."""
    return [unit for unit in player.units if unit.unit_type == TRADER_UNIT]


def trader_slot_free(player):
    """Whether one more Trader could ever be sent: capacity exceeds the
    routes running plus the Traders already standing (design §7.4, the
    Trader's build-mask rule). `City.can_produce_unit` applies it, so the
    build mask and `produce_unit` read the same predicate."""
    return route_capacity(player) > len(player.routes) + len(traders(player))


# --- Destinations and yields -------------------------------------------------------------


def origin_city(trader, env):
    """The city of `trader`'s owner whose centre it stands on, or None."""
    tile = env.map.get_tile(trader.coordinates)
    city = getattr(tile, "city", None)
    if city is None or city.player is not trader.player:
        return None
    return city


def eligible_destinations(trader, env):
    """The cities `trader` could open a route to from where it stands: none
    unless it is on one of its owner's city centres (the origin); otherwise
    every other city within ROUTE_RANGE of the origin by
    `distance_function`, with no route of this player between the pair in
    either direction, in city-id order. Capacity is not this function's
    question."""
    origin = origin_city(trader, env)
    if origin is None:
        return []
    linked = {frozenset((route.origin_city_id, route.destination_city_id))
              for route in trader.player.routes}
    out = []
    for city_id in sorted(env.city_by_id):
        city = env.city_by_id[city_id]
        if city is origin:
            continue
        if env.distance_function(origin.coordinates, city.coordinates) > ROUTE_RANGE:
            continue
        if frozenset((origin.city_id, city_id)) in linked:
            continue
        out.append(city)
    return out


def pair_yields(player, origin, destination):
    """Int tenths per yield (every YIELD_COLUMNS name) a route of `player`
    from its city `origin` to `destination` yields the origin per turn: the
    domestic table when `player` owns the destination, else the international
    one, over the destination's centre and its complete specialty districts
    (a district absent from the table adds nothing), plus each `route_yield`
    effect in force for the origin (an `international_only` one on an
    international route only). The one consumer of `route_yield`."""
    international = destination.player is not player
    table = ROUTE_TABLES[INTERNATIONAL if international else DOMESTIC]
    totals = dict.fromkeys(YIELD_COLUMNS, 0)
    for name in [CITY_CENTER, *(d.type for d in specialty_districts(destination))]:
        for yield_name, amount in table.get(name, {}).items():
            totals[yield_name] += 10 * amount
    for effect in active_effects(player, origin, KIND_ROUTE_YIELD):
        if effect["international_only"] and not international:
            continue
        for yield_name, tenths in effect["yields"].items():
            totals[yield_name] += tenths
    return totals


def route_yields(route, env):
    """What `route` yields its origin per turn (`pair_yields`), live; all
    zero if either city no longer stands (a route never outlives its cities:
    `end_routes_touching`)."""
    origin = env.city_by_id.get(route.origin_city_id)
    destination = env.city_by_id.get(route.destination_city_id)
    if origin is None or destination is None:
        return dict.fromkeys(YIELD_COLUMNS, 0)
    return pair_yields(env.players[route.player_index], origin, destination)


def yields_to_origin(city, name):
    """Int tenths of `name` that the routes of `city`'s owner starting at
    `city` yield it this turn: the route term of `city_yield`."""
    player = city.player
    routes = [r for r in player.routes if r.origin_city_id == city.city_id]
    if not routes:
        return 0
    env = player.game_env
    return sum(route_yields(route, env)[name] for route in routes)


# --- Ending routes ---------------------------------------------------------------------


def _return_trader(route, env):
    """A Trader back at the route's origin when its owner still holds it
    (placed, or queued if it cannot be: `City.place_or_queue_unit`)."""
    origin = env.city_by_id.get(route.origin_city_id)
    if origin is not None and origin.player is env.players[route.player_index]:
        origin.place_or_queue_unit(TRADER_UNIT, env)


def expire_routes(player, env):
    """One turn of `player`'s routes (economy phase, after the government and
    loadout defaults): each loses a turn; a route at 0 ends and its Trader
    reappears at the origin. Returns the routes that ended."""
    ended = []
    for route in list(player.routes):
        route.turns_left -= 1
        if route.turns_left <= 0:
            player.routes.remove(route)
            _return_trader(route, env)
            ended.append(route)
    return ended


def end_routes_touching(env, city_id):
    """End every route, of any player, whose origin or destination is city
    `city_id` (called by `City.set_owner` after the change of hands, and by
    `GameEnvironment.remove_city`). The player who still holds a route's
    origin gets its Trader back there; a route whose origin was lost is
    simply removed (design "v2 fixes", flips and captures)."""
    for player in env.players:
        for route in list(player.routes):
            if city_id in (route.origin_city_id, route.destination_city_id):
                player.routes.remove(route)
                _return_trader(route, env)
