"""Issue #116 P3: combat classes, `[combat] class_bonuses`, the six new units and
the Trader (docs/progression_design.md §6.1-§6.3, §14 rows "Class bonuses" and
"CLASS_INDEX is derived", and "v2 fixes": "Combat classes and the bit-identity
gate").

What is pinned here is the RULE each class member obeys, never the roster: no
test lists the units, counts them or fixes their order, because units are
designed to grow. Every existing pairing's numbers are pinned by the literal
table in test_unit_config_identity.py; this file pins the mechanism behind
them and the new content built on it.

The mechanism, in one paragraph: every `[units.*]` table declares a
`combat_class`; `[combat] class_bonuses` rows say which class (or single
unit) gets how much against which; `strength = "combat"` rows are read by
`Unit.get_combat_strength` in both roles, `strength = "ranged"` rows only by
`Unit.get_ranged_strength`, for the shooter. No combat rule names a unit.
"""

import ast
import inspect
import os
import sys
import textwrap

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

import matchup_matrix  # noqa: E402  (scripts/ is not a package; same pattern as test_matchup_matrix)

from civulator import unit_model
from civulator.agents.build_agent import BUILD_OPTIONS
from civulator.agents.state_encoders import (
    CLASS_CHANNEL,
    UNIT_CLASS_INDEX,
    EnhancedStateEncoder,
    _ENCODER_REGISTRY,
    get_encoder,
)
from civulator.config import CFG
from civulator.game.city import UNIT_CLASSES, City, _create_unit
from civulator.game.environment import GameEnvironment
from civulator.game.unit import (
    DEFERRED_BUILD_UNITS,
    MOVEMENT_DOMAIN,
    UNIT_SLOT,
    RangedUnit,
    Unit,
)
from civulator.research_model import ERAS
from civulator.unit_model import ClassBonus

from conftest import grant_all, stand
from test_combat_range import make_flat_env


# --- the class table is total and validated ----------------------------------------


def test_every_unit_declares_a_known_class_and_era():
    """Every configured unit has a combat class and an era, and the class
    registry covers exactly the configured units. Breaks if a unit table
    omits either column or the registry drifts from `[units.*]`."""
    assert set(unit_model.COMBAT_CLASS) == set(CFG["units"]) == set(unit_model.UNIT_ERA)
    for name in CFG["units"]:
        assert unit_model.COMBAT_CLASS[name] in unit_model.COMBAT_CLASSES
        assert unit_model.UNIT_ERA[name] in ERAS


def test_a_unit_class_agrees_with_the_unit_stats():
    """A class is a promise about a unit's attack: civilians and support units
    do not fight, a ranged, siege or naval ranged (v0.9.0 Q5) unit has a
    ranged strength, every other class fights in melee. `can_capture_city` and ZoC read the strengths, so a
    class that disagrees with them would be a unit the rules treat two ways.
    Breaks if a table is given a class its numbers contradict."""
    for name, cls in unit_model.COMBAT_CLASS.items():
        combat = unit_model.BASE_COMBAT_STRENGTH[name]
        ranged = unit_model.BASE_RANGED_STRENGTH[name]
        if cls in ("civilian", "support"):
            assert combat == 0 and ranged == 0, name
        elif cls in ("ranged", "siege", "naval_ranged"):
            assert ranged > 0 and combat > 0, name
        else:
            assert ranged == 0 and combat > 0, name


def test_a_unit_slot_follows_its_class():
    """Civilians stack in slot 1, siege support in slot 2, every fighting unit
    (the Catapult and Trebuchet included) in slot 0. Breaks if a new unit's
    UNIT_SLOT entry disagrees with its class."""
    expected = {"civilian": 1, "support": 2}
    for name, cls in unit_model.COMBAT_CLASS.items():
        assert UNIT_SLOT[name] == expected.get(cls, 0), name


def _probe(**extra):
    """A valid one-unit config: the Warrior's table without its upgrade (the
    probe has no Swordsman to upgrade into), with `extra` overrides."""
    table = {k: v for k, v in CFG["units"]["Warrior"].items() if k != "upgrades_to"}
    table.update(extra)
    return {"Probe": table}


def _probe_without(*columns):
    units = _probe()
    for column in columns:
        del units["Probe"][column]
    return units


def test_the_probe_unit_table_is_valid():
    """Positive control for the malformed-table cases below: each of them
    differs from this table in exactly one column."""
    columns = unit_model.parse_unit_columns(_probe())
    assert columns["combat_class"] == {"Probe": "melee"}


