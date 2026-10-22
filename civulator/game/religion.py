"""Religion in the engine (v0.9.0 Q7/Q8, docs/districts_religion_design.md §7,
§9, "v3 fixes" L1, L2, L4).

Q7 holds the pantheon predicate; Q8 the founded religion (`Religion`), the
founding and belief predicates with their refusal reasons, the seat rule and
founder pay; Q9 pressure (the loyalty formula, `loyalty.pressure_terms`),
the conversion test, upkeep and lapse, the directed-spread and inquisition
predicates, the `religion_param` reader and the foreign-religion loyalty
term. The registry -- `[religion]`, `[pantheons.*]`,
`[beliefs.*]` -- is read only through `civulator/religion_model.py`.

Pure: reads players, cities and the registry, mutates nothing. The writers of
religious state are `GameEnvironment.choose_pantheon` (`Player.pantheon`),
`GameEnvironment.found_religion` (`Player.religion`, the seat's
`City.religion`), `GameEnvironment.add_belief` (`Religion.follower_beliefs`
/ `enhancer_belief`), `GameEnvironment._religion_phase` (conversion:
`City.religion`, `conversion_streak`, `inquisition_rounds_left`,
`spread_ledger` expiry), `GameEnvironment.spread_religion` (`spread_ledger`,
`Player.spread_uses`), `GameEnvironment.inquisition` (`City.religion`, the
immunity) and `GameEnvironment._religion_upkeep` (`Religion.lapsed`). No RNG
anywhere.

Faith costs are whole points in config; the faith pool is int tenths, so every
comparison and debit here is in tenths (`*_tenths`).

Exclusivity (`[religion] exclusive`, Erik's ruling R13): a belief belongs to at
most one religion, so the founder beliefs cap the number of religions (v3
fixes L4: `can_found_religion` has the refusal REFUSE_NO_FOUNDER_BELIEF_LEFT).
"Taken" is derived from every player's religion (dead players included) and
never stored twice (`taken_beliefs`).
"""

from dataclasses import dataclass, field

from ..effects import (
    KIND_PER_FOLLOWER_CITY,
    KIND_RELIGION_PARAM,
    SOURCE_BELIEF,
    active_effects,
    effects_of,
)
from ..unit_model import BUILDING_RELIGIOUS_WEIGHT
from .districts import district_spec
from .loyalty import pressure_terms
from ..religion_model import (
    BELIEF_LADDER,
    BELIEFS,
    COUNTS_FOREIGN,
    PANTHEON_COST,
    PANTHEONS,
    RULES,
    TIER_FOLLOWER,
    TIER_FOUNDER,
    belief_tier,
    beliefs_of_tier,
)


@dataclass
class Religion:
    """A founded religion (design §7.1): the founder's player index (its
    identity -- `City.religion` holds it), its beliefs by tier (one founder
    belief, 1..`religion_model.MAX_FOLLOWER_BELIEFS` follower beliefs in
    purchase order, the
    enhancer or None) and `lapsed`: True while its founder's last upkeep went
    unpaid (written only by `GameEnvironment._religion_upkeep`, read through
    `is_unpaid`). Plain mutable record: the episode fingerprint compares it
    by fields."""

    founder: int
    founder_belief: str
    follower_beliefs: list = field(default_factory=list)
    enhancer_belief: object = None
    lapsed: bool = False

    @property
    def beliefs(self):
        """Every belief name the religion holds, founder first, then the
        follower beliefs in purchase order, then the enhancer."""
        names = [self.founder_belief, *self.follower_beliefs]
        if self.enhancer_belief is not None:
            names.append(self.enhancer_belief)
        return names

    @property
    def rung(self):
        """How many `belief_costs` rungs have been bought: the follower
        beliefs beyond the founding one plus the enhancer."""
        return (len(self.follower_beliefs) - 1) + (self.enhancer_belief is not None)

    @property
    def due_tier(self):
        """The tier the next `add_belief` buys (BELIEF_LADDER[rung]), or None
        when the ladder is climbed."""
        return BELIEF_LADDER[self.rung] if self.rung < len(BELIEF_LADDER) else None


# --- Costs ---------------------------------------------------------------------------


