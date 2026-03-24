# Civulator — Next Steps

_Created: 2026-03-18_

> Context: Erik has been building Breach (C++ physics engine + raylib) and gained strong C++ fluency.
> The skills transfer directly here — Civulator can benefit from C++ in performance-critical paths,
> and ML/RL lessons from Civulator feed back into Breach's future AI systems.

---

## 1. C++ Performance Module (pybind11) — LOCKED IN

_Decisions locked: 2026-03-20_

### Coordinate System: Axial (q, r) — DECIDED

We use **axial hex coordinates** as the canonical representation everywhere (Python + C++).
This replaces the current offset (even/odd row) system.

**Why axial wins:**
- Distance = `max(|dq|, |dr|, |dq + dr|)` — one subtraction, no branching
- Adjacency = same 6 direction vectors for ALL tiles, no even/odd logic
- Fully numpy-vectorizable: all neighbors of N hexes in one broadcast
- Cleaner C++ implementation

**Tradeoff accepted:** The 2D array is "skewed" — convolution filters see a parallelogram,
not a rectangle. We accept this for now (corner weights are low-importance anyway).
Hex-native convolutions are a separate future investigation.

**Cylindrical wrapping:** Only horizontal (q-axis). For A*, compare direct distance vs.
wrapped distance `|b - (a - map_width)|` and use the shorter one. A* sees the wrapped
neighbor as just another edge.

### Implementation Plan (mirrors Breach's architecture)

**Step 0: Profile** — run one training session with cProfile. Confirm pathfinding is the
bottleneck. Measure episodes/sec baseline.

**Step 1: Create `civulator/cpp/` module**
```
civulator/cpp/
├── CMakeLists.txt          # pybind11, C++17, same flags as Breach
└── src/
    ├── hex_grid.h          # Axial coords, distance, adjacency, wrapping
    ├── hex_astar.cpp       # A* with terrain costs + cylindrical wrap
    └── bindings.cpp        # Python interface
```
- Zero-copy numpy arrays (same `Grid2D<T>` pattern as Breach)
- Graceful fallback: `try: import civulator_core` → pure Python fallback

**Step 2: A* pathfinding in C++**
- Axial coordinates internally
- Terrain cost table passed from Python
- Cylindrical wrapping in neighbor generation
- Returns path as list of (q, r) tuples

### Further C++ candidates (after A* works)
- **State Encoding** — build 25-channel tensor in C++, write directly into numpy buffer
- **Combat Resolution** — damage formula + health updates
- **Hex Adjacency / Map Queries** — `get_neighbors()`, `get_tiles_in_range()`

---

## 2. ML / RL Improvements (existing plan, prioritized)

These are already documented in `documents/research_2026-03-07.md` and `documents/implementation_plan.md`.
Prioritized order for next work session:

### Immediate (fix training instability)
1. **Target network** — copy weights every N steps. This is the #1 cause of training instability.
2. **Epsilon decay** — currently fixed at 0.3. Implement linear decay (1.0 → 0.05 over ~50k episodes).
3. **Double DQN** — use online network to select action, target network to evaluate. Small change, big stability gain.

### Short-term (improve learning quality)
4. **Reward shaping** — current rewards may be too sparse. Consider intermediate rewards for:
   - Capturing territory / founding cities
   - Unit production milestones
   - Map exploration
5. **N-step returns** (n=3-5) — faster credit propagation
6. **Prioritized experience replay** — sample important transitions more often

### Medium-term (scale up)
7. **Vectorized environments** — run 8+ games in parallel (especially viable with C++ game core)
8. **Larger maps** — 8x16 → 16x32 (requires C++ pathfinding to be practical)
9. **Self-play with opponent pool** — prevents overfitting to a single opponent policy

### Long-term (architecture evolution)
10. **PPO** — likely better than DQN for this domain (continuous training, no replay buffer issues)
11. **AlphaZero-style MCTS** — gold standard for turn-based strategy games
12. **Specialist networks as input channels** — threat maps, economic value maps, settlement heuristics

