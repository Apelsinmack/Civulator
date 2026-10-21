"""Gold upkeep and bankruptcy order (issue #116 P5, docs/progression_design.md
§7.1-§7.2 and "v2 fixes").

What a player owes each own turn, in int tenths of gold (the treasury's
unit), and which unit goes first when it cannot pay. Read-only:
`GameEnvironment.economy_phase` is the one place that deducts and disbands
(its first two steps, before research).

- a unit owes `max(0, [units.<Type>] maintenance + 10 * the summed
  unit_maintenance_delta effects in force)` -- the delta is whole gold per
  unit (Civ 6's Conscription: -1), and no unit's upkeep falls below 0;
- a building owes its `[buildings.*] maintenance`, a COMPLETE district its
  `[districts.*] maintenance` (a placed, unfinished one owes nothing);
- bankruptcy disbands the unit with the highest upkeep, the lowest index in
  `player.units` ("oldest", v2 fixes) among equals -- never set or dict
  iteration order.

Pure: reads parsed config, the effects in force and live state.
"""

from ..effects import KIND_UNIT_MAINTENANCE_DELTA, active_effects
from ..unit_model import BUILDING_MAINTENANCE, UNIT_MAINTENANCE
from .districts import district_spec


def unit_maintenance_delta(player):
    """Whole gold added to every unit's upkeep by `player`'s
    `unit_maintenance_delta` effects in force: their sum, applied once per
    unit. The one consumer of that kind."""
    return sum(effect["amount"]
               for effect in active_effects(player, kind=KIND_UNIT_MAINTENANCE_DELTA))


def unit_upkeep(unit, delta):
    """Tenths of gold `unit` owes per turn, given the player's summed delta
    (`unit_maintenance_delta`), floored at 0."""
    return max(0, UNIT_MAINTENANCE.get(unit.unit_type, 0) + 10 * delta)


def city_upkeep(city):
    """Tenths of gold `city` owes per turn: its buildings' maintenance plus
    its complete districts'."""
    total = sum(BUILDING_MAINTENANCE.get(building, 0) for building in city.buildings)
    total += sum(district_spec(d.type).maintenance for d in city.districts if d.complete)
    return total


def maintenance_due(player):
    """Tenths of gold `player` owes this turn: every unit's upkeep plus every
    city's (`city_upkeep`)."""
    delta = unit_maintenance_delta(player)
    return (sum(unit_upkeep(unit, delta) for unit in player.units)
            + sum(city_upkeep(city) for city in player.cities))


def disband_candidate(player, delta):
    """The unit bankruptcy disbands next: the highest positive upkeep, the
    lowest `player.units` index among equals; None when every unit is free."""
    best, best_upkeep = None, 0
    for unit in player.units:
        upkeep = unit_upkeep(unit, delta)
        if upkeep > best_upkeep:
            best, best_upkeep = unit, upkeep
    return best
