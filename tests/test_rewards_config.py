"""Tests for issue #25: reward values must flow from config.toml, not literals.

Gate: bit-identical behavior with the shipped config (defaults == config values
== the old hardcoded literals), plus proof that changing REWARDS changes what
step()/_execute_attack() return.
"""

from civulator.game import environment as env_module
from civulator.game.environment import GameEnvironment, REWARDS
from civulator.game.unit import ArcherUnit, WarriorUnit

from test_combat_range import make_flat_env, place


def test_rewards_match_the_shipped_table():
    """The loaded table must be exactly what config.toml ships — a guard
    against silent drift between the file and the running experiment.
    Current pin: the #46 reward-v2 anti-turtling table (2026-09-01);
    the pre-#46 values live in the #39/#40 manifests and git history."""
    assert REWARDS == {
        "invalid_action": -1,
        "fortify": 0,
        "damage_per_hp": 0.1,
        "kill": 10,
        "unit_lost": -5,
        "capture_civilian": 15,
        "capture_city": 80,
        "found_city": 40,
        "win": 100,
        "loss": -100,
        "draw": 0,
        "proximity_weight": 0.5,
        "proximity_radius": 0,
    }


def test_kill_reward_flows_from_config(monkeypatch):
    env = make_flat_env()
    archer = place(env, ArcherUnit, 0, (2, 2))
    target = place(env, WarriorUnit, 1, (2, 3))
    target.health = 1  # any hit kills

    monkeypatch.setitem(env_module.REWARDS, "kill", 99)
    monkeypatch.setitem(env_module.REWARDS, "damage_per_hp", 0)
    reward = env._execute_attack(archer, target)
    assert reward == 99, "kill reward did not come from the REWARDS table"


def test_invalid_action_reward_flows_from_config(monkeypatch):
    env = make_flat_env()
    monkeypatch.setitem(env_module.REWARDS, "invalid_action", -7)
    # Select an empty tile: no unit there -> invalid action
    _, reward, _ = env.step([(0, 0), (0, 1)])
    assert reward == -7, "invalid-action reward did not come from the REWARDS table"
