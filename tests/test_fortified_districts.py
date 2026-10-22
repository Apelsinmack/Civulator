"""v0.9.0 Q3 (#94, #128): fortified districts -- the Encampment as a forward
wall (docs/districts_religion_design.md §4, "v2 fixes" B4, "v3 fixes" L8).

A COMPLETE district whose registry entry has `health` is a fortified
district: it is attacked through `_execute_attack` like a city, defends with
its city's strength, is never killed (floors at 0) and never captured,
refuses enemy entry while its health is above 0 (one lookup,
`GameEnvironment.enemy_fortification_at`, read by the dispatcher, both mask
loops, both `Unit.move` branches, the post-kill move-in and
`defaults.step_toward`), repairs unless besieged or occupied, strikes when its
city may, takes newly built land military units, and changes hands at
`captured_health_percent`.

Boards are test_districts' all-Plains fixture (every tech known, rivers
cleared). Player 0 owns the city at CENTRE and its fortified district at
FORT, two tiles east; player 1 is the attacker. The fortified type is read
from the registry, never named in a rule.
"""

import copy

import numpy as np
import pytest

from civulator import district_model, unit_model
from civulator.agents.networks import _valid_order_mask_np
from civulator.game import unit as unit_mod
from civulator.game.defaults import step_toward
from civulator.game.unit import (
    ArcherUnit, CatapultUnit, SettlerUnit, SwordsmanUnit, WarriorUnit, WorkerUnit,
)

from test_combat_range import place
from test_districts import board, make_city, own

CENTRE = (3, 5)
FORT = (3, 7)
RESERVE = (7, 0)


def fortified_types():
    return [n for n, s in district_model.DISTRICTS.items() if s.health is not None]


def fort_type():
    types = fortified_types()
    if not types:
        pytest.skip("no fortified district configured")
    return types[0]


def fortified_board(complete=True, walls=False):
    """Player 0's city at CENTRE with a fortified district at FORT (complete
    unless told otherwise); player 1 to move."""
    env = board()
    city = make_city(env, CENTRE)
    own(env, city, FORT)
    assert env.place_district(city, fort_type(), FORT), "fixture: the district must be placeable"
    district = city.districts[-1]
    if complete:
        env.complete_district(city, district)
    if walls:
        city.buildings.append(unit_model.CITY_RANGED_BUILDING)
    env.current_player = env.players[1]
    env.current_player_index = 1
    # A reserve far away keeps player 1's turn open after an order spends the
    # acting unit (`_check_game_end` would otherwise roll the turn over, and
    # player 0's repair phase would run inside the test's one step).
    place(env, WarriorUnit, 1, RESERVE)
    return env, city, district


def ring_of(env, pos):
    return [tuple(p) for p in env.map.get_adjacent_coords(pos)]


def unit_on_copy(trial, unit):
    """The copy of `unit` inside a deep-copied environment."""
    for u in trial.players[unit.player.player_index].units:
        if u.coordinates == unit.coordinates and u.unit_type == unit.unit_type:
            return u
    raise AssertionError("unit not found on the copy")


def order(env, unit, target):
    """One order through the real step path (`_step_inner`)."""
    r, c = unit.coordinates
    return env.step([np.array([r, c, unit.slot]), np.array(list(target))])


# --- Config and state -----------------------------------------------------------


def test_the_encampment_is_a_fortified_district_with_the_configured_columns():
    """§4.2: the Encampment has health 100 and captured_health_percent 50.
    Breaks if the columns leave the config or the parser drops them."""
    spec = district_model.DISTRICTS["Encampment"]
    assert spec.health == 100
    assert spec.captured_health_percent == 50
    assert "Encampment" in fortified_types()


