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

> **Correction 2026-09-02 (seed-schedule record, #44) — RESOLVED same evening:**
> the schedule from seed_base=390000 skips **19 seeds** (390016, 390053, 390065,
> 390076, 390264, 390277, 390294, 390385, 390408, 390489, 390672, 390683, 390689,
> 390759, 390770, 390785, 390850, 390909, 390945) — on every machine and every
> commit tested. Direct enumeration at the baseline's own commit 96b3578 on the
> baseline's own machine reproduces the identical 19 (golden mapgen SHA tests from
> 2026-08-23 still pass there, and numpy/Python/OS predate the baseline unchanged).
> **The baseline row's "3 seeds skipped" below is an incomplete hand transcription**
> — exactly the last 3 of 19 console warnings surviving in scrollback. Consequences:
> every run in this file (baseline, #40 Lenovo, all 2026-09 rungs) walked the SAME
> 19-skip sequence — "exact world sequence" replication holds run-for-run AND
> cross-machine; #40's episode-pairing caveat and #44's cross-machine-divergence
> premise are both retracted. Hardening: `run_baseline.py` now persists
> `skipped_schedule_seeds` into every run summary (console warnings are not a
> record).

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
- **Stats**: `stats/baseline_baseline_1000ep_1788304274.json` + `win_history`/`win_rate_plot_1788304273.*` + `build_orders_1788304274.*` + `stats/eval_duel_26ch_1000ep_vs_duel_25ch_1000ep_1788304495.json`

### duel_26ch_net32x64x64_1000ep.pth — the #48 capacity follower

- **Naming**: as duel_26ch, plus `net32x64x64` = conv_channels (32,64,64) — 3 backbone layers, ~101k params (5.6× the (16,32) net), receptive radius 4; the single changed variable vs duel_26ch_1000ep
- **Config**: city_distance 26ch, table v2, epsilon decay 800, seed_base 390000 on Home Desktop
- **Date**: 2026-09-02 early morning on Home Desktop — 3h51m06s, 13.87 s/episode
- **Final win distribution**: P0=455, P1=487, draws=58
- **Evaluation** (protocol v1, 200 games vs duel_25ch_1000ep): **86 / 84 / 30** — null; **all 200 games at the 250-turn cap, zero eliminations** — the fourth consecutive null on the turn-cap needle (rewards / epsilon / perception / capacity). Build mix tilts further military: Horseman 225, Catapult 200, Granary 59 (baseline same games: Settler 504)
- **Stats**: `stats/baseline_baseline_net32x64x64_1000ep_1788318444.json` + timestamped `win_history`/`win_rate_plot`/`build_orders` + `stats/eval_duel_26ch_net32x64x64_1000ep_vs_duel_25ch_1000ep_1788318680.json`

### duel_26ch_net64x5_1000ep.pth — the #48 capacity follower, second point

- **Naming**: `net64x5` = conv_channels (64,64,64,64,64) — 5 backbone layers, ~600k params (33× the original net), receptive radius 6; single changed variable vs duel_26ch_net32x64x64
- **Config**: city_distance 26ch, table v2, epsilon decay 800, seed_base 390000 on Home Desktop
- **Date**: 2026-09-02 morning on Home Desktop — 4h39m07s, 16.75 s/episode
- **Final win distribution**: P0=456, P1=467, draws=77
- **Evaluation** (protocol v1, 200 games vs duel_25ch_1000ep): **83 / 84 / 33** — null; **all 200 games at the 250-turn cap, zero eliminations** — fifth consecutive null on the turn-cap needle. Build mix stays broad-military (Horseman 204, Spearman 198, Catapult 195, Granary 76; baseline same games: Settler 507)
- **Stats**: `stats/baseline_baseline_net64x5_1000ep_1788335472.json` + timestamped `win_history`/`win_rate_plot`/`build_orders` + `stats/eval_duel_26ch_net64x5_1000ep_vs_duel_25ch_1000ep_1788335716.json`

### duel_26ch_net128x6_1000ep.pth — the #48 capacity follower, third point ⚡ FIRST NON-NULL

- **Naming**: `net128x6` = conv_channels (128,)×6 — ~950k params (52× the original), receptive radius 7; single changed variable vs duel_26ch_net64x5
- **Config**: city_distance 26ch, table v2, epsilon decay 800, seed_base 390000 on Home Desktop
- **Date**: 2026-09-02 day on Home Desktop — 9h11m15s, 33.08 s/episode
- **Final win distribution**: P0=362, P1=593, draws=45 — **first strongly asymmetric self-play of the epoch (~7σ)**: the seat-1 agent found something its twin didn't
- **Evaluation** (protocol v1, 200 games vs duel_25ch_1000ep): **109 / 70 / 21** (54.5% vs 35.0%; among decisive games 60.9%, p≈0.004) — **the ladder's first significant win**. Driven by the strong seat-1 agent (as A@seat1: 72/22; as A@seat0: 37/48). And the first game of the epoch to end before the cap: game 123 (seed 990062), **mutual annihilation draw at turn 227** — real combat to extinction. 199/200 still at cap; turtling dented, not broken
- **Builds**: A 1521 items (Warrior 287, Settler 254, Horseman 245, Spearman 238, Archer 229, Catapult 189, Granary 79) vs baseline's 1262 (Settler 500) — more total production AND more military
- **Stats**: `stats/baseline_baseline_net128x6_1000ep_1788368822.json` + timestamped `win_history`/`win_rate_plot`/`build_orders` + `stats/eval_duel_26ch_net128x6_1000ep_vs_duel_25ch_1000ep_1788369488.json`

### duel_53ch_net128x6_1000ep.pth — the "kitchen-sink" run ⭐⭐ THE BREAKTHROUGH

- **Naming**: 53ch = `FullStateEncoder` (Enhanced 25 + terrain block 27 + city-proximity 1), conv (128,)×6 (~950k params, radius 7)
- **The stack**: reward table v2 + epsilon-decay 800 + terrain awareness + city-distance + max capacity — every measured or hypothesized ingredient at once (Erik's "what if we run one time with everything" direction, 2026-09-02). Single changed variable vs `duel_26ch_net128x6`: **the 27-channel terrain block**
- **Config**: seed_base 390000 on Home Desktop; **19 skipped schedule seeds recorded machine-readably** (first run with the #44 hardening)
- **Date**: 2026-09-02/03 on Home Desktop — **28h01m02s, 100.86 s/episode** (the 53ch encoder ~tripled the big net's per-episode cost — the argument for dilated convolutions instead of depth)
- **Final win distribution**: P0=490, P1=408, draws=102 — late-training draws climb to 63/200 (mutual annihilation in self-play)
- **Evaluation** (protocol v1, 200 games vs `duel_25ch_1000ep`): **122 / 25 / 53 — 83.0% of decisive games, z ≈ 8.0.** Both seats strong (71/16 and 51/9), unlike net128x6's one-sided asymmetry
  - **56 of 200 games ended before the 250-turn cap** (vs 1 for the entire rest of the epoch), earliest at **turn 73**; mean length 235.1
  - **6 outright eliminations, all won by this model** — the first non-draw eliminations of the v0.6 epoch; the other 50 early endings are mutual annihilations
- **Build shift**: **Spearman 1153 of 2502 items (46%)** vs the baseline's 151 in the same games (baseline: Settler 473). Spearman is the strength-per-production optimum among cheap units (25 str / 50 prod, vs Warrior 20/40) — with terrain defense now visible in the state, the agent found the cheap-strong-defensive unit
- **Stats**: `stats/baseline_baseline_net128x6_1000ep_1788471884.json` + timestamped `win_history`/`win_rate_plot`/`build_orders_1788471884.*` + `stats/eval_duel_53ch_net128x6_1000ep_vs_duel_25ch_1000ep_1788477191.json`

### duel_54ch_settle_1000ep.pth — settle-site channel (#8), and the first run under v0.6.2

- **Naming**: 54ch = `SettleSiteStateEncoder` (the 53ch `full` stack + one channel marking every tile where a city may legally be founded, #8); conv (128,)×6
- **Date**: 2026-09-04 21:39 → 2026-09-05 12:09 on Home Desktop — 14h29m42s, **52.18 s/episode** (against the 53ch run's 100.86 for a model with one *more* channel; the #51 no-op-action fix roughly halved training cost). `truncated_episodes: 0` — the livelock is gone
- **Final win distribution**: P0=302, P1=674, draws=24 — the largest seat asymmetry recorded
- **Evaluation** (protocol v1, 200 games vs `duel_25ch_1000ep`, `stats/eval_duel_54ch_settle_1000ep_vs_duel_25ch_1000ep_1788604215.json`): **120 / 67 / 13 — 0.642 of decisive games (n=187, z ≈ 3.9)**, zero truncations. Seat-split is extreme: as seat 1 it wins 84/14, as seat 0 it *loses* 36/53
- **Behaviour**: 57 cities founded, 5 captured, 11 kills, 15 losses (baseline: 1 city founded, 0 captured)

> **⚠ THREE CONFOUNDS — this run does not measure the settle channel.** Stated
> here rather than left for a reader to reconstruct:
>
> 1. **Two variables changed** against `duel_53ch_net128x6`: the settle channel
>    *and* the v0.6.2 combat rebalance, whose constants were sitting
>    uncommitted in the working tree when the run launched.
> 2. **Rule-familiarity asymmetry** (#78): it trained under v0.6.2 and is
>    evaluated under v0.6.2, while the frozen baseline trained under
>    pre-rebalance rules. Some of the margin is that advantage, not policy.
> 3. **Untrustworthy embedded manifest**: the run predates the #75 fix, so its
>    manifest records a save-time commit and no dirty flag. The true launch
>    state was **HEAD d3b8c33 with a dirty tree** (`civulator/game/unit.py`
>    carrying the v0.6.2 constants, `__init__.py` at 0.6.2).
>
> Against the 53ch model's 0.887 it looks clearly weaker, and below even the
> weakest checkpoint of that run (0.767 at episode 500) — but the checkpoint
> curve showed swings of that size within a single run, so no causal claim
> about the settle channel is available from one point. A clean test needs a
> 53ch control trained under v0.6.2 (~13h at the new speed).

- **What it does answer**: v0.6.2's CHANGELOG said "Measured effect: pending… whether the rebalance moves that mix is the open question." It moves it decisively. **Spearman 1290 → 187 builds; Horseman 320 → 750** — the agent abandoned the unit whose production cost rose 50→65 and switched to cavalry. A state channel about city sites is not a plausible cause of a unit-cost-driven build flip, so this is attributable to the rebalance with reasonable confidence.
- **Stats**: `stats/baseline_baseline_settle_1000ep_1788602958.json` + timestamped `win_history`/`win_rate_plot`/`build_orders`
- **Re-evaluated 2026-09-04 after the #51 livelock fix** (`stats/eval_duel_53ch_net128x6_1000ep_vs_duel_25ch_1000ep_1788499820.json`, same protocol v1 settings): **172 / 22 / 6, zero truncated games, 88.7% of decisive games (n=194)**. The pre-fix run above lost ~50 games to livelocks scored as draws; both readings are kept, since the pre-fix numbers are what the pre-fix code produced.
  - 13 games ended before the cap (earliest turn 57); mean length 245.4
  - **Expansion, not conquest, is how it wins**: cities founded **92** vs the baseline's **0** (in the same 200 games, while the baseline produced 500 Settlers), cities captured 13 vs 0, enemy civilians captured 53 vs 0. It *loses* the unit exchange — 69 kills against 169 losses — and wins anyway, because a city is worth ten units in the turn-cap score
  - Builds: 2674 items (Spearman 1290) vs the baseline's 1284 (Settler 500)
