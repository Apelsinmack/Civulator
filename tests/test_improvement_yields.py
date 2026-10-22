"""Issue #116 P2: improvement yields (docs/progression_design.md "v2 fixes",
"Improvement yields (B6)").

`[improvements.*]` may declare `food`, `production` and `gold` in whole
points: food and production reach `Tile.yields` (so `assign_tiles`, the
encoders and the city's food and production), gold reaches
`city_yield(city, "gold")` over the centre and the worked tiles, and
building an improvement bumps the terrain epoch every yield cache keys on.
Every test iterates over whatever improvements are configured.
"""

import pytest
import torch

from civulator import terrain_model
from civulator.agents.state_encoders import get_encoder
from civulator.config import CFG
from civulator.game.yields import city_yield

from test_availability import _env_and_city, _improvement_terrain, _painted

COLUMNS = terrain_model.IMPROVEMENT_YIELD_COLUMNS


def _site(env, city):
    """A tile the city owns (founding ring)."""
    return sorted(env.map.get_ring_coords(city.coordinates, 1)[1])[0]


def _placeable():
    names = [n for n in sorted(terrain_model.IMPROVEMENT_NAMES) if _improvement_terrain(n)]
    assert names, "fixture: some improvement can stand somewhere"
    return names


def test_improvement_columns_are_parsed_as_whole_points_with_zero_default():
    """IMPROVEMENT_YIELDS holds every configured improvement's food,
    production and gold exactly as config.toml declares them (0 when
    absent), as ints. Breaks if a column is dropped, scaled or defaulted
    wrongly."""
    for name, table in CFG["improvements"].items():
        parsed = terrain_model.IMPROVEMENT_YIELDS[name]
        assert set(parsed) == set(COLUMNS)
        for column in COLUMNS:
            assert parsed[column] == table.get(column, 0) and type(parsed[column]) is int
    assert any(any(v for v in y.values()) for y in terrain_model.IMPROVEMENT_YIELDS.values()), \
        "fixture: some improvement yields something"


@pytest.mark.parametrize("bad", [-1, 0.5, True, "1"])
def test_a_malformed_improvement_yield_raises_at_load(bad):
    """A negative, fractional, bool or string yield column raises. Breaks if
    the loader accepts a value the whole-point tile sum cannot hold."""
    for column in COLUMNS:
        with pytest.raises(ValueError):
            terrain_model.parse_improvements({"Probe": {column: bad}})


def test_an_improvement_adds_exactly_its_columns_to_its_tile():
    """Building an improvement raises Tile.yields by exactly its (food,
    production) and Tile.gold by exactly its gold; the terrain layers are
    untouched. Breaks if a column is ignored or a layer value moves."""
    for name in _placeable():
        env, city = _env_and_city()
        pos = _painted(env, _site(env, city), name)
        tile = env.map.get_tile(pos)
        before, gold_before, composed = tile.yields, tile.gold, tile.composed
        assert env.build_improvement(pos, name)
        columns = terrain_model.IMPROVEMENT_YIELDS[name]
        assert tile.yields == (before[0] + columns["food"], before[1] + columns["production"])
        assert tile.gold == gold_before + columns["gold"]
        assert tile.composed == composed


@pytest.mark.usefixtures("neutral_amenities")  # v0.9.0 Q2: not about the amenity band
def test_improvement_yields_reach_the_city_working_the_tile_and_only_it():
    """A worked improved tile adds the improvement's food and production to
    the city's food and production and 10 x its gold to city_yield gold
    (tenths); the same tile unworked adds nothing. Breaks if the city sums
    terrain yields only, or counts tiles it does not work."""
    names = ("food", "production", "gold")
    for name in _placeable():
        env, city = _env_and_city()
        pos = _painted(env, _site(env, city), name)
        city.worked_tiles = []  # fixture: worked tiles set by hand, not assign_tiles
        unworked_before = {y: city_yield(city, y) for y in names}
        city.worked_tiles = [pos]
        before = {y: city_yield(city, y) for y in names}
        assert env.build_improvement(pos, name)
        columns = terrain_model.IMPROVEMENT_YIELDS[name]
        assert city.calculate_food(env) == before["food"] + columns["food"]
        assert city_yield(city, "production") == before["production"] + columns["production"]
        assert city_yield(city, "gold") == before["gold"] + 10 * columns["gold"]
        city.worked_tiles = []
        assert {y: city_yield(city, y) for y in names} == unworked_before


def test_building_an_improvement_bumps_the_terrain_epoch_and_a_refusal_does_not():
    """build_improvement bumps Map.terrain_epoch (a tile's gameplay numbers
    changed); a refused build leaves it alone. Breaks if improvements change
    yields behind every epoch-keyed cache."""
    for name in _placeable():
        env, city = _env_and_city()
        pos = _painted(env, _site(env, city), name)
        epoch = env.map.terrain_epoch
        assert env.build_improvement(pos, name)
        assert env.map.terrain_epoch > epoch
        epoch = env.map.terrain_epoch
        assert not env.build_improvement(pos, name), "already there"
        assert env.map.terrain_epoch == epoch


def test_the_terrain_encoder_sees_an_improvement_after_it_is_built():
    """The terrain-aware encoder's cached terrain block (keyed on
    terrain_epoch) is rebuilt once an improvement with food or production is
    built, so the policy never reads stale tile yields. Breaks if the build
    skips the epoch bump."""
    name = next((n for n in _placeable()
                 if terrain_model.IMPROVEMENT_YIELDS[n]["food"]
                 or terrain_model.IMPROVEMENT_YIELDS[n]["production"]), None)
    if name is None:
        pytest.skip("no configured improvement yields food or production")
    env, city = _env_and_city()
    pos = _painted(env, _site(env, city), name)
    encoder = get_encoder("terrain_aware", fog_of_war=False)
    before = encoder.encode(env, 0)
    assert env.build_improvement(pos, name)
    assert not torch.equal(encoder.encode(env, 0), before)


def test_placing_a_district_on_an_improved_tile_clears_it_and_bumps_the_epoch():
    """A district placed on an improved tile removes the improvement (its
    yields leave the tile) and bumps the terrain epoch. Breaks if the
    improvement list is cleared behind the epoch."""
    from conftest import grant_all
    from test_districts import placeable_type

    t = placeable_type()
    env, city = _env_and_city()
    grant_all(city.player)
    name = next(n for n in _placeable() if _improvement_terrain(n)[0] in ("Plains", "Grassland"))
    pos = sorted(env.map.get_ring_coords(city.coordinates, 2)[2])[0]
    env.map.claim(pos, city)
    _painted(env, pos, name)
    assert env.build_improvement(pos, name)
    epoch = env.map.terrain_epoch
    assert env.place_district(city, t, pos)
    assert env.map.get_tile(pos).improvements == []
    assert env.map.terrain_epoch > epoch