@pytest.mark.parametrize("table, message", [
    ({"production_cost": 10, "health": 100}, "needs captured_health_percent"),
    ({"production_cost": 10, "captured_health_percent": 50}, "needs health"),
    ({"production_cost": 10, "health": 0, "captured_health_percent": 50}, "positive"),
    ({"production_cost": 10, "health": 100, "captured_health_percent": 101}, "> 100"),
])
def test_the_fortification_columns_are_validated_together(table, message):
    """Both or neither, health positive, percent 0..100. Breaks if a half
    fortification (health with no capture rule, or the reverse) loads."""
    with pytest.raises(ValueError, match=message):
        district_model._parse_district("Probe", table, set(district_model.DISTRICTS))


def test_only_a_complete_district_is_a_fortification_and_it_completes_at_full_health():
    """An incomplete Encampment is not fortified (health 0, no lookup hit);
    completion sets the maximum. Breaks if health is set at placement or the
    lookup ignores `complete`."""
    env, city, district = fortified_board(complete=False)
    assert not district.is_fortification
    assert env.enemy_fortification_at(FORT, env.players[1]) is None
    env.complete_district(city, district)
    assert district.is_fortification
    assert district.health == district.max_health
    assert env.enemy_fortification_at(FORT, env.players[1]) is district
    assert env.enemy_fortification_at(FORT, env.players[0]) is None, "own units are never blocked"


def test_the_district_s_player_is_its_city_s_player_at_call_time():
    """The defender protocol reads the owner through the city, so a change of
    hands carries it. Breaks if `player` is stored on the district."""
    env, city, district = fortified_board()
    assert district.player is env.players[0]
    city.set_owner(env.players[1])
    assert district.player is env.players[1]


# --- Entry refusal: Unit.move, the mask, the move-in, step_toward ------------


def test_a_standing_fortification_refuses_enemy_entry_and_admits_it_when_breached():
    """§11 row 10: enemy entry refused while health > 0, admitted at 0; own
    units always pass. Breaks if the refusal leaves `Unit.move`'s adjacent
    branch."""
    env, _city, district = fortified_board()
    enemy = place(env, WarriorUnit, 1, (3, 8))
    assert not enemy.move(FORT, env)[0]
    assert enemy.coordinates == (3, 8)

    friend = place(env, WarriorUnit, 0, (3, 6))
    assert friend.move(FORT, env)[0], "the owner's units always pass"

    district.health = 0
    friend.move((3, 6), env)
    enemy.movement_points = enemy.get_max_movement()
    assert enemy.move(FORT, env)[0], "a breached fortification is an ordinary tile"


def test_a_path_never_walks_onto_a_standing_enemy_fortification():
    """The pathfinder branch of `Unit.move` refuses the tile too, as an
    intermediate step: (3, 8) -> (3, 6) is a straight line whose only
    two-step path crosses FORT. Breaks if only the destination or the
    adjacent branch checks."""
    env, _city, district = fortified_board()
    enemy = place(env, WarriorUnit, 1, (3, 8))
    assert env.map.distance_function(enemy.coordinates, (3, 6)) == 2
    enemy.move((3, 6), env)
    assert enemy.coordinates != FORT

    district.health = 0
    enemy.movement_points = enemy.get_max_movement()
    assert enemy.move((3, 6), env)[0]
    assert enemy.coordinates == (3, 6), "breached, the walk crosses it"


@pytest.mark.parametrize("breached", [False, True])
def test_the_mask_and_unit_move_agree_on_every_tile_around_a_fortification(breached):
    """B4 / §11 row 10: for an enemy Warrior on every tile around the
    fortification, every neighbouring tile is offered as a move exactly when
    `Unit.move` accepts it -- except the standing fortification itself, which
    is offered (as an attack) and never entered. Breaks if the refusal lives
    in one of the two only."""
    checked = 0
    for start in ring_of(fortified_board()[0], FORT):
        env, city, district = fortified_board()
        if breached:
            district.health = 0
        unit = place(env, WarriorUnit, 1, start)
        mask = _valid_order_mask_np(unit, env, env.n, env.m)
        for dest in ring_of(env, start):
            if env.map.get_tile(dest).city is not None:
                continue  # a city tile is the city's rule, tested in test_mask_city_orders
            trial = copy.deepcopy(env)
            moved, _ = unit_on_copy(trial, unit).move(dest, trial)
            if dest == FORT and not breached:
                assert mask[dest] == 1, f"from {start}: the attack on the fortification is offered"
                assert not moved, f"from {start}: Unit.move entered a standing fortification"
            else:
                assert bool(mask[dest]) == moved, f"from {start} to {dest}: mask {mask[dest]} vs move {moved}"
            checked += 1
    assert checked >= 24, f"property only exercised {checked} tiles"


