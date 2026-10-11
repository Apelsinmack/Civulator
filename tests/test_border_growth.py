"""Border growth (issue #87 P3, spec docs/borders_culture_design.md §3, §8).

Every test names the property it protects and the change that must break it.
Costs are always read from `env.border_cost` and culture rates from
`culture(city)`, never restated as numbers, so rebalancing the config does
not break these tests.
"""

import numpy as np
import pytest

from civulator import hexmath
from civulator.config import CFG
from civulator.game import territory
from civulator.game.culture import culture
from civulator.game.environment import GameEnvironment
from civulator.game.territory import NEUTRAL, border_cost_function, claim_candidates

from test_combat_range import make_flat_env
from test_territory import assert_territory_invariants

RESOURCE = "Wheat"  # valid on flat Plains, the flat test board's terrain


def _play_round(env):
    """One full round of end-turns: ends with the wrap to player 0, i.e.
    exactly one border phase."""
    for _ in range(len(env.players)):
        env.next_turn()


def _contest_board(early_seat):
    """Two cities of different players, 4 apart on one row, both with equal
    culture rate; the resource tile between them, at distance 2 from both
    and adjacent to both territories, is each city's unique best candidate.
    The city of seat `early_seat` banks more culture, so it crosses its first
    cost earlier in the round. Returns (env, early, late, contested)."""
    env = make_flat_env()
    contested = (4, 6)
    env.map.tiles[contested].set_layers("Plains", resource=RESOURCE, map_ref=env.map)
    # Created in seat order, so with early_seat = 1 the early city is also
    # the higher id: neither seat order nor id order can be what decides.
    spots = {early_seat: ((4, 4), "Early"), 1 - early_seat: ((4, 8), "Late")}
    made = {seat: env.create_city(env.players[seat], *spots[seat]) for seat in (0, 1)}
    early, late = made[early_seat], made[1 - early_seat]
    assert env.map.distance_function(contested, early.coordinates) == 2
    assert env.map.distance_function(contested, late.coordinates) == 2
    assert culture(early) == culture(late)
    return env, early, late, contested


def _bank(env, city, p0):
    """Set the pool so that, at the next border phase, p0 = border_culture -
    culture_this_round equals `p0` (accrual still due this round adds r)."""
    city.border_culture = p0 + city.culture_this_round


# --- §3.3 turn-order independence ---------------------------------------------


@pytest.mark.parametrize("early_seat", [0, 1])
def test_earlier_crossing_wins_contest_regardless_of_seat_order(early_seat):
    """Property: two cities of different players contest one tile; the one
    that crosses its cost earlier in the round wins it, whichever seat moves
    first (both seat orders). Breaks if claims resolve during each player's
    own turn (end_turn/start_turn) instead of in the round-end border phase,
    or the phase orders events by seat instead of crossing time."""
    env, early, late, contested = _contest_board(early_seat)
    _play_round(env)  # round 1: every city is now accruing normally
    cost = env.border_cost(1)
    r = culture(early)
    assert 0 < r < cost
    # Both cross this round; the early city strictly earlier.
    _bank(env, early, cost - r + 1)  # crosses at t = (r - 1) / r
    _bank(env, late, cost - r)       # crosses exactly at t = 1
    _play_round(env)
    assert env.map.owner_id_at(contested) == early.city_id
    assert early.border_claims == 1 and late.border_claims == 1


@pytest.mark.parametrize("early_seat", [0, 1])
def test_loser_of_a_contest_claims_next_best_tile_and_pays_one_cost(early_seat):
    """Property: losing a contest costs nothing extra — the loser claims its
    next-best tile in the same round (same ring), and its pool is reduced by
    exactly one cost. Breaks if the loser's points are consumed or
    discarded, or a lost contest drops the city from the phase."""
    env, early, late, contested = _contest_board(early_seat)
    _play_round(env)
    cost = env.border_cost(1)
    r = culture(late)
    assert r > 2
    p0_late = cost - r + 1           # crosses at t = (r - 1) / r
    _bank(env, early, cost - 1)      # crosses at t = 1 / r, earlier
    _bank(env, late, p0_late)
    late_before = set(env.map.tiles_of_city(late.city_id))
    _play_round(env)
    gained = set(env.map.tiles_of_city(late.city_id)) - late_before
    assert len(gained) == 1
    (pos,) = gained
    assert pos != contested
    assert env.map.distance_function(pos, late.coordinates) == 2
    # Player 0's next turn may already have accrued after the wrap.
    assert late.border_culture - late.culture_this_round == p0_late + r - cost
    assert late.border_claims == 1


# --- §3.3 total order, keys 1 and 2 --------------------------------------------


