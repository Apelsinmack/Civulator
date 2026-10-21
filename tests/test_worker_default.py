"""Issue #116 P8: the Worker default (docs/progression_design.md §13, the §14
rows "An idle Worker never builds an improvement its owner's techs do not
allow ..." and "Defaults: ...", "v2 fixes": Improvement yields, Worker
default, Load order and config ownership; docs/housing_design.md, the
accepted gap this closes).

Boards are the all-Plains fixture of test_districts (rivers cleared, both
players know the whole tree). Rules that must not depend on which
improvements are configured run against SYNTHETIC `[improvements.*]` tables
(`conftest.synthetic_improvements`, swapped in place and put back on exit);
the configured ones are checked by properties over whatever is there. No test
names a configured improvement or pins how many there are, or how many a game
builds.
"""

import ast
import inspect
import os
import subprocess
import sys
import textwrap

import pytest

from civulator import district_model, research_model, terrain_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.config import CFG
from civulator.effects import KIND_FREE_UNITS, one_shot_effects
from civulator.game import defaults
from civulator.game.city import UNIT_CLASSES
from civulator.game.defaults import default_workers, worker_target
from civulator.game.districts import can_place_district
from civulator.game.environment import GameEnvironment
from civulator.game.housing import housing
from civulator.game.improvements import (
    best_improvement,
    buildable_here,
    improvement_gain,
    worker_has_work,
    worker_targets,
)
from civulator.game.trade import TRADER_UNIT
from civulator.game.unit import DEFERRED_BUILD_UNITS, WorkerUnit

from conftest import grant_all, stand, synthetic_improvements
from test_districts import board, make_city, own, placeable_type, ring

CENTRE = (3, 4)
PLAINS = {"bases": ["Plains"], "relief": ["flat"]}
WORKER_INDEX = BUILD_OPTIONS.index("Worker")


# --- Fixtures -----------------------------------------------------------------------


def _table(**columns):
    """A synthetic `[improvements.*]` table buildable on flat Plains."""
    return {**columns, "on": PLAINS}


def scene():
    """A board with one city of player 0 at CENTRE (it owns its ring); the
    improvements are whatever the caller's `synthetic_improvements` block
    installed."""
    env = board()
    city = make_city(env, CENTRE)
    return env, env.players[0], city


def improve(env, positions, name):
    """Fixture only: `name` stands on every one of `positions`, through the
    tile's own writer."""
    for pos in positions:
        env.map.get_tile(tuple(pos)).add_improvement(name, map_ref=env.map)


def open_only(env, city, open_tiles, name):
    """Improve every owned tile of `city` but `open_tiles` (the centre is
    never improvable), so those are the only tiles with something to build."""
    keep = {tuple(p) for p in open_tiles} | {tuple(city.coordinates)}
    improve(env, [p for p in env.map.tiles_of_city(city.city_id) if p not in keep], name)


def new_turn(player):
    """The unit reset of `Player.start_turn`, for a loop of rounds."""
    for unit in player.units:
        unit.reset_movement()


def board_improvements(env):
    return {(t.row, t.column): list(t.improvements) for t in env.map.tiles.flat if t.improvements}


def nearer_neighbours(env, here, target):
    """The neighbours of `here` strictly nearer `target`, as sorted
    (distance, (row, col)) pairs: the geometry every step rule starts from."""
    now = env.distance_function(here, target)
    return sorted((env.distance_function(p, target), tuple(p))
                  for p in env.map.get_adjacent_coords(here)
                  if env.distance_function(p, target) < now)


def expected_step(env, unit, target):
    """Reference for one step, from the kernels: of the neighbours strictly
    nearer `target`, those passable on foot at a price the unit can pay, with
    no unit of another player and none of its own in its slot; the nearest,
    ties by (row, col); None when there is none."""
    candidates = []
    for distance, pos in nearer_neighbours(env, tuple(unit.coordinates), target):
        tile = env.map.get_tile(pos)
        if tile.impassable or tile.domain != "land" or tile.movement_cost > unit.movement_points:
            continue
        if any(u.player is not unit.player or u.slot == unit.slot for u in env.get_units_at(pos)):
            continue
        candidates.append((distance, pos))
    return min(candidates)[1] if candidates else None


def nearest_scene(env, ring1):
    """A tile W off the city's land and two ring-1 tiles, `near` strictly
    nearer to W than `far`, the farthest ring-1 tile from W. W has two
    neighbours equally near `near`, so a step has an alternative when one is
    refused and a tie to break by coordinates."""
    for distance in (3, 4, 5):
        for w in ring(env, CENTRE, distance):
            far = max(ring1, key=lambda r: (env.distance_function(w, r), r))
            for near in ring1:
                steps = nearer_neighbours(env, w, near)
                if (env.distance_function(w, near) < env.distance_function(w, far)
                        and len(steps) >= 2 and steps[0][0] == steps[1][0]):
                    return w, near, far
    raise AssertionError("fixture: no tile has a nearer ring-1 tile it can reach by two steps")


