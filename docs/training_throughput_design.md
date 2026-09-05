# Training throughput: where the night actually goes, and what to do about it

**Status**: design, not yet implemented. Written 2026-09-05 (Erik + Claude).
**Issues**: #22 (vectorized environments), #32 (C++ port umbrella), #71 (capacity sweep — the consumer).
**Slot**: after the anti-turtling ladder closes, **before #71**. Nothing here may land while a run is in flight.

---

## 1. The question, and the uncomfortable answer

The question was "can we run games in parallel to go faster?" — prompted by a
correct observation: **during training the CPU sits far from 100%.**

The observation is real. The inference drawn from it is not. Idle CPU here is
not spare simulation capacity waiting to be used; it is the signature of a
**serialized single-threaded loop on an 8-core/16-thread box** (one core partly
busy ≈ 6% of the machine), in which the busy core spends most of its time
launching small CUDA kernels rather than simulating anything.

Running more games in parallel, **on its own, is worth at most ~1.25×** — and
the arithmetic that shows this is in §3. The thing that would actually shorten a
night is the gradient step, and vectorized environments matter only as the
mechanism that makes a *cheaper gradient-step schedule* affordable. That
reframing is the substance of this document.

---

## 2. What the profile measured

From #34 (`scripts/profile_training.py`, 30 measured episodes, RTX 3070,
Duel×2, earthlike, 25ch, production C++ A*, CUDA active, CUDA-synced timers).
A 1000-episode night was **5.07 h**.

| bucket | share | what it is |
|---|---:|---|
| `learning_step` | **78.8%** | `DQNAgent.optimize` — 3 forwards (1 live + 2 target) + 1 backward + Adam, **batch 32** |
| `action_selection.mask_building` | 8.31% | since **vectorized by #42** — largely gone |
| *(unattributed remainder)* | ~9% | `action_selection.net_forward`, replay-memory ops, trainer glue |
| `state_encoding` | 2.4% | `build_state_tensor` |
| `env_step` | 1.2% | the whole game engine (pathfinding **0.17%** — already C++) |
| `world_gen` | 0.28% | 46 ms per Duel world |

Two facts deserve to be stated plainly, because every decision below follows
from them:

- **The engine is 1.2% of the night.** Making the simulation faster — by
  threading it, by porting it to C++, by any means — cannot shorten a night by
  more than about a percent. #32's port is justified by other things
  (determinism, a C++ vector env later), never by this.
- **`learning_step` is the learner, not the actor.** It is one gradient step per
  agent action (`trainer.py:325-326`), i.e. a **replay ratio of 1.0
  updates/transition** at batch 32. This is the load-bearing number.

**Staleness caveat (a real one).** That profile predates #42 (mask
vectorization), #40's 52ch encoder, and #48. With the mask cost removed,
`learning_step`'s share of what remains is ≈ **86%** — a derived figure, not a
measured one. The in-flight run trains at 54ch, which raises both encoding and
network cost. **A re-profile at the current config is gate 0 below**; no patch
should cite the 2026-08 shares as current.

---

## 3. Why parallel games alone cap at ~1.25×

Normalize one agent action to cost 1.0 and split it in two:

- **L = 0.788** — the gradient step. Strictly sequential: update *k+1* reads the
  weights update *k* wrote. It cannot be parallelized across games, ever.
- **A = 0.212** — everything else (encode, mask, forward-for-action, engine,
  replay ops). Batchable or overlappable across independent games.

Run *N* games concurrently and hold the replay ratio at 1.0, which is what
"parallel environments" means if you change nothing else. Each of the *N* games
still produces one transition per action and each transition still demands its
own gradient step, so the learner's work scales with *N* while only *A* is
amortized:

```
wall-clock per game  ≈  L·T + A·T/N
speedup              =  1 / (L + A/N)   →   1/L = 1.27×  as N → ∞
```

**N = 8 gives 1.22×. N = 64 gives 1.27×. There is no configuration of "more
games" that beats 1.27× while the replay ratio is held fixed.** Amdahl, with L
as the serial fraction.

This is the finding that saves the most time: it is exactly the plausible plan
that would have consumed weeks and returned nothing.

---

## 4. The two real levers

### Lever A — make each gradient step cheaper (semantics-preserving)

Batch 32, on a 12×24 board, through a FullyConv stack, three forwards and a
backward. Every kernel in that graph is far too small to occupy a 3070; the
launch overhead (~5–10 µs) plausibly exceeds the arithmetic. If so, the gradient
step is **launch-bound**, which has a startling implication: *its wall-clock cost
is nearly independent of batch size in this regime.* Batch 256 would cost close
to what batch 32 costs.

Interventions, in order of risk:

