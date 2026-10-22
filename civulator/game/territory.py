"""Territory rules (issue #87, spec docs/borders_culture_design.md §2, §3.2, §3.4).

The only reader of `[territory]` in config.toml, and home of the §3.2
tile-choice ranking (used by the founding claim's replacements now and by
border growth in P3). Pure engine code: hexmath for every radius/ring/
adjacency, the composed tile yields for value, `PortableRNG` (passed in) for
the tiebreak. The ownership grid itself and its mutation API live on `Map`.
"""

from .. import hexmath
from ..config import CFG
from ..effects import KIND_BORDER_COST_PERCENT, active_effects, percent_sum

_TERRITORY_CFG = CFG["territory"]
CLAIM_RADIUS = int(_TERRITORY_CFG["claim_radius"])
WORK_RADIUS = int(_TERRITORY_CFG["work_radius"])
FOUNDING_RING = int(_TERRITORY_CFG["founding_ring"])

NEUTRAL = -1


def _has_resource(tile):
    return tile is not None and bool(tile.resource)


def claim_candidates(game_map, city, claim_radius=None):
    """§3.2 candidates at minimum distance: neutral tiles within
    `claim_radius` of the city centre (canonical wrap distance), adjacent to a
    tile this city owns, restricted to the nearest ring that has any.

    Returns a list of (row, col), sorted by (row, col); empty if none.
    """
    radius = CLAIM_RADIUS if claim_radius is None else claim_radius
    owner = game_map.owner_city
    rows, cols = game_map.n, game_map.m
    rings = hexmath.hex_rings(city.coordinates, radius, rows, cols)
    for ring in rings[1:]:
        found = [
            pos for pos in ring
            if owner[pos] == NEUTRAL
            and any(owner[adj] == city.city_id for adj in hexmath.adjacent_coords(pos, rows, cols))
        ]
        if found:
            return sorted(found)
    return []


def claim_rank(game_map, pos):
    """§3.2 value key, larger is better: (has a resource, adjacent to a
    resource tile of any owner, food + production composed through the
    terrain model)."""
    tile = game_map.get_tile(pos)
    adjacent_resource = any(
        _has_resource(game_map.get_tile(adj))
        for adj in hexmath.adjacent_coords(pos, game_map.n, game_map.m)
    )
    food, production = tile.yields
    return (_has_resource(tile), adjacent_resource, food + production)


def choose_claim_tile(game_map, city, rng, claim_radius=None):
    """The tile `city` claims next by §3.2, or None if there is no candidate.

    Minimum distance first (the ring rule), then `claim_rank`; ties left
    after ranking are sorted by (row, col) and, only when two or more remain,
    shuffled with the engine RNG (§3.4) — the first is taken.
    """
    candidates = claim_candidates(game_map, city, claim_radius)
    if not candidates:
        return None
    ranked = [(claim_rank(game_map, pos), pos) for pos in candidates]
    best = max(key for key, _ in ranked)
    tied = sorted(pos for key, pos in ranked if key == best)
    if len(tied) >= 2:
        rng.shuffle(tied)
    return tied[0]


# --- §3.1 border cost curves ------------------------------------------------
#
# A curve is a pure function (n, **params) -> cost in culture points (float),
# n = 1, 2, ... the n-th tile a city claims by culture. Never change what an
# existing name computes (old manifests pin the name); add a new entry.


def _civ6_community(n, a, b, p):
    """Community reading of Civ 6's GlobalParameters: a + (b*(n-1))**p."""
    return a + (b * (n - 1)) ** p


BORDER_COST_CURVES = {
    "civ6_community": _civ6_community,
}


def border_cost_function(table):
    """Build the cost function selected by a `[territory.border_cost]` table.

    `table["curve"]` names an entry of `BORDER_COST_CURVES` (unknown names
    raise); every other key is passed to it as a keyword parameter. Returns
    `cost(n) -> int tenths`: the curve is evaluated in float once per n and
    converted once, `round(10 * curve(n))`, so every pool comparison is exact
    integer arithmetic.
    """
    params = dict(table)
    name = params.pop("curve")
    if name not in BORDER_COST_CURVES:
        raise ValueError(
            f"[territory.border_cost] curve = {name!r} is not in BORDER_COST_CURVES "
            f"(known: {sorted(BORDER_COST_CURVES)})"
        )
    curve = BORDER_COST_CURVES[name]
    cache = {}

    def cost(n):
        if n < 1:
            raise ValueError(f"border cost index must be >= 1, got {n}")
        if n not in cache:
            cache[n] = int(round(10 * curve(n, **params)))
        return cache[n]

    return cost


# --- §3.3 the round-end border phase ----------------------------------------


