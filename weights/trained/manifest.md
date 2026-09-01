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

### duel_52ch_1000ep.pth — the #40 terrain-aware follower

- **Naming**: Duel preset (12×24), 52ch = TerrainAwareStateEncoder depth
- **Payload**: both players' combat + build agents, `meta.save_weights`, manifest embedded (v0.6.0, run commit db1d12e)
- **Architecture**: FullyConvNetwork, conv_channels=(16, 32), symmetric — identical to the baseline except the encoder
- **Encoder**: TerrainAwareStateEncoder (52ch: Enhanced 25ch prefix bit-identical + 27ch terrain block — spec `docs/terrain_encoder_design.md`); the single changed variable vs the baseline
- **Training**: 1000 episodes self-play, Duel 12×24, 2 players, earthlike worlds; lr 0.001, gamma 0.9, batch 32, max_turns 250, epsilon 1.0→0.05 — all as the baseline
- **Seed schedule**: `seed_base=390000` — **but see #44**: on ERIK_LENOVO (Intel) 19 seeds are unplaceable where Home Desktop (AMD) skipped only 3 (its 3 ⊂ these 19), so the world sequence diverges from the baseline's from episode 16 (cursor shift). Distributional comparability intact; exact episode-pairing lost. Cross-machine mapgen float divergence, filed as #44 — not caused by this run's code (verified at b75dee2, both numpy 2.0.1/2.4.6, C++ and pure-Python A*).
- **Date**: 2026-08-26 overnight on ERIK_LENOVO (RTX 1000 Ada) — 5h11m54s, 18.71 s/episode (mask vectorization #42 active)
- **Final win distribution**: P0=482, P1=500, draws=18 — statistically even, as symmetric self-play should be
- **Evaluation**: head-to-head vs duel_25ch_1000ep via `scripts/evaluate.py` (protocol v1) — results on #40
- **Stats**: `stats/baseline_baseline_1000ep_1787713987.json` + `win_history`/`win_rate_plot`/`build_orders_1787713987.*`

### duel_25ch_rw2_1000ep.pth — the #46 reward-table-v2 follower

- **Naming**: Duel preset (12×24), 25ch = EnhancedStateEncoder (the baseline's), `rw2` = reward table v2 (the single changed variable)
- **Payload**: both players' combat + build agents, `meta.save_weights`, manifest embedded (v0.6.0, run commit e882c23 — the manifest's embedded config pins the exact reward table)
- **Architecture**: FullyConvNetwork, conv_channels=(16, 32), symmetric — identical to the #39 baseline except `[training.rewards]`
- **Rewards (issue #46)**: potential-based proximity shaping (w=0.5, R=cols//2+1, military-only, nearest enemy city), terminal win/loss/draw +100/−100/0 (with the trainer's lazy-pending fix so losers actually receive a done=True transition), unit_lost −5, found_city 40, capture_city 80; all else as baseline
- **Training**: 1000 episodes self-play, Duel 12×24, 2 players, earthlike; lr 0.001, gamma 0.9, batch 32, max_turns 250, epsilon config schedule — all as the baseline
- **Seed schedule**: `seed_base=390000` on Home Desktop (AMD) — the **same machine as the #39 baseline**, so unlike #40 (see #44) the exact world sequence matches the baseline's
- **Mid-training checkpoints**: every 100 episodes under `weights/checkpoints/` (gitignored, local to Home Desktop) — first run with episodes-to-50% computable
- **Date**: 2026-09-01 on Home Desktop (RTX 3070) — 6h35m08s, 23.71 s/episode
- **Final win distribution**: P0=464, P1=522, draws=14
- **Evaluation** (protocol v1, 200 games vs duel_25ch_1000ep): rw2 **85** / baseline **80** / **35 draws** — null on win rate; **all 200 games again hit the 250-turn cap, zero eliminations** (score tiebreak decided everything). Full analysis on #46
- **Stats**: `stats/baseline_baseline_rw2_1000ep_1788264048.json` + `win_history`/`win_rate_plot`/`build_orders_1788264048.*` + `stats/eval_duel_25ch_rw2_1000ep_vs_duel_25ch_1000ep_1788276202.json`

### duel_25ch_rw2eps800_1000ep.pth — the #46 epsilon-matched follower

- **Naming**: as rw2, plus `eps800` = epsilon_decay_episodes 800 (the single changed variable vs rw2: schedule reaches 0.05 by episode 800 instead of stalling at ~0.81 — commit 0dcb113)
- **Everything else**: identical to duel_25ch_rw2_1000ep (table v2, Enhanced 25ch, seed_base 390000 on Home Desktop — exact baseline world sequence)
- **Date**: 2026-09-01/02 overnight on Home Desktop — 3h27m50s, **12.47 s/episode** (vs 23.7 at high epsilon: greedy games run far fewer random no-ops)
- **Final win distribution**: P0=436, P1=496, draws=68 — draws climb as epsilon falls (3/2/11/16/36 per 200-episode block), self-play turtling visible at low epsilon
- **Evaluation** (protocol v1, 200 games vs duel_25ch_1000ep): eps800 **84** / baseline **79** / **37 draws** — null; **all 200 games at the 250-turn cap, zero eliminations**. Epsilon schedule alone does not break turtling — consistent with the #48 receptive-field hypothesis (the network cannot see distant cities regardless of how much greedy experience it gets)
- **Stats**: `stats/baseline_baseline_rw2eps800_1000ep_1788291341.json` + `win_history`/`win_rate_plot`/`build_orders_1788291341.*` + `stats/eval_duel_25ch_rw2eps800_1000ep_vs_duel_25ch_1000ep_1788291563.json`

### duel_26ch_1000ep.pth — the #48 city-distance-encoder follower

- **Naming**: Duel preset, 26ch = CityDistanceStateEncoder (Enhanced 25ch prefix + nearest-enemy-city proximity field — the single changed variable vs duel_25ch_rw2eps800)
- **Config**: reward table v2 + epsilon decay 800 (as rw2eps800), conv (16,32), seed_base 390000 on Home Desktop (exact baseline world sequence)
- **Date**: 2026-09-02 night on Home Desktop — 3h31m05s, 12.67 s/episode
- **Final win distribution**: P0=443, P1=484, draws=73 (late-training draws 31/200 — same turtling shape as rw2eps800)
- **Evaluation** (protocol v1, 200 games vs duel_25ch_1000ep): **84 / 83 / 33** — null; **all 200 games at the 250-turn cap, zero eliminations**. The proximity channel changed *production behavior* (flat military mix, Settler 200 vs the baseline's 482, first eval with build_distribution recorded) but not game outcomes — global direction input alone does not produce marching either
- **Stats**: `stats/baseline_baseline_1000ep_1788304274.json` + `win_history`/`win_rate_plot`/`build_orders_1788304274.*` + `stats/eval_duel_26ch_1000ep_vs_duel_25ch_1000ep_1788304495.json`
