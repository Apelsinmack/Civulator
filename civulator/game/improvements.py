"""Where a Worker can improve a tile, and what it would build there (issue
#116 P8, docs/progression_design.md §13 and "v2 fixes": Improvement yields,
Worker default, Load order and config ownership).

The one place that answers two questions about a player's land, for the two
things that need the answer:

- `best_improvement(player, coordinates, env)` -- what a Worker standing on
  this tile builds: of the improvements `GameEnvironment.can_player_build_
  improvement_at` allows, the one with the largest `improvement_gain`, ties
  by config order. Read by `defaults.default_workers`.
- `worker_targets(player, env)` -- the owned tiles a Worker could be sent
  to. `defaults.default_workers` picks the nearest; `worker_has_work(player)`
  asks whether there is any, and is the rule `City.can_produce_unit` applies
  to a Worker -- so the build mask, `produce_unit` and `purchase` read one
  predicate, and a Worker that could never be given a job is never offered
  (the mask invariant, CLAUDE.md, #51).

An improvement's numbers and its placement come only through
`terrain_model` (`IMPROVEMENT_YIELDS`, `IMPROVEMENT_HOUSING`,
`IMPROVEMENT_ORDER`); who may build it where is only
`GameEnvironment.can_player_build_improvement_at` (ownership, research, the
tile predicate). This module adds exactly one rule of its own, and says so:

**One improvement per tile.** A tile that already holds an improvement is
never improved again, by the default or by the offer of a Worker. The tile
predicate refuses only a repeat of the SAME improvement (housing design: "our
engine lets several stack" -- Civ 6 allows one), so without this rule a
Worker would stand on one Plains tile and add a Farm, then a Plantation, then
a Camp, a Pasture and a Quarry. The rule is this module's, not the tile
predicate's: `can_build_improvement_at`, the painter and `build_improvement`
keep the engine's permissive tile rule until Erik decides otherwise, and a
future agent action to build improvements (#99) must read this module for the
same reason.

Pure: reads live state, mutates nothing. Imports no `defaults` (the defaults
are called only from `GameEnvironment`; this module is what `City` may call).
"""

from .. import terrain_model
from .unit import WorkerUnit


def improvement_gain(name):
    """The ranking key of improvement `name`, larger is better: the whole
    points it adds to a tile (food + production + gold, each counted alike,
    design "v2 fixes": Improvement yields), then its housing in tenths."""
    columns = terrain_model.IMPROVEMENT_YIELDS[name]
    points = sum(columns[column] for column in terrain_model.IMPROVEMENT_YIELD_COLUMNS)
    return points, terrain_model.IMPROVEMENT_HOUSING.get(name, 0)


def _buildable(player, tile, env):
    """The improvement names `player` may build on `tile` now, lazily, in
    config order; none while the tile already holds one (one per tile)."""
    if tile.improvements:
        return
    for name in terrain_model.IMPROVEMENT_ORDER:
        if env.can_player_build_improvement_at(player, tile.coordinates, name):
            yield name


def buildable_here(player, coordinates, env):
    """Every improvement `player` may build on this tile now, in config order
    (`[]` when the tile is off the board, not the player's, already improved,
    or nothing is available)."""
    tile = env.map.get_tile(coordinates)
    return [] if tile is None else list(_buildable(player, tile, env))


def best_improvement(player, coordinates, env):
    """The improvement a Worker of `player` builds on this tile, or None when
    it may build none: the largest `improvement_gain`, and among equals the
    first in config order (the order `buildable_here` returns)."""
    best = None
    for name in buildable_here(player, coordinates, env):
        if best is None or improvement_gain(name) > improvement_gain(best):
            best = name
    return best


def worker_targets(player, env):
    """Yield, lazily and in a fixed order (city id, then (row, col)), every
    tile a Worker of `player` could be sent to: one of the player's owned
    tiles (`Map.tiles_of_city` over its cities) on which it may build some
    improvement now (`buildable_here`: a city centre, a district tile and an
    already improved tile are never among them) and where no unit of another
    player and no Worker of the player stands. A Worker standing on a tile is
    already at work on it, so the tile is not a target for another."""
    for city in sorted(player.cities, key=lambda c: c.city_id):
        for position in env.map.tiles_of_city(city.city_id):
            tile = env.map.get_tile(position)
            if any(unit.player is not player or isinstance(unit, WorkerUnit)
                   for unit in tile.units):
                continue
            if next(_buildable(player, tile, env), None) is not None:
                yield position


def worker_has_work(player):
    """Whether `player` owns a tile a Worker could be sent to
    (`worker_targets`). The Worker's build rule: `City.can_produce_unit`
    offers a Worker exactly while this holds."""
    return next(worker_targets(player, player.game_env), None) is not None
