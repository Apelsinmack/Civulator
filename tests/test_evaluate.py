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
