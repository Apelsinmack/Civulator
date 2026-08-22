# Civulator - Project CLAUDE.md

> **Last updated**: 2026-08-22 — rules-first restructure. Narrative moved to `docs/`/`documents/`; tasks moved to GitHub issues.

## What Is This?

Civulator is a **research project**: deep reinforcement learning in a simplified Civilization-like hex strategy game. We don't just build an agent — we **systematically measure what works**, comparing architectures, state representations, reward functions, and training configurations through controlled experiments. The active codebase is the Python package `civulator/` plus the C++ module `cpp/` (pybind11 → `civulator_core`); the original C# engine is archived.

## Where things live

- **Rules** (invariants + canonical systems): this file. Keep it lean — narrative does not belong here.
- **Tasks & roadmap**: GitHub issues at `Apelsinmack/Civulator`; the roadmap is the milestones **A: Combat**, **B: Peacetime growth**, **C: Diplomacy**.
- **Narrative** (design thinking, specs, results discussion): `docs/` and `documents/`. Gameplay-rule changes with measured effects: `CHANGELOG.md` (semver game version).
- **Scientific record**: `stats/`, `weights/trained/` (+ its `manifest.md` registry). Never delete previous results.

## Rules (invariants)

- **The engine is a pure simulation.** `civulator/game/` must never import torch, matplotlib, or anything from `civulator/agents/`. Agents read raw state through `GameEnvironment` and build their own tensors (`StateEncoder.encode`).
- **Research method**: baseline first; one variable at a time; every change documented with training curves / win rates; fixed seeds and logged hyperparameters. The engine is seedable: `env.reset(seed=N)` reproduces a world exactly — use it in every experiment.
- **Axial (q, r) coordinates only**, stored as `(row=r, col=q)` in a 2D array, cylindrical wrap on q. Never write new adjacency/distance/path code — use the canonical hex math below (the ranged-attack bug #24 is what happens otherwise).
- **All gameplay constants live in `config.toml`** — no hardcoded gameplay numbers in new code.
- **Every training artifact gets recorded**: new weights/scenarios/stats carry an embedded machine-readable manifest via `civulator/meta.py` (issue #28); still hand-write new weights into `weights/trained/manifest.md` too (naming: `{size}_{channels}_{episodes}ep.pth`).

## Canonical systems — check this table before building anything new

One line per system built for reuse. If what you need is here, use it; if it almost fits, extend it — never build a parallel copy.

| System | Where | Rule |
|---|---|---|
| Game interface | `GameEnvironment` (`game/environment.py`) | The only way to create/step/mutate game state. Trainer, viewer, painter, recorder all go through it |
| Hex math | `Map.distance_function` / `get_adjacent_coords` / `path_finder` (`game/map.py`) + `civulator_core` (C++ A*, Python fallback) | The only hex distance/adjacency/pathfinding — never reimplement |
| Gameplay config | `config.toml` via `CFG` (`civulator/config.py`) | Single source for terrain, LoS, map gen, game and training params |
| Unit system | `Unit` + data tables + `UNIT_SLOT` (`game/unit.py`); 4 stacking slots | Adding a unit type touches: the 5 tables + `UNIT_SLOT` (unit.py), `_create_unit` (city.py), `CLASS_INDEX` (state_encoders.py) — all three files, every time |
| Combat | `Unit.attack` + `calculate_damage` (Civ6 formula) + `GameEnvironment._execute_attack` | All damage flows through this path |
| City economy | `City.process_turn` / `assign_tiles` (`game/city.py`) | Food → growth → production logic lives here only |
| Line of sight | `Map.check_line_of_sight` + `Terrain.LOS` | Obstacle/vantage levels come from config.toml |
| State encoding | `StateEncoder` ABC (`agents/state_encoders.py`): Basic (2N+1 ch), Enhanced (25 ch) | New representations subclass it; never fork an agent to change encoding |
| Action masking | `get_valid_select_mask` / `get_valid_moves_mask` (`agents/networks.py`) | Agent masks AND human-tool click-highlighting must share these — anything else creates train/play skew |
| DQN stack | `DQNAgent`, `ReplayMemory`, `BuildAgent` (`agents/`), `train_agents` (`training/trainer.py`) | One of each; experiments parameterize, don't fork |
| Networks | `SelectAndMove` / `SharedBackbone` / `FullyConv` / `FullyConvSeparate` (`agents/networks.py`) | FullyConv variants are map-size independent — required for large maps |
| Hex renderer | `civulator/viz/hex_render.py` (hex↔pixel, drawing, terrain colors, camera, sprites) | All visual tools import it; no forked rendering code. `viz/` may use pyray/numpy, never torch; the engine never imports `viz/` |
| Artifact manifests | `civulator/meta.py` (`build_manifest` / `save_weights` / `load_weights`) | Everyone saving or loading weights/scenarios/stats embeds and reads manifests through this module |

## Tech stack

- Python 3, PyTorch (CUDA), NumPy; pyray for visual tools.
- C++ module: `cpp/` (pybind11 + CMake) → `civulator_core`; imports fall back to pure Python gracefully.

## Related Projects

- **Breach** — shares hex/grid AI patterns, C++/pybind11 architecture, and RL lessons both ways.
