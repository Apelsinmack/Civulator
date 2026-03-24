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
- **Build order**: Warriors 18%, Catapults 17%, Archers 16%, Horsemen 16%, Spearmen 14%, Granary 11%, Settler 5%
