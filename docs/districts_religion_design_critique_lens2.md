# Critique lens 2: rules semantics, edge cases, fit to principles

> Subject: `docs/districts_religion_design.md` v2.1, read with "v2 fixes"
> overriding §2–§15 and R1–R11 / C1–C9 taken as fixed. Independent of
> lens 1 (its report was not read). Code was read only to check rule claims:
> `game/loyalty.py`, `game/trade.py`, `game/victory.py`,
> `game/environment.py` (`economy_phase`, `is_city_under_siege`),
> `game/city.py` (`can_make_ranged_attack`), `game/unit.py`
> (`enemy_city_blocks`, `get_ranged_strength`), `mapgen/starts.py`,
> `config.toml` (`[loyalty]`, `[map.sizes.*]`, `[improvements.*]`).
> Opus, 2026-10-22.

**Verdict: survives with fixes — 10 blockers.** Every blocker is closed by a
sentence or two in v3. None reopens a ruling.

## Blockers

**1. Founding makes no city follow the religion, and the seat is not
unique (§7.3, §7.4, §10).** `found_religion` charges faith and names "the
Temple's city" the seat, but nothing sets any `City.religion = R`. Pressure
comes only from cities *following* R, and §10 says a religion with zero
followers projects nothing and cannot `spread_religion`. As written, every
religion is born dead and only a 75-faith inquisition revives it, and two
implementers will differ on whether founding converts. "A complete Holy Site
with a Temple somewhere" can also hold in several cities, and the seat is
not chosen. **Fix:** founding sets the seat's `City.religion = R`, overriding
whatever it followed, and clears its conversion streak. The seat is the
qualifying own city with the lowest city id; if the agent should choose,
it becomes an argument of the action.

**2. Lapse and a dead founder are undefined where they matter (§7.4, §7.5,
§10, v2 "Religion state").**
(a) "A lapsed religion projects no pressure" does not say whether that
includes its own cities' self-term at distance 0 and its ledger entries. If
it does, a lapsed religion's cities defend with 0. The conversion test's
`(pressure(current, C) or secular)` then either falls through to secular,
under a Python-`or` reading, or stays at 0, under the "current exists"
reading. Two builds would give different conversions.
(b) Upkeep runs "in the founder's economy phase", which a dead player never
has. Under one reading a dead founder's religion is never charged, never
lapses and projects free pressure forever. Under the other it is lapsed
forever and its cities have no defence. §7.4 says the religion "outlives
its founder", but not in which of these two states.
(c) The order of upkeep and founder pay inside the religion step is not
given. If pay comes first, a Pilgrimage religion with foreign followers can
never lapse. Partial payment ("treasury short": is the faith debited to 0,
or kept?) is not given either.
**Fix:** state it. My recommendation: lapse removes outward pressure, that
is, terms on cities that do not follow R plus R's ledger entries elsewhere,
but keeps each follower city's own self-term, so followers are not punished
(the stated principle for follower beliefs). A dead founder's religion is
permanently "unpaid but not lapsed for defence" under the same rule. Upkeep
is checked and debited before founder pay. A short treasury pays nothing and
keeps its faith. The incumbent term is `secular` only when
`City.religion is None`.

**3. Itinerant Preachers breaks the pressure arithmetic (§7.3 enhancer,
§7.4, §7.6).** The term is `population * weight * (citizen_weight −
distance)` with `range = 9` and `citizen_weight = 10`. +3 range makes
distance 10 contribute 0 and distances 11–12 contribute *negative*
pressure. The belief then does nothing at its new reach, or subtracts. Loyalty's own
parser forbids exactly this (`loyalty.parse_loyalty`: `citizen_weight` must
be ≥ `range + 1`, "a city at the edge of the range must still weigh"). The
belief is a dead or harmful choice in the enhancer tier. **Fix:**
`religion_param { range = 3 }` raises `citizen_weight` by the same amount
for that religion, or the term is `max(1, …)` beyond the base range. Either
way, `religion_model` validates `range + bonus < citizen_weight + bonus` at
load.

