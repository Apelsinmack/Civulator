"""Order Recorder core — record human (state, select, move) demonstrations.

Phase 2 of `docs/combat_training_tool_design.md`. This module is deliberately
UI-free so it can be unit-tested; `scripts/order_recorder.py` is a thin raylib
front-end over `RecordingSession`.

Model (per the design doc):
  * A scenario JSON (written by the Scenario Painter) is loaded into a
    `GameEnvironment`. Team 1 -> players[0] (the recorded human), Team 2 ->
    players[1] (stationary opposition).
  * It is always players[0]'s turn. One recording = one turn. "End turn"
    saves the demonstration and stops; the enemy turn is never played.
  * Before every executed action we snapshot the state tensor
    (`EnhancedStateEncoder`, players[0] perspective); the action itself is the
    same `(select, move)` pair the DQN agent emits, so no translation layer.

Click highlighting goes through the SAME masks the agent uses
(`get_valid_select_mask` / `get_valid_moves_mask`) — anything else would create
train/play skew (see the canonical-systems table in CLAUDE.md).
"""

import json
import os

import numpy as np
import torch

from ..agents.networks import get_valid_moves_mask, get_valid_select_mask
from ..agents.state_encoders import EnhancedStateEncoder
from ..game.city import City
from ..game.environment import GameEnvironment
from ..game.unit import (
    NUM_UNIT_SLOTS,
    ArcherUnit,
    CatapultUnit,
    HorsemanUnit,
    SpearmanUnit,
    SwordsmanUnit,
    WarriorUnit,
)
from ..meta import build_manifest

# The recorded human is always players[0] (scenario "team": 1).
HUMAN_PLAYER_INDEX = 0

UNIT_CLASSES = {
    "Warrior": WarriorUnit,
    "Archer": ArcherUnit,
    "Swordsman": SwordsmanUnit,
    "Spearman": SpearmanUnit,
    "Horseman": HorsemanUnit,
    "Catapult": CatapultUnit,
}

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DEMO_DIR = os.path.join(_REPO_ROOT, "demonstrations")
DEFAULT_SCENARIO_DIR = os.path.join(_REPO_ROOT, "scenarios")


# --- Scenario loading -------------------------------------------------------


def load_scenario(path):
    """Load a scenario JSON written by `scripts/scenario_painter.py`."""
    with open(path, "r") as f:
        return json.load(f)


def scenario_dims(scenario):
    """(rows, cols) of a scenario, accepting both key spellings.

    The painter writes `map_rows`/`map_cols`; the design document sketched
    `map_height`/`map_width`. Both mean the same thing (rows = r axis).
    """
    rows = scenario.get("map_rows", scenario.get("map_height", 16))
    cols = scenario.get("map_cols", scenario.get("map_width", 16))
    return int(rows), int(cols)


def entry_coords(entry):
    """(row, col) of a scenario unit/city entry.

    Accepts the painter's `row`/`col` keys and the design document's axial
    `r`/`q` keys (row = r, col = q).
    """
    if "row" in entry:
        return int(entry["row"]), int(entry["col"])
    return int(entry["r"]), int(entry["q"])


def build_env_from_scenario(scenario):
    """Build a `GameEnvironment` holding exactly the scenario's units/cities.

    Terrain comes from `GameEnvironment(..., seed=scenario["seed"])`. The
    Scenario Painter builds its map the same way, so the same seed reproduces
    the same terrain in both tools — do not replace this with a bare
    `Map(...)`, that reintroduces the unseeded-terrain bug (see the painter).
    """
    rows, cols = scenario_dims(scenario)
    env = GameEnvironment(rows, cols, num_players=2, seed=scenario.get("seed"))

    # The constructor places nothing today, but reset()/future changes might —
    # a scenario must contain only what the painter put in it.
    _clear_board(env)

    for entry in scenario.get("units", []):
        _place_unit(env, entry)
    for entry in scenario.get("cities", []):
        _place_city(env, entry)

    env.current_player_index = HUMAN_PLAYER_INDEX
    env.current_player = env.players[HUMAN_PLAYER_INDEX]
    return env


def _clear_board(env):
    for player in env.players:
        for unit in list(player.units):
            env.delete_unit(unit)
        for city in list(player.cities):
            tile = env.map.get_tile(city.coordinates)
            if tile is not None and tile.city is city:
                tile.set_city(None)
        player.cities = []
        player.units = []


