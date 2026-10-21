"""Issue #116 P2: the tech tree and research (docs/progression_design.md §4,
§13, "v2 fixes"; the §14 rows on research, the tree and the defaults).

No test pins which techs exist, how many, or in what order: each asserts the
rule every configured tech, or every research state, obeys. Reference values
are re-derived here from the parsed tree, never from the resolution code.
"""

import random

import pytest

from civulator import research_model
from civulator.game.defaults import default_research
from civulator.game.environment import GameEnvironment
from civulator.research_model import (
    ERAS,
    TECH_COST_PERCENT,
    TECH_INDEX,
    TECH_ORDER,
    TECHS,
    parse_research,
    parse_tree,
    scaled_tech_cost,
)

from conftest import grant_all
from test_districts import board, make_city


def _available(known):
    """Available techs, re-derived: not known, every prerequisite known."""
    return [t for t in TECHS if t not in known and all(r in known for r in TECHS[t].requires)]


def _pool_cost(tech):
    """The pool (tenths) a tech costs: 10 * (cost * percent // 100)."""
    return 10 * (TECHS[tech].cost * TECH_COST_PERCENT // 100)


def _fresh_player(env, index=0):
    """A board player with no techs (board() grants the whole tree)."""
    player = env.players[index]
    player.techs.clear()
    player.current_tech = None
    return player


# --- The tree -------------------------------------------------------------------


def test_the_prerequisite_graph_is_acyclic_and_every_tech_is_reachable():
    """Every tech's prerequisites are techs, the graph has no cycle, and
    learning whatever is available round after round learns the whole tree
    from the start set. Breaks if a config edit adds a dead or unreachable
    node (design §14: 'a dead node or an unreachable item')."""
    assert TECHS, "fixture: a tree is configured"
    for spec in TECHS.values():
        assert all(r in TECHS for r in spec.requires), spec.name
        assert spec.name not in spec.requires
        assert spec.era in ERAS
        assert isinstance(spec.cost, int) and spec.cost > 0
    known = []
    while True:
        ready = _available(known)
        if not ready:
            break
        known.extend(ready)
    assert sorted(known) == sorted(TECHS)
    assert any(not s.requires for s in TECHS.values()), "a start set exists"


def test_tech_order_and_index_follow_the_config_tables():
    """TECH_ORDER is the config order (the auto-pick tie-break) and
    TECH_INDEX its inverse. Breaks if the order comes from a set or a sort."""
    assert TECH_ORDER == tuple(research_model.CFG["techs"])
    assert all(TECH_ORDER[TECH_INDEX[t]] == t for t in TECHS)


def test_the_scaled_cost_is_whole_points_of_the_percent():
    """Every tech costs cost * [research] tech_cost_percent // 100 whole
    science. Breaks on float arithmetic or a second scaling knob."""
    for tech, spec in TECHS.items():
        cost = scaled_tech_cost(tech)
        assert type(cost) is int
        assert cost == spec.cost * TECH_COST_PERCENT // 100


def _tree(**overrides):
    tables = {
        "A": {"cost": 10, "era": ERAS[0]},
        "B": {"cost": 20, "era": ERAS[0], "requires": ["A"]},
    }
    tables.update(overrides)
    return tables


@pytest.mark.parametrize("tables", [
    _tree(B={"cost": 20, "era": ERAS[0], "requires": ["Nowhere"]}),   # unknown prerequisite
    _tree(A={"cost": 10, "era": ERAS[0], "requires": ["B"]}),         # cycle A <-> B
    _tree(C={"cost": 5, "era": ERAS[0], "requires": ["C"]}),          # self cycle
    _tree(B={"cost": 20, "era": "Atomic", "requires": ["A"]}),        # unknown era
    _tree(B={"cost": 0, "era": ERAS[0], "requires": ["A"]}),          # non-positive cost
    _tree(B={"cost": 2.5, "era": ERAS[0], "requires": ["A"]}),        # non-int cost
    _tree(B={"cost": True, "era": ERAS[0], "requires": ["A"]}),       # a bool is not a cost
    _tree(B={"cost": 20, "era": ERAS[0], "requires": ["A", "A"]}),    # duplicate prerequisite
    _tree(B={"cost": 20, "era": ERAS[0], "require": ["A"]}),          # unknown key (typo)
    _tree(B={"era": ERAS[0], "requires": ["A"]}),                     # missing cost
    _tree(B={"cost": 20, "era": ERAS[0], "requires": "A"}),           # requires not a list
    {},                                                                # empty tree
])
def test_a_malformed_tree_raises_at_load(tables):
    """parse_tree (used for [techs.*], and by P4 for [civics.*]) refuses a
    prerequisite naming nothing, a cycle, an unknown era, a bad cost and an
    unknown key. Breaks if validation is skipped."""
    with pytest.raises(ValueError):
        parse_tree(tables, "techs")


def test_a_well_formed_tree_parses_in_config_order_with_raw_effects_kept():
    """A valid tree parses in config order; `effects` is kept raw for the
    P4 interpreter. Breaks if the parser reorders nodes or drops effects."""
    effect = {"kind": "anything", "amount": 1}
    tree = parse_tree(_tree(B={"cost": 20, "era": ERAS[1], "requires": ["A"],
                               "effects": [effect]}), "techs")
    assert list(tree) == ["A", "B"]
    assert tree["B"].requires == ("A",) and tree["B"].effects == (effect,)
    assert tree["A"].requires == () and tree["A"].effects == ()


@pytest.mark.parametrize("table", [
    {},                                                 # missing key
    {"tech_cost_percent": 75, "speed": 2},              # unknown key
    {"tech_cost_percent": 0},                           # not positive
    {"tech_cost_percent": 7.5},                         # not an int
])
def test_the_research_table_is_read_strictly(table):
    """[research] holds exactly its known keys, each a positive int.
    Breaks if a typo in the one dial is silently ignored."""
    with pytest.raises(ValueError):
        parse_research(table)


def test_validate_tech_name_accepts_techs_and_refuses_anything_else():
    """The item registries' one check of a `requires_tech` column. Breaks if
    a misspelt or missing tech name passes."""
    for tech in TECHS:
        assert research_model.validate_tech_name(tech, "x") == tech
    for bad in ("Alchemy", "", None, 3):
        with pytest.raises(ValueError):
            research_model.validate_tech_name(bad, "x")


# --- Resolution (§4.3) ---------------------------------------------------------------


def test_research_completes_exactly_when_the_pool_reaches_the_scaled_cost():
    """One pool point short: nothing completes and nothing is paid. At the
    cost plus a remainder: the tech completes, exactly the cost is paid, the
    remainder stays, current_tech clears and the counter rises by one.
    Breaks if resolution drifts from 10 * scaled cost or drops the overflow."""
    env = board()
    player = _fresh_player(env)
    tech = _available(player.techs)[0]
    assert env.set_research(player, tech)
    cost = _pool_cost(tech)
    stats = env.episode_stats[player.player_index]

    player.science = cost - 1
    assert env.resolve_research(player) is None
    assert player.techs == [] and player.science == cost - 1
    assert player.current_tech == tech and stats["techs_researched"] == 0

    player.science = cost + 7
    assert env.resolve_research(player) == tech
    assert player.techs == [tech]
    assert player.science == 7
    assert player.current_tech is None
    assert stats["techs_researched"] == 1


def test_at_most_one_tech_completes_per_turn_and_the_overflow_waits():
    """A pool large enough for the whole tree completes exactly one tech per
    own turn (Player.start_turn -> economy phase), paying exactly that
    tech's cost and keeping the rest. The player has no city, so research is
    the only thing that touches the pool. Breaks if resolution loops within
    a turn (design §4.3: one per turn, Civ 6)."""
    env = board()
    player = _fresh_player(env)
    assert not player.cities
    huge = 2 * sum(_pool_cost(t) for t in TECHS)
    player.science = huge
    paid = 0
    for turn in range(1, 4):
        env.turn_counter += 1
        player.start_turn()
        assert len(player.techs) == turn
        paid += _pool_cost(player.techs[-1])
        assert player.science == huge - paid


def test_completion_order_is_kept_and_every_completed_tech_was_available():
    """`Player.techs` is the list of completed techs in completion order;
    each was available (its prerequisites earlier in the list) when it
    completed. Breaks if techs become a set or resolution skips the
    prerequisite check."""
    env = board()
    player = _fresh_player(env)
    player.science = 2 * sum(_pool_cost(t) for t in TECHS)
    while True:
        done = env.resolve_research(player)
        if done is None:
            break
    assert sorted(player.techs) == sorted(TECHS), "the whole tree completes"
    for i, tech in enumerate(player.techs):
        assert all(r in player.techs[:i] for r in TECHS[tech].requires), tech
    assert env.episode_stats[player.player_index]["techs_researched"] == len(TECHS)
    assert env.resolve_research(player) is None and player.current_tech is None


def test_set_research_refuses_an_unavailable_tech_and_changes_nothing():
    """set_research refuses an unknown name, a tech whose prerequisites are
    not all known, and a tech already known -- returning False with the
    current choice untouched -- and accepts an available one. Breaks if an
    agent could research out of order or twice."""
    env = board()
    player = _fresh_player(env)
    start = _available(player.techs)
    assert env.set_research(player, start[0])
    locked = [t for t in TECHS if t not in start]
    assert locked, "fixture: the tree has a tech behind a prerequisite"
    for bad in ["Alchemy", locked[0]]:
        assert env.set_research(player, bad) is False
        assert player.current_tech == start[0]
    player.techs.append(start[0])
    assert env.set_research(player, start[0]) is False
    assert player.current_tech == start[0]
    follow = _available(player.techs)[0]
    assert env.set_research(player, follow) is True
    assert player.current_tech == follow


def test_switching_research_loses_nothing():
    """The pool is one number, not per-tech progress (design §4.3):
    switching keeps the pool, and the new choice completes on it. Breaks if
    a switch resets or splits the pool."""
    env = board()
    player = _fresh_player(env)
    first, second = _available(player.techs)[:2]
    assert env.set_research(player, first)
    player.science = _pool_cost(second)
    assert env.set_research(player, second)
    assert player.science == _pool_cost(second)
    assert env.resolve_research(player) == second


def test_the_default_picks_the_cheapest_available_tech_by_cost_then_config_order():
    """With no choice made, the engine default (game/defaults.py) is the
    available tech minimising (scaled cost, config index), in every state
    along seeded random research orders; None once the tree is known.
    Breaks if the default reads set order, ignores prerequisites or uses
    the unscaled cost."""
    rng = random.Random(116)
    for _ in range(20):
        known = []
        while True:
            options = _available(known)
            player = type("P", (), {"techs": known})()
            if not options:
                assert default_research(player) is None
                break
            expected = min(options, key=lambda t: (
                TECHS[t].cost * TECH_COST_PERCENT // 100, list(TECHS).index(t)))
            assert default_research(player) == expected
            known = known + [rng.choice(options)]


def test_resolve_with_no_choice_uses_the_default():
    """resolve_research picks the default when current_tech is None and
    spends the pool on it. Breaks if the auto-pick is skipped (research
    would be dormant without an agent, design §13)."""
    env = board()
    player = _fresh_player(env)
    expected = default_research(player)
    player.science = _pool_cost(expected)
    assert env.resolve_research(player) == expected


# --- Turn order (v2 fixes) ----------------------------------------------------------


def test_the_economy_phase_runs_after_the_cities_and_before_the_city_strike(monkeypatch):
    """Player.start_turn: cities -> economy phase -> city ranged strike.
    Breaks if research runs before this turn's yields accrue or after the
    strike (the v2 turn order P4/P5 extend)."""
    env = board()
    city = make_city(env, (3, 4))
    calls = []
    monkeypatch.setattr(type(city), "process_turn",
                        lambda self, game_env: calls.append("city"))
    monkeypatch.setattr(env, "economy_phase", lambda player: calls.append("economy"))
    monkeypatch.setattr(env, "city_ranged_attack", lambda c: calls.append("strike"))
    city.player.start_turn()
    assert calls == ["city", "economy", "strike"]


def test_this_turns_science_counts_toward_this_turns_research():
    """A pool one turn's yield short of the cost completes the tech during
    that turn's start: the yield phase accrues first. Breaks if research
    resolves before the cities."""
    env = board()
    player = _fresh_player(env)
    city = make_city(env, (3, 4))
    from civulator.game.yields import city_yield
    gain = city_yield(city, "science")
    assert gain > 0, "fixture: the capital yields science"
    tech = default_research(player)
    player.science = _pool_cost(tech) - gain
    env.turn_counter += 1
    player.start_turn()
    assert player.techs == [tech]
    assert player.science == 0


def test_techs_researched_is_a_declared_int_counter():
    """`techs_researched` is declared at 0 (an int) for every player in the
    fresh episode stats. Breaks if the key is created lazily."""
    env = board()
    for stats in env.episode_stats.values():
        assert stats["techs_researched"] == 0 and type(stats["techs_researched"]) is int


# --- Defaults live in play (§14: a seeded game researches with no agent choice) -----


def _play_rounds(seed, rounds):
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for _ in range(rounds * len(env.players)):
        env.next_turn()
    return env


def test_a_seeded_game_with_no_research_choice_researches_and_reproduces():
    """With nobody choosing research and only turn ends played, every
    player has completed techs within 40 rounds and the counter matches;
    the same seed gives identical techs lists, pools and current choices.
    Breaks if the default is dormant or non-deterministic."""
    first = _play_rounds(5, 40)
    for player in first.players:
        assert player.techs, f"{player.name} researched nothing"
        assert first.episode_stats[player.player_index]["techs_researched"] == len(player.techs)
    second = _play_rounds(5, 40)
    assert [(p.techs, p.science, p.current_tech) for p in first.players] == \
        [(p.techs, p.science, p.current_tech) for p in second.players]


def test_grant_all_knows_the_whole_tree():
    """The shared test helper (tests/conftest.py) grants every tech. Breaks
    if the helper drifts from the tree."""
    env = board()
    player = _fresh_player(env)
    grant_all(player)
    assert sorted(player.techs) == sorted(TECHS)
    assert default_research(player) is None
