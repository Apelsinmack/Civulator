"""Resource tiers (v0.9.0 Q1, docs/districts_religion_design.md §2, §11 rows 1-5,
"v2 fixes" B1-B3): the class form of `matches`, the resource columns, the one
access predicate, the unit gate in every build path, districts on resources,
and the tiered mapgen stage.

Every test names the property it protects and the change that must break it.
Registries are iterated, never pinned: a new resource, class member or unit
gate is covered without editing this file.
"""

import itertools
import os
import subprocess
import sys

import numpy as np
import pytest

from civulator import terrain_model, unit_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.game import availability
from civulator.game.districts import can_place_district
from civulator.game.purchasing import can_purchase
from civulator.game.resources import accessible_resources, player_has_access, world_has_class
from civulator.game.unit import WarriorUnit
from civulator.game.upgrades import can_upgrade
from civulator.mapgen import earthlike, generate, starts, tiered_resources
from civulator.terrain_model import (
    BASE_TABLE, FEATURE_TABLE, IMPROVEMENT_ORDER, RELIEF_TABLE, RESOURCE_CLASSES,
    RESOURCE_IMPROVED_BY, RESOURCE_TABLE, matches, resource_class, resources_of_class,
)

from conftest import grant_all
from test_combat_range import make_flat_env, place
from test_districts import board, far_site, make_city, placeable_type
from test_mapgen_golden import PINNED_PARAMS

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))

TIERED = [n for n in RESOURCE_TABLE if resource_class(n) != "bonus"]
GATED_UNITS = sorted(unit_model.UNIT_REQUIRES_RESOURCE)
DUEL_SEEDS = range(1, 21)


def combos(resource, land_only=False, district_feature_ok=False):
    """Every (base, relief, feature) the resource's `on` admits (validate),
    in table order. `land_only`: passable land. `district_feature_ok`: the
    feature is one a district may stand on."""
    from civulator import district_model
    feature_ok = district_model.REMOVABLE_FEATURES | district_model.ALLOWED_FEATURES
    out = []
    for base, relief, feature in itertools.product(BASE_TABLE, RELIEF_TABLE,
                                                   [None, *FEATURE_TABLE]):
        try:
            terrain_model.validate(base, relief, feature, resource)
        except ValueError:
            continue
        if land_only and (BASE_TABLE[base].get("domain") != "land" or relief == "mountain"):
            continue
        if district_feature_ok and feature is not None and feature not in feature_ok:
            continue
        out.append((base, relief, feature))
    return out


def put(env, coords, resource, combo=None):
    combo = combo or combos(resource, land_only=True)[0]
    tile = env.map.get_tile(coords)
    tile.set_layers(combo[0], relief=combo[1], feature=combo[2], resource=resource,
                    map_ref=env.map)
    return tile


# --- B1: the class form of `matches` --------------------------------------------


@pytest.mark.parametrize("cls", RESOURCE_CLASSES)
def test_a_class_name_in_resources_matches_exactly_that_class(cls):
    """`resources = [<class>]` matches every resource of that class and no
    other, and never "no resource". Breaks if `_match` stops consulting
    `resource_class`, or a class name starts matching across classes."""
    on = {"resources": [cls]}
    for name in RESOURCE_TABLE:
        assert matches(on, "Plains", "flat", None, resource=name) == (resource_class(name) == cls)
    assert not matches(on, "Plains", "flat", None, resource=None)
    terrain_model.validate_on_table(on, "test", allow_resources=True, check_names=True)


@pytest.mark.parametrize("bad_name", [*RESOURCE_CLASSES, "any"])
def test_a_resource_named_like_a_class_is_refused_at_load(bad_name):
    """No resource may carry a class name (or "any"): the `resources` key
    would read it two ways. Breaks if `parse_resources` drops the check."""
    table = {bad_name: {"class": "luxury", "on": {"bases": ["Plains"]},
                        "improved_by": ["Plantation"], "frequency": 1}}
    with pytest.raises(ValueError, match="named like a class"):
        terrain_model.parse_resources(table)


