"""The one verdict and the one score formula (issue #55; #116 P9, progression
design §11 and "v2 fixes", Verdict and domination).

`determine_outcome(env) -> (winner, victory)` is the only place the engine
decides who won and how. Everything that ends a game, reports a winner or
shows a score reads it: `GameEnvironment._update_done` (through `game_over`),
the trainer's terminal rewards, `scripts/evaluate.py`'s per-game record and
the viewer HUD. `civulator/training/trainer.py` re-exports the names it has
always had (`determine_winner`, `player_score`, `CITY_SCORE_WEIGHT`); the
engine lives here because `civulator/game/` may import nothing of training.

The ways a game ends, in the order the verdict tests them:

1. **elimination** -- exactly one living player;
2. **domination** -- a living player holds every Palace in the game (the
   capital marker, `[city] capital_building`) and at least one of them was
   granted to another player (`Player.palace_granted`). The second clause is
   what stops a vacuous win: a board with no Palace at all (a painted
   scenario), and a lone player holding the only Palace ever granted (the
   first player to found a city, before the others have), never dominate;
3. **score at the turn cap** -- once the game is done at or past
   `env.max_turns`, the unique highest `player_score` wins (a dead player
   scores -1) and a tie is `(None, "draw")`.

Anything else is `(None, None)`: the game is still running, or it was cut off
by a step guard (#51) -- a truncated game's `victory` is `None`, never
`"draw"`.

The score is the sum of one term per kind of thing a player holds, a count
times its weight (`[game] city_score_weight` and `[game.score]`, config.toml).
`score_breakdown` is that sum term by term; `player_score` is its total, so a
displayed score cannot disagree with the verdict beside it.
"""

from ..config import CFG
from ..unit_model import CAPITAL_BUILDING
from .districts import is_wonder

VICTORY_ELIMINATION = "elimination"
VICTORY_DOMINATION = "domination"
VICTORY_SCORE = "score"
VICTORY_DRAW = "draw"
VICTORIES = (VICTORY_ELIMINATION, VICTORY_DOMINATION, VICTORY_SCORE, VICTORY_DRAW)

# `[game.score]`: one weight per term beside `[game] city_score_weight`.
_SCORE_KEYS = ("unit_weight", "population_weight", "tech_weight",
               "civic_weight", "wonder_weight")


def _weight(value, where):
    if type(value) is not int or value < 0:
        raise ValueError(f"{where} must be a whole number >= 0, got {value!r}")
    return value


def parse_score_weights(game_cfg):
    """`[game] city_score_weight` and `[game.score]` -> {term: weight}, the terms
    of `score_breakdown`. Raises ValueError on a missing, unknown or malformed
    key: a gameplay number has one home, the config, and no default here."""
    if "city_score_weight" not in game_cfg:
        raise ValueError("[game]: city_score_weight is required")
    table = game_cfg.get("score")
    if not isinstance(table, dict):
        raise ValueError("[game.score] must be a table")
    unknown = set(table) - set(_SCORE_KEYS)
    missing = set(_SCORE_KEYS) - set(table)
    if unknown or missing:
        raise ValueError(f"[game.score]: unknown key(s) {sorted(unknown)}, "
                         f"missing key(s) {sorted(missing)}")
    return {
        "cities": _weight(game_cfg["city_score_weight"], "[game] city_score_weight"),
        "units": _weight(table["unit_weight"], "[game.score] unit_weight"),
        "population": _weight(table["population_weight"], "[game.score] population_weight"),
        "techs": _weight(table["tech_weight"], "[game.score] tech_weight"),
        "civics": _weight(table["civic_weight"], "[game.score] civic_weight"),
        "wonders": _weight(table["wonder_weight"], "[game.score] wonder_weight"),
    }


SCORE_WEIGHTS = parse_score_weights(CFG["game"])
CITY_SCORE_WEIGHT = SCORE_WEIGHTS["cities"]


