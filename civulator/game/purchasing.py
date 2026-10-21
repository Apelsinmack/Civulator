"""Purchasing with gold or faith (issue #116 P5, docs/progression_design.md §7.3,
§10.1 and "v2 fixes").

Read-only rules; `GameEnvironment.purchase` is the one place that buys --
the only instant-completion path. A purchased unit is placed by
`City.complete_unit_production` (queued in `Player.queued_units` when it
cannot be), a purchased building is appended to `city.buildings`: nothing
about an item depends on how it was obtained.

- `purchase_cost(player, kind, name, resource)` -- whole points:
  `production_cost * [<resource>] purchase_multiplier * (100 + the summed
  purchase_percent effects for that resource) // 100`, floored at 0 (Civ 6:
  gold 4x, faith 2x production; production discounts do not reach it).
- `can_purchase(player, city, kind, name, resource)` -- `kind` is "unit" or
  "building" and `resource` "gold" or "faith"; the city is the player's; the
  item lists the resource in its `purchasable` column, or the resource is
  faith, the item a unit and its faith category (`unit_model.faith_category`)
  is unlocked by a `faith_purchase` effect in force for the city; the city
  could start it (`City.can_produce_unit` for a unit, `city_can_build_building`
  and not already owned for a building); and the pool covers 10 x the price.

Pure: reads parsed config, the effects in force and live state.
"""

from ..effects import KIND_FAITH_PURCHASE, KIND_PURCHASE_PERCENT, active_effects, percent_sum
from ..unit_model import (
    BUILDING_COSTS,
    BUILDING_PURCHASABLE,
    PRODUCTION_COST,
    PURCHASE_MULTIPLIER,
    PURCHASE_RESOURCES,
    UNIT_PURCHASABLE,
    faith_category,
)
from .availability import city_can_build_building

ITEM_UNIT = "unit"
ITEM_BUILDING = "building"
PURCHASE_KINDS = (ITEM_UNIT, ITEM_BUILDING)
RESOURCE_GOLD = "gold"
RESOURCE_FAITH = "faith"
assert set(PURCHASE_RESOURCES) == {RESOURCE_GOLD, RESOURCE_FAITH}


def pool(player, resource):
    """Tenths of `resource` in `player`'s pool (the treasury for gold)."""
    if resource == RESOURCE_GOLD:
        return player.gold
    if resource == RESOURCE_FAITH:
        return player.faith
    raise ValueError(f"unknown purchase resource {resource!r}, expected one of {PURCHASE_RESOURCES}")


def spend(player, resource, tenths):
    """Take `tenths` of `resource` from `player`'s pool."""
    if resource == RESOURCE_GOLD:
        player.gold -= tenths
    elif resource == RESOURCE_FAITH:
        player.faith -= tenths
    else:
        raise ValueError(f"unknown purchase resource {resource!r}, expected one of {PURCHASE_RESOURCES}")


def _production_cost(kind, name):
    if kind == ITEM_UNIT:
        return PRODUCTION_COST.get(name)
    if kind == ITEM_BUILDING:
        return BUILDING_COSTS.get(name)
    return None


def _purchase_percent(player, resource):
    """The summed `percent` of `player`'s `purchase_percent` effects in force
    for `resource` (Theocracy: faith -15), applied once by `purchase_cost`
    (v2 fixes, N3). The one consumer of that kind."""
    return percent_sum(effect for effect in active_effects(player, kind=KIND_PURCHASE_PERCENT)
                       if effect["resource"] == resource)


def purchase_cost(player, kind, name, resource):
    """Whole points of `resource` the `kind` item `name` costs `player` now,
    or None when it has no price (an unknown kind, item or resource, or a
    building with no production cost)."""
    base = _production_cost(kind, name)
    if base is None or resource not in PURCHASE_MULTIPLIER:
        return None
    percent = _purchase_percent(player, resource)
    return max(0, base * PURCHASE_MULTIPLIER[resource] * (100 + percent) // 100)


def faith_purchase_categories(player, city):
    """The faith-purchase categories unlocked for `city` of `player`: the
    union, in order of first appearance, of the `categories` of every
    `faith_purchase` effect in force there (a government's or a player-scoped
    building's everywhere, a city-scoped building's in its own city). The one
    consumer of that kind."""
    categories = []
    for effect in active_effects(player, city, KIND_FAITH_PURCHASE):
        for category in effect["categories"]:
            if category not in categories:
                categories.append(category)
    return tuple(categories)


def purchasable_with(player, city, kind, name, resource):
    """Whether the item may be bought with `resource` in `city`: its
    `purchasable` column lists it, or it is a unit bought with faith whose
    faith category is unlocked there (`faith_purchase_categories`)."""
    if kind == ITEM_UNIT:
        listed = UNIT_PURCHASABLE.get(name, ())
    elif kind == ITEM_BUILDING:
        listed = BUILDING_PURCHASABLE.get(name, ())
    else:
        return False
    if resource in listed:
        return True
    if resource != RESOURCE_FAITH or kind != ITEM_UNIT:
        return False
    category = faith_category(name)
    return category is not None and category in faith_purchase_categories(player, city)


def can_purchase(player, city, kind, name, resource):
    """Whether `player` may buy the `kind` item `name` with `resource` in
    `city` right now (every rule of the module docstring)."""
    if kind not in PURCHASE_KINDS or resource not in PURCHASE_RESOURCES:
        return False
    if city.player is not player:
        return False
    if not purchasable_with(player, city, kind, name, resource):
        return False
    if kind == ITEM_UNIT:
        if not city.can_produce_unit(name):
            return False
    elif name in city.buildings or not city_can_build_building(city, name):
        return False
    cost = purchase_cost(player, kind, name, resource)
    return cost is not None and pool(player, resource) >= 10 * cost
