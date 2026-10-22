"""Tile ownership (issue #87 P2, spec docs/borders_culture_design.md §2, §4, §5, §8).

Every test names the property it protects and the change that must break it.
"""

import hashlib
import json
import os

import numpy as np
import pytest
import torch

from civulator.agents.networks import get_valid_moves_mask
from civulator.agents.state_encoders import get_encoder
from civulator.game.environment import GameEnvironment
from civulator.game.territory import NEUTRAL, WORK_RADIUS
from civulator.game.unit import NUM_UNIT_SLOTS, SettlerUnit, WarriorUnit
from civulator.tools.recording import _clear_board, build_env_from_scenario, load_scenario

from test_combat_range import make_flat_env, place

SCENARIO_FIXTURE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fixtures", "scenario_fixture.json"
)


def assert_territory_invariants(env):
    """§2 invariants: every grid id resolves through `env.city_by_id` to a
    city in its player's list; every listed city is registered under its own
    id; `tile.city` set => the grid holds that city's id there; the live
    per-player counters equal the counts derived from the grid."""
    grid = env.map.owner_city
    for city_id in np.unique(grid):
        if city_id == NEUTRAL:
            continue
        city = env.city_by_id.get(int(city_id))
        assert city is not None, f"grid id {city_id} has no city"
        assert city in city.player.cities, f"city {city_id} missing from its player's list"
    for player in env.players:
        for city in player.cities:
            assert env.city_by_id.get(city.city_id) is city
        derived = sum(int(np.count_nonzero(grid == c.city_id)) for c in player.cities)
        assert env.map.owned_tile_count(player.player_index) == derived
    for r in range(env.n):
        for c in range(env.m):
            tile_city = env.map.tiles[r, c].city
            if tile_city is not None:
                assert grid[r, c] == tile_city.city_id, (r, c)


def _owned_by(env, city):
    return set(env.map.tiles_of_city(city.city_id))


# --- §2 invariants across every lifecycle path ------------------------------


def test_invariants_hold_after_reset_and_settler_founding():
    """Property: the §2 invariants hold after reset (capitals) and after a
    Settler founds a city through `step`. Breaks if reset or
    `SettlerUnit.found_city` builds a City outside `create_city`."""
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=123)
    assert_territory_invariants(env)
    for player in env.players:
        assert env.map.owned_tile_count(player.player_index) > 0

    env2 = make_flat_env()
    settler = place(env2, SettlerUnit, 0, (4, 4))
    env2.current_player, env2.current_player_index = env2.players[0], 0
    env2.step([(4, 4, settler.slot), (4, 4)])
    city = env2.map.get_tile((4, 4)).city
    assert city is not None and city.player is env2.players[0]
    assert (4, 4) in _owned_by(env2, city)
    assert_territory_invariants(env2)


def _painted_scenario():
    scenario = load_scenario(SCENARIO_FIXTURE)
    # Closer than min_city_distance on purpose: the second and third take the
    # recording fallback. (2, 4) is two steps from (2, 2); (2, 3) is between.
    scenario["cities"] = [
        {"team": 1, "row": 2, "col": 2, "hp": 200},
        {"team": 2, "row": 2, "col": 4, "hp": 200},
        {"team": 1, "row": 5, "col": 3, "hp": 200},
    ]
    return scenario


def test_invariants_hold_after_painted_placement_and_clear_board():
    """Property: painted placement (including the spacing-skipping fallback)
    and `_clear_board` keep the §2 invariants, contested ring tiles stay with
    the city placed earlier, and clearing the board leaves no owned tile.
    Breaks if `recording._place_city` or `_clear_board` bypass the creation/
    removal functions."""
    env = build_env_from_scenario(_painted_scenario())
    assert_territory_invariants(env)

    first = env.map.get_tile((2, 2)).city
    second = env.map.get_tile((2, 4)).city
    assert first is not None and second is not None
    contested = set(env.map.get_adjacent_coords((2, 2))) & set(env.map.get_adjacent_coords((2, 4)))
    assert contested
    for pos in contested:
        assert env.map.owner_id_at(pos) == first.city_id, pos

    _clear_board(env)
    assert_territory_invariants(env)
    assert (env.map.owner_city == NEUTRAL).all()
    assert not env.city_by_id


