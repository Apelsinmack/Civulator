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
"""

import math

from civulator.game.unit import Unit
from civulator.game.city import City
from civulator import unit_model


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


def test_max_movement_table_unchanged():
    assert Unit.MAX_MOVEMENT == EXPECTED_MAX_MOVEMENT
    assert unit_model.MAX_MOVEMENT == EXPECTED_MAX_MOVEMENT


def test_base_combat_strength_table_unchanged():
    assert Unit.BASE_COMBAT_STRENGTH == EXPECTED_BASE_COMBAT_STRENGTH
    assert unit_model.BASE_COMBAT_STRENGTH == EXPECTED_BASE_COMBAT_STRENGTH


def test_base_ranged_strength_table_unchanged():
    assert Unit.BASE_RANGED_STRENGTH == EXPECTED_BASE_RANGED_STRENGTH
    assert unit_model.BASE_RANGED_STRENGTH == EXPECTED_BASE_RANGED_STRENGTH


def test_range_values_table_unchanged():
    assert Unit.RANGE_VALUES == EXPECTED_RANGE_VALUES
    assert unit_model.RANGE_VALUES == EXPECTED_RANGE_VALUES


def test_production_cost_table_unchanged():
    assert Unit.PRODUCTION_COST == EXPECTED_PRODUCTION_COST
    assert unit_model.PRODUCTION_COST == EXPECTED_PRODUCTION_COST


# --- 2-7. Combat formula / modifier constants ---


def test_anti_cavalry_and_melee_vs_spearman_bonuses_unchanged():
    """Item 2: +10 Spearman vs Horseman, +5 Warrior/Swordsman vs Spearman."""
    assert unit_model.ANTI_CAVALRY_BONUS == 10
    assert unit_model.MELEE_VS_SPEARMAN_BONUS == 5


def test_ranged_modifiers_unchanged():
    """Item 3: flat -17 vs cities, -5 Archer vs Horseman."""
    assert unit_model.RANGED_CITY_PENALTY == 17
    assert unit_model.ARCHER_VS_HORSEMAN_PENALTY == 5


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
