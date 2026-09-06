"""Issue #84: cities repair 20 HP a turn unless they are under siege.

Without repair, walls only ever delay an attacker by a fixed amount. With
it, taking a city means putting enough damage on it faster than it heals -
or surrounding it so it cannot.

Civ 6's siege rule, verbatim: "The City Center ... [is] considered under
siege if all 6 tiles around them are occupied by enemy units, under enemy
Zone of Control, or are impassable due to mountains or Natural Wonders. In
these circumstances, the district will not recover lost health."

Zone of control did not exist in this engine before #84 and is added only in
the narrow form siege needs: a tile is under a player's ZoC when it is
adjacent to one of that player's land military units, and ZoC does not cross
a river. ZoC has NO movement effect here - that is a separate, much larger
rule and is deliberately out of scope.

The ring around a hex city, in HEX_DIRECTIONS order, is a cycle:

    A (5,8) - B (5,7) - C (4,7) - D (3,8) - E (3,9) - F (4,9) - back to A

A unit standing on a ring tile therefore covers three of the six: its own
(occupied) plus the two ring tiles beside it (ZoC). Three units on alternate
tiles cover all six; three bunched on one side cannot.
"""

import numpy as np
import pytest

from civulator import unit_model
from civulator.game.unit import (
    ArcherUnit, CatapultUnit, SettlerUnit, SlingerUnit, WarriorUnit, WorkerUnit,
)

from test_combat_range import make_flat_env, place

CITY = (4, 8)
RING_A, RING_B, RING_C = (5, 8), (5, 7), (4, 7)
RING_D, RING_E, RING_F = (3, 8), (3, 9), (4, 9)
RING = [RING_A, RING_B, RING_C, RING_D, RING_E, RING_F]


def besieged_fixture(positions, unit_cls=WarriorUnit):
    """Player 0's city at CITY, with player 1's units on `positions`."""
    env = make_flat_env()
    city = env.found_city(env.players[0], CITY, "Target")
    assert city is not None, "fixture: the city must actually be founded"
    for pos in positions:
        place(env, unit_cls, 1, pos)
    return env, city


def test_the_ring_is_the_cycle_the_tests_assume():
    """Guards the premise: RING is the city's six neighbours, in a cycle."""
    env = make_flat_env()
    assert set(env.map.get_adjacent_coords(CITY)) == set(RING)
    for i, pos in enumerate(RING):
        nxt = RING[(i + 1) % len(RING)]
        assert nxt in env.map.get_adjacent_coords(pos), (
            f"{pos} and {nxt} must be neighbours for the coverage argument"
        )


# --- Repair -----------------------------------------------------------------

def test_a_damaged_city_repairs_the_configured_amount_each_turn():
    env, city = besieged_fixture([])
    city.health = 100

    city.process_turn(env)

    assert city.health == 100 + unit_model.CITY_HEAL_PER_TURN


def test_the_repair_rate_is_a_config_value_and_is_twenty():
    from civulator.config import CFG

    assert CFG["city"]["heal_per_turn"] == 20, (
        "Civ 6: a city heals 20 HP per turn unless under siege"
    )
    assert unit_model.CITY_HEAL_PER_TURN == 20


def test_repair_stops_at_full_health():
    env, city = besieged_fixture([])
    city.health = unit_model.CITY_HEALTH - 5

    city.process_turn(env)

    assert city.health == unit_model.CITY_HEALTH


def test_an_undamaged_city_stays_at_full_health():
    env, city = besieged_fixture([])
    city.process_turn(env)
    assert city.health == unit_model.CITY_HEALTH


def test_a_besieged_city_does_not_repair():
    env, city = besieged_fixture([RING_A, RING_C, RING_E])
    city.health = 100

    assert env.is_city_under_siege(city), "fixture: the blockade must hold"
    city.process_turn(env)

    assert city.health == 100, "a besieged city must not recover a single point"


# --- The blockade: three spread units hold it, three bunched do not ---------