def pantheon_cost_tenths():
    """The faith a pantheon costs, in the faith pool's unit (int tenths):
    `[religion] pantheon_cost` whole points x 10."""
    return 10 * PANTHEON_COST


def found_cost_tenths():
    """`[religion] found_cost` in tenths: what founding debits."""
    return 10 * RULES.found_cost


def belief_cost_tenths(rung):
    """`[religion] belief_costs[rung]` in tenths: what the rung-th
    `add_belief` debits (rung 0 = tier 2, the second follower belief; rung 1
    = tier 3, the enhancer)."""
    return 10 * RULES.belief_costs[rung]


# --- Pantheon (Q7) ---------------------------------------------------------------------


def can_choose_pantheon(player, name, env=None):
    """Whether `player` may choose pantheon `name` now (design §9, the mask's
    predicate; every refusal reason is here): the player has no pantheon yet
    (a pantheon is permanent), `name` is a `[pantheons.*]` table, and the
    faith pool holds `[religion] pantheon_cost`. `env` is accepted for the
    predicate family's uniform signature; Q7's clauses do not read it."""
    if player is None or getattr(player, "is_dead", False):
        return False
    if player.pantheon is not None:
        return False
    if name not in PANTHEONS:
        return False
    return player.faith >= pantheon_cost_tenths()


# --- What exists (derived, never stored) ------------------------------------------------


def religions(env):
    """Every founded religion on the board, in founder index order -- dead
    founders included (a religion outlives its founder, design §7.5)."""
    return [p.religion for p in env.players if p.religion is not None]


def taken_beliefs(env):
    """The belief names some religion holds, in founder index order then
    tier order: what `[religion] exclusive` denies a second religion. Derived
    from `religions(env)` on every call; nothing records it twice."""
    return [name for religion in religions(env) for name in religion.beliefs]


def free_beliefs(env, tier):
    """The beliefs of `tier`, in config order, no religion holds (every
    belief of the tier when `exclusive` is false). The defaults walk it."""
    names = beliefs_of_tier(tier)
    if not RULES.exclusive:
        return list(names)
    taken = set(taken_beliefs(env))
    return [name for name in names if name not in taken]


def seat_city(player):
    """The city founding would convert (v3 fixes L1): the player's city with
    the lowest id that holds `[religion] founding_building` and its
    `requires_district` complete -- "a complete Holy Site with a Temple" --
    or None. The qualifying city, not the capital: the seat is where the
    faith infrastructure stands."""
    building = RULES.founding_building
    district = RULES.founding_district
    best = None
    for city in player.cities:
        if building not in city.buildings:
            continue
        if not any(d.type == district and d.complete for d in city.districts):
            continue
        if best is None or city.city_id < best.city_id:
            best = city
    return best


def follower_cities(religion, env):
    """The cities following `religion`, whoever owns them, in city-id order
    (`env.city_by_id`, the one city registry)."""
    return [env.city_by_id[cid] for cid in sorted(env.city_by_id)
            if env.city_by_id[cid].religion == religion.founder]


# --- Founding (design §7.3, §9; v3 fixes L1, L4) -------------------------------------

# The refusal reasons of `founding_refusals` / `belief_refusals`, each one
# clause of the predicate (the mask invariant: every reason is here).
REFUSE_DEAD = "player is dead"
REFUSE_NO_PANTHEON = "no pantheon chosen"
REFUSE_HAS_RELIGION = "already founded a religion"
REFUSE_NO_RELIGION = "no religion founded"
REFUSE_NO_SEAT = "no own city with the founding building and its district complete"
REFUSE_FAITH = "faith short of the cost"
REFUSE_MAX_RELIGIONS = "max_religions reached"
REFUSE_NO_FOUNDER_BELIEF_LEFT = "no founder belief left (exclusive)"
REFUSE_NOT_FOUNDER_BELIEF = "founder belief is not a founder belief"
REFUSE_NOT_FOLLOWER_BELIEF = "follower belief is not a follower belief"
REFUSE_TAKEN = "belief taken by another religion (exclusive)"
REFUSE_WRONG_TIER = "belief is not of the due tier"
REFUSE_LADDER_CLIMBED = "no belief tier left to buy"
REFUSE_ALREADY_HELD = "belief already held by this religion"


