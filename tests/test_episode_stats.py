"""GameEnvironment.episode_stats (issue #48 statistics wish): per-player
episode counters — kills, losses, damage_dealt, cities_founded,
cities_captured, civilians_captured — incremented by the engine's own
action paths and reset with every episode. Exercised through env.step
(the same path agents use), not by poking internals.
"""

import numpy as np

from civulator.game.environment import GameEnvironment
from civulator.game.unit import SettlerUnit, WarriorUnit

from test_combat_range import make_flat_env, place


def step(env, sel, order):
    return env.step([np.array(sel), np.array(order)])


def test_kill_and_loss_and_damage_counters():
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (4, 4))
    defender = place(env, WarriorUnit, 1, (4, 5))
    defender.health = 1  # any hit kills

    step(env, (4, 4, attacker.slot), (4, 5))

    s0, s1 = env.episode_stats[0], env.episode_stats[1]
    assert s0["kills"] == 1 and s0["losses"] == 0
    assert s1["losses"] == 1 and s1["kills"] == 0
    assert s0["damage_dealt"] > 0


def test_civilian_capture_counter():
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (4, 4))
    settler = place(env, SettlerUnit, 1, (4, 5))
    settler.health = 1  # capture triggers on the killing blow

    step(env, (4, 4, attacker.slot), (4, 5))

    assert env.episode_stats[0]["civilians_captured"] == 1
    assert env.episode_stats[0]["kills"] == 1  # capture is a kill event too
    assert env.episode_stats[1]["losses"] == 1


def test_found_and_capture_city_counters():
    env = make_flat_env()
    settler = place(env, SettlerUnit, 0, (4, 4))
    step(env, (4, 4, settler.slot), (4, 4))  # order onto own tile = found
    assert env.episode_stats[0]["cities_founded"] == 1

    # Undefended enemy city adjacent to a warrior: move in = capture.
    assert env.found_city(env.players[1], (0, 10), "Enemy City") is not None
    raider = place(env, WarriorUnit, 0, (0, 9))
    step(env, (0, 9, raider.slot), (0, 10))
    assert env.episode_stats[0]["cities_captured"] == 1


def test_reset_clears_counters():
    env = GameEnvironment(8, 16, num_players=2, map_type="basic")
    env.episode_stats[0]["kills"] = 5
    env.reset(seed=321)
    assert env.episode_stats[0]["kills"] == 0
    assert set(env.episode_stats) == {0, 1}
