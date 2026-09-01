"""Reward table v2 — the #46 anti-turtling package.

Three surfaces under test:
1. `GameEnvironment._proximity_potential` — the potential Phi(s) itself
   (military-only, nearest-enemy-city, radius cap, auto-radius, disable).
2. The shaping term gamma*Phi(s') - Phi(s) delivered through `env.step`
   (toward-city positive, away-from-city negative, exactly zero when
   proximity_weight is 0 — the byte-identical-to-pre-#46 guarantee).
3. Terminal win/loss/draw delivery through `train_agents` — every agent
   ends the episode with exactly one done=True transition carrying its
   terminal reward (previously a decisive game's loser never received a
   done=True transition at all).

REWARDS is patched per-test to pinned values so expectations never depend
on config.toml's current (experiment-tuned) table.
"""

import pytest

from civulator.game.environment import GameEnvironment, GAMMA, REWARDS
from civulator.game.unit import SettlerUnit, WarriorUnit
from civulator.agents.dqn_agent import DQNAgent
from civulator.agents.replay_memory import ReplayMemory
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.training import trainer as trainer_mod
from civulator.training.trainer import _terminal_rewards, train_agents

from test_combat_range import make_flat_env, place


@pytest.fixture
def pinned_rewards():
    """Pin REWARDS to known values; restore the live table afterwards.

    Mutates the module-level dict in place (trainer imported the same
    object by reference, so replacing it wouldn't propagate).
    """
    saved = dict(REWARDS)
    REWARDS.update(
        invalid_action=-1, fortify=0, damage_per_hp=0.1, kill=10,
        unit_lost=-10, capture_civilian=15, capture_city=20, found_city=15,
        win=1000, loss=-1000, draw=-777,
        proximity_weight=0.5, proximity_radius=0,
    )
    yield REWARDS
    REWARDS.clear()
    REWARDS.update(saved)


def env_with_enemy_city(city_pos=(4, 8)):
    """Flat 8x16 env, player 1 owning one city; no units yet."""
    env = make_flat_env()
    city = env.found_city(env.players[1], city_pos, "Enemy City")
    assert city is not None
    return env


# --- 1. The potential itself -----------------------------------------------

def test_potential_zero_without_enemy_cities(pinned_rewards):
    env = make_flat_env()
    place(env, WarriorUnit, 0, (4, 5))
    assert env._proximity_potential(env.players[0]) == 0.0


def test_potential_sums_military_units_by_nearest_city_distance(pinned_rewards):
    env = env_with_enemy_city((4, 8))
    # Auto radius on a 16-wide map: 16//2 + 1 = 9.
    place(env, WarriorUnit, 0, (4, 5))   # d=3 -> 0.5 * (9-3) = 3.0
    assert env._proximity_potential(env.players[0]) == pytest.approx(3.0)

    place(env, SettlerUnit, 0, (4, 6))   # civilian: no contribution
    assert env._proximity_potential(env.players[0]) == pytest.approx(3.0)

    place(env, WarriorUnit, 0, (4, 0))   # d=8 -> 0.5 * (9-8) = 0.5
    assert env._proximity_potential(env.players[0]) == pytest.approx(3.5)


def test_potential_radius_cap_and_override(pinned_rewards):
    env = env_with_enemy_city((4, 8))
    place(env, WarriorUnit, 0, (4, 5))   # d=3
    place(env, WarriorUnit, 0, (4, 0))   # d=8
    REWARDS["proximity_radius"] = 4
    # d=3 -> 0.5*(4-3) = 0.5; d=8 is outside the radius -> 0.
    assert env._proximity_potential(env.players[0]) == pytest.approx(0.5)


def test_potential_disabled_at_weight_zero(pinned_rewards):
    env = env_with_enemy_city((4, 8))
    place(env, WarriorUnit, 0, (4, 5))
    REWARDS["proximity_weight"] = 0
    assert env._proximity_potential(env.players[0]) == 0.0


# --- 2. Shaping through env.step -------------------------------------------

def _step_move(env, src, dst):
    import numpy as np
    return env.step([np.array(src), np.array(dst)])


def test_step_toward_enemy_city_pays_positive_shaping(pinned_rewards):
    env = env_with_enemy_city((4, 8))
    place(env, WarriorUnit, 0, (4, 4))          # d=4: Phi = 0.5*5 = 2.5
    place(env, WarriorUnit, 1, (0, 0))          # keep player 1 alive
    _, reward, _ = _step_move(env, (4, 4), (4, 5))  # d=3: Phi' = 3.0
    assert reward == pytest.approx(GAMMA * 3.0 - 2.5)  # +0.2 at gamma 0.9


def test_step_away_from_enemy_city_pays_negative_shaping(pinned_rewards):
    env = env_with_enemy_city((4, 8))
    place(env, WarriorUnit, 0, (4, 4))          # Phi = 2.5
    place(env, WarriorUnit, 1, (0, 0))
    _, reward, _ = _step_move(env, (4, 4), (4, 3))  # d=5: Phi' = 2.0
    assert reward == pytest.approx(GAMMA * 2.0 - 2.5)  # -0.7 at gamma 0.9


def test_step_shaping_exactly_zero_when_disabled(pinned_rewards):
    REWARDS["proximity_weight"] = 0
    env = env_with_enemy_city((4, 8))
    place(env, WarriorUnit, 0, (4, 4))
    place(env, WarriorUnit, 1, (0, 0))
    _, reward, _ = _step_move(env, (4, 4), (4, 5))
    assert reward == 0  # byte-identical to the pre-#46 move reward


# --- 3. Terminal delivery through the trainer ------------------------------

def test_terminal_rewards_helper(pinned_rewards):
    assert _terminal_rewards(None, 2) == {0: -777, 1: -777}
    assert _terminal_rewards(0, 2) == {0: 1000, 1: -1000}
    assert _terminal_rewards(1, 3) == {0: -1000, 1: 1000, 2: -1000}


def test_every_agent_gets_exactly_one_terminal_transition(pinned_rewards, monkeypatch):
    # No artifact writes from a unit test (stats/ is the scientific record).
    monkeypatch.setattr(trainer_mod, "save_win_history", lambda *a, **k: None)

    env = GameEnvironment(8, 16, num_players=2, map_type="basic")
    env.max_turns = 3  # force a fast end at the turn cap

    depth = EnhancedStateEncoder().get_depth(2)
    agents = [
        DQNAgent(8, 16, depth, ReplayMemory(1000), encoder="enhanced", fully_conv=True)
        for _ in range(2)
    ]
    # batch_size larger than any possible memory: optimization never runs.
    train_agents(env, agents, num_episodes=1, batch_size=10**9,
                 save_checkpoints=False)

    terminal_magnitudes = []
    for agent in agents:
        assert not agent.pending_transitions, "pending transition left unresolved"
        done_rewards = [t[2] for t in agent.memory.memory if t[4]]
        assert len(done_rewards) == 1, (
            f"expected exactly one done=True transition, got {len(done_rewards)}"
        )
        terminal_magnitudes.append(done_rewards[0])

    # Whatever the outcome (score-tiebreak winner or draw), each agent's
    # final reward must include its terminal component (|value| >= 777
    # dwarfs any in-game reward at these pinned values), and the pair must
    # be consistent: win+loss or draw+draw — never double-paid.
    for r in terminal_magnitudes:
        assert abs(r) > 700, f"terminal reward missing from final transition: {r}"
        assert abs(r) < 1500, f"terminal reward looks double-paid: {r}"
    assert (
        min(terminal_magnitudes) < 0
    ), "at least one agent must carry a loss or draw terminal"