def score_counts(player):
    """How many of each scored thing `player` holds, by term: its cities, its
    units, the population of its cities, the techs and civics it knows, and
    its complete wonders (a district-registry entry of `kind = "wonder"`, in
    any of its cities; a placed, unfinished one counts nothing)."""
    return {
        "cities": len(player.cities),
        "units": len(player.units),
        "population": sum(city.population for city in player.cities),
        "techs": len(player.techs),
        "civics": len(player.civics),
        "wonders": sum(1 for city in player.cities for district in city.districts
                       if district.complete and is_wonder(district.type)),
    }


def score_breakdown(player):
    """The points `player` earns from each term: its count times its weight
    (`SCORE_WEIGHTS`, read at call time)."""
    return {term: count * SCORE_WEIGHTS[term]
            for term, count in score_counts(player).items()}


def player_score(player):
    """A living player's turn-cap score: the total of `score_breakdown`.

    THE score formula (issue #55) -- `determine_outcome`'s cap tiebreak and
    every display of a score (scripts/watch.py's HUD) call this, so a
    scoreboard can never disagree with the verdict beside it. A dead player
    is ranked -1 by the verdict; that is a ranking convention, not a score.
    """
    return sum(score_breakdown(player).values())


def living_players(env):
    """The indices of the players still alive, in seat order."""
    return [i for i, player in enumerate(env.players) if not player.is_dead]


def palace_holders(env):
    """The set of player indices holding at least one Palace: a city whose
    buildings include `[city] capital_building`. Gameplay never reads
    "capital", it reads the Palace (CLAUDE.md, Palace)."""
    return {player.player_index for player in env.players
            for city in player.cities if CAPITAL_BUILDING in city.buildings}


def domination_winner(env):
    """The player index that holds every Palace in the game, or None.

    Needs exactly one holder, alive, and a Palace that was granted to some
    OTHER player: `Player.palace_granted` outlives the Palace's city, so a
    capital that was captured still counts. Without that clause a board with
    no Palace, and the first player to found a capital while the others have
    none yet, would "hold every Palace" vacuously."""
    holders = palace_holders(env)
    if len(holders) != 1:
        return None
    (holder,) = holders
    if env.players[holder].is_dead:
        return None
    if not any(player.palace_granted for player in env.players
               if player.player_index != holder):
        return None
    return holder


def decisive_outcome(env):
    """`(winner, victory)` for the two rules that end a game the moment they
    hold, whatever the turn: elimination, then domination. `(None, None)`
    when neither does."""
    alive = living_players(env)
    if len(alive) == 1:
        return alive[0], VICTORY_ELIMINATION
    dominator = domination_winner(env)
    if dominator is not None:
        return dominator, VICTORY_DOMINATION
    return None, None


def game_over(env):
    """Whether the game has ended by its own rules: elimination or domination,
    no one left alive, or the turn cap passed. The one test behind
    `GameEnvironment._update_done`, so `done` can never disagree with the
    verdict."""
    _, victory = decisive_outcome(env)
    return (victory is not None or not living_players(env)
            or env.turn_counter > env.max_turns)


def determine_outcome(env):
    """The one verdict: `(winner, victory)`.

    `winner` is a player index or None; `victory` is `"elimination"`,
    `"domination"`, `"score"`, `"draw"` (a tied top score at the cap) or None
    (nobody has won: the game is running, or was cut off before it ended --
    a truncated game is `(None, None)`, never `"draw"`, #51)."""
    winner, victory = decisive_outcome(env)
    if victory is not None:
        return winner, victory
    if env.done and env.turn_counter >= env.max_turns:
        scores = [-1 if player.is_dead else player_score(player) for player in env.players]
        top = max(scores)
        if scores.count(top) == 1:
            return scores.index(top), VICTORY_SCORE
        return None, VICTORY_DRAW
    return None, None


def determine_winner(env):
    """The winning player index, or None: `determine_outcome(env)[0]`."""
    return determine_outcome(env)[0]