---

## 3. Visualization

- Skip ASCII, go straight to **raylib** (Erik already has raylib experience from Breach)
- Or **Pygame** as documented in research — lower effort, good enough for debugging
- Decision: defer until C++ module exists, then decide based on whether we want a shared C++ rendering path with Breach

---

## 4. Breach ↔ Civulator Synergy

| Civulator teaches Breach | Breach teaches Civulator |
|---|---|
| RL training pipelines | C++ game engine patterns |
| State encoding for neural nets | raylib rendering |
| Reward shaping | Physics/simulation architecture |
| Self-play methodology | Performance optimization |

Both projects benefit from a shared C++ skills base and eventually shared AI architecture patterns.

---

## Suggested Order of Work

1. **Target network + epsilon decay** — quick wins, fix training stability (1-2 sessions)
2. **A* pathfinding in C++** — pybind11 module, hex grid, terrain costs (2-3 sessions)
3. **Benchmark** — measure episodes/sec improvement
4. **State encoder in C++** — move tensor construction to C++ (1-2 sessions)
5. **Double DQN + reward shaping** — improve learning quality (1-2 sessions)
6. **Scale to 8x16 maps** — test with C++ pathfinding
7. **Vectorized environments** — parallel game instances
8. **Visualization** — raylib or pygame, informed by where things stand

---

_This doc complements the existing plans in `documents/`. The ML roadmap there is comprehensive —
this file focuses on the C++ integration angle and prioritizes what to do next._

---

## 6. Scaling & Gameplay Roadmap (2026-03-20)

### Phase A — Today: 8-player combat on big map
- [x] All training stability fixes (target network, epsilon decay, slot stacking)
- [ ] Set up 24x48 map with 8 players, all at war (no diplomacy yet)
- [ ] Launch training run — observe if agents learn meaningful behavior
- [ ] Raylib replay viewer — minimal hex grid + colored dots for units
  - Load game state snapshots, scrub through turns
  - Reuse Breach raylib experience

### Shared-Weight Training — DONE (2026-03-24)
- [x] `train_shared.py` — one network, one replay buffer, all 8 players update same weights
- [x] 1000 episodes completed overnight, no OOM crash (~2.3 GB vs ~18 GB)
- [x] Weights saved: `weights/trained/medium_16x32_1000ep.pth`
- [x] Build orders diversified (Warriors 18%, Catapults 17%, Archers 16%, etc.)

### Tournament Plan (2026-03-24)

**Phase 1: Train all architectures** (1000 episodes each, shared weights, save at 250/500/750/1000):
- [ ] Small (8, 16) — `small_8x16_{250,500,750,1000}ep.pth`
- [x] Medium (16, 32) — done (1000ep)
- [ ] Large (32, 64) — `large_32x64_{250,500,750,1000}ep.pth`

**Phase 2: 12-player FFA tournament** (1000 episodes):
All 12 checkpoints play together:
  small_250, small_500, small_750, small_1000,
  medium_250, medium_500, medium_750, medium_1000,
  large_250, large_500, large_750, large_1000

**Phase 3: Top-6 bracket** (1000 episodes):
Top 6 from Phase 2 play another 1000 rounds.

**Open questions**:
- Does training against different AI opponents help? (mixed-level self-play vs same-level)
- Could train one AI against pretrained opponents — check literature on opponent diversity in self-play
- Is there value in 2-opponent diversity vs 8-opponent? Probably diminishing returns.

### Bugs
- [ ] **City disappearing bug** — observed a city vanishing near the start of a game (not captured, just gone). Investigate city destruction/capture logic.

### Observations from 35-episode tournament (2026-03-23)
- Agents don't play aggressively enough — after 500 turns, only 1 captured city
- Need to train combat behavior more deliberately (see "guided combat training" below)