def tie_scene(env, ring1):
    """A tile W and two ring-1 tiles a < b equally near it, nearer than every
    other ring-1 tile, whose first steps toward them differ -- so the choice
    of target is visible in where the Worker goes."""
    for w in ring(env, CENTRE, 3):
        ds = sorted((env.distance_function(w, r), r) for r in ring1)
        if ds[0][0] == ds[1][0] < ds[2][0]:
            a, b = ds[0][1], ds[1][1]
            if nearer_neighbours(env, w, a)[0] != nearer_neighbours(env, w, b)[0]:
                return w, a, b
    raise AssertionError("fixture: no tile sees two ring-1 tiles equally near with different steps")


# --- Config order ----------------------------------------------------------------------


def test_improvement_order_is_the_config_order():
    """`IMPROVEMENT_ORDER`, the order every "ties by config order" reads,
    is the order of `[improvements.*]` in config.toml and names exactly
    `IMPROVEMENT_NAMES`. Breaks if the order is taken from the frozenset,
    whose iteration order changes with the process's hash seed."""
    assert terrain_model.IMPROVEMENT_ORDER == tuple(CFG["improvements"])
    assert len(set(terrain_model.IMPROVEMENT_ORDER)) == len(terrain_model.IMPROVEMENT_ORDER)
    assert frozenset(terrain_model.IMPROVEMENT_ORDER) == terrain_model.IMPROVEMENT_NAMES


# --- (a) What a Worker builds under it ---------------------------------------------------


# name -> (tables in config order, the improvement a Worker builds, why)
CHOICES = {
    "the larger gain wins over config order": (
        {"First": _table(food=1), "Second": _table(gold=2)}, "Second"),
    "food, production and gold count alike": (
        {"Food": _table(food=2), "Prod": _table(production=1), "Gold": _table(gold=1),
         "All": _table(food=1, production=1, gold=1)}, "All"),
    "housing breaks a tie in gain": (
        {"Bare": _table(gold=2), "Roofed": _table(food=2, housing=0.5)}, "Roofed"),
    "gain beats housing": (
        {"Roofed": _table(food=1, housing=3.0), "Rich": _table(gold=2)}, "Rich"),
    "config order breaks the rest (one way)": (
        {"One": _table(food=1, housing=0.5), "Two": _table(gold=1, housing=0.5)}, "One"),
    "config order breaks the rest (the other)": (
        {"Two": _table(gold=1, housing=0.5), "One": _table(food=1, housing=0.5)}, "Two"),
}


@pytest.mark.parametrize("case", sorted(CHOICES))
def test_an_idle_worker_builds_the_largest_gain_improvement_under_it(case):
    """An idle Worker standing on an owned tile in the economy phase builds,
    of what its owner may build there, the improvement with the largest
    food + production + gold, then the largest housing, then the earliest in
    config order; the build spends its movement, marks it acted and counts in
    `episode_stats["improvements_built"]`. Breaks if the ranking uses another
    key, drops one of the three yields or the housing tie-break, or ties by
    anything but config order."""
    tables, expected = CHOICES[case]
    with synthetic_improvements(tables):
        env, player, city = scene()
        pos = ring(env, CENTRE, 1)[0]
        worker = stand(env, "Worker", 0, pos)
        assert env.episode_stats[0]["improvements_built"] == 0
        env.economy_phase(player)
        assert env.map.get_tile(pos).improvements == [expected]
        assert worker.has_acted and worker.movement_points == 0
        assert env.episode_stats[0]["improvements_built"] == 1
        assert env.episode_stats[1]["improvements_built"] == 0


def test_the_improvement_gain_is_the_three_yields_then_the_housing():
    """`improvement_gain` is (food + production + gold, housing in tenths) of
    the improvement's table. Breaks if a column is left out or housing is
    scaled."""
    tables = {"X": _table(food=1, production=2, gold=4, housing=1.5), "Y": _table()}
    with synthetic_improvements(tables):
        assert improvement_gain("X") == (7, 15)
        assert improvement_gain("Y") == (0, 0)


