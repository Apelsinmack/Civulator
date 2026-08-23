# Trained Weights Manifest

## Naming Convention

`{size}_{channels}_{episodes}ep.pth`

- size: small / medium / large
- channels: conv layer sizes (e.g. 16x32)
- episodes: number of training episodes

## Weights

### medium_16x32_1000ep.pth

- **Architecture**: FullyConvNetwork, conv_channels=(16, 32)
- **Training**: 1000 episodes, shared weights (8 players self-play)
- **Map**: 24x48, 8 players FFA
- **Encoder**: EnhancedStateEncoder (25 channels)
- **Learning rate**: 0.001
- **Epsilon**: 1.0 → 0.05 over 8000 episodes (Patient schedule)
- **Batch size**: 32
- **Replay buffer**: 10000 (shared)
- **Max turns**: 200
- **Starting weights**: agent_5 from 35-episode tournament (Medium-Patient, 8 wins)
- **Date**: 2026-03-23 overnight
- **Final win distribution**: P1=94, P2=90, P3=99, P4=96, P5=90, P6=107, P7=95, P8=106 (roughly even — expected with shared weights)
- **Build order**: Warriors 19%, Catapults 17%, Archers 17%, Horsemen 16%, Spearmen 16%, Granary 10%, Settler 6%

### large_32x64_1000ep.pth

- **Architecture**: FullyConvNetwork, conv_channels=(32, 64)
- **Training**: 1000 episodes, shared weights (8 players self-play)
- **Map**: 24x48, 8 players FFA
- **Encoder**: EnhancedStateEncoder (25 channels)
- **Learning rate**: 0.001
- **Epsilon**: 1.0 → 0.05 over 8000 episodes (Patient schedule)
- **Batch size**: 32
- **Replay buffer**: 10000 (shared)
- **Max turns**: 200
- **Starting weights**: random (no pretrained checkpoint)
- **Date**: 2026-03-24 overnight
- **Final win distribution**: P1=93, P2=106, P3=77, P4=97, P5=98, P6=110, P7=102, P8=100
- **Build order**: Spearmen 19%, Warriors 18%, Archers 17%, Horsemen 16%, Catapults 15%, Granary 10%, Settler 5%

---

## Epoch marker — 2026-08-23: v0.6.0 terrain remodel (design doc §11 P7)

Everything **above** this line was trained on a **v0.5 world**: the pre-remodel
flat `terrain_type` tile model, the old (non-isotropic) world generator, and the
pre-correction encoder value-semantics (`docs/terrain_model_design.md` §0/§7,
D16). The 0.6.0 terrain redesign changed maps, passability, and several encoder
channel semantics enough that **no result below this line is comparable to
anything above it** — different worlds, different action spaces, different
learned priors. Both entries stay recorded in place rather than deleted, per
the project's scientific-record rule (CLAUDE.md: "Never delete previous
results") — they are prior-epoch results, not superseded ones.

`scripts/watch.py` prints each loaded weight file's manifest `game_version` (or
`"pre-manifest/0.5 epoch"` for a bare state_dict with no manifest at all) so
this boundary is visible at load time, not just here.
