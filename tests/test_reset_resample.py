"""Tests for the unseeded-reset resample policy (design doc D26, §11 P7.5).

`mapgen.starts.place_starts` (the function whose own relax-and-retry ladder
raises `StartPlacementError` when exhausted, design doc §6.3/E5) is
monkeypatched here to fail on demand — these tests are about
`GameEnvironment.reset`'s policy layered ON TOP of that raise, not about
exercising the real ladder itself (test_mapgen_starts.py already covers
that statistically).

map_type="basic" at a small board throughout (design doc §11 P3 convention,
matching test_determinism.py): fast, and irrelevant to what's under test —
`_reset_attempt`'s retry wrapper doesn't care which generator produced the
StartPlacementError.
"""

import logging

import pytest

from civulator.game.environment import MAX_WORLD_RETRIES, GameEnvironment
from civulator.mapgen import starts as starts_mod
from civulator.mapgen.starts import StartPlacementError
from civulator.rng import PortableRNG

BASIC_SIZE = (8, 16)
LOGGER_NAME = "civulator.game.environment"


def _fail_then_succeed(monkeypatch, fail_count):
    """Patch starts.place_starts to raise StartPlacementError on the first
    `fail_count` calls, then delegate to the REAL implementation forever
    after. Returns a {"n": call_count} dict the test can inspect.

    Patching the module attribute (not the `generate_starts`-local name)
    works because `generate_starts` calls `place_starts(...)` as a bare
    module-global lookup, resolved at call time — same-module monkeypatch,
    no import-aliasing gotcha.
    """
    real_place_starts = starts_mod.place_starts
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= fail_count:
            raise StartPlacementError(f"forced failure #{calls['n']}")
        return real_place_starts(*args, **kwargs)

    monkeypatch.setattr(starts_mod, "place_starts", fake)
    return calls


def _always_fail(monkeypatch):
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        raise StartPlacementError(f"forced failure #{calls['n']}")

    monkeypatch.setattr(starts_mod, "place_starts", fake)
    return calls


def test_unseeded_reset_survives_forced_failures_then_succeeds(monkeypatch, caplog):
    """K forced failures, then a real success: K WARNING log records, the
    world actually comes up (every player gets a capital), and the engine
    RNG stream ends up exactly where an independent replay predicts.
    """
    seed = 999
    env = GameEnvironment(*BASIC_SIZE, num_players=2, map_type="basic", seed=seed)

    # Independent reference stream, using ONLY PortableRNG's public API —
    # replays what the design doc says happens: __init__'s own one
    # generate_map() draw, then one draw per _reset_attempt (success or
    # forced failure alike, design doc §4.2.1's "one documented draw"),
    # then the successful attempt's own start-list shuffle.
    ref_rng = PortableRNG(seed)
    ref_rng.next_uint64()  # __init__'s own generate_map() draw

    K = 3
    calls = _fail_then_succeed(monkeypatch, K)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    result = env.reset()  # unseeded
    assert result is env

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == K, f"expected {K} warnings, got {len(warnings)}: {[r.getMessage() for r in caplog.records]}"
    for i, rec in enumerate(warnings, start=1):
        msg = rec.getMessage()
        assert rec.name == LOGGER_NAME
        assert f"attempt {i}/{MAX_WORLD_RETRIES}" in msg
        assert "master seed=" in msg and "master seed=None" not in msg

    assert calls["n"] == K + 1, "K forced failures + exactly one real (successful) call"
    assert len(env.players) == 2
    for player in env.players:
        assert len(player.cities) == 1

    for _ in range(K):
        ref_rng.next_uint64()  # the K failed _reset_attempt draws
    ref_rng.next_uint64()  # the successful _reset_attempt's own draw
    ref_rng.shuffle(list(range(len(env.map.starts))))  # same-length shuffle as reset()'s own

    assert env.rng.random() == ref_rng.random(), "engine RNG stream did not advance as the replay predicts"


def test_seeded_reset_with_forced_failure_raises(monkeypatch, caplog):
    """reset(seed=N): StartPlacementError propagates unchanged, on the
    first and only attempt — no resample, no warning logged.
    """
    env = GameEnvironment(*BASIC_SIZE, num_players=2, map_type="basic", seed=999)
    calls = _always_fail(monkeypatch)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    with pytest.raises(StartPlacementError, match="forced failure #1"):
        env.reset(seed=42)

    assert calls["n"] == 1, "seeded reset must not retry"
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_unseeded_reset_exhausts_retries_and_raises(monkeypatch, caplog):
    """Every attempt fails: reset() tries exactly MAX_WORLD_RETRIES times,
    logs a warning each time, then raises a StartPlacementError summarizing
    the exhaustion (chained to the last underlying failure).
    """
    env = GameEnvironment(*BASIC_SIZE, num_players=2, map_type="basic", seed=999)
    calls = _always_fail(monkeypatch)

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    with pytest.raises(StartPlacementError, match="exhausted") as excinfo:
        env.reset()

    assert calls["n"] == MAX_WORLD_RETRIES
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == MAX_WORLD_RETRIES
    assert str(MAX_WORLD_RETRIES) in str(excinfo.value)
    assert excinfo.value.__cause__ is not None
    assert isinstance(excinfo.value.__cause__, StartPlacementError)
