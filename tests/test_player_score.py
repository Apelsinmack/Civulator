"""`player_score` is THE score formula (issue #55; #116 P9).

`scripts/watch.py`'s HUD used to re-derive `cities * 10 + units` while
calling `determine_winner` for the verdict two lines later, so a scoreboard
could in principle disagree with the banner beside it. Both now go through
one function, and every weight comes from config.toml rather than a literal.

Since #116 P9 the score is the `[game.score]` sum -- one term per kind of
thing a player holds (cities, units, population, techs, civics, complete
wonders), each a count times its weight (progression design §11, the
restatement table: "`test_player_score.py:20-34` ... inverted (P9)"). The
formula these tests protect is the sum, so every term is exercised with a
count of its own and no test pins a weight's value: weights are read from the
config, or patched to distinct primes to show each term reads its own.
"""

import random

import pytest

from civulator import district_model
from civulator.config import CFG
from civulator.game import victory
from civulator.game.districts import District
from civulator.game.unit import WarriorUnit
from civulator.research_model import CIVIC_ORDER, TECH_ORDER
from civulator.training import trainer

from test_combat_range import make_flat_env, place

WONDER = next(n for n, s in district_model.DISTRICTS.items()
              if s.kind == district_model.KIND_WONDER)
PLAIN = next(n for n, s in district_model.DISTRICTS.items()
             if s.kind == district_model.KIND_DISTRICT)
CENTRES = [(1, 1), (1, 9), (5, 1), (5, 9)]     # at least min_city_distance apart


def give(env, seat, cities=(), units=0, techs=0, civics=0, wonders=0,
         unfinished_wonders=0, plain_districts=0):
    """Hand player `seat` a holding with exactly these counts: one city per
    entry of `cities` (its population), `units` Warriors, the first `techs`
    techs and `civics` civics of their trees, and `wonders` COMPLETE wonders
    (plus `unfinished_wonders` placed ones and `plain_districts` complete
    ordinary districts, which score nothing) spread over its first city.
    Fixture only: districts are linked by hand."""
    player = env.players[seat]
    for index, population in enumerate(cities):
        made = env.found_city(player, CENTRES[seat * 2 + index], f"S{seat}C{index}")
        assert made is not None, "fixture: the city must actually be founded"
        made.population = population
    for i in range(units):
        place(env, WarriorUnit, seat, (7 - seat, i))
    player.techs.extend(TECH_ORDER[:techs])
    player.civics.extend(CIVIC_ORDER[:civics])
    home = player.cities[0] if player.cities else None
    for kind, count, complete in ((WONDER, wonders, True), (WONDER, unfinished_wonders, False),
                                  (PLAIN, plain_districts, True)):
        for _ in range(count):
            home.districts.append(District(kind, home.city_id, (0, 0), complete=complete))
    return player


def expected_from_config(cities, units, population, techs, civics, wonders):
    """The sum, written out from the config tables the way the design states it."""
    game = CFG["game"]
    score = game["score"]
    return (cities * game["city_score_weight"] + units * score["unit_weight"]
            + population * score["population_weight"] + techs * score["tech_weight"]
            + civics * score["civic_weight"] + wonders * score["wonder_weight"])


def test_weights_come_from_config():
    """Every weight the score uses is the config's: `[game] city_score_weight`
    and the five `[game.score]` keys, exported unchanged under the name the
    trainer has always had. Breaks if a weight is hardcoded or read from the
    wrong key."""
    game = CFG["game"]
    assert trainer.CITY_SCORE_WEIGHT == game["city_score_weight"]
    assert victory.SCORE_WEIGHTS == {
        "cities": game["city_score_weight"], "units": game["score"]["unit_weight"],
        "population": game["score"]["population_weight"], "techs": game["score"]["tech_weight"],
        "civics": game["score"]["civic_weight"], "wonders": game["score"]["wonder_weight"],
    }


def test_a_player_with_nothing_scores_zero():
    """No cities, units, techs, civics or wonders: no term has a constant
    part. Breaks if the score has a base or a floor of its own."""
    env = make_flat_env()
    assert victory.player_score(env.players[0]) == 0


def test_the_score_is_the_sum_of_every_term_with_its_configured_weight():
    """Cities, units, population, techs, civics and complete wonders each
    count with their weight from config, and nothing else counts: a placed,
    unfinished wonder and a complete ordinary district add nothing. Breaks if
    a term is dropped, double-counted or reads another term's weight, or if
    a wonder scores before it is complete or a plain district scores as one."""
    env = make_flat_env()
    player = give(env, 0, cities=(4, 2), units=3, techs=5, civics=4, wonders=2,
                  unfinished_wonders=1, plain_districts=1)
    counts = victory.score_counts(player)
    assert counts == {"cities": 2, "units": 3, "population": 6, "techs": 5,
                      "civics": 4, "wonders": 2}
    assert victory.player_score(player) == expected_from_config(2, 3, 6, 5, 4, 2)
    assert victory.player_score(player) == sum(victory.score_breakdown(player).values())


def test_each_term_reads_its_own_weight(monkeypatch):
    """With every weight patched to a distinct prime and every count distinct,
    the total decomposes uniquely: each term is its count times its own
    weight. Breaks if two terms swap weights or one term reads a neighbour's."""
    weights = {"cities": 2, "units": 3, "population": 5, "techs": 7, "civics": 11, "wonders": 13}
    monkeypatch.setattr(victory, "SCORE_WEIGHTS", weights)
    env = make_flat_env()
    player = give(env, 0, cities=(3, 2), units=4, techs=6, civics=3, wonders=1)
    breakdown = victory.score_breakdown(player)
    assert breakdown == {"cities": 2 * 2, "units": 4 * 3, "population": 5 * 5,
                         "techs": 6 * 7, "civics": 3 * 11, "wonders": 1 * 13}
    assert victory.player_score(player) == sum(breakdown.values())


