"""Issue #116 P3: unit upgrades (docs/progression_design.md §6.4, §14 row
"Upgrade: refused without the target's tech, off own territory, without full
movement; cost per §7.3; type, health and movement per §6.4", "v2 fixes":
"Upgrades and bankruptcy").

`upgrades_to` on a `[units.*]` table names the next unit in a chain;
`GameEnvironment.upgrade_unit(unit)` replaces the unit by one of that type for
`upgrade_cost(unit)` gold, if every precondition holds. Every chain test
iterates over `unit_model.UPGRADES_TO`, so a chain added later is covered
without an edit; the single-unit scenarios use the Slinger -> Archer upgrade,
the one data point Civ 6 states (60 gold).
"""

import pytest

from civulator import unit_model
from civulator.config import CFG
from civulator.game import upgrades
from civulator.game.availability import required_tech
from civulator.game.city import UNIT_CLASSES
from civulator.game.territory import NEUTRAL
from civulator.game.unit import MOVEMENT_DOMAIN, UNIT_SLOT
from civulator.research_model import ERAS

from conftest import grant, grant_all, stand
from test_combat_range import make_flat_env

MINE = (3, 4)         # the centre of player 0's city
THEIRS = (3, 12)      # the centre of player 1's city
CHAINS = sorted(unit_model.UPGRADES_TO.items())
SOURCES = [source for source, _ in CHAINS]


def _world():
    """Player 0's city at MINE and player 1's at THEIRS on a flat board."""
    env = make_flat_env()
    env.create_city(env.players[0], MINE, "Mine")
    env.create_city(env.players[1], THEIRS, "Theirs")
    return env


def _ready(unit_type="Slinger", at=MINE, techs=True):
    """A world where `unit_type` of player 0 meets every condition of an
    upgrade, with exactly the gold it costs (tenths) and its target's tech
    known (all techs when `techs`)."""
    env = _world()
    player = env.players[0]
    unit = stand(env, unit_type, 0, at)
    if techs:
        grant_all(player)
    cost = upgrades.upgrade_cost(unit)
    player.gold = 10 * cost if cost is not None else 99999
    return env, player, unit


def _state(env, player, unit):
    return (list(player.units), list(env.get_units_at(unit.coordinates)), player.gold,
            unit.unit_type, unit.health, unit.movement_points, unit.fortification,
            unit.has_acted, dict(env.episode_stats[player.player_index]))


def _assert_refused(env, player, unit):
    before = _state(env, player, unit)
    assert env.upgrade_unit(unit) is False
    assert _state(env, player, unit) == before


# --- the price ---------------------------------------------------------------------------


def test_the_price_reproduces_the_one_civ6_data_point():
    """Civ 6 states one price: Slinger -> Archer costs 60 gold at standard
    speed. Breaks if the formula or its two numbers drift from it."""
    env, player, slinger = _ready("Slinger")
    assert upgrades.upgrade_cost(slinger) == 60


@pytest.mark.parametrize("source,target", CHAINS)
def test_the_price_is_two_per_production_point_gained_plus_ten(source, target):
    """`2 * (target cost - unit cost) + 10` whole gold, for every chain, from
    the production costs written in config.toml. Breaks if the price is
    computed any other way."""
    env, player, unit = _ready(source)
    gap = CFG["units"][target]["production_cost"] - CFG["units"][source]["production_cost"]
    assert gap > 0
    assert upgrades.upgrade_cost(unit) == 2 * gap + 10
    assert type(upgrades.upgrade_cost(unit)) is int


def test_a_unit_with_no_upgrade_has_no_price():
    env = _world()
    for unit_type in unit_model.UNIT_NAMES - set(unit_model.UPGRADES_TO):
        unit = stand(env, unit_type, 0, MINE)
        assert upgrades.upgrade_cost(unit) is None, unit_type
        assert upgrades.upgrade_target(unit) is None
        env.delete_unit(unit)


