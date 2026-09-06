"""Issue #84: an order aimed at an enemy city attacks the city.

Before this, `GameEnvironment.step` only recognised an enemy *unit* on the
ordered tile; an order aimed at an undefended enemy city fell through to
movement and the city changed hands by occupation. `City.health` could
therefore never be reduced in a live game, which made Walls (#7) and the
siege class (#66) inert.

This file pins the combat half of the rule end to end, through
`GameEnvironment.step` — the order an agent or the human tool actually
issues, not a direct `Unit.attack` call.
"""

import numpy as np
import pytest

from civulator.game.unit import (
    ArcherUnit, CatapultUnit, SettlerUnit, SlingerUnit, SwordsmanUnit, WarriorUnit,
)

from test_combat_range import make_flat_env, place


def make_env():
    """Flat board, player 0 to move, no cities except the ones a test places."""
    env = make_flat_env()
    env.current_player = env.players[0]
    env.current_player_index = 0
    return env


def enemy_city(env, coords=(4, 8), walls=False):
    city = env.found_city(env.players[1], coords, "Target")
    assert city is not None, "fixture: the city must actually be founded"
    if walls:
        city.buildings.append("Walls")
    return city


def home_city(env, coords=(0, 0)):
    """A city for player 0. Without one, `Player.end_turn` declares player 0
    dead the moment the turn rolls over and the game ends — which any test
    that issues more than one order needs to avoid."""
    city = env.found_city(env.players[0], coords, "Home")
    assert city is not None, "fixture: the home city must actually be founded"
    return city


def order(env, unit, target):
    """Issue one (select, order) pair exactly as an agent would."""
    r, c = unit.coordinates
    action = [np.array([r, c, unit.slot]), np.array(list(target))]
    return env.step(action)


# --- The rule: a city takes damage ------------------------------------------

@pytest.mark.parametrize(
    "attacker_cls", [WarriorUnit, SwordsmanUnit, SlingerUnit, ArcherUnit, CatapultUnit]
)
def test_an_order_aimed_at_an_enemy_city_damages_it(attacker_cls):
    env = make_env()
    city = enemy_city(env, (4, 8))
    attacker = place(env, attacker_cls, 0, (4, 7))

    order(env, attacker, (4, 8))

    assert city.health < 200, (
        f"{attacker_cls.__name__} ordered onto an enemy city left its health "
        "untouched — the order did not reach the combat path (#84)"
    )
    assert city.player is env.players[1], "damage must not transfer ownership"


def test_the_city_stays_on_the_board_and_its_health_floors_at_zero():
    """A city is never destroyed: repeated attacks drive it to exactly 0 and
    it keeps standing, waiting to be occupied."""
    env = make_env()
    home_city(env)
    city = enemy_city(env, (4, 8))
    attacker = place(env, CatapultUnit, 0, (4, 6))

    for _ in range(40):
        # step() auto-advances the turn once every unit is spent; put player 0
        # back on the clock and give the Catapult its movement back so the
        # loop keeps bombarding the same city.
        env.current_player = env.players[0]
        env.current_player_index = 0
        attacker.movement_points = attacker.get_max_movement()
        order(env, attacker, (4, 8))
        if city.health == 0:
            break

    assert city.health == 0, f"city bottomed out at {city.health}, expected exactly 0"
    assert city in env.players[1].cities
    assert env.map.get_tile((4, 8)).city is city


def test_a_garrison_is_fought_before_the_city():
    """Unchanged behaviour: a defender in the city absorbs the order."""
    env = make_env()
    city = enemy_city(env, (4, 8))
    garrison = place(env, WarriorUnit, 1, (4, 8))
    attacker = place(env, WarriorUnit, 0, (4, 7))

    order(env, attacker, (4, 8))

    assert garrison.health < 100, "the garrison must take the hit"
    assert city.health == 200, "the city must be untouched while a garrison stands"


# --- The rule: ranged bombard takes no counterattack ------------------------

@pytest.mark.parametrize("attacker_cls", [SlingerUnit, ArcherUnit, CatapultUnit])
def test_a_ranged_bombard_takes_no_counterattack(attacker_cls):
    """This is what makes siege the safe way to reduce a city (#84)."""
    env = make_env()
    city = enemy_city(env, (4, 8), walls=True)
    attacker = place(env, attacker_cls, 0, (4, 7))

    order(env, attacker, (4, 8))

    assert city.health < 200, "fixture: the bombard must have landed"
    assert attacker.health == 100, (
        f"{attacker_cls.__name__} took {100 - attacker.health:.1f} damage "
        "bombarding a city — ranged attacks are answered by nothing"
    )


@pytest.mark.parametrize("attacker_cls", [WarriorUnit, SwordsmanUnit])
def test_a_melee_attack_takes_the_city_counterattack(attacker_cls):
    env = make_env()
    city = enemy_city(env, (4, 8), walls=True)
    attacker = place(env, attacker_cls, 0, (4, 7))

    order(env, attacker, (4, 8))

    assert attacker.health < 100, (
        "a melee attacker must take the city's counterattack — that is the "
        "whole reason siege units exist"
    )


def test_a_walled_city_hits_back_harder_through_the_order_path():
    """#7's walls reach the counterattack when the attack comes from an
    order, not only from a direct Unit.attack call."""
    class FixedRoll:
        def uniform(self, lo, hi):
            return 1.0

    env = make_env()
    env.rng = FixedRoll()
    bare = enemy_city(env, (2, 2), walls=False)
    walled = enemy_city(env, (6, 12), walls=True)
    a = place(env, WarriorUnit, 0, (2, 3))
    b = place(env, WarriorUnit, 0, (6, 13))

    order(env, a, (2, 2))
    env.current_player = env.players[0]
    env.current_player_index = 0
    order(env, b, (6, 12))

    assert walled.health > bare.health, "walls must absorb damage"
    assert b.health < a.health, "walls must make the counterattack hurt more"


# --- Bookkeeping ------------------------------------------------------------

def test_damage_to_a_city_is_recorded_in_the_episode_stats():
    env = make_env()
    city = enemy_city(env, (4, 8))
    attacker = place(env, ArcherUnit, 0, (4, 7))

    order(env, attacker, (4, 8))

    dealt = env.episode_stats[0]["damage_dealt"]
    assert dealt == pytest.approx(200 - city.health), (
        "the attacker's episode stats must carry the damage put on the city"
    )


def test_attacking_a_city_spends_the_attacker_s_movement():
    env = make_env()
    enemy_city(env, (4, 8))
    attacker = place(env, WarriorUnit, 0, (4, 7))

    order(env, attacker, (4, 8))

    assert attacker.movement_points == 0


def test_a_melee_attacker_does_not_move_onto_the_city_tile():
    env = make_env()
    enemy_city(env, (4, 8))
    attacker = place(env, WarriorUnit, 0, (4, 7))

    order(env, attacker, (4, 8))

    assert attacker.coordinates == (4, 7), (
        "attacking is not entering — the city tile is taken by occupation, "
        "in a separate order, once its health is 0"
    )


def test_a_civilian_ordered_onto_an_enemy_city_does_not_walk_in():
    """A Settler has combat strength 0; ordering it at a standing enemy city
    must not hand it the city."""
    env = make_env()
    city = enemy_city(env, (4, 8))
    settler = place(env, SettlerUnit, 0, (4, 7))

    order(env, settler, (4, 8))

    assert city.player is env.players[1]
    assert settler.coordinates == (4, 7)
