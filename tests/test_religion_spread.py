"""Religion III (v0.9.0 Q9, docs/districts_religion_design.md §7.4, §7.5, §9, §11 and
"v2 fixes" / "v3 fixes" L2, L3, L5, L6): pressure (the loyalty formula plus the
religious weight and the directed-spread ledger), the round-end conversion phase,
directed spread, upkeep and lapse, inquisition, the foreign-religion loyalty term,
the religious-victory flag, what capture and flip keep, the `religion_param`
reader, and the episode state.

Every test asserts a property and names the change that breaks it. Nothing here
pins how many beliefs, buildings or districts exist: weights are read from the
registry columns, beliefs come from the registry or are synthetic, and numbers
are derived from `[religion]` (`religion_model.RULES`) or patched for the test.
Boards are test_loyalty's flat 8 x m row board: cities on one row, so the
canonical distance between two of them is their column gap (wrapped).
"""

import os
import subprocess
import sys
from dataclasses import replace

import pytest

from civulator import religion_model
from civulator.district_model import DISTRICTS
from civulator.effects import KIND_RELIGION_PARAM, active_effects
from civulator.game import loyalty, religion as religion_mod, victory
from civulator.game.districts import District, district_spec
from civulator.game.environment import GameEnvironment
from civulator.game.religion import (
    REFUSE_DEAD,
    REFUSE_FAITH,
    REFUSE_NO_RELIGION,
    REFUSE_NOT_OWN_CITY,
    REFUSE_OUT_OF_RANGE,
    Religion,
    candidate,
    founder_pay_tenths,
    incumbent_term,
    inquisition_cost_tenths,
    inquisition_refusals,
    is_unpaid,
    pressure,
    pressure_citizen_weight,
    pressure_reach,
    religion_params,
    religious_weight,
    secular_pressure,
    spread_amount,
    spread_cost_tenths,
    spread_refusals,
    upkeep_tenths,
)
from civulator.game.unit import SettlerUnit
from civulator.game.yields import city_yield
from civulator.religion_model import (
    RULES,
    TIER_ENHANCER,
    TIER_FOLLOWER,
    TIER_FOUNDER,
    BeliefSpec,
    beliefs_of_tier,
)
from civulator.unit_model import BUILDING_RELIGIOUS_WEIGHT

from test_determinism import episode_fingerprint
from test_loyalty import city, flat

pytestmark = pytest.mark.usefixtures("neutral_amenities")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))


# --- fixtures ------------------------------------------------------------------------------


def give(env, seat, *followers, enhancer=None, follower_belief=None):
    """Hand seat `seat` a religion (the action is test_religion_beliefs'),
    founder belief i-th of its tier for seat i so two religions never share
    one; every city of `followers` follows it."""
    founders = beliefs_of_tier(TIER_FOUNDER)
    env.players[seat].religion = Religion(
        founder=seat, founder_belief=founders[seat % len(founders)],
        follower_beliefs=[follower_belief or beliefs_of_tier(TIER_FOLLOWER)[0]],
        enhancer_belief=enhancer)
    for c in followers:
        c.religion = seat
    return env.players[seat].religion


def belief(monkeypatch, name, tier, entries):
    """A synthetic `[beliefs.*]` table for one test (validated on first use)."""
    monkeypatch.setitem(religion_model.BELIEFS, name, BeliefSpec(
        name=name, tier=tier, effects=tuple(entries),
        counts=religion_model.COUNTS_ALL if tier == TIER_FOUNDER else None))
    return name


def rules(monkeypatch, **changes):
    """`[religion]` with `changes`, as game/religion.py reads it at call time."""
    monkeypatch.setattr(religion_mod, "RULES", replace(RULES, **changes))


def phase(env, times=1):
    for _ in range(times):
        env._religion_phase()


def link(env, owner, district_type, col_offset, complete=True):
    """Fixture only: a District linked by hand `col_offset` tiles east."""
    r, c = owner.coordinates
    pos = (r, (c + col_offset) % env.m)
    district = District(district_type, owner.city_id, pos, complete=complete, cost=10, city=owner)
    env.map.get_tile(pos).district = district
    owner.districts.append(district)
    return district


FAR = 20  # on the 40-column board: farther than any range a test uses


# --- (a) pressure ----------------------------------------------------------------------------