def test_with_the_configured_improvements_the_worker_builds_a_best_one():
    """On six differently shaped owned tiles, each with a Worker on it, every
    Worker builds an improvement no other one its owner may build there beats
    on (food + production + gold, housing), and among equals the first in
    config.toml -- the columns read raw from config. Breaks if the choice
    drifts from the config columns or the order."""
    env, player, city = scene()
    shapes = [("Plains", "flat"), ("Plains", "hills"), ("Grassland", "flat"),
              ("Desert", "flat"), ("Tundra", "flat"), ("Grassland", "hills")]
    tiles = ring(env, CENTRE, 1)
    for pos, (base, relief) in zip(tiles, shapes):
        env.map.get_tile(pos).set_layers(base, relief=relief, map_ref=env.map)
        stand(env, "Worker", 0, pos)

    def key(name):
        table = CFG["improvements"][name]
        return (table.get("food", 0) + table.get("production", 0) + table.get("gold", 0),
                round(10 * table.get("housing", 0)))

    options = {pos: [n for n in CFG["improvements"]
                     if env.can_player_build_improvement_at(player, pos, n)] for pos in tiles}
    assert all(options.values()), "fixture: every shape takes some improvement"
    assert len({tuple(o) for o in options.values()}) > 1, "fixture: the shapes differ"
    env.economy_phase(player)
    for pos in tiles:
        best = options[pos][0]
        for name in options[pos][1:]:
            if key(name) > key(best):
                best = name
        assert env.map.get_tile(pos).improvements == [best], pos


def test_the_worker_builds_only_what_its_owner_knows_on_land_its_owner_holds():
    """With the gating tech unknown the Worker builds the best improvement it
    MAY build; with it known, the gated one; on a neutral tile or one owned
    by another player it builds nothing, and every improvement of the game
    stands on a tile of the player that built it. Breaks if the default
    bypasses `can_player_build_improvement_at` -- the research gate or the
    ownership test."""
    tech = research_model.TECH_ORDER[-1]
    tables = {"Plain": _table(food=1), "Gated": _table(gold=3, requires_tech=tech)}
    with synthetic_improvements(tables):
        env, player, city = scene()
        player.techs[:] = [t for t in player.techs if t != tech]
        pos = ring(env, CENTRE, 1)[0]
        stand(env, "Worker", 0, pos)
        env.economy_phase(player)
        assert env.map.get_tile(pos).improvements == ["Plain"]

        env, player, city = scene()
        pos = ring(env, CENTRE, 1)[0]
        stand(env, "Worker", 0, pos)
        env.economy_phase(player)
        assert env.map.get_tile(pos).improvements == ["Gated"]

        env, player, city = scene()
        rival = make_city(env, (3, 12), player_index=1)
        theirs = ring(env, rival.coordinates, 1)[0]
        neutral = (6, 8)
        assert env.map.owner_id_at(theirs) == rival.city_id
        assert env.map.owner_id_at(neutral) == -1
        for pos in (theirs, neutral):
            stand(env, "Worker", 0, pos)
        env.economy_phase(player)
        assert board_improvements(env) == {}


def test_a_tile_never_holds_two_improvements_under_the_default():
    """Over many rounds, with two improvements both placeable everywhere,
    every owned tile ends with exactly one improvement and none with two; the
    Workers then have nothing to do and stay idle. The engine's tile predicate
    lets several stack (housing design) -- the default does not use it.
    Breaks if the default improves an improved tile, or never finishes."""
    tables = {"A": _table(food=1), "B": _table(gold=1)}
    with synthetic_improvements(tables):
        env, player, city = scene()
        for _ in range(2):
            assert city.complete_unit_production("Worker", env)
        for _ in range(12):
            new_turn(player)
            env.economy_phase(player)
        owned = [p for p in env.map.tiles_of_city(city.city_id) if p != CENTRE]
        assert sorted(board_improvements(env)) == sorted(owned)
        assert all(len(v) == 1 for v in board_improvements(env).values())
        assert env.episode_stats[0]["improvements_built"] == len(owned)
        new_turn(player)
        before = [(u.coordinates, u.movement_points) for u in player.units]
        env.economy_phase(player)
        assert [(u.coordinates, u.movement_points) for u in player.units] == before
        assert not any(u.has_acted for u in player.units)


def test_a_worker_never_improves_a_city_centre_or_a_district_tile():
    """A Worker on its city's centre and one on a district tile build
    nothing there, and neither tile is among the targets. Breaks if the
    default ignores the tile predicate's centre and district refusals."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        district_tile = ring(env, CENTRE, 1)[0]
        assert env.place_district(city, placeable_type(), district_tile)
        centre_worker = stand(env, "Worker", 0, CENTRE)
        district_worker = stand(env, "Worker", 0, district_tile)
        assert best_improvement(player, CENTRE, env) is None
        assert best_improvement(player, district_tile, env) is None
        assert CENTRE not in list(worker_targets(player, env))
        assert district_tile not in list(worker_targets(player, env))
        env.economy_phase(player)
        assert env.map.get_tile(CENTRE).improvements == []
        assert env.map.get_tile(district_tile).improvements == []
        assert centre_worker.coordinates != tuple(CENTRE), "it walked off to where it can work"
        assert district_worker.coordinates != tuple(district_tile)


# --- (b) The step toward the nearest tile ---------------------------------------------------


def _walker(monkeypatch, env, worker):
    """Spy on `worker.move` and forbid every pathfinder: the default must
    move only through `Unit.move`'s adjacent step."""
    moves = []
    real = worker.move

    def spy(destination, game_env):
        moves.append(tuple(destination))
        return real(destination, game_env)

    def boom(*args, **kwargs):
        raise AssertionError("the Worker default used a pathfinder")

    monkeypatch.setattr(worker, "move", spy)
    monkeypatch.setattr(env, "path_finder", boom)
    monkeypatch.setattr(env.map, "path_finder", boom)
    return moves


