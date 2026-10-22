"""Winning (issue #116 P9, docs/progression_design.md §11, "v2 fixes" -- Verdict
and domination -- and the §14 rows "Domination: ..." and "the verdict and the
score diverge (#55)").

`civulator/game/victory.py` holds the one verdict, `determine_outcome(env) ->
(winner, victory)`, and `GameEnvironment._update_done` asks the same module
(`game_over`) whether the game has ended, so `done` and the verdict cannot
disagree. The ways a game ends are elimination, domination (a living player
holds every Palace in the game and one of them was granted to another
player) and the turn-cap score; a game cut off by a step guard has no verdict
at all (#51).

Every test names the property it protects and the change that must break it.
Boards are the shared flat Plains fixtures; cities come from the engine
(`found_city` grants the Palace to a player's first city, exactly as in
play), and the loyalty test uses test_loyalty's flat row board. No test pins
which buildings, wonders or units exist.
"""

import pytest

from civulator.game import victory
from civulator.game.victory import (
    VICTORIES,
    decisive_outcome,
    determine_outcome,
    determine_winner,
    domination_winner,
    game_over,
    palace_holders,
)
from civulator.unit_model import CAPITAL_BUILDING

from test_city_combat import enemy_city, home_city, make_env, order
from test_combat_range import make_flat_env, place
from test_loyalty import city as loyal_city
from test_loyalty import flat
from civulator.game.unit import SettlerUnit, WarriorUnit


@pytest.fixture(autouse=True)
def domination_on(monkeypatch):
    """The domination tests describe the rule while it is switched on;
    `[game] domination_victory` is off by default (#126), and the tests of the
    switch itself turn it off again explicitly."""
    monkeypatch.setattr(victory, "DOMINATION_ENABLED", True)


def strip_palaces(env):
    """Make a 'painted' board: every city loses the Palace create_city granted
    (the flags saying a Palace was granted stay as they are)."""
    for player in env.players:
        for held in player.cities:
            while CAPITAL_BUILDING in held.buildings:
                held.buildings.remove(CAPITAL_BUILDING)


# --- (a) domination wins outright, while other cities stand --------------------------------


def test_capturing_the_last_foreign_palace_wins_at_once_while_the_loser_still_has_cities():
    """Seat 0 takes seat 1's capital (its Palace) while seat 1 still holds
    another city: the step that captures it ends the game with seat 0 the
    winner by domination -- seat 1 is not eliminated, it is alive with a city
    left. Breaks if domination is not tested where cities are captured, if it
    waits for elimination, or if a loser with cities left cannot lose."""
    env = make_env()
    home_city(env, (0, 0))
    capital = enemy_city(env, (4, 8))
    second = env.found_city(env.players[1], (4, 14), "Second")
    assert second is not None and CAPITAL_BUILDING not in second.buildings
    assert not env.done and determine_outcome(env) == (None, None)
    capital.health = 0
    raider = place(env, WarriorUnit, 0, (4, 7))

    _, _, done = order(env, raider, (4, 8))

    assert capital.player is env.players[0]
    assert second.player is env.players[1] and not env.players[1].is_dead
    assert done and env.done
    assert determine_outcome(env) == (0, "domination")
    assert determine_winner(env) == 0


def test_done_never_disagrees_with_the_verdict():
    """After `_update_done`, a decisive verdict (elimination or domination)
    has set `done`, and `done` set short of the cap has a decisive verdict: one
    test (`game_over`) behind both. Breaks if the engine keeps a second
    end-of-game test."""
    env = make_flat_env()
    a = env.found_city(env.players[0], (1, 1), "A")
    b = env.found_city(env.players[1], (5, 9), "B")
    env._update_done()
    assert not env.done and decisive_outcome(env) == (None, None) and not game_over(env)

    b.set_owner(env.players[0])                       # seat 0 now holds both Palaces
    assert decisive_outcome(env) == (0, "domination") and game_over(env)
    env._update_done()
    assert env.done
    assert a.player is env.players[0]


def test_domination_needs_every_palace_in_the_game():
    """A player holding one of two Palaces does not dominate; the second
    falling to it does. Breaks if one captured Palace (or the capital marker
    held by anyone) is enough."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    b = env.found_city(env.players[1], (5, 9), "B")
    second = env.found_city(env.players[1], (1, 9), "B2")
    assert palace_holders(env) == {0, 1}
    assert domination_winner(env) is None
    b.set_owner(env.players[0])
    assert palace_holders(env) == {0}
    assert domination_winner(env) == 0
    assert second.player is env.players[1], "seat 1 still has a city"


# --- (b) the vacuous cases never win --------------------------------------------------------


def test_a_board_with_no_palace_never_dominates():
    """A painted board (cities, no Palace anywhere) holds 'every Palace'
    vacuously for nobody: no player wins, however the cities are split.
    Breaks if an empty set of Palaces counts as held."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    env.found_city(env.players[0], (1, 9), "A2")
    env.found_city(env.players[1], (5, 9), "B")
    strip_palaces(env)
    assert palace_holders(env) == set()
    assert domination_winner(env) is None
    env._update_done()
    assert not env.done and determine_outcome(env) == (None, None)