@pytest.mark.parametrize("term, give_kwargs", [
    ("cities", {"cities": (1,)}),
    ("units", {"units": 1}),
    ("population", {"cities": (3,)}),
    ("techs", {"techs": 1}),
    ("civics", {"civics": 1}),
    ("wonders", {"cities": (1,), "wonders": 1}),
])
def test_every_term_can_move_the_score(monkeypatch, term, give_kwargs):
    """Each kind of holding changes the score by its own weight and the others
    by nothing -- the property that makes a new term's weight tunable in
    config alone. Breaks if a term is not wired to `score_breakdown`."""
    monkeypatch.setattr(victory, "SCORE_WEIGHTS", {**victory.SCORE_WEIGHTS, term: 1000})
    env = make_flat_env()
    player = give(env, 0, **give_kwargs)
    breakdown = victory.score_breakdown(player)
    assert breakdown[term] >= 1000
    assert sum(points for name, points in breakdown.items() if name != term) < 1000


def test_one_function_is_the_score_and_the_verdict_reads_it():
    """The trainer, the viewer and the verdict name one `player_score` and one
    `determine_winner`: re-exports of `civulator/game/victory.py`, never
    copies, and the HUD file computes no score of its own. Breaks if a second
    copy of the formula or the verdict appears (the #55 failure)."""
    import pathlib

    assert trainer.player_score is victory.player_score
    assert trainer.determine_winner is victory.determine_winner
    assert trainer.determine_outcome is victory.determine_outcome
    repo = pathlib.Path(__file__).resolve().parents[1]
    watch = (repo / "scripts" / "watch.py").read_text(encoding="utf-8")
    assert "player_score(" in watch and "determine_outcome(" in watch
    for path in sorted((repo / "civulator").rglob("*.py")) + sorted((repo / "scripts").glob("*.py")):
        if path.name == "victory.py":
            continue
        source = path.read_text(encoding="utf-8")
        assert "def player_score" not in source and "def determine_outcome" not in source, path
        assert "city_score_weight" not in source, f"{path} reads a score weight itself"


@pytest.mark.parametrize("seed", range(8))
def test_the_verdict_at_the_cap_picks_whoever_player_score_ranks_highest(seed):
    """At the cap the unique highest `player_score` wins and a tie is a draw,
    for holdings drawn at random over every term -- so the number a scoreboard
    shows can never disagree with the winner beside it. Breaks if the verdict
    ranks by anything but `player_score` (a copy of the formula, or the
    old cities-and-units pair)."""
    rng = random.Random(seed)
    env = make_flat_env()
    for seat in (0, 1):
        give(env, seat, cities=tuple(rng.randint(1, 5) for _ in range(rng.randint(1, 2))),
             units=rng.randint(0, 5), techs=rng.randint(0, 22), civics=rng.randint(0, 19),
             wonders=rng.randint(0, 2))
    env.turn_counter = env.max_turns
    env.done = True
    scores = [victory.player_score(p) for p in env.players]
    winner, how = victory.determine_outcome(env)
    if scores[0] == scores[1]:
        assert (winner, how) == (None, "draw")
    else:
        assert (winner, how) == (scores.index(max(scores)), "score")
    assert victory.determine_winner(env) == winner


def test_a_leader_in_techs_and_wonders_beats_a_leader_in_cities_and_units():
    """The terms the score gained decide a game the old pair would have given
    to the other player: seat 1 has fewer cities and units but a full tree and
    two wonders. Breaks if only cities and units rank the players."""
    env = make_flat_env()
    give(env, 0, cities=(1,), units=3)
    give(env, 1, cities=(1,), units=1, techs=len(TECH_ORDER), civics=len(CIVIC_ORDER), wonders=2)
    old_formula = [len(p.cities) * CFG["game"]["city_score_weight"] + len(p.units)
                   for p in env.players]
    assert old_formula[0] > old_formula[1], "fixture: the old pair favours seat 0"
    env.turn_counter = env.max_turns
    env.done = True
    assert victory.determine_outcome(env) == (1, "score")


_SCORE_KEYS = ("unit_weight", "population_weight", "tech_weight", "civic_weight", "wonder_weight")


def _game(**overrides):
    """A valid `[game]` table for the loader, with `overrides` applied (a value
    of None drops the key)."""
    game = {"city_score_weight": 10, "score": {k: 1 for k in _SCORE_KEYS}}
    for key, value in overrides.items():
        if value is None:
            game.pop(key)
        else:
            game[key] = value
    return game


@pytest.mark.parametrize("bad", [
    _game(city_score_weight=None),                                    # no city weight
    _game(score=None),                                                # no [game.score]
    _game(score={"unit_weight": 1}),                                  # keys missing
    _game(score={**{k: 1 for k in _SCORE_KEYS}, "relic_weight": 1}),  # an unknown key
    _game(city_score_weight=-1),                                      # negative
    _game(score={k: 1.5 for k in _SCORE_KEYS}),                       # not whole
    _game(city_score_weight=True),                                    # a bool is not a weight
])
def test_the_score_config_raises_on_anything_malformed(bad):
    """`[game] city_score_weight` and `[game.score]` must be present, exactly
    the five known keys, each a whole number >= 0 (a gameplay number has one
    home and no default in code). Breaks if a malformed or partial score
    table loads."""
    with pytest.raises(ValueError):
        victory.parse_score_weights(bad)
    assert victory.parse_score_weights(_game()) == {
        "cities": 10, "units": 1, "population": 1, "techs": 1, "civics": 1, "wonders": 1}
    assert victory.parse_score_weights(CFG["game"]) == victory.SCORE_WEIGHTS
