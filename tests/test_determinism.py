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

import numpy as np

from civulator.game.environment import GameEnvironment
from civulator.game.player import Player
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


# The fields a Player keeps across `reset` when the env keeps its players;
# every other attribute is per-episode (Player.reset_state).
PLAYER_IDENTITY_FIELDS = {"name", "player_index", "game_env"}
# `city`: a District's link to its city (v0.9.0 Q3) -- the city is compared
# through the player that owns it.
_BACK_REFERENCES = {"player", "game_env", "city"}


def _data(value):
    """Plain comparable data: objects by their fields, back-references to the
    owning player/environment dropped (they would recurse)."""
    if isinstance(value, np.ndarray):
        return ("ndarray", value.shape, value.tolist())
    if isinstance(value, dict):
        return {key: _data(v) for key, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_data(v) for v in value]
    if hasattr(value, "__dict__"):
        return (type(value).__name__,
                {k: _data(v) for k, v in vars(value).items() if k not in _BACK_REFERENCES})
    return value


def episode_fingerprint(env):
    """The world plus every Player field (whatever fields Player has), the
    episode counters, the round and the ownership grid."""
    players = [
        {k: _data(v) for k, v in vars(p).items() if k != "game_env"} for p in env.players
    ]
    return (world_fingerprint(env), players, _data(env.episode_stats),
            env.turn_counter, env.current_player_index, sorted(env.city_by_id),
            env.map.owner_city.tolist())


def test_reset_after_play_equals_a_fresh_reset_including_every_player_field():
    """Play rounds on a seeded env (pools fill, units heal, explored grows),
    then dirty every Player field except its identity, then reset(seed): the
    result equals a fresh environment's reset(seed) field for field. Breaks
    if a per-episode field is left out of Player.reset_state (it would leak
    from one episode into the next), or reset keeps players some other way."""
    seed = 31
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for _ in range(2 * 6):
        env.next_turn()
    assert any(p.science > 0 and p.culture > 0 and p.gold > 0 for p in env.players), \
        "fixture: the rounds filled the pools"
    fresh_fields = set(vars(Player("probe", 0, env)))
    assert fresh_fields - PLAYER_IDENTITY_FIELDS, "fixture: Player has per-episode state"
    sentinel = object()
    for player in env.players:
        for key in set(vars(player)) - PLAYER_IDENTITY_FIELDS:
            setattr(player, key, sentinel)

    env.reset(seed=seed)
    fresh = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    assert episode_fingerprint(env) == episode_fingerprint(fresh)


def test_same_seed_same_combat_outcome():
    def run_attack():
        env = make_flat_env()
        env.rng.seed(99)
        archer = place(env, ArcherUnit, 0, (2, 2))
        target = place(env, WarriorUnit, 1, (2, 3))
        damage_dealt, _, _, _ = archer.attack(target, env)
        return damage_dealt

    assert run_attack() == run_attack()


def test_same_seed_same_fortified_district_siege():
    """v0.9.0 Q3: attacks on a fortified district and its strikes draw the
    engine RNG through `calculate_damage`, so the same seed and the same
    orders give the same state -- unit health, district health, episode
    counters -- across turn rollovers (strikes, repair). Breaks if any
    fortification rule draws from another source or iterates a set."""
    from test_fortified_districts import FORT, fortified_board, order

    def run():
        env, city, district = fortified_board(walls=True)
        env.create_city(env.players[1], (6, 13), "Home")  # player 1 stays alive
        env.rng.seed(1234)
        attackers = [place(env, cls, 1, pos) for cls, pos in (
            (WarriorUnit, (3, 8)), (WarriorUnit, (2, 8)), (ArcherUnit, (3, 9)))]
        for _ in range(4):
            for unit in attackers:
                if unit in env.players[1].units and unit.movement_points > 0:
                    order(env, unit, FORT)
            env.next_turn()  # player 0: repair, centre strike, fortification strike
            env.next_turn()  # back to player 1
        return (_data(env.episode_stats),
                [(u.unit_type, u.coordinates, u.health) for p in env.players for u in p.units],
                district.health, city.health)

    first, second = run(), run()
    assert first == second
    stats = first[0]
    assert stats[1]["damage_dealt"] > 0 and stats[0]["encampment_strikes"] > 0,         "fixture: the fortification was attacked and fired back"


def test_the_episode_fingerprint_sees_the_religion():
    """v0.9.0 Q8: `Player.religion` (the founded religion, a `Religion`
    record) and `City.religion` (the founder index a city follows) are
    per-episode state -- reset to None by `reset_state` / a fresh City and
    part of the episode fingerprint, so two games that differ only in a
    religion, in one belief of it, or in one city's religion do not compare
    equal. Breaks if either field leaves the fingerprint's reach or
    `Player.religion` leaves `reset_state`."""
    from civulator.game.religion import Religion
    from civulator.religion_model import TIER_FOLLOWER, TIER_FOUNDER, beliefs_of_tier

    a = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=5)
    b = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=5)
    assert episode_fingerprint(a) == episode_fingerprint(b)
    assert a.players[0].religion is None and a.players[0].cities[0].religion is None
    founder, follower = beliefs_of_tier(TIER_FOUNDER)[0], beliefs_of_tier(TIER_FOLLOWER)[0]
    a.players[0].religion = Religion(founder=0, founder_belief=founder, follower_beliefs=[follower])
    with_religion = episode_fingerprint(a)
    assert with_religion != episode_fingerprint(b)
    a.players[0].religion.follower_beliefs.append(beliefs_of_tier(TIER_FOLLOWER)[1])
    assert episode_fingerprint(a) != with_religion
    a.players[0].religion = None
    assert episode_fingerprint(a) == episode_fingerprint(b)
    a.players[1].cities[0].religion = 0
    assert episode_fingerprint(a) != episode_fingerprint(b)
    a.reset(seed=5)
    assert episode_fingerprint(a) == episode_fingerprint(b)
    assert a.players[0].religion is None


def test_the_episode_fingerprint_sees_the_pantheon():
    """v0.9.0 Q7: `Player.pantheon` is per-episode state -- reset to None by
    `reset_state` and part of the episode fingerprint, so two games that
    differ only in a pantheon do not compare equal. Breaks if the field
    moves off Player (out of the fingerprint) or out of `reset_state`."""
    from civulator.religion_model import PANTHEON_ORDER

    a = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=5)
    b = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=5)
    assert episode_fingerprint(a) == episode_fingerprint(b)
    assert a.players[0].pantheon is None
    a.players[0].pantheon = PANTHEON_ORDER[0]
    assert episode_fingerprint(a) != episode_fingerprint(b)
    a.reset(seed=5)
    assert a.players[0].pantheon is None
