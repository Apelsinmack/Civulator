# Civulator Changelog

Each entry documents what changed, why, and the measured effect.
Training results (plots, win histories) are in `stats/`.

---

## v0.5.1 — Portable engine RNG (PCG32) (2026-08-22)

**RNG stream change: a seed from before v0.5.1 produces a DIFFERENT world
after it.** No v0.5.0 scenario files existed yet, so nothing was invalidated —
this swap deliberately landed *before* the first reproducible scenarios were
painted. From now on the seeded world is frozen by a golden test
(tests/test_rng.py::test_engine_world_is_frozen_across_versions); changing it
again requires a version bump and CHANGELOG entry.

- `civulator/rng.py`: PortableRNG — PCG-XSH-RR 64/32, bit-verified against
  O'Neill's published pcg32 reference output. Replaces `random.Random`
  everywhere in the engine (map gen, starting locations, damage rolls).
- Purpose (#33): a future C++ engine twin can reproduce the identical random
  stream, so golden seeded games gate each ported subsystem. Derived-draw
  specs (floats, randint, shuffle, choices) documented in the module docstring
  and frozen as golden test vectors.

---

## v0.5.0 — Fog of war + ranged targeting + fortify fix (2026-08-22)

**Gameplay/training-affecting: training runs before and after this version are
not comparable baselines** (fortify became reachable, ranged attacks became
selectable; fog is opt-in).

- **Fog of war** (design: Erik + Claude, 2026-08-22). Three knowledge states —
  hidden / explored-but-fogged / visible. The engine owns perception:
  `env.get_visibility_mask(p)`, `env.get_explored_mask(p)`,
  `env.update_exploration(p)`; visibility unions unit AND city sight (cities
  have eyes), with a per-tile visibility cache on `Map` (terrain is static per
  episode, so after warm-up a mask is a union of cached sets — no LoS walks).
  The `EnhancedStateEncoder` applies fog optionally via `[training] fog_of_war`
  (default false → output bit-identical to v0.4.x, depth 25). With fog on
  (depth 27): enemy units appear only where visible, enemy cities and terrain
  where explored, plus visible+explored mask channels. C++ port of visibility
  deliberately deferred until profiling shows it hot.
- **Ranged targets in the action mask** (#30): `get_valid_moves_mask` now marks
  enemy tiles within a ranged unit's range AND rules-line-of-sight as valid
  targets — archers/catapults can finally shoot at range 2, for the agent and
  the Order Recorder alike. Rules-LoS implies the shooter sees the target, so
  the mask leaks nothing under fog.
- **Fortify fix** (#29): the slot-aware select `(r, c, slot)` never matched the
  `(r, c)` order, so the DQN agent could never fortify (always scored
  invalid_action). Fixed by comparing positions only.
- `civulator_core` C++ module now also built on the Home Desktop (cp311).

---

## v0.4.1 — Engine correctness + reproducibility (2026-08-22)

- Ranged attacks now use hex distance with cylindrical wrap, fixing incorrect
  range checks near the map seam (#24, gameplay-affecting).
- Combat/action rewards read from `config.toml` `[training.rewards]` instead of
  hardcoded literals (#25).
- Engine RNG is seedable via `reset(seed=...)`, enabling reproducible episodes (#26).
- Hex rendering extracted into a shared `civulator/viz` module — one renderer for
  the viewer and other visual tools instead of forked drawing code (#27).
- Saved artifacts (trained weights, scenarios, stats) now carry an embedded
  manifest (`civulator/meta.py`) recording the game version, git commit, full
  config, and save date that produced them (#28).

---

## v0.3.0 — Combat + City Production + Healing (2026-03-04)

### New Features

**Combat system activated in step()**
- `env.step()` now detects enemy units at the order destination and triggers attack.
- Two-click paradigm: select unit → click destination. Enemy unit = attack, empty = move,
  same tile = fortify, enemy city tile = capture after killing defender.
- Melee attacker moves into vacated tile after killing defender (Civ-style).
- Combat rewards: `damage_dealt * 0.1`, +10 for kill, -10 for being killed, +20 for city capture.

**City auto-production (Patch 1)**
- Cities now default to producing Warriors (cost 40, ~20 turns at pop 1).
- After completing a unit, auto-queue next Warrior.
- New units spawn ON the city tile (Civ-style stacking).

**Unit healing**
- +10 HP/turn base, +20 HP/turn if fortified. Capped at 100.
- Called at start of each turn via `player.start_turn()`.

**Configurable network sizes**
- `SelectAndMoveNetwork` accepts `conv_channels` and `fc_hidden` parameters.
- Four model sizes defined for tournament:
  - Small: 36k params (conv=(16,32), no fc_hidden)
  - Medium: 246k params (conv=(32,64), fc_hidden=128)
  - Large: 958k params (conv=(64,128), fc_hidden=256)
  - XL: 3.8M params (conv=(128,256), fc_hidden=512)

**Tournament script** (`scripts/tournament.py`)
- Trains all model sizes, then round-robin (100 games per matchup, 50 as each side).

**Replay tool** (`scripts/replay.py`)
- ASCII visualization of trained agents playing. Interactive (Enter per turn) or `--no-pause`.

### Training Results (500 episodes, with combat, before Patch 1)

- Player 1: 240 wins (48%), Player 2: 238 wins (48%), **Draws: 22 (4%)**
- Massive improvement from v0.1.0 baseline (76% draws → 4%)
- Episodes now ~0.3s (down from 30s in v0.1.0)

### Files Changed
- `civulator/game/environment.py` — combat in step(), _execute_attack(), _check_game_end()
- `civulator/game/city.py` — auto-production, city tile spawning
- `civulator/game/player.py` — heal() in start_turn()
- `civulator/game/unit.py` — heal() method
- `civulator/agents/networks.py` — configurable conv_channels, fc_hidden
- `civulator/agents/dqn_agent.py` — pass conv_channels, fc_hidden to network

### Files Created
- `scripts/tournament.py`
- `scripts/replay.py`
- `documents/game_state.md`
- `CHANGELOG.md`

---

## v0.2.0 — DQN Fix + Pathfinder Fix (2026-03-04)

### Bug Fixes

**Softmax removed from network output**
- The network used `F.softmax()` on both heads, squashing Q-values into a probability
  distribution that sums to 1. This broke DQN — the Bellman target can be any magnitude,
  but softmax outputs are always in [0, 1]. Loss was meaningless.
- Greedy action selection used `torch.multinomial` (sampling) instead of `argmax`.
  So even "greedy" was stochastic.
- `compute_loss()` sampled random actions for next-state Q-values instead of taking max.
- **Fix**: Raw Q-values, argmax for greedy, proper Bellman targets with `torch.no_grad()`.

**Pathfinder bypass for adjacent moves**
- `unit.move()` rejected all 1-hop moves. The pathfinder returns positions *not including
  the start*, but `move()` assumed `path[0]` was the start and skipped it. A path of
  length 1 (adjacent tile) was rejected by `if len(path) <= 1`.
- **Result**: 72% of all agent actions were invalid moves that did nothing. Episodes took
  2000-3600 steps instead of ~40. Training time was ~30s/episode instead of ~0.3s.
- **Fix**: Adjacent moves (distance 1) bypass the pathfinder entirely — direct move with
  terrain cost check. The underlying pathfinder wrapping logic (Erik's original modulus
  approach) is correct and unchanged.

**Matplotlib hang on save**
- `plt.savefig()` without `plt.close()` and without Agg backend caused the process to
  hang after training completed.
- **Fix**: Set `matplotlib.use("Agg")` and added `plt.close()`.

### Baseline Results (v0.1.0 — before fixes)

500 episodes, max 250 turns, 4x8 map, 2 players, 3 warriors each.

- Player 1: 75 wins (15%), Player 2: 46 wins (9.2%), **No winner: 379 (75.8%)**
- Win rate curve: flat, no learning trend
- ~6s/episode (but most time wasted on invalid moves)
- Stats: `stats/win_history_1772649997.npy`, `stats/win_rate_plot_1772649997.png`

### Post-Fix Results (v0.2.0)

*Training in progress — results to be added when complete.*

### Files Changed
- `civulator/agents/networks.py` — removed F.softmax from forward()
- `civulator/agents/dqn_agent.py` — argmax greedy, proper compute_loss
- `civulator/game/unit.py` — adjacent move bypass in move()
- `civulator/training/trainer.py` — Agg backend, plt.close()

---

## v0.1.0 — Package Refactoring (2026-03-03)

### Changes

**Monolithic code split into clean package structure**
- `pyCiv.py` (~2077 lines) split into: terrain.py, tile.py, map.py, unit.py, city.py,
  player.py, environment.py
- Agent code split into: networks.py, dqn_agent.py, replay_memory.py, state_encoders.py
- Training loop extracted to trainer.py
- ASCII display extracted to utils/ascii_display.py
- Entry point: scripts/train.py with CLI args

**StateEncoder abstraction**
- Abstract base class so different agents can use different state representations.
- BasicStateEncoder: 5 channels (own cities, own health, own movement, enemy cities,
  enemy health).

**Bug fixes during refactoring**
- `GameEnvironment.done` not initialized in `__init__` (would AttributeError before reset)
- `reset()` referenced `self.__class__.Player` instead of `Player`
- Move masking used 8-directional grid instead of hex adjacency
- Unit placement from cities used square grid instead of hex adjacency

**CUDA support**
- Installed PyTorch 2.6.0+cu124, confirmed RTX 3070 working.

**C# code archived**
- Moved to `archive/csharp/` — only Python codebase is active.

### Files Created
- `civulator/` package (game/, agents/, training/, utils/)
- `scripts/train.py`
- `documents/design_document.md`
- `CLAUDE.md`

---

## v0.0.0 — Original Code (pre-2026-03-03)

- Single-file game engine: `python/v2_debugging/pyCiv.py`
- Single-file DQN: `python/v2_debugging/GlobalDQNetworkSelectingAndMovingMultipleAgents.py`
- Multiple version folders used as version control
- CPU-only PyTorch
- Archived in `archive/python_versions/`
