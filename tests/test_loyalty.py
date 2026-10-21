"""Loyalty (issue #116 P7, docs/progression_design.md §8, "v2 fixes" -- Loyalty
arithmetic, Flips, captures and `set_owner`, Turn order -- and the §14 rows
"Loyalty: ..." and "After N rounds of play, reset(seed) ...").

Every test names the property it protects and the change that must break it.
Pressures, ranges, weights, sources and bands are read from `game/loyalty.py`,
the unit and district registries and the parsed effects, never restated as
config numbers -- except the design's worked drift examples, which pin the
arithmetic under explicitly patched Civ 6 constants. No test pins which
buildings, districts, policies or wonders carry loyalty, or how many.

Boards are flat Plains rows (row 4 of an 8-row board); along one row the
canonical hex distance between two cities is their column difference.
Cities are created through `GameEnvironment.create_city`; the Palace it grants
a player's first city is stripped unless the test is about the Palace, so a
delta is exactly the terms the test names.
"""

import pytest

from civulator import district_model, research_model, unit_model
from civulator.effects import KIND_LOYALTY, effects_of
from civulator.game import loyalty
from civulator.game.districts import District, completed_wonder_city, district_spec
from civulator.game.environment import GameEnvironment
from civulator.game.loyalty import (
    BANDS,
    band,
    drift,
    growth_share,
    largest_foreign_presser,
    loyalty_delta,
    loyalty_percent,
    parse_bands,
    parse_loyalty,
    pressure,
)
from civulator.game.trade import DURATION_TURNS, TradeRoute
from civulator.game.yields import city_yield
from civulator.training.trainer import determine_winner
from civulator.unit_model import CAPITAL_BUILDING, POOL_YIELDS
from civulator.config import CFG

from conftest import grant_civic, stand, synthetic_government
from test_determinism import episode_fingerprint

ROW = 4


def flat(m=40, players=2, seed=None, terrain="Plains"):
    """An 8 x `m` board of flat `terrain` with `players` seats and no city."""
    env = GameEnvironment(8, m, num_players=players, map_type="basic", seed=seed)
    for i in range(env.n):
        for j in range(env.m):
            env.map.tiles[i, j].set_layers(terrain, map_ref=env.map)
    return env


def city(env, seat, col, population=1, palace=False):
    """A city of seat `seat` at (ROW, col) with `population` citizens; the
    granted Palace is stripped unless `palace`."""
    made = env.create_city(env.players[seat], (ROW, col), f"S{seat}@{col}")
    made.population = population
    if not palace and CAPITAL_BUILDING in made.buildings:
        made.buildings.remove(CAPITAL_BUILDING)
    made.assign_tiles(env)
    return made


def put_district(env, owner, district_type, col_offset=2, complete=True):
    """Fixture only: link a District by hand two tiles east of its city."""
    r, c = owner.coordinates
    pos = (r, (c + col_offset) % env.m)
    district = District(district_type, owner.city_id, pos, complete=complete, cost=10)
    env.map.get_tile(pos).district = district
    owner.districts.append(district)
    return district


def unit_of_class(cls):
    """A unit type of combat class `cls`, from the unit tables."""
    return next(u for u in sorted(unit_model.UNIT_NAMES) if unit_model.COMBAT_CLASS[u] == cls)


def fighter():
    """A unit type of a fighting class (any: the garrison test is the class)."""
    return next(u for u in sorted(unit_model.UNIT_NAMES)
                if unit_model.COMBAT_CLASS[u] in unit_model.FIGHTING_CLASSES)


def raider(env, seat, coordinates):
    """A unit of seat `seat` that can take a city at 0 health."""
    unit = stand(env, unit_of_class("melee"), seat, coordinates)
    assert unit.can_capture_city()
    return unit


def play_round(env):
    for _ in range(len(env.players)):
        env.next_turn()


# --- (a) pressure ------------------------------------------------------------------


def test_a_city_presses_itself_for_its_owner_at_distance_zero():
    """A lone city's own pressure is population * CITIZEN_WEIGHT (distance
    0, the heaviest weight) and no other player presses it. Breaks if the
    city is left out of its own owner's sum or weighted by a distance."""
    env = flat()
    home = city(env, 0, 10, population=3)
    assert pressure(home, 0, env) == 3 * loyalty.CITIZEN_WEIGHT
    assert pressure(home, 1, env) == 0


