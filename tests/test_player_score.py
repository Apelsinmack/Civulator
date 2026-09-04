"""`player_score` is THE score formula (issue #55).

`scripts/watch.py`'s HUD used to re-derive `cities * 10 + units` while
calling `determine_winner` for the verdict two lines later, so a scoreboard
could in principle disagree with the banner beside it. Both now go through
one function, and the weight comes from config.toml rather than a literal.
"""

from civulator.config import CFG
from civulator.game.unit import WarriorUnit
from civulator.training.trainer import (
    CITY_SCORE_WEIGHT,
    determine_winner,
    player_score,
)

from test_combat_range import make_flat_env, place


def test_weight_comes_from_config():
    assert CITY_SCORE_WEIGHT == CFG["game"]["city_score_weight"]


def test_score_counts_cities_by_weight_plus_units():
    env = make_flat_env()
    player = env.players[0]
    assert player_score(player) == 0

    place(env, WarriorUnit, 0, (4, 4))
    place(env, WarriorUnit, 0, (4, 6))
    assert player_score(player) == 2

    assert env.found_city(player, (2, 2), "A") is not None
    assert player_score(player) == CITY_SCORE_WEIGHT + 2


def test_determine_winner_tiebreak_agrees_with_player_score():
    """The cap tiebreak must pick whoever player_score ranks highest —
    the property the duplicated HUD copy could have violated."""
    env = make_flat_env()
    p0, p1 = env.players
    assert env.found_city(p0, (2, 2), "A") is not None
    assert env.found_city(p1, (6, 12), "B") is not None
    place(env, WarriorUnit, 0, (4, 4))          # p0: 1 city + 1 unit
    place(env, WarriorUnit, 1, (6, 13))
    place(env, WarriorUnit, 1, (6, 14))          # p1: 1 city + 2 units

    env.turn_counter = env.max_turns
    env.done = True

    assert player_score(p1) > player_score(p0)
    assert determine_winner(env) == p1.player_index