@pytest.mark.parametrize("units_cfg,reason", [
    (_probe_without("combat_class"), "`combat_class` is required"),
    (_probe_without("era"), "`era` is required"),
    (_probe_without("maintenance"), "`maintenance` is required"),   # no silently free unit
    (_probe(combat_class="wizard"), "combat_class 'wizard'"),
    (_probe(era="Stone"), "era 'Stone'"),
    (_probe(maintenance=-1), "maintenance must be >= 0"),
    (_probe(maintenance=0.25), "not a multiple of 0.1"),
    (_probe(purchasable="gold"), "purchasable must be a list"),
    (_probe(purchasable=["gold", "gold"]), "purchasable must be a list"),
    (_probe(purchasable=["silver"]), "purchasable must be a list"),
    (_probe(upgrades_to="Nowhere"), "is not a unit type"),
    (_probe(upgrades_to="Probe"), "loops back"),
    (_probe(siege_class=True), "unknown key"),                     # the retired column
    (_probe(combat_clas="melee"), "unknown key"),                  # a typo'd column
    ({"melee": dict(_probe()["Probe"])}, "named like a combat class"),
    ({"A": {**_probe()["Probe"], "upgrades_to": "B"},
      "B": {**_probe()["Probe"], "upgrades_to": "A"}}, "loops back"),
])
def test_a_malformed_unit_column_raises_at_load(units_cfg, reason):
    """Every new column is validated by `unit_model.parse_unit_columns`, each
    case for its own reason: required columns, names, vocabularies, tenths and
    upgrade loops. Breaks if the loader accepts a table it cannot interpret and
    leaves the unit silently mis-classed, free or un-upgradable."""
    with pytest.raises(ValueError, match=reason):
        unit_model.parse_unit_columns(units_cfg)


def test_the_unit_columns_parse_into_their_tables():
    """`maintenance` is stored in int tenths (nonzero entries only, like
    BUILDING_MAINTENANCE), `purchasable` defaults to gold, `upgrades_to` is
    kept as written. Breaks if a column is dropped or stored unscaled."""
    for name, table in CFG["units"].items():
        assert unit_model.UNIT_MAINTENANCE.get(name, 0) == round(10 * table["maintenance"])
        assert type(unit_model.UNIT_MAINTENANCE.get(name, 0)) is int
        assert unit_model.UNIT_PURCHASABLE[name] == tuple(table.get("purchasable", ["gold"]))
        assert unit_model.UPGRADES_TO.get(name) == table.get("upgrades_to")
    columns = unit_model.parse_unit_columns(_probe_without("purchasable"))
    assert columns["purchasable"] == {"Probe": ("gold",)}


@pytest.mark.parametrize("rows,reason", [
    ("not a list", "must be a list"),
    ([{"unit": "melee", "target": "anti_cavalry", "amount": 5}], "exactly the keys"),    # no strength
    ([{"unit": "melee", "target": "anti_cavalry", "amount": 5, "strength": "combat", "x": 1}],
     "exactly the keys"),
    ([{"unit": "wizard", "target": "melee", "amount": 5, "strength": "combat"}],
     "neither a combat class"),                                                          # unit names nothing
    ([{"unit": "melee", "target": "wizard", "amount": 5, "strength": "combat"}],
     "neither a combat class"),                                                          # target names nothing
    ([{"unit": "melee", "target": "melee", "amount": 5.5, "strength": "combat"}],
     "amount must be an int"),
    ([{"unit": "melee", "target": "melee", "amount": True, "strength": "combat"}],
     "amount must be an int"),                                                           # a bool is not an int
    ([{"unit": "melee", "target": "melee", "amount": 5, "strength": "defence"}],
     "strength 'defence'"),
    ([{"unit": 3, "target": "melee", "amount": 5, "strength": "combat"}], "neither a combat class"),
])
def test_a_malformed_class_bonus_row_raises_at_load(rows, reason):
    """Names must be combat classes or unit types, `amount` an int, `strength`
    "combat" or "ranged", and the keys exactly those four, each case raising
    for its own reason. Breaks if a typo can silently drop or distort a combat
    modifier."""
    with pytest.raises(ValueError, match=reason):
        unit_model.parse_class_bonuses(rows, unit_model.UNIT_NAMES)


def test_class_bonus_rows_keep_config_order_and_both_vocabularies():
    rows = unit_model.parse_class_bonuses([
        {"unit": "melee", "target": "Spearman", "amount": 5, "strength": "combat"},
        {"unit": "Archer", "target": "light_cavalry", "amount": -5, "strength": "ranged"},
    ], unit_model.UNIT_NAMES)
    assert rows == (ClassBonus("melee", "Spearman", 5, "combat"),
                    ClassBonus("Archer", "light_cavalry", -5, "ranged"))


