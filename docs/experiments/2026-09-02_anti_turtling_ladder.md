# The anti-turtling ladder — experiment report

*Erik Steen & Claude · issues #46, #48, #51 · game v0.6.0 → v0.6.1 · runs
2026-09-01 → 09-04 on Home Desktop (RTX 3070).*

> **Revision history.** A first draft of this report was written on 09-02,
> before instrumentation existed, and contained two errors: a three-game
> probe written up as a property of the ladder, and 50 games truncated by an
> engine bug read as battles. Both are corrected below and the corrections
> are kept visible rather than overwritten. **This version is built entirely
> from instrumented evaluations re-run after that bug was fixed**, listed in
> §7 so every number here can be re-derived.

## 1. The question

Trained agents did not fight. Every one of 200 evaluation games in the #40
run reached the 250-turn cap with no eliminations, and the winner was
decided by the score tiebreak. This session tested four explanations, one
new variable per rung, each rung a full 1000-episode training run followed
by the ratified protocol-v1 evaluation: 200 games against the frozen #39
baseline `duel_25ch_1000ep`, 100 seeds × both seat assignments, ε = 0.05.

## 2. The four diagnoses

1. **No incentive** (#46): the reward table had no reward for winning at all,
   symmetric kill/loss (±10), and γ = 0.9 hides anything beyond ~10 turns.
2. **No exploitation** (#46): `epsilon_decay_episodes = 5000` meant a
   1000-episode run trained at ε ≈ 0.81–1.0 throughout — the policies almost
   never experienced their own play.
3. **No perception** (#48): the network's receptive field is ~3 hexes and
   enemy cities were a single binary channel, so a target 12 hexes away was
   architecturally invisible; a proximity-field channel was added.
4. **No capacity** (#48): 18,118 parameters, scaled to ~950k across three
   rungs.

## 3. Results — all eight models, one table

Every model re-evaluated 2026-09-04 under identical post-fix rules, 200
games each, **zero truncated games in any run**. "Decisive rate" is A's
share of games that produced a winner; z is against a fair coin.

All counts are **totals across that model's 200 games** and are the model's
own (its opponent is always the same frozen baseline). "Kills" is enemy
units destroyed; "losses" is its own units destroyed; "eliminations" is
games won outright by wiping the opponent out, which in this engine means
capturing their last city.

| model | what it adds | decisive rate | z | kills | losses | cities founded | cities captured | eliminations |
|---|---|---|---|---|---|---|---|---|
| `duel_52ch` | terrain block, 18k params (#40) | 0.447 (n=170) | −1.4 | 1 | 0 | 0 | 0 | 0 |
| `duel_25ch_rw2` | reward table v2 | 0.472 (n=176) | −0.7 | 0 | 0 | 0 | 0 | 0 |
| `duel_25ch_rw2eps800` | + ε decay to 0.05 by ep 800 | 0.500 (n=172) | 0.0 | 0 | 0 | 0 | 0 | 0 |
| `duel_26ch` | + city-proximity channel | 0.469 (n=175) | −0.8 | 0 | 0 | 1 | 0 | 0 |
| `duel_26ch_net32x64x64` | + 101k params | 0.528 (n=163) | +0.7 | 0 | 0 | 0 | 0 | 0 |
| `duel_26ch_net64x5` | + 600k params | 0.465 (n=170) | −0.9 | 0 | 0 | 1 | 0 | 0 |
| `duel_26ch_net128x6` | + 950k params | 0.587 (n=184) | **+2.4** | 0 | 2 | 21 | 0 | 0 |
| **`duel_53ch_net128x6`** | **+ terrain block** | **0.887 (n=194)** | **+10.8** | 69 | 169 | **92** | 13 | **13** |

The last two columns are the same thirteen games: **every elimination was a
city capture, and every one was won from seat 1** (the winning model's
seat-1 network scores 93 wins to seat 0's 79 — the same twin asymmetry the
earlier 26ch run showed). Eliminations are the only games in this entire
table that ended before the 250-turn cap.

## 4. What the instrumentation actually shows

**Combat is essentially absent from seven of the eight models.** Across 200
games each, six record **zero kills** and one records one. This is not a
subtle effect: at 250 turns per game that is 50,000 turns of play per model
without a single unit dying. The turtling diagnosis was correct, and none of
rewards, exploration, perception or capacity-below-950k changed it at all.

**Win rate tracks cities founded, and nothing else.** Ordering the table by
cities founded reproduces the ordering by win rate: 0–1 cities → decisive
rates clustered around 0.47–0.53, all statistically indistinguishable from a
coin flip; 21 cities → 0.587; 92 cities → 0.887. Nothing else in the
measurements separates the models.

**Settler production is almost entirely wasted, for everyone.** In every
matchup the baseline built between 520 and 551 Settlers per 200 games — over
40% of its total production — and founded between **0 and 3 cities**. That
is roughly one city per two hundred Settlers. Erik observed a second city
being founded in a replay and asked whether it was real; it is real, and it
is also rare enough that a three-game probe (the first draft's error) could
easily see none.

**The winning model wins by expanding while losing the fight.** The 53ch
model is the only one that fights at all, and it *loses* the exchange: 69
kills against 169 losses. It wins 88.7% of decisive games anyway, because a
city is worth ten units in the turn-cap score (`player_score`, #55) and it
founds 92 cities to the baseline's 0. It also captures 53 enemy Settlers and
13 cities — the only model to do either.

**Two ingredients were needed for that, and neither works alone.** Terrain
at 18k parameters produced nothing (`duel_52ch`: 0 cities, 1 kill,
decisive rate 0.447 — the original #40 null, confirmed with behavioural
data). Capacity without terrain produced the first real expansion but only
21 cities (`duel_26ch_net128x6`). Capacity *and* terrain produced 92.

Two honest caveats on the size of these effects. First, even the best model
founds a second city in fewer than half its games (92 per 200) and kills
0.35 units per game — this is a comparison between very passive policies,
not between competent ones. Second, `duel_26ch_net128x6`'s +2.4 z is a
single 200-game measurement of a modest effect; it deserves a repeat before
anything is built on it.

## 5. The bug that corrupted the first reading

The first draft reported "56 games ended before the cap — warfare at last".
Fifty of those were **livelocks**, not battles (issue #51): a mask-legal
action that changes nothing — a Settler ordered to found where
`min_city_distance` forbids it, or a step the unit cannot afford — returns
`invalid_action` having consumed no movement and ended no turn, so a greedy
policy repeats it until the 10,000-step guard. Those games were cut off and
scored as draws, indistinguishable in the record from real ones.

It cost more than a misreading: it had truncated **85 of the 53ch model's
1000 training episodes**, and 50 of its 200 evaluation games. With the bug
fixed, the same model and the same protocol give **172 / 22 / 6** instead of
122 / 25 / 53 — the livelocks had been suppressing about fifty wins.

Fixed in v0.6.1 with a new invariant: *a mask must never offer an action that
cannot change the state.* Truncation is now recorded machine-readably
(`truncated_games`, `truncated_episodes`) instead of silently becoming a
draw, and the reporting rule in CLAUDE.md requires excluding truncated games
before any claim rests on them.

## 6. What to do next

1. **The score function is doing the work, so look at it first.** Win rate
   is currently a proxy for cities founded, because a city is worth ten
   units and games essentially never end by elimination. Before more
   architecture experiments, decide whether that is the game we want to
   measure — a draw penalty, a different tiebreak weight, or a longer cap
   would each change what "winning" means.
2. **Settlers are the cheapest available win.** Everyone builds them and
   nobody settles them; the model that learned to settle 92 of them beat the
   baseline 172–22. A reward or curriculum aimed squarely at founding may be
   worth more than any encoder change.
3. **Efficiency**: the 53ch run cost 28h01m at 100.9 s/episode, roughly
   triple the earlier big-net runs. Dilated convolutions would reach the same
   receptive field far more cheaply and would pay for every experiment after
   them.
4. **Ablations at 128×6** to attribute what rungs 0–2 could not: they are now
   known to be behaviourally inert *at 18k parameters*, which says nothing
   about whether they contribute at 950k.
5. **Pool the winner** (#6) — `duel_53ch_net128x6` is the first legitimate
   second member of the opponent pool, and this evaluation is the bridge
   match a promotion to reference opponent would need.

## 7. Provenance

Every number above comes from these committed artifacts, all produced by
`scripts/evaluate.py` (protocol v1) after the #51 fix, and re-derivable with
the per-file summary script used to write this section:

`stats/eval_duel_53ch_net128x6_1000ep_vs_duel_25ch_1000ep_1788499820.json` ·
`..._duel_52ch_1000ep_..._1788500042.json` ·
`..._duel_25ch_rw2_1000ep_..._1788500240.json` ·
`..._duel_25ch_rw2eps800_1000ep_..._1788500434.json` ·
`..._duel_26ch_1000ep_..._1788500642.json` ·
`..._duel_26ch_net32x64x64_1000ep_..._1788500859.json` ·
`..._duel_26ch_net64x5_1000ep_..._1788501091.json` ·
`..._duel_26ch_net128x6_1000ep_..._1788501456.json`

Training runs and their manifests are in `weights/trained/manifest.md`;
pre-fix evaluations are kept alongside the post-fix ones, since the pre-fix
numbers are what the pre-fix code produced.

## 8. Also produced this session

**#44 resolved and closed**: the "cross-machine mapgen divergence" was a
record error — the seed schedule skips the identical 19 seeds on every
machine and commit tested, and the baseline's recorded "3 skips" was a hand
transcription of the last three console warnings. Mapgen is cross-machine
bit-stable; skip lists are now persisted machine-readably.

**Five unification issues closed** after an audit against the canonical
systems table: four pre-0.6 scripts archived (their end-turn sentinel
predated the slot-aware action space, so they scored every game a draw —
#53); one shared action decoder (#54); one `player_score` (#55); continuous
east-west scrolling in the canonical renderer, which turned out to be a
one-copy limitation rather than a second render engine (#52); and the
livelock fix itself (#51). The audit found the systems CLAUDE.md names
canonical to be genuinely singular — the drift was concentrated in
`scripts/`.

Also: protocol v1 ratified · an eval-harness crash on unplaceable worlds
fixed · `hexmath.distance` vectorized · FullyConv generalized to arbitrary
depth with checkpoint compatibility pinned · per-side build distributions and
combat counters in every evaluation · mid-training checkpoints.

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
