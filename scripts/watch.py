"""Live game viewer — watch agents play with raylib hex grid rendering."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyray as rl
import numpy as np

from civulator.config import CFG
from civulator.meta import load_weights
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.agents import DQNAgent, BuildAgent, BasicStateEncoder, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.agents.build_agent import BUILD_OPTIONS
from civulator.game.city import City
from civulator.game.unit import NUM_UNIT_SLOTS
from civulator.viz.hex_render import (
    draw_hex,
    draw_hex_outline,
    draw_resource_marker,
    draw_river_edges,
    hex_to_pixel,
    make_camera,
    tile_color,
    update_camera_zoom_pan,
    wrap_camera_x,
    wrapped_draw_x,
)

# --- Config ---
_gcfg = CFG.get("game", {})
_tcfg = CFG.get("training", {})

# Size preset (design doc D14/§6, §11 P5): one resolver, shared with the
# engine and every other run script — no more per-script divergent
# num_players fallbacks (this file used to default to 8, others to 2).
MAP_ROWS, MAP_COLS, NUM_PLAYERS = resolve_size_and_players()
MAX_TURNS = _gcfg.get("max_turns", 200)

# Hex rendering
HEX_SIZE = 12  # Outer radius of each hex
SCREEN_W = 1600
SCREEN_H = 900

# Player colors (up to 8)
PLAYER_COLORS = [
    rl.Color(220, 50, 50, 255),    # Red
    rl.Color(50, 100, 220, 255),   # Blue
    rl.Color(50, 200, 50, 255),    # Green
    rl.Color(220, 200, 50, 255),   # Yellow
    rl.Color(200, 50, 200, 255),   # Purple
    rl.Color(50, 200, 200, 255),   # Cyan
    rl.Color(220, 130, 50, 255),   # Orange
    rl.Color(180, 180, 180, 255),  # Gray
]


def run_viewer():
    """Run one game with live rendering."""
    rl.init_window(SCREEN_W, SCREEN_H, b"Civulator - Live Viewer")
    rl.set_target_fps(30)

    # Camera for panning/zooming
    camera = make_camera(MAP_ROWS, MAP_COLS, HEX_SIZE, SCREEN_W, SCREEN_H, zoom=0.5)

    # Set up game
    env = GameEnvironment(MAP_ROWS, MAP_COLS, NUM_PLAYERS)
    env.max_turns = MAX_TURNS
    env.reset()

    encoder = _tcfg.get("encoder", "enhanced")
    d = EnhancedStateEncoder().get_depth(NUM_PLAYERS) if encoder == "enhanced" else BasicStateEncoder().get_depth(NUM_PLAYERS)

    agents = []
    build_agents_list = []
    for i in range(NUM_PLAYERS):
        mem = ReplayMemory(1000)
        agent = DQNAgent(MAP_ROWS, MAP_COLS, d, mem, encoder=encoder, fully_conv=True)
        agents.append(agent)
        build_agents_list.append(BuildAgent(MAP_ROWS, MAP_COLS, d))

    # Load trained weights if available
    import glob
    for i, agent in enumerate(agents):
        pattern = f"weights/agent_{i}_episode_*.pth"
        files = glob.glob(os.path.join(os.path.dirname(os.path.dirname(__file__)), pattern))
        if files:
            # Find highest episode
            best = max(files, key=lambda f: int(f.split("episode_")[1].split(".")[0]))
            try:
                checkpoint, manifest = load_weights(best, map_location=agent.device)
                agent.network.load_state_dict(checkpoint["model_state_dict"])
                agent.target_network.load_state_dict(checkpoint["model_state_dict"])
                ep = best.split("episode_")[1].split(".")[0]
                # design doc §8, §11 P7 deliverable 5: weights are never
                # version-gated (0.5-world weights stay usable, just
                # labeled), but the version they came from is always shown.
                version_label = manifest["game_version"] if manifest else "pre-manifest/0.5 epoch"
                print(f"Agent {i}: loaded weights from episode {ep} (version: {version_label})")
            except Exception as e:
                print(f"Agent {i}: could not load weights ({e})")
        else:
            print(f"Agent {i}: no weights found, using random")

    done = False
    turn = 0
    last_player = -1
    paused = False
    speed = 1  # Actions per frame

    while not rl.window_should_close():
        # --- Input ---
        if rl.is_key_pressed(rl.KEY_SPACE):
            paused = not paused
        if rl.is_key_pressed(rl.KEY_UP):
            speed = min(speed * 2, 64)
        if rl.is_key_pressed(rl.KEY_DOWN):
            speed = max(speed // 2, 1)

        # Zoom with scroll, pan with right mouse
        update_camera_zoom_pan(camera, zoom_step=0.05, zoom_min=0.1, zoom_max=3.0)
        # Re-enter from the opposite side after panning past the column-wrap
        # seam (§7.5 camera/seam policy) instead of drifting into unmapped
        # space — this is a scrolling view, unlike the painter/recorder.
        wrap_camera_x(camera, HEX_SIZE, env.m)

        # --- Game step ---
        if not done and not paused:
            for _ in range(speed):
                if done:
                    break

                pi = env.current_player.player_index
                agent = agents[pi]

                # Build decisions at turn boundary
                if pi != last_player:
                    ba = build_agents_list[pi]
                    cs = agent.build_state_tensor(env)
                    for city in env.current_player.cities:
                        if city.current_production is None:
                            idx = ba.select_build(cs, city, env, epsilon=0.1)
                            opt = BUILD_OPTIONS[idx]
                            if opt in City.BUILDING_COSTS:
                                city.produce_building(opt)
                            else:
                                city.produce_unit(opt)
                    last_player = pi

                state = agent.build_state_tensor(env)
                action = agent.select_action(state, epsilon=0.1, game_env=env)

                end_turn_idx = env.n * env.m * NUM_UNIT_SLOTS
                if action[0] == end_turn_idx:
                    env.current_player.end_turn()
                    env.next_turn()
                    turn = env.turn_counter
                else:
                    tile_idx = action[0] // NUM_UNIT_SLOTS
                    slot = action[0] % NUM_UNIT_SLOTS
                    r, c = tile_idx // env.m, tile_idx % env.m
                    mr, mc = action[1] // env.m, action[1] % env.m
                    action_matrix = [np.array([r, c, slot]), np.array([mr, mc])]
                    _, reward, done = env.step(action_matrix)

        # --- Draw ---
        rl.begin_drawing()
        rl.clear_background(rl.Color(30, 30, 35, 255))
        rl.begin_mode_2d(camera)

        # Draw terrain
        for row in range(MAP_ROWS):
            for col in range(MAP_COLS):
                tile = env.map.tiles[row, col]
                if tile is None:
                    continue
                cx, cy = hex_to_pixel(row, col, HEX_SIZE, env.m)
                cx = wrapped_draw_x(cx, camera.target.x, HEX_SIZE, env.m)
                draw_hex(cx, cy, HEX_SIZE - 1, tile_color(tile))
                draw_hex_outline(cx, cy, HEX_SIZE, rl.Color(60, 60, 60, 100))
                draw_resource_marker(cx, cy, HEX_SIZE, tile)

        # Rivers (design doc §5 — none generate until P4; the primitive is
        # wired in now so P4's rivers appear automatically).
        draw_river_edges(env.map, HEX_SIZE, env.m, camera_x=camera.target.x)

        # Draw cities
        for player in env.players:
            if player.is_dead:
                continue
            pcolor = PLAYER_COLORS[player.player_index % len(PLAYER_COLORS)]
            for city in player.cities:
                cx, cy = hex_to_pixel(*city.coordinates, HEX_SIZE, env.m)
                cx = wrapped_draw_x(cx, camera.target.x, HEX_SIZE, env.m)
                rl.draw_circle(int(cx), int(cy), HEX_SIZE * 0.7, pcolor)
                rl.draw_circle_lines(int(cx), int(cy), HEX_SIZE * 0.7, rl.WHITE)

        # Draw units
        for player in env.players:
            if player.is_dead:
                continue
            pcolor = PLAYER_COLORS[player.player_index % len(PLAYER_COLORS)]
            for unit in player.units:
                cx, cy = hex_to_pixel(*unit.coordinates, HEX_SIZE, env.m)
                cx = wrapped_draw_x(cx, camera.target.x, HEX_SIZE, env.m)
                # Offset by slot to avoid overlap
                offset_x = (unit.slot - 1.5) * 4
                rl.draw_circle(int(cx + offset_x), int(cy), 3, pcolor)
                # Health bar
                hp_frac = unit.health / 100.0
                bar_w = HEX_SIZE * 0.8
                rl.draw_rectangle(int(cx - bar_w/2), int(cy - HEX_SIZE * 0.6),
                                  int(bar_w * hp_frac), 2,
                                  rl.Color(50, 220, 50, 200))

        rl.end_mode_2d()

        # HUD
        rl.draw_text(f"Turn: {turn}".encode(), 10, 10, 20, rl.WHITE)
        rl.draw_text(f"Speed: {speed}x".encode(), 10, 35, 16, rl.LIGHTGRAY)
        status = b"PAUSED" if paused else (b"GAME OVER" if done else b"RUNNING")
        rl.draw_text(status, 10, 55, 16, rl.YELLOW if paused else rl.WHITE)

        # Player scoreboard
        alive = [p for p in env.players if not p.is_dead]
        for i, p in enumerate(env.players):
            pcolor = PLAYER_COLORS[p.player_index % len(PLAYER_COLORS)]
            y = 80 + i * 18
            label = f"P{p.player_index+1}: {len(p.units)}u {len(p.cities)}c"
            if p.is_dead:
                label += " DEAD"
            rl.draw_text(label.encode(), 10, y, 14, pcolor)

        rl.draw_text(b"SPACE=pause  UP/DOWN=speed  SCROLL=zoom  RMOUSE=pan", 10, SCREEN_H - 25, 14, rl.DARKGRAY)

        rl.end_drawing()

    rl.close_window()


if __name__ == "__main__":
    run_viewer()
