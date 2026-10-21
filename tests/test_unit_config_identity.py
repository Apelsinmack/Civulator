"""Bit-identity gate for issue #64 (combat/unit constants -> config.toml).

Issue #64 moved the five per-unit-type data tables, the class-advantage and
ranged modifiers, the fortification bonuses, the health-penalty coefficient,
the damage formula constants, the healing amounts, and the city health/
defense numbers out of civulator/game/unit.py and civulator/game/city.py
Python literals into config.toml ([units.*], [combat], [city]), interpreted
by the new civulator/unit_model.py.

This file is the oracle that the move changed NOTHING. Every value below is
a HARDCODED LITERAL, copied from the pre-#64 source — it does NOT read
config.toml or civulator.unit_model for its expected values, because a test
that compared config against itself would prove nothing. If a number here
ever needs to change, that is a deliberate balance change (and must be
called out as one, with CHANGELOG + measured effects per CLAUDE.md), never
a side effect of a refactor.

#116 P3 extends the gate to the class table. The three name-keyed modifier
constants (`anti_cavalry_bonus`, `melee_vs_spearman_bonus`,
`archer_vs_horseman_penalty`) became `[combat] class_bonuses` rows keyed on
`combat_class`, and the old tests that pinned those constants are replaced by
`EXPECTED_PAIR_STRENGTH` below: the literal combat and ranged strength of every
ordered pairing of the seven units that existed before the patch (the Slinger
included), copied from a run of the engine BEFORE the patch and
cross-checked by hand (Warrior 20 + 5 vs Spearman = 25; Spearman 25 + 10 vs
Horseman = 35; Archer 25 - 5 vs Horseman = 20; the Slinger no penalty). The
other half of the gate is `scripts/matchup_matrix.py --units Warrior Slinger
Archer Swordsman Spearman Horseman Catapult` with one seed, identical before and
after (CHANGELOG, #116 P3).
"""

import math

import pytest

from civulator.game.unit import Unit
from civulator.game.city import City, _create_unit
from civulator import unit_model

from test_combat_range import make_flat_env


# --- 1. The five per-unit-type data tables ---

EXPECTED_MAX_MOVEMENT = {
    "Warrior": 2,
    "Archer": 2,
    "Swordsman": 2,
    "Spearman": 2,
    "Horseman": 4,
    "Settler": 2,
    "Worker": 2,
    "Catapult": 2,
}

EXPECTED_BASE_COMBAT_STRENGTH = {
    "Warrior": 20,
    "Archer": 15,
    "Swordsman": 35,
    "Spearman": 25,
    "Horseman": 35,
    "Settler": 0,
    "Worker": 0,
    "Catapult": 23,
}

EXPECTED_BASE_RANGED_STRENGTH = {
    "Archer": 25,
    "Catapult": 35,
    "Warrior": 0,
    "Swordsman": 0,
    "Spearman": 0,
    "Horseman": 0,
    "Settler": 0,
    "Worker": 0,
}

EXPECTED_RANGE_VALUES = {
    "Archer": 2,
    "Catapult": 2,
    "Warrior": 1,
    "Swordsman": 1,
    "Spearman": 1,
    "Horseman": 1,
    "Settler": 0,
    "Worker": 0,
}

EXPECTED_PRODUCTION_COST = {
    "Warrior": 40,
    "Archer": 60,
    "Swordsman": 90,
    "Spearman": 65,
    "Horseman": 80,
    "Settler": 120,
    "Worker": 50,
    "Catapult": 120,
}


def _assert_pins_hold(actual, expected, label):
    """Every unit type #64 moved must still carry the value it moved with.

    Deliberately a subset check, not dict equality (changed 2026-09-05 when
    #67 added the Slinger): #64's claim is that the *move* changed nothing,
    which is a claim about the units that existed when it landed. A later
    rule change that adds a NEW unit type must not have to edit this oracle
    to stay green — but it must also not be able to alter a pinned value
    without this file failing, which the per-key comparison below preserves.
    """
    for name, value in expected.items():
        assert name in actual, f"{label}: unit type {name!r} disappeared"
        assert actual[name] == value, (
            f"{label}: {name} is {actual[name]}, pinned at {value} by #64"
        )


def test_max_movement_table_unchanged():
    _assert_pins_hold(Unit.MAX_MOVEMENT, EXPECTED_MAX_MOVEMENT, "MAX_MOVEMENT")
    _assert_pins_hold(unit_model.MAX_MOVEMENT, EXPECTED_MAX_MOVEMENT, "MAX_MOVEMENT")


def test_base_combat_strength_table_unchanged():
    _assert_pins_hold(
        Unit.BASE_COMBAT_STRENGTH, EXPECTED_BASE_COMBAT_STRENGTH, "BASE_COMBAT_STRENGTH"
    )
    _assert_pins_hold(
        unit_model.BASE_COMBAT_STRENGTH, EXPECTED_BASE_COMBAT_STRENGTH, "BASE_COMBAT_STRENGTH"
    )


