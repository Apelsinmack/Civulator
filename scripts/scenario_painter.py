"""Scenario Painter — create combat scenarios for imitation learning.

Place units and cities on a hex grid with random terrain.
Save scenarios to JSON. New terrain generated on each save.

Controls:
  LEFT CLICK   — place selected unit/city on hex
  RIGHT CLICK  — remove unit/city from hex
  1-6          — select unit type (Warrior, Archer, Spearman, Horseman, Catapult, Swordsman)
  C            — toggle city placement mode
  T            — toggle team (1 / 2)
  F            — toggle fortified
  S            — save scenario + generate new terrain
  R            — regenerate terrain without saving
  SCROLL       — zoom
  RMOUSE DRAG  — pan (hold right mouse + drag)
"""

import os
import sys
import json
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyray as rl
import numpy as np

from civulator.game.map import Map
from civulator.viz.hex_render import (
    TERRAIN_COLORS,
    hex_to_pixel,
    pixel_to_hex,
    draw_hex,
    draw_hex_outline,
    make_camera,
    update_camera_zoom_pan,
    load_sprites,
    unload_sprites,
)

# --- Config ---
MAP_ROWS = 16
MAP_COLS = 16
HEX_SIZE = 28
SCREEN_W = 1200
SCREEN_H = 800
SCENARIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios")

UNIT_TYPES = ["Warrior", "Archer", "Spearman", "Horseman", "Catapult", "Swordsman"]

SPRITE_FILES = {
    "Warrior":   "icon_unit_swordsman.png",  # reuse swordsman sprite
    "Archer":    "icon_unit_archer.png",
    "Spearman":  "icon_unit_spearman.png",
    "Horseman":  "icon_unit_horseman.png",
    "Catapult":  "icon_unit_catapult.png",
    "Swordsman": "icon_unit_swordsman.png",
}

PLAYER_COLORS = [
    rl.Color(50, 100, 220, 255),   # Team 1: Blue
    rl.Color(220, 50, 50, 255),    # Team 2: Red
]

# --- State ---

class PainterState:
    def __init__(self):
        self.seed = random.randint(0, 99999)
        self.game_map = None
        self.units = []       # list of dicts
        self.cities = []      # list of dicts
        self.selected_type = 0  # index into UNIT_TYPES
        self.team = 0         # 0 = Team 1, 1 = Team 2
        self.fortified = False
        self.city_mode = False
        self.scenario_count = 0
        self.sprites = {}     # loaded textures
        self.generate_terrain()

    def generate_terrain(self):
        self.seed = random.randint(0, 99999)
        np.random.seed(self.seed)
        self.game_map = Map(MAP_ROWS, MAP_COLS)
        self.game_map.generate_map()
        self.units = []
        self.cities = []

    def add_unit(self, row, col):
        # Remove existing at this position
        self.remove_at(row, col)
        self.units.append({
            "type": UNIT_TYPES[self.selected_type],
            "team": self.team + 1,
            "row": row, "col": col,
            "fortified": self.fortified,
            "hp": 100,
        })

    def add_city(self, row, col):
        self.remove_at(row, col)
        self.cities.append({
            "team": self.team + 1,
            "row": row, "col": col,
            "hp": 200,
            "walls": False,
        })

    def remove_at(self, row, col):
        self.units = [u for u in self.units if not (u["row"] == row and u["col"] == col)]
        self.cities = [c for c in self.cities if not (c["row"] == row and c["col"] == col)]

    def save(self):
        os.makedirs(SCENARIO_DIR, exist_ok=True)
        self.scenario_count += 1
        filename = f"scenario_{self.scenario_count:03d}.json"
        filepath = os.path.join(SCENARIO_DIR, filename)

        data = {
            "seed": self.seed,
            "map_rows": MAP_ROWS,
            "map_cols": MAP_COLS,
            "units": self.units,
            "cities": self.cities,
        }
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        print(f"Saved: {filepath} ({len(self.units)} units, {len(self.cities)} cities)")

        # Generate fresh terrain for next scenario
        self.generate_terrain()

    def load_sprites(self):
        art_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "art")
        self.sprites = load_sprites(SPRITE_FILES, art_dir)

    def unload_sprites(self):
        unload_sprites(self.sprites)


# --- Main ---