@pytest.mark.parametrize("d", [1, 4, 7])
def test_pressure_falls_by_one_weight_step_per_tile(d):
    """A city at canonical distance d presses with population *
    (CITIZEN_WEIGHT - d), and a player's cities in range sum. Breaks if the
    falloff is not linear in the hex distance or a player's second city is
    dropped."""
    assert d <= loyalty.RANGE
    env = flat()
    target = city(env, 0, 10)
    near = city(env, 1, 10 + d, population=4)
    assert env.map.distance_function(near.coordinates, target.coordinates) == d
    assert pressure(target, 1, env) == 4 * (loyalty.CITIZEN_WEIGHT - d)
    second = city(env, 1, 10 - d, population=2)
    assert pressure(target, 1, env) == (4 + 2) * (loyalty.CITIZEN_WEIGHT - d)
    assert pressure(target, 0, env) == loyalty.CITIZEN_WEIGHT, "only the city itself"
    assert second.player is near.player


@pytest.mark.parametrize("reach", [None, 4])
def test_the_range_cutoff_is_inclusive(monkeypatch, reach):
    """A city exactly RANGE away presses; one RANGE + 1 away does not --
    for the configured range and for a patched shorter one, so the cutoff
    is the range test and not the weight reaching zero. Breaks if the range
    is exclusive, ignored, or measured by anything but the canonical
    distance."""
    if reach is not None:
        monkeypatch.setattr(loyalty, "RANGE", reach)
    r = loyalty.RANGE
    env = flat(m=2 * (r + 1) + 4)
    target = city(env, 0, 0)
    inside = city(env, 1, r, population=2)
    outside = city(env, 1, env.m - (r + 1), population=5)
    assert env.map.distance_function(inside.coordinates, target.coordinates) == r
    assert env.map.distance_function(outside.coordinates, target.coordinates) == r + 1
    assert pressure(target, 1, env) == 2 * (loyalty.CITIZEN_WEIGHT - r)


def test_foreign_pressure_sums_every_other_living_player_and_skips_the_dead():
    """`foreign` in the drift is the sum over every other living player:
    with two rivals the delta is drift(own, p1 + p2); once one is dead its
    cities press no more. Breaks if only the largest rival counts, the
    owner is counted as foreign, or a dead player keeps pressing."""
    env = flat(players=3)
    target = city(env, 0, 10)
    city(env, 1, 13, population=3)
    rival = city(env, 2, 6, population=2)
    own = pressure(target, 0, env)
    p1, p2 = pressure(target, 1, env), pressure(target, 2, env)
    assert p1 > 0 and p2 > 0
    assert loyalty_delta(target, env) == drift(own, p1 + p2)
    env.players[2].is_dead = True
    assert pressure(target, 2, env) == 0
    assert loyalty_delta(target, env) == drift(own, p1)
    assert rival.player.is_dead


# --- (b) drift ----------------------------------------------------------------------


@pytest.fixture
def civ6_drift(monkeypatch):
    """Civ 6's constants, explicitly: 10 * (D - F) / (min + 0.5), cap 20."""
    monkeypatch.setattr(loyalty, "DRIFT_GAIN", 10)
    monkeypatch.setattr(loyalty, "DRIFT_CAP", 20)


@pytest.mark.parametrize("own, foreign, expected", [
    (31, 45, -4),    # the wiki's worked example, -4.4: truncated toward zero, not floored to -5
    (45, 31, 4),
    (10, 30, -19),   # the design's Duel example
    (0, 0, 0),
    (12, 0, 20),     # alone: capped
    (0, 12, -20),
    (100, 99, 0),    # near parity the quotient truncates to 0
])
def test_drift_truncates_toward_zero_and_clamps(civ6_drift, own, foreign, expected):
    """drift = sign * (20 * |own - foreign| // (2 * min + 1)), clamped to
    +-20 (design "v2 fixes", Loyalty arithmetic). Breaks if the division
    floors negative values, the cap is lost, or the min term changes."""
    assert drift(own, foreign) == expected


def test_the_design_duel_example_end_to_end(civ6_drift):
    """A population-1 city five tiles from a population-6 rival with nothing
    else in range drifts -19 (own 10, foreign 30), and its loyalty moves by
    exactly that at round end. Breaks if pressure, drift or the phase
    disagree with the design's worked example."""
    assert loyalty.CITIZEN_WEIGHT == 10, "the example is stated for Civ 6's 10 % per tile"
    env = flat()
    weak = city(env, 0, 10)
    city(env, 1, 15, population=6)
    assert (pressure(weak, 0, env), pressure(weak, 1, env)) == (10, 30)
    weak.loyalty = 60
    env._loyalty_phase()
    assert weak.loyalty == 60 - 19


