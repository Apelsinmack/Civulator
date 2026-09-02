# The anti-turtling ladder — experiment report, 2026-09-01/02

*Erik Steen & Claude · issues #46, #48 · game v0.6.0 · one overnight session on
Home Desktop (RTX 3070). Report written 2026-09-02 morning; rung 4 still
training at publication (result appended when recorded).*

## 1. The question

The #40 evaluation surfaced a stark fact: **every one of 200 evaluation games
hit the 250-turn cap with zero eliminations** — trained agents don't fight,
they turtle, and the score tiebreak decides everything. This session
systematically tested four hypotheses for why, one variable per rung, each
rung a full 1000-episode training run followed by the ratified protocol-v1
evaluation (200 games vs the frozen #39 baseline `duel_25ch_1000ep`, 100
seeds × both seats, ε=0.05, seed range 990000+). The headline metric is NOT
win rate but **whether games end before the cap**.

## 2. The diagnoses behind the rungs

1. **No incentive** (#46): the reward table had no reward for winning at all,
   symmetric kill/loss (±10), and γ=0.9 makes rewards >10 turns away
   invisible — turtling was arguably *optimal*.
2. **No exploitation** (#46): `epsilon_decay_episodes=5000` meant a
   1000-episode run trained at ε≈0.81–1.0 throughout — the policies almost
   never experienced their own play.
3. **No perception** (#48): the FullyConv network's receptive field is ~3
   hexes; enemy cities (a single 1.0 on channel 23) are architecturally
   invisible across a duel map's ~12-hex capital separation — directed
   marching is not representable.
4. **No capacity** (#48): 18,118 parameters may simply be too small.

## 3. The rungs and results

| Rung | Run | Single variable changed | Eval vs baseline (W/L/D) | Games past cap | Eliminations |
|---|---|---|---|---|---|
| 0 | `duel_25ch_rw2` | Reward table v2: potential-based proximity shaping (Φ = 0.5·Σ military max(0, R−d)), terminal win/loss ±100, capture 80, found 40, unit_lost −5 | 85 / 80 / 35 | 200/200 | 0 |
| 1 | `duel_25ch_rw2eps800` | ε decays to 0.05 by ep 800 (was: stuck at ~0.81) | 84 / 79 / 37 | 200/200 | 0 |
| 2 | `duel_26ch` | CityDistance encoder: +1 channel, unclipped proximity field to nearest enemy city | 84 / 83 / 33 | 200/200 | 0 |
| 3 | `duel_26ch_net32x64x64` | Network (32,64,64): ~101k params, receptive radius 4 | 86 / 84 / 30 | 200/200 | 0 |
| 4 | `duel_26ch_net64x5` | Network (64×5): ~600k params, radius 6 | 83 / 84 / 33 | 200/200 | 0 |
| 5 | `duel_26ch_net128x6` | Network (128×6): ~950k params, radius 7 | *(training at publication)* | | |

Every rung: statistically even win rate (95% CI ≈ ±7pp), **all 200 games at
turn 251, zero eliminations** — five consecutive nulls on the needle that
matters. (Rung 5, approved as the final capacity point, records the evening
of 2026-09-02; a sixth null closes the capacity family.)

## 4. What did move: production behavior

Rung 2's evaluation was the first with per-side build tracking, and it shows
the interventions are *not* inert — they shift the joint policy's production
even though combat outcomes don't budge:

| Producer | Settler | Warrior | Spearman | Archer | Horseman | Catapult | Granary |
|---|---|---|---|---|---|---|---|
| Baseline (same games) | **504** | 175 | 184 | 73 | 80 | 94 | 125 |
| Rung 2 (city-distance) | 200 | 208 | 194 | 190 | 180 | 151 | 90 |
| Rung 3 (+capacity) | 159 | 207 | 181 | 147 | **225** | **200** | 59 |

The baseline mass-produces Settlers; the direction-aware agents shift hard
toward a broad military mix, deepening with capacity (rung 3: cavalry and
siege lead, Granary nearly abandoned). They build armies — they just never
march them into contact.

## 5. Interpretation

Two real defects were found and fixed (a reward table with no win incentive
and a broken exploration schedule), one genuine architectural limit was
identified and bypassed (receptive-field blindness, via the proximity field),
and capacity was scaled 5.6× (33× once rung 4 records) — and the turtle
survived all of it. The surviving explanations, roughly in order of our
current suspicion:

- **The optimum at the cap may genuinely be turtling.** A draw costs nothing
  (draw reward is 0 by deliberate first-pass choice), attacking a fortified
  defender on good terrain is locally negative EV, and the score tiebreak
  rewards accumulating units — which is exactly what the build shift shows
  the agents learning. The cheapest next probe: a **draw penalty**, making
  the cap itself aversive.
- **Multi-step credit assignment**: even with dense shaping (+~0.2 per
  approach step), an 8-turn march into a fight the policy has never won may
  never look good to one-step Q-learning at γ=0.9. Probes: γ=0.95/0.99, or
  n-step returns.
- **The policies may simply need to see wins to value winning**: nothing in
  1000 episodes of self-play between equally passive agents demonstrates
  that captures pay. This is the argument that milestone A routes through
  **imitation learning** (#3/#4 — recorded human demonstrations of combat
  scenarios) rather than further reward/architecture tuning.
- **Look at the games.** Before the next rung of anything: watch the
  city-distance agent play (`scripts/watch.py` needs a two-line encoder
  update first) and read a few eval games move-by-move. Four nulls earn a
  qualitative look at what the agents actually do all those 250 turns.

## 6. Bookkeeping this session also produced

Protocol v1 ratified · eval flake fixed (D26 resample at construction) ·
`hexmath.distance` vectorized (ndarray broadcasting, scalar path untouched) ·
FullyConv generalized to arbitrary depth with checkpoint compatibility pinned
· eval summaries now record per-side build distributions · mid-training
checkpoints every 100 episodes (episodes-to-50% now computable) · issues
filed: #47 (C++ build provenance), #49 (BuildAgent rewards) · everything on
`develop` through `7e8c56d`; all runs, weights, and eval JSONs in the
scientific record with embedded manifests.

---

## Appendix: Civulator — the game in half a page

*(from `docs/game_overview.md`, v0.6.0)*

Civulator is a simplified Civilization-like strategy game on a **hex map that
wraps east–west** (a cylinder). Experiments use the **Duel** preset: 12×24
tiles, 2 players, procedurally generated "earthlike" worlds (seeded and
exactly reproducible). Each player starts with one capital city and three
Warriors.

**Terrain** is layered — base (grassland, desert, coast, ocean, …), relief
(hills, mountains), features (woods, marsh, …), resources, and rivers — and
determines movement cost, defense bonuses, food/production yields, and line
of sight.

**Cities** produce one thing at a time from seven options: five military
units (Warrior, Spearman, Archer, Horseman, Catapult), Settlers (found new
cities), and the Granary building (growth). Food accumulates into population
growth; a city works its surrounding tiles. An undefended city is captured by
moving a unit onto it.

**Combat** uses a Civ6-style strength formula: units have 100 HP, melee and
ranged attacks, fortification and terrain defense bonuses; ranged units need
line of sight.

**A game ends** by elimination, or at the 250-turn cap, where the winner is
decided by score (cities ×10 + units) — equal scores are a draw.

**The agents**: each player is two networks — a combat DQN that picks a unit
and gives it an order (move/attack/fortify/end turn) from an encoded map
view, and a separate build network that chooses city production. They learn
by self-play against each other.