def test_an_order_onto_a_standing_enemy_fortification_is_a_melee_attack_never_a_move():
    """B4: the dispatcher sends an adjacent order to `_execute_attack`. The
    fortification loses health, the attacker stays and spends its turn.
    Breaks if `_step_inner` falls through to movement."""
    env, _city, district = fortified_board()
    unit = place(env, SwordsmanUnit, 1, (3, 8))
    order(env, unit, FORT)
    assert district.health < district.max_health
    assert unit.coordinates == (3, 8)
    assert unit.movement_points == 0
    assert unit.health < 100, "a fortification counterattacks in melee, like a city"


def test_an_order_onto_a_standing_enemy_fortification_in_range_is_a_ranged_attack():
    """B4: a ranged unit in range and sight hits it, takes no counterattack,
    and the ranged mask offers the tile. Breaks if the ranged mask loop or
    the dispatcher skips fortifications."""
    env, _city, district = fortified_board()
    archer = place(env, ArcherUnit, 1, (3, 9))
    assert env.map.distance_function(archer.coordinates, FORT) == 2
    assert _valid_order_mask_np(archer, env, env.n, env.m)[FORT] == 1
    order(env, archer, FORT)
    assert district.health < district.max_health
    assert archer.coordinates == (3, 9) and archer.health == 100


def test_a_breached_fortification_is_no_ranged_target():
    """At 0 another hit could not lower it, so offering it would be a no-op
    (#51). Breaks if the ranged loop ignores health."""
    env, _city, district = fortified_board()
    district.health = 0
    archer = place(env, ArcherUnit, 1, (3, 9))
    assert _valid_order_mask_np(archer, env, env.n, env.m)[FORT] == 0


def test_the_post_kill_move_in_never_lands_on_a_standing_enemy_fortification():
    """B4: killing the unit that stands on a standing enemy fortification
    leaves the attacker where it is; on a breached one it moves in. Breaks
    if the move-in checks only `enemy_city_blocks`."""
    for health, lands in ((None, False), (0, True)):
        env, _city, district = fortified_board()
        if health is not None:
            district.health = health
        garrison = place(env, WarriorUnit, 0, FORT)
        garrison.health = 1
        attacker = place(env, SwordsmanUnit, 1, (3, 8))
        order(env, attacker, FORT)
        assert garrison not in env.players[0].units, "fixture: the garrison dies"
        assert (attacker.coordinates == FORT) is lands


def test_step_toward_never_steps_onto_a_standing_enemy_fortification():
    """B4: the engine defaults' one step obeys the same refusal. Breaks if
    `defaults.step_toward` skips the lookup."""
    env, _city, district = fortified_board()
    worker = place(env, WorkerUnit, 1, (3, 8))
    assert step_toward(worker, FORT, env) is None
    district.health = 0
    assert step_toward(worker, FORT, env) == FORT


# --- Combat arithmetic ----------------------------------------------------------


def _record_damage_calls(monkeypatch):
    calls = []

    def fake(attacker_strength, defender_strength, rng=None):
        calls.append((attacker_strength, defender_strength))
        return 10

    monkeypatch.setattr(unit_mod, "calculate_damage", fake)
    return calls


