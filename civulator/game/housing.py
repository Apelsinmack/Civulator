"""The one housing computation (issue #88, spec docs/housing_design.md s1).

Pure engine code: reads only config-derived tables (unit_model, terrain_model),
the effects in force (`effects.active_effects`, #116 P4) and the live map. All
values are integer tenths of a housing point. Nothing is cached on the city,
so ownership changes need no extra rule.
"""

from ..effects import (
    KIND_HOUSING_IF_DISTRICTS,
    KIND_HOUSING_WITH_BUILDING,
    active_effects,
)
from ..terrain_model import IMPROVEMENT_HOUSING
from ..unit_model import (
    BUILDING_HOUSING,
    HOUSING_IMPROVEMENT_RADIUS,
    HOUSING_WATER_COASTAL,
    HOUSING_WATER_DRY,
    HOUSING_WATER_FRESH,
)
from .districts import district_spec, specialty_districts


def _water_housing(game_map, coordinates):
    """Fresh (canonical fresh-water query), else coastal (a water-domain
    neighbour of the centre), else dry."""
    if game_map.is_fresh_water(coordinates):
        return HOUSING_WATER_FRESH
    if any(tile.is_water() for tile in game_map.get_adjacent_tiles(coordinates)):
        return HOUSING_WATER_COASTAL
    return HOUSING_WATER_DRY


def _district_water(city, water):
    """Apply every complete district's declared water adjustment (design §6):
    max(water_housing_min, water + water_housing_boost). Fields come from
    config; no district name appears here."""
    for district in city.districts:
        spec = district_spec(district.type)
        if district.complete and spec.water_housing_min is not None:
            water = max(spec.water_housing_min, water + (spec.water_housing_boost or 0))
    return water


def _effect_housing(city):
    """The housing effects in force for the city, in tenths (#116 P4, design
    §5.2-§5.3): every `housing_if_districts` entry whose `min_districts` the
    city's complete specialty districts reach, and every
    `housing_with_building` entry whose building the city holds. The one
    consumer of both kinds."""
    total = 0
    specialty = None
    for effect in active_effects(city.player, city):
        if effect.kind == KIND_HOUSING_IF_DISTRICTS:
            if specialty is None:
                specialty = len(specialty_districts(city))
            if specialty >= effect["min_districts"]:
                total += effect["amount"]
        elif effect.kind == KIND_HOUSING_WITH_BUILDING:
            if effect["building"] in city.buildings:
                total += effect["amount"]
    return total


def housing(city):
    """Housing a city offers, in integer tenths.

    water (adjusted by complete districts) + sum of each complete district's
    flat `housing` + sum of each building's `housing` + sum, over tiles this city owns
    within `[housing] improvement_radius` (centre excluded), of the largest
    `housing` among that tile's improvements + the housing effects in force
    (`_effect_housing`).
    """
    game_map = city.player.game_env.map
    total = _district_water(city, _water_housing(game_map, city.coordinates))
    total += sum(district_spec(d.type).housing for d in city.districts if d.complete)
    total += sum(BUILDING_HOUSING.get(b, 0) for b in city.buildings)
    for pos in game_map.tiles_of_city(city.city_id):
        if pos == tuple(city.coordinates):
            continue
        if game_map.distance_function(city.coordinates, pos) > HOUSING_IMPROVEMENT_RADIUS:
            continue
        tile = game_map.get_tile(pos)
        total += max((IMPROVEMENT_HOUSING.get(i, 0) for i in tile.improvements), default=0)
    return total + _effect_housing(city)