def test_a_worker_steps_toward_the_nearest_improvable_owned_tile_through_unit_move(monkeypatch):
    """With only two owned tiles open, a Worker standing off its land takes
    ONE step, through `Unit.move`, onto the neighbour nearest the nearer of
    the two (the nearest first, ties by coordinates), pays that tile's cost
    from its movement and does not build that turn; no pathfinder is used.
    Breaks if it targets the farther tile, jumps, wanders, builds on arrival
    in the same turn, or calls `path_finder`."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        w, near, far = nearest_scene(env, ring(env, CENTRE, 1))
        open_only(env, city, [near, far], "Plot")
        worker = stand(env, "Worker", 0, w)
        moves = _walker(monkeypatch, env, worker)
        assert worker_target(worker, env) == near
        step = expected_step(env, worker, near)
        before = worker.movement_points
        env.economy_phase(player)
        assert moves == [step] and worker.coordinates == step
        assert env.distance_function(step, near) == env.distance_function(w, near) - 1
        assert before - worker.movement_points == env.map.get_tile(step).movement_cost
        assert board_improvements(env) == {
            p: ["Plot"] for p in env.map.tiles_of_city(city.city_id) if p not in (near, far, CENTRE)}


def test_equally_near_targets_are_broken_by_coordinates_and_the_step_by_coordinates(monkeypatch):
    """Of two equally near open tiles the Worker heads for the one with the
    smaller (row, col): its first step is the step toward that tile, which a
    step toward the other would not be. Breaks if ties go by config order,
    set order, or the larger coordinates."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        w, a, b = tie_scene(env, ring(env, CENTRE, 1))
        assert a < b
        open_only(env, city, [a, b], "Plot")
        worker = stand(env, "Worker", 0, w)
        assert worker_target(worker, env) == a
        first_a = expected_step(env, worker, a)
        assert first_a != expected_step(env, worker, b)
        env.economy_phase(player)
        assert worker.coordinates == first_a


@pytest.mark.parametrize("blocker", ["a foreign unit", "terrain it cannot pay for", "an own civilian"])
def test_a_step_never_lands_where_unit_move_would_refuse(blocker):
    """A neighbour that is strictly nearer but holds a foreign unit, an own
    unit in the Worker's slot or costs more than the Worker's movement is not
    stepped onto: the Worker takes the next best neighbour, or stays. Breaks
    if the step ignores occupancy, slots or the price (the `Unit.move`
    preconditions the step must share)."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        w, near, far = nearest_scene(env, ring(env, CENTRE, 1))
        open_only(env, city, [near], "Plot")
        worker = stand(env, "Worker", 0, w)
        blocked = expected_step(env, worker, near)
        tile = env.map.get_tile(blocked)
        if blocker == "a foreign unit":
            warrior = stand(env, "Warrior", 1, blocked)
        elif blocker == "an own civilian":
            stand(env, "Settler", 0, blocked)
        else:
            tile.set_layers("Plains", relief="hills", feature="Woods", map_ref=env.map)
            assert tile.movement_cost > worker.movement_points, "fixture: too dear"
        expected = expected_step(env, worker, near)
        assert expected != blocked
        env.economy_phase(player)
        assert worker.coordinates == (expected if expected is not None else w)
        assert worker.coordinates != blocked
        if blocker == "a foreign unit":
            assert warrior.coordinates == blocked and warrior.health == 100


def test_a_worker_with_every_nearer_neighbour_blocked_stays_instead_of_stepping_sideways():
    """A step must bring the Worker strictly nearer its target: with every
    nearer neighbour held by a foreign unit it stays put, though neighbours at
    the same distance are free. Breaks if a sideways or backward step is ever
    taken (the Worker would shuffle forever beside a blocked path)."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        w, near, far = nearest_scene(env, ring(env, CENTRE, 1))
        open_only(env, city, [near], "Plot")
        worker = stand(env, "Worker", 0, w)
        for _, pos in nearer_neighbours(env, w, near):
            stand(env, "Warrior", 1, pos)
        sideways = [p for p in env.map.get_adjacent_coords(w)
                    if env.distance_function(p, near) == env.distance_function(w, near)
                    and not env.get_units_at(p)]
        assert sideways, "fixture: a free neighbour at the same distance"
        env.economy_phase(player)
        assert worker.coordinates == w and worker.movement_points == worker.get_max_movement()


