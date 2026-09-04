"""Tests for the episode-indexed seed schedule (issue #39): `train_agents(
..., seed_base=N)` must make episode k's world reproducible across
independent runs -- the experiment-design requirement that every follower
experiment (#40 encoder, ...) trains on literally the same sequence of
worlds as the baseline -- including when the running-cursor scheme has to
skip a seed that fails start placement (`GameEnvironment.reset(seed=...)`
raises `StartPlacementError` on ~2% of seeds BY DESIGN, doc D26; see
`civulator/training/trainer.py`'s `_seeded_reset` docstring for the exact
scheme these tests exercise).

Small board (map_type="basic", 8x16, matching test_reset_resample.py's
BASIC_SIZE) + tiny conv_channels + low max_turns throughout: these tests
are about the SCHEDULE, not combat or state encoding, so everything else
is kept minimal for speed (same convention as test_determinism.py and
test_reset_resample.py). `world_fingerprint` is reused verbatim from
test_determinism.py rather than reinvented (bare cross-file import, same
pattern test_determinism.py itself uses for test_combat_range's helpers —
no `__init__.py` under tests/, so pytest puts this directory on sys.path).

Failure injection patches `GameEnvironment.reset` directly (raising the
same `StartPlacementError` a real placement failure would) rather than
`mapgen.starts.place_starts` the way test_reset_resample.py does: that
file is about reset()'s OWN retry policy; this one is about how
`train_agents`'s schedule reacts to whatever reset() raises, keyed on the
exact seed VALUE the schedule chose -- reset() is the boundary the
schedule actually observes, and the only place a specific seed value is
available to key the forced failure on (mapgen never sees `seed=N`
directly; it only sees a master seed drawn from the RNG `reset(seed=N)`
seeded).
"""

import logging

import pytest

from civulator.agents import DQNAgent, ReplayMemory, BasicStateEncoder
from civulator.game.environment import GameEnvironment
from civulator.mapgen.starts import StartPlacementError
from civulator.training import train_agents

from test_determinism import world_fingerprint

BASIC_SIZE = (8, 16)
LOGGER_NAME = "civulator.training.trainer"


def _make_agents(num_players=2):
    env = GameEnvironment(*BASIC_SIZE, num_players=num_players, map_type="basic")
    env.max_turns = 4  # episodes end fast -- only the schedule is under test
    d = BasicStateEncoder().get_depth(num_players)
    agents = [
        DQNAgent(*BASIC_SIZE, d, ReplayMemory(1000), conv_channels=(4, 8),
                 encoder="basic", fully_conv=False)
        for _ in range(num_players)
    ]
    return env, agents


def _run_with_fingerprints(seed_base, num_episodes=3, bad_seed=None):
    """Run `train_agents(seed_base=seed_base)` for `num_episodes`,
    recording `world_fingerprint()` and the raw `seed` argument
    `GameEnvironment.reset` was called with at every SUCCESSFUL reset.

    If `bad_seed` is given, `reset(seed=bad_seed)` is forced to raise
    `StartPlacementError` (every time that exact seed is tried) so the
    schedule's skip path runs; any other seed delegates to the real
    `reset`, so the world it produces is the genuine one.
    """
    env, agents = _make_agents()
    fingerprints = []
    seeds_used = []
    real_reset = GameEnvironment.reset

    def patched_reset(self, num_players=None, seed=None):
        if bad_seed is not None and seed == bad_seed:
            raise StartPlacementError(f"forced failure for seed {seed}")
        result = real_reset(self, num_players=num_players, seed=seed)
        fingerprints.append(world_fingerprint(self))
        seeds_used.append(seed)
        return result

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(GameEnvironment, "reset", patched_reset)
        train_agents(env, agents, num_episodes=num_episodes, batch_size=8, debug=False,
                     save_checkpoints=False, seed_base=seed_base)

    return fingerprints, seeds_used


def test_seed_schedule_is_deterministic_across_runs(monkeypatch, tmp_path):
    """Same seed_base, two independent runs (fresh env + fresh agents
    each time): identical seed sequence, identical world per episode.
    Common case (no skips): episode k's seed is exactly seed_base + k.
    """
    monkeypatch.chdir(tmp_path)  # train_agents always writes stats/ -- keep it out of the repo
    seed_base = 700000

    fingerprints_a, seeds_a = _run_with_fingerprints(seed_base)
    fingerprints_b, seeds_b = _run_with_fingerprints(seed_base)

    assert seeds_a == seeds_b == [seed_base, seed_base + 1, seed_base + 2]
    assert fingerprints_a == fingerprints_b


