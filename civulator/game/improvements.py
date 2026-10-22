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

**The Worker default builds a tile's best improvement.** The engine keeps
one improvement per tile and lets a build replace it (`GameEnvironment.
build_improvement`, #126), so a player may re-improve a tile however it
likes. The default is narrower: it builds on a tile only when the best
improvement for it -- ranked by (`improvement_gain`, config order), a total
order -- is not the one already there. A new tech that unlocks a better
improvement therefore makes the tile work again, and two equal improvements
can never replace each other back and forth. A future agent action to build
improvements (#99) is free to replace anything the engine allows.

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


def _rank(name):
    """The default's total order over improvements, larger is better:
    `improvement_gain`, then the earlier in config order."""
    return improvement_gain(name), -terrain_model.IMPROVEMENT_ORDER.index(name)


def _buildable(player, tile, env):
    """The improvement names `player` may build on `tile` now, lazily, in
    config order: `can_player_build_improvement_at` for each, so never the
    improvement already there."""
    for name in terrain_model.IMPROVEMENT_ORDER:
        if env.can_player_build_improvement_at(player, tile.coordinates, name):
            yield name


def buildable_here(player, coordinates, env):
    """Every improvement `player` may build on this tile now, in config order
    (`[]` when the tile is off the board, not the player's, or nothing is
    available). A build replaces the tile's improvement (#126)."""
    tile = env.map.get_tile(coordinates)
    return [] if tile is None else list(_buildable(player, tile, env))


def _best_on(player, tile, env):
    """The improvement the default builds on `tile`, or None: the best by
    `_rank` of what `player` may build there, provided it ranks above every
    improvement already on the tile (so a tile already holding its best is
    left alone)."""
    best = max(_buildable(player, tile, env), key=_rank, default=None)
    if best is None:
        return None
    if any(_rank(present) >= _rank(best) for present in tile.improvements
           if present in terrain_model.IMPROVEMENT_YIELDS):
        return None
    return best


def best_improvement(player, coordinates, env):
    """The improvement a Worker of `player` builds on this tile, or None when
    there is nothing to build: the largest `improvement_gain`, among equals
    the first in config order, and only when the tile does not already hold
    an improvement that ranks at least as high (`_best_on`)."""
    tile = env.map.get_tile(coordinates)
    return None if tile is None else _best_on(player, tile, env)


def worker_targets(player, env):
    """Yield, lazily and in a fixed order (city id, then (row, col)), every
    tile a Worker of `player` could be sent to: one of the player's owned
    tiles (`Map.tiles_of_city` over its cities) on which the default would
    build now (`best_improvement`: never a city centre or a district tile,
    and an improved tile only while a better improvement is available there)
    and where no unit of another
    player and no Worker of the player stands. A Worker standing on a tile is
    already at work on it, so the tile is not a target for another."""
    for city in sorted(player.cities, key=lambda c: c.city_id):
        for position in env.map.tiles_of_city(city.city_id):
            tile = env.map.get_tile(position)
            if any(unit.player is not player or isinstance(unit, WorkerUnit)
                   for unit in tile.units):
                continue
            if _best_on(player, tile, env) is not None:
                yield position


def worker_has_work(player):
    """Whether `player` owns a tile a Worker could be sent to
    (`worker_targets`). The Worker's build rule: `City.can_produce_unit`
    offers a Worker exactly while this holds."""
    return next(worker_targets(player, player.game_env), None) is not None
