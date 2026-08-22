# Civulator — Big Goals & Locked Decisions

> Slimmed 2026-08-22: roadmap and task lists moved to the GitHub issue tracker
> (`Apelsinmack/Civulator`, milestones A/B/C). This file keeps only the goals and
> decisions that are settled. Full historical roadmaps: git history of this file.

## Big Goals (Erik)

**A. Combat** — civs have to be able to wage effective war: if they can capture, they should capture. They should play effectively!

**B. Peacetime growth** — get growing civs effective during peace time: optimize wide vs tall builds, improve the empire.

**C. Diplomacy** — not worth training until A and B work to a reasonable degree; diplomacy rewards only mean something when war (A) and growth (B) are effective.

**All work is tracked as GitHub issues** under milestones A/B/C, plus unmilestoned bugs/tooling/ideas.

---

## Locked Decisions

### Coordinate System: Axial (q, r) — DECIDED 2026-03-20

We use **axial hex coordinates** as the canonical representation everywhere (Python + C++). This replaced the offset (even/odd row) system.

**Why axial wins:**
- Distance = `max(|dq|, |dr|, |dq + dr|)` — one subtraction, no branching
- Adjacency = same 6 direction vectors for ALL tiles, no even/odd logic
- Fully numpy-vectorizable: all neighbors of N hexes in one broadcast
- Cleaner C++ implementation

**Tradeoff accepted:** The 2D array is "skewed" — convolution filters see a parallelogram, not a hexagon. We accept this for now (corner weights are low-importance anyway). Hex-native convolutions are a separate future investigation.

**Cylindrical wrapping:** Only horizontal (q-axis). For A*, compare direct distance vs. wrapped distance and use the shorter one. A* sees the wrapped neighbor as just another edge.

### C++ acceleration pattern — DECIDED 2026-03-20

Mirror Breach's architecture: pybind11 + CMake, zero-copy numpy arrays, graceful `try: import civulator_core` fallback to pure Python. Profile before porting anything — state encoding, not pathfinding, was the first real bottleneck (11x speedup in numpy alone).

---

## Breach ↔ Civulator Synergy

| Civulator teaches Breach | Breach teaches Civulator |
|---|---|
| RL training pipelines | C++ game engine patterns |
| State encoding for neural nets | raylib rendering |
| Reward shaping | Physics/simulation architecture |
| Self-play methodology | Performance optimization |

---

## Egregore Integration — Concept Nodes for Cross-Project Transfer

_Added: 2026-03-20_

As we implement ML/RL techniques in Civulator, we capture each solved problem as an **egregore concept node** — not a project-level link, but a *technique-level* knowledge unit that lives between projects and is reusable in new contexts.

**Why:** Civulator and Breach share fundamental challenges (hex/grid state encoding, action spaces, reward shaping, neural network AI) in different domains. Lessons transfer only if we capture the *principle*, not just the code. This is the core use case egregore was built for.

**Workflow:** implement in Civulator → validate with training curves → create a concept node (domain-agnostic problem, approach and why it works, code reference, adaptation notes) → egregore surfaces it when returning to Breach.

**Planned concept nodes** (created as each technique is validated):

| Concept | Created after | Transferable to |
|---------|--------------|-----------------|
| `hex_grid_state_encoding` | State encoder refactor | Breach grid AI |
| `action_masking_variable_spaces` | Select-and-move fix | Breach unit actions |
| `reward_shaping_sparse_games` | Reward experiments | Breach mission AI |
| `target_network_stabilization` | Target network impl | Any RL project |
| `self_play_opponent_pool` | Self-play impl | Breach adversarial AI |
| `cpp_pybind11_game_acceleration` | C++ module | Breach (already C++) |

This is the first real test of egregore's value: can concept nodes surface the right knowledge at the right time when switching projects? Usage will be logged and reviewed to guide egregore's own development.
