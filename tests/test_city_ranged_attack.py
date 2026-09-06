"""Issue #84: a city with Walls shoots back.

Civ 6, City combat: "once a city has walls, it can make ranged attacks
against enemy units using a City Ranged Strength stat". A garrison alone is
not enough - that is the whole rule, and it is the second reason to build
Walls.

The strike fires automatically at the start of its owner's turn rather than
as an order, because the action space selects units and naming a city would
change it (see GameEnvironment.city_ranged_attack). These tests drive it
both ways: directly, and through a real turn rollover.
"""

import pytest

from civulator import unit_model
from civulator.game.unit import WarriorUnit

from test_combat_range import make_flat_env, place
from test_city_combat import make_env


def walled_city(env, coords=(4, 8), player_index=0, walls=True):
    city = env.found_city(env.players[player_index], coords, "Fortress")
    assert city is not None, "fixture: the city must actually be founded"
    if walls:
        city.buildings.append("Walls")
    return city


# --- The rule: only a walled city shoots ------------------------------------

def test_a_walled_city_damages_an_enemy_unit_in_range():
    env = make_env()
    city = walled_city(env)
    victim = place(env, WarriorUnit, 1, (4, 9))

    shot = env.city_ranged_attack(city)

    assert shot is victim
    assert victim.health < 100, "a walled city must actually hurt the target"


def test_an_unwalled_city_does_not_shoot():
    """The gate. A garrison changes nothing - only Walls unlock the strike."""
    env = make_env()
    city = walled_city(env, walls=False)
    place(env, WarriorUnit, 0, city.coordinates)  # a garrison, not walls
    victim = place(env, WarriorUnit, 1, (4, 9))

    assert env.city_ranged_attack(city) is None
    assert victim.health == 100


def test_the_unlocking_building_is_a_config_value():
    """CLAUDE.md: all gameplay constants live in config.toml."""
    from civulator.config import CFG

    assert CFG["city"]["ranged_building"] == "Walls"
    assert CFG["city"]["ranged_building"] in CFG["buildings"]
    assert unit_model.CITY_RANGED_BUILDING == "Walls"


def test_the_strength_and_range_are_config_values():
    from civulator.config import CFG

    env = make_env()
    city = walled_city(env)
    assert city.get_ranged_strength() == CFG["city"]["ranged_strength"]
    assert city.get_range() == CFG["city"]["ranged_range"]
    assert city.get_range() == 2, "Civ 6: the city ranged strike has Range 2"


# --- Range and line of sight ------------------------------------------------

def test_a_unit_beyond_the_city_range_is_safe():
    env = make_env()
    city = walled_city(env)
    far = place(env, WarriorUnit, 1, (4, 11))  # hex distance 3, range is 2

    assert env.map.distance_function(city.coordinates, far.coordinates) == 3
    assert env.city_ranged_attack(city) is None
    assert far.health == 100


def test_a_unit_at_the_edge_of_range_is_hit():
    env = make_env()
    city = walled_city(env)
    victim = place(env, WarriorUnit, 1, (4, 10))

    assert env.map.distance_function(city.coordinates, victim.coordinates) == 2
    assert env.city_ranged_attack(city) is victim
    assert victim.health < 100


def test_the_strike_respects_line_of_sight():
    """Civ 6's city strike, unlike Civ 5's, obeys line of sight."""
    env = make_env()
    city = walled_city(env)
    # A mountain on the intervening tile blocks sight to the far target.
    env.map.tiles[4, 9].set_layers("Plains", relief="mountain", map_ref=env.map)
    hidden = place(env, WarriorUnit, 1, (4, 10))

    assert not env.check_line_of_sight(city.coordinates, hidden.coordinates), (
        "fixture: the mountain must actually block sight"
    )
    assert env.city_ranged_attack(city) is None
    assert hidden.health == 100


def test_own_units_are_never_shot():
    env = make_env()
    city = walled_city(env)
    friend = place(env, WarriorUnit, 0, (4, 9))

    assert env.city_ranged_attack(city) is None
    assert friend.health == 100


# --- The strike takes no counterattack, and can kill ------------------------

def test_the_city_takes_nothing_back():
    env = make_env()
    city = walled_city(env)
    place(env, WarriorUnit, 1, (4, 9))

    env.city_ranged_attack(city)

    assert city.health == 200, "a ranged strike is answered by nothing (#84)"


def test_a_killed_unit_leaves_the_board_and_the_books_balance():
    env = make_env()
    city = walled_city(env)
    victim = place(env, WarriorUnit, 1, (4, 9))
    victim.health = 1

    env.city_ranged_attack(city)

    assert victim not in env.players[1].units
    assert env.map.get_tile((4, 9)).units == []
    assert env.episode_stats[0]["kills"] == 1
    assert env.episode_stats[1]["losses"] == 1
    assert env.episode_stats[0]["damage_dealt"] > 0


def test_the_weakest_target_in_reach_is_chosen():
    env = make_env()
    city = walled_city(env)
    healthy = place(env, WarriorUnit, 1, (4, 9))
    wounded = place(env, WarriorUnit, 1, (4, 7))
    wounded.health = 20

    assert env.city_ranged_attack(city) is wounded
    assert healthy.health == 100


def test_a_city_reduced_to_zero_stops_shooting():
    env = make_env()
    city = walled_city(env)
    city.health = 0
    victim = place(env, WarriorUnit, 1, (4, 9))

    assert env.city_ranged_attack(city) is None
    assert victim.health == 100


# --- End to end, through a real turn ----------------------------------------

def test_the_city_fires_when_its_owner_s_turn_begins():
    env = make_flat_env()
    city = env.found_city(env.players[0], (4, 8), "Fortress")
    assert city is not None
    city.buildings.append("Walls")
    besieger = place(env, WarriorUnit, 1, (4, 9))

    env.players[0].start_turn()

    assert besieger.health < 100, (
        "a walled city must fire on its owner's turn without anyone ordering it"
    )
