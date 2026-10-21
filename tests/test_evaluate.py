"""Smoke test for scripts/evaluate.py -- the #40 head-to-head evaluation
harness (protocol v1).

This is deliberately NOT a claim about play quality or protocol-correctness
of the real #40 run (that's `python scripts/evaluate.py --a ... --b ...`,
run once manually against the real 200-game budget). Its only job: the
harness runs end-to-end on a tiny, fast configuration and is reproducible --
same call twice must yield identical per-game results, which is exactly
what a comparison harness's credibility depends on.

Same weights file on both sides (duel_25ch_1000ep.pth, the #39 baseline --
loading it twice, once per side, is entirely realistic even though a real
run always compares two DIFFERENT files) so this test needs no dedicated
tiny fixture weights of its own; --games=2 and a tiny --max-turns keep it
well under the ~60s budget on both CPU and GPU machines.

No `__init__.py` under tests/ (tests/conftest.py's own docstring) -- same
bare cross-directory import pattern as the rest of this suite, extended one
level to reach scripts/ (which is not a package either).
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "scripts"))

import evaluate
from civulator import __version__ as GAME_VERSION
from civulator.game.victory import VICTORIES

WEIGHTS = os.path.join(_PROJECT_ROOT, "weights", "trained", "duel_25ch_1000ep.pth")

GAMES = 2
SEED_BASE = 123456  # arbitrary, well clear of any real run's seed_base
MAX_TURNS = 15      # tiny -- this test is about the harness, not gameplay depth


def _run():
    return evaluate.run_evaluation(
        a_weights=WEIGHTS, a_encoder="enhanced",
        b_weights=WEIGHTS, b_encoder="enhanced",
        games=GAMES, seed_base=SEED_BASE, epsilon=0.05,
        max_turns=MAX_TURNS, verbose=False,
    )


def test_evaluate_harness_completes_and_is_deterministic():
    summary_1 = _run()
    summary_2 = _run()

    # Completes, and counts add up to the requested game count.
    totals = summary_1["totals"]
    assert totals["a_wins"] + totals["b_wins"] + totals["draws"] == GAMES
    assert len(summary_1["games_detail"]) == GAMES

    # Side balance (module docstring): game 0 seats A on seat 0, game 1 on
    # seat 1 -- and since both sides load the SAME weights file, game 1
    # replays game 0's exact world (world-pair schedule) with seats swapped.
    assert summary_1["games_detail"][0]["a_seat"] == 0
    assert summary_1["games_detail"][1]["a_seat"] == 1
    assert summary_1["games_detail"][0]["seed"] == summary_1["games_detail"][1]["seed"]

    # Determinism: identical call twice -> byte-identical per-game results
    # (seeds, outcomes, turn counts) and identical aggregates.
    assert summary_1["games_detail"] == summary_2["games_detail"]
    assert summary_1["totals"] == summary_2["totals"]
    assert summary_1["by_a_seat"] == summary_2["by_a_seat"]
    assert summary_1["game_length"] == summary_2["game_length"]
    assert summary_1["build_distribution"] == summary_2["build_distribution"]
    assert summary_1["combat_stats"] == summary_2["combat_stats"]
    assert set(summary_1["combat_stats"]) == {"a", "b"}
    # Schema: both sides present. Counts are EMPTY at this tiny MAX_TURNS by
    # design — capitals are founded with a Warrior (40 production) already
    # queued, which never completes in 15 turns, so no new build decision
    # arises; real 250-turn evals accumulate plenty.
    assert set(summary_1["build_distribution"]) == {"a", "b"}


def test_truncation_is_recorded_and_absent_from_a_healthy_run():
    """Issue #51: a game cut off by the step-limit guard must be visible in
    the machine-readable record.

    `determine_winner` has no verdict for a game stopped mid-play — both
    players alive, below the turn cap — so it returns None and the game
    lands in totals["draws"], indistinguishable from a real draw. That is
    how 50 of the 200 games in the #48 rung-6 evaluation were first read as
    combat results. The per-game entry now carries `truncated`, and the
    summary a `truncated_games` count.

    Truncation is forced by lowering `evaluate.STEP_LIMIT`, not by building
    a livelock: after #51 the masks no longer offer an action that changes
    nothing, so a real one cannot be constructed here — what is under test
    is the guard's REPORTING.
    """
    healthy = _run()
    assert healthy["truncated_games"] == 0
    assert all(g["truncated"] is False for g in healthy["games_detail"])

    original_limit = evaluate.STEP_LIMIT
    evaluate.STEP_LIMIT = 3  # cut every game off almost immediately
    try:
        cut_off = _run()
    finally:
        evaluate.STEP_LIMIT = original_limit

    assert cut_off["truncated_games"] == GAMES
    assert all(g["truncated"] is True for g in cut_off["games_detail"])
    # The point of the field: these are counted as draws and would otherwise
    # be unrecognizable as non-results.
    assert cut_off["totals"]["draws"] == GAMES


def test_games_detail_keeps_the_fields_older_readers_use():
    """scripts/watch.py reads games_detail entries by name (game_index, seed,
    a_seat, b_seat, winner_seat, outcome, turns). #51 ADDS `truncated` and
    #116 P9 `victory`; neither may rename or drop anything, and older
    summaries that lack the keys must stay readable (consumers treat a
    missing key as False / unknown). The set of keys is designed to grow, so
    only the ones older readers need are asserted."""
    summary = _run()
    for game in summary["games_detail"]:
        assert {"game_index", "seed", "a_seat", "b_seat", "winner_seat",
                "outcome", "turns"} <= set(game)


def test_every_game_records_how_it_ended():
    """Each `games_detail` entry carries `victory`, the engine's verdict
    (`civulator.game.victory.determine_outcome`): one of the known kinds for a
    game that ended on its own, and consistent with the winner -- a game has
    no winner exactly when it is a draw. Breaks if `victory` is missing, is
    re-derived in the harness, or disagrees with `winner_seat`."""
    summary = _run()
    assert summary["games_detail"], "fixture: games were played"
    for game in summary["games_detail"]:
        assert game["truncated"] is False
        assert game["victory"] in VICTORIES, game
        assert (game["winner_seat"] is None) == (game["victory"] == "draw"), game


def test_a_truncated_game_has_no_victory():
    """A game cut off by the step guard has `victory: null` -- never "draw",
    though it is also counted in `totals["draws"]` (#51, #116 P9). Breaks if
    a cut-off game is given a verdict."""
    original_limit = evaluate.STEP_LIMIT
    evaluate.STEP_LIMIT = 3
    try:
        cut_off = _run()
    finally:
        evaluate.STEP_LIMIT = original_limit
    assert cut_off["truncated_games"] == GAMES
    for game in cut_off["games_detail"]:
        assert game["truncated"] is True
        assert game["victory"] is None, game
        assert game["winner_seat"] is None


def test_the_summary_records_the_rules_and_each_sides_weights_version():
    """The summary names the engine's `game_version` and, per side, the
    `game_version` of the weights' own manifest (None when a file carries no
    manifest), so archived weights playing newer rules are visible in the
    record (#116 P9: 0.7 weights play 0.8 rules). Breaks if either is
    missing, or the weights' version is taken from the engine."""
    summary = _run()
    assert summary["game_version"] == GAME_VERSION
    assert set(summary["weights_game_version"]) == {"a", "b"}
    for side in ("a", "b"):
        manifest = summary[f"manifest_{side}"]
        recorded = manifest.get("game_version") if manifest else None
        assert summary["weights_game_version"][side] == recorded


def test_a_weights_manifest_version_is_read_from_the_manifest_not_the_engine():
    """`_weights_game_version` reports what the manifest says (an older epoch's
    number stays an older number) and None for a file without one. Breaks if
    it falls back to the engine's version."""
    assert evaluate._weights_game_version({"game_version": "0.7.3"}) == "0.7.3"
    assert evaluate._weights_game_version({"git_commit": "abc"}) is None
    assert evaluate._weights_game_version(None) is None
