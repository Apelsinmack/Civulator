# Critique, lens 1: systems reuse, regression, determinism

Document: `docs/districts_religion_design.md` v1 (commit 444d94a). Critic:
Claude (Opus), 2026-10-22. Every claim was checked against the code at that
commit; file:line references are to it.

**Verdict: survives with fixes — 9 blockers.**

## Blockers

1. **`matches` does not accept a resource class.** §2.2 and §5.1 say
   "`terrain_model.matches`'s `resources` key already accepts a class name
   (districts design v3)". It does not: `_match` tests
   `resource not in on["resources"]` against names only
   (`civulator/terrain_model.py:191-199`), and `validate_on_table` admits only
   `set(RESOURCE_TABLE) | {"any"}` (`terrain_model.py:240`). Districts design
   v3 *planned* class names (`docs/districts_design.md:291`) but the code
   shipped names and `"any"` only. So the Industrial Zone's strategic row
   (Q4) cannot be written as specified. **Fix:** extend `_match` and the
   load-time name check to accept a class name (and refuse a resource named
   like a class). That is a change to the canonical `on` evaluator, so it
   goes into Q1 (Opus), not Q4.

2. **The access predicate contradicts itself and has no data to work
   from.** §2.2 says a tile is accessed when it has "any improvement in
   `tile.improvements`, since only an admitted improvement can stand
   there". §2.1, §10 and §11 row 1 say a Farm on Niter does not count. Both
   cannot hold. Improvement `on` tables also cannot name a resource
   (`terrain_model.py:170-174`, `_validate_config_on_tables`
   `terrain_model.py:381-390`), and Farm, Plantation, Camp and Pasture all
   admit Grassland/Plains flat (`config.toml:453-485`). "The improvement
   whose `on` admits the tile" is therefore never unique: under the "any"
   rule a Farm grants Horses, Wine and Silk. **Fix:** add one column,
   `[terrain.resource.<Name>] improved_by = [...]` (validated against
   `IMPROVEMENT_NAMES`), read only by `player_has_access`. A luxury is then
   still "one table", just with one more column.

