"""The one computation of a city's per-turn yields (issue #116 P1, spec
docs/progression_design.md §2.1 as corrected by its "v2 fixes").

    city_yield(city, name), name in unit_model.YIELD_COLUMNS

Science, culture, gold and faith are integer TENTHS scaled by
`loyalty.loyalty_percent(city)` (the city's loyalty band, #116 P7); food and
production are WHOLE points, unscaled (loyalty scales production once, at its
consumer `City.calculate_production`, and growth at `City.growth_bucket_gain`;
food is never scaled). The terms:

- science/culture/gold/faith: `[<name>] base + per_pop * population`;
  food/production: the city centre plus the worked tiles (`Tile.yields`,
  which includes their improvements' food and production since #116 P2);
- gold also: the improvement gold of the centre and the worked tiles
  (`Tile.gold`, #116 P2) -- the one place tile gold is summed;
- the `<name>` column of each of the city's buildings (`[buildings.*]`);
- the `<name>` column of each of its complete districts (`[districts.*]`);
- `10 * district_yields(city, percent_by_district)[name]`, the adjacency of
  its complete districts (the one conversion of adjacency into yields), each
  district's score raised by the summed `adjacency_percent` effects in force
  for its type (#116 P4);
- the `city_yield` effects in force for the city (#116 P4): each entry's
  amount of `name`, only in the city holding `[city] capital_building` when
  `capital_only`, times the city's complete specialty districts when
  `per_district`;
- the trade routes of the city's owner that start here (#116 P5,
  `trade.yields_to_origin`): per route, the `[trade]` table entries of its
  destination and the `route_yield` effects in force, in tenths of every
  yield (food and production too, floored with the rest).

Every term is summed in tenths; food and production are then floored once
to whole points. Pure engine code: reads config-derived tables and the live
map, caches nothing. No building, district or wonder name appears in this
module (a test greps for every configured one): a new source is a column
on its own config table or an effect, never a term here.
"""

from ..effects import KIND_ADJACENCY_PERCENT, KIND_CITY_YIELD, active_effects
from ..unit_model import (
    BUILDING_YIELDS,
    CAPITAL_BUILDING,
    YIELD_BASE,
    YIELD_COLUMNS,
    YIELD_PER_POP,
)
from .districts import district_spec, district_yields, specialty_districts
from .loyalty import loyalty_percent
from .trade import yields_to_origin

# Position of food and production in `Tile.yields`.
_TILE_YIELD_INDEX = {"food": 0, "production": 1}


def _effect_yield(city, name, in_force):
    """The `city_yield` effects among `in_force` (the city's active
    effects), in tenths of `name`: each entry's amount, skipped outside the
    city holding the capital building when `capital_only`, multiplied by the
    city's complete specialty districts when `per_district` (#116 P4,
    design §3). The one consumer of `city_yield`."""
    total = 0
    for effect in in_force:
        if effect.kind != KIND_CITY_YIELD:
            continue
        amount = effect["yields"].get(name, 0)
        if not amount:
            continue
        if effect["capital_only"] and CAPITAL_BUILDING not in city.buildings:
            continue
        if effect["per_district"]:
            amount *= len(specialty_districts(city))
        total += amount
    return total


def _effect_adjacency_percents(in_force):
    """District type -> the summed `adjacency_percent` of the entries among
    `in_force`, for `district_yields` to apply once per district (v2 fixes:
    summed, then applied with one floor). The one consumer of
    `adjacency_percent`."""
    percents = {}
    for effect in in_force:
        if effect.kind == KIND_ADJACENCY_PERCENT:
            district = effect["district"]
            percents[district] = percents.get(district, 0) + effect["percent"]
    return percents


def _route_yield(city, name):
    """Tenths of `name` from the trade routes whose origin is this city
    (#116 P5, design §7.4): `trade.yields_to_origin`, which sums each route's
    destination table entries and the `route_yield` effects in force (their
    one consumer, `trade.pair_yields`). Only the owner's own routes start at
    its city, so only the origin's owner gains."""
    return yields_to_origin(city, name)


def _tile_yield(city, name):
    """Whole points of food or production from the centre plus the worked
    tiles, summed as `calculate_food` / `calculate_production` did in v0.7."""
    game_map = city.player.game_env.map
    index = _TILE_YIELD_INDEX[name]
    total = game_map.get_tile(city.coordinates).yields[index]
    for pos in city.worked_tiles:
        tile = game_map.get_tile(pos)
        if tile:
            total += tile.yields[index]
    return total


def _tile_gold_tenths(city):
    """Tenths of gold from the improvements on the centre and the worked
    tiles (`Tile.gold`, whole points)."""
    game_map = city.player.game_env.map
    total = game_map.get_tile(city.coordinates).gold
    for pos in city.worked_tiles:
        tile = game_map.get_tile(pos)
        if tile:
            total += tile.gold
    return 10 * total


def _source_tenths(city, name):
    """Every term the six yields share, in tenths: building and complete-
    district columns, district adjacency, effects and routes."""
    in_force = active_effects(city.player, city)
    columns = sum(BUILDING_YIELDS[name].get(b, 0) for b in city.buildings)
    columns += sum(
        district_spec(d.type).yield_columns[name] for d in city.districts if d.complete
    )
    adjacency = 10 * district_yields(city, _effect_adjacency_percents(in_force)).get(name, 0)
    return (columns + adjacency + _effect_yield(city, name, in_force)
            + _route_yield(city, name))


def city_yield(city, name):
    """What `city` yields of `name` this turn: int tenths (loyalty-scaled)
    for science/culture/gold/faith, whole points (unscaled, unfloored at 1)
    for food/production. Raises ValueError for any other name."""
    if name in _TILE_YIELD_INDEX:
        return (10 * _tile_yield(city, name) + _source_tenths(city, name)) // 10
    if name in YIELD_BASE:
        total = (YIELD_BASE[name] + YIELD_PER_POP[name] * city.population
                 + _source_tenths(city, name))
        if name == "gold":  # the one pool yield tiles produce (Tile.gold)
            total += _tile_gold_tenths(city)
        return total * loyalty_percent(city) // 100
    raise ValueError(f"city_yield: unknown yield {name!r}, expected one of {YIELD_COLUMNS}")