### Next priorities
- [x] **Shared weights (self-play)** — `train_shared.py`, fixed OOM, 8x more training data per step
- [x] **Memory management** — single shared replay buffer solves OOM. `gc.collect()` added.
- [ ] **Guided combat training** — design hand-crafted engagement scenarios (surround a city, 2v1 unit fights, etc.) and feed those states directly to the optimizer. Produce many examples of combat situations that occur in real games. This should teach aggressive play much faster than waiting for random encounters on a big map.
- [ ] **Unit sprites** — replace colored dots with one sprite per unit type for more readable replays
- [ ] **Map generation fix** — current noise generates in axial space, making the skew visible in terrain. Fix: generate terrain in Cartesian (x, y) space with right angles, then sample hex tiles from that. Alternative (more elegant): multiply the noise distribution by sin(30°) or sin(60°) to correct for the axial axis angle.
- [ ] **Replay system** — save game state each turn to file, allow rewind/scrub in viewer
- [ ] **Save winning weights** — checkpoint at episodes where an agent won. Useful for beginner-level bot opponents.

### Phase B — Next session: Buildings + War/Peace
- [ ] Add Walls to build agent (BUILD_OPTIONS 7→8, +30 city defense)
- [ ] War/Peace system — pairwise relationship matrix
  - Default = peace, declare war = unilateral, peace = mutual (10-turn minimum)
  - Units can only attack enemies at war
  - New diplomacy network or extend build agent
- [ ] Staged training: freeze combat weights → train build + diplomacy on top

### Phase C — Science & Culture trees
- [ ] Science tree (unlocks units/buildings):
  - Archery → Archer
  - Bronze Working → Spearman
  - Horseback Riding → Horseman
  - Siege → Battering Ram, Catapult
  - Masonry → Walls
- [ ] Districts: Encampment (military), Campus (science), Commercial Hub
- [ ] Culture tree: policies, government types (autocracy/democracy)
  - Adjacency combat bonus as early policy
  - Traders unlocked via culture/commerce
- [ ] Rivers as tactical features (movement cost + defense bonus)

### Phase D — Full game
- [ ] Great people (slot 3)
- [ ] Full tech/civic trees
- [ ] Trade routes between cities
- [ ] Fog of war as state encoding channel (LoS system already implemented)

---

## 5. Egregore Integration — Concept Nodes for Cross-Project Transfer

_Added: 2026-03-20_

### The Idea

As we implement ML/RL techniques in Civulator, we capture each solved problem as an
**egregore concept node** — not a project-level link, but a *technique-level* knowledge
unit that lives between projects and is reusable in new contexts.

### Why

Civulator and Breach share fundamental challenges (hex/grid state encoding, action spaces,
reward shaping, neural network AI) but in different domains. The lessons from solving these
in Civulator should be directly transferable to Breach — but only if we capture the
*principle*, not just the code.

This is the core use case egregore was built for: building a lifetime of transferable
experience across projects.

### Workflow

1. **Implement a technique in Civulator** (e.g., target network, hex state encoding)
2. **Validate it works** — training curves, before/after comparison
3. **Create an egregore concept node** capturing:
   - The problem it solves (domain-agnostic description)
   - The approach and why it works
   - Reference to the specific Civulator code (file + function)
   - Notes on how to adapt it to other domains (e.g., Breach's tactical grid)
4. **When returning to Breach**, egregore surfaces relevant concept nodes

### Planned Concept Nodes (created as each technique is implemented)

| Concept | Created after | Transferable to |
|---------|--------------|-----------------|
| `hex_grid_state_encoding` | State encoder refactor | Breach grid AI |
| `action_masking_variable_spaces` | Select-and-move fix | Breach unit actions |
| `reward_shaping_sparse_games` | Reward experiments | Breach mission AI |
| `target_network_stabilization` | Target network impl | Any RL project |
| `self_play_opponent_pool` | Self-play impl | Breach adversarial AI |
| `cpp_pybind11_game_acceleration` | C++ module | Breach (already C++) |

### What This Tests in Egregore

This is the first real test of egregore's value: can concept nodes surface the right
knowledge at the right time when switching between projects? Usage will be logged and
reviewed to guide egregore's own development (representation, retrieval, usefulness).
