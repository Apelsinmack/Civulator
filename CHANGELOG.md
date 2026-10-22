# Civulator Changelog

Each entry documents what changed, why, and the measured effect.
Training results (plots, win histories) are in `stats/`.

---

## v0.9.0 — Unreleased

### Engine RNG: PCG32 -> philox32 (#128, patch Q0)

**Opens the 0.9 rules epoch. Not a bug fix, effect NOT yet measured.**
`PortableRNG` (PCG32, #33) was already integer arithmetic and already
machine-independent; the cross-machine divergence remembered from #44 was
closed as a record error (the skip schedule was bit-identical across
machines). Nothing gets better here except ownership: Erik's simulation
projects now share one deterministic generator, the `philox32` kit
(Philox-4x32-10, gated on Random123's known-answer vectors, bit-identical
C++/CUDA/Python), so a fix to the kit reaches every consumer and a future C++
or CUDA subsystem draws the same words from `philox32.h` without a port.
Design: `docs/rng_philox_migration.md`.

- **`PhiloxRNG`** (`civulator/rng.py`) replaces the PCG32 class behind the same
  method set; `PortableRNG` stays as an alias for one release, then goes
  (with its own line here). Stream: `key = (seed_lo, seed_hi)`, `counter =
  (block, 0, STREAM_SALT, 0)`, four buffered words per block; the module
  docstring is the contract a C++ twin implements. `randint` is now the kit's
  multiply-shift (`philox32_below`), one word per call, no modulo. `random`,
  `uniform`, `shuffle`, `choices` and `next_uint64` keep their rules.
- **Dependency:** `philox32` pinned to commit `6c33a3d` in a new
  `requirements.txt` (the kit has no tags yet; the pin becomes `v0.1.0`).
  `build_manifest` records `rng = {"kind": "philox32", "version": ...}` beside
  the game version in every artifact (additive; no loader requires it).
- **Epoch consequences (by design).** Every seeded world, damage roll and
  shuffle changes. Game version 0.9.0, so `check_version` refuses 0.8
  scenarios and recordings (a 0.8 recording re-simulated under the new stream
  diverges). `tests/fixtures/scenario_fixture.json` is regenerated. The #39
  episode-seed skip set and every pre-0.9 number in `stats/` are not
  comparable to anything measured under 0.9 (#78 convention; epoch line in
  `weights/trained/manifest.md`).
- **Goldens.** The MapData ceremony SHA
  (`tests/test_mapgen_golden.py`) did **not** move
  (`c1789b41...01d5f5`): it calls `generate(42, ...)` directly and never
  touches the engine RNG, so the generator's output is unchanged. The world a
  seeded `reset(seed=42)` builds *does* change (its master seed is now
  `PhiloxRNG(42).next_uint64() = 2089907835372453007`); the engine-level
  vector in `tests/test_rng.py::test_engine_world_is_frozen_across_versions`
  and the derived-draw vectors are regenerated and frozen again.
  **Inspection by Erik: pending** (renders of the Standard 48x24, 6-player
  world for the new engine seed 42 and of the unchanged ceremony world were
  made for it; not committed).
- **Effect NOT yet measured:** no agent was trained or evaluated, and no claim
  is made about play.

### Resource tiers: strategic and luxury (#128, patch Q1)

**Rule change, effect NOT yet measured.** Source:
`docs/districts_religion_design.md` §2, rulings R2 and R10 (C1, C2), and its
"v2 fixes" B1-B3 and non-blocking list. No version bump: Q0 opened 0.9.0.

- **Twelve new resources** under `[terrain.resource.*]`: strategic Horses,
  Iron, Niter; luxury Wine, Silk, Dyes, Cotton, Salt, Silver, Furs, Pearls,
  Whales, placed exactly as design §2.1. New columns, read only by
  `terrain_model` and refused at load when unknown or dangling: `improved_by`
  (the improvements that grant access; Niter is Mine only, so a Farm on Niter
  never grants it), `reveals` (a tech, informational -- the engine never
  hides state), `frequency` (the tiered stage's weight). A resource may not be
  named like a class. **Yields: 0** for all twelve -- the source rule is "Civ 6
  GS where the digest has them", and `docs/civ6_progression_reference.md`
  lists no resource tile yields; the Civ 6 values are recorded in the
  config comment, not modelled.
- **`matches` accepts a class** (`resources = ["strategic"]` matches every
  strategic resource, B1) -- what the Industrial Zone's strategic row (Q4)
  needs. The Harbor's existing `resources = ["any"]` row now also counts
  Pearls and Whales.
- **Access** (`civulator/game/resources.py player_has_access`): the player
  owns a tile with the resource that holds one of its `improved_by`
  improvements, a district or wonder, or is a city centre. Boolean, never a
  stockpile (C1).
- **Units gated** (`[units.*] requires_resource`): Horseman and Knight need
  Horses, Swordsman and Man-At-Arms Iron, Musketman Niter. **Declared rule
  change for two pre-0.8 units, the Swordsman and the Horseman.** The gate is
  the third clause of `availability.player_can_build`, so the build mask,
  `produce_unit`, `purchase` and `upgrade_unit` refuse alike. It is honoured
  only on a world that carries strategic resources
  (`resources.world_has_class`): **the basic generator's worlds and the
  matchup board keep the pre-0.9 roster** (declared). A unit already in
  production when access is lost completes. Combat strengths are untouched
  (the oracle does not move).
- **Districts on resources (R2 generalised, §2.3):** a district or wonder may
  stand on any resource (was: bonus only). A bonus resource is removed as
  before; a strategic or luxury one stays and the district is its access --
  "discovered" never enters the engine. When clearing the tile's feature would
  leave the kept resource on terrain its `on` refuses (Dyes or Furs on Woods
  hills), the feature stays.
- **World generation:** a third sequential mapgen stage,
  `mapgen/tiered_resources.py place_tiered_resources`, runs after
  `generate_starts` (which now also returns its regions, additively) over the
  start regions in start order, ranked by `tile_roll01` under
  `STAGE_TIERED_RESOURCES` (id 12) and its purpose ids, total sort keys,
  never overwriting a resource. Luxuries: two tiles of one type per region,
  types differing between regions where possible, never in a founding ring.
  **Fairness rule** (Claude's call, design §2.4): every region reaches at
  least one Horses and one Iron within distance 3 of a settleable tile of the
  region; a world where that cannot hold raises `StartPlacementError` (the
  existing reset policy: seeded raises, unseeded resamples). Measured while
  building it: 0 fairness failures on 200 Duel, 40 4-player and 40
  Standard 6-player seeds. Niter has no guarantee: it comes from the extra
  pool (2 strategic tiles per 100 land tiles, split 1:1:2 by `frequency`).
  The stage's six knobs are `[map.earthlike] tiered_*`, mirrored in
  `earthlike.DEFAULT_PARAMS` and recorded in `MapData.params`. **The `basic`
  generator does not run the stage** (declared).
- **Golden re-baseline, field-by-field proof.** The ceremony world (Standard
  48x24, seed 42, 6 players) was generated before and after: `base_terrain`,
  `relief`, `feature`, `rivers` (edges, flux, junctions), `fresh_water` and
  `starts` are byte-identical; no pre-existing resource tile changed; only
  `resource` (new tiles only) and `params` (the six `tiered_*` keys added,
  every old key equal) differ. The same held on Duel seeds 1-20. New
  resources on the ceremony world: Horses 9, Iron 8, Niter 5, and two each
  of Cotton, Dyes, Pearls, Salt, Whales, Wine (six regions, six luxury
  types). SHA `c1789b41...01d5f5` -> `b674a660...6b07c3`. The engine-level
  Duel world (`test_rng.py::test_engine_world_is_frozen_across_versions`)
  moved the same way: 5 -> 15 resources, terrain, starts and rivers
  unchanged; re-frozen. The seeded-Duel reset digest in
  `tests/test_territory.py` moved too and was re-baselined: with the tiered
  names stripped it equals the Q0 value exactly. Three content-coupled tests
  were updated: the district-config "unknown resource" probe used "Iron"
  (now real), the P4 resource-count band now counts the bonus tier it was
  tuned for, and a test pinning the exact set of eight bonus resources was
  rewritten as a property. **Inspection by Erik: pending.**
- **Stats:** `episode_stats` gains `luxuries_accessible` (distinct luxuries a
  player has access to, the max over round ends) and `units_refused_resource`
  (refusals by the resource clause -- every predicate evaluation counts, so
  it is a pressure indicator, not a decision count); the smoke script's end
  line prints both. **Luxuries have no consumer yet** -- amenities are Q2.
- **Effect NOT yet measured:** nothing was trained or evaluated.

### Amenities and the Entertainment Complex (#128, patch Q2)

**Rule change, effect NOT yet measured.** Source:
`docs/districts_religion_design.md` §3 and its "v2/v3 fixes" (L7: greedy
luxury assignment). No version bump: Q0 opened 0.9.0.

- **The mechanic** (`civulator/game/amenities.py`, the only interpreter of the
  new `[amenities]` table and the only happiness computation): a city needs
  `ceil(population / need_divisor) - free_first` amenities (Civ 6 GS: one per
  two citizens rounded up, so a size-1 city needs 1; `free_first = 0`) and has
  the `amenity` columns of its buildings and complete districts, the `amenity`
  effects in force for it, and its share of the player's luxuries. The surplus
  picks a band row of `[amenities] bands` = `[min surplus, yield %, growth %,
  loyalty / round]`. **Yield and growth percents are Civ 6 GS's** (Ecstatic
  +20 %, Happy +10 %, Content 0, Displeased -10 % yields / -15 % growth, Unhappy
  -20 % / -30 %, Unrest -30 %, Revolt -40 %; the growth column is 100 minus
  Civ 6's penalty). **The loyalty column is Claude's starting values** (Civ 6
  spawns rebels at Unrest; we have no barbarians, so the loyalty column
  replaces them, and Rise and Fall's amenity-to-loyalty values are not in the
  digest) -- a dial for Erik. The default table is design §3.1's, verbatim.
- **Consumers**, one each, in this order: `city_yield` scales science,
  culture, gold and faith by `(100 + yield %) / 100` **after** the loyalty
  percent, each step an integer floor in tenths, never food; production gets
  the same factor in `City.calculate_production`, beside its loyalty percent
  (not in `city_yield`); `City.growth_bucket_gain` multiplies the bucket by
  `growth % / 100` (floor once, at the end); `loyalty.loyalty_delta` adds the
  band's loyalty column. **Consequence, by the rule: a city short of amenities
  is penalised from the start** -- with `free_first = 0` every size-1 city
  without a Palace needs 1 and has 0 (surplus -1: yields -10 %, growth 85 %,
  loyalty -1 per round) until a source or a luxury covers it.
- **Luxuries** (L7): every distinct luxury the player has access to (two Wine
  are one Wine) gives +1 amenity to up to `luxury_cities` (4) of its cities,
  assigned greedily -- luxuries in config order, each to the cities with the
  largest *current* deficit counting luxuries already assigned, ties by city
  id -- computed for the whole player in one call and cached nowhere.
- **New column and effect kind.** `amenity` (whole points) on `[buildings.*]`
  and `[districts.*]`: Palace 1, Entertainment Complex 1, Alhambra 2 (GS), and
  the **new building Arena** (150 production, maintenance 1, Games and
  Recreation, needs a complete Entertainment Complex, `amenity` 2, culture 1;
  appended to `BUILD_OPTIONS`, so the build head is one channel wider and
  archived heads stay evaluable at their own width). New effect kind `amenity`
  `{ amount, range, min_districts, requires_garrison }`, parsed like the
  `loyalty` kind (including its reach rule), one consumer
  (`amenities.effect_supply`). Carriers: Colosseum (+2 amenity and its existing
  +2 loyalty, both `range = 6` from its city, owner's cities only), Classical
  Republic (+1 in a city with a specialty district), and the new policy
  **Retainers** (military, Civil Service: +1 in a garrisoned city, reading
  `loyalty.is_garrisoned`). Zen Meditation is Q8's.
- **Engine-default change (declared; defaults are placeholders for #99).**
  Tiered resources yield 0, so the Worker default ranked by yield alone never
  chose the improvement that grants a luxury. Now: among improvements of equal
  gain the one in the tile's resource's `improved_by` ranks higher (order:
  gain, grants-the-resource, config order); and `defaults.worker_target` counts
  a build that would grant a resource its player has no access to as
  `[worker_default] access_bonus` (1) tiles nearer (order: distance minus
  bonus, bigger bonus, row, column). The scalar lives in its own
  `[worker_default]` table rather than under `[improvements]`, whose keys are
  all improvement names (several readers and tests iterate them). A pre-Q2
  game's Workers may therefore build a different improvement on a resource
  tile; no test pinned one.
- **Stats.** `episode_stats` gains `amenity_surplus_mean` (mean city surplus at
  each round end, then the mean over rounds, in **int tenths of an amenity**,
  floored) and `cities_unhappy_rounds` (city-rounds with surplus below 0);
  the smoke script's end line prints both beside `luxuries_accessible`.
- **Tests un-coupled by this rule** (declared): with the configured bands a
  size-1 city without a Palace is 10 % short, so tests that pin other rules'
  exact arithmetic (`test_yields`, `test_loyalty`, `test_effects` at module
  level; one test each in `test_civics`, `test_culture`,
  `test_improvement_yields`, `test_wonders`) now use the `neutral_amenities`
  fixture (`tests/conftest.py`: one band row, no change). `tests/test_amenities.py`
  pins the rule itself.
- **Effect NOT yet measured:** nothing was trained or evaluated; the bands'
  loyalty column and the order of the two percents are starting values.

---

## v0.8.1 — Erik's rulings on the block's open calls; build charges (2026-10-22)

**Rule changes, effects NOT yet measured** (#126; the open calls of #116).
Nothing has been trained or evaluated under 0.8 rules, so no comparison is
broken; the major.minor version gate is unchanged.

- **Domination is off by default, on every map size.** New switch `[game]
  domination_victory = false` (required boolean; `victory.DOMINATION_ENABLED`).
  Losing the capital no longer loses the game; with the switch off, games end
  by elimination or at the turn cap. Domination itself (#116 P9) is unchanged
  and returns with `true`. Why (Erik): a player should lose when nothing is
  left, and a Duel ended at the first capital capture cuts training games
  short.
- **A player is eliminated only with no city and no Settler left**
  (`Player.has_lost`, read at the end of the player's turn). Before: a player
  with no city died at the end of its turn even with a Settler alive.
- **One improvement per tile; a build replaces what stands there**
  (`GameEnvironment.build_improvement`). Before, the engine let different
  improvements stack and only the Worker default kept one per tile. Any
  replacement is allowed -- a Farm laid on iron before Mining can become a
  Mine. The Worker default (`improvements.best_improvement`) now revisits an
  improved tile when a better improvement than the one there becomes
  available (rank: `improvement_gain`, then config order, a total order, so
  two equal improvements never replace each other back and forth). Housing's
  "a tile adds only its largest improvement housing" (#88) is moot for game
  builds now; it still holds for painted tiles.
- **Build charges (#127).** A Worker has 3 build charges (`[units.Worker]
  build_charges`, Civ 6 Builder); every build spends one, a replacement
  included, and the Worker is removed after its last. Two new effect kinds
  add charges: `build_charges_trained` (fixed when the Worker is made --
  trained, bought or granted) and `build_charges` (live, every Worker of the
  player, existing and future, while the source is in force; a Worker left at
  0 when the source is lost is removed in its owner's economy phase, before
  the Worker default).
- **Serfdom**, a new Economic card (Feudalism): Workers made while it is
  slotted get +2 charges (Civ 6: newly trained Builders gain 2 extra build
  actions; never obsolete here, since Civil Engineering is not in our tree).
- **Pyramids** take their Civ 6 effect: one free Worker (was three, which made
  up for the missing charges) and +1 charge for every Worker of the owner
  while it holds the wonder. With Serfdom too, a new Worker builds 6 times.

---

## v0.8.0 — Progression: science, civics, gold, faith, wonders, loyalty, winning (2026-10-21)

**New rules epoch (#116).** The progression block gives cities science,
gold and faith beside food, production and culture, and builds on them the
tech and civics trees, governments and policies, new units and buildings,
gold upkeep and trade, wonders, loyalty, Workers that improve tiles by
default, and two new ways to end a game (domination, and a turn-cap score
with more terms than cities and units). **Results trained or evaluated under
0.7.x rules are not comparable to 0.8 results** (epoch marker in
`weights/trained/manifest.md`; the #78 convention: a win rate is comparable
only within a rules epoch). Archived 0.6 and 0.7 weights stay loadable and
playable (the build head at its own saved width, #67) but play 0.8 rules;
`scripts/evaluate.py` now records the engine's `game_version` and each
side's weights' `weights_game_version` beside it. The block landed in nine
patches: P1 yields and pools, P2 the tech tree, P3 units, P4 civics, P5
gold, P6 wonders, P7 loyalty, P8 Workers, P9 winning and this release. The
version was bumped in the first, so that no artifact saved under 0.8 rules
carries a 0.7 manifest, and each section below states the rules as the block
ends: where a later patch changed a rule an earlier section describes, the
earlier section says so ("P9:" ...). Design: `docs/progression_design.md`
(v2; its "Implementation notes (P1–P9)" section lists every place the code
differs from it); Civ 6 facts: the Civilization Wiki, digested in
`docs/civ6_progression_reference.md`. Everything below is a **rule change**,
not a refactor.

**What the block contains at release:** 22 techs, 19 civics, 6 governments,
26 policy cards, 18 unit types, 16 buildings, 10 districts, 12 wonders, 31
build options (`BUILD_OPTIONS`, append-only: an archived head keeps its width).

**Nothing in it has been measured on agents.** No network has been trained
or evaluated under 0.8 rules, so no section claims an effect on play. The one
whole-game observation is a smoke run, **one seeded random-play game, not a
measurement**: `python scripts/smoke_random_selfplay.py --seed 4242 --rounds
250` (duel; both seats draw random valid actions; the engine defaults do the
rest) ended at round 250 with techs researched 15 and 17, civics 13 and 13,
wonders completed 1 and 3 (seat 0 lost one wonder race), trade routes opened
0 and 0, loyalty flips 0, improvements built 6 and 6, and the verdict seat 1
by score (93 to 113, no Palace changed hands). It says the defaults run
together; it says nothing about balance.

### Yields and pools (#116 P1)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§2.1–§2.2 and "v2 fixes". Civ 6 values: `docs/civ6_progression_reference.md`
§7 (Palace, Granary) and the Science (Civ6) wiki page (per-citizen science).

- **One yield computation.** `city_yield(city, name)` (`game/yields.py`) is
  the only computation of a city's science, culture, gold and faith (integer
  tenths) and of its food and production (whole points). Terms:
  `[<name>] base + per_pop * population` for the four pool yields, or the
  centre plus the worked tiles for food and production; the `<name>` column
  of each building; the `<name>` column of each complete district; and
  10 × the adjacency score of the complete districts that yield `<name>`.
  `culture(city)` is now an alias of it, and `City.calculate_food` /
  `calculate_production` read it (production keeps its floor of 1).
  Loyalty scaling (P7), effects (P4) and trade routes (P5) were stubs
  returning 100 %, 0 and 0 in this patch; each is live from its own patch.
- **New per-city tables** `[science] base = 0, per_pop = 0.5` (Civ 6: each
  citizen +0.5 science), `[gold] base = 0, per_pop = 0`, `[faith] base = 0,
  per_pop = 0`; `[culture]` is unchanged (1.0, 0.3). Each table must hold
  exactly `base` and `per_pop`, or loading raises.
- **The Palace yields** +2 science, +5 gold and +2 production per turn in the
  city holding it (Civ 6). Its Civ 6 +1 culture is not added: every city
  keeps v0.7's culture base of 1 instead (design §0.3).
- **The Granary yields +1 food** per turn (Civ 6), beside its housing 2.
- **District adjacency is consumed.** A complete district's adjacency score
  now reaches its yield: Theater Square → culture (into `culture()`, so into
  the border pool and the civic pool), Industrial Zone → production (into
  `calculate_production`), Campus → science, Holy Site → faith, Commercial
  Hub and Harbor → gold (into the pools). This closes the #86 accepted gap
  "a complete Theater Square or Industrial Zone produces no culture or
  production in play". A placed, unfinished district still yields nothing.
  District tables may also declare flat `science`, `culture`, `gold`,
  `faith`, `food` and `production` columns (none does yet), and
  `district_yields(city, percent_by_district)` takes per-district percent
  raises, floored per district (for P4's policy cards; nothing passes one
  yet).
- **Four player pools**, all integer tenths: `Player.science`,
  `Player.culture` (unchanged), `Player.gold` (the treasury) and the new
  `Player.faith`. The culture phase of `City.process_turn` is now the
  **yield phase**: after growth and before production, once per city per
  round (the existing round stamp, so a city captured mid-round still
  accrues once), it adds all four yields to the owner's pools. Only culture
  is spent so far (border growth, #87); science waits for the tech tree
  (P2), culture's civic pool for civics (P4), gold and faith for upkeep and
  purchases (P5).
- **Episode stats**: new per-player `science_produced`, `gold_produced`,
  `faith_produced` (int tenths) beside `culture_produced`;
  `district_yield_<name>` stays the raw, unscaled adjacency score.
- **Engine.** `Player.reset_state()` holds every per-episode Player field
  and is called by the constructor and by `reset` when it keeps its players,
  in place of a field-by-field list; it declares the later patches'
  placeholders `techs` and `civics` (lists, replacing the unused
  `technologies`), `current_tech`, `current_civic`, `government`,
  `policies` and `routes`. `GameEnvironment.complete_district` is now the
  one place a district finishes (P6 hangs wonder effects there).
- **Version 0.8.0** (`civulator.__version__`). The version gate
  (`meta.check_version`) now refuses 0.7 scenario and recording manifests
  unless `override=True`; `tests/fixtures/scenario_fixture.json` was
  regenerated with `scripts/make_fixture_scenario.py`.

**What agents see.** No encoder channel reads a pool or a yield (#99,
#111). The build agent's turns-to-complete channels read
`calculate_production`, so archived weights get different inputs for a
capital (+2 production) and for a city with a complete Industrial Zone.

**Accepted gaps.** Science, gold and faith accumulate without a consumer
until P2 and P5; nothing passes `percent_by_district` until P4.

### The tech tree (#116 P2)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§4, §6.2–§6.3, §13 and "v2 fixes". Civ 6 facts:
`docs/civ6_progression_reference.md` §1 (techs) and §7 (buildings); the
improvement yields from the Civilization Wiki pages Farm, Mine, Quarry,
Pasture, Camp, Plantation and Fishing Boats (Civ6), read through the
MediaWiki API.

- **A tech tree.** 22 techs from Pottery to Gunpowder in `[techs.*]`, with
  Civ 6's names, eras and Gathering Storm costs (Education and Military
  Engineering 335, the per-tech pages' value) and this design's
  prerequisites where a cut tech sat in between (design §4.2). Every tech
  costs `cost * [research] tech_cost_percent // 100` whole science, 75 %
  (design §12). The table sums to 4,065 science at Civ 6 cost, 3,043 at
  75 % (design §4.2 states 4,015, an arithmetic slip). Four techs are
  available at the start. `civulator/research_model.py` is the only
  interpreter; it raises at load on an unknown key, a bad cost or era, a
  prerequisite naming nothing, and a cyclic or unreachable graph.
- **Research.** A player's science pool (tenths, P1) pays for one current
  tech. Each own turn, after every city has accrued, the new **economy
  phase** resolves it: with no current tech the engine picks the cheapest
  available one, by scaled cost and then config order (design §13; no agent
  chooses research until #99); when the pool holds 10 × the scaled cost the
  tech completes, exactly that is paid and the overflow stays. At most one
  tech completes per turn (Civ 6). `GameEnvironment.set_research(player,
  tech)` chooses one, refused unless every prerequisite is known and the
  tech is not; switching keeps the pool (one number, not per-tech
  progress). New per-player stat `techs_researched`.
- **Gates.** What a city may build depends on what its owner has
  researched: a `requires_tech` column on the item's own table, checked by
  `player_can_build` (`game/availability.py`) on every build path — the
  build mask, `City.produce_unit` / `produce_building` (both now refuse,
  returning False), `can_place_district`, and the new
  `GameEnvironment.can_player_build_improvement_at` that Worker builds go
  through. **No longer buildable from turn 1:** Archer (Archery), Spearman
  (Bronze Working), Horseman (Horseback Riding), Swordsman (Iron Working;
  #67 had admitted it ungated), Catapult (Engineering), Granary (Pottery)
  and Walls (Masonry). The opening web is Warrior, Slinger and Settler
  (and, from P8, the Worker, which needs no tech but is offered only while
  there is a tile for it to improve).
  Battering Ram (Masonry) and Siege Tower (Machinery) carry their gates and
  stay deferred (#66). Districts: Campus (Writing), Holy Site (Astrology),
  Encampment (Bronze Working), Commercial Hub (Currency), Harbor (Celestial
  Navigation), Aqueduct (Engineering), Industrial Zone (Apprenticeship);
  Theater Square, Entertainment Complex and Government Plaza stay ungated
  until their civics (P4). Improvements: Mine and Quarry (Mining), Pasture
  and Camp (Animal Husbandry), Plantation (Irrigation), Fishing Boats
  (Celestial Navigation; Civ 6: Sailing, cut); the Farm is ungated. An
  improvement may now be built only on a tile one of the builder's cities
  owns. Captured cities keep whatever they hold, and an item in production
  that the new owner could not start still completes (design "v2 fixes":
  it was paid for).
- **Buildings.** A building may require a complete district of a type in
  its city (`requires_district`) and a building the city owns
  (`requires_building`), checked with the tech by one predicate,
  `city_can_build_building`. New, with Civ 6's costs and yields: Library
  (90; Writing; Campus; +2 science), University (250; Education; Campus
  and Library; +4 science, +1 housing), Shrine (70; Astrology; Holy Site;
  +2 faith), Barracks (90; Bronze Working; Encampment; +1 production, +1
  housing) and Medieval Walls (220; Castles; Walls; +30 defence, 60 with
  the Walls). The **Workshop** takes Civ 6's cost and yield: 195
  production (was 120), +3 production, Apprenticeship and an Industrial
  Zone (it was unbuildable and inert). The **Monument** (50, culture 2)
  becomes buildable: it had a cost and no build option (closes #73's gap).
  `maintenance` (gold per turn: Workshop, Library, Shrine, Barracks 1;
  University 2; Campus, Theater Square, Holy Site, Industrial Zone,
  Encampment, Entertainment Complex 1) is parsed and stored in tenths;
  nothing is deducted until P5.
- **Removed.** `[buildings.Factory]` (Industrialization, beyond the tree;
  it was inert) and `[improvements."Oil Well"]` (no tech in this span
  unlocks it).
- **District costs escalate.** `game_progress(player)` is now (techs known,
  techs in the tree), so the #86 hook is live: a district placed with k of
  the 22 techs known costs `base * (22 + 9k) // 22`, from 54 with none to
  540 with the whole tree (Civ 6's curve); `fixed` districts never scale,
  and the cost stays locked at placement.
- **Improved tiles yield more.** `[improvements.*]` declares `food`,
  `production` and `gold` in whole points, the Civ 6 GS base yields: Farm
  +1 food; Mine, Quarry, Pasture +1 production; Camp +2 gold (the wiki: +1,
  GS +2); Plantation +2 gold; Fishing Boats +1 food. (The design's
  provisional Camp and Plantation values were +1 gold; the wiki says +2.)
  Food and production enter `Tile.yields` — so the tiles a city chooses to
  work, its food and production, border-claim ranking and the terrain
  encoder channels — and gold enters `city_yield(city, "gold")` over the
  centre and the worked tiles. Building an improvement bumps the terrain
  epoch, as does a district clearing one. Later-tech bonuses (Apprenticeship
  on Mines, Feudalism on Farms, …) are not modelled.
- **Build options** appended, the #67 append-only contract: Monument,
  Library, University, Shrine, Barracks, Medieval Walls, Workshop.
- **Engine.** `Player.start_turn`: exploration → units → cities → economy
  phase (research; P4 and P5 add their steps inside it) → city ranged
  strike → queued units. Engine defaults live in `game/defaults.py`. Load
  order: `research_model` first, then `unit_model`, `terrain_model` and
  `district_model`, each validating its own gating columns (a
  `requires_tech` / `requires_district` / `requires_building` naming
  nothing raises); unknown keys in `[units.*]`, `[buildings.*]` and
  `[improvements.*]` now raise. The smoke script draws production from the
  build mask and logs techs researched; one seeded run (`python
  scripts/smoke_random_selfplay.py --seed 4242`, duel, 250 rounds, random
  valid actions, 1 game) researched 15 and 16 techs.

**What agents see.** No encoder channel reads techs or research (#99,
#111). The build mask hides unresearched options, so an archived build head
(10 options, loaded at its own width) can choose only Warrior, Slinger and
Settler until its owner's research opens the rest. At full width the build
state has 7 more turns-to-complete channels. The terrain-aware encoders'
tile-yield channels include improvement yields.

**Accepted gaps.** `requires_civic` and `requires_government_tier` are
parsed and pass until P4. Maintenance is stored, not paid, until P5.
Workers stay deferred until P8, so tech-gated improvements, and their
yields, appear in play only once P8 gives Workers a default.

### Units, combat classes and upgrades (#116 P3)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§6.1–§6.4 and "v2 fixes" ("Combat classes and the bit-identity gate",
"Upgrades and bankruptcy"). Civ 6 facts: `docs/civ6_progression_reference.md`
§6 (unit stats), §8.3 (maintenance) and §8.5 (upgrades); the Gathering Storm
values where the wiki splits them (Pikeman 180, Knight 220).

- **Every unit has a combat class and an era.** `combat_class` and `era` are
  required columns of every `[units.*]` table, read by `civulator/unit_model.py`
  (`COMBAT_CLASS`, `UNIT_ERA`): Warrior melee (Ancient); Slinger and Archer
  ranged (Ancient); Spearman anti-cavalry (Ancient); Horseman light cavalry
  (Classical); Swordsman melee (Classical); Catapult siege (Classical);
  Battering Ram support (Ancient); Siege Tower support (Classical); Settler
  and Worker civilian (Ancient). The boolean `siege_class` is gone (it now
  raises as an unknown key): `SIEGE_CLASS` is the set of units whose class is
  `siege` (the Catapult, and now the Trebuchet).
- **Class bonuses are a table.** `[combat] class_bonuses` replaces the three
  name-keyed constants `anti_cavalry_bonus`, `melee_vs_spearman_bonus` and
  `archer_vs_horseman_penalty`. A row is `{ unit, target, amount, strength }`:
  `unit` and `target` name a class or a single unit type (a row matches a unit
  by its name or its class), `amount` is an int, `strength` is `"combat"` or
  `"ranged"`. `Unit.get_combat_strength` reads the combat rows in BOTH roles,
  as today's +10 and +5 are applied (#63); `Unit.get_ranged_strength` reads
  the ranged rows for the shooter only. Today's three rules are three rows,
  written as `unit.py` applied them: anti-cavalry +10 vs light cavalry, melee
  +5 vs anti-cavalry, and the archer penalty -5 vs light cavalry as a ranged
  row for the unit named `Archer` (it is the shooter's alone and the Slinger,
  a ranged unit by class, has never had it). New rows: anti-cavalry +10 vs
  heavy cavalry (Civ 6), Archer -5 vs heavy cavalry (the Knight is a mounted
  target of the same shooters), and **Claude's call:** the Crossbowman takes
  the archer penalty against both cavalry classes, as the Archer it replaces
  does. No combat rule names a unit or a class any more: the siege "fires
  only with a movement point left" rule, civilian capture, `is_siege_class`
  and the class bonuses all read the class registry.
- **Every existing number is bit-identical.** The oracle, run before the
  patch (at 7622a6b) and after, with one seed: `python scripts/matchup_matrix.py
  --seed 652026 --terrain flat,hills,woods --fortified --damaged --units
  Warrior Slinger Archer Swordsman Spearman Horseman Catapult` (`--units` is
  new; 200 duels per ordered pairing, five conditions, 7 × 7 pairings = 245
  cells) printed the same report and, in the machine-readable result, the
  same float to the last digit in every cell; the default six-unit run
  printed the same report as well. `tests/test_unit_config_identity.py` pins
  the gate in the repo: the combat and ranged strength of every ordered
  pairing of the seven units, both roles, as literals copied from the engine
  before the patch (the Slinger included), in place of the three constants it
  pinned, plus the ranged-vs-city strength of each. A class-keyed shortcut
  (`ranged` vs cavalry in place of the named Archer rows) fails it on the
  Slinger.
- **Six new units, a Trader, and their classes.** Civ 6 Gathering Storm
  numbers; each is a `[units.*]` table, a subclass, a slot, a movement domain
  and a build option (`BUILD_OPTIONS` appended, in this order). Man-At-Arms
  (melee, Medieval, 160 production, strength 45, movement 2, Apprenticeship,
  upkeep 3), Pikeman (anti-cavalry, Medieval, 180, 45, Military Tactics, 2),
  Crossbowman (ranged, Medieval, 180, strength 30, ranged 40, range 2,
  Machinery, 3), Knight (heavy cavalry, Medieval, 220, 50, movement 4,
  Stirrups, 4), Trebuchet (siege, Medieval, 200, strength 35, ranged 45,
  range 2, Military Engineering, 3), Musketman (melee, Renaissance, 240, 55,
  Gunpowder, 4). Existing units keep their v0.7 numbers (Horseman 35, Catapult
  23). The class bonuses reach them by class: Man-At-Arms and Musketman get
  the melee +5 against Spearman and Pikeman, the Pikeman the anti-cavalry +10,
  the Trebuchet the siege rules (full-strength bombard against cities, fires
  only with a movement point left).
- **The Trader exists but is not buildable.** A civilian (40 production,
  movement 2, slot 1, land, upkeep 0, `requires_civic = "Foreign Trade"`, kept
  raw until P4): its table, class and subclass exist so that a Trader is
  captured and not killed (civilian capture is keyed on the class), but it
  stays in `DEFERRED_BUILD_UNITS` until P5 gives it trade routes — offering it
  now would be a build option that cannot pay off (#67).
- **Upkeep and purchasability are columns.** `maintenance` (required on every
  unit; gold per turn, stored in tenths like the building column: Warrior,
  Slinger, Settler, Worker, Trader 0; Archer, Spearman, Battering Ram 1;
  Horseman, Swordsman, Catapult, Siege Tower, Pikeman 2; Man-At-Arms,
  Crossbowman, Trebuchet 3; Knight, Musketman 4 — Civ 6 GS) and `purchasable`
  (default `["gold"]`) are parsed into `UNIT_MAINTENANCE` and
  `UNIT_PURCHASABLE`. Nothing reads them until P5.
- **Upgrade chains and prices.** `upgrades_to` names the next unit: Warrior →
  Swordsman, Slinger → Archer, Archer → Crossbowman, Spearman → Pikeman,
  Horseman → Knight (Claude's call: one cavalry line; Civ 6 has the Courser),
  Swordsman → Man-At-Arms, Man-At-Arms → Musketman, Catapult → Trebuchet. A
  name that is no unit, or a chain that loops, raises at load. The price is
  `[gold] upgrade_per_production * (target production − unit production) +
  [gold] upgrade_base` whole gold, with 2 and 10: the wiki states no formula;
  this one reproduces its single data point (Slinger → Archer = 60 gold) and
  is the community's reading of the game files. Prices: Warrior → Swordsman
  110, Slinger → Archer 60, Archer → Crossbowman 250, Spearman → Pikeman 240,
  Horseman → Knight 290, Swordsman → Man-At-Arms 150, Man-At-Arms →
  Musketman 170, Catapult → Trebuchet 170. `upgrade_cost` (`game/upgrades.py`)
  has a hook for P4's `upgrade_cost_percent` effects (summed, then applied
  once, floored; 0 until then).
- **`GameEnvironment.upgrade_unit(unit)`** is refused (False, nothing
  changes) unless the unit has an `upgrades_to`, its owner may build the
  target (`player_can_build`, so the tech gate holds), it stands on a tile of
  one of its owner's cities, it has all its movement and has not acted this
  turn, and the treasury covers the price. It then replaces the unit through
  `_create_unit` at the same index of `player.units` and the same place in
  its tile's stack: health carries over, movement is spent, fortification
  resets, the unit counts as having acted, the gold is paid. New per-player
  stat `units_upgraded`. `GameEnvironment.player_owns_tile` is the one
  ownership test (the improvement rule now calls it too). Civ 6's strategic-
  resource cost of an upgrade is not modelled (there are no strategic
  resources here).
- **One registry of unit classes.** `UNIT_CLASSES` (type name → subclass)
  lives in `game/city.py` beside `_create_unit`; the matchup harness and the
  order recorder import it instead of keeping copies. **Two behaviour
  changes that are not about balance:** `_create_unit` now raises on an
  unknown type (it fell back to the bare `Unit`, which strips a shooter of its
  attack), and the recorder raises on a scenario unit of an unknown type
  (it fell back to a Warrior without a word).
- **Encoder.** `CLASS_INDEX` is derived from `combat_class` through
  `CLASS_CHANNEL` in `agents/state_encoders.py` (melee 0, anti-cavalry 1,
  ranged 2, light and heavy cavalry 3, siege 4, support and civilian none):
  it reproduces every existing unit's channel, and a new unit adds none, so no
  encoder's depth changes (a test pins the depth of every encoder that
  existed). The unit-stat channels are clamped at 1.0, because the Musketman's
  strength (55) exceeds `MAX_MELEE_STR` (50) and the Knight's (50) sits on
  it. **ACCEPTED GAP:** the constants stay, so those two units saturate the
  melee-strength channel; changing them would shift every trained network's
  inputs. #111 revisits the input space.
- **Matchup harness.** `scripts/matchup_matrix.py --units ...` measures the
  named unit types instead of the headline six (the default is unchanged), and
  refuses a unit that cannot attack.

**What agents see.** `BUILD_OPTIONS` grows by six (23 in all): at full width
the build head has six more outputs and the build state six more
turns-to-complete channels; an archived narrower head is loaded at its own
width and does not see them. The build mask offers each new unit once its
owner knows its tech. The combat network's input does not change: the new
units share the existing class channels. Nothing in the action space or the
encoders gives an agent an upgrade, a price or upkeep.

**Accepted gaps.** Upgrades have no engine default and no agent action:
`upgrade_unit` is dormant until #99, like `swap_tile`, so no unit changes type
in play yet. Maintenance and `purchasable` are stored, not used, until P5. The
upgrade-cost effect hook is 0 until P4. The Trader cannot be built until P5.
The Musketman and Knight saturate the strength channel (above).

### Civics, governments and policy cards (#116 P4)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§3, §5, §6.2 (the four buildings), §13 and "v2 fixes". Civ 6 facts:
`docs/civ6_progression_reference.md` §2 (civics), §3 (governments), §4
(policy cards) and §7 (buildings), Gathering Storm values where the wiki
splits them.

- **A civics tree.** 19 civics from Code of Laws to Guilds in `[civics.*]`,
  with Civ 6's names, eras and Gathering Storm culture costs and this
  design's prerequisites where a cut civic sat in between (Mysticism, Naval
  Tradition and the Renaissance civics are cut: Military Training requires
  only Military Tradition, Theology only Drama and Poetry; design §5.1).
  Each costs `cost * [research] civic_cost_percent // 100` whole culture,
  75 % (design §12). The table sums to 3,330 culture at Civ 6 cost, 2,494 at
  75 % (design §5.1 states 3,100, an arithmetic slip). Parsed by the techs'
  own parser (`research_model.parse_tree`): a cycle, an unreachable civic,
  an unknown prerequisite, era or key raise at load.
- **Civics develop like techs.** The culture pool (`Player.culture`, tenths;
  borders keep their own per-city pools, #87) pays for one current civic.
  Each own turn the economy phase resolves it after research: with no
  current civic the engine picks the cheapest available one, by scaled cost
  and then config order; when the pool holds 10 × the scaled cost the civic
  completes, exactly that is paid and the overflow stays; at most one civic
  per turn. `GameEnvironment.set_civic(player, civic)` chooses one (refused
  unless every prerequisite is known and the civic is not); switching keeps
  the pool. New per-player stat `civics_researched`.
- **Six governments** in `[governments.*]` (`requires_civic`, `tier`,
  `effects`), Civ 6's slots with the diplomatic slot folded into a wildcard
  slot (there are no city-states or diplomatic cards), legacy bonuses, envoys
  and favour dropped. Slots are military / economic / wildcard:
  Chiefdom (tier 0, Code of Laws) 1 / 1 / 0, no bonus; Autocracy (1,
  Political Philosophy) 1 / 1 / 2, the city holding the Palace +1 food,
  production, science, culture, gold and faith, +10 % production toward
  wonders (Civ 6 vanilla's bonus; no wonder exists until P6); Classical Republic (1, Political
  Philosophy) 0 / 2 / 2, +1 housing in every city with at least one specialty
  district; Oligarchy (1, Political Philosophy) 2 / 1 / 1, melee and
  anti-cavalry units +4 combat strength; Monarchy (2, Divine Right) 2 / 1 /
  3, +1 housing per Walls and per Medieval Walls, +50 % production toward
  both; Theocracy (2, Divine Right; Civ 6's Reformed Church is cut) 2 / 2 /
  2, land military units may be bought with faith and faith purchases cost
  15 % less (both consumed from P5). `Player.government` is None until one is
  adopted; `GameEnvironment.set_government(player, name)` adopts one whose
  civic is known, with no anarchy and no switching cost (design §5.2).
- **26 policy cards** in `[policies.*]` (`type`, `requires_civic`, optional
  `obsolete_with`, `effects`), each a rule: God King (economic, Code of Laws;
  obsolete with Theology) +1 faith and +1 gold in the city holding the
  Palace; Urban Planning (E, Code of Laws) +1 production in every city; Ilkum
  (E, Craftsmanship) +30 % production toward Workers (Civ 6: Builders;
  Workers are not a build option until P8);
  Agoge (military, Craftsmanship; obsolete with Feudalism) +50 % toward
  Ancient and Classical melee, ranged and anti-cavalry units; Caravansaries
  (E, Foreign Trade) +2 gold per trade route (P5); Maneuver (M, Military
  Tradition; obsolete with Divine Right) +50 % toward Ancient and Classical
  light and heavy cavalry; Conscription (M, State Workforce) unit upkeep −1
  per unit (P5); Corvee (E, State Workforce; obsolete with Divine Right)
  +15 % toward wonders (P6; see the gaps); Colonization (E, Early Empire)
  +50 % toward Settlers; Limitanei (M, Early Empire) +2 loyalty in a
  garrisoned city (P7); Insulae (E, Games and Recreation; obsolete with
  Medieval Faires) +1 housing in a city with at least two specialty
  districts; Veterancy (M, Military Training) +30 % toward Encampment and
  Harbor districts and the buildings that require them; Scripture (E,
  Theology) +100 % Holy Site adjacency; Bastions (M, Defensive Tactics) +6
  city defence and +5 city ranged strength; Limes (M, Defensive Tactics)
  +100 % toward Walls and Medieval Walls; Natural Philosophy (E, Recorded
  History) +100 % Campus adjacency; Feudal Contract (M, Feudalism) +50 %
  toward melee, ranged and anti-cavalry units of every era here; Meritocracy
  (E, Civil Service; the Civ 6 vanilla card) +1 culture per specialty
  district in every city; Professional Army (M, Mercenaries) −50 % upgrade
  gold; Trade Confederation (E, Mercenaries) +1 culture and +1 science per
  international route (P5); Aesthetics (E, Medieval Faires) +100 % Theater
  Square adjacency; Medina Quarter (E, Medieval Faires) +2 housing in a city
  with at least three specialty districts; Craftsmen (E, Guilds) +100 %
  Industrial Zone adjacency; Town Charters (E, Guilds) +100 % Commercial Hub
  adjacency; Chivalry (M, Divine Right) +50 % toward light and heavy
  cavalry; Gothic Architecture (E, Divine Right) +15 % toward wonders (P6).
  Dropped from Civ 6's span (design §5.3): the barbarian, naval,
  great-person, tile-purchase, builder-charge, amenity, governor, pillage,
  strategic-resource and diplomatic cards.
- **Loadouts.** `Player.policies` is the list of slotted cards. A loadout is
  legal when every card is unlocked (its civic known) and not obsolete (its
  `obsolete_with` civic unknown), no card appears twice, and the cards fit
  the slots: each card in a slot of its type or in a wildcard slot.
  `GameEnvironment.set_policies(player, names)` slots exactly a legal
  loadout and refuses anything else. A card's effects hold only while it is
  slotted and legal: an unlocked card that is not slotted, and a card that
  became obsolete, do nothing. Slots = the government's plus every other
  slot effect in force (none yet; the Alhambra and the Forbidden City in
  P6); a card can never add slots.
- **One effects interpreter.** `civulator/effects.py` is the only reader of
  `effects = [...]` lists on techs, civics, governments, policies, buildings
  and districts. The kinds are a closed set and each has exactly one
  consumer (`effects.CONSUMERS`): `city_yield` (`city_yield`; `capital_only`
  = the city holding `[city] capital_building`, the Palace;
  `per_district` = times the city's complete specialty districts),
  `production_percent` (`calculate_production`; a target names units, unit
  classes, unit eras, buildings, districts, the buildings that require a
  district, or a kind of item), `adjacency_percent` (`city_yield`, per
  district through `district_yields`), `combat_strength` (unit strength in
  both roles and in the shooter's ranged strength, by class or every unit;
  or the city's defence), `city_ranged_strength`, `upgrade_cost_percent`,
  `policy_slots`, `housing_if_districts`, `housing_with_building` (`housing`)
  and `enables` (a rule's gate) are consumed now;
  `unit_maintenance_delta`, `purchase_percent`, `faith_purchase`,
  `trade_route_capacity`, `route_yield` (P5), `growth_percent`, `free_units`,
  `free_tech`, `free_civic`, `free_population` (P6) and `loyalty` (P7) are
  validated now and read by nothing until their patch. Effects of one kind
  are summed and then applied once with one integer floor: two +50 % cards
  are +100 %, never 1.5 × 1.5. Every entry has a scope: a building's or a
  district's holds in its own city unless it says `scope = "player"`; every
  other source's holds for the player. At load, an unknown kind, attribute
  or name (unit, building, district, class, era, rule, resource), a
  `city_yield` effect on a building (a building says it with a column),
  city scope on a card, government, civic or tech, slots on a card and a
  one-shot effect off a wonder raise.
- **Flanking is a civic unlock** — #59's "gate it behind culture
  eventually", done. Military Tradition (Civ 6's civic that grants the
  flanking and support bonuses; support is not modelled) carries
  `enables = ["flanking"]`; the +2 per flanking tile (`[combat]
  flanking_bonus`, unchanged) applies to a striker only while its owner
  knows the civic. Before this patch flanking applied from turn 1; every #59
  number holds once the civic is known (`tests/test_flanking_bonus.py`).
- **Civic and government gates.** `requires_civic` is enforced on units,
  buildings and districts by `player_can_build`, and a building's
  `requires_government_tier` by `city_can_build_building` (the current
  government's tier; no government is below every tier), on every build
  path (the build mask, `produce_unit` / `produce_building`,
  `can_place_district`). **No longer available from the start:** the Theater
  Square (Drama and Poetry), the Entertainment Complex (Games and
  Recreation) and the Government Plaza (State Workforce). The Trader needs
  Foreign Trade (and stays deferred until P5).
- **Four buildings,** Civ 6's costs and yields: Temple (120 production,
  upkeep 2, +4 faith; Theology, a Holy Site and a Shrine), Amphitheater (150,
  1, +2 culture; Drama and Poetry, a Theater Square), Ancestral Hall (150,
  1; a tier-1 government, a Government Plaza; +50 % production toward
  Settlers in its city) and Grand Master's Chapel (290, 2, +5 faith; a
  tier-2 government, a Government Plaza and an Ancestral Hall; land
  military units may be bought with faith, P5). Buildings gain
  `purchasable` (default gold, consumed from P5): the Shrine and the Temple
  may be bought with gold or faith; the Walls, Medieval Walls, Palace,
  Ancestral Hall and Grand Master's Chapel never.
- **District costs escalate with civics too.** `game_progress(player)` is
  the larger of (techs known, techs) and (civics known, civics), compared by
  cross-multiplication, a tie to the tech fraction.
- **Engine defaults** (no agent chooses yet, #99; design §13 as amended by
  v2): each economy phase, after research and civics, the engine adopts the
  highest-tier government whose civic is known when it is above the current
  one (ties by config order: Chiefdom on Code of Laws, Autocracy on
  Political Philosophy, Monarchy on Divine Right), and re-fits the loadout
  whenever a civic completes or the slots change (`set_government` does it
  too, so an agent's government change keeps a legal loadout): the legal
  cards stay in their order, the newest-slotted falling out when slots
  shrink; each empty typed slot takes the newest unlocked card of its type,
  then each wildcard slot the newest of any type ("newest": unlocked by the
  later civic, then config order).
- **Engine.** `Player.civics` (completion order), `current_civic`,
  `government` and `policies` are declared in `Player.reset_state`. The
  economy phase is research → civics → government and loadout defaults
  (P5 puts maintenance and bankruptcy before research and the route steps
  after). `[city] capital_building = "Palace"` names the capital marker
  once (`create_city` grants it; `capital_only` reads it). Build options
  appended, the #67 contract: Temple, Amphitheater, Ancestral Hall, Grand
  Master's Chapel. The smoke script logs civics, governments and slotted
  cards; one seeded run (`python scripts/smoke_random_selfplay.py --seed
  4242`, duel, 250 rounds, random valid actions, 1 game) completed 13 and
  13 civics (and 16 and 18 techs); both players had adopted Chiefdom and
  slotted two cards by round 50, one player Autocracy by round 150 and both
  by round 200, and each ended under Autocracy with four cards slotted (log
  checkpoints at rounds 50, 100, 150, 200 and 250).

**What agents see.** No encoder channel reads civics, governments or cards
(#99, #111): the engine defaults drive them, and their effects reach agents
only through what they change — yields, production (the build state's
turns-to-complete channels read `calculate_production`), housing, combat
strengths and flanking. At full width the build head has four more outputs
and the build state four more channels; an archived narrower head is loaded
at its own width and does not see them.

**Accepted gaps.** No agent action chooses a civic, government or card
until #99. Corvee targeted every wonder: Civ 6 limits it to Ancient and
Classical wonders, and wonders carried no era yet (closed in P6, which gave
them one). The Grand Master's Chapel's faith purchase held in its own city
(a building's effect defaults to city scope); Civ 6 applies it empire-wide
(closed in P5: `scope = "player"`). Veterancy's Harbor buildings arrive
with the Lighthouse (P5). Governor titles, legacy cards, amenities,
the Audience Chamber and Warlord's Throne are not modelled. Every
deferred effect kind above is validated and dormant until its patch.

### Gold: maintenance, bankruptcy, purchasing, trade routes (#116 P5)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§3 (the five kinds consumed here), §6.2 (Market, Lighthouse), §7, §10.1, §13
and "v2 fixes" (turn order; flips, captures and `set_owner`; upgrades and
bankruptcy). Civ 6 facts: `docs/civ6_progression_reference.md` §7 (Market,
Lighthouse), §8 (gold), §10 (trade routes) and §13 (faith purchasing),
Gathering Storm values where the wiki splits them.

- **Upkeep is paid.** The economy phase now opens with maintenance: each own
  turn the treasury pays, in tenths, every unit's `maintenance` column (the
  Civ 6 GS values listed under P3: Warrior, Slinger, Settler, Worker, Trader
  0 up to Knight and Musketman 4), every building's (Civ 6: Library,
  Shrine, Amphitheater, Barracks, Workshop, Ancestral Hall 1; University,
  Temple, Grand Master's Chapel 2; Walls, Monument, Granary, Market,
  Lighthouse 0) and every COMPLETE district's (Civ 6: Campus, Theater
  Square, Holy Site, Industrial Zone, Encampment, Entertainment Complex 1;
  Commercial Hub, Harbor, Government Plaza, Aqueduct 0 -- the gold
  districts pay for themselves; a placed, unfinished district pays
  nothing). `unit_maintenance_delta` effects are summed into one whole-gold
  change per unit, and no unit's upkeep falls below 0 (Conscription: -1
  gold per unit, so the 1-gold units become free). New per-player stat
  `gold_maintenance` (tenths actually paid). Civ 6: maintenance is paid
  from the treasury every turn (Gold page).
- **Bankruptcy disbands units.** If the treasury is negative after upkeep,
  units are disbanded one at a time -- the highest upkeep first, the
  lowest index in `Player.units` ("oldest", creation order) among equals --
  each removed through `delete_unit`, until the treasury is >= 0 or no unit
  with upkeep is left; then the treasury is floored at 0, so it never ends
  an economy phase negative. A disbanded unit does not pay that turn's
  upkeep (its upkeep goes back to the treasury) and nothing else is
  refunded. New stat `units_disbanded`. Civ 6: "if the treasury becomes
  empty, units disband automatically until the balance is restored" (Unit
  page); which units go first is not stated, so this order is the
  design's (§7.2). Buildings and districts are never sold.
- **Purchasing.** `GameEnvironment.purchase(city, kind, name, resource)`
  lets the current player buy a unit or a building with gold or faith in
  one of its cities: the price is `production_cost * [<resource>]
  purchase_multiplier` (new keys: `[gold]` 4, `[faith]` 2 -- Civ 6: gold is
  4x production, faith 2x), scaled by the summed `purchase_percent` effects
  for that resource (Theocracy: faith -15 %), floored at 0. Refused, with
  nothing changed, unless the item lists the resource in its `purchasable`
  column (default gold; Shrine and Temple gold or faith; Walls, Medieval
  Walls, Palace and the Government Plaza buildings never -- Civ 6) or it is
  a land military unit (every unit of a fighting combat class:
  `unit_model.faith_category`) bought with faith where a `faith_purchase`
  effect unlocks the category (Theocracy, the Grand Master's Chapel); the
  city could start it (the build predicates: tech, civic, government tier,
  district, building chain; a building not already owned; the Trader rule
  below) and the pool covers it. A bought unit is placed by the same
  `complete_unit_production` as a built one (queued when the city has no
  room); a bought building is appended exactly as a built one, and if the
  city was producing it the production item is cleared (the production
  pool is kept). New stats `gold_spent_purchases`, `faith_spent_purchases`
  (tenths).
- **The Grand Master's Chapel unlocks faith purchases in every city** of
  its owner: its `faith_purchase` effect is now `scope = "player"` (Civ 6:
  empire-wide; P4 left it city-scoped and named the one-word fix).
- **Trade routes** (`civulator/game/trade.py`, the only interpreter of the
  new `[trade]` table). A Trader standing on one of its owner's city
  centres (the origin) is consumed by
  `GameEnvironment.establish_trade_route(trader, destination)` to open a
  route to any other city, of any owner, within `[trade] range = 15` hexes
  (canonical wrap distance; Civ 6's land range), when no route of this
  player already links the two cities in either direction and a route slot
  is free. Capacity (`route_capacity`) = the `trade_route_capacity` effects
  in force: the Foreign Trade civic's +1 (Civ 6), plus one per city holding
  a Market or a Lighthouse -- a city holding both still adds 1 (Civ 6, R&F
  onward), the largest building capacity per city -- plus any later
  wonder's. A route lasts `[trade] duration_turns = 21` of its owner's
  turns (Civ 6's minimum duration on Standard speed) and then ends, its
  Trader reappearing at the origin. Every turn it yields its ORIGIN, through
  `city_yield`, the `[trade.domestic]` (destination of the same owner) or
  `[trade.international]` entries of the destination's centre and of each
  of its complete specialty districts -- Civ 6's destination-district
  table: City Center 1 food 1 production / 3 gold; Campus, Holy Site,
  Theater Square 1 food / 1 science, 1 faith, 1 culture; Entertainment
  Complex 1 food / 1 food; Encampment, Industrial Zone 1 production / 1
  production; Commercial Hub, Harbor 1 production / 3 gold; Government
  Plaza 1 food 1 production / 2 gold (domestic / international) -- plus the
  `route_yield` effects in force (Caravansaries +2 gold per route, Trade
  Confederation +1 culture +1 science per international route). Food and
  production from routes are the first non-tile source of either. The
  destination's owner gets nothing (Civ 6). A name in a `[trade.*]` table
  that is no district and not "City Center" raises at load. New stat
  `trade_routes_established`.
- **Routes end when a city changes hands or is removed.** `City.set_owner`
  (every capture) and `remove_city` end every route, of any player, that
  starts or ends at the city: a player who still holds a route's origin
  gets its Trader back there; a route whose origin was the city is simply
  removed (its Trader is lost). Civ 6 cancels routes when a city becomes a
  Free City and returns Traders on war; there is no war here.
- **Queued units are back.** `Player.queued_units` holds `(city_id,
  unit_type)` entries for a unit owed but not placeable -- a purchase or a
  returning Trader in a city with no free tile; `Player.start_turn` places
  them at the end of the turn start through the city's
  `complete_unit_production`, keeps the ones that still cannot be placed,
  and drops those whose city the player no longer holds; `City.set_owner`
  drops the old owner's entries for the city. (Production that cannot place
  its unit still waits in the city, as before.)
- **Two buildings,** Civ 6's costs and yields: Market (120 production, no
  upkeep, +3 gold, +1 route capacity; Currency, a Commercial Hub) and
  Lighthouse (120, no upkeep, +1 food, +1 gold, +1 housing, +1 route
  capacity; Celestial Navigation, a Harbor). The wiki gives neither an
  upkeep. Veterancy's +30 % toward Harbor buildings now reaches the
  Lighthouse.
- **The Trader is buildable**, offered while a route slot is free: the
  build mask, `produce_unit` and `purchase` offer or accept a Trader only
  when the owner's route capacity exceeds its running routes plus its
  standing Traders (`City.can_produce_unit`, one predicate for all three),
  so a Trader that could never be sent is never an option (#67, #51). Civ
  6: "when Traders equal capacity you cannot build more". Build options
  appended, the #67 contract: Market, Lighthouse, Trader. The Trader left
  `DEFERRED_BUILD_UNITS`; the trade unit is named once, as `[trade] unit`.
- **Engine defaults** (design §13 as amended by v2; no agent chooses yet,
  #99): `defaults.default_trade`, each economy phase after route expiry: in
  `Player.units` order, a Trader on an own city centre with all its
  movement and not having acted is sent, while a slot is free, to the
  eligible destination whose route would yield the origin the most (every
  yield counted alike), ties to the lower city id; a Trader anywhere else
  takes one step, through `Unit.move`, to the adjacent tile strictly nearer
  the nearest own city centre (ties by coordinates; never onto a foreign
  unit, never `path_finder`). A returned Trader is therefore sent out again
  in the same phase.
- **Engine.** The economy phase order is now maintenance, bankruptcy,
  research, civics, the government and loadout defaults, route expiry and
  Trader return, the Trader default (design "v2 fixes", turn order; the
  Worker default follows in P8). `Player.routes` (`trade.TradeRoute`
  records) and `queued_units` are declared in `Player.reset_state`. The
  P4 hook stubs in `environment.py` are replaced by the real consumers:
  `unit_maintenance_delta` (`game/maintenance.py`), `purchase_percent` and
  `faith_purchase` (`game/purchasing.py`), `trade_route_capacity` and
  `route_yield` (`game/trade.py`). The smoke script logs treasury, upkeep
  paid, units disbanded, routes opened and running, and purchases per
  player; one seeded run (`python scripts/smoke_random_selfplay.py --seed
  4242`, duel, 250 rounds, random valid actions, 1 game) opened 2 and 6
  routes (none by the round-50 checkpoint, 2 each by round 100), paid 674
  and 1,023 gold of upkeep, disbanded no unit (treasuries 985 and 897 gold
  at the end), bought nothing (no default buys), and had no route running
  at the round-200 and round-250 checkpoints (log checkpoints at rounds 50,
  100, 150, 200 and 250).

**What agents see.** No encoder channel reads the treasury, faith, upkeep or
routes (#99, #111): routes reach agents only through their origin's yields
(the build state's turns-to-complete channels read `calculate_production`,
which now includes route production), and upkeep only through which units
survive. At full width the build head has three more outputs and the build
state three more channels; an archived narrower head is loaded at its own
width and does not see them.

**Accepted gaps.** No engine default and no agent action buys or upgrades
(#99): `purchase` and `upgrade_unit` are dormant in play, like `swap_tile`.
No plunder, no route path on the map, no Trading Posts and no "Switch City";
routes need neither a discovered destination nor a land path. A route lasts
21 turns flat: no round-trip arithmetic and no era extension (Civ 6 GS adds
10 turns from the Medieval world era). The destination's owner gets nothing
(as in Civ 6). A bought unit can act the turn it is bought (Civ 6: no
movement until next turn) and a city may buy a unit while a unit of its
class stands on the centre (it is placed beside it or queued; Civ 6 refuses
the purchase). Unit and Trader prices do not rise with each purchase or
with tech (Civ 6's progressive Settler, Builder and Trader costs are not
modelled). Bankruptcy has no amenity penalty (no amenities, #96).

### Wonders (#116 P6)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§3 (the one-shot kinds and `growth_percent`), §5.4, §9 and "v2 fixes"
(Wonders; District registry readers; Yields: the growth formula). Civ 6
facts: `docs/civ6_progression_reference.md` §5 (the Civilization Wiki's
wonder list and per-wonder pages, Gathering Storm). Erik's March notes
(`civulator_notes-20260322.md`): keep wonders, soften the lost race.

- **A wonder is a district.** The district registry gains a `kind` column,
  `"district"` (default) or `"wonder"`. A wonder table declares `era` (one
  of the tree's eras, new; a wonder column only), `counts_toward_limit =
  false` (it takes no population slot), `cost_model = "fixed"` (Civ 6:
  wonder costs never escalate), `max_per_city = 1` and (P9) `max_per_player =
  1`, and no `adjacency_yield`, `adjacency` or `discount_percent`; anything
  else raises at load. So placing, paying for and completing a wonder is the district
  path, unchanged: `can_place_district`, `place_district`,
  `produce_district`, the production branch of `process_turn`, and
  `complete_district`. Its yield and `housing` columns count in its city
  once complete, like a district's; its `effects` hold in its city (scope
  `"city"`, the district default) or, with `scope = "player"`, in every city
  of its owner. A wonder is never a specialty district (Meritocracy,
  Classical Republic, Insulae, Medina Quarter, the trade table,
  `housing_if_districts` do not count it) and never counts toward the
  district discount's A or B.
- **World-unique: the race.** `can_place_district` refuses a wonder that
  any player has completed (computed from the live board, every city in
  id order; no registry). Copies placed but unfinished in other players'
  cities are the race (a player may have only one copy of a wonder
  placed at a time, P9 below): when one completes (in
  `complete_district`), every other copy is removed (its tile is freed and
  worked again, `Map.district_epoch` bumps) and its city's production item
  is cleared if it was that wonder. `[wonders] consolation_percent` of the
  removed copy's LOCKED cost (integer floor) is added to that city's
  production pool: P6 shipped 50 % (Civ 6: "the consolation is 50 % of the
  production invested"; the design's call, §9.2, to keep attempting a
  wonder a gamble rather than a trap), and **P9 sets it to 0**: a city's
  production pool is one number that a switch keeps (§2.3), so the losing
  city already keeps everything it had put toward the copy, and a refund on
  top -- even for a copy that received no production -- was pure gain. The
  key and the mechanism stay for a future sunk-cost model, in which the
  pool would be spent at placement. The race is decided inside the
  completing player's turn, so turn order decides a same-round tie
  (**accepted**). New per-player stats `wonders_completed`,
  `wonder_races_lost`.
- **One-shot effects fire once, on completion.** Four effect kinds,
  validated since P4, now fire in `GameEnvironment.complete_district` --
  the one completion path, which raises on a second call -- and never on
  capture or on load (no loader rebuilds districts): `free_units` (each
  unit placed through `City.place_or_queue_unit`, queued when the city has
  no room), `free_tech` / `free_civic` (the current tech or civic, or the
  engine default's pick, completes at once at no cost, outside the
  one-per-turn rule; the pools are untouched and the turn's own research
  still resolves; `techs_researched` / `civics_researched` count it),
  `free_population` (added to the city, or to every city of the owner with
  `all_cities`, each re-assigning its tiles). A one-shot kind is accepted
  only on a `kind = "wonder"` table and is never among the effects in
  force. When a wonder grants a civic or changes its owner's policy slots,
  the government and loadout defaults re-run at once, so a new slot is
  filled (design §5.4); and (P9) when a city holding such a wonder changes
  hands, `City.set_owner` re-fits both players' loadouts the same way.
- **Growth percent.** The growth bucket is now `food_net * housing_percent
  * growth_share * (100 + growth_percent) // 10000` hundredths (design v2;
  `growth_share` is 100 until loyalty, P7): the summed `growth_percent`
  effects in force, applied once. With none it is v0.7's `food_net *
  housing_percent` exactly.
- **New placement and adjacency vocabulary.** `requires_adjacent_all`
  (every listed source must match a neighbour; `requires_adjacent` needs
  any one); `river_on_tile = true` accepted as a tile test in both
  requirement lists (a river along any edge of the tile, the edge shared
  with the city centre included -- unlike the Aqueduct's
  `river_edge_not_shared_with_center`); the adjacency source `wonder =
  "any"`, which counts adjacent COMPLETE wonders. A wonder is no
  `district = "any"` source, placed or complete (the city centre still is),
  and a `district = [...]` list may name districts only. The Theater Square
  gains Civ 6's `+2 per adjacent wonder` row (dropped in #86 because no
  wonder existed).
- **Wonder eras in production targets.** A `production_percent` target may
  name `wonder_era = [...]`, AND-combined with `kind = "wonder"`, read from
  the wonder's own `era`. Corvee is now +15 % toward Ancient and Classical
  wonders and Gothic Architecture toward Ancient to Renaissance ones (every
  era of the tree) -- Civ 6's scopes; this closes P4's gap ("Corvee targets
  every wonder").
- **The twelve wonders** (Civ 6 Gathering Storm costs; requirements moved
  where a cut tech or civic held them; "flat" is spelled as the flat land
  bases, since water is flat too; every placement also obeys the general
  district rules -- owned tile within radius 3, no district, centre or
  other city's centre next to it, no blocking feature, bonus resources
  only):

  | Wonder | Era · cost | Requires | Placement | Columns · effects | Civ 6 / source |
  |---|---|---|---|---|---|
  | Pyramids | Ancient 220 | Masonry | flat Desert or Plains | culture 2; 3 free Workers | Desert only; +1 Builder and a build charge (Erik: "quite a few builders") |
  | Stonehenge | Ancient 180 | Astrology | flat land, adjacent to Stone | faith 4 | +2 faith and a Great Prophet (no prophets here) |
  | Hanging Gardens | Ancient 180 | Irrigation | a river on an edge of its tile | housing 2; +15 % growth in every city of its owner | as Civ 6 |
  | Temple of Artemis | Ancient 180 | Archery | adjacent to Cattle, Sheep or Deer | food 4, housing 3 | next to a Camp; its amenities are not modelled |
  | Oracle | Ancient 290 | State Workforce (civic) | hills | culture 2, faith 2; one free civic | Mysticism (cut), Ancient; a great-person discount with no object here |
  | Statue of Zeus | Classical 400 | Military Training (civic) | flat land, adjacent to an Encampment | gold 3; 3 free Spearmen and 3 Archers; +50 % toward anti-cavalry units in every city of its owner | Civ 6 also grants a Battering Ram and needs a Barracks in the Encampment |
  | Great Library | Classical 400 | Recorded History (civic) | flat land, adjacent to a Campus | science 3; one free tech | +2 science and boosts for every Ancient/Classical tech; needs a Library |
  | Colossus | Classical 400 | Celestial Navigation | on Coast, adjacent to land AND to a Harbor | gold 3; +1 trade route capacity (owner); 1 free Trader | Shipbuilding (cut); its Great Admiral points are not modelled |
  | Colosseum | Classical 400 | Games and Recreation (civic) | flat land, adjacent to an Entertainment Complex | culture 2; +2 loyalty to own city centres within 6 tiles (consumed from P7) | its amenities are not modelled |
  | Alhambra | Medieval 710 | Castles | hills, adjacent to an Encampment | +1 military policy slot; +6 defence for its city | "the defences of a Fort"; its amenities and Great General points are not modelled |
  | Angkor Wat | Medieval 710 | Medieval Faires (civic) | adjacent to an Aqueduct | faith 2; +1 population in every city of its owner when built; +1 housing in every city | as Civ 6 |
  | Forbidden City | Renaissance 920 | Divine Right (civic) | flat land, adjacent to the city centre | culture 5; +1 wildcard policy slot | Printing (not in the tree) |

  A placement district requirement (Encampment, Campus, Entertainment
  Complex, Harbor, Aqueduct) is met by a placed district, finished or not
  -- the framework's rule for every requirement (#86) -- and asks for no
  building in it (Civ 6 asks for a Barracks, a Library, an Arena).
- **Engine.** `GameEnvironment._remove_district(city, district)` is the one
  district removal (frees the tile, leaves `city.districts`, bumps
  `district_epoch`, re-runs `assign_tiles`); `remove_city` now uses it
  too. `resolve_research` / `resolve_civic` share their completion step
  with the free tech and civic (`_complete_tech` / `_complete_civic`).
  `effects.CONSUMERS` names the consumers of `growth_percent`
  (`City.growth_bucket_gain`) and the four one-shot kinds
  (`GameEnvironment._one_shot_effects`); only `loyalty` stays deferred
  (P7). The smoke script draws a district or wonder type among those its
  owner can build, a tile through `can_place_district`, and reports per
  player the wonders completed, the races lost and the wonders held; one
  seeded run (`python scripts/smoke_random_selfplay.py --seed 4242`, duel,
  250 rounds, random valid actions, 1 game) completed 1 and 3 wonders (the
  Pyramids; Stonehenge, the Temple of Artemis and the Hanging Gardens), the
  first player lost 1 race; 14 districts and wonders were placed and 9
  stood complete at the end. Being a different random sequence from P5's
  run, it opened no trade route; two further seeds (7 and 99, same
  command) each had one player open routes (12 and 8).

**What agents see.** Nothing new: no agent action and no engine default
places a district or a wonder (#99), so wonders occur only where a script or
a test places them; no encoder channel reads a wonder (#111). The build
state's district branch still raises `NotImplementedError` naming #99.

**Accepted gaps.** Civ 6's "completing a wonder claims two more tiles" is
not implemented (borders grow only by culture, #87), and no wonder's amenity
effect exists (no amenities, #96). A wonder cannot be bought (Civ 6 neither).
Tourism, great-person points, great works and era score do not exist. (P6
let a player place copies of one wonder in several of its own cities; P9
closes that, Civ 6's rule: once one city has broken ground, no other city
of that player may start it.)

### Loyalty (#116 P7)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§8 and "v2 fixes" (Loyalty arithmetic; Flips, captures and `set_owner`;
Turn order; Yields: units, scaling and adjacency). Civ 6 facts:
`docs/civ6_progression_reference.md` §11 (the Civilization Wiki's Loyalty
page, Rise and Fall / Gathering Storm, and the Monument, Palace and Colosseum
pages). Erik asked for loyalty from the ground up, Civ 6-inspired
(2026-10-21): the non-military way to take a city, and the counter to
founding cities in a bigger neighbour's shadow.

- **A loyalty per city.** `City.loyalty`, an int from 0 to `[loyalty]
  maximum = 100`: `founded = 100` for a new city, `captured = 50` whenever a
  city changes hands -- by capture or by a flip, both through
  `City.set_owner` (design §8.1, Claude's call: a conquest must be
  consolidated; the wiki gives no starting value). It travels with the city.
  All of `[loyalty]` is read by `civulator/game/loyalty.py` only.
- **Pressure (Civ 6's formula, in integers).** A player presses a city with
  the sum, over its cities within `range = 9` (canonical wrap distance,
  inclusive), of `population * (citizen_weight - distance)`,
  `citizen_weight = 10` (Civ 6: -10 % per tile); the city presses for its own
  owner at distance 0. `own` is the owner's pressure, `foreign` the sum of
  every other living player's. Departure: no age factor (there are no
  golden or dark ages) and no Bread and Circuses or cultural-dominance
  multiplier.
- **Drift.** `sign(own - foreign) * (2 * drift_gain * |own - foreign| // (2 *
  min(own, foreign) + 1))`, clamped to `+-drift_cap`, `drift_gain = 10`,
  `drift_cap = 20` -- Civ 6's `10 * (D - F) / (min(D, F) + 0.5)`, capped at
  +-20. Departure: integer arithmetic, truncated toward zero, so the wiki's
  worked example (domestic 31, foreign 45, -4.4) gives -4 here. A city
  alone drifts +20; a population-1 city five tiles from a population-6
  rival capital drifts -19 (own 10, foreign 30), the design's Duel example.
- **The other per-round sources**, added after the drift (so the total may
  exceed +-20, as in Civ 6):

  | Source | Loyalty per round | How it is declared | Civ 6 |
  |---|---|---|---|
  | Garrison: a unit of the owner of a fighting class (not `support`, not `civilian`) on the centre | `[loyalty] garrison = 2` | inherent | **departure** (design §8.2, Claude's call): Civ 6 has no inherent garrison term -- only cards that need one; here a garrison is the one lever a player has on turn one |
  | Monument | +1 | `loyalty` column of `[buildings.Monument]` | +1 |
  | Government Plaza (complete) | +8 | `loyalty` column of `[districts."Government Plaza"]` | +8 (a Governor's +8 is not modelled) |
  | Palace | +1 per citizen of its city | effect `{ kind = "loyalty", amount = 1, per_population = true }` | +1 per citizen (R&F Palace) |
  | Limitanei (policy card) | +2 in a garrisoned city | effect with `requires_garrison = true` | +2 if garrisoned |
  | Colosseum (complete wonder) | +2 to every city of its owner within 6 tiles of it, its own included | effect with `range = 6`, `scope = "player"` | +2 to each city centre within 6 tiles; **departure**: own cities only |

  A building's or district's `loyalty` column is whole points (not tenths);
  everything conditional is the `loyalty` effect kind, whose one consumer is
  `loyalty.loyalty_delta` (`effects.DEFERRED_KINDS` is now empty: every
  kind has its reader). The loader refuses a `range` on anything but a
  building or district of scope `"player"` (it measures from the city
  holding the source; every entry in force now carries that
  `source_city`), and a flat, unconditional city-scoped loyalty effect on a
  building or district (that is what the column says -- one way to say it,
  as for yields). Not modelled (design §8.6): amenities (#96), governors,
  religion, starvation's -4, grievances, the other loyalty cards, the
  Audience Chamber, the Statue of Liberty, free cities' and city-states'
  base levels.
- **Once per round, at round end.** `GameEnvironment._loyalty_phase` runs in
  `next_turn` after the border phase and before the end-of-game test and
  `turn_counter += 1` (design "v2 fixes", Turn order), with the border
  phase's discipline: every city takes part, whoever owns it, and
  everything is computed from the state at the start of the phase -- every
  delta first (cities in id order), then `loyalty = clamp(loyalty + delta,
  0, 100)` for all, then, for every city left at 0, the player pressing it
  hardest (still the phase-start board: pressure reads population,
  distance and owners, never loyalty), then the flips in city-id order. So
  neither seat order nor a city founded late in the round, nor an earlier
  flip of the same phase, decides a delta or a flip target. Integers only;
  no RNG.
- **Bands** (`[loyalty] bands = [[min, yield_percent, growth_share], ...]`,
  ints, mins strictly descending, first match wins, loyalty 0 in the last
  band; the loader raises otherwise), Civ 6's four exactly:

  | Loyalty | Science, culture, gold, faith, production | Growth |
  |---|---|---|
  | 76-100 (Loyal) | 100 % | 100 % |
  | 51-75 (Wavering) | 75 % | 75 % |
  | 26-50 (Disloyal) | 50 % | 25 % |
  | 0-25 (Unrest) | 0 % | 0 % |

  The percent scales the four pool yields inside `city_yield` (one floor,
  as P1 specified) and production once in `City.calculate_production`,
  after the summed `production_percent` effects; the share scales the
  growth bucket in `City.growth_bucket_gain` (replacing P6's 100 %
  stub). **Departures**: food is not scaled (starvation is its own
  punishment, design §8.4; Civ 6 says "all yields"), and production keeps
  its floor of 1, so a city in unrest still builds, slowly. A 0 % growth
  share blocks growth even with a full bucket, like housing's 0 % band (Civ
  6 Unrest: "no Population growth"); the bucket is kept.
- **Revolt: a direct flip.** A city at 0 after the phase joins the player
  exerting the largest foreign pressure on it (ties: the lower player
  index); a city nobody else presses stays with its owner at 0. The flip,
  `GameEnvironment._flip_city`, deletes the old owner's units on the centre
  tile (each counted in its `losses`), then calls `City.set_owner` -- the one
  place a city changes hands, now with two callers, `_capture_city` (force)
  and `_flip_city` (loyalty): the tiles, districts and wonders go with the
  city, its loyalty resets to `captured`, every trade route touching it
  ends and the old owner's queued units for it are dropped (P5). New
  per-player stats `cities_flipped_out` / `cities_flipped_in`; a flip is
  never counted in `cities_captured`. **Departures**: no free city (Civ 6:
  the city first becomes a Free City and later petitions to join the civ
  pressing it most; there is no neutral owner in the engine, design §8.6);
  a city flips at 0 whatever the sign of that round's delta (Civ 6: "0 or
  less while still receiving negative Loyalty"; here a city can only reach
  0 by a delta of at most 0). The capital is protected the Civ 6 way, by
  the Palace's per-citizen loyalty, not by immunity.
- **No reward.** A flip pays no reward: it happens at round end, where no
  step returns one. Whether the training objective should see flips is
  Erik's call. A player whose last city flips is eliminated exactly as after
  a capture: it plays one more turn without a city and dies in
  `Player.end_turn`, which ends a two-player game.
- **Engine.** `next_turn`'s round end is `_border_phase` -> `_loyalty_phase`
  -> the end-of-game test (`_update_done`, the same test `_check_game_end`
  and the end of `next_turn` run; since P9 it also tests domination)
  -> `turn_counter += 1`. `unit_model.FIGHTING_CLASSES` names the classes that garrison a
  city and that are "land military" for faith purchases (P5).
  `effects.Effect` gains `source_city` (set on the entries `active_effects`
  returns; ignored by equality). The smoke script logs per player the lowest
  and mean loyalty of its cities and the loyalty flips at every checkpoint,
  and the end line adds the lowest loyalty any of its cities had after any
  round. Seeded runs, 1 game each, random valid actions, 250 rounds:
  `python scripts/smoke_random_selfplay.py --seed 4242` (duel, 2 players)
  -- no city below 100 after any round and no flip, and the districts and
  wonders lines match what P6 recorded for the same command (14 placed, 9
  complete; 1 and 3 wonders): the top band changes nothing; seeds 7 and 99
  (same command) likewise no city below 100. `python
  scripts/smoke_random_selfplay.py --seed 4242 --size tiny` (3 players): a
  city of the second player was at 1 at the round-150 checkpoint; 3 flips
  over the game (the second player lost 2 cities and gained 1, the third
  lost 1 and gained 2), the third player holding a city at 50 at the end;
  seed 7 (same command): no city below 100.

**What agents see.** Nothing new in the encoders (#111): no channel reads
loyalty, and no agent action or engine default acts on it (#99). The build
agent's turns-to-complete channels read `calculate_production`, so a city
below the top band shows its scaled production to archived weights.

**Accepted gaps.** In the one tiny-map run above, the 3 flips all fell
between rounds 150 and 250 and between the second and third players, in
both directions (2 to the third player, 1 back; 1 game). Nothing in this
model damps a flip back -- a flipped city starts at 50 where it was pressed
before, and there is no free city, post-flip immunity or governor -- so
cities between two rivals may change hands repeatedly; not measured beyond
that one game. The Colosseum reaches only its owner's cities.

### Workers build improvements by default (#116 P8)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§13, §15 P8 and "v2 fixes" (Improvement yields; Worker default; Load order
and config ownership; Turn order). This patch closes the accepted gap of the
housing design (#88): no unit built improvements in play, so improvement
housing, improvement yields and every tech that unlocks an improvement were
dormant in real games.

- **The rule.** The last step of the economy phase, after the Trader default,
  is `defaults.default_workers` (no RNG). In `player.units` order, every
  Worker that is idle -- all its movement and not having acted, so a Worker an
  agent ordered this turn is left alone -- does exactly one of:
  - **(a) builds.** On a tile where its owner may build some improvement
    (`GameEnvironment.can_player_build_improvement_at`: the tile is the
    owner's, the improvement's `requires_tech` is known, the tile predicate
    holds) it builds the one with the largest **gain**: the improvement's
    food + production + gold from `[improvements.*]`, whole points, each
    counted alike; then the larger housing; then config order
    (`terrain_model.IMPROVEMENT_ORDER`) -- through `WorkerUnit.
    build_improvement`, which now also marks the Worker acted and counts the
    build in the new per-player stat `improvements_built`.
  - **(b) walks.** Otherwise it takes one step toward the nearest of its
    owner's tiles where it could build something -- nearest by the canonical
    `distance_function`, ties by `(row, col)`; the candidates come from
    `Map.tiles_of_city` over the player's cities in city-id order, and a
    candidate is never a city centre, a district tile or an improved tile and
    has no unit of another player and no own Worker standing on it. The step
    is the Trader default's one-step rule, factored out of `trader_step` into
    `defaults.step_toward` so both defaults share it: the adjacent tile the
    unit can enter, with no foreign unit, its own slot free, a payable
    `step_cost` and strictly nearer, ties by `(row, col)`, taken through
    `Unit.move`. Never `path_finder`. One action per turn: a Worker that
    stepped onto its target builds the next turn.
  - **(c) stays,** when there is nothing to build or reach.
- **Claude's calls** (the design is silent on all three).
  - **One improvement per tile.** The engine's tile predicate refuses only a
    repeat of the *same* improvement ("our engine lets several stack",
    `docs/housing_design.md`), so without a rule of its own a Worker would
    stand on one Plains tile and build a Farm, then a Plantation, a Camp, a
    Pasture and a Quarry. The default, and the Worker's build offer, never
    improve a tile that already holds one (Civ 6 allows one). The rule lives in
    the new `civulator/game/improvements.py`, not in the tile predicate:
    `can_build_improvement_at`, the painter and `build_improvement` are as
    they were. Whether the engine itself should refuse a second improvement is
    Erik's call.
  - **Workers spread.** A tile an earlier Worker of the same pass chose is
    chosen by a later one only when no other open tile is left, so Workers
    that start together -- the Pyramids' three -- go to different tiles
    instead of queueing for one. The fallback is not optional: a first version
    that excluded the claimed tiles outright deadlocked six Workers on a
    36-tile territory with 35 improved and nobody moving (the Worker nearest
    the last tile had nothing to aim at while a farther one, first in unit
    order, held it behind a blocked way); `tests/test_worker_default.py` keeps
    that scene.
  - **Config order is a tuple.** `IMPROVEMENT_NAMES` is a frozenset, whose
    iteration order changes with the process's hash seed; "ties by config
    order" reads the new `terrain_model.IMPROVEMENT_ORDER`. (On flat Plains
    with every tech, Plantation and Camp tie on gain and housing: the order
    decides.)
- **The Worker is a build option.** `Worker` left `DEFERRED_BUILD_UNITS` and
  is appended to `BUILD_OPTIONS` (30 -> 31 options; archived build heads keep
  their width, #67). It is offered, producible and purchasable only while its
  owner holds a tile a Worker could be sent to -- `improvements.
  worker_has_work`, read by `City.can_produce_unit`, so the build mask,
  `produce_unit` and `purchase` share one predicate: an owned tile where an
  improvement may be built now, with no improvement yet and no foreign unit or
  own Worker on it (the mask invariant, #51: a Worker with nothing to build
  cannot pay off). It counts tiles, not Workers already on their way.
- **What is live now.** Workers; the Ilkum policy's +30 % production toward
  them (P4); the Pyramids' three free Workers (P6), which the default sends to
  work in the turn they appear; improvement yields (P2: food and production
  into `Tile.yields`, so the terrain-aware encoder's yield channels see them;
  gold into `city_yield`); improvement housing (#88); and the techs that unlock
  an improvement (P2). Idle Workers cost no upkeep (`[units.Worker]
  maintenance = 0`), so only production limits how many exist.
- **Measured** (nothing here is an effect on agents). *Default alone, no
  agent:* two Workers per player placed next to each capital, every tech known,
  seed 11, 8x16 `basic` world, 2 players (`play(11, rounds)` in
  `tests/test_worker_default.py`, 1 game): improvements built per player after
  2 rounds [2, 2], after 6 rounds [5, 5], after 12 rounds [7, 6], after 50
  rounds [9, 8]. The capitals own 7 tiles at the start and 10 by round 50, so
  after the first rounds the default builds as the borders grow. *Random
  agents:* `python scripts/smoke_random_selfplay.py --seed S [--size tiny]`, 1
  game each, 250 rounds; it now logs per player the improvements built, the
  improvements standing on its cities' tiles and its Workers alive at every
  checkpoint and in an end line. Built / standing / Workers alive at the end,
  one entry per player: seed 4242 duel [6, 0] / [6, 0] / [3, 0]; seed 7 duel
  [0, 3] / [0, 1] / [0, 1]; seed 99 duel [0, 6] / [0, 3] / [0, 1]; seed 4242
  `--size tiny` (3 players) [0, 7, 8] / [0, 3, 5] / [0, 0, 2]; seed 7 `--size
  tiny` [20, 9, 17] / [13, 7, 12] / [0, 4, 2]. The counts are low and uneven
  because the random build choice rarely picks a Worker and the random agent
  also moves the Workers the default is working. Built minus standing is, in
  all five runs, exactly the improvements the smoke script's random district
  placement cleared (a district placed on an improved tile removes the
  improvement, P2): 0, 2, 3, 7 and 14, counted by a one-off wrapper around
  `Tile.clear_improvements` that is not committed.
- **What agents see.** The terrain-aware encoder reads `Tile.yields`, so built
  improvements show in its food and production channels (the terrain epoch is
  bumped, P2); nothing else in the encoders changes. No agent action builds an
  improvement or orders a Worker's work (#99): the default is the only builder,
  and an order an agent gives a Worker is overruled only at the next turn start,
  when the default acts on an idle Worker.

**Accepted gaps.** The Worker is offered while *any* open tile has no Worker on
it, even when the Workers already alive outnumber the open tiles. Whether the
engine's tile predicate should itself forbid a second improvement (above) is
open. One action per turn, and Civ 6's work-over-several-turns, charges and
pillaging are not modelled. Nothing removes an improvement from a tile its
owner loses: it changes hands with the tile.

### Winning (#116 P9)

**Rule change, effect NOT yet measured.** Spec: `docs/progression_design.md`
§11, §12 and "v2 fixes" (Verdict and domination; Turn order; Wonders), and
the §14 rows "Domination ..." and "the verdict and the score diverge (#55)".
This patch closes #100's gap with the two cheapest honest rules, finishes the
wonder rulings P6 left open, and releases 0.8.0.

- **One verdict.** `determine_outcome(env) -> (winner, victory)` lives in the
  new engine module `civulator/game/victory.py` (the engine may import nothing
  of training; `training/trainer.py` re-exports `determine_winner`,
  `determine_outcome`, `player_score` and `CITY_SCORE_WEIGHT` under their old
  names, so every caller is unchanged). In this order: **elimination** (one
  living player), **domination**, then, once the game is done at or past the
  turn cap (`env.done and env.turn_counter >= env.max_turns`), the **turn-cap
  score** -- the unique highest `player_score` wins (`"score"`; a dead player
  ranks -1), a tied top score is `(None, "draw")` -- and otherwise `(None,
  None)`: the game is running, or a step guard cut it off, and **a truncated
  game's `victory` is null, never `"draw"`** (#51). `determine_winner(env)` is
  `determine_outcome(env)[0]`. `GameEnvironment._update_done` -- called by
  `_check_game_end` after every step that can capture a city, and by
  `next_turn` after `_loyalty_phase` and before `turn_counter += 1` -- asks
  the same module (`victory.game_over`: a decisive outcome, nobody alive, or
  the cap passed), so `done` can never disagree with the verdict.
- **Domination** (new, outright): a living player that holds **every Palace
  in the game** -- `[city] capital_building`, the capital marker -- **and** at
  least one Palace that was granted to another player (`Player.palace_granted`,
  which outlives the Palace's city) wins the moment it takes the last one,
  whether or not the others still have cities (Civ 6: capture all capitals).
  In a Duel, taking the enemy capital now ends the game at once; before this
  patch it ended when the loser had no city left, which took conquering every
  city. The second clause is what stops a vacuous win: a board with no Palace
  (a painted scenario) and the first player to found a capital (the only
  Palace that exists, no other player yet granted one) both "hold every
  Palace" and neither wins. A loyalty flip that takes the last Palace ends the
  game in its own round (the verdict runs after the loyalty phase). Rewards
  are the existing ones: the capture's own reward, then the terminal win and
  loss rewards once `done` (so they arrive at the capture, not several turns
  later). Decisions of this patch, all Claude's: a player that has not yet
  founded its capital does not block a domination (every Palace that exists
  is held, one of them granted to the loser); a Palace gone with a removed
  city (`remove_city`, painter and recorder only; no rule removes a city) is
  gone, but the grant stays recorded.
- **The score has terms.** `[game] city_score_weight` stays where it is and a
  new `[game.score]` holds the rest. `player_score(player)` is the sum of
  `score_breakdown`, one term per kind of holding, each a count times its
  weight:

  | Term | Count | Weight (config) | Starting value |
  |---|---|---|---|
  | cities | the player's cities | `[game] city_score_weight` | 10 (unchanged) |
  | units | its units | `unit_weight` | 1 (unchanged) |
  | population | the population of its cities | `population_weight` | 1 |
  | techs | techs known | `tech_weight` | 2 |
  | civics | civics known | `civic_weight` | 2 |
  | wonders | its complete wonders (`kind = "wonder"`, any city; a placed, unfinished one counts nothing) | `wonder_weight` | 10 |

  The starting weights are Claude's (design §11): a full tech tree (22 techs)
  is worth about four cities and a wonder one; **Erik tunes them while the
  agents play** -- the loader accepts whole numbers >= 0, exactly these five
  keys, and raises otherwise, and `meta.build_manifest` records the table with
  every artifact. Until P9 the score was `cities * 10 + units`. The viewer
  HUD shows `player_score` and the verdict's `victory` kind, and the smoke
  script prints the verdict and each player's score term by term.
- **The eval record says how a game ended and under which rules.**
  `scripts/evaluate.py`'s `games_detail[]` gains `victory`
  (`"elimination" | "domination" | "score" | "draw"`, null when truncated),
  read from `determine_outcome` and never re-derived there; the summary gains
  the engine's `game_version` and, per side, `weights_game_version` (the
  `game_version` of each weights file's manifest, null for a file saved before
  manifests): archived 0.7 weights play 0.8 rules, and the record must say so.
  Older summaries lack the keys; readers treat them as absent.
- **Wonder rulings** (P6 left them for P9; Claude's calls, Erik may overturn
  them). `[wonders] consolation_percent = 0`: the production pool is not sunk
  until completion, so a losing city already keeps its production and a
  refund was pure gain (the key stays for a future sunk-cost model).
  `max_per_player = 1` on every `kind = "wonder"` table, and the loader
  requires a wonder table to declare it: once one city of a player has placed
  a wonder, no other city of that player may (Civ 6; the district placement
  check already counted placed copies per player). The Oracle's era is
  Ancient (Civ 6; it was Classical): its effects do not change (Corvee covers
  both eras). When a city holding a complete wonder that grants policy slots
  changes hands, by capture or flip, `City.set_owner` re-fits **both**
  players' loadouts through the engine's government and loadout defaults, so
  the old owner is not left with a card in a slot it no longer has and the
  new owner's new slot is filled.
- **Release.** `__version__` was 0.8.0 since P1; the fixture was regenerated
  then. This entry is dated and finished, `docs/game_overview.md` describes
  0.8.0, `weights/trained/manifest.md` carries the 0.8 epoch marker, and
  CLAUDE.md's rows are brought to the final state (the Victory row is new;
  Win/score determination is amended).

**What agents see.** Nothing in the encoders or the action space changes. The
terminal reward now arrives at the moment a capital is taken, not when the
last city falls, and a policy that takes the enemy capital wins the game. The
turn-cap tiebreak now weighs techs, civics, population and wonders. No agent
chooses research or civics until #99 (the engine defaults research the
trees), so what separates two players at the cap is mostly the science and
culture their cities yield and how many cities they hold. In the five smoke
games run for this patch (seeds 4242, 7 and 99 on the duel map; 4242 and 7
on `--size tiny`; 1 game each, random play) the techs and civics terms were
56 to 68 of the winner's 91 to 132 points, every game ended on score at round
250, none ended by domination or elimination, and no city flipped. Five random
games say nothing about the weights; they are why the weights are Erik's to
tune.

**Accepted gaps.** No tree victory, religious victory or culture victory (named
in design §11, not designed). The weights are starting values, never tuned
against play. A domination can be won before every player has founded a
capital (the Palaces that exist are all held and one was granted to the
loser). A `watch.py --eval-json` replay of a pre-0.8 summary plays 0.8 rules,
so it will not reproduce the recorded game.

---

## v0.7.0 — Borders and culture; city combat and the other post-0.6.2 rule changes (2026-10-11)

**New rules epoch (#78).** Borders (#87) are the first change that gives
cities territory, and they land on top of the rule changes that had been
collected here under "Unreleased" (city combat #84, minimum city distance #74,
siege class #66, flanking #59, Walls #7, Slinger/Swordsman #67). Together they
open the 0.7 epoch: results trained or evaluated under 0.6.x rules are not
comparable to 0.7 results (epoch marker in `weights/trained/manifest.md`). The
plain semver bump 0.6.2 → 0.7.0 follows the borders design
(`docs/borders_culture_design.md` §7); #83's open question about the number
("v0.2.0" was once said) remains unresolved. Everything below is a **rule
change**, not a refactor.

### Borders and culture (#87)

**Rule change, effect NOT yet measured.** Spec:
`docs/borders_culture_design.md` (v2). Lands in patches P1–P5; this entry
grows with each. Civ 6 source: the Civilization Wiki,
[Borders (Civ6)](https://civilization.fandom.com/wiki/Borders_(Civ6)).

**P1 — culture yield.** Each city produces
`culture = base + per_pop * population + sum of each source's culture` per
turn (`[culture] base = 1.0`, `per_pop = 0.3`, a stand-in for the Civ 6 Palace
and the community-reported Civ 6 per-citizen value). Sources declare a
`culture` column in their own config table; today `[buildings.Monument]
culture = 2` (Civ 6). Culture is stored as integer tenths and accrues in
`City.process_turn` (after growth, before production) into the city's border
pool and the player's civic pool (`Player.culture`, no consumer yet). The
Monument is not yet in `BUILD_OPTIONS`, so building culture is dormant in real
games (accepted gap, #73).

**P2 — tile ownership.** Tiles are owned per city: one grid on `Map`
(`owner_city`, city id or −1), written only by its mutation API
(`claim` / `transfer` / `release` / `city_changed_player`), with its own
`territory_epoch` (ownership never bumps `terrain_epoch`) and live owned-tile
counters per player. Every city is created and removed through
`GameEnvironment.create_city` / `remove_city`, including the Settler, reset,
and the painted-scenario paths.

- **Founding claim.** A new city owns its centre and every neutral ring-1 tile
  (`[territory] founding_ring = 1`). For each ring-1 tile already owned by
  another player it claims one replacement further out; Civ 6: *"tiles more
  than one hex away from the City Center and closest to the tiles that would
  have been claimed are immediately claimed instead."* Replacements are chosen
  by the border-growth ranking (nearest ring first, then resource, adjacent to
  a resource, food + production; remaining ties sorted by coordinates and
  shuffled with the engine RNG). A ring-1 tile owned by another of the same
  player's cities stays with that city (our call; the wiki does not say).
  At reset capitals are `min_city_distance` apart, so founding draws no RNG
  and seeded worlds are unchanged.
- **Founding restriction.** A city cannot be founded on a tile owned by
  another player; founding on your own territory is allowed and the tile
  moves to the new city. `can_found_city_at(coords, player)` now takes the
  founder; the action mask and the `settle` encoder's settle layer (now per
  player) both read it, so the `settle` channel can differ between players.
- **Capture.** A captured city keeps all its tiles; they change player with
  it (Civ 6).
- **Cities work only tiles they own** (radius: see P4).
- **Tile swap** between two cities of the same player
  (`GameEnvironment.swap_tile`): only tiles at least two steps from their
  current owner's centre (Civ 6: *"a tile adjacent to the City Center of one
  city cannot be swapped to another city"*) and within the target's work
  radius. Engine API only; no agent action yet (#99).
- Agents do not see ownership except through the settle layer (encoder
  follow-up).

**P3 — border growth.** A city's culture also fills a border pool; the n-th
tile it claims by culture costs `a + (b * (n - 1)) ** p` (`[territory.border_cost]`
`curve = "civ6_community"`, a = 10, b = 6, p = 1.3: 10, 20.3, 35.3, 52.8, …;
evaluated in floats once per n, stored as integer tenths). Curves are a named
registry (`BORDER_COST_CURVES`); a rebalance is a config edit or a new entry.
The claimed tile is a neutral tile within `claim_radius = 5` and adjacent to the
city's territory, taken from the nearest ring first (Erik's rule: every tile at
radius R before any at R+1), then ranked resource, next to a resource, food +
production, then ties sorted canonically and shuffled with the engine RNG.

- **Contest rule.** Claims resolve once per round in one border phase at the
  round's end, never during a player's own turn. Each city's pool is taken to
  fill linearly over the round; claims are processed in the order the cost is
  crossed (exact integer arithmetic; ties by larger surplus, then city id with
  an RNG shuffle). A city whose tile was just taken picks its next best and
  loses nothing. Turn order therefore never decides a contested tile, and cities
  of one player compete the same way as rivals.

**P4 — work radius and stats.** Cities work tiles up to `work_radius = 3`
(Civ 6), but only tiles they own; `assign_tiles` is order-independent of
border growth within a round. Episode stats gain `tiles_owned` (live, per
seat), `tiles_claimed_by_culture` and `culture_produced`.

**P5 — border overlay.** The hex renderer draws a segment on every hex edge
where the owning city differs between a tile and its neighbour (or one side is
neutral), coloured by the owning player, on the owned side so contested edges
show both colours. It follows the cylinder seam and the camera copy rules like
rivers. Borders are drawn dashed with a dark outline, so they cannot be
mistaken for the solid blue river edges (#115). Wired into `scripts/watch.py`
and `scripts/order_recorder.py`.

**Known gaps.** The Monument is not in `BUILD_OPTIONS`, so building culture is
dormant in real games (#73). Agents have no ownership channels (encoder
follow-up), start placement is still tuned to ring-1 fertility, and tile swap
has no agent action (#99).

### A founding Settler is consumed from its tile too (#113)

`SettlerUnit.found_city` removed the Settler from its player's units but left
it in the tile's unit list. Everything that reads a tile's units saw the
phantom:
- the city's own production never placed a unit on its centre, because it
  counted a friendly unit there (`City.complete_unit_production`);
- the A* occupancy grid treated the city tile as occupied;
- for an enemy, the move mask offered the city tile as an attack on the
  phantom, and `_get_enemy_unit_at` returned it as the defender.

Cities founded by a Settler during play were affected; capitals placed at
reset were not. The Settler now leaves through `GameEnvironment.delete_unit`,
like every other removed unit. This is a rule change inside the v0.7.0 epoch.
Pre-0.7 weights trained with the phantom present.

### City combat: cities can be attacked, besieged and taken (#84)

**Rule change, effect NOT yet measured.** No training or evaluation run has
been made against these rules; everything below is a statement about the
engine, verified by tests, not about play.

Issue #84: no order in the action space could attack a city.
`GameEnvironment._step_inner` recognised only an enemy *unit* on the ordered
tile, so an order aimed at an undefended enemy city fell through to
*movement* and the city changed hands by occupation. `City.health` could
never be reduced in a live game, which left Walls (#7) and the siege class
(#66) correct, tested and unreachable — 100 production for an effect no agent
could observe.

**The rules, all sourced from Civ 6.**

1. **An order aimed at an enemy city attacks it.** It routes to
   `_execute_attack` — the one path all damage flows through — with the City
   as defender. A city holding a defender still resolves against the defender
   first; that branch is untouched.
2. **Ranged bombard takes no counterattack; melee does.** This is what makes
   a siege unit the safe way to reduce a city, and it falls out of the
   existing ranged/melee split rather than being added.
3. **Capture requires `city.health == 0`,** and a melee-capable land unit
   moving in (`Unit.can_capture_city`: land domain, combat strength above 0,
   not ranged). A ranged unit reduces a city and never owns it; a civilian or
   siege support unit cannot take one either. Below 0 the city does not die —
   its health floors at 0 and it waits to be occupied. Killing the garrison
   of a full-health city no longer hands it over.
4. **A city can only make a ranged attack if it has Walls.** Civ 6, City
   combat: *"once a city has walls, it can make ranged attacks against enemy
   units using a City Ranged Strength stat"* — a garrison alone is not
   enough. Source: <https://civilization.fandom.com/wiki/City_combat_(Civ6)>,
   and the Civilopedia entry for City Combat
   (<https://www.civilopedia.net/en-US/gathering-storm/concepts/combat_9/>)
   carries the same sentence.
5. **The city ranged strike has Range 2, subject to line of sight.** This is
   the number Erik asked to be researched and cited. Source: the same Civ 6
   wiki City combat page — *"the city's ranged strike has a Range of 2, but
   unlike in Civilization V, it is subject to line-of-sight rules"*. Both
   halves are implemented: canonical hex distance, and
   `Map.check_line_of_sight`. The Civilopedia page confirms the Walls
   requirement but does not state the range; the wiki is the source for the
   2. Direct fetches of the Fandom pages returned HTTP 402 during this work —
   the quotes above come through search-result extracts of those pages, not
   from a page render.
6. **Cities repair 20 HP per turn unless under siege.** Civ 6 / Civilopedia:
   a garrison heals 20 HP per turn unless under siege.
7. **Siege (blockade).** Civilopedia, City Combat, verbatim: *"The City
   Center and other defensible districts like the Encampment are considered
   under siege if all 6 tiles around them are occupied by enemy units, under
   enemy Zone of Control, or are impassable due to mountains or Natural
   Wonders. In these circumstances, the district will not recover lost
   health."*

**Zone of control is new, and deliberately partial.** It did not exist in
this engine. It is added only in the narrow form siege needs: a tile is under
a player's ZoC when it is adjacent to one of that player's land military
units, and **ZoC does not cross a river** (the same shared-edge test
`Unit.step_cost` uses for the crossing surcharge). Ranged units do not
project it (`[combat] zone_of_control_from_ranged = false`, Civ 6's rule).

> **ZoC has NO movement effect here.** In Civ, entering an enemy zone of
> control ends a unit's movement. That rule is a separate and much larger
> change and is **not implemented**. Nothing in this engine should be written
> as though full ZoC exists.

Consequence, pinned by tests: three well-spread units blockade a city and
three bunched on one side do not, because a unit on the ring covers three of
the six tiles (its own by occupation, its two ring neighbours by ZoC). Two
units exactly opposite each other also cover all six — surprising, but a real
property of the model rather than a bug.

**Numbers, all in `config.toml`.**

| Key | Value | Where it comes from |
|---|---|---|
| `[city] ranged_building` | `"Walls"` | Civ 6 gates the city strike on Walls |
| `[city] ranged_strength` | 25 | Civ 6 derives City Ranged Strength from the strongest ranged unit built; with no tech tree (#41/#76) the Ancient-era stand-in is `[units.Archer] ranged_strength` |
| `[city] ranged_range` | 2 | Civ 6, cited above |
| `[city] heal_per_turn` | 20 | Civ 6, cited above |
| `[combat] zone_of_control_from_ranged` | `false` | Civ 6 projects ZoC from melee, anti-cavalry and mounted units, not ranged |

**Divergences from Civ 6, stated rather than hidden.**

- **Walls are +30 defence, not +3 combat strength.** Civ 6's Ancient Walls
  add 3 combat strength (and their own HP pool); issue #7 specified +30
  defence here and this patch does **not** change it. On this engine's
  strength scale — Warrior 20, city base 20 — +30 is a much larger effect
  than Civ 6's +3. Flagged, unchanged, and left as a balance decision.
- **No wall HP pool.** Civ 6 models walls as a separate health bar with
  per-class damage multipliers; #66 deferred that and it stays deferred.
  Walls contribute defensive strength only, which is also why the Battering
  Ram and Siege Tower remain in `DEFERRED_BUILD_UNITS` — there is still no
  wall to break.
- **The city's ranged strike is automatic**, fired once at the start of its
  owner's turn at the weakest enemy unit in range and sight (ties broken by
  coordinates, so it is reproducible). Civ 6 makes it a player order. The
  action space here selects a *unit* and names a tile; giving a city an order
  would change that action space, which is the kind of change #82 and #84
  keep separate. Automatic firing is the only way the rule is reachable at
  all, and an unreachable rule is what this issue is about.
- **City ranged strength is flat**: no health penalty (a unit's ranged
  strength drops as it is damaged; a city's does not here) and not derived
  from what the player has built.
- **"Impassable" for siege means no *land* unit could stand there** —
  mountains and, since there are no naval units, water. A coastal city is
  therefore besiegeable from land alone, where Civ 6 needs ships.
- **At least one ring tile must actually be held or controlled by an enemy**
  for a city to count as besieged. The Civ wording alone would leave a city
  ringed by mountains permanently besieged by nobody and never healing.
- **The garrison's own healing is unchanged.** Civ 6 stops the garrisoned
  unit healing under siege too; only the city's repair is gated here.

**No encoder change (#82).** Cities are still encoded as coordinates only —
no health, no walls. Adding a city-HP channel changes the channel count for
every encoder and is a separate decision. This is survivable because the
**action mask leaks the needed signal**: "move onto the city" becomes legal
exactly when its health reaches 0. Said plainly: **an agent cannot see how
damaged a city is until it is at 0.** It can see that the tile is a legal
attack, and then, once the city falls, that the same tile is a legal capture.
Any finer judgement — is this city nearly down, is it worth one more
Catapult — is invisible to it under the current encoders.

**The mask.** Once capture requires 0 HP, moving onto a city above 0 is an
order the engine refuses, and a refused order consumes nothing and changes
nothing — issue #51's livelock, which truncated 85 training episodes and 50
of 200 eval games. So the city tile now carries exactly one meaning at a
time: an attack while health is above 0, a capture move once it is 0, never
both, and the capture only for a unit that can hold the city and pay the
step. Enemy cities are also ranged targets within range and line of sight
(without which the siege class would be adjacent-only), and a city already at
0 is not a ranged target at all. `civulator/tools/recording.py` highlights
human clicks with the same two functions, so the tool and the agent cannot
drift apart.

**Comparability.** This is a rule change in the same bundle as
#67/#7/#59/#66/#74 and invalidates policy comparisons across it in the same
way: trained weights still load (`check_version` gates on major.minor), but a
policy trained when cities fell to a walk-in has never met a city that
fights. Recorded scenarios keep their terrain; recorded *orders* against
cities now mean something different and have not been re-validated.

New tests: `tests/test_city_combat.py` (17), `tests/test_city_capture.py`
(14), `tests/test_city_ranged_attack.py` (13), `tests/test_city_siege.py`
(28), `tests/test_mask_city_orders.py` (6). Suite 588 -> 666 passed, 1
skipped.

Three existing tests changed deliberately, each named in its commit:
`test_episode_stats.py::test_found_and_capture_city_counters` (walked into a
full-health city to reach the capture counter; now reduces it first),
`test_mask_no_op_actions.py::_observables` (did not include city health, so a
legal bombard read as a no-op) and
`test_mask_vectorization.py::_reference_get_valid_moves_mask` (the pre-#42
reference copy, which has to track deliberate rule changes made after it).
`test_city_combat.py::make_env` keeps an idle unit on the board so a
single-attack test does not roll the turn over into the defender's repair and
return fire.

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

### Housing and the Palace (#88)

**Rule change, effect NOT yet measured.** Spec: `docs/housing_design.md` (v2).
Source: the Civilization Wiki,
[Housing (Civ6)](https://civilization.fandom.com/wiki/Housing_(Civ6)).
Population growth used to be unbounded; now a city's housing limits it.

- **Water tiers** at the city centre: fresh 5, coastal 3, dry 2 (`[housing]`).
- **Buildings and improvements declare `housing`** in their own config table:
  Granary 2, Palace 1; Farm, Pasture, Plantation, Camp and Fishing Boats 0.5,
  counted only on tiles the city owns within `improvement_radius` (3), one
  improvement per tile (the largest). `housing(city)` (`game/housing.py`) is
  the only computation, in integer tenths.
- **Growth bands** (`[housing] growth_bands`), keyed on housing minus
  population: >= 2 keeps 100 % of a positive food surplus, >= 1 keeps 50 %,
  > -5 keeps 25 %, otherwise 0 % (**hard cap** at housing + 5: no growth even
  with a full bucket). Starvation is unchanged; housing never removes
  population.
- **Exact arithmetic.** The growth bucket `City.food_surplus` is now in
  hundredths of food (`+= food_net * percent`; growth at `100 * threshold`), so
  a 1-food surplus at 25 % still accumulates. Percents must be ints and band
  mins strictly descending, or loading raises.
- **Palace.** Each player's first city gets a Palace (housing 1); it is never
  buildable. **The Palace stays with the city on capture** (Erik's deliberate
  departure from Civ 6): a conqueror can hold several, the old owner gets no
  replacement.
- `[buildings.*] production_cost` is now optional; absent means never
  buildable (the silent default of 100 is gone).
- New per-player episode stat `growth_slowed_turns`: city-turns with a
  positive food net whose band was below 100 %.

**Accepted gaps.** Improvement housing is dormant in play until Workers can
build improvements; the Aqueduct waits for districts (#86); amenities are out
(#41).

### Districts framework (#86)

**Engine only; effect NOT yet measured.** Spec and rulings:
`docs/districts_design.md` (v3). No agent can place or build a district until
the action space is redesigned (#99), as with `swap_tile` (#87).

- **Districts occupy a tile** and earn an adjacency score from their
  neighbours (Civ 6 Gathering Storm values, copied, no tuning). Ten districts
  in `[districts.*]`: Campus, Commercial Hub, Theater Square, Holy Site,
  Industrial Zone, Harbor, Encampment, Entertainment Complex, Government Plaza,
  Aqueduct. Rows are floored one by one, then summed; the city centre and
  placed-but-unfinished districts count as neighbours.
- **Two steps.** `GameEnvironment.place_district` checks `can_place_district`,
  locks the cost, clears the tile's improvements, a removable feature
  (Woods, Rainforest, Marsh) and a bonus resource, and points production at it;
  `City.process_turn` pays the cost like a building and completes it.
  `produce_district` resumes an unfinished one. A district tile is never
  worked, cannot be swapped, built on or settled.
- **Limits**: 1 + floor((pop - 1) / 3) slots (the Aqueduct takes none),
  `max_per_city`, `max_per_player` (Government Plaza), all counted on placed
  districts.
- **Aqueduct housing**: water = max(6, water + 2), so fresh 5 -> 7, coastal
  3 -> 6, dry 2 -> 6; a district may also declare a flat `housing`.
- **Yields are computed and reported, not consumed.** `district_yields(city)`
  sums the live score of complete districts per yield; `culture()` and
  production are unchanged. New per-player stats `district_yield_<name>`.

**Rulings (Erik, 2026-10-11).** The ten districts above; Government Plaza is
only an adjacency source with a one-per-player limit; yields wired in by later
patches, one per yield; every district stays with its city on capture,
Government Plaza included, as with the Palace (Civ 6 removes it). Claude's
calls: a placed district counts as a neighbour; bonus resources are cleared on
placement; a foreign unit on the tile blocks placement.

**Accepted gaps.** Costs do not escalate with tech (no tech tree, #90);
a complete Theater Square or Industrial Zone produces no culture or
production in play; drought protection and geothermal amenity have no
counterpart; Civ 6 adjacency rows whose source is absent (wonders, natural
wonders, Dam, Canal, strategic resources) are dropped; Neighborhood, Water
Park and the other districts are not in; nothing is drawn in the viewer.

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
