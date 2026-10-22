"""Amenities (v0.9.0 Q2, docs/districts_religion_design.md §3 and "v2/v3
fixes"): the one interpreter of `[amenities]` in config.toml and the only
happiness computation in the engine. Civ 6 Gathering Storm's model, in
integers:

    need(city)    = max(0, ceil(population / need_divisor) - free_first)
                    (a size-1 city needs 1)
    supply(city)  = the `amenity` COLUMNS of the city's buildings and complete
                    districts (wonders included)
                    + the `amenity` EFFECTS in force for the city (the one
                      consumer of that kind): `range` counts only when the
                      city holding the source belongs to this city's owner and
                      lies within that range (canonical wrap distance),
                      `min_districts` only with that many complete specialty
                      districts, `requires_garrison` only with a garrison
                      (`loyalty.is_garrisoned`)
                    + the city's share of the player's luxuries
    surplus(city) = supply - need
    band(city)    = the first row of `[amenities] bands` whose min the surplus
                    reaches (the last row for a surplus below every min):
                    (yield_percent, growth_percent, loyalty_delta)

Luxuries (design "v3 fixes" L7): every distinct luxury the player has access to
(`resources.accessible_resources`, so two copies of Wine are one Wine) gives +1
amenity to up to `luxury_cities` of the player's cities, assigned GREEDILY:
luxuries in config order, each to the cities with the largest current deficit
(`need - supply`, counting the luxuries already assigned in this computation),
ties by city id. `luxury_shares` computes the whole player in one call and
nothing is cached: amenities are recomputed from live state on every call, like
`district_yields`.

Three readers, one each, and never a fourth: `yields.city_yield` scales
science, culture, gold and faith by `(100 + yield_percent) / 100` AFTER the
loyalty percent (food never; production in `City.calculate_production`, beside
its loyalty percent), `City.growth_bucket_gain` multiplies the growth bucket by
`growth_percent / 100`, and `loyalty.loyalty_delta` adds `loyalty_term`. Civ 6
spawns rebels at Unrest; we have no barbarians, so the loyalty column replaces
rebels -- its numbers are Claude's starting values for Erik's dial.

Pure and integer-only: reads the parsed config, the live map and the effects in
force; mutates nothing, draws no RNG; cities are visited in city-id order. No
building, district, wonder or policy name appears here: a source is a column on
its own table or an `amenity` effect.
"""

from typing import NamedTuple

from ..config import CFG
from ..effects import KIND_AMENITY, active_effects
from ..unit_model import BUILDING_AMENITY
from .districts import district_spec, specialty_districts
from .loyalty import is_garrisoned
from .resources import accessible_resources

_KEYS = frozenset({"need_divisor", "free_first", "luxury_cities", "bands"})


class AmenityBand(NamedTuple):
    """One row of `[amenities] bands`: from `min` surplus up, the city keeps
    `100 + yield_percent` percent of its science, culture, gold, faith and
    production, `growth_percent` percent of its growth, and its loyalty moves
    by `loyalty` per round."""

    min: int
    yield_percent: int
    growth_percent: int
    loyalty: int


def _int(value, what, low=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"[amenities] {what} must be an int, got {value!r}")
    if low is not None and value < low:
        raise ValueError(f"[amenities] {what} must be >= {low}, got {value!r}")
    return value


def parse_bands(bands):
    """`[[min, yield_percent, growth_percent, loyalty], ...]` -> tuple of
    AmenityBand. The contract of `loyalty.parse_bands`, widened to what a
    happiness table needs: four int columns, a min that may be negative (a
    deficit), a yield percent that may be negative (not below -100) and a
    loyalty delta that may be negative.

    Raises on a table that is not a non-empty list of four-int rows, a growth
    percent below 0, a yield percent below -100, or mins that are not
    strictly descending -- so a mis-ordered table cannot silently change which
    band wins. The first matching row wins and the last row catches every
    surplus below the rest (`band_row`)."""
    if not isinstance(bands, list) or not bands:
        raise ValueError("[amenities] bands must be a non-empty list of [min, yield_percent, "
                         "growth_percent, loyalty] rows")
    parsed = []
    for i, row in enumerate(bands):
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError(f"[amenities] bands[{i}] must be [min, yield_percent, "
                             f"growth_percent, loyalty], got {row!r}")
        low, yield_percent, growth_percent, loyalty = row
        parsed.append(AmenityBand(_int(low, f"bands[{i}] min"),
                                  _int(yield_percent, f"bands[{i}] yield_percent", -100),
                                  _int(growth_percent, f"bands[{i}] growth_percent", 0),
                                  _int(loyalty, f"bands[{i}] loyalty")))
    for a, b in zip(parsed, parsed[1:]):
        if not a.min > b.min:
            raise ValueError("[amenities] bands mins must be strictly descending")
    return tuple(parsed)


class AmenityRules(NamedTuple):
    """The parsed `[amenities]` table (see config.toml for each key)."""

    need_divisor: int
    free_first: int
    luxury_cities: int
    bands: tuple


def parse_amenities(cfg):
    """Parse and validate one `[amenities]` table -> AmenityRules. Raises on a
    non-table, an unknown or missing key, a non-int value, a `need_divisor`
    below 1, a negative `free_first` or `luxury_cities`, and bad `bands`."""
    if not isinstance(cfg, dict):
        raise ValueError("[amenities] must be a table")
    unknown = set(cfg) - _KEYS
    if unknown:
        raise ValueError(f"[amenities]: unknown key(s) {sorted(unknown)}")
    missing = _KEYS - set(cfg)
    if missing:
        raise ValueError(f"[amenities]: missing key(s) {sorted(missing)}")
    return AmenityRules(
        need_divisor=_int(cfg["need_divisor"], "need_divisor", 1),
        free_first=_int(cfg["free_first"], "free_first", 0),
        luxury_cities=_int(cfg["luxury_cities"], "luxury_cities", 0),
        bands=parse_bands(cfg["bands"]),
    )


