"""Loyalty (issue #116 P7, docs/progression_design.md §8 and "v2 fixes").

The one interpreter of `[loyalty]` in config.toml and the one computation of
a city's loyalty: the pressure players exert on it, its per-round delta, the
band that scales its yields and growth, and the player it flips to at 0.
Civ 6's model (Rise and Fall / Gathering Storm; the Civilization Wiki,
digested in docs/civ6_progression_reference.md §11), in integers:

    pressure(C, P) = the sum over P's cities c within RANGE of C (canonical
                     wrap distance, inclusive) of
                     population(c) * (CITIZEN_WEIGHT - distance(c, C));
                     C counts for its owner at distance 0
    own, foreign   = the owner's pressure; every other living player's, summed
    drift          = sign(own - foreign)
                     * (2 * DRIFT_GAIN * |own - foreign| // (2 * min(own, foreign) + 1)),
                     clamped to +-DRIFT_CAP -- Civ 6's
                     10 * (D - F) / (min(D, F) + 0.5), truncated toward zero
    delta          = drift
                     + GARRISON while a unit of the owner of a fighting class
                       (`unit_model.FIGHTING_CLASSES`) stands on the centre
                     + the `loyalty` columns of the city's buildings and
                       complete districts
                     + the `loyalty` effects in force for the city (the one
                       consumer of that kind): `requires_garrison` holds only
                       with that garrison, `per_population` multiplies by the
                       city's population, and an entry with a `range` counts
                       only when the city holding its source is the city's
                       owner's and within that range of it

`GameEnvironment._loyalty_phase` applies the deltas once per round, at round
end, computed for every city from the state at the start of the phase, and
flips a city left at 0 to its `largest_foreign_presser` through
`GameEnvironment._flip_city`. `loyalty_percent` and `growth_share` read the
city's band: the first of `BANDS` whose minimum the loyalty reaches, the last
for a loyalty below every minimum.

Pure: reads the parsed config, the live map, the units on the centre and the
effects in force; mutates nothing. No building, district, wonder or policy
name appears here: a source is a column on its own table or a `loyalty`
effect.
"""

from dataclasses import dataclass

from ..config import CFG
from ..effects import KIND_LOYALTY, active_effects
from ..unit_model import BUILDING_LOYALTY, FIGHTING_CLASSES
from .districts import district_spec

# The floor of the score: a city here after the phase flips, if anyone presses it.
LOYALTY_MIN = 0

_KEYS = frozenset({
    "founded", "captured", "maximum", "range", "citizen_weight",
    "drift_gain", "drift_cap", "garrison", "bands",
})


@dataclass(frozen=True)
class Band:
    """One row of `[loyalty] bands`: from `min` loyalty up, the city keeps
    `yield_percent` of its science, culture, gold, faith and production and
    `growth_share` percent of its growth."""

    min: int
    yield_percent: int
    growth_share: int


def _int(value, what, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"[loyalty] {what} must be an int, got {value!r}")
    if low is not None and value < low:
        raise ValueError(f"[loyalty] {what} must be >= {low}, got {value!r}")
    if high is not None and value > high:
        raise ValueError(f"[loyalty] {what} must be <= {high}, got {value!r}")
    return value


def parse_bands(bands, maximum):
    """`[[min, yield_percent, growth_share], ...]` -> tuple of Band.

    Raises on a table that is not a non-empty list of three-int rows, a min
    outside 0..`maximum`, a negative percent or share, or mins that are not
    strictly descending -- so a mis-ordered table cannot silently change which
    band wins (the `parse_growth_bands` discipline, #88)."""
    if not isinstance(bands, list) or not bands:
        raise ValueError("[loyalty] bands must be a non-empty list of [min, yield_percent, "
                         "growth_share] rows")
    parsed = []
    for i, row in enumerate(bands):
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"[loyalty] bands[{i}] must be [min, yield_percent, growth_share], "
                             f"got {row!r}")
        low, yield_percent, share = row
        parsed.append(Band(_int(low, f"bands[{i}] min", 0, maximum),
                           _int(yield_percent, f"bands[{i}] yield_percent", 0),
                           _int(share, f"bands[{i}] growth_share", 0)))
    for a, b in zip(parsed, parsed[1:]):
        if not a.min > b.min:
            raise ValueError("[loyalty] bands mins must be strictly descending")
    return tuple(parsed)


@dataclass(frozen=True)
class LoyaltyRules:
    """The parsed `[loyalty]` table (see config.toml for each key)."""

    founded: int
    captured: int
    maximum: int
    range: int
    citizen_weight: int
    drift_gain: int
    drift_cap: int
    garrison: int
    bands: tuple


def parse_loyalty(cfg):
    """Parse and validate one `[loyalty]` table -> LoyaltyRules. Raises on an
    unknown or missing key, a non-int value, `founded` / `captured` outside
    0..`maximum`, a `citizen_weight` that does not exceed `range` (a city at
    the edge of the range must still weigh), and bad `bands`."""
    if not isinstance(cfg, dict):
        raise ValueError("[loyalty] must be a table")
    unknown = set(cfg) - _KEYS
    if unknown:
        raise ValueError(f"[loyalty]: unknown key(s) {sorted(unknown)}")
    missing = _KEYS - set(cfg)
    if missing:
        raise ValueError(f"[loyalty]: missing key(s) {sorted(missing)}")
    maximum = _int(cfg["maximum"], "maximum", 1)
    reach = _int(cfg["range"], "range", 0)
    rules = LoyaltyRules(
        founded=_int(cfg["founded"], "founded", LOYALTY_MIN, maximum),
        captured=_int(cfg["captured"], "captured", LOYALTY_MIN, maximum),
        maximum=maximum,
        range=reach,
        citizen_weight=_int(cfg["citizen_weight"], "citizen_weight", reach + 1),
        drift_gain=_int(cfg["drift_gain"], "drift_gain", 0),
        drift_cap=_int(cfg["drift_cap"], "drift_cap", 0),
        garrison=_int(cfg["garrison"], "garrison"),
        bands=parse_bands(cfg["bands"], maximum),
    )
    return rules


