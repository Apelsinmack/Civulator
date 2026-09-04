"""Issue #51: a mask-legal action must always change the game state.

The livelock. `_step_inner` returns REWARDS["invalid_action"] for an action
the engine refuses, and does so *without consuming movement, ending the turn
or altering anything*. If the masks offer such an action, a deterministic
(greedy) policy whose argmax lands on it will choose it again from the
identical state, forever — until the `step_counter > 10000` guard in
`_play_game` / `train_agents` cuts the game off. That truncated 85 of 1000
training episodes and 50 of 200 evaluation games for `duel_53ch_net128x6`,
and the 50 cut-off games were recorded as ordinary draws.

The fix is in the masks, which are canonical (project CLAUDE.md: the agent
and the human tools share them), so the tests are too:

  1. `test_settler_inside_min_city_distance_*` — the exact reproduction from
     the issue.
  2. `test_unaffordable_step_*` — the second no-op path found while writing
     these: `Unit.move` refuses a step whose cost exceeds the unit's
     remaining movement points, while the mask only required
     movement_points > 0.
  3. `test_stuck_settler_is_not_selectable` — completeness. Once (1) can
     take the own tile away, a Settler can have an all-zero move mask;
     selecting it would livelock again (`_greedy_action` falls back to the
     unit's own tile when no move is valid).
  4. `test_every_masked_action_changes_state` — the general property, worth
     having on its own: over many varied random states, EVERY action the
     masks offer must move at least one observable.
"""

import copy
import random

import numpy as np
import torch

from civulator.agents.networks import get_valid_moves_mask, get_valid_select_mask
from civulator.game.unit import NUM_UNIT_SLOTS, SettlerUnit, WarriorUnit

from test_combat_range import make_flat_env, place
from test_mask_vectorization import _build_random_scenario


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _blank_state(env):
    """A state tensor of the right shape. The masks read `game_env`, not the
    tensor's contents (the state-tensor fallback was deleted in P2a), so the
    values are irrelevant — only shape and device are."""
    return torch.zeros(3, env.n, env.m)


def _select_index(env, unit):
    r, c = unit.coordinates
    return (r * env.m + c) * NUM_UNIT_SLOTS + unit.slot


def _clear_board(env):
    """Remove every unit and city placed by the fixture, leaving bare terrain."""
    for player in env.players:
        for unit in list(player.units):
            env.map.get_tile(unit.coordinates).remove_unit(unit)
        player.units.clear()
        player.cities.clear()
    for r in range(env.n):
        for c in range(env.m):
            env.map.tiles[r, c].units.clear()
            env.map.tiles[r, c].city = None


def _observables(env):
    """Everything a player could see change: whose turn it is, how far the
    game has got, and every unit's and city's situation."""
    units = tuple(sorted(
        (
            p.player_index,
            u.unit_type,
            int(u.coordinates[0]),
            int(u.coordinates[1]),
            round(float(u.health), 6),
            float(u.movement_points),
            int(u.fortification),
            bool(u.has_acted),
        )
        for p in env.players for u in p.units
    ))
    cities = tuple(sorted(
        (p.player_index, int(c.coordinates[0]), int(c.coordinates[1]))
        for p in env.players for c in p.cities
    ))
    return (env.turn_counter, env.current_player.player_index, bool(env.done),
            units, cities)


