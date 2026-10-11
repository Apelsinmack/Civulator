"""Districts (issue #86, docs/districts_design.md): the data record, the one
adjacency computation, the one placement check and the cost rule.

Pure: reads the map, the config registry (district_model) and the city;
mutates nothing. The only writers of `Tile.district` / `City.districts` are
`GameEnvironment.place_district` and `GameEnvironment.remove_city`.

No terrain, improvement or district name appears here: every source is
matched through terrain_model.matches or the names the config declares.
"""

from dataclasses import dataclass

from ..district_model import (
    ALLOWED_FEATURES,
    ACCEPTED_YIELDS,
    ANY_DISTRICT,
    CITY_CENTER,
    COST_PROGRESS_FACTOR,
    DISCOUNTED_TYPES,
    DISTRICTS,
    POPULATION_PER_DISTRICT,
    REMOVABLE_FEATURES,
)
from ..terrain_model import matches, resource_class
from . import territory

# Reportable yield names; "none" is not a yield.
YIELD_NAMES = tuple(y for y in ACCEPTED_YIELDS if y != "none")

# The resource class a district tile may carry (design §2). Not a gameplay
# number: the class name Civ 6's rule is written in.
_PLACEABLE_RESOURCE_CLASS = "bonus"


@dataclass(eq=False)
class District:
    """A placed district (design §7). `cost` is locked at placement (§4.3)."""

    type: str
    city_id: int
    coordinates: tuple
    complete: bool = False
    cost: int = 0


# --- Source matching (design §1.2) ------------------------------------------


def _neighbour_matches(source, tile):
    """True if neighbour `tile` counts for a neighbour source."""
    if source.kind == "terrain":
        return matches(source.value, tile.base_terrain, tile.relief, tile.feature,
                       resource=tile.resource)
    if source.kind == "improvement":
        return any(i in source.value for i in tile.improvements)
    if source.kind == "district":
        if source.value == ANY_DISTRICT:
            return tile.city is not None or tile.district is not None
        if tile.city is not None and CITY_CENTER in source.value:
            return True
        return tile.district is not None and tile.district.type in source.value
    raise ValueError(f"not a neighbour source: {source.kind!r}")


def _river_on_tile(game_map, coords, excluded=None):
    """A river runs along an edge between `coords` and a neighbour other
    than `excluded`."""
    return any(
        game_map.has_river_between(coords, n)
        for n in game_map.get_adjacent_coords(coords)
        if n != excluded
    )


def _source_count(source, coords, game_map, centre=None):
    """How many times `source` holds around `coords`: a neighbour count, or
    0/1 for a tile test."""
    if source.kind == "river_on_tile":
        return int(_river_on_tile(game_map, coords))
    if source.kind == "river_edge_not_shared_with_center":
        return int(_river_on_tile(game_map, coords, excluded=centre))
    return sum(
        1 for tile in game_map.get_adjacent_tiles(coords) if _neighbour_matches(source, tile)
    )


# --- Adjacency (design §1.1) --------------------------------------------------