RULES = parse_loyalty(CFG["loyalty"])
# Module-level names, read at call time (a test may patch one).
FOUNDED = RULES.founded
CAPTURED = RULES.captured
MAXIMUM = RULES.maximum
RANGE = RULES.range
CITIZEN_WEIGHT = RULES.citizen_weight
DRIFT_GAIN = RULES.drift_gain
DRIFT_CAP = RULES.drift_cap
GARRISON = RULES.garrison
BANDS = RULES.bands


# --- Pressure and drift -------------------------------------------------------------


def pressures(city, env):
    """Player index -> the pressure that player exerts on `city`, for every
    living player with a city within RANGE of it (a player absent from the
    dict exerts 0). The cities are read in `city_by_id` order; `city` itself
    counts for its owner at distance 0."""
    distance = env.map.distance_function
    out = {}
    for city_id in sorted(env.city_by_id):
        other = env.city_by_id[city_id]
        if other.player.is_dead:
            continue
        d = distance(other.coordinates, city.coordinates)
        if d > RANGE:
            continue
        index = other.player.player_index
        out[index] = out.get(index, 0) + other.population * (CITIZEN_WEIGHT - d)
    return out


def pressure(city, player_index, env):
    """The pressure player `player_index` exerts on `city` (0 for a dead
    player or one with no city in range)."""
    return pressures(city, env).get(player_index, 0)


def _own_and_foreign(city, by_player):
    owner = city.player.player_index
    own = by_player.get(owner, 0)
    return own, sum(value for index, value in by_player.items() if index != owner)


def drift(own, foreign):
    """The pressure term of a city's delta: Civ 6's 10 * (own - foreign) /
    (min(own, foreign) + 0.5) in integers, truncated toward zero, clamped to
    +-DRIFT_CAP (design "v2 fixes", Loyalty arithmetic)."""
    diff = own - foreign
    q = (2 * DRIFT_GAIN * abs(diff)) // (2 * min(own, foreign) + 1)
    sign = (diff > 0) - (diff < 0)
    return max(-DRIFT_CAP, min(DRIFT_CAP, sign * q))


# --- Sources ------------------------------------------------------------------------


def is_garrisoned(city, env):
    """Whether a unit of the city's owner of a fighting combat class (not
    `support`, not `civilian`) stands on its centre."""
    return any(unit.player is city.player and unit.combat_class in FIGHTING_CLASSES
               for unit in env.get_units_at(city.coordinates))


def column_loyalty(city):
    """The `loyalty` columns of the city's buildings and complete districts
    (wonders included), whole points."""
    total = sum(BUILDING_LOYALTY.get(building, 0) for building in city.buildings)
    total += sum(district_spec(d.type).loyalty for d in city.districts if d.complete)
    return total


def effect_loyalty(city, env, garrisoned):
    """The `loyalty` effects in force for the city, summed (the one consumer
    of the kind): an entry with `requires_garrison` only when `garrisoned`;
    one with a `range` only when the city holding its source belongs to this
    city's owner and lies within that range (canonical wrap distance); each
    amount times the city's population when `per_population`."""
    distance = env.map.distance_function
    total = 0
    for effect in active_effects(city.player, city, KIND_LOYALTY):
        if effect["requires_garrison"] and not garrisoned:
            continue
        reach = effect["range"]
        if reach > 0:
            holder = effect.source_city
            if (holder is None or holder.player is not city.player
                    or distance(holder.coordinates, city.coordinates) > reach):
                continue
        amount = effect["amount"]
        if effect["per_population"]:
            amount *= city.population
        total += amount
    return total


def loyalty_delta(city, env):
    """What the city's loyalty moves by this round (before the clamp to
    LOYALTY_MIN..MAXIMUM): drift + garrison + columns + effects."""
    own, foreign = _own_and_foreign(city, pressures(city, env))
    garrisoned = is_garrisoned(city, env)
    return (drift(own, foreign) + (GARRISON if garrisoned else 0)
            + column_loyalty(city) + effect_loyalty(city, env, garrisoned))


def clamp(loyalty):
    """`loyalty` held to LOYALTY_MIN..MAXIMUM."""
    return max(LOYALTY_MIN, min(MAXIMUM, loyalty))


def largest_foreign_presser(city, env):
    """The living player other than the city's owner exerting the largest
    pressure on it (ties: the lower player index), or None when no other
    player exerts any."""
    by_player = pressures(city, env)
    owner = city.player.player_index
    best = None
    for index in sorted(by_player):
        if index == owner or by_player[index] <= 0:
            continue
        if best is None or by_player[index] > by_player[best]:
            best = index
    return None if best is None else env.players[best]


# --- Bands --------------------------------------------------------------------------


def band(city):
    """The city's band: the first of BANDS whose min its loyalty reaches, the
    last one when it reaches none (loyalty 0)."""
    for row in BANDS:
        if city.loyalty >= row.min:
            return row
    return BANDS[-1]


def loyalty_percent(city):
    """Percent of its science, culture, gold, faith and production the city
    keeps (read by `city_yield` and `City.calculate_production`)."""
    return band(city).yield_percent


def growth_share(city):
    """Percent of its growth the city keeps (read by
    `City.growth_bucket_gain`)."""
    return band(city).growth_share
