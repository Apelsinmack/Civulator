"""E2E repro for issue #24: ranged attacks must use hex distance, not Manhattan.

Two failure modes of the old Manhattan computation:
1. Diagonal shots: a target at true hex distance 2 along the (+q, -r) diagonal
   reads as Manhattan 4 and a legal shot is refused.
2. Map seam: cylindrical wrap is ignored, so a target one tile across the seam
   reads as Manhattan (map_width - 1) and can never be shot.
"""

from civulator.game.environment import GameEnvironment
from civulator.game.unit import ArcherUnit, CatapultUnit, WarriorUnit


def make_flat_env(n=8, m=16):
    """Environment with all-Plains terrain so LoS and occupancy can't interfere."""
    env = GameEnvironment(n, m, num_players=2)
    for i in range(n):
        for j in range(m):
            tile = env.map.tiles[i, j]
            tile.terrain_type = "Plains"
            tile.features = []
            tile.update_terrain_properties()
    return env


def place(env, unit_cls, player_index, coords):
    player = env.players[player_index]
    tile = env.map.get_tile(coords)
    unit = unit_cls(player, coords, tile.terrain_type)
    player.units.append(unit)
    env.add_unit_to_tile(unit, coords)
    return unit


def test_archer_hits_diagonal_at_hex_distance_2():
    env = make_flat_env()
    # (2,2) -> (0,4): dr=-2, dq=+2, dq+dr=0 -> hex distance 2 (in range).
    # Manhattan distance is 4, which the old code wrongly refused.
    archer = place(env, ArcherUnit, 0, (2, 2))
    target = place(env, WarriorUnit, 1, (0, 4))
    assert env.map.distance_function(archer.coordinates, target.coordinates) == 2

    damage_dealt, _, _, _ = archer.attack(target, env)
    assert damage_dealt > 0, "legal diagonal shot at hex distance 2 was refused"


def test_archer_shoots_across_map_seam():
    env = make_flat_env()
    # (3,0) -> (3,15) on a 16-wide cylinder: adjacent across the seam (hex distance 1).
    # Manhattan distance is 15, so the old code could never shoot across the seam.
    archer = place(env, ArcherUnit, 0, (3, 0))
    target = place(env, WarriorUnit, 1, (3, 15))
    assert env.map.distance_function(archer.coordinates, target.coordinates) == 1

    damage_dealt, _, _, _ = archer.attack(target, env)
    assert damage_dealt > 0, "shot across the cylindrical seam was refused"


def test_catapult_hits_diagonal_at_hex_distance_2():
    env = make_flat_env()
    catapult = place(env, CatapultUnit, 0, (4, 6))
    # (4,6) -> (2,8): dr=-2, dq=+2 -> hex distance 2 (catapult range 2).
    target = place(env, WarriorUnit, 1, (2, 8))
    assert env.map.distance_function(catapult.coordinates, target.coordinates) == 2

    damage_dealt, _, _, _ = catapult.attack(target, env)
    assert damage_dealt > 0, "legal catapult bombard at hex distance 2 was refused"


def test_archer_refuses_target_beyond_range():
    env = make_flat_env()
    archer = place(env, ArcherUnit, 0, (2, 2))
    # (2,2) -> (2,5): hex distance 3 > range 2 -> must be refused.
    target = place(env, WarriorUnit, 1, (2, 5))
    assert env.map.distance_function(archer.coordinates, target.coordinates) == 3

    damage_dealt, _, target_killed, _ = archer.attack(target, env)
    assert damage_dealt == 0 and not target_killed, "out-of-range shot was allowed"