@pytest.mark.parametrize("start, delta, expected", [
    ("max", 5, "max"), ("max", -5, "max-5"), (3, -5, "min"), (3, 5, 8),
])
def test_loyalty_is_clamped_to_its_scale_after_the_delta(monkeypatch, start, delta, expected):
    """The phase sets loyalty to clamp(loyalty + delta): a delta past either
    end stops at MAXIMUM / LOYALTY_MIN, one inside the scale applies in
    full. The city is alone, so no flip follows. Breaks if the clamp is
    applied before the delta, or not at all."""
    named = {"max": loyalty.MAXIMUM, "max-5": loyalty.MAXIMUM - 5, "min": loyalty.LOYALTY_MIN}
    env = flat()
    lone = city(env, 0, 0)
    lone.loyalty = named.get(start, start)
    monkeypatch.setattr(loyalty, "loyalty_delta", lambda c, e: delta)
    env._loyalty_phase()
    assert lone.loyalty == named.get(expected, expected)
    assert lone.player is env.players[0]


# --- (c) sources --------------------------------------------------------------------


def test_a_garrison_is_a_fighting_unit_of_the_owner_on_the_centre():
    """A unit of a fighting class on the centre adds exactly GARRISON; a
    civilian or a support unit there adds nothing, nor does a fighter on the
    next tile. Breaks if any unit counts as a garrison, or the class test
    is replaced by a name list."""
    env = flat()
    home = city(env, 0, 10)
    base = loyalty_delta(home, env)
    for cls in ("civilian", "support"):
        unit = stand(env, unit_of_class(cls), 0, home.coordinates)
        assert loyalty_delta(home, env) == base, cls
        env.delete_unit(unit)
    stand(env, fighter(), 0, (ROW, 11))
    assert loyalty_delta(home, env) == base, "next door is no garrison"
    stand(env, fighter(), 0, home.coordinates)
    assert loyalty_delta(home, env) == base + loyalty.GARRISON


def test_every_building_loyalty_column_adds_exactly_its_points():
    """Each building with a `loyalty` column adds exactly that many points
    to its city's delta, and together they add their sum. Breaks if a
    column is read in tenths, read for the wrong city, or not at all."""
    assert unit_model.BUILDING_LOYALTY, "fixture: some building declares loyalty"
    env = flat()
    home = city(env, 0, 10)
    base = loyalty_delta(home, env)
    for building, points in sorted(unit_model.BUILDING_LOYALTY.items()):
        home.buildings.append(building)
        assert loyalty_delta(home, env) == base + points, building
        home.buildings.remove(building)
    home.buildings.extend(sorted(unit_model.BUILDING_LOYALTY))
    assert loyalty_delta(home, env) == base + sum(unit_model.BUILDING_LOYALTY.values())


def test_a_district_loyalty_column_counts_once_the_district_is_complete():
    """A district with a `loyalty` column adds exactly it when complete and
    nothing while placed but unfinished. Breaks if an incomplete district
    counts or the column is ignored."""
    name = next(n for n, s in district_model.DISTRICTS.items() if s.loyalty)
    env = flat()
    home = city(env, 0, 10)
    base = loyalty_delta(home, env)
    district = put_district(env, home, name, complete=False)
    assert loyalty_delta(home, env) == base
    district.complete = True
    assert loyalty_delta(home, env) == base + district_spec(name).loyalty


def _palace_loyalty_entries():
    return [e for e in effects_of("building", CAPITAL_BUILDING)
            if e.kind == KIND_LOYALTY and e["per_population"]]


def test_the_palace_adds_its_amount_per_citizen_in_its_own_city_only():
    """The Palace's `per_population` loyalty entry adds amount * population
    to its city -- one more per citizen -- and nothing to another city of
    the same owner. Breaks if `per_population` is ignored, or a city-scoped
    entry leaks into the owner's other cities."""
    entries = _palace_loyalty_entries()
    assert entries, "fixture: the Palace has a per-citizen loyalty entry"
    per_citizen = sum(e["amount"] for e in entries)
    env = flat()
    capital = city(env, 0, 0, population=1, palace=True)
    other = city(env, 0, 20, population=1)
    base_capital = loyalty_delta(capital, env)
    base_other = loyalty_delta(other, env)
    capital.population, other.population = 4, 4
    # Alone, drift stays at its cap whatever the population.
    assert loyalty_delta(capital, env) - base_capital == 3 * per_citizen
    assert loyalty_delta(other, env) == base_other
    capital.buildings.remove(CAPITAL_BUILDING)
    assert loyalty_delta(capital, env) == base_other


def _garrison_card():
    return next(n for n, p in sorted(research_model.POLICIES.items())
                if any(e.kind == KIND_LOYALTY and e["requires_garrison"]
                       for e in effects_of("policy", n)))


