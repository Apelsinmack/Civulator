"""Issue #84: a city is captured by occupying it once its health is 0.

The old rule was "walk onto the tile". That is what made a city's defence
irrelevant: no amount of Walls could stop an occupation. Capture now has two
conditions - the city must be at 0 health, and the unit moving in must be
able to hold it (a melee-capable land unit; a ranged unit bombards but never
owns).

Both conditions are engine preconditions, so both are also mask conditions:
an order the engine refuses consumes nothing and changes nothing, and a
greedy policy repeats it until the step guard (#51). Every rule below is
therefore asserted twice - once on the engine, once on the mask.
"""

import torch

from civulator.agents.networks import get_valid_moves_mask
from civulator.game.unit import (
    NUM_UNIT_SLOTS, ArcherUnit, CatapultUnit, SettlerUnit, SlingerUnit, WarriorUnit,
)

from test_combat_range import make_flat_env, place
from test_city_combat import enemy_city, home_city, make_env, order


def move_mask(env, unit):
    state = torch.zeros(3, env.n, env.m)
    r, c = unit.coordinates
    sel = (r * env.m + c) * NUM_UNIT_SLOTS + unit.slot
    return get_valid_moves_mask(state, sel, env).reshape(env.n, env.m)


# --- Capture is blocked while the city stands -------------------------------

def test_a_full_health_city_is_not_captured_by_moving_in():
    env = make_env()
    city = enemy_city(env, (4, 8))
    raider = place(env, WarriorUnit, 0, (4, 7))

    order(env, raider, (4, 8))

    assert city.player is env.players[1], "a standing city cannot be walked into"
    assert raider.coordinates == (4, 7)


def test_one_hit_point_still_holds_the_gate():
    """The boundary: capture needs health at 0, not merely low."""
    env = make_env()
    city = enemy_city(env, (4, 8))
    city.health = 1
    raider = place(env, WarriorUnit, 0, (4, 7))

    order(env, raider, (4, 8))

    assert city.player is env.players[1]
    assert city.health == 0, "the order resolved as an attack, and finished the job"


def test_killing_the_garrison_does_not_hand_over_a_standing_city():
    """The melee move-in inside `_execute_attack` bypasses `Unit.move`, so it
    carries its own copy of the gate. Without it, killing the defender of a
    full-health city would still capture it by the old rule."""
    env = make_env()
    city = enemy_city(env, (4, 8))
    garrison = place(env, WarriorUnit, 1, (4, 8))
    garrison.health = 1
    raider = place(env, WarriorUnit, 0, (4, 7))

    order(env, raider, (4, 8))

    assert garrison not in env.players[1].units, "fixture: the garrison must die"
    assert city.player is env.players[1], "the city itself is still standing"
    assert raider.coordinates == (4, 7), "the attacker must not enter the city"


def test_a_dead_city_is_taken_by_the_garrison_killer_moving_in():
    """Same shape, city already at 0: the melee move-in does capture."""
    env = make_env()
    city = enemy_city(env, (4, 8))
    city.health = 0
    garrison = place(env, WarriorUnit, 1, (4, 8))
    garrison.health = 1
    raider = place(env, WarriorUnit, 0, (4, 7))

    order(env, raider, (4, 8))

    assert city.player is env.players[0]
    assert raider.coordinates == (4, 8)


# --- Capture is allowed at 0 ------------------------------------------------

def test_a_city_at_zero_health_is_captured_by_moving_in():
    env = make_env()
    city = enemy_city(env, (4, 8))
    city.health = 0
    raider = place(env, WarriorUnit, 0, (4, 7))

    order(env, raider, (4, 8))

    assert city.player is env.players[0], "a city at 0 health is taken by occupation"
    assert raider.coordinates == (4, 8)
    assert env.episode_stats[0]["cities_captured"] == 1


def test_bombard_to_zero_then_walk_in_end_to_end():
    """The whole rule as an end user sees it: a Catapult reduces the city, a
    Warrior takes it."""
    env = make_env()
    home_city(env)
    city = enemy_city(env, (4, 8))
    catapult = place(env, CatapultUnit, 0, (4, 6))
    warrior = place(env, WarriorUnit, 0, (4, 7))

    for _ in range(40):
        env.current_player = env.players[0]
        env.current_player_index = 0
        if city.health == 0:
            break
        catapult.movement_points = catapult.get_max_movement()
        order(env, catapult, (4, 8))

    assert city.health == 0, "fixture: the bombard must finish the city"
    assert city.player is env.players[1], "bombarding alone must never capture"

    env.current_player = env.players[0]
    env.current_player_index = 0
    warrior.movement_points = warrior.get_max_movement()
    order(env, warrior, (4, 8))

    assert city.player is env.players[0]


