"""Standalone mapgen preview CLI (design doc §4.1 D17, §11 P3 deliverable 4).

    python -m civulator.mapgen --seed 42 --size standard --type earthlike
    python -m civulator.mapgen --seed 42 --size duel --type basic --png out.png
    python -m civulator.mapgen --rows 20 --cols 40 --type earthlike

Interactive keys: N = new (random) seed, S = screenshot, arrows/right-mouse-
drag = pan, mouse wheel = zoom. `--png PATH` renders one frame and saves
it directly (no interactive loop) — used by the P3 smoke test and any
scripted/CI use.

The one module in `civulator.mapgen` allowed to import outside numpy/stdlib/
hexmath/terrain_model (design doc §4.1): `civulator.config` (to resolve
`[map.sizes.*]` / `[map.earthlike]`, the same "read config once at the call
boundary" role `Map.generate_map` plays for the engine) and `civulator.viz`
(the renderer) and `civulator.game.tile.Tile` (so `viz.hex_render.tile_color`
— which reads `.base_terrain`/`.relief`/`.feature`/`.resource` off a real
Tile — can be reused as-is instead of forking a second terrain-color path).
"""

import argparse
import os
import random
import shutil
import sys
import types

import pyray as rl

from ..config import CFG
from ..game.tile import Tile
from ..viz.hex_render import (
    draw_hex,
    draw_hex_outline,
    draw_resource_marker,
    draw_river_edges,
    draw_start_marker,
    hex_to_pixel,
    make_camera,
    tile_color,
    update_camera_zoom_pan,
    wrap_camera_x,
    wrapped_draw_x,
)
from . import MAP_TYPES, generate
from .data import resolve_size
from .starts import StartPlacementError

HEX_SIZE = 12
SCREEN_W = 1400
SCREEN_H = 850
PAN_SPEED = 400.0  # pixels/sec at zoom=1, arrow-key panning


def _build_tiles(map_data):
    """MapData grids -> a (rows, cols) array of real `Tile`s, so
    `viz.hex_render.tile_color`/`draw_resource_marker` (which read
    `.base_terrain`/`.relief`/`.feature`/`.resource`) work unmodified —
    reusing the one canonical terrain-color path instead of forking it.
    """
    rows, cols = map_data.rows, map_data.cols
    tiles = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            tiles[r][c] = Tile(
                r, c, map_data.base_terrain[r, c],
                relief=map_data.relief[r, c],
                feature=map_data.feature[r, c],
                resource=map_data.resource[r, c],
            )
    return tiles


def _draw_frame(tiles, rivers, starts, rows, cols, camera, show_starts=True):
    rl.begin_drawing()
    rl.clear_background(rl.Color(30, 30, 35, 255))
    rl.begin_mode_2d(camera)

    for r in range(rows):
        for c in range(cols):
            tile = tiles[r][c]
            cx, cy = hex_to_pixel(r, c, HEX_SIZE, cols)
            cx = wrapped_draw_x(cx, camera.target.x, HEX_SIZE, cols)
            draw_hex(cx, cy, HEX_SIZE - 1, tile_color(tile))
            draw_hex_outline(cx, cy, HEX_SIZE, rl.Color(60, 60, 60, 100))
            draw_resource_marker(cx, cy, HEX_SIZE, tile)

    draw_river_edges(
        types.SimpleNamespace(rivers=rivers), HEX_SIZE, cols, camera_x=camera.target.x
    )

    # Start-position markers (design doc §11 P7.5) — drawn last, on top of
    # terrain/rivers/resources, so they read clearly at a glance; toggled
    # with T, shown by default (Erik inspects start fairness at the P8
    # ceremony without an extra keypress).
    if show_starts:
        for (r, c) in starts:
            cx, cy = hex_to_pixel(r, c, HEX_SIZE, cols)
            cx = wrapped_draw_x(cx, camera.target.x, HEX_SIZE, cols)
            draw_start_marker(cx, cy, HEX_SIZE)

    rl.end_mode_2d()
    rl.end_drawing()


def _screenshot(path):
    """Save a screenshot to an ARBITRARY path (`rl.take_screenshot` only
    ever writes relative to the process's current working directory,
    silently dropping any directory component passed to it — verified
    during the P3 smoke test, which otherwise left a stray PNG in the repo
    root instead of the requested path). Takes the shot under a throwaway
    cwd-relative name, then moves it to `path` (creating parent directories
    if needed), so `--png` and the interactive `S` key both work with any
    absolute path a caller gives them.
    """
    tmp_name = f".mapgen_screenshot_{os.getpid()}.png"
    rl.take_screenshot(tmp_name.encode())
    out_dir = os.path.dirname(os.path.abspath(path))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    shutil.move(tmp_name, path)


def _draw_warmed_up_frame(tiles, rivers, starts, rows, cols, camera, show_starts=True, warmup_frames=3):
    """Draw `warmup_frames` throwaway frames, then the real one, and return
    right after — `rl.take_screenshot` reads back a buffer that (verified
    during the P3 smoke test) is still blank after only ONE `begin_drawing`/
    `end_drawing` pair right after `init_window`; a couple of extra
    presented frames before the one that matters reliably fixes it.
    """
    for _ in range(warmup_frames):
        _draw_frame(tiles, rivers, starts, rows, cols, camera, show_starts)
    _draw_frame(tiles, rivers, starts, rows, cols, camera, show_starts)