def test_a_garrison_card_adds_its_amount_only_where_a_garrison_stands(monkeypatch):
    """A slotted policy whose loyalty entry `requires_garrison` adds its
    amount to a garrisoned city (on top of the inherent GARRISON) and
    nothing to an ungarrisoned one of the same player. Breaks if the
    condition is dropped or read from the wrong city."""
    name = _garrison_card()
    amount = sum(e["amount"] for e in effects_of("policy", name) if e.kind == KIND_LOYALTY)
    env = flat()
    player = env.players[0]
    held = city(env, 0, 0)
    bare = city(env, 0, 20)
    stand(env, fighter(), 0, held.coordinates)
    before = (loyalty_delta(held, env), loyalty_delta(bare, env))
    synthetic_government(monkeypatch, "Loyal Test Government", {"wildcard": 1})
    grant_civic(player, research_model.CIVIC_ORDER[0], research_model.POLICIES[name].requires_civic)
    assert env.set_government(player, "Loyal Test Government")
    assert env.set_policies(player, [name])
    assert loyalty_delta(held, env) == before[0] + amount
    assert loyalty_delta(bare, env) == before[1]


def _ranged_wonder():
    for name in district_model.DISTRICTS:
        entries = [e for e in effects_of("district", name)
                   if e.kind == KIND_LOYALTY and e["range"] > 0]
        if entries:
            return name, entries
    raise AssertionError("fixture: some district has a ranged loyalty effect")


def test_a_ranged_effect_reaches_own_cities_within_its_range_only():
    """A complete district's ranged loyalty entry adds its amount to every
    city of its owner within `range` of the city holding it (that city
    included), nothing to an own city one tile further, and nothing to
    another player's city in range. Breaks if the range is measured from
    the wrong city, is exclusive, or reaches foreign cities."""
    name, entries = _ranged_wonder()
    reach = entries[0]["range"]
    amount = sum(e["amount"] for e in entries)
    env = flat(m=4 * reach + 8)
    holder = city(env, 0, 0)
    inside = city(env, 0, reach)
    beyond = city(env, 0, env.m - (reach + 1))
    foreign = city(env, 1, 2 * reach)
    assert env.map.distance_function(foreign.coordinates, holder.coordinates) > reach
    foreign_near = city(env, 1, env.m - 3)  # within reach of the holder
    assert env.map.distance_function(foreign_near.coordinates, holder.coordinates) <= reach
    district = put_district(env, holder, name, col_offset=2, complete=False)
    before = {c.city_id: loyalty_delta(c, env) for c in (holder, inside, beyond, foreign_near)}
    district.complete = True
    after = {c.city_id: loyalty_delta(c, env) for c in (holder, inside, beyond, foreign_near)}
    assert after[holder.city_id] - before[holder.city_id] == amount
    assert after[inside.city_id] - before[inside.city_id] == amount
    assert after[beyond.city_id] == before[beyond.city_id]
    assert after[foreign_near.city_id] == before[foreign_near.city_id]
    assert env.map.distance_function(beyond.coordinates, holder.coordinates) == reach + 1


# --- (d) bands -------------------------------------------------------------------


def test_every_loyalty_falls_into_the_first_band_it_reaches():
    """For every loyalty on the scale the band is the first row whose min
    it reaches, and the last row below every min (loyalty 0). Breaks if the
    bands are searched in another order or loyalty 0 finds no band."""
    env = flat()
    home = city(env, 0, 10)
    for value in range(loyalty.LOYALTY_MIN, loyalty.MAXIMUM + 1):
        home.loyalty = value
        expected = next((row for row in BANDS if value >= row.min), BANDS[-1])
        assert band(home) == expected, value
        assert loyalty_percent(home) == expected.yield_percent
        assert growth_share(home) == expected.growth_share
    home.loyalty = 0
    assert band(home) == BANDS[-1]


def _band_loyalties():
    return [row.min for row in BANDS] + [0]


