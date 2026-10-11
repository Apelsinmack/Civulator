"""Issue #88 H1: housing (spec docs/housing_design.md s1, s3, s5)."""

from civulator import terrain_model, unit_model
from civulator.config import CFG
from civulator.game import housing as housing_mod
from civulator.game.city import City
from civulator.game.housing import housing

from test_city_walls import make_city
from test_combat_range import make_flat_env

HCFG = CFG["housing"]
RADIUS = HCFG["improvement_radius"]


def _tenths(x):
    return round(10 * x)


def _owned_at_distance(env, city, dist):
    for pos in env.map.tiles_of_city(city.city_id):
        if env.map.distance_function(city.coordinates, pos) == dist:
            return pos
    raise AssertionError(f"fixture: city owns no tile at distance {dist}")


def test_water_tiers_follow_config_and_canonical_queries(monkeypatch):
    """fresh > coastal > dry, with the config values, decided by
    Map.is_fresh_water and water-domain neighbours. Breaks if terrain names are
    read or fresh water is recomputed outside the canonical query."""
    env = make_flat_env()
    city = make_city(env, (3, 8))
    assert housing(city) == _tenths(HCFG["water_dry"]) + unit_model.BUILDING_HOUSING["Palace"]
    dry = housing(city)

    nb = env.map.get_adjacent_coords(city.coordinates)[0]
    env.map.get_tile(nb).set_layers("Coast", map_ref=env.map)
    assert housing(city) - dry == _tenths(HCFG["water_coastal"]) - _tenths(HCFG["water_dry"])

    monkeypatch.setattr(env.map, "is_fresh_water", lambda c: True)
    assert housing(city) - dry == _tenths(HCFG["water_fresh"]) - _tenths(HCFG["water_dry"])
    assert _tenths(HCFG["water_fresh"]) > _tenths(HCFG["water_coastal"]) > _tenths(HCFG["water_dry"])


def test_a_declared_building_adds_exactly_its_value_and_undeclared_adds_zero(monkeypatch):
    """Breaks if the sum hardcodes a building name or ignores the column."""
    env = make_flat_env()
    city = make_city(env, (3, 8))
    base = housing(city)
    city.buildings.append("Walls")
    assert "Walls" not in unit_model.BUILDING_HOUSING
    assert housing(city) == base
    monkeypatch.setitem(unit_model.BUILDING_HOUSING, "Walls", 7)
    monkeypatch.setattr(housing_mod, "BUILDING_HOUSING", unit_model.BUILDING_HOUSING)
    assert housing(city) == base + 7


def test_granary_and_palace_declare_housing_in_config():
    """Breaks if the [buildings.*] housing column is not parsed."""
    for name in ("Granary", "Palace"):
        assert unit_model.BUILDING_HOUSING[name] == _tenths(CFG["buildings"][name]["housing"])


def test_a_declared_improvement_adds_exactly_its_value_and_undeclared_adds_zero(monkeypatch):
    """Breaks if the sum hardcodes an improvement name or ignores the column."""
    env = make_flat_env()
    city = make_city(env, (3, 8))
    tile = env.map.get_tile(_owned_at_distance(env, city, 1))
    base = housing(city)
    tile.add_improvement("Mine")
    assert "Mine" not in terrain_model.IMPROVEMENT_HOUSING
    assert housing(city) == base
    tile.remove_improvement("Mine")
    tile.add_improvement("Farm")
    assert housing(city) == base + terrain_model.IMPROVEMENT_HOUSING["Farm"]
    monkeypatch.setitem(terrain_model.IMPROVEMENT_HOUSING, "Farm", 3)
    assert housing(city) == base + 3


def test_config_improvements_declare_housing():
    """Breaks if the [improvements.*] housing column is not parsed."""
    for name in ("Farm", "Pasture", "Plantation", "Camp", "Fishing Boats"):
        assert terrain_model.IMPROVEMENT_HOUSING[name] == _tenths(CFG["improvements"][name]["housing"])


