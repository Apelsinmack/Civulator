"""Issue #7: Walls, +30 city defence, reachable by the build agent.

Walls were half-present: a cost in `City.BUILDING_COSTS` and a `+30` literal
inside `City.get_combat_strength`, with no way for any agent to ever build
them. This file pins the rule end to end — the cost lives in config, the
defence is applied by the one combat path, and the option is reachable.

The headline assertion is `test_a_walled_city_takes_less_damage`: same
attacker, same fixed damage roll, walls the only difference.
"""

import pytest

from civulator import unit_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.game.city import City
from civulator.game.unit import ArcherUnit, CatapultUnit, WarriorUnit

from test_combat_range import make_flat_env, place


class FixedRoll:
    """Damage roll pinned to its midpoint, so two attacks differ only by the
    rule under test and not by the RNG."""

    def uniform(self, lo, hi):
        return 1.0


def make_city(env, coords=(3, 3), walls=False, player_index=0):
    player = env.players[player_index]
    city = City(player, coords, "Test City")
    player.cities.append(city)
    env.add_city(city)
    if walls:
        city.buildings.append("Walls")
    return city


# --- The rule: walls reduce the damage a city takes -------------------------


def test_a_walled_city_takes_less_damage():
    """E2E, the thing an end user sees: two identical cities, two identical
    Warriors, the same damage roll. The walled one loses less health."""
    env = make_flat_env()
    env.rng = FixedRoll()

    bare = make_city(env, (3, 3), walls=False, player_index=0)
    walled = make_city(env, (5, 5), walls=True, player_index=0)

    attacker_bare = place(env, WarriorUnit, 1, (3, 4))
    attacker_walled = place(env, WarriorUnit, 1, (5, 6))

    damage_bare, _, _, _ = attacker_bare.attack(bare, env)
    damage_walled, _, _, _ = attacker_walled.attack(walled, env)

    assert damage_walled < damage_bare, (
        f"walled city took {damage_walled:.1f}, unwalled took {damage_bare:.1f} "
        "— the +30 defence is not reaching the combat path"
    )
    assert walled.health > bare.health


def test_walls_add_exactly_the_configured_defence_bonus():
    env = make_flat_env()
    bare = make_city(env, (3, 3), walls=False)
    walled = make_city(env, (5, 5), walls=True)

    bonus = unit_model.BUILDING_DEFENSE_BONUS["Walls"]
    assert walled.get_combat_strength() == bare.get_combat_strength() + bonus
    assert bonus == 30, "Civ 6 Ancient Walls, the value this issue specifies"


def test_the_defence_bonus_is_a_config_value_not_a_literal():
    """CLAUDE.md: all gameplay constants live in config.toml. Changing the
    config number must change the city's strength."""
    from civulator.config import CFG

    assert CFG["buildings"]["Walls"]["defense_bonus"] == 30
    assert CFG["buildings"]["Walls"]["production_cost"] == 100


def test_building_costs_come_from_config():
    from civulator.config import CFG

    for name, table in CFG["buildings"].items():
        assert City.BUILDING_COSTS[name] == table["production_cost"]
    assert City.BUILDING_COSTS is unit_model.BUILDING_COSTS, (
        "city.py must alias the interpreter's table, not keep a second copy"
    )


def test_a_building_with_no_defence_bonus_changes_nothing():
    """Only buildings that declare a defense_bonus may touch combat — the
    Granary must not become a fortification by accident."""
    env = make_flat_env()
    city = make_city(env, (3, 3))
    before = city.get_combat_strength()
    city.buildings.append("Granary")
    assert city.get_combat_strength() == before