def test_founding_replaces_tiles_blocked_by_another_player_and_keeps_own():
    """Property (§2.1): a ring tile owned by another player is replaced by a
    tile outside ring 1, a ring tile owned by the founder's own other city
    stays with that city, and no tile changes player. Breaks if the founding
    claim takes enemy tiles, drops replacements, or steals own-city tiles."""
    env = make_flat_env()
    enemy = env.create_city(env.players[1], (4, 4), "Enemy")
    own = env.create_city(env.players[0], (4, 8), "Own")
    enemy_before = _owned_by(env, enemy)
    own_before = _owned_by(env, own)

    # Placed between both, so ring 1 touches enemy and own territory.
    new = env.create_city(env.players[0], (4, 6), "New")
    assert _owned_by(env, enemy) == enemy_before
    assert _owned_by(env, own) == own_before
    new_tiles = _owned_by(env, new)
    blocked_by_enemy = [
        p for p in env.map.get_adjacent_coords((4, 6)) if p in enemy_before
    ]
    assert blocked_by_enemy
    outside_ring1 = {p for p in new_tiles if env.map.distance_function(p, (4, 6)) > 1}
    assert len(outside_ring1) == len(blocked_by_enemy)
    assert_territory_invariants(env)


# --- §2.3 capture -------------------------------------------------------------


def test_capture_transfers_exactly_the_citys_tiles_and_bumps_territory_epoch():
    """Property: capturing a city through `step` moves every tile it owns to
    the captor — the grid is unchanged, the counters move by exactly that
    many tiles, no other tile changes — and territory_epoch is bumped.
    Breaks if transfer is per-tile/incomplete or `set_owner` skips the
    territory hook."""
    env = make_flat_env()
    mine = env.found_city(env.players[0], (2, 2), "Mine")
    target = env.found_city(env.players[1], (4, 8), "Target")
    assert mine is not None and target is not None
    target.health = 0
    warrior = place(env, WarriorUnit, 0, (4, 7))
    place(env, WarriorUnit, 0, (0, 0))  # keeps the turn from rolling over
    env.current_player, env.current_player_index = env.players[0], 0

    grid_before = env.map.owner_city.copy()
    target_tiles = _owned_by(env, target)
    counts_before = [env.map.owned_tile_count(i) for i in range(2)]
    epoch_before = env.map.territory_epoch

    env.step([(4, 7, warrior.slot), (4, 8)])

    assert target.player is env.players[0]
    assert np.array_equal(env.map.owner_city, grid_before)
    assert _owned_by(env, target) == target_tiles
    assert env.map.owned_tile_count(0) == counts_before[0] + len(target_tiles)
    assert env.map.owned_tile_count(1) == counts_before[1] - len(target_tiles)
    assert env.map.territory_epoch > epoch_before
    assert_territory_invariants(env)


# --- §5 swap ------------------------------------------------------------------


def _two_own_cities():
    env = make_flat_env()
    a = env.create_city(env.players[0], (4, 4), "A")
    b = env.create_city(env.players[0], (4, 8), "B")
    return env, a, b


def test_swap_moves_a_valid_tile_and_both_cities_reassign():
    """Property: a tile owned by A, two or more steps from A's centre and
    within B's work radius, swaps to B. Breaks if swap validity drifts from
    §5 towards refusing legal swaps, or the transfer skips the mutation API."""
    env, a, b = _two_own_cities()
    pos = (4, 6)
    assert env.map.distance_function(pos, a.coordinates) >= 2
    assert env.map.distance_function(pos, b.coordinates) <= WORK_RADIUS
    env.map.claim(pos, a)
    assert env.swap_tile(pos, b) is True
    assert env.map.owner_id_at(pos) == b.city_id
    assert_territory_invariants(env)


