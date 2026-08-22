# Civulator - Project CLAUDE.md

> **Last updated**: 2026-08-22 — rules-first restructure. Narrative moved to `docs/`/`documents/`; tasks moved to GitHub issues.

## What Is This?

Civulator is a **research project**: deep reinforcement learning in a simplified Civilization-like hex strategy game. We don't just build an agent — we **systematically measure what works**, comparing architectures, state representations, reward functions, and training configurations through controlled experiments. The active codebase is the Python package `civulator/` plus the C++ module `cpp/` (pybind11 → `civulator_core`); the original C# engine is archived.

## Where things live

- **Rules** (invariants + canonical systems): this file. Keep it lean — narrative does not belong here.
- **Tasks**: GitHub issues at `Apelsinmack/Civulator`. Milestones are the big goals: **A: Combat**, **B: Peacetime growth**, **C: Diplomacy**. Roadmap lists in markdown files are forbidden — they drift.
- **Narrative** (design thinking, specs, results discussion): `docs/` and `documents/`. Gameplay-rule changes with measured effects: `CHANGELOG.md` (semver game version).
- **Scientific record**: `stats/`, `weights/trained/` (+ its `manifest.md` registry). Never delete previous results.

## Rules (invariants)

- **The engine is a pure simulation.** `civulator/game/` must never import torch, matplotlib, or anything from `civulator/agents/`. Agents read raw state through `GameEnvironment` and build their own tensors (`StateEncoder.encode`).
- **Research method**: baseline first; one variable at a time; every change documented with training curves / win rates; fixed seeds and logged hyperparameters. (True engine reproducibility is blocked until seedable RNG lands — issue #26.)
- **Axial (q, r) coordinates only**, stored as `(row=r, col=q)` in a 2D array, cylindrical wrap on q. Never write new adjacency/distance/path code — use the canonical hex math below (the ranged-attack bug #24 is what happens otherwise).
- **All gameplay constants live in `config.toml`** — no hardcoded gameplay numbers in new code (known pre-existing drift: rewards, issue #25).
- **Every training artifact gets recorded**: for now, hand-write new weights into `weights/trained/manifest.md` (naming: `{size}_{channels}_{episodes}ep.pth`); embedded machine-readable manifests are issue #28.

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
| Hex renderer | `scripts/watch.py` (extraction into a shared module: issue #27) | Base for all visual tools; no more forked rendering code |

## Environment

- Python: anaconda base env; PyTorch with CUDA for training; pyray for viewers.
- C++: `cpp/` built with CMake + MSVC; import falls back to pure Python gracefully.
- Machine specifics (paths, GPUs, env names) live in `environment.md` / the `machine-env` skill — not here.

## Related Projects

- **Breach** — shares hex/grid AI patterns, C++/pybind11 architecture, and RL lessons both ways.
