"""Issue #66: the flat -17 vs cities punished the one class Civ 6 exempts.

`get_ranged_strength` subtracted a flat 17 from EVERY ranged unit attacking a
city, siege included. That penalty stands in for a wall model we have not
built, and Civ 6 does the opposite: ordinary ranged units do half damage to
walls, and the **siege class does full damage** — that is the class's entire
identity ([City combat
(Civ6)](https://civilization.fandom.com/wiki/City_combat_(Civ6))).

Two things are pinned here:

1. the siege class is exempt from the flat penalty, declared per unit type in
   config.toml rather than by a name in an `if`;
2. `BatteringRam` and `SiegeTower` have complete stats — they had a stacking
   slot and nothing else.

What is deliberately NOT here, because the issue itself scopes it out: the wall
model (city walls as their own HP pool with a per-attacker-class damage
multiplier) and the support units' adjacency mechanic. See the CHANGELOG.
"""

import pytest

from civulator import unit_model
from civulator.agents.build_agent import BUILD_OPTIONS
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.game.city import City, _create_unit
from civulator.game.unit import (
    DEFERRED_BUILD_UNITS,
    MOVEMENT_DOMAIN,
    UNIT_SLOT,
    ArcherUnit,
    BatteringRamUnit,
    CatapultUnit,
    SiegeSupportUnit,
    SiegeTowerUnit,
    Unit,
)

from test_combat_range import make_flat_env, place


class FixedRoll:
    def uniform(self, lo, hi):
        return 1.0


def make_city(env, coords=(3, 3), walls=False, player_index=1):
    player = env.players[player_index]
    city = env.create_city(player, coords, "Test City")
    if walls:
        city.buildings.append("Walls")
    return city


# --- 1. The siege class is exempt from the flat city penalty ---------------


def test_the_catapult_bombards_a_city_at_full_strength():
    env = make_flat_env()
    catapult = place(env, CatapultUnit, 0, (3, 3))

    assert catapult.get_ranged_strength(is_city=True) == 35
    assert catapult.get_ranged_strength(is_city=True) == catapult.get_base_ranged_strength()


def test_an_ordinary_ranged_unit_still_pays_the_penalty():
    """The exemption is for the siege class, not an across-the-board buff."""
    env = make_flat_env()
    archer = place(env, ArcherUnit, 0, (3, 3))

    assert archer.get_ranged_strength(is_city=True) == 25 - unit_model.RANGED_CITY_PENALTY
    assert unit_model.RANGED_CITY_PENALTY == 17


def test_the_exemption_does_not_leak_into_attacks_on_units():
    """The penalty only ever applied against cities; the exemption must not
    quietly change unit-vs-unit ranged combat."""
    env = make_flat_env()
    catapult = place(env, CatapultUnit, 0, (3, 3))
    archer = place(env, ArcherUnit, 0, (5, 5))

    assert catapult.get_ranged_strength(is_city=False) == 35
    assert archer.get_ranged_strength(is_city=False) == 25


def test_siege_class_membership_is_config_declared():
    """CLAUDE.md: no hardcoded gameplay decisions in code. A further siege unit
    must be a config line, not a name added to an `if`. Since #116 P3 the line
    is `combat_class = "siege"` (it was the boolean `siege_class`, which now
    raises as an unknown key): the siege set is exactly the units declaring
    that class, and the Catapult, which defined the class, is in it. Restated
    from `== {"Catapult"}`, which pinned a set designed to grow (the
    Trebuchet joined it in the same patch). Breaks if membership is decided
    anywhere but the class column."""
    from civulator.config import CFG

    declared = {name for name, table in CFG["units"].items() if table["combat_class"] == "siege"}
    assert unit_model.SIEGE_CLASS == declared
    assert "Catapult" in unit_model.SIEGE_CLASS
    with pytest.raises(ValueError, match="unknown key"):
        unit_model.parse_unit_columns({"Probe": {**CFG["units"]["Catapult"], "siege_class": True}})


def test_is_siege_class_is_the_one_query():
    env = make_flat_env()
    assert place(env, CatapultUnit, 0, (3, 3)).is_siege_class()
    assert not place(env, ArcherUnit, 0, (5, 5)).is_siege_class()


# --- The effect: a siege unit is now genuinely the city-breaker ------------


def test_a_catapult_hurts_a_city_far_more_than_an_archer():
    """E2E, same fixed roll: the difference the class exists for."""
    env = make_flat_env()
    env.rng = FixedRoll()

    city_a = make_city(env, (3, 3))
    city_b = make_city(env, (7, 9))

    catapult = place(env, CatapultUnit, 0, (3, 5))
    archer = place(env, ArcherUnit, 0, (7, 11))

    cat_damage, _, _, _ = catapult.attack(city_a, env)
    arc_damage, _, _, _ = archer.attack(city_b, env)

    assert cat_damage > 2 * arc_damage, (
        f"catapult {cat_damage:.1f} vs archer {arc_damage:.1f} against a city"
    )


def test_a_catapult_now_out_damages_its_own_pre_66_self():
    """The regression v0.6.2 accepted and asked #66 to undo: 35 - 17 = 18
    against a bare city's 20 was a deficit; 35 is an advantage."""
    env = make_flat_env()
    env.rng = FixedRoll()
    city = make_city(env, (3, 3))
    catapult = place(env, CatapultUnit, 0, (3, 5))

    exempt_damage, _, _, _ = catapult.attack(city, env)
    penalised = catapult.calculate_damage(35 - 17, 20, rng=FixedRoll())

    assert exempt_damage > penalised
    assert exempt_damage == pytest.approx(catapult.calculate_damage(35, 20, rng=FixedRoll()))