def test_three_well_spread_units_besiege_a_city():
    """Erik's sanity check, and the reason ZoC exists here at all: it must
    not take six units to blockade a six-tile ring."""
    env, city = besieged_fixture([RING_A, RING_C, RING_E])
    assert env.is_city_under_siege(city)


def test_three_units_bunched_on_one_side_do_not():
    """The other half of the same check - a blockade is a ring, not a mob."""
    env, city = besieged_fixture([RING_A, RING_B, RING_C])
    assert not env.is_city_under_siege(city), (
        "A, B and C cover F through D by occupation and ZoC; E is open"
    )


def test_two_adjacent_units_cannot_hold_the_ring():
    env, city = besieged_fixture([RING_A, RING_B])
    assert not env.is_city_under_siege(city)


def test_two_diametrically_opposite_units_do_hold_it():
    """Not a bug, and worth pinning because it is surprising: each unit
    covers three consecutive ring tiles, so two units exactly opposite each
    other cover all six. Three is what it takes when they are merely
    well-spread rather than perfectly placed."""
    env, city = besieged_fixture([RING_A, RING_D])
    assert env.is_city_under_siege(city)


def test_six_units_one_per_tile_besiege_it_by_occupation_alone():
    env, city = besieged_fixture(RING)
    assert env.is_city_under_siege(city)


def test_a_city_with_nobody_near_it_is_not_besieged():
    env, city = besieged_fixture([])
    assert not env.is_city_under_siege(city)


def test_the_owner_s_own_units_do_not_besiege_their_city():
    env = make_flat_env()
    city = env.found_city(env.players[0], CITY, "Target")
    for pos in RING:
        place(env, WarriorUnit, 0, pos)
    assert not env.is_city_under_siege(city)


# --- Impassable tiles count as held ----------------------------------------

def test_impassable_tiles_do_not_need_holding():
    """Civ 6 exempts mountains from the ring. Two units plus a mountain on
    the third arc is a siege."""
    env = make_flat_env()
    env.map.tiles[RING_E].set_layers("Plains", relief="mountain", map_ref=env.map)
    city = env.found_city(env.players[0], CITY, "Target")
    assert city is not None
    place(env, WarriorUnit, 1, RING_A)
    place(env, WarriorUnit, 1, RING_C)

    assert env.is_city_under_siege(city), (
        "A covers F/A/B, C covers B/C/D, and the mountain at E needs nobody"
    )


def test_a_city_ringed_by_impassable_terrain_alone_is_not_besieged():
    """The guard the Civ wording alone does not give: with no enemy anywhere,
    a city walled in by mountains would otherwise never heal again."""
    env = make_flat_env()
    for pos in RING:
        env.map.tiles[pos].set_layers("Plains", relief="mountain", map_ref=env.map)
    city = env.found_city(env.players[0], CITY, "Target")
    assert city is not None
    city.health = 100

    assert not env.is_city_under_siege(city)
    city.process_turn(env)
    assert city.health == 120, "a city besieged by nobody must keep repairing"


# --- Who projects zone of control ------------------------------------------

def test_a_land_military_unit_projects_zone_of_control():
    env = make_flat_env()
    place(env, WarriorUnit, 1, RING_C)
    assert env.tile_under_zone_of_control(CITY, env.players[1])
    assert env.tile_under_zone_of_control(RING_B, env.players[1])
    assert not env.tile_under_zone_of_control(RING_E, env.players[1])


@pytest.mark.parametrize("cls", [SlingerUnit, ArcherUnit, CatapultUnit])
def test_ranged_units_do_not_project_zone_of_control(cls):
    env = make_flat_env()
    shooter = place(env, cls, 1, RING_C)
    assert not shooter.projects_zone_of_control()
    assert not env.tile_under_zone_of_control(RING_B, env.players[1])