def test_a_worker_does_not_head_for_a_tile_another_worker_stands_on_or_chose_earlier(monkeypatch):
    """(i) An own Worker standing on the nearest open tile makes it no
    target: the other Worker's target is the next nearest. (ii) Idle Workers
    of one pass choose different targets -- the later one never takes a tile
    an earlier one already chose -- so Workers that start together spread
    out. Breaks if a tile under a Worker, or one already chosen, is offered
    again."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        ring1 = ring(env, CENTRE, 1)
        w, near, far = nearest_scene(env, ring1)
        open_only(env, city, ring1[:3], "Plot")
        open_tiles = ring1[:3]
        worker = stand(env, "Worker", 0, w)
        nearest = min(open_tiles, key=lambda p: (env.distance_function(w, p), p))
        assert worker_target(worker, env) == nearest
        sitter = stand(env, "Worker", 0, nearest)
        sitter.has_acted = True            # at work there, not idle
        assert nearest not in list(worker_targets(player, env))
        second = min((p for p in open_tiles if p != nearest),
                     key=lambda p: (env.distance_function(w, p), p))
        assert worker_target(worker, env) == second

    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        ring1 = ring(env, CENTRE, 1)
        open_only(env, city, ring1[:3], "Plot")
        first = stand(env, "Worker", 0, ring(env, CENTRE, 3)[0])
        later = stand(env, "Worker", 0, ring(env, CENTRE, 3)[1])
        targets = []
        real = defaults.step_toward
        monkeypatch.setattr(defaults, "step_toward",
                            lambda unit, target, game_env: (targets.append((unit, target)),
                                                            real(unit, target, game_env))[1])
        assert default_workers(player, env) == 0
        assert [u for u, _ in targets] == [first, later]
        assert targets[0][1] != targets[1][1], "the later Worker took the earlier one's target"
        open_set = {tuple(p) for p in ring1[:3]}
        assert {t for _, t in targets} <= open_set
        nearest_first = min(open_set, key=lambda p: (env.distance_function(first.coordinates, p), p))
        assert targets[0][1] == nearest_first


def test_when_every_open_tile_is_claimed_a_later_worker_takes_the_nearest_claimed_one(monkeypatch):
    """With a single open tile, every idle Worker of the pass heads for it:
    the claim of an earlier Worker only steers a later one to ANOTHER tile
    when another is open. Breaks if a Worker idles while a tile can be
    reached (the first Worker would hold the tile its blocked way never
    reaches, and the Worker next to it would never be sent)."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        w, near, far = nearest_scene(env, ring(env, CENTRE, 1))
        open_only(env, city, [near], "Plot")
        first = stand(env, "Worker", 0, w)
        later = stand(env, "Worker", 0, next(p for p in ring(env, CENTRE, 3) if p != w))
        targets = []
        real = defaults.step_toward
        monkeypatch.setattr(defaults, "step_toward",
                            lambda unit, target, game_env: (targets.append((unit, target)),
                                                            real(unit, target, game_env))[1])
        default_workers(player, env)
        assert [(u, t) for u, t in targets] == [(first, near), (later, near)]