def test_walls_still_blunt_a_catapult():
    """The exemption is not immunity: #7's walls still raise the city's
    defence above the Catapult's strength. That is the shape the wall model in
    the deferred half of #66 is meant to refine, not remove."""
    env = make_flat_env()
    env.rng = FixedRoll()

    bare = make_city(env, (3, 3), walls=False)
    walled = make_city(env, (7, 9), walls=True)

    a = place(env, CatapultUnit, 0, (3, 5))
    b = place(env, CatapultUnit, 0, (7, 11))

    bare_damage, _, _, _ = a.attack(bare, env)
    walled_damage, _, _, _ = b.attack(walled, env)

    assert walled_damage < bare_damage


# --- 2. The two statless units now have stats -------------------------------


@pytest.mark.parametrize("unit_type", ["BatteringRam", "SiegeTower"])
def test_all_six_unit_tables_carry_the_support_unit(unit_type):
    assert unit_type in Unit.MAX_MOVEMENT
    assert unit_type in Unit.BASE_COMBAT_STRENGTH
    assert unit_type in Unit.BASE_RANGED_STRENGTH
    assert unit_type in Unit.RANGE_VALUES
    assert unit_type in Unit.PRODUCTION_COST
    assert unit_type in MOVEMENT_DOMAIN
    assert unit_type in UNIT_SLOT


def test_support_unit_stats_match_the_civ6_reference():
    """Civ 6 support units: combat strength 0, movement 2. Production costs
    from the Civilopedia (standard rules): Battering Ram 65, Siege Tower 100.
    """
    assert Unit.BASE_COMBAT_STRENGTH["BatteringRam"] == 0
    assert Unit.BASE_COMBAT_STRENGTH["SiegeTower"] == 0
    assert Unit.MAX_MOVEMENT["BatteringRam"] == Unit.MAX_MOVEMENT["SiegeTower"] == 2
    assert Unit.PRODUCTION_COST["BatteringRam"] == 65
    assert Unit.PRODUCTION_COST["SiegeTower"] == 100
    assert Unit.BASE_RANGED_STRENGTH["BatteringRam"] == 0
    assert Unit.BASE_RANGED_STRENGTH["SiegeTower"] == 0


def test_support_units_keep_the_siege_support_slot():
    """Slot 2 stacks with a military unit — the stacking design that was
    already done, and the reason the slot exists."""
    assert UNIT_SLOT["BatteringRam"] == UNIT_SLOT["SiegeTower"] == 2

    env = make_flat_env()
    ram = place(env, BatteringRamUnit, 0, (3, 3))
    assert ram.slot == 2


@pytest.mark.parametrize("unit_type,expected_cls", [
    ("BatteringRam", BatteringRamUnit),
    ("SiegeTower", SiegeTowerUnit),
])
def test_create_unit_builds_the_support_class(unit_type, expected_cls):
    unit = _create_unit(unit_type, None, (0, 0))
    assert isinstance(unit, expected_cls)
    assert isinstance(unit, SiegeSupportUnit)
    assert type(unit) is not Unit


@pytest.mark.parametrize("unit_type", ["BatteringRam", "SiegeTower"])
def test_support_units_are_deliberately_not_buildable(unit_type):
    """Their mechanic does not exist yet, so offering them would be a build
    option that cannot pay off. The partition must say so out loud (#67)."""
    assert unit_type in DEFERRED_BUILD_UNITS
    assert unit_type not in BUILD_OPTIONS


@pytest.mark.parametrize("unit_type", ["BatteringRam", "SiegeTower"])
def test_support_units_have_no_encoder_class_channel(unit_type):
    """-1, like the civilians: a new class index would change the channel count
    and invalidate every trained .pth for units nobody can build."""
    assert EnhancedStateEncoder.CLASS_INDEX[unit_type] == -1


@pytest.mark.parametrize("unit_cls", [BatteringRamUnit, SiegeTowerUnit])
def test_support_units_have_no_attack_of_their_own(unit_cls):
    """Combat strength 0 and ranged strength 0: they escort, they do not fight.
    They must not be silently siege units themselves."""
    env = make_flat_env()
    support = place(env, unit_cls, 0, (3, 3))

    assert support.get_base_combat_strength() == 0
    assert support.get_base_ranged_strength() == 0
    assert support.get_ranged_strength(is_city=True) == 0
    assert not support.is_siege_class()


def test_the_deferred_adjacency_mechanic_is_absent_and_says_so():
    """Guard against a half-implemented mechanic: standing a Battering Ram
    beside a city must not change how anything resolves today. When #66's
    second half lands, this test is what it has to change.
    """
    env = make_flat_env()
    env.rng = FixedRoll()

    plain = make_city(env, (3, 3), walls=True)
    supported = make_city(env, (7, 9), walls=True)

    a = place(env, CatapultUnit, 0, (3, 5))
    b = place(env, CatapultUnit, 0, (7, 11))
    place(env, BatteringRamUnit, 0, (7, 10))  # adjacent to the supported city

    plain_damage, _, _, _ = a.attack(plain, env)
    supported_damage, _, _, _ = b.attack(supported, env)

    assert supported_damage == pytest.approx(plain_damage), (
        "a Battering Ram adjacent to a city changes nothing yet — its Civ 6 "
        "adjacency mechanic is the deferred half of #66"
    )