def test_clamped_event_precedes_any_unclamped_one():
    """Property: an event at t = 0 (pool already covers the cost before this
    round's culture) comes before any unclamped event, even one from a city
    with a far higher rate. Breaks if clamped events are ordered by a
    cross-multiplication that treats r = 0 as tied, or by rate first."""
    env, a, b, contested = _contest_board(0)
    cost = env.border_cost(1)
    a.culture_this_round, a.border_culture = 0, cost          # boxed in, t = 0
    b.culture_this_round, b.border_culture = 10 * cost, 10 * cost  # p0 = 0, t > 0
    env._border_phase()
    assert env.map.owner_id_at(contested) == a.city_id


@pytest.mark.parametrize("rng_seed", range(8))
def test_equal_crossing_time_goes_to_larger_end_of_round_surplus(rng_seed):
    """Property: on equal t the city with the larger end-of-round surplus
    p0 + r - S_k (here: the larger culture rate) wins, for every RNG state.
    Breaks if the second key is dropped (falls through to id + RNG, which
    loses on about half of the seeds) or inverted."""
    env, a, b, contested = _contest_board(0)
    env.rng.seed(rng_seed)
    cost = env.border_cost(1)
    # Equal t = 1/2 for both; the HIGHER id gets the larger rate, so id order
    # (the third key) would pick the other city.
    r_slow, r_fast = 2, 4
    p0_slow, p0_fast = cost - r_slow // 2, cost - r_fast // 2
    assert (cost - p0_slow) * r_fast == (cost - p0_fast) * r_slow
    assert a.city_id < b.city_id
    a.culture_this_round, a.border_culture = r_slow, p0_slow + r_slow
    b.culture_this_round, b.border_culture = r_fast, p0_fast + r_fast
    env._border_phase()
    assert env.map.owner_id_at(contested) == b.city_id


# --- §3.3 r = 0 -----------------------------------------------------------------


def test_zero_round_culture_produces_no_claim_and_no_error():
    """Property: a city with r = 0 and nothing banked (player 0's cities in
    round 1, a city founded after its owner's turn started) makes no claim
    and raises nothing. Breaks if t is computed by dividing by r."""
    env = make_flat_env()
    first = env.create_city(env.players[0], (4, 4), "Round1")
    env.next_turn()  # player 1's turn starts; player 0 never accrued in round 1
    late = env.create_city(env.players[1], (4, 10), "FoundedMidRound")
    owned_before = env.map.owner_city.copy()
    env.next_turn()  # wrap -> border phase
    assert first.border_claims == 0 and late.border_claims == 0
    assert np.array_equal(env.map.owner_city, owned_before)
    # The phase zeroed the round; only player 0's new turn has accrued since.
    assert late.culture_this_round == 0
    assert first.culture_this_round == culture(first)


def test_zero_round_culture_with_banked_pool_claims_at_t0():
    """Property (§3.3 r = 0 rule): a city with r = 0 whose banked pool covers
    S_k claims those k tiles at t = 0. Breaks if r = 0 cities are skipped
    outright, leaving a boxed-in city's banked culture stuck forever."""
    env = make_flat_env()
    city = env.create_city(env.players[0], (4, 4), "Banked")
    city.culture_this_round = 0
    city.border_culture = env.border_cost(1) + env.border_cost(2)
    env._border_phase()
    assert city.border_claims == 2
    assert city.border_culture == 0


# --- §3.1/§3.3 multi-claim and the cost sequence ---------------------------------


def test_high_culture_claims_several_tiles_per_round_in_cost_sequence():
    """Property: a city whose round culture covers cost(n+1) + ... + cost(n+k)
    but not cost(n+k+1) claims exactly k tiles this round, its pool drops by
    exactly that sum, n advances by k, and the remainder carries over.
    Breaks if the phase claims at most one tile per round, charges a flat
    cost, or restarts n each round."""
    env = make_flat_env()
    city = env.create_city(env.players[0], (4, 4), "Rich")
    city.border_claims = 2  # n carries: next costs are cost(3), cost(4), ...
    k = 3
    total = sum(env.border_cost(city.border_claims + i) for i in range(1, k + 1))
    leftover = env.border_cost(city.border_claims + k + 1) - 1
    r = total + leftover
    city.culture_this_round, city.border_culture = r, r
    before = set(env.map.tiles_of_city(city.city_id))
    env._border_phase()
    assert city.border_claims == 2 + k
    assert city.border_culture == leftover
    assert len(set(env.map.tiles_of_city(city.city_id)) - before) == k
    assert city.culture_this_round == 0


# --- §3.2 ring order and §8 "never take an owned tile", in real play ----------------


def _spy_claims(monkeypatch):
    """Record, at every border-phase claim event, the chosen tile, its
    distance, the minimum candidate distance and the tile's owner at that
    moment (before the claim)."""
    events = []
    original = territory.choose_claim_tile

    def spy(game_map, city, rng, claim_radius=None):
        candidates = claim_candidates(game_map, city, claim_radius)
        pos = original(game_map, city, rng, claim_radius)
        if pos is not None:
            dist = lambda p: hexmath.distance(p, city.coordinates, game_map.m)  # noqa: E731
            events.append({
                "pos": pos,
                "dist": dist(pos),
                "min_dist": min(dist(p) for p in candidates),
                "owner_before": game_map.owner_id_at(pos),
            })
        return pos

    monkeypatch.setattr(territory, "choose_claim_tile", spy)
    return events