def test_swap_refuses_centre_adjacent_out_of_radius_and_foreign_tiles():
    """Property (§5): swap refuses the owner's centre, a tile adjacent to the
    owner's centre, a tile outside the target's work radius, a tile of
    another player's city, and a swap to the current owner. Breaks if swap
    validity checks drift from §5."""
    env, a, b = _two_own_cities()
    adjacent = (4, 5)  # adjacent to A, within B's radius
    assert env.map.owner_id_at(adjacent) == a.city_id
    assert env.map.distance_function(adjacent, b.coordinates) <= WORK_RADIUS
    assert env.swap_tile(adjacent, b) is False
    assert env.swap_tile(a.coordinates, b) is False

    far = (4, 1)  # A's, not adjacent to A, beyond B's radius
    env.map.claim(far, a)
    assert env.map.distance_function(far, b.coordinates) > WORK_RADIUS
    assert env.swap_tile(far, b) is False

    near_b = (4, 6)
    env.map.claim(near_b, a)
    assert env.swap_tile(near_b, a) is False  # already A's
    enemy = env.create_city(env.players[1], (1, 12), "Enemy")
    assert env.swap_tile(near_b, enemy) is False

    assert env.map.owner_id_at(adjacent) == a.city_id
    assert env.map.owner_id_at(far) == a.city_id
    assert env.map.owner_id_at(near_b) == a.city_id


# --- §4 ownership filter in assign_tiles --------------------------------------


def test_city_works_only_tiles_it_owns():
    """Property: every worked tile is owned by the working city, even when an
    earlier city holds part of its ring 1 and it has citizens to spare.
    Breaks if `assign_tiles` ignores ownership."""
    env = make_flat_env()
    earlier = env.create_city(env.players[1], (4, 4), "Earlier")
    later = env.create_city(env.players[0], (4, 6), "Later")  # painted-style, too close
    for city in (earlier, later):
        city.population = 6
        city.assign_tiles(env)
        assert city.worked_tiles
        for pos in city.worked_tiles:
            assert env.map.owner_id_at(pos) == city.city_id, (city.name, pos)
    lost = [p for p in env.map.get_adjacent_coords((4, 6)) if env.map.owner_id_at(p) == earlier.city_id]
    assert lost and not set(lost) & set(later.worked_tiles)


# --- §2.2 founding restriction and the settle layer ---------------------------


def _far_tile_claimed_by(env, city, pos):
    """Give `city` a tile far from every city, through the mutation API."""
    for player in env.players:
        for other in player.cities:
            assert env.map.distance_function(pos, other.coordinates) >= 4
    env.map.claim(pos, city)


def test_founding_refused_on_another_players_tile_allowed_on_own():
    """Property (§2.2): `can_found_city_at` refuses a tile owned by another
    player and allows one the founder owns; founding there moves the tile
    to the new city. Breaks if the ownership condition is missing or
    inverted, or founding on own territory leaves the tile with the old city."""
    env = make_flat_env()
    theirs = env.found_city(env.players[1], (1, 2), "Theirs")
    env.found_city(env.players[0], (6, 12), "Mine")
    pos = (5, 6)
    _far_tile_claimed_by(env, theirs, pos)

    assert env.can_found_city_at(pos, env.players[0]) is False
    assert env.found_city(env.players[0], pos, "Refused") is None
    assert env.can_found_city_at(pos, env.players[1]) is True
    new = env.found_city(env.players[1], pos, "Allowed")
    assert new is not None
    assert env.map.owner_id_at(pos) == new.city_id
    assert pos not in _owned_by(env, theirs)
    assert_territory_invariants(env)


