# Civulator — Next Steps

_Created: 2026-03-18_

> Context: Erik has been building Breach (C++ physics engine + raylib) and gained strong C++ fluency.
> The skills transfer directly here — Civulator can benefit from C++ in performance-critical paths,
> and ML/RL lessons from Civulator feed back into Breach's future AI systems.

---

## 1. C++ Performance Module (via pybind11 or ctypes)

The game simulation is the training bottleneck. Key candidates for C++ extraction:

### High Priority
- **A* Pathfinding** — currently greedy and terrain-unaware. Needs rewrite anyway (known issue).
  Writing it in C++ from scratch makes sense: hex grid A* with terrain costs, obstacle avoidance,
  cylindrical wrap. This is the single biggest win — pathfinding runs every unit every turn.
- **State Encoding** — `EnhancedStateEncoder` builds 25-channel tensors from game state every step.
  A C++ encoder writing directly into a NumPy buffer would eliminate Python overhead in the
  innermost training loop.

### Medium Priority
- **Combat Resolution** — damage formula + health updates. Small function but called frequently.
- **Hex Adjacency / Map Queries** — `get_neighbors()`, `get_tiles_in_range()`, distance calculations.
  These are called constantly by pathfinding, combat, and state encoding.

### Approach
- Use **pybind11** to expose C++ functions as a Python module (e.g., `civulator_core`)
- Keep the game logic authoritative in Python; C++ module accelerates hot paths
- Benchmark before/after — target: 10x+ speedup on episodes/second
- This enables training on larger maps (16x32, 32x64) which is currently impractical

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