def test_resource_columns_are_validated_at_load():
    """An unknown key, an unknown improvement in `improved_by`, an unknown
    `reveals` tech, a non-positive `frequency`, a tiered column on a bonus
    resource and a tiered resource without `improved_by` all raise. Breaks if
    a column escapes the strict key list or its validation."""
    good = {"class": "luxury", "on": {"bases": ["Plains"]},
            "improved_by": [IMPROVEMENT_ORDER[0]], "frequency": 1}
    terrain_model.parse_resources({"X": dict(good)})
    bad = [
        {**good, "frequncy": 1},
        {**good, "improved_by": ["No Such Improvement"]},
        {**good, "reveals": "No Such Tech"},
        {**good, "frequency": 0},
        {**good, "frequency": 1.5},
        {"class": "bonus", "on": {"bases": ["Plains"]}, "improved_by": [IMPROVEMENT_ORDER[0]]},
        {k: v for k, v in good.items() if k != "improved_by"},
        {**good, "class": "precious"},
    ]
    for table in bad:
        with pytest.raises(ValueError):
            terrain_model.parse_resources({"X": table})


def test_every_configured_improved_by_and_reveals_names_something_real():
    """Registry property: every tiered resource names existing improvements
    and (if any) an existing tech; bonus resources name none. Breaks if
    config gains a dangling name the loader let through."""
    from civulator.research_model import TECHS
    for name in RESOURCE_TABLE:
        if resource_class(name) == "bonus":
            assert RESOURCE_IMPROVED_BY[name] == ()
            continue
        assert RESOURCE_IMPROVED_BY[name]
        assert set(RESOURCE_IMPROVED_BY[name]) <= set(IMPROVEMENT_ORDER)
        tech = terrain_model.RESOURCE_REVEALS[name]
        assert tech is None or tech in TECHS


def test_requires_resource_must_name_a_strategic_resource():
    """`[units.*] requires_resource` naming a luxury or an unknown resource
    raises at load. Breaks if the gate column is left unvalidated."""
    luxury = resources_of_class("luxury")[0]
    for bad in (luxury, "Unobtainium"):
        with pytest.raises(ValueError, match="strategic"):
            terrain_model._validate_unit_resource_gates({"Warrior": bad})
    for unit, name in unit_model.UNIT_REQUIRES_RESOURCE.items():
        assert resource_class(name) == "strategic", unit


# --- §2.2 / B2: access ------------------------------------------------------------


@pytest.mark.parametrize("resource", TIERED)
def test_access_is_exactly_an_owned_improved_districted_or_centre_tile(resource):
    """`player_has_access` holds for an owned tile carrying the resource that
    holds one of its `improved_by` improvements, a district, or a centre --
    and for nothing else: not a bare owned tile, not another improvement,
    not a neutral or foreign tile. Breaks if the access rule gains an
    exception or loses the district clause (R2)."""
    env = board()
    me, other = env.players
    city = make_city(env, (3, 5))
    rival = make_city(env, (3, 12), player_index=1)
    site = far_site(env, city)
    combo = combos(resource)[0]
    tile = put(env, site, resource, combo)
    assert not player_has_access(me, resource, env)  # bare tile
    for improvement in IMPROVEMENT_ORDER:
        tile.add_improvement(improvement, map_ref=env.map)
        expected = improvement in RESOURCE_IMPROVED_BY[resource]
        assert player_has_access(me, resource, env) == expected, improvement
        assert not player_has_access(other, resource, env)
        tile.remove_improvement(improvement, map_ref=env.map)
    # A district (complete or not) is access.
    tile.district = object()
    assert player_has_access(me, resource, env)
    tile.district = None
    # The same improved tile in foreign or neutral hands is no access.
    tile.add_improvement(RESOURCE_IMPROVED_BY[resource][0], map_ref=env.map)
    env.map.transfer(site, city, rival)
    assert not player_has_access(me, resource, env) and player_has_access(other, resource, env)


def test_a_city_centre_on_a_resource_is_access():
    """The centre clause: a city founded on a tiered resource has it. Breaks
    if access requires an improvement on the centre."""
    for resource in TIERED:
        env = board()
        land = combos(resource, land_only=True)
        if not land:
            continue
        put(env, (3, 5), resource, land[0])
        city = make_city(env, (3, 5))
        assert player_has_access(city.player, resource, env), resource


