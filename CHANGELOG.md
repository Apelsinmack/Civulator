# Civulator Changelog

Each entry documents what changed, why, and the measured effect.
Training results (plots, win histories) are in `stats/`.

---

## Unreleased

Version number deliberately not bumped: the next number is an open question
(#83 — "v0.2.0" was said while the code is at 0.6.2). Everything below is a
**rule change**, not a refactor.

### Minimum city distance 3 -> 4, and the start-placement floor with it (#74)

**Rule change, effect NOT yet measured** beyond the seed-schedule count below.
Erik, 2026-09-04: the minimum distance between cities was wrong.

Distance is counted in **steps between tiles**. Standing on a city centre you
must move 4 tiles to get outside the radius and found another city, so the
minimum distance is 4 — which leaves **3 tiles between city centres**. The old
value of 3 came from counting border-to-border instead of centre-to-centre.

`[game] min_city_distance` 3 -> 4 in `config.toml`. **No code changed**:
`GameEnvironment.can_found_city_at` already compares
`if distance < MIN_CITY_DISTANCE: return False`, i.e. founding is legal at
distance >= the constant, so 4 expresses exactly the rule above. Every consumer
reads the rule through that one method and follows automatically — the
found-city path, the action masks (#51), and the #8 settle-site state channel.
No consumer holds its own copy of the number.

`[map.starts] d_min_floor` 3 -> 4 in the same patch (mirrored in
`civulator/mapgen/starts.py`'s `DEFAULT_PARAMS`). It is the same quantity one
layer up — the minimum spacing between *starting positions* — and every start
becomes a capital, so a floor below the city rule could seat two capitals
closer than the rule permits. It is a **floor**, not the spacing: `_compute_d_min`
takes `max(d_min_floor, round(sqrt(tiles / (players * d_min_players_factor))))`,
which on Duel computes 6 and on the Standard ceremony world 7. It binds only on
crowded maps, and only when the relax-and-retry ladder walks all the way down
to it — most maps do not move at all.

**Measured effect — the episode-seed schedule.** Walking the #39 schedule
(`seed_base=390000`, Duel earthlike, 2 players) for a full 1000-episode
baseline run, the seeds start placement rejects went from **19 to 21** out of
1021 consumed (~2.1%, unchanged in order of magnitude). The new set is a strict
**superset** of the old — no seed became placeable — with two additions:
`390477` and `390675`. Full old set: 390016, 390053, 390065, 390076, 390264,
390277, 390294, 390385, 390408, 390489, 390672, 390683, 390689, 390759, 390770,
390785, 390850, 390909, 390945. Because the cursor scheme shifts every later
episode by one per skip, **episode k now maps to a different world from
episode k of the pre-#74 baseline** from episode 477's neighbourhood onward:
runs are not seed-for-seed comparable across this change.

**Golden re-baseline.** `tests/test_mapgen_golden.py`'s `CEREMONY_SHA256`
moved from `73a79864...ed5de4b` to `c1789b41...5b01d5f5`. **Terrain did not
change.** A field-by-field diff of the ceremony `MapData` (Standard 48x24,
seed 42, 6 players) between floor 3 and floor 4 shows `base_terrain`, `relief`,
`feature`, `resource`, `rivers`, `fresh_water` **and `starts`** all
byte-identical; the only field that moved is `params`, the provenance dict,
which now records `d_min_floor: 4`. The floor is not binding on that world (its
raw d_min is 7), so no re-inspection ceremony was needed. `test_rng.py`'s
engine-level twin and `test_ceremony_world_excerpt` both still pass unchanged.
`tests/fixtures/scenario_fixture.json` keeps `d_min_floor: 3` in its pinned
manifest and still reproduces its world exactly — the manifest-pinning contract
working as intended (loaders rebuild from the manifest, never from live config).

**Comparability.** Trained weights still load (`check_version` gates on
major.minor), but their policies were tuned to spacing 3 — the same situation
as the v0.6.2 combat rebalance. A before/after re-evaluation is what would make
this measurable; cities founded per 200 games is the instrumented metric this
rule should move, and it has **not** been run for this patch. Replays
re-simulate rather than replay stored state, so a legality change makes them
diverge; recorded scenarios keep their terrain but may contain city layouts the
new rule would forbid — neither has been validated here.

New test: `tests/test_min_city_distance.py` (7 tests) asserts the boundary
directly — illegal at `MIN_CITY_DISTANCE - 1`, legal at `MIN_CITY_DISTANCE`,
the whole inner ring illegal in every direction, and the mask/encoder agreeing
with `can_found_city_at` tile-for-tile. It imports the constant rather than
hardcoding it (the precedent #8's test set), with one test pinning the literal
4 so the number cannot move silently.

### Siege vs cities: the siege class is exempt from the flat penalty; the two support units get stats (#66)

**Rule change, effect NOT yet measured.** Erik, 2026-09-04: *"Catapults are
good against city walls etc."* They were not — the code penalised them.

`get_ranged_strength` subtracted a flat 17 from **every** ranged unit attacking
a city, the siege unit included. That penalty is a stand-in for a wall model we
have not built, and Civ 6 does the opposite of what it did: ordinary ranged
units do half damage to walls and **the siege class does full damage** — that
is the class's entire identity
([City combat (Civ6)](https://civilization.fandom.com/wiki/City_combat_(Civ6))).
The `-17` was evidently tuned against our old Catapult ranged strength of 45,
and v0.6.2's correction to Civ 6's 35 left it bombarding from a deficit.

**The siege class is now exempt from the penalty.** Membership is declared per
unit type — `siege_class = true` in `config.toml` `[units.Catapult]` — so a
second siege unit is a config line, not a name added to an `if`. Non-siege
ranged units still pay the 17.

**Derived effect** (shots to raze a 200 HP city, mean roll — derivation, not
measurement; city defence 20, or 50 with #7's Walls):

| attacker | vs bare city | vs walled city |
|---|---|---|
| Catapult, before | 27.7 dmg / 7.2 shots | 8.3 dmg / 24.0 shots |
| Catapult, **now** | **54.7 dmg / 3.7 shots** | **16.5 dmg / 12.1 shots** |
| Archer (unchanged) | 18.6 dmg / 10.8 shots | 5.6 dmg / 35.8 shots |

The Catapult goes from 1.5x the Archer's damage against a bare city to 2.9x,
and walls still blunt it — the exemption is an advantage, not immunity.

**BatteringRam and SiegeTower have stats.** Both had occupied `UNIT_SLOT` 2
since the stacking design landed and appeared in no other table: names with a
slot and nothing else. They now have complete entries in all six unit tables,
a `SiegeSupportUnit` class, a `_create_unit` entry, and a `CLASS_INDEX` of -1.

| unit | strength | movement | production | Civ 6 era / tech |
|---|---|---|---|---|
| Battering Ram | 0 | 2 | 65 | Ancient, Masonry |
| Siege Tower | 0 | 2 | 100 | **Classical**, Construction |

Source: the in-game Civilopedia (standard rules), via
[civilopedia.net](https://www.civilopedia.net/en-US/standard-rules/units/unit_battering_ram).
Combat strength 0 is the Civ 6 Analyst's value for both. Note the Siege Tower
is *Classical*, not Ancient, so its stats are Civ 6 correct but not
Ancient-era; the Civ 6 Analyst's production column is on a different, smaller
scale than this repo's costs and was not used (same conflict as the Slinger
entry above).

They are in `DEFERRED_BUILD_UNITS`, **not** `BUILD_OPTIONS`.

**What was deliberately NOT implemented, and why.** The issue itself scopes
this into two rungs and recommends the first only:

1. **The wall model** — city walls as their own HP pool with a per-attacker-
   class damage multiplier (melee ~15% to walls and none to the city behind,
   ranged half, siege full, later wall tiers negating support units) —
   replacing the flat penalty outright. Not implemented. It needs design
   decisions the issue does not settle: how many wall HP, whether walls repair,
   what happens to `City.health` while walls stand, and how a wall pool is
   encoded for an agent. The exemption above is the honest approximation until
   then, and it is strictly closer to Civ 6 than what it replaces.
2. **The support units' adjacency mechanic** — a Battering Ram making adjacent
   melee units do full damage to walls, a Siege Tower letting them ignore walls
   — plus the encoder channels and mask work to make it usable. Not
   implemented; the issue calls it "its own rung afterwards", and a Battering
   Ram is meaningless until walls mean something. `test_siege_vs_city.py`
   asserts that a Ram beside a city changes nothing today, so the mechanic
   arriving has to change that test on purpose.

**Also unaddressed**: the issue asks for city HP / defence strength to move to
`config.toml` in the same pass. That already happened in #64 (`[city] health`,
`[city] defense_strength`).

**And the caveat from #7 applies here too**: no engine order targets a city, so
none of this is reachable in self-play yet. It is reachable — and tested — in
the combat path that the scenario/recording tool uses.

### Flanking bonus: +2 per friendly unit adjacent to the defender (#59)

**Rule change, effect NOT yet measured.** The motivation is measured: the
2026-09-04 cross-model evaluation found six of eight trained models recording
**zero kills across 200 games**, and the one model that does fight losing its
exchanges **69:169** while winning on cities. Attacking is close to pure
downside — a defender on good terrain, possibly fortified, wins the exchange,
and the score rewards keeping units alive rather than trading them. Flanking is
one of the few levers that changes that arithmetic *inside* the combat system,
and it makes a coordinated two-unit attack better than two separate ones, which
is exactly the behaviour no agent has yet learned.

**Who gets the bonus: the unit that is striking.** `get_combat_strength` adds
`flanking_bonus` per neighbouring tile of its target that holds one of the
striker's own combat-capable units. That means:

- the **attacker** gets it, counting its units around the defender — the rule
  as #59 states it;
- the **melee counterattack** gets it symmetrically, because that is the
  defender striking back, counting *its* units around the attacker;
- a unit's **defensive** strength never gets it.

The asymmetry is deliberate and is not v0.6.2's bug in a new costume. #63's
lesson was that a modifier must be applied in every role it belongs in — the
Spearman's anti-cavalry bonus is a property of the *pairing*, so it belongs in
both roles. Flanking is a property of *pressure on the target of a blow*, so it
belongs to whoever is landing the blow. Applying it to defence as well would
reward standing in a crowd, which is the opposite of the behaviour the issue is
trying to buy.

One consequence worth stating: `Unit.attack` computes the attacker's strength
once and reuses it as the attacker's defence during the counterattack (the same
mechanic v0.6.2 documented for class bonuses). So a flanked attacker both hits
harder and takes less. That compounds the incentive to coordinate, which is
intended, and it is a property of the existing combat path rather than
something added here.

**Counted per tile, not per unit.** Tiles stack up to four units in different
slots; a stack is one position pressing on the defender, not three. Civilians
(combat strength 0) do not flank. Adjacency comes from `Map.get_adjacent_coords`
and therefore from `civulator/hexmath.py`, wrap included — no neighbour
arithmetic is written in `unit.py`, which is the invariant #24 was caused by
breaking.

**Value and off switch.** `[combat] flanking_bonus = 2`. Civ 6 uses +2 per
flanking unit and our strength scale is Civ 6's, so the number transfers
directly. **0 disables the rule entirely**, including the adjacency scan — the
minimum version of the tech/culture gate Erik eventually wants (#41/#76), and
what keeps this epoch's behaviour reproducible. It sits in `[combat]` rather
than `[game]`, where the issue's shorthand put it, because
`civulator/unit_model.py` is the only interpreter of the combat tables (#64);
a number in `[game]` would need a direct `CFG` read inside `game/unit.py`.

**Derived effect** (Warrior vs Warrior, flat, no fortification, mean roll —
derivation, not measurement; ratio is damage dealt / damage taken in one
exchange):

| flanking units | attacker strength | dealt | taken | ratio |
|---|---|---|---|---|
| 0 | 20 | 30.00 | 30.00 | 1.00 |
| 1 | 22 | 32.50 | 27.69 | **1.17** |
| 2 | 24 | 35.21 | 25.56 | **1.38** |
| 3 | 26 | 38.14 | 23.60 | **1.62** |

The comparison the rule exists for: two Warriors attacking the same defender
from adjacent tiles deal **65.0** and take **55.4**, against **60.0 / 60.0** for
the same two Warriors attacking separately.

**Measured effect: pending.** Kills per 200 games against the frozen baseline
is an instrumented metric, so the before/after is cheap to produce; whether
agents can *discover* the rule (they must represent "my other unit is adjacent
to that enemy") is the open question that makes this an experiment rather than
a balance tweak. Nothing here should be reported as an improvement until a run
answers it.

### Walls: +30 city defence, buildable, and applied in combat (#7)

**Rule change, effect NOT yet measured — and see the caveat below, which is the
most important sentence in this entry.**

Walls were half-present: a cost in `City.BUILDING_COSTS` and a `+30` literal
inside `City.get_combat_strength`, with no way for any agent to build them.
Wired end to end:

- cost and defence bonus moved to `config.toml` `[buildings.*]`, interpreted by
  `civulator/unit_model.py` — the same discipline #64 applied to the unit
  tables. `City.BUILDING_COSTS` is now an alias, not a second copy.
- `City.get_combat_strength` sums each standing building's configured
  `defense_bonus` instead of a chain of `if building == ...` literals.
- `Walls` added to `BUILD_OPTIONS`; the mask offers it only while the city does
  not already have it (producing a building it owns could not change its
  state — CLAUDE.md's mask invariant, #51).

**Derived effect** (mean roll, 200 HP city, defence 20 → 50 — derivation, not
measurement):

| attacker | attacks to raze, no walls | with walls |
|---|---|---|
| Warrior (melee 20) | 6.7 | **22.1** |
| Archer (ranged 25 − 17) | 10.8 | **35.8** |
| Catapult (ranged 35 − 17) | 7.2 | **24.0** |

And the melee attacker's side of it: a city counterattacks with the same
strength it defends at, so a Warrior that hits a bare city takes 30 damage and
one that hits a walled city takes **99.6** — it dies on its first attack.
Walls do not merely slow a melee assault; at these numbers they end it. That
is a consequence of the existing combat path (a defender always counterattacks
melee), not a new rule, and it is a strong argument for #66's wall model, where
the siege class is the answer rather than an arithmetic wall nobody can climb.

**Caveat — Walls currently buy nothing in self-play.** No engine order targets
a city. `GameEnvironment.step` routes an order to `_execute_attack` only when
`_get_enemy_unit_at` finds a *unit*; a city changes hands by a unit **moving
onto its tile**, and `City.health` is never reduced by anything in the live
game. So the +30 is real, tested, and applied by the one combat path — and
today that path is reached only by the scenario/recording tool and by direct
calls. Until a city-attack order exists, **Walls is a strictly wasted build
option in a training run**, and any measured effect of this change will be
negative for that reason alone. This is a gap worth its own issue; it is
recorded here rather than papered over, and it is the reason no effect is
claimed.

**A latent crash, fixed.** `get_combat_strength` and `get_ranged_strength` read
`target.unit_type` to apply class bonuses. A `City` has no `unit_type`, so
*every* attack on a city raised `AttributeError`. Nothing noticed, because
nothing ever attacked a city. Both sites now read through `getattr`; a city
matches no unit-class bonus, which is the correct answer.

**Removed as dead code**: `elif building == "Castle": strength += 20`. Castle
has no cost, no build option, and no path into a city's `buildings` list —
it was not a rule, it was an unreachable literal.

### Slinger added, Swordsman made buildable (#67)

**Rule change, effect NOT yet measured.** Two holes in the build system, one
of which had been silently costing an entire training epoch.

**1. The Swordsman was unbuildable.** It carried a complete stat line — 35
combat strength, 90 production, movement 2, military slot, the +5 vs Spearman
class bonus — and was absent from `BUILD_OPTIONS`. Derived from the tables it
is the strongest melee unit in the game, and no agent could ever produce it;
it appears in no build-mix statistic because it could not be built. It is now
a build option.

**2. The Slinger did not exist.** Civ 6's Ancient-era ranged starter is now a
unit type, present in all six unit tables, in `_create_unit`, in the encoder's
`CLASS_INDEX`, and in `BUILD_OPTIONS`.

| stat | Slinger | (Archer, for comparison) |
|---|---|---|
| combat strength | 5 | 15 |
| ranged strength | 15 | 25 |
| range | **1** | 2 |
| movement | 2 | 2 |
| production | 35 | 60 |

**Source, and where the sources conflict.** Values are Civ 6 Ancient-era from
the Civilization Wiki
([Slinger (Civ6)](https://civilization.fandom.com/wiki/Slinger_(Civ6))): 5 / 15
/ range 1 / movement 2 / 35 production. The **Civ 6 Analyst**
([well-of-souls.com](https://www.well-of-souls.com/civ/civ6_units.html)) quotes
production on a different, smaller scale — Slinger 25, Archer 33 — which is not
comparable to this repo's costs (Warrior 40, Archer 60, Catapult 120 are all on
the wiki scale). A third figure, 17, appears in web summaries of a different
wiki. We took the wiki scale, because it is the one every existing unit here is
already on; mixing scales would have made the Slinger cheap for the wrong
reason. This is the same honesty the v0.6.2 entry applied to the Archer's cost.

**Range 1 is the point of the unit.** The Slinger shoots, so it takes no
counterattack — but only into adjacent tiles. It is strictly the cheap, weak
predecessor of the Archer: cheaper, weaker, shorter-ranged.

**Ungated, deliberately.** Neither unit has an availability gate beyond
production cost. Research/tech gating is being designed separately (#41/#76).
An ungated unit is a genuinely state-changing action, so CLAUDE.md's mask
invariant holds: `get_valid_build_mask` never offers an option that cannot
change the city's state. In Civ 6 the Swordsman is a *Classical*-era unit
behind Iron Working; admitting it with no tech tree in front of it flattens the
Ancient-era counter web, and that is a known, accepted consequence — it is the
natural answer to the Spearman dominance measured in #60 (48% of 2674 builds,
`stats/eval_duel_53ch_net128x6_1000ep_vs_duel_25ch_1000ep_1788499820.json`)
and it was unreachable.

**What this is supposed to produce.** Derived from the tables and the damage
formula, not measured: the Swordsman beats every other unit except an even
fight against the Horseman, so the build mix should stop being 48% Spearman.
The Slinger is the cheapest way onto the board with ranged damage (35 vs the
Warrior's 40) at the price of needing to stand adjacent. Whether either changes
the measured build mix is the open question; nothing here should be reported as
an improvement until a run answers it.

**Archived weights stay loadable.** `BUILD_OPTIONS` grew 7 → 9, which changes
the `BuildNetwork` output width and input depth, so a checkpoint saved before
this change no longer matches a freshly built agent. Rather than brick every
artifact in `weights/trained/`, options are **append-only** (index k always
means the same option) and `scripts/evaluate.py` now infers the build head's
width from the saved `fc` layer, exactly as it already inferred `conv_channels`
for the combat net. A pre-#67 run therefore keeps playing its own seven-option
policy instead of being padded with fabricated Q-values for options it never
saw. `test_evaluate.py`'s end-to-end load of `weights/trained/duel_25ch_1000ep.pth`
(the #39 frozen baseline) is the gate.

**Not comparable across the change**, in the v0.6.2 sense: policies trained
against a seven-option build space are tuned to a game that no longer exists.
They still load and run, which is what makes a before/after possible.

**Deliberately left out**: the Slinger is not in `scripts/matchup_matrix.py`'s
`COMBAT_UNITS` headline scope (it is in that script's `UNIT_CLASSES`, so
`--units Slinger ...` measures it today). Which units the #65 headline matrix
covers is a scientific-scope decision, not a consequence of a unit existing.
The harness did need one fix to measure it at all: it placed every ranged
attacker at hex distance 2, where a range-1 shooter would record a duel it
could never fire in.

---

## v0.6.2 — Civ 6 Ancient-era combat alignment (2026-09-04)

**Rule change, effect NOT yet measured.** The unit counter web existed in code
but did not function. Two independent causes, both fixed here:

**1. Class bonuses applied only when attacking.** `get_combat_strength` gated
every class advantage behind `is_attacking`, so a Spearman standing still and
being charged by a Horseman got no anti-cavalry bonus — the one thing the unit
exists to do. Only the defender was shortchanged: `Unit.attack` computes the
attacker's strength once and reuses it as the attacker's defence during the
counterattack, so an *attacking* Spearman kept its +10 through the exchange.
Civ 6 applies these bonuses in both directions, and so do we now. Closes #63.

**2. Four constants disagreed with Civ 6**, one of them decisively: our
Horseman was 36 where Civ 6's is 35, one point *above* the boosted Spearman's
35, so the anti-cavalry counter failed by a single point of strength.

| unit | field | was | now |
|---|---|---|---|
| Spearman | production | 50 | **65** |
| Horseman | combat strength | 36 | **35** |
| Catapult | combat strength | 25 | **23** |
| Catapult | ranged strength | 45 | **35** |

Deliberately unchanged: the **Archer** stays at 60 production rather than Civ
6's 50 — the sources conflict (50 in the Analyst table, 60 on the wiki) and
there is no signal yet worth rebalancing on. Warrior, Swordsman and every
movement/range value already matched Civ 6.

**What the change is supposed to produce.** In Civ 6 the counter relationships
resolve to *even* fights decided by production cost, because all melee units
get +5 vs anti-cavalry, which cancels the Spearman's 25-vs-20 strength edge.
Derived from the tables and the damage formula (both units at 100 HP, flat
terrain, no fortification, mean roll — **derivation, not measurement**):

| exchange | before | after |
|---|---|---|
| Horseman → Spearman | 1.62 (cavalry wins) | **1.00**, Spearman 1.23x cheaper |
| Spearman → Horseman | 0.92 (counter fails) | **1.00** |
| Warrior → Spearman | 1.00, 1.25x on cost | **1.00**, Warrior **1.62x** cheaper |
| Spearman → Warrior | 1.22 | **1.00** |

Ratio is damage dealt / damage taken in one attack. The rock-paper-scissors
web is therefore expressed in **cost, not strength**, which means it is only
exploitable through build decisions — see #73.

**Measured effect: pending.** No training run has happened under these rules.
The prior epoch's build mix is what motivated the change (`duel_53ch_net128x6_1000ep`
vs the frozen baseline, 200 games,
`stats/eval_duel_53ch_net128x6_1000ep_vs_duel_25ch_1000ep_1788499820.json`:
**Spearman 1290 of 2674 builds, 48%**, against Warrior 343 and Horseman 320).
Whether the rebalance moves that mix is the open question, and #65 (matchup
harness) plus a fresh run are what would answer it. Nothing here should be
reported as an improvement until then.

**Not comparable across the change**: existing trained weights were trained
against the old costs and strengths, so their build policies are tuned to a
game that no longer exists. Version stays on 0.6.x deliberately — `check_version`
gates on major.minor, so v0.6 weights and scenarios still *load*, which is what
makes a before/after re-evaluation possible at all. Comparability of results is
a separate matter from loadability, and this change breaks the former only.

**Deferred, filed**: the constants are still Python literals rather than
`config.toml` (#64, which should have landed first and would have made this a
one-file diff).

**One accepted regression, quantified.** Copying Civ 6's Catapult ranged
strength (45 → 35) while keeping our ad-hoc flat `-17` vs cities drops the
Catapult to **18 against a city defence of 20** — it now bombards cities from
a strength *deficit*, where before it had 28 against 20. Razing a 200 HP city
goes from ~4.8 shots to ~7.2 (derived, mean roll). Civ 6 has no such flat
penalty: it models walls and exempts the siege class from the reduction other
units suffer, so the `-17` was evidently tuned against our old 45. Taking
cities was already the scarce event in this epoch (the previous run captured
13 cities and founded 92), so this makes the scarce thing scarcer. Accepted
deliberately rather than patched around — replacing the `-17` with a real wall
model is #66, and `tests/test_combat_class_bonus.py` pins the deficit so #66
has to change it on purpose.

---

## v0.6.1 — Masks may not offer no-op actions (2026-09-04)

**Rule change, measured.** An action the engine refuses (`invalid_action`)
consumes no movement, ends no turn and alters nothing, so a deterministic
policy whose argmax lands on one repeats it forever. Two such actions were
reachable through the masks: a **Settler ordered to found a city where
`min_city_distance` forbids it**, and **any step the unit cannot afford**
(1 movement point left with hills or a river crossing ahead). Both are now
excluded by `get_valid_moves_mask`; a Settler with no legal order at all is
no longer selectable. `Unit.step_cost` became the single price of one step,
read by `Unit.move` and by the mask, so the two can no longer disagree.
Closes #51.

**Measured effect** (`duel_53ch_net128x6_1000ep` vs the frozen #39 baseline,
protocol v1, 200 games, before → after the fix):

| | pre-fix | post-fix |
|---|---|---|
| A / B / draw | 122 / 25 / 53 | **172 / 22 / 6** |
| decisive win rate | 0.830 (n=147) | **0.887 (n=194)** |
| games truncated by the step guard | 50 | **0** |

The livelock had been costing the stronger model about fifty games, each
scored as a draw and therefore indistinguishable from a real one. It had
also truncated 85 of that model's 1000 training episodes. Truncation is now
recorded machine-readably (`truncated` / `truncated_games` per evaluation,
`truncated_episodes` per run) rather than silently becoming a draw — hitting
the guard is a bug, never an outcome.

**Not bit-comparable across the fix**: re-running an evaluation of an
existing model no longer reproduces numbers recorded before it, because the
previously livelocked games now play out. Both readings are kept in
`weights/trained/manifest.md`.

## v0.6.0 — Terrain remodel: layered tiles, real worlds (2026-08-23)

**Every seeded world changes.** All pre-0.6 scenario terrain is invalid; the
nine painted scenarios moved to `scenarios/archive_v0.5/` (preserved, never
deleted). Trained weights remain valid 0.5-epoch records, incomparable to 0.6
results (epoch marker in `weights/trained/manifest.md`). Closes #36, #10,
#13, #14 — and with them the #35 land-before-the-1k-baseline bucket: the
world is now declared stable for baseline recording. Full design, adversarial
critique, and measurements: `docs/terrain_model_design.md`.

**The tile model** (#36): `terrain_type` is gone. A tile is base terrain
(Grassland/Plains/Desert/Tundra/Snow/Coast/Lake/Ocean) × relief
(flat/hills/mountain) × ≤1 feature (Woods/Rainforest/Marsh/Floodplains/
Oasis/Reef/Ice) × ≤1 bonus resource (8 types). All gameplay numbers are
additive compositions of per-layer `config.toml` tables interpreted by
`civulator/terrain_model.py`; placement validity is declared per layer as
`on` constraints — one evaluator for generator, painter, and Tile alike.
Water exists for the first time and is impassable to the land movement
domain (`unit.can_enter`; embarkation is a future domain value, not a
rewrite). Rivers stay on edges, now with flow direction and flux, and cost
`[terrain.river] crossing_cost` to cross — priced identically by movement
execution and both A* implementations (C++ ≡ Python verified exactly).

**World generation** (#13, #14): new pure package `civulator/mapgen/` —
periodic-lattice Perlin gradient noise sampled at hex Cartesian centers
(exact cylinder wrap, no seam handling, no trig; lowbias32 integer hashing,
bit-portable for the future C++ twin), split-elevation pipeline
(continentalness shapes coasts; ridged-multifractal orogeny shapes relief,
rivers, and temperature lapse), latitude climate reaching the poles,
Whittaker biomes, corner-junction flow-accumulation rivers, deterministic
floodplains, oases, resources, and fertility-scored starting locations.
Measured effects: directional-isotropy ratio 1.04–1.21 (the old axial
sampling scores 1.68–2.75 — #13's streaks are dead, with a regression
oracle); start-placement failure 27.7% → 2.0% over 900 seeds after the
split-elevation fix; 3–5 continents per world at every size.

**Starts & sizes** (#10, superseding its map-around-starts sketch): map
first → equal-fertility regions → d_min placement → additive normalization
with bonus resources. Named size presets Duel…Huge (+Colossal) carry
dimensions and player counts; Standard stays 48×24 but defaults to 6
players (max 8). Seeded `reset` raises on an unplaceable world
(reproducibility); unseeded `reset` resamples with logged, bounded retries.

**Reproducibility hardening**: scenario/recording manifests pin the mapgen
params; loaders rebuild from the manifest, never live config — tuning knobs
can no longer silently rewrite saved worlds (regression-tested). One version
gate (`meta.check_version`) refuses missing/mismatched manifests. The frozen
world is now sealed at two layers: full-MapData SHA-256 and an engine-level
label fingerprint, both re-baselined this release onto worlds inspected in
the live preview (`python -m civulator.mapgen`) and pronounced good by Erik.

**Ten latent fixes** rode along, notably: unit terrain defense was frozen at
the spawn tile (city-produced units had none, ever) — defense now reads the
composed current tile; feature movement/defense/LoS bonuses existed but were
consumed by nothing — now active; four eval/replay scripts used a
terrain-blind mask fallback instead of the training masks; the C++ A* popped
equal-cost paths in insertion order (nondeterministic ties) — now matches
Python's (f, r, q) tie-break exactly; the renderer drew axial coordinates in
an offset layout (~17% of adjacencies rendered wrong) — replaced by the
brick-rectangle projection with a permanent adjacency-render invariant test.

State encoding: channel layout unchanged (25/27), with three documented
value corrections (cost scale 4.0 with impassable unique at 1.0; composed
defense; masks now domain-filtered). 0.6 agents cannot yet see resources or
rivers — the richer encoder is a separate measured experiment (design §7).

---

## v0.5.2 — Every player gets a capital (2026-08-22)

Fixes the long-standing "city disappears near game start" bug (#1): `reset()`
ignored `found_city`'s return value, which is silently `None` on a
Mountain/Ocean start tile or within min city distance of an earlier capital.
The city-less player was marked dead by `end_turn` on turn one and their
units deleted — observed as a vanishing city. Capitals now re-roll (seeded
rng, bounded) until placed; reset raises if the map genuinely can't fit the
player count. Spawn-affecting: episode worlds differ from v0.5.1 for seeds
that previously produced an invalid start. The full starting-locations
overhaul (standardized map sizes, generate-terrain-around-starts) remains #10.

---

## v0.5.1 — Portable engine RNG (PCG32) (2026-08-22)

**RNG stream change: a seed from before v0.5.1 produces a DIFFERENT world
after it.** No v0.5.0 scenario files existed yet, so nothing was invalidated —
this swap deliberately landed *before* the first reproducible scenarios were
painted. From now on the seeded world is frozen by a golden test
(tests/test_rng.py::test_engine_world_is_frozen_across_versions); changing it
again requires a version bump and CHANGELOG entry.

- `civulator/rng.py`: PortableRNG — PCG-XSH-RR 64/32, bit-verified against
  O'Neill's published pcg32 reference output. Replaces `random.Random`
  everywhere in the engine (map gen, starting locations, damage rolls).
- Purpose (#33): a future C++ engine twin can reproduce the identical random
  stream, so golden seeded games gate each ported subsystem. Derived-draw
  specs (floats, randint, shuffle, choices) documented in the module docstring
  and frozen as golden test vectors.

---

## v0.5.0 — Fog of war + ranged targeting + fortify fix (2026-08-22)

**Gameplay/training-affecting: training runs before and after this version are
not comparable baselines** (fortify became reachable, ranged attacks became
selectable; fog is opt-in).

- **Fog of war** (design: Erik + Claude, 2026-08-22). Three knowledge states —
  hidden / explored-but-fogged / visible. The engine owns perception:
  `env.get_visibility_mask(p)`, `env.get_explored_mask(p)`,
  `env.update_exploration(p)`; visibility unions unit AND city sight (cities
  have eyes), with a per-tile visibility cache on `Map` (terrain is static per
  episode, so after warm-up a mask is a union of cached sets — no LoS walks).
  The `EnhancedStateEncoder` applies fog optionally via `[training] fog_of_war`
  (default false → output bit-identical to v0.4.x, depth 25). With fog on
  (depth 27): enemy units appear only where visible, enemy cities and terrain
  where explored, plus visible+explored mask channels. C++ port of visibility
  deliberately deferred until profiling shows it hot.
- **Ranged targets in the action mask** (#30): `get_valid_moves_mask` now marks
  enemy tiles within a ranged unit's range AND rules-line-of-sight as valid
  targets — archers/catapults can finally shoot at range 2, for the agent and
  the Order Recorder alike. Rules-LoS implies the shooter sees the target, so
  the mask leaks nothing under fog.
- **Fortify fix** (#29): the slot-aware select `(r, c, slot)` never matched the
  `(r, c)` order, so the DQN agent could never fortify (always scored
  invalid_action). Fixed by comparing positions only.
- `civulator_core` C++ module now also built on the Home Desktop (cp311).

---

## v0.4.1 — Engine correctness + reproducibility (2026-08-22)

- Ranged attacks now use hex distance with cylindrical wrap, fixing incorrect
  range checks near the map seam (#24, gameplay-affecting).
- Combat/action rewards read from `config.toml` `[training.rewards]` instead of
  hardcoded literals (#25).
- Engine RNG is seedable via `reset(seed=...)`, enabling reproducible episodes (#26).
- Hex rendering extracted into a shared `civulator/viz` module — one renderer for
  the viewer and other visual tools instead of forked drawing code (#27).
- Saved artifacts (trained weights, scenarios, stats) now carry an embedded
  manifest (`civulator/meta.py`) recording the game version, git commit, full
  config, and save date that produced them (#28).

---

## v0.3.0 — Combat + City Production + Healing (2026-03-04)

### New Features

**Combat system activated in step()**
- `env.step()` now detects enemy units at the order destination and triggers attack.
- Two-click paradigm: select unit → click destination. Enemy unit = attack, empty = move,
  same tile = fortify, enemy city tile = capture after killing defender.
- Melee attacker moves into vacated tile after killing defender (Civ-style).
- Combat rewards: `damage_dealt * 0.1`, +10 for kill, -10 for being killed, +20 for city capture.

**City auto-production (Patch 1)**
- Cities now default to producing Warriors (cost 40, ~20 turns at pop 1).
- After completing a unit, auto-queue next Warrior.
- New units spawn ON the city tile (Civ-style stacking).

**Unit healing**
- +10 HP/turn base, +20 HP/turn if fortified. Capped at 100.
- Called at start of each turn via `player.start_turn()`.

**Configurable network sizes**
- `SelectAndMoveNetwork` accepts `conv_channels` and `fc_hidden` parameters.
- Four model sizes defined for tournament:
  - Small: 36k params (conv=(16,32), no fc_hidden)
  - Medium: 246k params (conv=(32,64), fc_hidden=128)
  - Large: 958k params (conv=(64,128), fc_hidden=256)
  - XL: 3.8M params (conv=(128,256), fc_hidden=512)

**Tournament script** (`scripts/tournament.py`)
- Trains all model sizes, then round-robin (100 games per matchup, 50 as each side).

**Replay tool** (`scripts/replay.py`)
- ASCII visualization of trained agents playing. Interactive (Enter per turn) or `--no-pause`.

### Training Results (500 episodes, with combat, before Patch 1)

- Player 1: 240 wins (48%), Player 2: 238 wins (48%), **Draws: 22 (4%)**
- Massive improvement from v0.1.0 baseline (76% draws → 4%)
- Episodes now ~0.3s (down from 30s in v0.1.0)

### Files Changed
- `civulator/game/environment.py` — combat in step(), _execute_attack(), _check_game_end()
- `civulator/game/city.py` — auto-production, city tile spawning
- `civulator/game/player.py` — heal() in start_turn()
- `civulator/game/unit.py` — heal() method
- `civulator/agents/networks.py` — configurable conv_channels, fc_hidden
- `civulator/agents/dqn_agent.py` — pass conv_channels, fc_hidden to network

### Files Created
- `scripts/tournament.py`
- `scripts/replay.py`
- `documents/game_state.md`
- `CHANGELOG.md`

---

## v0.2.0 — DQN Fix + Pathfinder Fix (2026-03-04)

### Bug Fixes

**Softmax removed from network output**
- The network used `F.softmax()` on both heads, squashing Q-values into a probability
  distribution that sums to 1. This broke DQN — the Bellman target can be any magnitude,
  but softmax outputs are always in [0, 1]. Loss was meaningless.
- Greedy action selection used `torch.multinomial` (sampling) instead of `argmax`.
  So even "greedy" was stochastic.
- `compute_loss()` sampled random actions for next-state Q-values instead of taking max.
- **Fix**: Raw Q-values, argmax for greedy, proper Bellman targets with `torch.no_grad()`.

**Pathfinder bypass for adjacent moves**
- `unit.move()` rejected all 1-hop moves. The pathfinder returns positions *not including
  the start*, but `move()` assumed `path[0]` was the start and skipped it. A path of
  length 1 (adjacent tile) was rejected by `if len(path) <= 1`.
- **Result**: 72% of all agent actions were invalid moves that did nothing. Episodes took
  2000-3600 steps instead of ~40. Training time was ~30s/episode instead of ~0.3s.
- **Fix**: Adjacent moves (distance 1) bypass the pathfinder entirely — direct move with
  terrain cost check. The underlying pathfinder wrapping logic (Erik's original modulus
  approach) is correct and unchanged.

**Matplotlib hang on save**
- `plt.savefig()` without `plt.close()` and without Agg backend caused the process to
  hang after training completed.
- **Fix**: Set `matplotlib.use("Agg")` and added `plt.close()`.

### Baseline Results (v0.1.0 — before fixes)

500 episodes, max 250 turns, 4x8 map, 2 players, 3 warriors each.

- Player 1: 75 wins (15%), Player 2: 46 wins (9.2%), **No winner: 379 (75.8%)**
- Win rate curve: flat, no learning trend
- ~6s/episode (but most time wasted on invalid moves)
- Stats: `stats/win_history_1772649997.npy`, `stats/win_rate_plot_1772649997.png`

### Post-Fix Results (v0.2.0)

*Training in progress — results to be added when complete.*

### Files Changed
- `civulator/agents/networks.py` — removed F.softmax from forward()
- `civulator/agents/dqn_agent.py` — argmax greedy, proper compute_loss
- `civulator/game/unit.py` — adjacent move bypass in move()
- `civulator/training/trainer.py` — Agg backend, plt.close()

---

## v0.1.0 — Package Refactoring (2026-03-03)

### Changes

**Monolithic code split into clean package structure**
- `pyCiv.py` (~2077 lines) split into: terrain.py, tile.py, map.py, unit.py, city.py,
  player.py, environment.py
- Agent code split into: networks.py, dqn_agent.py, replay_memory.py, state_encoders.py
- Training loop extracted to trainer.py
- ASCII display extracted to utils/ascii_display.py
- Entry point: scripts/train.py with CLI args

**StateEncoder abstraction**
- Abstract base class so different agents can use different state representations.
- BasicStateEncoder: 5 channels (own cities, own health, own movement, enemy cities,
  enemy health).

**Bug fixes during refactoring**
- `GameEnvironment.done` not initialized in `__init__` (would AttributeError before reset)
- `reset()` referenced `self.__class__.Player` instead of `Player`
- Move masking used 8-directional grid instead of hex adjacency
- Unit placement from cities used square grid instead of hex adjacency

**CUDA support**
- Installed PyTorch 2.6.0+cu124, confirmed RTX 3070 working.

**C# code archived**
- Moved to `archive/csharp/` — only Python codebase is active.

### Files Created
- `civulator/` package (game/, agents/, training/, utils/)
- `scripts/train.py`
- `documents/design_document.md`
- `CLAUDE.md`

---

## v0.0.0 — Original Code (pre-2026-03-03)

- Single-file game engine: `python/v2_debugging/pyCiv.py`
- Single-file DQN: `python/v2_debugging/GlobalDQNetworkSelectingAndMovingMultipleAgents.py`
- Multiple version folders used as version control
- CPU-only PyTorch
- Archived in `archive/python_versions/`
