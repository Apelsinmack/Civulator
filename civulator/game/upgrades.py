"""Unit upgrades: what an upgrade costs and when it is allowed (issue #116 P3,
docs/progression_design.md §6.4 and "v2 fixes").

Two read-only functions, and `GameEnvironment.upgrade_unit` is the one place
that acts on them -- the only way a unit changes type:

- `upgrade_cost(unit)` -- whole gold: `[gold] upgrade_per_production *
  (target production cost - unit production cost) + [gold] upgrade_base`
  (`unit_model.base_upgrade_cost`), then scaled by the owner's
  `upgrade_cost_percent` effects.
- `can_upgrade(env, unit)` -- the unit has an `upgrades_to` target, its owner
  may build it (`player_can_build`, so a tech gate applies), it stands in its
  owner's territory, it has all its movement and has not acted this turn, and
  the treasury covers the price.

Civ 6 upgrades need a friendly tile, movement left and the gold; its gold
formula is not stated, so this one is the community's reading of the game
files and reproduces the single data point (Slinger -> Archer = 60 gold).

Pure: reads parsed config and live state, mutates nothing.
"""

from .. import unit_model
from .availability import player_can_build


def upgrade_target(unit):
    """The unit type `unit` upgrades into, or None when it has no upgrade."""
    return unit_model.UPGRADES_TO.get(unit.unit_type)


def _upgrade_cost_percent(player):
    """Percent added to every upgrade price by `player`'s active
    `upgrade_cost_percent` effects (Civ 6's Professional Army: -50).

    HOOK for #116 P4: the effects interpreter (`effects.py`) has not landed, so
    nothing yet changes a price and this is 0. P4 returns the SUM of the
    player's `upgrade_cost_percent` effects here -- summed first and applied
    once, floored, as every effect of one kind is ("v2 fixes", N3) -- and
    `upgrade_cost` below already applies it that way.
    """
    return 0


def upgrade_cost(unit):
    """Whole gold `unit`'s upgrade costs now, or None when it has none."""
    base = unit_model.base_upgrade_cost(unit.unit_type)
    if base is None:
        return None
    return max(0, base * (100 + _upgrade_cost_percent(unit.player)) // 100)


def can_upgrade(env, unit):
    """Whether `unit` may be upgraded right now (every rule of §6.4). `env`
    is the GameEnvironment `unit` is playing in."""
    target = upgrade_target(unit)
    if target is None:
        return False
    player = unit.player
    if unit not in player.units:
        return False
    if not player_can_build(player, "unit", target):
        return False
    if not env.player_owns_tile(player, unit.coordinates):
        return False
    if unit.movement_points < unit.get_max_movement() or unit.has_acted:
        return False
    return player.gold >= 10 * upgrade_cost(unit)  # the treasury is in tenths