def test_seed_schedule_skips_failing_seed_identically_across_runs(monkeypatch, tmp_path, caplog):
    """One seed (what would be episode 1's, with no skip) is forced to
    fail start placement. Both runs must: skip it identically (same
    resulting seed sequence, permanently shifted for every later
    episode), log exactly one WARNING naming that seed, and still land
    on identical worlds for the episodes that DO succeed.
    """
    monkeypatch.chdir(tmp_path)
    seed_base = 800000
    bad_seed = seed_base + 1

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    fingerprints_a, seeds_a = _run_with_fingerprints(seed_base, bad_seed=bad_seed)
    warnings_a = [r for r in caplog.records if r.levelno == logging.WARNING]
    caplog.clear()

    fingerprints_b, seeds_b = _run_with_fingerprints(seed_base, bad_seed=bad_seed)
    warnings_b = [r for r in caplog.records if r.levelno == logging.WARNING]

    # bad_seed is consumed by the failure and never appears in the used list;
    # every later episode's seed is permanently shifted up by one.
    assert seeds_a == seeds_b == [seed_base, seed_base + 2, seed_base + 3]
    assert fingerprints_a == fingerprints_b

    for warnings in (warnings_a, warnings_b):
        assert len(warnings) == 1, [r.getMessage() for r in warnings]
        assert warnings[0].name == LOGGER_NAME
        assert f"seed {bad_seed}" in warnings[0].getMessage()
        assert "episode 1" in warnings[0].getMessage()


def test_seed_base_absent_uses_unseeded_reset_unchanged(monkeypatch, tmp_path):
    """seed_base omitted (the default): every episode still calls
    env.reset() unseeded, exactly like before this feature existed --
    full backward compatibility, not just 'doesn't crash'.
    """
    monkeypatch.chdir(tmp_path)
    env, agents = _make_agents()
    calls = []
    real_reset = GameEnvironment.reset

    def recording_reset(self, num_players=None, seed=None):
        calls.append(seed)
        return real_reset(self, num_players=num_players, seed=seed)

    monkeypatch.setattr(GameEnvironment, "reset", recording_reset)
    win_counts, win_history = train_agents(env, agents, num_episodes=2, batch_size=8,
                                            debug=False, save_checkpoints=False)

    assert calls == [None, None]
    assert len(win_history) == 2
    assert set(win_counts) == {0, 1}


def test_skipped_seeds_are_persisted_to_caller_list(monkeypatch, tmp_path):
    """`train_agents(skipped_seeds=[...])` records every skipped schedule
    seed in place — the #44 lesson: the baseline's skip record was a hand
    transcription of console scrollback and captured only 3 of 19 skips,
    spawning a phantom cross-machine-divergence investigation. The run
    summary now persists the machine-readable list (run_baseline.py wires
    this into its stats JSON).
    """
    monkeypatch.chdir(tmp_path)
    seed_base = 810000
    bad_seed = seed_base + 1
    env, agents = _make_agents()
    real_reset = GameEnvironment.reset

    def patched_reset(self, num_players=None, seed=None):
        if seed == bad_seed:
            raise StartPlacementError(f"forced failure for seed {seed}")
        return real_reset(self, num_players=num_players, seed=seed)

    skipped = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(GameEnvironment, "reset", patched_reset)
        train_agents(env, agents, num_episodes=3, batch_size=8, debug=False,
                     save_checkpoints=False, seed_base=seed_base,
                     skipped_seeds=skipped)

    assert skipped == [bad_seed]


def test_truncated_episodes_are_persisted_to_caller_list(monkeypatch, tmp_path):
    """`train_agents(truncated_episodes=[...])` records every episode cut off
    by the step-limit guard — the #51 lesson, and the same argument as
    `skipped_seeds` above: a truncated episode's recorded winner is an
    artifact of where the loop was cut, not a result, and a console warning
    is not a record (85 of the `duel_53ch_net128x6` run's 1000 episodes were
    truncated and nothing in that run's stats says which).

    Forced by lowering `trainer.STEP_LIMIT` rather than by building a
    livelock: after #51 the masks no longer offer an action that changes
    nothing, so a real one cannot be constructed — what is under test here is
    the guard's REPORTING, not its trigger.
    """
    monkeypatch.chdir(tmp_path)
    env, agents = _make_agents()
    env.max_turns = 250  # far beyond what 3 steps can reach

    truncated = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("civulator.training.trainer.STEP_LIMIT", 3)
        train_agents(env, agents, num_episodes=2, batch_size=8, debug=False,
                     save_checkpoints=False, seed_base=820000,
                     truncated_episodes=truncated)

    assert truncated == [0, 1]


def test_untruncated_run_reports_nothing(monkeypatch, tmp_path):
    """The healthy case: the list stays empty when episodes end on their own."""
    monkeypatch.chdir(tmp_path)
    env, agents = _make_agents()  # max_turns = 4, ends well inside the guard

    truncated = []
    train_agents(env, agents, num_episodes=2, batch_size=8, debug=False,
                 save_checkpoints=False, seed_base=830000,
                 truncated_episodes=truncated)

    assert truncated == []
