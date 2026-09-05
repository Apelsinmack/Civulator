# Civulator - Project CLAUDE.md

> **Last updated**: 2026-09-05 — canonical-systems rows name seams, not instances (see the note under the table); #64 combat/unit constants moved to `config.toml` (`civulator/unit_model.py`), bit-identical. Prior: 2026-08-26 — #42 mask vectorization + #40 terrain-aware encoder (52ch) with encoder registry. Encoder spec: `docs/terrain_encoder_design.md`.

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
- **Reports state only what was measured** (rule added 2026-09-04 after two errors in one report: a three-game probe written up as a property of the ladder, and 50 livelocked games — issue #51 — read as battles). Every quantitative claim names the artifact it came from (stats JSON / log path) and the sample size; a claim from N games says "N games", never "the runs". Behavioural claims ("nobody expands", "they never fight") require a population-level count from the instrumented eval, not a spot check. Before any claim rests on games ending early or on unusual counts, exclude truncated games — read `truncated_games` / `games_detail[].truncated` (eval) or `truncated_episodes` (training) from the run record, falling back to `Step limit exceeded` in the log for runs recorded before #51. Prefer numbers a reader can re-derive from a committed artifact with a named script; when a claim cannot be backed that way, say so in the report instead of rounding it into a conclusion. Corrections are appended to the report in place, never silently overwritten.

## Canonical systems — check this table before building anything new

One line per system built for reuse. If what you need is here, use it; if it almost fits, extend it — never build a parallel copy.

**What belongs in a row (tightened 2026-09-05, Erik: the table "is meant to list all systems that we plug into", and it had crept).** A row names the **seam you plug into** — the ABC, the registry, the single entry point — and says who must use it. A row is **not an inventory of that system's instances**: encoders, unit types, network variants, presets and trained models are *instances*, and enumerating them here guarantees a stale table, because instances are added far more often than seams. List instances where they live — the registry in code, `weights/trained/manifest.md`, the system's own design doc — and let the row point at that place. Ask of any proposed row: *would a new instance of this force an edit here?* If yes, the row is written at the wrong altitude.

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
| Gameplay config | `config.toml` via `CFG` (`civulator/config.py`); `[units.*]` + `[combat]` (issue #64) | Single source for terrain, LoS, map gen, game, unit/combat and training params |
| Unit system | `Unit` (`game/unit.py`); 5 stat tables in `config.toml` `[units.*]` (issue #64); `UNIT_SLOT` + `MOVEMENT_DOMAIN` still in `unit.py`; 4 stacking slots | Adding a unit type touches: a new `[units.<Name>]` table (config.toml) + `UNIT_SLOT` + `MOVEMENT_DOMAIN` (unit.py), `_create_unit` (city.py), `CLASS_INDEX` (state_encoders.py) — every one of these, every time |
| Unit/combat config interpreter | `civulator/unit_model.py` — the only interpreter of `[units.*]` / `[combat]` / city health+defense in `config.toml` (issue #64) | Nothing reads `[units.*]`/`[combat]` from `CFG` directly; `game/unit.py` and `game/city.py` import from this module; no new hardcoded combat number anywhere else. Bit-identity gate: `tests/test_unit_config_identity.py` |
| Combat | `Unit.attack` + `calculate_damage` (Civ6 formula) + `GameEnvironment._execute_attack` | All damage flows through this path |
| City economy | `City.process_turn` / `assign_tiles` (`game/city.py`) | Food → growth → production logic lives here only |
| Win/score determination | `determine_winner` + `player_score` (`training/trainer.py`); weight in `[game] city_score_weight` | The only verdict and the only score formula — trainer, evaluate and the viewer HUD all call these, so a displayed score can never disagree with the verdict beside it (#55). Elimination wins outright; the cap falls back to the score tiebreak, dead players ranked -1 |
| Line of sight | Rules: `Map.check_line_of_sight` over composed tile `los` (terrain_model). Perception: `env.get_visibility_mask` / `get_explored_mask` / `update_exploration` (epoch-cached on `Map`) | One LoS system, two surfaces. Fog is applied by the ENCODER (`[training] fog_of_war`), never by the engine — the engine always knows the truth |
| State encoding | `StateEncoder` ABC (`agents/state_encoders.py`) — the seam. The encoders that exist, with their channel counts, are the registry in that module (see the row below); do not re-list them here | New representations **subclass** it; never fork an agent to change encoding. Terrain channels belong in `TerrainAware`'s block — never add ad-hoc terrain channels elsewhere (spec: `docs/terrain_encoder_design.md`) |
| Encoder registry | `get_encoder(name, fog_of_war=None)` (`agents/state_encoders.py`); `[training] encoder` in config.toml | The only way scripts, trainer, and `DQNAgent` obtain an encoder — never instantiate encoder classes directly; unknown names raise |
| Action masking | `get_valid_select_mask` / `get_valid_moves_mask` over `_valid_order_mask_np` (`agents/networks.py`) | Agent masks AND human-tool click-highlighting must share these — anything else creates train/play skew. **A mask must never offer an action that cannot change the state**: `invalid_action` consumes nothing, so a greedy policy repeats it until the step guard (#51 — 85 truncated training episodes, 50 of 200 eval games). Every new engine precondition on an order goes into the mask too |
| Movement cost | `Unit.step_cost` (`game/unit.py`) — destination tile cost + river crossing | The one price of one step: `Unit.move` (both branches) and the action masks read it, so the mask can never offer a step the unit cannot pay for (#51) |
| Run truncation | `STEP_LIMIT` in `scripts/evaluate.py` and `training/trainer.py`; reported via `games_detail[].truncated` + `truncated_games`, and `train_agents(truncated_episodes=[...])` | Hitting the step guard is a bug, never an outcome — it must reach the machine-readable record, never be scored as a draw (#51). Same in-place-list contract as `skipped_seeds` (#44) |
| DQN stack | `DQNAgent`, `ReplayMemory`, `BuildAgent` (`agents/`), `train_agents` (`training/trainer.py`) | One of each; experiments parameterize, don't fork |
| Networks | `agents/networks.py` — the Q-network seam; the variants that exist are the classes in that module | New architectures go in that module, never in a forked agent. **FullyConv variants are map-size independent — required for large maps**; anything not map-size independent cannot run the larger presets |
| Hex renderer | `civulator/viz/hex_render.py` (brick-rectangle hex↔pixel with wrap, layer compositing, river edges, start markers, camera + seam wrap, sprites) | All visual tools import it; no forked rendering code. The adjacency-render invariant test pins it to engine adjacency. `viz/` may use pyray/numpy, never torch; the engine never imports `viz/` |
| Artifact manifests | `civulator/meta.py` (`build_manifest` / `check_version` / `save_weights` / `load_weights`) | Everyone saving or loading weights/scenarios/stats embeds and reads manifests through this module; every scenario/recording loader calls `check_version` and rebuilds worlds from the manifest's pinned mapgen params |
| Combat-training tools | Painter: `scripts/scenario_painter.py`. Recorder: `scripts/order_recorder.py` on `civulator/tools/recording.py` (`RecordingSession`) | The only authoring path for scenarios and demonstrations — recorded data stays in the agent's exact action space. Extend these; never build a second editor/recorder |
| Evaluation harness | `scripts/evaluate.py` (protocol v1 — ratification pending; seeded paired-sides head-to-head, per-seat weights, own encoder per side) | The only way to measure agent-vs-agent strength in the v0.6 epoch; `tournament.py`'s play_match is pre-0.6 legacy. Extend this; never write a second eval loop |

## Tech stack

- Python 3, PyTorch (CUDA), NumPy; pyray for visual tools.
- C++ module: `cpp/` (pybind11 + CMake) → `civulator_core`; imports fall back to pure Python gracefully.

## Related Projects

- **Breach** — shares AI patterns, C++/pybind11 architecture, and RL lessons both ways.
