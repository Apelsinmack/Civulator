"""Tests for scripts/matchup_matrix.py -- the #65 matchup-matrix harness
that MEASURES unit pairings through the real engine instead of deriving
them from config.toml.

Same bare cross-directory import pattern as tests/test_evaluate.py
(tests/conftest.py's own docstring: no `__init__.py` under tests/, and
scripts/ is not a package either).

Coverage, per the #65 issue's own gate:
- the harness runs end-to-end on a tiny configuration
- results are reproducible under a fixed seed
- the matrix is genuinely asymmetric where it should be: a ranged attacker
  takes no counterattack
- the valuable one: the #63 anti-cavalry bonus lands the same whichever
  direction the charge comes from -- the regression gate for #63 expressed
  as a measurement instead of a single unit.attack() call.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

import pytest

import matchup_matrix as mm


def _pairings_by_key(condition):
    return {(p["attacker"], p["defender"]): p for p in condition["pairings"]}


# --- Harness runs end-to-end on a tiny configuration ------------------------


def test_runs_end_to_end_on_tiny_configuration():
    result = mm.run_matrix(units=["Warrior", "Archer"], duels=5, seed=1)

    assert result["units"] == ["Warrior", "Archer"]
    assert result["excluded_civilians"] == ["Settler", "Worker"]
    assert result["duels_per_pairing"] == 5
    assert len(result["conditions"]) == 1  # headline only, no opt-in flags

    headline = result["conditions"][0]
    assert headline["name"] == "headline"
    # 2 units -> 4 ordered pairings (2x2), every one measured.
    assert len(headline["pairings"]) == 4
    for p in headline["pairings"]:
        assert p["duels"] == 5
        assert p["mean_damage_dealt"] > 0  # calculate_damage's own floor is 1 HP


def test_unknown_unit_type_raises():
    with pytest.raises(ValueError):
        mm.run_matrix(units=["Warrior", "Settler"], duels=2, seed=1)


def test_unknown_terrain_raises():
    with pytest.raises(ValueError):
        mm.run_matrix(units=["Warrior"], duels=2, seed=1, terrain=("swamp",))


def test_headline_run_covers_all_36_ordered_pairings():
    result = mm.run_matrix(duels=3, seed=2)
    headline = result["conditions"][0]
    assert set(result["units"]) == set(mm.COMBAT_UNITS)
    assert len(headline["pairings"]) == 36
    seen = {(p["attacker"], p["defender"]) for p in headline["pairings"]}
    assert seen == {(a, d) for a in mm.COMBAT_UNITS for d in mm.COMBAT_UNITS}


# --- Reproducibility (a fixed seed must reproduce the table) ---------------


def test_reproducible_under_fixed_seed():
    kwargs = dict(units=["Warrior", "Horseman", "Catapult"], duels=25, seed=999)
    result_a = mm.run_matrix(**kwargs)
    result_b = mm.run_matrix(**kwargs)
    assert result_a == result_b


def test_different_seed_changes_the_numbers():
    kwargs = dict(units=["Warrior", "Horseman"], duels=25)
    result_a = mm.run_matrix(seed=111, **kwargs)
    result_b = mm.run_matrix(seed=222, **kwargs)
    assert result_a["conditions"][0]["pairings"] != result_b["conditions"][0]["pairings"]


# --- Ranged asymmetry: the whole point of #65 ("A->B and B->A differ") ----


def test_ranged_attacker_takes_no_counterattack():
    """Archer attacking a melee unit must show zero mean damage taken --
    the engine's is_ranged branch never runs a counterattack."""
    result = mm.run_matrix(units=["Warrior", "Archer"], duels=50, seed=3)
    pairings = _pairings_by_key(result["conditions"][0])

    archer_attacks_warrior = pairings[("Archer", "Warrior")]
    assert archer_attacks_warrior["mean_damage_taken"] == 0.0
    assert archer_attacks_warrior["mean_damage_dealt"] > 0
    assert archer_attacks_warrior["exchange_ratio"] is None
    assert archer_attacks_warrior["cost_normalized_ratio"] is None


def test_melee_attacker_of_a_ranged_unit_still_takes_a_counter():
    """The mirror cell: a Warrior charging an Archer is melee, so the
    Archer counterattacks with its (non-zero) melee combat_strength -- the
    asymmetry is specifically about who is ATTACKING, not which unit type
    is involved."""
    result = mm.run_matrix(units=["Warrior", "Archer"], duels=50, seed=3)
    pairings = _pairings_by_key(result["conditions"][0])

    warrior_attacks_archer = pairings[("Warrior", "Archer")]
    assert warrior_attacks_archer["mean_damage_taken"] > 0
    assert warrior_attacks_archer["exchange_ratio"] is not None


def test_catapult_also_takes_no_counterattack():
    result = mm.run_matrix(units=["Spearman", "Catapult"], duels=50, seed=4)
    pairings = _pairings_by_key(result["conditions"][0])
    assert pairings[("Catapult", "Spearman")]["mean_damage_taken"] == 0.0


# --- #63 regression gate: anti-cavalry bonus must land in BOTH directions -