def test_a_farm_on_niter_is_not_access():
    """Design §2.1 / B2: a Farm on a Niter tile never grants Niter; a Mine
    (where it can stand) does. Breaks if access reads "any improvement"."""
    assert "Farm" not in RESOURCE_IMPROVED_BY["Niter"]
    env = board()
    city = make_city(env, (3, 5))
    site = far_site(env, city)
    tile = put(env, site, "Niter", ("Plains", "flat", None))
    tile.add_improvement("Farm", map_ref=env.map)
    assert not player_has_access(city.player, "Niter", env)
    tile.set_layers("Desert", relief="flat", resource="Niter", map_ref=env.map)
    tile.add_improvement("Mine", map_ref=env.map)
    assert player_has_access(city.player, "Niter", env)


def test_world_has_class_follows_the_tiles_and_their_epoch():
    """`world_has_class` is true exactly while some tile carries a resource
    of the class, and follows a `set_layers` change (the cache keys on
    terrain_epoch). Breaks if the cache misses the epoch or reads a set."""
    env = board()
    assert not world_has_class(env.map, "strategic")
    put(env, (5, 9), "Iron")
    assert world_has_class(env.map, "strategic")
    assert not world_has_class(env.map, "luxury")
    env.map.get_tile((5, 9)).set_layers("Plains", map_ref=env.map)
    assert not world_has_class(env.map, "strategic")


# --- §2.2: the unit gate in every build path (§11 row 3) ----------------------------


def _gated_env(unit_type, with_access):
    """A board with the unit's tech known, a city, a strategic resource on the
    world, and -- if `with_access` -- the unit's resource improved on an
    owned tile; otherwise only on a far neutral tile."""
    env = board()
    player = env.players[0]
    player.gold = 10 ** 7
    city = make_city(env, (3, 5))
    resource = unit_model.UNIT_REQUIRES_RESOURCE[unit_type]
    if with_access:
        tile = put(env, far_site(env, city), resource)
        tile.add_improvement(RESOURCE_IMPROVED_BY[resource][0], map_ref=env.map)
    else:
        put(env, (7, 14), resource)  # neutral: the world has it, the player not
    return env, player, city


@pytest.mark.parametrize("unit_type", GATED_UNITS)
@pytest.mark.parametrize("with_access", [False, True])
def test_a_gated_unit_is_refused_or_offered_by_every_path_alike(unit_type, with_access):
    """On a world with strategic resources a `requires_resource` unit is
    refused by `player_can_build`, `can_produce_unit` / `produce_unit`, the
    build mask and `purchase` while its owner lacks access, and offered by
    all of them with it (design §11 row 3; DECLARED rule change v0.9.0 for
    the Swordsman and Horseman). Breaks if one caller forgets the
    predicate."""
    env, player, city = _gated_env(unit_type, with_access)
    assert world_has_class(env.map, "strategic")
    assert availability.player_can_build(player, "unit", unit_type) is with_access
    assert city.can_produce_unit(unit_type) is with_access
    if unit_type in BUILD_OPTIONS:
        assert get_valid_build_mask(city)[BUILD_OPTIONS.index(unit_type)] == float(with_access)
    if "gold" in unit_model.UNIT_PURCHASABLE.get(unit_type, ()):
        assert can_purchase(player, city, "unit", unit_type, "gold") is with_access
    before = dict(city.current_production)
    assert city.produce_unit(unit_type) is with_access
    if not with_access:
        assert city.current_production == before


@pytest.mark.parametrize("with_access", [False, True])
def test_the_swordsman_upgrade_follows_iron_access(with_access):
    """`upgrade_unit` (Warrior -> Swordsman) follows the same predicate: no
    Iron access, no upgrade. Breaks if `can_upgrade` checks only the tech."""
    assert unit_model.UPGRADES_TO.get("Warrior") == "Swordsman"
    env, player, city = _gated_env("Swordsman", with_access)
    warrior = place(env, WarriorUnit, 0, city.coordinates)
    warrior.movement_points = warrior.get_max_movement()
    assert can_upgrade(env, warrior) is with_access
    assert env.upgrade_unit(warrior) is with_access