def test_the_first_player_to_found_a_capital_does_not_dominate():
    """At the start of a game the first capital is the only Palace anywhere,
    and its owner holds it: no Palace has been granted to anyone else, so
    there is nothing to dominate. Breaks if 'every Palace in the game' is read
    as only the Palaces that exist now."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    assert palace_holders(env) == {0} and not env.players[1].palace_granted
    assert domination_winner(env) is None
    env._update_done()
    assert not env.done and determine_outcome(env) == (None, None)
    env.found_city(env.players[1], (5, 9), "B")        # the second capital arrives
    assert palace_holders(env) == {0, 1} and domination_winner(env) is None


def test_a_palace_granted_to_nobody_else_is_no_domination_even_if_two_cities_hold_one():
    """The 'granted to another player' clause reads `Player.palace_granted`,
    not the board: a hand-placed second Palace on a player's own city, with no
    other player ever granted one, is no win. Breaks if the clause is
    dropped."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    second = env.found_city(env.players[0], (1, 9), "A2")
    second.buildings.append(CAPITAL_BUILDING)
    assert palace_holders(env) == {0} and not env.players[1].palace_granted
    assert domination_winner(env) is None


def test_a_dead_holder_never_dominates():
    """The winner must be a living player. Breaks if `is_dead` is ignored."""
    env = make_flat_env()
    a = env.found_city(env.players[0], (1, 1), "A")
    env.found_city(env.players[1], (5, 9), "B").set_owner(env.players[0])
    assert domination_winner(env) == 0
    env.players[0].is_dead = True
    assert domination_winner(env) is None
    assert a.player is env.players[0]


# --- (e) a loyalty flip that takes the last Palace ends the game in its round --------------


def test_a_flip_that_takes_the_last_palace_ends_the_game_in_the_same_round():
    """Seat 1's capital (its Palace) is at 1 loyalty beside seat 0's much
    larger capital, so the round-end loyalty phase flips it to seat 0; seat 1
    keeps a far city, so it is alive. The verdict runs after the phase, before
    the next round starts: `done` is set in that very `next_turn` call, by
    domination, not elimination. Breaks if the end-of-game test is not run
    after `_loyalty_phase` (the game would run one more round) or ignores a
    flipped Palace."""
    env = flat()
    home = loyal_city(env, 0, 15, population=6, palace=True)
    weak = loyal_city(env, 1, 10, population=1, palace=True)
    far = loyal_city(env, 1, 30, population=1)
    weak.loyalty = 1
    assert palace_holders(env) == {0, 1}
    env.next_turn()                                   # seat 0 -> seat 1: mid-round
    assert not env.done
    round_before = env.turn_counter

    env.next_turn()                                   # seat 1 -> seat 0: the round ends

    assert weak.player is env.players[0] and home.player is env.players[0]
    assert far.player is env.players[1] and not env.players[1].is_dead
    assert env.done
    assert env.turn_counter == round_before + 1
    assert determine_outcome(env) == (0, "domination")


def test_a_flip_of_an_ordinary_city_does_not_end_the_game():
    """The same flip of a city that holds no Palace leaves both Palaces where
    they were: no domination, the game goes on. Breaks if any flip (or any
    capture of any city) ends the game."""
    env = flat()
    loyal_city(env, 0, 15, population=6, palace=True)
    loyal_city(env, 1, 30, population=1, palace=True)
    weak = loyal_city(env, 1, 10, population=1)
    weak.loyalty = 1
    env.next_turn()
    env.next_turn()
    assert weak.player is env.players[0]
    assert not env.done and determine_outcome(env) == (None, None)


# --- (f) `victory` is null when truncated and "draw" only for a tied score at the cap ------


def _at_the_cap(env, done=True, turn=None):
    env.turn_counter = env.max_turns if turn is None else turn
    env.done = done
    return env


