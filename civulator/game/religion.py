"""Religion in the engine (v0.9.0 Q7/Q8, docs/districts_religion_design.md §7,
§9, "v3 fixes" L1, L2, L4).

Q7 holds the pantheon predicate; Q8 the founded religion (`Religion`), the
founding and belief predicates with their refusal reasons, the seat rule and
founder pay. Pressure, conversion, upkeep and inquisition (their predicates
and pure helpers) arrive in Q9. The registry -- `[religion]`, `[pantheons.*]`,
`[beliefs.*]` -- is read only through `civulator/religion_model.py`.

Pure: reads players, cities and the registry, mutates nothing. The writers of
religious state are `GameEnvironment.choose_pantheon` (`Player.pantheon`),
`GameEnvironment.found_religion` (`Player.religion`, the seat's
`City.religion`) and `GameEnvironment.add_belief` (`Religion.follower_beliefs`
/ `enhancer_belief`); Q9 adds conversion and inquisition as writers of
`City.religion` and upkeep as the writer of `Religion.lapsed`. No RNG anywhere.

Faith costs are whole points in config; the faith pool is int tenths, so every
comparison and debit here is in tenths (`*_tenths`).

Exclusivity (`[religion] exclusive`, Erik's ruling R13): a belief belongs to at
most one religion, so the founder beliefs cap the number of religions (v3
fixes L4: `can_found_religion` has the refusal REFUSE_NO_FOUNDER_BELIEF_LEFT).
"Taken" is derived from every player's religion (dead players included) and
never stored twice (`taken_beliefs`).
"""

from dataclasses import dataclass, field

from ..effects import KIND_PER_FOLLOWER_CITY, SOURCE_BELIEF, effects_of
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
    enhancer or None) and `lapsed`, the flag Q9's upkeep writes (a placeholder
    here: always False, read by nothing yet). Plain mutable record: the
    episode fingerprint compares it by fields."""

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


