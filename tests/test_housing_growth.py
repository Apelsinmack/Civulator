"""Issue #88 H2: housing growth bands and the hundredths growth bucket
(spec docs/housing_design.md s2, s5)."""

import pytest

from civulator import unit_model
from civulator.config import CFG
from civulator.game import city as city_mod
from civulator.game.environment import GameEnvironment

from test_city_walls import make_city
from test_combat_range import make_flat_env

BANDS = unit_model.HOUSING_GROWTH_BANDS


def _setup(monkeypatch, margin_tenths, food_net=2, pop=2):
    """A city whose housing minus population is `margin_tenths` and whose net
    food is `food_net`, both pinned so only the growth rule is under test."""
    env = make_flat_env()
    city = make_city(env, (3, 8))
    city.population = pop
    monkeypatch.setattr(city_mod, "housing", lambda c: margin_tenths + 10 * c.population)
    monkeypatch.setattr(city, "calculate_food", lambda g: food_net + 2 * city.population)
    monkeypatch.setattr(city, "assign_tiles", lambda g: None)
    return env, city


def _bucket_after_one_turn(monkeypatch, margin_tenths, food_net=2):
    env, city = _setup(monkeypatch, margin_tenths, food_net)
    city.process_turn(env)
    return city.food_surplus


def test_bucket_gain_follows_the_band_table_and_config_changes_it(monkeypatch):
    """Each margin adds food_net * the percent of the first band whose min it
    reaches (0 below all). Breaks if a percent is hardcoded or the bands are
    not read from config."""
    for low, percent in BANDS:
        assert _bucket_after_one_turn(monkeypatch, low, 2) == 2 * percent
    below = BANDS[-1][0] - 1
    assert _bucket_after_one_turn(monkeypatch, below, 2) == 0
    monkeypatch.setattr(unit_model, "HOUSING_GROWTH_BANDS", ((20, 70), (-50, 10)))
    assert _bucket_after_one_turn(monkeypatch, 20, 2) == 140
    assert _bucket_after_one_turn(monkeypatch, 19, 2) == 20


def test_one_food_surplus_at_25_percent_still_grows_eventually(monkeypatch):
    """Breaks if the bucket floors fractional food (a 25 % share of 1 food
    would be lost forever)."""
    env, city = _setup(monkeypatch, -10, food_net=1, pop=1)
    pop0 = city.population
    quarter = dict(BANDS).get(BANDS[-1][0])
    assert quarter < 100
    for _ in range(10_000):
        city.process_turn(env)
        if city.population > pop0:
            break
    assert city.population == pop0 + 1


def test_housing_never_removes_population_but_starvation_does(monkeypatch):
    """A negative net is not scaled by housing and shrinking housing alone
    never lowers population. Breaks if housing is applied to negative nets or
    deficit removes pop."""
    env, city = _setup(monkeypatch, -80, food_net=3, pop=3)
    for _ in range(50):
        city.process_turn(env)
    assert city.population == 3  # far below every band: stalls, never shrinks
    monkeypatch.setattr(city, "calculate_food", lambda g: 2 * city.population - 1)
    city.food_surplus = 0
    city.process_turn(env)
    assert city.population == 2  # starvation still drops it


def test_negative_net_drains_the_bucket_in_hundredths(monkeypatch):
    """Breaks if the drain is not 100 * food_net or is scaled by percent."""
    env, city = _setup(monkeypatch, 40, food_net=-2)
    city.food_surplus = 1000
    city.process_turn(env)
    assert city.food_surplus == 800


def test_zero_percent_band_blocks_growth_even_with_a_full_bucket(monkeypatch):
    """Breaks if growth ignores the band: the full bucket is kept, not spent."""
    env, city = _setup(monkeypatch, BANDS[-1][0] - 1, food_net=1)
    city.food_surplus = 100 * city.get_growth_threshold() + 500
    full = city.food_surplus
    pop0 = city.population
    city.process_turn(env)
    assert city.population == pop0 and city.food_surplus == full


def test_full_bucket_grows_outside_the_cap_and_subtracts_the_threshold(monkeypatch):
    """Breaks if the threshold is compared in whole food against hundredths."""
    env, city = _setup(monkeypatch, 100, food_net=0)
    thr = 100 * city.get_growth_threshold()
    city.food_surplus = thr + 7
    pop0 = city.population
    city.process_turn(env)
    assert city.population == pop0 + 1 and city.food_surplus == 7


def test_bad_growth_bands_raise_at_load():
    """Breaks if a float percent or unordered/duplicate mins are accepted."""
    with pytest.raises(ValueError):
        unit_model.parse_growth_bands([[2.0, 100.5]])
    with pytest.raises(ValueError):
        unit_model.parse_growth_bands([[1.0, 50], [2.0, 100]])
    with pytest.raises(ValueError):
        unit_model.parse_growth_bands([[1.0, 50], [1.0, 25]])
    with pytest.raises(ValueError):
        unit_model.parse_growth_bands([[1.05, 50]])
    assert unit_model.parse_growth_bands([[2.0, 100], [-4.9, 25]]) == ((20, 100), (-49, 25))


def test_config_bands_are_parsed_ints_and_descending():
    """Breaks if the shipped config violates the load contract."""
    assert all(isinstance(p, int) for _, p in BANDS)
    mins = [m for m, _ in BANDS]
    assert mins == sorted(mins, reverse=True) and len(set(mins)) == len(mins)
    assert len(BANDS) == len(CFG["housing"]["growth_bands"])


def _run(seed, rounds=40):
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for _ in range(rounds * env.num_players):
        env.current_player.end_turn()
        env.next_turn()
    return [(c.population, c.food_surplus) for p in env.players for c in p.cities]


def test_same_seed_same_actions_give_identical_populations_and_buckets():
    """Two envs in one process. Breaks if growth uses floats or any
    non-seeded state."""
    a, b = _run(321), _run(321)
    assert a == b and a
    assert all(isinstance(s, int) for _, s in a)


def test_growth_slowed_turns_counts_positive_net_below_full_share(monkeypatch):
    """Counts only positive-net city-turns with percent < 100; not full-share,
    not zero or negative net; reset clears it. Breaks if the count includes
    those or misses the 0 % band."""
    env, city = _setup(monkeypatch, 100, food_net=2)
    city.process_turn(env)
    assert env.episode_stats[0]["growth_slowed_turns"] == 0  # 100 % band
    monkeypatch.setattr(city_mod, "housing", lambda c: 10 * c.population + 10)
    city.process_turn(env)
    assert env.episode_stats[0]["growth_slowed_turns"] == 1  # 50 % band
    monkeypatch.setattr(city_mod, "housing", lambda c: 10 * c.population - 200)
    city.process_turn(env)
    assert env.episode_stats[0]["growth_slowed_turns"] == 2  # 0 % band
    monkeypatch.setattr(city, "calculate_food", lambda g: 2 * city.population)
    city.process_turn(env)
    assert env.episode_stats[0]["growth_slowed_turns"] == 2  # zero net
    monkeypatch.setattr(city, "calculate_food", lambda g: 2 * city.population - 1)
    city.process_turn(env)
    assert env.episode_stats[0]["growth_slowed_turns"] == 2  # negative net
    assert env.episode_stats_snapshot(0)["growth_slowed_turns"] == 2
    env.reset(seed=1)
    assert env.episode_stats[0]["growth_slowed_turns"] == 0
