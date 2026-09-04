# Pre-0.6 scripts — archived 2026-09-04 (issue #53)

These four scripts were moved here out of `scripts/` because they are
**silently broken against the current action space**, not merely superseded.

Each ends the turn with `if action[0] == env.n * env.m:` (`tournament.py:132`,
`tournament_backbone.py:94`, `test_shared_backbone.py:131`, `replay.py:87`).
Since v0.6 the action space is slot-aware and the end-turn index is
`n * m * NUM_UNIT_SLOTS` (`civulator/agents/dqn_agent.py:146-147`,
`NUM_UNIT_SLOTS = 4` in `civulator/game/unit.py`). Consequently:

1. `n*m` is a legal *selection* index, so an ordinary unit selection was
   misread as "end turn";
2. the real end-turn index decoded to an off-map row, and the resulting
   exception was swallowed by a bare `except Exception: pass`.

The visible symptom was not a crash but a no-op loop that spun to the step
cap and reported **every game as a draw** — a decoding bug that reads like a
modelling result. They are also pinned to a 4×8 map and an encoder depth no
current weights file matches, and none of them seeds its worlds, so their
runs were never reproducible under the project's research-method rule.

**Do not repair these in place.** The canonical evaluation harness is
`scripts/evaluate.py` (protocol v1), which CLAUDE.md names as the only way
to measure agent-vs-agent strength in the v0.6 epoch; their training halves
are redundant with `scripts/run_baseline.py`.

`replay.py`'s ASCII board view is the one capability with no successor. If it
is wanted again it should return as a `--render ascii` flag on
`evaluate._play_game`, not as a fifth copy of the game loop (issue #54 tracks
the loop duplication that made this class of bug possible).