def test_base_ranged_strength_table_unchanged():
    _assert_pins_hold(
        Unit.BASE_RANGED_STRENGTH, EXPECTED_BASE_RANGED_STRENGTH, "BASE_RANGED_STRENGTH"
    )
    _assert_pins_hold(
        unit_model.BASE_RANGED_STRENGTH, EXPECTED_BASE_RANGED_STRENGTH, "BASE_RANGED_STRENGTH"
    )


def test_range_values_table_unchanged():
    _assert_pins_hold(Unit.RANGE_VALUES, EXPECTED_RANGE_VALUES, "RANGE_VALUES")
    _assert_pins_hold(unit_model.RANGE_VALUES, EXPECTED_RANGE_VALUES, "RANGE_VALUES")


def test_production_cost_table_unchanged():
    _assert_pins_hold(Unit.PRODUCTION_COST, EXPECTED_PRODUCTION_COST, "PRODUCTION_COST")
    _assert_pins_hold(unit_model.PRODUCTION_COST, EXPECTED_PRODUCTION_COST, "PRODUCTION_COST")


# --- 2-7. Combat formula / modifier constants ---


# Every ordered pairing of the seven pre-#116-P3 units, flat Plains, full
# health, unfortified, nobody flanking. Value = (the attacker's combat strength
# when it ATTACKS the defender, the same unit's combat strength when it
# DEFENDS against it, the attacker's ranged strength against it). Combat
# strength carries a class bonus in BOTH roles (#63) and never the ranged-only
# archer penalty; ranged strength is the shooter's alone.
EXPECTED_PAIR_STRENGTH = {
    ("Warrior", "Warrior"): (20, 20, 0),
    ("Warrior", "Slinger"): (20, 20, 0),
    ("Warrior", "Archer"): (20, 20, 0),
    ("Warrior", "Swordsman"): (20, 20, 0),
    ("Warrior", "Spearman"): (25, 25, 0),
    ("Warrior", "Horseman"): (20, 20, 0),
    ("Warrior", "Catapult"): (20, 20, 0),
    ("Slinger", "Warrior"): (5, 5, 15),
    ("Slinger", "Slinger"): (5, 5, 15),
    ("Slinger", "Archer"): (5, 5, 15),
    ("Slinger", "Swordsman"): (5, 5, 15),
    ("Slinger", "Spearman"): (5, 5, 15),
    ("Slinger", "Horseman"): (5, 5, 15),
    ("Slinger", "Catapult"): (5, 5, 15),
    ("Archer", "Warrior"): (15, 15, 25),
    ("Archer", "Slinger"): (15, 15, 25),
    ("Archer", "Archer"): (15, 15, 25),
    ("Archer", "Swordsman"): (15, 15, 25),
    ("Archer", "Spearman"): (15, 15, 25),
    ("Archer", "Horseman"): (15, 15, 20),
    ("Archer", "Catapult"): (15, 15, 25),
    ("Swordsman", "Warrior"): (35, 35, 0),
    ("Swordsman", "Slinger"): (35, 35, 0),
    ("Swordsman", "Archer"): (35, 35, 0),
    ("Swordsman", "Swordsman"): (35, 35, 0),
    ("Swordsman", "Spearman"): (40, 40, 0),
    ("Swordsman", "Horseman"): (35, 35, 0),
    ("Swordsman", "Catapult"): (35, 35, 0),
    ("Spearman", "Warrior"): (25, 25, 0),
    ("Spearman", "Slinger"): (25, 25, 0),
    ("Spearman", "Archer"): (25, 25, 0),
    ("Spearman", "Swordsman"): (25, 25, 0),
    ("Spearman", "Spearman"): (25, 25, 0),
    ("Spearman", "Horseman"): (35, 35, 0),
    ("Spearman", "Catapult"): (25, 25, 0),
    ("Horseman", "Warrior"): (35, 35, 0),
    ("Horseman", "Slinger"): (35, 35, 0),
    ("Horseman", "Archer"): (35, 35, 0),
    ("Horseman", "Swordsman"): (35, 35, 0),
    ("Horseman", "Spearman"): (35, 35, 0),
    ("Horseman", "Horseman"): (35, 35, 0),
    ("Horseman", "Catapult"): (35, 35, 0),
    ("Catapult", "Warrior"): (23, 23, 35),
    ("Catapult", "Slinger"): (23, 23, 35),
    ("Catapult", "Archer"): (23, 23, 35),
    ("Catapult", "Swordsman"): (23, 23, 35),
    ("Catapult", "Spearman"): (23, 23, 35),
    ("Catapult", "Horseman"): (23, 23, 35),
    ("Catapult", "Catapult"): (23, 23, 35),
}

