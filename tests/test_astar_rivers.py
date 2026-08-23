"""Tests for river-edge costs in A* (design doc §11 P6, E3, D23).

Both A* implementations (civulator_core's C++ hex_astar and Map._python_astar)
must now charge [terrain.river] crossing_cost when a step crosses a flagged
river edge — the same per-edge surcharge unit.move already charges
(RIVER_CROSSING_COST in unit.py) — so planned path costs equal executed
charges. Oracle lettering below matches the P6 task list (design doc §11):
(a) planned cost == executed charges, incl. detour-vs-crossing preference,
(b) empty rivers regress to pre-P6 behavior,
(c) C++ ≡ Python over random earthlike worlds,
(d) cache invalidation on add_river,
(e) full suite green — verified by running the whole suite, not here.
"""

import collections

import pytest

from civulator import hexmath
from civulator.config import CFG
from civulator.game.map import BLOCKED_COST, HAS_CPP_CORE, Map, _river_crossing_cost
from civulator.game.unit import RIVER_CROSSING_COST, WarriorUnit
from civulator.rng import PortableRNG

from test_combat_range import make_flat_env, place

DUEL_ROWS, DUEL_COLS = 12, 24  # design doc §6: earthlike minimum size (E5)
N_PARITY_WORLDS = 20


def _paint(env, coords, base, relief=None, feature=None):
    env.map.get_tile(coords).set_layers(base, relief=relief, feature=feature, map_ref=env.map)


def _path_cost(map_obj, start, path, domain):
    """Ground-truth cost of a path: tile movement_cost (via the SAME cached
    cost grid path_finder uses) plus RIVER_CROSSING_COST wherever
    has_river_between says a step crosses a river. Deliberately independent
    of _river_flags_grid/_river_crossing_cost — this is the oracle those are
    checked against, not a restatement of them. `path` excludes `start`
    (path_finder's own contract), so `start` is passed separately.
    """
    crossing_cost = CFG.get("terrain", {}).get("river", {}).get("crossing_cost", 1)
    cost_grid = map_obj._build_cost_grid(domain)
    prev = tuple(int(x) for x in start)
    total = 0.0
    for step in path:
        cur = tuple(int(x) for x in step)
        total += float(cost_grid[cur[0], cur[1] % map_obj.m])
        if map_obj.has_river_between(prev, cur):
            total += crossing_cost
        prev = cur
    return total


def _build_ford_wall(env):
    """A 3-column-wide impassable wall (columns 7-9) across an 8x16 flat
    board, open only at row 4 (a river-crossed "ford") and row 0 (a longer
    dry detour). 3 columns thick so the only way through the wall at row 4
    is straight through the flagged edge (4,7)-(4,8) — a single-column wall
    lets a path sneak into the ford tile diagonally from an unwalled
    neighbor column, entering (4,8) without ever taking the flagged step.
    Requires env from make_flat_env(n=8, m=16).
    """
    for r in range(env.n):
        if r not in (0, 4):
            for c in (7, 8, 9):
                _paint(env, (r, c), "Plains", relief="mountain")
    env.map.add_river((4, 7), (4, 8))


# --- Bit layout (deliverable 1) ---------------------------------------------


def test_river_edge_flags_cover_all_six_directions():
    """Every one of the 6 hex directions must be correctly encoded whether
    OWNED by the center tile or MIRRORED via the neighbor (RIVER_EDGE_
    DIRECTIONS' first 3 vs last 3 in map.py) — a bug in either branch would
    only surface for edges going "the other way".
    """
    env = make_flat_env(n=9, m=18)
    center = (4, 8)
    for dr, dc in hexmath.HEX_DIRECTIONS:
        neighbor = (center[0] + dr, (center[1] + dc) % env.m)
        env.map.add_river(center, neighbor)

    flags = env.map._river_flags_grid()
    for dr, dc in hexmath.HEX_DIRECTIONS:
        neighbor = (center[0] + dr, (center[1] + dc) % env.m)
        assert env.map.has_river_between(center, neighbor)  # ground truth sanity
        cost = _river_crossing_cost(flags, center, neighbor, env.m, 7)
        assert cost == 7, f"direction ({dr},{dc}) not correctly flagged"


# --- (a) planned cost == executed charges; crossing vs. detour preference ---