def test_the_two_numbers_come_from_the_gold_table(monkeypatch):
    """The price reads `[gold] upgrade_per_production` / `upgrade_base`, not
    literals in code. Breaks if either is hard-coded."""
    env, player, slinger = _ready("Slinger")
    gap = unit_model.PRODUCTION_COST["Archer"] - unit_model.PRODUCTION_COST["Slinger"]
    monkeypatch.setattr(unit_model, "UPGRADE_PER_PRODUCTION", 3)
    monkeypatch.setattr(unit_model, "UPGRADE_BASE", 5)
    assert upgrades.upgrade_cost(slinger) == 3 * gap + 5
    assert CFG["gold"]["upgrade_per_production"] == 2 and CFG["gold"]["upgrade_base"] == 10


@pytest.mark.parametrize("percent,expected", [(-50, 30), (50, 90), (0, 60), (-100, 0), (-250, 0)])
def test_the_effect_hook_scales_the_price_once_and_never_below_zero(monkeypatch, percent, expected):
    """P4's `upgrade_cost_percent` effects are SUMMED by `_upgrade_cost_percent`
    and applied once, floored, to the base price (a discount card is a negative
    percent), and a price is never negative. Until the effects interpreter
    exists the hook is 0. Breaks if the percent is applied per effect, rounds
    the wrong way, or can pay the player."""
    assert upgrades._upgrade_cost_percent(None) == 0
    env, player, slinger = _ready("Slinger")
    monkeypatch.setattr(upgrades, "_upgrade_cost_percent", lambda owner: percent)
    assert upgrades.upgrade_cost(slinger) == expected


# --- the success path ----------------------------------------------------------------------


def test_an_upgrade_replaces_the_unit_in_place_and_charges_the_gold():
    """The unit OBJECT is replaced by one of the target type, at the same index
    of `player.units` and the same place in its tile's stack; health carries
    over; the new unit has spent its movement, is unfortified and has acted;
    the treasury pays 10 * cost tenths; the upgrade is counted; the target's
    stats apply. Breaks if any of these is dropped."""
    env = _world()
    player = env.players[0]
    first = stand(env, "Warrior", 0, (2, 4))
    slinger = stand(env, "Slinger", 0, MINE)           # slot 0, FIRST in its tile's stack
    settler = stand(env, "Settler", 0, MINE)           # slot 1 of the same tile
    last = stand(env, "Warrior", 0, (4, 4))
    grant_all(player)
    slinger.health = 63.5
    slinger.fortification = 1
    player.gold = 600 + 7
    index = player.units.index(slinger)
    stack = env.get_units_at(MINE)
    stack_index = stack.index(slinger)
    assert (index, stack_index) == (1, 0)

    assert env.upgrade_unit(slinger) is True

    archer = player.units[index]
    assert archer is not slinger and archer.unit_type == "Archer"
    assert type(archer) is UNIT_CLASSES["Archer"]
    assert player.units == [first, archer, settler, last]
    assert env.get_units_at(MINE) == [archer, settler] and env.get_units_at(MINE)[stack_index] is archer
    assert slinger not in player.units and slinger not in env.get_units_at(MINE)
    assert archer.player is player and archer.coordinates == MINE
    assert archer.health == 63.5
    assert archer.movement_points == 0 and archer.fortification == 0 and archer.has_acted is True
    assert player.gold == 7
    assert env.episode_stats[0]["units_upgraded"] == 1 and env.episode_stats[1]["units_upgraded"] == 0
    assert archer.get_base_ranged_strength() == unit_model.BASE_RANGED_STRENGTH["Archer"]
    assert archer.get_range() == unit_model.RANGE_VALUES["Archer"] > slinger.get_range()
    assert archer.slot == slinger.slot


