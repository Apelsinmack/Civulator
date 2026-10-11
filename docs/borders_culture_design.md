# Borders and culture (#87): design

> Settled 2026-10-11 in chat between Erik and Claude. Civ 6 facts are from the
> Civ 6 wiki (pages listed under Sources) unless marked otherwise. This doc is
> the contract for the implementing patches. Re-planning happens at patch
> boundaries only.

## Goal

Cities own territory, and territory grows with culture. This comes before
everything else in milestone D: districts can only be placed on owned tiles
(#86), and Civ 6's three-hex work radius only means something once there is
territory to work. It is a rules change, so it lands before #83 fixes the new
reference opponent (see the 2026-09-05 handoff on #31: rule changes are free
until then).

Every gameplay number below is a config value, and every rule that might be
swapped later is a named function behind a registry. Erik, 2026-10-11: RL
agents will expose whatever is overpowered, and the point is to be able to
rebalance by editing config, not code.

## In scope

1. A **culture** yield per city.
2. **Tile ownership** per city, the founding claim, and transfer on capture.
3. **Border growth** from culture: cost curve, tile choice, and fair resolution
   when two cities want the same tile.
4. **Work radius 3**: cities work only tiles they own.
5. **Swapping** an owned tile between two cities of the same player (engine API).
6. Viewer overlay for borders (so the change can be checked by eye), CHANGELOG,
   game version and rules epoch.

## Out of scope (each a follow-up)

| Item | Where it belongs |
|---|---|
| Agents seeing ownership (encoder channels) | new encoder issue; ownership is not terrain, so it does not go into TerrainAware's block |
| Tile swap as an agent action | city governor / action space, #99 |
| Buying tiles with gold | #91, once gold exists. Civ 6: 50 gold at distance 2, 75 at distance 3, rising with tech |
| Faster healing inside own borders | Erik wants it, separate patch |
| Closed borders, borders giving sight of adjacent tiles | later; sight interacts with fog |
| Wonders claiming +2 tiles, culture bombs | no wonders yet |
| Housing | #88 (independent of this design) |
| Districts, adjacency | #86 and the per-district issues |

---

## 1. Culture yield

Each city produces culture every turn:

```
culture(city) = base + per_pop * population + sum(culture of each source in the city)
```

- `base = 1`, `per_pop = 0.3`. The 0.3 is the community-reported Civ 6 game-file
  value; the base 1 stands in for the Civ 6 Palace (Claude's recall, not
  wiki-checked). Both are config values.
- **Sources** are anything a city has that declares a `culture` value: today the
  `[buildings.*]` tables (Monument `culture = 2`, the Civ 6 value), later the
  district tables (Theatre Square, #92) through the same column. A new source
  declares `culture` in its own config table; the formula does not change.
- Culture is a float. Each turn the city's culture is added to two places, as in
  Civ 6 where one culture output feeds both:
  - the city's own **border pool** (`city.border_culture`), consumed by border
    growth (§3);
  - the player's **civic pool** (`Player.culture`, the field already exists and
    is unused), which has no consumer yet and is recorded for stats and the
    future civics tree.
- Accrual happens in `City.process_turn` (at the start of the owner's turn),
  next to food and production. The amount accrued this turn is stored
  (`city.culture_last_turn`) because §3 needs it.

`culture(city)` lives in one function; it is the only place culture is computed.

## 2. Ownership

- **Ownership is per city**, not per player. The player's territory is the union
  of its cities' tiles. A tile has at most one owning city, or none (neutral).
- Stored as one integer grid on `Map` (`owner_city[r, q]`, city id or −1), with
  a stable integer id per city assigned by the environment. One mutation API
  writes it (`claim`, `transfer`, `release`); nothing else writes the grid.
- Ownership changes bump a new `Map.territory_epoch`, **not** `terrain_epoch`:
  terrain caches (LoS, cost grids, encoder terrain layers) must not be
  invalidated by border growth. Future ownership-derived caches key on
  `territory_epoch`.
- All tiles may be owned, including water, mountains and other impassable tiles
  (Civ 6 claims them too). Owning a tile does not make it workable; §4 decides
  that.

### 2.1 Founding claim

When a city is founded:

1. It owns its own tile.
2. It claims every **neutral** ring-1 tile.
3. For each ring-1 tile already owned by **another player**, it claims one
   replacement tile chosen by the §3.2 rule. Civ 6: "tiles more than one hex
   away from the City Center and closest to the tiles that would have been
   claimed are immediately claimed instead."
4. A ring-1 tile owned by **another of the same player's cities** stays with
   that city. It can be swapped later (§5). (Claude's call; Civ 6's exact
   behaviour here is not on the wiki.)

Founding claims do not count towards the culture cost index `n` (§3.1).

Both founding paths (`GameEnvironment.found_city` and the settler's
`SettlerUnit.found_city` → `add_city`) must go through one claim function.

### 2.2 Where a city may be founded

`can_found_city_at` gains one condition: the tile is not owned by another
player. Founding on a tile you already own (outside `min_city_distance` of every
city, as today) is allowed, and the tile moves to the new city. Erik,
2026-10-11: "I think it should be allowed." The settler action mask already calls `can_found_city_at`, so masks
and rules stay one function.

### 2.3 Capture and destruction

- A **captured** city keeps all its tiles, and they change player with it
  (Civ 6). Its `border_culture` and `n` go with it.
- If a city ever **ceases to exist** without being captured (razing, or any
  future path that deletes a city), its tiles become neutral.

---

## 3. Border growth

### 3.1 Cost curve

The n-th tile a city claims by culture (n = 1, 2, …) costs

```
cost(n) = a + (b * (n - 1)) ** p        a = 10, b = 6, p = 1.3
```

The values come from community readings of Civ 6's GlobalParameters. The formula
is reported to be approximate. Numbers: 10, 20.3, 35.3, 52.8, 72.2 … about 189
for the 10th tile.

The curve is a **named function in a registry**, selected by config:

```toml
[territory.border_cost]
curve = "civ6_community"   # key into BORDER_COST_CURVES; unknown names raise
a = 10
b = 6
p = 1.3
```

The other keys of the table are passed to the curve as parameters. A new curve
is a new registry entry, with config that names it.

### 3.2 Which tile

The candidates are the neutral tiles that are:

- within `claim_radius` (5) hexes of the city centre (canonical wrap distance), and
- adjacent to a tile the city already owns.

From those, take the ones at **minimum distance** from the centre. This
enforces Erik's ring rule: every available tile at radius R is claimed before
any at R+1. A tile at R that is cut off from the city's territory is not
available. Rank the remaining ties by:

1. the tile has a resource;
2. the tile is adjacent to a resource tile;
3. total composed yield, food + production (read through the terrain model,
   never by terrain name);
4. **the deterministic tiebreak, §3.4.**

Civ 6 ranks the same way: resources and tiles next to resources first, then
terrain features, then the rest. We use yield instead of "features".

If there is no candidate, nothing is claimed and the pool keeps accumulating.

### 3.3 Fair resolution: claims happen once per round, in time order

Claims are **not** made during each player's own turn. If they were, the player
who moves first in the round would always win a tile that two cities reach in
the same round. Instead:

- Each city accrues culture at the start of its owner's turn (§1).
- When the round ends (in `next_turn`, when play wraps back to player 0, before
  `turn_counter` advances), one **border phase** resolves every city's claims.
- Each city accrued `r = culture_last_turn` this round, from a pool of
  `p0 = border_culture - r` at round start. Treat the round as running from
  time 0 to 1, with the city's pool filling linearly. Its k-th claim this round
  happens at
  ```
  t_k = (cost(n+1) + … + cost(n+k) − p0) / r          (clamped to ≥ 0)
  ```
  for every k with `t_k ≤ 1`.
- All cities' claim events go into one queue, ordered by `t`. Each event claims
  that city's best tile **at that moment** by §3.2, and subtracts the cost from
  its pool. A city whose preferred tile was just taken by an earlier event
  simply takes its next-best tile. **Nobody loses points or progress.**
- **Ties on t** go to the larger overflow (`pool − cost` at that event), then to
  the engine RNG (§3.4).
- Points left over carry to the next round. A city can claim several tiles in
  one round if its culture is high enough.

So whoever reaches the cost first wins the tile, independent of turn order.
This is exactly the property the tests pin (§8).

Cities of the same player follow the same rule as rival cities.

### 3.4 The deterministic tiebreak

When candidates are still tied after §3.2's ranking (common: two plain grassland
tiles), or two claim events tie on both t and overflow, **the tied set is
shuffled with the engine RNG (`PortableRNG`) at the moment of the claim** and
the first one is taken.

Why this rule:

- **Reproducible**: `PortableRNG` is seeded by `env.reset(seed=N)`, so the same
  seed gives the same borders.
- **No direction bias**: a fixed scan order (by row, then column) would always
  grow borders towards one corner of the map. Over hundreds of training games
  that is a systematic tilt agents could learn to exploit.
- **One randomness system**: CLAUDE.md makes `PortableRNG` the only randomness
  in episode simulation. A coordinate hash would be a second one.

The cost is that border ties consume RNG draws, so damage rolls downstream of a
tie differ from a world without borders. Irrelevant, since this is a new epoch
anyway.

Rejected: a fixed scan order (direction bias), and a per-tile static hash
(second randomness system).

---

## 4. Work radius

`City.assign_tiles` chooses among tiles that are:

- owned by this city,
- within `work_radius` (3) of the centre, and
- workable (not impassable, as today).

The sort key is unchanged (food, then production). The city centre is still
free. Re-run `assign_tiles` when the city gains a tile, when a tile is swapped
in or out, and on population change. A city whose ring 1 is partly owned by an
enemy simply has fewer tiles to choose from.

Today `assign_tiles` reads `get_adjacent_coords` (ring 1 only). It switches to
`hexmath.hex_rings`. No new hex code.

## 5. Swapping a tile between two of your cities

Erik wants to keep this, as in Civ 6. Engine API:
`GameEnvironment.swap_tile(coords, to_city)`. It is valid only if:

- the tile is owned by a city of the same player as `to_city`;
- the tile is within `to_city`'s `work_radius`;
- the tile is **not adjacent to its current owner's centre** (Civ 6: "a tile
  adjacent to the City Center of one city cannot be swapped to another city");
- later, the tile holds no district or wonder (Civ 6). There are none yet, so
  this check lands with districts.

A swap is free and instant, and both cities re-run `assign_tiles`. No agent can
issue a swap yet (out of scope, #99). The API is there for tools and for the
future governor.

---

## 6. Config

All new gameplay numbers:

```toml
[culture]
base = 1.0          # per city per turn (stand-in for the Civ 6 Palace)
per_pop = 0.3       # per citizen

[buildings.Monument]
production_cost = 50
culture = 2         # new column; any [buildings.*] or district table may declare it

[territory]
claim_radius = 5    # Civ 6: culture claims tiles up to 5 hexes from the centre
work_radius = 3     # Civ 6: cities work and buy tiles up to 3 hexes out
founding_ring = 1   # tiles claimed at founding

[territory.border_cost]
curve = "civ6_community"
a = 10
b = 6
p = 1.3
```

`min_city_distance` stays 4, which is also Civ 6's value. #74 remains its own
question.

## 7. What it changes for agents and experiments

- **New rules epoch** (#78), **CHANGELOG** entry with the Civ 6 sources, and a
  minor game-version bump. The exact number is still open, see #83.
- No new actions and no new mask: masks change only through
  `can_found_city_at` (§2.2), which the mask already calls.
- **Agents are blind to ownership** until the encoder follow-up. Accepted for
  this patch: the economy changes underneath them (cities work tiles up to
  radius 3), but nothing in their input or action space does.
- `episode_stats` gains: tiles owned per player at the end of the episode,
  culture produced, and tiles claimed by culture. These are the order
  parameters for checking that borders actually grow in real games.

## 8. Tests: properties, each named with the change that must break it

| Property | Breaks if |
|---|---|
| No tile has two owners; every owned tile's city exists | a write bypasses the mutation API |
| Ring order: a city never owns a culture-claimed tile at radius R+1 while a neutral, available tile at R adjacent to its territory exists | §3.2 picks by value before distance |
| Culture claims never take a tile owned by anyone | growth can flip tiles |
| **Turn-order independence**: two cities with different crossing times contest one tile. The earlier one wins regardless of which player moves first (test both seat orders) | claims resolve during each player's turn instead of in the border phase |
| Losing a contest costs nothing: the loser claims its next-best tile in the same round, and its pool is reduced by exactly one cost | the loser's points are consumed or discarded |
| Same seed gives identical ownership grids after N rounds | the tiebreak uses anything but `PortableRNG`, or iteration order leaks in |
| Capture transfers every tile of the city, and no other tile | transfer is per-tile or incomplete |
| A city works only owned tiles within `work_radius` | `assign_tiles` still reads ring 1 or ignores ownership |
| Swap refuses a tile adjacent to its owner's centre and a tile outside the target's radius | swap validity checks drift from §5 |
| Changing a config value (cost curve parameters, radius, culture base) changes behaviour accordingly; an unknown curve name raises | a number is hardcoded or the registry silently falls back |
| Ownership changes do not bump `terrain_epoch` | ownership is wired into the terrain cache key |

## 9. Patch plan

Erik, 2026-10-11: the arc runs to the end without him. No patch is HUMAN-TEST.
All patches are subagents, one at a time, on one implementation branch, each
merged `--no-ff` to `develop` when its gate is green.

| Patch | Content | Gate (oracle) | Mode · tier |
|---|---|---|---|
| P1 | Culture yield: `culture(city)`, `[culture]` config, `culture` column on buildings, Monument = 2, accrual in `process_turn`, `Player.culture` civic pool | §8 culture properties; full suite green | subagent · Sonnet |
| P2 | Ownership grid + mutation API + `territory_epoch`, city ids, founding claim through one function (both founding paths), founding restriction, capture/destroy transfer, `swap_tile` | §8 ownership properties; full suite green | subagent · Opus (touches founding, capture, masks) |
| P3 | Border growth: cost-curve registry, tile choice, round-end border phase with the event queue and tie rules | §8 ring-order, turn-order independence, seed determinism; full suite green | subagent · Opus (the subtle one) |
| P4 | Work radius 3 over owned tiles in `assign_tiles`; `episode_stats` additions | §8 work-radius property; full suite green; a seeded 250-turn random-policy self-play smoke run logs tiles owned per player over time and shows growth | subagent · Sonnet |
| P5 | Border overlay in `viz/hex_render.py` (city-coloured edges between owned and other tiles), CHANGELOG, version, epoch, CLAUDE.md rows | full suite green; the adjacency-render invariant test still passes; a headless screenshot of a seeded mid-game map shows borders (checked by the orchestrator) | subagent · Sonnet |

E2E check at the end (orchestrator): a seeded game rendered at several turns,
where borders visibly grow ring by ring, plus the turn-order independence test
run on the merged `develop`.

## Critique (lens table — one Opus critic per lens, run one at a time, each verdict written here before the next spawns)

| Lens | Verdict | Blockers |
|---|---|---|
| Rules semantics and edge cases | pending | |
| Systems reuse and regression | pending | |
| Determinism and single-writer | pending | |

---

## Systems

### (a) Existing canonical systems this design must use

- **Game interface** (`GameEnvironment`): the border phase, founding claim,
  `swap_tile` and capture transfer all live behind it.
- **Hex math** (`hexmath.distance`, `adjacent_coords`, `hex_rings`): every
  radius, ring and adjacency here. No new hex code.
- **Terrain model**: tile yields for the §3.2 ranking and resource presence. No
  terrain names in gameplay code.
- **Engine RNG** (`PortableRNG`): the only tiebreak randomness (§3.4).
- **Gameplay config** (`config.toml` via `CFG`): every number in §6.
- **City economy** (`City.process_turn` / `assign_tiles`): culture accrual and
  the work-radius change live there. No second economy loop.
- **Terrain epoch**: explicitly *not* bumped by ownership; see the new
  territory epoch below.
- **Hex renderer** (`viz/hex_render.py`): the border overlay extends it; no
  forked rendering.
- **Action masking**: unchanged code, the founding restriction reaches masks
  through `can_found_city_at`.

### (b) New systems, with draft CLAUDE.md rows (written into CLAUDE.md at implementation, pointing at the real code)

| System | Where | Draft rule |
|---|---|---|
| Culture yield | `culture(city)` (module decided at P1) | The only computation of a city's culture. A new culture source declares a `culture` value in its own config table (building, district, …); never add a culture term to the formula itself |
| Territory | `Map.owner_city` + its mutation API (`claim` / `transfer` / `release`), `Map.territory_epoch` | The only record of who owns a tile and the only writer of it. Founding, border growth, capture and swaps all go through it; ownership-derived caches key on `territory_epoch`, never on `terrain_epoch` |
| Border growth | border phase in `GameEnvironment` (round end) + tile-choice function | The only way a tile becomes owned after founding. Claims resolve once per round in crossing-time order, never during a player's own turn, so turn order cannot decide a contest |
| Border cost curves | `BORDER_COST_CURVES` registry, selected by `[territory.border_cost] curve` | Rebalance by config or by adding a registry entry; never edit a curve in place in a way that changes an existing name's meaning (old manifests pin the name) |

## Sources

- Civ 6 wiki: [Borders](https://civilization.fandom.com/wiki/Borders_(Civ6)),
  [District](https://civilization.fandom.com/wiki/District_(Civ6)).
- Cost formula (community, approximate):
  [Realms Beyond](https://realmsbeyond.net/forums/showthread.php?pid=657450),
  [CivFanatics](https://forums.civfanatics.com/threads/how-to-make-border-expand-faster.603457/latest).
  #87's 2026-09-05 sketch has `10 + 6*n^1.3`, a different reading. This doc
  uses the community spreadsheet version as Erik chose on 2026-10-11.
