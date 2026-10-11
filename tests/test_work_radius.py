"""Work radius and episode stats (issue #87 P4, spec docs/borders_culture_design.md §4, §7, §8).

Every test names the property it protects and the change that must break it.
"""

import pytest

from civulator.game import territory
from civulator.game.environment import GameEnvironment
from civulator.game.territory import NEUTRAL

from test_combat_range import make_flat_env


def _desert_env():
    """Flat board of Desert (0 food, 0 production) so only tiles a test
    upgrades have a yield worth choosing."""
    env = make_flat_env()
    for row in env.map.tiles:
        for tile in row:
            tile.set_layers("Desert", map_ref=env.map)
    return env


def _set(env, pos, base):
    env.map.tiles[pos].set_layers(base, map_ref=env.map)


def _city_with_pop(env, pos, pop):
    city = env.create_city(env.players[0], pos, "C")
    city.population = pop
    return city


def _ring_tile(env, city, distance, skip=()):
    """A tile at exactly `distance` from the city, in canonical order."""
    rings = env.map.get_ring_coords(city.coordinates, distance)
    return next(pos for pos in rings[distance] if pos not in skip)


def test_city_prefers_owned_far_tile_over_ring_one():
    """Property: a city works the best owned tile within work_radius, not the
    best ring-1 tile. An owned Grassland (2 food) at distance 3 beats an owned
    Plains (1/1) in ring 1 for a one-pop city. Breaks if assign_tiles reads
    only ring 1."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 1)
    near = _ring_tile(env, city, 1)
    far = _ring_tile(env, city, 3)
    _set(env, near, "Plains")
    _set(env, far, "Grassland")
    env.map.claim(far, city)
    city.assign_tiles(env)
    assert city.worked_tiles == [far]


def test_city_never_works_unowned_tiles_even_in_radius():
    """Property: neutral and enemy-owned tiles are never worked, however good.
    Breaks if assign_tiles ignores ownership."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 3)
    other = env.create_city(env.players[1], (4, 2), "Other")
    neutral = _ring_tile(env, city, 2)
    enemy = _ring_tile(env, city, 2, skip=(neutral,))
    for pos in (neutral, enemy):
        _set(env, pos, "Grassland")
    env.map.claim(enemy, other)
    city.assign_tiles(env)
    assert neutral not in city.worked_tiles
    assert enemy not in city.worked_tiles
    assert env.map.owner_id_at(neutral) == NEUTRAL


def test_city_never_works_owned_tile_beyond_radius():
    """Property: an owned tile farther than work_radius is not worked. Breaks
    if the radius is dropped or exceeded."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 1)
    beyond = _ring_tile(env, city, territory.WORK_RADIUS + 1)
    _set(env, beyond, "Grassland")
    env.map.claim(beyond, city)
    city.assign_tiles(env)
    assert beyond not in city.worked_tiles


def test_centre_is_never_a_worked_candidate():
    """Property: the centre is worked free and never consumes a citizen.
    Breaks if ring 0 enters the candidate list."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 4)
    city.assign_tiles(env)
    assert city.coordinates not in city.worked_tiles
    assert len(city.worked_tiles) == len(set(city.worked_tiles))


def test_work_radius_config_changes_eligible_tiles(monkeypatch):
    """Property: `[territory] work_radius` decides eligibility. A distance-3
    tile is worked at radius 3 and not at radius 2. Breaks if the radius is
    hardcoded or cached outside the live config value."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 1)
    far = _ring_tile(env, city, 3)
    _set(env, far, "Grassland")
    env.map.claim(far, city)

    monkeypatch.setattr(territory, "WORK_RADIUS", 3)
    city.assign_tiles(env)
    assert far in city.worked_tiles

    monkeypatch.setattr(territory, "WORK_RADIUS", 2)
    city.assign_tiles(env)
    assert far not in city.worked_tiles


def test_equal_yield_ties_are_deterministic_and_nearest_first():
    """Property: equal-yield tiles are chosen in a fixed order (nearer ring
    first, then (row, col)) independent of claim order. Breaks if the choice
    depends on set/dict iteration or claim history."""
    def worked_with(claim_order):
        env = _desert_env()
        city = _city_with_pop(env, (4, 8), 2)
        ring2 = env.map.get_ring_coords(city.coordinates, 2)[2][:4]
        for pos in ring2:
            _set(env, pos, "Plains")
        for pos in claim_order(ring2):
            env.map.claim(pos, city)
        # Make one ring-1 tile equally good: it must come first (nearer).
        near = env.map.get_ring_coords(city.coordinates, 1)[1][0]
        _set(env, near, "Plains")
        city.assign_tiles(env)
        return city.worked_tiles, near, sorted(ring2)

    forward, near, ring2_sorted = worked_with(lambda t: list(t))
    backward, _, _ = worked_with(lambda t: list(reversed(t)))
    assert forward == backward
    assert forward[0] == near
    assert forward[1] == ring2_sorted[0]


def test_tiles_owned_stat_tracks_the_grid():
    """Property: the snapshot's `tiles_owned` equals the number of grid cells
    held by that player's cities, and moves when ownership moves. Breaks if
    the stat is a stale counter instead of read from the ownership grid."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 1)
    before = env.episode_stats_snapshot(0)["tiles_owned"]
    assert before == int((env.map.owner_city == city.city_id).sum())
    assert env.episode_stats_snapshot(1)["tiles_owned"] == 0
    pos = _ring_tile(env, city, 3)
    env.map.claim(pos, city)
    assert env.episode_stats_snapshot(0)["tiles_owned"] == before + 1


def test_culture_produced_stat_accrues_and_resets():
    """Property: `culture_produced` (int tenths) rises with each city's
    accrual and is cleared by reset. Breaks if accrual bypasses the stat or
    reset reuses the old dict."""
    env = _desert_env()
    city = _city_with_pop(env, (4, 8), 1)
    assert env.episode_stats[0]["culture_produced"] == 0
    city.process_turn(env)
    produced = env.episode_stats[0]["culture_produced"]
    assert isinstance(produced, int) and produced > 0
    assert produced == city.culture_this_round
    env.reset(seed=1)
    assert env.episode_stats[0]["culture_produced"] == 0
    assert "tiles_claimed_by_culture" in env.episode_stats[0]