# --- a row's `strength` decides which path reads it ---------------------------------


@pytest.fixture
def board():
    return make_flat_env()


# Attackers stand on row 6 and targets on row 1, so no unit of the attacking
# side is adjacent to a target: flanking (+2 per friendly unit adjacent to the
# defender, #59) never adds to a strength these tests compare.
def _atk(k=0):
    return (6, 2 * k)


def _tgt(k=0):
    return (1, 3 * k)


def _rows(monkeypatch, *rows):
    monkeypatch.setattr(unit_model, "CLASS_BONUSES", tuple(ClassBonus(*row) for row in rows))


def test_a_combat_row_is_read_by_combat_strength_only(monkeypatch, board):
    """A synthetic `strength = "combat"` row moves `get_combat_strength` (in
    both roles) and leaves `get_ranged_strength` alone. Breaks if the ranged
    path reads combat rows."""
    _rows(monkeypatch, ("Archer", "Horseman", 7, "combat"))
    archer = stand(board, "Archer", 0, _atk())
    horseman = stand(board, "Horseman", 1, _tgt())
    base_combat = unit_model.BASE_COMBAT_STRENGTH["Archer"]
    base_ranged = unit_model.BASE_RANGED_STRENGTH["Archer"]
    assert archer.get_combat_strength(True, horseman) == base_combat + 7
    assert archer.get_combat_strength(False, horseman) == base_combat + 7
    assert archer.get_ranged_strength(horseman) == base_ranged


def test_a_ranged_row_is_read_by_ranged_strength_only(monkeypatch, board):
    """A synthetic `strength = "ranged"` row moves `get_ranged_strength` and
    leaves `get_combat_strength` alone, in either role. Breaks if the combat
    path reads ranged rows (the archer penalty would then weaken the Archer's
    own defence)."""
    _rows(monkeypatch, ("Archer", "Horseman", 9, "ranged"))
    archer = stand(board, "Archer", 0, _atk())
    horseman = stand(board, "Horseman", 1, _tgt())
    assert archer.get_ranged_strength(horseman) == unit_model.BASE_RANGED_STRENGTH["Archer"] + 9
    base_combat = unit_model.BASE_COMBAT_STRENGTH["Archer"]
    assert archer.get_combat_strength(True, horseman) == base_combat
    assert archer.get_combat_strength(False, horseman) == base_combat


def test_a_ranged_row_applies_to_the_shooter_never_the_defender(monkeypatch, board):
    """The row `unit = Archer, target = Horseman` is the Archer's penalty AS
    THE SHOOTER. The Horseman it shoots at is not the row's `unit` and gets
    nothing; a row naming the Horseman as `unit` against the Archer changes the
    Horseman's ranged strength (which it does not have) and not its defence.
    Breaks if the ranged rows leak into the defender's combat strength."""
    _rows(monkeypatch,
          ("Archer", "Horseman", -5, "ranged"),
          ("light_cavalry", "Archer", 8, "ranged"))
    archer = stand(board, "Archer", 0, _atk())
    horseman = stand(board, "Horseman", 1, _tgt())
    assert horseman.get_combat_strength(False, archer) == unit_model.BASE_COMBAT_STRENGTH["Horseman"]
    assert horseman.get_ranged_strength(archer) == 0   # no ranged strength to modify


def test_a_row_matches_a_unit_by_its_name_or_by_its_class(monkeypatch, board):
    """`unit` / `target` name a single unit type OR a combat class: a class
    row reaches every unit of the class, a name row only that unit. Breaks if
    a class row misses a member or a name row reaches its whole class."""
    warrior = stand(board, "Warrior", 0, _atk(0))
    swordsman = stand(board, "Swordsman", 0, _atk(1))
    horseman = stand(board, "Horseman", 1, _tgt(0))
    knight = stand(board, "Knight", 1, _tgt(1))

    _rows(monkeypatch, ("melee", "light_cavalry", 7, "combat"))            # class vs class
    for melee in (warrior, swordsman):
        assert melee.get_combat_strength(True, horseman) == melee.get_base_combat_strength() + 7
        assert melee.get_combat_strength(True, knight) == melee.get_base_combat_strength()

    _rows(monkeypatch, ("Warrior", "light_cavalry", 7, "combat"))          # name vs class
    assert warrior.get_combat_strength(True, horseman) == warrior.get_base_combat_strength() + 7
    assert swordsman.get_combat_strength(True, horseman) == swordsman.get_base_combat_strength()

    _rows(monkeypatch, ("melee", "Horseman", 7, "combat"))                 # class vs name
    assert warrior.get_combat_strength(True, horseman) == warrior.get_base_combat_strength() + 7
    assert warrior.get_combat_strength(True, knight) == warrior.get_base_combat_strength()


