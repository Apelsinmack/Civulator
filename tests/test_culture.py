"""Issue #87 P1: culture yield (spec docs/borders_culture_design.md s1, s8)."""

import importlib

import pytest

from civulator import unit_model
from civulator.config import CFG
from civulator.game.city import City
from civulator.game.culture import culture

from test_city_walls import make_city
from test_combat_range import make_flat_env


def _tenths(x):
    return round(10 * x)


def test_culture_follows_the_config_formula():
    """culture(city) == base + per_pop * population from [culture], in int
    tenths. Breaks if base/per_pop are hardcoded or the formula drifts."""
    env = make_flat_env()
    city = make_city(env)
    for pop in (1, 4):
        city.population = pop
        expected = _tenths(CFG["culture"]["base"]) + _tenths(CFG["culture"]["per_pop"]) * pop
        assert culture(city) == expected
        assert type(culture(city)) is int


def test_a_declared_culture_source_adds_its_value(monkeypatch):
    """A building that declares `culture` in its table adds exactly that to
    the city's yield. Breaks if the source sum ignores the column or reads a
    hardcoded building name."""
    env = make_flat_env()
    city = make_city(env)
    base = culture(city)
    monkeypatch.setitem(unit_model.BUILDING_CULTURE, "Granary", 7)
    city.buildings.append("Granary")
    assert culture(city) == base + 7


def test_monument_declares_culture_in_config():
    """Monument's culture comes from the [buildings.Monument] table, parsed by
    unit_model. Breaks if the column is not read."""
    assert unit_model.BUILDING_CULTURE["Monument"] == _tenths(CFG["buildings"]["Monument"]["culture"])
    env = make_flat_env()
    city = make_city(env)
    base = culture(city)
    city.buildings.append("Monument")
    assert culture(city) == base + unit_model.BUILDING_CULTURE["Monument"]


def test_buildings_without_culture_column_default_to_zero():
    """The column is optional with default 0. Breaks if a missing column
    raises or counts as nonzero."""
    assert "Walls" not in unit_model.BUILDING_CULTURE
    env = make_flat_env()
    city = make_city(env)
    base = culture(city)
    city.buildings.append("Walls")
    assert culture(city) == base


def test_non_multiples_of_a_tenth_raise():
    """to_tenths and the config loader reject values not a multiple of 0.1.
    Breaks if rounding is silent."""
    assert unit_model.to_tenths(0.3, "x") == 3
    assert unit_model.to_tenths(2, "x") == 20
    with pytest.raises(ValueError):
        unit_model.to_tenths(0.25, "x")
    saved = CFG["culture"]["per_pop"]
    CFG["culture"]["per_pop"] = 0.25
    try:
        with pytest.raises(ValueError):
            importlib.reload(unit_model)
    finally:
        CFG["culture"]["per_pop"] = saved
        importlib.reload(unit_model)


def test_accrual_is_int_tenths_and_at_most_once_per_round():
    """process_turn adds culture(city) once per round to border_culture,
    culture_this_round and Player.culture, all ints; a second call in the same
    round adds nothing, a new round adds again. Breaks if the round stamp is
    missing or a pool is a float."""
    env = make_flat_env()
    city = make_city(env)
    player = city.player
    b0, p0 = city.border_culture, player.culture

    city.process_turn(env)
    gained = city.border_culture - b0
    assert gained > 0
    assert city.culture_this_round == gained
    assert player.culture - p0 == gained
    for v in (city.border_culture, city.culture_this_round, player.culture):
        assert type(v) is int

    city.process_turn(env)
    assert city.border_culture - b0 == gained, "second accrual in the same round"

    env.turn_counter += 1
    city.process_turn(env)
    assert city.border_culture - b0 > gained


def test_accrual_uses_post_growth_population():
    """per_pop applies to the population after this turn's growth. Breaks if
    culture accrues before the growth step."""
    env = make_flat_env()
    city = make_city(env)
    city.food_surplus = city.get_growth_threshold() + 1000  # force growth
    pop0 = city.population
    city.process_turn(env)
    assert city.population > pop0
    assert city.border_culture == culture(city)
