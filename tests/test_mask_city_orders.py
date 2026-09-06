"""Issue #84 x issue #51: no mask-legal order against a city may be a no-op.

Making a city attackable changes what an order aimed at a city tile MEANS,
so it changes the mask for every city tile in the game. Two ways that can go
wrong, and the second is the one that costs training runs:

  * something legal is not offered - a siege unit that cannot bombard from
    range is a rule nobody can use;
  * something offered is refused by the engine - `_step_inner` returns
    REWARDS["invalid_action"] having consumed no movement and changed
    nothing, and a greedy policy repeats it until the 10,000-step guard.
    That is issue #51 exactly: 85 truncated training episodes, 50 of 200
    eval games.

This file is the property test for the second, restricted to boards that
actually contain cities - the general property test in
tests/test_mask_no_op_actions.py only founds a city 30% of the time and
never in a deliberate relationship to the units.

The masks are canonical (project CLAUDE.md): `civulator/tools/recording.py`
highlights human clicks with the same two functions the agent uses, so
whatever is pinned here holds for the human tools too.
"""

import copy
import itertools

import numpy as np
import torch

from civulator.agents.networks import get_valid_moves_mask, get_valid_select_mask
from civulator.game.unit import (
    NUM_UNIT_SLOTS, ArcherUnit, CatapultUnit, SettlerUnit, SlingerUnit,
    SpearmanUnit, SwordsmanUnit, WarriorUnit, WorkerUnit,
)

from test_combat_range import make_flat_env, place

CITY = (4, 8)
UNIT_CLASSES = [
    WarriorUnit, SwordsmanUnit, SpearmanUnit,
    SlingerUnit, ArcherUnit, CatapultUnit,
    SettlerUnit, WorkerUnit,
]


def _blank_state(env):
    return torch.zeros(3, env.n, env.m)


def _observables(env):
    """Everything an order could visibly change - the #84 version, with city
    health, since a bombard changes nothing else."""
    units = tuple(sorted(
        (p.player_index, u.unit_type, int(u.coordinates[0]), int(u.coordinates[1]),
         round(float(u.health), 6), float(u.movement_points),
         int(u.fortification), bool(u.has_acted))
        for p in env.players for u in p.units
    ))
    cities = tuple(sorted(
        (p.player_index, int(c.coordinates[0]), int(c.coordinates[1]),
         round(float(c.health), 6))
        for p in env.players for c in p.cities
    ))
    return (env.turn_counter, env.current_player.player_index, bool(env.done),
            units, cities)