def test_improvement_housing_counts_only_owned_tiles():
    """Breaks if ownership is ignored (a neighbour's or a neutral tile counts)."""
    env = make_flat_env(n=12, m=24)
    city = make_city(env, (6, 12))
    other = make_city(env, (6, 12 + RADIUS), player_index=1)
    base = housing(city)
    theirs = next(
        p for p in env.map.tiles_of_city(other.city_id)
        if 0 < env.map.distance_function(city.coordinates, p) <= RADIUS
    )
    env.map.get_tile(theirs).add_improvement("Farm")
    assert housing(city) == base
    mine = _owned_at_distance(env, city, 1)
    env.map.get_tile(mine).add_improvement("Farm")
    assert housing(city) == base + terrain_model.IMPROVEMENT_HOUSING["Farm"]


def test_improvement_radius_is_read_from_config(monkeypatch):
    """Breaks if the radius is ignored or hardcoded: an owned improvement
    beyond it must not count."""
    env = make_flat_env(n=12, m=24)
    city = make_city(env, (6, 12))
    pos = (6, 14)  # distance 2; claim it so the city owns it
    assert env.map.distance_function(city.coordinates, pos) == 2
    if env.map.owner_city[pos] != city.city_id:
        env.map.claim(pos, city)
    base = housing(city)
    env.map.get_tile(pos).add_improvement("Farm")
    assert housing(city) == base + terrain_model.IMPROVEMENT_HOUSING["Farm"]
    monkeypatch.setattr(housing_mod, "HOUSING_IMPROVEMENT_RADIUS", 1)
    assert housing(city) == base


def test_stacked_improvements_count_the_max_and_the_centre_adds_none():
    """Breaks if stacking is summed, or the city centre counts."""
    env = make_flat_env()
    city = make_city(env, (3, 8))
    base = housing(city)
    tile = env.map.get_tile(_owned_at_distance(env, city, 1))
    tile.add_improvement("Farm")
    one = housing(city)
    assert one > base
    tile.add_improvement("Pasture")
    assert housing(city) == one, "two improvements on one tile must count once"
    env.map.get_tile(city.coordinates).add_improvement("Farm")
    assert housing(city) == one, "the centre never counts"


def test_housing_is_int_tenths():
    """Breaks if any term becomes a float."""
    env = make_flat_env()
    city = make_city(env, (3, 8))
    env.map.get_tile(_owned_at_distance(env, city, 1)).add_improvement("Farm")
    assert type(housing(city)) is int


# --- Palace ------------------------------------------------------------------

def test_first_city_per_player_holds_the_palace_and_later_ones_do_not():
    """Breaks if the grant rule drifts (every city, or none)."""
    env = make_flat_env()
    a1 = make_city(env, (1, 2), player_index=0)
    a2 = make_city(env, (5, 10), player_index=0)
    b1 = make_city(env, (3, 6), player_index=1)
    assert "Palace" in a1.buildings and "Palace" in b1.buildings
    assert "Palace" not in a2.buildings
    assert housing(a1) - housing(a2) == unit_model.BUILDING_HOUSING["Palace"]


def test_a_second_reset_on_the_same_env_still_grants_palaces():
    """Breaks if palace_granted is not reset per attempt."""
    from civulator.game.environment import GameEnvironment
    env = GameEnvironment(num_players=2, seed=1)
    env.reset(seed=2)
    env.reset(seed=3)
    for p in env.players:
        assert sum("Palace" in c.buildings for c in p.cities) == 1


def test_clear_board_resets_the_grant():
    """Breaks if recording._clear_board leaves palace_granted set."""
    from civulator.tools.recording import _clear_board
    env = make_flat_env()
    make_city(env, (3, 3), player_index=0)
    assert env.players[0].palace_granted
    _clear_board(env)
    assert not env.players[0].palace_granted
    assert "Palace" in make_city(env, (3, 3), player_index=0).buildings


def test_captured_palace_city_keeps_it_and_old_owner_gets_no_new_one():
    """Breaks if capture strips buildings or re-grants a Palace."""
    env = make_flat_env()
    capital = make_city(env, (3, 3), player_index=1)
    make_city(env, (5, 10), player_index=0)
    capital.set_owner(env.players[0])
    assert "Palace" in capital.buildings
    assert env.players[1].palace_granted
    again = make_city(env, (1, 12), player_index=1)
    assert "Palace" not in again.buildings


def test_the_palace_cannot_be_produced():
    """Breaks if the production path accepts a building without a cost."""
    env = make_flat_env()
    city = make_city(env, (3, 3))
    assert "Palace" not in City.BUILDING_COSTS
    before = city.current_production
    assert city.produce_building("Palace") is False
    assert city.current_production == before
    assert city.produce_building("Granary") is True