def _taken_by_another(name, player, env):
    """Whether `name` is held by a religion other than `player`'s own, under
    `exclusive` (never when exclusivity is off)."""
    if not RULES.exclusive:
        return False
    return any(name in religion.beliefs for religion in religions(env)
               if religion.founder != player.player_index)


def founding_refusals(player, founder_belief, follower_belief, env):
    """Why `player` may not found a religion with these two beliefs now --
    every clause of design §7.3 and v3 fixes L1/L4 as a list of REFUSE_*
    reasons, empty when founding is allowed:

    - the player lives, has a pantheon and no religion;
    - `seat_city` exists (an own city with `[religion] founding_building` and
      its district complete);
    - the faith pool (tenths) covers `found_cost`;
    - fewer than `max_religions` religions exist (0 = unlimited);
    - at least one founder belief is free (L4: `exclusive` caps religions at
      the founder-belief count);
    - `founder_belief` is a founder belief and `follower_belief` a follower
      belief, and under `exclusive` neither is held by another religion.
    """
    reasons = []
    if player is None or getattr(player, "is_dead", False):
        return [REFUSE_DEAD]
    if player.pantheon is None:
        reasons.append(REFUSE_NO_PANTHEON)
    if player.religion is not None:
        reasons.append(REFUSE_HAS_RELIGION)
    if seat_city(player) is None:
        reasons.append(REFUSE_NO_SEAT)
    if player.faith < found_cost_tenths():
        reasons.append(REFUSE_FAITH)
    if RULES.max_religions and len(religions(env)) >= RULES.max_religions:
        reasons.append(REFUSE_MAX_RELIGIONS)
    if not free_beliefs(env, TIER_FOUNDER):
        reasons.append(REFUSE_NO_FOUNDER_BELIEF_LEFT)
    if belief_tier(founder_belief) != TIER_FOUNDER:
        reasons.append(REFUSE_NOT_FOUNDER_BELIEF)
    elif _taken_by_another(founder_belief, player, env):
        reasons.append(REFUSE_TAKEN)
    if belief_tier(follower_belief) != TIER_FOLLOWER:
        reasons.append(REFUSE_NOT_FOLLOWER_BELIEF)
    elif _taken_by_another(follower_belief, player, env):
        reasons.append(REFUSE_TAKEN)
    return reasons


def can_found_religion(player, founder_belief, follower_belief, env):
    """Whether `player` may found a religion with `founder_belief` and
    `follower_belief` now (design §9, the mask's predicate): no
    `founding_refusals`."""
    return not founding_refusals(player, founder_belief, follower_belief, env)


# --- Beliefs after founding (design §7.3) --------------------------------------------


def belief_refusals(player, name, env):
    """Why `player` may not add belief `name` to its religion now, as REFUSE_*
    reasons (empty when allowed): the player lives and has a religion; a tier
    is due (`Religion.due_tier`: tier 2 -- a second follower belief -- before
    tier 3, the enhancer); `name` is a belief of that tier, not already held
    by this religion, and under `exclusive` not held by another; the faith
    pool covers `belief_costs[rung]`."""
    if player is None or getattr(player, "is_dead", False):
        return [REFUSE_DEAD]
    religion = player.religion
    if religion is None:
        return [REFUSE_NO_RELIGION]
    reasons = []
    due = religion.due_tier
    if due is None:
        reasons.append(REFUSE_LADDER_CLIMBED)
    else:
        if player.faith < belief_cost_tenths(religion.rung):
            reasons.append(REFUSE_FAITH)
        if belief_tier(name) != due:
            reasons.append(REFUSE_WRONG_TIER)
    if name in religion.beliefs:
        reasons.append(REFUSE_ALREADY_HELD)
    elif belief_tier(name) is not None and _taken_by_another(name, player, env):
        reasons.append(REFUSE_TAKEN)
    return reasons


def can_add_belief(player, name, env):
    """Whether `player` may add belief `name` to its religion now (design §9,
    the mask's predicate): no `belief_refusals`."""
    return not belief_refusals(player, name, env)


# --- Founder pay (design §7.3, the `per_follower_city` kind; v3 fixes L2) -------------