def _resolve_cli_size_and_players(args):
    sizes_table = CFG.get("map", {}).get("sizes", {})
    if args.rows is not None and args.cols is not None:
        rows, cols = int(args.rows), int(args.cols)
        preset = {}
    else:
        rows, cols = resolve_size(args.size, sizes_table)
        preset = sizes_table.get(args.size, {})
    if args.players is not None:
        players = int(args.players)
    else:
        # Named preset -> its default_players; bare rows/cols fall back to
        # generate()'s own default (2). The status line always shows the
        # count, so a 2-capital world can't be mistaken for a preset default.
        players = int(preset.get("default_players", 2))
    return rows, cols, players


def _resolve_cli_params(map_type):
    """Same config.toml -> explicit `params` translation `Map.generate_map`
    does (design doc §4.1: mapgen itself never reads config) — kept here
    too, not imported from there, since this is the CLI's OWN "read config
    once at the call boundary" moment, independent of the engine's.
    """
    map_cfg = CFG.get("map", {})
    if map_type == "earthlike":
        return map_cfg.get("earthlike", {})

    params = {}
    if map_cfg.get("terrain_weights"):
        params["terrain_weights"] = map_cfg["terrain_weights"]
    features_cfg = map_cfg.get("features", {})
    feature_chance = {}
    if "woods_chance" in features_cfg:
        feature_chance["woods"] = features_cfg["woods_chance"]
    if "rainforest_chance" in features_cfg:
        feature_chance["rainforest"] = features_cfg["rainforest_chance"]
    if feature_chance:
        params["feature_chance"] = feature_chance
    return params


def run_preview(argv=None):
    parser = argparse.ArgumentParser(prog="python -m civulator.mapgen", description=__doc__)
    parser.add_argument("--seed", type=int, default=None, help="master seed (random if omitted)")
    parser.add_argument("--size", type=str, default="standard", help="named preset from [map.sizes.*]")
    parser.add_argument("--rows", type=int, default=None, help="override: explicit row count")
    parser.add_argument("--cols", type=int, default=None, help="override: explicit column count")
    parser.add_argument("--type", dest="map_type", choices=MAP_TYPES, default="earthlike")
    parser.add_argument("--players", type=int, default=None,
                        help="number of players/starts (default: the size preset's default_players)")
    parser.add_argument("--png", type=str, default=None, help="render one frame, save it here, exit")
    args = parser.parse_args(argv)

    rows, cols, players = _resolve_cli_size_and_players(args)
    seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)
    params = _resolve_cli_params(args.map_type)

    rl.init_window(SCREEN_W, SCREEN_H, b"Civulator - Mapgen Preview")
    rl.set_target_fps(60)
    camera = make_camera(rows, cols, HEX_SIZE, SCREEN_W, SCREEN_H, zoom=0.6)

    map_data = generate(seed, (rows, cols), num_players=players, params=params, map_type=args.map_type)
    tiles = _build_tiles(map_data)
    # Shown by default (design doc §11 P7.5: Erik inspects start fairness at
    # the P8 ceremony) — T toggles, in both the --png one-shot render and
    # the interactive loop.
    show_starts = True

    if args.png:
        _draw_warmed_up_frame(tiles, map_data.rivers, map_data.starts, rows, cols, camera, show_starts)
        _screenshot(args.png)
        rl.close_window()
        print(f"Saved {args.png} (seed={seed}, {rows}x{cols}, {players}p, type={args.map_type})")
        return

    print(f"seed={seed} size={rows}x{cols} players={players} type={args.map_type} — "
          f"N=new seed  S=screenshot  T=toggle starts  arrows/drag=pan  wheel=zoom  ESC=quit")

    while not rl.window_should_close():
        if rl.is_key_pressed(rl.KEY_N):
            # A random reroll may hit a world where fair placement is
            # impossible (D26: ~2% of seeds) — skip those with a note
            # rather than crashing the preview.
            for _ in range(20):
                seed = random.randint(0, 2**31 - 1)
                try:
                    map_data = generate(seed, (rows, cols), num_players=players,
                                        params=params, map_type=args.map_type)
                    break
                except StartPlacementError:
                    print(f"seed={seed}: no fair start placement for {players}p, rerolling")
            tiles = _build_tiles(map_data)
            print(f"seed={seed}")

        if rl.is_key_pressed(rl.KEY_T):
            show_starts = not show_starts
            print(f"show_starts={show_starts}")

        if rl.is_key_pressed(rl.KEY_S):
            out = f"mapgen_seed{seed}_{rows}x{cols}.png"
            _draw_frame(tiles, map_data.rivers, map_data.starts, rows, cols, camera, show_starts)
            _screenshot(out)
            print(f"Saved {out}")

        update_camera_zoom_pan(camera, zoom_step=0.05, zoom_min=0.1, zoom_max=3.0)
        dt = rl.get_frame_time()
        step = PAN_SPEED * dt / max(camera.zoom, 0.05)
        if rl.is_key_down(rl.KEY_LEFT):
            camera.target.x -= step
        if rl.is_key_down(rl.KEY_RIGHT):
            camera.target.x += step
        if rl.is_key_down(rl.KEY_UP):
            camera.target.y -= step
        if rl.is_key_down(rl.KEY_DOWN):
            camera.target.y += step
        wrap_camera_x(camera, HEX_SIZE, cols)

        _draw_frame(tiles, map_data.rivers, map_data.starts, rows, cols, camera, show_starts)

    rl.close_window()


if __name__ == "__main__":
    run_preview(sys.argv[1:])