def test_a_class_row_follows_the_class_registry_not_a_name(monkeypatch, board):
    """Reclassing a unit in the registry moves it into and out of the rows
    that name its class: the rows are matched through `COMBAT_CLASS`, not
    through any list of names in code. Breaks if a unit's class is cached or
    re-derived anywhere but the registry."""
    slinger = stand(board, "Slinger", 0, _atk())
    spearman = stand(board, "Spearman", 1, _tgt())
    base = slinger.get_base_combat_strength()
    assert slinger.get_combat_strength(True, spearman) == base      # a ranged unit: no melee bonus
    monkeypatch.setitem(unit_model.COMBAT_CLASS, "Slinger", "melee")
    assert slinger.get_combat_strength(True, spearman) == base + 5  # now in the melee row


def test_a_row_never_applies_against_a_city(monkeypatch, board):
    """A City has no unit type, so no class row matches it (strength against
    a city carries no class bonus, as before). Breaks if the matcher raises
    on, or matches, a target without a unit type."""
    _rows(monkeypatch, ("Archer", "melee", 7, "ranged"), ("melee", "melee", 7, "combat"))
    city = board.create_city(board.players[1], (6, 12), "Enemy")
    archer = stand(board, "Archer", 0, _atk(0))
    warrior = stand(board, "Warrior", 0, _atk(1))
    assert archer.get_ranged_strength(city, is_city=True) == (
        unit_model.BASE_RANGED_STRENGTH["Archer"] - unit_model.RANGED_CITY_PENALTY)
    assert warrior.get_combat_strength(True, city) == warrior.get_base_combat_strength()


def _string_literals(function):
    """Every string constant in `function`'s body except its docstring."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
    node = tree.body[0]
    body = node.body
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    return {n.value for stmt in body for n in ast.walk(stmt)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def test_no_combat_rule_names_a_unit_or_a_class():
    """The combat code carries no unit or class name as a string literal: the
    modifiers, the siege movement rule, capture, ZoC and flanking are all read
    from the class table (docs/progression_design.md "v2 fixes", N14). The two
    queries whose whole job is to name a class, `is_siege_class` and
    `is_civilian`, are the only exceptions. Breaks if any of these functions
    grows an `if unit_type == "..."`, which is exactly the name-keyed rule
    #116 P3 removed."""
    names = set(unit_model.UNIT_NAMES) | set(unit_model.COMBAT_CLASSES)
    for function in (
        Unit.get_combat_strength, Unit.get_ranged_strength, Unit.attack,
        Unit.flanking_count, Unit.can_capture_city, Unit.projects_zone_of_control,
        GameEnvironment._execute_attack,
    ):
        assert not (_string_literals(function) & names), function.__qualname__


# --- the new rows ---------------------------------------------------------------------


@pytest.mark.parametrize("anti_cavalry", ["Spearman", "Pikeman"])
@pytest.mark.parametrize("cavalry", ["Horseman", "Knight"])
def test_anti_cavalry_gets_ten_against_every_cavalry_in_both_roles(board, anti_cavalry, cavalry):
    """Civ 6: anti-cavalry +10 against light AND heavy cavalry, attacking or
    defending (#63). Breaks if the heavy_cavalry row is missing or either
    role loses the bonus."""
    pike = stand(board, anti_cavalry, 0, _atk())
    rider = stand(board, cavalry, 1, _tgt())
    base = pike.get_base_combat_strength()
    assert pike.get_combat_strength(True, rider) == base + 10
    assert pike.get_combat_strength(False, rider) == base + 10
    assert rider.get_combat_strength(True, pike) == rider.get_base_combat_strength()


def test_only_anti_cavalry_gets_the_cavalry_bonus(board):
    knight = stand(board, "Knight", 1, _tgt())
    for k, other in enumerate(("Warrior", "Man-At-Arms", "Archer", "Catapult")):
        unit = stand(board, other, 0, _atk(k))
        assert unit.get_combat_strength(True, knight) == unit.get_base_combat_strength(), other


