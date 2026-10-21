Verdict: survives with fixes

Lens: systems reuse, regression, determinism. Read against worktree `116-progression-design` at 9d877b5. Baseline: the 17 named test files pass (246 tests). Measured regression evidence comes from two scratch pytest plugins that simulate the gates for a player with no techs or civics. Nothing in the worktree was changed.
- `gatesim_plugin.py` refuses every configured district, the gated units and buildings, and the gated improvements in `can_place_district`, the build mask, `produce_*` and `can_build_improvement_at`. Result: **33 failed / 778 passed** on the full suite, with `test_mapgen_earthlike.py` excluded because a native numpy abort, not this plugin, kills the process there. Log: `scratchpad/gatesim/run2.txt`.
- `flanksim_plugin.py` sets the flanking count to 0. Result: **8 failed** in `test_flanking_bonus.py`.

---

## BLOCKERS

**B1. Pre-existing tests the design breaks without saying how each is restated (Erik's rule: a failing pre-existing test is a finding, never a target to bend).** §14 and §15 promise "suite green" per patch, but no section names these tests.
- **P2 availability gate** (simulated, 33 failures):
  - `test_districts.py`: 20 failures. `placeable_type()` returns a real district, and the design gates all ten districts.
  - `test_district_yields.py`: 7 failures, including `test_same_seed_gives_identical_completion_yields_and_stats` at :294 ("fixture: something completed").
  - `test_build_options.py`: `test_the_build_mask_offers_the_unit[Swordsman]` and `test_city_can_actually_produce_the_unit[Swordsman]`.
  - `test_city_walls.py`: `test_the_mask_offers_walls_until_they_are_built` and `test_a_city_builds_walls_and_becomes_harder_to_take`.
  - `test_housing.py::test_the_palace_cannot_be_produced`, which asserts `produce_building("Granary") is True`.
  - `test_terrain_repoint.py::test_improvement_validity_reads_the_on_constraints` (Mine, Fishing Boats).
- **Found by reading the code:**
  - `test_districts.py:735 test_escalation_is_integer_and_fixed_never_scales`. Its `game_progress(None) == (0, 1)` breaks at P2. From P6 its loop over every `DISTRICTS` entry expects escalation, which fails for `fixed` wonders.
  - `test_district_yields.py:144 test_districts_do_not_change_culture_or_production`. P1 inverts this test on purpose.
  - `test_build_options.py:230`: the civilian exemption `{"Settler", "Worker"}` misses the Trader, whose class index is −1.
  - `test_unit_config_identity.py:137-146`: `ANTI_CAVALRY_BONUS`, `MELEE_VS_SPEARMAN_BONUS` and `ARCHER_VS_HORSEMAN_PENALTY` disappear.
  - `test_player_score.py:20-34`: `CFG["game"]["city_score_weight"]` moves to `[game.score]`, and the new population term turns `CITY_SCORE_WEIGHT + 2` into `+ 3`.
- **P4 flanking civic gate** (simulated): 8 failures in `test_flanking_bonus.py`. The `flanking_on` fixture monkeypatches only `FLANKING_BONUS`.
- **Fix:** add a §14 sub-table, "pre-existing tests whose subject is not availability", with the restatement for each. Add one shared helper (e.g. `grant_all(player)` in `tests/conftest.py`) for tests that are not about gating. Their property must keep its strength (for example "mask offers Swordsman *once Iron Working is known*"). Name the three intentional inversions (culture/production consumption, flanking gate, score terms).

**B2. The class-bonus table cannot meet the bit-identity gate, and the oracle is blind to the pair it breaks.**
- Today the archer penalty is applied only in `get_ranged_strength` and only for `unit_type == "Archer"` (`unit.py:424-425`). That is the shooter role only; it is absent from `get_combat_strength`, so it never touches defence or the counterattack. The anti-cavalry and melee-vs-spear bonuses live in `get_combat_strength` (`unit.py:347-352`) and so apply in attack, defence and counterattack.
- The row `{ unit = "ranged", target = "light_cavalry", amount = -5 }`, "applied … in BOTH roles", changes two existing numbers:
  - Slinger → Horseman ranged strength: 15 → 10.
  - Archer defending against, and countering, a Horseman: 15 → 10.
- §6.2 offers a single-unit override but no role or strength dimension, so the archer rule as applied today cannot be written in the table's vocabulary.
- The gate is also weaker than claimed. `matchup_matrix.COMBAT_UNITS` (`scripts/matchup_matrix.py:162`) deliberately excludes the Slinger. One run draws a single continuing RNG stream, so "before/after agree" holds only on an identical unit list and seed.
- **Fix:**
  - Give each row `strength = "combat" | "ranged"`. Combat rows are read by `get_combat_strength`; ranged rows only by `get_ranged_strength`.
  - Write the archer row as `unit = "Archer"`, `strength = "ranged"`.
  - Run the gate as `--units Warrior Slinger Archer Swordsman Spearman Horseman Catapult`, with the same list and seed before and after.
  - Rewrite the two constant tests in `test_unit_config_identity` as literal per-pair strengths (attacker, defender, role, combat or ranged), Slinger included.

**B3. New player state leaks across episodes.**
- `_reset_attempt` (`environment.py:335-347`) resets Player fields one by one on the `recreate_players=False` path. That is the normal seeded `reset()` the trainer and `evaluate.py` use every episode.
- Any field the design adds and this list omits survives into the next episode, so same-seed episodes differ by history. The affected fields are `techs`, `civics`, `current_tech`, `current_civic`, `government`, the policy loadout, `faith`, trade routes, and the pools now in tenths. So does any env-level registry, such as completed wonders or route ids.
- The §14 determinism row builds fresh environments, so it cannot catch this.
- **Fix:** move Player state into one `Player.reset_state()`, called by both `__init__` and `_reset_attempt`. Env-level registries reset in `_reset_city_registry`. Add a test: play N rounds, `reset(seed)`, and require a fingerprint (new state included) equal to a fresh env's `reset(seed)`.

**B4. Config ownership: one reader per table, and the import order is cyclic as written.**
- §3 has `effects.py` validate "every `effects` list in every table". Read literally, that makes it a second reader of `[districts.*]`, which `district_model` owns, and of `[buildings.*]`/`[units.*]`, which `unit_model` owns.
- `requires_tech`/`requires_civic` columns live on unit, building, district and improvement tables. Their owners have to validate those names against `research_model`.
- `research_model`'s policy and government effects name units, buildings and districts. If research_model validates them itself, the import is cyclic: research_model → effects → district_model → research_model.
- `district_model` rejects unknown keys (`_DISTRICT_KEYS`, `district_model.py:43-48`), so every new column has to be declared there.
- `environment.py:109` already reads `CFG["improvements"]` directly, and adding `requires_tech` there would deepen that.
- **Fix:** state the load order:
  1. `research_model`: names, prerequisites, raw effects.
  2. `unit_model` / `terrain_model` / `district_model`: their own new columns, `requires_*` validated against research_model names, raw `effects` kept on their specs.
  3. `effects.py`: validates every spec's effects from those parsed specs, never from `CFG`.
  4. `game/`.
  
  Improvement gating is read through a `terrain_model` accessor.

**B5. `can_build_improvement_at(coordinates, improvement_type)` (`environment.py:1125`) has no player.** §4.1 and §14 have it call `player_can_build`, and P8 adds "never on a tile its owner does not own". It is also the terrain-validity predicate that `test_terrain_repoint` pins on an unowned board (simulated failure). Whose techs it would check is unspecified.
- **Fix:** keep it as the tile and terrain predicate. Add `can_player_build_improvement_at(player, coords, name)` (ownership via `Map.owner_city`, `player_can_build`, then the tile predicate). `WorkerUnit.build_improvement` and the worker default call the new function. Or make `player` a required parameter and update every caller. Choose one.

**B6. The worker default ranks by a number the engine does not have.**
- `Tile.yields` is the terrain composition only (`tile.py:69-71`), and `[improvements.*]` carries only `on` and `housing`.
- So "largest (food + production) gain" (§15 P8) is 0 for every improvement and the rule collapses to config order. The P8 gate "improvements appear in the smoke run" passes anyway.
- If the implementer adds a gain table in `defaults.py`, that is a second interpreter of tile gameplay numbers, against the Terrain model row.
- **Fix:** either
  - add `food`/`production` columns to `[improvements.*]`, parsed by `terrain_model` and composed into `Tile.yields`. Improvements are not layers, so say that no `terrain_epoch` bump is needed and that every yield consumer reads live; or
  - rank by housing gain, then config order, and drop the claim.

**B7. Existing CLAUDE.md rules the design contradicts with no amendment listed.** By the #86 precedent (the Housing row broken without an amendment was a blocker), Systems (b) needs an "amended rows" list:
- **City combat:** "`_capture_city` is the one place a city changes hands". Proposed rewrite: `City.set_owner` is that place; `_capture_city` (force) and `_flip_city` (loyalty) are its only callers.
- **District placement:** "the only writer of `Tile.district` / `City.districts` (beside `remove_city`)". Wonder-race removal adds a writer; route it through one helper, named in the row.
- **Culture yield:** "never add a culture term to the formula". It becomes an alias of City yields; retire or merge the row.
- **Housing:** "never add a term". The effect kinds `housing_if_districts` / `housing_with_building` add terms.
- **District yields:** "nothing consumes it yet".
- **City economy:** phase order; completion moves to `complete_district`; loyalty scaling; growth percent.
- **Win/score:** `[game] city_score_weight`.
- **Combat:** `siege_class` becomes `combat_class`.
- **Buildings:** new columns.
- **Unit system:** the touch list. `CLASS_INDEX` becomes derived, and two undeclared parallel name→class factories must be added or derived from `_create_unit`:
  - `scripts/matchup_matrix.py:165` `UNIT_CLASSES`;
  - `civulator/tools/recording.py:46` `UNIT_CLASSES`, whose `WarriorUnit` fallback at :225 silently turns a painted Crossbowman into a Warrior.
- **Palace:** "gameplay never reads 'capital'". `capital_only` must be defined as "the city holding a Palace".

---

## NON-BLOCKING

1. **Loyalty arithmetic contradicts its own examples.** Python `//` floors negative numbers, but both worked examples in §8.2 assume truncation toward zero:
   - own 31 / foreign 45: `-280 // 63 = -5`, where the doc says −4;
   - own 10 / foreign 30: `-400 // 21 = -20`, where the doc says −19.
   
   A test written from §8.2 fails against a `//` implementation. Specify sign-aware truncation, and say loyalty is clamped to 0..100 after the delta.
2. **Store `Player.techs` / `Player.civics` as lists in completion order, not sets (§4.1).**
   - Python string hashing is randomized per process. A same-process determinism test cannot see set-order dependence.
   - §13's "newest = latest civic" needs completion order, which a set does not keep.
   - Iterate registries in config order and test membership. The auto-pick key is `(cost, config_index)`.
   - Replace the unused legacy `Player.technologies` (`player.py:19`) rather than adding a parallel field.
3. **Percent effects:** state that effects of one kind are summed, then applied once with an integer floor. This covers `production_percent`, `purchase_percent`, `upgrade_cost_percent`, `growth_percent` and `adjacency_percent`. Sequential multiplication with a floor at each step is order-dependent.
4. **`city_yield` units and double scaling.**
   - Pools are in tenths; food and production are whole points.
   - The district term `district_yields()[name]` is whole points and needs ×10.
   - §8.4 says food is not scaled, yet `city_yield(city,"food")` passes through the loyalty scale.
   - Production would be scaled once inside `city_yield` and again in `calculate_production`.
   - Fix: `city_yield` returns unscaled food and production; loyalty is applied once, at the consumer. Give one integer expression for production (percent, loyalty, floor 1) and one for growth (housing band × growth effect × loyalty share).
5. **Adjacency percent is keyed by yield name in §2.1 and by district in §3.** Commercial Hub and Harbor both yield gold, so Town Charters' +100 % would double the Harbor's gold too. Computing it per district inside `yields.py` would be a second conversion of adjacency into yields. Fix: extend `district_yields(city, percent_by_district=None)` to apply per district before summing, keeping one conversion.
6. **Readers of the district registry.** `test_district_yields.synthetic()` monkeypatches only `districts_mod.DISTRICTS` and `housing_mod.DISTRICTS`. Every new reader (`complete_district` reading `kind`, `yields.py` reading wonder columns, loyalty reading the Government Plaza column, `effects.py`) should read through one accessor in `game/districts.py`, or that fixture breaks.
7. **Define a "specialty district" in registry terms** as `kind == "district" and counts_toward_limit`. Meritocracy `per_district`, Classical Republic, `housing_if_districts` and Insulae/Medina all need it; otherwise wonders, the Aqueduct and the Government Plaza get counted by guesswork.
8. **Colossus placement needs a requires-all list.** "Adjacent to land AND to a Harbor" needs an AND, but `requires_adjacent` is any-of (`districts.py:191-195`). Add `requires_adjacent_all` or nested lists. Moving `river_on_tile` into `REQUIREMENT_TILE_TESTS` (`district_model.py:37`) is noted in §9.4; also extend `_DISTRICT_KEYS`.
9. **World-unique wonders:** computed from live state (a razed copy frees the wonder again) or from a persistent registry? Say which. If a registry, reset it per B3.
10. **Patch sequencing.** Each column or effect should land in the patch that owns its validator and its consumer.
    - P3 adds the Trader with `requires_civic = "Foreign Trade"` before civics exist (P4) and before routes (P5). Today that is a build option that cannot pay off, which `DEFERRED_BUILD_UNITS` exists to prevent. Keep the Trader deferred until P5.
    - P2's "new buildings of §6.2" include civic gates (Temple, Amphitheater), effects (Market, Lighthouse) and a government tier (Ancestral Hall) whose validators arrive in P4/P5.
    - P2 can gate districts on techs only; Theater Square, Entertainment Complex and Government Plaza get their civic gates in P4.
11. **Version timing:** bump `__version__` to 0.8.0 in P1, not P9. Otherwise any artifact saved during P1–P8 carries a 0.7.0 manifest under 0.8 rules and passes `check_version` against true 0.7 artifacts. Regenerate the fixture in the same patch.
12. **Domination predicate.**
    - Guard the vacuous case: one player with the only Palace, or none (painted scenarios hold none). A sound form: P holds every Palace and at least one Palace that was granted to another player.
    - Check it from one function called in both `_check_game_end` (`environment.py:776-792`) and `next_turn` (`:807-812`). The end-turn path (`:471-474`) never calls `_check_game_end`, and a loyalty flip at round end happens inside `next_turn`.
    - Return `(winner, victory)` from the one verdict function (`determine_outcome`, with `determine_winner` as a wrapper) so `evaluate.py` does not re-derive the victory type.
    - A truncated game's `victory` is `null`, never `"draw"` (#51).
13. **§8.5 vs §14 row 22 contradict:** §8.5 says a capital can flip; §14 row 22 says "the Palace city never flips". Pick one.
14. **Name-keyed rules left behind by `combat_class`:**
    - `unit.py:560`: the Catapult needs movement ≥ 1 to fire, and the Trebuchet would not inherit it;
    - `environment.py:624`: only `("Settler", "Worker")` are captured, so a Trader is killed;
    - `unit.py:270-276`: `is_siege_class`.
    
    Key all three on the class, or state each exception.
15. **Upgrades:** "the unit becomes the target type". Mutating `unit_type` in place leaves the old subclass (`WarriorUnit` holding "Swordsman"). Replace the unit through `_create_unit` at the same `player.units` index and tile slot, so bankruptcy's "oldest" ordering is preserved.
16. **Bankruptcy's "unit creation order":** no creation id exists. `player.units` order is append order, and captured civilians are appended at capture (`environment.py:627`). Define "oldest" as the index in `player.units`, or add an env-counter `uid`.
17. **Durable retry for one-shot units.** `free_units`, purchased units and returning Traders can fail to place (7 tiles, 6 free units for Statue of Zeus). Specify the retry: the dormant `Player.queued_units` (`player.py:42-50`, never appended to today), or a per-city queue. If `queued_units` is revived, `set_owner` must purge or re-home its entries. Today a queued entry holds a City and places the unit for `city.player`, so after a capture or flip the conqueror would receive the old owner's unit.
18. **Engine defaults that move units:** move the Worker through `Unit.move`, so `step_cost`, slots and `can_enter` apply. Pick the step among adjacent tiles by canonical distance, ties by coordinates. Do not use `path_finder`'s first step: the C++ and Python A* are not shown to break equal-cost ties identically, and an every-turn default with no agent in the loop would turn that into cross-machine divergence.
19. **`free_tech` and `free_population` fire inside the city loop.**
    - Say whether `free_tech` plus a normal resolution may complete two techs in one turn.
    - `free_population` must re-run `assign_tiles` in every city.
20. **Mask invariant in the smoke script:** `smoke_random_selfplay.py:114` draws `random.choice(BUILD_OPTIONS)` without the mask. Under gating it bypasses the availability rule (if `produce_*` does not refuse) or spins on refusals. It also builds Traders beyond capacity. Draw from `get_valid_build_mask`.
21. **The encoder's claim "no new channel" holds, but normalization overflows:** Musketman CS 55 against `MAX_MELEE_STR = 50` (`state_encoders.py:145`). Clamp, or state the overflow; changing the constant would shift every trained `.pth`'s inputs.
22. **`episode_stats` values must stay ints**, because `evaluate.py:401-403` sums every key. Say whether `district_yield_<name>` stays the raw adjacency score or is loyalty-scaled. The capture test in `test_district_yields.py` (`== 3` after `set_owner`) breaks if it is scaled.
23. **Discount rule A:** with techs in the game, is A still "configured discounted types" (`district_model.py:273`) or "the types the player has unlocked" (Civ 6)? Say which.
24. **Inconsistent gating lists:** §0.3 says Swordsman, Horseman and Catapult are newly gated, and that Archer and Spearman are in the opening web. §6.2 also gates Archer (Archery), Spearman (Bronze Working), Granary (Pottery) and Walls (Masonry). Reconcile the two. The build-mask docstring (`build_agent.py:23-25, 173`) changes either way.
25. **Wonder race is decided by turn order:** completion inside player 0's turn beats player 1 every time. That contrasts with the order-independent border and loyalty phases. Accept it in the CHANGELOG, or resolve completions at round end.
26. **Flip rewards (Erik's call; it touches the training objective):** a flip happens in `next_turn`, which has no reward channel. A city lost by loyalty costs the loser nothing and pays the gainer nothing, unlike `REWARDS["capture_city"]`.

---

## Answers

**a. Determinism of the per-turn computations.**
- **Integer sums:** yields, maintenance and loyalty pressure are integer sums over lists (`city.buildings`, `city.districts`, `player.units`, routes) and are order-free.
- **Explicit tie-breaks** are given for auto-pick, government, Trader auto-send, loyalty flips (city-id order, phase-start snapshot) and bankruptcy.
- **RNG:** none is drawn. Flips change ownership, so they shift later border-phase draws, but deterministically.
- **Where the design is silent and order can creep in:**
  1. `Player.techs` / `civics` are sets. The auto-pick `min` over a set with ties, "newest civic", and the list order of `active_effects` depend on per-process hash order (N2).
  2. Percent effects applied sequentially with a floor each step (N3).
  3. Bankruptcy's "creation order" is undefined (N16).
  4. Upgrades that replace the unit object reorder `player.units` (N15).
  5. The worker step via `path_finder` (C++ vs Python tie-breaks, N18).
  6. The loyalty-phase position relative to `turn_counter += 1`, and the economy-phase sub-order (see g).
  7. Episode carry-over through `_reset_attempt` (B3). This is the largest real risk, and the planned test cannot see it.
  8. Negative floor division in loyalty (N1). Deterministic, but it contradicts the spec.

**b. Moving completion, the yield phase, production modifiers and the culture alias.**
- **Pinned numbers:**
  - `test_district_yields.py:144` (inverted by design).
  - The production-pool tests at `test_district_yields.py:56-70` survive: they monkeypatch `calculate_production`, and `process_turn` still pays and nulls `current_production` before calling `complete_district`.
  - `test_district_yields.py:228` survives only if `district_yield_*` stays unscaled after `set_owner` resets loyalty to 50 (N22).
  - `test_districts.py:735` (P2 `game_progress(None)`; P6 `fixed` wonders).
  - The synthetic-registry fixture breaks for any new direct `DISTRICTS` reader (N6).
  - `test_culture.py` holds: culture is unchanged.
- **The v0.7-identity promise holds for culture only.**
  - Every capital gains the Palace's production +2. Every Granary city gains food +1.
  - Loyalty is 100 for founded cities, so scaling is the identity there, but captured cities start at 50.
  - Restate identity as: a non-capital city with none of the new sources equals v0.7 in culture, food and production; a capital differs by exactly the Palace columns.

**c. `BUILD_OPTIONS` growth.**
- Append-only is kept if every patch appends. `options_for_width` keeps archived 10-wide heads evaluable, and the masked prefix stays valid: Warrior is ungated, so the `select_build` fallback at `build_agent.py:253` is safe.
- Gating breaks `test_build_options` (two Swordsman tests), `test_city_walls` (two), `test_housing` (Granary), and the Trader civilian-exemption test (B1).
- The mask invariant holds only if the gate is in both `get_valid_build_mask` and `produce_unit`/`produce_building`. §4.1's list of paths omits `produce_*`; §14 includes it.
- The smoke script bypasses the mask (N20).
- A captured city keeps its in-progress item, so the new owner can complete an unresearched unit. Decide whether that is accepted.

**d. Bit-identity of the class table.** No, not as printed (B2).
- `unit.py:347-352` applies +10 and +5 inside `get_combat_strength`, so in every role.
- `unit.py:424-425` applies −5 only inside `get_ranged_strength`, and only to `unit_type == "Archer"`.
- A class-`ranged`, both-roles row changes Slinger → Horseman ranged strength (15 → 10) and the Archer's defence and counter against a Horseman (15 → 10).
- It is reachable with a per-row `strength` attribute and a unit-level Archer row.
- `CLASS_INDEX` derivation reproduces today's values exactly (`state_encoders.py:135-144`).

**e. Places that would treat a wonder as a district by accident.**

| Place | Status |
|---|---|
| `districts.py:58-59` (`district = "any"` counts `tile.district`) | Covered by §9.1 |
| `districts.py:149-152`: a district row may name a wonder | Harmless |
| `districts.py:182-185` / `_district_slots` (population slot) | Covered by `counts_toward_limit = false` |
| `districts.py:208-212` and `district_model.py:273` (discount A/B) | Covered by `cost_model = "fixed"` |
| `district_cost` escalation | Covered by `fixed` |
| `districts.py:174` `max_per_city` | Fine |
| `districts.py:191-195` requires-any (Colossus AND) | **Not covered** (N8) |
| `district_model.py:43-48` `_DISTRICT_KEYS` (kind, yield columns, effects, requires_*) | Implied, not named |
| `housing.py:133`: a complete wonder's `housing` is summed | Covered (intended) |
| `housing.py:112-120` water fields | Fine |
| `environment.py:1118` / `remove_city` `district_epoch` bump | Covered for race removal |
| `state_encoders.py:660` settle key | Covered via `district_epoch` |
| `can_found_city_at` refuses wonder tiles | Fine |
| `build_agent.py:149-152`: wonder production raises `NotImplementedError` | Safe: no engine default sets district production, and race losers fall to `None` at `city.py:301-302` |
| `_fresh_episode_stats` keys | Unaffected (`adjacency_yield = "none"`) |
| `smoke_random_selfplay.py:85` `choice(list(DISTRICTS))` | Places wonders (intended, P6) |
| `test_districts.py:776` / `test_district_yields.py:270` loop over all `DISTRICTS` | Will include wonders |
| `test_districts.py:735` expects escalation for every entry | **Breaks** |
| "Specialty district" counts (Meritocracy, Classical Republic, Insulae) | **Not covered** (N7) |

**f. What `_flip_city` must mirror from capture.**
- **What `_capture_city` (`environment.py:552-567`) does:** calls `set_owner` (cities lists, `city_changed_player` counters and `territory_epoch`, `assign_tiles`), increments `cities_captured`, and returns `REWARDS["capture_city"]` to the acting step.
- **What stays with the city:** health (stays 0 and repairs at the new owner's turn), `production` and `current_production` (kept, districts v3), districts, the Palace (no re-grant, since `palace_granted` is unchanged), border pools, and `_culture_round`, which prevents double accrual.
- **What `_flip_city` must add or decide:**
  - Put the loyalty reset to `captured` inside `set_owner`, or `_capture_city` is not "untouched" as §8.5 claims.
  - Put trade-route teardown in `set_owner`. §7.4 says "captured or destroyed", which a flip is not.
  - Purge `queued_units` (N17).
  - Keep or null an unavailable `current_production`.
  - Decide the reward, since there is no channel (N26).
  - Decide the stats (`cities_flipped_*`, and whether `cities_captured` also counts).
  - Deleting the old owner's centre units is new; capture never does it. The melee move-in at `environment.py:636-645` can even leave a stacked enemy civilian on a captured centre.
  - Run domination and elimination after the flip (N12).

**g. Turn order.**
- Today `Player.start_turn` runs: exploration → unit reset and heal → cities (repair, food, growth, culture, production) → `city_ranged_attack` → queued units.
- The design places the economy phase "after the cities" but does not order it against the strike or queued units. Within the phase it never fixes the order of maintenance, bankruptcy, research, civics, government and loadout defaults, route expiry and Trader return, Trader auto-send, and the Worker default.
- Consequences:
  - A Bastions card slotted before the strike fires this turn; slotted after, it fires next turn.
  - Bankruptcy before queued placement spares a queued unit; after placement, it can disband it.
  - A Trader returning after auto-send idles a turn.
- Write one order. Proposed:
  1. cities;
  2. maintenance;
  3. bankruptcy;
  4. research;
  5. civics;
  6. government and loadout defaults;
  7. route expiry and return;
  8. Trader auto-send;
  9. Worker default;
  10. `city_ranged_attack`;
  11. queued units.
- At round end, run `_loyalty_phase` after `_border_phase` and before `turn_counter += 1` (`environment.py:801-803`). Say so.
- **Remaining turn-order dependences:** the wonder race (N25); a player stripped of its last city by a flip still plays one turn (`is_dead` is set only in `end_turn`); domination after a flip is unchecked (N12).

**h. Version bump and fixture.**
- `check_version` gates only scenario and recording loads, through `recording.build_env_from_scenario` (`recording.py:171`).
- The fixture is loaded by `test_recording.py` (two tests) and `test_territory.py:90`. `test_version_gate.py` is version-relative.
- `load_weights` and `evaluate.py:159` do not gate. Archived 0.7 weights play 0.8 rules silently; `evaluate.py` should record the weights' `game_version` against the current one in the summary.
- Build heads load at their saved width (append-only kept). Combat encoder depth is unchanged, but normalization overflows (N21).
- `scenarios/archive_v0.5` already needs `override`. No demonstrations are committed.
- Bump the version in P1, not P9 (N11).

**i. Systems missed.**
- **Terrain model:** improvement yields and the improvement gate (B5, B6). Also the existing direct `CFG["improvements"]` read at `environment.py:109`.
- **Movement cost / `Unit.move`** for the Worker step (N18).
- **`Map.tiles_of_city`** (sorted) and `Map.distance_function` for the worker's tile search and Trader destinations. Destinations should come from `city_by_id` sorted, never a set of cities.
- **`_reset_attempt` / Player state** (B3).
- **The two parallel `UNIT_CLASSES` factories** (B7).
- **`evaluate.py`'s numeric stats sum** (N22).
- **Interpreters for the new tables** `[science]`, `[gold]`, `[faith]`, `[trade]`, `[loyalty]`, `[wonders]` and `[game.score]` are not named. Under B4, each needs exactly one module.
- **New reusable seams that deserve rows or amendments:**
  - `combat_class` as the class registry read by combat, the encoder, capture, ZoC, siege and the matrix (amend Combat and Unit system);
  - `city_can_build_building`, the one building-availability predicate, alongside `player_can_build`;
  - the loyalty `pressure` function, which §10.2 plans to reuse for religion;
  - the round-end phase discipline (border, loyalty, and any wonder phase).
- **Epochs:** wonder removal is covered by `district_epoch`; flips by `territory_epoch` via `city_changed_player`. No new cache is proposed, so no new epoch is needed. Any cache of `city_yield`, `active_effects` or loyalty would have to key on a new "progression epoch"; better to say they are never cached, as `district_yields` is not.
