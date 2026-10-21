# Progression (#116): science, civics, gold, faith, wonders, loyalty, winning — design

> **Status: v1 draft (2026-10-21).** Written by Claude as lead game designer on
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

`housing`, `culture`, `science`, `gold`, `faith` on a building, district or
wonder stay **columns** (the #87/#88 pattern), not effects; the loader
rejects a `city_yield` effect on a building so there is one way to say it.

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

*(tree table — §4.2 is completed from the Civ 6 digest; see the v1 table
below once filled)*

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

*(civics table — completed from the digest)*

### 5.2 Governments

`[governments.<Name>]`: `requires_civic`, `tier`, `effects` (its
`policy_slots` and its inherent bonus). A player has `Player.government`
(None until Code of Laws). `set_government(player, name)` is refused unless
the civic is known. No switching penalty (Claude's call: Civ 6's anarchy turn
exists for humans; an agent changing government every turn gains nothing).

### 5.3 Policy cards

`[policies.<Name>]`: `type` (`military` / `economic` / `diplomatic` /
`wildcard`), `requires_civic`, optional `obsolete_with` (a civic), `effects`.
`Player.policies` is the list of **slotted** cards. A loadout is legal when
every card is unlocked and not obsolete, distinct, and fits its slot type or
a wildcard slot; `set_policies(player, names)` is refused otherwise.

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

*(tables — completed from the digest: Pikeman, Crossbowman, Man-At-Arms,
Knight, Trebuchet, Musketman, Trader; Library, University, Market,
Lighthouse, Shrine, Temple, Amphitheater, Barracks, Medieval Walls, Monument
into BUILD_OPTIONS; Granary and Workshop effects; Factory removed)*

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
costs `upgrade_cost(unit)` gold (§7.3, Civ 6's formula scaled by
`upgrade_cost_percent` effects); the unit becomes the target type at the
same health, movement spent. No engine default (§13): dormant until #99,
like `swap_tile` — **ACCEPTED GAP**, recorded in the CHANGELOG.

---

## 7. Gold

### 7.1 Maintenance

`maintenance = N` columns on `[units.*]` and `[buildings.*]` (Civ 6 values).
At the start of the owner's turn, after the cities have accrued:

```
treasury += 0                      # yields were added by the cities
treasury -= 10 * (sum unit maintenance (+ unit_maintenance_delta effects, floored at 0 per unit)
                  + sum building maintenance)
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
building table (districts and wonders are never purchasable, Civ 6).
`purchase_cost(player, kind, name, resource)` =
`production_cost * [gold] purchase_multiplier` (or `[faith]`), scaled by
`purchase_percent` effects; `GameEnvironment.purchase(city, kind, name,
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
another city within `[trade] range` hexes (canonical wrap distance from the
origin), and `len(routes) < route_capacity(player)` =
`[trade] base_capacity` + `trade_route_capacity` effects.

Yields, per turn, to the **origin city** (a term of `city_yield`, §2.1):

| route | origin gets | destination owner gets |
|---|---|---|
| domestic (same owner) | `[trade] domestic_food` + `domestic_production`, plus `per_district_food` per complete specialty district at the destination | — |
| international | `[trade] international_gold`, plus `per_district_gold` per complete specialty district at the destination | `[trade] destination_gold` |

A route lasts `[trade] duration_turns`; when it ends, a Trader reappears at
the origin (through `complete_unit_production`) and idles. An idle Trader is
**auto-sent** by the engine default (§13) so trade stays live without an
agent. Routes end when either city is captured or destroyed (the Trader
returns to the origin if it still belongs to the player; otherwise it is
lost). No plunder, no path on the map.

---

## 8. Loyalty

*(the model — §8.1–8.5 — is written against the digest's Civ 6 numbers)*

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

*(table — completed from the digest: Pyramids, Stonehenge, Hanging Gardens,
Temple of Artemis, Statue of Zeus, Oracle, Great Library, Colossus,
Colosseum, Alhambra, Angkor Wat, Forbidden City — era, cost, requirement,
placement, effect)*

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

*(written out in §10.2 below, after the digest)*

---

## 11. Winning

*(§11 — domination and the score terms)*

## 12. Game length and cost scaling

*(§12 — the turn-count model behind `tech_cost_percent`)*

## 13. Engine defaults where no agent chooses yet

| Choice | Default (deterministic, no RNG) | Overridden by |
|---|---|---|
| current tech / civic | cheapest available; ties in config order | `set_research` / `set_civic` |
| government | on unlocking a civic that grants one, adopt it if it is a higher tier than the current one; ties (the three Tier-1s) by config order | `set_government` |
| policy loadout | whenever slots or unlocked cards change: keep legal cards, then fill each empty slot with the newest unlocked card of its type not yet slotted (wildcard: newest of any type); newest = latest civic, then config order | `set_policies` |
| idle Trader | at its owner's turn start, send it to the eligible destination with the highest total yield to the origin; ties by city id | `establish_trade_route` |
| purchase, upgrade, district/wonder placement, production | none (production: the build agent, as today) | #99 |

Defaults live in `civulator/game/defaults.py` and are called from
`GameEnvironment` only, so a future agent action replaces one call.

## 14. Tests · 15. Patches · Systems

*(completed with the content sections)*