**4. `exclusive = true` caps religions at four, which contradicts
`max_religions = 0` (§7.3, §7.6, C5).** There are four founder beliefs and
eight follower beliefs (two per religion), so at most four religions can
ever be founded. The presets seat up to 6 (Small), 8 (Standard, and
`[game] num_players = 8`), 12 and 24 players. §7.3's reason for the default,
"every player may found, the race is for followers, not for a slot", is
false on every preset above Tiny. The fifth player meets a refusal whose
reason the doc never names. **Fix:** say it. With `exclusive`, religions
are capped by the founder-belief count. `can_found_religion` names "no
founder belief left" as a refusal clause, and §7.3's sentence is reworded.
If Erik wants "every player", the alternative is more founder beliefs or
exclusivity per tier. That is a ruling, so it is flagged rather than chosen
here.

**5. "A city whose religion is not its owner's" is undefined for the common
cases (§7.5 loyalty term, on by default at −1).** Only founders have a
religion. It is unclear whether a founder's still-secular city (None ≠ R)
pays −1, and whether a non-founder's city following anything pays −1 (it
always would, so adoption always costs loyalty, which may be intended but
is not said). For a non-founder's secular city, None == None, so 0 is
presumably intended. Two builds will differ on the first case, and that
moves loyalty for every founder from founding onward. **Fix:** the term
applies iff `city.religion is not None and city.religion !=
owner.founded_religion_index`, and §7.5 says in one line that adopting a
foreign religion always costs its adopter this term (the price of the
follower beliefs).

**6. The conversion phase is under-specified in integers and rounds (§7.4,
v2).**
(a) Ledger expiry is undefined. An entry appended mid-round with
`rounds_left = 10` counts in 9, 10 or 11 `_religion_phase`s depending on
where the decrement sits.
(b) A candidate with pressure 0 is not excluded, and when the incumbent
is also 0 (see 2a), `0*100 ≥ 0*125` "converts" to a religion that does not
press.
(c) What happens to the streak during immunity is not given: frozen, reset,
or accrued (accrual means conversion fires the round immunity ends).
(d) The candidate changing mid-streak is implied to reset the streak, but
this is never stated.
**Fix:** entries are counted in the phase, then decremented, and removed at
0, so an entry counts in exactly `spread_rounds` phases. A candidate needs
pressure > 0. Immunity resets the streak to 0. A new candidate restarts the
streak at 1.

**7. Luxury assignment is static or greedy, and the doc does not say which
(§3.2).** "Cities sorted by `need − supply_without_luxuries`, the first
`luxury_cities` get it." If the order is computed once, every luxury lands
on the same four cities, and a fifth city stays at a deficit while the
fourth sits at +5. If it is recomputed after each luxury, the luxuries
spread out. The two differ as soon as a player has more than four cities.
The order in which luxuries are processed is also unstated. **Fix:** greedy.
Luxuries are taken in config order, and each goes to the `luxury_cities`
cities with the largest *current* deficit (supply counting luxuries already
assigned), ties by city id.

**8. A breached Encampment can hold an enemy and then repair under it (§4.2,
v2 "Encampment repair", B4).** A city is never stood on by an enemy that
does not capture it (`enemy_city_blocks`: entry only at 0 and only by a
capturer, who then owns it). A breached Encampment is never captured, so an
enemy *can* stand on it. The repair test is the siege ring around the tile
(`is_city_under_siege` reads only the six neighbours), so a lone enemy on
the tile does not block repair. The district then returns to health > 0
with an enemy inside a tile that "refuses enemy entry". The strike gate is
"when its city may" (§15(b)), and `City.can_make_ranged_attack` reads the
*city's* health. A breached Encampment at 0 therefore still fires, while a
healthy Encampment of a 0-health city does not. Whether it may target a
unit standing on its own tile is undefined. **Fix:** an enemy unit on the
tile blocks repair, as the ring does. The Encampment strikes iff its own
health > 0, the city holds `ranged_building`, and no enemy stands on its
tile.