def _step_on_copy(env, select_index, move_index):
    trial = copy.deepcopy(env)
    before = _observables(trial)
    tile_idx, slot = divmod(select_index, NUM_UNIT_SLOTS)
    trial.step([
        np.array([tile_idx // trial.m, tile_idx % trial.m, slot]),
        np.array([move_index // trial.m, move_index % trial.m]),
    ])
    return before, _observables(trial)


def _scenario(unit_cls, distance, city_health):
    """Player 0's unit `distance` tiles west of player 1's city at CITY."""
    env = make_flat_env()
    env.current_player = env.players[0]
    env.current_player_index = 0
    city = env.found_city(env.players[1], CITY, "Target")
    assert city is not None
    city.health = city_health
    unit = place(env, unit_cls, 0, (CITY[0], CITY[1] - distance))
    assert env.map.distance_function(unit.coordinates, CITY) == distance
    return env, city, unit


def _select_index(env, unit):
    r, c = unit.coordinates
    return (r * env.m + c) * NUM_UNIT_SLOTS + unit.slot


# --- The property -----------------------------------------------------------

def test_no_masked_order_near_a_city_is_a_no_op():
    """Every unit type, at every distance from 1 to 3, against a city at full
    health, at 1 HP and at 0: every order the mask offers must change
    something."""
    checked = 0
    for unit_cls, distance, health in itertools.product(
        UNIT_CLASSES, (1, 2, 3), (200, 1, 0)
    ):
        env, _city, unit = _scenario(unit_cls, distance, health)
        state = _blank_state(env)
        select_index = _select_index(env, unit)

        select_mask = get_valid_select_mask(state, env)
        if select_mask[select_index] == 0:
            continue

        move_mask = get_valid_moves_mask(state, select_index, env)
        move_indices = torch.nonzero(move_mask).flatten().tolist()
        assert move_indices, (
            f"{unit_cls.__name__} at distance {distance} from a city at "
            f"{health} HP is selectable with no legal order (#51)"
        )

        for move_index in move_indices:
            before, after = _step_on_copy(env, select_index, move_index)
            assert before != after, (
                f"{unit_cls.__name__} at distance {distance}, city at {health} "
                f"HP: masked order {divmod(move_index, env.m)} changed nothing "
                "- a greedy policy would repeat it until the step guard"
            )
            checked += 1

    assert checked > 100, f"property test only exercised {checked} orders"


# --- The legal orders are actually offered ----------------------------------

def test_a_siege_unit_is_offered_the_bombard_at_its_full_range():
    """Without this the whole siege class is adjacent-only, which is most of
    the point of range."""
    for cls in (ArcherUnit, CatapultUnit):
        env, _city, unit = _scenario(cls, 2, 200)
        mask = get_valid_moves_mask(
            _blank_state(env), _select_index(env, unit), env
        ).reshape(env.n, env.m)
        assert mask[CITY] == 1, f"{cls.__name__} was not offered a city at range 2"


def test_a_range_one_shooter_is_not_offered_a_city_two_tiles_away():
    env, _city, unit = _scenario(SlingerUnit, 2, 200)
    mask = get_valid_moves_mask(
        _blank_state(env), _select_index(env, unit), env
    ).reshape(env.n, env.m)
    assert mask[CITY] == 0, "the Slinger's range is 1"


def test_a_city_at_zero_health_is_not_a_ranged_target():
    """Another hit could not lower it, so the order would consume the unit's
    turn for nothing an observer could see - and for a Catapult out of melee
    reach it is a pure no-op."""
    for cls in (ArcherUnit, CatapultUnit):
        env, _city, unit = _scenario(cls, 2, 0)
        mask = get_valid_moves_mask(
            _blank_state(env), _select_index(env, unit), env
        ).reshape(env.n, env.m)
        assert mask[CITY] == 0, (
            f"{cls.__name__} was offered a bombard against a city already at 0"
        )


def test_line_of_sight_gates_the_bombard_like_any_other_ranged_order():
    env, _city, unit = _scenario(CatapultUnit, 2, 200)
    env.map.tiles[CITY[0], CITY[1] - 1].set_layers(
        "Plains", relief="mountain", map_ref=env.map
    )
    assert not env.check_line_of_sight(unit.coordinates, CITY)

    mask = get_valid_moves_mask(
        _blank_state(env), _select_index(env, unit), env
    ).reshape(env.n, env.m)
    assert mask[CITY] == 0


def test_the_move_in_and_the_attack_are_never_offered_at_once():
    """The city tile carries exactly one meaning at a time, and the mask
    entry is the only signal an agent gets about which - the encoders do not
    carry city health (#82)."""
    env, city, warrior = _scenario(WarriorUnit, 1, 200)
    idx = _select_index(env, warrior)

    assert get_valid_moves_mask(_blank_state(env), idx, env).reshape(env.n, env.m)[CITY] == 1
    _before, after = _step_on_copy(env, idx, CITY[0] * env.m + CITY[1])
    attacked = dict(((c[0], c[1], c[2]), c[3]) for c in after[4])
    assert attacked[(1, CITY[0], CITY[1])] < 200, "at full health the order is an attack"

    city.health = 0
    assert get_valid_moves_mask(_blank_state(env), idx, env).reshape(env.n, env.m)[CITY] == 1
    _before, after = _step_on_copy(env, idx, CITY[0] * env.m + CITY[1])
    owners = set(c[0] for c in after[4])
    assert owners == {0}, "at 0 health the same order is the capture"
