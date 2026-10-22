"""The one computation of a city's per-turn yields (issue #116 P1, spec
docs/progression_design.md §2.1 as corrected by its "v2 fixes").

    city_yield(city, name), name in unit_model.YIELD_COLUMNS

Science, culture, gold and faith are integer TENTHS scaled first by
`loyalty.loyalty_percent(city)` (the city's loyalty band, #116 P7) and THEN by
`(100 + yield_percent) / 100` of the city's amenity band
(`amenities.yield_percent`, v0.9.0 Q2), each step an integer floor in tenths;
food and production are WHOLE points, unscaled here (loyalty and the amenity
percent scale production once each, in that order, at its consumer
`City.calculate_production`, and growth at `City.growth_bucket_gain`; food is
never scaled). The terms:

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
  `per_district`, times its complete wonders when `per_wonder` (v0.9.0 Q8);
- the cross-yield term (v0.9.0 Q8, `_cross_yield_tenths`): the `cross_yield`
  effects in force whose `to` is `name` -- each complete district of the
  effect's `from_district` pays `percent` of its raw adjacency score
  (`adjacency_score`, the owner's rows included, before any
  `adjacency_percent`) as `name`, floored once in tenths, beside its normal
  yield;
- the trade routes of the city's owner that start here (#116 P5,
  `trade.yields_to_origin`): per route, the `[trade]` table entries of its
  destination and the `route_yield` effects in force, in tenths of every
  yield (food and production too, floored with the rest);
- the improvement term (v0.9.0 Q7, `_improvement_tenths`): the
  `improvement_yield` effects in force, per centre or worked tile carrying
  their improvement (and a resource of their `resource_class`, if named), in
  tenths of every yield;
- the regional term (v0.9.0 Q4, `_regional_tenths`): the `regional_yield`
  effects in force whose carrier stands in ANOTHER city of the owner and
  whose district tile lies within the effect's `range` of this city's centre
  (canonical wrap distance, inclusive), the MAX per yield over the carriers in
  reach -- never a sum, never the carrier's own city, never a foreign one.

Every term is summed in tenths; food and production are then floored once
to whole points. Pure engine code: reads config-derived tables and the live
map, caches nothing. No building, district or wonder name appears in this
module (a test greps for every configured one): a new source is a column
on its own config table or an effect, never a term here.
"""

from ..effects import (
    KIND_ADJACENCY_PERCENT,
    KIND_CITY_YIELD,
    KIND_CROSS_YIELD,
    KIND_IMPROVEMENT_YIELD,
    KIND_REGIONAL_YIELD,
    active_effects,
)
from ..terrain_model import resource_class
from ..unit_model import (
    BUILDING_REQUIRES_DISTRICT,
    BUILDING_YIELDS,
    CAPITAL_BUILDING,
    YIELD_BASE,
    YIELD_COLUMNS,
    YIELD_PER_POP,
)
from .amenities import yield_percent as amenity_yield_percent
from .districts import (
    adjacency_score,
    complete_wonders,
    district_spec,
    district_yields,
    specialty_districts,
)
from .loyalty import loyalty_percent
from .trade import yields_to_origin

# Position of food and production in `Tile.yields`.
_TILE_YIELD_INDEX = {"food": 0, "production": 1}


def _effect_yield(city, name, in_force):
    """The `city_yield` effects among `in_force` (the city's active
    effects), in tenths of `name`: each entry's amount, skipped outside the
    city holding the capital building when `capital_only`, multiplied by the
    city's complete specialty districts when `per_district` (#116 P4,
    design §3), by its complete wonders when `per_wonder` (v0.9.0 Q8). The
    one consumer of `city_yield`."""
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
        if effect["per_wonder"]:
            amount *= len(complete_wonders(city))
        total += amount
    return total


def _cross_yield_tenths(city, name, in_force):
    """Tenths of `name` from the `cross_yield` effects among `in_force` whose
    `to` is `name` (v0.9.0 Q8, districts_religion_design §7.3): for each
    complete district of the city of the effect's `from_district`, `percent`
    of its adjacency score -- the raw score (`adjacency_score` with the
    owner's rows, before any `adjacency_percent`), floored once in tenths --
    paid as `name` beside the district's own yield. The one consumer of
    `cross_yield`; food and production reach `calculate_food` /
    `calculate_production` through `city_yield`."""
    entries = [e for e in in_force if e.kind == KIND_CROSS_YIELD and e["to"] == name]
    if not entries:
        return 0
    game_map = city.player.game_env.map
    total = 0
    for district in city.districts:
        if not district.complete:
            continue
        for effect in entries:
            if effect["from_district"] != district.type:
                continue
            score = adjacency_score(district.type, district.coordinates, game_map, city.player)
            total += 10 * score * effect["percent"] // 100
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


