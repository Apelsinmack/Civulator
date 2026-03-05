# Civulator — Implementation Plan

> **Created**: 2026-03-04
> **Last updated**: 2026-03-05
> **Status**: Active

---

## Current State (v0.3.1)

- DQN with Select-and-Move working
- Warriors only, cities auto-produce warriors
- Healing/fortification fixed (per-turn, requires inaction via `has_acted` flag)
- Attack always consumes all movement points
- EnhancedStateEncoder (25 channels) implemented and wired up
- Configurable network sizes, shared backbone option
- Tournament complete: model size doesn't matter much yet (game too simple)

---

## Design Philosophy (2026-03-05)

**Game complexity before model refinement.** The interesting strategic question is not
"which neural network architecture is best?" but "can the agent learn to make meaningful
economic and diplomatic decisions?" The game needs to present real trade-offs before
optimizing the model is worthwhile:

- **Units vs settlers vs buildings** — the classic Civ dilemma
- **War vs peace** — when to fight, when to build
- **Short-term vs long-term** — rush an enemy now or invest in economy?

These choices are what make the game interesting for both humans and AI. Get the game
there first, then refine the models.

**Why not refine the NN first?** The tournament (4 model sizes, 500 episodes each)
already showed that model size and architecture don't matter when the game is warriors-only.
More architecture tweaks on a simple game would just confirm the same thing. The model
becomes the bottleneck only when the game presents decisions complex enough to require
a better model.

---

## Priority A: Game Complexity (next)

### A1: Build Queue — Agent Chooses What to Produce

**Goal**: Let the agent decide what each city builds, instead of auto-producing warriors.

**The problem**: The current Select-and-Move network selects tiles on the map. It can't
distinguish "I'm selecting a unit to move" from "I'm selecting a city to give orders."
Even if we overloaded the select action, there's no natural way to express "build a
Spearman in this city" through the move head.

**Proposed solution: Separate Build Network**

A dedicated network that runs once per city per turn, choosing what to produce.

```
Build state → [Conv/FC] → Q-values over build options
```

**Chosen design: Build info embedded in the map tensor**

The "table" of build options lives *inside* the spatial state tensor as extra channels,
non-zero only at city tiles. This is elegant because:
- The CNN sees both "what can I build?" and "are enemies nearby?" in one pass
- City position is implicit (spatial embedding — no explicit coordinates needed)
- Variable city count handled naturally (more cities = more non-zero tiles)
- Shares the same spatial representation as the combat network

**Extra channels at city tiles** (added to state tensor):

| Channel | Value | Purpose |
|---------|-------|---------|
| turns_to_warrior | warrior_cost / city_production | Build speed per option |
| turns_to_spearman | spearman_cost / city_production | |
| turns_to_archer | archer_cost / city_production | |
| turns_to_horseman | horseman_cost / city_production | |
| turns_to_settler | settler_cost / city_production | |
| turns_to_granary | granary_cost / city_production | |
| current_production | one-hot or index | What's being built now |
| production_progress | progress / total_cost (0→1) | How close to finishing |

Non-city tiles are 0 in these channels. Normalized so the network sees
"5 turns" as 5/max rather than raw cost.

**Build head**: Separate FC layers that read conv features and output Q-values
per build option at each tile. At turn start, for each own city, take argmax
at that city's (row, col) in the output.

**Build actions** (per city):
- Warrior, Spearman, Archer, Horseman, Catapult
- Settler (if pop >= 3?)
- Granary (first building — see A3)
- "Continue current" / do nothing

**When it runs**: At the start of each turn, for each city that has no active
production. Or: every turn, allowing the agent to change mid-build (like in Civ).

**Architecture notes for future**:
- Shared backbone option: the combat CNN already extracts spatial features.
  The build head could branch from the same conv features (different FC head).
  Start separate, test shared later — coupling could cause training interference.
- Receptive field: on a 4×8 map, two conv3 layers give a 5×5 receptive field,
  covering most of the board. This is sufficient for now.
- On larger maps (16×32+), build decisions need broader spatial awareness.
  Options: larger kernel sizes, stride > 1 (e.g. stride 3 to cover 3x the area
  per layer), or pooling layers. Stride reduces spatial resolution but build
  decisions only need Q-values at city locations, not every tile — so the
  resolution loss is acceptable.
- Cylindrical wrapping: `horizontal_wrap_padding` already handles this
  (wraps left/right, zero-pads top/bottom). A city at column 0 correctly
  "sees" tiles at column m-1. Build network reuses the same padding.

**Implementation plan**:
1. Add build-info channels to `EnhancedStateEncoder` (or new `BuildStateEncoder`)
2. Design `BuildHead` — FC layers outputting [n*m × num_build_options]
3. Add build Q-learning: separate replay memory, separate loss, separate optimizer
4. Integrate into training loop: build decisions at turn start, combat during turn
5. Reward signal for build decisions: delayed — city production payoff comes
   turns later. May need longer gamma or shaped rewards.

---

### A2: Unit Types