def _place_unit(env, entry):
    """Place one scenario unit through the environment's public helpers."""
    row, col = entry_coords(entry)
    player = env.players[int(entry.get("team", 1)) - 1]
    unit_cls = UNIT_CLASSES.get(entry.get("type", "Warrior"), WarriorUnit)

    terrain = env.get_terrain_at((row, col))
    unit = unit_cls(player, (row, col), terrain)
    unit.health = float(entry.get("hp", 100))
    if entry.get("fortified"):
        unit.fortification = 1

    player.units.append(unit)
    env.add_unit_to_tile(unit, (row, col))
    return unit


def _place_city(env, entry):
    """Place one scenario city, bypassing the min-distance rule if needed.

    `found_city` enforces the normal game placement rules (>= 3 tiles apart,
    not on Mountain/Ocean). A painted scenario may violate them on purpose, so
    fall back to the same primitives `SettlerUnit.found_city` uses.
    """
    row, col = entry_coords(entry)
    player = env.players[int(entry.get("team", 1)) - 1]

    city = env.found_city(player, (row, col), f"{player.name}'s City")
    if city is None:
        city = City(player, (row, col), f"{player.name}'s City")
        player.cities.append(city)
        env.add_city(city)
        city.assign_tiles(env)

    city.health = float(entry.get("hp", 200))
    if entry.get("walls") and "Walls" not in city.buildings:
        city.buildings.append("Walls")
    return city


# --- Recording session ------------------------------------------------------