def test_religious_pressure_is_the_loyalty_formula_on_the_same_inputs(monkeypatch):
    """Design §7.4 / §11: with weight 1 and no ledger, the pressure of the
    religion seat 1 founded -- every city of seat 1 following it -- equals
    seat 1's loyalty pressure on every city of the board, its own included
    (both count a city for itself at distance 0), at the same range and
    citizen weight. Breaks if the two formulas drift (falloff, inclusive
    range, distance-0 self term, population factor)."""
    monkeypatch.setattr(loyalty, "RANGE", RULES.range)
    monkeypatch.setattr(loyalty, "CITIZEN_WEIGHT", RULES.citizen_weight)
    env = flat()
    targets = [city(env, 0, 10, population=3), city(env, 0, 30, population=2)]
    presser = [city(env, 1, 10 + RULES.range, population=4), city(env, 1, 6, population=2),
               city(env, 1, 10 + RULES.range + 1 + 4, population=5)]
    give(env, 1, *presser)
    assert all(religious_weight(c) == 1 for c in presser), "fixture: no weighted building"
    for target in targets + presser:
        assert pressure(1, target, env) == loyalty.pressure(target, 1, env), target.name
    assert pressure(1, targets[0], env) > 0


def test_weights_and_the_ledger_add_to_the_loyalty_formula(monkeypatch):
    """The two terms religion adds: a source city's citizens weigh
    `religious_weight` (here a synthetic building column of 3: weight 4), so
    its term grows by population * 3 * (citizen_weight - d); a running ledger
    entry adds its amount on the city it is on, and an expired one (rounds
    left 0) or another religion's adds nothing. Breaks if the weight
    multiplies the wrong factor or the ledger is read for the wrong
    religion or after expiry."""
    monkeypatch.setitem(religion_mod.BUILDING_RELIGIOUS_WEIGHT, "Synthetic Altar", 3)
    env = flat()
    target = city(env, 0, 10, population=2)
    source = city(env, 1, 13, population=4)
    give(env, 1, source)
    base = pressure(1, target, env)
    assert base == 4 * (RULES.citizen_weight - 3)
    source.buildings.append("Synthetic Altar")
    assert religious_weight(source) == 4
    assert pressure(1, target, env) == base + 4 * 3 * (RULES.citizen_weight - 3)
    weighted = pressure(1, target, env)
    target.spread_ledger.extend([(1, 60, 4), (1, 15, 0), (0, 99, 5)])
    assert pressure(1, target, env) == weighted + 60


def test_religious_weight_is_one_plus_the_columns_never_a_name(monkeypatch):
    """`religious_weight` = 1 + the `religious_weight` columns of the city's
    buildings and COMPLETE districts, whatever their names: every configured
    building column is read, a district counts only once complete, and a
    synthetic building with a column weighs like any other. Breaks if a
    building or district name is tested in code, or an incomplete district
    counts."""
    env = flat()
    seat = city(env, 0, 10)
    assert religious_weight(seat) == 1
    seat.buildings.extend(sorted(BUILDING_RELIGIOUS_WEIGHT))
    expected = 1 + sum(BUILDING_RELIGIOUS_WEIGHT.values())
    assert religious_weight(seat) == expected
    weighted = [name for name in DISTRICTS if district_spec(name).religious_weight]
    assert weighted, "fixture: some district carries the column"
    district = link(env, seat, weighted[0], 2, complete=False)
    assert religious_weight(seat) == expected
    district.complete = True
    assert religious_weight(seat) == expected + district_spec(weighted[0]).religious_weight
    monkeypatch.setitem(religion_mod.BUILDING_RELIGIOUS_WEIGHT, "Synthetic Altar", 5)
    seat.buildings.append("Synthetic Altar")
    assert religious_weight(seat) == expected + district_spec(weighted[0]).religious_weight + 5


def test_a_secular_city_resists_with_population_times_secular_weight():
    """Design §7.4, L2: the incumbent term of a secular city is population x
    `secular_weight` (a bigger city resists more); of a follower city, its
    own religion's pressure on it. Breaks if the secular term is read for a
    follower city or loses the population factor."""
    env = flat()
    small, big = city(env, 0, 10, population=1), city(env, 0, 30, population=6)
    assert incumbent_term(small, env) == secular_pressure(small) == RULES.secular_weight
    assert incumbent_term(big, env) == 6 * RULES.secular_weight
    give(env, 0, big)
    assert incumbent_term(big, env) == pressure(0, big, env) > 0


