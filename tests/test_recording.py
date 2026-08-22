"""Tests for the Order Recorder core (civulator.tools.recording).

Phase 2 of docs/combat_training_tool_design.md: loading a painted scenario into
a GameEnvironment, and recording the human's (state, select, move) orders.
"""

import json
import os
import sys

import numpy as np
import pytest

from civulator.game.terrain import Terrain
from civulator.tools.recording import (
    RecordingSession,
    build_env_from_scenario,
    entry_coords,
    load_scenario,
)

SCENARIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios"
)
SCENARIO_001 = os.path.join(SCENARIO_DIR, "scenario_001.json")


def _terrain_grid(env):
    return [
        [env.map.tiles[r, c].terrain_type for c in range(env.m)] for r in range(env.n)
    ]


# --- (a) scenario loading ---------------------------------------------------


def test_scenario_001_units_land_on_their_painted_tiles():
    scenario = load_scenario(SCENARIO_001)
    env = build_env_from_scenario(scenario)

    assert (env.n, env.m) == (scenario["map_rows"], scenario["map_cols"])
    assert env.current_player is env.players[0]

    for entry in scenario["units"]:
        row, col = entry_coords(entry)
        player = env.players[entry["team"] - 1]
        matches = [u for u in player.units if u.coordinates == (row, col)]
        assert matches, f"no team-{entry['team']} unit at {(row, col)}"
        unit = matches[0]
        assert unit.unit_type == entry["type"]
        assert unit.health == entry["hp"]
        assert unit.fortification == (1 if entry["fortified"] else 0)

    # Nothing extra: no auto-placed starting units or cities survived.
    total_units = sum(len(p.units) for p in env.players)
    assert total_units == len(scenario["units"])
    assert sum(len(p.cities) for p in env.players) == len(scenario.get("cities", []))


def test_scenario_terrain_is_reproducible_from_its_seed():
    scenario = load_scenario(SCENARIO_001)
    first = build_env_from_scenario(scenario)
    second = build_env_from_scenario(scenario)
    assert _terrain_grid(first) == _terrain_grid(second)


def test_painter_and_recorder_build_the_same_terrain_from_one_seed():
    """The painted map and the recorded map must be the same map."""
    sys.path.insert(0, os.path.join(os.path.dirname(SCENARIO_DIR), "scripts"))
    painter = pytest.importorskip("scenario_painter")  # skipped if pyray is unavailable

    state = painter.PainterState()
    scenario = {
        "seed": state.seed,
        "map_rows": painter.MAP_ROWS,
        "map_cols": painter.MAP_COLS,
        "units": [],
        "cities": [],
    }
    env = build_env_from_scenario(scenario)
    painted = [
        [state.game_map.tiles[r, c].terrain_type for c in range(painter.MAP_COLS)]
        for r in range(painter.MAP_ROWS)
    ]
    assert painted == _terrain_grid(env)


# --- synthetic mini-scenario ------------------------------------------------


def _passable(env, coords):
    tile = env.map.get_tile(coords)
    return tile is not None and Terrain.MOVEMENT_COSTS.get(tile.terrain_type, 1) < 999


def _cost(env, coords):
    return Terrain.MOVEMENT_COSTS.get(env.map.get_tile(coords).terrain_type, 1)


def _find_attack_line(env):
    """Find (start, step, enemy): step costs 1 MP, enemy is adjacent to step.

    Derived from the actual generated terrain rather than hardcoded, so the
    test does not break when terrain weights in config.toml change.
    """
    for row in range(env.n):
        for col in range(env.m):
            start = (row, col)
            if not _passable(env, start):
                continue
            for step in env.map.get_adjacent_coords(start):
                if not _passable(env, step) or _cost(env, step) != 1:
                    continue
                for enemy in env.map.get_adjacent_coords(step):
                    if enemy in (start, step) or not _passable(env, enemy):
                        continue
                    return start, step, enemy
    raise AssertionError("no passable attack line on this map")


def _far_tile(env, taken):
    for row in range(env.n):
        for col in range(env.m):
            here = (row, col)
            if here in taken or not _passable(env, here):
                continue
            if all(env.map.distance_function(here, t) > 2 for t in taken):
                return here
    raise AssertionError("no free tile for the keeper unit")


def _mini_scenario(tmp_path, seed=7, rows=8, cols=8):
    """A 2-unit-vs-1 combat scenario written to a temp scenarios dir.

    Returns (path, start, step, enemy, keeper). The second own unit ("keeper")
    keeps the turn alive: the engine auto-ends a turn once every unit is spent.
    """
    base = {"seed": seed, "terrain_seeded": True, "map_rows": rows, "map_cols": cols,
            "units": [], "cities": []}
    env = build_env_from_scenario(base)
    start, step, enemy = _find_attack_line(env)
    keeper = _far_tile(env, {start, step, enemy})

    scenario = dict(base)
    scenario["units"] = [
        {"type": "Warrior", "team": 1, "row": start[0], "col": start[1],
         "fortified": False, "hp": 100},
        {"type": "Archer", "team": 1, "row": keeper[0], "col": keeper[1],
         "fortified": False, "hp": 100},
        {"type": "Warrior", "team": 2, "row": enemy[0], "col": enemy[1],
         "fortified": False, "hp": 1},
    ]
    path = tmp_path / "scenario_042.json"
    path.write_text(json.dumps(scenario))
    return str(path), start, step, enemy, keeper