def founder_pay_tenths(player, env):
    """What the religion `player` founded pays it this turn (design §7.3,
    the one consumer of `per_follower_city`): for each `per_follower_city`
    effect of its founder belief, the effect's tenths of each pool yield
    times the follower cities the belief `counts` -- every city following
    the religion (`all`), or only those another player owns (`foreign`). A
    dict {yield: tenths} of the nonzero amounts; empty for no religion, and
    for a DEAD founder (L2: a dead founder's religion pays nobody -- its
    follower cities keep their beliefs). Pure; `GameEnvironment._founder_pay`
    adds it to the pools in the religion step of the economy phase, after
    Q9's upkeep."""
    religion = player.religion
    if religion is None or player.is_dead:
        return {}
    cities = follower_cities(religion, env)
    if BELIEFS[religion.founder_belief].counts == COUNTS_FOREIGN:
        cities = [c for c in cities if c.player is not player]
    count = len(cities)
    pay = {}
    for effect in effects_of(SOURCE_BELIEF, religion.founder_belief):
        if effect.kind != KIND_PER_FOLLOWER_CITY:
            continue
        for name, tenths in effect["yields"].items():
            amount = tenths * count
            if amount:
                pay[name] = pay.get(name, 0) + amount
    return pay




# --- Q9: the religion engine (design §7.4, §7.5; v2 fixes; v3 fixes L2, L3, L5, L6) ----
#
# Pressure, the conversion test, directed spread, upkeep and inquisition, as
# pure functions; their writers are `GameEnvironment._religion_phase`,
# `spread_religion`, `_religion_upkeep` and `inquisition`. Integers only, no
# RNG; every walk is in city-id order (`env.city_by_id`) or founder-index
# order (`religions(env)`), never over a set.


@dataclass(frozen=True)
class ReligionParams:
    """The summed `religion_param` effects in force for a founder (v0.9.0 Q8
    parses them; Q9 reads them here and only here): `range` raises the
    religion's pressure range AND its citizen weight (v3 fixes L3);
    `spread_amount_percent` scales a directed spread's ledger amount;
    `cost_percent` scales the spread and inquisition costs."""

    range: int = 0
    spread_amount_percent: int = 0
    cost_percent: int = 0


def religion_params(founder_player):
    """The one consumer of `religion_param` (effects.CONSUMERS): the sums of
    each attribute over the entries in force for `founder_player` -- the
    enhancer belief of the religion it founded, the only source the kind may
    sit on. All zero for no player or no such belief."""
    if founder_player is None:
        return ReligionParams()
    entries = active_effects(founder_player, kind=KIND_RELIGION_PARAM)
    return ReligionParams(range=sum(e["range"] for e in entries),
                          spread_amount_percent=sum(e["spread_amount_percent"] for e in entries),
                          cost_percent=sum(e["cost_percent"] for e in entries))


def pressure_reach(founder_player):
    """The pressure range of the religion `founder_player` founded:
    `[religion] range` + its `religion_param` range (v3 fixes L3)."""
    return RULES.range + religion_params(founder_player).range


def pressure_citizen_weight(founder_player):
    """The citizen weight of that religion's pressure: `[religion]
    citizen_weight` + the same `range` bonus, so the term stays positive to
    the raised edge (v3 fixes L3; the parser re-checks `citizen_weight >
    range` with both raised)."""
    return RULES.citizen_weight + religion_params(founder_player).range


def religious_weight(city):
    """What one citizen of `city` weighs in its religion's pressure (design
    §7.4): 1 + the `religious_weight` columns of its buildings and of its
    complete districts -- read from the registries, never by name (a Holy
    Site, Shrine and Temple at 1 each make a seat weigh 4)."""
    weight = 1 + sum(BUILDING_RELIGIOUS_WEIGHT.get(b, 0) for b in city.buildings)
    weight += sum(district_spec(d.type).religious_weight for d in city.districts if d.complete)
    return weight


def is_unpaid(religion, env):
    """Whether `religion` projects no outward pressure this round (v3 fixes
    L2): its upkeep went unpaid at its founder's last economy phase
    (`Religion.lapsed`), or its founder is dead -- a dead founder's religion
    is permanently unpaid. One rule, read by `pressure`; nothing stores the
    dead-founder case twice."""
    return religion.lapsed or env.players[religion.founder].is_dead