def run_painter():
    rl.init_window(SCREEN_W, SCREEN_H, b"Civulator - Scenario Painter")
    rl.set_target_fps(60)

    state = PainterState()
    state.load_sprites()

    # Find existing scenario count to not overwrite
    if os.path.exists(SCENARIO_DIR):
        existing = [f for f in os.listdir(SCENARIO_DIR) if f.endswith(".json")]
        if existing:
            nums = []
            for f in existing:
                try:
                    nums.append(int(f.split("_")[1].split(".")[0]))
                except (IndexError, ValueError):
                    pass
            if nums:
                state.scenario_count = max(nums)

    camera = make_camera(MAP_ROWS, MAP_COLS, HEX_SIZE, SCREEN_W, SCREEN_H, zoom=1.0)

    while not rl.window_should_close():
        # --- Input ---

        # Unit type selection (1-6)
        for i in range(6):
            if rl.is_key_pressed(rl.KEY_ONE + i):
                state.selected_type = i
                state.city_mode = False

        # Toggle keys
        if rl.is_key_pressed(rl.KEY_T):
            state.team = 1 - state.team
        if rl.is_key_pressed(rl.KEY_F):
            state.fortified = not state.fortified
        if rl.is_key_pressed(rl.KEY_C):
            state.city_mode = not state.city_mode
        if rl.is_key_pressed(rl.KEY_R):
            state.generate_terrain()
        if rl.is_key_pressed(rl.KEY_S):
            if state.units or state.cities:
                state.save()

        # Zoom, pan with right mouse drag
        update_camera_zoom_pan(camera, zoom_step=0.1, zoom_min=0.3, zoom_max=3.0)

        # Place/remove with left click (only when not dragging)
        if rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            # Convert screen pos to world pos
            mouse_screen = rl.get_mouse_position()
            mouse_world = rl.get_screen_to_world_2d(mouse_screen, camera)
            row, col = pixel_to_hex(mouse_world.x, mouse_world.y, HEX_SIZE, MAP_ROWS, MAP_COLS)

            if row is not None and 0 <= row < MAP_ROWS and 0 <= col < MAP_COLS:
                # Check if tile is passable (not ocean/mountain for units)
                tile = state.game_map.tiles[row, col]
                if tile is not None:
                    if rl.is_key_down(rl.KEY_LEFT_SHIFT):
                        # Shift+click = remove
                        state.remove_at(row, col)
                    elif state.city_mode:
                        state.add_city(row, col)
                    else:
                        state.add_unit(row, col)

        # --- Draw ---
        rl.begin_drawing()
        rl.clear_background(rl.Color(30, 30, 35, 255))
        rl.begin_mode_2d(camera)

        # Terrain
        for row in range(MAP_ROWS):
            for col in range(MAP_COLS):
                tile = state.game_map.tiles[row, col]
                if tile is None:
                    continue
                cx, cy = hex_to_pixel(row, col, HEX_SIZE)
                color = TERRAIN_COLORS.get(tile.terrain_type, rl.GRAY)
                draw_hex(cx, cy, HEX_SIZE - 1, color)
                draw_hex_outline(cx, cy, HEX_SIZE, rl.Color(60, 60, 60, 100))

        # Cities
        for city in state.cities:
            cx, cy = hex_to_pixel(city["row"], city["col"], HEX_SIZE)
            pcolor = PLAYER_COLORS[city["team"] - 1]
            rl.draw_circle(int(cx), int(cy), HEX_SIZE * 0.6, pcolor)
            rl.draw_circle_lines(int(cx), int(cy), HEX_SIZE * 0.6, rl.WHITE)
            rl.draw_text(b"C", int(cx) - 4, int(cy) - 5, 12, rl.WHITE)

        # Units
        for unit in state.units:
            cx, cy = hex_to_pixel(unit["row"], unit["col"], HEX_SIZE)
            pcolor = PLAYER_COLORS[unit["team"] - 1]
            utype = unit["type"]

            # Try sprite first
            if utype in state.sprites:
                tex = state.sprites[utype]
                scale = (HEX_SIZE * 1.2) / max(tex.width, tex.height)
                draw_x = cx - (tex.width * scale) / 2
                draw_y = cy - (tex.height * scale) / 2
                rl.draw_texture_ex(tex, rl.Vector2(draw_x, draw_y), 0, scale, pcolor)
            else:
                # Fallback: colored dot with label
                rl.draw_circle(int(cx), int(cy), HEX_SIZE * 0.35, pcolor)
                label = utype[0].encode()  # First letter
                rl.draw_text(label, int(cx) - 4, int(cy) - 5, 12, rl.WHITE)

            # Fortified indicator
            if unit["fortified"]:
                rl.draw_circle_lines(int(cx), int(cy), HEX_SIZE * 0.5, rl.WHITE)

            # HP bar
            hp_frac = unit["hp"] / 100.0
            bar_w = HEX_SIZE * 0.8
            rl.draw_rectangle(int(cx - bar_w / 2), int(cy - HEX_SIZE * 0.7),
                              int(bar_w * hp_frac), 3,
                              rl.Color(50, 220, 50, 200))

        # Hover highlight
        mouse_screen = rl.get_mouse_position()
        mouse_world = rl.get_screen_to_world_2d(mouse_screen, camera)
        hr, hc = pixel_to_hex(mouse_world.x, mouse_world.y, HEX_SIZE, MAP_ROWS, MAP_COLS)
        if hr is not None and 0 <= hr < MAP_ROWS and 0 <= hc < MAP_COLS:
            hx, hy = hex_to_pixel(hr, hc, HEX_SIZE)
            draw_hex_outline(hx, hy, HEX_SIZE, rl.Color(255, 255, 255, 150))

        rl.end_mode_2d()

        # --- HUD ---
        panel_x = 10
        rl.draw_rectangle(0, 0, 280, SCREEN_H, rl.Color(20, 20, 25, 200))

        rl.draw_text(b"SCENARIO PAINTER", panel_x, 10, 18, rl.WHITE)
        rl.draw_text(f"Seed: {state.seed}".encode(), panel_x, 35, 14, rl.LIGHTGRAY)
        rl.draw_text(f"Units: {len(state.units)}  Cities: {len(state.cities)}".encode(),
                     panel_x, 55, 14, rl.LIGHTGRAY)

        # Team
        team_color = PLAYER_COLORS[state.team]
        rl.draw_text(f"Team: {state.team + 1}".encode(), panel_x, 85, 16, team_color)
        rl.draw_text(b"[T] toggle", 100, 85, 12, rl.DARKGRAY)

        # Mode
        if state.city_mode:
            rl.draw_text(b"Mode: CITY", panel_x, 110, 16, rl.YELLOW)
        else:
            uname = UNIT_TYPES[state.selected_type]
            rl.draw_text(f"Unit: {uname}".encode(), panel_x, 110, 16, rl.WHITE)

        rl.draw_text(b"[C] city mode", 150, 110, 12, rl.DARKGRAY)

        # Fortified
        fort_text = "ON" if state.fortified else "OFF"
        fort_color = rl.GREEN if state.fortified else rl.GRAY
        rl.draw_text(f"Fortified: {fort_text}".encode(), panel_x, 135, 16, fort_color)
        rl.draw_text(b"[F] toggle", 150, 135, 12, rl.DARKGRAY)

        # Unit palette
        rl.draw_text(b"--- Units ---", panel_x, 170, 14, rl.LIGHTGRAY)
        for i, utype in enumerate(UNIT_TYPES):
            y = 190 + i * 22
            selected = (i == state.selected_type and not state.city_mode)
            color = rl.WHITE if selected else rl.DARKGRAY
            prefix = "> " if selected else "  "
            rl.draw_text(f"{prefix}[{i+1}] {utype}".encode(), panel_x, y, 14, color)

        # Controls
        y_controls = SCREEN_H - 120
        rl.draw_text(b"--- Controls ---", panel_x, y_controls, 14, rl.LIGHTGRAY)
        rl.draw_text(b"CLICK = place    SHIFT+CLICK = remove", panel_x, y_controls + 20, 12, rl.DARKGRAY)
        rl.draw_text(b"S = save + new terrain", panel_x, y_controls + 36, 12, rl.DARKGRAY)
        rl.draw_text(b"R = regenerate terrain", panel_x, y_controls + 52, 12, rl.DARKGRAY)
        rl.draw_text(b"SCROLL = zoom    RMOUSE = pan", panel_x, y_controls + 68, 12, rl.DARKGRAY)
        rl.draw_text(b"ESC = quit", panel_x, y_controls + 84, 12, rl.DARKGRAY)

        rl.end_drawing()

    state.unload_sprites()
    rl.close_window()


if __name__ == "__main__":
    run_painter()