def _step_on_copy(env, select_index, move_index):
    """Apply one masked action to a deep copy; return (before, after)."""
    trial = copy.deepcopy(env)
    before = _observables(trial)
    tile_idx, slot = divmod(select_index, NUM_UNIT_SLOTS)
    action = [
        np.array([tile_idx // trial.m, tile_idx % trial.m, slot]),
        np.array([move_index // trial.m, move_index % trial.m]),
    ]
    trial.step(action)
    return before, _observables(trial)


# ---------------------------------------------------------------------------
# 1. The reported reproduction: Settler inside min_city_distance of a city.
# ---------------------------------------------------------------------------

def _settler_next_to_city():
    """Player 0 owns a city at (4, 4); its Settler stands adjacent at (4, 5),
    well inside `min_city_distance` (3), so it cannot found there."""
    env = make_flat_env()
    _clear_board(env)
    env.found_city(env.players[0], (4, 4), "Capital")
    settler = place(env, SettlerUnit, 0, (4, 5))
    env.current_player = env.players[0]
    env.current_player_index = 0
    return env, settler


def test_settler_inside_min_city_distance_cannot_found_there():
    """Guards the premise of the regression test below."""
    env, settler = _settler_next_to_city()
    assert not env.can_found_city_at(settler.coordinates)


def test_settler_inside_min_city_distance_is_not_offered_its_own_tile():
    env, settler = _settler_next_to_city()
    state = _blank_state(env)

    moves = get_valid_moves_mask(state, _select_index(env, settler), env)
    moves = moves.reshape(env.n, env.m)
    assert moves[settler.coordinates] == 0, (
        "the move mask still offers a Settler its own tile where no city can "
        "be founded — issue #51's livelock"
    )
    # It can still walk away: the settler stays selectable and useful.
    assert moves.sum() > 0


def test_settler_own_tile_is_offered_where_a_city_may_be_founded():
    """The other half of the rule: a legal found is still offered."""
    env = make_flat_env()
    _clear_board(env)
    settler = place(env, SettlerUnit, 0, (4, 5))
    env.current_player = env.players[0]
    env.current_player_index = 0

    moves = get_valid_moves_mask(_blank_state(env), _select_index(env, settler), env)
    assert moves.reshape(env.n, env.m)[settler.coordinates] == 1
    assert env.can_found_city_at(settler.coordinates)


# ---------------------------------------------------------------------------
# 2. Second no-op path: a step the unit cannot pay for.
# ---------------------------------------------------------------------------

def test_unaffordable_step_is_not_offered():
    """1 movement point left, hills (cost 2) next door: `Unit.move` refuses
    and changes nothing, so the mask must not offer the tile."""
    env = make_flat_env()
    _clear_board(env)
    env.map.tiles[4, 6].set_layers("Grassland", relief="hills", map_ref=env.map)
    warrior = place(env, WarriorUnit, 0, (4, 5))
    warrior.movement_points = 1
    env.current_player = env.players[0]
    env.current_player_index = 0

    assert env.map.tiles[4, 6].movement_cost == 2, "fixture assumes hills cost 2"

    moves = get_valid_moves_mask(_blank_state(env), _select_index(env, warrior), env)
    moves = moves.reshape(env.n, env.m)
    assert moves[4, 6] == 0, "the move mask offers a step the unit cannot pay for"
    # With 2 points it is affordable again.
    warrior.movement_points = 2
    moves = get_valid_moves_mask(
        _blank_state(env), _select_index(env, warrior), env
    ).reshape(env.n, env.m)
    assert moves[4, 6] == 1


def test_unaffordable_step_is_still_offered_as_an_attack():
    """Attacking costs no movement points, only requires having some — so an
    enemy on that same expensive tile stays a legal target."""
    env = make_flat_env()
    _clear_board(env)
    env.map.tiles[4, 6].set_layers("Grassland", relief="hills", map_ref=env.map)
    warrior = place(env, WarriorUnit, 0, (4, 5))
    warrior.movement_points = 1
    place(env, WarriorUnit, 1, (4, 6))
    env.current_player = env.players[0]
    env.current_player_index = 0

    moves = get_valid_moves_mask(
        _blank_state(env), _select_index(env, warrior), env
    ).reshape(env.n, env.m)
    assert moves[4, 6] == 1

    before, after = _step_on_copy(env, _select_index(env, warrior), 4 * env.m + 6)
    assert before != after, "the offered attack changed nothing"


# ---------------------------------------------------------------------------
# 3. Completeness: a Settler with no valid order must not be selectable.
# ---------------------------------------------------------------------------

def test_stuck_settler_is_not_selectable():
    """Cannot found (too close to a city) and cannot leave (ringed by
    mountains): an all-zero move mask. Selecting it is the livelock again,
    because `_greedy_action` falls back to the unit's own tile."""
    env = make_flat_env()
    _clear_board(env)
    env.found_city(env.players[0], (4, 4), "Capital")
    settler = place(env, SettlerUnit, 0, (4, 6))
    for coords in env.map.get_adjacent_coords((4, 6)):
        env.map.get_tile(coords).set_layers("Plains", relief="mountain", map_ref=env.map)
    env.current_player = env.players[0]
    env.current_player_index = 0

    state = _blank_state(env)
    sel_idx = _select_index(env, settler)
    assert get_valid_moves_mask(state, sel_idx, env).sum() == 0, "fixture is wrong"
    assert get_valid_select_mask(state, env)[sel_idx] == 0, (
        "a settler with no legal order is still selectable — selecting it "
        "would repeat a no-op forever"
    )


def test_a_boxed_in_warrior_is_still_selectable():
    """The same box does not strand a military unit: fortifying on its own
    tile always succeeds while it has movement points."""
    env = make_flat_env()
    _clear_board(env)
    warrior = place(env, WarriorUnit, 0, (4, 6))
    for coords in env.map.get_adjacent_coords((4, 6)):
        env.map.get_tile(coords).set_layers("Plains", relief="mountain", map_ref=env.map)
    env.current_player = env.players[0]
    env.current_player_index = 0

    state = _blank_state(env)
    sel_idx = _select_index(env, warrior)
    assert get_valid_select_mask(state, env)[sel_idx] == 1
    assert get_valid_moves_mask(state, sel_idx, env).sum() == 1  # fortify only

    before, after = _step_on_copy(env, sel_idx, 4 * env.m + 6)
    assert before != after


# ---------------------------------------------------------------------------
# 4. The general property.
# ---------------------------------------------------------------------------

N_PROPERTY_SCENARIOS = 20
MAX_SELECTIONS_PER_SCENARIO = 8
MAX_MOVES_PER_SELECTION = 8


def test_end_turn_always_changes_state():
    """The always-valid action in the select mask is never a no-op either."""
    env = make_flat_env()
    env.current_player = env.players[0]
    env.current_player_index = 0
    before, after = _step_on_copy(env, env.n * env.m * NUM_UNIT_SLOTS, 0)
    assert before != after


def test_every_masked_action_changes_state():
    """Over varied random states, every (select, order) pair the masks offer
    must move at least one observable: turn counter, whose turn it is, the
    done flag, or some unit's or city's position, health, movement points,
    fortification, acted flag or ownership.

    This is the general form of issue #51 — an offered action that leaves
    all of that untouched is one a greedy policy can repeat forever.
    """
    rng = random.Random(51)
    checked = 0
    for scenario in range(N_PROPERTY_SCENARIOS):
        n, m = rng.choice([(8, 16), (10, 20), (6, 12)])
        env, _units, _cp = _build_random_scenario(rng, n, m, rng.choice([2, 2, 3]))
        state = _blank_state(env)

        select_mask = get_valid_select_mask(state, env)
        select_indices = torch.nonzero(select_mask).flatten().tolist()
        rng.shuffle(select_indices)

        for select_index in select_indices[:MAX_SELECTIONS_PER_SCENARIO]:
            move_mask = get_valid_moves_mask(state, select_index, env)
            move_indices = torch.nonzero(move_mask).flatten().tolist()
            assert move_indices, (
                f"scenario {scenario}: unit at select_index {select_index} is "
                f"selectable but has no legal order — selecting it is a "
                f"guaranteed no-op (issue #51)"
            )
            rng.shuffle(move_indices)

            for move_index in move_indices[:MAX_MOVES_PER_SELECTION]:
                before, after = _step_on_copy(env, select_index, move_index)
                assert before != after, (
                    f"scenario {scenario}: masked action "
                    f"select={select_index} order={move_index} changed nothing "
                    f"— a greedy policy would repeat it until the step guard"
                )
                checked += 1

    assert checked > 200, f"property test only exercised {checked} actions"


def test_every_tile_costs_at_least_one_whole_movement_point():
    """A premise the #51 audit rests on, pinned so it cannot drift silently.

    `Unit.attack` bails out (returning zero damage — a no-op) when
    movement_points < 0.25, and a Catapult's bombard when < 1, while the
    masks only require movement_points > 0. Those guards are unreachable
    ONLY because every tile costs a whole movement point or more, so
    "> 0" means ">= 1". Introduce a fractional or zero movement cost in
    config.toml and both become live no-op paths (a zero cost would also
    let a unit shuttle between two tiles forever without spending
    anything). Then the mask needs the same affordability rule for attacks
    that it already has for moves.
    """
    from civulator.config import CFG
    from civulator.terrain_model import compose, validate

    terrain = CFG["terrain"]
    combos = 0
    for base in terrain["base"]:
        for relief in terrain["relief"]:
            for feature in [None] + list(terrain["feature"]):
                for resource in [None] + list(terrain["resource"]):
                    try:
                        validate(base, relief=relief, feature=feature, resource=resource)
                    except ValueError:
                        continue
                    cost = compose(
                        base, relief=relief, feature=feature, resource=resource
                    ).movement
                    combos += 1
                    assert cost == int(cost) and cost >= 1, (
                        f"{base}/{relief}/{feature}/{resource} costs {cost}"
                    )
    assert combos > 20, "terrain tables look empty — the check proved nothing"
