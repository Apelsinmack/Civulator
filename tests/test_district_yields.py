"""Issue #86 D2: district production, yields, Aqueduct housing, capture and
stats (docs/districts_design.md sections 3, 5, 6 and "v3 fixes").

Rules that depend on specific config rows use a synthetic registry, so the
tests do not move when the Civ 6 values are rebalanced.
"""

import pytest

from civulator import district_model
from civulator.agents.build_agent import encode_build_state
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.game import districts as districts_mod
from civulator.game import housing as housing_mod
from civulator.game.city import City
from civulator.game.culture import culture
from civulator.game.districts import YIELD_NAMES, District, district_yields
from civulator.game.environment import GameEnvironment
from civulator.game.housing import housing
from civulator.game.yields import city_yield
from civulator.unit_model import POOL_YIELDS, YIELD_COLUMNS

from conftest import grant_all
from test_districts import DISTRICTS, board, far_site, make_city, neighbours, placeable_type


def synthetic(monkeypatch):
    """Probe: +3 gold per adjacent Marker; Marker: no yield; Flat: flat housing."""
    cfg = {
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Probe": {"production_cost": 10, "adjacency_yield": "gold",
                  "adjacency": [{"amount": 3, "district": ["Marker"]}]},
        "Marker": {"production_cost": 10},
        "Flat": {"production_cost": 10, "housing": 1.5},
    }
    reg = district_model.parse_districts(cfg)
    # Every reader outside district_model goes through districts.district_spec
    # (#116), so patching the registry here reaches housing and yields too.
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    return reg


def synthetic_per_yield(monkeypatch, amount=3):
    """One probe per reportable yield ("Probe <yield>": `amount` per adjacent
    Marker), a second gold probe, and the Marker itself."""
    cfg = {
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Marker": {"production_cost": 10},
        "Second gold": {"production_cost": 10, "adjacency_yield": "gold",
                        "adjacency": [{"amount": 2, "district": ["Marker"]}]},
    }
    for y in YIELD_NAMES:
        cfg[f"Probe {y}"] = {"production_cost": 10, "adjacency_yield": y,
                             "adjacency": [{"amount": amount, "district": ["Marker"]}]}
    reg = district_model.parse_districts(cfg)
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    return reg


def put(env, city, name, pos, complete=True):
    """Fixture only: link a District by hand (synthetic types cannot go
    through place_district)."""
    d = District(name, city.city_id, pos, complete=complete, cost=10)
    env.map.get_tile(pos).district = d
    city.districts.append(d)
    return d


# --- Production ------------------------------------------------------------------


def test_district_completion_goes_through_complete_district(monkeypatch):
    """The production branch finishes a district only through
    GameEnvironment.complete_district (the one place a district finishes;
    #116 P6 hangs one-shot wonder effects there). Breaks if process_turn
    marks a district complete itself."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    assert env.place_district(city, t, far_site(env, city))
    calls = []
    real = env.complete_district
    monkeypatch.setattr(env, "complete_district",
                        lambda c, d: (calls.append((c, d)), real(c, d)))
    city.production = city.districts[0].cost
    env.turn_counter += 1
    city.process_turn(env)
    assert calls == [(city, city.districts[0])]
    assert city.districts[0].complete and city.current_production is None


def test_complete_district_refuses_a_finished_or_foreign_district():
    """complete_district raises for a district already complete or not the
    city's, so nothing can finish twice (a one-shot effect would fire twice).
    Breaks if the guard is dropped."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    other = make_city(env, (3, 12), player_index=1)
    assert env.place_district(city, t, far_site(env, city))
    district = city.districts[0]
    with pytest.raises(ValueError):
        env.complete_district(other, district)
    env.complete_district(city, district)
    assert district.complete
    with pytest.raises(ValueError):
        env.complete_district(city, district)


