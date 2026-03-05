# Civulator — Implementation Plan

> **Created**: 2026-03-04
> **Status**: Active

---

## Current State (v0.3.0)

- DQN with Select-and-Move working (softmax fix, pathfinder fix, combat fix)
- Warriors only, cities auto-produce warriors, healing active
- 500-episode training: 48%/48% win split, 4% draws (massive improvement from 76% draws)
- Configurable network sizes (Small/Medium/Large/XL)
- Tournament script ready

---

## Step 1: Overnight Tournament (current)

**Goal**: Determine if model size matters at this stage of game complexity.

**What to run**:
```bash
python -u scripts/tournament.py --episodes 500
```

**What it does**:
1. Trains 4 model sizes (Small 36k, Medium 246k, Large 958k, XL 3.8M) × 500 episodes each
2. Saves weights to `weights/tournament/`
3. Round-robin tournament: 100 games per matchup (50 as P1, 50 as P2)
4. Saves results plot to `stats/`

**What to look for**:
- Does larger model = better win rate? Or is game too simple for big models?
- Training time scaling (is XL prohibitively slow?)
- Any model size that clearly dominates

---

## Step 2: Shared Backbone Test

**Goal**: Test whether sharing CNN layers between select and move heads improves learning.

**Current architecture**:
```
State → [Conv1_select → Conv2_select] → FC_select → Select Q-values
State → [Conv1_move  → Conv2_move]  → FC_move   → Move Q-values
```
Both heads have independent conv layers (no weight sharing).

**Proposed architecture**:
```
State → [Conv1_shared → Conv2_shared] → Shared features
                                        ├─ FC_select → Select Q-values
                                        └─ [concat selected_pos] → FC_move → Move Q-values
```

**Implementation steps**:
1. Add `SharedBackboneNetwork` class to `networks.py`
   - Single conv stack (Conv1 → BN → ReLU → Conv2 → BN → ReLU)
   - Two FC heads branching from shared features
   - Same interface as `SelectAndMoveNetwork` (drop-in replacement)
2. Add `--shared-backbone` flag to `scripts/train.py`
3. Train shared backbone with same hyperparameters as best model from Step 1
4. Compare win rate curves: shared vs separate backbone
5. If shared is better, add to tournament script and re-run

**Why test separately**: Halves the conv parameters. Could help (shared representation)
or hurt (heads interfere). Need data.

**Note on ordering**: We considered doing hierarchical Q (Step 3) before this, since the
shared backbone might not help much if the select head is fundamentally blind to move quality.
But shared backbone is simpler to implement (~30 min) and the result is informative either way:
if it helps, great; if it doesn't, that's a signal that the bottleneck is in the Q decomposition,
which motivates Step 3.

---

## Step 3: Hierarchical Q-Learning on Select/Move

**Goal**: Make the select head aware of move quality — pick units that have good moves available.

**The problem**: Currently we use branching DQN: `Q(s, a_select, a_move) = Q_select(s, a_select) + Q_move(s, a_select, a_move)`.
The select head assigns value to each unit *independently of what moves are available*. It might
select a unit that has no good moves, or ignore a unit that has a devastating attack available.

**Proposed change**: Train the select head using the *best achievable Q-value for each selection*:
```
Q_select(s, a_select) should approximate max_{a_move} Q(s, a_select, a_move)
```
This means: for each possible unit selection, ask "what's the best thing I could do with this
unit?" and use that as the target for the select head. The agent learns to pick the unit with
the highest-value best move.

**Implementation steps**:
1. During `compute_loss()`, for each sample in the batch:
   - Run the move head for each possible selection (or at least the top-K)
   - The select target becomes `max(move_qvalues)` for each selection
2. This is more expensive per training step (multiple forward passes through move head)
3. Alternative: use the current summed Q-value but backprop through both heads jointly
   (which we already do — but verify the gradient actually flows correctly)
4. Train and compare

**Open question**: Is the current branching decomposition already sufficient, or does the
select head genuinely suffer from not seeing move quality? Measure first.

---

## Step 4: Temporal State Stacking

**Goal**: Give agents memory of recent history so they can perceive motion, threats, and patterns.

**Current input**: Single snapshot — the agent sees where everything is *right now*, but has
zero information about where things *were*. It can't distinguish "unit moving toward me" from
"unit sitting still." This makes flanking, pursuit, and retreat impossible to learn.