def test_the_range_param_raises_range_and_citizen_weight_together(monkeypatch):
    """v3 fixes L3: a `religion_param { range = 3 }` enhancer raises the
    religion's reach AND its citizen weight by 3, so a follower city 3 tiles
    beyond the base range presses with the same positive weight the base
    edge had, and a city inside presses 3 x population more. Breaks if only
    one of the two numbers is raised, or the param is read from anyone but
    the founder."""
    env = flat(m=60)
    target = city(env, 0, 0, population=1)
    edge = city(env, 1, RULES.range + 3, population=2)
    inside = city(env, 1, env.m - 2, population=5)
    give(env, 1, edge, inside)
    assert pressure(1, target, env) == 5 * (RULES.citizen_weight - 2)
    name = belief(monkeypatch, "Synthetic Preachers", TIER_ENHANCER,
                  [{"kind": "religion_param", "range": 3}])
    env.players[1].religion.enhancer_belief = name
    assert pressure_reach(env.players[1]) == RULES.range + 3
    assert pressure_citizen_weight(env.players[1]) == RULES.citizen_weight + 3
    assert pressure(1, target, env) == (5 * (RULES.citizen_weight + 3 - 2)
                                        + 2 * (RULES.citizen_weight - RULES.range))
    assert pressure_reach(env.players[0]) == RULES.range


# --- (b) lapse and the dead founder (v3 fixes L2) ---------------------------------------------


def _lapse_board(monkeypatch):
    env = flat()
    home = city(env, 1, 10, population=3)
    neighbour = city(env, 1, 13, population=2)
    target = city(env, 0, 16, population=2)
    name = belief(monkeypatch, "Synthetic Hymn", TIER_FOLLOWER,
                  [{"kind": "city_yield", "faith": 1}])
    give(env, 1, home, neighbour, follower_belief=name)
    target.spread_ledger.append((1, 40, 5))
    env.players[1].pantheon = religion_model.PANTHEON_ORDER[0]
    return env, home, neighbour, target


def test_a_lapsed_religion_loses_its_outward_pressure_and_keeps_its_followers_defence(monkeypatch):
    """L2: while the religion is lapsed its pressure on a city that does not
    follow it -- the ledger entry there included -- is 0, while its pressure
    on its own follower cities (the self term and the neighbouring
    followers') is unchanged, and the follower belief still pays in the
    follower city. Breaks if lapse touches the followers, or leaves the
    ledger running on a foreign city."""
    env, home, neighbour, target = _lapse_board(monkeypatch)
    before = {c.name: pressure(1, c, env) for c in (home, neighbour, target)}
    faith_before = city_yield(home, "faith")
    assert before[target.name] > 40
    env.players[1].religion.lapsed = True
    assert is_unpaid(env.players[1].religion, env)
    assert pressure(1, target, env) == 0
    assert pressure(1, home, env) == before[home.name]
    assert pressure(1, neighbour, env) == before[neighbour.name]
    assert city_yield(home, "faith") == faith_before
    assert env.players[1].religion.beliefs  # beliefs stay


def test_upkeep_is_debited_before_pay_and_a_short_pool_pays_nothing_and_lapses(monkeypatch):
    """L2 in the religion step: a pool covering `upkeep_per_follower_city` x
    follower cities (all owners) is debited exactly that and the founder is
    paid; a pool one tenth short keeps every tenth, the religion lapses and
    the founder pay stops; covered again, it is paid and no longer lapsed.
    Breaks if the debit is partial, follows the pay, or lapse leaves the pay
    running."""
    env, home, neighbour, target = _lapse_board(monkeypatch)
    pays = belief(monkeypatch, "Synthetic Tithe", TIER_FOUNDER,
                  [{"kind": "per_follower_city", "gold": 1}])
    player = env.players[1]
    player.religion.founder_belief = pays
    target.religion = 1  # a follower of another owner counts for the upkeep too
    owed = upkeep_tenths(player, env)
    assert owed == 10 * RULES.upkeep_per_follower_city * 3 > 0
    player.faith = owed - 1
    gold = player.gold
    env._religion_step(player)
    assert player.faith == owed - 1 and player.religion.lapsed
    assert player.gold == gold and env.episode_stats[1]["founder_pay_tenths"] == 0
    assert env.episode_stats[1]["religion_lapsed_rounds"] == 1
    player.faith = owed
    env._religion_step(player)
    assert player.faith == 0 and not player.religion.lapsed
    assert player.gold == gold + sum(founder_pay_tenths(player, env).values()) > gold
    assert env.episode_stats[1]["faith_spent_religion"] == owed