def test_purchase_follows_iron_access():
    """`purchase` of a gated unit with gold is refused without access and
    succeeds with it. Breaks if purchasing skips `can_produce_unit`."""
    unit_type = "Swordsman"
    for with_access in (False, True):
        env, player, city = _gated_env(unit_type, with_access)
        assert can_purchase(player, city, "unit", unit_type, "gold") is with_access
        assert bool(env.purchase(city, "unit", unit_type, "gold")) is with_access


def test_the_gate_is_not_in_force_on_a_world_without_strategic_resources():
    """Basic boards and the matchup board keep the pre-0.9 roster: with no
    strategic resource anywhere, a gated unit needs only its tech ("v2
    fixes", non-blocking list). Breaks if the gate ignores
    `world_has_class`."""
    env = board()
    assert not world_has_class(env.map, "strategic")
    city = make_city(env, (3, 5))
    for unit_type in GATED_UNITS:
        assert city.can_produce_unit(unit_type), unit_type


def test_a_basic_world_carries_no_tiered_resource():
    """The `basic` generator does not run the tiered stage (declared): its
    worlds hold bonus resources at most. Breaks if basic starts placing
    strategic resources (and so gating its units)."""
    for seed in range(5):
        md = generate(seed, (12, 24), num_players=2, map_type="basic")
        assert all(v is None or resource_class(v) == "bonus" for v in md.resource.ravel())


def test_a_gated_unit_in_production_completes_after_access_is_lost():
    """"The order was legal when given": a Swordsman started with Iron access
    completes after the Mine is gone; only new orders are refused. Breaks if
    production completion re-asks the predicate."""
    env, player, city = _gated_env("Swordsman", with_access=True)
    assert city.produce_unit("Swordsman")
    iron = next(t for t in (env.map.get_tile(c) for c in env.map.tiles_of_city(city.city_id))
                if t.resource == "Iron")
    iron.clear_improvements(map_ref=env.map)
    assert not player_has_access(player, "Iron", env)
    assert not city.can_produce_unit("Swordsman")
    city.production = city.get_unit_cost("Swordsman")
    city.process_turn(env)
    assert any(u.unit_type == "Swordsman" for u in player.units)


def test_resource_refusals_and_luxuries_reach_episode_stats():
    """`units_refused_resource` counts refusals by the resource clause;
    `luxuries_accessible` is the max distinct luxuries with access at a
    round end. Breaks if either counter is not written."""
    env, player, city = _gated_env("Swordsman", with_access=False)
    before = env.episode_stats[0]["units_refused_resource"]
    assert not city.can_produce_unit("Swordsman")
    assert env.episode_stats[0]["units_refused_resource"] > before
    luxury = next(n for n in resources_of_class("luxury") if combos(n, land_only=True))
    tile = put(env, far_site(env, city), luxury)
    tile.add_improvement(RESOURCE_IMPROVED_BY[luxury][0], map_ref=env.map)
    assert accessible_resources(player, env, "luxury") == (luxury,)
    for _ in env.players:
        env.next_turn()
    assert env.episode_stats[0]["luxuries_accessible"] == 1
    tile.clear_improvements(map_ref=env.map)
    for _ in env.players:
        env.next_turn()
    assert env.episode_stats[0]["luxuries_accessible"] == 1  # a max, not the current count


# --- §2.3: districts on resources (§11 row 2) ----------------------------------------


def _district_site(resource):
    """(env, city, district type, site, tile) with `resource` on an owned
    site some configured district may take, searching the registry and the
    resource's admitted terrain (a water resource finds a water district);
    None if no pairing exists."""
    from civulator import district_model
    for combo in combos(resource, district_feature_ok=True):
        for district_type in district_model.DISTRICTS:
            env = board()
            city = make_city(env, (3, 4))
            site = far_site(env, city)
            tile = put(env, site, resource, combo)
            if can_place_district(city, district_type, site):
                return env, city, district_type, site, tile
    return None


