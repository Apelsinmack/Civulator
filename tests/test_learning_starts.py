"""Tests for the `learning_starts` knob on `train_agents` (issue #80):
`civulator/training/trainer.py` used to gate a DQN agent's first
optimization step on a hardcoded `len(memory) > batch_size`. #80 exposes
that threshold as a parameter — `learning_starts=None` (the default) must
resolve to exactly `batch_size + 1` and use a `>=` comparison, so the
default behaviour is bit-identical to the old `> batch_size` gate transition
for transition; an explicit value delays the first gradient step until the
buffer reaches it.

Small board (map_type="basic", 8x16, matching test_seed_schedule.py's
BASIC_SIZE) + tiny conv_channels, same convention as test_seed_schedule.py
and test_determinism.py: these tests are about the GATE, not combat or
state encoding.

`DQNAgent.optimize` is monkeypatched to record `len(self.memory)` at the
moment it is called and then immediately raise a sentinel exception —
this stops `train_agents` at the very first optimize call without ever
running a real gradient step or a long game, per the issue's own guidance
to prefer wrapping/monkeypatching `DQNAgent.optimize` over running long
games.

A single-player environment (`num_players=1`) is used deliberately, not
just for speed: with two or more agents, `train_agents`'s pending-
transition bookkeeping (a player's transition is only completed once
their own turn comes back around, `civulator/training/trainer.py`'s
`complete_pending_transition` call at the top of the loop) can push TWO
transitions into the same agent's memory within a single loop iteration
(the completed carry-over transition, plus this iteration's own fresh
one) — an existing, pre-#80 property of the multi-agent bookkeeping, not
something this patch touches. That makes the exact buffer size at the
first optimize call nondeterministic with several agents (it can overshoot
a target by one). With a single player, `env.current_player` never
changes, so the trainer's "did the turn switch" check is always false,
every action is stored immediately, and the buffer grows by exactly one
transition per loop iteration — giving a fully deterministic count to
assert on, which is what this gate test needs.
"""

import pytest

from civulator.agents import DQNAgent, ReplayMemory, BasicStateEncoder
from civulator.game.environment import GameEnvironment
from civulator.training import train_agents

BASIC_SIZE = (8, 16)


class _StoppedAtFirstOptimize(Exception):
    """Raised by the patched DQNAgent.optimize to abort the run the instant
    the first optimization call happens, so the test never has to play out
    a full (or even long) game."""


def _make_single_player_agent(max_turns=250):
    num_players = 1
    env = GameEnvironment(*BASIC_SIZE, num_players=num_players, map_type="basic")
    env.max_turns = max_turns
    d = BasicStateEncoder().get_depth(num_players)
    agents = [
        DQNAgent(*BASIC_SIZE, d, ReplayMemory(1000), conv_channels=(4, 8),
                 encoder="basic", fully_conv=False)
    ]
    return env, agents


def _memory_size_at_first_optimize(monkeypatch, tmp_path, learning_starts,
                                    batch_size=32, num_episodes=500):
    """Run `train_agents(..., learning_starts=learning_starts)` on a
    single-player environment and return `len(memory)` as observed at the
    very first `DQNAgent.optimize` call. Aborts the run right there via
    `_StoppedAtFirstOptimize` — cheap regardless of `num_episodes`, which
    is only an upper bound in case the threshold is never reached (each
    episode contributes only a handful of transitions, since a lone
    player's game ends almost immediately).
    """
    monkeypatch.chdir(tmp_path)  # train_agents always writes stats/ -- keep it out of the repo
    env, agents = _make_single_player_agent()
    calls = []

    def fake_optimize(self, bs):
        calls.append(len(self.memory))
        raise _StoppedAtFirstOptimize()

    monkeypatch.setattr(DQNAgent, "optimize", fake_optimize)

    try:
        train_agents(env, agents, num_episodes=num_episodes, batch_size=batch_size,
                     debug=False, save_checkpoints=False,
                     learning_starts=learning_starts)
    except _StoppedAtFirstOptimize:
        pass

    assert calls, (
        "DQNAgent.optimize was never called within "
        f"{num_episodes} episodes -- threshold too high for this test board"
    )
    return calls[0]


def test_default_learning_starts_reproduces_the_old_gt_batch_size_gate(monkeypatch, tmp_path):
    """learning_starts omitted (the default): the first optimize call must
    happen at exactly the same buffer size the old hardcoded
    `len(memory) > batch_size` gate fired at -- i.e. no call at
    len(memory) == batch_size (32), the first one at len(memory) == 33.
    """
    first_call_size = _memory_size_at_first_optimize(
        monkeypatch, tmp_path, learning_starts=None, batch_size=32)

    assert first_call_size == 33


def test_explicit_learning_starts_delays_the_first_optimize_call(monkeypatch, tmp_path):
    """An explicit, larger learning_starts: no optimize call happens until
    the buffer reaches that count -- the first call's buffer size must be
    exactly the configured threshold, not the old batch_size + 1 default.
    """
    first_call_size = _memory_size_at_first_optimize(
        monkeypatch, tmp_path, learning_starts=50, batch_size=32)

    assert first_call_size == 50