# Ranged strength against a CITY (the flat -17 for every ranged unit that is
# not in the siege class; the Slinger's 15 - 17 floors at 0).
EXPECTED_RANGED_VS_CITY = {
    "Warrior": 0,
    "Slinger": 0,
    "Archer": 8,
    "Swordsman": 0,
    "Spearman": 0,
    "Horseman": 0,
    "Catapult": 35,
}


def _stand(env, unit_type, player_index, coordinates):
    """A real unit of `unit_type` standing on the board for `player_index`."""
    unit = _create_unit(unit_type, env.players[player_index], coordinates)
    unit.player.units.append(unit)
    env.add_unit_to_tile(unit, coordinates)
    return unit


@pytest.mark.parametrize("attacker_type,defender_type", sorted(EXPECTED_PAIR_STRENGTH))
def test_every_pre_class_table_pairing_keeps_its_strengths(attacker_type, defender_type):
    """The #116 P3 gate: the class table reproduces every v0.7 number. Pinned
    per ordered pair, both roles, both strengths. Breaks if a class_bonuses
    row, the combat_class of a pre-existing unit, or the modifier code changes
    what any existing unit is worth against any other."""
    env = make_flat_env()
    attacker = _stand(env, attacker_type, 0, (3, 3))
    defender = _stand(env, defender_type, 1, (3, 4))

    attacking, defending, ranged = EXPECTED_PAIR_STRENGTH[(attacker_type, defender_type)]
    assert attacker.get_combat_strength(True, defender) == attacking
    assert attacker.get_combat_strength(False, defender) == defending
    assert attacker.get_ranged_strength(defender) == ranged


@pytest.mark.parametrize("unit_type", sorted(EXPECTED_RANGED_VS_CITY))
def test_ranged_strength_against_a_city_keeps_its_siege_exemption(unit_type):
    """The flat ranged-vs-city penalty (17) reaches every ranged unit except
    the siege class, which is now declared by `combat_class = "siege"`. Breaks
    if the Catapult loses its exemption or another unit gains one."""
    env = make_flat_env()
    city = env.create_city(env.players[1], (6, 12), "Enemy")
    unit = _stand(env, unit_type, 0, (3, 3))
    assert unit.get_ranged_strength(city, is_city=True) == EXPECTED_RANGED_VS_CITY[unit_type]


def test_ranged_city_penalty_unchanged():
    """Item 3: the flat -17 vs cities."""
    assert unit_model.RANGED_CITY_PENALTY == 17


def test_fortification_bonuses_unchanged():
    """Item 4: 3 at fortification level 1, 6 at level 2 ("otherwise")."""
    assert unit_model.FORTIFICATION_BONUS[1 - 1] == 3
    assert unit_model.FORTIFICATION_BONUS[2 - 1] == 6


def test_health_penalty_coefficient_unchanged_and_shared():
    """Item 5: the -10 in -10 * (100 - hp) / 100, one value for both melee
    and ranged strength (must be the SAME config value, not two copies)."""
    assert unit_model.HP_PENALTY_COEFFICIENT == -10


def test_damage_formula_constants_unchanged():
    """Item 6: base 30, exponent coefficient 0.04, roll range (0.8, 1.2)."""
    assert unit_model.DAMAGE_BASE == 30
    assert unit_model.DAMAGE_EXPONENT_COEFFICIENT == 0.04
    assert unit_model.DAMAGE_ROLL_MIN == 0.8
    assert unit_model.DAMAGE_ROLL_MAX == 1.2


def test_healing_amounts_unchanged():
    """Item 7: 20 HP fortified, 10 HP otherwise."""
    assert unit_model.HEAL_FORTIFIED == 20
    assert unit_model.HEAL_NORMAL == 10


# --- 8. City health / defense strength ---


def test_city_health_and_defense_strength_unchanged():
    assert unit_model.CITY_HEALTH == 200
    assert unit_model.CITY_DEFENSE_STRENGTH == 20


def test_city_instance_carries_the_unchanged_numbers():
    """E2E: a real City still gets health=200, defense_strength=20."""
    city = City(player=None, coordinates=(0, 0), name="Test City")
    assert city.health == 200
    assert city.defense_strength == 20


# --- End-to-end cross-check: the damage formula itself, at a fixed roll ---


def test_calculate_damage_formula_reproduces_hardcoded_civ6_formula():
    """Pins the whole formula, not just its constants, against a literal
    re-derivation: Damage(HP) = 30 * e^(0.04 * diff) * roll, roll fixed at 1.0
    (midpoint of neither bound, but exercised without RNG) via a stub."""

    class _FixedRNG:
        def uniform(self, lo, hi):
            assert (lo, hi) == (0.8, 1.2)
            return 1.0

    unit = Unit(player=None, coordinates=(0, 0), unit_type="Warrior")
    damage = unit.calculate_damage(attacker_strength=50, defender_strength=20, rng=_FixedRNG())

    expected = 30 * math.exp(0.04 * (50 - 20)) * 1.0
    assert damage == max(1, min(100, expected))
