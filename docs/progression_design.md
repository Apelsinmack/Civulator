# Progression (#116): science, civics, gold, faith, wonders, loyalty, winning — design

> **Status: implemented (P1–P9, 2026-10-21); the Implementation notes section records where the code differs.** Written as the v2 build contract (2026-10-21): one critique lens run (systems reuse / regression / determinism, Opus); its seven blockers are resolved in "v2 fixes", which overrides §1–§13 where they differ. Written by Claude as lead game designer on
> Erik's delegation ("you are now the lead game designer, and I want you to
> implement these systems; you have to make all the decisions of where to
> stop", chat 2026-10-21). Erik's brief is in #116; the earlier sketches are
> #90 (science), #92 (culture), #91 (gold), #93 (religion), #100 (winning),
> #101 (game length), and his March 2026 notes (`civulator_notes-20260322.md`:
> cut filler nodes, keep wonders, soften the lost wonder race).
>
> Civ 6 facts (Gathering Storm) are taken from the Civilization Wiki; the
> digest used while writing is `docs/civ6_progression_reference.md`. Where this
> design departs from Civ 6 it says so and why. **Decisions marked "Claude's
> call" are Erik's to overturn**; the ones that reverse an earlier sketch of
> his are listed in §0.3 so he can find them in one place.

## 0. Goal, principles, departures

### 0.1 Goal

The next game version (v0.8.0, a new rules epoch) is **meaningfully more
complex than v0.7**: cities choose between science, culture, gold and faith
as well as food and production; what a city may build depends on what its
owner has researched; policies change how production and combat resolve;
wonders are races; gold pays for armies and buys time; faith is a fourth
currency; cities can change hands without a fight; and the game can be won
in more than one way. Everything in this block is engine state reachable
through `GameEnvironment`, with deterministic engine defaults wherever an
agent action does not yet exist, so that **every system is live in play from
the day it merges**, not dormant until #99.

### 0.2 Principles (Erik's, applied throughout)

1. **Few nodes, always a meaningful choice.** A tree node exists only if it
   unlocks a capability — a unit, a building, a district, a wonder, a policy,
   a rule. No node is a flat +x%. Two real options at a time is plenty.
2. **Content stops where Civ 6 stops being fun**: the last military content is
   the Knight and the Musketman; the last wonders are Medieval.
3. **Config, not code.** Every node, item, effect and number is a
   `config.toml` table read by one interpreter. A new tech, policy, wonder or
   unit is a new table; adding one never edits an `if`.
4. **One seam per effect.** Every kind of effect has exactly one consumer in
   the engine (§3). A modifier is applied in every role it belongs in.
5. **Reasonable starting numbers, auto-balance later.** Costs are Civ 6's,
   scaled by one knob per tree, so a later balancing pass has one dial per
   tree and one per item.
6. **Reports state only what was measured.** This document promises no
   gameplay effect; the CHANGELOG entry says "effect not yet measured".

### 0.3 Departures from Erik's earlier sketches (Claude's calls, flagged)

| Sketch | This design | Why |
|---|---|---|
| #90: unit **tiers** that mutate a unit's stats instead of named upgrade chains | **Named units with `upgrades_to` chains** (Warrior → Swordsman → Man-At-Arms → Musketman, …) | The roster, the encoder's class index, `_create_unit`, the matchup matrix and the build options are all keyed by unit name. A unit whose stats change with its owner's research would make unit identity time- and owner-dependent in every one of those, for no gameplay gain over a chain of named units. The chains ARE tiers, with names. |
| #58 / #92: **culture pressure** — enough culture makes enemy cities defect | **Loyalty** (§8), a per-city pressure model driven by population and distance, not by culture | Erik asked for loyalty from the ground up, Civ 6-inspired (2026-10-21). Culture keeps its two consumers (borders, civics); loyalty is the non-military way to take a city. |
| #90: "every current unit is tier 0 except Archer, tier 2" | Slinger → Archer → Crossbowman is one chain; Archer is simply the Classical ranged unit | follows from the first row |
| #58: Campus science "buys +x% upgrades to yields" | Science buys **techs**; the +% to yields are **policy cards** unlocked by civics (Natural Philosophy +100 % Campus adjacency, etc.) | keeps science and culture distinct trees, as Erik's March notes left open and his 2026-10-21 brief assumes |
| #67 (CHANGELOG): the Swordsman admitted ungated "as the natural answer to Spearman dominance"; Horseman and Catapult buildable from turn 1 | every unit but Warrior, Slinger, Settler and Worker is **tech-gated**: Archer and Spearman by Ancient techs, Swordsman, Horseman and Catapult by Classical ones (Iron Working, Horseback Riding, Engineering) | a tech tree with the strongest early units outside it would be decoration; the opening web is Warrior and Slinger, as in Civ 6. The #60 Spearman question is re-measured after this block (`matchup_matrix`, the ladder) |
| #88: the Palace is a housing-only marker | the Palace gets its Civ 6 yields (science 2, gold 5, production 2) and +1 loyalty per citizen | the capital needs its yields for the trees to start and its loyalty for §8; culture keeps the v0.7 per-city base rather than moving to the Palace (no retune) |

---

## 1. Scope

**In:** (§2) four city yields and four player pools; (§3) one effect schema
and interpreter; (§4) the tech tree, research, and tech-gated items; (§5)
the civics tree, governments and policy cards; (§6) new units and buildings,
combat classes, upgrades; (§7) gold — maintenance, bankruptcy, purchasing,
trade routes; (§8) loyalty; (§9) wonders; (§10) faith and the religion
suggestion; (§11) winning; (§12) game length and cost scaling; (§13)
engine defaults for choices no agent makes yet; (§14) tests; (§15) patches;
Systems.

**Out:**

| Item | Where |
|---|---|
| Agent actions for research, civics, policies, purchase, upgrade, trade, placement; encoder channels for any of it | #99, #111 (Erik: "we don't worry about how the agents interact with the systems yet") |
| Religion as a mechanic (spread, beliefs) | suggestion only, §10.2; #93 |
| Amenities, Entertainment Complex content, Arena/Colosseum amenities | #96; the Colosseum ships with its loyalty and culture effect only |
| Encampment content beyond Barracks; promotions / XP | #94, #61 |
| Great people, governors, era score, golden/dark ages, boosts (eurekas) | not in the game; loyalty has no age multiplier |
| Strategic resources gating units (Iron, Horses, Niter) | #102; units gate on tech alone (Claude's call: resources are schema-ready but unshipped, and a second gate on top of tech doubles the balancing surface) |
| Naval units and naval combat | none; the Harbor, Lighthouse and Colossus are economic content |
| Pillaging, plunder of trade routes, route paths on the map | later; routes are city-to-city links, not units on the map |
| Diplomacy (alliances, open borders) | milestone C |
| Drawing new state in the viewer / painter | later, as for districts |

---

## 2. Yields and pools

### 2.1 City yields