@pytest.mark.parametrize("melee", ["Warrior", "Swordsman", "Man-At-Arms", "Musketman"])
@pytest.mark.parametrize("anti_cavalry", ["Spearman", "Pikeman"])
def test_every_melee_unit_gets_five_against_every_anti_cavalry_in_both_roles(board, melee, anti_cavalry):
    """Civ 6: melee +5 vs anti-cavalry, the class rule that replaced the
    `Warrior/Swordsman` name list, so the new melee units get it too. Breaks
    if a melee unit is left out or the bonus is attack-only."""
    sword = stand(board, melee, 0, _atk())
    pike = stand(board, anti_cavalry, 1, _tgt())
    base = sword.get_base_combat_strength()
    assert sword.get_combat_strength(True, pike) == base + 5
    assert sword.get_combat_strength(False, pike) == base + 5
    assert pike.get_combat_strength(True, sword) == pike.get_base_combat_strength()


@pytest.mark.parametrize("shooter", ["Archer", "Crossbowman"])
@pytest.mark.parametrize("target", ["Horseman", "Knight"])
def test_archers_and_crossbowmen_shoot_five_weaker_at_cavalry(board, shooter, target):
    """The archer penalty vs cavalry (v0.7: Horseman only) now covers the
    Knight, and the Crossbowman has it too (Claude's call, CHANGELOG). It is
    the shooter's alone: the shooter's combat strength and the rider's are not
    touched. Breaks if a row is missing or reaches another role."""
    bow = stand(board, shooter, 0, _atk())
    rider = stand(board, target, 1, _tgt())
    assert bow.get_ranged_strength(rider) == bow.get_base_ranged_strength() - 5
    assert bow.get_combat_strength(True, rider) == bow.get_base_combat_strength()
    assert rider.get_combat_strength(False, bow) == rider.get_base_combat_strength()


def test_other_ranged_units_get_no_cavalry_penalty(board):
    """The penalty is by unit name, shooter-only: the Slinger (a ranged unit
    by class) and the Trebuchet shoot cavalry at full strength, as the Slinger
    always has. The class-keyed shortcut `ranged vs cavalry` would break this
    (design critique B2)."""
    rider = stand(board, "Knight", 1, _tgt())
    for k, shooter in enumerate(("Slinger", "Trebuchet")):
        unit = stand(board, shooter, 0, _atk(k))
        assert unit.get_ranged_strength(rider) == unit.get_base_ranged_strength(), shooter


# --- rules keyed on class ---------------------------------------------------------------


def test_the_trebuchet_is_a_siege_unit_by_class(board):
    """The siege class is exempt from the flat ranged-vs-city penalty: the
    Trebuchet fires at full ranged strength at a city while the Crossbowman
    loses 17. Breaks if the Trebuchet is not in the class."""
    city = board.create_city(board.players[1], (6, 12), "Enemy")
    trebuchet = stand(board, "Trebuchet", 0, _atk(0))
    bow = stand(board, "Crossbowman", 0, _atk(1))
    assert trebuchet.is_siege_class()
    assert trebuchet.get_ranged_strength(city, is_city=True) == trebuchet.get_base_ranged_strength()
    assert bow.get_ranged_strength(city, is_city=True) == bow.get_base_ranged_strength() - 17


@pytest.mark.parametrize("siege", ["Catapult", "Trebuchet"])
def test_a_siege_unit_fires_only_with_a_movement_point_left(board, siege):
    """Civ 6: siege cannot attack after moving. The rule is the class's, so
    the Trebuchet obeys it as the Catapult does: refused below one movement
    point (no damage, nothing consumed), fired at one. Breaks if the rule is
    keyed on a name."""
    gun = stand(board, siege, 0, (3, 3))
    target = stand(board, "Warrior", 1, (3, 5))
    gun.movement_points = 0.5
    assert gun.attack(target, board) == (0, 0, False, False)
    assert target.health == 100.0
    gun.movement_points = 1
    damage, _, _, _ = gun.attack(target, board)
    assert damage > 0


def test_the_siege_rules_follow_the_class_registry(monkeypatch, board):
    """Declaring another unit siege in the registry gives it both siege rules
    without touching code. Breaks if `is_siege_class` or the movement rule
    reads anything but the class."""
    archer = stand(board, "Archer", 0, (3, 3))
    target = stand(board, "Warrior", 1, (3, 5))
    assert not archer.is_siege_class()
    monkeypatch.setitem(unit_model.COMBAT_CLASS, "Archer", "siege")
    assert archer.is_siege_class()
    archer.movement_points = 0.5
    assert archer.attack(target, board) == (0, 0, False, False)


