# Districts II and religion (#93 #94 #95 #96 #97 #102): design

> **Status: v1, awaiting Erik's rulings and the critique round.** Authored
> 2026-10-22 by Claude as lead game designer, at Erik's request (chat,
> 2026-10-22, Erik away for the rest of the session). Rules that are Erik's
> are marked *(Erik)*; everything else is Claude's call, flagged where it
> constrains later design. Civ 6 facts: `docs/civ6_progression_reference.md`
> (the digest) and `docs/districts_design.md` (the dumps). The build
> procedure for every patch here is `.claude/skills/civulator-progression`.
>
> Companion docs this one extends and never repeats: `docs/districts_design.md`
> (the district framework, v3), `docs/progression_design.md` (yields, effects,
> trees, gold, loyalty, wonders, §10.2's religion sketch).

## 0. Goal, rulings, principles

### 0.1 Goal

Finish milestone D's open content so that every district in the registry
*changes how a player strategizes* (issue #41's rule), give the coast a game
(Harbor, ships, sea trade), and give faith a purpose beyond purchasing: a
religion system of our own that spreads on its own, is steered with faith,
and whose benefits are shared with whoever adopts it.

### 0.2 Erik's rulings this session (2026-10-22, chat) — recorded with reasons

| # | Ruling | Consequence here |
|---|---|---|
| R1 | **A district built on an improvement leaves only the district.** | Already the engine's rule (`place_district` clears `tile.improvements`, districts design v3). Confirmed; a test names it (§11). |
| R2 | **A district built on a strategic resource before the resource is "discovered" still grants the resource.** | Needs strategic resources to exist (§2); the generalised rule is §2.3. |
| R3 | **Harbor must be in the game; naval units too; sea trade, with the discrete yield jump when trade crosses the sea and later the ocean.** | §5. The Harbor district exists since #86; what is new is ships, sea routes, the overseas bonus and the three techs that carry them. |
| R4 | **Neighborhood (housing district) is skipped.** | #97's second question closes: declined. Housing's ceiling stays Aqueduct + buildings + improvements. |
| R5 | **Encampment and Industrial Zone follow Civ 6's design**; the Industrial Zone's Aqueduct adjacency and the two-cities-one-river minigame are what Erik wants kept. | §3, §4. The minigame already works: a named `district = ["Aqueduct"]` row counts a neighbour whoever owns it (`districts._neighbour_matches`). |
| R6 | **Minimum city distance is 4** (three full tiles between centres). | Shipped 2026-09 as #74 (commit 6d7359f, CHANGELOG v0.7.x "min_city_distance 3 -> 4"); `config.toml [game] min_city_distance = 4`. Nothing to do; #74 is closed with this pointer. |
| R7 | **Religion**: faith is spent to spread and to maintain a religion; spread is a function of religious population and distance, boosted by faith; the spreading is automated (no missionary micro); the game-altering abilities stay and the most interesting are chosen. | §7. |
| R8 | **Meaningful choices, no braindead micro** (standing principle, restated). | Every new agent action in §9 is a choice, never a chore: no per-unit religious orders, no per-turn confirmations. |
| R9 | **State space is not designed now**; it gets one big pass later and may evolve through the whole 0.9 era. | §12 lists what the pass will need to see, nothing more. |

### 0.3 Principles (from `progression_design.md` §0.2, applied here)

Few nodes, each a real choice · content stops where Civ 6 stops being fun ·
config, not code · one seam per effect · reasonable starting numbers,
auto-balance later · reports state only what was measured. Added for this
block, from #93: **science, culture and religion compete** — a player who
wants all three should find it hard, and the competition is for district
slots, production and the faith pool, never for a forbidden combination.

### 0.4 Civ 6 as a reference, not a model

Where Civ 6 has a mechanic whose fun Erik confirmed (Encampment, Industrial
Zone adjacency, Harbor, amenities, pantheons, beliefs) its values are copied
and the sources named. Where Erik rejected it (missionaries, apostles,
theological combat, Great People) it is not adapted, it is replaced.

---

## 1. Scope

In: §2 resource tiers · §3 amenities + Entertainment Complex · §4 Encampment
· §5 Industrial Zone (+ optional Dam) · §6 Harbor, ships, sea trade, the
naval techs and civic · §7 religion · §8 the touch on loyalty and victory ·
§9 agent actions and engine defaults · §10–§14 tests, patches, systems.

| Out of scope | Where |
|---|---|
| Embarkation of land units (#76: `can_enter` is single-domain, cost grids player-blind) | **ACCEPTED GAP for this block**: no land unit ever enters water; islands without a land path are reachable only by ships, never settled. Revisit when #76 is designed |
| Promotions / unit XP (#61) | the Encampment is not XP-gated; Barracks stays yield-only |
| Great People | none; every Civ 6 "+1 Great X point" is dropped, as in the progression block |
| Pillaging | a district has no pillaged state; the Encampment's "blocks movement unless pillaged" becomes "unless breached" (§4.2) |
| Civ 6 GS strategic stockpiles | access is boolean (§2.2); the Encampment's "1 resource instead of 2" has no meaning and is dropped |
| Neighborhood, Water Park, Canal, Preserve | declined (R4) or beyond the tree |
| Theological combat, religious units, Holy City mechanics, relics | replaced by §7 |
| Encoder channels for any of this | #111 and the state-space pass (R9); §12 only lists what exists |
| Rewards for any of this | #123/#124: the potential reward pays for held value, so nothing here needs an event payment |
| Balancing | the dial table (§13) is filled in; nothing is measured in this block |

---

## 2. Resource tiers: strategic and luxury (#102)

`config.toml` ships the bonus tier; luxury and strategic are schema-ready via
`class`. Both are load-bearing for this block (Encampment needs nothing
from them, but R2, amenities and the Industrial Zone's strategic row do), so
they ship first.

### 2.1 The set

Civ 6 names; placement in `terrain_model`'s `on` form; the improvement that
"improves" it is the one whose `on` admits the tile (the existing rule — a
resource declares nothing about improvements). `reveals` is informational
(R9: the encoder decides what a player sees; the engine never hides state).

| Resource | Class | On | Improved by | `reveals` (tech) |
|---|---|---|---|---|
| Horses | strategic | Grassland / Plains, flat | Pasture | Animal Husbandry |
| Iron | strategic | hills; Desert / Tundra flat | Mine | Bronze Working |
| Niter | strategic | Grassland / Plains / Desert / Tundra flat | Mine (Desert/Tundra) — **Farm does not count**: a Niter tile is accessed by Mine, district or centre only | Military Engineering |
| Wine, Silk, Dyes, Cotton | luxury | Grassland / Plains flat (Dyes also Woods, Rainforest) | Plantation | — |
| Salt, Silver | luxury | Salt: Desert / Tundra flat; Silver: hills, Tundra flat | Mine | — |
| Furs | luxury | Tundra flat, Woods | Camp | — |
| Pearls, Whales | luxury | Coast | Fishing Boats | — |

Nine luxuries, three strategics; Civ 6 has more of each, but a Duel world
has ~115 land tiles and luxury *diversity* is the amenity dial (§3.2), so
nine is enough for a player to see four or five distinct ones.

`[terrain.resource.<Name>]` gains two optional columns: `reveals` (a
`[techs.*]` name) and `frequency` (a positive int weight for the placement
stage; absent = the bonus tier's existing behaviour). A luxury also
declares nothing else: its amenity is the class's rule (§3.2), not a
column — adding a luxury is a new table and nothing more.

### 2.2 Access (the one predicate)

`resources.player_has_access(player, resource) -> bool` (new module
`civulator/game/resources.py`): the player owns a tile carrying the resource
that is **improved** (any improvement in `tile.improvements`, since only an
admitted improvement can stand there), **holds a district or wonder**, or
**is a city centre**. Boolean, never a stockpile (Civ 5's model, not Civ 6
GS's: one less pool, and no unit is lost to a shortfall mid-game).

Consumers:

- `[units.<Name>] requires_resource = "Iron"` — read by `City.can_produce_unit`
  through `game/availability.py player_can_build` (the one predicate; the
  build mask, `purchase` and `upgrade_unit` follow). Horseman and Knight
  need Horses; Swordsman and Man-At-Arms Iron; Musketman Niter (Civ 6). **A
  pre-0.8 unit becomes resource-gated**: this is a rule change for the
  Swordsman and Horseman, declared in the CHANGELOG. The combat oracle is
  untouched (strengths do not change).
- Amenities (§3.2): one amenity per distinct *luxury* the player has access to.
- The Industrial Zone's `{ amount = 1, terrain = { resources = <class strategic> } }`
  row (§5): `terrain_model.matches`'s `resources` key already accepts a
  class name (districts design v3, "resources match key").

### 2.3 Districts on resources (R2 generalised)

Today `can_place_district` refuses a non-bonus resource and `place_district`
removes a bonus one. New rule, one line: **a district may be placed on any
resource; a bonus resource is removed (as today); a strategic or luxury
resource stays on the tile and the district counts as its improvement**
(§2.2's access rule). Erik's R2 is the strategic case; the luxury case
follows the same sentence so there is no second rule, and "discovered" never
enters the engine — access is a fact about tiles, the encoder decides what
the agent knows. A wonder on a resource behaves like a district.

### 2.4 World generation

`mapgen/resources.py place_resources` gains the two classes: a luxury is
placed with `frequency` weight on admitted tiles, at most one luxury *type*
per region of the start-placement partition where possible (so neighbours
differ — the trade incentive), never within the founding ring of a start
(the bonus-tier rule, kept); a strategic resource is placed so that **every
start region holds at least one Horses and one Iron within work radius 3 of
some tile the region's player can settle** (a fairness rule, Claude's call —
a Duel where only one side can ever build a Swordsman is a world defect, not
a strategy). Niter has no guarantee (it is Medieval; a player who lacks it
keeps the Man-At-Arms and the Knight).

This changes `MapData.resource` on every seeded world: **a golden
re-baseline** (`tests/test_mapgen_golden.py`), with the field-by-field diff
showing `base_terrain`, `relief`, `feature`, `rivers`, `fresh_water` and
`starts` unchanged — only `resource` and `params` move. Start fertility
(`mapgen/starts.py`) does not score resources today and keeps not scoring
them (#112 is its own issue).

---

## 3. Amenities and the Entertainment Complex (#96)

### 3.1 The mechanic

Civ 6 GS, in integers, one module `civulator/game/amenities.py` (the only
interpreter of `[amenities]`):

- **need(city)** = `ceil(population / need_divisor)` (GS: `ceil(pop / 2)`),
  minus `free_first` (Civ 6 Vanilla gave two free citizens; GS none but the
  capital's Palace). Default `need_divisor = 2`, `free_first = 0`; the
  Palace carries `amenity = 1` as a column (GS: +1).
- **supply(city)** = the `amenity` **columns** of the city's buildings and
  complete districts (Palace 1, Entertainment Complex 1, Arena 2, Alhambra 2)
  + the `amenity` **effects** in force for the city (§3.3) + the city's share
  of the player's luxuries (§3.2).
- **surplus** = supply − need. **band(surplus)**: `[amenities] bands` =
  `[min surplus, yield percent, growth percent, loyalty delta]`, ints, mins
  strictly descending, first match wins, the last row catches the rest —
  the `[loyalty] bands` shape, so the parser is shared (`loyalty.parse_bands`
  generalised to N columns, or a sibling with the same contract).

```toml
[amenities]
need_divisor = 2          # Civ 6 GS: one amenity per two citizens, rounded up
free_first = 0
luxury_cities = 4         # Civ 6: each distinct luxury serves up to 4 cities
#        [min surplus, yield %, growth %, loyalty / round]
bands = [[5, 20, 100, 1], [3, 10, 100, 0], [0, 0, 100, 0], [-2, -10, 85, -1], [-4, -20, 70, -2], [-6, -30, 50, -3], [-99, -40, 25, -4]]
```

Yield percent and growth percent are Civ 6 GS's (Ecstatic +20 %, Happy +10 %,
Content 0, Displeased −10 % / −15 % growth, Unhappy −20 % / −30 %, Unrest
−30 %, Revolt −40 %); the growth column is "100 − Civ 6's penalty". Civ 6
spawns rebels at Unrest — we have no barbarians, so **the loyalty column
replaces rebels**: Civ 6 R&F does tie amenity state to loyalty per turn, with
values the digest does not give, so the column's numbers are Claude's
starting values for Erik's dial.

Consumers (each one place):
- **yields**: `city_yield` scales science, culture, gold, faith and production
  by `(100 + yield_percent) / 100` *after* the loyalty percent (integer
  tenths, floor); food is never scaled (Civ 6).
- **growth**: `City.growth_bucket_gain` multiplies by `growth_percent / 100`,
  beside the housing bands and loyalty share (floor once at the end).
- **loyalty**: one more term of `loyalty.loyalty_delta`: `amenities.loyalty_term(city)`.

Amenities are recomputed from live state on every call, like
`district_yields`, never cached.

### 3.2 Luxuries

Each distinct luxury the player has access to (§2.2) gives **+1 amenity to
up to `luxury_cities` of the player's cities**, assigned deterministically
to the neediest: cities sorted by `(need − supply_without_luxuries)`
descending, then city id ascending; the first `luxury_cities` get it. Two
copies of Wine are one Wine (Civ 6). No trading of luxuries between players
(no diplomacy yet; milestone C).

### 3.3 Sources that are effects

One new effect kind, **`amenity`**: `{ kind = "amenity", amount = N,
range = R (0 = this city; absent = 0), min_districts = M (optional: only
cities with ≥ M complete specialty districts) }`, attachable to wonders,
governments, policies and beliefs. Consumer: `amenities.supply`. Carriers in
this block:

| Carrier | Effect |
|---|---|
| Colosseum (exists; its amenity "not implemented") | `amenity` +2, `range = 6`, and `loyalty` +2 `range = 6` (R&F/GS; the loyalty kind already takes `range`) |
| Classical Republic (exists) | `amenity` +1, `min_districts = 1` (Civ 6: +1 per city with a district) |
| Retainers (new policy, M, Civil Service; the digest: "+1 amenity in garrisoned cities") | `amenity` +1 with `requires_garrison = true` — the loyalty kind's attribute, reused (one more consumer of `loyalty.is_garrisoned`) |
| Zen Meditation (belief, §7.5) | `amenity` +1, `min_districts = 2` |

### 3.4 The Entertainment Complex

`[districts."Entertainment Complex"]` gains `amenity = 1` (column). The
**Arena** is a new building: Games and Recreation, 150 production,
maintenance 1, `requires_district = "Entertainment Complex"`, `amenity = 2`,
`culture = 1` (GS). Civ 6's Zoo and Stadium are beyond the tree; the
Colosseum (above) is the regional amenity of our era, and it is the reason
to place the Entertainment Complex *between* cities rather than in the
biggest one — the district now changes a decision (#41's rule).

**Why amenities ship in the same patch as the district (not after it)**:
#96's own condition — an amenity yield only once unhappiness does something.

---

## 4. Encampment (#94)

Civ 6's Encampment is a fortress and a barracks. Keep both; drop Great
Generals (no Great People) and the resource discount (boolean access).

### 4.1 Spawn tile

A city whose complete Encampment exists places a newly produced or purchased
**land military** unit on the Encampment tile when the city centre's slot
for it is taken: `City.place_new_unit`'s candidate order becomes centre →
Encampment → adjacent tiles (today: centre → adjacent). Same routine, one
more candidate; naval units never go there (§6.4).

### 4.2 Fortress

A complete Encampment is a **fortified district**:

- it has **health**, `[districts.Encampment] health = 100` (Civ 6 districts
  have 100; the city has 200), repaired `[city] heal_per_turn` at its owner's
  turn start unless an enemy land military unit is adjacent to *it* (the
  siege test `is_city_under_siege` generalised to "adjacent to this tile",
  one function with the tile as argument; the city keeps calling it with its
  centre);
- **enemy units cannot enter its tile while its health > 0** (`Unit.move` and
  the movement mask refuse, exactly as `enemy_city_blocks` refuses a healthy
  enemy city); own and allied-to-nobody units may. At 0 it is **breached**:
  enemies may pass and stand on it; it repairs again once no enemy is adjacent;
- it **defends with its city's strength**: `_execute_attack` accepts a
  fortified district as defender — the defender protocol (`health`,
  `get_combat_strength()`, `coordinates`, `player`) that `City` already
  satisfies, so the district object gains the same four and
  `get_combat_strength` returns `city.get_combat_strength()`. The
  `ranged_city_penalty` applies (Civ 6: −17 vs *district defenses*), siege
  class bonuses apply, it is never killed (floors at 0, like a city), and it
  cannot be captured — it belongs to its city;
- **ranged strike**: once the city holds `[city] ranged_building` (Walls),
  the Encampment strikes too, automatically at its owner's turn start, with
  the city's `get_ranged_strength()` and `ranged_range`, from its own tile,
  target chosen by the same rule as `GameEnvironment.city_ranged_attack`
  (that function takes an origin tile; the city passes its centre). A walled
  city with an Encampment fires twice (Civ 6, #94's note);
- it goes with its city on capture (every district does), health reset to
  `captured_health_percent` of max (50, Claude's call: like loyalty 50 on
  capture — a conqueror's fortress is half-built).

Why this is the district's "one feature": placement **not** adjacent to the
centre (exists) plus "enemies cannot cross it" makes the Encampment a
**forward wall**: placed on the approach, it is a chokepoint a besieger must
breach first and that shoots back. That is a placement decision with a
military answer, not a yield.

### 4.3 Barracks

Exists (`production 1, housing 1`); unchanged. Stable and Armory are not
added (no XP to hand out).

---

## 5. Industrial Zone (#95)

Exists with Civ 6's adjacency (Aqueduct +2, Quarry +1, Mine per 2 +1,
districts per 2, Government Plaza). Changes:

1. **Strategic row** (Civ 6 GS): `{ amount = 1, terrain = { resources = "strategic" } }`
   — the `resources` key takes a class name (v3). It needs §2.
2. **Workshop** exists (Apprenticeship, 195, production 3 — the design said
   Civ 6's +2 and the config says 3; the implementer sets **2** (GS) and
   declares it in the CHANGELOG, or leaves 3 and says so; either is a one-line
   entry).
3. **Regional production — Erik's call (open call C3).** Civ 6's Factory
   gives +3 production to every city within 6 tiles, which is the mechanic
   that makes players cluster cities around one Industrial Zone — the
   "minigame" Erik remembers is adjacency *and* this. The Factory is beyond
   the tree (Industrialization). Proposal: a `regional_yield` effect
   `{ kind = "regional_yield", production = 1, range = 6 }` on the
   **Workshop**, paying every *other* city of the owner within range 6 of the
   Industrial Zone (never twice from two Workshops — a city takes the max per
   yield). Consumer: `city_yield`. If Erik declines, the Industrial Zone's
   strategy is adjacency alone, which already works.
4. **Optional: the Dam** (Erik: "I'm not sure we have dams"). Civ 6 GS Dam:
   a district on a Floodplains tile with a river edge, +2 Industrial Zone
   adjacency, +1 housing, +1 amenity, prevents floods (none here). Cheap:
   one `[districts.Dam]` table (`requires_tech = "Engineering"`, with the
   Aqueduct, since Buttress is cut; `on = { features = ["Floodplains"] }`,
   `requires_adjacent = [{ river_on_tile = true }]`, `counts_toward_limit =
   false`, `max_per_city = 1`, `housing = 1`, `amenity = 1`) and one new row
   on the Industrial Zone. It makes the river minigame richer (Aqueduct + Dam
   + Industrial Zone between two cities = +4 before Mines). **Open call C4:**
   ship it or not. Default if Erik is silent: ship — it is a table, not code.

The two-cities-one-river play (R5): verified by a test, not assumed — a
neighbour city's Aqueduct counts for my Industrial Zone (`_neighbour_matches`
reads `tile.district.type` and never the owner).

---

## 6. Harbor, ships and the sea (#97, R3)

### 6.1 Techs and civic

Three Civ 6 techs return (the progression block cut them for "no naval"):

| Tech | Era | Cost | Requires | Unlocks here |
|---|---|---|---|---|
| **Sailing** | Ancient | 50 | — | Galley; **Fishing Boats** (moved from Celestial Navigation, Civ 6's placement) |
| **Shipbuilding** | Classical | 200 | Sailing | Quadrireme; **Colossus** (moved from Celestial Navigation — Civ 6 places it here) |
| **Cartography** | Renaissance | 600 | Shipbuilding, Celestial Navigation (Civ 6 GS: Buttress, cut) | Caravel; **naval units and sea routes may enter Ocean** (the `enables` kind: `rules = ["ocean_navigation"]`) |

Celestial Navigation now `requires = ["Sailing", "Astrology"]` (Civ 6); it
keeps Harbor and Lighthouse and gains the **Great Lighthouse** (wonder, Civ 6:
+1 movement for naval units, +3 gold; Coast, adjacent to land and to a Harbor
with a Lighthouse). Five starting techs (Civ 6's five). The tree sums to
4,865 at Civ 6 costs (was 4,015); the `tech_cost_percent` dial absorbs it in
the balancing pass — §12 of the progression design said the dial exists for
exactly this.

One civic returns: **Naval Tradition** (Classical, GS cost 220, requires
Defensive Tactics per the digest §2 — the implementer takes the digest's
row): cards **Maritime Industries** (M: `production_percent` +100 toward
Ancient/Classical naval units — Civ 6 hangs it on Foreign Trade; moving it
here keeps Foreign Trade's node to Trader + Caravansaries) and **Naval
Infrastructure** (E: `adjacency_percent` +100, Harbor — GS).

### 6.2 Naval units

Two new combat classes, `naval_melee` and `naval_ranged`, in the one class
registry. Civ 6 GS stats:

| Unit | Class | Era | Cost | CS / RS / range / move | Tech | Maint. | Upgrades to |
|---|---|---|---|---|---|---|---|
| Galley | naval_melee | Ancient | 65 | 30 / — / — / 3 | Sailing | 1 | Caravel |
| Quadrireme | naval_ranged | Classical | 120 | 20 / 25 / 1 / 3 | Shipbuilding | 2 | — |
| Caravel | naval_melee | Renaissance | 240 | 55 / — / — / 4 | Cartography | 4 | — |

`MOVEMENT_DOMAIN` gains the three as `"water"`. `UNIT_SLOT`: military (slot
0). Class bonuses (Civ 6: land ranged −17 vs naval units): `{ unit = "ranged",
target = "naval_melee", amount = -17, strength = "ranged" }` and the same for
`naval_ranged`. The combat oracle (`matchup_matrix`) is run over the
existing seven units before and after: **identical**, since no existing
pairing changes.

### 6.3 Passability: coast and ocean

`can_enter(domain, tile)` matches `tile.domain`; Coast, Lake and Ocean are
all `"water"`. Civ 6: coast only until Cartography. One canonical change:

- `[terrain.base.Ocean]` declares `deep = true` (composed into
  `ComposedProperties.deep`; every other base `false`).
- `Unit.get_movement_domain()` returns `"water"` for a naval unit whose
  owner knows the `ocean_navigation` rule, else `"coast"`. `can_enter("coast",
  tile)` = water and not deep; `can_enter("water", tile)` = water. The cost
  grids are already cached per `(map_uid, terrain_epoch, domain)`, so
  `"coast"` is simply a third grid — the #76 "player-blind" problem does not
  arise, because the player-dependence is in the *domain string*, not in the
  grid.
- `path_finder(..., domain)` is unchanged.

### 6.4 Building and placing ships

`City.can_produce_unit` (through `player_can_build`) admits a water-domain
unit only when the city has a **spawn water tile**: its complete Harbor's
tile, else a water tile adjacent to the centre that the unit could enter
(so a Lake city builds Galleys that never leave the lake — Civ 6 does the
same; its agent will learn not to). `place_new_unit` uses the Harbor tile
first, then adjacent water tiles in `get_adjacent_coords` order, never a
land tile; a land unit never goes to the Harbor tile.

### 6.5 Naval combat

- Melee attacks across domains are **allowed both ways** (Civ 6: a Galley
  attacks a coastal Warrior; a Warrior attacks an adjacent Galley). The
  move-in after a kill happens only when the attacker `can_enter` the
  vacated tile — the existing branch's condition, made explicit.
- A naval melee unit attacks a coastal **city** like any melee unit
  (damage to health), but **cannot capture** (`can_capture_city` is a melee
  *land* unit, #84 — unchanged; Civ 6 is the same).
- Ranged across domains: unchanged (LoS over water is open).
- The city's and the Encampment's ranged strike may target ships (a unit is
  a unit).

### 6.6 Sea trade and the overseas jump (Erik's "discrete, extremely satisfying")

Routes today: a Trader at an own centre, a destination within `[trade]
range` 15 by wrap distance, no path. Added, in `game/trade.py`:

- A route is a **sea route** when origin and destination both hold a complete
  **Harbor** and `path_finder(origin_harbor, destination_harbor, domain =
  owner's naval domain)` finds a water path of length ≤ `[trade] sea_range`
  (30, Civ 6's water range). The owner's naval domain means: **before
  Cartography the path may use Coast and Lake only; after it, Ocean too** —
  which is the second jump, when the far continent comes into reach. A pair
  that qualifies both ways is a sea route (longer reach, the bonus below).
- **Overseas bonus**: a route whose two cities lie on **different
  landmasses** yields `(100 + [trade] overseas_percent) / 100` of every
  yield (per-yield floor, in tenths). `overseas_percent = 100` (Civ 4's
  overseas doubling, the game Erik's memory comes from; Civ 6 has no such
  term). A landmass is a connected component of land tiles under canonical
  adjacency: `Map.landmass_id(coords)` from one BFS, cached on
  `terrain_epoch` (no mapgen change, no golden move). A Lake-only path is
  never overseas (same landmass).
- `eligible_destinations` returns land-reachable (distance ≤ `range`) and
  sea-reachable cities; the Trader default (`default_trade`) already picks the
  best-yield destination, so an idle Trader finds the overseas route by
  itself — the jump happens for an agentless game too.
- Land routes keep needing no path (ACCEPTED GAP, as in the progression
  design: "a route has no path on the map").

`[trade]` grows `sea_range = 30` and `overseas_percent = 100`.

### 6.7 Harbor itself

Unchanged table (Celestial Navigation, gold adjacency, Lighthouse). Its
*function* is now: spawn tile, sea-route terminal, +1 route capacity
(Lighthouse), gold adjacency — a coastal capital is a different game from an
inland one (#97's test).

---

## 7. Religion (#93, R7)

### 7.1 Shape

Not Civ 6's. Three faith sinks a player *chooses* among, one passive spread
the player *steers*, and benefits that are **shared with whoever adopts the
religion** (#93, 2026-10-11: "you get the benefits, but so does the other
player getting your religion"). No unit has a religious order. No religious
combat.

```
pantheon  ──25 faith──▶ one pantheon (permanent, player-scoped effects)
religion  ──found──▶ tier 1: one FOUNDER belief + one FOLLOWER belief
           ──faith──▶ tier 2: a second FOLLOWER belief
           ──faith──▶ tier 3: one ENHANCER belief (how it spreads / defends)
spread    ──passive pressure from follower cities (population, distance, Holy Sites)
           ──faith──▶ spread_religion(city): directed pressure, one action, no unit
           ──faith/turn──▶ upkeep per follower city; unpaid = the religion lapses that round
counter   ──faith──▶ inquisition(own city): reconvert + immunity
```

State: `Player.pantheon` (name or None), `Player.religion` (a `Religion`:
founder index, beliefs by tier, `lapsed` flag), `City.religion` (founder
index or None), `City.religious_pressure` (a small ledger of directed-spread
entries `(religion, amount, rounds_left)`), `City.inquisition_rounds_left`.
All ints; no RNG anywhere in §7.

### 7.2 Pantheon

At `[religion] pantheon_cost` (25, Civ 6) faith a player may `choose_pantheon(name)`
from `[pantheons.*]`: an `effects` list, scope player, permanent, kept even if
every city converts away (Civ 6). The set (Civ 6 names; those whose
mechanic exists here — Great People, appeal, barbarians, harvesting drop):

| Pantheon | Effect (kind) |
|---|---|
| God of the Forge | `production_percent` +25, classes melee/ranged/anti_cavalry/light_cavalry/heavy_cavalry/siege, eras Ancient+Classical |
| Fertility Rites | `growth_percent` +10 |
| Religious Settlements | **`border_cost_percent` −15** (one new kind; consumer `territory.border_cost`) |
| City Patron Goddess | `production_percent` +25, `kind = "district"`, **`no_specialty_district = true`** (one more `target` attribute; consumer `calculate_production`) |
| God of the Sea | **`improvement_yield`** `{ improvement = "Fishing Boats", production = 1 }` (one new kind; consumer `Tile.yields` via `terrain_model`'s improvement yields — the owner's effects) |
| Goddess of the Hunt | `improvement_yield` Camp: food 1, production 1 |
| Stone Circles | `improvement_yield` Quarry: faith 2 |
| God of the Open Sky | `improvement_yield` Pasture: culture 1 |
| Desert Folklore / Dance of the Aurora / Sacred Path | **`adjacency_row`** `{ district = "Holy Site", amount = 1, terrain = { bases = ["Desert"] } }` (one new kind: an extra adjacency row for the owner's districts of that type; consumer `adjacency_score`, which takes the owner's active rows beside the config rows) |

Twelve choices; the pantheon is the first "which tree am I in" decision.

### 7.3 Founding and beliefs

`found_religion(founder_belief, follower_belief)`: the player has a complete
**Holy Site with a Temple** somewhere, has a pantheon, `Player.faith ≥
[religion] found_cost` (**200**, Claude's starting value: with Shrine 2 +
Temple 4 + adjacency ~2 it is ~25 turns of faith after the Temple, around
round 70–90 in the §12 yield model), and fewer than `[religion]
max_religions` (0 = unlimited; Civ 6: half the players + 1 → Duel 2;
default **0**: every player may found, the race is for followers, not for a
slot) religions exist. The Temple's city becomes the religion's **seat** (no
mechanic beyond §7.4's weight). `add_belief(name)` buys tier 2 at
`belief_costs[0]` (**300**) and tier 3 at `belief_costs[1]` (**500**); a
belief is taken by at most one religion (Civ 6) — **`exclusive = true`** in
`[religion]`, Erik's dial (false lets two players share Tithe).

Beliefs are `[beliefs.<Name>]` tables: `tier` (`founder` | `follower` |
`enhancer`), `effects`, and for founder beliefs `counts = "all" | "foreign"`.
The chosen set — "the most interesting" (R7), each either an **augmentation
across systems** or a **reason to spread**:

**Founder** (tier 1, pays the founder per follower city; one new kind
**`per_follower_city`** `{ gold/science/culture/faith = N }`, consumer: the
religion step of `economy_phase`, added to the founder's pools):

| Belief | Pays | Counts |
|---|---|---|
| Tithe | +1 gold per follower city | all |
| Pilgrimage | +2 faith per follower city | foreign |
| World Church | +1 culture per follower city | all |
| Cross-Cultural Dialogue | +1 science per follower city | foreign |

"Foreign" beliefs are the trade-off Erik asked for: they pay *only* when
your neighbour adopts your religion, and your neighbour gets the follower
beliefs too.

**Follower** (tiers 1 and 2; in force in **every city that follows the
religion, whoever owns it** — `active_effects(player, city)` gains the source
"the follower beliefs of `city.religion`", looked up through the founder's
`Player.religion`; scope city):

| Belief | Effect (kind) | What it augments |
|---|---|---|
| Work Ethic | **`cross_yield`** `{ from_district = "Holy Site", to = "production", percent = 100 }` (one new kind; consumer `city_yield`: a district's adjacency score also paid as another yield) | faith → production |
| Choral Music | `cross_yield` Holy Site → culture 100 % | faith → culture |
| Scholars' Patron (ours; #93's "science gives culture as well") | `cross_yield` Campus → culture 50 % | science → culture |
| Feed the World | `city_yield` food +2 (Shrine/Temple cities; the belief requires a Shrine — `requires_building` on the belief, read by the source) | growth |
| Religious Community | `housing_with_building` Shrine +1, Temple +1 (kind exists) | housing |
| Zen Meditation | `amenity` +1, `min_districts = 2` (§3.3) | amenities |
| Jesuit Education | `faith_purchase` `categories = ["campus_buildings", "theater_buildings"]` (two more categories of the existing kind: buildings whose `requires_district` is Campus / Theater Square) | faith buys the science/culture trees' buildings |
| Divine Inspiration | `city_yield` faith +4 `per_wonder = true` (one more attribute, like `per_district`) | wonders → faith |

**Enhancer** (tier 3; scope player, the founder only — about *how* the
religion spreads and what it does in war):

| Belief | Effect |
|---|---|
| Itinerant Preachers | `[religion] range` +3 for this religion's pressure (kind **`religion_param`** `{ range = 3 }`; consumer `religion.pressure`) |
| Missionary Zeal | `religion_param { spread_amount_percent = 50 }`: directed spread adds 150 % |
| Holy Order | `religion_param { cost_percent = -30 }`: spread and inquisition cost 30 % less |
| Crusade | `combat_strength` +10, `scope = "all"`, **`vs_city_of_other_religion = true`** (one more attribute; consumer `Unit.get_combat_strength` when the defender is a City whose `religion` ≠ the attacker's player's religion, None included) — religion matters in a siege |
| Defender of the Faith | `combat_strength` +5, `scope = "all"`, **`in_follower_territory = true`**: units standing on a tile owned by a city following the religion (both roles) |

Five enhancer choices, eight follower, four founder, twelve pantheons:
2 × 4 × 8 × 7 × 5 distinct religions, each a different cross-system shape.

### 7.4 Spread: pressure, conversion, upkeep

**Pressure** of religion R on city C, computed like loyalty pressure
(`loyalty.pressures` generalised to take the source set and weight — one
function, two callers, or `religion.pressure` mirroring it line for line and
a test pinning the two to the same formula on the same inputs):

```
pressure(R, C) = Σ over cities c following R within `range` (9, wrap distance, inclusive)
                  of population(c) * religious_weight(c) * (citizen_weight − distance(c, C))
               + Σ directed entries for R on C (amount, while rounds_left > 0)
religious_weight(c) = 1, + the `religious_weight` columns of c's complete Holy Site (1) and
                      Shrine (1) and Temple (1)  → a seat with Temple weighs 4
C counts for its own religion at distance 0
```

A city with **no religion** resists with `secular_pressure = population *
secular_weight` (2): a small city converts fast, a big city slowly.

**Conversion** (round-end phase `_religion_phase`, after `_loyalty_phase`,
phase-start state, city-id order): C converts to R when `pressure(R, C) *
100 ≥ (pressure(current, C) or secular) * (100 + conversion_margin)` (margin
**25**) for `conversion_rounds` (**3**) consecutive rounds, R being the
strongest foreign pressure; a city under inquisition immunity never
converts. On conversion `City.religion = R`; the city's owner is unchanged
(religion never moves a city — loyalty does). A city with `religion = R`
whose founder is **eliminated** keeps following R (the religion outlives its
founder; its founder beliefs pay nobody).

**Directed spread**: `spread_religion(city)` — any city on the map, own or
foreign, within `range` of a city following the religion — costs
`spread_cost` faith (**100**, rising `spread_cost_step` **25** per use, the
Civ 6 price curve) and appends `(R, spread_amount = 60, spread_rounds = 10)`
to the city's ledger: 60 pressure for ten rounds, against a typical city's
own 5 pop × 1 × 10 = 50. One action, one choice (which city), no unit, no
movement (R7, R8).

**Upkeep** (R7 "maintain"): in the founder's economy phase the religion
costs `upkeep_per_follower_city` faith (**1**) per follower city, own and
foreign. Unpaid (treasury short): the religion is **lapsed** this round —
it projects no pressure and its founder beliefs pay nothing (follower
beliefs still hold: the followers are not punished for the founder's
poverty). A founder who spends every faith point on purchases watches the
religion stall — the choice Erik asked for. The upkeep comes before
purchases are possible (the economy phase runs first).

**Inquisition**: `inquisition(own city)` costs `inquisition_cost` (**75**,
Civ 6's Inquisitor): the city's religion becomes the owner's (or None if the
owner has none) and `inquisition_rounds` (**10**) of immunity begin. The
one active counter; it is a choice because it costs the same faith that
spreads.

### 7.5 What religion touches elsewhere

- **Loyalty**: a city whose religion is not its owner's gets
  `[religion] foreign_religion_loyalty` (**−1**) per round, through one
  more term of `loyalty_delta` (Civ 6 has no such term; Claude's call —
  it ties the non-military conquest paths together and makes a converted
  border city the natural loyalty target. **Open call C6**; 0 disables it).
- **Victory**: `[game] religious_victory = false`. When true: a religion
  followed by more than half of the cities of *every* living player wins
  for its founder (`victory.determine_outcome` gains the branch beside
  domination; recorded as `victory = "religious"`). Off by default like
  domination (#126).
- **Capture / flip**: a city keeps its religion through `set_owner`
  (religion is the city's, not the owner's). Its ledger is kept; immunity
  is kept.
- **Elimination**: handled above; `Player.religion` of a dead player stays
  readable (its follower beliefs keep working).
- **Competition** (§0.3): Holy Sites take specialty slots and production a
  Campus or Theater Square would; faith spent on beliefs is faith not spent
  on purchases; and the follower beliefs that pay the most (`cross_yield`)
  pay through the *other* trees — a religion is a multiplier on the tree you
  already chose, which is why "all three" is hard.

### 7.6 Config

```toml
[religion]
pantheon_cost = 25            # Civ 6
found_cost = 200              # Claude's starting value (§7.3)
belief_costs = [300, 500]     # tier 2, tier 3
max_religions = 0             # 0 = every player may found one
exclusive = true              # a belief belongs to one religion (Civ 6)
range = 9                     # pressure range, hexes (= [loyalty] range)
citizen_weight = 10           # as [loyalty]
secular_weight = 2            # a religionless city's own resistance per citizen
conversion_margin = 25        # percent over the incumbent
conversion_rounds = 3
spread_cost = 100
spread_cost_step = 25
spread_amount = 60
spread_rounds = 10
upkeep_per_follower_city = 1
inquisition_cost = 75
inquisition_rounds = 10
foreign_religion_loyalty = -1
```

`civulator/religion_model.py` parses `[religion]`, `[pantheons.*]`,
`[beliefs.*]` (load order: after `research_model`, with the other
`*_model` modules; effects validated by `effects.py` like every other
list); `civulator/game/religion.py` holds pressure, conversion, upkeep, the
actions' preconditions (`can_choose_pantheon`, `can_found_religion`,
`can_add_belief`, `can_spread_to`, `can_inquisition` — the mask invariant:
every refusal reason is in the predicate).

---

## 8. Loyalty and victory, summarised

Loyalty gains two terms, each one function in its own module called from
`loyalty_delta`: `amenities.loyalty_term` (§3.1) and
`religion.loyalty_term` (§7.5). Victory gains one optional branch (§7.5).
Nothing else in the progression block moves.

---

## 9. Agent actions and engine defaults (for #99)

New actions, each with a predicate the mask calls (one for one with #99's
list; `defaults.py` gets a default only where a game *without* an agent
would otherwise be stuck):

| Action | Precondition predicate | Engine default (absent agent) |
|---|---|---|
| `choose_pantheon(name)` | `can_choose_pantheon` | first affordable pantheon in config order (the research default's rule) |
| `found_religion(founder, follower)` | `can_found_religion` | first available pair in config order, when affordable |
| `add_belief(name)` | `can_add_belief` | first available in config order, when affordable |
| `spread_religion(city)` | `can_spread_to` | **none** — the default spends no faith on spreading (passive spread only) |
| `inquisition(city)` | `can_inquisition` | none |
| `place_district(Dam / …)` | exists (`can_place_district`) | none (as today) |
| sea routes | `establish_trade_route` unchanged; `eligible_destinations` wider | `default_trade` unchanged (picks the best yield, so overseas) |

The defaults for pantheon/founding/beliefs exist so the smoke script and
agentless evaluations exercise the code (`tests/test_determinism.py`'s
contract: identical with or without defaults for the same actions). They are
braindead by design and say so in `defaults.py`; #99 replaces them.

---

## 10. Interactions checked

| Pair | Rule |
|---|---|
| District on a luxury the player has no improvement for | access through the district (§2.3): a Campus on Silk gives the amenity — Civ 6 does this too |
| Encampment breached, enemy stands on it, city captured | the Encampment goes with the city (health → 50 %); the enemy unit on it is now the owner's guest on its own district — legal (own units may stand there) |
| Encampment of a city under loyalty flip | goes with the city, health unchanged (no combat happened) |
| Ship inside a Lake (Harbor on Lake) | legal, useless beyond the lake; the agent learns; a Lake Harbor still terminates sea routes if a water path exists (none) → land-range rules apply |
| Sea route when the Harbor is captured | `end_routes_touching` fires on `set_owner` (exists) |
| Overseas route to a city on another landmass but within land range 15 | still overseas (the landmass test is geographic, not path-based): a strait rewards the Harbor pair |
| Two religions' directed spread on one city | each has its own ledger entries; the strongest foreign pressure is the candidate; margin applies against the incumbent only |
| Founder loses its seat city | nothing: the seat has no mechanic; weights come from Holy Sites wherever they are |
| Religion with zero follower cities (all converted away) | exists, projects nothing, upkeep 0; a `spread_religion` with no follower city in range is refused — the religion is dead unless an inquisition revives it in an own city |
| Amenity band + loyalty band both scale yields | loyalty percent first, then amenity percent, integer tenths, floor once per step; documented in `city_yield` |
| Niter Farm (R2 corner) | a Farm on a Niter tile does not grant Niter (§2.1); the Worker default's replacement rule (#126) builds the Mine when Military Engineering reveals the use — no: the default ranks by yield columns only (ACCEPTED GAP: the default may leave a Niter Farm; the agent (#99) decides) |

---

## 11. Tests (properties, each naming the change that breaks it)

| Property | Breaks if |
|---|---|
| `player_has_access` is true exactly for an owned tile that is improved, districted or a centre; a Farm on Niter is not access | the access rule gains an exception or loses the district clause (R2) |
| A district placed on a strategic/luxury tile keeps the resource; on a bonus tile removes it | `place_district` treats classes alike |
| A resource-gated unit is refused by `player_can_build`, the mask, `purchase` and `upgrade_unit` alike | one caller forgets the predicate |
| Every start region has Horses and Iron within radius 3 of a settleable tile, on every golden world | the fairness rule drops from `place_resources` |
| Golden re-baseline: only `resource` and `params` differ from the previous ceremony `MapData` | resources placement touches terrain |
| Amenity need, supply and band follow the config rows; the last row catches every deficit | a band is hardcoded |
| A luxury serves at most `luxury_cities` cities, the neediest first, ties by id; duplicates count once | the assignment reads a set or counts copies |
| Amenity percent applies after loyalty percent, never to food; growth share multiplies once | the order or the food exemption changes |
| `amenity` effects reach `supply` with `range` / `min_districts` / `requires_garrison` honoured; the Colosseum pays cities within 6 | a carrier bypasses `active_effects` |
| An Encampment tile refuses enemy entry while health > 0 and admits it at 0; own units always pass; the mask agrees with `Unit.move` | the refusal lives in one of the two only |
| An attack on an Encampment damages it with the city's strength and the −17 ranged penalty; it floors at 0; it repairs unless an enemy is adjacent | the defender protocol diverges from the City's |
| A walled city with a complete Encampment strikes twice per turn; without Walls neither strikes | the Encampment strike skips the `ranged_building` gate |
| A land military unit spawns on the Encampment when the centre's slot is full; a ship never does | `place_new_unit`'s candidate order changes |
| A neighbour city's Aqueduct counts for my Industrial Zone (R5) | `_neighbour_matches` starts reading the owner |
| The strategic adjacency row counts an adjacent Iron/Horses/Niter tile once each | the class match in `matches` breaks |
| `regional_yield` pays other own cities within range once (max, not sum) and never the carrier's own city | the consumer sums |
| A Galley enters Coast and Lake, never Ocean, until its owner knows the `ocean_navigation` rule; then Ocean too; cost grids for `"coast"` and `"water"` differ exactly on deep tiles | `deep` or the domain switch is bypassed |
| A city builds a ship only with a spawn water tile; the ship appears on the Harbor first | `can_produce_unit` ignores the domain |
| Melee across domains hits and never moves in; the capture rule is unchanged (a Caravel at a 0-health city does not take it) | the move-in condition or `can_capture_city` changes |
| Combat oracle over the seven pre-0.8 units: byte-identical before and after §6 | a class row touches an existing pairing |
| A pair with Harbors and a coast path ≤ 30 is a sea route; the same pair without Harbors is a land pair; an Ocean-only path needs Cartography | the route test skips the domain or the Harbor |
| Different landmasses → every yield × 2 (percent 100), floor in tenths; a Lake path is never overseas | `landmass_id` or the multiplier moves |
| `landmass_id` is a BFS over canonical adjacency, cached on `terrain_epoch` | hand-rolled adjacency or a stale cache |
| Tech graph still acyclic, every tech reachable, 2–4 open (existing registry property, re-run) | a prerequisite points wrong |
| Pantheon/founding/belief refusals: faith, Holy Site + Temple, pantheon first, `max_religions`, exclusivity | a predicate drops a clause |
| Pressure equals the loyalty formula on the same inputs, plus weights and ledger | the two formulas drift |
| Conversion needs margin for N consecutive rounds, phase-start state, city-id order; immunity blocks it; turn order is irrelevant | the phase reads live state or iterates a set |
| Lapsed religion: no pressure, no founder pay, follower beliefs still in force | upkeep failure punishes followers |
| Follower beliefs apply to a foreign follower city; founder beliefs pay per `counts` | `active_effects` misses the religion source |
| Each new effect kind (`amenity`, `border_cost_percent`, `improvement_yield`, `adjacency_row`, `regional_yield`, `cross_yield`, `per_follower_city`, `religion_param`) moves exactly its consumer and nothing else | a kind grows a second reader (`test_effects.py`'s rule) |
| A religion survives its founder's elimination; a city keeps its religion through capture and flip | `set_owner` or elimination clears it |
| Religious victory fires only with the flag and only at a majority of every living player's cities | the branch misreads the flag or counts dead players |
| Same seed, same actions → identical resources, amenities, religion state (hash-seed subprocess test) | anything iterates a set |

---

## 12. What the state-space pass will need (R9: listed, not designed)

Per tile: resource class and access (improved/districted), landmass id,
`deep`, district health (Encampment), city religion. Per player: pantheon,
religion tiers, faith pool, amenity surplus per city, accessible luxuries
and strategics, naval domain. Per route: sea / overseas flags. None of it is
encoded in this block.

---

## 13. Balancing dials (added to the skill's §4 table at implementation)

| Dial | Moves | Read in |
|---|---|---|
| `[amenities] bands`, `luxury_cities`, `need_divisor` | how much population costs | `amenity_surplus_mean`, `cities_unhappy_rounds` (new stats) |
| `[religion] found_cost`, `belief_costs`, `spread_*`, `upkeep_per_follower_city`, `conversion_*` | when religions appear, how fast they spread, how often they lapse | `religions_founded`, `cities_converted_in/out`, `faith_spent_religion`, `religion_lapsed_rounds` |
| `[trade] sea_range`, `overseas_percent` | the value of a coast | `sea_routes`, `overseas_routes` |
| `[districts.Encampment] health`, `captured_health_percent` | how hard a forward wall is | `encampment_breaches` |
| `[terrain.resource.*] frequency` | luxury diversity, strategic scarcity | `luxuries_accessible_mean`, `units_refused_resource` |
| `[research] tech_cost_percent` | re-tuned for 25 techs | `techs_researched` |

---

## 14. Patch plan

One system per patch (the autonomous-patch-workflow rule); one worktree agent
at a time; every patch merges green `--no-ff` and updates the CHANGELOG
("effect NOT yet measured") and the CLAUDE.md rows in §15(b). Branch per
patch: `<issue#>-<slug>`. **No patch is HUMAN-TEST**; the feel-check is
Erik's reading of this doc and of the smoke script's end line after each.

| # | Patch | Gate | Tier |
|---|---|---|---|
| Q1 | **Resource tiers** (§2): tables, `reveals`/`frequency`, `game/resources.py` access, `requires_resource` on units through `player_can_build`, §2.3 placement rule, `place_resources` classes + fairness rule, golden re-baseline with field diff, smoke counters | §11 rows 1–5; full suite; goldens re-baselined with the diff in the CHANGELOG | Opus (touches mapgen and the canonical `on` evaluator) |
| Q2 | **Amenities + Entertainment Complex** (§3): `amenities.py`, bands, luxuries, `amenity` kind + Colosseum/Classical Republic/Retainers carriers, Arena, consumers in `city_yield`, growth, loyalty | §11 rows 6–9; full suite; smoke | Sonnet (oracle: the integer rules in §3) |
| Q3 | **Encampment** (§4): fortified-district protocol, health, entry refusal + mask, strike, spawn order, capture health | §11 rows 10–13; matchup oracle unchanged; full suite | Opus (touches combat and masks) |
| Q4 | **Industrial Zone** (§5): strategic row, Workshop value, `regional_yield` (if C3 yes), Dam (if C4 yes) | §11 rows 14–16; full suite | Sonnet |
| Q5 | **Sea** (§6): techs + civic + cards, naval classes and units, `deep` + `"coast"` domain, spawn, cross-domain melee, class rows, Great Lighthouse, Colossus/Fishing Boats moves | §11 rows 17–21 + oracle byte-identical; full suite; smoke shows a ship built | Opus (three canonical systems: passability, combat, unit registry) |
| Q6 | **Sea trade** (§6.6): `landmass_id`, sea routes, overseas bonus, `eligible_destinations`, stats | §11 rows 22–24; full suite; smoke shows an overseas route on a two-landmass seed | Sonnet |
| Q7 | **Religion I**: `religion_model`, pantheons + `border_cost_percent`, `improvement_yield`, `adjacency_row` kinds, `choose_pantheon` + default | §11 pantheon rows + kind isolation; full suite | Opus |
| Q8 | **Religion II**: founding, beliefs (`cross_yield`, `per_follower_city`, `religion_param`, the `combat_strength` attributes, `faith_purchase` categories), `active_effects` religion source, defaults | §11 belief rows; full suite | **Fable** (composes effects, yields, combat and purchasing — four canonical systems — and the follower-source semantics are a judgement the suite cannot catch) |
| Q9 | **Religion III**: pressure, ledger, conversion phase, upkeep/lapse, inquisition, loyalty term, religious victory flag, stats, smoke end line, CHANGELOG release of **v0.9.0** (new rules epoch, #78), `docs/game_overview.md`, skill §4/§5 rows | §11 spread rows; determinism subprocess; full suite; seeded smoke | Opus |

Q1 first (R2, §3.2, §5 depend on it). Q2–Q4 and Q5–Q6 are independent
pairs; Q7–Q9 need nothing but the kinds they add. Version: Q1 opens
**v0.9.0** in the CHANGELOG as Unreleased; Q9 dates it.

---

## 15. Systems

### (a) Existing canonical systems this design must use

Game interface (`GameEnvironment`: every mutator) · Hex math
(`get_adjacent_coords`, wrap distance, `path_finder` for sea routes and
`landmass_id`'s BFS) · Terrain model (`matches` with `resources`, `on`
tables for the new resources, `compose` for `deep`, `can_enter` extended
with the `"coast"` domain — the one passability check) · Passability (cost
grids per domain) · World generation (`place_resources`; golden re-baseline
rule) · Terrain epoch (`landmass_id` cache) · Engine RNG (nothing here
draws) · Gameplay config (`CFG`) · Unit system touch list (three ships, two
classes) · Unit/combat config interpreter (class rows) · Combat
(`_execute_attack` with the fortified-district defender; modifiers in both
roles) · City combat (`city_ranged_attack` with an origin tile;
`enemy_city_blocks` pattern for the Encampment) · Siege (generalised to a
tile) · Buildings (Arena, Great Lighthouse columns) · City yields
(`city_yield`: amenity percent, `cross_yield`, `regional_yield`) · Effects
(`active_effects` + the religion source; eight new kinds, one consumer
each) · Research (three techs, one civic, `enables` rule) · Governments and
policies (three cards) · Economy phase (religion upkeep and founder pay, in
its stated place: after maintenance, before research) · Purchasing (two
`faith_purchase` categories) · Trade routes (`eligible_destinations`,
`route_yields` × overseas) · Wonders (Great Lighthouse; Colosseum effects) ·
Loyalty (two terms; `parse_bands` shared) · Territory (`border_cost`
percent; ownership for `in_follower_territory`) · Engine defaults
(`defaults.py`: three braindead defaults, named as such) · Round-end phases
(`_religion_phase` after `_loyalty_phase`) · Victory (one branch, one flag) ·
Building availability (`requires_resource` beside `requires_tech`) · Action
masking (every new precondition is a predicate the mask calls) · Movement
cost (unchanged; the Encampment refusal is an entry rule, not a cost) ·
Districts registry / adjacency / placement / yields (new columns `health`,
`amenity`, `religious_weight`; `adjacency_score` takes owner rows) ·
Artifact manifests (`check_version` gates on 0.9).

### (b) New systems, with draft CLAUDE.md rows (written at implementation, pointing at code)

| System | Where | Draft rule |
|---|---|---|
| Resource access | `game/resources.py player_has_access`; `requires_resource` column; `[terrain.resource.*] class/reveals/frequency` | The only answer to "does this player have Iron": an owned tile with the resource that is improved, districted or a centre. Boolean, never a stockpile; `player_can_build` is its one build-side caller; the encoder, not the engine, decides what is "revealed" |
| Amenities | `game/amenities.py` (`need`, `supply`, `surplus`, `band`, `loyalty_term`), `[amenities]`, the `amenity` column and effect kind | The only happiness computation; luxuries are assigned here and nowhere else; yields read the band through `city_yield`, growth through `growth_bucket_gain`, loyalty through `loyalty_delta` — never a fourth reader |
| Fortified districts | the defender protocol (`health`, `get_combat_strength`, `coordinates`, `player`) on `District`; `[districts.<T>] health` | A district with `health` is attacked through `_execute_attack` like a city, refuses enemy entry while > 0, and strikes when its city may; the Encampment is the first; a second fortified district is a config row, never a new combat path |
| Naval domains | `deep` composed property; `Unit.get_movement_domain` → `"coast"` / `"water"`; the `ocean_navigation` rule | Player-dependent passability lives in the *domain string*, never in a per-player grid; `can_enter` stays the one check |
| Landmasses | `Map.landmass_id(coords)`, cached on `terrain_epoch` | The only continent test; sea trade reads it; a future encoder channel reads it; never recomputed elsewhere |
| Sea trade | `trade.is_sea_route`, `[trade] sea_range / overseas_percent`, `route_yields` multiplier | The only route-kind decision; a route's kind is derived from Harbors and a water path at establishment, never stored twice |
| Religion registry | `civulator/religion_model.py` (`[religion]`, `[pantheons.*]`, `[beliefs.*]`) | The only interpreter; a pantheon or belief is a table of effects; `exclusive`, tiers and costs are columns here |
| Religion engine | `game/religion.py` (`pressure`, `_religion_phase`, upkeep, the five predicates), `Player.pantheon/religion`, `City.religion`, the ledger | The only religious state and the only change of a city's religion; pressure mirrors `loyalty.pressure`'s formula (one test pins them equal); every action has a predicate the mask calls; no RNG |
| Effect kinds added | `amenity`, `border_cost_percent`, `improvement_yield`, `adjacency_row`, `regional_yield`, `cross_yield`, `per_follower_city`, `religion_param` | Each has exactly one consumer named in §3/§5/§7; `DEFERRED_KINDS` stays empty |

### (c) Existing rows amended at implementation

District registry (new columns), Adjacency (owner rows), District placement
(§2.3 resources), Combat (fortified districts), City combat (origin tile;
Encampment strike), Siege (tile-general), Unit system (naval classes; the
touch list gains `requires_resource`), Passability (`"coast"`), Trade routes
(sea/overseas), Loyalty (two terms, shared parser), Victory (religious flag),
Effects (eight kinds), Engine defaults (three more), Round-end phases
(`_religion_phase`), Buildings (`amenity`, `religious_weight` columns),
Building availability (`requires_resource`), Terrain model (`deep`,
`reveals`, `frequency`, class placement), World generation (resource
classes; fairness rule; golden).

---

## 16. Open calls for Erik

| # | Call | Claude's recommendation |
|---|---|---|
| C1 | Strategic access boolean (Civ 5) rather than GS stockpiles; Swordsman and Horseman become resource-gated | yes — one predicate, no new pool; the fairness rule in §2.4 keeps every Duel seat able to build both |
| C2 | Luxury set (nine) and that a district on a luxury grants it | yes; the luxury rule is R2's sentence applied to the other class |
| C3 | Workshop pays +1 production to other own cities within 6 (the Factory's regional effect, moved) | yes — it is what makes two close cities on one river *the* Industrial Zone play |
| C4 | Ship the Dam (Engineering, Floodplains + river; +2 IZ adjacency, +1 housing, +1 amenity) | yes, it is one table |
| C5 | Religion numbers in §7.6; `max_religions = 0`; `exclusive = true`; three tiers rather than #93's "two choices per level" tree | numbers are dials; the tiers *are* the levels (each a choice of one from four to eight) |
| C6 | `foreign_religion_loyalty = −1` | yes, small; 0 turns it off |
| C7 | Religious victory flag exists, off | yes (mirrors domination) |
| C8 | Crusade and Defender of the Faith touch combat strength through two new attributes | yes — they are the two beliefs that make religion matter in a war, which is the game the agents actually play |
| C9 | Three techs + one civic lengthen the trees (+850 science, +220 culture) | accept; re-tune `tech_cost_percent` in the balancing pass, not here |

## Critique (lens table)

| Lens | Verdict | Blockers |
|---|---|---|
| (pending) | | |