def test_district_is_paid_from_the_pool_and_completes_exactly_at_its_cost(monkeypatch):
    """A district completes when the pool reaches its locked cost, pays that
    cost (surplus stays) and clears production. Breaks if the cost is
    recomputed, paid early or not deducted."""
    monkeypatch.setattr(City, "calculate_production", lambda self, env: 5)
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    assert env.place_district(city, t, far_site(env, city))
    d = city.districts[0]
    city.production = d.cost - 6          # +5 this turn -> cost - 1: not yet
    env.turn_counter += 1
    city.process_turn(env)
    assert not d.complete and city.current_production is not None
    assert city.production == d.cost - 1
    env.turn_counter += 1
    city.process_turn(env)                # +5 -> cost + 4
    assert d.complete and city.current_production is None
    assert city.production == 4


def test_produce_district_resumes_incomplete_and_refuses_otherwise():
    """produce_district succeeds only for an incomplete placed district of
    that type; unplaced and complete types refuse and change nothing. Breaks
    if it accepts any configured name like a unit, or resumes a finished
    district."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    other = next(n for n in DISTRICTS if n != t)
    assert not city.produce_district(t)               # nothing placed
    assert env.place_district(city, t, far_site(env, city))
    city.produce_unit("Warrior")
    assert city.produce_district(t)
    assert city.current_production == {"type": "district", "district_type": t}
    city.produce_unit("Warrior")
    assert not city.produce_district(other)           # never placed
    city.districts[0].complete = True
    assert not city.produce_district(t)               # complete
    assert city.current_production["type"] == "unit"  # refusals changed nothing


def test_produce_district_resumes_the_oldest_of_several():
    """With several incomplete districts of one type the oldest is resumed
    and completed first. Breaks if the newest or an arbitrary one is picked."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    first = District(t, city.city_id, (0, 0), complete=False, cost=5)
    second = District(t, city.city_id, (0, 1), complete=False, cost=5)
    city.districts.extend([first, second])
    assert city.produce_district(t)
    city.production = 100
    env.turn_counter += 1
    city.process_turn(env)
    assert first.complete and not second.complete