def _attack_with_a_hurt_defender(env, attacker_type, defender_type):
    attacker = stand(env, attacker_type, 0, (3, 3))
    defender = stand(env, defender_type, 1, (3, 4))
    defender.health = 1.0
    env.current_player = env.players[0]
    env._execute_attack(attacker, defender)
    return attacker, defender


def test_a_beaten_trader_is_captured_not_killed(board):
    """Civilian capture is keyed on the class `civilian`, so the Trader, which
    no code names, is taken like a Settler or Worker: it changes owner and
    stays on the board, and the capture is counted. Breaks if capture is a
    list of names."""
    _, trader = _attack_with_a_hurt_defender(board, "Warrior", "Trader")
    assert trader.player is board.players[0]
    assert trader in board.players[0].units and trader not in board.players[1].units
    assert trader in board.get_units_at((3, 4))
    assert board.episode_stats[0]["civilians_captured"] == 1


def test_a_beaten_fighter_is_killed_not_captured(board):
    _, victim = _attack_with_a_hurt_defender(board, "Warrior", "Man-At-Arms")
    assert victim not in board.players[1].units and victim not in board.players[0].units
    assert board.episode_stats[0]["civilians_captured"] == 0
    assert board.episode_stats[0]["kills"] == 1


def test_civilian_capture_follows_the_class_registry(monkeypatch, board):
    """Reclassing a unit `civilian` in the registry makes it capturable and
    nothing else. Breaks if capture checks a unit name."""
    monkeypatch.setitem(unit_model.COMBAT_CLASS, "Spearman", "civilian")
    _, spearman = _attack_with_a_hurt_defender(board, "Warrior", "Spearman")
    assert spearman.player is board.players[0]


# --- the registry of unit classes ----------------------------------------------------------


def test_the_unit_class_registry_covers_exactly_the_configured_units():
    """`UNIT_CLASSES` is the one name -> subclass registry: a unit type is in
    it iff it has a `[units.*]` table. Breaks if a new unit table is added
    without its class (or the reverse)."""
    assert set(UNIT_CLASSES) == set(unit_model.UNIT_NAMES)


@pytest.mark.parametrize("unit_type", sorted(UNIT_CLASSES))
def test_the_factory_builds_the_registered_class_with_its_own_type(unit_type):
    unit = _create_unit(unit_type, None, (0, 0))
    assert type(unit) is UNIT_CLASSES[unit_type] and type(unit) is not Unit
    assert unit.unit_type == unit_type
    assert unit.combat_class == unit_model.COMBAT_CLASS[unit_type]
    # a shooter must be built from a class that can shoot
    assert isinstance(unit, RangedUnit) == (unit_model.BASE_RANGED_STRENGTH[unit_type] > 0)


def test_an_unknown_unit_type_is_an_error_not_a_bare_unit():
    """The factory used to fall back to the plain `Unit`, which strips a
    shooter of its attack and a siege unit of its rules and looks like a unit.
    It raises, naming the type. Breaks if the fall-back returns."""
    with pytest.raises(ValueError, match="Dragon"):
        _create_unit("Dragon", None, (0, 0))


def test_one_registry_serves_the_factory_the_matrix_and_the_recorder():
    """The matchup harness and the order recorder import `UNIT_CLASSES`
    instead of keeping a copy. Breaks if either grows its own dict again."""
    from civulator.tools import recording

    assert matchup_matrix.UNIT_CLASSES is UNIT_CLASSES
    assert recording.UNIT_CLASSES is UNIT_CLASSES


def test_the_recorder_places_a_new_unit_and_refuses_an_unknown_one():
    """A scenario unit entry resolves through the registry (a unit that exists
    since #116 P3 is placed as itself); an unknown type raises, naming it,
    where it used to become a Warrior without a word. Breaks if the silent
    fall-back returns."""
    from civulator.tools.recording import _place_unit

    env = make_flat_env()
    entry = {"type": "Knight", "team": 1, "row": 3, "col": 3}
    unit = _place_unit(env, entry)
    assert unit.unit_type == "Knight" and unit in env.get_units_at((3, 3))
    with pytest.raises(ValueError, match="Dragon"):
        _place_unit(env, {"type": "Dragon", "team": 1, "row": 4, "col": 4})
    assert _place_unit(env, {"team": 1, "row": 5, "col": 5}).unit_type == "Warrior"  # no type: Warrior