def test_a_crowd_of_workers_improves_every_open_tile_and_none_is_left_behind():
    """Six Workers on a city that owns three rings of tiles improve every one
    of them within a bounded number of rounds, whatever order the Workers
    stand in and however they block each other's way, and then stay idle.
    Breaks if the default can deadlock: a Worker with a blocked way holding
    the last tile while the Workers nearest it have nothing to aim at (found
    by this very scene: 35 of 36 tiles built and nobody moving, for ever)."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        for distance in (2, 3):
            for pos in ring(env, CENTRE, distance):
                own(env, city, pos)
        owned = [p for p in env.map.tiles_of_city(city.city_id) if p != CENTRE]
        assert len(owned) > 30, "fixture: a wide territory"
        for _ in range(6):
            assert city.complete_unit_production("Worker", env)
        for rounds in range(1, 41):
            new_turn(player)
            env.economy_phase(player)
            if env.episode_stats[0]["improvements_built"] == len(owned):
                break
        assert sorted(board_improvements(env)) == sorted(owned), rounds
        new_turn(player)
        env.economy_phase(player)
        assert not any(u.has_acted for u in player.units)


# --- (c) Nothing to do -> it stays ---------------------------------------------------------


@pytest.mark.parametrize("why", ["everything improved", "nothing it may build", "no land"])
def test_a_worker_with_nothing_to_do_stays(why):
    """A Worker whose owner holds no tile where it may build -- every tile
    improved, the only improvement gated by an unknown tech, or no city at
    all -- keeps its place and its full movement, has not acted and builds
    nothing. Breaks if it wanders aimlessly, or builds over an improvement."""
    tech = research_model.TECH_ORDER[-1]
    tables = {"Plot": _table(food=1, requires_tech=tech) if why == "nothing it may build"
              else _table(food=1)}
    with synthetic_improvements(tables):
        env, player, city = scene()
        owner = 0
        if why == "everything improved":
            improve(env, [p for p in env.map.tiles_of_city(city.city_id) if p != CENTRE], "Plot")
        elif why == "nothing it may build":
            player.techs[:] = [t for t in player.techs if t != tech]
        else:
            owner = 1
        mover = env.players[owner]
        worker = stand(env, "Worker", owner, ring(env, CENTRE, 2)[0])
        snapshot = board_improvements(env)
        here, mp = worker.coordinates, worker.movement_points
        assert not worker_has_work(mover)
        env.economy_phase(mover)
        assert worker.coordinates == here and worker.movement_points == mp
        assert not worker.has_acted
        assert board_improvements(env) == snapshot
        assert env.episode_stats[owner]["improvements_built"] == 0


# --- (d) A Worker that acted or moved is untouched ---------------------------------------------


@pytest.mark.parametrize("state", ["acted", "partly moved", "ordered to move"])
def test_a_worker_that_already_acted_or_moved_is_left_alone(state):
    """A Worker that has acted this turn, one without its full movement, and
    one an agent already moved is untouched by the default -- even standing
    on a tile it could improve: no build, no step. Breaks if "idle" is
    anything but full movement and not having acted."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        pos = ring(env, CENTRE, 1)[0]
        worker = stand(env, "Worker", 0, pos)
        if state == "acted":
            worker.has_acted = True
        elif state == "partly moved":
            worker.movement_points -= 1
        else:
            moved, where = worker.move(ring(env, CENTRE, 1)[1], env)
            assert moved
            pos = where
        here, mp, acted = worker.coordinates, worker.movement_points, worker.has_acted
        snapshot = board_improvements(env)
        env.economy_phase(player)
        assert (worker.coordinates, worker.movement_points, worker.has_acted) == (here, mp, acted)
        assert board_improvements(env) == snapshot
        assert env.episode_stats[0]["improvements_built"] == 0


# --- (h) One step rule for every walking default -------------------------------------------------


def test_the_trader_and_the_worker_defaults_share_one_step_rule(monkeypatch):
    """`defaults.step_toward` is called for a Trader away from home and for a
    Worker with a target, in one economy phase; neither default scans the
    neighbours or calls a pathfinder itself. Breaks if either default grows
    its own copy of the step rule (the P5 Trader step and the Worker's would
    then drift)."""
    calls = []
    real = defaults.step_toward

    def spy(unit, target, env):
        calls.append(unit.unit_type)
        return real(unit, target, env)

    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        monkeypatch.setattr(defaults, "step_toward", spy)
        stand(env, TRADER_UNIT, 0, ring(env, CENTRE, 3)[0])
        stand(env, "Worker", 0, ring(env, CENTRE, 3)[1])
        env.economy_phase(player)
    assert TRADER_UNIT in calls and "Worker" in calls

    tree = ast.parse(textwrap.dedent(inspect.getsource(defaults)))
    functions = {f.name: f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)}
    for name in ("trader_step", "default_workers"):
        called = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
                  for n in ast.walk(functions[name]) if isinstance(n, ast.Call)}
        assert "step_toward" in called, name
        assert not called & {"get_adjacent_coords", "path_finder", "step_cost"}, name


# --- (f) The offer: mask, production and purchase read one predicate ---------------------------------


def _offers(env, city, player):
    """(mask, produce_unit, purchase) for a Worker, each as a bool, from a
    board left as it was (the purchase's Worker is deleted again)."""
    mask = bool(get_valid_build_mask(city)[WORKER_INDEX])
    before = city.current_production
    produced = city.produce_unit("Worker")
    assert produced or city.current_production == before, "a refusal changed production"
    city.current_production = before
    player.gold = 10 ** 6
    units = list(player.units)
    bought = env.purchase(city, "unit", "Worker", "gold")
    for unit in [u for u in player.units if u not in units]:
        env.delete_unit(unit)
    return mask, produced, bought