class RecordingSession:
    """One human-played turn over one scenario, recorded for imitation learning.

    Typical UI loop::

        session = RecordingSession("scenarios/scenario_001.json")
        session.click((4, 8))       # select own unit -> "select"
        session.click((4, 9))       # order            -> "attack"
        path = session.end_turn()   # writes the demonstration
    """

    def __init__(self, scenario_path, demo_dir=None, device=None):
        self.scenario_path = os.path.abspath(scenario_path)
        self.scenario_file = os.path.basename(self.scenario_path)
        self.scenario = load_scenario(self.scenario_path)
        self.demo_dir = demo_dir or DEFAULT_DEMO_DIR
        self.device = device or torch.device("cpu")

        self.env = build_env_from_scenario(self.scenario)
        self.encoder = EnhancedStateEncoder()

        self.selected = None  # (row, col, slot) of the selected unit
        self.actions = []  # [{"state": ndarray, "select": (r,c), "move": (r,c), "slot": int}]
        self.finished = False
        self.saved_path = None
        # The painter did not seed terrain before this was fixed; scenarios
        # saved by the old painter cannot have their terrain reconstructed.
        self.terrain_reproducible = bool(self.scenario.get("terrain_seeded", False))

    # --- board queries (used by the UI) ---

    @property
    def player(self):
        return self.env.players[HUMAN_PLAYER_INDEX]

    @property
    def n(self):
        return self.env.n

    @property
    def m(self):
        return self.env.m

    @property
    def action_count(self):
        return len(self.actions)

    def encode_state(self):
        """State tensor from the recorded player's perspective, [25, n, m]."""
        return self.encoder.encode(self.env, HUMAN_PLAYER_INDEX, self.device)

    def selectable_tiles(self):
        """{(row, col)} of own units that may still act — agent's select mask."""
        mask = get_valid_select_mask(self.encode_state(), self.env)
        tiles = set()
        for idx in torch.nonzero(mask).flatten().tolist():
            tile_idx = idx // NUM_UNIT_SLOTS
            tiles.add((tile_idx // self.m, tile_idx % self.m))
        return tiles

    def valid_targets(self):
        """{(row, col)} the selected unit may be ordered to — agent's move mask."""
        if self.selected is None:
            return set()
        row, col, slot = self.selected
        selected_pos = (row * self.m + col) * NUM_UNIT_SLOTS + slot
        mask = get_valid_moves_mask(self.encode_state(), selected_pos, self.env)
        return {(idx // self.m, idx % self.m) for idx in torch.nonzero(mask).flatten().tolist()}

    def selected_unit(self):
        if self.selected is None:
            return None
        row, col, slot = self.selected
        return self.env.get_unit_in_slot((row, col), slot, self.player)

    def units_at(self, coords):
        return self.env.get_units_at(coords)

    # --- interaction ---

    def click(self, coords):
        """Handle one board click. Returns what it did.

        One of: "select", "move", "attack", "fortify", "rejected", "invalid",
        "finished". Mirrors the design document's interaction table:
        own unit -> select; valid empty tile -> move; enemy in range -> attack;
        the selected unit's own tile -> fortify.
        """
        coords = (int(coords[0]), int(coords[1]))
        if self.finished:
            return "finished"

        # Clicking the selected unit's own tile = fortify (checked before
        # re-selection, otherwise fortify would be unreachable).
        if self.selected is not None and coords == (self.selected[0], self.selected[1]):
            return self.issue_order(coords)

        if coords in self.selectable_tiles():
            return self.select(coords)

        if self.selected is not None and coords in self.valid_targets():
            return self.issue_order(coords)

        return "invalid"

    def select(self, coords):
        """Select one of the player's units (must be selectable this turn)."""
        coords = (int(coords[0]), int(coords[1]))
        if self.finished or coords not in self.selectable_tiles():
            return "invalid"
        for unit in self.player.units:
            if unit.coordinates == coords and unit.movement_points > 0:
                self.selected = (coords[0], coords[1], unit.slot)
                return "select"
        return "invalid"

    def issue_order(self, coords):
        """Order the selected unit to `coords`, recording (state, select, move).

        The state tensor is captured BEFORE the action executes. Orders the
        engine refuses (nothing on the board changed) are not recorded.
        """
        coords = (int(coords[0]), int(coords[1]))
        if self.finished or self.selected is None:
            return "invalid"
        if coords not in self.valid_targets():
            return "invalid"

        row, col, slot = self.selected
        unit = self.selected_unit()
        if unit is None:
            self.selected = None
            return "invalid"

        # Classify the click for the caller before the board changes.
        if coords == (row, col):
            kind = "fortify"
        elif any(u.player is not self.player for u in self.env.get_units_at(coords)):
            kind = "attack"
        else:
            kind = "move"

        state = self.encode_state().cpu().numpy()
        before = self._snapshot()

        # GameEnvironment.step only reaches its fortify branch when
        # select_pos == order_pos, which a slot-aware 3-tuple select can never
        # satisfy against a 2-tuple order — so a fortify order is issued with
        # the legacy 2-tuple select (it resolves to the first own unit on the
        # tile, which for a single-military-slot combat scenario is this one).
        select_arg = np.array([row, col]) if kind == "fortify" else np.array([row, col, slot])
        self.env.step([select_arg, np.array(coords)])

        if self._snapshot() == before:
            return "rejected"  # engine refused it — nothing to learn from

        self.actions.append(
            {
                "state": state,
                "select": (row, col),
                "move": coords,
                "slot": int(slot),
            }
        )
        self.selected = None

        # The engine ends the turn by itself once every unit is spent
        # (GameEnvironment._check_game_end). One recording = one turn, so the
        # session stops there — the enemy turn is never played.
        if self.env.current_player_index != HUMAN_PLAYER_INDEX or self.env.done:
            self.finished = True

        return kind

    def _snapshot(self):
        """Cheap board fingerprint used to detect orders the engine refused."""
        return tuple(
            (
                id(u),
                u.coordinates,
                round(float(u.health), 4),
                round(float(u.movement_points), 4),
                u.fortification,
            )
            for p in self.env.players
            for u in p.units
        )

    # --- saving ---

    def end_turn(self):
        """End the recorded turn: write the demonstration, stop the session.

        Returns the path of the demonstration JSON, or None if nothing was
        recorded. Idempotent — a second call returns the same path.
        """
        if self.saved_path is not None:
            return self.saved_path
        self.finished = True
        self.selected = None
        if not self.actions:
            return None
        self.saved_path = self.save()
        return self.saved_path

    def next_play_index(self):
        """Lowest unused play number for this scenario in `demo_dir`."""
        stem = os.path.splitext(self.scenario_file)[0]
        used = set()
        if os.path.isdir(self.demo_dir):
            for name in os.listdir(self.demo_dir):
                if name.startswith(f"{stem}_play_") and name.endswith(".json"):
                    try:
                        used.add(int(name[len(stem) + 6 : -5]))
                    except ValueError:
                        pass
        index = 1
        while index in used:
            index += 1
        return index

    def save(self):
        """Write the demonstration JSON + one .npy state tensor per action."""
        os.makedirs(self.demo_dir, exist_ok=True)
        stem = os.path.splitext(self.scenario_file)[0]
        base = f"{stem}_play_{self.next_play_index():03d}"

        entries = []
        for i, action in enumerate(self.actions):
            npy_name = f"{base}_state_{i:03d}.npy"
            np.save(os.path.join(self.demo_dir, npy_name), action["state"])
            entries.append(
                {
                    "state_tensor": npy_name,
                    "select": [action["select"][0], action["select"][1]],
                    "move": [action["move"][0], action["move"][1]],
                    "slot": action["slot"],
                }
            )

        path = os.path.join(self.demo_dir, f"{base}.json")
        with open(path, "w") as f:
            json.dump(
                {
                    "scenario_file": self.scenario_file,
                    "manifest": build_manifest(),
                    "actions": entries,
                },
                f,
                indent=2,
            )
        return path
