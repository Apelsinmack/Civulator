"""Resource access (v0.9.0 Q1, docs/districts_religion_design.md §2.2, §2.3 and
"v2 fixes" B2): the one answer to "does this player have Iron".

- `player_has_access(player, resource, env)` -- the player owns (through
  `Map.owner_city`) a tile carrying `resource` that holds one of the
  resource's `improved_by` improvements (`terrain_model.RESOURCE_IMPROVED_BY`),
  or a district or wonder (`tile.district`, complete or not: R2 -- a district
  placed on a strategic resource grants it), or is a city centre. Boolean,
  never a stockpile (Civ 5's model). "Revealed" never enters: the encoder, not
  the engine, decides what a player knows.
- `world_has_class(game_map, cls)` -- whether any tile of the world carries a
  resource of class `cls`. `availability.player_can_build` honours a unit's
  `requires_resource` only on a world that has strategic resources, so the
  basic generator's boards and the matchup board keep today's roster
  ("v2 fixes", non-blocking list).
- `accessible_resources(player, env, cls=None)` -- every resource the player
  has access to, in config order (the stats read it).

Both read one index of the resource tiles, rebuilt per `(map_uid,
terrain_epoch)` -- resources move only through `Tile.set_layers`, which bumps
the epoch, and improvements bump it too. Ownership, districts and centres
are read live. Pure: no RNG, no mutation of game state; tiles are visited
in row-major order, names in config order -- never a set.
"""

from ..terrain_model import RESOURCE_IMPROVED_BY, RESOURCE_TABLE, resource_class

NEUTRAL = -1


def _resource_index(game_map):
    """{resource name: [(row, col), ...] row-major} over every tile carrying a
    resource, cached on the Map per (map_uid, terrain_epoch)."""
    key = (game_map.map_uid, game_map.terrain_epoch)
    cached = getattr(game_map, "_resource_index_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1]
    index = {}
    for row in range(game_map.n):
        for col in range(game_map.m):
            tile = game_map.tiles[row, col]
            if tile is not None and tile.resource is not None:
                index.setdefault(tile.resource, []).append((row, col))
    game_map._resource_index_cache = (key, index)
    return index


def world_has_class(game_map, cls):
    """Whether any tile of `game_map` carries a resource of class `cls`.
    False for no map. Cached with the resource index on (map_uid,
    terrain_epoch)."""
    if game_map is None:
        return False
    return any(resource_class(name) == cls for name in _resource_index(game_map))


def _tile_grants(tile, resource):
    """The tile clause of access: the tile carries `resource` and is a
    centre, holds a district or wonder, or holds an `improved_by`
    improvement of it."""
    if tile is None or tile.resource != resource:
        return False
    if tile.city is not None or tile.district is not None:
        return True
    return any(name in RESOURCE_IMPROVED_BY.get(resource, ()) for name in tile.improvements)


def player_has_access(player, resource, env):
    """True iff `player` owns a tile carrying `resource` that is improved by
    one of its `improved_by` improvements, holds a district or wonder, or is
    a city centre (design §2.2, B2). An unknown resource or a missing map
    gives no access."""
    game_map = getattr(env, "map", None)
    if game_map is None or resource not in RESOURCE_TABLE:
        return False
    own_ids = {city.city_id for city in player.cities}
    if not own_ids:
        return False
    for coords in _resource_index(game_map).get(resource, ()):
        if game_map.owner_id_at(coords) not in own_ids:
            continue
        if _tile_grants(game_map.get_tile(coords), resource):
            return True
    return False


def accessible_resources(player, env, cls=None):
    """Every resource (of class `cls`, or of any class) `player` has access
    to, in config order."""
    return tuple(
        name for name in RESOURCE_TABLE
        if (cls is None or resource_class(name) == cls)
        and player_has_access(player, name, env)
    )