**9. The two combat beliefs do not say which tile and which defender
(§7.3 enhancer, R10/C8, v2 "Crusade / Defender of the Faith").** R10 says
Defender of the Faith pays "+5 for units fighting on tiles owned by a city
that follows yours". §7.3 says "units standing on a tile … (both roles)".
v2 has the strength functions gain "the defender's tile". For an attacker
these name different tiles: its own tile, or the target's. Crusade's
condition is "the defender is a City whose religion ≠ …", but after B4 a
fortified district is a defender that reads as a city (`is_city`) and has
no `religion`. Whether Crusade applies against an Encampment is open.
Whether enhancers stay in force while the religion is lapsed is also not
said. **Fix:** Defender of the Faith reads the tile of the unit that
receives the bonus, in both roles. Crusade reads the religion of the
defending city, or of the Encampment's city. Enhancers hold while lapsed
(lapse touches only pressure and founder pay), or the opposite, stated once.

**10. The overseas bonus is reachable only on routes to another player
(§1 ACCEPTED GAP #76, §6.6, v2 B6, §0.1/R3).** Land units never enter
water, and an island "without a land path" is never settled. So a player
owns cities on exactly one landmass, except for one that flips to it by
loyalty. `trade.pair_yields` admits international destinations, so
an overseas route exists only toward an opponent on another landmass.
`starts._apportion_players` puts players on separate landmasses only when
fertility apportions it, so in a single-continent Duel the jump never
fires. The design presents the jump as Erik's "discrete, extremely
satisfying" coast game and says the Trader default "finds the overseas route
by itself", but it never says the route goes to the enemy. That is what
Erik's ruling (R3) is being asked to accept. This also answers the farming question:
two one-tile islands cannot be settled, so the ×2 cannot be farmed.
**Fix:** declare it in §1's gap row and §6.6 ("domestic overseas routes
arise only from loyalty flips until #76"). The Q6 smoke gate needs a seed
whose players start on different landmasses, which should be named.

## Non-blocking

- **Religious victory (§7.5, v2):** "more than half of the cities of every
  living player" needs `followers * 2 > cities`, and a living player with
  0 cities (Settler only) must be said to block it or be skipped. The
  domination code already guards the same vacuity (`palace_granted`). The
  founder must also be living to win (domination checks `is_dead`).
  Secular cities count in the denominator, which is presumably intended;
  say so.
- **Spread into an immune city** whose `inquisition_rounds_left ≥
  spread_rounds` is strictly wasted faith, an always-wrong action the mask
  offers. `can_spread_to` should refuse it.
- **Route kind live or frozen (§15(b) vs B6):** "derived … at
  establishment" conflicts with the multiplier living in `pair_yields`,
  which is read every turn. It decides whether a land pair across a strait
  turns ×2 when its Harbors complete, or when Cartography opens an Ocean
  path mid-route. Pick one; live is simpler.
- **`requires_resource` honoured "when the world has any resource of that
  class" (v2):** a painted world with Horses but no Iron gates the Swordsman
  forever. Key the test by resource *name*.
- **Worker default vs `improved_by` (§10's Niter row):** the gap is general.
  Farm, Camp, Pasture and Quarry all admit the Grassland/Plains luxury tiles,
  so a yield-ranked default can bury Silk or Wine under a Farm, and
  agentless amenities then depend on it. Widen the ACCEPTED GAP to every
  tiered resource. Niter on Grassland/Plains flat admits no Mine at all
  (`[improvements.Mine] on`), so it is district- or centre-only, which is
  worth one line.
- **Holy Order −30 % and Religious Settlements −15 %:** the rounding is
  unstated (125 × 70 / 100 = 87.5). Say floor.
- **`need − free_first`** can go negative if `free_first` is raised. Clamp
  it at 0.
- **Pantheon exclusivity** is unstated (Civ 6: exclusive). Say which.
- **Counts:** the pantheon table lists 11, not "twelve". The three
  `adjacency_row` pantheons need their own rows (Desert / Tundra /
  Rainforest). "2 × 4 × 8 × 7 × 5" is not the number of religions
  (4 × 8 × 7 × 5 = 1,120 ordered).
- **Same-round founding under `exclusive`:** sequential turns give the
  lower seat first pick of beliefs every time. The paired-sides eval
  cancels this, but name it.
- **Principle 3 (compete, not add):** Choral Music and Work Ethic pay a Holy
  Site's adjacency a second time as culture or production at 100 %, so one
  slot serves two trees, and Jesuit Education turns faith into Campus and
  Theater buildings. The competition for slots is weakened by design. The
  percent is a dial, so the dial table should name the stat that shows it
  (e.g. Theater Squares built by players holding Choral Music).
- **Secular resistance** has no neighbour term, unlike every religion. It is
  a structural asymmetry, not just a number: an unaligned region cannot
  resist collectively. This is fine if intended; one line says so.
- **"Own and allied-to-nobody units may" (§4.2)** names a category that does
  not exist. It should read "own units".
- **Lake–Coast adjacency:** if mapgen can put a Lake beside a Coast tile, a
  "lake" Harbor joins the sea. Say whether Lake is a separate water body for
  §6.4 / §10.

## Checked and fine

- Pressure mirrors `loyalty.pressures` (own city at distance 0, inclusive
  range, the cities of living players). The one-test pin is sound.
- Conversion compares in integers (`×100` against `×(100 + margin)`), and
  ties go to the lower founder index (v2). It is deterministic.
- Two religions spreading to one city: separate ledger entries, the
  strongest foreign candidate, and the margin against the incumbent only.
  Consistent.
- Founder pay and upkeep are not a money pump. Upkeep is faith, pay is
  gold, science or culture, except Pilgrimage, whose net +1 faith per
  foreign follower is the intended reward and needs the neighbour's city.
- Inquisition and spread do not ping-pong. Inquisition is a flat 75 for 10
  rounds of immunity, while the spread price rises 25 per use, so the cost
  war favours the defender and terminates.
- A religion with zero followers projects nothing, owes no upkeep, and can
  be revived only by its founder's inquisition. This is consistent once
  blocker 1 is fixed.
- A city keeps its religion, ledger and immunity through capture and flip.
  Follower beliefs of a dead founder's religion stay readable.
- Amenities are recomputed live, so a luxury lost to a capture mid-turn
  changes supply at the next read with no stale state. A city at
  population 1 cannot fall below −1, so the deep bands are reachable only
  by large cities.
- The amenity bands parse (strictly descending mins, last row catches all),
  and the yield scaling is applied after loyalty in tenths with a floor.
  Food is exempt.
- The economy-phase position of the religion step (after maintenance,
  before research) comes after city accrual, so the round's faith income
  is in the pool before upkeep. Purchases come after, as §7.4 claims.
- An Encampment on the only land approach is the intended forward wall. It
  is breached by attack, entry is refused in the mask and in `Unit.move`
  alike (B4), and ZoC remains movement-free.
- Cross-domain melee: hits both ways, never moves in without `can_enter`,
  and a Galley cannot capture (`can_capture_city` is land-only). A Caravel
  is melee, so it has no Ocean bombard. A Quadrireme takes the
  `ranged_city_penalty` against cities and Encampments under the existing
  non-siege rule.
- Harbor on a Lake: ships are confined to the lake, a sea route is possible
  only to another Harbor on the same water, and it is never overseas. A
  pair reachable by land and sea is a sea route (§6.6).
- A player with no coast cannot build ships and has no Harbor. This is a
  real geographic difference, not a dead action, because
  `can_produce_unit` refuses.
- The mask invariant holds for every §9 action given the stated predicates:
  inquisition on an already-own-religion city still changes immunity, and
  spread on an own follower city adds defensive ledger pressure. Neither is
  a no-op. The single exception, spread into an immune city, is listed
  above.
- Shared benefits are a real trade-off. Foreign-counting founder beliefs
  pay only through the neighbour, Crusade pays only against cities *not*
  following you, so spreading to the enemy costs its bonus, and
  `foreign_religion_loyalty` rewards spreading. Founders face reasons both
  ways.
- No action is braindead micro. Spread is one priced choice per city with
  no unit, and the religion defaults are declared braindead, to be replaced
  by #99.