def _crowded_high_culture_game(monkeypatch, seed, rounds):
    """Seeded basic world plus extra cities of both players packed together,
    with a high culture source so borders collide within a few rounds."""
    monkeypatch.setattr("civulator.game.city.culture", lambda city: 300)
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for player in env.players:
        capital = player.cities[0].coordinates
        for pos in env.map.get_ring_coords(capital, 4)[4]:
            if env.can_found_city_at(pos, env.players[1 - player.player_index]):
                env.create_city(env.players[1 - player.player_index], pos, "Rival")
                break
    for _ in range(rounds):
        _play_round(env)
    return env


def test_every_claim_is_at_min_candidate_distance_and_never_owned(monkeypatch):
    """Property: at every border-phase claim event the claimed tile's
    distance equals the minimum distance over that city's candidates at
    that moment (ring rule), and the tile was neutral (culture never flips a
    tile). Breaks if §3.2 picks by value before distance, or candidates
    include tiles owned by anyone."""
    events = _spy_claims(monkeypatch)
    env = _crowded_high_culture_game(monkeypatch, seed=11, rounds=12)
    assert events, "no culture claims happened; the scenario tests nothing"
    for event in events:
        assert event["dist"] == event["min_dist"], event
        assert event["owner_before"] == NEUTRAL, event
    assert_territory_invariants(env)


# --- §3.4 determinism -----------------------------------------------------------------


def test_same_seed_same_actions_give_identical_borders_pools_and_n(monkeypatch):
    """Property: two environments in one process, same seed and same actions
    (end turns only, with contests and ties), have identical owner grids,
    pools and claim indices after N rounds. Breaks if the tiebreak uses
    anything but PortableRNG, set/dict iteration order leaks into the event
    order, or float t is used anywhere."""
    env1 = _crowded_high_culture_game(monkeypatch, seed=23, rounds=10)
    env2 = _crowded_high_culture_game(monkeypatch, seed=23, rounds=10)
    assert np.array_equal(env1.map.owner_city, env2.map.owner_city)
    assert sorted(env1.city_by_id) == sorted(env2.city_by_id)
    for city_id, city in env1.city_by_id.items():
        twin = env2.city_by_id[city_id]
        assert (city.border_culture, city.border_claims) == (twin.border_culture, twin.border_claims)
    assert any(c.border_claims > 0 for c in env1.city_by_id.values())


# --- §3.1 config and registry --------------------------------------------------------------


def _rounds_until_first_claim(env, city, limit=60):
    for round_index in range(1, limit + 1):
        _play_round(env)
        if city.border_claims:
            return round_index
    return None


def test_border_cost_parameter_changes_when_the_first_claim_happens(monkeypatch):
    """Property: the cost curve's parameters come from [territory.border_cost]:
    raising `a` delays the first culture claim. Breaks if a cost number is
    hardcoded instead of read through the registry from config."""
    table = CFG["territory"]["border_cost"]
    timings = []
    for a in (table["a"], 2 * table["a"]):
        monkeypatch.setitem(table, "a", a)
        env = make_flat_env()
        city = env.create_city(env.players[0], (4, 4), "Timer")
        env.create_city(env.players[1], (4, 12), "Other")
        timings.append(_rounds_until_first_claim(env, city))
    assert None not in timings
    assert timings[1] > timings[0]


def test_unknown_border_cost_curve_raises(monkeypatch):
    """Property: an unknown `curve` name raises instead of silently falling
    back to a default curve. Breaks if the registry lookup has a fallback."""
    with pytest.raises(ValueError):
        border_cost_function({"curve": "no_such_curve", "a": 10})
    monkeypatch.setitem(CFG["territory"]["border_cost"], "curve", "no_such_curve")
    with pytest.raises(ValueError):
        GameEnvironment(8, 16, num_players=2, map_type="basic")


def test_border_cost_is_integer_tenths_of_the_curve():
    """Property: cost(n) is the curve evaluated in float and converted once
    to int tenths, and grows with n for the shipped curve. Breaks if costs
    stay float (inexact comparisons) or are rounded to whole points."""
    cost = border_cost_function(CFG["territory"]["border_cost"])
    params = {k: v for k, v in CFG["territory"]["border_cost"].items() if k != "curve"}
    curve = territory.BORDER_COST_CURVES[CFG["territory"]["border_cost"]["curve"]]
    for n in range(1, 12):
        assert isinstance(cost(n), int)
        assert cost(n) == round(10 * curve(n, **params))
        if n > 1:
            assert cost(n) > cost(n - 1)