1. **CUDA graphs** on `optimize()` — capture the fixed forward/backward/step
   graph once, replay it. Same math, same order, same numerics; removes
   per-iteration launch overhead. If L falls by 4×: `1/(0.197 + 0.212) = 2.4×`
   **on the whole night, with no experimental confound at all.**
2. **Fuse the three forwards.** `compute_loss` runs the target network twice on
   the same `next_state_batch` (dqn_agent.py:248,251) to get select-then-move
   Q-values. One forward returning both heads would remove a third of the
   forward work outright.
3. **Fewer H2D transfers** — `torch.stack(batch.state)` on every optimize; a
   pre-allocated pinned staging buffer, or storing replay states already on
   device, removes a per-step copy.
4. **channels_last / TF32** — cheap, but **TF32 changes numerics**. It is
   therefore *not* neutral and must not be enabled silently mid-series.

Items 1–3 are the rare kind of change that is both large and scientifically
free. **They should happen regardless of what we decide about parallel games.**

### Lever B — fewer gradient steps per transition (an experiment, not a speedup)

The other way to cut `L·T` is to stop paying it once per transition. Run *N*
games, collect *N* transitions per round, and do **one** gradient step at batch
32·N:

```
replay ratio: 1.0  →  1/N
wall-clock per game ≈ (L' + A)·T / N,  where L' = one gradient step at batch 32N
if launch-bound (L' ≈ L):  speedup ≈ N
```

**This is where the entire gain lives, and it is not free — it is an algorithmic
change.** Replay ratio, batch size and data diversity all move together, which
is precisely the confound the literature documents:

- Replay ratio (updates per environment step) is a first-class hyperparameter of
  off-policy agents; lowering it makes the learning problem **more stationary**
  but spends each transition less thoroughly.
- Scaling off-policy learning under massive parallelism ([Parallel Q-Learning,
  arXiv:2307.12983]) finds the gain is **not** explained by data recency or
  policy diversity alone — a substantial part comes from better exploration and
  reduced overfitting. So there is an expected *quality* upside here, not only
  speed; it is not a pure speed-for-accuracy trade.
- Batch size and parallelism change **policy churn** — how many distinct policy
  networks the agent traverses ([Policy Churn, arXiv:2206.00730]) — which is one
  of the axes separating DoubleDQN from R2D2.

**Consequence for method**: N is not a performance knob we may turn quietly. It
is an experiment variable in the #39-baseline series, and it must be reported as
one.

### Lever B is available at N = 1 — and that reorders the plan

Added 2026-09-05 after Erik asked the obvious question the analysis had skipped:
*why are we optimizing on every single action at all?*

Nothing about lowering the replay ratio requires parallel games. Let *r* be the
replay ratio relative to today's 1.0; the trainer change is a counter and a
modulo at `trainer.py:325`. Then at N = 1:

```
per-action cost = L·r + A
r = 0.25  →  1/(0.197 + 0.212) = 2.44×
r = 0.10  →  1/(0.079 + 0.212) = 3.44×
r → 0     →  1/A               = 4.72×  (the ceiling)
```

**Pure replay-ratio reduction at N = 1 is worth up to 4.7×, against 1.27× for
pure vectorization at fixed r.** It is also roughly three lines of code. It is
the highest-value, lowest-effort change on the board, and it is *not* what this
document originally led with.

The two levers then compose in a specific order, and only that order:

| stage | L·r | A | speedup vs today |
|---|---:|---:|---:|
| today (r=1, N=1) | 0.788 | 0.212 | 1.00× |
| r = 0.25, N = 1 | 0.197 | 0.212 | **2.44×** |
| r = 0.25, N = 8 | 0.197 | 0.027 | **4.47×** |

Lowering *r* raises A's share of the night from 21% to **52%**, and A is the part
that vectorization amortizes. So the RR reduction does not merely precede the
vector env — **it is what makes the vector env worth building.** At today's r,
N = 8 buys 1.22×; after the RR change the same N = 8 buys 1.83×. Doing #22
first would have measured the vectorization at its worst possible operating
point and probably concluded, correctly but uselessly, that it does not pay.

The same reordering also lowers risk: a lower replay ratio *reduces* exposure to
the plasticity-loss / primacy-bias failure mode that afflicts high-RR agents
(§4B), so the cheap change is also the conservative one.

**Caveat — "one gradient step per Civ turn" is not yet a number we can state.**
Erik's suggested unit ("at minimum one Civ turn") is the natural granularity, but
`stats/*.json` records neither steps nor turns per episode, so actions-per-turn
is unmeasured and *r* for that policy cannot be derived from any committed
artifact. Gate 0 must capture it, and the run record should gain `steps`,
`turns` and `optimize_count` fields — a small schema gap worth closing anyway.

---

## 5. Civ is sequential — what that actually constrains

This has to sit at the centre of every decision, so let us be exact about what
it forbids and what it permits.

