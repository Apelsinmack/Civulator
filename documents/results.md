# Civulator — Experiment Results

> **Last updated**: 2026-03-07

Results from training runs and tournaments. Raw data in `stats/`, weights in `weights/`.

---

## v0.4.0 — Fully Convolutional Network Experiments

### Experiment: Shared vs Separate Backbone (2026-03-07)

**Question**: Does sharing conv layers between select and move heads help or hurt?

**Setup**:
- FullyConvNetwork (shared backbone): 18,019 params
- FullyConvSeparateNetwork (separate backbones): 26,371 params (+46%)
- Enhanced encoder (25 channels), 4x8 map, 2 players
- 200 max turns, epsilon=0.3, seed=42, RTX 3070

#### Training Results

| Model | Episodes | P1 Wins | P2 Wins | Draws | Time |
|-------|----------|---------|---------|-------|------|
| Shared backbone (run 1) | 500 | 255 (51%) | 245 (49%) | 0 (0%) | ~60 min |
| Separate backbone | 500 | 309 (62%) | 191 (38%) | 0 (0%) | 43 min |
| Shared backbone (run 2, resumed) | 500 more | 259 (52%) | 212 (42%) | 29 (6%) | 96 min |

**Observations from training**:
- **Shared backbone run 1**: P2 learned to overtake P1 in later episodes (Q3-Q4: 54-61% P2).
  Suggests real adaptation happening.
- **Separate backbone**: Strong P1 bias throughout (62%). P2 never caught up.
  More parameters didn't translate to better P2 learning.
- **Shared backbone 1000 eps**: Some draws appeared (6%). Longer episodes (96 min vs 60 min
  for same episode count) suggest more complex games. P1 still slightly ahead.

#### Tournament Results (100 games per matchup, 50 as each side)

| Matchup | Result | Draws |
|---------|--------|-------|
| Shared-500 vs Shared-1000 | 14-14 (dead even) | 72 |
| Shared-500 vs Separate-500 | 17-35 (Separate wins) | 48 |
| Shared-1000 vs Separate-500 | 17-35 (Separate wins) | 48 |

**Final standings**:

| Model | Wins | Losses | Draws | Win% |
|-------|------|--------|-------|------|
| **Separate-500** | **70** | 34 | 96 | **35%** |
| Shared-500 | 31 | 49 | 120 | 15.5% |
| Shared-1000 | 31 | 49 | 120 | 15.5% |

Plot: `stats/backbone_tournament_1772866361.png`

**Conclusions**:
- Separate backbone clearly outperforms shared backbone (2x wins)
- Extra training (500→1000 eps) adds nothing — agents plateau at 500
- High draw rate (48-72%) suggests optimal play on 4x8 maps tends toward stalemate,
  especially between similar agents. Larger maps may be needed for decisive games.
- Having independent feature extraction per head lets select and move specialize,
  which matters more than parameter efficiency at this scale.

---

## v0.3.0 — Model Size Tournament (2026-03-05)

**Question**: Does a bigger network learn better on this game?

**Setup**: 4 model sizes, SelectAndMoveNetwork (FC-based), basic encoder (5ch), warriors only.

| Model | Params | Conv | FC Hidden |
|-------|--------|------|-----------|
| Small | 36k | (16, 32) | None |
| Medium | 246k | (32, 64) | 128 |
| Large | 958k | (64, 128) | 256 |
| XL | 3.8M | (128, 256) | 512 |

**Tournament results** (100 games per matchup, 50 as each side):

| Model | Win% |
|-------|------|
| Large | 31% |
| XL | 29% |
| Small | 28% |
| Medium | 22% |

**Conclusion**: Model size doesn't matter much when the game is warriors-only.
This motivated the shift to game complexity (v0.4.0) before model refinement.

---

## v0.2.0 — Baseline After Bug Fixes (2026-03-04)

| Metric | v0.1.0 (broken) | v0.2.0 (fixed) | v0.3.0 (combat) |
|--------|-----------------|----------------|-----------------|
| Draws | 76% | ~50% | 4% |
| P1 wins | 15% | ~25% | 48% |
| P2 wins | 9% | ~25% | 48% |
| Episode time | ~6s (wasted on invalid moves) | ~0.3s | ~0.3s |
| Invalid actions | 72% | <5% | <5% |
