# Housing (#88): design

> **v2**, 2026-10-11 (v1 + two Opus critique lenses, see the lens table). Rules settled in chat between Erik and Claude; Civ 6 facts
> from the [Civ 6 wiki Housing page](https://civilization.fandom.com/wiki/Housing_(Civ6)).
> This doc is the contract for the implementing patches.

## Goal

Population growth is currently unbounded: any food surplus grows the city
(`City.process_turn`). Civ 6 limits growth with **housing**: a city with too
little housing grows slower and finally stops. Housing comes mostly from where
the city stands (fresh water) and from what it builds.

Every number is a config value, as for borders and culture (#87), so the game
can be rebalanced when RL agents find what is overpowered.

## In scope

1. A per-city **housing** value from: water at the city centre, buildings
   (Granary), the new **Palace** building, and improvements on the city's owned
   tiles.
2. The **growth slowdown**: the food surplus going into growth is scaled by how
   much housing exceeds population.
3. The **Palace** building, given to each player's first city.

## Out of scope

| Item | Where |
|---|---|
| Aqueduct (+2, or water housing raised to 6) | a district: waits for #86 |
| Amenities | #88's own rule (#41): only once unhappiness does something |
| Neighborhood, Sewer, policies, wonders | not in the game yet |
| Workers building improvements | no agent action and no Worker in `BUILD_OPTIONS`. Improvement housing ships but is dormant in play (ACCEPTED GAP below) |
| Civ 6's growth-threshold curve | ours (`15 + 10·(pop−1)`) stays; separate question |

---

## 1. Housing of a city

```
housing(city) = water(city)
              + sum(housing of each building in the city)
              + sum(housing of each improvement on a tile the city owns,
                    within improvement_radius of the centre)
```

- **Water** (Civ 6 values, read at the city centre):
  - **fresh** = 5: the centre tile is fresh water by the canonical
    fresh-water query (`Map.is_fresh_water`: river edge, lake, oasis);
  - **coastal** = 3: not fresh, and some neighbour of the centre is a
    water-domain tile (`hexmath` adjacency, `tile.domain`). A lake neighbour
    already makes the centre fresh, so "coastal" in practice means sea;
  - **dry** = 2: neither.

  No terrain names are read (CLAUDE.md terrain-model rule).
- **Buildings** declare `housing` in their `[buildings.*]` table (optional,
  default 0), parsed by `civulator/unit_model.py` beside `culture`. Granary
  `housing = 2`, Palace `housing = 1`. A new source declares the column; the
  formula never changes.
- **Improvements** declare `housing` in their `[improvements.*]` table
  (optional, default 0): Farm, Pasture, Plantation, Camp and Fishing Boats get
  `housing = 0.5` (Civ 6). They count only on tiles **owned by this city**
  (Erik, 2026-10-11: "owned only") within `improvement_radius` (3, Civ 6's
  "within 3 tiles"). The column is parsed into `IMPROVEMENT_HOUSING` (tenths)
  by `civulator/terrain_model.py`, the only interpreter of tile gameplay
  numbers and already the reader of `[improvements.*]` placement (v2, critic 2).
  Owned tiles come from `Map.tiles_of_city(city_id)`, the radius from
  `Map.distance_function`; no new ring scan.
- **Integer tenths**, as for culture: every housing value is converted once at
  load with `unit_model.to_tenths` (raises on non-multiples of 0.1), so
  `housing(city)` is an int in tenths and all comparisons are exact.
- `housing(city)` lives in `civulator/game/housing.py` (mirroring
  `game/culture.py`) and is the only place housing is computed. It is a pure query of current state (no cache needed; it is called
  once per city per turn).

**ACCEPTED GAP:** no unit can build improvements in play, so improvement
housing is 0 in real games until Workers and an improvement action exist. The
rule and its column ship and are tested, exactly as building culture did in
#87.

## 2. Growth slowdown

In `City.process_turn`, a **positive** food surplus is scaled before it enters
the growth bucket:

| housing − population | share of surplus that counts (Civ 6) |
|---|---|
| ≥ 2 | 100 % |
| ≥ 1 | 50 % |
| > −5 | 25 % |
| ≤ −5 | 0 % (hard cap at housing + 5) |

- Config holds the bands as an ordered list of `(min, percent)`, first match
  wins, otherwise 0 %:
  ```toml
  [housing]
  water_fresh = 5
  water_coastal = 3
  water_dry = 2
  improvement_radius = 3
  growth_bands = [ [2.0, 100], [1.0, 50], [-4.9, 25] ]   # min (inclusive), percent
  ```
  `-4.9` encodes "> −5" for values in tenths. At load, percents must be ints
  and band `min`s strictly descending, or loading raises.
- **Exact arithmetic.** The growth bucket (`city.food_surplus`) changes units to
  hundredths of food: `food_surplus += food_net * percent` for a positive net,
  and growth happens when `food_surplus >= 100 * threshold`. No float, no
  rounding, so a 1-food surplus at 25 % still accumulates (a floor would lose
  it forever). The implementer converts every reader of `food_surplus`
  (starvation, growth, any encoder or stat reading it) to the new unit, or
  keeps a helper that reports whole food.
- **Starvation is unchanged.** A negative net drains the bucket and then drops a
  population, as today. Housing never removes population: losing housing (the
  an improvement tile lost with a captured city) only slows or stops growth.
- `housing − population` is evaluated with the housing **at the start of the
  food phase**, before this turn's growth.

### v2 fixes (critic 1)

- **Units.** The band key is `housing_tenths − 10·population`; band `min` values
  go through `to_tenths`; percents are ints. A negative or zero net is handled as
  today but in the new unit: a negative net drains `100 * food_net`
  hundredths; `food_net == 0` takes the positive branch (adds 0).
- **The 0 % band is a real cap.** When `housing − population` is in the 0 %
  band, the city does not grow this turn even if the stored bucket is at or
  above the threshold; the bucket is kept. In every other band growth checks
  the bucket as today.
- **One improvement per tile counts** (Claude's call: Civ 6 allows one
  improvement per tile, our engine lets several stack). A tile contributes the
  largest `housing` among its improvements.
- **The city centre never counts** for improvement housing (Civ 6 clears
  improvements from a city centre).
- `housing(city)` reads `Map.owner_city` live every call; nothing about housing
  is cached on `City`, so swaps, capture and border growth need no extra rule.
- The coastal test is `tile.is_water()` on the centre's neighbours.
- `growth_slowed_turns` counts city-turns with a positive net whose band was
  below 100 %.

## 3. The Palace

- `[buildings.Palace]` with `housing = 1` and **no** `production_cost`: it can
  never be built (it is not in `BUILD_OPTIONS`, and the production path must
  refuse a building without a cost). Civ 6's Palace also gives culture; ours
  does not, because `[culture] base = 1` already stands in for it (#87).
- **Costs.** `BUILDING_COSTS` holds only buildings that declare
  `production_cost`. `City.produce_building` refuses (returns False) any name
  not in `BUILDING_COSTS`, and the silent `100` default in `get_building_cost`
  goes. The pre-existing `test_city_walls.py` property becomes "every
  *costed* building mirrors config" (a contract change this spec makes).
- **Granting:** the creation function (`GameEnvironment.create_city`) gives the
  Palace to a city when its player has never held one (`player.palace_granted`
  flag). The flag is reset to False in every reset attempt (the player-reset
  branch of `_reset_attempt`, unseeded retries included) and by
  `recording._clear_board`, so the grant works in every episode. At reset that
  is each player's capital. Under #85 (no pre-founded
  capital) it will be the first city a player founds, with no code change.
  Painted scenarios get it on each team's first placed city, the same rule; the
  scenario format does not store a Palace, it is always re-granted in file
  order.
- **Capture: the Palace stays with the city** (Erik, 2026-10-11: "I don't want
  it to be removed upon capture. This is something new I'd like to change in my
  civ"). This departs from Civ 6 on purpose. The building and its housing go to
  the conqueror with the city, so a player can hold more than one Palace. The
  old owner keeps `palace_granted = True` and gets no replacement; there is no
  relocation project.
- Nothing else reads "capital" for gameplay.

---

## 4. What changes for agents and experiments

- Growth slows for cities without enough housing. This is a rule change inside
  the **v0.7.0** epoch (no artifact has been produced under 0.7.0 yet). Extend
  the v0.7.0 CHANGELOG entry; no version bump.
- No new actions, masks or encoder channels. Agents see population as before;
  they do not see housing (part of the future input-space design, like #111).
- `episode_stats` per player: `growth_slowed_turns` (city-turns where the band
  was below 100 %), so the order parameter "how often housing binds" is
  measurable.

## 5. Tests (properties, each naming the change that breaks it)

| Property | Breaks if |
|---|---|
| Water housing is fresh > coastal > dry by the config values, decided by `Map.is_fresh_water` and water-domain adjacency | terrain names are read, or fresh water is recomputed outside the canonical query |
| A building or improvement declaring `housing` adds exactly its value; one not declaring it adds 0 | the formula hardcodes a building name |
| Improvement housing counts only on tiles the city owns within `improvement_radius` | ownership or radius is ignored |
| The growth share follows the band table; changing a band in config changes growth | a percent is hardcoded |
| A 1-food surplus at 25 % still grows the city eventually | the bucket floors fractional food |
| Housing never removes population; starvation still does | housing is applied to negative nets |
| Each player's first city holds the Palace; later cities do not; a captured Palace city keeps it, and its old owner gets no new one | the grant rule drifts, or capture strips buildings |
| The Palace cannot be produced | the production path accepts a building without a cost |
| A second reset (same env object) still grants every capital a Palace | `palace_granted` is not reset per attempt |
| At the 0 % band a city with a full bucket does not grow | growth ignores the band |
| A tile with several improvements adds only the largest housing; the centre adds none | stacking is summed, or the centre counts |
| Same seed, same actions → identical populations and buckets | float arithmetic in growth |

## 6. Patch plan

No patch is HUMAN-TEST; the arc runs without Erik. One agent at a time on one
branch, merged when green.

| Patch | Content | Gate | Mode · tier |
|---|---|---|---|
| H1 | `game/housing.py` `housing(city)`: `[housing]` water values + radius, `housing` column on buildings (`unit_model.BUILDING_HOUSING`) and improvements (`terrain_model.IMPROVEMENT_HOUSING`), Palace building + grant in `create_city` (kept on capture), `palace_granted` (default in `Player.__init__`, reset per attempt and in `_clear_board`), the §3 cost changes (filtered `BUILDING_COSTS`, `produce_building` refusal, no default 100, `test_city_walls.py` contract) | §5 housing and Palace properties; full suite green | subagent · Sonnet |
| H2 | Growth bands in `process_turn` with the hundredths bucket (and `tests/test_culture.py:114`, the one outside reader), the 0 % cap, load checks, `growth_slowed_turns` stat, CHANGELOG (v0.7.0), CLAUDE.md rows, smoke run by extending `scripts/smoke_random_selfplay.py` | §5 growth properties; full suite green; seeded 250-round random-play smoke showing population vs housing | subagent · Sonnet |

## Critique (lens table)

| Lens | Verdict | Blockers |
|---|---|---|
| Rules semantics and edge cases | survives with fixes | (1) `BUILDING_COSTS` comprehension (unit_model.py:101) KeyErrors on a cost-less Palace; `test_city_walls.py:85` pins "every building has a cost"; (2) `produce_building` accepts any name and `get_building_cost` defaults to 100, so a Palace could be built; (3) `palace_granted` on reused `Player` objects is not reset between episodes / retry attempts; (4) starvation units in the hundredths bucket unspecified; (5) the 0 % band does not cap growth from an already-full bucket. Non-blocking: band key units, int percents, stacked improvements per tile, improvements on the centre, ownership read live, `_clear_board` and the grant flag, scenario format has no Palace, `growth_slowed_turns` with non-positive net, water test via `tile.is_water()` |
| Systems reuse, regression and determinism | survives with fixes | (1) improvement-housing parse placed in environment.py breaks the Terrain-model rule and creates an import cycle → `terrain_model.IMPROVEMENT_HOUSING`. Non-blocking: H1 must carry the cost changes; `test_culture.py:114` breaks in H2 (bucket units); reject float percents and unordered bands at load; reuse `tiles_of_city`/`distance_function`, `game/housing.py`; Growth bands is an amendment to City economy, Buildings row must be amended; Combat-training tools missing from Systems (a); `palace_granted` default in `Player.__init__`; extend `scripts/smoke_random_selfplay.py` |

**Synthesis (v2).** Both lenses: survives with fixes. All blockers resolved in
the text above (§1 parse location and module, §2 units/cap/load checks, §3
costs and the grant flag reset). No further round: v2 is the build contract.

---

## Systems

### (a) Existing canonical systems this design must use

- **Fresh water** (`Map.is_fresh_water`): the only fresh-water query; water
  housing reads it.
- **Hex math** (`hexmath` adjacency, distance): the coastal check and the
  improvement radius.
- **Terrain model**: `tile.is_water()` for the coastal test, and the
  interpreter of `[improvements.*] housing` (`IMPROVEMENT_HOUSING`); no terrain
  names.
- **Territory** (`Map.owner_city`, #87): improvement housing counts owned tiles
  only.
- **City economy** (`City.process_turn`): the growth slowdown lives there; no
  second growth loop.
- **Buildings** (`unit_model.py`, `to_tenths`): `BUILDING_HOUSING` beside
  `BUILDING_CULTURE`; `production_cost` becomes optional (absent = never
  buildable). Amend the row.
- **Culture yield** (`game/culture.py`): the pattern `housing.py` mirrors.
- **Combat-training tools** (`recording._place_city` / `_clear_board`): the
  Palace is re-granted through `create_city`; `_clear_board` resets the flag.
- **Territory** (`create_city`, `Map.tiles_of_city`): the Palace grant hooks
  into `create_city`; owned tiles for improvement housing.
  Capture needs no hook: buildings already travel with the city.
- **Gameplay config** (`CFG`): every number.

### (b) New systems, with draft CLAUDE.md rows

| System | Where | Draft rule |
|---|---|---|
| Housing | `housing(city)` (`game/housing.py`) over `[housing]`, `[buildings.*] housing`, `[improvements.*] housing` | The only computation of a city's housing (integer tenths). A new housing source declares a `housing` value in its own config table; never add a term to the formula |
| City economy (amend) | `City.process_turn` | Add: growth is scaled by `[housing] growth_bands`; the growth bucket is in hundredths of food, never floats; the 0 % band blocks growth |
| Palace | `[buildings.Palace]`, granted in `create_city` | Granted once per player to its first city, kept by the city on capture, never buildable; gameplay never reads "capital", it reads the Palace |