def test_astar_prefers_river_crossing_when_cheap_and_matches_execution():
    env = make_flat_env(n=8, m=16)
    _build_ford_wall(env)
    warrior = place(env, WarriorUnit, 0, (4, 6))
    warrior.movement_points = 9999

    path = env.map.path_finder((4, 6), (4, 10), domain="land")
    coords = [tuple(int(x) for x in s) for s in path]

    assert (4, 8) in coords, "the short ford through the river beats the long way around"
    assert (0, 8) not in coords, "at the default crossing cost, the detour should lose"

    planned = _path_cost(env.map, (4, 6), coords, "land")
    before = warrior.movement_points
    for step in coords:
        moved, pos = warrior.move(step, env)
        assert moved, f"executor refused a step the planner offered: now at {pos}, wanted {step}"
    executed = before - warrior.movement_points

    assert executed == planned == len(coords) + RIVER_CROSSING_COST


def test_astar_prefers_dry_detour_when_crossing_is_expensive(monkeypatch):
    env = make_flat_env(n=8, m=16)
    _build_ford_wall(env)

    cheap_path = env.map.path_finder((4, 6), (4, 10), domain="land")

    # Config read fresh per path_finder call (design doc §11 P6 deliverable 2)
    # — this monkeypatch would be invisible to a frozen-at-import constant.
    monkeypatch.setitem(CFG["terrain"]["river"], "crossing_cost", 10)
    path = env.map.path_finder((4, 6), (4, 10), domain="land")
    coords = [tuple(int(x) for x in s) for s in path]

    assert (0, 8) in coords, "the longer dry detour should win once crossing costs 10"
    assert (4, 8) not in coords, "the ford should now be avoided entirely"
    assert len(coords) > len(cheap_path), "the winning route is a genuinely longer detour"

    # This route never crosses a river, so its executed cost equals its
    # planned cost regardless of unit.py's RIVER_CROSSING_COST (frozen at
    # import time, unaffected by this test's monkeypatch either way).
    warrior = place(env, WarriorUnit, 0, (4, 6))
    warrior.movement_points = 9999
    planned = _path_cost(env.map, (4, 6), coords, "land")
    before = warrior.movement_points
    for step in coords:
        moved, pos = warrior.move(step, env)
        assert moved, f"executor refused a step the planner offered: now at {pos}, wanted {step}"
    executed = before - warrior.movement_points

    assert executed == planned == len(coords)


# --- (b) empty rivers regress to pre-P6 behavior ----------------------------


def test_no_rivers_matches_pre_p6_behavior():
    env = make_flat_env(n=8, m=16)
    assert env.map.rivers == {}
    assert not env.map._river_flags_grid().any()

    start, goal = (2, 2), (2, 6)
    path = env.map.path_finder(start, goal, domain="land")
    coords = [tuple(int(x) for x in s) for s in path]

    assert len(coords) == env.map.distance_function(start, goal)
    assert _path_cost(env.map, start, coords, "land") == len(coords), \
        "1 per flat tile, 0 crossings — unchanged from before P6"


# --- (d) cache invalidation --------------------------------------------------


def test_river_flags_cache_invalidated_by_add_river():
    env = make_flat_env(n=8, m=16)
    flags_before = env.map._river_flags_grid()
    assert env.map._river_flags_grid() is flags_before, "unchanged rivers reuse the grid"
    assert not flags_before.any()

    env.map.add_river((3, 5), (3, 6))

    flags_after = env.map._river_flags_grid()
    assert flags_after is not flags_before, "add_river bumps terrain_epoch, dropping the cache"
    assert flags_after.any()


def test_path_finder_picks_up_a_new_river_immediately():
    env = make_flat_env(n=8, m=16)
    start, goal = (3, 5), (3, 6)

    before_path = env.map.path_finder(start, goal, domain="land")
    assert _path_cost(env.map, start, before_path, "land") == 1  # one flat tile, no crossing

    env.map.add_river(start, goal)

    after_path = env.map.path_finder(start, goal, domain="land")
    assert _path_cost(env.map, start, after_path, "land") == 1 + RIVER_CROSSING_COST, \
        "the cache must not still be serving the pre-river grid"


# --- (c) C++ vs Python parity over random earthlike worlds ------------------