def test_a_fortification_defends_with_its_city_s_strength_and_takes_the_ranged_penalty(monkeypatch):
    """§11 row 11: the defender strength is the city's, the shooter's is
    reduced by `ranged_city_penalty` (Civ 6: -17 vs district defences) and
    the siege class is exempt, as against a city. Breaks if the defender
    protocol diverges from the City's."""
    env, city, district = fortified_board()
    city.buildings.append(unit_model.CITY_RANGED_BUILDING)  # walls raise the city's strength
    archer = place(env, ArcherUnit, 1, (3, 9))
    catapult = place(env, CatapultUnit, 1, (2, 9))
    calls = _record_damage_calls(monkeypatch)

    archer.attack(district, env)
    catapult.attack(district, env)

    plain_archer = archer.get_ranged_strength(district, False)
    plain_catapult = catapult.get_ranged_strength(district, False)
    assert calls[0] == (plain_archer - unit_model.RANGED_CITY_PENALTY,
                        city.get_combat_strength(False, archer))
    assert calls[1] == (plain_catapult, city.get_combat_strength(False, catapult))
    assert district.health == district.max_health - 20


def test_a_fortification_floors_at_zero_is_never_removed_and_counts_a_breach():
    """§4.2: never killed -- health floors at 0, the district stays on its
    tile, and the attacker's `encampment_breaches` counts the breach once.
    Breaks if `Unit.attack` stops reading the flag."""
    env, _city, district = fortified_board()
    district.health = 1
    unit = place(env, SwordsmanUnit, 1, (3, 8))
    order(env, unit, FORT)
    assert district.health == 0
    assert env.map.get_tile(FORT).district is district
    assert env.episode_stats[1]["encampment_breaches"] == 1
    assert unit.coordinates == (3, 8), "the blow breaches; walking in is the next order"


# --- Repair --------------------------------------------------------------------


def test_a_damaged_fortification_repairs_at_its_owner_s_turn_start():
    """§4.2: `[city] heal_per_turn` in the city's repair phase, capped at the
    maximum. Breaks if fortifications stop repairing."""
    env, city, district = fortified_board()
    district.health = 50
    city.process_turn(env)
    assert district.health == 50 + unit_model.CITY_HEAL_PER_TURN
    district.health = district.max_health - 1
    city.process_turn(env)
    assert district.health == district.max_health


def test_the_ring_blocks_repair_and_its_lifting_resumes_it():
    """v2 fixes: the full ring test of `is_city_under_siege`, with the
    district's tile. Breaks if the repair uses another test or the city's
    centre."""
    env, city, district = fortified_board()
    district.health = 50
    besiegers = [place(env, WarriorUnit, 1, pos) for pos in ring_of(env, FORT)]
    assert env.is_city_under_siege(city, FORT)
    assert not env.is_city_under_siege(city), "fixture: the centre itself is not besieged"
    city.process_turn(env)
    assert district.health == 50

    env.delete_unit(besiegers[0])
    for unit in besiegers[1:]:
        env.delete_unit(unit)
    city.process_turn(env)
    assert district.health == 50 + unit_model.CITY_HEAL_PER_TURN


def test_an_enemy_standing_on_the_tile_blocks_repair():
    """L8: a breached fortification under an occupier does not mend; it
    repairs again once the occupier leaves, and an own unit there does not
    block. Breaks if the occupier clause is dropped."""
    env, city, district = fortified_board()
    district.health = 0
    # An Archer: it projects no zone of control, so the ring around the tile
    # stays open and the occupier clause alone decides (a melee occupier
    # would also besiege the tile through its own ZoC).
    occupier = place(env, ArcherUnit, 1, FORT)
    assert not env.is_city_under_siege(city, FORT), "fixture: no ring, only the occupier"
    city.process_turn(env)
    assert district.health == 0

    env.delete_unit(occupier)
    place(env, WarriorUnit, 0, FORT)
    city.process_turn(env)
    assert district.health == unit_model.CITY_HEAL_PER_TURN


# --- Strike -------------------------------------------------------------------


