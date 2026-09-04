"""Live game viewer — watch agents play with raylib hex grid rendering.

Two modes:

**Versus / replay mode** (`--a <weights>`): load two combined payloads (the
`meta.save_weights` format run_baseline.py produces) and watch them play.
Loading goes through `evaluate._load_side` — encoder by registry name,
network architecture inferred from the checkpoint (issue #48), so any
capacity-ladder weights file works with no extra flags.

Because protocol-v1 evaluation games are fully deterministic (seeded world +
seeded per-game RNG + the same action-selection order), `--eval-json
<summary.json> --game N` REPLAYS eval game N exactly as it was scored —
same world, same seats, same epsilon rolls (same machine/device required
for bit-identical torch RNG). This is the replay tool: re-simulation, not
recorded state (issue #16's scrub-in-viewer remains a separate idea).

    python scripts/watch.py --a weights/trained/duel_26ch_1000ep.pth \
        --a-encoder city_distance \
        --eval-json stats/eval_duel_26ch_1000ep_vs_duel_25ch_1000ep_1788304495.json \
        --game 37

Without --eval-json, `--seed` picks the world (default: random) and A sits
in seat 0; --b defaults to the frozen #39 baseline.

**Legacy mode** (no --a): original behavior — config-driven env, latest
`weights/agent_{i}_episode_*.pth` checkpoints if present, epsilon 0.1.

Controls: SPACE pause · UP/DOWN speed · scroll zoom · right-mouse pan.
"""

import argparse
import json
import os
import random
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # for `import evaluate`

import pyray as rl
import numpy as np
import torch

from civulator.config import CFG
from civulator.meta import load_weights
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.agents import DQNAgent, BuildAgent, BasicStateEncoder, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.agents.build_agent import BUILD_OPTIONS
from civulator.game.city import City
from civulator.game.unit import NUM_UNIT_SLOTS
from civulator.training.trainer import determine_winner, player_score
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
    wrap_copies_x,
)

# --- Config ---
_gcfg = CFG.get("game", {})
_tcfg = CFG.get("training", {})

# Size preset (design doc D14/§6, §11 P5): one resolver, shared with the
# engine and every other run script — no more per-script divergent
# num_players fallbacks (this file used to default to 8, others to 2).
MAP_ROWS, MAP_COLS, NUM_PLAYERS = resolve_size_and_players()
MAX_TURNS = _gcfg.get("max_turns", 200)

DEFAULT_B = os.path.join("weights", "trained", "duel_25ch_1000ep.pth")

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


def _setup_legacy():
    """Original no-args behavior: config-driven env + latest per-agent
    episode checkpoints (the pre-#39 weights format) if any exist."""
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

    import glob
    for i, agent in enumerate(agents):
        pattern = f"weights/agent_{i}_episode_*.pth"
        files = glob.glob(os.path.join(_PROJECT_ROOT, pattern))
        if files:
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

    labels = {i: f"P{i + 1}" for i in range(NUM_PLAYERS)}
    return env, agents, build_agents_list, labels, 0.1


def _setup_versus(args):
    """Versus/replay mode: two combined payloads via evaluate._load_side
    (registry encoders, architecture inferred from the checkpoint)."""
    import evaluate  # scripts/evaluate.py — the canonical loader + protocol

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if args.eval_json:
        with open(args.eval_json) as f:
            summary = json.load(f)
        game = summary["games_detail"][args.game]
        n = summary["map_dims"]["rows"]
        m = summary["map_dims"]["cols"]
        num_players = summary["num_players"]
        map_type = summary["map_type"]
        max_turns = summary["max_turns"]
        epsilon = summary["epsilon"] if args.epsilon is None else args.epsilon
        world_seed = game["seed"]
        a_seat = game["a_seat"]
        game_rng_seed = summary["seed_base"] + game["game_index"]
        expected = (game["winner_seat"], game["turns"])
        # The JSON knows which files/encoders it scored — CLI can override
        # (e.g. relocated files) but defaults to replay exactly what ran.
        a_weights = args.a or summary["a_weights"]
        a_encoder = args.a_encoder or summary["a_encoder"]
        b_weights = args.b or summary["b_weights"]
        b_encoder = args.b_encoder or summary["b_encoder"]
        print(f"Replaying eval game {args.game}: seed={world_seed} a_seat={a_seat} "
              f"recorded outcome={game['outcome']!r} in {game['turns']} turns")
    else:
        n, m, num_players = resolve_size_and_players(size="duel")
        map_type = "earthlike"
        max_turns = _tcfg.get("max_turns", 250)
        epsilon = 0.05 if args.epsilon is None else args.epsilon
        world_seed = args.seed if args.seed is not None else random.randrange(1 << 30)
        a_seat = 0
        game_rng_seed = world_seed
        a_weights, a_encoder = args.a, args.a_encoder
        b_weights, b_encoder = args.b, args.b_encoder
        expected = None

    if not a_weights or not a_encoder:
        raise SystemExit("versus mode needs --a and --a-encoder (or --eval-json)")

    a_agents, a_builds, _, a_ch = evaluate._load_side(a_weights, a_encoder, n, m, num_players, device)
    b_agents, b_builds, _, b_ch = evaluate._load_side(b_weights, b_encoder, n, m, num_players, device)
    print(f"A: {os.path.basename(a_weights)} ({a_encoder}, conv {a_ch}) — seat {a_seat}")
    print(f"B: {os.path.basename(b_weights)} ({b_encoder}, conv {b_ch}) — seat {1 - a_seat}")

    env = GameEnvironment(n, m, num_players, map_type=map_type)
    env.max_turns = max_turns
    env.reset(seed=world_seed)

    # Same per-game agent-side RNG discipline as evaluate.run_evaluation —
    # this is what makes --eval-json replays reproduce the scored game.
    random.seed(game_rng_seed)
    np.random.seed(game_rng_seed)
    torch.manual_seed(game_rng_seed)

    b_seat = 1 - a_seat
    agents = {a_seat: a_agents[a_seat], b_seat: b_agents[b_seat]}
    build_agents = {a_seat: a_builds[a_seat], b_seat: b_builds[b_seat]}
    labels = {
        a_seat: f"A {os.path.basename(a_weights)}",
        b_seat: f"B {os.path.basename(b_weights)}",
    }
    return env, agents, build_agents, labels, epsilon, expected