@pytest.mark.parametrize("cls", [SettlerUnit, WorkerUnit])
def test_civilians_do_not_project_zone_of_control(cls):
    env = make_flat_env()
    civilian = place(env, cls, 1, RING_C)
    assert not civilian.projects_zone_of_control()
    assert not env.tile_under_zone_of_control(RING_B, env.players[1])


def test_a_ranged_blockade_fails_where_a_melee_one_holds():
    """Three Archers stand on the same tiles that three Warriors besiege
    with; occupation still counts, but their ZoC does not, so the arcs
    between them stay open."""
    env, city = besieged_fixture([RING_A, RING_C, RING_E], unit_cls=ArcherUnit)
    assert not env.is_city_under_siege(city)


def test_the_ranged_zoc_rule_is_a_config_flag():
    from civulator.config import CFG

    assert CFG["combat"]["zone_of_control_from_ranged"] is False
    assert unit_model.ZOC_FROM_RANGED is False


# --- Zone of control does not cross a river ---------------------------------

def test_zone_of_control_does_not_cross_a_river():
    env = make_flat_env()
    place(env, WarriorUnit, 1, RING_C)
    assert env.tile_under_zone_of_control(CITY, env.players[1])

    env.map.add_river(RING_C, CITY)

    assert env.map.has_river_between(RING_C, CITY), "fixture: the river must exist"
    assert not env.tile_under_zone_of_control(CITY, env.players[1]), (
        "ZoC must not reach across a river edge (#84)"
    )


def test_a_river_can_break_an_otherwise_valid_blockade():
    """End to end: the same three spread units, but tile B is now reachable
    only across rivers, so the ring has a gap and the city keeps healing."""
    env, city = besieged_fixture([RING_A, RING_C, RING_E])
    assert env.is_city_under_siege(city), "fixture: the blockade holds first"

    # B is covered only by the ZoC of the units on A and C.
    env.map.add_river(RING_A, RING_B)
    env.map.add_river(RING_C, RING_B)

    assert not env.is_city_under_siege(city)
    city.health = 100
    city.process_turn(env)
    assert city.health == 120


def test_a_river_does_not_stop_a_unit_standing_on_the_tile_from_counting():
    """Occupation is not ZoC: a unit on a ring tile holds that tile whatever
    runs along its edges."""
    env, city = besieged_fixture(RING)
    for pos in RING:
        env.map.add_river(pos, CITY)
    assert env.is_city_under_siege(city)


# --- End to end: attack, then the defender's turn ---------------------------

def _attack_the_city(env, attacker):
    """Player 1 issues one order against the city at CITY."""
    env.current_player = env.players[1]
    env.current_player_index = 1
    r, c = attacker.coordinates
    env.step([np.array([r, c, attacker.slot]), np.array([CITY[0], CITY[1]])])


def test_a_damaged_city_repairs_when_its_owner_s_turn_comes_round():
    """The interaction that makes repair matter: hit a city once and it wins
    20 of it back before the next blow lands."""
    env, city = besieged_fixture([RING_C])
    place(env, WarriorUnit, 1, (7, 0))  # keeps player 1 alive and on the clock
    _attack_the_city(env, env.players[1].units[0])

    hurt = city.health
    assert hurt < unit_model.CITY_HEALTH, "fixture: the attack must land"

    env.players[0].start_turn()

    assert city.health == pytest.approx(
        min(unit_model.CITY_HEALTH, hurt + unit_model.CITY_HEAL_PER_TURN)
    )


def test_a_besieged_city_wins_nothing_back_between_blows():
    env, city = besieged_fixture([RING_A, RING_C, RING_E])
    place(env, WarriorUnit, 1, (7, 0))
    assert env.is_city_under_siege(city), "fixture: the blockade must hold"
    _attack_the_city(env, env.players[1].units[0])

    hurt = city.health
    assert hurt < unit_model.CITY_HEALTH

    env.players[0].start_turn()

    assert city.health == pytest.approx(hurt), (
        "a besieged city must not repair a single point between turns"
    )
