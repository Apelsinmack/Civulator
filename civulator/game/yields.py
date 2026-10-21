"""The one computation of a city's per-turn yields (issue #116 P1, spec
docs/progression_design.md §2.1 as corrected by its "v2 fixes").

    city_yield(city, name), name in unit_model.YIELD_COLUMNS

Science, culture, gold and faith are integer TENTHS scaled by
`loyalty_percent(city)`; food and production are WHOLE points, unscaled
(loyalty scales production at its consumer, P7). The terms:

- science/culture/gold/faith: `[<name>] base + per_pop * population`;
  food/production: the city centre plus the worked tiles (`Tile.yields`);
- the `<name>` column of each of the city's buildings (`[buildings.*]`);
- the `<name>` column of each of its complete districts (`[districts.*]`);
- `10 * district_yields(city, percent_by_district)[name]`, the adjacency of
  its complete districts (the one conversion of adjacency into yields);
- flat effects (stub until P4) and trade routes to this city (stub until P5).

Every term is summed in tenths; food and production are then floored once
to whole points. Pure engine code: reads config-derived tables and the live
map, caches nothing. No building, district or wonder name appears in this
module (a test greps for every configured one): a new source is a column
on its own config table or an effect, never a term here.
"""

from ..unit_model import BUILDING_YIELDS, YIELD_BASE, YIELD_COLUMNS, YIELD_PER_POP
from .districts import district_spec, district_yields

# Position of food and production in `Tile.yields`.
_TILE_YIELD_INDEX = {"food": 0, "production": 1}


def loyalty_percent(city):
    """Percent of its science, culture, gold and faith the city keeps under
    its loyalty band. STUB: 100 until loyalty exists (#116 P7, design §8.4,
    which moves it to game/loyalty.py and also scales production and growth
    at their consumers)."""
    return 100


def _effect_yield(city, name):
    """Flat `city_yield` effects in force for the city, in tenths. STUB: 0
    until the effects interpreter exists (#116 P4, design §3)."""
    return 0


def _effect_adjacency_percents(city):
    """Summed `adjacency_percent` effects per district type, for
    `district_yields`. STUB: none until the effects interpreter exists
    (#116 P4, design §3 and v2 fixes)."""
    return None


def _route_yield(city, name):
    """Yields of trade routes whose origin is this city, in tenths. STUB: 0
    until trade routes exist (#116 P5, design §7.4)."""
    return 0


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


def _source_tenths(city, name):
    """Every term the six yields share, in tenths: building and complete-
    district columns, district adjacency, effects and routes."""
    columns = sum(BUILDING_YIELDS[name].get(b, 0) for b in city.buildings)
    columns += sum(
        district_spec(d.type).yield_columns[name] for d in city.districts if d.complete
    )
    adjacency = 10 * district_yields(city, _effect_adjacency_percents(city)).get(name, 0)
    return columns + adjacency + _effect_yield(city, name) + _route_yield(city, name)


def city_yield(city, name):
    """What `city` yields of `name` this turn: int tenths (loyalty-scaled)
    for science/culture/gold/faith, whole points (unscaled, unfloored at 1)
    for food/production. Raises ValueError for any other name."""
    if name in _TILE_YIELD_INDEX:
        return (10 * _tile_yield(city, name) + _source_tenths(city, name)) // 10
    if name in YIELD_BASE:
        total = (YIELD_BASE[name] + YIELD_PER_POP[name] * city.population
                 + _source_tenths(city, name))
        return total * loyalty_percent(city) // 100
    raise ValueError(f"city_yield: unknown yield {name!r}, expected one of {YIELD_COLUMNS}")
