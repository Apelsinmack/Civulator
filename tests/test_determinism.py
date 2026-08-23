"""Tests for issue #26: reset(seed=...) must reproduce a world exactly.

Determinism is required by the project's research methodology (fixed seeds,
replicable experiments) and by demonstration recording (plays must be
replayable against the identical world).

map_type="basic" is explicit everywhere below (design doc §11 P3): these
worlds are all 8x16, below earthlike's Duel-size minimum (24x12, E5) now
that `[map] type`'s live default is "earthlike". Determinism itself is
exercised for earthlike too, at Duel size, in
tests/test_mapgen_earthlike.py — this file is about the reset(seed)/RNG-
stream CONTRACT (world identity + the seeded-then-unseeded replay sequence),
which is orthogonal to which generator produced the world.
"""

from civulator.game.environment import GameEnvironment
from civulator.game.unit import ArcherUnit, WarriorUnit

from test_combat_range import make_flat_env, place


def world_fingerprint(env):
    """Everything random about a freshly reset world, as comparable data.

    Terrain is compared as the composable layers themselves (design doc §3) —
    the tile's whole terrain state, not a flat name.
    """
    terrain = [
        (
            env.map.tiles[i, j].base_terrain,
            env.map.tiles[i, j].relief,
            env.map.tiles[i, j].feature,
            env.map.tiles[i, j].resource,
        )
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
    env1 = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=123)
    env2 = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=123)
    assert world_fingerprint(env1) == world_fingerprint(env2)


def test_different_seeds_produce_different_worlds():
    env1 = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=123)
    env2 = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=456)
    # 128 tiles of weighted terrain — identical worlds are astronomically unlikely
    assert world_fingerprint(env1) != world_fingerprint(env2)


def test_seeded_reset_sequence_is_reproducible():
    """reset(seed) then unseeded resets: the episode SEQUENCE must replay exactly."""
    def three_worlds():
        env = GameEnvironment(8, 16, num_players=2, map_type="basic")
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