Four per-turn city yields beside food and production: **science, culture,
gold, faith**. All four are computed by **one function**,
`city_yield(city, name)` in `civulator/game/yields.py`, in **integer tenths**
(the culture convention from #87, `unit_model.to_tenths`):

```
city_yield(city, name) =
    [<name>] base                                   # per city
  + [<name>] per_pop * population
  + sum of <name> columns over the city's buildings and complete wonders
  + district_yields(city)[name] * (100 + adjacency_percent(name)) // 100   # §3
  + flat city-yield effects from policies/governments/wonders (§3)
  + trade-route yields to this city (§7.4)
then scaled by loyalty_percent(city) (§8.4), integer floor
```

`culture(city)` (`game/culture.py`) becomes `city_yield(city, "culture")` —
same values as today plus the new sources, so the Theater Square's adjacency
finally reaches its consumer (#92's accepted gap closes).

Per-yield config tables carry the two scalars; today's `[culture]` stays as
it is (base 1.0, per_pop 0.3). New, Civ 6 values:

| Table | base | per_pop | source |
|---|---|---|---|
| `[science]` | 0 | 0.5 | Civ 6: each citizen +0.5 science |
| `[gold]` | 0 | 0 | citizens yield no gold; the Palace, districts, buildings and routes do |
| `[faith]` | 0 | 0 | — |

Flat sources are **columns** on the item's own table, as culture and housing
already are: `science = 2` on `[buildings.Library]`, `gold = 5` on the
Palace, `faith = 2` on the Shrine (§6.2, §9). `unit_model` parses a
`BUILDING_<YIELD>` dict per yield exactly like `BUILDING_CULTURE`.

### 2.2 Player pools

`Player` carries four pools, all integer tenths:

| Pool | Field | Spent on |
|---|---|---|
| science | `Player.science` (exists, now tenths) | the current tech (§4.3) |
| culture | `Player.culture` (exists) | the current civic (§5.3); borders keep their own city pools (#87) |
| gold | `Player.gold` (exists, now tenths) — the treasury | maintenance, purchases, upgrades (§7) |
| faith | `Player.faith` (new) | faith purchases (§10.1) |

Accrual: `City.process_turn`'s culture phase becomes the **yield phase** and
adds all four yields to the owner's pools, once per city per round under the
existing `_culture_round` guard. `episode_stats` gains
`science_produced`, `gold_produced`, `faith_produced` (tenths) beside
`culture_produced`.

### 2.3 Production modifiers

`City.calculate_production` gains one term: the summed `production_percent`
effects (§3) whose target matches the city's **current production item**:

```
production = max(1, base_production * (100 + percent) // 100)
```

applied to the whole per-turn production while the item is being built
(Claude's call: Civ 6 does the same; the city has one production pool, so
switching away keeps what was earned — accepted). Loyalty scales production
too (§8.4).

---

## 3. Effects: one schema, one consumer each

The "general building-effect schema" #98 asked for, used by buildings,
wonders, policies, governments, civics and techs. An item declares

```toml
effects = [
    { kind = "production_percent", target = { unit = "Settler" }, percent = 50 },
    { kind = "combat_strength", scope = "melee", amount = 4 },
]
```

`civulator/effects.py` is the **only interpreter**: it validates every
`effects` list in every table at load (unknown `kind`, missing or unknown
attributes, a target that names nothing in the game → raise), and offers
`active_effects(player, city=None)`: the effect entries currently in force
for a player — from its government, its slotted policies, its unlocked
civics and techs, its complete wonders with `scope = "player"`, and (when a
city is given) that city's buildings and complete wonders with `scope =
"city"`. Pure; recomputed on every call, as `district_yields` is.

Kinds — **closed set**; each has exactly one consumer:

| kind | attributes | attaches to | consumed by |
|---|---|---|---|
| `city_yield` | `science/culture/gold/faith/food/production = N` (any subset); optional `capital_only = true` | policies, governments, wonders (scope player) | `city_yield` (§2.1); food/production terms in `calculate_food` / `calculate_production` |
| `production_percent` | `target` (one of `unit = "Name"`, `unit_class = "melee"…`, `unit_era = ["Ancient","Classical"]`, `building = "Name"`, `kind = "wonder" | "district" | "building" | "unit"`), `percent` | policies, governments, wonders | `calculate_production` (§2.3) |
| `adjacency_percent` | `district = "Campus"`, `percent` | policies | `city_yield` (§2.1) |
| `combat_strength` | `scope` (`melee`, `anti_cavalry`, `ranged`, `light_cavalry`, `heavy_cavalry`, `siege`, `all`, `city`), `amount` | governments, policies, wonders | `Unit.get_combat_strength` / `get_ranged_strength` (both roles); `City.get_combat_strength` for `city` |
| `unit_maintenance_delta` | `amount` (per unit, may be negative) | policies | maintenance (§7.1) |
| `upgrade_cost_percent` | `percent` | policies | `upgrade_cost` (§6.4) |
| `purchase_percent` | `resource`, `percent` | governments, policies | `purchase_cost` (§7.3) |
| `faith_purchase` | `categories = ["land_military"]` | governments, wonders | `can_purchase` (§7.3) |
| `trade_route_capacity` | `amount` | buildings, wonders, civics, governments | `route_capacity` (§7.4) |
| `loyalty` | `amount`, optional `range` (0 = this city), optional `requires_garrison = true` | buildings, wonders, policies | `loyalty_sources` (§8.2) |
| `growth_percent` | `percent` | wonders | the growth bucket in `process_turn` |
| `policy_slots` | `military/economic/diplomatic/wildcard = N` | governments (their slots), wonders | `slot_counts` (§5.4) |
| `enables` | `rules = ["flanking"]` | civics | the named rule's gate (`flanking` → `Unit.get_combat_strength`) |
| `free_units` | `[{ unit = "Worker", count = 3 }]` | wonders | **one-shot** on completion, placed through `complete_unit_production` |
| `free_tech` / `free_civic` | `count` | wonders | one-shot on completion: completes the current research/civic (or the auto-pick) at no cost |
| `free_population` | `amount`, `all_cities = true` | wonders | one-shot on completion |
| `housing_if_districts` | `amount`, `min_districts` (0 = every city) | governments, policies, wonders | `housing(city)` |
| `housing_with_building` | `building`, `amount` | governments | `housing(city)` |
| `route_yield` | `gold/culture/science/food/production = N`, optional `international_only = true` | policies | the route term of `city_yield` (§7.4) |
| `city_ranged_strength` | `amount` | policies | `City.get_ranged_strength` |

`city_yield` takes one optional `per_district = true` (Meritocracy: the
amount is multiplied by the city's complete specialty districts).

`housing`, `culture`, `science`, `gold`, `faith`, and now `food` and
`production`, on a building, district or wonder stay **columns** (the
#87/#88 pattern), not effects; the loader rejects a `city_yield` effect on a
building so there is one way to say it. `food` / `production` columns are
read by `calculate_food` / `calculate_production` (Palace +2 production,
Granary +1 food, Workshop +3 production, Barracks +1, Lighthouse +1 food).

One-shot effects fire inside `GameEnvironment` when the wonder completes
(§9.3), never on load or capture.

---

## 4. Science: the tech tree

### 4.1 Research

`[research]` + one `[techs.<Name>]` table per tech (`cost`, `era`,
`requires = [...]`, optional `effects`). `civulator/research_model.py` is the
only interpreter of `[research]`, `[techs.*]`, `[civics.*]`,
`[governments.*]` and `[policies.*]` (one module: the four tables share the
prerequisite/unlock vocabulary).

An item is gated by a column on **its own table**: `requires_tech = "Writing"`
on `[districts.Campus]`, `[buildings.Library]`, `[units.Archer]`,
`[improvements.Mine]`, `[districts.Pyramids]`; `requires_civic` likewise
(§5). Loading raises on a name that is not a tech/civic. "What a tech
unlocks" is **derived** by inverting those columns (for tooling and the
CHANGELOG), never declared twice.

`player_can_build(player, kind, name)` is the one availability check: the
item's `requires_tech` / `requires_civic` are in `Player.techs` /
`Player.civics` (sets). Every build path reads it: `get_valid_build_mask`
(mask invariant — an unresearched option must never be offered),
`can_place_district` (districts and wonders), `can_build_improvement_at`,
`purchase`, `upgrade_unit`. Captured units and buildings are kept whatever
the new owner knows (Civ 6).

### 4.2 The tree

Chosen for impact (each node unlocks something you could not do before).
Civ 6 names, costs and eras; **our own prerequisites**, drawn so that 2–4
techs are available at any time and every path reaches the end. Costs are
scaled by `[research] tech_cost_percent` (§12).

Cut from Civ 6's span: Sailing, Wheel, Shipbuilding, Mathematics,
Construction, Buttress (no naval, no Water Mill, no Petra, no Terracotta Army)
and every Renaissance tech but Gunpowder. 22 techs remain; Civ 6 has 33 in
the same span. Prerequisites differ from Civ 6 only where a cut tech sat in
between.

| Tech | Era | Cost | Requires | Unlocks here |
|---|---|---|---|---|
| Pottery | Ancient | 25 | — | Granary |
| Animal Husbandry | Ancient | 25 | — | Pasture, Camp |
| Mining | Ancient | 25 | — | Mine, Quarry |
| Astrology | Ancient | 50 | — | Holy Site, Shrine, Stonehenge |
| Irrigation | Ancient | 50 | Pottery | Plantation, Hanging Gardens |
| Writing | Ancient | 50 | Pottery | Campus, Library |
| Archery | Ancient | 50 | Animal Husbandry | Archer, Temple of Artemis |
| Masonry | Ancient | 80 | Mining | Walls, Battering Ram (still deferred, #66), Pyramids |
| Bronze Working | Ancient | 80 | Mining | Spearman, Encampment, Barracks |
| Celestial Navigation | Classical | 120 | Astrology | Harbor, Lighthouse, Fishing Boats, Colossus (Civ 6: Shipbuilding) |
| Currency | Classical | 120 | Writing | Commercial Hub, Market |
| Horseback Riding | Classical | 120 | Archery | Horseman (**now gated**; it was buildable from turn 1) |
| Iron Working | Classical | 120 | Bronze Working | Swordsman (now gated; #67 admitted it ungated) |
| Engineering | Classical | 200 | Masonry (Civ 6: Wheel) | Catapult (now gated), Aqueduct |
| Military Tactics | Medieval | 300 | Bronze Working, Currency (Civ 6: Mathematics) | Pikeman |
| Apprenticeship | Medieval | 300 | Currency, Horseback Riding | Industrial Zone, Workshop, Man-At-Arms |
| Machinery | Medieval | 300 | Iron Working, Engineering | Crossbowman, Siege Tower (deferred) |
| Education | Medieval | 335 | Apprenticeship (Civ 6: + Mathematics) | University |
| Military Engineering | Medieval | 335 | Engineering (Civ 6: Construction) | Trebuchet |
| Stirrups | Medieval | 390 | Horseback Riding, Apprenticeship | Knight |
| Castles | Medieval | 390 | Military Engineering (Civ 6: Construction) | Medieval Walls, Alhambra |
| Gunpowder | Renaissance | 600 | Apprenticeship, Stirrups, Military Engineering | Musketman |

Four techs are available at the start; the lattice keeps 2–4 open until
Gunpowder, which closes it. The sum is 4,015 science at Civ 6 costs (§12).

Improvements (Mine, Pasture, …) are live content only once Workers build
them — P8 (§15) gives idle Workers an engine default so a tech that unlocks
an improvement is not a dead node. The Oil Well improvement, which no tech
in this span could unlock, is removed from config.

### 4.3 Resolution

At the end of `Player.start_turn`'s city phase (after every city has
accrued), `GameEnvironment.resolve_research(player)`:

1. if `current_tech` is `None`, **auto-pick** (§13);
2. if `science >= 10 * cost(current_tech) * tech_cost_percent // 100`:
   subtract, add to `Player.techs`, `current_tech = None`, record
   `episode_stats["techs_researched"] += 1`. **One completion per turn**
   (Civ 6); overflow stays in the pool.

`GameEnvironment.set_research(player, tech)` chooses (refused unless
available: all `requires` known, not owned). Switching loses nothing: the
pool is one number, not per-tech progress (Claude's call: simplest honest
design; Civ 6's per-tech progress exists to stop switching exploits that an
agent gains nothing from here).

`game_progress(player)` (`game/districts.py`) returns the larger of
`(len(techs), total techs)` and `(len(civics), total civics)` as a fraction —
the #86 hook, now live: district costs escalate.

---

## 5. Culture: civics, governments, policies

### 5.1 Civics

`[civics.<Name>]`: `cost`, `era`, `requires`, optional `effects` (the
`enables` kind lives here: **flanking becomes a civic unlock**, Civ 6's
Military Tradition, closing #59's "gate it behind culture eventually").
Resolution mirrors §4.3 on `Player.culture` with `civic_cost_percent`;
`set_civic`; `episode_stats["civics_researched"]`.

Cut from Civ 6's span: Mysticism (its only content for us, the Oracle, moves
to State Workforce), Naval Tradition, Medieval Faires' envoy card, every
Renaissance civic (Exploration's Merchant Republic and Reformed Church's
Theocracy go: Theocracy moves to Divine Right so that one node offers two
Tier-2 governments), every diplomatic card (no city-states) and every
great-person card. 19 civics remain; Civ 6 has 24 in the span.

| Civic | Era | Cost (GS) | Requires | Unlocks here |
|---|---|---|---|---|
| Code of Laws | Ancient | 20 | — | Chiefdom; God King, Urban Planning |
| Craftsmanship | Ancient | 40 | Code of Laws | Ilkum, Agoge |
| Foreign Trade | Ancient | 40 | Code of Laws | Trader, +1 route capacity; Caravansaries |
| Military Tradition | Ancient | 50 | Craftsmanship | **flanking** (`enables`); Maneuver |
| State Workforce | Ancient | 70 | Craftsmanship | Government Plaza; Conscription, Corvee; Oracle (Civ 6: Mysticism) |
| Early Empire | Ancient | 70 | Foreign Trade | Colonization, Limitanei |
| Games and Recreation | Classical | 110 | State Workforce | Entertainment Complex; Insulae; Colosseum |
| Political Philosophy | Classical | 110 | State Workforce, Early Empire | Autocracy, Classical Republic, Oligarchy |
| Drama and Poetry | Classical | 110 | Early Empire | Theater Square, Amphitheater |
| Military Training | Classical | 120 | Military Tradition (Civ 6: + Games and Recreation) | Veterancy; Statue of Zeus |
| Theology | Classical | 120 | Drama and Poetry (Civ 6: + Mysticism) | Temple; Scripture |
| Defensive Tactics | Classical | 175 | Games and Recreation, Political Philosophy | Bastions, Limes |
| Recorded History | Classical | 175 | Drama and Poetry, Political Philosophy | Natural Philosophy; Great Library |
| Feudalism | Medieval | 300 | Defensive Tactics | Feudal Contract |
| Civil Service | Medieval | 300 | Defensive Tactics, Recorded History | Meritocracy (the vanilla card) |
| Mercenaries | Medieval | 340 | Feudalism, Military Training | Professional Army, Trade Confederation |
| Divine Right | Medieval | 340 | Civil Service, Theology | Monarchy, Theocracy (Civ 6: Reformed Church); Chivalry, Gothic Architecture; Forbidden City (Civ 6: Printing) |
| Medieval Faires | Medieval | 420 | Feudalism | Aesthetics, Medina Quarter; Angkor Wat |
| Guilds | Medieval | 420 | Feudalism, Civil Service | Craftsmen, Town Charters |

The sum is 3,100 culture at GS costs (§12).

### 5.2 Governments

`[governments.<Name>]`: `requires_civic`, `tier`, `effects` (its
`policy_slots` and its inherent bonus). A player has `Player.government`
(None until Code of Laws). `set_government(player, name)` is refused unless
the civic is known. No switching penalty (Claude's call: Civ 6's anarchy turn
exists for humans; an agent changing government every turn gains nothing).
Civ 6's **diplomatic** slots become wildcard slots here (no diplomatic
cards exist); legacy bonuses are dropped.

| Government | Tier | Civic | Slots M / E / W | Inherent bonus (effects) |
|---|---|---|---|---|
| Chiefdom | 0 | Code of Laws | 1 / 1 / 0 | none |
| Autocracy | 1 | Political Philosophy | 1 / 1 / 2 | `city_yield` +1 food, production, science, culture, gold, faith, `capital_only`; `production_percent` wonders +10 |
| Classical Republic | 1 | Political Philosophy | 0 / 2 / 2 | `housing_if_districts` +1 in every city with ≥ 1 specialty district |
| Oligarchy | 1 | Political Philosophy | 2 / 1 / 1 | `combat_strength` +4 for `melee` and `anti_cavalry` |
| Monarchy | 2 | Divine Right | 2 / 1 / 3 | `housing_with_building` +1 per Walls and per Medieval Walls; `production_percent` +50 toward Walls and Medieval Walls |
| Theocracy | 2 | Divine Right | 2 / 2 / 2 | `faith_purchase` land military (Civ 6 vanilla; GS moved it to the Grand Master's Chapel, which also grants it here); `purchase_percent` faith −15 |

Two new effect kinds for the housing cards and governments, both consumed
by `housing(city)`: `housing_if_districts` (`amount`, `min_districts`) and
`housing_with_building` (`building`, `amount`). They are added to §3's table.

### 5.3 Policy cards

`[policies.<Name>]`: `type` (`military` / `economic` / `diplomatic` /
`wildcard`), `requires_civic`, optional `obsolete_with` (a civic), `effects`.
`Player.policies` is the list of **slotted** cards. A loadout is legal when
every card is unlocked and not obsolete, distinct, and fits its slot type or
a wildcard slot; `set_policies(player, names)` is refused otherwise.

Civ 6's cards, kept where their effect has a consumer here (Military =
M, Economic = E):

| Card | T | Civic | Effect (kind) | Obsolete with |
|---|---|---|---|---|
| God King | E | Code of Laws | `city_yield` +1 faith, +1 gold, `capital_only` | Theology |
| Urban Planning | E | Code of Laws | `city_yield` +1 production | — |
| Ilkum | E | Craftsmanship | `production_percent` +30, `unit = "Worker"` | — |
| Agoge | M | Craftsmanship | `production_percent` +50, classes melee/ranged/anti_cavalry, eras Ancient+Classical | Feudalism |
| Caravansaries | E | Foreign Trade | `route_yield` +2 gold per route (one more kind: consumed by the route term of `city_yield`) | — |
| Maneuver | M | Military Tradition | `production_percent` +50, classes light/heavy cavalry, eras Ancient+Classical | Divine Right |
| Conscription | M | State Workforce | `unit_maintenance_delta` −1 | — |
| Corvee | E | State Workforce | `production_percent` +15, `kind = "wonder"`, eras Ancient+Classical | Divine Right |
| Colonization | E | Early Empire | `production_percent` +50, `unit = "Settler"` | — |
| Limitanei | M | Early Empire | `loyalty` +2, `requires_garrison` | — |
| Insulae | E | Games and Recreation | `housing_if_districts` +1, `min_districts = 2` | Medieval Faires |
| Veterancy | M | Military Training | `production_percent` +30 toward Encampment and Harbor districts and their buildings | — |
| Scripture | E | Theology | `adjacency_percent` +100, Holy Site | — |
| Bastions | M | Defensive Tactics | `combat_strength` +6 `city`; `city_ranged_strength` +5 (one more attribute of the same kind) | — |
| Limes | M | Defensive Tactics | `production_percent` +100 toward Walls and Medieval Walls | — |
| Natural Philosophy | E | Recorded History | `adjacency_percent` +100, Campus | — |
| Feudal Contract | M | Feudalism | `production_percent` +50, classes melee/ranged/anti_cavalry, eras Ancient–Renaissance | — |
| Meritocracy | E | Civil Service | `city_yield` +1 culture per specialty district (attribute `per_district = true`) | — |
| Professional Army | M | Mercenaries | `upgrade_cost_percent` −50 | — |
| Trade Confederation | E | Mercenaries | `route_yield` +1 culture, +1 science per international route | — |
| Aesthetics | E | Medieval Faires | `adjacency_percent` +100, Theater Square | — |
| Medina Quarter | E | Medieval Faires | `housing_if_districts` +2, `min_districts = 3` | — |
| Craftsmen | E | Guilds | `adjacency_percent` +100, Industrial Zone | — |
| Town Charters | E | Guilds | `adjacency_percent` +100, Commercial Hub | — |
| Chivalry | M | Divine Right | `production_percent` +50, classes light/heavy cavalry, all eras | — |
| Gothic Architecture | E | Divine Right | `production_percent` +15, `kind = "wonder"`, all eras | — |

Dropped: Survey, Discipline (barbarians), Maritime Industries, Strategos,
Land Surveyors (tile purchase), Serfdom (charges), Retainers and Civil
Prestige (amenities, governors), Raid (pillage), Equestrian Orders
(resources), the diplomatic and great-person cards.

### 5.4 Slots

`slot_counts(player)` = the government's `policy_slots` + every active
`policy_slots` effect (Alhambra, Forbidden City). When slots shrink (a
government change) the loadout is truncated newest-first; when a card goes
obsolete it is dropped. Empty slots are filled by the default rule (§13).

---

## 6. Units, buildings, combat classes, upgrades

### 6.1 Combat classes

Every `[units.*]` table declares `combat_class`: `melee`, `anti_cavalry`,
`ranged`, `light_cavalry`, `heavy_cavalry`, `siege`, `support`, `civilian`;
and `era`. The three name-keyed modifiers in `Unit.get_combat_strength` /
`get_ranged_strength` become one class-pair table in `[combat]`:

```toml
# applied to the unit of class `unit` in BOTH roles against a target of class `target` (#63)
class_bonuses = [
    { unit = "anti_cavalry", target = "light_cavalry", amount = 10 },
    { unit = "anti_cavalry", target = "heavy_cavalry", amount = 10 },
    { unit = "melee",        target = "anti_cavalry",  amount = 5 },
    { unit = "ranged",       target = "light_cavalry", amount = -5 },   # today's archer_vs_horseman_penalty
]
```

`siege_class = true` is replaced by `combat_class = "siege"` (the ranged
city-penalty exemption keys on the class). **Bit-identity gate**: every
existing unit pairing produces the same numbers as before
(`tests/test_unit_config_identity.py` extended; `scripts/matchup_matrix.py`
run before and after must agree on every existing pair). `CLASS_INDEX`
(`state_encoders.py`) is derived from `combat_class` (melee 0, anti-cavalry
1, ranged 2, light and heavy cavalry 3, siege 4; support/civilian −1), so a
new unit adds no channel.

### 6.2 New units and buildings

**Units.** Civ 6 GS stats; existing units keep their v0.7 numbers
(Horseman 35 not 36, Catapult 23 not 25 — not retuned). `maintenance` is gold
per turn; `era` and `combat_class` are new columns on every unit.

| Unit | Class | Era | Cost | CS / RS / range / move | Tech | Maint. | Upgrades to |
|---|---|---|---|---|---|---|---|
| Warrior | melee | Ancient | 40 | 20 / — / — / 2 | — | 0 | Swordsman |
| Slinger | ranged | Ancient | 35 | 5 / 15 / 1 / 2 | — | 0 | Archer |
| Archer | ranged | Ancient | 60 | 15 / 25 / 2 / 2 | Archery | 1 | Crossbowman |
| Spearman | anti_cavalry | Ancient | 65 | 25 / — / — / 2 | Bronze Working | 1 | Pikeman |
| Horseman | light_cavalry | Classical | 80 | 35 / — / — / 4 | Horseback Riding | 2 | Knight (Claude's call: one cavalry line; Civ 6 has Courser) |
| Swordsman | melee | Classical | 90 | 35 / — / — / 2 | Iron Working | 2 | Man-At-Arms |
| Catapult | siege | Classical | 120 | 23 / 35 / 2 / 2 | Engineering | 2 | Trebuchet |
| Battering Ram, Siege Tower | support | Ancient, Classical | 65, 100 | 0 | Masonry, Machinery | 1, 2 | — (deferred, #66) |
| **Man-At-Arms** | melee | Medieval | 160 | 45 / — / — / 2 | Apprenticeship | 3 | Musketman |
| **Pikeman** | anti_cavalry | Medieval | 180 | 45 / — / — / 2 | Military Tactics | 2 | — |
| **Crossbowman** | ranged | Medieval | 180 | 30 / 40 / 2 / 2 | Machinery | 3 | — |
| **Knight** | heavy_cavalry | Medieval | 220 | 50 / — / — / 4 | Stirrups | 4 | — |
| **Trebuchet** | siege | Medieval | 200 | 35 / 45 / 2 / 2 | Military Engineering | 3 | — |
| **Musketman** | melee | Renaissance | 240 | 55 / — / — / 2 | Gunpowder | 4 | — |
| Settler, Worker | civilian | Ancient | 120, 50 | 0 | — | 0 | — |
| **Trader** | civilian | Ancient | 40 | 0 / 2 move | Foreign Trade (civic) | 0 | — |

Class bonuses (`[combat] class_bonuses`, both roles, #63): anti_cavalry vs
light_cavalry +10 (today's Spearman vs Horseman), anti_cavalry vs
heavy_cavalry +10 (Civ 6), melee vs anti_cavalry +5 (today's Warrior/
Swordsman vs Spearman), ranged vs light_cavalry −5 and vs heavy_cavalry −5
(today's archer-vs-horseman penalty, extended to the Knight — Claude's
call). A row may name `unit_class` or a single `unit` on either side, so the
implementer can express today's rule exactly as it is applied today (e.g. if
the archer penalty applies to the Archer only, not the Slinger) — the
bit-identity gate decides, not this table.

**Buildings.** Civ 6 GS; `maintenance` 0 where the wiki is silent.
`purchasable` per §7.3.

| Building | Cost | Maint. | Requires | Columns / effects |
|---|---|---|---|---|
| Monument (exists, 50) | 50 | 0 | — | culture 2 (v0.7), `loyalty` +1; **enters BUILD_OPTIONS** (closes #73's gap) |
| Granary (exists, 60) | 60 | 0 | Pottery | housing 2 (v0.7), food 1 (#98) |
| Walls (exists, 100) | 100 | 0 | Masonry | defense_bonus 30 (v0.7); not purchasable |
| Palace (granted) | — | 0 | — | housing 1 (v0.7), science 2, gold 5, production 2, `loyalty` +1 per citizen |
| Workshop (exists, 120, inert) | 195 | 1 | Apprenticeship; Industrial Zone | production 3 (#98; cost raised to Civ 6's — it was unbuildable and inert) |
| Factory (exists, inert) | removed | | | beyond the tree (Industrialization) |
| **Library** | 90 | 1 | Writing; Campus | science 2 |
| **University** | 250 | 2 | Education; Campus, Library | science 4, housing 1 |
| **Market** | 120 | 0 | Currency; Commercial Hub | gold 3, `trade_route_capacity` 1 |
| **Lighthouse** | 120 | 0 | Celestial Navigation; Harbor | food 1, gold 1, housing 1, `trade_route_capacity` 1 |
| **Shrine** | 70 | 1 | Astrology; Holy Site | faith 2; faith-purchasable |
| **Temple** | 120 | 2 | Theology; Holy Site, Shrine | faith 4; faith-purchasable |
| **Amphitheater** | 150 | 1 | Drama and Poetry; Theater Square | culture 2 |
| **Barracks** | 90 | 1 | Bronze Working; Encampment | production 1, housing 1 |
| **Medieval Walls** | 220 | 0 | Castles; Walls | defense_bonus 30 (total 60); not purchasable |
| **Ancestral Hall** | 150 | 1 | a Tier-1 government; Government Plaza | `production_percent` +50 Settler, `scope = "city"`; not purchasable |
| **Grand Master's Chapel** | 290 | 2 | a Tier-2 government; Government Plaza, Ancestral Hall | faith 5, `faith_purchase` land military; not purchasable |

A building's `requires_government_tier` is one more gate read by
`city_can_build_building`. Trade-route capacity from Market and Lighthouse
counts **once per city** (Civ 6; `route_capacity` takes the max per city,
not the sum). Districts gain `requires_tech` / `requires_civic` (Campus:
Writing; Holy Site: Astrology; Encampment: Bronze Working; Commercial Hub:
Currency; Harbor: Celestial Navigation; Aqueduct: Engineering; Industrial
Zone: Apprenticeship; Theater Square: Drama and Poetry; Entertainment
Complex: Games and Recreation; Government Plaza: State Workforce) and a
`maintenance` column (Campus, Theater Square, Holy Site, Industrial Zone,
Encampment, Entertainment Complex 1; Commercial Hub, Harbor, Aqueduct,
Government Plaza 0 — Civ 6: the gold districts pay for themselves).

A building may declare `requires_district = "Campus"` (a complete district of
that type in the city) and `requires_building = "Shrine"`; `produce_building`,
the build mask and `purchase` all read them through one predicate,
`city_can_build_building(city, name)`.

### 6.3 Build options

`BUILD_OPTIONS` grows **by appending** (the #67 contract): the new buildings,
then the new units, then the Trader. `get_valid_build_mask` gains the
availability gate (§4.1), `requires_district` / `requires_building`, and the
Trader's capacity test (§7.4). Districts and wonders stay out (#99).

### 6.4 Upgrades

`upgrades_to = "Swordsman"` on `[units.Warrior]` etc. `GameEnvironment.
upgrade_unit(unit)`: refused unless the target is `player_can_build`, the
unit stands on a tile its owner owns, has full movement and has not attacked;
costs `upgrade_cost(unit)` = `[gold] upgrade_per_production (2) *
(target cost − unit cost) + upgrade_base (10)` gold, scaled by
`upgrade_cost_percent` effects (the wiki states no formula; this one
reproduces its single data point, Slinger → Archer = 60, and is the
community's reading of the game files); the unit becomes the target type at
the same health, movement spent. No engine default (§13): dormant until #99,
like `swap_tile` — **ACCEPTED GAP**, recorded in the CHANGELOG.

---

## 7. Gold

### 7.1 Maintenance

`maintenance = N` columns on `[units.*]` and `[buildings.*]` (Civ 6 values).
At the start of the owner's turn, after the cities have accrued:

```
treasury += 0                      # yields were added by the cities
treasury -= 10 * (sum unit maintenance (+ unit_maintenance_delta effects, floored at 0 per unit)
                  + sum building maintenance + sum complete-district maintenance)
```

### 7.2 Bankruptcy

If the treasury is negative after maintenance, units are **disbanded one at
a time** — highest maintenance first, oldest first among equals (unit
creation order, never set iteration) — each refunding nothing, until the
treasury is ≥ 0 or no unit with maintenance remains; then the treasury is
floored at 0. Deterministic and brutal: an army the economy cannot carry
shrinks (Erik's reason for the whole economy, #91). `episode_stats
["units_disbanded"]`.

### 7.3 Purchasing

`purchasable = ["gold"]` / `["gold", "faith"]` / `[]` on each unit and
building table (districts and wonders are never purchasable, Civ 6; nor
are Walls, Medieval Walls and the Government Plaza buildings). Default:
every unit and building `["gold"]`; Shrine and Temple `["gold", "faith"]`;
land military units gain `"faith"` through `faith_purchase` (§3).
`purchase_cost(player, kind, name, resource)` =
`production_cost * [gold] purchase_multiplier (4)` (Civ 6: gold is 4×
production) or `* [faith] purchase_multiplier (2)` (Civ 6: faith is 2×),
scaled by `purchase_percent` effects; `GameEnvironment.purchase(city, kind, name,
resource)`: refused unless affordable, purchasable with that resource,
`player_can_build`, `city_can_build_building`, and — for faith — the
category is unlocked by a `faith_purchase` effect when the item's table says
`faith_category = "land_military"`. A purchased unit is placed by
`complete_unit_production` (or queued as production is); a purchased building
is appended as a built one. Nothing about ownership depends on how an item
was obtained. No engine default (§13): dormant until #99 — **ACCEPTED GAP**.

### 7.4 Trade routes

Civ 6's trade, reduced to what matters: a **Trader** (civilian unit, slot 1,
`requires_civic = "Foreign Trade"`) is produced or bought in a city; `
GameEnvironment.establish_trade_route(trader, destination_city)` consumes
the unit and records a `TradeRoute(origin_city_id, destination_city_id,
player_index, turns_left)` on the player. Refused unless the destination is
another city within `[trade] range` (15, Civ 6's land range) hexes
(canonical wrap distance from the origin), at most one route between any
two cities, and `len(routes) < route_capacity(player)` = the Foreign Trade
civic's `trade_route_capacity` 1 + one per city holding a Market or a
Lighthouse (max, not sum, per city — Civ 6) + wonder effects (Colossus).

Yields, per turn, to the **origin city** (a term of `city_yield`, §2.1), are
Civ 6's **destination-district rule**: every complete district at the
destination, the city centre included, adds a fixed amount, from two config
tables `[trade.domestic.<District>]` and `[trade.international.<District>]`
(a district absent from a table adds nothing; a name that is not a district
raises):

| District at destination | Domestic route (same owner) | International route |
|---|---|---|
| City Center | 1 food, 1 production | 3 gold |
| Campus | 1 food | 1 science |
| Holy Site | 1 food | 1 faith |
| Theater Square | 1 food | 1 culture |
| Entertainment Complex | 1 food | 1 food |
| Encampment, Industrial Zone | 1 production | 1 production |
| Commercial Hub, Harbor | 1 production | 3 gold |
| Government Plaza | 1 food, 1 production | 2 gold |

plus every `route_yield` effect in force (Caravansaries +2 gold per route;
Trade Confederation +1 culture +1 science per international route). The
destination's owner gets nothing (Civ 6). Food and production from routes
are the first non-tile source of either: `calculate_food` /
`calculate_production` read the route term through `city_yield(city,
"food")` / `"production"`.

A route lasts `[trade] duration_turns` (21, Civ 6's minimum; no round-trip
arithmetic, no era extension); when it ends, a Trader reappears at the
origin (through `complete_unit_production`) and idles. An idle Trader is
**auto-sent** by the engine default (§13) so trade stays live without an
agent. Routes end when either city is captured or destroyed (the Trader
returns to the origin if it still belongs to the player; otherwise it is
lost). No plunder, no path on the map.

---

## 8. Loyalty

Designed from the ground up on Erik's request, Civ 6-inspired: a city whose
people are surrounded by a larger foreign population drifts away from its
owner, and a city that reaches zero loyalty **changes hands without a
fight**. It is the non-military way to take a city that #58 wanted from
"culture pressure", and it is a direct counter to the one strategy the
ladder measured (win by founding cities, #58): a city planted next to a big
foreign neighbour must be held — by a garrison, a Monument, policies — or it
is lost.

### 8.1 State

`City.loyalty`, an integer 0..100, in `[loyalty]`: `founded = 100` for a
new city; `captured = 50` for a city taken by force or by a flip (Claude's
call: a conquest must be consolidated, which is what gives Limitanei,
garrisons and the Colosseum a job). Travels with the city.

### 8.2 Pressure (Civ 6's formula, in integers)

For a city C and a player P, the **pressure** P exerts on C is the sum over
P's cities c within `[loyalty] range` (9, Civ 6) of

```
population(c) * (10 - distance(c, C))        # canonical wrap distance; Civ 6: -10 % per tile
```

C itself counts for its owner (distance 0, the heaviest weight). No age
multiplier: there are no eras of fortune here.

Per round, with `own` = the owner's pressure and `foreign` = the sum of
every other player's pressure (Civ 6):

```
drift   = clamp( 20 * (own - foreign) // (2 * min(own, foreign) + 1), -20, +20 )
          # Civ 6: 10 * (own - foreign) / (min(own, foreign) + 0.5), capped at ±20
sources = [loyalty] garrison (2) if a combat unit of the owner stands on the centre
          (Claude's call: Civ 6 has no inherent garrison term, only Limitanei; here a
          garrison is the one lever a player has on turn one)
        + sum of `loyalty` effects in force for the city (§3): Monument +1; Palace +1 per
          citizen (`per_population = true`); Colosseum +2 to every own city within 6;
          Limitanei +2 with a garrison; Government Plaza +8 (a `loyalty` column on the
          district, read like a building's)
delta   = drift + sources
```

The wiki's worked example (own 31, foreign 45 → −4.4) gives −4 here. A city
alone (foreign 0) drifts up by 20 and sits at 100. Example, Duel map: a pop-1
city five tiles from a pop-6 enemy capital, no other cities in range: own
10, foreign 30 → drift −19; a garrison and a Monument make it −16; it flips
in about six rounds. Civ 6's curve is steep near parity, and that is the
intended cost of forward settling: a city planted in a bigger neighbour's
shadow is held by population, not by a flag.

### 8.3 Phase

`GameEnvironment._loyalty_phase`, run from `next_turn` after `_border_phase`
(same round-end discipline: every city, whoever owns it, from the state at
phase start, so turn order cannot decide a contest). Deltas are computed for
all cities first, then applied, then flips are resolved in city-id order.
Integers only, no RNG.

### 8.4 Bands

`[loyalty] bands = [[min, yield_percent, can_grow], ...]`, first match wins,
same shape as housing's growth bands:

| loyalty | yields (science, culture, gold, faith, production) | growth (share of surplus) |
|---|---|---|
| 76–100 (Loyal) | 100 % | 100 % |
| 51–75 (Wavering) | 75 % | 75 % |
| 26–50 (Disloyal) | 50 % | 25 % |
| 1–25 (Unrest) | 0 % | 0 % |

Civ 6's bands exactly. `loyalty_percent(city)` is read by `city_yield`
(§2.1) and `calculate_production` (which keeps its floor of 1); the growth
share multiplies the housing band's percent in `process_turn`. Food is not
scaled (starvation is a separate punishment).

### 8.5 Revolt

At phase end a city at loyalty 0 **flips to the player exerting the largest
foreign pressure** (ties by player index; there always is one: own pressure
alone never reaches 0). Civ 6 makes it a Free City first and lets it petition
to join; there is no neutral owner here, so the flip is direct — the
non-military conquest #58 asked for. The flip is
`GameEnvironment._flip_city(city, new_player)`: the old owner's units on the
centre tile are deleted (counted as its `losses`), `City.set_owner` moves
the city, its tiles, districts and wonders exactly as a capture does,
loyalty resets to `captured`, `episode_stats` records `cities_flipped_out` /
`cities_flipped_in`. `_capture_city` is untouched: capture and flip are two
doors, `set_owner` is the one room behind both.

The capital is protected the Civ 6 way, by the Palace's +1 loyalty per
citizen, not by immunity (Civ 6: "a Capital can in principle flip").

### 8.6 What loyalty is not

No free cities (no neutral owner exists in the engine and every system
would need one); no governors; no amenities term until #96 exists (the
schema takes one more source then); no effect on units, trade or borders.

---

## 9. Wonders

### 9.1 A wonder is a district with `kind = "wonder"`

The district registry (`[districts.*]`, #86) gains `kind = "district" |
"wonder"` (default `district`). A wonder is a district table with
`counts_toward_limit = false`, `max_per_city = 1`, `adjacency_yield` absent,
placement rules in the existing vocabulary (`on`, `requires_adjacent`,
`adjacent_to_city_center`), `requires_tech` / `requires_civic`, `cost_model =
"fixed"` (Civ 6: wonder costs do not escalate), yield **columns** and
`effects`. So **placing, paying for and completing a wonder is the district
path**, unchanged: `can_place_district`, `place_district`,
`produce_district`, the production branch of `process_turn`. One registry,
one placement check, one production branch.

Differences, all in the registry's `kind` test:

- **World-unique.** `can_place_district` refuses a wonder any player has
  **completed**; placed-but-unfinished copies elsewhere are the race.
- **No population slot, no discount, no "any district" adjacency**: a wonder
  is not a district for the `district = "any"` rows. A new source key
  `wonder = "any"` counts adjacent complete wonders (Theater Square: +2 per
  adjacent wonder, Civ 6).
- **Capture**: a wonder goes with its city like every district (#86 ruling);
  one-shot effects never fire again.

### 9.2 Losing the race

When a wonder completes, every other city's placed copy is **removed**
(tile freed, `district_epoch` bump, `assign_tiles` re-run) and
`[wonders] consolation_percent` of the removed copy's locked cost is
refunded into that city's production pool. Erik's March notes: the decision
to attempt a wonder must stay interesting, not a trap; a 50 % refund keeps
the race a gamble rather than a dead end (Claude's call on the number).

### 9.3 Effects

Columns for flat yields and housing; `effects` for the rest (§3);
`scope = "player" | "city"` says where a non-one-shot effect applies.
One-shot effects (`free_units`, `free_tech`, `free_civic`,
`free_population`) fire in `GameEnvironment` the moment `complete` becomes
true — which is why completion moves from `City.process_turn` into a
`GameEnvironment.complete_district(city, district)` call that the production
branch invokes (one place for "a district just completed").

### 9.4 The set

Twelve, chosen so that each tree has wonder races on it, every era has
some, and every one changes something a player does (growth, armies,
loyalty, policy slots, free research). Civ 6 costs; requirements moved
where a cut tech or civic held them; placement in the §1.2/§2 vocabulary
of the district registry.

| Wonder | Era · cost | Requires | Placement (`on` / `requires_adjacent`) | Columns · effects |
|---|---|---|---|---|
| Pyramids | Ancient 220 | Masonry | flat Desert **or Plains** (Claude's call: Civ 6 is Desert-only; our Duel maps may hold little desert and Erik asked for this one) | culture 2; `free_units` Worker ×3 (Civ 6: one Builder + a charge; Erik: "quite a few builders", cost comparable to the builders) |
| Stonehenge | Ancient 180 | Astrology | flat, adjacent to a Stone resource | faith 4 (Civ 6: +2 and a Great Prophet; no prophets here) |
| Hanging Gardens | Ancient 180 | Irrigation | river on an edge of its tile (`river_on_tile`, accepted in `requires_adjacent`) | housing 2; `growth_percent` +15, scope player |
| Temple of Artemis | Ancient 180 | Archery | adjacent to a Cattle, Sheep or Deer resource (Civ 6: a Camp) | food 4, housing 3 |
| Oracle | Classical 290 | State Workforce (civic; Civ 6: Mysticism) | hills | culture 2, faith 2; `free_civic` 1 (Claude's call: Civ 6's great-person discount has no object here) |
| Statue of Zeus | Classical 400 | Military Training (civic) | flat, adjacent to an Encampment | gold 3; `free_units` Spearman ×3, Archer ×3; `production_percent` +50 anti_cavalry, scope player |
| Great Library | Classical 400 | Recorded History (civic) | flat, adjacent to a Campus | science 3; `free_tech` 1 (Civ 6: +2 and boosts for every Ancient/Classical tech) |
| Colossus | Classical 400 | Celestial Navigation (Civ 6: Shipbuilding) | Coast, adjacent to land and to a Harbor | gold 3; `trade_route_capacity` 1; `free_units` Trader ×1 |
| Colosseum | Classical 400 | Games and Recreation (civic) | flat, adjacent to an Entertainment Complex | culture 2; `loyalty` +2, `range` 6, scope player (own cities only) |
| Alhambra | Medieval 710 | Castles | hills, adjacent to an Encampment | `policy_slots` military 1; `combat_strength` `city` +6, scope city (Civ 6: "as a Fort") |
| Angkor Wat | Medieval 710 | Medieval Faires (civic) | adjacent to an Aqueduct | faith 2; `free_population` 1 all cities; `housing_if_districts` +1, `min_districts` 0 (every city) |
| Forbidden City | Renaissance 920 | Divine Right (civic; Civ 6: Printing) | flat, adjacent to the city centre | culture 5; `policy_slots` wildcard 1 |

Civ 6's "completing a wonder claims two more tiles" and the amenity effects
are not implemented (**ACCEPTED GAP**: borders have their own system, and
amenities do not exist).

---

## 10. Faith

### 10.1 In this block

Faith is a yield (§2), a pool, and a purchase currency (§7.3): Shrine and
Temple are faith-purchasable; Theocracy's `faith_purchase =
["land_military"]` lets faith buy armies. Sources: Holy Site adjacency,
Shrine, Temple, Stonehenge, the Oracle, God King. That is enough for faith
to be "another build class the agents can focus on" (Erik) without a
religion.

### 10.2 Suggestion: religion as shared augmentation (not implemented)

Erik's constraints (#93, 2026-10-21): not a copy of Civ 6; religion
**augments** other systems ("the Campus gives culture as well as science");
a religion that spreads gives its bonus **to the receiving civ too**; no
missionary micromanagement; Holy Sites and faith stay. A design that fits
all four, for a later session:

1. **Pantheon** (faith sink one): at `[religion] pantheon_cost` faith a
   player picks one pantheon from a short config list; a pantheon is an
   `effects` list (§3), player-scoped, permanent. Examples: *God of the
   Forge* (+25 % production toward Ancient/Classical military); *Fertility
   Rites* (+10 % growth); *Scholars' Patron* (every Campus also yields
   culture equal to half its science — an `adjacency_percent`-style kind,
   `cross_yield`, one new effect kind); *Religious Settlements* (border
   claims cost 20 % less).
2. **Religion** (faith sink two): a player with a Holy Site and a Temple
   founds a religion at `[religion] found_cost`, choosing two **follower
   beliefs** from a list of effects that apply **to every city that follows
   the religion, whoever owns it**, plus one **founder belief** that pays
   the founder per foreign follower city (gold, science or culture per
   turn). The follower beliefs are the augmentations Erik describes; the
   founder belief is why spreading pays even though it strengthens the
   neighbour.
3. **Spread is pressure, not units.** Each city carries `religion`
   (None or a name). Religious pressure is computed exactly like loyalty
   pressure (§8.2) from cities that follow a religion, with a Holy Site
   weighting its city up and a Temple more; a city converts when a
   religion's pressure exceeds its current religion's by `[religion]
   conversion_margin` for `conversion_turns` consecutive rounds. Resolved
   in the loyalty phase. No missionaries, no apostles, no theological
   combat; faith can be spent on **Inquisition** (reset a city's religion
   to the owner's) as the one active counter.
4. **Victory hook:** a religious win = a majority of all living players'
   cities following your religion (§11 takes it as a config flag when the
   mechanic exists).

Everything above is config tables plus one pressure function already
written for loyalty; the only new engine state is `City.religion` and
`Player.religion`. It is a one-patch mechanic once this block is in.

---

## 11. Winning

#100's gap closes with the two cheapest honest rules; the richer victory
types wait until agents play the trees and we can see what they do.

1. **Elimination** — unchanged (`determine_winner`).
2. **Domination** (new, outright): a player who holds **every Palace in the
   game** wins at the end of any turn, whether or not the other players still
   have cities (Civ 6: capture all capitals). In a Duel this is "take the
   enemy capital"; it rewards the decisive strike over the grind, and it is
   the first win condition that does not require killing every last city.
   Checked in `_check_game_end` beside elimination; the Palace is the only
   capital marker (#88 rule).
3. **Turn-cap score** (`player_score`, the one formula, #55) grows terms, all
   weights in `[game.score]`:

   ```
   score = cities * city_weight (10) + units * unit_weight (1)
         + population * population_weight (1)
         + techs * tech_weight (2) + civics * civic_weight (2)
         + wonders * wonder_weight (10)
   ```

   Starting weights are Claude's; they make a full tech tree worth about
   four cities and a wonder worth one. Erik tunes while the agents play.

Not now, named so the next pass does not re-derive them: a **tree victory**
(first to complete the tech tree) and a **religious victory** (§10.2) as
config flags; a culture victory needs tourism or an equivalent and is not
designed.

`scripts/evaluate.py`, the trainer and the viewer HUD all keep calling
`determine_winner` / `player_score`; `games_detail[]` gains `victory`
(`"elimination" | "domination" | "score" | "draw"`) so the eval record says
how a game was won.

## 12. Game length and cost scaling

#101 asked for the target before any paced content lands. The target is
**the training cap, 250 rounds** (`[training] max_turns`): the trees should
be *nearly* exhausted by a strong player around round 200 and well short of
that for an ordinary one, so that tree choices matter for the whole game
and the end of the tree is a late-game event, not a mid-game one.

A back-of-the-envelope yield model on the Duel preset (one player, cities
founded at rounds 1, 40, 80, 120; population growing one point per twelve
rounds to the housing cap; a Campus with a Library by round 90, a second
Campus by 140, a University by 180):

| rounds | science / round | cumulative science | culture / round | cumulative culture |
|---|---|---|---|---|
| 1–50 | 2–4 | ~150 | 2–4 | ~150 |
| 50–100 | ~10 | ~650 | ~7 | ~500 |
| 100–150 | ~18 | ~1550 | ~12 | ~1100 |
| 150–200 | ~26 | ~2850 | ~17 | ~1950 |
| 200–250 | ~32 | ~4450 | ~22 | ~3050 |

The tree in §4.2 sums to 4,015 science at Civ 6 costs and the civics in
§5.1 to 3,100 culture, which the model finishes only at the cap or past it.
Civ 6's own Quick speed scales costs to 67 %; a 250-round game against
Civ 6's 500 is closer to Online speed (50 %), but our yields are also
lower than Civ 6's. **Both knobs start at 75 %** (`[research]
tech_cost_percent = 75`, `civic_cost_percent = 75`): the model then puts
the last tech around round 215 and the last civic around round 230. The two
knobs exist so the balancing pass has one dial per tree; a measured curve
replaces this table in the first evaluation report after the block merges
(`techs_researched` / `civics_researched` per game are in the episode stats
for exactly that).

District costs escalate from this block on (`game_progress`, §4.3): a
Campus placed with half the tree known costs `54 * (1 + 9 * 0.5) = 297`
(Civ 6's own curve). Wonder and unit costs do not escalate (Civ 6).

Truncation stays a bug (#51): the step guard is unchanged; the turn cap is a
normal ending with a score.

## 13. Engine defaults where no agent chooses yet

| Choice | Default (deterministic, no RNG) | Overridden by |
|---|---|---|
| current tech / civic | cheapest available; ties in config order | `set_research` / `set_civic` |
| government | on unlocking a civic that grants one, adopt it if it is a higher tier than the current one; ties (the three Tier-1s) by config order | `set_government` |
| policy loadout | whenever slots or unlocked cards change: keep legal cards, then fill each empty slot with the newest unlocked card of its type not yet slotted (wildcard: newest of any type); newest = latest civic, then config order | `set_policies` |
| idle Trader | at its owner's turn start, send it to the eligible destination with the highest total yield to the origin; ties by city id | `establish_trade_route` |
| idle Worker | build the best available improvement under it, else one step toward the nearest owned tile where it could (§15 P8) | #99's improvement action |
| purchase, upgrade, district/wonder placement, production | none (production: the build agent, as today) | #99 |

Defaults live in `civulator/game/defaults.py` and are called from
`GameEnvironment` only, so a future agent action replaces one call.

## v2 fixes (critique round 1, lens: systems reuse / regression / determinism)

Where this section and §1–§13 differ, **this section wins**. Numbers refer
to the critic's findings (B = blocker, N = non-blocking).

**Load order and config ownership (B4, B5, i)**
- Import order: (1) `research_model` parses `[research]`, `[techs.*]`,
  `[civics.*]`, `[governments.*]`, `[policies.*]`: names, costs,
  prerequisites, raw `effects` lists — it validates nothing that names a
  unit, building or district. (2) `unit_model`, `terrain_model`,
  `district_model` parse their own new columns (`requires_tech`,
  `requires_civic`, `requires_district`, `requires_building`,
  `requires_government_tier`, `maintenance`, `purchasable`, `combat_class`,
  `era`, `upgrades_to`, `kind`, yield and loyalty columns, raw `effects`),
  validating `requires_*` names against `research_model`'s name sets.
  (3) `effects.py` validates every spec's `effects` **from those parsed
  specs**, never from `CFG`, and resolves targets against the three
  registries. (4) `game/`. No cycle.
- One interpreter per new table: `[science]`, `[gold]`, `[faith]` →
  `unit_model` (beside `[culture]`, `[housing]`, `[buildings]`);
  `[wonders]` → `district_model`; `[trade]` → `game/trade.py`;
  `[loyalty]` → `game/loyalty.py`; `[game.score]` → `training/trainer.py`
  (beside `city_score_weight`, which **stays** in `[game]`; the new weights
  go in `[game.score]`).
- Improvement gating: `terrain_model` parses `requires_tech` on
  `[improvements.*]` into an accessor; `environment.py`'s direct
  `CFG["improvements"]` read is replaced by that accessor in the same patch
  (P2). `can_build_improvement_at(coords, name)` stays the **tile predicate**
  (unchanged, so `test_terrain_repoint` holds); new
  `GameEnvironment.can_player_build_improvement_at(player, coords, name)` =
  tile owned by one of the player's cities (`Map.owner_city`) and
  `player_can_build` and the tile predicate. `WorkerUnit.build_improvement`
  and the worker default call the new one.

**Improvement yields (B6)** — improvements yield nothing today, so a tech
that unlocks one would be a dead node. `[improvements.*]` gains optional
`food`, `production`, `gold` columns, parsed by `terrain_model` and added to
`Tile.yields` (the sum over the tile's improvements, read live: improvements
are not layers). Civ 6 base values, to be checked by the implementer on the
wiki improvement pages: Farm food 1; Mine, Quarry, Pasture production 1;
Camp, Plantation gold 1; Fishing Boats food 1. `build_improvement` bumps
`terrain_epoch` (Claude's call: it changes a tile's gameplay numbers, and
every yield cache keys on that epoch; improvements are rare events).
`gold` on a tile is a new tile yield dimension read by `city_yield(city,
"gold")` over worked tiles — the one place tile gold is summed.
The worker default ranks by (food + production + gold) gain, ties by
config order.

**Player state and reset (B3)** — `Player.reset_state()` holds every
per-episode field (pools, `techs`, `civics`, `current_tech`,
`current_civic`, `government`, `policies`, `routes`, `queued_units`,
`palace_granted`, …) and is called from `__init__` and from
`_reset_attempt`'s `recreate_players=False` path in place of the field-by-
field list. Env-level registries (none are added: wonder uniqueness is
computed from live state, N9) reset in `_reset_city_registry`. New test:
play N rounds, `reset(seed)`, fingerprint (new state included) equals a
fresh environment's `reset(seed)`.

**`Player.techs` / `civics` are lists in completion order (N2)**, replacing
the unused `Player.technologies`; membership tests only; registries are
iterated in config order; the auto-pick key is `(scaled cost, config
index)`; "newest" means last in the list.

**Combat classes and the bit-identity gate (B2, N14)**
- A `class_bonuses` row has `strength = "combat" | "ranged"`: combat rows
  are read by `get_combat_strength` (both roles, as today's +10/+5), ranged
  rows only by `get_ranged_strength` (the shooter). Today's archer rule is
  the row `{ unit = "Archer", target = "light_cavalry", amount = -5,
  strength = "ranged" }` — Archer by name, shooter only, exactly as
  `unit.py` applies it now; the heavy-cavalry extension is a second row
  with the same shape. The Slinger gets no penalty (today it has none).
- The gate: `scripts/matchup_matrix.py --units Warrior Slinger Archer
  Swordsman Spearman Horseman Catapult` with one seed before and after;
  `test_unit_config_identity` rewritten as literal per-pair strengths
  (attacker, defender, role, combat/ranged), Slinger included, in place of
  the three constants it pins today.
- Keyed on class from now on: the siege "needs movement to fire" rule
  (`unit.py:560`), `is_siege_class`, civilian capture
  (`environment.py:624`: class `civilian`, so the Trader is captured, not
  killed), `flanking_count`'s "combat-capable" test (base strength > 0 is
  fine as is).
- `UNIT_CLASSES` (name → subclass) becomes one exported dict in
  `game/city.py` next to `_create_unit`; `scripts/matchup_matrix.py` and
  `civulator/tools/recording.py` import it, and recording's silent
  `WarriorUnit` fallback becomes a raise.

**Yields: units, scaling and adjacency (N4, N5, N22)**
- `city_yield` returns science/culture/gold/faith in tenths **scaled by
  loyalty**, and food/production in whole points **unscaled**. Loyalty is
  applied once, at the consumer: production = `max(1, (tiles + columns +
  routes) * (100 + production_percent_sum) // 100 * loyalty_percent //
  100)`; growth bucket (hundredths, as today) `food_surplus += food_net *
  housing_percent * growth_share * (100 + growth_percent_sum) // 10000`.
- The district term is `10 * district_yields(city, percent_by_district)
  [name]`; `adjacency_percent` is keyed by **district**, and
  `district_yields` applies it per district before summing — still the one
  conversion of adjacency into yields. §2.1's `adjacency_percent(name)` is
  withdrawn.
- Effects of one kind are **summed, then applied once** with an integer
  floor (N3): `production_percent`, `purchase_percent`,
  `upgrade_cost_percent`, `growth_percent`, `adjacency_percent`.
- `episode_stats` values stay ints; `district_yield_<name>` stays the raw
  adjacency score, unscaled.

**District registry readers (N6, N7, N8, N23)**
- Every reader of the registry outside `district_model` goes through
  `game/districts.py`'s accessor `district_spec(type)` (so the synthetic
  fixture in `test_district_yields` keeps working).
- A **specialty district** is `kind == "district" and counts_toward_limit`;
  Meritocracy, Classical Republic, Insulae, Medina Quarter, trade's
  "complete district" rule and `housing_if_districts` count exactly those.
- `requires_adjacent_all` (every listed source must match some neighbour)
  joins `requires_adjacent` (any); Colossus = `on` Coast,
  `requires_adjacent_all` [land base, Harbor]. `river_on_tile` is accepted
  as a tile test in `requires_adjacent`. `_DISTRICT_KEYS` lists every new
  key.
- The discount's A stays "configured discounted types" (**ACCEPTED GAP**:
  Civ 6 counts unlocked types).

**Wonders (N9, N19, N25, e)** — uniqueness is computed from live state
(every city's districts, in `city_by_id` order), no registry. Race losers
are removed through one helper `GameEnvironment._remove_district(city,
district)` shared with `remove_city`. `free_tech` / `free_civic` complete
at once, outside the one-per-turn rule; `free_population` re-runs
`assign_tiles` in every city. The race is decided inside the completing
player's turn, so turn order can decide a same-round tie — accepted and
stated in the CHANGELOG. `test_districts.py:735`'s "every entry escalates"
is restated as "every `kind == "district"` entry escalates; `fixed` never".

**Flips, captures and `set_owner` (f, N17, N26)**
- `City.set_owner` is **the one place a city changes hands**; it also
  resets `loyalty` to `captured`, ends every trade route touching the city
  (Traders of the player who keeps a city return to it; others are lost),
  and drops `queued_units` entries for the city. `_capture_city` (force) and
  `_flip_city` (loyalty) are its only callers — the City combat row is
  amended accordingly (B7). An unavailable in-progress item is kept and may
  complete (it was paid for; **accepted**).
- A flip pays **no reward** (there is no reward channel at round end) and
  increments only `cities_flipped_*`, not `cities_captured`. Whether the
  training objective should see flips is Erik's call, listed in the report.
- `Player.queued_units` is revived for every unit that cannot be placed
  (free units, purchases, returning Traders): entries are `(city_id,
  unit_type)`, placed at the owner's turn start as today.
- After the loyalty phase, `next_turn` runs the one verdict function (below)
  so a flip can end the game.

**Turn order (g)** — `Player.start_turn`: exploration → unit reset and heal
→ cities → **economy phase** in this order: maintenance; bankruptcy;
research; civics; government and loadout defaults; route expiry and Trader
return; Trader auto-send; Worker default → `city_ranged_attack` → queued
units. Round end in `next_turn`: `_border_phase` → `_loyalty_phase` → the
verdict → `turn_counter += 1`. A player whose last city flips plays one
more turn and dies in `end_turn`, as after a capture.

**Loyalty arithmetic (N1, N13)** — drift truncates toward zero:
`q = (20 * abs(own - foreign)) // (2 * min(own, foreign) + 1)`, `drift =
clamp(sign * q, -20, 20)` (the wiki's example gives −4, the Duel example
−19). Loyalty is clamped to 0..100 after the delta. §14's "the Palace city
never flips" is withdrawn: the capital is protected by the Palace's +1 per
citizen only (§8.5).

**Upgrades and bankruptcy (N15, N16)** — an upgrade replaces the unit
object through `_create_unit` at the same `player.units` index and the same
tile slot (health copied, movement 0, fortification 0). "Oldest" is the
index in `player.units`.

**Worker default (N18)** — moves through `Unit.move` to the adjacent
enterable tile that minimises the canonical distance to the chosen target
tile, ties by coordinates; never `path_finder`. Target = the nearest owned
tile (by `distance_function`, ties by coordinates, candidates from
`Map.tiles_of_city` over the player's cities in city-id order) where
`can_player_build_improvement_at` holds for some improvement.

**Verdict and domination (N12)** — `determine_outcome(env) -> (winner,
victory)` in `trainer.py` is the one verdict: elimination; domination
(P holds every Palace in the game **and** at least one Palace granted to
another player — so a painted board with no Palace, or a lone player, never
wins vacuously); turn-cap score; else `(None, None)`. `determine_winner`
wraps it. Called from `_check_game_end` and from `next_turn` after the
loyalty phase. A truncated game's `victory` is `null`, never `"draw"`
(#51). `evaluate.py` records each seat's weights `game_version` beside the
engine's in the summary (archived 0.7 weights play 0.8 rules; the record
must say so).

**Patch sequencing (N10, N11)**
- P1 also bumps `__version__` to 0.8.0, regenerates the fixture and opens
  the CHANGELOG entry, so no artifact saved under 0.8 rules carries a 0.7
  manifest.
- P2 gates districts on **techs only** and ships only the buildings whose
  gates it can validate: Library, University, Shrine, Barracks, Medieval
  Walls, the Workshop change, Granary/Monument/Walls gates, Factory removed.
- P3 adds the Trader's table but keeps it in `DEFERRED_BUILD_UNITS` (a
  build option that cannot pay off, #67) until P5 un-defers it.
- P4 adds the civic and government gates (Theater Square, Entertainment
  Complex, Government Plaza; Temple, Amphitheater, Ancestral Hall, Grand
  Master's Chapel) with the effects interpreter.
- P5 adds Market and Lighthouse (their `trade_route_capacity` effect needs
  P4's interpreter and P5's routes).
- P8's smoke script draws production from `get_valid_build_mask`, never
  `random.choice(BUILD_OPTIONS)` (N20).

**Encoder (N21)** — the class channels clamp at the existing `MAX_*`
constants; Knight (50) and Musketman (55) saturate the melee channel.
**ACCEPTED GAP**: the constants stay (changing them shifts every trained
`.pth`'s inputs); #111 revisits the input space.

**Gating list reconciled (N24)** — the opening web is Warrior and Slinger;
Archer (Archery), Spearman (Bronze Working), Granary (Pottery) and Walls
(Masonry) arrive with Ancient techs; Horseman, Swordsman and Catapult with
Classical ones. §0.3's row is corrected to say so. The build-mask docstring
in `build_agent.py` changes with it.

**Pre-existing tests the design changes (B1)** — a failing pre-existing
test is a finding, never a target; each one below is restated so that its
property keeps its strength. A shared `grant_all(player)` helper in
`tests/conftest.py` (every tech and civic known) serves tests whose subject
is not availability. Three inversions are intentional and named:

| Test | Today it asserts | Restated as |
|---|---|---|
| `test_district_yields.py:144 test_districts_do_not_change_culture_or_production` | district yields reach nothing | **inverted (P1)**: a complete district raises exactly its yield; an incomplete one nothing |
| `test_flanking_bonus.py` (8 tests, `flanking_on` fixture) | flanking is always on | **inverted (P4)**: with Military Tradition known, the #59 numbers; without it, 0; the fixture grants the civic |
| `test_player_score.py:20-34` | `cities * weight + units` | **inverted (P9)**: the `[game.score]` sum, with every new term exercised |
| `test_districts.py` (20 placement tests via `placeable_type()`), `test_district_yields.py` (7, incl. the seeded-completion test) | any district is placeable | `grant_all` in the fixture; one new test asserts refusal without the tech (P2) |
| `test_build_options.py` Swordsman mask/produce tests | offered from turn 1 | offered **once Iron Working is known**, refused before (P2) |
| `test_build_options.py:230` civilian exemption `{"Settler","Worker"}` | two civilians | every `combat_class == "civilian"` unit (P3) |
| `test_city_walls.py` (2) | Walls always offered | with Masonry known (P2) |
| `test_housing.py::test_the_palace_cannot_be_produced` | `produce_building("Granary")` is True | with Pottery known (P2) |
| `test_terrain_repoint.py::test_improvement_validity_reads_the_on_constraints` | tile predicate on an unowned board | unchanged: `can_build_improvement_at` stays the tile predicate (B5) |
| `test_districts.py:735 test_escalation_is_integer_and_fixed_never_scales` | `game_progress(None) == (0, 1)`; every entry escalates | a player with no techs is `(0, total)`; every `kind == "district"` entry escalates, `fixed` never (P2, P6) |
| `test_unit_config_identity.py:137-146` | three modifier constants | per-pair literal strengths, both strengths, Slinger included (P3) |
| `test_district_yields.py:228` capture test | `== 3` after `set_owner` | holds: the stat stays unscaled (N22); a new assertion checks loyalty reset to `captured` (P7) |

## Critique (lens table)

| Lens | Verdict | Blockers |
|---|---|---|
| Systems reuse, regression and determinism (Opus, 2026-10-21) | survives with fixes | B1 pre-existing tests unnamed; B2 class table not bit-identical (archer penalty is shooter-only, Archer-only) and the matrix excludes the Slinger; B3 new Player state leaks across `reset()`; B4 config ownership / cyclic import order; B5 `can_build_improvement_at` has no player; B6 worker default ranks by yields that do not exist; B7 CLAUDE.md rows contradicted without amendment. 26 non-blocking points, all folded in above. Full text: the session scratchpad `critique_lens1_systems.md` |
| Rules semantics (not run) | — | Erik reads the rules himself (he is the rules authority); implementers report semantic contradictions as findings |

**Synthesis (v2).** One lens, survives with fixes; all seven blockers
resolved in "v2 fixes" above, the non-blocking points folded in. v2 is the
build contract.

## 14. Tests (properties, each naming the change that breaks it)

Written from this section, never from the implementation. No test pins the
set, count or order of techs, civics, policies, wonders, units or build
options — those are designed to grow; every test asserts the rule each
member obeys.

| Property | Breaks if |
|---|---|
| `city_yield(city, "culture")` equals today's `culture(city)` for a city with no districts, wonders, routes or effects (v0.7 fixture values) | the refactor changes culture numbers |
| Every yield source is a column or an effect; `yields.py` contains no building, district, wonder or policy name | a source is special-cased in code |
| A complete Theater Square / Campus / Holy Site / Commercial Hub raises its city's culture / science / faith / gold by exactly its adjacency score; an incomplete one by nothing | district yields reach the wrong consumer or are double-counted |
| The four pools grow by the sum of the owner's cities' yields once per round; a city captured mid-round accrues once | the once-per-round guard is lost |
| Every `effects` entry in every table has a known `kind` and valid attributes; an unknown kind, a `city_yield` effect on a building, or a target naming nothing raises at load | the loader accepts junk |
| Each effect kind is consumed exactly where §3 says (one test per kind with a synthetic policy) | a kind gains a second consumer or loses its one |
| An item with `requires_tech` is refused by the build mask, `produce_*`, `can_place_district`, `can_build_improvement_at`, `purchase` and `upgrade_unit` until its tech is known; the mask never offers it before | any one path skips `player_can_build` (mask invariant, #51) |
| A `requires_tech` / `requires_civic` / `requires` / `requires_district` / `requires_building` naming nothing raises at load | validation is skipped |
| Research completes exactly when the pool reaches the scaled cost, at most one tech per turn, overflow kept; `set_research` refuses an unavailable tech | resolution drifts or allows two per turn |
| `game_progress` is the larger of the two tree fractions and district cost follows `base * (den + 9*num) // den` | the #86 hook is fed wrongly |
| With every tech of the tree known, every unit, building, district and wonder is available; every tech is reachable from the start (prerequisite graph acyclic and connected) | a dead node or an unreachable item |
| Class bonuses: every existing unit pairing's attack and defence strength is bit-identical to v0.7 (`matchup_matrix` before/after; `test_unit_config_identity`) | the class table changes an old number |
| `CLASS_INDEX` is derived from `combat_class`; the encoder channel count is unchanged | a new unit adds a channel |
| A government's and the slotted policies' effects are in force; a card of the wrong type, an obsolete card, a duplicate or an unlocked-but-unslotted card has no effect; `set_policies` refuses an illegal loadout | the loadout check or the aggregation drifts |
| Flanking adds nothing until the civic that enables it is known, then exactly `[combat] flanking_bonus` per flanking tile (the #59 numbers) | the rule gate is lost or the bonus changes |
| Maintenance is deducted once per owner turn; at a negative treasury units are disbanded highest-maintenance-first, oldest-first, until it is non-negative; the treasury never ends a turn negative | bankruptcy order depends on iteration order |
| Purchase costs `production_cost * multiplier` scaled by effects, is refused when unaffordable / not purchasable / not available / wrong resource, and yields a unit placed by `complete_unit_production` or a building in `city.buildings` | purchase bypasses the build rules or the placement path |
| Upgrade: refused without the target's tech, off own territory, without full movement; cost per §7.3; type, health and movement per §6.4 | any precondition is dropped |
| A trade route needs a Trader, a destination within range, and free capacity; its yields reach the origin's `city_yield`; it ends after `duration_turns` with a Trader back at the origin; capture of either city ends it | route bookkeeping drifts |
| A wonder is refused anywhere once any player completed it; completion removes other players' copies, refunds `consolation_percent` of their locked cost, bumps `district_epoch`; one-shot effects fire exactly once, never on load or capture | the race or the one-shot discipline breaks |
| Wonders are not `district = "any"` sources; `wonder = "any"` counts complete wonders only | adjacency double-counts wonders |
| Loyalty: pressure per §8.2 (own city counted, foreign summed), drift truncated toward zero and clamped, garrison and sources added, the Palace's per-citizen term included; bands scale yields and production and growth; a city at 0 flips to the largest foreign presser through `set_owner`; all deltas from phase-start state (turn-order independence, as in `test_border_growth`) | any term or the phase discipline drifts |
| After N rounds of play, `reset(seed)` reproduces exactly what a fresh environment's `reset(seed)` gives, every new Player field included | a per-episode field is left out of `Player.reset_state` |
| Domination: a player holding every Palace is the winner even while other cities stand; `player_score` sums the `[game.score]` terms | the verdict and the score diverge (#55) |
| Defaults: with no agent choice a seeded game researches techs and civics, adopts governments, slots policies, sends Traders and improves tiles — all counters positive by round 150 of the smoke run — and two same-seed games produce identical pools, techs, loyalty and flips | a default is non-deterministic or dormant |
| An idle Worker never builds an improvement its owner's techs do not allow, never on a tile its owner does not own, and steps only along `path_finder` | the worker default bypasses `can_build_improvement_at` or the hex kernels |
| Same seed, same actions → identical everything (`test_determinism` extended with the new state) | set/dict iteration or RNG use anywhere new |

## 15. Patch plan

One agent at a time; branch `116-progression-<patch>` from develop, merged
`--no-ff` when green, worktree and branch deleted. No patch is HUMAN-TEST.
Every patch: full suite green, its §14 rows, a CHANGELOG paragraph under the
v0.8.0 entry (opened by P1), `episode_stats` keys declared in
`_fresh_episode_stats`.

| Patch | Content | Gate | Mode · tier |
|---|---|---|---|
| **P1 yields** | `game/yields.py` (`city_yield`, loyalty hook stubbed at 100 %), `[science]`/`[gold]`/`[faith]`, yield columns in `unit_model`, `Player.faith`, pools in tenths, the yield phase, `episode_stats` counters; `culture()` delegates; district yields consumed (Theater, Campus, Holy Site, Commercial, Harbor, Industrial Zone production into `calculate_production`) | §14 rows 1–4; v0.7 culture identity; suite green | subagent · Opus |
| **P2 tech tree** | `research_model.py` (`[research]`, `[techs.*]`), `Player.techs`, `current_tech`, `resolve_research`, `set_research`, auto-pick default (`game/defaults.py`), `player_can_build`, `requires_tech` on existing units/buildings/districts/improvements, `game_progress` live, build-mask gate, the new buildings of §6.2 with `requires_district`/`requires_building` and `city_can_build_building`, Granary/Workshop effects, Factory removed, `BUILD_OPTIONS` appended (buildings) | §14 rows 5 (tech part), 7–11; suite green; smoke run shows techs researched | subagent · Opus |
| **P3 units** | `combat_class`, `era`, `[combat] class_bonuses`, `CLASS_INDEX` derivation, the six new units + Trader tables (`UNIT_SLOT`, `MOVEMENT_DOMAIN`, `_create_unit`, `BUILD_OPTIONS` appended), `upgrades_to`, `upgrade_unit`, `upgrade_cost` | bit-identity on every existing pairing (`matchup_matrix` + identity test); §14 rows 12–13, 18; suite green | subagent · Sonnet (oracle-gated) |
| **P4 civics** | `[civics.*]`, `[governments.*]`, `[policies.*]` in `research_model`; `effects.py` interpreter and the consumers `city_yield`, `production_percent`, `adjacency_percent`, `combat_strength`, `enables` (flanking gate), `policy_slots`; `Player.civics/current_civic/government/policies`; `resolve_civic`, `set_civic`, `set_government`, `set_policies`; government and loadout defaults; Government Plaza buildings | §14 rows 5–6, 14–15; suite green; smoke shows civics, governments, policies | subagent · Opus |
| **P5 gold** | `maintenance` columns, the economy phase, bankruptcy, `purchasable`/`purchase_cost`/`purchase`, `faith_purchase` and `purchase_percent` consumers, trade routes (`TradeRoute`, `establish_trade_route`, capacity, yields, expiry, auto-send default), Trader mask rule | §14 rows 16–19; suite green; smoke shows routes and maintenance | subagent · Opus |
| **P6 wonders** | `kind = "wonder"` in `district_model`, the twelve tables, uniqueness, race resolution + consolation, `wonder = "any"` source, `GameEnvironment.complete_district` with one-shot effects (`free_units`, `free_tech`, `free_civic`, `free_population`, `growth_percent` consumer), smoke script places wonders | §14 rows 20–21; suite green | subagent · Opus |
| **P7 loyalty** | `game/loyalty.py` (pressure, drift, sources, bands), `City.loyalty`, `_loyalty_phase`, `_flip_city`, `loyalty` effect consumer, Monument/Colosseum/Limitanei values live, `loyalty_percent` into `city_yield`/`calculate_production`/growth, stats | §14 row 22; turn-order independence; suite green | subagent · Opus |
| **P8 workers** | Worker automation default (`game/defaults.py`): at its owner's turn start an idle Worker on an owned tile with a buildable, tech-available improvement builds the one with the largest (food + production) gain (ties: config order); otherwise it moves one `path_finder` step toward the nearest owned tile where it could build (ties: coordinates); nothing to do → it stays. `Worker` leaves `DEFERRED_BUILD_UNITS` and enters `BUILD_OPTIONS`; `requires_tech` on improvements enforced by `can_build_improvement_at` | determinism; improvements appear in the smoke run; suite green | subagent · Sonnet |
| **P9 winning + release** | domination in `_check_game_end`, `[game.score]` terms in `player_score`, `victory` in `games_detail`; `__version__ = "0.8.0"`, fixture regenerated (`scripts/make_fixture_scenario.py`), CHANGELOG v0.8.0 entry finalised with the epoch marker, `docs/game_overview.md`, CLAUDE.md rows from the Systems section, `weights/trained/manifest.md` epoch note | §14 rows 23–25; suite green; one seeded smoke run of 250 rounds logged | subagent · Sonnet |

Re-planning happens at patch boundaries; the spec of the patch in flight is
locked.

---

## Systems

### (a) Existing canonical systems this design must use

- **Gameplay config** (`CFG`): every number and every table.
- **Unit/combat config interpreter** (`unit_model.py`): yield and
  maintenance columns, `combat_class`, `class_bonuses`, `purchasable`,
  `upgrades_to` — no other reader of `[units.*]` / `[buildings.*]`.
- **Combat** (`Unit.get_combat_strength` / `get_ranged_strength`,
  `_execute_attack`): class bonuses and `combat_strength` effects applied in
  both roles; the flanking gate; nothing else touches damage.
- **City economy** (`City.process_turn`, `calculate_production`): the yield
  phase, production modifiers, loyalty scaling, growth percent.
- **Culture yield** (`culture(city)`): becomes a `city_yield` alias.
- **District registry / placement / yields / Adjacency** (`district_model`,
  `game/districts.py`, `place_district`): wonders ride them unchanged;
  `game_progress` is the escalation hook.
- **Housing** (`housing(city)`): wonder housing columns are read like
  building columns.
- **Territory** (`Map.owner_city`, `set_owner`, `city_changed_player`): flips
  and upgrades-on-own-tile read it; a flip moves tiles exactly as a capture.
- **Palace** rule: the capital marker for domination and loyalty immunity.
- **Build options / Action masking** (`BUILD_OPTIONS`, `get_valid_build_mask`):
  append-only growth; the availability gate.
- **Hex math** (`distance_function`, `get_adjacent_coords`): loyalty range,
  trade range, every adjacency.
- **Engine RNG**: untouched — nothing in this block draws from it.
- **Run truncation / Evaluation harness / Win determination**:
  `determine_winner` / `player_score` are the only verdict; `games_detail`
  gains `victory`.
- **Artifact manifests** (`meta.py`): the version bump and fixture regen.
- **Combat-training tools** and the smoke script: extended, not forked.

### (b) New systems, with draft CLAUDE.md rows

| System | Where | Draft rule |
|---|---|---|
| City yields | `city_yield(city, name)` (`game/yields.py`) over `[science]`/`[culture]`/`[gold]`/`[faith]`, yield columns, `district_yields`, effects, routes, loyalty | The only computation of a city's science, culture, gold and faith (integer tenths). A new source is a column on its own table or an effect, never a term in code |
| Effects | `civulator/effects.py` (`active_effects`), `effects = [...]` on any table | The only interpreter of effect lists; a closed set of kinds, each with exactly one consumer named in the design (§3). A new kind adds a row there and one consumer, never a second reader of the same kind |
| Research | `civulator/research_model.py` (`[research]`, `[techs.*]`, `[civics.*]`, `[governments.*]`, `[policies.*]`); `Player.techs/civics`; `GameEnvironment.resolve_research/resolve_civic/set_research/set_civic`; `player_can_build` | The only interpreter of the trees and the only availability check. An item is gated by `requires_tech`/`requires_civic` on its own table; every build, purchase, placement and upgrade path calls `player_can_build`; "what a tech unlocks" is derived, never declared |
| Governments and policies | `Player.government/policies`, `set_government/set_policies`, `slot_counts` | The only loadout state and the only legality check; effects reach the game only through `active_effects` |
| Economy phase | `GameEnvironment.economy_phase(player)` in `Player.start_turn` after the cities: maintenance, bankruptcy, research, civics, routes | The only place gold leaves the treasury on a timer and the only place a tech or civic completes |
| Purchasing | `purchase_cost` / `GameEnvironment.purchase` | The only instant-completion path; purchasability is a column on the item's table; a purchased item is created by the same code as a built one |
| Upgrades | `upgrades_to` column; `upgrade_cost` / `GameEnvironment.upgrade_unit` | The only way a unit changes type |
| Trade routes | `TradeRoute`, `GameEnvironment.establish_trade_route`, `route_capacity`, `[trade]` | The only route state; yields reach cities only through `city_yield` |
| Wonders | `kind = "wonder"` in the district registry; `GameEnvironment.complete_district` | A wonder is a district table; uniqueness, the race and one-shot effects live in `complete_district`, the one place a district finishes |
| Loyalty | `game/loyalty.py` (`pressure`, `loyalty_delta`, `loyalty_percent`), `City.loyalty`, `_loyalty_phase`, `_flip_city` | The only loyalty computation and the only non-combat change of a city's owner; it goes through `City.set_owner` like a capture. Amenities, governors and ages do not exist here |
| Engine defaults | `game/defaults.py` | The deterministic choice the engine makes where no agent action exists yet (research, civic, government, loadout, Trader); each default is one function `GameEnvironment` calls, replaced one-for-one by an agent action in #99 |
| Victory | `determine_outcome(env) -> (winner, victory)` with `determine_winner` as its wrapper (elimination, domination, score), `[game.score]` | the one verdict, called from `_check_game_end` and from `next_turn` after the loyalty phase; `victory` is recorded per game, `null` when truncated |
| Combat classes | `combat_class` column, `[combat] class_bonuses` (rows with `strength`), `UNIT_CLASSES` in `game/city.py` | the one class registry: combat modifiers, the encoder's `CLASS_INDEX`, civilian capture, the siege rules, the matchup matrix and the recorder all read it; no name-keyed combat rule remains |
| Building availability | `city_can_build_building(city, name)` beside `player_can_build` | the one building-availability predicate (tech, civic, government tier, district, prerequisite building); `produce_building`, the mask and `purchase` call it |
| Round-end phases | `next_turn`: `_border_phase` → `_loyalty_phase` → verdict → `turn_counter += 1` | every round-end rule computes from phase-start state in city-id order; a new one is a new phase here, never inside a player's turn |

### (c) Existing rows amended at implementation (B7)

| Row | Amendment |
|---|---|
| City combat | `City.set_owner` is the one place a city changes hands; `_capture_city` (force) and `_flip_city` (loyalty) are its only callers |
| District placement | `_remove_district` (race losers, `remove_city`) is the only other writer of `Tile.district` / `City.districts` |
| Culture yield | merged into the City yields row (`culture()` is an alias) |
| Housing | effects `housing_if_districts` / `housing_with_building` are declared sources, read through `active_effects` |
| District yields | consumed by `city_yield` and `calculate_production`; `percent_by_district` applied inside |
| City economy | phase order per v2; completion in `GameEnvironment.complete_district`; loyalty and growth scaling |
| Win/score | `determine_outcome`; weights in `[game.score]` beside `[game] city_score_weight` |
| Combat | `combat_class` replaces `siege_class`; class bonuses from config rows |
| Buildings | yield, maintenance, `purchasable`, `requires_*` columns |
| Unit system | the touch list gains `combat_class`, `era`, `maintenance`, `purchasable`, `requires_tech`; `CLASS_INDEX` and `UNIT_CLASSES` are derived, never edited |
| Palace | `capital_only` means "the city holding a Palace" |
| Terrain model | improvement yields and `requires_tech` are read through it; `build_improvement` bumps `terrain_epoch` |
| Action masking | the build mask reads `player_can_build` / `city_can_build_building`; the smoke script draws from the mask |


## Implementation notes (P1–P9, 2026-10-21)

The block is implemented and merged as nine patches. The text above is the
build contract as it stood and is not edited; this section lists, patch by
patch, every decision that diverges from it or that it left open, so a reader
of §1–§15 knows where the code differs. The rules, numbers and sources of each
patch are in `CHANGELOG.md`, v0.8.0 (one section per patch). Where an item
changes a rule the design states, it says so; items marked **ruling** are
Claude's calls that Erik may overturn.

### Corrections of the design's own arithmetic and facts

- §4.2: the tech tree sums to **4,065** science at Civ 6 cost, not 4,015, and
  to **3,043** at 75 % (each cost floored per tech; 3,049 is 75 % of the total
  before flooring), the sum of `research_model.scaled_tech_cost`.
- §5.1: the civics sum to **3,330** culture at Civ 6 cost, not 3,100, and to
  2,494 at 75 %.
- §12's pacing table rests on the two wrong totals and on a yield model that
  has not been measured against play. The one observation is a seeded smoke
  run, not a measurement (random agents choose neither research nor
  production): seed 4242, 250 rounds, 15 and 17 of the 22 techs and 13 and 13
  of the 19 civics researched. The "last tech around round 215" target is
  restated when an evaluation report supplies a measured curve.
- "v2 fixes", Improvement yields: Camp and Plantation are **+2 gold** in
  Gathering Storm (the wiki's per-improvement pages), not +1.
- §14 row "An idle Worker ... steps only along `path_finder`" and §15 P8
  ("largest (food + production) gain", "one `path_finder` step"): read them as
  "v2 fixes", Worker default (N18), and the code have them -- the Worker steps
  through `Unit.move` by `defaults.step_toward`, **never `path_finder`**, and
  ranks improvements by **food + production + gold** (then housing in tenths,
  then config order). The property the test pins is "never builds an
  improvement its owner's techs do not allow, never on a tile its owner does
  not own, and steps only through the shared one-step rule".

### P1 -- yields and pools

- Food and production building columns are stored in tenths and floored once
  per city, not per building.
- `complete_district` raises on a second completion (the design says only that
  it is the one place a district finishes).
- The CLAUDE.md rows were amended in P1 (Systems (c) lists them as amended at
  implementation); Win/score and Victory are P9's.
- The Palace's Civ 6 +1 culture is not added: v0.7's culture base of 1 per city
  stays (design §0.3).

### P2 -- tech tree

- `game_progress(None)` is no longer valid: it needs a player.
- `[units.*]`, `[buildings.*]` and `[improvements.*]` have strict key lists:
  an unknown key raises.
- `district_model` validates every building's `requires_district` against the
  district registry (the design left the owner of that check open).
- `city_can_build_building` includes the production-cost check ("a costed
  building"), so the build mask, `produce_building` and `purchase` need no
  second one.
- A captured city's in-progress item that its new owner could not start still
  completes (accepted in "v2 fixes"; recorded because tests pin it).

### P3 -- units

- The Crossbowman takes the archer's cavalry penalty against both cavalry
  classes, as the Archer it replaces does.
- `maintenance` is a required column of every `[units.*]` table.
- A unit's name may not equal a combat class's name (the loader raises: a row
  matches by name or by class).
- `_create_unit` raises on an unknown type (it fell back to the bare `Unit`).
- "Has not attacked", for an upgrade, is `not has_acted` and full movement.
- Upgrade prices are `[gold] upgrade_per_production * (target cost - unit
  cost) + upgrade_base` with 2 and 10: Warrior 110, Slinger 60, Archer 250,
  Spearman 240, Horseman 290, Swordsman 150, Man-At-Arms 170, Catapult 170.
- The encoder clamps its unit-stat channels at 1.0, so the Knight and the
  Musketman saturate the melee-strength channel (N21's accepted gap, made
  concrete).

### P4 -- civics

- `combat_strength`'s class attribute is `applies_to` (not `scope`, which
  already means where an effect applies).
- `production_percent` targets also accept `district` and `in_district` (the
  Veterancy card needs them).
- `default_government` is the highest tier available, ties by config order.
- The loadout default runs on civic completion and on a government change
  only, not every turn.
- `[city] capital_building` replaces the Palace literal; a `capital_only`
  effect tests it.
- The Ilkum policy is never obsolete.
- The Agoge policy holds Chiefdom's military slot until Feudalism under the
  default, so the Maneuver policy is never slotted by default.

### P5 -- gold

- A disbanded unit's own upkeep is not charged that turn, so bankruptcy
  converges.
- `gold_maintenance` records what actually left the treasury.
- A city's trade-route capacity from buildings is the largest building amount
  (a city with both a Market and a Lighthouse adds 1, not 2).
- Route yields are stored in tenths; `[trade] unit = "Trader"` names the trade
  unit once.
- `purchase` buys for the current player and applies the Trader's route-slot
  rule; buying the building a city is producing clears the production item.
- `remove_city` ends routes like `set_owner` does.
- `establish_trade_route` needs the Trader on its origin city but not its full
  movement.
- The support class is excluded from faith purchase (it is not "land
  military").
- The Settler's population >= 3 rule is mask-only (pre-existing, not changed).

### P6 -- wonders

- **Ruling, applied in P9:** `[wonders] consolation_percent` is 0 (the design
  says 50) and every wonder table declares `max_per_player = 1` (the design
  has only `max_per_city`); the Oracle's era is Ancient (the design's §9.4
  table says Classical).
- The Statue of Zeus grants no Battering Ram (it is a deferred unit).
- A placement requirement on a district (Encampment, Campus, ...) is met by a
  placed, unfinished district and asks for no building in it (Civ 6 asks for a
  Barracks, a Library, an Arena).
- "Flat land" is spelled as relief flat plus the five land bases (water is
  flat too).
- One-shot effect kinds are accepted on `kind = "wonder"` tables only.
- `free_*` grants ignore availability.
- Wonders carry an `era` column and `production_percent` targets read
  `wonder_era`, so Corvee and Gothic Architecture target by era (the design's
  Corvee text targeted every wonder).

### P7 -- loyalty

- `[loyalty]` gained `maximum`, `citizen_weight` (10), `drift_gain` (10) and
  `drift_cap` (20), so no loyalty number is hardcoded.
- Flip targets are computed from the state at the start of the phase.
- A flat, unconditional, city-scoped loyalty effect on a building or district
  is refused: the `loyalty` column says it (one way to say it).
- A 0 % growth share blocks growth even with a full bucket; the production
  floor of 1 holds in Unrest; food is never scaled.
- The Colosseum reaches its owner's cities only.
- A city at 0 loyalty with a delta of 0 flips (Civ 6: only while falling).
- The design's consumer name `loyalty_sources` is `loyalty_delta` /
  `effect_loyalty` in code.
- `_update_done` is the one end-of-game check, called from `_check_game_end`,
  after the loyalty phase and at the end of `next_turn`.

### P8 -- Workers

- One improvement per tile is the Worker default's rule and the Worker build
  offer's, not the engine's: `can_build_improvement_at` still lets improvements
  stack. Whether the engine should refuse a second one is Erik's open call.
  **Settled 2026-10-22 (#126, v0.8.1):** the engine keeps one per tile and a
  build replaces what stands there, any replacement allowed; the default
  revisits a tile when a better improvement is available. Same patch:
  domination off by default (`[game] domination_victory`), and elimination
  needs no city and no Settler.
- A tile an earlier Worker of the same pass chose is a preference with a
  fallback, not an exclusion (an outright exclusion deadlocked six Workers on
  36 tiles).
- `terrain_model.IMPROVEMENT_ORDER` is config order as a tuple (the frozenset
  `IMPROVEMENT_NAMES` iterates by hash seed).
- `WorkerUnit.build_improvement` now marks the unit as having acted.
- The Worker offer counts open tiles, not Workers already on their way.
- `Unit.move`'s adjacent branch does not itself refuse a foreign-occupied
  destination; the defaults avoid it.

### P9 -- winning and the release

- `determine_outcome` and `player_score` live in the engine module
  `civulator/game/victory.py`, not in `trainer.py` ("v2 fixes", Verdict and
  domination): the engine may import nothing of training, and the verdict now
  sets `done`. `trainer.py` re-exports `determine_winner`, `determine_outcome`,
  `player_score` and `CITY_SCORE_WEIGHT`.
- Domination is tested in `GameEnvironment._update_done` -- which asks
  `victory.game_over` and is called from `_check_game_end` and from
  `next_turn` after `_loyalty_phase` -- not in `_check_game_end` alone, so one
  test sets `done` for elimination, domination and the cap.
- A living player dominates when it holds every Palace that exists and at
  least one was granted to another player (`Player.palace_granted`). **Ruling:**
  a player that has not yet founded its capital does not block a domination,
  and a Palace gone with a removed city (tools only) is gone while the grant
  stays recorded.
- `[game.score]` is read by `victory.py` only, strictly (exactly the five keys,
  whole numbers >= 0); `city_score_weight` stays under `[game]`. The design's
  term list is unchanged; `score_counts` / `score_breakdown` expose it term by
  term, and the smoke script and the viewer HUD show it.
- `evaluate.py` records the weights' `game_version` per side (`a`, `b`), the
  design's "each seat's weights" (a side's weights serve both its seats), beside
  the engine's `game_version`.
- A loyalty flip or capture of a city holding a slot-granting wonder re-fits
  both players' loadouts in `City.set_owner` (P6's open ruling).
- CLAUDE.md: the P1-P8 "Prior" entries of the header are collapsed into one
  line pointing at the CHANGELOG, and instance lists that crept into the P1-P8
  rows were removed (a row names the seam, not what plugs into it).
- `docs/game_overview.md` is 42 lines against the old 34: the block adds the
  trees, the pools, loyalty, wonders and two ways to win.