@pytest.mark.parametrize("resource", list(RESOURCE_TABLE))
def test_a_district_may_stand_on_any_resource_and_keeps_exactly_the_tiered_ones(resource):
    """R2 generalised (DECLARED rule change v0.9.0, was bonus-only): a
    district may be placed on a tile with any resource; a bonus resource is
    removed, a strategic or luxury one stays and the district is its access.
    Breaks if `can_place_district` refuses a class or `place_district` treats
    the classes alike."""
    found = _district_site(resource)
    assert found is not None, f"no district can stand on {resource}"
    env, city, district_type, site, tile = found
    assert env.place_district(city, district_type, site)
    if resource_class(resource) == "bonus":
        assert tile.resource is None
    else:
        assert tile.resource == resource
        assert player_has_access(city.player, resource, env)
    terrain_model.validate(tile.base_terrain, tile.relief, tile.feature, tile.resource)


def test_a_kept_resource_keeps_the_feature_it_needs():
    """A Dyes on Woods hills cannot lose its Woods (Dyes' `on` would refuse
    the bare hills), so the feature stays with it; on flat Plains Woods the
    Woods is cleared as usual. Breaks if the feature is cleared regardless
    (set_layers would raise) or kept when it need not be."""
    t = placeable_type()
    for relief, kept in (("hills", True), ("flat", False)):
        env = board()
        city = make_city(env, (3, 4))
        site = far_site(env, city)
        tile = put(env, site, "Dyes", ("Plains", relief, "Woods"))
        assert env.place_district(city, t, site)
        assert tile.resource == "Dyes"
        assert (tile.feature == "Woods") is kept


# --- §2.4 / B3: the mapgen stage -------------------------------------------------------


def _without_stage(monkeypatch, seed, size, players):
    monkeypatch.setattr(tiered_resources, "place_tiered_resources", lambda *a, **k: None)
    md = generate(seed, size, num_players=players, params=PINNED_PARAMS)
    monkeypatch.undo()
    return md


@pytest.mark.parametrize("seed,size,players", [(42, (24, 48), 6), (3, (12, 24), 2), (11, (18, 36), 4)])
def test_the_stage_touches_only_new_resource_tiles(monkeypatch, seed, size, players):
    """The tiered stage runs after starts and writes only `resource`, and only
    on tiles that had none, and only strategic/luxury names: every other
    MapData field and every pre-existing (bonus) resource is unchanged.
    Breaks if the stage moves before starts, overwrites a resource, or
    touches terrain."""
    before = _without_stage(monkeypatch, seed, size, players)
    after = generate(seed, size, num_players=players, params=PINNED_PARAMS)
    for field in ("base_terrain", "relief", "feature", "fresh_water"):
        assert np.array_equal(getattr(before, field), getattr(after, field)), field
    assert before.starts == after.starts
    assert before.rivers.keys() == after.rivers.keys()
    for (r, c), old in np.ndenumerate(before.resource):
        new = after.resource[r, c]
        if old is not None:
            assert new == old
        elif new is not None:
            assert resource_class(new) != "bonus"
    assert any(v is not None and resource_class(v) != "bonus" for v in after.resource.ravel())


def _regions(md):
    """The start regions of `md`, recomputed from its own pre-stage grids
    (the stage never overwrites, so dropping the tiered names restores
    them)."""
    pre = np.array([[None if v is None or resource_class(v) != "bonus" else v for v in row]
                    for row in md.resource], dtype=object)
    found, _, regions = starts.generate_starts(
        md.base_terrain, md.relief, md.feature, pre, md.fresh_water,
        md.params["num_players"], md.rows, md.cols, params=md.params["starts"],
        return_regions=True,
    )
    assert found == md.starts
    return regions


def _assert_fair(md):
    p = md.params["earthlike"]
    for region in _regions(md):
        reach = tiered_resources.fair_tiles(md, region, p["tiered_fair_radius"])
        for name in p["tiered_guaranteed"]:
            assert any(md.resource[t] == name for t in reach), (name, region[0])


def test_fairness_holds_on_the_golden_world():
    """Design §11 row 4: on the ceremony world every start region reaches
    Horses and Iron within distance 3 of a settleable tile of the region.
    Breaks if the fairness rule drops from the stage."""
    _assert_fair(generate(42, (24, 48), num_players=6, params=PINNED_PARAMS))