def ledger_pressure(religion_index, city):
    """The directed-spread entries for `religion_index` on `city` (design
    §7.4): the summed `amount` of its `spread_ledger` entries still running
    (`rounds_left > 0`)."""
    return sum(amount for index, amount, left in city.spread_ledger
               if index == religion_index and left > 0)


def pressure(religion_index, city, env):
    """The pressure of the religion founded by player `religion_index` on
    `city` (design §7.4; one formula with loyalty, `loyalty.pressure_terms`):

        sum over the cities c following R within reach (wrap distance,
        inclusive) of population(c) * religious_weight(c) *
        (citizen_weight - distance(c, city)) -- `city` counts at distance 0
        when it follows R -- plus R's running ledger entries on `city`,

    reach and citizen weight raised by the founder's `religion_param` range
    (L3). LAPSE (L2): while R `is_unpaid`, its outward pressure is 0 -- every
    term on a city that does not follow R, its ledger entries there
    included; on R's own follower cities everything stays (their defence).
    0 for a player without a religion."""
    founder = env.players[religion_index]
    religion = founder.religion
    if religion is None:
        return 0
    if city.religion != religion_index and is_unpaid(religion, env):
        return 0
    sources = follower_cities(religion, env)
    total = sum(term for _, term in pressure_terms(
        sources, city, env, pressure_reach(founder), pressure_citizen_weight(founder),
        religious_weight))
    return total + ledger_pressure(religion_index, city)


def secular_pressure(city):
    """A secular city's resistance (design §7.4): population x `[religion]
    secular_weight`."""
    return city.population * RULES.secular_weight


def incumbent_term(city, env):
    """The incumbent side of the conversion test (v3 fixes L2): the secular
    pressure iff `city.religion is None`, otherwise its own religion's
    pressure on it (which may be 0)."""
    if city.religion is None:
        return secular_pressure(city)
    return pressure(city.religion, city, env)


def candidate(city, env):
    """`(religion index, pressure)` of the strongest religion other than the
    city's own (ties: the lower founder index; v2 fixes), requiring pressure
    > 0 (L6) -- or `(None, 0)`."""
    best, best_pressure = None, 0
    for religion in religions(env):
        if religion.founder == city.religion:
            continue
        value = pressure(religion.founder, city, env)
        if value > best_pressure:
            best, best_pressure = religion.founder, value
    return best, best_pressure


def wins_margin(candidate_pressure, incumbent):
    """The conversion test (design §7.4), in integers: the candidate's
    pressure x 100 >= the incumbent term x (100 + `conversion_margin`)."""
    return candidate_pressure * 100 >= incumbent * (100 + RULES.conversion_margin)


def next_streak(city, env):
    """`(new streak, convert_to)` for `city` this phase, from the state as it
    is (the phase computes every city before changing any; v3 fixes L6):
    under inquisition immunity the streak resets and nothing converts; a
    candidate that wins the margin extends a streak for the same candidate
    or restarts it at 1; anything else resets it to `(None, 0)`. At
    `conversion_rounds` the city converts (convert_to = the candidate) and
    the streak resets."""
    if city.inquisition_rounds_left > 0:
        return (None, 0), None
    best, best_pressure = candidate(city, env)
    if best is None or not wins_margin(best_pressure, incumbent_term(city, env)):
        return (None, 0), None
    held, rounds = city.conversion_streak
    rounds = rounds + 1 if held == best else 1
    if rounds >= RULES.conversion_rounds:
        return (None, 0), best
    return (best, rounds), None


def decremented_ledger(city):
    """The city's ledger after one phase (L6): every entry one round shorter,
    those reaching 0 removed, order kept."""
    return [(index, amount, left - 1) for index, amount, left in city.spread_ledger
            if left - 1 > 0]


def loyalty_term(city, env):
    """The foreign-religion loyalty term (design §7.5, v3 fixes L5; Erik's
    accepted call C6 -- Civ 6 has none): `[religion] foreign_religion_loyalty`
    iff the city follows a religion and it is not the one its owner founded
    (a non-founder's follower city pays it; a founder's secular city does
    not); 0 otherwise. One term of `loyalty.loyalty_delta`."""
    if city.religion is None:
        return 0
    founded = city.player.religion
    if founded is not None and city.religion == founded.founder:
        return 0
    return RULES.foreign_religion_loyalty