def test_a_dead_founders_religion_is_permanently_unpaid_and_its_followers_keep_it(monkeypatch):
    """L2: a dead founder's religion projects no outward pressure, whatever
    `lapsed` says, its follower cities keep their self terms and their
    religion, the founder is charged and paid nothing. Breaks if the dead
    founder's religion keeps spreading, or its followers lose it."""
    env, home, neighbour, target = _lapse_board(monkeypatch)
    founder = env.players[1]
    held = pressure(1, home, env)
    founder.is_dead = True
    founder.faith = 1000
    assert not founder.religion.lapsed and is_unpaid(founder.religion, env)
    assert pressure(1, target, env) == 0
    assert pressure(1, home, env) == held
    env._religion_upkeep(founder)
    assert founder.faith == 1000 and founder_pay_tenths(founder, env) == {}
    phase(env, RULES.conversion_rounds + 1)
    assert home.religion == neighbour.religion == 1


# --- (c) the conversion phase (design §7.4, L6) -----------------------------------------------


def _ledger_board(target_pop=4, players=2):
    """A secular city of seat 0 and seat 1's religion, its follower city out
    of range: the only pressure on the target is what the ledger holds."""
    env = flat(players=players)
    target = city(env, 0, 0, population=target_pop)
    home = city(env, 1, FAR, population=1)
    give(env, 1, home)
    assert pressure(1, target, env) == 0
    return env, target