**Proposed change**: Stack the last K state tensors along the channel dimension.
- K=3: state goes from 5 channels to 15 channels (last 3 turns)
- K=5: 25 channels
- Start with K=3 (same as DeepMind's Atari DQN, which used 4 frames)

**Implementation steps**:
1. Add a `FrameStacker` wrapper that maintains a deque of the last K states per agent
2. On each step, push current state, output the stacked tensor
3. At episode start, fill the deque with K copies of the initial state
4. Update `D` parameter: `D = original_D * K`
5. No architecture changes needed — the CNN just sees more input channels
6. Train and compare against non-stacked baseline

**Why this could help**: Flanking requires coordinating two units over multiple turns.
Retreat requires knowing the enemy is advancing. Healing strategy requires knowing how
long you've been fortified. All of these need temporal context.

**Cost**: Cheap. No extra computation at inference — just more input channels. Memory
increases by factor K for the state tensors in replay memory.

**Note on ordering**: This is orthogonal to the architecture changes in Steps 2-3 (shared
backbone and hierarchical Q). It can be tested before or after them without interference.
Placed here so the two architecture experiments run back-to-back first.

---

## Step 5: Add Unit Types
(was Step 3)

**Goal**: Introduce Spearman, Archer, and Horseman alongside Warriors.

**Implementation steps**:
1. **City production rule**: Maintain ratio — e.g., 2 Warriors : 1 Archer : 1 Spearman
   - Simple rule in `city.process_turn()` based on current unit counts
   - No neural network decision for now
2. **Activate ranged combat**: Archers attack at range 2 with ranged strength (no counter-damage)
   - Verify `ArcherUnit.attack()` override works correctly
   - Archers defend with melee (take and deal damage when defending)
3. **Activate class advantages**: Spearman +10 vs Horseman, etc.
4. **Update state encoder**: Current 5-channel tensor can't distinguish unit types
   - Minimum: add unit type layers (see Step 4)

**Dependencies**: Requires state space update (Step 4) to be useful — agents can't learn unit-specific tactics if they can't tell units apart.

---

## Step 6: State Space Redesign
(was Step 4)

**Goal**: Richer state representation that encodes unit identity and terrain.

**Current state tensor**: 5 channels × 4 × 8
- [0] Own cities, [1] Own unit HP, [2] Own movement, [3] Enemy cities, [4] Enemy HP

**Proposed state tensor** (Erik's design):
- **Unit features** (per tile): HP, attack strength, defense strength, movement points, range
- **Unit class one-hot** (per tile): melee, spear, ranged, cavalry, siege
- **Terrain layer**: terrain type encoded as movement cost or one-hot
- **City layers**: own cities (with population?), enemy cities

**Estimated new depth**: ~15-20 channels
- 5 own unit features + 5 own unit class one-hot = 10
- 5 enemy unit features + 5 enemy unit class one-hot = 10 (or negative encoding)
- 1 terrain, 1 own cities, 1 enemy cities = 3
- Total: ~13-23 channels

**Implementation steps**:
1. Design exact channel layout and document it
2. Create new `EnhancedStateEncoder` class (keep `BasicStateEncoder` for comparison)
3. Handle multi-unit tiles (currently only stores one unit per tile — stacking issue)
4. Update `D` parameter in training scripts
5. Retrain and compare

---

## Step 7: Settlers and City Founding
(was Step 5)

**Goal**: Agents can expand by building settlers and founding new cities.

**Implementation steps**:
1. Add settler to city production options (rule-based: build settler when pop >= 3?)
2. Add "found city" as an agent action (settler on valid tile → found)
3. Could be a special action type or an extension of the move head
4. Balance: settler costs 120 production, city founding removes the settler

---

## Step 8: Training Improvements
(was Step 6)

**Goal**: Standard DQN enhancements for stability and sample efficiency.

**Candidates** (implement one at a time, measure each):
1. **Target network**: Separate network for computing Bellman targets, updated periodically
2. **Epsilon decay**: Start high (0.5), decay to low (0.05) over training
3. **Prioritized experience replay**: Sample important transitions more often
4. **Double DQN**: Use online network to select actions, target network to evaluate
5. **Reward normalization**: Clip or normalize rewards for stable learning

---

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

## Testing Methodology

For every change:
1. Train 500 episodes with the change
2. Compare win rate curve against previous best
3. Run head-to-head tournament (changed vs unchanged)
4. Document results in CHANGELOG.md
5. Keep the change only if it improves performance (or is neutral but simplifies)