@pytest.mark.parametrize("source", SOURCES)
def test_every_chain_upgrades_when_every_condition_holds(source):
    """For every configured chain, a unit meeting every condition becomes its
    target, paying exactly the price (and nothing is left to a hard-coded
    list of units)."""
    env, player, unit = _ready(source)
    target = unit_model.UPGRADES_TO[source]
    price = upgrades.upgrade_cost(unit)
    assert env.upgrade_unit(unit) is True
    upgraded = env.get_units_at(MINE)[-1]
    assert upgraded.unit_type == target and type(upgraded) is UNIT_CLASSES[target]
    assert player.gold == 0 and price > 0


def test_exactly_enough_gold_is_enough_and_one_tenth_less_is_not():
    env, player, slinger = _ready("Slinger")
    player.gold = 599
    _assert_refused(env, player, slinger)
    player.gold = 600
    assert env.upgrade_unit(slinger) is True and player.gold == 0


def test_an_upgrade_uses_up_the_turn_but_not_the_chain():
    """The upgraded unit has no movement, so it cannot be upgraded again in the
    same turn (a Slinger cannot reach a Crossbowman at once); next turn, with
    the tech and the gold, it can take the next step. Breaks if the new unit
    keeps its movement."""
    env, player, slinger = _ready("Slinger")
    player.gold = 100000
    assert env.upgrade_unit(slinger) is True
    archer = env.get_units_at(MINE)[-1]
    assert archer.unit_type == "Archer"
    _assert_refused(env, player, archer)
    archer.reset_movement()
    assert env.upgrade_unit(archer) is True
    assert env.get_units_at(MINE)[-1].unit_type == unit_model.UPGRADES_TO["Archer"]


# --- the refusals --------------------------------------------------------------------------------


def test_a_unit_at_the_end_of_its_line_cannot_upgrade():
    env = _world()
    grant_all(env.players[0])
    env.players[0].gold = 100000
    ends = unit_model.UNIT_NAMES - set(unit_model.UPGRADES_TO)
    assert ends
    for unit_type in sorted(ends):
        unit = stand(env, unit_type, 0, MINE)
        _assert_refused(env, env.players[0], unit)
        env.delete_unit(unit)


@pytest.mark.parametrize("source", [s for s, t in CHAINS if required_tech("unit", t) is not None])
def test_an_upgrade_is_refused_until_the_targets_tech_is_known(source):
    """§14: `requires_tech` gates `upgrade_unit` like every build path
    (`player_can_build`). Breaks if an upgrade skips the gate."""
    env, player, unit = _ready(source, techs=False)
    _assert_refused(env, player, unit)
    grant(player, required_tech("unit", unit_model.UPGRADES_TO[source]))
    assert env.upgrade_unit(unit) is True


def test_an_upgrade_is_refused_off_its_owners_territory():
    """The unit must stand on a tile of one of its OWNER's cities: not on a
    neutral tile, not on a tile another player owns. Breaks if the ownership
    test is dropped or tests the wrong owner."""
    env, player, unit = _ready("Slinger")
    ours = [(r, c) for r in range(env.n) for c in range(env.m)
            if env.map.owner_id_at((r, c)) != NEUTRAL
            and env.player_owns_tile(player, (r, c))]
    theirs = [(r, c) for r in range(env.n) for c in range(env.m)
              if env.map.owner_id_at((r, c)) != NEUTRAL
              and env.player_owns_tile(env.players[1], (r, c))]
    neutral = [(r, c) for r in range(env.n) for c in range(env.m)
               if env.map.owner_id_at((r, c)) == NEUTRAL]
    assert ours and theirs and neutral, "fixture: all three kinds of tile exist"
    for where in (theirs[0], neutral[0]):
        env.move_unit(unit, where)
        _assert_refused(env, player, unit)
    env.move_unit(unit, ours[-1])           # a ring tile of its own city, not the centre
    assert env.upgrade_unit(unit) is True


def test_an_upgrade_is_refused_after_the_unit_has_moved():
    """Full movement is required: a unit that has walked a step (a real
    `Unit.move`) cannot upgrade. Breaks if the movement condition is dropped."""
    env, player, unit = _ready("Slinger")
    moved, _ = unit.move((MINE[0], MINE[1] + 1), env)
    assert moved and 0 < unit.movement_points < unit.get_max_movement()
    assert env.player_owns_tile(player, unit.coordinates)
    _assert_refused(env, player, unit)

    env, player, unit = _ready("Slinger")    # movement short, nothing else wrong
    unit.movement_points = unit.get_max_movement() - 1
    assert not unit.has_acted
    _assert_refused(env, player, unit)