**Forbidden — parallelism inside a game.** Turn *t+1* depends on turn *t*. Worse,
*within* a turn, unit A's move changes unit B's legal moves, so even the orders
inside one player's turn are a dependent chain. There is no batch axis inside a
game, at any granularity.

**Permitted — parallelism across games.** Game 5's turn 100 is fully independent
of game 6's. **The batch axis is games, and only games.** Everything below
follows from that single sentence.

Three consequences that shape the implementation:

1. **The batch is ragged and asynchronous.** Games have different lengths, and at
   any instant each game sits at a different point in its own sequence: one is
   mid-turn on its third unit order, another is between turns, another has just
   ended. You **cannot** batch by lockstep step index. You can only batch
   *whatever decision requests happen to be pending*.
2. **Batching must key on (seat, network).** A duel has two DQN agents with
   separate weights, plus a BuildAgent. A batch may only contain requests bound
   for the same network. Games desynchronize immediately, so "all games' player-0
   decisions" is not a thing that exists after turn 1.
3. **Autoreset and truncation are per-env.** A finished game must reset and
   rejoin without disturbing the others, and per-env truncation must still reach
   the machine-readable record — `truncated_episodes` is an invariant (#51), and
   silently averaging it away across N envs would be exactly the bug that
   invariant exists to prevent.

This is also the honest reason **GPU-side simulation stays rejected** (#32): A*,
per-unit branching, and production queues are maximally SIMT-divergent. Nothing
in this document reopens that.

---

## 6. What AcceRL contributes, and what it does not

[AcceRL, arXiv:2603.18464] proposes **inference-as-a-service**: rollout workers
fire asynchronous inference requests at a centralized pool, which uses **dynamic
windowing** (wait up to a latency budget, or until B requests accumulate) to
form batches, balancing GPU utilization against per-request latency.

**What does not transfer.** AcceRL's target is VLA models where *actor inference
dominates*. Here actor inference is a slice of the ~9% remainder. Adopting
AcceRL to speed up action selection would be optimizing the wrong tenth of the
night.

**What transfers, and is genuinely the right idea.** Two things:

- **Dynamic windowing is the correct answer to §5's ragged batch.** It is the one
  batching discipline that does not require games to be in lockstep — which, per
  §5.1, they never can be. Any lockstep vector-env design fights the sequential
  structure of the game; a windowing batcher works *with* it.
- **Decoupling collection from learning turns N and the replay ratio into
  independent knobs.** Today they are welded together: one env, one update per
  action. With a request-queue architecture, "how many games are running" and
  "how often the learner steps" are separately configurable — which is precisely
  what §4B says we must be able to vary **one at a time**. AcceRL's architecture
  is what makes lever B a *controlled* experiment rather than a compound change.

That is the case for reading it seriously: not for its throughput claim, but
because it supplies the control we need for scientific hygiene.

For comparison, **EnvPool** ([arXiv:2206.10558]) is the reference implementation
of the same asynchronous idea one layer down (C++ thread pool, `send`/`recv`
instead of a synchronous `step`, pybind11 — the stack `civulator_core` already
uses). It is the model to copy **if and when** the engine's 1.2% ever becomes
worth attacking, which per §2 it currently is not. Note also that async
vectorization is not universally superior: on modest hardware the IPC overhead
makes *sync* vectorization faster ([Gymnasium, arXiv:2407.17032]), so the
sync/async choice is a measurement on our boxes, not a citation.

---

## 7. Measurement gates (do these before writing any design-dependent code)

**Gate 0 — re-profile at current config.** `scripts/profile_training.py` at
54ch, post-#42, on the box that will run #71. The 2026-08 shares are stale.
*Cost: one profiling run. Output: a stats artifact the whole plan cites.*

**Gate 1 — the decisive microbenchmark (~30 minutes of work).** Time
`DQNAgent.optimize()` at batch 32 / 64 / 128 / 256 / 512 / 1024, CUDA-synced,
warm. This single curve decides everything:

- **Flat** (256 costs ≈ what 32 costs) → the learner is launch-bound → lever A's
  CUDA graphs will pay, and lever B's big-batch scheme gives ≈ N× as derived.
- **Linear** → the learner is compute-bound → **lever B collapses**: a batch-32N
  step costs N× a batch-32 step and there is no throughput gain at all, only a
  replay-ratio change. In that world the honest recommendation is to do lever A
  items 2–3, drop parallel envs entirely, and reconsider only when the network
  grows.

**Gate 2 — `torch.profiler` kernel trace** on one `optimize()` call: launch gaps
vs kernel duration, confirming gate 1's verdict mechanistically. This is step (1)
of the sequence already agreed in #22's comment thread.

**No parallel-env code is written before gates 1 and 2 report.** If gate 1 comes
back linear, this document's recommendation changes, and that must be allowed to
happen.

---

## 8. Proposed patch sequence

| # | patch | neutral? | expected |
|---|---|---|---|
| P0 | Gate 0 re-profile + gate 1 batch-scaling bench (`scripts/bench_learning_step.py`) | measurement | the decision |
| P1 | Gate 2 kernel trace | measurement | mechanism |
| P2 | Fuse the double target-network forward in `compute_loss` | **yes** | ~1.2–1.3× |
| P3 | Remove per-optimize H2D staging (pinned buffer / device-side replay) | **yes** | modest |
| P4 | CUDA graphs on `optimize()` | **yes** (same numerics) | the big neutral win |
| P5 | **`replay_ratio` in config + the modulo at `trainer.py:325`; `steps`/`turns`/`optimize_count` into the run record** | **no — experiment** | up to 4.7× at N=1 (§4B) |
| P6 | Replay-ratio ladder at fixed wall-clock vs the frozen #39 baseline | — | picks *r*; the scientific record |
| P7 | `VectorGameEnvironment` + windowing inference batcher; `n_envs` in config | **no — experiment** | ≈1.8× *on top of* P6's *r*, conditional on gate 1 |

P5/P6 come **before** P7 deliberately: at today's replay ratio the vector env is
operating at its worst point (1.22× at N=8) and would measure as not worth
building; after P6 the same N=8 is worth 1.83×. See §4B.

P2–P4 are safe to land as ordinary optimization patches with before/after
profiling shares cited, per #34's rule of use. **P5 is a designed experiment and
gets the full treatment**: design gate, one variable at a time, CHANGELOG entry,
before/after evaluation.

---

## 9. Experimental protocol for P5/P6

The failure mode to avoid is changing N, batch size and replay ratio together
and being unable to attribute the result. Concretely:

- **Hold wall-clock fixed, not episode count.** The claim under test is "more
  learning per hour", so the comparison is *5.07 h of old* vs *5.07 h of new*,
  both evaluated against the frozen baseline with `scripts/evaluate.py`.
- **Vary replay ratio alone first**, at N = 1, over {1.0, 0.5, 0.25, 0.125}. This
  separates "the replay ratio changed" from "there are more games", which is the
  confound §4B names. It is cheap and it is the control.
- Then vary N at the chosen replay ratio.
- **Record `n_envs`, `replay_ratio` and `batch_size` in the run manifest**
  (`civulator/meta.py`) — pinned at launch, per #75. A run whose manifest does
  not name its replay ratio is not comparable to anything.
- Report `truncated_episodes` per env; N envs must not hide #51-class livelocks.

---

## 10. Systems

**(a) Existing canonical systems this design must use** (from CLAUDE.md's inventory):

- **Game interface** — `GameEnvironment`. The vector env *wraps N instances*; it
  never reaches around them into game state.
- **Engine RNG** — `PortableRNG`. Each env draws its own master seed; the
  episode-seed schedule is partitioned across envs, never shared.
- **DQN stack** — `DQNAgent` / `ReplayMemory` / `train_agents`. Parameterized by
  `n_envs` and `replay_ratio`; **no forked trainer**.
- **Action masking** — `get_valid_select_mask` / `get_valid_moves_mask`. The
  batched path calls the same functions; a second mask implementation would
  recreate the train/play skew these exist to prevent.
- **State encoding + encoder registry** — `get_encoder`; one encoder per side,
  unchanged.
- **Run truncation** — `STEP_LIMIT` and `truncated_episodes`; per-env, never
  aggregated away (#51).
- **Artifact manifests** — `civulator/meta.py`, pinned at launch (#75).
- **Win/score determination**, **gameplay config `CFG`** — untouched.

**(b) New systems this design creates** (draft rules for CLAUDE.md at implementation):

- **`VectorGameEnvironment`** — *the only way to run N concurrent games; owns
  per-env seeding, autoreset and per-env truncation bookkeeping. A single game
  uses `GameEnvironment` directly — never a vector of one.*
- **Batched inference service** (windowing request queue) — *the only path from a
  game's decision point to a network forward pass during vectorized training;
  batches by (seat, network) under a latency window, never by lockstep turn
  index.*
- **`scripts/bench_learning_step.py`** — *the only place batch-size/latency curves
  are measured; every throughput claim in a report or CHANGELOG cites its output
  artifact.*

---

## Sources

- EnvPool — https://arxiv.org/pdf/2206.10558
- Gymnasium (sync vs async vectorization) — https://arxiv.org/pdf/2407.17032
- Parallel Q-Learning: scaling off-policy RL under massively parallel simulation — https://arxiv.org/pdf/2307.12983
- The Phenomenon of Policy Churn — https://arxiv.org/pdf/2206.00730
- AcceRL (inference-as-a-service, dynamic windowing) — https://arxiv.org/pdf/2603.18464