def test_the_matchup_harness_measures_a_new_unit_and_refuses_one_that_cannot_attack():
    """`--units` reaches any unit that can attack, the new ones included, and
    refuses a civilian or a support unit (no exchange to measure). Breaks if
    the harness only knows the units of the day it was written."""
    result = matchup_matrix.run_matrix(units=["Knight", "Pikeman", "Crossbowman"], duels=3, seed=5)
    assert {(p["attacker"], p["defender"]) for p in result["conditions"][0]["pairings"]} == {
        (a, d) for a in result["units"] for d in result["units"]}
    for bad in ("Trader", "Settler", "SiegeTower"):
        with pytest.raises(ValueError):
            matchup_matrix.run_matrix(units=["Knight", bad], duels=2, seed=1)


# --- build options ----------------------------------------------------------------------------


# The BUILD_OPTIONS list as it stood before #116 P3 (v0.7 + the P2 buildings).
PRE_P3_BUILD_OPTIONS = [
    "Warrior", "Spearman", "Archer", "Horseman", "Catapult",
    "Settler", "Granary", "Slinger", "Swordsman", "Walls",
    "Monument", "Library", "University", "Shrine", "Barracks",
    "Medieval Walls", "Workshop",
]


def test_the_new_units_are_appended_to_build_options():
    """BUILD_OPTIONS is append-only (#67): the pre-P3 list is still its prefix,
    so an archived build head's indices keep their meaning, and every unit the
    patch added that can be offered stands after it. Breaks if an option is
    inserted, moved or removed."""

    assert BUILD_OPTIONS[:len(PRE_P3_BUILD_OPTIONS)] == PRE_P3_BUILD_OPTIONS
    added = [n for n in unit_model.UNIT_NAMES
             if n not in PRE_P3_BUILD_OPTIONS and n not in DEFERRED_BUILD_UNITS
             and unit_model.BASE_COMBAT_STRENGTH[n] > 0]
    assert added, "fixture: the patch adds buildable fighting units"
    for name in added:
        assert BUILD_OPTIONS.index(name) >= len(PRE_P3_BUILD_OPTIONS), name


_BUILDABLE_UNITS = [o for o in BUILD_OPTIONS if o in unit_model.UNIT_NAMES]


@pytest.mark.parametrize("unit_type", _BUILDABLE_UNITS)
def test_a_city_produces_every_buildable_unit_as_its_registered_class(unit_type):
    """E2E through the build path: with the owner's research complete, a city
    that starts a unit and pays for it puts a unit of its registered subclass
    on the board, whatever unit it is (the new Medieval units included). A
    ship (v0.9.0 Q5) needs a spawn water tile, so for a water-domain unit one
    tile beside the city is Coast -- the declared rule of §6.4, not an
    exemption. Breaks if a build option cannot be produced, or is produced as
    the wrong class."""
    env = make_flat_env()
    if MOVEMENT_DOMAIN[unit_type] == "water":
        coast = env.map.get_adjacent_coords((3, 3))[0]
        env.map.get_tile(coast).set_layers("Coast", map_ref=env.map)
    city = env.create_city(env.players[0], (3, 3), "C")
    city.population = 3
    grant_all(env.players[0])
    assert city.produce_unit(unit_type) is True
    city.production = city.get_unit_cost(unit_type)
    city.process_turn(env)
    made = [u for u in env.players[0].units if u.unit_type == unit_type]
    assert made, f"the city never produced a {unit_type}"
    assert type(made[0]) is UNIT_CLASSES[unit_type]


def test_the_trader_is_a_build_option_once_routes_exist():
    """Restated in #116 P5 (it asserted the P3 deferral): the Trader's
    table, subclass, slot and capture rules exist since P3, and since P5 it
    makes trade routes, so it has left DEFERRED_BUILD_UNITS and is appended
    to BUILD_OPTIONS after every earlier option (#67's append-only
    contract), gated on its civic. Breaks if it is deferred again, inserted
    before an older option, or loses its class, slot or civic gate."""

    assert "Trader" in unit_model.UNIT_NAMES
    assert unit_model.COMBAT_CLASS["Trader"] == "civilian"
    assert unit_model.UNIT_REQUIRES_CIVIC["Trader"] == "Foreign Trade"
    assert "Trader" not in DEFERRED_BUILD_UNITS and "Trader" in BUILD_OPTIONS
    assert BUILD_OPTIONS.index("Trader") >= len(PRE_P3_BUILD_OPTIONS)
    assert UNIT_SLOT["Trader"] == 1 and MOVEMENT_DOMAIN["Trader"] == "land"


# --- the encoder ---------------------------------------------------------------------------------


