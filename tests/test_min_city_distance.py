"""The city-spacing rule (issue #74): `[game] min_city_distance` counts steps
between city CENTRES, and founding is legal from that distance outward.

`GameEnvironment.can_found_city_at` rejects `distance < MIN_CITY_DISTANCE`, so
the constant IS the first legal distance — with the value 4 that means a
Settler standing 3 steps from a city cannot found, 4 steps can, and two city
centres end up with 3 tiles between them. The old value of 3 came from
counting border-to-border instead of centre-to-centre.

Tests import `MIN_CITY_DISTANCE` rather than hardcoding it (the precedent
tests/test_settle_encoder.py set for #8), so the boundary tests keep testing
the boundary if the number is ever tuned again. Exactly one test pins the
literal 4, so a config edit cannot move the rule silently.
"""

from civulator.game.environment import MIN_CITY_DISTANCE, GameEnvironment
from civulator.mapgen.starts import DEFAULT_PARAMS
from civulator.config import CFG

from test_combat_range import make_flat_env

CITY = (4, 4)


def _env_with_a_city():
    env = make_flat_env()
    assert env.found_city(env.players[0], CITY, "Mine") is not None
    return env


def test_min_city_distance_is_four():
    """The #74 decision itself, pinned in both places that state it."""
    assert MIN_CITY_DISTANCE == 4
    assert CFG["game"]["min_city_distance"] == 4


def test_cannot_found_one_step_inside_the_rule():
    """distance == MIN_CITY_DISTANCE - 1 (3 with today's value) is illegal."""
    env = _env_with_a_city()
    inside = (CITY[0], CITY[1] + MIN_CITY_DISTANCE - 1)
    assert env.map.distance_function(CITY, inside) == MIN_CITY_DISTANCE - 1
    assert env.can_found_city_at(inside, env.players[0]) is False
    assert env.found_city(env.players[0], inside, "TooClose") is None


def test_can_found_exactly_at_the_rule():
    """distance == MIN_CITY_DISTANCE (4) is the first legal site: `<` not `<=`."""
    env = _env_with_a_city()
    at = (CITY[0], CITY[1] + MIN_CITY_DISTANCE)
    assert env.map.distance_function(CITY, at) == MIN_CITY_DISTANCE
    assert env.can_found_city_at(at, env.players[0]) is True
    assert env.found_city(env.players[0], at, "FarEnough") is not None


def test_the_whole_ring_inside_the_rule_is_illegal_in_every_direction():
    """Not just the +q direction — the rule is a hex ring, so sample the board."""
    env = _env_with_a_city()
    for i in range(env.n):
        for j in range(env.m):
            d = env.map.distance_function(CITY, (i, j))
            if d < MIN_CITY_DISTANCE:
                assert env.can_found_city_at((i, j), env.players[0]) is False, ((i, j), d)


def test_legal_spacing_leaves_min_distance_minus_one_tiles_between_centres():
    """The user-facing statement of the rule: 4 steps apart == 3 tiles between."""
    env = _env_with_a_city()
    at = (CITY[0], CITY[1] + MIN_CITY_DISTANCE)
    assert env.found_city(env.players[0], at, "FarEnough") is not None
    between = [(CITY[0], CITY[1] + k) for k in range(1, MIN_CITY_DISTANCE)]
    assert len(between) == MIN_CITY_DISTANCE - 1 == 3
    assert all(env.map.get_tile(c).city is None for c in between)


def test_start_placement_floor_never_undercuts_the_city_rule():
    """Every start becomes a capital, so `d_min_floor` must not seat two
    capitals closer than a city could ever be founded (#74)."""
    assert DEFAULT_PARAMS["d_min_floor"] >= MIN_CITY_DISTANCE
    assert CFG["map"]["starts"]["d_min_floor"] == DEFAULT_PARAMS["d_min_floor"]


def test_action_mask_offers_no_settle_site_the_rule_forbids():
    """The mask reads the rule through can_found_city_at, so it must agree
    tile-for-tile — anything else is train/play skew (#51)."""
    from civulator.agents.state_encoders import get_encoder

    env = _env_with_a_city()
    encoder = get_encoder("settle", fog_of_war=False)
    layer = encoder.encode(env, 0).numpy()[53]
    for i in range(env.n):
        for j in range(env.m):
            assert bool(layer[i, j]) == env.can_found_city_at((i, j), env.players[0]), (i, j)