def _threshold(incumbent):
    """The least candidate pressure that wins the margin over `incumbent`."""
    return -(-incumbent * (100 + RULES.conversion_margin) // 100)


def test_conversion_needs_the_margin_for_conversion_rounds_consecutive_phases():
    """A candidate pressing exactly the margin over the secular term converts
    the city at the `conversion_rounds`-th phase and not before; one point
    less never converts. The owner never changes. Breaks if the margin
    test, its integer rounding, or the streak length is off by one."""
    env, target = _ledger_board()
    need = _threshold(secular_pressure(target))
    target.spread_ledger.append((1, need - 1, 100))
    phase(env, RULES.conversion_rounds + 2)
    assert target.religion is None and target.conversion_streak == (None, 0)
    target.spread_ledger[:] = [(1, need, 100)]
    for rounds in range(1, RULES.conversion_rounds):
        phase(env)
        assert target.religion is None and target.conversion_streak == (1, rounds)
    phase(env)
    assert target.religion == 1 and target.conversion_streak == (None, 0)
    assert target.player is env.players[0]
    assert env.episode_stats[1]["cities_converted_in"] == 1


def test_a_follower_city_converts_against_its_own_religions_pressure(monkeypatch):
    """L2: once a city follows a religion, the incumbent term is that
    religion's pressure on it, not the secular one; conversion away counts
    `cities_converted_out` for the old religion's founder. Breaks if a
    follower city is still measured against secular resistance."""
    rules(monkeypatch, conversion_rounds=1)
    env, target = _ledger_board(players=3)
    give(env, 2, target)
    own = pressure(2, target, env)
    assert own != secular_pressure(target)
    target.spread_ledger.append((1, _threshold(own) - 1, 9))
    phase(env)
    assert target.religion == 2
    target.spread_ledger[:] = [(1, _threshold(own), 9)]
    phase(env)
    assert target.religion == 1
    assert env.episode_stats[2]["cities_converted_out"] == 1


def test_zero_pressure_never_converts(monkeypatch):
    """L6: a candidate needs pressure > 0 -- with secular resistance at 0
    (secular_weight 0) and no religion pressing, nothing starts a streak,
    though 0 x 100 >= 0 x 125. Breaks if a zero-pressure religion can be a
    candidate."""
    rules(monkeypatch, secular_weight=0)
    env, target = _ledger_board()
    assert candidate(target, env) == (None, 0)
    phase(env, RULES.conversion_rounds + 1)
    assert target.religion is None and target.conversion_streak == (None, 0)


def test_a_changed_candidate_restarts_the_streak_at_one():
    """L6: when the strongest foreign religion changes, the streak restarts
    at 1 for the new one; ties go to the lower founder index (v2 fixes).
    Breaks if the streak carries over between candidates or the tie-break
    reads anything but the founder index."""
    env, target = _ledger_board(players=3)
    give(env, 2, city(env, 2, FAR + 5, population=1))
    need = _threshold(secular_pressure(target))
    target.spread_ledger.append((2, need, 100))
    phase(env, 1)
    assert target.conversion_streak == (2, 1)
    target.spread_ledger.append((1, need, 100))
    assert candidate(target, env) == (1, need)  # a tie: the lower founder index
    phase(env)
    assert target.conversion_streak == (1, 1)


def test_immunity_resets_the_streak_and_blocks_conversion_while_it_runs():
    """L6: a city with `inquisition_rounds_left` > 0 never converts, its
    streak is reset to (None, 0) and the immunity counts down one per phase;
    once it is out the streak starts again at 1. Breaks if immunity only
    pauses the streak, or is never decremented."""
    env, target = _ledger_board()
    target.spread_ledger.append((1, _threshold(secular_pressure(target)), 100))
    phase(env)
    assert target.conversion_streak == (1, 1)
    target.inquisition_rounds_left = RULES.conversion_rounds + 1
    for left in range(RULES.conversion_rounds, -1, -1):
        phase(env)
        assert target.religion is None and target.conversion_streak == (None, 0)
        assert target.inquisition_rounds_left == left
    phase(env)
    assert target.conversion_streak == (1, 1)


def test_the_phase_reads_phase_start_state_in_city_id_order():
    """Design §7.4: every city's decision is taken from the state at the
    start of the phase. Here the lower-id city converts this phase, and in
    the live state it would then press its neighbour past the margin --
    but the neighbour's streak stays what the phase-start state gave
    (none). Breaks if the phase reads live state (a city converted earlier
    in the loop pressing the next one)."""
    import civulator.game.religion as rel
    env, first = _ledger_board(target_pop=1)
    first.population = 5
    neighbour = city(env, 0, 3, population=1)
    assert first.city_id < neighbour.city_id
    assert rel.pressure(1, neighbour, env) == 0
    first.spread_ledger.append((1, _threshold(secular_pressure(first)), 100))
    first.conversion_streak = (1, RULES.conversion_rounds - 1)
    predicted = {c.city_id: rel.next_streak(c, env) for c in (first, neighbour)}
    phase(env)
    assert first.religion == 1
    assert neighbour.conversion_streak == predicted[neighbour.city_id][0] == (None, 0)
    assert rel.wins_margin(rel.pressure(1, neighbour, env), secular_pressure(neighbour)), \
        "fixture: the live state would have started the neighbour's streak"


def test_a_ledger_entry_counts_in_exactly_spread_rounds_phases():
    """L6: a directed spread's entry counts in the phase, then is
    decremented, and is removed at 0 -- so it presses in exactly
    `spread_rounds` phases. Breaks if the entry is decremented before it
    counts, or kept at 0."""
    env, target = _ledger_board()
    player = env.players[1]
    player.faith = spread_cost_tenths(player)
    target_far = env.map.distance_function(target.coordinates, player.cities[0].coordinates)
    assert target_far > pressure_reach(player)
    home = player.cities[0]
    assert env.spread_religion(player, home)
    counted = 0
    while home.spread_ledger:
        assert pressure(1, home, env) > 0
        counted += religion_mod.ledger_pressure(1, home) > 0
        phase(env)
    assert counted == RULES.spread_rounds


# --- (d) directed spread and inquisition (design §9) ------------------------------------------


def test_spread_refusals_name_every_clause():
    """`spread_refusals` lists why a spread is refused -- no religion; a
    target no follower city reaches; faith short of the cost -- and is empty
    for a target in reach with the faith. A target of any owner may be
    chosen. Breaks if a clause is dropped from the predicate (the mask would
    offer a spread the action refuses)."""
    env = flat(m=60)
    home = city(env, 1, 0, population=2)
    near = city(env, 0, RULES.range, population=1)
    far = city(env, 0, RULES.range + 5, population=1)
    founder = env.players[1]
    assert spread_refusals(founder, near, env) == [REFUSE_NO_RELIGION]
    give(env, 1, home)
    founder.faith = spread_cost_tenths(founder) - 1
    assert spread_refusals(founder, near, env) == [REFUSE_FAITH]
    assert spread_refusals(founder, far, env) == [REFUSE_OUT_OF_RANGE, REFUSE_FAITH]
    founder.faith += 1
    assert spread_refusals(founder, near, env) == []
    assert not env.spread_religion(founder, far)
    env.players[1].is_dead = True
    assert spread_refusals(founder, near, env) == [REFUSE_DEAD]


def test_each_spread_costs_more_and_appends_its_entry(monkeypatch):
    """A spread debits `spread_cost_tenths`, adds one use (the next costs
    `spread_cost_step` more, in tenths) and appends (religion,
    spread_amount, spread_rounds) to the target's ledger; the
    `religion_param` percents scale the cost (floored) and the amount.
    Breaks if the price curve ignores the uses or the params."""
    env = flat()
    home = city(env, 1, 0, population=2)
    target = city(env, 0, 3, population=1)
    give(env, 1, home)
    founder = env.players[1]
    first = spread_cost_tenths(founder)
    assert first == 10 * RULES.spread_cost
    founder.faith = 10 * first
    assert env.spread_religion(founder, target)
    assert founder.faith == 9 * first and founder.spread_uses == 1
    assert target.spread_ledger == [(1, RULES.spread_amount, RULES.spread_rounds)]
    assert spread_cost_tenths(founder) == first + 10 * RULES.spread_cost_step
    name = belief(monkeypatch, "Synthetic Missions", TIER_ENHANCER,
                  [{"kind": "religion_param", "spread_amount_percent": 50, "cost_percent": -30}])
    founder.religion.enhancer_belief = name
    base = RULES.spread_cost + RULES.spread_cost_step
    assert spread_cost_tenths(founder) == 10 * base * 70 // 100
    assert spread_amount(founder) == RULES.spread_amount * 150 // 100
    assert inquisition_cost_tenths(founder) == 10 * RULES.inquisition_cost * 70 // 100
    assert env.episode_stats[1]["spreads"] == 1


def test_inquisition_refusals_and_effect():
    """`inquisition_refusals`: only in an own city, only with the faith. The
    effect: the city follows the player's own religion (secular for a player
    that founded none), `inquisition_rounds` of immunity, streak reset,
    exactly the cost debited. Breaks if a clause is dropped or the effect
    leaves the old religion or the streak in place."""
    env = flat(players=3)
    mine = city(env, 0, 0, population=2)
    theirs = city(env, 1, 10, population=2)
    give(env, 2, mine, city(env, 2, 20))
    player = env.players[0]
    cost = inquisition_cost_tenths(player)
    player.faith = cost - 1
    assert inquisition_refusals(player, theirs, env) == [REFUSE_NOT_OWN_CITY, REFUSE_FAITH]
    assert inquisition_refusals(player, mine, env) == [REFUSE_FAITH]
    assert not env.inquisition(player, mine)
    player.faith = cost
    mine.conversion_streak = (2, 1)
    assert env.inquisition(player, mine)
    assert mine.religion is None and player.faith == 0
    assert mine.inquisition_rounds_left == RULES.inquisition_rounds
    assert mine.conversion_streak == (None, 0)
    give(env, 0, city(env, 0, 30))
    player.faith = cost
    mine.religion = 2
    assert env.inquisition(player, mine) and mine.religion == 0
    assert env.episode_stats[0]["inquisitions"] == 2


def test_no_engine_default_spends_faith_on_spreading():
    """Design §9: a game left to the engine defaults never buys a directed
    spread or an inquisition, however much faith a founder holds. Breaks if
    a default starts calling spread_religion or inquisition."""
    env = flat()
    home = city(env, 1, 0, population=3)
    city(env, 0, 4, population=1)
    give(env, 1, home)
    env.players[1].pantheon = religion_model.PANTHEON_ORDER[0]
    env.players[1].faith = 10 ** 6
    for _ in range(2 * 3):
        env.next_turn()
    assert env.players[1].spread_uses == 0
    assert all(not c.spread_ledger for c in env.city_by_id.values())
    assert env.episode_stats[1]["spreads"] == env.episode_stats[1]["inquisitions"] == 0


# --- (e) loyalty (design §7.5, L5) -------------------------------------------------------------


def test_the_loyalty_term_charges_a_city_following_a_religion_its_owner_did_not_found():
    """L5: `foreign_religion_loyalty` applies iff the city follows a
    religion and it is not the one its owner founded -- a founder's secular
    city and a founder's follower city pay nothing, a non-founder's city
    following someone's religion pays it, and the term is one more term of
    `loyalty_delta`. Breaks if the term reads the owner's religion for a
    secular city or is left out of the delta."""
    env = flat()
    founders_follower = city(env, 1, 0, population=2)
    founders_secular = city(env, 1, 30, population=2)
    adopter = city(env, 0, 15, population=2)
    give(env, 1, founders_follower)
    assert religion_mod.loyalty_term(founders_follower, env) == 0
    assert religion_mod.loyalty_term(founders_secular, env) == 0
    assert religion_mod.loyalty_term(adopter, env) == 0
    before = loyalty.loyalty_delta(adopter, env)
    adopter.religion = 1
    assert religion_mod.loyalty_term(adopter, env) == RULES.foreign_religion_loyalty
    assert loyalty.loyalty_delta(adopter, env) == before + RULES.foreign_religion_loyalty


# --- (f) capture and flip keep the city's religious state (design §7.5) -----------------------


@pytest.mark.parametrize("door", ["capture", "flip"])
def test_capture_and_flip_keep_religion_ledger_streak_and_immunity(door):
    """Design §7.5: a city's religion, ledger, streak and immunity are the
    city's -- kept through `set_owner` by force and by loyalty alike.
    Breaks if either door clears any of them."""
    env = flat()
    target = city(env, 0, 10, population=2)
    city(env, 0, 30)
    give(env, 1, target, city(env, 1, 14))
    target.spread_ledger.append((1, 30, 4))
    target.conversion_streak = (1, 1)
    target.inquisition_rounds_left = 2
    kept = (target.religion, list(target.spread_ledger), target.conversion_streak,
            target.inquisition_rounds_left)
    if door == "capture":
        target.set_owner(env.players[1])
    else:
        env._flip_city(target, env.players[1])
    assert target.player is env.players[1]
    assert (target.religion, target.spread_ledger, target.conversion_streak,
            target.inquisition_rounds_left) == kept


# --- (g) the religious victory (design §7.5, "v2 fixes") ----------------------------------------


def _victory_board():
    env = flat(players=3)
    seats = {i: [city(env, i, 13 * i + k * 4) for k in range(3)] for i in range(3)}
    give(env, 0, *seats[0])
    return env, seats


def test_the_religious_victory_needs_the_flag(monkeypatch):
    """Off by default (C7): a religion followed by every city on the board
    wins nothing while `[game] religious_victory` is false. Breaks if the
    branch ignores the flag."""
    monkeypatch.setattr(victory, "RELIGIOUS_ENABLED", False)
    env, seats = _victory_board()
    for c in env.city_by_id.values():
        c.religion = 0
    assert victory.religious_winner(env) is None
    assert victory.decisive_outcome(env) == (None, None)


def test_the_religious_victory_needs_a_majority_of_every_living_players_cities(monkeypatch):
    """With the flag on: the founder wins when MORE than half of each living
    player's cities follow its religion -- half is not enough, one player
    short blocks it, a dead player is not counted, and a living player with
    no city (alive by a Settler) blocks it (0 > 0 fails). The verdict ends
    the game through `decisive_outcome` / `game_over`. Breaks if the branch
    counts cities board-wide, counts dead players, or lives outside
    `decisive_outcome`."""
    monkeypatch.setattr(victory, "RELIGIOUS_ENABLED", True)
    env, seats = _victory_board()
    for i in (1, 2):
        seats[i][0].religion = seats[i][1].religion = 0
    assert victory.decisive_outcome(env) == (0, "religious")
    assert victory.game_over(env) and victory.determine_outcome(env) == (0, "religious")
    seats[2][1].religion = None  # 1 of 3: not a majority
    assert victory.religious_winner(env) is None
    seats[2][2].religion = 0     # 2 of 3 again
    assert victory.religious_winner(env) == 0
    seats[1].append(city(env, 1, 37))  # seat 1: 2 of 4 -- half, not more
    assert victory.religious_winner(env) is None
    seats[1][2].religion = 0     # 3 of 4
    assert victory.religious_winner(env) == 0
    # A living player without a city (a Settler keeps it alive) blocks it.
    for c in list(seats[2]):
        env.remove_city(c)
    settler = SettlerUnit(env.players[2], (0, 0))
    env.players[2].units.append(settler)
    assert not env.players[2].is_dead
    assert victory.religious_winner(env) is None
    env.players[2].is_dead = True
    assert victory.religious_winner(env) == 0
    env._update_done()
    assert env.done


# --- (h) religion_param isolation, state, determinism -----------------------------------------


def test_religion_params_reads_only_the_founders_enhancer(monkeypatch):
    """The one reader of `religion_param` sums the founder's entries; a
    player without the enhancer reads zeros. Breaks if the kind is read for
    another player or from another source."""
    env = flat()
    give(env, 0, city(env, 0, 0))
    give(env, 1, city(env, 1, 20))
    name = belief(monkeypatch, "Synthetic Reach", TIER_ENHANCER,
                  [{"kind": "religion_param", "range": 2, "cost_percent": 10}])
    env.players[0].religion.enhancer_belief = name
    assert [e.kind for e in active_effects(env.players[0], kind=KIND_RELIGION_PARAM)] \
        == ["religion_param"]
    assert religion_params(env.players[0]).range == 2
    assert religion_params(env.players[0]).cost_percent == 10
    assert religion_params(env.players[1]) == religion_mod.ReligionParams()


def test_the_episode_fingerprint_sees_every_religion_engine_field():
    """v2 fixes: the streak, the ledger, the immunity, the spread-use counter
    and the lapsed flag are per-episode state -- each moves the episode
    fingerprint, and reset clears every one. Breaks if a field leaves the
    fingerprint's reach or survives `reset`."""
    a = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=5)
    b = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=5)
    base = episode_fingerprint(b)
    assert episode_fingerprint(a) == base
    home = a.players[0].cities[0]
    give(a, 0, home)
    with_religion = episode_fingerprint(a)
    for mutate in (lambda: home.spread_ledger.append((0, 1, 1)),
                   lambda: setattr(home, "conversion_streak", (0, 1)),
                   lambda: setattr(home, "inquisition_rounds_left", 1),
                   lambda: setattr(a.players[0], "spread_uses", 1),
                   lambda: setattr(a.players[0].religion, "lapsed", True)):
        snapshot = episode_fingerprint(a)
        mutate()
        assert episode_fingerprint(a) != snapshot
    assert episode_fingerprint(a) != with_religion
    a.reset(seed=5)
    assert episode_fingerprint(a) == base
    assert a.players[0].spread_uses == 0
    assert all(c.spread_ledger == [] and c.conversion_streak == (None, 0)
               and c.inquisition_rounds_left == 0 for c in a.city_by_id.values())