**Goal**: Activate Spearman, Archer, and Horseman alongside Warriors.

**Implementation steps**:
1. City produces units based on build queue (A1) — no more auto-warrior
2. Activate ranged combat: Archers attack at range 2 with ranged strength (no counter-damage)
   - Verify `ArcherUnit.attack()` override works correctly
3. Activate class advantages: Spearman +10 vs Horseman, etc.
4. EnhancedStateEncoder already supports all unit types (one-hot class encoding)

**Dependencies**: A1 (build queue) — agents need to choose what to build.
Without A1, fall back to rule-based ratios (2 Warriors : 1 Archer : 1 Spearman).

---

### A3: Buildings — Granary (First Building)

**Goal**: Introduce buildings as an alternative to unit production. First building:
Granary (increases food → population → production).

**Why granary first**: It creates the core economic trade-off: spend production now
on a building that pays off later (more pop → more production), or spend it on a
unit for immediate military power. This is the essence of Civ's "guns vs butter" dilemma.

**Economy model (first version — keep it simple)**:
- Each city has population (starts at 1)
- Production per turn = base + population bonus (scale tile yields by pop)
- Granary: +2 food per turn → faster population growth
- Don't implement tile-working or citizen assignment yet — not interesting for NN

**Later buildings** (future, not now):
- Walls: +3 city defense, affects combat
- Barracks: units start with +15 XP (could be a stat bonus)
- Library: +science (when we add tech tree)

**Implementation steps**:
1. Add population and food tracking to `City`
2. Add Granary as a buildable option (production cost ~60)
3. Population growth: food accumulates, pop increases at threshold
4. Production scales with population
5. Add building info to state encoder (new channel or extend city channels)

---

### A4: Settlers and City Founding

**Goal**: Agents can expand by building settlers and founding new cities.

**Implementation steps**:
1. Settler available in build queue (A1) — costs 120 production, requires pop >= 3?
2. Founding: settler on valid tile + "fortify" action (move to same tile) = found city
   - Or: special action when settler is selected
3. Settler consumed on city founding
4. New city starts with pop 1, no buildings

**Why this matters**: Expansion is the third strategic lane alongside military and
economy. "Should I build a settler or an army?" is one of the deepest decisions in Civ.

---

### A5: Alliances and Diplomacy

**Goal**: N-player games with war/peace mechanics. Relationship-based state encoding.

**Core mechanics**:
- N*(N-1)/2 pairwise relationships, default state = peace
- **Declare war**: Unilateral. Immediate effect. Enables combat between the two players.
- **Propose peace**: Requires mutual agreement (both players must select it).
  10-turn minimum war duration before peace is possible.
- War = can attack each other's units and capture cities
- Peace = units pass through each other, no combat

**State encoding** (relationship-based, scales to N players):
- Instead of "own" and "enemy" channels, use: own / ally / neutral / enemy
- Diplomacy status encoded as a small vector per player pair
- The agent sees *relationships*, not player IDs — Team 1 vs Team 2 is meaningless,
  but "at war with" vs "at peace with" is meaningful

**Action space for diplomacy**:
- Extend select head: beyond `n*m + 1` (end turn), add 2*(N-1) diplomacy slots
  - For each other player: "declare war" and "propose peace"
  - These are select-only actions (no move phase needed)
- Or: dedicated diplomacy phase at turn start (like build phase)

**Inspiration**: Meta's CICERO (Diplomacy AI) — relationship-based encoding,
learned when to cooperate and when to betray. Our version is simpler (binary
war/peace, no negotiation text) but the core idea is the same.

**Threat / aggression scoring**:
- Track attacks per player pair: how many times player A attacked player B
- Aggression score = recent attacks (windowed, e.g. last 20 turns)
- Feed this into the state encoder — the agent can learn "this player is aggressive,
  they're a threat" vs "this player is peaceful, safe to ignore"
- Could also factor in: army size near my borders, cities captured, units killed
- This creates emergent diplomacy: if player A attacks player B a lot, player C
  might learn to ally with B against the common threat — or exploit B's weakness

**Implementation steps**:
1. Add `DiplomacyState` tracking war/peace between all player pairs
2. Add aggression tracking: attacks per pair, windowed history
3. Add diplomacy actions to the select head (or separate diplomacy network)
4. Update state encoder with relationship channels + threat scores
5. Reward signals: captured city of ally = penalty? Breaking peace = cost?
6. Start with 3-player games (N=3) — the minimum for interesting diplomacy

---

## Priority B: Model Refinement (after game complexity)

These are worth doing eventually, but the game needs more strategic depth first.
Results from Priority A will inform which of these matter.

### B1: Shared Backbone
**Status**: Implemented, testing in progress (2026-03-05).
Single CNN shared between select and move heads. 15% fewer params.
Result will inform whether to keep it as default.

### B2: Hierarchical Q-Learning on Select/Move
Make the select head aware of move quality. Currently the select head picks units
independently of what moves are available. Proposed: train select targets using
`max_{a_move} Q(s, a_select, a_move)`.

