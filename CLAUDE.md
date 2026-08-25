# Civulator - Project CLAUDE.md

> **Last updated**: 2026-08-26 — #42 mask vectorization + #40 terrain-aware encoder (52ch) with encoder registry. Encoder spec: `docs/terrain_encoder_design.md`.

## What Is This?

Civulator is a **research project**: deep reinforcement learning in a simplified Civilization-like hex strategy game. We don't just build an agent — we **systematically measure what works**, comparing architectures, state representations, reward functions, and training configurations through controlled experiments. The active codebase is the Python package `civulator/` plus the C++ module `cpp/` (pybind11 → `civulator_core`); the original C# engine is archived.

## Where things live

- **Rules** (invariants + canonical systems): this file. Keep it lean — narrative does not belong here.
- **Tasks & roadmap**: GitHub issues at `Apelsinmack/Civulator`; the roadmap is the milestones **A: Combat**, **B: Peacetime growth**, **C: Diplomacy**.
- **Session handoff**: pinned issue #31 — read its newest comment when starting a session; append one comment at session close (done / next / open questions). Only the latest comment is current.
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
| Hex math | Pure kernels in `civulator/hexmath.py` (directions, wrap distance, adjacency, axial↔Cartesian); `Map` delegates; `path_finder` (`game/map.py`) + `civulator_core` (C++ A*, Python fallback) | The only hex distance/adjacency/pathfinding — game, mapgen, viz all call the same kernels; never reimplement |
| Terrain model | `civulator/terrain_model.py` (`compose`, `matches`/`validate`, `can_enter`) over the `[terrain.*]` config tables | The only interpreter of tile gameplay numbers and `on` placement validity — `Tile`, generator, painter, fertility, improvements all read through it; no code reads terrain names for gameplay values |
| World generation | `civulator/mapgen/` (pure: numpy + hexmath + terrain_model): `generate(seed, size, num_players, params) → MapData`; `noise.py` (the only mapgen randomness — coordinate-hashed, §4.2 discipline), `stats.py` (map-quality metrics), preview CLI `python -m civulator.mapgen` | The only world synthesis. Engine builds Tiles from `MapData`; loaders rebuild with manifest-pinned params, never live config; `MapData` fields change only with a golden re-baseline |
| Passability | `unit.can_enter(tile)` / per-domain cost grids on `Map` (epoch-cached) | The only terrain-passability check — masks, pathfinding, spawning, tools all route through it; the C++ `≥99` cost is the A* adapter encoding, written only by the grid builder |
| Fresh water | `MapData.fresh_water` → `Map`'s cached mask | The single fresh-water query surface (start scoring now; housing later) |
| Start placement | `civulator/mapgen/starts.py` (fertility → equal-fertility regions → d_min → additive normalization) | The only start-position authority; `reset` consumes its output — seeded resets raise on failure, unseeded resample with logged bounded retries (`[map] max_world_retries`) |
| Size presets | `[map.sizes.*]` via `resolve_size_and_players` (`game/environment.py`) | The only source of map dimensions and player counts; explicit rows/cols remain for tests and tool boards |
| Terrain epoch | `Map.terrain_epoch` + `map_uid`; bumped by `Tile.set_layers` and river mutations | Every terrain-derived cache (LoS, fresh water, cost grids, encoder layers) keys on it — never cache terrain products without it |
| Engine RNG | `PortableRNG` (`civulator/rng.py`, PCG32) | The only randomness in episode simulation (damage rolls, shuffles); world synthesis takes exactly one master-seed draw from it at reset |
| Gameplay config | `config.toml` via `CFG` (`civulator/config.py`) | Single source for terrain, LoS, map gen, game and training params |
| Unit system | `Unit` + data tables + `UNIT_SLOT` (`game/unit.py`); 4 stacking slots | Adding a unit type touches: the 6 tables incl. `MOVEMENT_DOMAIN` + `UNIT_SLOT` (unit.py), `_create_unit` (city.py), `CLASS_INDEX` (state_encoders.py) — all three files, every time |
| Combat | `Unit.attack` + `calculate_damage` (Civ6 formula) + `GameEnvironment._execute_attack` | All damage flows through this path |
| City economy | `City.process_turn` / `assign_tiles` (`game/city.py`) | Food → growth → production logic lives here only |
| Line of sight | Rules: `Map.check_line_of_sight` over composed tile `los` (terrain_model). Perception: `env.get_visibility_mask` / `get_explored_mask` / `update_exploration` (epoch-cached on `Map`) | One LoS system, two surfaces. Fog is applied by the ENCODER (`[training] fog_of_war`), never by the engine — the engine always knows the truth |
| State encoding | `StateEncoder` ABC (`agents/state_encoders.py`): Basic (2N+1 ch), Enhanced (25 ch), TerrainAware (52 ch: Enhanced prefix + 27ch terrain block) | New representations subclass it; never fork an agent to change encoding. Terrain channels belong in TerrainAware's block — never add ad-hoc terrain channels elsewhere (spec: `docs/terrain_encoder_design.md`) |
| Encoder registry | `get_encoder(name, fog_of_war=None)` (`agents/state_encoders.py`); `[training] encoder` in config.toml | The only way scripts, trainer, and `DQNAgent` obtain an encoder — never instantiate encoder classes directly; unknown names raise |
| Action masking | `get_valid_select_mask` / `get_valid_moves_mask` (`agents/networks.py`) | Agent masks AND human-tool click-highlighting must share these — anything else creates train/play skew |
| DQN stack | `DQNAgent`, `ReplayMemory`, `BuildAgent` (`agents/`), `train_agents` (`training/trainer.py`) | One of each; experiments parameterize, don't fork |
| Networks | `SelectAndMove` / `SharedBackbone` / `FullyConv` / `FullyConvSeparate` (`agents/networks.py`) | FullyConv variants are map-size independent — required for large maps |
| Hex renderer | `civulator/viz/hex_render.py` (brick-rectangle hex↔pixel with wrap, layer compositing, river edges, start markers, camera + seam wrap, sprites) | All visual tools import it; no forked rendering code. The adjacency-render invariant test pins it to engine adjacency. `viz/` may use pyray/numpy, never torch; the engine never imports `viz/` |
| Artifact manifests | `civulator/meta.py` (`build_manifest` / `check_version` / `save_weights` / `load_weights`) | Everyone saving or loading weights/scenarios/stats embeds and reads manifests through this module; every scenario/recording loader calls `check_version` and rebuilds worlds from the manifest's pinned mapgen params |
| Combat-training tools | Painter: `scripts/scenario_painter.py`. Recorder: `scripts/order_recorder.py` on `civulator/tools/recording.py` (`RecordingSession`) | The only authoring path for scenarios and demonstrations — recorded data stays in the agent's exact action space. Extend these; never build a second editor/recorder |

## Tech stack

- Python 3, PyTorch (CUDA), NumPy; pyray for visual tools.
- C++ module: `cpp/` (pybind11 + CMake) → `civulator_core`; imports fall back to pure Python gracefully.

## Related Projects

- **Breach** — shares AI patterns, C++/pybind11 architecture, and RL lessons both ways.