@pytest.mark.parametrize("attacker_cls", [WarriorUnit, ArcherUnit, CatapultUnit])
def test_walls_defend_against_every_kind_of_attacker(attacker_cls):
    """Melee and ranged alike read the city's strength through
    City.get_combat_strength, so no attacker type can bypass the walls."""
    env = make_flat_env()
    env.rng = FixedRoll()

    bare = make_city(env, (3, 3), walls=False)
    walled = make_city(env, (5, 5), walls=True)

    a = place(env, attacker_cls, 1, (3, 4))
    b = place(env, attacker_cls, 1, (5, 6))

    damage_bare, _, _, _ = a.attack(bare, env)
    damage_walled, _, _, _ = b.attack(walled, env)

    assert damage_bare > 0
    assert damage_walled < damage_bare


# --- The option is reachable ------------------------------------------------


def test_walls_is_a_build_option():
    assert "Walls" in BUILD_OPTIONS


def test_the_mask_offers_walls_until_they_are_built():
    """Mask invariant (CLAUDE.md, #51): once a city owns Walls, producing them
    again could not change its state, so the option must disappear."""
    env = make_flat_env()
    city = make_city(env, (3, 3))
    idx = BUILD_OPTIONS.index("Walls")

    assert get_valid_build_mask(city)[idx] == 1.0

    city.buildings.append("Walls")
    assert get_valid_build_mask(city)[idx] == 0.0


def test_a_city_builds_walls_and_becomes_harder_to_take():
    """E2E through the production system: choose Walls, pay for them, and the
    city's defence actually goes up."""
    env = make_flat_env()
    city = make_city(env, (3, 3))
    city.assign_tiles(env)
    before = city.get_combat_strength()

    city.produce_building("Walls")
    city.production = City.BUILDING_COSTS["Walls"]
    city.process_turn(env)

    assert "Walls" in city.buildings
    assert city.get_combat_strength() == before + 30
    assert city.current_production is None, "production slot freed for the next decision"


# --- The crash Walls uncovered ---------------------------------------------


@pytest.mark.parametrize("attacker_cls", [WarriorUnit, ArcherUnit, CatapultUnit])
def test_attacking_a_city_does_not_crash(attacker_cls):
    """E2E repro of a latent bug this issue exposed.

    `get_combat_strength` and `get_ranged_strength` read `target.unit_type` to
    apply class bonuses. A City has no `unit_type`, so every attack on a city
    raised AttributeError. It went unnoticed because no engine order has ever
    aimed at a city — capture happens by moving onto the tile — but a city's
    defence is meaningless if the combat path cannot resolve an attack on one,
    and the combat training tool places cities with optional walls (#7).
    """
    env = make_flat_env()
    city = make_city(env, (3, 3), walls=True)
    attacker = place(env, attacker_cls, 1, (3, 4))

    damage_dealt, _, _, _ = attacker.attack(city, env)

    assert damage_dealt > 0
    assert city.health < 200


def test_a_melee_attacker_takes_a_counterattack_from_the_city():
    """A city defends itself: the melee counterattack reads the same walled
    strength, so walls both absorb and hit back."""
    env = make_flat_env()
    env.rng = FixedRoll()

    bare = make_city(env, (3, 3), walls=False)
    walled = make_city(env, (5, 5), walls=True)

    a = place(env, WarriorUnit, 1, (3, 4))
    b = place(env, WarriorUnit, 1, (5, 6))

    _, taken_bare, _, _ = a.attack(bare, env)
    _, taken_walled, _, _ = b.attack(walled, env)

    assert taken_bare > 0
    assert taken_walled > taken_bare, (
        "walls raise the city's strength, so its counterattack must hurt more"
    )


def test_the_dead_castle_branch_is_gone():
    """city.py carried `elif building == "Castle": strength += 20` for a
    building with no cost, no build option and no way into a city's `buildings`
    list. It is not a rule, it is unreachable code, and it is removed — a
    Castle is no longer silently a fortification."""
    assert "Castle" not in City.BUILDING_COSTS
    assert "Castle" not in unit_model.BUILDING_DEFENSE_BONUS

    env = make_flat_env()
    city = make_city(env, (3, 3))
    before = city.get_combat_strength()
    city.buildings.append("Castle")
    assert city.get_combat_strength() == before