def test_an_upgrade_is_refused_after_the_unit_has_attacked():
    """A unit that attacked this turn (a real `_execute_attack`) cannot
    upgrade; neither can one merely flagged as having acted with its movement
    intact. Breaks if the attack condition is dropped."""
    env, player, unit = _ready("Slinger")
    enemy = stand(env, "Warrior", 1, (MINE[0], MINE[1] + 1))
    env.current_player = player
    env._execute_attack(unit, enemy)
    assert unit.has_acted
    _assert_refused(env, player, unit)

    env, player, unit = _ready("Slinger")
    unit.has_acted = True                    # movement still full
    assert unit.movement_points == unit.get_max_movement()
    _assert_refused(env, player, unit)


def test_a_unit_that_is_not_in_its_players_army_is_refused():
    """A deleted or foreign unit object is not upgraded. Breaks if
    `upgrade_unit` trusts a stale reference."""
    env, player, unit = _ready("Slinger")
    env.delete_unit(unit)
    assert env.upgrade_unit(unit) is False and player.gold == 600


# --- what an upgrade is not -----------------------------------------------------------------------


def test_the_engine_never_upgrades_on_its_own():
    """No engine default and no agent action upgrades a unit (an ACCEPTED GAP,
    dormant until #99): with every condition met and the gold in the treasury,
    whole rounds of play leave the unit what it was. Breaks if a default is
    wired in without the CHANGELOG saying so."""
    env, player, slinger = _ready("Slinger")
    player.gold = 100000
    for _ in range(2 * len(env.players)):
        env.next_turn()
    assert slinger.unit_type == "Slinger" and slinger in player.units
    assert env.episode_stats[0]["units_upgraded"] == 0


def test_units_upgraded_is_a_declared_int_counter_that_resets():
    env = _world()
    for i in range(env.num_players):
        assert env.episode_stats[i]["units_upgraded"] == 0
        assert type(env.episode_stats[i]["units_upgraded"]) is int
    env.episode_stats[0]["units_upgraded"] = 3
    env.reset(seed=1)
    assert env.episode_stats[0]["units_upgraded"] == 0


# --- every chain is a sane step up ------------------------------------------------------------------


@pytest.mark.parametrize("source,target", CHAINS)
def test_an_upgrade_chain_keeps_the_stack_slot_the_domain_and_the_shooting(source, target):
    """The unit is swapped into the same tile slot and the same movement
    domain, so the two must agree; a shooter stays a shooter and a fighter a
    fighter. Breaks if a chain links units the in-place swap cannot handle
    (an upgrade into another slot would stack two units of one slot)."""
    assert UNIT_SLOT[source] == UNIT_SLOT[target]
    assert MOVEMENT_DOMAIN[source] == MOVEMENT_DOMAIN[target]
    assert (unit_model.BASE_RANGED_STRENGTH[source] > 0) == (unit_model.BASE_RANGED_STRENGTH[target] > 0)


@pytest.mark.parametrize("source,target", CHAINS)
def test_an_upgrade_is_a_step_up(source, target):
    """The target costs more, is no earlier in era and attacks at least as
    hard (its ranged strength for a shooter, its combat strength otherwise).
    Breaks if a chain points backwards."""
    cost, era = unit_model.PRODUCTION_COST, unit_model.UNIT_ERA
    assert cost[target] > cost[source]
    assert ERAS.index(era[target]) >= ERAS.index(era[source])

    def attack(unit_type):
        return max(unit_model.BASE_COMBAT_STRENGTH[unit_type], unit_model.BASE_RANGED_STRENGTH[unit_type])

    assert attack(target) >= attack(source)