3. **The §2.4 mapgen spec cannot be built in `place_resources`, and it
   would move `starts`.**
   - Start fertility *does* score resources. `_yield_sum_grid` composes
     each tile's resource into its food+production
     (`civulator/mapgen/starts.py:140-153`), and `_is_settleable` /
     `_passable_ring1_count` compose it too (`starts.py:190-203`). Any new
     resource with a food or production yield, placed where
     `place_resources` runs today (before starts,
     `civulator/mapgen/earthlike.py:247` then `:266`), changes fertility,
     then regions, then `starts`. The promised golden diff ("`starts`
     unchanged") would then be false.
   - The region partition exists only inside `generate_starts`
     (`starts.py:821-826`), after resources are placed, and is not
     returned. The rules "one luxury type per region" and "every start
     region has Horses and Iron" cannot run inside `place_resources`.
   - There is no "founding ring" rule for the bonus tier.
     `place_resources` is a pure per-tile hash (`mapgen/resources.py:61-94`),
     and normalization *adds* resources next to starts
     (`starts.py:752-798`).
   - The fairness rule is conditional on what a region already holds, so
     it is not order-free. It is a sequential stage, the kind design
     §4.2 rule 3 allows only by name.

   **Fix:** place the luxury and strategic tiers in a new stage *after*
   `generate_starts`. `generate_starts` returns its regions, and the stage
   ranks candidates by `tile_roll01` with new purpose ids appended to
   `seeding.py`, total sort keys, and regions processed in start order. It
   is declared as the third sequential mapgen stage. Then fertility, regions
   and `starts` really are unchanged, and the golden diff is `resource` plus
   `params` only.

4. **An Encampment can never be attacked or breached as written, and the
   melee move-in walks past its entry refusal.**
   - `_step_inner` sends an order to `_execute_attack` only for an enemy
     unit or for `_get_enemy_city_at` (`civulator/game/environment.py:561-578`).
     There is no branch for a district. An order on an empty enemy
     Encampment falls through to `Unit.move`, which §4.2 makes refuse. The
     result is an invulnerable wall and an `invalid_action` no-op.
   - The order mask offers an attack only on enemy units and cities, for
     melee (`civulator/agents/networks.py:521-551`) and for ranged
     (`networks.py:569-591`).
   - The "four-attribute defender protocol" is incomplete. `Unit.attack`
     reads `target.is_city` for both the ranged-vs-city penalty and the
     floor at 0 (`civulator/game/unit.py:647, 665`). It calls
     `get_combat_strength(is_attacking, target)` with two arguments
     (`unit.py:650-652`). `District` has no `player` and no `health`
     (`civulator/game/districts.py:52-60`).
   - After a kill, the melee move-in checks only `enemy_city_blocks`
     (`environment.py:686-690`). Killing a unit that stands on a healthy
     enemy Encampment moves the attacker onto it, bypassing `Unit.move`.
     This is the exact #84 failure that `_capture_city`'s docstring names.

   **Fix:** add one lookup, e.g. `GameEnvironment.enemy_fortification_at(coords)`
   with a `Unit.enemy_fortification_blocks` beside `enemy_city_blocks`.
   Every one of these reads it: the dispatcher, both mask loops, both
   branches of `Unit.move`, the move-in, and `defaults.step_toward`
   (`civulator/game/defaults.py:157-189`). The protocol becomes `health`,
   `player` (through a back-reference to the city, so capture and flip
   carry it), `coordinates`, `get_combat_strength(is_attacking, target)`,
   and the flag `Unit.attack` reads.

5. **Cross-domain melee is unreachable, and its move-in condition does not
   exist yet.** §6.5 says the move-in after a kill happens "only when the
   attacker `can_enter` the vacated tile — the existing branch's
   condition, made explicit". The existing branch has no such condition
   (`environment.py:686-690`), so a Galley that kills a coastal Warrior
   would move onto land. The order mask also skips any tile the unit
   cannot enter *before* it looks for enemies (`networks.py:516-519`). A
   Warrior is therefore never offered an adjacent Galley, and a Galley
   never a coastal unit or city.

   Separately, the player-dependent domain has two sources. §6.3 puts it
   in `Unit.get_movement_domain()`, but spawning uses the static
   `movement_domain(unit_type)` (`unit.py:134-136`, read by
   `City.complete_unit_production`, `civulator/game/city.py:466`), which
   cannot see the player. A Galley built before Cartography could
   therefore spawn on Ocean that its own domain forbids.

   **Fix:** make it `movement_domain(unit_type, player)` as the single
   source, with `get_movement_domain` delegating to it. Have the mask test
   for an enemy before the `can_enter` gate for melee attacks. Write the
   `can_enter` clause into the move-in.

6. **Sea routes through `path_finder` depend on unit positions, and the
   overseas bonus changes existing land routes.**
   - `Map.path_finder` always blocks occupied tiles
     (`civulator/game/map.py:546-557, 583`). Whether a pair of cities
     qualifies as a sea route would then flicker with every ship parked on
     the coast. An enemy could block a route by parking a ship, and the
     trade mask would read unit positions.
   - §6.6 applies ×2 to "a route whose two cities lie on different
     landmasses". Land routes need no path (`civulator/game/trade.py:188-210`),
     so any existing route across a strait within range 15 doubles with no
     Harbor. That is an undeclared change to today's trade, and it
     contradicts §10's "a strait rewards the Harbor pair".
   - The Trader default ranks destinations with `pair_yields`
     (`defaults.py:150`), not `route_yields`. A multiplier placed in
     `route_yields` (§15(b)) would be invisible to it, which breaks "an
     idle Trader finds the overseas route by itself".

   **Fix:** decide sea reachability from terrain alone: a BFS over the
   `"coast"`/`"water"` cost grid with no occupancy, cached on
   `terrain_epoch`, with path length in tiles. Pay the overseas bonus on
   sea routes only (or declare the land-route change in the CHANGELOG).
   Put the multiplier in `pair_yields`.

7. **`improvement_yield`'s named consumer, `Tile.yields`, cannot carry the
   kind and would poison an epoch-keyed cache.** `Tile.yields` is food and
   production only (`civulator/game/tile.py:74-86`), so Stone Circles
   (faith 2) and God of the Open Sky (culture 1) cannot be expressed
   there. It is also player-blind and is read by the encoder's terrain
   block, cached on `(map_uid, terrain_epoch)`
   (`civulator/agents/state_encoders.py:458`), and by `claim_rank`
   (`civulator/game/territory.py:56`). An owner-dependent `Tile.yields`
   goes stale the moment a pantheon is chosen, because nothing bumps the
   epoch. That breaks CLAUDE.md's Terrain-epoch row. **Fix:** make the
   consumer `game/yields.py`, over the centre and worked tiles (beside
   `_tile_yield` / `_tile_gold_tenths`, `yields.py:98-120`, for all six
   yields), and leave `Tile.yields` untouched.

8. **`Map.landmass_id` duplicates an existing landmass BFS.**
   `starts._find_landmasses` (`starts.py:224-257`) already computes
   connected land-domain components with hexmath adjacency and wrap,
   mountains included. §15(b) would register a second one as "the only
   continent test". **Fix:** promote `_find_landmasses` to a public pure
   kernel, and have `Map.landmass_id` cache its result on `terrain_epoch`.
   Then mapgen and sea trade share one definition of a landmass.

9. **The version gate stays open for eight patches.** Q1 changes
   `MapData.resource` on every seeded world and makes Swordsman/Horseman
   resource-gated. `__version__` stays `"0.8.1"` (`civulator/__init__.py:3`),
   while the plan only "opens v0.9.0 in the CHANGELOG" at Q1 and dates it
   at Q9. `check_version` compares the major.minor of `__version__`
   (`civulator/meta.py:115`). Through Q1–Q8, a 0.8 scenario or recording
   therefore loads without a refusal into worlds and rules it was not made
   in. The precedent is #116 P1, which bumped `__version__` to 0.8.0 and
   regenerated the fixture in the first patch
   (`docs/progression_design.md:1157`). **Fix:** Q1 sets
   `__version__ = "0.9.0"` and regenerates `tests/fixtures/scenario_fixture.json`.
   Q9 only dates the entry.

## Non-blocking

- `City.place_new_unit` (§4.1, §6.4, §11) does not exist. The routine is
  `City.complete_unit_production` (`city.py:459-491`).
- §4.2 says both "repairs unless an enemy is adjacent" and "`is_city_under_siege`
  generalised to a tile". The real test is Civ 6's full ring: every ring
  tile held, under ZoC or impassable, with at least one contested
  (`environment.py:737-768`). Pick one. Also, that function's premise
  "since there are no naval units, water [is impassable]"
  (`environment.py:740-745, 759`) stops being true in Q5, and ships never
  count for a blockade. Say so in the CHANGELOG.
- `city_ranged_attack` with an origin also needs `_bombard_target` to take
  the origin (`environment.py:808-822`; it reads `city.coordinates` and
  `city.get_range()`). State the strike order: centre first, then the
  Encampment. §15(a)'s "Engine RNG: nothing here draws" is false. Every
  Encampment strike and every attack on one draws `env.rng` through
  `calculate_damage`. That is deterministic, but it shifts the RNG stream.
- Amenities on production: production's percent scaling lives in
  `City.calculate_production` (`city.py:291-303`), and `city_yield`
  returns production unscaled (`yields.py:140-141`). The amenity percent
  for production belongs there, so the draft row's "never a fourth reader"
  is wrong from the start.
- `loyalty.parse_bands` cannot be shared as it stands. It bounds mins to
  0..maximum, refuses negative percents and fixes three columns
  (`loyalty.py:80-102`). The amenity bands have negative mins and percents
  and four columns.
- There is no `territory.border_cost`. The cost is a player-blind,
  per-n-memoised `cost(n)` (`territory.py:95-121`). `border_cost_percent`
  has to be applied where the claiming city is known (`run_border_phase`),
  not inside `cost(n)`.
- Crusade and Defender of the Faith: `combat_strength_amounts(player,
  applies, city)` and `Unit._effect_strength_amounts()` take no target or
  tile (`effects.py:763-775`, `unit.py:422-428`). The new attributes need
  that signature widened. Also apply them in `get_ranged_strength` ("both
  roles"). `scope = "all"` in §7.3 means `applies_to = ["all"]`, since
  `scope` is player|city. Add the matchup oracle to Q8's gate.
- Beliefs need a new effect source. `SOURCES` is fixed
  (`effects.py:59-66`), and `parse_effect` refuses `scope = "city"` on any
  source that stands in no city. Follower beliefs are "scope city" and
  reach only consumers that pass a city, so restrict them to such kinds at
  load.
- Jesuit Education: faith categories unlock units only
  (`civulator/game/purchasing.py:116-119`), and `FAITH_CATEGORIES` lives in
  `unit_model.py:586-597`. Building categories need a new branch there,
  not just "two more categories".
- Two naval classes: `UNIT_CLASS_INDEX = {... CLASS_CHANNEL[cls] ...}`
  raises KeyError at import for an unmapped class
  (`state_encoders.py:33-40`). Q5 must map them, to -1 or to an existing
  channel, because a new channel changes encoder depth (R9). `FIGHTING_CLASSES`
  is derived (`unit_model.py:436`), so ships fall into the `land_military`
  faith category (`unit_model.py:595`) and into `is_garrisoned` unless
  excluded.
- `BUILD_OPTIONS` is never named. Galley, Quadrireme, Caravel and Arena
  must be appended (or listed as deferred). That grows `NUM_BUILD_CHANNELS`
  for new build heads, which is allowed by the append-only contract but
  worth saying under R9.
- The Great Lighthouse's "+1 movement for naval units" needs a ninth
  effect kind, since no movement kind exists in `CONSUMERS`
  (`effects.py:101-134`). The "eight kinds" count is off by one.
- The religious-victory branch belongs in `victory.decisive_outcome`
  (`victory.py:168`), so that `game_over` ends the game, not only in
  `determine_outcome`.
- Pre-existing tests that resource gating breaks:
  `tests/test_build_options.py:63-104` assert that the Swordsman is
  producible and offered with its tech alone on a flat env. Q1 updates
  them as a declared rule change, not as a surprise. The `basic`
  generator never runs `place_resources` (`mapgen/basic.py:14-21`), so on
  basic worlds (many tests, the matchup board) every gated unit is
  unbuildable forever. The fairness rule covers earthlike only.
- Access can be lost (capture or flip of the resource city). Say what
  happens to a gated unit already in production; nothing re-checks it at
  completion today.
- Religion state missing from §7.1: the per-city conversion streak
  (candidate religion plus count), the per-player spread-use counter, and
  the lapsed flag. All of them go in `Player.reset_state` / the episode
  fingerprint (`player.py:16`, `tests/test_determinism.py:111-132`). Name
  the tie-break for "strongest foreign pressure", e.g. lower founder index.
- Plan ordering:
  - the Dam's `amenity` column (Q4) needs Q2;
  - Zen Meditation (Q8) needs Q2's `amenity` kind;
  - `religion_param`'s consumer (`religion.pressure`, Holy Order's cost)
    is Q9, so Q8 puts it in `DEFERRED_KINDS` for one patch
    (`effects.py:137-139`) or the enhancers move to Q9.

  "Q7–Q9 need nothing but the kinds they add" does not hold.
- Faith pools are int tenths (`player.py:37-43`), so every religion cost
  is compared ×10.
- `adjacency_score(district_type, coords, game_map)` takes no owner
  (`districts.py:156`). `adjacency_row` must thread one in. There is only
  one caller (`districts.py:192`), so it is cheap.
- The new `frequency` column sits beside the existing `chance`
  (`mapgen/resources.py:83`). Say which one the new tiers read.
- The matchup headline is six units (`scripts/matchup_matrix.py:167`), not
  seven.
- `landmass_id` on `terrain_epoch` rebuilds after every improvement
  (`tile.py:135-150` bumps the epoch). That is correct, just not free.

## Checked and fine

- R1: `place_district` clears improvements (`environment.py:1231`).
- R5: `_neighbour_matches` reads the district type, never the owner
  (`districts.py:118-124`).
- Cost grids are keyed `(map_uid, terrain_epoch, domain)` (`map.py:497`),
  so `"coast"` is simply a third grid. `path_finder` takes `domain`
  (`map.py:559`).
- `can_capture_city` requires land domain (`unit.py:271-275`), so ships
  cannot capture and nothing changes for the capture rule.
- `projects_zone_of_control` is land-only (`unit.py:305-309`).
- The `loyalty` kind's `range` from a wonder of scope player is legal
  (`effects.py:523-536`), so the Colosseum works. `is_garrisoned` exists
  (`loyalty.py:209`).
- `set_owner` ends routes touching the city (`city.py:504-551`).
- Round-end phase discipline (phase-start state, city-id order,
  `environment.py:894-920`) has room for `_religion_phase` after
  `_loyalty_phase` and before `_update_done`.
- `economy_phase` is written for inserted steps (`environment.py:1660-1691`).
- `player_can_build` is the one unit predicate behind produce, the mask
  and purchase (`city.py:154-170`), and behind `upgrade_unit` (through
  `can_upgrade`).
- `_bombard_target` has a total tie-break (`environment.py:808-822`).
- The matchup headline has no naval unit, and its board is Plains. Class
  rows that name naval targets cannot touch an existing pairing.
- The `BUILD_OPTIONS` tests pin only the prefix
  (`tests/test_worker_default.py:712-727`, `tests/test_build_options.py:309-315`),
  so appending is safe.
- `resource_class` is the one class accessor (`terrain_model.py:258`), and
  `DEFERRED_KINDS` exists for a kind whose consumer is one patch away.