def adjacency_score(district_type, coords, game_map):
    """Integer adjacency score of `district_type` at `coords` on the live map.

    Each row is floored on its own, then summed: floor(count / per) * amount.
    Neighbouring districts count whether placed or complete, and city centres
    count as districts (Civ 6). Never cached.
    """
    spec = DISTRICTS[district_type]
    return sum(
        (_source_count(row.source, coords, game_map) // row.per) * row.amount
        for row in spec.adjacency
    )


# --- Yields (design §5) --------------------------------------------------------


def district_yields(city):
    """Mapping yield name -> summed adjacency score over the city's COMPLETE
    districts, for every reportable yield name (0 when none). Live, never
    cached; reported only -- nothing consumes it yet (design §5)."""
    game_map = city.player.game_env.map
    result = dict.fromkeys(YIELD_NAMES, 0)
    for district in city.districts:
        spec = DISTRICTS[district.type]
        if district.complete and spec.adjacency_yield in result:
            result[spec.adjacency_yield] += adjacency_score(
                district.type, district.coordinates, game_map)
    return result


# --- Placement (design §2 + v3 fixes) -----------------------------------------


def _district_slots(city):
    """Population slots for `counts_toward_limit` districts."""
    return 1 + (city.population - 1) // POPULATION_PER_DISTRICT


def can_place_district(city, district_type, coords):
    """The only placement check. True iff `city` may place `district_type` on
    `coords` now. Pure."""
    spec = DISTRICTS.get(district_type)
    if spec is None or city.city_id is None:
        return False
    game_env = city.player.game_env
    game_map = game_env.map
    tile = game_map.get_tile(coords)
    if tile is None:
        return False
    coords = tile.coordinates

    # Owned by this city, within the work radius.
    if game_map.owner_id_at(coords) != city.city_id:
        return False
    if game_map.distance_function(coords, city.coordinates) > territory.WORK_RADIUS:
        return False
    # Not a centre, not already a district, not next to another city's centre.
    if tile.city is not None or tile.district is not None:
        return False
    neighbours = game_map.get_adjacent_coords(coords)
    for n in neighbours:
        other = game_map.get_tile(n)
        if other is not None and other.city is not None and other.city is not city:
            return False
    # No foreign unit on the tile (v3 fixes); own units are fine.
    if any(u.player is not city.player for u in tile.units):
        return False
    # Terrain of the tile itself.
    if tile.impassable:
        return False
    if spec.on is None:
        if tile.domain != "land":
            return False
    elif not matches(spec.on, tile.base_terrain, tile.relief, tile.feature,
                     resource=tile.resource):
        return False
    if tile.feature is not None and tile.feature not in REMOVABLE_FEATURES | ALLOWED_FEATURES:
        return False
    if tile.resource is not None and resource_class(tile.resource) != _PLACEABLE_RESOURCE_CLASS:
        return False

    # Limits: placed districts, complete or not (v3 fixes).
    if sum(1 for d in city.districts if d.type == district_type) >= spec.max_per_city:
        return False
    if spec.max_per_player is not None:
        owned = sum(
            1 for c in city.player.cities for d in c.districts if d.type == district_type
        )
        if owned >= spec.max_per_player:
            return False
    if spec.counts_toward_limit:
        used = sum(1 for d in city.districts if DISTRICTS[d.type].counts_toward_limit)
        if used >= _district_slots(city):
            return False

    # The district's own rules.
    if spec.adjacent_to_city_center is not None:
        if (tuple(city.coordinates) in neighbours) != spec.adjacent_to_city_center:
            return False
    if spec.requires_adjacent and not any(
        _source_count(source, coords, game_map, centre=tuple(city.coordinates)) > 0
        for source in spec.requires_adjacent
    ):
        return False
    return True


# --- Cost (design §4 + v3 fixes: one integer rule) -----------------------------


def game_progress(player):
    """The player's progress through the tech/civic tree as a fraction
    (num, den). (0, 1) until a tech tree exists (#90): ACCEPTED GAP."""
    return (0, 1)


def _completed_discounted(player):
    return [
        d.type for c in player.cities for d in c.districts
        if d.complete and DISTRICTS[d.type].cost_model == "discounted"
    ]


def district_cost(player, district_type):
    """Integer production cost of `district_type` for `player` now.

    escalated = base * (den + factor * num) // den; "fixed" never scales.
    A "discounted" type costs discount_percent less iff B >= A and
    count_T * A < B, where A = the configured discounted types, B = the
    player's completed discounted districts (captured ones included) and
    count_T those of type T.
    """
    spec = DISTRICTS[district_type]
    base = spec.production_cost
    if spec.cost_model == "fixed":
        return base
    num, den = game_progress(player)
    escalated = base * (den + COST_PROGRESS_FACTOR * num) // den
    if spec.cost_model == "discounted":
        completed = _completed_discounted(player)
        a = len(DISCOUNTED_TYPES)
        b = len(completed)
        count_t = completed.count(district_type)
        if b >= a and count_t * a < b:
            return escalated * (100 - spec.discount_percent) // 100
    return escalated