def test_switching_production_away_keeps_the_placed_district():
    """Changing production leaves the placed district and its tile link.
    Breaks if switching production discards the district."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    site = far_site(env, city)
    assert env.place_district(city, t, site)
    city.produce_unit("Warrior")
    assert len(city.districts) == 1
    assert env.map.get_tile(site).district is city.districts[0]


# --- Yields (design section 5) ---------------------------------------------------


def test_yields_count_only_complete_districts_and_follow_the_live_score(monkeypatch):
    """district_yields sums the live adjacency score of COMPLETE districts per
    yield. Breaks if incomplete districts count, or the score is cached."""
    synthetic(monkeypatch)
    env = board()
    city = make_city(env, (3, 4))
    a = (3, 6)
    probe = put(env, city, "Probe", a, complete=False)
    assert district_yields(city)["gold"] == 0                 # incomplete
    probe.complete = True
    assert district_yields(city)["gold"] == 0                 # no Marker yet
    put(env, city, "Marker", neighbours(env, a)[0])
    assert district_yields(city)["gold"] == 3                 # live, no refresh call
    put(env, city, "Marker", neighbours(env, a)[1])
    assert district_yields(city)["gold"] == 6
    assert all(v == 0 for k, v in district_yields(city).items() if k != "gold")


def test_a_complete_district_raises_exactly_its_yield_and_an_incomplete_one_nothing(monkeypatch):
    """INVERTED in #116 P1 (until then: "districts do not change culture or
    production"). For each reportable yield, a complete district yielding it
    raises city_yield of that yield by exactly its adjacency score -- x10 in
    the tenths yields, whole points for production -- and leaves every other
    yield alone; the consumers culture() and calculate_production see the
    same change; an incomplete one changes nothing. Breaks if district
    yields reach the wrong consumer, are double-counted, or count while
    incomplete."""
    synthetic_per_yield(monkeypatch, amount=3)
    for y in YIELD_NAMES:
        env = board()
        city = make_city(env, (3, 4))
        site = (3, 8)
        probe = put(env, city, f"Probe {y}", site, complete=False)
        put(env, city, "Marker", neighbours(env, site)[0])
        assert district_yields(city)[y] == 0
        before = {n: city_yield(city, n) for n in YIELD_COLUMNS}
        consumers = (culture(city), city.calculate_production(env))
        probe.complete = True
        assert district_yields(city)[y] == 3
        gain = 30 if y in POOL_YIELDS else 3
        assert {n: city_yield(city, n) - before[n] for n in YIELD_COLUMNS} == {
            n: (gain if n == y else 0) for n in YIELD_COLUMNS}, y
        assert culture(city) - consumers[0] == (30 if y == "culture" else 0)
        assert city.calculate_production(env) - consumers[1] == (3 if y == "production" else 0)


def test_percent_by_district_scales_exactly_that_districts_contribution(monkeypatch):
    """district_yields(city, percent_by_district) raises each named
    district's score by its percent before summing, floored per district:
    +100 doubles exactly that district's share, the other district's is
    untouched, no mapping changes nothing. Breaks if the percent is applied
    to the summed yield, to every district, or before the per-row floors."""
    synthetic_per_yield(monkeypatch, amount=3)
    env = board()
    city = make_city(env, (3, 4))
    site_a, site_b = (3, 8), (6, 8)
    put(env, city, "Probe gold", site_a)
    put(env, city, "Marker", neighbours(env, site_a)[0])
    put(env, city, "Second gold", site_b)
    put(env, city, "Marker", neighbours(env, site_b)[0])
    assert district_yields(city)["gold"] == 3 + 2
    assert district_yields(city, {})["gold"] == 3 + 2
    assert district_yields(city, {"Probe gold": 100})["gold"] == 6 + 2
    assert district_yields(city, {"Second gold": 100})["gold"] == 3 + 4
    assert district_yields(city, {"Probe gold": 50})["gold"] == 4 + 2   # floor(4.5)


# --- Housing (design section 6) --------------------------------------------------


def _water_adjuster():
    for name, spec in DISTRICTS.items():
        if spec.water_housing_min is not None:
            return name, spec
    pytest.skip("no configured district adjusts water housing")


def test_water_adjusting_district_follows_the_declared_formula(monkeypatch):
    """With a complete water-adjusting district, water becomes
    max(min, water + boost) for fresh, coastal and dry alike (Civ 6 values:
    5 -> 7, 3 -> 6, 2 -> 6); an incomplete one changes nothing. Breaks if the
    formula is per case, hardcoded, or reads incomplete districts."""
    name, spec = _water_adjuster()
    env = board()
    city = make_city(env, (3, 8))
    nb = env.map.get_adjacent_coords(city.coordinates)[0]
    d = District(name, city.city_id, (3, 9), complete=False)
    city.districts.append(d)
    seen = {}
    for case in ("fresh", "coastal", "dry"):
        env.map.get_tile(nb).set_layers("Coast" if case == "coastal" else "Plains",
                                        map_ref=env.map)
        monkeypatch.setattr(env.map, "is_fresh_water", lambda c, case=case: case == "fresh")
        water = housing_mod._water_housing(env.map, city.coordinates)
        d.complete = False
        base = housing(city)
        d.complete = True
        expected = max(spec.water_housing_min, water + spec.water_housing_boost) - water
        assert housing(city) - base == expected, case
        seen[case] = water + expected
    if (spec.water_housing_min, spec.water_housing_boost) == (60, 20):
        assert seen == {"fresh": 70, "coastal": 60, "dry": 60}


def test_a_districts_flat_housing_is_added_only_when_complete(monkeypatch):
    """A district's declared flat `housing` adds exactly that, once complete.
    Breaks if it is ignored, counted while incomplete, or read by name."""
    synthetic(monkeypatch)
    env = board()
    city = make_city(env, (3, 4))
    base = housing(city)
    d = put(env, city, "Flat", (3, 6), complete=False)
    assert housing(city) == base
    d.complete = True
    assert housing(city) == base + 15


# --- Capture and stats -----------------------------------------------------------


def test_capture_keeps_districts_production_and_current_production():
    """A captured city keeps its districts (incomplete included), pool and
    current production unchanged, and can finish the district for its new
    owner. Breaks if set_owner resets, drops or reassigns any of them."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    assert env.place_district(city, t, far_site(env, city))
    city.production = 7
    district, current = city.districts[0], dict(city.current_production)
    city.set_owner(env.players[1])
    assert city.districts == [district] and not district.complete
    assert (city.production, city.current_production) == (7, current)
    city.production = district.cost
    env.turn_counter += 1
    city.process_turn(env)
    assert district.complete