def test_a_worker_is_offered_produced_and_bought_exactly_while_there_is_work():
    """The build mask, `produce_unit` and `purchase` agree, and offer a Worker
    exactly while its owner holds a tile it could improve that no Worker of
    the player and no foreign unit stands on and the owner may build on --
    not with every tile improved, not with the only open tile taken by a
    Worker or a foreign unit, not while the only improvement waits for an
    unknown tech. Breaks if a Worker with nothing to build is offered (the
    mask invariant, #51), or the three paths read different predicates."""
    tech = research_model.TECH_ORDER[-1]

    def check(setup, expected, tables=None):
        with synthetic_improvements(tables or {"Plot": _table(food=1)}):
            env, player, city = scene()
            city.population = 3
            setup(env, player, city)
            assert _offers(env, city, player) == (expected,) * 3
            assert worker_has_work(player) is expected

    def one_open(env, city):
        tile = ring(env, CENTRE, 1)[0]
        open_only(env, city, [tile], "Plot")
        return tile

    check(lambda env, p, c: None, True)
    check(lambda env, p, c: improve(env, [q for q in env.map.tiles_of_city(c.city_id)], "Plot"), False)
    check(lambda env, p, c: one_open(env, c), True)
    check(lambda env, p, c: stand(env, "Worker", 0, one_open(env, c)), False)
    check(lambda env, p, c: stand(env, "Warrior", 1, one_open(env, c)), False)
    check(lambda env, p, c: stand(env, "Warrior", 0, one_open(env, c)), True)
    check(lambda env, p, c: p.techs.remove(tech), False,
          {"Plot": _table(food=1, requires_tech=tech)})
    check(lambda env, p, c: None, True, {"Plot": _table(food=1, requires_tech=tech)})


def test_work_is_the_open_owned_tiles_without_a_worker_or_a_foreign_unit_in_a_fixed_order():
    """`worker_targets` yields exactly the owned tiles that are not a centre,
    hold no district or improvement and no unit of another player or own
    Worker, where an improvement may be built -- in (city id, row, col)
    order. Breaks if a filter is dropped or the order depends on set or dict
    iteration."""
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, first = scene()
        second = make_city(env, (3, 10))
        for pos in ring(env, second.coordinates, 2)[:2]:
            own(env, second, pos)
        ring1 = ring(env, CENTRE, 1)
        improve(env, ring1[:1], "Plot")
        stand(env, "Worker", 0, ring1[1])
        stand(env, "Warrior", 1, ring1[2])
        stand(env, "Warrior", 0, ring1[3])       # an own non-Worker does not block
        assert env.place_district(first, placeable_type(), ring1[4])
        expected = []
        for city in sorted(player.cities, key=lambda c: c.city_id):
            for pos in sorted(env.map.tiles_of_city(city.city_id)):
                if pos == tuple(city.coordinates) or pos in (ring1[0], ring1[1], ring1[2], ring1[4]):
                    continue
                expected.append(pos)
        assert list(worker_targets(player, env)) == expected
        assert ring1[3] in expected and ring1[5] in expected
        assert buildable_here(player, ring1[0], env) == []
        assert buildable_here(player, (7, 15), env) == []


def test_the_worker_is_appended_to_the_build_options():
    """The Worker is a build option, no longer deferred, and BUILD_OPTIONS
    stays append-only: the options of the version before P8 are its prefix,
    so an archived build head's indices keep their meaning (#67). Breaks if
    the Worker is inserted, or listed as deferred too."""
    pre_p8 = [
        "Warrior", "Spearman", "Archer", "Horseman", "Catapult",
        "Settler", "Granary", "Slinger", "Swordsman", "Walls",
        "Monument", "Library", "University", "Shrine", "Barracks",
        "Medieval Walls", "Workshop",
        "Man-At-Arms", "Pikeman", "Crossbowman", "Knight", "Trebuchet",
        "Musketman",
        "Temple", "Amphitheater", "Ancestral Hall", "Grand Master's Chapel",
        "Market", "Lighthouse", "Trader",
    ]
    assert BUILD_OPTIONS[:len(pre_p8)] == pre_p8
    assert "Worker" in BUILD_OPTIONS[len(pre_p8):]
    assert "Worker" not in DEFERRED_BUILD_UNITS
    assert UNIT_CLASSES["Worker"] is WorkerUnit


# --- (e) Determinism ----------------------------------------------------------------------------------------


GAME = '''
import sys
sys.path.insert(0, {root!r})
sys.path.insert(0, {tests!r})
from conftest import grant_all
from civulator.game.environment import GameEnvironment


def play(seed, rounds):
    """Two players who know everything and have two Workers each, left to the
    engine defaults for `rounds` rounds: the improvements standing at the end
    and what each player's counter says."""
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for player in env.players:
        grant_all(player)
        for _ in range(2):
            assert player.cities[0].complete_unit_production("Worker", env)
    for _ in range(2 * rounds):
        env.next_turn()
    standing = [(int(t.row), int(t.column), tuple(t.improvements))
                for t in env.map.tiles.flat if t.improvements]
    return standing, [env.episode_stats[i]["improvements_built"] for i in range(2)]
'''
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(TESTS_DIR)
SEED, ROUNDS = 11, 12


def _play_here(seed=SEED, rounds=ROUNDS):
    namespace = {}
    exec(GAME.format(root=ROOT_DIR, tests=TESTS_DIR), namespace)
    return namespace["play"](seed, rounds)


