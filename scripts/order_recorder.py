"""Order Recorder — play a scenario, record every order for imitation learning.

Phase 2 of docs/combat_training_tool_design.md. All game logic lives in
civulator.tools.recording.RecordingSession; all hex math and drawing comes from
civulator.viz.hex_render. This file is only the raylib front-end.

Usage:
    python scripts/order_recorder.py [scenarios/scenario_001.json]

Controls:
  LEFT CLICK   — click own unit = select, valid tile = move,
                 enemy in range = attack, selected unit's own tile = fortify
  E            — end turn: save the demonstration and stop
  SCROLL       — zoom
  RMOUSE DRAG  — pan
  ESC          — quit (unsaved orders are saved on exit)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyray as rl

from civulator.tools.recording import DEFAULT_SCENARIO_DIR, RecordingSession
from civulator.viz.hex_render import (
    TERRAIN_COLORS,
    draw_hex,
    draw_hex_outline,
    hex_to_pixel,
    load_sprites,
    make_camera,
    pixel_to_hex,
    unload_sprites,
    update_camera_zoom_pan,
)

HEX_SIZE = 28
SCREEN_W = 1200
SCREEN_H = 800
ART_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "art")

SPRITE_FILES = {
    "Warrior": "icon_unit_swordsman.png",
    "Archer": "icon_unit_archer.png",
    "Spearman": "icon_unit_spearman.png",
    "Horseman": "icon_unit_horseman.png",
    "Catapult": "icon_unit_catapult.png",
    "Swordsman": "icon_unit_swordsman.png",
}

PLAYER_COLORS = [
    rl.Color(50, 100, 220, 255),  # players[0] — the recorded human (Team 1, blue)
    rl.Color(220, 50, 50, 255),   # players[1] — the opposition (Team 2, red)
]
SELECT_COLOR = rl.Color(255, 240, 80, 255)
TARGET_COLOR = rl.Color(255, 255, 255, 90)
SELECTABLE_COLOR = rl.Color(120, 255, 160, 160)


def pick_scenario(argv):
    """Scenario path from argv, else the first file in scenarios/."""
    if len(argv) > 1:
        return argv[1]
    files = sorted(f for f in os.listdir(DEFAULT_SCENARIO_DIR) if f.endswith(".json"))
    if not files:
        raise SystemExit(f"No scenarios found in {DEFAULT_SCENARIO_DIR}")
    print("Scenarios available:")
    for name in files:
        print(f"  {name}")
    print(f"Loading {files[0]} (pass a path to choose another).")
    return os.path.join(DEFAULT_SCENARIO_DIR, files[0])


def draw_board(session, sprites, selectable, targets):
    """Terrain, highlights, cities and units — all via hex_render primitives."""
    env = session.env
    for row in range(session.n):
        for col in range(session.m):
            tile = env.map.tiles[row, col]
            if tile is None:
                continue
            cx, cy = hex_to_pixel(row, col, HEX_SIZE)
            draw_hex(cx, cy, HEX_SIZE - 1, TERRAIN_COLORS.get(tile.terrain_type, rl.GRAY))
            draw_hex_outline(cx, cy, HEX_SIZE, rl.Color(60, 60, 60, 100))

    for row, col in targets:
        cx, cy = hex_to_pixel(row, col, HEX_SIZE)
        draw_hex(cx, cy, HEX_SIZE - 4, TARGET_COLOR)

    for row, col in selectable:
        cx, cy = hex_to_pixel(row, col, HEX_SIZE)
        draw_hex_outline(cx, cy, HEX_SIZE - 3, SELECTABLE_COLOR)

    if session.selected is not None:
        cx, cy = hex_to_pixel(session.selected[0], session.selected[1], HEX_SIZE)
        draw_hex_outline(cx, cy, HEX_SIZE, SELECT_COLOR)
        draw_hex_outline(cx, cy, HEX_SIZE - 2, SELECT_COLOR)

    for index, player in enumerate(env.players):
        color = PLAYER_COLORS[index % len(PLAYER_COLORS)]
        for city in player.cities:
            cx, cy = hex_to_pixel(city.coordinates[0], city.coordinates[1], HEX_SIZE)
            rl.draw_circle(int(cx), int(cy), HEX_SIZE * 0.6, color)
            rl.draw_circle_lines(int(cx), int(cy), HEX_SIZE * 0.6, rl.WHITE)
            rl.draw_text(b"C", int(cx) - 4, int(cy) - 5, 12, rl.WHITE)
        for unit in player.units:
            draw_unit(unit, color, sprites)


def draw_unit(unit, color, sprites):
    cx, cy = hex_to_pixel(unit.coordinates[0], unit.coordinates[1], HEX_SIZE)
    sprite = sprites.get(unit.unit_type)
    if sprite is not None:
        scale = (HEX_SIZE * 1.2) / max(sprite.width, sprite.height)
        pos = rl.Vector2(cx - sprite.width * scale / 2, cy - sprite.height * scale / 2)
        rl.draw_texture_ex(sprite, pos, 0, scale, color)
    else:
        rl.draw_circle(int(cx), int(cy), HEX_SIZE * 0.35, color)
        rl.draw_text(unit.unit_type[0].encode(), int(cx) - 4, int(cy) - 5, 12, rl.WHITE)

    if unit.fortification > 0:
        rl.draw_circle_lines(int(cx), int(cy), HEX_SIZE * 0.5, rl.WHITE)

    # HP bar + number
    hp = max(0.0, min(1.0, unit.health / 100.0))
    bar_w = HEX_SIZE * 0.8
    rl.draw_rectangle(int(cx - bar_w / 2), int(cy - HEX_SIZE * 0.7), int(bar_w), 3,
                      rl.Color(40, 40, 40, 200))
    rl.draw_rectangle(int(cx - bar_w / 2), int(cy - HEX_SIZE * 0.7), int(bar_w * hp), 3,
                      rl.Color(50, 220, 50, 220))
    rl.draw_text(str(int(unit.health)).encode(), int(cx - bar_w / 2), int(cy + HEX_SIZE * 0.35),
                 10, rl.WHITE)
    if unit.movement_points <= 0:
        rl.draw_text(b".", int(cx) + 10, int(cy) - 14, 20, rl.LIGHTGRAY)


def draw_hud(session, last_action):
    rl.draw_rectangle(0, 0, SCREEN_W, 74, rl.Color(20, 20, 25, 210))
    rl.draw_text(b"ORDER RECORDER", 10, 8, 18, rl.WHITE)
    rl.draw_text(session.scenario_file.encode(), 200, 12, 14, rl.LIGHTGRAY)
    rl.draw_text(f"Recorded orders: {session.action_count}".encode(), 480, 12, 16, rl.WHITE)
    rl.draw_text(f"last: {last_action}".encode(), 700, 12, 14, rl.LIGHTGRAY)

    if session.finished:
        saved = session.saved_path or "nothing recorded"
        rl.draw_text(f"TURN ENDED - {os.path.basename(saved)}".encode(), 10, 40, 16, rl.YELLOW)
    else:
        rl.draw_text(b"CLICK unit = select | tile = move | enemy = attack | own tile = fortify",
                     10, 40, 14, rl.LIGHTGRAY)
        rl.draw_text(b"[E] end turn + save", 880, 40, 14, SELECT_COLOR)

    if not session.terrain_reproducible:
        rl.draw_text(b"WARNING: scenario has no seeded terrain - map is NOT the painted one",
                     10, 58, 12, rl.ORANGE)


def run(scenario_path):
    session = RecordingSession(scenario_path)
    if not session.terrain_reproducible:
        print("WARNING: this scenario predates seeded terrain — the terrain shown is "
              "a fresh map from the stored seed, not the one it was painted on.")

    rl.init_window(SCREEN_W, SCREEN_H, b"Civulator - Order Recorder")
    rl.set_target_fps(60)
    sprites = load_sprites(SPRITE_FILES, ART_DIR)
    camera = make_camera(session.n, session.m, HEX_SIZE, SCREEN_W, SCREEN_H, zoom=1.0)
    last_action = "-"

    while not rl.window_should_close():
        update_camera_zoom_pan(camera, zoom_step=0.1, zoom_min=0.3, zoom_max=3.0)

        if rl.is_key_pressed(rl.KEY_E) and not session.finished:
            path = session.end_turn()
            last_action = "end turn"
            print(f"Saved: {path}" if path else "Nothing recorded — no file written.")

        if rl.is_mouse_button_pressed(rl.MOUSE_BUTTON_LEFT):
            world = rl.get_screen_to_world_2d(rl.get_mouse_position(), camera)
            row, col = pixel_to_hex(world.x, world.y, HEX_SIZE, session.n, session.m)
            if row is not None:
                last_action = session.click((row, col))

        selectable = session.selectable_tiles() if not session.finished else set()
        targets = session.valid_targets() if not session.finished else set()

        rl.begin_drawing()
        rl.clear_background(rl.Color(30, 30, 35, 255))
        rl.begin_mode_2d(camera)
        draw_board(session, sprites, selectable, targets)
        rl.end_mode_2d()
        draw_hud(session, last_action)
        rl.end_drawing()

    unload_sprites(sprites)
    rl.close_window()

    if not session.finished and session.action_count:
        path = session.end_turn()
        print(f"Saved on exit: {path}")


if __name__ == "__main__":
    run(pick_scenario(sys.argv))