def run_viewer(env, agents, build_agents_list, labels, epsilon, smoke_frames=0,
               expected=None):
    """Render loop. `agents`/`build_agents_list` are indexable by
    player_index (list or dict); action order mirrors evaluate._play_game
    exactly so seeded games replay identically."""
    rl.init_window(SCREEN_W, SCREEN_H, b"Civulator - Live Viewer")
    rl.set_target_fps(30)

    n_rows, n_cols = env.n, env.m
    camera = make_camera(n_rows, n_cols, HEX_SIZE, SCREEN_W, SCREEN_H, zoom=0.5)

    done = False
    turn = env.turn_counter
    last_player = -1
    paused = False
    speed = 1  # Actions per frame
    frames = 0
    end_turn_idx = env.n * env.m * NUM_UNIT_SLOTS

    while not rl.window_should_close():
        frames += 1
        if smoke_frames and frames > smoke_frames:
            break

        # --- Input ---
        if rl.is_key_pressed(rl.KEY_SPACE):
            paused = not paused
        if rl.is_key_pressed(rl.KEY_UP):
            speed = min(speed * 2, 64)
        if rl.is_key_pressed(rl.KEY_DOWN):
            speed = max(speed // 2, 1)

        update_camera_zoom_pan(camera, zoom_step=0.05, zoom_min=0.1, zoom_max=3.0)
        # Re-enter from the opposite side after panning past the column-wrap
        # seam (§7.5 camera/seam policy) instead of drifting into unmapped
        # space — this is a scrolling view, unlike the painter/recorder.
        wrap_camera_x(camera, HEX_SIZE, env.m)

        # --- Game step (mirrors evaluate._play_game's order exactly) ---
        if not done and not paused:
            with torch.no_grad():
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
                                idx = ba.select_build(cs, city, env, epsilon=epsilon)
                                opt = BUILD_OPTIONS[idx]
                                if opt in City.BUILDING_COSTS:
                                    city.produce_building(opt)
                                else:
                                    city.produce_unit(opt)
                        ba.pending = []  # viewer never trains
                        last_player = pi

                    state = agent.build_state_tensor(env)
                    action = agent.select_action(state, epsilon=epsilon, game_env=env)

                    if action[0] == end_turn_idx:
                        env.current_player.end_turn()
                        env.next_turn()
                        turn = env.turn_counter
                        done = env.done
                    else:
                        tile_idx = action[0] // NUM_UNIT_SLOTS
                        slot = action[0] % NUM_UNIT_SLOTS
                        r, c = tile_idx // env.m, tile_idx % env.m
                        mr, mc = action[1] // env.m, action[1] % env.m
                        action_matrix = [np.array([r, c, slot]), np.array([mr, mc])]
                        _, reward, done = env.step(action_matrix)
                    turn = env.turn_counter

        # --- Draw ---
        rl.begin_drawing()
        rl.clear_background(rl.Color(30, 30, 35, 255))
        rl.begin_mode_2d(camera)

        # Half the visible world width — every draw below repeats the world
        # at each wrap copy inside it, so panning east cycles continuously
        # instead of jumping by one period at the seam (issue #52).
        view_half_width = SCREEN_W / (2 * camera.zoom)

        # Draw terrain
        for row in range(n_rows):
            for col in range(n_cols):
                tile = env.map.tiles[row, col]
                if tile is None:
                    continue
                cx0, cy = hex_to_pixel(row, col, HEX_SIZE, env.m)
                for cx in wrap_copies_x(cx0, camera.target.x, HEX_SIZE, env.m,
                                        view_half_width):
                    draw_hex(cx, cy, HEX_SIZE - 1, tile_color(tile))
                    draw_hex_outline(cx, cy, HEX_SIZE, rl.Color(60, 60, 60, 100))
                    draw_resource_marker(cx, cy, HEX_SIZE, tile)

        # Rivers (design doc §5 — none generate until P4; the primitive is
        # wired in now so P4's rivers appear automatically).
        draw_river_edges(env.map, HEX_SIZE, env.m, camera_x=camera.target.x,
                         view_half_width=view_half_width)

        # Draw cities
        for player in env.players:
            if player.is_dead:
                continue
            pcolor = PLAYER_COLORS[player.player_index % len(PLAYER_COLORS)]
            for city in player.cities:
                cx0, cy = hex_to_pixel(*city.coordinates, HEX_SIZE, env.m)
                for cx in wrap_copies_x(cx0, camera.target.x, HEX_SIZE, env.m,
                                        view_half_width):
                    rl.draw_circle(int(cx), int(cy), HEX_SIZE * 0.7, pcolor)
                    rl.draw_circle_lines(int(cx), int(cy), HEX_SIZE * 0.7, rl.WHITE)

        # Draw units
        for player in env.players:
            if player.is_dead:
                continue
            pcolor = PLAYER_COLORS[player.player_index % len(PLAYER_COLORS)]
            for unit in player.units:
                cx0, cy = hex_to_pixel(*unit.coordinates, HEX_SIZE, env.m)
                for cx in wrap_copies_x(cx0, camera.target.x, HEX_SIZE, env.m,
                                        view_half_width):
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
        rl.draw_text(f"Speed: {speed}x  eps={epsilon}".encode(), 10, 35, 16, rl.LIGHTGRAY)
        status = b"PAUSED" if paused else (b"GAME OVER" if done else b"RUNNING")
        rl.draw_text(status, 10, 55, 16, rl.YELLOW if paused else rl.WHITE)

        # Player scoreboard
        for i, p in enumerate(env.players):
            pcolor = PLAYER_COLORS[p.player_index % len(PLAYER_COLORS)]
            y = 80 + i * 18
            # THE score formula, not a copy of it (issue #55) — a scoreboard
            # must never disagree with determine_winner's verdict below.
            score = player_score(p)
            label = (f"{labels.get(p.player_index, f'P{p.player_index + 1}')}: "
                     f"{len(p.units)}u {len(p.cities)}c = {score}pts")
            if p.is_dead:
                label += " DEAD"
            rl.draw_text(label.encode(), 10, y, 14, pcolor)

        if done:
            w = determine_winner(env)
            # Score = cities*weight + units (determine_winner's cap tiebreak)
            # — shown so a turn-cap winner is self-explanatory in the HUD.
            result = "DRAW" if w is None else f"WINNER: {labels.get(w, f'P{w + 1}')} (score tiebreak)"
            y_result = 80 + len(env.players) * 18 + 6
            rl.draw_text(result.encode(), 10, y_result, 18, rl.GOLD)
            # Replay fidelity check: bit-exact replay needs the same float
            # arithmetic as the scored run — a BUSY GPU can flip cuDNN
            # algorithm choices and thus near-tie argmaxes. Say so loudly
            # instead of silently showing a different history.
            if expected is not None and (w, env.turn_counter) != tuple(expected):
                rl.draw_text(
                    (f"REPLAY DIVERGED from recorded game "
                     f"(recorded: winner_seat={expected[0]}, {expected[1]} turns) "
                     f"- replay on an IDLE GPU for fidelity").encode(),
                    10, y_result + 24, 16, rl.RED)

        rl.draw_text(b"SPACE=pause  UP/DOWN=speed  SCROLL=zoom  RMOUSE=pan", 10, SCREEN_H - 25, 14, rl.DARKGRAY)

        rl.end_drawing()

    rl.close_window()


def main():
    parser = argparse.ArgumentParser(description="Civulator live viewer / eval-game replayer.")
    parser.add_argument("--a", default=None, help="Side A combined weights payload (versus mode).")
    parser.add_argument("--a-encoder", default=None, help="Side A encoder registry name.")
    parser.add_argument("--b", default=DEFAULT_B,
                        help=f"Side B weights payload (default: the frozen #39 baseline {DEFAULT_B}).")
    parser.add_argument("--b-encoder", default="enhanced", help="Side B encoder (default: enhanced).")
    parser.add_argument("--eval-json", default=None,
                        help="Protocol-v1 eval summary JSON: replay one of its games exactly.")
    parser.add_argument("--game", type=int, default=0, help="Game index within --eval-json (default 0).")
    parser.add_argument("--seed", type=int, default=None,
                        help="World seed for a fresh versus game (ignored with --eval-json).")
    parser.add_argument("--epsilon", type=float, default=None,
                        help="Exploration (default: the eval JSON's, else 0.05).")
    parser.add_argument("--smoke", type=int, default=0,
                        help="Close the window after N frames (self-test).")
    args = parser.parse_args()

    if args.a or args.eval_json:
        env, agents, builds, labels, epsilon, expected = _setup_versus(args)
    else:
        env, agents, builds, labels, epsilon = _setup_legacy()
        expected = None
    run_viewer(env, agents, builds, labels, epsilon, smoke_frames=args.smoke,
               expected=expected)


if __name__ == "__main__":
    main()