@pytest.mark.parametrize("seed", DUEL_SEEDS)
def test_fairness_holds_on_seeded_duel_worlds(seed):
    """The same fairness property on 20 seeded Duel worlds. Breaks as above."""
    _assert_fair(generate(seed, (12, 24), num_players=2, params=PINNED_PARAMS))


def test_luxuries_avoid_founding_rings_and_neighbours_differ_on_duels():
    """No luxury within the founding ring of a start; on a Duel the two
    regions get different luxury types where both could (design §2.4).
    Breaks if the founding-ring rule or the "prefer an unused type" rule is
    dropped."""
    from civulator import hexmath
    differ = 0
    for seed in DUEL_SEEDS:
        md = generate(seed, (12, 24), num_players=2, params=PINNED_PARAMS)
        ring = md.params["earthlike"]["tiered_founding_ring"]
        types_per_region = []
        for region in _regions(md):
            region_set = set(region)
            types_per_region.append({md.resource[t] for t in region_set
                                     if md.resource[t] is not None
                                     and resource_class(md.resource[t]) == "luxury"})
        for (r, c), v in np.ndenumerate(md.resource):
            if v is not None and resource_class(v) == "luxury":
                assert all(hexmath.distance((r, c), s, md.cols) > ring for s in md.starts)
        if types_per_region[0] and types_per_region[1]:
            differ += types_per_region[0].isdisjoint(types_per_region[1])
    assert differ > 0


def test_mapdata_params_record_the_stage_params():
    """Every stage param is echoed in `MapData.params["earthlike"]`, defaults
    and overrides alike, so a pinned rebuild reproduces the stage. Breaks if
    a param is read but not recorded."""
    md = generate(5, (12, 24), num_players=2, params=PINNED_PARAMS)
    for key in tiered_resources.PARAM_KEYS:
        assert md.params["earthlike"][key] == earthlike.DEFAULT_PARAMS[key], key
    override = generate(5, (12, 24), num_players=2,
                        params={**PINNED_PARAMS, "tiered_luxury_per_region": 1})
    assert override.params["earthlike"]["tiered_luxury_per_region"] == 1
    luxuries = sum(v is not None and resource_class(v) == "luxury" for v in override.resource.ravel())
    assert luxuries <= len(override.starts)


def test_config_mirrors_the_stage_defaults():
    """`[map.earthlike]`'s tiered_* keys equal `earthlike.DEFAULT_PARAMS`
    (the mirror rule of that table). Breaks if one side is tuned alone."""
    from civulator.config import CFG
    cfg = CFG["map"]["earthlike"]
    for key in tiered_resources.PARAM_KEYS:
        assert cfg[key] == earthlike.DEFAULT_PARAMS[key], key


_STAGE_CODE = (
    "import sys; sys.path.insert(0, {root!r}); sys.path.insert(0, {tests!r})\n"
    "from test_mapgen_golden import PINNED_PARAMS\n"
    "from civulator.mapgen import generate\n"
    "md = generate(7, (18, 36), num_players=4, params=PINNED_PARAMS)\n"
    "print(repr(md.resource.tolist()))\n"
)


def test_the_stage_is_deterministic_in_process():
    """Same seed, same params -> the same resource grid. Breaks if the stage
    draws from a stream or reads mutable global state."""
    a = generate(7, (18, 36), num_players=4, params=PINNED_PARAMS).resource
    b = generate(7, (18, 36), num_players=4, params=PINNED_PARAMS).resource
    assert a.tolist() == b.tolist()


@pytest.mark.parametrize("hash_seed", ["1", "2"])
def test_the_stage_does_not_depend_on_the_hash_seed(hash_seed):
    """A fresh process with another PYTHONHASHSEED places exactly the same
    resources. Breaks if a set of tiles or names decides an order."""
    code = _STAGE_CODE.format(root=ROOT_DIR, tests=TESTS_DIR)
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONHASHSEED": hash_seed}, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    here = generate(7, (18, 36), num_players=4, params=PINNED_PARAMS).resource.tolist()
    assert run.stdout.strip() == repr(here)