def test_district_stats_are_declared_and_accrue_once_per_round_under_capture(monkeypatch):
    """Every reportable yield has a district_yield_<name> counter; a city that
    changes hands mid-round accrues once that round, to whoever processed it
    first. Breaks if the accrual skips the _culture_round guard."""
    synthetic(monkeypatch)
    env = board()
    names = [y for y in district_model.ACCEPTED_YIELDS if y != "none"]
    for stats in env.episode_stats.values():
        assert all(f"district_yield_{y}" in stats for y in names)
    city = make_city(env, (3, 4))
    put(env, city, "Probe", (3, 6))
    put(env, city, "Marker", neighbours(env, (3, 6))[0])
    env.turn_counter += 1
    city.process_turn(env)
    city.set_owner(env.players[1])
    city.process_turn(env)                       # same round, new owner
    assert env.episode_stats[0]["district_yield_gold"] == 3
    assert env.episode_stats[1]["district_yield_gold"] == 0
    env.turn_counter += 1
    city.process_turn(env)
    assert env.episode_stats[1]["district_yield_gold"] == 3


# --- Build agent -----------------------------------------------------------------


def test_build_state_encoding_refuses_district_production_naming_99():
    """encode_build_state raises NotImplementedError naming #99 for district
    production. Breaks if it falls through to the building branch (KeyError)."""
    t = placeable_type()
    env = board()
    city = make_city(env, (3, 4))
    assert env.place_district(city, t, far_site(env, city))
    state = EnhancedStateEncoder(fog_of_war=False).encode(env, 0)
    with pytest.raises(NotImplementedError, match="#99"):
        encode_build_state(state, city, env)


# --- Determinism -----------------------------------------------------------------


def _play(seed):
    """Placement and completion under fixed actions. Every player knows both
    trees (#116 P4: every district is tech- or civic-gated), which escalates
    district costs ~10x (`game_progress`), so each city is granted the
    production its placed districts cost, once, before the rounds: they then
    complete one per turn, in the order this loop resumes them."""
    env = GameEnvironment(8, 16, num_players=2, map_type="basic")
    env.reset(seed=seed)
    for player in env.players:
        grant_all(player)
        for city in player.cities:
            city.population = 6
            for pos in sorted(env.map.tiles_of_city(city.city_id)):
                for name in DISTRICTS:
                    env.place_district(city, name, pos)
            city.production = sum(d.cost for d in city.districts)
    for _ in range(40):
        env.turn_counter += 1
        for player in env.players:
            for city in player.cities:
                for d in city.districts:
                    if not d.complete:
                        city.produce_district(d.type)
                        break
                city.process_turn(env)
    return ([(d.type, d.coordinates, d.complete) for p in env.players
             for c in p.cities for d in c.districts],
            [district_yields(c) for p in env.players for c in p.cities],
            env.episode_stats)


def test_same_seed_gives_identical_completion_yields_and_stats():
    """Same seed and actions give identical districts, yields and stats.
    Breaks if completion order or yields depend on set iteration."""
    first = _play(17)
    assert any(d[2] for d in first[0]), "fixture: something completed"
    assert first == _play(17)