def _tied_board():
    """Two players with one city each and nothing else: equal scores."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    env.found_city(env.players[1], (5, 9), "B")
    assert victory.player_score(env.players[0]) == victory.player_score(env.players[1])
    return env


def _ahead_board():
    env = _tied_board()
    place(env, WarriorUnit, 1, (6, 9))
    assert victory.player_score(env.players[1]) > victory.player_score(env.players[0])
    return env


@pytest.mark.parametrize("make, done, turn_offset, expected", [
    (_tied_board, True, 0, (None, "draw")),        # a tied top score at the cap is the only draw
    (_ahead_board, True, 0, (1, "score")),         # a unique top score at the cap wins on score
    (_tied_board, False, 0, (None, None)),         # not done at the cap: still running or cut off
    (_ahead_board, False, 0, (None, None)),
    (_tied_board, True, -5, (None, None)),         # done short of the cap with nobody decisive: no verdict
    (_ahead_board, True, -5, (None, None)),
    (_tied_board, False, -5, (None, None)),        # mid-game
])
def test_the_verdict_says_draw_only_for_a_tied_score_at_the_cap(make, done, turn_offset, expected):
    """`"draw"` is a tied top score once the game is done at or past the turn
    cap and nothing else; a game that is not done (a truncated one) or is done
    short of the cap without a decisive rule has `(None, None)` -- a truncated
    game's `victory` is null, never "draw" (#51). Breaks if a cut-off game is
    scored as a draw or a score verdict is given before the cap."""
    env = make()
    _at_the_cap(env, done=done, turn=env.max_turns + turn_offset)
    assert determine_outcome(env) == expected
    assert determine_winner(env) == expected[0]
    assert expected[1] is None or expected[1] in VICTORIES


def test_elimination_is_the_verdict_when_one_player_is_left():
    """One living player: `(index, "elimination")`, before the turn cap and
    whatever the Palaces say. Breaks if elimination is dropped from the one
    verdict."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    env.found_city(env.players[1], (5, 9), "B")
    env.players[1].is_dead = True
    assert determine_outcome(env) == (0, "elimination")
    env._update_done()
    assert env.done


def test_the_cap_ends_the_game_the_round_after_the_last_allowed_one():
    """`done` is set once the turn counter passes `max_turns`, and the score
    verdict is given only then. Breaks if the cap is off by one against the
    verdict's own `>= max_turns` condition (a done game with no verdict)."""
    env = _ahead_board()
    env.turn_counter = env.max_turns
    env._update_done()
    assert not env.done and determine_outcome(env) == (None, None)
    env.turn_counter = env.max_turns + 1
    env._update_done()
    assert env.done and determine_outcome(env) == (1, "score")


# --- the domination switch and Settler survival (#126) -----------------------------------


def test_with_domination_off_taking_the_last_foreign_palace_does_not_end_the_game(monkeypatch):
    """With `[game] domination_victory` false, seat 0 capturing seat 1's
    capital while seat 1 keeps another city ends nothing: no verdict, the
    game goes on. Breaks if the switch is not read by the verdict, or if
    domination is tested somewhere else."""
    monkeypatch.setattr(victory, "DOMINATION_ENABLED", False)
    env = make_env()
    home_city(env, (0, 0))
    capital = enemy_city(env, (4, 8))
    second = env.found_city(env.players[1], (4, 14), "Second")
    capital.health = 0
    raider = place(env, WarriorUnit, 0, (4, 7))

    _, _, done = order(env, raider, (4, 8))

    assert capital.player is env.players[0] and second.player is env.players[1]
    assert domination_winner(env) is None
    assert not done and not env.done and determine_outcome(env) == (None, None)


def test_the_domination_switch_is_a_required_boolean():
    """`[game] domination_victory` must be present and a real boolean. Breaks
    if a missing or mistyped switch silently falls back to a default."""
    assert victory.parse_domination_enabled({"domination_victory": False}) is False
    assert victory.parse_domination_enabled({"domination_victory": True}) is True
    for bad in ({}, {"domination_victory": 0}, {"domination_victory": "false"}):
        with pytest.raises(ValueError):
            victory.parse_domination_enabled(bad)


def test_a_player_without_cities_lives_while_it_has_a_settler():
    """A player with no city but a Settler survives the end of its turn; once
    the Settler is gone it dies there, and the other player wins by
    elimination. Breaks if death is decided by cities alone, or if a Settler
    no longer keeps its player in the game."""
    env = make_flat_env()
    env.found_city(env.players[0], (1, 1), "A")
    loser = env.players[1]
    assert not loser.cities
    for unit in list(loser.units):
        env.delete_unit(unit)
    settler = place(env, SettlerUnit, 1, (5, 9))

    loser.end_turn()
    assert not loser.is_dead and determine_outcome(env) == (None, None)

    env.delete_unit(settler)
    loser.end_turn()
    assert loser.is_dead and determine_outcome(env) == (0, "elimination")