def test_two_same_seed_games_build_identical_improvements():
    """Two games from one seed, left to the defaults, end with the same
    improvements on the same tiles and the same counts; some are built (the
    default is live). A different seed gives a different world. Breaks if the
    default depends on randomness, on set or dict iteration, or on state
    that survives `reset`."""
    first, second = _play_here(), _play_here()
    assert first == second
    assert sum(first[1]) > 0 and first[0]
    assert _play_here(seed=SEED + 1) != first


@pytest.mark.parametrize("hash_seed", ["1", "2"])
def test_the_improvements_built_do_not_depend_on_the_hash_seed(hash_seed):
    """A fresh process with another PYTHONHASHSEED builds exactly the same
    improvements from the same seed: no tie is decided by the iteration order
    of a set of names (improvements are ranked, ties go to config order).
    Breaks if `IMPROVEMENT_NAMES` (a frozenset) or any hash-ordered container
    decides a choice."""
    code = GAME.format(root=ROOT_DIR, tests=TESTS_DIR) + f"print(play({SEED}, {ROUNDS}))\n"
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env={**os.environ, "PYTHONHASHSEED": hash_seed}, timeout=300)
    assert run.returncode == 0, run.stderr[-2000:]
    assert run.stdout.strip() == str(_play_here())


# --- (g) A real game -----------------------------------------------------------------------------------------------


BOUND = 8


def test_a_seeded_game_builds_improvements_within_a_bounded_number_of_rounds():
    """From a seeded world, two players who know everything and have two
    Workers each have each built an improvement within a few rounds of the
    defaults alone, every improvement standing is one of the counted builds
    (nothing else builds), and a reset zeroes the counters. Breaks if the
    default is dormant, the counter drifts from the board, or the counter is
    not reset with the episode."""
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=SEED)
    for player in env.players:
        grant_all(player)
        for _ in range(2):
            assert player.cities[0].complete_unit_production("Worker", env)
    for _ in range(2 * BOUND):
        env.next_turn()
    built = [env.episode_stats[i]["improvements_built"] for i in range(2)]
    assert all(b > 0 for b in built), built
    assert len(board_improvements(env)) == sum(built)
    assert all(len(v) == 1 for v in board_improvements(env).values())
    env.reset(seed=SEED)
    assert [env.episode_stats[i]["improvements_built"] for i in range(2)] == [0, 0]
    assert board_improvements(env) == {}


def _worker_wonder():
    """(wonder, Workers it frees) of some configured wonder whose one-shot
    effects free Workers."""
    for name, spec in district_model.DISTRICTS.items():
        if spec.kind != district_model.KIND_WONDER:
            continue
        for effect in one_shot_effects(name):
            if effect.kind == KIND_FREE_UNITS:
                count = sum(c for unit, c in effect["units"] if UNIT_CLASSES[unit] is WorkerUnit)
                if count:
                    return name, count
    pytest.skip("no configured wonder frees Workers")


def test_the_free_workers_of_a_wonder_go_to_work():
    """The Workers a wonder frees on completion are live: in the same turn's
    economy phase and the rounds after, each goes to an open tile and builds,
    within a bounded number of rounds. Breaks if freed Workers stand idle
    (the Worker default is dormant for units that did not come from
    production)."""
    wonder, count = _worker_wonder()
    env = board()
    player = env.players[0]
    city = make_city(env, CENTRE, population=3)
    pos = next(p for p in ring(env, CENTRE, 1) if can_place_district(city, wonder, p))
    assert env.place_district(city, wonder, pos)
    district = next(d for d in city.districts if d.type == wonder)
    env.complete_district(city, district)
    workers = [u for u in player.units if isinstance(u, WorkerUnit)]
    assert len(workers) + sum(1 for _, t in player.queued_units
                              if UNIT_CLASSES[t] is WorkerUnit) == count
    assert workers
    for _ in range(BOUND):
        env.economy_phase(player)
        new_turn(player)
    assert env.episode_stats[0]["improvements_built"] >= len(workers)
    assert env.map.get_tile(CENTRE).improvements == []
    assert env.map.get_tile(pos).improvements == [], "the wonder's own tile"


def test_a_built_improvement_adds_its_housing_to_the_city():
    """The accepted gap of the housing design is closed: a Worker's
    improvement raises the housing of the city that owns the tile by exactly
    the improvement's `housing`. Breaks if the default builds without the
    housing reader seeing the improvement."""
    with synthetic_improvements({"Roofed": _table(food=1, housing=0.5)}):
        env, player, city = scene()
        before = housing(city)
        stand(env, "Worker", 0, ring(env, CENTRE, 1)[0])
        env.economy_phase(player)
        assert terrain_model.IMPROVEMENT_HOUSING["Roofed"] == 5
        assert housing(city) == before + 5