def _largest_landmass(map_obj, cost_grid):
    """BFS connected components over domain-passable tiles, using the SAME
    adjacency pathfinding uses; returns the largest one. Picking arbitrary
    corners on a small earthlike world often lands on two different
    islands — a valid (both-agree-on-no-path) but uninteresting comparison
    — so the parity oracle below restricts itself to one guaranteed-
    reachable landmass per world.
    """
    rows, cols = cost_grid.shape
    seen = set()
    best = []
    for r in range(rows):
        for c in range(cols):
            if cost_grid[r, c] >= BLOCKED_COST or (r, c) in seen:
                continue
            comp = []
            queue = collections.deque([(r, c)])
            seen.add((r, c))
            while queue:
                cur = queue.popleft()
                comp.append(cur)
                for nb in map_obj.get_adjacent_coords(cur):
                    if nb not in seen and cost_grid[nb[0], nb[1] % cols] < BLOCKED_COST:
                        seen.add(nb)
                        queue.append(nb)
            if len(comp) > len(best):
                best = comp
    return best


def _spread_pairs(component):
    """Two well-separated (start, goal) pairs within one connected
    component (extremes along the two diagonals), so the parity oracle
    exercises long, varied routes instead of trivial adjacent hops."""
    if len(component) < 2:
        return []
    by_sum = sorted(component, key=lambda rc: rc[0] + rc[1])
    by_diff = sorted(component, key=lambda rc: rc[0] - rc[1])
    pairs = [(by_sum[0], by_sum[-1]), (by_diff[0], by_diff[-1])]
    return [(a, b) for a, b in pairs if a != b]


@pytest.mark.skipif(
    not HAS_CPP_CORE,
    reason="civulator_core C++ module not built in this worktree",
)
def test_cpp_matches_python_over_random_earthlike_worlds_with_rivers():
    """Design doc §11 P6 deliverable 5(c): C++ hex_astar and the Python
    fallback must agree on both total cost and the exact path (not merely
    tied costs via a different route — see module docstring) over many
    river-bearing worlds, not just the constructed cases above.
    """
    import civulator_core

    compared = 0
    total_rivers = 0
    river_crossings_exercised = 0

    for seed in range(N_PARITY_WORLDS):
        m = Map(DUEL_ROWS, DUEL_COLS, rng=PortableRNG(seed))
        m.generate_map(map_type="earthlike", num_players=2)
        total_rivers += len(m.rivers)

        cost_grid = m._build_cost_grid("land")
        river_flags = m._river_flags_grid()
        crossing_cost = float(CFG.get("terrain", {}).get("river", {}).get("crossing_cost", 1))
        component = _largest_landmass(m, cost_grid)

        for start, goal in _spread_pairs(component):
            occupied = m._build_occupied_grid(goal)

            py_path = m._python_astar(start, goal, cost_grid, occupied, river_flags, crossing_cost)
            path_tuples, cpp_total = civulator_core.hex_astar(
                cost_grid, start[1], start[0], goal[1], goal[0],
                occupied, river_flags, crossing_cost,
            )
            cpp_coords = [] if cpp_total < 0 else [(r, q) for q, r in path_tuples]
            py_coords = [tuple(int(x) for x in s) for s in py_path]
            compared += 1

            assert bool(py_coords) == bool(cpp_coords), (
                f"seed={seed} {start}->{goal}: reachability mismatch "
                f"python={bool(py_coords)} cpp={bool(cpp_coords)}"
            )
            if not py_coords:
                continue

            py_cost = _path_cost(m, start, py_coords, "land")
            cpp_cost = _path_cost(m, start, cpp_coords, "land")
            assert py_cost == cpp_cost, (
                f"seed={seed} {start}->{goal}: total cost mismatch "
                f"python={py_cost} cpp={cpp_cost}"
            )
            assert py_coords == cpp_coords, (
                f"seed={seed} {start}->{goal}: same cost ({py_cost}) but "
                f"different path — python={py_coords} cpp={cpp_coords}"
            )

            prev = start
            for step in py_coords:
                if m.has_river_between(prev, step):
                    river_crossings_exercised += 1
                prev = step

    assert compared >= N_PARITY_WORLDS, "sanity: at least one comparable pair per world"
    assert total_rivers > 0, "sanity: earthlike worlds should generate rivers"
    assert river_crossings_exercised > 0, "sanity: the oracle should exercise actual crossings"
