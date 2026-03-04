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

**Why test separately**: Halves the conv parameters. Could help (shared representation) or hurt (heads interfere). Need data.

---

## Step 3: Add Unit Types

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

## Step 4: State Space Redesign

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

## Step 5: Settlers and City Founding

**Goal**: Agents can expand by building settlers and founding new cities.

**Implementation steps**:
1. Add settler to city production options (rule-based: build settler when pop >= 3?)
2. Add "found city" as an agent action (settler on valid tile → found)
3. Could be a special action type or an extension of the move head
4. Balance: settler costs 120 production, city founding removes the settler

---

## Step 6: Training Improvements

**Goal**: Standard DQN enhancements for stability and sample efficiency.

**Candidates** (implement one at a time, measure each):
1. **Target network**: Separate network for computing Bellman targets, updated periodically
2. **Epsilon decay**: Start high (0.5), decay to low (0.05) over training
3. **Prioritized experience replay**: Sample important transitions more often
4. **Double DQN**: Use online network to select actions, target network to evaluate
5. **Reward normalization**: Clip or normalize rewards for stable learning

---

## Testing Methodology

For every change:
1. Train 500 episodes with the change
2. Compare win rate curve against previous best
3. Run head-to-head tournament (changed vs unchanged)
4. Document results in CHANGELOG.md
5. Keep the change only if it improves performance (or is neutral but simplifies)
