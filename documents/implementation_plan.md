Comment added by erik: I wonder if builders and settlers can share tile with military units, they are supposed to, perhaps we need to increase complexity of the state space or the way we give orders to solve this, and perhaps there is a way to circumvent it, we'll see. 

# Civulator — Implementation Plan

> **Created**: 2026-03-04
> **Last updated**: 2026-03-07
> **Status**: Active

---

## Current State (v0.4.0)

- FullyConvNetwork: shared CNN backbone, map-size independent, ~15k params
- All unit types active via build agent (Warrior, Spearman, Archer, Horseman, Catapult, Settler)
- City economy: food, production, population growth, tile working
- Granary building available
- Settlers can found cities (select settler → order to same tile)
- Training: 500 episodes in ~1 hour on RTX 3070 GPU
- Results: zero draws, P2 learns to overtake P1 (59%→61% in later episodes)

---

## Design Philosophy (2026-03-05)

**Game complexity before model refinement.** The interesting strategic question is not
"which neural network architecture is best?" but "can the agent learn to make meaningful
economic and diplomatic decisions?" The game needs to present real trade-offs before
optimizing the model is worthwhile:

- **Units vs settlers vs buildings** — the classic Civ dilemma
- **War vs peace** — when to fight, when to build
- **Short-term vs long-term** — rush an enemy now or invest in economy?

---

## Priority A: Game Complexity

### A1: Build Queue — DONE (v0.4.0)

Separate BuildAgent (DQN) decides city production. 7 build options: 5 unit types +
Settler + Granary. Runs at turn boundaries in trainer.py.

### A2: Unit Types — DONE (v0.4.0)

All combat units active: Warrior, Spearman, Archer, Horseman, Catapult.
Ranged combat works (Archer, Catapult). Class advantages active.

### A3: Buildings / Granary — DONE (v0.4.0)

City economy: food/production from worked tiles, population growth, starvation.
Granary available as build option. Full Civ-like economic loop.

### A4: Settlers and City Founding — IMPLEMENTED, NEEDS VERIFICATION

**Code is wired up**: Settler in BUILD_OPTIONS (index 5, requires pop >= 3).
Selecting a settler and ordering to same tile triggers `found_city()` (+15 reward).
Minimum 3 tiles from other cities.

**Unknown**: Whether agents actually learn to build and use settlers.
Need build order tracking (see TODO) to verify.

### A5: Alliances and Diplomacy — NEXT MAJOR FEATURE

**Goal**: N-player games with war/peace mechanics.

**Game mechanics** (designed, not implemented):
- N*(N-1)/2 pairwise relationships, default state = peace
- **Declare war**: Unilateral. Immediate. Enables combat between the two players.
- **Propose peace**: Requires mutual agreement. 10-turn minimum war.
- War = can attack. Peace = units pass through, no combat.

**State encoding** (designed):
- Relationship-based: own / ally / neutral / enemy (instead of own/enemy)
- Aggression tracking: windowed attack history per pair
- Threat scoring: army size near borders, attacks, captures

**Action space** (designed):
- Extend select head: beyond n*m + 1 (end turn), add 2*(N-1) diplomacy slots
  - For each other player: "declare war" and "propose peace"
  - These are select-only actions (no move phase needed)
- Alternative: dedicated diplomacy phase at turn start (like build phase)

**Open question**: Which network approach for diplomacy decisions?
- Option 1: Extra slots in select head (simple, but mixes tactical and strategic decisions)
- Option 2: Dedicated diplomacy network at turn start (clean separation, like build agent)
- Option 3: Diplomacy as part of build phase (build agent already runs at turn start)

**Implementation steps**:
1. Add `DiplomacyState` tracking war/peace between all player pairs
2. Guard combat with war check (can only attack enemies at war)
3. Add diplomacy actions (declare war / propose peace)
4. Update state encoder with relationship channels + threat scores
5. Start with 3-player games (N=3) — minimum for interesting diplomacy

---

## Priority B: Model Refinement

### B1: Shared Backbone — DONE (inherent in FullyConvNetwork)

FullyConvNetwork already uses shared conv layers for select and move heads.
FullyConvSeparateNetwork created for A/B comparison (separate conv per head).
Test in progress (2026-03-07): training separate variant, tournament to follow.

### B2: Hierarchical Q-Learning on Select/Move

Make the select head aware of move quality. Currently select picks units
independently of what moves are available.

**Proposed**: Train select targets using `max_{a_move} Q(s, a_select, a_move)`.

**When**: After A4 verification and A5.

### B3: Temporal State Stacking