# --- Only a melee land unit may capture -------------------------------------

def test_a_ranged_unit_cannot_capture_a_city_at_zero_health():
    for cls in (SlingerUnit, ArcherUnit, CatapultUnit):
        env = make_env()
        city = enemy_city(env, (4, 8))
        city.health = 0
        shooter = place(env, cls, 0, (4, 7))

        order(env, shooter, (4, 8))

        assert city.player is env.players[1], f"{cls.__name__} captured a city"
        assert shooter.coordinates == (4, 7), (
            f"{cls.__name__} entered a city it cannot own - it must not even "
            "stand there"
        )


def test_a_civilian_cannot_capture_a_city_at_zero_health():
    env = make_env()
    city = enemy_city(env, (4, 8))
    city.health = 0
    settler = place(env, SettlerUnit, 0, (4, 7))

    order(env, settler, (4, 8))

    assert city.player is env.players[1]
    assert settler.coordinates == (4, 7)


def test_can_capture_city_is_the_one_predicate():
    env = make_env()
    assert place(env, WarriorUnit, 0, (1, 1)).can_capture_city()
    assert not place(env, ArcherUnit, 0, (1, 2)).can_capture_city()
    assert not place(env, CatapultUnit, 0, (1, 3)).can_capture_city()
    assert not place(env, SettlerUnit, 0, (1, 4)).can_capture_city()


# --- A pathfinder walk cannot slip past the gate ----------------------------

def test_a_multi_step_walk_cannot_enter_a_standing_enemy_city():
    """`Unit.move`'s pathfinder branch carries the same gate as its adjacent
    fast path, so a long move cannot end inside a city an adjacent order
    could not enter."""
    env = make_env()
    city = enemy_city(env, (4, 8))
    walker = place(env, WarriorUnit, 0, (4, 5))
    walker.movement_points = 10

    _moved, final = walker.move((4, 8), env)

    assert final != (4, 8), "a walk must not end inside a standing enemy city"
    assert city.player is env.players[1]


# --- The mask follows the engine, exactly -----------------------------------

def test_the_mask_offers_the_bombard_while_the_city_stands():
    env = make_env()
    enemy_city(env, (4, 8))
    raider = place(env, WarriorUnit, 0, (4, 7))

    assert move_mask(env, raider)[4, 8] == 1, (
        "attacking a standing city is legal and must be offered"
    )


def test_the_mask_offers_the_move_in_once_the_city_is_dead():
    env = make_env()
    city = enemy_city(env, (4, 8))
    raider = place(env, WarriorUnit, 0, (4, 7))
    assert move_mask(env, raider)[4, 8] == 1

    city.health = 0
    assert move_mask(env, raider)[4, 8] == 1, (
        "a city at 0 health is the one legal capture order"
    )


def test_the_mask_stops_offering_a_dead_city_to_a_unit_that_cannot_take_it():
    """The no-op the capture gate creates (#51): once health is 0, a ranged
    unit's order onto the city tile is refused by the engine and consumes
    nothing. It must not be offered."""
    for cls in (SlingerUnit, ArcherUnit, CatapultUnit, SettlerUnit):
        env = make_env()
        city = enemy_city(env, (4, 8))
        unit = place(env, cls, 0, (4, 7))
        city.health = 0

        assert move_mask(env, unit)[4, 8] == 0, (
            f"{cls.__name__} was offered a city tile it can neither attack "
            "(health is 0) nor enter - a guaranteed no-op"
        )


def test_the_mask_does_not_offer_a_capture_the_unit_cannot_pay_for():
    """A dead city on a hill the unit has no movement points left to climb is
    still an unpayable step, capture or not."""
    env = make_flat_env()
    env.current_player = env.players[0]
    env.current_player_index = 0
    env.map.tiles[4, 8].set_layers("Plains", relief="hills", map_ref=env.map)
    city = env.found_city(env.players[1], (4, 8), "Hilltop")
    assert city is not None
    city.health = 0
    raider = place(env, WarriorUnit, 0, (4, 7))
    raider.movement_points = 1  # a hill costs 2

    assert move_mask(env, raider)[4, 8] == 0
    moved, _ = raider.move((4, 8), env)
    assert not moved, "fixture: the engine must refuse the step too"