def test_settle_layer_agrees_with_mask_per_player_after_ownership_change():
    """Property: after an ownership change, each player's settle layer equals
    `can_found_city_at(·, that player)` everywhere, and a Settler's own-tile
    mask entry agrees with it. Breaks if the settle cache misses
    territory_epoch or the player index."""
    env = make_flat_env()
    theirs = env.found_city(env.players[1], (1, 2), "Theirs")
    env.found_city(env.players[0], (6, 12), "Mine")
    encoder = get_encoder("settle", fog_of_war=False)
    for i in range(2):
        encoder.encode(env, i)  # warm the cache before the change

    pos = (5, 6)
    _far_tile_claimed_by(env, theirs, pos)

    settle_ch = encoder.get_depth(2) - 1
    for i, player in enumerate(env.players):
        layer = encoder.encode(env, i).numpy()[settle_ch]
        for r in range(env.n):
            for c in range(env.m):
                assert bool(layer[r, c]) == env.can_found_city_at((r, c), player), (i, r, c)
    assert encoder.encode(env, 0).numpy()[settle_ch][pos] == 0
    assert encoder.encode(env, 1).numpy()[settle_ch][pos] == 1

    state = torch.zeros(3, env.n, env.m)
    for i in range(2):
        settler = place(env, SettlerUnit, i, pos)
        env.current_player, env.current_player_index = env.players[i], i
        select = (pos[0] * env.m + pos[1]) * NUM_UNIT_SLOTS + settler.slot
        mask = get_valid_moves_mask(state, select, env).reshape(env.n, env.m)
        layer = encoder.encode(env, i).numpy()[settle_ch]
        assert bool(mask[pos]) == bool(layer[pos]), i
        env.delete_unit(settler)


# --- epochs -------------------------------------------------------------------


def test_ownership_changes_never_bump_terrain_epoch():
    """Property: founding, claim, swap, capture and removal bump
    territory_epoch and leave terrain_epoch alone. Breaks if ownership is
    wired into the terrain cache key."""
    env, a, b = _two_own_cities()
    terrain_epoch = env.map.terrain_epoch
    territory_epoch = env.map.territory_epoch

    env.map.claim((4, 6), a)
    env.swap_tile((4, 6), b)
    enemy = env.create_city(env.players[1], (1, 12), "Enemy")
    enemy.set_owner(env.players[0])
    env.remove_city(b)

    assert env.map.terrain_epoch == terrain_epoch
    assert env.map.territory_epoch > territory_epoch


# --- determinism ----------------------------------------------------------------


def _digest(env):
    """Terrain layers, cities, units and the next RNG draw after reset, as one
    hash — computed with the same function on the pre-#87-P2 code."""
    terrain = [
        [str(getattr(env.map.tiles[i, j], a)) for a in ("base_terrain", "relief", "feature", "resource")]
        for i in range(env.n) for j in range(env.m)
    ]
    cities = sorted(
        [int(p.player_index), int(c.coordinates[0]), int(c.coordinates[1])]
        for p in env.players for c in p.cities
    )
    units = sorted(
        [int(p.player_index), u.unit_type, int(u.coordinates[0]), int(u.coordinates[1])]
        for p in env.players for u in p.units
    )
    blob = json.dumps([terrain, cities, units, int(env.rng.next_uint64())])
    return hashlib.sha256(blob.encode()).hexdigest()


# Recorded on develop at 7e4fa79 (before ownership existed), under the PCG32
# stream. Re-baselined at the v0.9.0 Q0 migration (#128, philox32): every
# digest includes the world and the next RNG draw, both of which the stream
# change moves by design. The "no draw, no world change from borders"
# property they protected is kept stream-independent by
# `test_world_fingerprint_equals_a_reset_without_founding_claims` below.
_PRE_BORDERS_DIGESTS = [
    (dict(n=8, m=16, num_players=2, map_type="basic"), 123,
     "5c16cd0ab7648505c373775f1d90ec0e32e23f6115a213bf21e4914a325b176b"),
    (dict(n=8, m=16, num_players=2, map_type="basic"), 7,
     "ff969a89d102c6b5f843bf0cd60383fc42aacf3526b62f6ebe2890ba9cba5ee0"),
    (dict(size="duel", map_type="earthlike"), 4242,
     "2d37c8ef83d9000b21251e1a6977ec6e2904ecd2be51df64d583ef7b914694f0"),
]