Stack last K state tensors as extra channels (like Atari DQN's 4 frames).
Cheap, gives agents memory of recent history. Helps with flanking, retreat, pursuit.

**When**: After A5. Could combine with B2 for a bigger experiment.

### B4: Training Improvements

Standard DQN enhancements. Implement one at a time, measure each:
- Target network (training stability)
- Epsilon decay schedule
- Prioritized replay
- Double DQN
- Reward normalization

### B5: Unified Training CLI

Consolidate all training scripts into a single parameterized `train.py`:
```
python train.py --network fully-conv --backbone shared --encoder enhanced \
    --episodes 500 --resume weights/checkpoint.pth --output weights/experiment_name/
```

All experiment settings as CLI args: network type, backbone mode, encoder, episodes,
resume path, output dir, learning rate, etc. Benefits:
- **Parallel training**: run multiple sessions concurrently (GPU/CPU not saturated by
  one small network). Just open multiple terminals with different args.
- **Reproducibility**: the command line IS the experiment config. Copy-paste to rerun.
- **No more one-off scripts**: `train_separate_backbone.py`, `overnight_backbone_test.py`
  etc. become just different arg combinations to one script.
- **Easy automation**: loop over configs, grid search, overnight batch runs.

---

## Priority C: Future Features

### C1: Reward Function Profiles (Agent Personality)

Different profiles produce different playstyles:
- **Aggressive**: High attack rewards, low death penalty
- **Defensive**: Rewards fortification, penalizes leaving territory
- **Barbarian**: Always attack, rigged games where they're stronger
- **Balanced**: Current default

### C2: Scaling Architecture Ideas (2026-03-07)

Ideas for making the architecture scale to large maps (16x32+):

**Sparse convolutions**: Most state channels are very sparse (units on ~10 of 512 tiles
on a 16x32 map). Libraries like MinkowskiEngine or spconv compute only where there's
data. Could be a huge win for large maps.

**Terrain feature caching**: Terrain is static for the entire game. Conv features
from terrain channels could be computed once at game start and cached. Split state into
static (terrain) and dynamic (units, cities) channels, combine cached terrain features
with per-step dynamic features. Saves ~half the backbone computation.

**Specialist networks as state channels**: Separate lightweight networks that
pre-digest information on different timescales:
- **Settlement value network**: scores tiles for settling quality → extra channel
  for select-and-move. Only recomputed when map changes (city founded).
- **Threat map network**: scores tiles by military danger → channel for combat.
  Updated every step.
- **Economic value network**: evaluates production potential → channel for build.
  Updated per turn.

Each specialist's output becomes an input channel to the main policy.
The main network doesn't need to learn these heuristics from scratch — it
just reads pre-digested assessments. This is essentially learned feature engineering.

**Key insight**: On large maps, the interesting information is sparse and multi-scale.
Specialist networks handle different spatial scales and timescales, keeping the
main policy network focused on decision-making rather than feature extraction.

### C3: Tech Tree

Research unlocks new units and buildings. Another strategic dimension.

---

## Parked: Multi-Step Lookahead / Planning (Model-Based RL)

**Status**: Parked. See previous version of this doc for full analysis.

Key points:
- We have a perfect environment model (the game code itself)
- Even 2-step lookahead is ~1000 simulations per decision (branching factor ~33)
- Revisit after model-free improvements plateau
- Relevant approaches: MCTS, AlphaZero, MuZero, Dyna-Q

---

## Completed

### v0.4.0 (2026-03-05)
- City economy (food, production, population, tile working)
- Build agent (separate DQN for city production decisions)
- FullyConvNetwork (map-size independent, shared backbone)
- All unit types active via build agent
- Ranged combat (Archer, Catapult)
- Settlers and Granary in build options

### v0.3.0-v0.3.1
- Tournament: 4 model sizes, Large won. Model size doesn't matter on simple game.
- EnhancedStateEncoder: 25 channels with unit class one-hot, stats, terrain
- Bug fixes: attack consumes all MP, fortification/healing per-turn, unit spawn stacking

### v0.2.0
- DQN fix (removed softmax, proper Bellman targets)
- Pathfinder fix (adjacent move bypass)
- 72% invalid actions → working agent

### v0.1.0
- Package refactoring from monolithic code
- StateEncoder abstraction
- CUDA support

---

## Testing Methodology

For every change:
1. Train 500 episodes with the change
2. Compare win rate curve against previous best
3. Run head-to-head tournament (changed vs unchanged)
4. Document results in CHANGELOG.md
5. Keep the change only if it improves performance (or is neutral but simplifies)

---

## TODO

Task tracking moved to GitHub issues (`Apelsinmack/Civulator`, milestones A/B/C) on 2026-08-22.
This document remains as design narrative only — do not add task lists here.