GAME = '''
import sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
from conftest import grant_all
from civulator.game.environment import GameEnvironment
from civulator.game.religion import Religion
from civulator.religion_model import TIER_FOLLOWER, TIER_FOUNDER, beliefs_of_tier


def play(seed, rounds):
    """Two seats on a basic world; seat 0's capital (population 6) follows
    the religion seat 0 is handed, and seat 0 spreads it to seat 1's
    capital once. The religion state of every city and the religion stats
    after `rounds` rounds of engine play."""
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for player in env.players:
        grant_all(player)
    env.players[0].cities[0].population = 6
    env.players[0].religion = Religion(founder=0, founder_belief=beliefs_of_tier(TIER_FOUNDER)[0],
                                       follower_beliefs=[beliefs_of_tier(TIER_FOLLOWER)[0]])
    env.players[0].cities[0].religion = 0
    env.players[0].faith = 10 ** 5
    assert env.spread_religion(env.players[0], env.players[1].cities[0])
    for _ in range(2 * rounds):
        env.next_turn()
    cities = [(c.city_id, c.religion, c.conversion_streak, c.inquisition_rounds_left,
               tuple(c.spread_ledger)) for c in (env.city_by_id[i] for i in sorted(env.city_by_id))]
    keys = ("cities_converted_in", "cities_converted_out", "spreads", "religion_lapsed_rounds",
            "faith_spent_religion")
    stats = [tuple(env.episode_stats[i][k] for k in keys) for i in range(2)]
    return cities, stats
'''
SEED, ROUNDS = 13, 8


def _play_here(seed=SEED, rounds=ROUNDS):
    namespace = {}
    exec(GAME.format(root=ROOT_DIR, tests=TESTS_DIR), namespace)
    return namespace["play"](seed, rounds)


def test_two_same_seed_games_convert_alike():
    """Two games from one seed end with the same religion state in every
    city and the same religion stats, and the fixture is live (a spread was
    bought and converted the target). Breaks if the phase or
    the spread depends on anything but state."""
    first = _play_here()
    assert first == _play_here()
    cities, stats = first
    assert stats[0][2] == 1 and stats[0][0] >= 1, "fixture: the spread converted the city"


def test_conversion_does_not_depend_on_the_hash_seed():
    """A fresh process with another PYTHONHASHSEED reproduces the same
    conversions from the same seed. Breaks if any religion walk iterates a
    hash-ordered container."""
    code = GAME.format(root=ROOT_DIR, tests=TESTS_DIR) + f"print(play({SEED}, {ROUNDS}))\n"
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONHASHSEED": "2"}, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == str(_play_here())