RULES = parse_amenities(CFG["amenities"])
# Module-level names, read at call time (a test may patch one).
NEED_DIVISOR = RULES.need_divisor
FREE_FIRST = RULES.free_first
LUXURY_CITIES = RULES.luxury_cities
BANDS = RULES.bands


# --- Need and supply ----------------------------------------------------------------


def need(city):
    """What the city's population asks of its amenities: `ceil(population /
    NEED_DIVISOR) - FREE_FIRST`, floored at 0 (Civ 6 GS: one per two citizens
    rounded up, so a size-1 city needs 1)."""
    return max(0, -(-city.population // NEED_DIVISOR) - FREE_FIRST)


def column_supply(city):
    """The `amenity` columns of the city's buildings and complete districts
    (wonders included), whole points."""
    total = sum(BUILDING_AMENITY.get(building, 0) for building in city.buildings)
    total += sum(district_spec(d.type).amenity for d in city.districts if d.complete)
    return total


def effect_supply(city, env, garrisoned=None):
    """The `amenity` effects in force for the city, summed (the one consumer
    of the kind): an entry with `requires_garrison` only when the city is
    garrisoned (`loyalty.is_garrisoned`); one with `min_districts` only when
    the city holds that many complete specialty districts; one with a `range`
    only when the city holding its source belongs to this city's owner and
    lies within that range (canonical wrap distance, inclusive; a source city
    reaches itself)."""
    effects = active_effects(city.player, city, KIND_AMENITY)
    if not effects:
        return 0
    distance = env.map.distance_function
    specialty = None
    total = 0
    for effect in effects:
        if effect["requires_garrison"]:
            if garrisoned is None:
                garrisoned = is_garrisoned(city, env)
            if not garrisoned:
                continue
        if effect["min_districts"]:
            if specialty is None:
                specialty = len(specialty_districts(city))
            if specialty < effect["min_districts"]:
                continue
        reach = effect["range"]
        if reach > 0:
            holder = effect.source_city
            if (holder is None or holder.player is not city.player
                    or distance(holder.coordinates, city.coordinates) > reach):
                continue
        total += effect["amount"]
    return total


def supply_without_luxuries(city, env):
    """The city's amenities from columns and effects alone."""
    return column_supply(city) + effect_supply(city, env)


def luxury_shares(player, env):
    """City id -> the luxuries assigned to that city (absent = 0), for every
    city of `player` at once (design "v3 fixes" L7): luxuries in config
    order, each to the `LUXURY_CITIES` cities with the largest current
    deficit -- `need` minus the supply without luxuries minus the luxuries
    already assigned in this computation -- ties by city id. Computed fresh on
    every call; the one place luxuries are assigned."""
    luxuries = accessible_resources(player, env, "luxury")
    if not luxuries or not LUXURY_CITIES:
        return {}
    cities = sorted(player.cities, key=lambda c: c.city_id)
    deficit = {c.city_id: need(c) - supply_without_luxuries(c, env) for c in cities}
    shares = {}
    for _ in luxuries:
        order = sorted(deficit, key=lambda city_id: (-deficit[city_id], city_id))
        for city_id in order[:LUXURY_CITIES]:
            shares[city_id] = shares.get(city_id, 0) + 1
            deficit[city_id] -= 1
    return shares


def supply(city, env):
    """Everything the city has to keep its citizens content: columns, effects
    and its luxury share."""
    return supply_without_luxuries(city, env) + luxury_shares(city.player, env).get(city.city_id, 0)


def surplus(city, env):
    """`supply - need`: positive is content or better, negative is unrest."""
    return supply(city, env) - need(city)


def surpluses(player, env):
    """City id -> `surplus` for every city of `player`, in city-id order, from
    one luxury assignment (what the round-end stats read; each value equals
    `surplus(city, env)`)."""
    shares = luxury_shares(player, env)
    return {c.city_id: supply_without_luxuries(c, env) + shares.get(c.city_id, 0) - need(c)
            for c in sorted(player.cities, key=lambda c: c.city_id)}


# --- Bands --------------------------------------------------------------------------


def band_row(amount):
    """The band of a surplus: the first of BANDS whose min `amount` reaches,
    the last row when it reaches none (the last row catches every deficit)."""
    for row in BANDS:
        if amount >= row.min:
            return row
    return BANDS[-1]


def band(city, env):
    """`(yield_percent, growth_percent, loyalty_delta)` of the city's
    surplus band."""
    row = band_row(surplus(city, env))
    return row.yield_percent, row.growth_percent, row.loyalty


def yield_percent(city, env):
    """Percent added to (or, negative, taken from) the city's science,
    culture, gold, faith and production (read by `city_yield` and
    `City.calculate_production`)."""
    return band(city, env)[0]


def growth_percent(city, env):
    """Percent of its growth the city keeps (read by
    `City.growth_bucket_gain`)."""
    return band(city, env)[1]


def loyalty_term(city, env):
    """What the city's amenity band adds to its loyalty each round (the term
    `loyalty.loyalty_delta` adds)."""
    return band(city, env)[2]