# Class channels as v0.7 had them, for the units that existed then.
PRE_P3_CLASS_INDEX = {
    "Warrior": 0, "Swordsman": 0, "Spearman": 1, "Slinger": 2, "Archer": 2,
    "Horseman": 3, "Catapult": 4, "Settler": -1, "Worker": -1,
    "BatteringRam": -1, "SiegeTower": -1,
}


def test_class_index_is_derived_from_the_combat_class():
    """CLASS_INDEX is `COMBAT_CLASS` through `CLASS_CHANNEL`, for every unit,
    and reproduces v0.7's channel for every unit that existed then. Breaks if
    a channel is edited by hand or a derivation changes an old unit's input."""
    assert EnhancedStateEncoder.CLASS_INDEX is UNIT_CLASS_INDEX
    assert set(UNIT_CLASS_INDEX) == set(unit_model.UNIT_NAMES)
    for name, cls in unit_model.COMBAT_CLASS.items():
        assert UNIT_CLASS_INDEX[name] == CLASS_CHANNEL[cls], name
    for name, channel in PRE_P3_CLASS_INDEX.items():
        assert UNIT_CLASS_INDEX[name] == channel, name


def test_every_class_has_a_channel_inside_the_existing_one_hot():
    """Every combat class maps to a channel of the five-wide one-hot (or -1,
    none), so no unit can add a channel. Breaks if a class is left out or
    given an index past the one-hot."""
    assert set(CLASS_CHANNEL) >= set(unit_model.COMBAT_CLASSES)
    assert all(-1 <= channel <= 4 for channel in CLASS_CHANNEL.values())


# Channel counts of the encoders that existed before #116 P3, as (no fog, fog).
PRE_P3_DEPTHS = {
    "basic": (5, 5), "enhanced": (25, 27), "terrain_aware": (52, 54),
    "city_distance": (26, 28), "full": (53, 55), "settle": (54, 56),
}


def test_no_registered_encoder_changed_its_channel_count():
    """The encoders that existed before the patch keep their exact depth, fog
    on and off (a new unit must not add an input channel: that invalidates
    every trained .pth). A newer encoder is not constrained. Breaks if a
    channel is added to any of them."""
    for name, (plain, fogged) in PRE_P3_DEPTHS.items():
        assert get_encoder(name, fog_of_war=False).get_depth(2) == plain, name
        assert get_encoder(name, fog_of_war=True).get_depth(2) == fogged, name


@pytest.mark.parametrize("name", sorted(_ENCODER_REGISTRY))
def test_a_board_holding_every_unit_type_encodes_to_the_declared_depth(name):
    """With every configured unit type on the board for both players, each
    registered encoder still returns exactly `get_depth` channels, and the
    unit class and stat channels stay inside [0, 1] (the strongest units
    saturate instead of leaving the range the networks were trained on).
    Breaks if a unit adds a channel or an out-of-range input."""
    env = make_flat_env()
    for player_index in (0, 1):
        for i, unit_type in enumerate(sorted(unit_model.UNIT_NAMES)):
            stand(env, unit_type, player_index, (1 + 3 * player_index + i // 16, i % 16))
    encoder = get_encoder(name, fog_of_war=False)
    state = encoder.encode(env, 0)
    assert state.shape[0] == encoder.get_depth(len(env.players))
    if isinstance(encoder, EnhancedStateEncoder):
        assert float(state[0:22].min()) >= 0.0 and float(state[0:22].max()) <= 1.0


def test_the_strongest_units_saturate_the_strength_channel():
    """Knight (50) sits on the MAX_MELEE_STR constant and Musketman (55) is
    clamped to it; units below it are unchanged. The constant itself stays
    (ACCEPTED GAP, #111): moving it would shift every trained input. Breaks if
    the clamp is lost (the channel would read 1.1) or the constant moves."""
    assert EnhancedStateEncoder.MAX_MELEE_STR == 50.0
    for unit_type, expected in (("Swordsman", 35 / 50), ("Knight", 1.0), ("Musketman", 1.0)):
        env = make_flat_env()
        stand(env, unit_type, 0, (3, 3))
        state = get_encoder("enhanced", fog_of_war=False).encode(env, 0)
        assert float(state[6, 3, 3]) == pytest.approx(expected), unit_type   # own combat strength
    stand(env, "Crossbowman", 1, (3, 6))
    state = get_encoder("enhanced", fog_of_war=False).encode(env, 0)
    assert float(state[16 + 2, 3, 6]) == pytest.approx(40 / 50)              # an enemy's ranged strength
