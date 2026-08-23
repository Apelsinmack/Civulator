"""Regenerate tests/fixtures/scenario_fixture.json.

Design doc §11 P7 deliverable 3 / E2: "A code-generated, manifest-stamped
fixture scenario replaces scenario_001.json in tests" — this is that
generator. `tests/test_recording.py` loads the file this script writes
through the REAL `load_scenario` / `build_env_from_scenario` path (a real
file, real manifest, real pinned mapgen params), the same way it loaded
`scenarios/scenario_001.json` before P7 archived that file to
`scenarios/archive_v0.5/`.

Regenerable and deterministic: fixed seed, "basic" map type (no earthlike
Duel-size minimum), a small 10x10 board — fast to build in every test run.
The manifest carries a full `mapgen_params` echo (`meta.build_manifest(
mapgen_params=env.map.mapgen_params)`), so loading it exercises the
production manifest-pinned rebuild path (design doc §8), not the
override/legacy fallback.

Run directly to regenerate (byte-identical output, since generation is a
pure function of the fixed SEED/ROWS/COLS below):
    python scripts/make_fixture_scenario.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.game.environment import GameEnvironment
from civulator.meta import build_manifest

SEED = 20260823
ROWS, COLS = 10, 10
MAP_TYPE = "basic"

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_PATH = os.path.join(_REPO_ROOT, "tests", "fixtures", "scenario_fixture.json")


def _passable(env, coords):
    tile = env.map.get_tile(coords)
    return tile is not None and tile.is_passable("land")


def _find_two_passable_tiles(env):
    """Two distinct land-passable (row, col) tiles, first-found order —
    deterministic given a fixed seed/board, which is all this needs.
    """
    found = []
    for row in range(env.n):
        for col in range(env.m):
            if _passable(env, (row, col)):
                found.append((row, col))
                if len(found) == 2:
                    return found
    raise RuntimeError(
        f"seed {SEED} produced fewer than 2 passable tiles on a {ROWS}x{COLS} "
        f"basic board — pick a different SEED"
    )


def main():
    env = GameEnvironment(ROWS, COLS, num_players=2, map_type=MAP_TYPE, seed=SEED)
    (r1, c1), (r2, c2) = _find_two_passable_tiles(env)

    scenario = {
        "seed": SEED,
        "terrain_seeded": True,
        "map_rows": ROWS,
        "map_cols": COLS,
        "map_type": MAP_TYPE,
        "units": [
            {"type": "Warrior", "team": 1, "row": r1, "col": c1, "fortified": False, "hp": 100},
            {"type": "Archer", "team": 2, "row": r2, "col": c2, "fortified": True, "hp": 80},
        ],
        "cities": [],
        # design doc §8: manifest-pinned world identity, embedded exactly
        # the way the Scenario Painter's own save() does it.
        "manifest": build_manifest(mapgen_params=env.map.mapgen_params),
    }

    os.makedirs(os.path.dirname(FIXTURE_PATH), exist_ok=True)
    with open(FIXTURE_PATH, "w") as f:
        json.dump(scenario, f, indent=2)
    print(f"Wrote {FIXTURE_PATH}")
    print(f"  seed={SEED} board={ROWS}x{COLS} map_type={MAP_TYPE}")
    print(f"  team-1 Warrior at {(r1, c1)}, team-2 Archer at {(r2, c2)}")


if __name__ == "__main__":
    main()
