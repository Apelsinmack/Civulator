---
name: civulator-progression
description: How to work on Civulator's progression systems (v0.8.0, #116) as a developer — add a tech, civic, policy card, government, building, unit, wonder, improvement or effect kind; change combat numbers without breaking the bit-identity oracle; turn the balancing dials and read the stats that measure them; where every engine default lives that an agent action will replace; and where a new per-turn rule goes. Load before touching config.toml's [techs]/[civics]/[policies]/[governments]/[units]/[buildings]/[districts]/[improvements]/[trade]/[loyalty]/[wonders]/[game.score] tables, civulator/effects.py, research_model.py, or any game/*.py module the CLAUDE.md progression rows name.
---

# Civulator progression: the developer's procedure

Design: `docs/progression_design.md` (v2 is the contract; "Implementation
notes" at the end records where the code differs). Rules: the project
`CLAUDE.md` canonical-systems table (rows City yields, Effects, Research,
Building availability, Combat classes, Upgrades, Governments and policies,
Economy phase, Purchasing, Trade routes, Wonders, Loyalty, Improvable tiles,
Engine defaults, Round-end phases, Victory, Win/score). This skill is the
*procedure*; CLAUDE.md is the *rule*. Civ 6 facts used while designing:
`docs/civ6_progression_reference.md`.

## 1. The load order (never import against it)

1. `civulator/research_model.py` — `[research]`, `[techs.*]`, `[civics.*]`,
   `[governments.*]`, `[policies.*]`: names, costs, prerequisites, raw
   `effects`. Imports only `config`.
2. `unit_model.py` (`[units.*]`, `[buildings.*]`, `[culture]/[science]/
   [gold]/[faith]`, `[combat]`, `[city]`, `[housing]`), `terrain_model.py`
   (`[terrain.*]`, `[improvements.*]`), `district_model.py` (`[districts.*]`
   incl. wonders, `[wonders]`): each parses its own columns, validates
   `requires_tech` / `requires_civic` names against `research_model`, keeps
   `effects` raw, and rejects unknown keys through strict key lists
   (`UNIT_KEYS`, `BUILDING_KEYS`, `_DISTRICT_KEYS`, the improvement keys,
   `_POOL_TABLE_EXTRA_KEYS`). **A new column must be added to the list or
   the config fails to load** — that is the point.
3. `civulator/effects.py` — validates every `effects` list from the parsed
   specs (never from `CFG`); `CONSUMERS` maps every kind to its one consumer;
   `DEFERRED_KINDS` is empty and must stay so.
4. `civulator/game/*` — `trade.py` reads `[trade]`, `loyalty.py` reads
   `[loyalty]`, `victory.py` reads `[game.score]` (`training/trainer.py`
   re-exports `player_score` / `determine_winner`), `improvements.py`
   decides what a Worker can build where, `maintenance.py` /
   `purchasing.py` / `upgrades.py` price things, `availability.py` gates
   them, `defaults.py` chooses for absent agents.

## 2. Adding content — the touch lists

| You add | Config | Code | Tests to extend |
|---|---|---|---|
| a **tech** | `[techs.<Name>]` cost, era, requires, (effects; an `enables` rule must be in `effects.RULES` — `ocean_navigation`, v0.9.0 Q5, is read by `game/unit.py movement_domain`) | nothing — gates are columns on the items (`requires_tech = "<Name>"`) | `tests/test_research.py` graph properties run over the registry; add a case only if the tech carries an effect |
| a **civic** | `[civics.<Name>]` + `requires_civic` on what it unlocks | nothing | `tests/test_civics.py` (registry properties) |
| a **policy card** | `[policies.<Name>]` type, requires_civic, obsolete_with, effects | nothing if every effect kind exists | `tests/test_effects.py` validates every configured effect at import |
| a **government** | `[governments.<Name>]` requires_civic, tier, effects incl. `policy_slots` | nothing | same |
| a **building** | `[buildings.<Name>]` production_cost, maintenance, purchasable, requires_tech/civic/district/building/government_tier, yield, loyalty and `amenity` columns (whole points, v0.9.0 Q2; a district or wonder takes the same `amenity` column), effects | **append** to `BUILD_OPTIONS` (`agents/build_agent.py`) — never reorder | `tests/test_build_options.py` partition; availability tests run over the registry |
| a **unit** | `[units.<Name>]` every column (combat_class, era, stats, maintenance, purchasable, requires_tech, upgrades_to; `build_charges` for a unit that builds improvements, #127; `requires_resource` = a strategic resource, honoured on worlds that have strategic resources, v0.9.0 Q1) | `UNIT_SLOT`, `MOVEMENT_DOMAIN` (`game/unit.py`; `"water"` makes it a ship, v0.9.0 Q5: it moves in `"coast"` until its owner has `ocean_navigation`, is built only where its city has a spawn water tile, and is never land military), a subclass registered in `UNIT_CLASSES` (`game/city.py`), **append** to `BUILD_OPTIONS` or name it in `DEFERRED_BUILD_UNITS` with a reason; `CLASS_INDEX` is derived — never edit it; a new **combat class** goes into `unit_model.COMBAT_CLASSES` and gets a `CLASS_CHANNEL` row onto an existing channel (`agents/state_encoders.py`; the naval classes ride melee and ranged) | `test_build_options.py`, `test_combat_classes.py` (registry properties); run the oracle (§3) if any `[combat]` row changes |
| a **district** | `[districts.<Name>]` (see `docs/districts_design.md`), requires_tech/civic, maintenance, loyalty; optional `health` + `captured_health_percent` (both or neither) make it a fortified district (v0.9.0 Q3: attacked like a city, refuses enemy entry while health > 0, strikes when its city may) | nothing | `tests/test_districts.py` placement properties; `tests/test_fortified_districts.py` for a fortified one |
| a **wonder** | `[districts.<Name>]` with `kind = "wonder"`, era, fixed cost, `max_per_player = 1`, placement, columns, scoped effects | nothing | `tests/test_wonders.py` runs the placeability property over every wonder |
| an **improvement** | `[improvements.<Name>]` on, housing, food/production/gold, requires_tech | nothing (the Worker default ranks by the columns, config order breaks ties) | `tests/test_improvement_yields.py`, `tests/test_worker_default.py` |
| a **resource** | `[terrain.resource.<Name>]` class, on, (yields); bonus: `chance`; strategic/luxury: `improved_by`, `frequency`, optional `reveals` (v0.9.0 Q1) | a bonus one: append to `mapgen/resources.RESOURCE_ORDER` with a purpose id in `seeding.py`; a strategic/luxury one: a purpose id in `seeding.py` + its `tiered_resources.TIERED_PURPOSE` entry (append-only). Access, gating and district placement need nothing | `tests/test_resource_tiers.py` runs over the registry; a golden re-baseline (`tests/test_mapgen_golden.py`, `test_rng.py`'s frozen world) with the field-by-field diff in the CHANGELOG |
| an **effect kind** | — | one parser in `effects.py` + exactly one consumer named in `CONSUMERS` (`amenity`, v0.9.0 Q2: `game/amenities.py effect_supply`; `regional_yield`, v0.9.0 Q4: `game/yields.py _regional_tenths`, a building of scope player only; `movement_delta`, v0.9.0 Q5: `Unit.get_max_movement`, player scope only); a `tests/test_effects.py` case showing the kind moves its consumer and nothing else | that test is the rule: "each kind has exactly one consumer" |

Every build path reads `game/availability.py` (`player_can_build`,
`city_can_build_building`) and `City.can_produce_unit` — the build mask,
`produce_*`, `purchase`, `can_place_district`,
`can_player_build_improvement_at`, `upgrade_unit`. A new precondition goes
into the predicate, never into one caller (the mask invariant: a mask must
never offer an action that cannot change the state).

## 3. Changing combat numbers: the oracle

Before touching `[combat]`, `combat_class`, or `get_combat_strength` /
`get_ranged_strength`:

```
python scripts/matchup_matrix.py --seed 652026 --terrain flat,hills,woods --fortified --damaged \
    --units Warrior Slinger Archer Swordsman Spearman Horseman Catapult > before.txt
# change
python scripts/matchup_matrix.py <same arguments> > after.txt
diff before.txt after.txt          # identical unless the change is a declared rule change
```

`tests/test_unit_config_identity.py` pins literal per-pair strengths (both
roles, both strengths) for the pre-0.8 units; a deliberate balance change
updates those literals **in the same commit as the CHANGELOG entry that
declares the change and its measured effect**. Class-bonus rows carry
`strength = "combat" | "ranged"`: combat rows apply in both roles, ranged rows
to the shooter only (the Archer's cavalry penalty is Archer-by-name, shooter
only — that asymmetry is deliberate and tested; the naive class row changes
the Slinger–Horseman pair).

## 4. Balancing dials and what measures them

| Dial (config) | Moves | Read in `episode_stats` / the eval record |
|---|---|---|
| `[research] tech_cost_percent`, `civic_cost_percent` (75) | how far the trees get in 250 rounds (tree totals since v0.9.0 Q5: 4,915 science → 3,680 scaled; 3,550 culture → 2,659 scaled -- the naval techs and Naval Tradition added 850 and 220, to re-tune in the balancing pass) | `techs_researched`, `civics_researched` per game |
| `[game] city_score_weight`, `[game.score].*` | the turn-cap verdict | `victory`, `player_score` in `games_detail` |
| `[loyalty] bands`, `garrison`, `founded`, `captured`, `citizen_weight`, `drift_gain`, `drift_cap`, `range` | how fast cities flip | `cities_flipped_in/out`; the smoke script's lowest/mean loyalty lines |
| `[amenities] bands`, `luxury_cities`, `need_divisor`, `free_first` (v0.9.0 Q2; the loyalty column of the bands is Claude's starting values) | how unhappy cities are, how fast they grow and how much they yield, how far a luxury reaches | `amenity_surplus_mean` (int tenths of an amenity, mean city surplus per round end), `cities_unhappy_rounds` (city-rounds with surplus < 0), `luxuries_accessible`; the smoke script's end line prints all three |
| `[worker_default] access_bonus` (v0.9.0 Q2) | how eagerly the Worker default walks to a tile that grants a resource its owner lacks | `luxuries_accessible`, `improvements_built` |
| `[gold] purchase_multiplier`, `[faith] purchase_multiplier`, `upgrade_per_production`, `upgrade_base` | purchase and upgrade prices | `gold_spent_purchases`, `faith_spent_purchases`, `units_upgraded` |
| `[units.*] maintenance`, Conscription | army size the economy carries | `gold_maintenance`, `units_disbanded` |
| `[trade] range`, `duration_turns`, the two yield tables | route value | `trade_routes_established`, the smoke script's route lines |
| `[wonders] consolation_percent` (0: the pool is not sunk, so a loser keeps its production) | the cost of losing a race | `wonders_completed`, `wonder_races_lost` |
| `[improvements.*] food/production/gold/housing` | what Workers build and what tiles are worth | `improvements_built` |
| `[districts] cost_progress_factor` | district price over the game (`game_progress` = the larger tree fraction) | district placements in the smoke log |
| `[districts.Encampment] health`, `captured_health_percent` (v0.9.0 Q3) | how hard a forward wall is to breach, and how much of it a conqueror inherits | `encampment_breaches`, `encampment_strikes`; the smoke script's end line prints both |
| the three naval techs' costs (v0.9.0 Q5: the tree is 4,915 science at Civ 6 costs, +850) and `[units.Galley/Quadrireme/Caravel]` | when ships appear and what the sea is worth | `naval_units_built` (ships put on the board: trained, bought, granted); the smoke script's end line prints it |
| `[buildings.Workshop] production` and its `regional_yield` effect `range` / amount (v0.9.0 Q4), `[districts.Dam]` costs and housing/amenity columns | how much a cluster of cities around one Industrial Zone is worth, and what the river minigame (Aqueduct + Dam beside the zone) pays | `regional_production` (int tenths, summed over cities and rounds), `district_yield_production`; the smoke script's end line prints `regional_production_tenths` |

Method (CLAUDE.md "Research method"): one dial at a time; a seeded run
before and after (`scripts/smoke_random_selfplay.py --seed 4242` for a sanity
look, `scripts/evaluate.py` for a measurement); the CHANGELOG entry names
the artifact and the sample size. "Reports state only what was measured."
Nothing in the v0.8.0 block has been measured on agents yet.

## 5. Engine defaults (what #99 replaces, one for one)

All in `civulator/game/defaults.py`, each called from exactly one place in
`GameEnvironment.economy_phase`:

| Default | Rule | Agent action that replaces it |
|---|---|---|
| `default_research` / `default_civic` | cheapest available by (scaled cost, config index) | `set_research` / `set_civic` |
| `default_government` | highest tier available, config order | `set_government` |
| `default_loadout` | keep legal cards, fill empty slots with the newest unlocked card of the slot's type (runs on civic completion and government change) | `set_policies` |
| `default_trade` | idle Trader on an own centre → best-yield destination; stray Trader steps home | `establish_trade_route` + a move order |
| `default_workers` | idle Worker builds the best improvement under it (ties: the one that grants the tile's resource, v0.9.0 Q2), else steps toward the nearest improvable owned tile (a build that grants a resource its owner lacks counts `access_bonus` tiles nearer) | an improvement order (the (option, tile) action space) |
| — | purchase, upgrade, district and wonder placement have **no** default | `purchase`, `upgrade_unit`, `place_district` |

Both movement defaults share `defaults.step_toward` (one `Unit.move` step,
strictly nearer, ties by coordinates, never `path_finder`). Defaults never
draw from the engine RNG and never iterate a set; two same-seed games are
identical with or without them (`tests/test_determinism.py`,
`test_worker_default.py`'s hash-seed subprocess test).

## 6. Turn order (where a new per-turn rule goes)

`Player.start_turn`: exploration → units reset/heal → cities (`process_turn`:
repair → food → growth → yields → production) → `GameEnvironment.
economy_phase` (maintenance → bankruptcy → research → civics → government
and loadout defaults → route expiry → Trader default → spent Workers removed
→ Worker default) →
city ranged strikes (per city: the centre, then each fortified district,
v0.9.0 Q3; a fortified district's repair sits in `process_turn`'s repair
step, after the city's) → queued units. Round end in `next_turn`: `_border_phase`
→ `_loyalty_phase` → `_update_done` (the one end-of-game check, through
`victory.game_over`) → `turn_counter += 1`. A rule that must not depend on
turn order is a round-end phase computed from phase-start state in city-id
order; everything else is a step in the economy phase, in its stated place.
`City.set_owner` is the one place a city changes hands (`_capture_city` and
`_flip_city` are its callers): anything that must happen on a change of
hands goes there.

## 7. Before you merge

- Full suite green (`python -m pytest tests -q`; `tests/test_mapgen_earthlike.py`
  separately if the process aborts; #122 is a known flake).
- A seeded smoke run runs clean (`scripts/smoke_random_selfplay.py --seed 4242`).
- CHANGELOG paragraph under the current version entry: the rule, its
  source, "effect NOT yet measured" until it is.
- CLAUDE.md row amended if a seam changed; never list instances in a row.
- Tests assert properties over registries, never a set, count or order of
  content; a failing pre-existing test is a finding, never a target.
