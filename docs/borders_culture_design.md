# Borders and culture (#87): design

> **v2**, 2026-10-11: v1 settled in chat between Erik and Claude, then revised
> after three Opus critique lenses (table and synthesis at the end of §9). Civ 6 facts are from the
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
- **Culture is stored and summed as integer tenths** (v2, critic 3 B6). Config
  stays human-readable (`per_pop = 0.3`); the loader converts every culture
  value to integer tenths once (`round(10 * x)`) and raises if a value is not a
  multiple of 0.1. All pools, rates and costs are ints, so comparisons are exact
  and identical on every machine.
- Accrual order in `process_turn`: repair → food → growth/starvation →
  **culture** → production. `per_pop` uses the population after this turn's
  growth.
- Each turn the city's culture is added to two places, as in Civ 6 where one
  culture output feeds both:
  - the city's own **border pool** (`city.border_culture`), consumed by border
    growth (§3);
  - the player's **civic pool** (`Player.culture`, the field already exists and
    is unused), which has no consumer yet and is recorded for stats and the
    future civics tree.
- Accrual happens in `City.process_turn` (at the start of the owner's turn).
  It also adds to `city.culture_this_round`, which the border phase (§3.3)
  reads and then zeroes. A city accrues at most once per round (guarded by a
  round stamp). A city captured during the capturer's turn has either already
  accrued this round under its old owner, or skips this round's accrual. Capture
  happens in the capturer's turn, after the capturer's `start_turn`, so a city
  can never accrue twice. The skip is accepted.
- Round 1: `reset` does not call player 0's `start_turn`, so player 0's cities
  accrue nothing in round 1 (r = 0, no claims). Accepted.
- **ACCEPTED GAP: Monument is not in `BUILD_OPTIONS`** (`agents/build_agent.py`),
  so no agent can build it and building culture is dormant in real games. The
  `culture` column and the source sum ship and are tested. Appending Monument
  changes the build head's width and `NUM_BUILD_CHANNELS`, which is an
  action-space change and belongs to the BuildAgent design pass (#73). This
  patch does not make it.

`culture(city)` lives in one function; it is the only place culture is computed.
The `culture` column of `[buildings.*]` is parsed by `civulator/unit_model.py`,
the only interpreter of building tables, beside `production_cost` and
`defense_bonus`.

## 2. Ownership

- **Ownership is per city**, not per player. The player's territory is the union
  of its cities' tiles. A tile has at most one owning city, or none (neutral).
- Stored as one integer grid on `Map` (`owner_city[r, q]`, city id or −1). One
  mutation API writes it (`claim`, `transfer`, `release`); nothing else writes
  the grid. There is no `Tile.owner` attribute. A player's territory is always
  derived from the grid and never cached on `Player`.
- **City ids** (critic 3 B7): a per-environment counter, reset in every reset
  attempt (unseeded retries included), assigned only inside the city-creation
  function (§2.1). Ids are monotonic and never reused within an episode.
  `env.city_by_id` is the single lookup. Never a process-global counter: two
  same-seed environments in one process must produce identical grids.
- Invariants: `tile.city` set ⇒ `owner_city` at that tile equals that city's
  id; every id in the grid is in `env.city_by_id`, and that city is in its
  player's `cities`.
- Ownership changes bump a new `Map.territory_epoch`, **not** `terrain_epoch`:
  terrain caches (LoS, cost grids, encoder terrain layers) must not be
  invalidated by border growth. Capture bumps `territory_epoch` too: the grid
  stores city ids, but the owning player changes. Ownership-derived caches key on
  `(map_uid, territory_epoch)`.
- A per-player live counter of owned tiles is maintained by the mutation API,
  for `episode_stats` (evaluate.py snapshots stats mid-run).
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

Replacements (step 3) are claimed one at a time through §3.2, with the territory
updated after each. If there are fewer candidates than blocked tiles, the city
simply gets fewer tiles. Founding claims do not count towards the culture cost
index `n` (§3.1).

**Every city is created and removed through `GameEnvironment`** (v2, critics 1
and 2): one creation function assigns the id, sets the centre, makes the
founding claim, and runs `assign_tiles` for every city whose tiles changed. One
removal function releases the city's tiles (§2.3). All four existing lifecycle
paths route through them:

| Path | Today | After |
|---|---|---|
| `GameEnvironment.found_city` | builds `City`, `set_city`, `assign_tiles` | creation function |
| `SettlerUnit.found_city` → `add_city` (unit.py) | builds `City` directly | creation function |
| `recording._place_city` fallback (painted cities closer than `min_city_distance`) | `City(...)` + `cities.append` + `add_city` | creation function, with the spacing check skipped as today. If its centre tile is owned by another city, the new city takes it. Contested ring-1 tiles go to the city placed earlier in the scenario file |
| `recording._clear_board` | `set_city(None)`, `cities = []` | removal function |

At reset, founding claims draw no RNG: capitals are at least
`min_city_distance` (4) apart, so ring-1 sets cannot overlap and no tie arises.
The world fingerprint must be unchanged by this patch.

### 2.2 Where a city may be founded

`can_found_city_at` becomes `can_found_city_at(coords, player)` (v2, all three
critics), and every caller passes the founder: the mask (`networks.py`), the
settler, `found_city`, the `settle` encoder's settle layer, and the tests that
call the one-argument form. It gains one condition: the tile is not owned by
another player.

The `settle` encoder's settle layer (`state_encoders.py`, `_get_settle_layer`)
becomes per player, and its cache key adds `territory_epoch` and the player
index. Otherwise it would show tiles the mask refuses (train/play skew), and one
player's grid to the other. Founding on a tile you already own (outside `min_city_distance` of every
city, as today) is allowed, and the tile moves to the new city. Erik,
2026-10-11: "I think it should be allowed." The settler action mask already calls `can_found_city_at`, so masks
and rules stay one function.

### 2.3 Capture and destruction

- A **captured** city keeps all its tiles, and they change player with it
  (Civ 6). Its `border_culture`, `culture_this_round` and `n` go with it. The
  hook is the existing capture path (`_capture_city` → `City.set_owner`), which
  bumps `territory_epoch` and updates both players' tile counters. From the next
  border phase on, the city claims for its new owner.
- A city that **ceases to exist** without being captured goes through the
  removal function, and its tiles become neutral. Today that is only
  `_clear_board`; razing later.
- Note for the razing follow-up: a boxed-in city's pool grows without bound, so
  tiles turning neutral would let it claim several at once.

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

The curve is evaluated in floats once per `n`, then converted to integer tenths
(`round(10 * cost(n))`). The pools are integer tenths too (§1), so every
comparison is exact.

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
2. the tile is adjacent to a resource tile (whoever owns that tile; this is
   only a ranking);
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
- When the round ends, one **border phase** resolves every city's claims. It
  runs inside `next_turn` only (never in `end_turn`, which is called twice per
  turn in places): after the last player's `end_turn`, when play wraps back to
  player 0, before `turn_counter += 1` and player 0's `start_turn`. Dead players
  still cycle through `next_turn`, so the wrap happens every round. Every
  existing city takes part, whoever owns it now.
- For each city, `r = culture_this_round` (integer tenths) and
  `p0 = border_culture − r`. Treat the round as running from time 0 to 1, with
  the pool filling linearly. With `S_k = cost(n+1) + … + cost(n+k)`, its k-th
  claim this round happens at
  ```
  t_k = (S_k − p0) / r          clamped to ≥ 0; an event exists only if t_k ≤ 1
  ```
  If `r = 0`, the city has events at t = 0 for each k with `S_k ≤ p0` (only
  possible for a city that was boxed in earlier) and none otherwise.
- **Lazy queue** (v2): each city holds at most one pending event, its next k.
  Events are popped in the total order below. The popped event claims that
  city's best tile **at that moment** by §3.2, subtracts the cost from its pool
  (`n += 1`), and then the city's next event is computed and pushed. A city
  whose preferred tile was just taken by an earlier event simply takes its
  next-best tile. **Nobody loses points or progress.** If a city has no candidate
  at its event, it is dropped for the rest of this phase. That is exact: within a
  phase a city's candidate set only shrinks, except through its own claims.
- **Total order of events, all exact integer arithmetic, no float t:**
  1. earlier `t`, compared by cross-multiplication:
     `(S_a − p0_a)·r_b` vs `(S_b − p0_b)·r_a`, with clamped events (t = 0) first;
  2. on equal `t`: the larger end-of-round surplus `p0 + r − S_k`, which for
     unclamped events is the city with the larger culture rate (this is what
     "larger overflow" means; at an unclamped crossing the pool equals the
     cost exactly);
  3. still tied: the tied events are sorted by city id, then shuffled with the
     engine RNG (§3.4).

  One city's own events are always in k order.
- At the end of the phase every city's `culture_this_round` is zeroed. Points
  left over stay in `border_culture` for the next round. A city can claim
  several tiles in one round if its culture is high enough.

So whoever reaches the cost first wins the tile, independent of turn order.
This is exactly the property the tests pin (§8).

Cities of the same player follow the same rule as rival cities.

### 3.4 The deterministic tiebreak

When candidates are still tied after §3.2's ranking (common: two plain grassland
tiles), or two claim events tie on both t and overflow, **the tied set is
sorted canonically (tiles by `(row, col)`, events by city id), then shuffled
with the engine RNG (`PortableRNG`) at the moment of the claim**, and the first
one is taken. RNG is drawn only when the tied set has two or more members. The
canonical sort makes the result independent of how the set was built, so it
survives refactors and a future C++ twin (#33).

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

The sort key is unchanged (food, then production). The city centre is not
among the candidates: it is still worked for free. Re-run `assign_tiles` for
every city that gains or loses a tile (claims, founding, swaps, capture) and on
population change. A city whose ring 1 is partly owned by an enemy simply has
fewer tiles to choose from.

The ownership filter lands in P2, while the radius is still 1, so no city ever
works an enemy-owned tile between patches. P4 widens the radius to 3.

Today `assign_tiles` reads `get_adjacent_coords` (ring 1 only). It switches to
`hexmath.hex_rings`. No new hex code.

## 5. Swapping a tile between two of your cities

Erik wants to keep this, as in Civ 6. Engine API:
`GameEnvironment.swap_tile(coords, to_city)`. It is valid only if:

- the tile is owned by a city of the same player as `to_city`, and that city is
  not `to_city`;
- the tile is within `to_city`'s `work_radius`;
- the tile is **at distance ≥ 2 from its current owner's centre**: neither the
  centre itself nor a tile adjacent to it (Civ 6: "a tile adjacent to the City
  Center of one city cannot be swapped to another city");
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
  minor game-version bump, **in P2**, the first patch that changes behaviour (v2,
  critic 2 B4). Each patch merges to `develop`, so from P2 on weights must not
  be stamped with the old version. P3–P5 extend the same CHANGELOG entry. The
  bump is 0.6.2 → **0.7.0**, plain semver; #83's open question (Erik once said
  v0.2.0) is unresolved. Follow the #78 epoch convention as implemented in
  `scripts/evaluate.py` and the CHANGELOG. The same patch regenerates
  `tests/fixtures/scenario_fixture.json` via `scripts/make_fixture_scenario.py`,
  so `check_version` still accepts it.
- No new actions. Masks change only through `can_found_city_at` (§2.2), which
  the mask already calls.
- **Agents mostly cannot see ownership** until the encoder follow-up. The one
  exception: the `settle` encoder's settle layer reflects founding legality,
  which now depends on ownership (§2.2). That is correct and mask-consistent.
  Accepted for this patch: the economy changes underneath them (cities work
  tiles up to radius 3), but their input and action space barely change.
- Start-placement fertility (`mapgen/starts.py`) scores rings 0–2 with a ring-1
  floor, tuned for ring-1 work. With radius 3 it measures the economy less well.
  Recorded as a follow-up issue; mapgen goldens are unaffected.
- `episode_stats` gains: tiles owned per player at the end of the episode,
  culture produced, and tiles claimed by culture. These are the order
  parameters for checking that borders actually grow in real games.

## 8. Tests: properties, each named with the change that must break it

| Property | Breaks if |
|---|---|
| No tile has two owners; every owned tile's city exists | a write bypasses the mutation API |
| Ring order: at every border-phase claim event, the claimed tile's distance equals the minimum distance over that city's candidates at that moment | §3.2 picks by value before distance |
| `tile.city` ⇒ `owner_city` there is that city's id; every grid id resolves through `env.city_by_id` to a city in its player's list, also after `_clear_board` and painted placement | a lifecycle path bypasses the creation/removal functions |
| World fingerprint at reset is unchanged by this arc (founding claims draw no RNG) | reset-time claims consume `PortableRNG` |
| Settle layer agrees with the mask for every player after border growth | the settle cache misses `territory_epoch`/player |
| r = 0 (city founded this round, or round 1 for player 0) produces no claim and no error | division by r |
| Culture claims never take a tile owned by anyone | growth can flip tiles |
| **Turn-order independence**: two cities with different crossing times contest one tile. The earlier one wins regardless of which player moves first (test both seat orders) | claims resolve during each player's turn instead of in the border phase |
| Losing a contest costs nothing: the loser claims its next-best tile in the same round, and its pool is reduced by exactly one cost | the loser's points are consumed or discarded |
| Same seed + same actions give identical `owner_city`, pools and `n` after N rounds, including two environments in one process | the tiebreak uses anything but `PortableRNG`, iteration order leaks in, or city ids are process-global |
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
| P2 | Ownership grid + mutation API + `territory_epoch`, per-env city ids, city creation/removal functions with all four lifecycle paths routed through them, founding restriction with `can_found_city_at(coords, player)` and the per-player settle layer, capture transfer, `swap_tile`, ownership filter in `assign_tiles` (radius still 1), version bump to 0.7.0 + CHANGELOG + fixture regeneration | §8 ownership properties; full suite green | subagent · Opus (touches founding, capture, masks, encoder) |
| P3 | Border growth: cost-curve registry, tile choice, round-end border phase with the event queue and tie rules | §8 ring-order, turn-order independence, seed determinism; full suite green | subagent · Opus (the subtle one) |
| P4 | Work radius 3 over owned tiles in `assign_tiles`; `episode_stats` additions | §8 work-radius property; full suite green; a seeded 250-turn random-policy self-play smoke run logs tiles owned per player over time and shows growth | subagent · Sonnet |
| P5 | Border overlay in `viz/hex_render.py` (city-coloured edges between owned and other tiles), CHANGELOG finalised, CLAUDE.md rows, follow-up issues filed (encoder ownership channels, start-placement fertility at radius 3, swap as agent action, Monument in BUILD_OPTIONS) | full suite green; the adjacency-render invariant test still passes; a headless screenshot of a seeded mid-game map shows borders (checked by the orchestrator) | subagent · Sonnet |

E2E check at the end (orchestrator): a seeded game rendered at several turns,
where borders visibly grow ring by ring, plus the turn-order independence test
run on the merged `develop`.

## Critique (lens table — one Opus critic per lens, run one at a time, each verdict written here before the next spawns)

| Lens | Verdict | Blockers |
|---|---|---|
| Rules semantics and edge cases | survives with fixes | (1) stale `culture_last_turn` after mid-round capture/founding → `culture_this_round`; (2) r = 0 undefined; (3) failed claim invalidates later t_k; (4) overflow tiebreak degenerate at t > 0; (5) `can_found_city_at` has no player arg, settle-layer cache and capture don't bump an ownership key; (6) founding replacements shortfall/order, and losing a tile to a new own city must re-run `assign_tiles`; (7) swap of a centre tile, and tool paths (`recording._place_city` fallback, `_clear_board`) bypass the claim/release API. Non-blocking: accrual order vs growth, centre not a worked candidate, resource adjacency counts any owner, ring property needs a claim-source notion, unbounded pool when boxed in, phase relies on dead players still cycling, phase only in `next_turn` |
| Systems reuse and regression | survives with fixes | (B1) `can_found_city_at` needs a player; the `settle` encoder's settle layer (state_encoders.py:649-668) becomes ownership- and player-dependent, so §7's "agents blind to ownership / masks unchanged" is false for it; 1-arg callers in tests; (B2) `recording._place_city` fallback and `_clear_board` create/remove cities outside the API; (B3) Monument is not in `BUILD_OPTIONS`, so building culture is dead in real games; (B4) version/epoch bump lands in P5 though behaviour changes from P2; P5 bump turns `test_recording` red via the 0.6.0 fixture. Non-blocking: Buildings row (unit_model.py) and City-combat row (`_capture_city`/`set_owner`) missing from Systems (a); tiles-owned stat live per seat; city-id counter resets per episode; P3→P4 gap where cities work enemy tiles; `assign_tiles` call belongs in the claim function; start-placement fertility tuned for ring 1 (follow-up); no C++/matchup impact; founding claims must draw no RNG at reset |
| Determinism and single-writer | survives with fixes | (B1) settle cache stale and player-agnostic; (B2) four city-lifecycle paths; (B3) `culture_last_turn` stale / r = 0 in round 1 and after capture; (B4) pre-shuffle order unspecified; (B5) overflow tiebreak a no-op; (B6) float t and `**1.3` make ties and `t ≤ 1` machine-dependent → integer tenths + cross-multiplication; (B7) city-id counter must be per env. Non-blocking: capture bumps `territory_epoch`; lazy queue; invariants for `tile.city` vs grid; reset draws no RNG; fingerprint/snapshot need no format change; no deepcopy/pickle of env; phase placement |

**Synthesis (v2, 2026-10-11).** All three lenses agreed the design survives with
fixes; their blockers overlapped heavily. Every blocker is resolved on paper
above: integer-tenths culture and exact event ordering (§1, §3.1, §3.3),
`culture_this_round` and the r = 0 rule, the lazy queue, the defined
tie keys and canonical pre-shuffle sort (§3.3–3.4), per-env city ids, invariants
and capture bumping `territory_epoch` (§2), all four lifecycle paths through
creation/removal functions (§2.1), `can_found_city_at(coords, player)` and the
per-player settle layer (§2.2), swap distance ≥ 2 (§5), the ownership filter
moved to P2 and the version bump moved to P2 (§4, §7, §9). One item is a
recorded ACCEPTED GAP rather than a fix: Monument is not buildable (§1, #73).
No further critique round: v2 is the build contract.

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
- **Action masking**: the founding restriction reaches masks through
  `can_found_city_at(coords, player)`.
- **State encoding** (`settle` encoder's settle layer): per player, cache key
  gains `territory_epoch` (§2.2).
- **Buildings** (`civulator/unit_model.py`, the only interpreter of
  `[buildings.*]`): parses the new `culture` column. Amend its CLAUDE.md row.
- **City combat** (`_capture_city` → `City.set_owner`, the one place a city
  changes hands): the hook for territory transfer. Amend its row.
- **Combat-training tools** (`civulator/tools/recording.py`): `_place_city`
  and `_clear_board` route through the city creation/removal functions.
- **Artifact manifests** (`civulator/meta.py`): the version bump; the scenario
  fixture is regenerated.
- **Evaluation harness** (`scripts/evaluate.py`): reads the new
  `episode_stats` fields through its existing snapshot/aggregate path.

### (b) New systems, with draft CLAUDE.md rows (written into CLAUDE.md at implementation, pointing at the real code)

| System | Where | Draft rule |
|---|---|---|
| Culture yield | `culture(city)` (module decided at P1) | The only computation of a city's culture. A new culture source declares a `culture` value in its own config table (building, district, …); never add a culture term to the formula itself |
| Territory | `Map.owner_city` + its mutation API (`claim` / `transfer` / `release`), `Map.territory_epoch` | The only record of who owns a tile and the only writer of it. Cities are created and removed only through `GameEnvironment`'s creation/removal functions (id, claim, release). Founding, border growth, capture and swaps all go through it; ownership-derived caches key on `(map_uid, territory_epoch)`, never on `terrain_epoch` |
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
