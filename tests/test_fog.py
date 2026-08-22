"""Tests for the fog-of-war system (design agreed with Erik 2026-08-22).

Three knowledge states: hidden / explored-but-fogged / visible.
Engine owns perception (get_visibility_mask / get_explored_mask /
update_exploration); the EnhancedStateEncoder applies it optionally
(config.toml [training] fog_of_war). Ranged targets appear in the
canonical move mask when in range and line of sight (issue #30).
"""

import numpy as np

from civulator.agents.networks import get_valid_moves_mask
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.game.unit import NUM_UNIT_SLOTS, ArcherUnit, WarriorUnit

from test_combat_range import make_flat_env, place


def set_terrain(env, coords, base, relief=None, feature=None):
    """Repaint one tile. set_layers bumps the map's terrain epoch, which is what
    drops the line-of-sight cache (design doc §3.4) — no manual clearing."""
    env.map.get_tile(coords).set_layers(base, relief=relief, feature=feature, map_ref=env.map)


# --- Engine perception surface ---

def test_visibility_radius_on_flat_ground():
    env = make_flat_env()
    place(env, WarriorUnit, 0, (4, 8))
    vis = env.get_visibility_mask(0)

    assert vis[4, 8]
    for coords in [(4, 10), (2, 8), (6, 8)]:  # hex distance 2
        assert vis[coords], f"{coords} at distance 2 should be visible"
    assert not vis[4, 11], "distance 3 must be beyond base vision"


def test_mountain_blocks_sight_but_is_seen_itself():
    env = make_flat_env()
    place(env, WarriorUnit, 0, (4, 4))
    set_terrain(env, (4, 5), "Plains", relief="mountain")
    vis = env.get_visibility_mask(0)

    assert vis[4, 5], "adjacent mountain is visible"
    assert not vis[4, 6], "tile behind the mountain is hidden"


def test_cities_have_eyes():
    env = make_flat_env()
    env.found_city(env.players[0], (3, 3), "Watchtown")
    vis = env.get_visibility_mask(0)
    assert vis[3, 3] and vis[3, 5], "city must see its surroundings"


def test_explored_persists_after_leaving():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (2, 2))
    env.update_exploration(0)

    env.move_unit(warrior, (6, 12))
    env.update_exploration(0)

    vis = env.get_visibility_mask(0)
    explored = env.get_explored_mask(0)
    assert not vis[2, 2], "old position no longer visible"
    assert explored[2, 2], "old position stays explored"
    assert explored[6, 12] and vis[6, 12]


def test_reset_initializes_and_clears_exploration():
    env = make_flat_env()
    env.get_explored_mask(0)  # works even before any update (all False)
    env.reset(seed=5)
    explored = env.get_explored_mask(0)
    assert explored.any(), "players know their starting surroundings"
    total_first = explored.sum()

    env.reset(seed=5)
    assert env.get_explored_mask(0).sum() == total_first, \
        "reset must clear fog memory, not accumulate across episodes"


# --- Encoder ---

def test_encoder_fog_off_shows_everything_at_depth_25():
    env = make_flat_env()
    place(env, WarriorUnit, 0, (1, 1))
    place(env, WarriorUnit, 1, (6, 12))  # far beyond vision

    enc = EnhancedStateEncoder(fog_of_war=False)
    state = enc.encode(env, 0)
    assert state.shape[0] == 25
    assert state[16, 6, 12] > 0, "fog off: distant enemy is encoded"


def test_encoder_fog_on_hides_unseen_enemy():
    env = make_flat_env()
    place(env, WarriorUnit, 0, (1, 1))
    near = place(env, WarriorUnit, 1, (1, 3))   # distance 2: visible
    far = place(env, WarriorUnit, 1, (6, 12))   # hidden

    enc = EnhancedStateEncoder(fog_of_war=True)
    state = enc.encode(env, 0)
    assert state.shape[0] == 27
    assert state[16, 1, 3] > 0, "visible enemy encoded"
    assert state[16, 6, 12] == 0, "hidden enemy absent"
    assert state[25, 1, 1] == 1 and state[25, 6, 12] == 0, "visible channel"
    assert state[24, 6, 12] == 0, "unexplored terrain masked"


def test_encoder_fog_on_remembers_enemy_city_not_enemy_unit():
    env = make_flat_env()
    scout = place(env, WarriorUnit, 0, (3, 3))
    env.found_city(env.players[1], (3, 5), "Fogtown")   # distance 2: seen
    place(env, WarriorUnit, 1, (3, 4))                  # adjacent: seen
    env.update_exploration(0)

    env.move_unit(scout, (7, 14))  # walk away; city+unit now fogged
    env.update_exploration(0)

    enc = EnhancedStateEncoder(fog_of_war=True)
    state = enc.encode(env, 0)
    assert state[23, 3, 5] == 1, "explored enemy city stays on the map"
    assert state[16, 3, 4] == 0, "fogged enemy unit disappears (units move)"
    assert state[26, 3, 5] == 1 and state[25, 3, 5] == 0, "explored but not visible"
    assert state[24, 3, 5] > 0, "explored terrain remembered"


# --- Ranged targets in the canonical move mask (#30) ---

def _mask_for(env, unit):
    enc = EnhancedStateEncoder(fog_of_war=False)
    state = enc.encode(env, 0)
    r, c = unit.coordinates
    selected_pos = (r * env.m + c) * NUM_UNIT_SLOTS + unit.slot
    return get_valid_moves_mask(state, selected_pos, env).reshape(env.n, env.m)


def test_ranged_mask_marks_enemy_at_range_two():
    env = make_flat_env()
    archer = place(env, ArcherUnit, 0, (2, 2))
    place(env, WarriorUnit, 1, (2, 4))  # straight line, hex distance 2
    mask = _mask_for(env, archer)
    assert mask[2, 4] == 1, "in-range, clear-LoS enemy must be a valid target"


def test_ranged_mask_respects_line_of_sight():
    env = make_flat_env()
    archer = place(env, ArcherUnit, 0, (2, 2))
    place(env, WarriorUnit, 1, (2, 4))
    set_terrain(env, (2, 3), "Plains", relief="mountain")
    mask = _mask_for(env, archer)
    assert mask[2, 4] == 0, "blocked LoS: not a valid target"


def test_ranged_mask_respects_range_limit():
    env = make_flat_env()
    archer = place(env, ArcherUnit, 0, (2, 2))
    place(env, WarriorUnit, 1, (2, 5))  # hex distance 3
    mask = _mask_for(env, archer)
    assert mask[2, 5] == 0, "beyond range: not a valid target"


def test_melee_mask_gains_no_ranged_targets():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (2, 2))
    place(env, WarriorUnit, 1, (2, 4))
    mask = _mask_for(env, warrior)
    assert mask[2, 4] == 0, "melee units cannot target at range"