def test_the_fortification_strikes_from_its_own_tile_only_with_walls_health_and_no_occupier():
    """L8 / §11 row 12: it shoots iff its own health > 0, its city holds
    `[city] ranged_building`, and no enemy stands on its tile; from its own
    tile (the target is out of the centre's range). Breaks if a gate is
    skipped or the strike fires from the centre."""
    victim_pos = (3, 9)
    env, city, district = fortified_board(walls=False)
    victim = place(env, WarriorUnit, 1, victim_pos)
    assert env.map.distance_function(CENTRE, victim_pos) > city.get_range()
    assert env.map.distance_function(FORT, victim_pos) <= city.get_range()
    assert env.fortification_ranged_attack(district) is None, "no Walls, no strike"

    city.buildings.append(unit_model.CITY_RANGED_BUILDING)
    assert env.fortification_ranged_attack(district) is victim
    assert victim.health < 100
    assert env.episode_stats[0]["encampment_strikes"] == 1

    victim.health = 100
    district.health = 0
    assert env.fortification_ranged_attack(district) is None, "a breached fortification is silent"

    district.health = 50
    place(env, WarriorUnit, 1, FORT)
    assert env.fortification_ranged_attack(district) is None, "an occupier silences it"
    assert victim.health == 100


def test_the_strike_honours_range_and_line_of_sight():
    """The same targeting rule as the city's, from the district's tile.
    Breaks if `_bombard_target` measures from the centre or skips LoS."""
    env, city, district = fortified_board(walls=True)
    far = place(env, WarriorUnit, 1, (3, 10))
    assert env.map.distance_function(FORT, far.coordinates) > city.get_range()
    assert env.fortification_ranged_attack(district) is None

    hidden_pos = (3, 9)
    env.map.tiles[3, 8].set_layers("Plains", relief="mountain", map_ref=env.map)
    hidden = place(env, WarriorUnit, 1, hidden_pos)
    if env.check_line_of_sight(FORT, hidden_pos):
        pytest.skip("fixture: the mountain does not block this line")
    assert env.fortification_ranged_attack(district) is None
    assert hidden.health == 100


@pytest.mark.parametrize("walls", [True, False])
def test_a_walled_city_with_a_fortification_strikes_twice_centre_first(monkeypatch, walls):
    """§11 row 12: at its owner's turn start the centre fires, then the
    fortification; without Walls neither does. Breaks if the strike order
    changes or the fortification skips the `ranged_building` gate."""
    env, city, district = fortified_board(walls=walls)
    place(env, WarriorUnit, 1, (3, 6))  # in reach of both
    origins = []
    real = env._ranged_strike

    def spy(c, origin):
        origins.append(tuple(origin))
        return real(c, origin)

    monkeypatch.setattr(env, "_ranged_strike", spy)
    env.current_player = env.players[0]
    env.current_player_index = 0
    env.players[0].start_turn()
    assert origins == ([CENTRE, FORT] if walls else [])


# --- Spawn ----------------------------------------------------------------------


def unit_types():
    """Every configured unit type (the class registry), in config order."""
    return list(unit_mod.Unit.COMBAT_CLASS)


def test_a_land_military_unit_spawns_on_the_fortification_when_the_centre_is_taken():
    """§11 row 13: candidate order centre -> fortified district -> adjacent.
    Breaks if `complete_unit_production`'s candidate order changes."""
    env, city, district = fortified_board()
    place(env, WarriorUnit, 0, CENTRE)
    fighter = next(t for t in unit_types()
                   if unit_mod.Unit.COMBAT_CLASS[t] in unit_model.FIGHTING_CLASSES
                   and unit_mod.movement_domain(t) == "land")
    assert city.complete_unit_production(fighter, env)
    assert [u.unit_type for u in env.get_units_at(FORT)] == [fighter]


def test_a_civilian_never_spawns_on_the_fortification():
    """§4.1: land military units only. Breaks if the class clause is
    dropped."""
    env, city, district = fortified_board()
    place(env, WarriorUnit, 0, CENTRE)
    for civilian in (t for t in unit_types() if unit_mod.Unit.COMBAT_CLASS[t] == "civilian"):
        assert city.complete_unit_production(civilian, env)
    assert env.get_units_at(FORT) == []