def _carrier_tile(effect):
    """The tile a `regional_yield` effect measures from: the tile of the
    complete district its building requires, in the city holding the building
    (a building with no `requires_district` measures from its city's centre).
    None when that district is gone or unfinished -- the carrier then pays
    nothing."""
    holder = effect.source_city
    needed = BUILDING_REQUIRES_DISTRICT.get(effect.source[1])
    if needed is None:
        return tuple(holder.coordinates)
    for district in holder.districts:
        if district.type == needed and district.complete:
            return tuple(district.coordinates)
    return None


def _regional_tenths(city, name, in_force):
    """Tenths of `name` this city is paid by the `regional_yield` effects
    among `in_force` (v0.9.0 Q4, design section 5, Civ 6's Factory rule):
    `in_force` is the owner's, so a carrier is always the owner's own; an
    entry pays when its carrier's city is another city than this one
    and the carrier's district tile lies within its `range` of this city's
    centre (canonical wrap distance, inclusive). A city takes the MAX per
    yield over all carriers in reach, never a sum. The one consumer of
    `regional_yield`."""
    distance = city.player.game_env.map.distance_function
    best = 0
    for effect in in_force:
        if effect.kind != KIND_REGIONAL_YIELD:
            continue
        amount = effect["yields"].get(name, 0)
        holder = effect.source_city
        if amount <= best or holder is None or holder is city:
            continue
        origin = _carrier_tile(effect)
        if origin is not None and distance(origin, city.coordinates) <= effect["range"]:
            best = amount
    return best


def regional_tenths(city, name):
    """`_regional_tenths` for a caller outside `city_yield` that only reports
    it (the round-end `regional_production` stat): same function, the city's
    own active effects."""
    return _regional_tenths(city, name, active_effects(city.player, city))


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


def _improvement_tenths(city, name, in_force):
    """Tenths of `name` from the `improvement_yield` effects among `in_force`
    (v0.9.0 Q7, the yield pantheons): for the city centre and each worked
    tile, every entry whose `improvement` the tile carries -- and, when the
    entry names a `resource_class`, whose resource is of that class -- adds
    its amount of `name`. Read here, never in `Tile.yields` (player-blind and
    epoch-cached; design "v2 fixes" B7). The one consumer of
    `improvement_yield`; food and production reach `calculate_food` /
    `calculate_production` through `city_yield`."""
    entries = [e for e in in_force
               if e.kind == KIND_IMPROVEMENT_YIELD and e["yields"].get(name, 0)]
    if not entries:
        return 0
    game_map = city.player.game_env.map
    total = 0
    for pos in (city.coordinates, *city.worked_tiles):
        tile = game_map.get_tile(pos)
        if tile is None or not tile.improvements:
            continue
        for effect in entries:
            if effect["improvement"] not in tile.improvements:
                continue
            wanted = effect["resource_class"]
            if wanted is not None and (not tile.resource
                                       or resource_class(tile.resource) != wanted):
                continue
            total += effect["yields"][name]
    return total


def _source_tenths(city, name):
    """Every term the six yields share, in tenths: building and complete-
    district columns, district adjacency, effects, the cross-yield term, the
    improvement effects, routes and the regional term."""
    in_force = active_effects(city.player, city)
    columns = sum(BUILDING_YIELDS[name].get(b, 0) for b in city.buildings)
    columns += sum(
        district_spec(d.type).yield_columns[name] for d in city.districts if d.complete
    )
    adjacency = 10 * district_yields(city, _effect_adjacency_percents(in_force)).get(name, 0)
    return (columns + adjacency + _effect_yield(city, name, in_force)
            + _cross_yield_tenths(city, name, in_force)
            + _improvement_tenths(city, name, in_force)
            + _route_yield(city, name) + _regional_tenths(city, name, in_force))


def city_yield(city, name):
    """What `city` yields of `name` this turn: int tenths (scaled by the
    loyalty percent, then by the amenity percent) for science/culture/gold/faith, whole points (unscaled, unfloored at 1)
    for food/production. Raises ValueError for any other name."""
    if name in _TILE_YIELD_INDEX:
        return (10 * _tile_yield(city, name) + _source_tenths(city, name)) // 10
    if name in YIELD_BASE:
        total = (YIELD_BASE[name] + YIELD_PER_POP[name] * city.population
                 + _source_tenths(city, name))
        if name == "gold":  # the one pool yield tiles produce (Tile.gold)
            total += _tile_gold_tenths(city)
        total = total * loyalty_percent(city) // 100
        return total * (100 + amenity_yield_percent(city, city.player.game_env)) // 100
    raise ValueError(f"city_yield: unknown yield {name!r}, expected one of {YIELD_COLUMNS}")