def border_cost_percent(player):
    """The summed `percent` of the `border_cost_percent` effects in force for
    `player` (v0.9.0 Q7, Religious Settlements); 0 for no player. Read by
    `run_border_phase` -- the one consumer of that kind."""
    if player is None:
        return 0
    return percent_sum(active_effects(player, kind=KIND_BORDER_COST_PERCENT))


def claim_cost(cost, n, percent):
    """Tenths of culture the n-th claim costs a city whose owner's
    `border_cost_percent` sums to `percent`: `cost(n)` unchanged at 0, else
    `cost(n) * (100 + percent) // 100`, at least 1. `cost(n)` itself stays
    player-blind (design "v2 fixes")."""
    base = cost(n)
    if not percent:
        return base
    return max(1, base * (100 + percent) // 100)


class _PhaseCity:
    """One city's state for one border phase. `b0` = pool at phase start
    (= p0 + r), `spent` = S_{k-1}, the culture claimed so far this phase."""

    __slots__ = ("city", "r", "p0", "b0", "spent", "next_cost", "percent")

    def __init__(self, city, cost):
        self.city = city
        self.r = city.culture_this_round
        self.b0 = city.border_culture
        self.p0 = self.b0 - self.r
        self.spent = 0
        # The owner's border_cost_percent at phase start (v0.9.0 Q7).
        self.percent = border_cost_percent(getattr(city, "player", None))
        self.next_cost = claim_cost(cost, city.border_claims + 1, self.percent)

    def has_event(self):
        """Event k exists iff t_k <= 1, i.e. S_k <= p0 + r. With r = 0 this is
        S_k <= p0, the boxed-in case (events at t = 0)."""
        return self.spent + self.next_cost <= self.b0

    def numerator(self):
        """S_k - p0 clamped at 0: t_k = numerator / r."""
        return max(0, self.spent + self.next_cost - self.p0)

    def surplus(self):
        """End-of-round surplus p0 + r - S_k (the §3.3 second key)."""
        return self.b0 - self.spent - self.next_cost


def _compare_events(a, b):
    """§3.3 keys 1 and 2, exact integers: negative if a's event comes first,
    0 if tied on both t and surplus. Clamped events (t = 0) are all equal on
    t and precede every unclamped one; unclamped events always have r > 0
    and compare by cross-multiplication (S_a - p0_a)*r_b vs (S_b - p0_b)*r_a.
    """
    na, nb = a.numerator(), b.numerator()
    if na == 0 or nb == 0:
        t_cmp = (na != 0) - (nb != 0)
    else:
        lhs, rhs = na * b.r, nb * a.r
        t_cmp = (lhs > rhs) - (lhs < rhs)
    if t_cmp:
        return t_cmp
    sa, sb = a.surplus(), b.surplus()
    return (sb > sa) - (sb < sa)


def run_border_phase(game_map, cities, cost, rng, on_claim=None, claim_radius=None):
    """Resolve one round's culture claims for `cities` (borders design §3.3).

    Lazy queue: each city holds at most its next event; the earliest event
    by `_compare_events` is popped, ties on both keys are sorted by city id
    and shuffled with the engine RNG (drawn only when two or more tie). The
    popped city claims `choose_claim_tile` at that moment, pays `cost(n+1)`
    -- scaled by its owner's `border_cost_percent` effects (`claim_cost`,
    v0.9.0 Q7; the percent is read once per city at phase start) -- from its
    pool and increments its `border_claims`; `on_claim(city, pos)`
    runs after every claim. A city with no candidate is dropped for the rest
    of the phase (its pool is kept). Finally every city's
    `culture_this_round` is zeroed. Returns the claims as [(city_id, pos)]
    in event order.
    """
    states = sorted((_PhaseCity(c, cost) for c in cities), key=lambda s: s.city.city_id)
    pending = [s for s in states if s.has_event()]
    claims = []
    while pending:
        first = pending[0]
        tied = [first]
        for state in pending[1:]:
            cmp = _compare_events(state, first)
            if cmp < 0:
                first, tied = state, [state]
            elif cmp == 0:
                tied.append(state)
        if len(tied) >= 2:
            tied.sort(key=lambda s: s.city.city_id)
            rng.shuffle(tied)
        state = tied[0]
        city = state.city
        pos = choose_claim_tile(game_map, city, rng, claim_radius)
        if pos is None:
            pending.remove(state)
            continue
        game_map.claim(pos, city)
        city.border_culture -= state.next_cost
        city.border_claims += 1
        state.spent += state.next_cost
        state.next_cost = claim_cost(cost, city.border_claims + 1, state.percent)
        claims.append((city.city_id, pos))
        if on_claim is not None:
            on_claim(city, pos)
        if not state.has_event():
            pending.remove(state)
    for state in states:
        state.city.culture_this_round = 0
    return claims
