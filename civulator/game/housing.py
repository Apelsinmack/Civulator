"""The one housing computation (issue #88, spec docs/housing_design.md s1).

Pure engine code: reads only config-derived tables (unit_model, terrain_model)
and the live map. All values are integer tenths of a housing point. Nothing is
cached on the city, so ownership changes need no extra rule.
"""

from ..terrain_model import IMPROVEMENT_HOUSING
from ..unit_model import (
    BUILDING_HOUSING,
    HOUSING_IMPROVEMENT_RADIUS,
    HOUSING_WATER_COASTAL,
    HOUSING_WATER_DRY,
    HOUSING_WATER_FRESH,
)


def _water_housing(game_map, coordinates):
    """Fresh (canonical fresh-water query), else coastal (a water-domain
    neighbour of the centre), else dry."""
    if game_map.is_fresh_water(coordinates):
        return HOUSING_WATER_FRESH
    if any(tile.is_water() for tile in game_map.get_adjacent_tiles(coordinates)):
        return HOUSING_WATER_COASTAL
    return HOUSING_WATER_DRY


def housing(city):
    """Housing a city offers, in integer tenths.

    water + sum of each building's `housing` + sum, over tiles this city owns
    within `[housing] improvement_radius` (centre excluded), of the largest
    `housing` among that tile's improvements.
    """
    game_map = city.player.game_env.map
    total = _water_housing(game_map, city.coordinates)
    total += sum(BUILDING_HOUSING.get(b, 0) for b in city.buildings)
    for pos in game_map.tiles_of_city(city.city_id):
        if pos == tuple(city.coordinates):
            continue
        if game_map.distance_function(city.coordinates, pos) > HOUSING_IMPROVEMENT_RADIUS:
            continue
        tile = game_map.get_tile(pos)
        total += max((IMPROVEMENT_HOUSING.get(i, 0) for i in tile.improvements), default=0)
    return total