@pytest.mark.parametrize("kwargs,seed,expected", _PRE_BORDERS_DIGESTS)
def test_world_fingerprint_at_reset_is_unchanged_by_borders(kwargs, seed, expected):
    """Property (§2.1): founding claims at reset draw no RNG, so the world
    and the RNG stream after reset are what they were before ownership
    existed. Breaks if reset-time claims consume `PortableRNG`."""
    assert _digest(GameEnvironment(**kwargs).reset(seed=seed)) == expected


@pytest.mark.parametrize("kwargs,seed,expected", _PRE_BORDERS_DIGESTS)
def test_world_fingerprint_equals_a_reset_without_founding_claims(
        kwargs, seed, expected, monkeypatch):
    """Property (§2.1), independent of which RNG stream is in force: a reset
    with founding claims produces the same terrain, cities, units and next RNG
    draw as a reset where no founding claim is ever made (ownership absent).
    Breaks if reset-time claims consume the engine RNG or change what is built."""
    with_claims = _digest(GameEnvironment(**kwargs).reset(seed=seed))
    monkeypatch.setattr(GameEnvironment, "_founding_claim",
                        lambda self, city: set())
    without_claims = _digest(GameEnvironment(**kwargs).reset(seed=seed))
    assert with_claims == without_claims


def test_founding_claims_at_reset_draw_no_rng(monkeypatch):
    """Property: the RNG state is identical before and after every founding
    claim made during reset. Breaks if reset-time claims consume
    `PortableRNG` (e.g. a tiebreak on non-overlapping rings)."""
    original = GameEnvironment._founding_claim
    calls = []

    def spy(self, city):
        before = dict(self.rng.__dict__)
        result = original(self, city)
        calls.append(before == dict(self.rng.__dict__))
        return result

    monkeypatch.setattr(GameEnvironment, "_founding_claim", spy)
    GameEnvironment(size="duel", map_type="earthlike").reset(seed=4242)
    assert calls and all(calls)


def _contested_play(seed):
    env = GameEnvironment(8, 16, num_players=2, map_type="basic")
    env.reset(seed=seed)
    env.reset(seed=seed)  # ids restart in every reset attempt
    # Painted-style cities right against the capitals force replacement
    # claims, which exercise the RNG tiebreak.
    for player in env.players:
        capital = player.cities[0].coordinates
        for other in env.players:
            if other is player:
                continue
            for pos in env.map.get_ring_coords(capital, 2)[2]:
                tile = env.map.get_tile(pos)
                if tile.city is None and env.map.owner_id_at(pos) in (NEUTRAL,):
                    env.create_city(other, pos, "Painted")
                    break
    return env


def test_same_seed_gives_identical_ownership_grid_and_ids_in_one_process():
    """Property: two environments in one process, same seed and same
    actions, produce identical ownership grids, city ids and counters.
    Breaks if city ids are process-global, the counter is not reset per
    reset attempt, or the tiebreak uses anything but `PortableRNG`."""
    env1 = _contested_play(31)
    env2 = _contested_play(31)
    assert np.array_equal(env1.map.owner_city, env2.map.owner_city)
    assert sorted(env1.city_by_id) == sorted(env2.city_by_id)
    for city_id, city in env1.city_by_id.items():
        assert env2.city_by_id[city_id].coordinates == city.coordinates
    for i in range(2):
        assert env1.map.owned_tile_count(i) == env2.map.owned_tile_count(i)
    assert_territory_invariants(env1)
