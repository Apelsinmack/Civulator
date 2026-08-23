# Trained Weights Manifest

## Naming Convention

`{size}_{channels}_{episodes}ep.pth`

- size: small / medium / large
- channels: conv layer sizes (e.g. 16x32)
- episodes: number of training episodes
- 0.6+ entries may instead use a map-size preset for `size` (duel/…) and
  encoder depth for `channels` (e.g. 25ch); each entry states its own meaning

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

## Weights — v0.6.0 epoch

### duel_25ch_1000ep.pth  ⭐ THE #39 BASELINE — the reference opponent

- **Naming here**: size = Duel preset (12×24), 25ch = encoder depth (not conv width)
- **Payload**: both players' combat + build agents (`{"agents": [...], "build_agents": [...]}`), saved via `meta.save_weights`, manifest embedded (v0.6.0, run commit 96b3578)
- **Architecture**: FullyConvNetwork, conv_channels=(16, 32), symmetric identical hyperparameters for both players (a reference opponent must not be two differently-tuned agents)
- **Training**: 1000 episodes self-play, Duel 12×24, 2 players, earthlike worlds
- **Seed schedule**: `seed_base=390000`, running-cursor skip (design D26) — 3 seeds skipped (390850, 390909, 390945: unplaceable worlds, deterministically logged); every follower experiment replays this exact world sequence
- **Encoder**: EnhancedStateEncoder (25 channels — resource/river-blind by design; #40 is the seeing counterpart experiment)
- **Hyperparameters**: lr 0.001, gamma 0.9, batch 32, max_turns 250, epsilon 1.0→0.05 (config schedule)
- **Date**: 2026-08-23 (launched 16:12, finished 23:23 — 7h10m26s, 25.83 s/episode)
- **Final win distribution**: P0=500, P1=486, draws=14 — statistically even, as a symmetric reference should be
- **Build popularity**: agent A — Catapult 16.3%, Archer 15.4%, Settler 14.7%, Horseman 14.6%, Warrior 14.5%, Granary 12.7%, Spearman 11.9%; agent B — Settler 17.3%, Horseman 15.8%, Catapult 15.6%, Warrior 15.2%, Archer 14.8%, Spearman 12.6%, Granary 8.9%
- **Role**: frozen reference opponent (#6 pool member #1); win-rate-vs-this is the standard evaluation metric; all followers train the same M=1000 with episodes-to-50%-vs-baseline as the secondary metric
- **Stats**: `stats/baseline_baseline_1000ep_1787520197.json` + `win_history`/`win_rate_plot`/`build_orders_1787520197.*`