def test_spearman_horseman_exchange_is_symmetric_in_the_matrix():
    """The measurement-level twin of tests/test_combat_class_bonus.py.

    Post-#63, Spearman (25 + 10 anti-cavalry) vs Horseman (35) is a dead
    level 35 vs 35 fight in EITHER direction, so the mean damage dealt by
    Horseman->Spearman and by Spearman->Horseman should land in the same
    24.0-36.0 band (0.8-1.2 roll around a mean of 30.0, config.toml
    [combat] damage_roll_min/max) and be close to each other. The bug this
    guards against (#63: class bonuses gated behind is_attacking) would
    show up here as a HORSEMAN->SPEARMAN mean far above that band (~46.6,
    see test_combat_class_bonus.py) while SPEARMAN->HORSEMAN stayed
    correct -- i.e. as a visibly asymmetric matrix.
    """
    result = mm.run_matrix(units=["Spearman", "Horseman"], duels=300, seed=5)
    pairings = _pairings_by_key(result["conditions"][0])

    horseman_to_spearman = pairings[("Horseman", "Spearman")]["mean_damage_dealt"]
    spearman_to_horseman = pairings[("Spearman", "Horseman")]["mean_damage_dealt"]

    for mean_damage in (horseman_to_spearman, spearman_to_horseman):
        assert 24.0 <= mean_damage <= 36.0, (
            f"mean damage {mean_damage:.1f} outside the dead-even 35v35 band -- "
            "the anti-cavalry bonus may not be applying symmetrically (#63)"
        )

    # 300 duels/pairing keeps the two means' sampling noise well under the
    # gap (~16.6 HP) between the correct (~30.0) and buggy (~46.6) values.
    assert abs(horseman_to_spearman - spearman_to_horseman) < 5.0, (
        f"Horseman->Spearman ({horseman_to_spearman:.1f}) and Spearman->Horseman "
        f"({spearman_to_horseman:.1f}) disagree by more than sampling noise "
        "explains -- the anti-cavalry bonus is not landing the same in both "
        "directions (#63)"
    )


# --- Conditions (opt-in flags each add one matrix, one variable at a time) -


def test_condition_flags_each_add_exactly_one_matrix():
    result = mm.run_matrix(
        units=["Warrior", "Spearman"], duels=5, seed=6,
        terrain=("flat", "hills"), fortified=True, damaged=True,
    )
    names = [c["name"] for c in result["conditions"]]
    assert names == ["headline", "terrain=hills", "fortified", "damaged"]


def test_fortified_condition_only_changes_the_defender():
    """Fortification bonus only ever applies on defence
    (Unit.get_combat_strength gates it behind `not is_attacking`), so a
    fortified defender must take LESS damage than the unfortified headline,
    for a melee attacker where the counterattack channel is unaffected."""
    baseline = mm.run_matrix(units=["Warrior", "Spearman"], duels=200, seed=8)
    fortified = mm.run_matrix(
        units=["Warrior", "Spearman"], duels=200, seed=8, fortified=True,
    )
    base_pairing = _pairings_by_key(baseline["conditions"][0])[("Warrior", "Spearman")]
    fort_pairing = _pairings_by_key(fortified["conditions"][1])[("Warrior", "Spearman")]

    assert fort_pairing["mean_damage_dealt"] < base_pairing["mean_damage_dealt"]


def test_damaged_condition_applies_to_both_sides():
    """--damaged is documented (module docstring) as setting BOTH units to
    half HP -- a raised HP_PENALTY_COEFFICIENT term on both sides of a
    mirror match should roughly cancel, leaving the mean exchange ratio
    close to the undamaged mirror match's ratio (both ~1.0, Warrior vs
    Warrior)."""
    baseline = mm.run_matrix(units=["Warrior"], duels=300, seed=9)
    damaged = mm.run_matrix(units=["Warrior"], duels=300, seed=9, damaged=True)

    base_ratio = baseline["conditions"][0]["pairings"][0]["exchange_ratio"]
    damaged_ratio = damaged["conditions"][1]["pairings"][0]["exchange_ratio"]

    assert base_ratio == pytest.approx(1.0, abs=0.15)
    assert damaged_ratio == pytest.approx(1.0, abs=0.15)


# --- Scenario geometry (canonical hex math, never hand-derived) -----------


def test_scenario_positions_have_the_intended_hex_distance():
    from civulator.game.environment import GameEnvironment

    env = GameEnvironment(mm.BOARD_ROWS, mm.BOARD_COLS, num_players=2, map_type="basic", seed=1)
    mm._verify_geometry(env)  # must not raise
    assert env.map.distance_function(mm.ATK_MELEE, mm.DEF_MELEE) == 1
    assert env.map.distance_function(mm.ATK_RANGED, mm.DEF_RANGED) == 2


# --- Cost-normalised ratio formula (module docstring's judgment call) ------


def test_cost_normalized_ratio_matches_its_documented_formula():
    result = mm.run_matrix(units=["Spearman", "Horseman"], duels=50, seed=10)
    pairing = _pairings_by_key(result["conditions"][0])[("Spearman", "Horseman")]

    from civulator.unit_model import PRODUCTION_COST

    expected = (
        pairing["mean_damage_dealt"] / PRODUCTION_COST["Spearman"]
    ) / (
        pairing["mean_damage_taken"] / PRODUCTION_COST["Horseman"]
    )
    assert pairing["cost_normalized_ratio"] == pytest.approx(expected)