# --- (b) recording a played turn -------------------------------------------


def test_move_then_kill_writes_a_demonstration(tmp_path):
    scenario_path, start, step, enemy, _keeper = _mini_scenario(tmp_path)
    demo_dir = tmp_path / "demonstrations"
    session = RecordingSession(scenario_path, demo_dir=str(demo_dir))

    assert start in session.selectable_tiles()
    assert session.click(start) == "select"
    assert step in session.valid_targets()
    assert session.click(step) == "move"

    assert session.click(step) == "select"
    assert enemy in session.valid_targets()
    assert session.click(enemy) == "attack"

    # The 1-HP defender died and the melee attacker took its tile.
    assert session.env.players[1].units == []
    assert any(u.coordinates == enemy for u in session.env.players[0].units)

    path = session.end_turn()
    assert path is not None and os.path.isfile(path)
    assert os.path.basename(path) == "scenario_042_play_001.json"

    with open(path) as f:
        demo = json.load(f)

    assert demo["scenario_file"] == "scenario_042.json"
    assert set(demo["manifest"]) == {"game_version", "git_commit", "config", "date"}
    assert len(demo["actions"]) == 2
    assert demo["actions"][0]["select"] == list(start)
    assert demo["actions"][0]["move"] == list(step)
    assert demo["actions"][1]["select"] == list(step)
    assert demo["actions"][1]["move"] == list(enemy)

    for i, action in enumerate(demo["actions"]):
        assert action["state_tensor"] == f"scenario_042_play_001_state_{i:03d}.npy"
        state = np.load(os.path.join(str(demo_dir), action["state_tensor"]))
        assert state.shape == (25, 8, 8)
        assert state.dtype == np.float32

    # State is recorded BEFORE the action: the first tensor still shows the
    # unit on its starting tile (own-unit HP channel 5), not on `step`.
    first = np.load(os.path.join(str(demo_dir), demo["actions"][0]["state_tensor"]))
    assert first[5, start[0], start[1]] > 0
    assert first[5, step[0], step[1]] == 0


def test_replays_of_one_scenario_get_separate_play_numbers(tmp_path):
    scenario_path, start, step, _enemy, _keeper = _mini_scenario(tmp_path)
    demo_dir = str(tmp_path / "demonstrations")

    paths = []
    for _ in range(2):
        session = RecordingSession(scenario_path, demo_dir=demo_dir)
        session.click(start)
        session.click(step)
        paths.append(os.path.basename(session.end_turn()))

    assert paths == ["scenario_042_play_001.json", "scenario_042_play_002.json"]


def test_end_turn_without_orders_writes_nothing(tmp_path):
    scenario_path, _start, _step, _enemy, _keeper = _mini_scenario(tmp_path)
    demo_dir = tmp_path / "demonstrations"
    session = RecordingSession(scenario_path, demo_dir=str(demo_dir))

    assert session.end_turn() is None
    assert session.finished
    assert session.click((0, 0)) == "finished"
    assert not demo_dir.exists() or list(demo_dir.iterdir()) == []


# --- (c) fortify ------------------------------------------------------------


def test_clicking_own_tile_fortifies_and_is_recorded(tmp_path):
    scenario_path, start, _step, _enemy, _keeper = _mini_scenario(tmp_path)
    demo_dir = tmp_path / "demonstrations"
    session = RecordingSession(scenario_path, demo_dir=str(demo_dir))

    assert session.click(start) == "select"
    assert session.click(start) == "fortify"

    unit = [u for u in session.env.players[0].units if u.coordinates == start][0]
    assert unit.fortification == 1
    assert unit.movement_points == 0
    assert start not in session.selectable_tiles()  # spent, no longer selectable

    with open(session.end_turn()) as f:
        demo = json.load(f)
    assert len(demo["actions"]) == 1
    assert demo["actions"][0]["select"] == list(start)
    assert demo["actions"][0]["move"] == list(start)


# --- guards -----------------------------------------------------------------


def test_orders_outside_the_agent_masks_are_rejected(tmp_path):
    scenario_path, start, _step, _enemy, keeper = _mini_scenario(tmp_path)
    session = RecordingSession(scenario_path, demo_dir=str(tmp_path / "demonstrations"))

    session.click(start)
    assert keeper not in session.valid_targets()  # far away — not a legal order
    assert session.click(keeper) == "select"      # it is a selectable own unit
    assert session.selected[:2] == keeper

    session.selected = None
    assert session.issue_order((0, 0)) in ("invalid", "rejected")
    assert session.action_count == 0


def test_tools_package_is_ui_free():
    import civulator.tools.recording as recording

    source = open(recording.__file__).read()
    assert "pyray" not in source


@pytest.mark.parametrize("keys", [
    {"row": 3, "col": 5},
    {"r": 3, "q": 5},
])
def test_entry_coords_accepts_both_key_spellings(keys):
    assert entry_coords(keys) == (3, 5)