def test_an_incomplete_or_occupied_fortification_is_no_spawn_tile():
    """Only a complete fortified district is a candidate, and the same
    occupancy rule as an adjacent tile holds. Breaks if placement reads the
    district list without `complete` or stacks units."""
    env, city, district = fortified_board(complete=False)
    place(env, WarriorUnit, 0, CENTRE)
    assert city.complete_unit_production("Warrior", env)
    assert env.get_units_at(FORT) == []

    env, city, district = fortified_board()
    place(env, WarriorUnit, 0, CENTRE)
    place(env, SettlerUnit, 0, FORT)
    assert city.complete_unit_production("Warrior", env)
    assert [u.unit_type for u in env.get_units_at(FORT)] == ["Settler"]


# --- Capture and flip -----------------------------------------------------------


def test_capture_sets_fortified_health_to_the_captured_percent():
    """§4.2: the district goes with its city at `captured_health_percent` of
    its maximum. Breaks if `set_owner` leaves district health alone."""
    env, city, district = fortified_board()
    district.health = 10
    city.health = 0
    taker = place(env, SwordsmanUnit, 1, (3, 6))
    env._capture_city(taker, city)
    assert city.player is env.players[1]
    spec = district_model.DISTRICTS[district.type]
    assert district.health == spec.health * spec.captured_health_percent // 100


def test_a_loyalty_flip_sets_fortified_health_too():
    """The orchestrator's Q3 contract: a flip is the same door (`set_owner`).
    Breaks if the reset moves into `_capture_city`."""
    env, city, district = fortified_board()
    district.health = 90
    env._flip_city(city, env.players[1])
    spec = district_model.DISTRICTS[district.type]
    assert district.health == spec.health * spec.captured_health_percent // 100


def test_an_incomplete_district_gains_no_health_on_capture():
    """Only fortified (complete) districts carry health. Breaks if the reset
    reads every district."""
    env, city, district = fortified_board(complete=False)
    env._flip_city(city, env.players[1])
    assert district.health == 0 and not district.is_fortification


# --- #51: no offered order near a fortification is a no-op -------------------


def _observables(env, district):
    units = tuple(sorted(
        (p.player_index, u.unit_type, tuple(u.coordinates), round(float(u.health), 6),
         float(u.movement_points), int(u.fortification))
        for p in env.players for u in p.units
    ))
    return (env.turn_counter, env.current_player_index, units,
            round(float(district.health), 6))


@pytest.mark.parametrize("breached", [False, True])
def test_no_masked_order_near_a_fortification_is_a_no_op(breached):
    """CLAUDE.md, Action masking: a mask must never offer an action that
    cannot change the state (#51). Every unit type at distance 1-3 from a
    standing and a breached fortification: every offered order changes
    something. Breaks if the mask offers the walk-in onto a standing
    fortification that `Unit.move` refuses, or a ranged shot at a breached
    one."""
    checked = 0
    for cls in (WarriorUnit, SwordsmanUnit, ArcherUnit, CatapultUnit, SettlerUnit, WorkerUnit):
        for start in ((3, 8), (3, 9), (3, 10), (2, 9), (4, 8)):
            env, _city, district = fortified_board()
            if breached:
                district.health = 0
            unit = place(env, cls, 1, start)
            mask = _valid_order_mask_np(unit, env, env.n, env.m)
            for dest in zip(*np.nonzero(mask)):
                dest = (int(dest[0]), int(dest[1]))
                trial = copy.deepcopy(env)
                trial_district = trial.map.get_tile(FORT).district
                before = _observables(trial, trial_district)
                order(trial, unit_on_copy(trial, unit), dest)
                assert _observables(trial, trial_district) != before, (
                    f"{cls.__name__} at {start}, breached={breached}: order {dest} changed nothing")
                checked += 1
    assert checked > 50, f"property only exercised {checked} orders"
