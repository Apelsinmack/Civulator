"""Tests for issue #26: reset(seed=...) must reproduce a world exactly.

Determinism is required by the project's research methodology (fixed seeds,
replicable experiments) and by demonstration recording (plays must be
replayable against the identical world).
"""

from civulator.game.environment import GameEnvironment
from civulator.game.unit import ArcherUnit, WarriorUnit

from test_combat_range import make_flat_env, place


def world_fingerprint(env):
    """Everything random about a freshly reset world, as comparable data."""
    terrain = [
        (env.map.tiles[i, j].terrain_type, tuple(env.map.tiles[i, j].features))
        for i in range(env.n)
        for j in range(env.m)
    ]
    cities = sorted(
        (p.player_index, c.coordinates) for p in env.players for c in p.cities
    )
    units = sorted(
        (p.player_index, u.unit_type, u.coordinates)
        for p in env.players
        for u in p.units
    )
    return terrain, cities, units


def test_same_seed_reproduces_identical_world():
    env1 = GameEnvironment(8, 16, num_players=2).reset(seed=123)
    env2 = GameEnvironment(8, 16, num_players=2).reset(seed=123)
    assert world_fingerprint(env1) == world_fingerprint(env2)


def test_different_seeds_produce_different_worlds():
    env1 = GameEnvironment(8, 16, num_players=2).reset(seed=123)
    env2 = GameEnvironment(8, 16, num_players=2).reset(seed=456)
    # 128 tiles of weighted terrain — identical worlds are astronomically unlikely
    assert world_fingerprint(env1) != world_fingerprint(env2)


def test_seeded_reset_sequence_is_reproducible():
    """reset(seed) then unseeded resets: the episode SEQUENCE must replay exactly."""
    def three_worlds():
        env = GameEnvironment(8, 16, num_players=2)
        env.reset(seed=7)
        worlds = [world_fingerprint(env)]
        for _ in range(2):
            env.reset()
            worlds.append(world_fingerprint(env))
        return worlds

    assert three_worlds() == three_worlds()


def test_same_seed_same_combat_outcome():
    def run_attack():
        env = make_flat_env()
        env.rng.seed(99)
        archer = place(env, ArcherUnit, 0, (2, 2))
        target = place(env, WarriorUnit, 1, (2, 3))
        damage_dealt, _, _, _ = archer.attack(target, env)
        return damage_dealt

    assert run_attack() == run_attack()