@pytest.mark.parametrize("value", _band_loyalties())
def test_bands_scale_pool_yields_and_production_but_not_food(value):
    """At each band the four pool yields are the full value times the
    band's percent (one floor), production is the raised production times
    it with the floor of 1, and food is untouched. Breaks if loyalty is
    applied twice, to food, before the production-percent effects, or
    without the floor of 1."""
    env = flat()
    home = city(env, 0, 10, population=4, palace=True)
    home.loyalty = loyalty.MAXIMUM
    assert loyalty_percent(home) == 100, "fixture: the top band keeps everything"
    full = {y: city_yield(home, y) for y in (*POOL_YIELDS, "food")}
    production = city_yield(home, "production") * (100 + home.production_percent()) // 100
    assert production > 1
    home.loyalty = value
    percent = loyalty_percent(home)
    for y in POOL_YIELDS:
        assert city_yield(home, y) == full[y] * percent // 100, y
    assert city_yield(home, "food") == full["food"]
    assert home.calculate_production(env) == max(1, production * percent // 100)


@pytest.mark.parametrize("value", _band_loyalties())
def test_bands_scale_growth_exactly(value):
    """The growth bucket gains food_net * housing_percent * growth_share *
    (100 + growth_percent) // 10000 at every band. Breaks if the share is
    left out, applied to starvation, or compounded with another floor."""
    env = flat()
    home = city(env, 0, 10)
    home.loyalty = value
    share = growth_share(home)
    assert home.growth_bucket_gain(7, 100) == 7 * 100 * share * 100 // 10000
    assert home.growth_bucket_gain(3, 25) == 3 * 25 * share * 100 // 10000


def test_a_zero_growth_share_blocks_growth_even_with_a_full_bucket():
    """A city in a band with growth share 0 does not grow even when its
    bucket already holds the threshold (Civ 6 Unrest: no growth), and keeps
    the bucket; back in a growing band it grows. Breaks if only the bucket
    gain is scaled and a full bucket still grows the city."""
    assert BANDS[-1].growth_share == 0, "fixture: the last band blocks growth"
    env = flat()
    home = city(env, 0, 10, population=1)
    home.loyalty = 0
    home.food_surplus = 100 * home.get_growth_threshold()
    env.turn_counter += 1
    home.process_turn(env)
    assert home.population == 1
    assert home.food_surplus >= 100 * home.get_growth_threshold() - 200 * home.population
    home.loyalty = loyalty.MAXIMUM
    home.food_surplus = 100 * home.get_growth_threshold()
    env.turn_counter += 1
    home.process_turn(env)
    assert home.population == 2


# --- (e) flips ----------------------------------------------------------------------


def _flip_board():
    """Seat 0's weak city (population 1, loyalty 1) five tiles from seat 1's
    population-6 capital, garrisoned by a fighter of seat 0, holding a
    complete district and a complete wonder, running a trade route to the
    rival; seat 0 keeps a home city far away. Its delta is negative enough
    that one phase takes it to 0."""
    env = flat(m=48)
    home = city(env, 0, 40, palace=True)
    weak = city(env, 0, 10)
    rival = city(env, 1, 15, population=6)
    weak.loyalty = 1
    garrison = stand(env, fighter(), 0, weak.coordinates)
    district_type = next(n for n, s in district_model.DISTRICTS.items()
                         if s.kind == district_model.KIND_DISTRICT)
    wonder_type = next(n for n, s in district_model.DISTRICTS.items()
                       if s.kind == district_model.KIND_WONDER)
    district = put_district(env, weak, district_type, col_offset=-2)
    wonder = put_district(env, weak, wonder_type, col_offset=-1)
    route = TradeRoute(weak.city_id, rival.city_id, 0, DURATION_TURNS)
    env.players[0].routes.append(route)
    assert loyalty_delta(weak, env) < -1
    return env, home, weak, rival, garrison, (district, wonder), route


def test_a_city_at_zero_flips_to_the_largest_foreign_presser_through_set_owner():
    """At 0 the city joins the player pressing it hardest: its old owner's
    units on the centre are deleted and counted as losses, its loyalty is
    `captured`, its tiles, districts and wonders go with it, its routes
    end, and the flip is counted in cities_flipped_* -- never in
    cities_captured. Breaks if the flip bypasses `City.set_owner`, leaves
    the garrison, or is booked as a capture."""
    env, home, weak, rival, garrison, (district, wonder), route = _flip_board()
    old, new = env.players
    tiles = sorted(env.map.tiles_of_city(weak.city_id))
    owned = (env.map.owned_tile_count(0), env.map.owned_tile_count(1))
    losses = env.episode_stats[0]["losses"]
    env._loyalty_phase()
    assert weak.player is new and weak in new.cities and weak not in old.cities
    assert weak.loyalty == loyalty.CAPTURED
    assert garrison not in old.units and garrison not in env.get_units_at(weak.coordinates)
    assert env.episode_stats[0]["losses"] == losses + 1
    assert sorted(env.map.tiles_of_city(weak.city_id)) == tiles
    assert (env.map.owned_tile_count(0), env.map.owned_tile_count(1)) == (
        owned[0] - len(tiles), owned[1] + len(tiles))
    assert weak.districts == [district, wonder]
    assert completed_wonder_city(env, wonder.type) is weak
    assert route not in old.routes
    assert env.episode_stats[0]["cities_flipped_out"] == 1
    assert env.episode_stats[1]["cities_flipped_in"] == 1
    assert env.episode_stats[1]["cities_captured"] == 0
    assert home.player is old and home.loyalty > 0


def test_no_flip_without_a_foreign_presser(monkeypatch):
    """A city driven to 0 that no other player presses stays with its owner
    at 0; one that is pressed flips. Breaks if a city flips to nobody, to a
    player exerting no pressure, or the flip ignores the presser test."""
    env = flat(players=3)
    alone = city(env, 0, 0)
    pressed = city(env, 0, 20)
    city(env, 2, 24, population=2)
    monkeypatch.setattr(loyalty, "loyalty_delta", lambda c, e: -loyalty.MAXIMUM)
    env._loyalty_phase()
    assert largest_foreign_presser(alone, env) is None
    assert alone.player is env.players[0] and alone.loyalty == loyalty.LOYALTY_MIN
    assert pressed.player is env.players[2]


def test_the_largest_presser_wins_and_ties_go_to_the_lower_index():
    """With two rivals the larger pressure wins; at equal pressure the
    lower player index. Breaks if the presser is the first city found, the
    nearest city, or a tie is broken by anything else."""
    env = flat(players=3)
    target = city(env, 0, 20)
    a = city(env, 1, 24, population=2)
    b = city(env, 2, 16, population=3)
    assert largest_foreign_presser(target, env) is env.players[2]
    b.population = 2
    assert pressure(target, 1, env) == pressure(target, 2, env)
    assert largest_foreign_presser(target, env) is env.players[1]
    assert a.player is env.players[1]


# --- (f) the phase reads the state at its start --------------------------------------


def _phase_order_board(a_first):
    """Seat 0's A and B with seats 1 and 2 around them (the numbers are in
    the test docstrings). `a_first`: A is created first (the lower id)."""
    env = flat(players=3)
    city(env, 1, 10, population=4)
    made = {}
    for name, col, pop in ((("A", 18, 2), ("B", 14, 1)) if a_first
                           else (("B", 14, 1), ("A", 18, 2))):
        made[name] = city(env, 0, col, population=pop)
    city(env, 2, 22, population=8)
    return env, made["A"], made["B"]


@pytest.mark.parametrize("a_first", [True, False])
def test_every_delta_comes_from_the_state_at_phase_start(a_first):
    """A flips to seat 2 in this phase; B, its neighbour, does not. B's new
    loyalty is its loyalty plus the delta computed before the phase, with A
    still seat 0's -- whether A has the lower id or not. Breaks if flips are
    resolved city by city while deltas are still being computed (then A's
    citizens would already press B as seat 2's)."""
    env, a, b = _phase_order_board(a_first)
    a.loyalty, b.loyalty = 1, 30
    expected = loyalty.clamp(b.loyalty + loyalty_delta(b, env))
    env._loyalty_phase()
    assert a.player is env.players[2], "fixture: A flips"
    assert b.player is env.players[0]
    assert b.loyalty == expected


@pytest.mark.parametrize("a_first", [True, False])
def test_the_flip_target_comes_from_the_state_at_phase_start(a_first):
    """A and B both reach 0. B's largest presser at phase start is seat 1
    (24 against seat 2's 16); after A's flip seat 2 would press it harder
    (16 + A's 12 = 28). B goes to seat 1 whatever the id order. Breaks if a
    flip's target is read after earlier flips of the same phase."""
    env, a, b = _phase_order_board(a_first)
    a.loyalty, b.loyalty = 1, 1
    assert largest_foreign_presser(b, env) is env.players[1]
    env._loyalty_phase()
    assert a.player is env.players[2]
    assert b.player is env.players[1]


@pytest.mark.parametrize("target_seat", [0, 1])
@pytest.mark.parametrize("late", [False, True])
def test_a_city_founded_late_in_the_round_counts_like_one_standing_all_round(late,
                                                                            target_seat):
    """Seat 1 (the last seat) founds a city three tiles from a target city
    held by either seat, which a population-6 city of the other seat also
    presses: whether the new city stands from the start of the round or is
    founded during seat 1's own turn, the target's loyalty does not move
    before the round ends and then moves by the delta of the board at the
    end of the round, the new city included. Breaks if loyalty resolves
    during a player's turn (seat 1's own city would be updated before its
    new neighbour exists), at the start of the round, or from anything but
    the board at phase start."""
    env = flat()
    target = city(env, target_seat, 10)
    city(env, 1 - target_seat, 15, population=6)
    target.loyalty = 60
    if not late:
        city(env, 1, 7)
    env.next_turn()                          # seat 0 -> seat 1, no round end
    assert target.loyalty == 60, "loyalty moves only at round end"
    if late:
        city(env, 1, 7)
    expected = loyalty.clamp(60 + loyalty_delta(target, env))
    env.next_turn()                          # seat 1 -> seat 0: the round ends
    assert target.loyalty == expected
    del env.city_by_id[max(env.city_by_id)]  # what the board would say without it
    assert loyalty.clamp(60 + loyalty_delta(target, env)) != expected, "fixture: it presses"


# --- (g) determinism and reset ------------------------------------------------------


def _loyalty_history(seed, rounds=30):
    """Seat 0's weak city five tiles from seat 1's population-6 capital on
    Grassland (the capital does not starve): it flips within a few rounds,
    then recovers as seat 1's."""
    env = flat(m=32, seed=seed, terrain="Grassland")
    city(env, 0, 0, palace=True)
    weak = city(env, 0, 10)
    city(env, 1, 15, population=6, palace=True)
    weak.loyalty = 20
    history = []
    for _ in range(rounds):
        play_round(env)
        history.append(tuple((c.city_id, c.player.player_index, c.loyalty, c.population)
                             for c in (env.city_by_id[i] for i in sorted(env.city_by_id))))
    flips = [(s["cities_flipped_out"], s["cities_flipped_in"])
             for s in env.episode_stats.values()]
    return history, flips


def test_same_seed_gives_identical_loyalty_histories_and_flips():
    """Two same-seed games give identical per-round loyalty, owners and
    flips (a flip happens). Breaks if the phase depends on set or dict
    iteration order, or draws randomness."""
    first = _loyalty_history(seed=5)
    assert any(out for out, _ in first[1]), "fixture: a city flips"
    assert _loyalty_history(seed=5) == first


def test_reset_restores_every_city_to_founded_loyalty():
    """After rounds of play with every loyalty dirtied, reset(seed) gives
    exactly what a fresh environment's reset(seed) gives (the reset-identity
    fingerprint reads every City field, loyalty included), and every city
    stands at `founded`. Breaks if loyalty state survives a reset."""
    seed = 31
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for _ in range(2 * 4):
        env.next_turn()
    for c in env.city_by_id.values():
        c.loyalty = 7
    env.reset(seed=seed)
    fresh = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    assert episode_fingerprint(env) == episode_fingerprint(fresh)
    assert all(c.loyalty == loyalty.FOUNDED for c in env.city_by_id.values())
    assert env.city_by_id, "fixture: reset founds capitals"


def test_flip_stats_are_declared_ints_from_the_first_turn():
    """cities_flipped_out / cities_flipped_in exist for every seat as ints
    before anything happens. Breaks if a key is created lazily."""
    env = flat(players=3)
    for stats in env.episode_stats.values():
        assert type(stats["cities_flipped_out"]) is int
        assert type(stats["cities_flipped_in"]) is int


# --- (h) config validation -------------------------------------------------------------


@pytest.mark.parametrize("bands", [
    "bands",                                        # not a list
    [],                                             # empty
    [[76, 100]],                                    # a row of two
    [[76, 100, 100, 1]],                            # a row of four
    [[76.0, 100, 100]],                             # a float min
    [[76, 100, 100.5]],                             # a float share
    [[76, True, 100]],                              # a bool
    [[76, 100, 100], [76, 75, 75]],                 # equal mins
    [[26, 50, 25], [51, 75, 75]],                   # ascending
    [[76, -1, 100]],                                # negative percent
    [[176, 100, 100]],                              # above the scale
])
def test_malformed_bands_raise(bands):
    """The bands table is a non-empty list of [min, yield_percent,
    growth_share] int rows within the scale, mins strictly descending.
    Breaks if a mis-shaped or mis-ordered table is accepted (it would
    silently change which band wins)."""
    with pytest.raises(ValueError):
        parse_bands(bands, loyalty.MAXIMUM)


def _loyalty_cfg(**changes):
    cfg = dict(CFG["loyalty"])
    for key, value in changes.items():
        if value is None:
            cfg.pop(key)
        else:
            cfg[key] = value
    return cfg


@pytest.mark.parametrize("changes", [
    {"founded": None},                              # missing key
    {"bonus": 3},                                   # unknown key
    {"founded": 101},                               # above the maximum
    {"captured": -1},
    {"citizen_weight": 9, "range": 9},              # the range edge would weigh 0
    {"garrison": 2.5},
    {"drift_cap": -1},
])
def test_malformed_loyalty_table_raises(changes):
    """`[loyalty]` has exactly its keys, ints, start values on the scale,
    and a citizen weight above the range. Breaks if junk is accepted."""
    with pytest.raises(ValueError):
        parse_loyalty(_loyalty_cfg(**changes))


def test_the_configured_table_parses_with_descending_bands():
    """The live table parses; its bands are strictly descending and start
    within the scale. Breaks if the shipped config fails its own rules."""
    rules = parse_loyalty(CFG["loyalty"])
    mins = [row.min for row in rules.bands]
    assert mins == sorted(mins, reverse=True) and len(set(mins)) == len(mins)
    assert loyalty.LOYALTY_MIN <= rules.captured <= rules.founded <= rules.maximum


# --- (i) capture ------------------------------------------------------------------------


def test_a_captured_city_starts_at_captured_and_recovers_when_alone():
    """A city taken by force starts at `captured` (the shared `set_owner`
    reset), and with no other city in range it climbs by its delta every
    round until it reaches the maximum. Breaks if capture keeps the old
    loyalty or the recovery is not the phase's delta."""
    env = flat(m=48)
    victim = city(env, 0, 0, population=2)
    city(env, 1, 24)
    victim.health = 0
    env._capture_city(raider(env, 1, (ROW, 1)), victim)
    assert victim.player is env.players[1]
    assert victim.loyalty == loyalty.CAPTURED
    previous = victim.loyalty
    for _ in range(loyalty.MAXIMUM):
        delta = loyalty_delta(victim, env)
        env._loyalty_phase()
        assert victim.loyalty == loyalty.clamp(previous + delta)
        if victim.loyalty == loyalty.MAXIMUM:
            break
        assert victim.loyalty > previous
        previous = victim.loyalty
    assert victim.loyalty == loyalty.MAXIMUM


# --- (j) elimination ----------------------------------------------------------------------


@pytest.mark.parametrize("door", ["capture", "flip"])
def test_losing_the_last_city_by_flip_eliminates_as_a_capture_does(door):
    """Seat 0 loses its only city, by capture during seat 1's turn or by a
    flip at that round's end: either way it is still alive (and the game
    not over) on its next turn, which it plays without a city; its end of
    turn kills it, deletes its units and ends the game with seat 1 the
    winner. Breaks if a flip eliminates differently from a capture (at once,
    never, or without ending the game)."""
    env = flat()
    weak = city(env, 0, 10)
    rival = city(env, 1, 15, population=6)
    straggler = stand(env, fighter(), 0, (0, 30))
    weak.loyalty = 1 if door == "flip" else loyalty.MAXIMUM
    seat0, seat1 = env.players
    seat0.gold = 10 ** 6                              # no bankruptcy disbands the straggler
    env.next_turn()                                   # seat 0 -> seat 1
    if door == "capture":
        weak.health = 0
        env._capture_city(raider(env, 1, (ROW, 11)), weak)
    env.next_turn()                                   # the round ends -> seat 0
    assert weak.player is seat1 and seat0.cities == []
    assert not seat0.is_dead and not env.done
    assert straggler in seat0.units
    env.next_turn()                                   # seat 0's turn ends
    assert seat0.is_dead and seat0.units == []
    assert env.done
    assert determine_winner(env) == 1
    assert rival.player is seat1


# --- the wiring ---------------------------------------------------------------------------


def test_loyalty_moves_only_in_the_round_end_phase():
    """Inside a round no start or end of a turn moves any loyalty; the wrap
    to seat 0 applies every city's delta -- as computed from the board when
    the round ends -- exactly once. Breaks if loyalty is updated in
    `Player.start_turn` / `end_turn` or twice per round."""
    env = flat()
    a = city(env, 0, 10)
    b = city(env, 1, 15, population=6)
    a.loyalty, b.loyalty = 60, 60
    env.next_turn()                                   # seat 0 -> seat 1
    assert (a.loyalty, b.loyalty) == (60, 60)
    expected = {c.city_id: loyalty.clamp(60 + loyalty_delta(c, env)) for c in (a, b)}
    env.next_turn()                                   # the round ends
    assert {c.city_id: c.loyalty for c in (a, b)} == expected


def test_loyalty_module_names_no_building_district_wonder_or_policy():
    """Every loyalty source is a column or an effect: no configured
    building, district, wonder or policy name appears in game/loyalty.py.
    Breaks if a source is special-cased in code."""
    import inspect

    source = inspect.getsource(loyalty)
    names = (set(unit_model.BUILDING_NAMES) | set(district_model.DISTRICTS)
             | set(research_model.POLICIES))
    assert not [n for n in names if f'"{n}"' in source or f"'{n}'" in source]


def test_loyalty_scales_one_city_without_touching_another():
    """Lowering one city's loyalty changes that city's yields only; a second
    city of the same owner keeps every yield. Breaks if the band is read
    from the owner or from the wrong city."""
    env = flat()
    a = city(env, 0, 0, population=3, palace=True)
    b = city(env, 0, 20, population=3)
    full_a = {y: city_yield(a, y) for y in POOL_YIELDS}
    before = {y: city_yield(b, y) for y in POOL_YIELDS}
    a.loyalty = 0
    assert {y: city_yield(b, y) for y in POOL_YIELDS} == before
    assert {y: city_yield(a, y) for y in POOL_YIELDS} == {
        y: full_a[y] * BANDS[-1].yield_percent // 100 for y in POOL_YIELDS}
