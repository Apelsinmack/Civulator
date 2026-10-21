"""What a player and a city may build (issue #116 P2, docs/progression_design.md
§4.1, §6.2 and "v2 fixes").

Two predicates, and every build path reads them:

- `player_can_build(player, kind, name)` -- the one availability check for a
  unit, building, district or improvement: the item exists and its
  `requires_tech` (a column on the item's own config table) is in
  `player.techs`. `City.produce_unit` / `produce_building`, the build mask
  (`agents/build_agent.get_valid_build_mask`), `can_place_district` and
  `GameEnvironment.can_player_build_improvement_at` call it.
- `city_can_build_building(city, name)` -- the one building-availability
  predicate: the building is producible, its owner `player_can_build` it, a
  COMPLETE district of its `requires_district` type stands in the city, and
  the city owns its `requires_building`. `produce_building` and the build
  mask call it (P5's purchase will too).

`requires_civic` and `requires_government_tier` are read when an item
declares them and PASS until #116 P4 defines civics and governments: no
civic or government tier can be known before then, so a gate on one cannot
be evaluated yet. P4 replaces `_civic_known` / `_government_tier_met`.

Captured units and buildings are kept whatever the new owner knows (Civ 6):
nothing here is consulted for what a city already has.

Pure: reads the parsed specs (unit_model, terrain_model, the district
registry through `district_spec`) and live state; mutates nothing.
"""

from .. import terrain_model, unit_model
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


def _civic_known(player, civic):
    """STUB until #116 P4: no civic exists yet, so a `requires_civic` gate
    passes (documented in the module docstring)."""
    return True


def _government_tier_met(player, tier):
    """STUB until #116 P4: governments do not exist yet; the gate passes."""
    return True


def player_can_build(player, kind, name):
    """True iff `player` may build the `kind` item `name` now: it exists and
    its `requires_tech` (if any) is among `player.techs` (and, from P4, its
    `requires_civic` among `player.civics`). `kind` is one of KINDS."""
    if not _exists(kind, name):
        return False
    tech = required_tech(kind, name)
    if tech is not None and tech not in player.techs:
        return False
    civic = _required_civic(kind, name)
    if civic is not None and not _civic_known(player, civic):
        return False
    return True


def city_can_build_building(city, name):
    """True iff `city` may start producing building `name`: it has a
    production cost (the Palace is granted, never built), its owner
    `player_can_build` it, a complete `requires_district` stands in the city,
    and the city owns its `requires_building`. Whether the city already owns
    `name` is not this predicate's question (the build mask asks it)."""
    if name not in unit_model.BUILDING_COSTS:
        return False
    if not player_can_build(city.player, "building", name):
        return False
    tier = unit_model.BUILDING_REQUIRES_GOVERNMENT_TIER.get(name)
    if tier is not None and not _government_tier_met(city.player, tier):
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