# --- Upkeep (design §7.4, v3 fixes L2) --------------------------------------------------


def upkeep_tenths(player, env):
    """What `player`'s religion owes this economy phase, in tenths:
    `upkeep_per_follower_city` x its follower cities, whoever owns them; 0
    for no religion."""
    if player.religion is None:
        return 0
    return 10 * RULES.upkeep_per_follower_city * len(follower_cities(player.religion, env))


# --- Directed spread and inquisition (design §7.4, §9) ------------------------------------

REFUSE_NO_CITY = "no such city"
REFUSE_OUT_OF_RANGE = "no city following the religion within range"
REFUSE_NOT_OWN_CITY = "not the player's own city"


def _scaled_tenths(points, percent):
    """`points` whole faith x (100 + percent) / 100, floored, in tenths."""
    return 10 * points * (100 + percent) // 100


def spread_cost_tenths(player):
    """What `player`'s next directed spread costs, in tenths (design §7.4,
    the Civ 6 price curve): (`spread_cost` + `spread_cost_step` x
    `Player.spread_uses`) x (100 + the `religion_param` cost_percent) / 100,
    floored."""
    return _scaled_tenths(RULES.spread_cost + RULES.spread_cost_step * player.spread_uses,
                          religion_params(player).cost_percent)


def spread_amount(player):
    """The pressure one directed spread of `player`'s religion adds for
    `spread_rounds` phases: `spread_amount` x (100 + the `religion_param`
    spread_amount_percent) / 100, floored."""
    return RULES.spread_amount * (100 + religion_params(player).spread_amount_percent) // 100


def inquisition_cost_tenths(player):
    """What an inquisition costs `player`, in tenths: `inquisition_cost` x
    (100 + the `religion_param` cost_percent) / 100, floored."""
    return _scaled_tenths(RULES.inquisition_cost, religion_params(player).cost_percent)


def _in_reach_of_a_follower(player, city, env):
    reach = pressure_reach(player)
    distance = env.map.distance_function
    return any(distance(c.coordinates, city.coordinates) <= reach
               for c in follower_cities(player.religion, env))


def spread_refusals(player, city, env):
    """Why `player` may not spread its religion to `city` now (design §9,
    `can_spread_to`; every clause, as REFUSE_* reasons, empty when allowed):
    the player lives and founded a religion; `city` stands (any owner); some
    city following the religion lies within its reach (`pressure_reach`,
    the `religion_param` range included) of `city`; the faith pool covers
    `spread_cost_tenths`."""
    if player is None or getattr(player, "is_dead", False):
        return [REFUSE_DEAD]
    if player.religion is None:
        return [REFUSE_NO_RELIGION]
    if city is None or env.city_by_id.get(city.city_id) is not city:
        return [REFUSE_NO_CITY]
    reasons = []
    if not _in_reach_of_a_follower(player, city, env):
        reasons.append(REFUSE_OUT_OF_RANGE)
    if player.faith < spread_cost_tenths(player):
        reasons.append(REFUSE_FAITH)
    return reasons


def can_spread_to(player, city, env):
    """Whether `player` may spread its religion to `city` now (the mask's
    predicate): no `spread_refusals`."""
    return not spread_refusals(player, city, env)


def inquisition_refusals(player, city, env):
    """Why `player` may not hold an inquisition in `city` now (design §9,
    `can_inquisition`; every clause as REFUSE_* reasons): the player lives;
    `city` stands and is the player's own; the faith pool covers
    `inquisition_cost_tenths`. A player without a religion may hold one (the
    city becomes secular, design §7.4)."""
    if player is None or getattr(player, "is_dead", False):
        return [REFUSE_DEAD]
    if city is None or env.city_by_id.get(city.city_id) is not city:
        return [REFUSE_NO_CITY]
    reasons = []
    if city.player is not player:
        reasons.append(REFUSE_NOT_OWN_CITY)
    if player.faith < inquisition_cost_tenths(player):
        reasons.append(REFUSE_FAITH)
    return reasons


def can_inquisition(player, city, env):
    """Whether `player` may hold an inquisition in `city` now (the mask's
    predicate): no `inquisition_refusals`."""
    return not inquisition_refusals(player, city, env)
