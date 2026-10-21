# Districts (#86): design

> **Status: implemented** (D1 + D2, 2026-10-11). **v3** is the build contract. Rulings agreed with Erik (§9); two Opus critique lenses resolved in "v3 fixes". Erik's rulings so far (chat,
> 2026-10-11): follow Civ 6 for adjacency and copy its values; no tuning before
> the milestone plays; no agent action yet (the action space waits until all
> game changes of milestone D are done, #99); what is done *inside* a district
> (buildings, specialists) is designed later. The four further rulings are in §9.
>
> Civ 6 facts: Gathering Storm ruleset, final patch 1.0.12.68, read from two
> independent dumps of the game database (they agree on every row compared) and
> cross-checked against the Civ 6 wiki. Sources at the end.

## Goal

Districts are city extensions that **occupy a map tile** (Civ 6). Where one is
placed matters because of **adjacency**: each district earns a score from what
surrounds its tile. This patch builds the framework every district plugs into:
one config table per district, one adjacency scorer, one placement check, and
the engine path that places and completes a district. It ships the Aqueduct as
the first district with a full effect.

The framework is in the engine only. No agent can place a district until the
action space is redesigned (#99), exactly as `swap_tile` shipped in #87.

## In scope

1. A config table per district: cost, limits, placement rules, adjacency rows,
   and what its adjacency score becomes.
2. `adjacency_score(district_type, tile)`: the one adjacency computation.
3. `can_place_district(city, district_type, tile)`: the one placement check.
4. `GameEnvironment.place_district` and the production path that completes a
   district.
5. District yields computed and reported, not yet consumed (§5).
6. The Aqueduct's housing effect (§6).

## Out of scope

| Item | Where |
|---|---|
| An agent action to place or build a district | #99, after all milestone-D game changes |
| Buildings inside districts, specialists, great-person points | later, per district (#90–#95) |
| Consuming any district yield (culture, production, science, gold, faith) | one later patch per yield. Adjacency is computed and reported only (§5) |
| Cost escalation with tech/civic progress | needs a tech tree (#90). The hook exists; progress is 0 (§4.3) |
| Tech prerequisites | needs a tech tree. Every configured district is available |
| Encampment defence, pillaging, district combat | later |
| Neighborhood (needs Appeal), Water Park, Dam, Canal, Spaceport, Aerodrome, Preserve, Diplomatic Quarter | their systems are not in the game (#97 decides Neighborhood) |
| Drawing districts in the viewer / painting them in the scenario painter | later; nothing in play can build one yet |
| Encoder channels | the input-space design (#111) |

---

## 1. Districts and their config

One table per district in `config.toml`:

```toml
[districts]
population_per_district = 3   # specialty districts allowed = 1 + floor((pop - 1) / 3)
cost_progress_factor = 9      # cost = base * (1 + 9 * P); P = 0 until tech exists (§4.3)
removable_features = ["Woods", "Rainforest", "Marsh"]   # cleared on placement
allowed_features = ["Floodplains"]                      # kept on placement

[districts.Campus]
production_cost = 54
cost_model = "discounted"     # "discounted" | "progress" | "fixed"
discount_percent = 40
counts_toward_limit = true    # takes one of the population slots
max_per_city = 1
adjacency_yield = "science"   # what the score becomes (§5)
adjacency = [
    { amount = 1, per = 2, district = "any" },
    { amount = 1, terrain = { relief = ["mountain"] } },
    { amount = 1, per = 2, terrain = { features = ["Rainforest"] } },
    { amount = 2, terrain = { features = ["Reef"] } },
    { amount = 1, district = ["Government Plaza"] },
]
```

The districts in this patch (§9), with Civ 6's values:

| District | Cost (model) | Limit slot | Score becomes | Placement beyond the general rules |
|---|---|---|---|---|
| Campus | 54 (discounted 40 %) | yes | science | — |
| Commercial Hub | 54 (discounted 40 %) | yes | gold | — |
| Theater Square | 54 (discounted 40 %) | yes | culture | — |
| Holy Site | 54 (discounted 40 %) | yes | faith | — |
| Industrial Zone | 54 (discounted 40 %) | yes | production | — |
| Harbor | 54 (discounted 40 %) | yes | gold | on Coast or Lake, adjacent to land, not on Reef |
| Encampment | 54 (discounted 40 %) | yes | none | not adjacent to the city centre |
| Entertainment Complex | 54 (discounted 40 %) | yes | none | — |
| Government Plaza | 30 (discounted 25 %) | yes | none | one per player |
| Aqueduct | 36 (progress) | **no** | none | adjacent to the city centre, and adjacent to a river (on an edge not shared with the centre), a lake, an oasis or a mountain |

The cost models are explained in §4.3.

### 1.1 Adjacency rows (Civ 6 Gathering Storm)

A row is `amount` per `per` matching neighbours (`per` defaults to 1). Each row
is floored on its own, then rows are summed: `floor(count / per) * amount`
(Civ 6: an Industrial Zone next to one Mine and one district gets 0, not 1).
Scores are integers.

| District | Rows |
|---|---|
| Campus | +1 per Mountain · +1 per 2 Rainforest · +2 per Reef · +1 per 2 districts · +1 per Government Plaza |
| Commercial Hub | +2 if a river runs along any edge of its own tile · +2 per Harbor · +1 per 2 districts · +1 per Government Plaza |
| Theater Square | +2 per Entertainment Complex · +1 per 2 districts · +1 per Government Plaza |
| Holy Site | +1 per Mountain · +1 per 2 Woods · +1 per 2 districts · +1 per Government Plaza |
| Industrial Zone | +2 per Aqueduct · +1 per Quarry · +1 per 2 Mines · +1 per 2 districts · +1 per Government Plaza |
| Harbor | +2 if adjacent to the city centre · +1 per resource on an adjacent water tile · +1 per 2 districts · +1 per Government Plaza |
| Encampment, Aqueduct, Entertainment Complex, Government Plaza | none of their own; they are sources for others |

"Districts" in the generic row means every adjacent district, **the city
centre included** (Civ 6), placed or complete (§3).

**Civ 6 rows dropped because their source does not exist here**, to be added
with the content that brings them: natural wonders, Geothermal Fissure,
Pamukkale, Great Barrier Reef, wonders (Theater +2), Lumber Mill and strategic
resources (Industrial Zone), Dam and Canal (Industrial Zone +2). A row may
only name a terrain layer, improvement or district that exists, and loading
raises otherwise (§1.2), so a dropped row cannot sit in config pointing at
nothing.

### 1.2 Row sources

A row has exactly one source:

| Source key | Counts a neighbour when | Example |
|---|---|---|
| `terrain = {...}` | it matches the mapping, in `terrain_model`'s `on` form (`bases` / `relief` / `features`, plus a new `resources` key (names or `"any"`), §8) | Mountain, Woods, sea resource |
| `improvement = [...]` | it has one of these improvements | Mine, Quarry |
| `district = [...]` or `"any"` | it holds one of these districts (`"City Center"` names a city centre); `"any"` = any district or city centre | Aqueduct, Harbor |
| `river_on_tile = true` | not a neighbour count: true once if a river runs along any edge of the district's own tile | Commercial Hub |

Loading validates every row: one source; every name exists in its table;
`amount` and `per` are positive ints. Unknown keys raise.

---

## 2. Placement

`can_place_district(city, district_type, coords)` (in `game/districts.py`) is
the only placement check. General rules (Civ 6):

- the tile is **owned by this city** (`Map.owner_city`) and within
  `territory.WORK_RADIUS` (3, the same number as Civ 6's district radius);
- it is not a city centre, holds no district, and is not adjacent to **another**
  city's centre;
- it is not impassable (mountains);
- land, unless the district's own `on` mapping says otherwise (Harbor);
- its feature, if any, is in `removable_features` or `allowed_features`
  (Oasis, Ice and Reef therefore block placement);
- its resource, if any, is of class `bonus` (luxury and strategic resources
  block; none exist yet);
- the city does not already have `max_per_city` of this type, and the player
  not `max_per_player`;
- a `counts_toward_limit` district needs a free population slot:
  `1 + floor((population - 1) / population_per_district)` minus this city's
  placed `counts_toward_limit` districts;
- the district's own rules: `on` (terrain mapping for the tile itself),
  `adjacent_to_city_center = true | false` (Aqueduct requires it, Encampment
  forbids it), `requires_adjacent` (a list of sources, as in §1.2, of which at
  least one must match a neighbour; for the Aqueduct the river source is
  `river_edge_not_shared_with_center = true`).

---

## 3. Placing and completing a district

Civ 6's two steps, kept:

1. **Place.** `GameEnvironment.place_district(city, district_type, coords)`
   checks `can_place_district`, then:
   - creates a `District(type, city_id, coords, complete=False, cost=...)`,
     linked from `tile.district` and `city.districts` (§7), the only two
     references, written only here and in `remove_city`;
   - clears a removable feature, the tile's improvements and its bonus
     resource through `Tile.set_layers(..., map_ref=map)` (so the terrain epoch
     bumps) (**Claude's call**: Civ 6 removes features and improvements; for bonus
     resources the sources did not say, and removing them keeps the rule "a
     district tile carries nothing workable");
   - locks the cost (Civ 6 locks it at placement, §4.3);
   - sets `city.current_production = {"type": "district", "district_type": T}`.
2. **Build.** `City.process_turn` pays production into it like a building. When
   paid, `complete = True` and production goes to `None`. Switching production
   away keeps the placed district; `City.produce_district(T)` resumes the city's
   own placed district of type `T` (there is at most one per type per city,
   except for types with `max_per_city > 1`, where it resumes the oldest).
   Production is still one pool per city, as for units and buildings.

A placed district (complete or not):
- is **never worked** by citizens: `assign_tiles` skips its tile (Civ 6: a
  district replaces the tile's yields);
- **counts as a neighbour** for others' adjacency (**Claude's call**: the sources leave this unconfirmed; counting it
  makes a placement's value fixed when it is placed);
- **cannot be swapped**: `swap_tile` refuses a tile with a district (Civ 6);
- **goes with its city on capture**, every type including the Government Plaza
  (Erik, 2026-10-11: "leave it like the Palace"; Civ 6 removes a captured
  Government Plaza). The City object keeps `city.districts`; ownership already
  moves with `City.set_owner`. The conqueror may then hold more than
  `max_per_player` of a type, as with the Palace; the limit binds placement
  only;
- is deleted with its city in `remove_city`.

A district earns yields (§5) and effects (§6) only when **complete**.

## 4. Cost

### 4.1 Discounted (Civ 6 `NUM_UNDER_AVG_PLUS_TECH`)

Let A = the number of `discounted` district types the player can build (all of
them, until techs exist) and B = the player's completed `discounted` districts.
Type T costs `discount_percent` less if B ≥ A and the player's count of T is
< B / A (Civ 6). This makes the rarest types cheaper once the player has
roughly one of each.

### 4.2 Progress and fixed

`progress`: no discount (Aqueduct). `fixed`: the base cost, never scaled
(unused here; Civ 6's Spaceport).

### 4.3 Escalation

Civ 6: `cost = floor(base * (1 + 9 * P))`, where P is the player's progress
through the tech or civic tree, whichever is further. Ours:
`game_progress(player)` returns 0 until #90 brings a tech tree.

**ACCEPTED GAP:** district costs do not escalate. Late districts are not
"free" yet, because there is no late game: no tech, no eras.

The cost is computed once, at placement, and stored on the `District`.

## 5. Yields

A complete district turns its adjacency score into `adjacency_yield`, whole
points per turn. `district_yields(city)` (in `game/districts.py`) returns a
mapping `yield name → summed score` over the city's complete districts, and is
the only place a district's yield is computed. Loading accepts `culture`,
`production`, `science`, `gold`, `faith` and `none`.

**Nothing consumes it yet** (Erik, 2026-10-11: "just calculated what they
produce for now … they get their own patch"). `culture(city)` and
`City.calculate_production` are unchanged; wiring each yield into its consumer
is a later patch per yield. `district_yields` is reported per player in
`episode_stats` (`district_yield_<name>`, summed per turn) so the patch that
wires it in has a measured baseline.

**ACCEPTED GAP:** a complete Theater Square or Industrial Zone produces no
culture or production in play.

**Update (#116 P1, 2026-10-21):** the gap is closed. `city_yield`
(`game/yields.py`) consumes `district_yields` for every yield, so culture
reaches `culture()` and production `calculate_production`; science, gold and
faith go to the player pools. Spec: `docs/progression_design.md` §2.1 and
its "v2 fixes".

The score is recomputed from the live map on every call, never cached, so a
later district next door raises an old one's yield (Civ 6).

## 6. The Aqueduct

Civ 6 raises the city's water housing to at least 6, or adds 2 when the city
already has fresh water. With our water values (fresh 5, coastal 3, dry 2):
fresh 5 → 7, coastal 3 → 6, dry 2 → 6. One formula:

```
water = max(water_housing_min, water + water_housing_boost)    # 6, 2
```

declared on the district (`[districts.Aqueduct] water_housing_min = 6`,
`water_housing_boost = 2`) and applied in `housing.py`'s water term when the
city has a complete district declaring them. A district may also declare a flat
`housing` (unused now; Neighborhood later), added like a building's.

The Aqueduct is also a +2 source for an adjacent Industrial Zone (§1.1). Civ 6's
drought protection and geothermal amenity have no counterpart here.

## 7. Data

- `District`: `type`, `city_id`, `coordinates`, `complete`, `cost`.
- `Tile.district`: the `District` on this tile, or `None`.
- `City.districts`: the city's `District`s, in placement order.

Districts are engine state. A seeded game with the same actions reproduces
them; no RNG is involved.

## 8. Code layout

- `civulator/district_model.py`: the only interpreter of `[districts]` (parse,
  validate, defaults), mirroring `unit_model.py` / `terrain_model.py`.
- `terrain_model.matches` gains the `resources` key (names, `"any"`, or a
  resource class), so adjacency and placement test resources through the one
  terrain interpreter.
- `civulator/game/districts.py`: `adjacency_score`, `can_place_district`,
  `district_yields`, cost. Pure: reads the map, config and the city; mutates
  nothing.
- `GameEnvironment.place_district`: the only mutator, beside `remove_city`.

## 9. Rulings (Erik, 2026-10-11)

1. **Districts:** the ten in §1.
2. **Government Plaza:** in, as an adjacency source with a one-per-player limit;
   no government system.
3. **Yields:** computed only (§5); each yield is wired in by its own later patch.
4. **Capture:** every district stays with its city, the Government Plaza
   included, as with the Palace.

## v3 fixes (critique round 1)

Where this section and §1–§8 differ, **this section wins**.

**Tile state and caches**
- `place_district` clears `tile.improvements` **directly** (improvements are not
  a layer). It clears a removable feature and a bonus resource in **one**
  `set_layers(base, relief, feature=None/kept, resource=None, map_ref=map)` call
  (clearing only the feature can raise in `validate`: Deer, Bananas and Rice
  need their feature), and only when there is something to clear.
- New **`Map.district_epoch`**, bumped by every `place_district` and by
  `remove_city` when it clears districts. The settle-layer cache key
  (`agents/state_encoders.py:660`) gains it. Any future cache of
  district-derived state keys on it.
- `place_district` re-runs `city.assign_tiles(env)`, so a worked tile leaves
  `worked_tiles` at once.

**Every path that could put something else on a district tile refuses it**
- `can_found_city_at` refuses a tile with a district (the settle mask follows);
  `create_city` raises on one (covers the painter's `_place_city`).
- `can_build_improvement_at` refuses a tile with a district.
- `swap_tile` refuses a tile with a district (as in §3).
- Invariant: a district tile is always owned by the district's city.

**Placement details**
- Placement is refused if a **foreign** unit stands on the tile (Claude's
  call); own units are fine.
- `max_per_city`, `max_per_player` and the population slot all count
  **placed** districts, complete or not. They bind placement only: an
  incomplete district can still be finished after the city loses population,
  and a conqueror may exceed `max_per_player` (§3).
- The `district = "any"` source counts every adjacent district and city centre,
  **whoever owns it** (Civ 6).
- Aqueduct river test: some edge between the Aqueduct's own tile and a
  neighbour n with `Map.has_river_between` true, where n is **not** the city
  centre. Spelled `river_edge_not_shared_with_center = true`, a district-tile
  test, not a neighbour source.
- Harbor "adjacent to land": `requires_adjacent = [{ terrain = { bases =
  [<the land bases>] } }]`. A mountain counts as land (its base is land).

**`resources` match key** (`terrain_model`)
- `matches(on, base, relief=None, feature=None, resource=None)`. `resources` is
  a list of resource names or `"any"`. Evaluating a mapping that has
  `resources` with `resource` not passed raises (no silent pass).
- `resources` is rejected inside layer and improvement `on` tables at load, and
  every `on` table rejects unknown keys at load. Existing callers keep their
  behaviour: the mapgen golden tests and `test_terrain_model` are in D1's gate.
- Resource class (placement: bonus only) is read through one new accessor,
  `terrain_model.resource_class(name)`.
- Improvement names are validated through a `terrain_model` accessor
  (`IMPROVEMENT_NAMES`), never by reading `CFG["improvements"]` again.

**Config loading**
- `[districts]` scalars and sub-tables are split by the loader. `"City Center"`
  and `"any"` are reserved and no district may take them. Names with spaces are
  quoted in TOML.
- District housing values (`housing`, `water_housing_min`,
  `water_housing_boost`) go through `unit_model.to_tenths`.

**Cost: one integer rule**
- `game_progress(player)` returns a fraction `(num, den)`, `(0, 1)` until #90.
- `escalated = base * (den + factor * num) // den`.
- A = the number of configured `discounted` types (static). B = the player's
  **completed** `discounted` districts across all its cities, captured ones
  included. count_T = the same, of type T. T is discounted iff
  `B >= A and count_T * A < B`.
- `cost = escalated * (100 - discount_percent) // 100` when discounted, else
  `escalated`. Integers throughout; locked at placement.

**Production and capture**
- `produce_district(T)` returns False unless the city has an **incomplete**
  placed district of type T (like `produce_building` refusing a cost-less name).
- On capture the city's incomplete districts, its `production` pool and
  `current_production` go with it unchanged.
- `build_agent.encode_build_state` (`agents/build_agent.py:146`) gains an
  explicit `"district"` branch that raises `NotImplementedError` naming #99, in
  place of a silent `KeyError`.

**Stats**
- `district_yield_<name>` for every accepted yield is declared in
  `_fresh_episode_stats` and accrued once per city per round under the same
  guard as culture (`_culture_round`), so a city captured mid-round is not
  counted twice.

**Smoke determinism**
- The smoke script lists candidate tiles from `Map.tiles_of_city`, sorted,
  before choosing with its seeded RNG.

**CLAUDE.md row amendments** (D2), besides the four new rows: Housing (complete
districts are a declared source; the Aqueduct adjusts the water term through
its declared fields), City economy (district production branch; district tiles
are never worked), Territory (`swap_tile` refuses district tiles; a district
tile is always owned by its city), Action masking (`can_found_city_at` refuses
district tiles; the settle key includes `district_epoch`), Terrain model (the
`resources` match key and the two accessors).

## 10. Tests (properties, each naming the change that breaks it)

| Property | Breaks if |
|---|---|
| Each adjacency row adds `floor(count / per) * amount`, rows floored separately | rows are summed before flooring |
| A row's source is matched through `terrain_model.matches` / improvements / districts; no terrain name appears in `districts.py` | terrain names are read in code |
| A placed-but-unfinished district counts as a neighbour; the city centre counts as a district | either is dropped from the "any district" source |
| Placement refuses: unowned tile, beyond radius, centre, occupied by a district, next to another city's centre, mountain, blocking feature, non-bonus resource, over the population slot, over `max_per_city` / `max_per_player` | any general rule is dropped |
| Aqueduct placement needs the centre next to it and a qualifying water/mountain neighbour; a river on the edge it shares with the centre does not qualify | the Aqueduct rule drifts |
| Placing clears a removable feature and improvements and bumps the terrain epoch | placement mutates tile layers without `set_layers(map_ref=...)` |
| A district tile is never worked; `swap_tile` refuses it | `assign_tiles` or `swap_tile` ignores districts |
| `district_yields` counts only complete districts and follows the live score; `culture()` and production are unchanged by districts | yields read incomplete districts, are cached, or leak into a consumer |
| The discount applies exactly under Civ 6's condition; the cost is locked at placement | the cost is recomputed later |
| Aqueduct water housing: fresh 5 → 7, coastal 3 → 6, dry 2 → 6 | the formula is per case or hardcoded |
| A config row naming a missing terrain, improvement or district raises at load | validation is skipped |
| Captured city keeps its districts; `remove_city` clears its tiles | district references outlive their city |
| Same seed, same actions → identical districts and yields | anything order-dependent on set iteration |
| A district tile cannot host a new city, an improvement, or be swapped; its owner is always its city | any of `can_found_city_at`, `create_city`, `can_build_improvement_at`, `swap_tile` ignores districts |
| The settle layer refuses a district placed on a featureless, resourceless tile | the settle cache key misses `district_epoch` |
| A tile worked before placement is not worked right after it | `place_district` does not re-run `assign_tiles` |
| A `resources` constraint evaluated without a resource raises; an unknown `on` key raises at load; mapgen goldens unchanged | `matches` silently ignores keys |
| The discount follows the integer rule exactly (e.g. A = 9, B = 10: count 1 discounted, count 2 not) | real division or a different rounding order |
| A city captured mid-round accrues district stats once that round | the stats accrual skips the once-per-round guard |

## 11. Patch plan

No patch is HUMAN-TEST. One agent at a time on branch `86-district-framework`,
merged when green.

| Patch | Content | Gate | Mode · tier |
|---|---|---|---|
| D1 | `district_model.py` + the `[districts]` tables; `terrain_model` `resources` key, `resource_class`, `IMPROVEMENT_NAMES`, unknown-key rejection; `game/districts.py` `adjacency_score`, `can_place_district`, cost; `District`, `Tile.district`, `City.districts`; `Map.district_epoch`; a minimal `place_district` (check, create, link, clear, lock cost, bump epoch, re-run `assign_tiles`); `remove_city` clearing; refusals in `can_found_city_at`, `create_city`, `can_build_improvement_at`, `swap_tile`; settle cache key | §10 adjacency, placement, cost, load, refusal and cache properties; mapgen goldens and `test_terrain_model` unchanged; full suite green | subagent · Opus (changes the canonical `on` evaluator) |
| D2 | production branch, `produce_district`, capture behaviour, `district_yields` + its `episode_stats` counters, Aqueduct housing, `build_agent` district branch, CHANGELOG (v0.7.0), CLAUDE.md rows and amendments, extend `scripts/smoke_random_selfplay.py` to place districts through the engine | the remaining §10 properties; full suite green; seeded smoke run | subagent · Sonnet |

## Critique (lens table)

| Lens | Verdict | Blockers |
|---|---|---|
| Systems reuse, regression and determinism (Opus) | survives with fixes | (1) settle cache key (state_encoders.py:660) goes stale on placement on a bare tile; (2) `terrain_model.matches` cannot see resources and silently ignores unknown keys (terrain_model.py:107-121; callers incl. mapgen starts.py:747); (3) Housing row's "never add a term" broken without amendment; (4) D1 cannot test placed-district properties without `place_district`. Non-blocking: one `set_layers` call (Deer/Bananas/Rice need their feature); row amendments for City economy, Territory, Action masking; no third reader of `CFG["improvements"]`; reserved names and scalar/sub-table split; stats keys and once-per-round guard; build_agent.py:146 branch; integer cost arithmetic; sorted smoke candidates; D1 on Opus |
| Rules semantics and edge cases (Opus) | survives with fixes | (1) improvements are not a layer: `set_layers` cannot clear them; the epoch bump on placement is unstated; (2) a city can be founded on an owned district tile (`can_found_city_at` environment.py:929, `_founding_claim`; painter `_place_city` bypass); (3) `can_build_improvement_at` (environment.py:1065) lets an improvement onto a district tile; (4) `assign_tiles` is not re-run on placement, so the tile stays worked; (5) the §4.1 discount is not one deterministic integer rule (division, A, count_T, rounding order). Non-blocking: placed-vs-complete for every limit; incomplete districts after population loss; `produce_district` on complete/unplaced T; Aqueduct river test is on its own edges; Harbor "adjacent to land" encoding; `resources` key described two ways; units on the tile; "any" counts other cities' districts; `_fresh_episode_stats` keys and accrual phase; build_agent.py:146 treats any non-unit production as a building |


**Synthesis (v3).** Both lenses: survives with fixes. All nine blockers are
resolved in "v3 fixes" (it overrides §1–§8 where they differ); the
non-blocking points are folded in there too. No further round: v3 is the build
contract.

---

## Systems

### (a) Existing canonical systems this design must use

- **Terrain model** (`terrain_model.matches`, `compose`, `Tile.set_layers`):
  terrain sources and the tile's own `on` rule; feature clearing. No terrain
  names in code. Extended with a `resources` match key.
- **Hex math** (`Map.get_adjacent_coords`, `get_ring_coords`,
  `distance_function`): every neighbour count and the radius.
- **Territory** (`Map.owner_city`, `swap_tile`, `create_city` / `remove_city`,
  `City.set_owner`): ownership for placement; swap refusal; removal and capture.
- **Rivers** (`Map.has_river_between`): Commercial Hub and Aqueduct river tests.
- **Terrain epoch**: placement changes layers through `set_layers(map_ref=...)`.
- **City economy** (`process_turn`, `assign_tiles`, `calculate_production`): the
  district production branch, the worked-tile exclusion, production yield.
- **Culture yield** (`culture(city)`): untouched in this patch (§5). The patch
  that wires district culture in adds one term fed by `district_yields`.
- **Housing** (`housing(city)`): the water term reads district water fields.
- **Gameplay config** (`CFG`): every number.
- **Game interface** (`GameEnvironment`): `place_district` lives there.

### (b) New systems, with draft CLAUDE.md rows

| System | Where | Draft rule |
|---|---|---|
| District registry | `[districts.*]` in config.toml → `civulator/district_model.py` | The only interpreter of district config. A new district is a new table, never code; a row may only name a source that exists |
| Adjacency | `adjacency_score` (`game/districts.py`) | The only adjacency computation. Rows floored separately; a new source kind extends §1.2's table here, never a per-district `if` |
| District placement | `can_place_district` + `GameEnvironment.place_district` (`game/districts.py`, `game/environment.py`) | The only placement check and the only writer of `Tile.district` / `City.districts` (beside `remove_city`). A future agent mask must call `can_place_district` (mask invariant) |
| District yields | `district_yields(city)` (`game/districts.py`) | The only conversion of adjacency into yields; consumers (culture, production, later science/gold/faith) read it, never recompute |

## Sources

- Game database dumps: `jad0083/game-harness` `corpora/civ6/data/`
  (`_adjacency.json`, `district.json`; game XML 1.0.12.68, Gathering Storm), and
  `Seth9976/Civilopedia_Java` `databases/Civ6GatheringStorm/` (Districts,
  District_Adjacencies, Adjacency_YieldChanges, GlobalParameters).
- [District (Civ6)](https://civilization.fandom.com/wiki/District_(Civ6)) (cost
  formula, discount, placement, population limit);
  [Adjacency bonus (Civ6)](https://civilization.fandom.com/wiki/Adjacency_bonus_(Civ6))
  (rounding, city centre counts, Government Plaza); the per-district wiki pages.
- [CivFanatics formula thread](https://forums.civfanatics.com/threads/formula-thread.600534/page-4)
  (cost escalation).