### B3: Temporal State Stacking
Stack last K state tensors as extra channels (like Atari DQN's 4 frames).
Cheap, gives agents memory of recent history. Helps with flanking, retreat, pursuit.

### B4: Training Improvements
Standard DQN enhancements: target network, epsilon decay, prioritized replay,
Double DQN, reward normalization. Implement one at a time, measure each.

---

## Priority C: Future Features

### C1: Reward Function Profiles (Agent Personality)

Extract reward calculations into a `RewardFunction` class. Different profiles produce
different playstyles:
- **Aggressive**: High attack rewards, low death penalty
- **Defensive**: Rewards fortification, penalizes leaving territory
- **Barbarian**: Always attack, trained in rigged games where they're stronger
- **Balanced**: Current default

Use cases: barbarian AI, city-state AI, difficulty levels, curriculum learning.

**When**: After A1-A4, when there are meaningful tactical choices to differentiate.

### C2: Larger Maps and Scaling

Current: 4×8. Future: 8×16, 16×32. Requires testing whether CNN architecture
scales or needs adaptation (deeper networks, pooling layers, attention).

### C3: Tech Tree

Research unlocks new units and buildings. Adds another strategic dimension:
invest in science → better units later vs build army now.

---

## Parked: Multi-Step Lookahead / Planning (Model-Based RL)

**Status**: Parked for future exploration. Worth studying, not worth implementing yet.

**The idea**: Instead of just evaluating the current state (model-free), simulate future
game states and pick the action sequence with the best expected outcome. This is what
AlphaGo/AlphaZero does with Monte Carlo Tree Search (MCTS) — play out many hypothetical
futures and choose the move that leads to the best ones.

**Model-free vs model-based RL — key distinction**:
- **Model-free** (what we do now): The agent learns Q(s, a) directly from experience.
  It doesn't know *how* the game works — it just learns "in this situation, this action
  tends to give good rewards." DQN, policy gradient, A2C/A3C are all model-free.
- **Model-based**: The agent has (or learns) a *model of the environment* — given state s
  and action a, it can predict the next state s'. This lets it *plan ahead* by simulating
  future trajectories without actually playing them. MCTS, Dyna-Q, MuZero, and World Models
  are model-based approaches.

**Why it's interesting for Civulator**:
- Strategy games are inherently about planning multiple turns ahead
- We *have* a perfect environment model (the game code itself) — no need to learn one
- Could use the game simulator as a forward model for MCTS-style search
- Even shallow lookahead (2-3 turns) could dramatically improve tactical play

**Why we're parking it**:
- Expensive: each lookahead step runs the full game simulation for each candidate action
- With branching factor ~33 (n*m+1 selections × n*m moves), even 2-step lookahead is
  33^2 ≈ 1000 simulations per decision. At 4 decisions per turn, that's 4000 simulations.
- Multi-agent complication: opponent's moves are unknown, need to model or assume them
- Our model-free DQN hasn't been fully optimized yet — get more from simpler improvements first
- The architecture would fundamentally change (hybrid model-free + model-based, or pure MCTS)

**When to revisit**:
- After we've exhausted model-free improvements and hit a performance ceiling
- If we want the agent to exhibit genuine strategic planning (sacrificing a unit now for
  positional advantage 5 turns later)
- If we implement AlphaZero-style self-play (MCTS + neural network policy/value)

**Further reading topics**:
- Monte Carlo Tree Search (MCTS) — the planning algorithm
- AlphaGo / AlphaZero — MCTS + deep learning for perfect-information games
- MuZero — learned environment model (doesn't need game rules, learns to predict)
- Dyna-Q — hybrid: model-free Q-learning + model-based simulated experience
- World Models (Ha & Schmidhuber) — learn a compressed environment model in latent space

---

## Completed

### Tournament (v0.3.0)
- 4 model sizes × 500 episodes, round-robin
- Result: Large (958k) 31% > XL 29% > Small 28% > Medium 22%
- Conclusion: model size doesn't matter much yet — game too simple
- Recommendation: use Small for rapid iteration

### State Space Redesign (v0.3.1)
- EnhancedStateEncoder: 25 channels with unit class one-hot, stats, terrain, cities
- Relationship-based team encoding (own/enemy, extensible to own/ally/neutral/enemy)
- Auto-detection in mask functions (d==25 → enhanced, else basic)
- `--encoder enhanced` flag in train.py

### Bug Fixes (v0.3.1)
- Attack consumes all movement points (was only on kill)
- Fortification/healing per-turn via `has_acted` flag (was per-step)
- Removed double `end_turn()` in `_check_game_end()`
- Unit spawning: try center → adjacent → defer (was stacking on city tile)

---

## Testing Methodology

For every change:
1. Train 500 episodes with the change
2. Compare win rate curve against previous best
3. Run head-to-head tournament (changed vs unchanged)
4. Document results in CHANGELOG.md
5. Keep the change only if it improves performance (or is neutral but simplifies)
