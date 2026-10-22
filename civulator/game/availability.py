"""What a player and a city may build (issue #116 P2, P4; docs/progression_design.md
§4.1, §5, §6.2 and "v2 fixes").

Two predicates, and every build path reads them:

- `player_can_build(player, kind, name)` -- the one availability check for a
  unit, building, district or improvement: the item exists, its
  `requires_tech` (a column on the item's own config table) is in
  `player.techs` and its `requires_civic` in `player.civics` (#116 P4).
  `City.can_produce_unit` (so `produce_unit`, the build mask
  `agents/build_agent.get_valid_build_mask` and `GameEnvironment.purchase`),
  `produce_building`, `can_place_district` and
  `GameEnvironment.can_player_build_improvement_at` call it.
- `city_can_build_building(city, name)` -- the one building-availability
  predicate: the building is producible, its owner `player_can_build` it,
  the owner's current government is of at least its
  `requires_government_tier` (no government: below every tier, #116 P4), a
  COMPLETE district of its `requires_district` type stands in the city, and
  the city owns its `requires_building`. `produce_building`, the build
  mask and `GameEnvironment.purchase` (#116 P5) call it.

A unit's `requires_resource` (v0.9.0 Q1, docs/districts_religion_design.md
§2.2) is the third clause of `player_can_build`: the owner has access to the
strategic resource (`game/resources.player_has_access`). It is honoured only
on a world that carries strategic resources at all
(`resources.world_has_class`): the basic generator's boards and the matchup
board keep the pre-0.9 roster ("v2 fixes", non-blocking list). An item
already in production when access is lost completes -- the order was legal
when given; only new orders are refused (City.process_turn never re-asks).
Each refusal by this clause counts in the owner's
`episode_stats["units_refused_resource"]` -- a pressure indicator (every
predicate evaluation counts: the build mask, produce, purchase, upgrade),
not a count of distinct decisions, and the one write this module makes.

Captured units and buildings are kept whatever the new owner knows (Civ 6):
nothing here is consulted for what a city already has.

Pure but for that counter: reads the parsed specs (unit_model,
terrain_model, the district registry through `district_spec`) and live
state; mutates no game state.
"""

from .. import research_model, terrain_model, unit_model
from . import resources as _resources
# A module reference, not a name: districts.py imports this module for
# can_place_district's gate, and module references resolve in either
# import order.
from . import districts as _districts

KINDS = ("unit", "building", "district", "improvement")


def _district(name):
    """The registry entry of district type `name`, or None if there is none."""
    try:
        return _districts.district_spec(name)
    except KeyError:
        return None


def required_tech(kind, name):
    """The tech `name` of `kind` requires, or None when it is ungated.
    Raises ValueError for an unknown kind; an unknown name has no tech."""
    if kind == "unit":
        return unit_model.UNIT_REQUIRES_TECH.get(name)
    if kind == "building":
        return unit_model.BUILDING_REQUIRES_TECH.get(name)
    if kind == "district":
        spec = _district(name)
        return spec.requires_tech if spec is not None else None
    if kind == "improvement":
        return terrain_model.IMPROVEMENT_REQUIRES_TECH.get(name)
    raise ValueError(f"unknown item kind {kind!r}, expected one of {KINDS}")


def _required_civic(kind, name):
    if kind == "unit":
        return unit_model.UNIT_REQUIRES_CIVIC.get(name)
    if kind == "building":
        return unit_model.BUILDING_REQUIRES_CIVIC.get(name)
    if kind == "district":
        spec = _district(name)
        return spec.requires_civic if spec is not None else None
    return None


def _exists(kind, name):
    if kind == "unit":
        return name in unit_model.UNIT_NAMES
    if kind == "building":
        return name in unit_model.BUILDING_NAMES
    if kind == "district":
        return _district(name) is not None
    if kind == "improvement":
        return name in terrain_model.IMPROVEMENT_NAMES
    raise ValueError(f"unknown item kind {kind!r}, expected one of {KINDS}")


# The tier of "no government" (progression design §5.2: Player.government is
# None until one is adopted): below every configured tier, so any
# `requires_government_tier` gate refuses.
NO_GOVERNMENT_TIER = -1


def government_tier(player):
    """The tier of `player`'s current government, NO_GOVERNMENT_TIER for none."""
    if player.government is None:
        return NO_GOVERNMENT_TIER
    return research_model.GOVERNMENTS[player.government].tier


def required_civic(kind, name):
    """The civic `name` of `kind` requires, or None when it is ungated.
    Improvements carry no civic gate. Raises ValueError for an unknown kind."""
    if kind == "improvement":
        return None
    if kind not in KINDS:
        raise ValueError(f"unknown item kind {kind!r}, expected one of {KINDS}")
    return _required_civic(kind, name)


def required_resource(kind, name):
    """The strategic resource the `kind` item `name` requires, or None. Only
    units carry the column (v0.9.0 Q1)."""
    if kind == "unit":
        return unit_model.UNIT_REQUIRES_RESOURCE.get(name)
    return None


def resource_gate_holds(player, kind, name):
    """The resource clause alone: True when `name` requires no resource, the
    owner's world carries no strategic resource (the gate is not in force),
    or the owner has access to it."""
    resource = required_resource(kind, name)
    if resource is None:
        return True
    env = getattr(player, "game_env", None)
    game_map = getattr(env, "map", None)
    if not _resources.world_has_class(game_map, terrain_model.resource_class(resource)):
        return True
    return _resources.player_has_access(player, resource, env)


def player_can_build(player, kind, name):
    """True iff `player` may build the `kind` item `name` now: it exists, its
    `requires_tech` (if any) is among `player.techs`, its `requires_civic`
    (if any) among `player.civics`, and -- for a unit with a
    `requires_resource`, on a world that has resources of that class -- the
    player has access to that resource. `kind` is one of KINDS."""
    if not _exists(kind, name):
        return False
    tech = required_tech(kind, name)
    if tech is not None and tech not in player.techs:
        return False
    civic = _required_civic(kind, name)
    if civic is not None and civic not in player.civics:
        return False
    if not resource_gate_holds(player, kind, name):
        _count_resource_refusal(player)
        return False
    return True


def _count_resource_refusal(player):
    """Count one refusal by the resource clause in the owner's episode stats
    (stats only; nothing reads it back)."""
    env = getattr(player, "game_env", None)
    stats = getattr(env, "episode_stats", None)
    if stats is not None and player.player_index in stats:
        stats[player.player_index]["units_refused_resource"] += 1


def city_can_build_building(city, name):
    """True iff `city` may start producing building `name`: it has a
    production cost (the Palace is granted, never built), its owner
    `player_can_build` it, the owner's government is of at least its
    `requires_government_tier`, a complete `requires_district` stands in the
    city, and the city owns its `requires_building`. Whether the city
    already owns `name` is not this predicate's question (the build mask
    asks it)."""
    if name not in unit_model.BUILDING_COSTS:
        return False
    if not player_can_build(city.player, "building", name):
        return False
    tier = unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER.get(name)
    if tier is not None and government_tier(city.player) < tier:
        return False
    district = unit_model.BUILDING_REQUIRES_DISTRICT.get(name)
    if district is not None and not any(
        d.type == district and d.complete for d in city.districts
    ):
        return False
    building = unit_model.BUILDING_REQUIRES_BUILDING.get(name)
    if building is not None and building not in city.buildings:
        return False
    return True
