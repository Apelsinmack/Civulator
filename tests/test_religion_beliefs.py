"""Religion II (v0.9.0 Q8, docs/districts_religion_design.md §7.3, §7.5, §9, §11,
"v2 fixes" (Crusade/Defender, the belief source, Jesuit Education) and "v3
fixes" L1, L2, L4, L9): the belief registry, founding and beliefs with their
predicates, the follower source of `active_effects`, founder pay, the
`cross_yield` / `per_follower_city` / `religion_param` kinds, `per_wonder`,
the building faith-purchase categories, the two combat attributes, what
religion keeps through capture, flip and elimination, the engine defaults.

Every test asserts a property and names the change that breaks it. Nothing
here pins the number, order or names of the configured beliefs: registry
tests iterate `[beliefs.*]`, and a test that needs a belief of a given shape
finds it in the registry or adds a synthetic one for its own duration.
Boards are test_districts' all-Plains fixture (every tech and civic known).
"""

from dataclasses import replace

import pytest

from civulator import district_model, effects, religion_model, unit_model
from civulator.effects import (
    KIND_COMBAT_STRENGTH,
    KIND_CROSS_YIELD,
    KIND_FAITH_PURCHASE,
    KIND_PER_FOLLOWER_CITY,
    KIND_RELIGION_PARAM,
    SOURCE_BELIEF,
    active_effects,
    effects_of,
    parse_effect,
)
from civulator.game import religion as religion_mod
from civulator.game.defaults import default_add_belief, default_found_religion
from civulator.game.districts import District, adjacency_score, district_spec
from civulator.game.environment import GameEnvironment
from civulator.game.purchasing import can_purchase
from civulator.game.religion import (
    REFUSE_ALREADY_HELD,
    REFUSE_FAITH,
    REFUSE_HAS_RELIGION,
    REFUSE_LADDER_CLIMBED,
    REFUSE_MAX_RELIGIONS,
    REFUSE_NO_FOUNDER_BELIEF_LEFT,
    REFUSE_NO_PANTHEON,
    REFUSE_NO_RELIGION,
    REFUSE_NO_SEAT,
    REFUSE_NOT_FOLLOWER_BELIEF,
    REFUSE_NOT_FOUNDER_BELIEF,
    REFUSE_TAKEN,
    REFUSE_WRONG_TIER,
    Religion,
    belief_cost_tenths,
    belief_refusals,
    can_add_belief,
    can_found_religion,
    found_cost_tenths,
    founder_pay_tenths,
    founding_refusals,
    seat_city,
    taken_beliefs,
)
from civulator.game.yields import city_yield
from civulator.religion_model import (
    BELIEFS,
    PANTHEON_ORDER,
    RULES,
    TIER_ENHANCER,
    TIER_FOLLOWER,
    TIER_FOUNDER,
    TIERS,
    BeliefSpec,
    beliefs_of_tier,
    parse_religion,
)
from civulator.unit_model import (
    BUILDING_FAITH_CATEGORIES,
    BUILDING_PURCHASABLE,
    BUILDING_REQUIRES_DISTRICT,
    FAITH_CATEGORY_LAND_MILITARY,
    YIELD_COLUMNS,
    building_faith_category,
    parse_building_faith_categories,
)

from conftest import stand
from test_districts import board, far_site, make_city, own, ring

pytestmark = pytest.mark.usefixtures("neutral_amenities")

SEAT_BUILDING = RULES.founding_building
SEAT_DISTRICT = RULES.founding_district
POOL_YIELDS = tuple(unit_model.YIELD_BASE)


# --- fixtures ------------------------------------------------------------------------------


def _belief(monkeypatch, name, tier, entries, counts=None, requires_building=None):
    """A synthetic `[beliefs.*]` table for one test, in the registry every
    reader sees (`religion_model.BELIEFS`); validated by the real interpreter
    on first use."""
    if tier == TIER_FOUNDER and counts is None:
        counts = religion_model.COUNTS_ALL
    monkeypatch.setitem(religion_model.BELIEFS, name,
                        BeliefSpec(name=name, tier=tier, effects=tuple(entries), counts=counts,
                                   requires_building=requires_building))
    return name


def _env():
    env = board()
    make_city(env, (3, 4))
    make_city(env, (5, 12), player_index=1)
    return env


def _seat(env, city, complete=True):
    """Make `city` qualify as a seat: the founding district on an owned tile
    at distance 2 (complete unless told otherwise) and the founding building."""
    pos = far_site(env, city)
    assert env.place_district(city, SEAT_DISTRICT, pos), "fixture: the seat district places"
    if complete:
        env.complete_district(city, city.districts[-1])
    city.buildings.append(SEAT_BUILDING)
    return city


def _ready(env, player_index=0, extra_faith=0):
    """A player that may found: pantheon chosen, a seat, `found_cost` faith
    (plus `extra_faith` tenths)."""
    player = env.players[player_index]
    player.pantheon = PANTHEON_ORDER[0]
    _seat(env, player.cities[0])
    player.faith = found_cost_tenths() + extra_faith
    return player


def _pair():
    """The first configured founder and follower belief."""
    return beliefs_of_tier(TIER_FOUNDER)[0], beliefs_of_tier(TIER_FOLLOWER)[0]


def _found(env, player_index=0, extra_faith=0):
    player = _ready(env, player_index, extra_faith)
    founder, follower = _pair()
    assert env.found_religion(player, founder, follower)
    return player


def _give_religion(player, founder_belief, follower_beliefs=(), enhancer=None):
    """Fixture: a religion handed to `player` without the action (tested
    elsewhere), its seat the player's first city."""
    player.religion = Religion(founder=player.player_index, founder_belief=founder_belief,
                               follower_beliefs=list(follower_beliefs), enhancer_belief=enhancer)
    player.cities[0].religion = player.player_index
    return player.religion


def _link(env, city, name, pos, complete=True):
    """Fixture only: a District linked by hand (bypasses placement rules)."""
    district = District(name, city.city_id, pos, complete=complete, cost=10, city=city)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    own(env, city, pos)
    return district


def _belief_with(kind, tier, predicate=lambda e: True):
    """A configured belief of `tier` carrying an effect of `kind` that
    satisfies `predicate`, with that effect; skip when none is configured."""
    for name in beliefs_of_tier(tier):
        for effect in effects_of(SOURCE_BELIEF, name):
            if effect.kind == kind and predicate(effect):
                return name, effect
    pytest.skip(f"no {tier} belief with a {kind} effect configured")


# --- (a) the registry -----------------------------------------------------------------------


def test_every_configured_belief_parses_with_its_tiers_scope():
    """Registry property over `[beliefs.*]`: every table validates through the
    interpreter, carries at least one effect, every effect has a consumer, is
    never a one-shot, and holds with its tier's scope -- a founder belief
    carries `per_follower_city` only (player), a follower belief city-scoped
    kinds whose consumer takes a city, an enhancer player-scoped kinds. At
    least one belief of each tier is configured. Breaks if a belief names an
    unknown kind, the tier scoping flips, or a tier is left empty."""
    assert BELIEFS, "fixture: beliefs are configured"
    for tier in TIERS:
        assert beliefs_of_tier(tier), tier
    for name, spec in BELIEFS.items():
        parsed = effects_of(SOURCE_BELIEF, name)
        assert parsed, name
        for effect in parsed:
            assert effect.kind in effects.CONSUMERS, name
            assert effect.kind not in effects.ONE_SHOT_KINDS, name
            assert effect.source == (SOURCE_BELIEF, name)
            if spec.tier == TIER_FOUNDER:
                assert effect.kind == KIND_PER_FOLLOWER_CITY, name
                assert effect.scope == effects.SCOPE_PLAYER, name
            elif spec.tier == TIER_FOLLOWER:
                assert effect.scope == effects.SCOPE_CITY, name
                assert effect.kind not in effects._PLAYER_ONLY_KINDS, name
            else:
                assert effect.scope == effects.SCOPE_PLAYER, name


@pytest.mark.parametrize("kind, entry", [
    (KIND_PER_FOLLOWER_CITY, {"kind": "per_follower_city", "gold": 1}),
    (KIND_CROSS_YIELD, {"kind": "cross_yield", "from_district": SEAT_DISTRICT,
                        "to": "production", "percent": 100}),
    (KIND_RELIGION_PARAM, {"kind": "religion_param", "range": 3}),
])
def test_a_tier_bound_kind_parses_on_its_tier_only(monkeypatch, kind, entry):
    """`per_follower_city`, `cross_yield` and `religion_param` each belong to
    one belief tier: on that tier they parse; on each other tier and on a
    policy card they raise. Breaks if a tier-bound kind leaks to another
    source (a second reader would follow)."""
    home = effects._TIER_KINDS[kind]
    for tier in TIERS:
        name = _belief(monkeypatch, f"Probe {tier}", tier, [entry])
        if tier == home:
            assert parse_effect(entry, SOURCE_BELIEF, name).kind == kind
        else:
            with pytest.raises(ValueError):
                parse_effect(entry, SOURCE_BELIEF, name)
    with pytest.raises(ValueError):
        parse_effect(entry, effects.SOURCE_POLICY, "Card")


def test_a_beliefs_entry_must_hold_with_its_tiers_scope_and_kinds(monkeypatch):
    """A follower belief refuses scope player and a player-read kind; an
    enhancer refuses scope city; a founder belief refuses any kind but
    `per_follower_city`; a name that is no belief cannot be parsed. Breaks if
    `_check_belief` drops a clause."""
    quiet = {"kind": "growth_percent", "percent": 5}
    follower = _belief(monkeypatch, "Probe F", TIER_FOLLOWER, [quiet])
    assert parse_effect(quiet, SOURCE_BELIEF, follower).scope == "city"
    with pytest.raises(ValueError):
        parse_effect({**quiet, "scope": "player"}, SOURCE_BELIEF, follower)
    with pytest.raises(ValueError):
        parse_effect({"kind": "movement_delta", "domain": "land", "amount": 1},
                     SOURCE_BELIEF, follower)
    enhancer = _belief(monkeypatch, "Probe E", TIER_ENHANCER, [quiet])
    assert parse_effect(quiet, SOURCE_BELIEF, enhancer).scope == "player"
    with pytest.raises(ValueError):
        parse_effect({**quiet, "scope": "city"}, SOURCE_BELIEF, enhancer)
    founder = _belief(monkeypatch, "Probe G", TIER_FOUNDER, [quiet])
    with pytest.raises(ValueError):
        parse_effect(quiet, SOURCE_BELIEF, founder)
    with pytest.raises(ValueError):
        parse_effect(quiet, SOURCE_BELIEF, "No Such Belief")


@pytest.mark.parametrize("tier, entry", [
    # cross_yield: the district's own adjacency yield is adjacency_percent's job
    (TIER_FOLLOWER, {"kind": "cross_yield", "from_district": SEAT_DISTRICT, "to": "faith",
                     "percent": 100}),
    (TIER_FOLLOWER, {"kind": "cross_yield", "from_district": "No Such", "to": "gold",
                     "percent": 100}),
    (TIER_FOLLOWER, {"kind": "cross_yield", "from_district": SEAT_DISTRICT, "to": "gold",
                     "percent": 0}),
    (TIER_FOLLOWER, {"kind": "cross_yield", "from_district": SEAT_DISTRICT, "to": "mana",
                     "percent": 50}),
    # per_follower_city: pool yields only, at least one
    (TIER_FOUNDER, {"kind": "per_follower_city", "food": 1}),
    (TIER_FOUNDER, {"kind": "per_follower_city"}),
    # religion_param: at least one parameter, range >= 0, cost_percent > -100
    (TIER_ENHANCER, {"kind": "religion_param"}),
    (TIER_ENHANCER, {"kind": "religion_param", "range": -1}),
    (TIER_ENHANCER, {"kind": "religion_param", "cost_percent": -100}),
    (TIER_ENHANCER, {"kind": "religion_param", "spread_amount_percent": 1.5}),
    (TIER_ENHANCER, {"kind": "religion_param", "pressure": 3}),
    # combat_strength: one religious condition, never for the city's own defence
    (TIER_ENHANCER, {"kind": "combat_strength", "applies_to": ["all"], "amount": 5,
                     "vs_city_of_other_religion": True, "in_follower_territory": True}),
    (TIER_ENHANCER, {"kind": "combat_strength", "applies_to": ["city"], "amount": 5,
                     "in_follower_territory": True}),
    (TIER_ENHANCER, {"kind": "combat_strength", "applies_to": ["all"], "amount": 5,
                     "vs_city_of_other_religion": 1}),
    # city_yield: one multiplier
    (TIER_FOLLOWER, {"kind": "city_yield", "faith": 4, "per_wonder": True, "per_district": True}),
])
def test_a_malformed_belief_effect_raises_at_load(monkeypatch, tier, entry):
    """Each bound of the Q8 parsers (design §7.3) raises at load. Breaks if a
    bound is dropped."""
    name = _belief(monkeypatch, "Probe", tier, [entry])
    with pytest.raises(ValueError):
        parse_effect(entry, SOURCE_BELIEF, name)


def test_a_religion_param_range_is_checked_against_citizen_weight(monkeypatch):
    """v3 fixes L3: `religion_param { range }` raises BOTH the range and the
    citizen weight of the religion, so the loader re-runs
    `check_pressure_weights` on the raised pair -- which holds for any range
    when the base holds. Breaks if the loader stops re-running the check."""
    name = _belief(monkeypatch, "Probe", TIER_ENHANCER, [{"kind": "religion_param", "range": 3}])
    attrs = parse_effect({"kind": "religion_param", "range": 3}, SOURCE_BELIEF, name)
    assert (attrs["range"], attrs["spread_amount_percent"], attrs["cost_percent"]) == (3, 0, 0)
    calls = []
    monkeypatch.setattr(religion_model, "check_pressure_weights",
                        lambda weight, reach, where="": calls.append((weight, reach)))
    parse_effect({"kind": "religion_param", "range": 3}, SOURCE_BELIEF, name)
    assert calls == [(RULES.citizen_weight + 3, RULES.range + 3)]


def test_founding_building_must_be_a_building_with_a_district():
    """`[religion] founding_building` names a building whose table has a
    `requires_district` -- the seat rule needs both. Breaks if the column
    loosens or is dropped."""
    table = dict(religion_model.CFG["religion"])
    assert parse_religion(table).founding_district == BUILDING_REQUIRES_DISTRICT[SEAT_BUILDING]
    with pytest.raises(ValueError):
        parse_religion({**table, "founding_building": "No Such"})
    without_district = next(b for b in sorted(unit_model.BUILDING_NAMES)
                            if BUILDING_REQUIRES_DISTRICT.get(b) is None)
    with pytest.raises(ValueError):
        parse_religion({**table, "founding_building": without_district})
    del table["founding_building"]
    with pytest.raises(ValueError):
        parse_religion(table)


def test_building_faith_categories_parse_and_name_districts(monkeypatch):
    """`[faith] purchase_building_categories` maps category -> district: a
    building is in the category when its `requires_district` is that
    district; the unit category's name, a duplicate district, a non-string
    and -- at the interpreter's load -- an unknown district raise. Breaks if
    the parser or the load-time district check loosens."""
    assert BUILDING_FAITH_CATEGORIES, "fixture: building categories are configured"
    for category, district in BUILDING_FAITH_CATEGORIES.items():
        assert category in unit_model.FAITH_CATEGORIES
        covered = [b for b, d in BUILDING_REQUIRES_DISTRICT.items() if d == district]
        assert covered, category
        assert all(building_faith_category(b) == category for b in covered)
    assert building_faith_category(SEAT_BUILDING) is None or \
        BUILDING_FAITH_CATEGORIES[building_faith_category(SEAT_BUILDING)] == SEAT_DISTRICT
    assert building_faith_category("No Such") is None
    parsed = parse_building_faith_categories({"a": "Campus"})
    assert parsed == {"a": "Campus"}
    for bad in ({FAITH_CATEGORY_LAND_MILITARY: "Campus"}, {"a": "Campus", "b": "Campus"},
                {"a": 3}, {"": "Campus"}, ["a"]):
        with pytest.raises(ValueError):
            parse_building_faith_categories(bad)
    monkeypatch.setattr(unit_model, "BUILDING_FAITH_CATEGORIES", {"a": "No Such District"})
    with pytest.raises(ValueError):
        effects._validate_registries()


# --- (b) founding ----------------------------------------------------------------------------


def test_founding_refuses_each_clause_and_a_refusal_changes_nothing():
    """`founding_refusals` names every clause of design §7.3 / v3 L1: no
    pantheon, no seat (no building; building but district incomplete), faith
    short, a wrong-tier name for either belief; `found_religion` refuses with
    them and changes nothing. Breaks if a predicate drops a clause or the
    action bypasses it."""
    env = _env()
    player = env.players[0]
    founder, follower = _pair()
    player.faith = found_cost_tenths()
    reasons = founding_refusals(player, founder, follower, env)
    assert REFUSE_NO_PANTHEON in reasons and REFUSE_NO_SEAT in reasons
    player.pantheon = PANTHEON_ORDER[0]
    city = player.cities[0]
    city.buildings.append(SEAT_BUILDING)  # the building without its district
    assert REFUSE_NO_SEAT in founding_refusals(player, founder, follower, env)
    city.buildings.remove(SEAT_BUILDING)
    _seat(env, city, complete=False)  # the district placed, not complete
    assert REFUSE_NO_SEAT in founding_refusals(player, founder, follower, env)
    env.complete_district(city, city.districts[-1])
    assert founding_refusals(player, founder, follower, env) == []
    player.faith -= 1
    assert founding_refusals(player, founder, follower, env) == [REFUSE_FAITH]
    assert not env.found_religion(player, founder, follower)
    assert player.religion is None and city.religion is None
    assert player.faith == found_cost_tenths() - 1
    player.faith += 1
    assert founding_refusals(player, follower, founder, env) == [REFUSE_NOT_FOUNDER_BELIEF,
                                                                  REFUSE_NOT_FOLLOWER_BELIEF]
    assert founding_refusals(player, "No Such", follower, env) == [REFUSE_NOT_FOUNDER_BELIEF]
    assert not env.found_religion(player, "No Such", follower)
    assert can_found_religion(player, founder, follower, env)


def test_founding_debits_exactly_the_cost_takes_the_beliefs_and_converts_the_seat_only():
    """Founding debits exactly `found_cost` (tenths), creates the religion
    (founder index, the two beliefs, no enhancer, not lapsed), marks both
    beliefs taken, converts the seat -- the qualifying own city with the
    LOWEST id, not the capital, not a non-qualifying city -- and nothing
    else; counts `religions_founded` and `faith_spent_religion`; a second
    founding is refused. Breaks if the debit is off, the seat rule reads
    another city, or the counters miss it."""
    env = _env()
    player = env.players[0]
    capital = player.cities[0]
    second = make_city(env, (3, 10))  # id 2
    third = make_city(env, (7, 4))    # id 3
    assert capital.city_id < second.city_id < third.city_id
    _seat(env, third)
    _seat(env, second)  # qualifies too, lower id -> the seat
    player.pantheon = PANTHEON_ORDER[0]
    player.faith = found_cost_tenths() + 7
    founder, follower = _pair()
    assert seat_city(player) is second
    assert env.found_religion(player, founder, follower)
    assert player.faith == 7
    religion = player.religion
    assert (religion.founder, religion.founder_belief, religion.follower_beliefs,
            religion.enhancer_belief, religion.lapsed) == (0, founder, [follower], None, False)
    assert religion.beliefs == [founder, follower]
    assert taken_beliefs(env) == [founder, follower]
    assert second.religion == 0
    assert capital.religion is None and third.religion is None
    assert env.players[1].cities[0].religion is None
    stats = env.episode_stats[0]
    assert stats["religions_founded"] == 1
    assert stats["faith_spent_religion"] == found_cost_tenths()
    player.faith = 2 * found_cost_tenths()
    assert REFUSE_HAS_RELIGION in founding_refusals(player, founder, follower, env)
    assert not env.found_religion(player, founder, follower)


def test_exclusive_denies_a_taken_belief_and_caps_religions_at_the_founder_beliefs(monkeypatch):
    """Under `exclusive`, a belief another religion holds is refused
    (REFUSE_TAKEN), and once every founder belief is taken founding is
    refused for want of one (v3 fixes L4, REFUSE_NO_FOUNDER_BELIEF_LEFT)
    whatever `max_religions` says; with `exclusive = false` both religions
    may hold the same beliefs. Breaks if exclusivity is checked on one tier
    only, or the founder-belief cap is dropped."""
    env = _env()
    quiet = [{"kind": "growth_percent", "percent": 5}]
    monkeypatch.setattr(religion_model, "BELIEFS", {})
    only_founder = _belief(monkeypatch, "Only Founder", TIER_FOUNDER,
                           [{"kind": "per_follower_city", "gold": 1}])
    first, other = (_belief(monkeypatch, "W1", TIER_FOLLOWER, quiet),
                    _belief(monkeypatch, "W2", TIER_FOLLOWER, quiet))
    one, two = _ready(env, 1), _ready(env, 0)
    assert env.found_religion(one, only_founder, first)
    reasons = founding_refusals(two, only_founder, first, env)
    assert REFUSE_NO_FOUNDER_BELIEF_LEFT in reasons
    assert reasons.count(REFUSE_TAKEN) == 2
    assert REFUSE_TAKEN in founding_refusals(two, only_founder, other, env)
    assert not env.found_religion(two, only_founder, other)
    assert two.religion is None
    monkeypatch.setattr(religion_mod, "RULES", replace(RULES, exclusive=False))
    assert founding_refusals(two, only_founder, first, env) == []
    assert env.found_religion(two, only_founder, first)
    assert one.religion.beliefs == two.religion.beliefs


def test_max_religions_caps_the_count_and_zero_is_unlimited(monkeypatch):
    """`max_religions = 1` refuses a second founding (REFUSE_MAX_RELIGIONS);
    0 lets every player found. Breaks if the cap misreads 0 or counts
    wrong."""
    env = _env()
    one, two = _ready(env, 1), _ready(env, 0)
    founder_a, founder_b = beliefs_of_tier(TIER_FOUNDER)[:2]
    follower_a, follower_b = beliefs_of_tier(TIER_FOLLOWER)[:2]
    monkeypatch.setattr(religion_mod, "RULES", replace(RULES, max_religions=1))
    assert env.found_religion(one, founder_a, follower_a)
    assert founding_refusals(two, founder_b, follower_b, env) == [REFUSE_MAX_RELIGIONS]
    monkeypatch.setattr(religion_mod, "RULES", replace(RULES, max_religions=0))
    assert founding_refusals(two, founder_b, follower_b, env) == []
    assert env.found_religion(two, founder_b, follower_b)


# --- (c) beliefs after founding -------------------------------------------------------------


def test_add_belief_climbs_the_ladder_in_tier_order_at_its_costs():
    """After founding, tier 2 (a second follower belief, `belief_costs[0]`)
    must be bought before tier 3 (the enhancer, `belief_costs[1]`); each
    debits exactly its cost, is refused when faith is short, a wrong-tier
    name, a held belief or a taken one; a fourth purchase is refused (the
    ladder is climbed). Breaks if the order, a cost or a clause changes."""
    env = _env()
    player = _found(env)
    religion = player.religion
    founder, follower = _pair()
    second = beliefs_of_tier(TIER_FOLLOWER)[1]
    enhancer = beliefs_of_tier(TIER_ENHANCER)[0]
    assert religion.due_tier == TIER_FOLLOWER
    assert belief_refusals(player, enhancer, env) == [REFUSE_FAITH, REFUSE_WRONG_TIER]
    player.faith = belief_cost_tenths(0) - 1
    assert belief_refusals(player, second, env) == [REFUSE_FAITH]
    assert not env.add_belief(player, second)
    player.faith += 1 + 5
    assert belief_refusals(player, follower, env) == [REFUSE_WRONG_TIER, REFUSE_ALREADY_HELD] \
        or REFUSE_ALREADY_HELD in belief_refusals(player, follower, env)
    assert not env.add_belief(player, enhancer)
    assert env.add_belief(player, second)
    assert player.faith == 5
    assert religion.follower_beliefs == [follower, second]
    assert religion.due_tier == TIER_ENHANCER
    player.faith = belief_cost_tenths(1) + 3
    assert belief_refusals(player, second, env) == [REFUSE_WRONG_TIER, REFUSE_ALREADY_HELD]
    assert env.add_belief(player, enhancer)
    assert player.faith == 3
    assert religion.enhancer_belief == enhancer
    assert religion.due_tier is None
    player.faith = 10 * belief_cost_tenths(1)
    for name in beliefs_of_tier(TIER_FOLLOWER) + beliefs_of_tier(TIER_ENHANCER):
        assert REFUSE_LADDER_CLIMBED in belief_refusals(player, name, env)
        assert not env.add_belief(player, name)
    stats = env.episode_stats[0]
    assert stats["beliefs_added"] == 2
    assert stats["faith_spent_religion"] == (found_cost_tenths() + belief_cost_tenths(0)
                                             + belief_cost_tenths(1))
    other = env.players[1]
    assert belief_refusals(other, second, env) == [REFUSE_NO_RELIGION]
    other.faith = 10 * belief_cost_tenths(1)
    assert not env.add_belief(other, second)


def test_a_belief_another_religion_holds_cannot_be_added_under_exclusive():
    """Two religions: the second cannot add a follower belief the first
    already holds (REFUSE_TAKEN), but may add a free one. Breaks if
    `add_belief` skips the exclusivity clause."""
    env = _env()
    followers = beliefs_of_tier(TIER_FOLLOWER)
    founders = beliefs_of_tier(TIER_FOUNDER)
    one, two = _ready(env, 1), _ready(env, 0)
    assert env.found_religion(one, founders[0], followers[0])
    assert env.found_religion(two, founders[1], followers[1])
    one.faith = two.faith = belief_cost_tenths(0)
    assert env.add_belief(one, followers[2])
    assert belief_refusals(two, followers[2], env) == [REFUSE_TAKEN]
    assert not env.add_belief(two, followers[2])
    assert can_add_belief(two, followers[3], env)


# --- (d) the follower source ----------------------------------------------------------------


def test_follower_beliefs_hold_in_a_foreign_follower_city_and_not_elsewhere(monkeypatch):
    """A follower belief is in force in every city that follows the religion
    -- the founder's seat and a city ANOTHER player owns -- and in no city
    that does not, not even the founder's own secular city; it is
    city-scoped and carries the follower city as `source_city`. Breaks if
    `active_effects` misses the `belief` source, reads the owner instead of
    `city.religion`, or leaks it (§11 "Follower beliefs apply to a foreign
    follower city")."""
    env = _env()
    founder, other = env.players
    name = _belief(monkeypatch, "Probe", TIER_FOLLOWER, [{"kind": "city_yield", "science": 1}])
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [name])
    seat = founder.cities[0]
    secular = make_city(env, (3, 10))
    foreign = other.cities[0]
    foreign.religion = founder.player_index
    source = (SOURCE_BELIEF, name)

    def sources(player, city):
        return [(e.source, e.scope, e.source_city) for e in active_effects(player, city)]

    assert (source, "city", seat) in sources(founder, seat)
    assert (source, "city", foreign) in sources(other, foreign)
    assert source not in [s for s, _, _ in sources(founder, secular)]
    assert source not in [s for s, _, _ in sources(founder, None)]
    assert source not in [s for s, _, _ in sources(other, None)]
    following = city_yield(foreign, "science")
    foreign.religion = None
    assert following - city_yield(foreign, "science") == 10


def test_a_follower_belief_with_requires_building_holds_only_where_the_building_stands():
    """A follower belief that `requires_building` (Feed the World) is in
    force only in a follower city holding that building; without it, the
    city follows but gets nothing. Breaks if the source ignores the column."""
    env = _env()
    founder = env.players[0]
    name = next((n for n in beliefs_of_tier(TIER_FOLLOWER) if BELIEFS[n].requires_building),
                None)
    if name is None:
        pytest.skip("no follower belief with requires_building configured")
    building = BELIEFS[name].requires_building
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [name])
    seat = founder.cities[0]
    assert building not in seat.buildings
    assert (SOURCE_BELIEF, name) not in [e.source for e in active_effects(founder, seat)]
    seat.buildings.append(building)
    assert (SOURCE_BELIEF, name) in [e.source for e in active_effects(founder, seat)]


def test_the_enhancer_belief_holds_for_the_founder_only(monkeypatch):
    """An enhancer belief is player-scoped and in force for the founder (and
    in each of its cities), never for a follower of another player. Breaks
    if the enhancer joins the follower source."""
    env = _env()
    founder, other = env.players
    name = _belief(monkeypatch, "Probe", TIER_ENHANCER, [{"kind": "growth_percent", "percent": 5}])
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [], enhancer=name)
    other.cities[0].religion = founder.player_index
    source = (SOURCE_BELIEF, name)
    assert source in [e.source for e in active_effects(founder)]
    assert source in [e.source for e in active_effects(founder, founder.cities[0])]
    assert source not in [e.source for e in active_effects(other, other.cities[0])]


# --- (e) founder pay ------------------------------------------------------------------------


def test_founder_pay_counts_all_or_foreign_follower_cities_in_tenths(monkeypatch):
    """A founder belief with `counts = "all"` pays its tenths per follower
    city of any owner; one with `counts = "foreign"` only per follower city
    another player owns; a secular city pays nothing; the economy phase
    adds exactly that to the pools and counts `founder_pay_tenths`. Breaks
    if the count misreads `counts`, pays whole points, or pays a city that
    does not follow."""
    env = _env()
    founder, other = env.players
    make_city(env, (3, 10))
    all_belief = _belief(monkeypatch, "Pays All", TIER_FOUNDER,
                         [{"kind": "per_follower_city", "gold": 1, "culture": 0.5}],
                         counts=religion_model.COUNTS_ALL)
    foreign_belief = _belief(monkeypatch, "Pays Foreign", TIER_FOUNDER,
                             [{"kind": "per_follower_city", "faith": 2}],
                             counts=religion_model.COUNTS_FOREIGN)
    _give_religion(founder, all_belief)
    assert founder_pay_tenths(founder, env) == {"gold": 10, "culture": 5}
    other.cities[0].religion = founder.player_index
    assert founder_pay_tenths(founder, env) == {"gold": 20, "culture": 10}
    founder.religion.founder_belief = foreign_belief
    assert founder_pay_tenths(founder, env) == {"faith": 20}
    other.cities[0].religion = None
    assert founder_pay_tenths(founder, env) == {}
    assert founder_pay_tenths(other, env) == {}
    other.cities[0].religion = founder.player_index
    gold, faith = founder.gold, founder.faith
    founder.religion.founder_belief = all_belief
    env._founder_pay(founder)
    assert (founder.gold, founder.faith) == (gold + 20, faith)
    assert env.episode_stats[0]["founder_pay_tenths"] == 30
    assert env.episode_stats[1]["founder_pay_tenths"] == 0


def test_a_dead_founder_is_paid_nothing_while_its_followers_keep_their_beliefs(monkeypatch):
    """The founder loses its only city by capture and dies: its religion is
    still readable from the dead Player, the captured city keeps following
    it, the follower beliefs still hold there for the new owner, and founder
    pay is nothing (v3 fixes L2, §7.5). Breaks if elimination or capture
    clears religion state, or pay ignores `is_dead`."""
    env = _env()
    founder, other = env.players
    follower = _belief(monkeypatch, "Probe", TIER_FOLLOWER, [{"kind": "city_yield", "science": 1}])
    pays = _belief(monkeypatch, "Pays", TIER_FOUNDER, [{"kind": "per_follower_city", "gold": 1}])
    _give_religion(founder, pays, [follower])
    seat = founder.cities[0]
    assert founder_pay_tenths(founder, env) == {"gold": 10}
    seat.health = 0
    raider = stand(env, "Warrior", 1, tuple(seat.coordinates))
    env._capture_city(raider, seat)
    assert seat.player is other
    founder.end_turn()
    assert founder.is_dead and founder.religion is not None
    assert seat.religion == founder.player_index
    assert (SOURCE_BELIEF, follower) in [e.source for e in active_effects(other, seat)]
    assert effects.followed_religion(seat) is founder.religion
    assert founder_pay_tenths(founder, env) == {}
    gold = founder.gold
    env._founder_pay(founder)
    assert founder.gold == gold
    assert env.episode_stats[0]["founder_pay_tenths"] == 0


def test_a_city_keeps_its_religion_through_capture_and_flip():
    """`City.religion` is the city's, not the owner's: it survives
    `_capture_city` and `_flip_city` (both doors of `set_owner`). Breaks if
    `set_owner` or either door clears it (§11)."""
    env = _env()
    founder, other = env.players
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0])
    captured = founder.cities[0]
    flipped = make_city(env, (3, 10))
    flipped.religion = founder.player_index
    captured.health = 0
    env._capture_city(stand(env, "Warrior", 1, tuple(captured.coordinates)), captured)
    assert captured.player is other and captured.religion == founder.player_index
    env._flip_city(flipped, other)
    assert flipped.player is other and flipped.religion == founder.player_index


# --- (f) cross_yield and per_wonder -------------------------------------------------------


def test_cross_yield_pays_the_floored_share_of_the_right_districts_adjacency(monkeypatch):
    """A `cross_yield` from the seat district pays `floor(score * percent /
    100)` in tenths of its `to` yield for each COMPLETE district of that
    type in a follower city -- the raw adjacency score, so the district's own
    yield is unchanged -- and nothing for an incomplete one or another type.
    Breaks if the term reads the boosted score, skips the floor, or pays the
    wrong yield."""
    env = _env()
    founder = env.players[0]
    city = founder.cities[0]
    _seat(env, city)
    district = city.districts[-1]
    # The all-Plains board gives the seat district no adjacency of its own; an
    # owner's `adjacency_row` (v0.9.0 Q7) for the board's base terrain gives it
    # one per neighbour, so the score is read at run time, never pinned.
    base = env.map.get_tile(city.coordinates).base_terrain
    pantheon = "Probe Pantheon"
    monkeypatch.setitem(religion_model.PANTHEONS, pantheon, religion_model.PantheonSpec(
        name=pantheon, effects=({"kind": "adjacency_row", "district": SEAT_DISTRICT,
                                 "amount": 1, "terrain": {"bases": [base]}},)))
    founder.pantheon = pantheon
    score = adjacency_score(SEAT_DISTRICT, district.coordinates, env.map, founder)
    assert score >= 1, "fixture: the seat district has some adjacency"
    own_yield = district_spec(SEAT_DISTRICT).adjacency_yield
    to = next(y for y in POOL_YIELDS if y != own_yield)
    name = _belief(monkeypatch, "Probe", TIER_FOLLOWER,
                   [{"kind": "cross_yield", "from_district": SEAT_DISTRICT, "to": to,
                     "percent": 33}])
    before = {y: city_yield(city, y) for y in YIELD_COLUMNS}
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [name])
    after = {y: city_yield(city, y) for y in YIELD_COLUMNS}
    assert after[to] - before[to] == 10 * score * 33 // 100
    assert {y for y in YIELD_COLUMNS if after[y] != before[y]} == {to}
    district.complete = False
    assert city_yield(city, to) == before[to]


def test_per_wonder_counts_complete_wonders_only(monkeypatch):
    """A `city_yield` with `per_wonder` pays its amount times the city's
    COMPLETE wonders: 0 with none or an unfinished one, the amount per
    complete wonder. Breaks if the multiplier counts placed wonders or
    specialty districts."""
    wonders = [n for n, s in district_model.DISTRICTS.items()
               if s.kind == district_model.KIND_WONDER]
    if len(wonders) < 2:
        pytest.skip("fewer than two wonders configured")
    env = _env()
    founder = env.players[0]
    city = founder.cities[0]
    name = _belief(monkeypatch, "Probe", TIER_FOLLOWER,
                   [{"kind": "city_yield", "faith": 4, "per_wonder": True}])
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [name])

    def paid_by_belief():
        """The belief's share: the city's faith with the religion minus
        without it (a real wonder may carry a faith column of its own)."""
        with_belief = city_yield(city, "faith")
        city.religion, index = None, city.religion
        without = city_yield(city, "faith")
        city.religion = index
        return with_belief - without

    sites = ring(env, city.coordinates, 2)
    assert paid_by_belief() == 0
    first = _link(env, city, wonders[0], sites[0], complete=False)
    assert paid_by_belief() == 0
    first.complete = True
    assert paid_by_belief() == 40
    _link(env, city, wonders[1], sites[1], complete=True)
    assert paid_by_belief() == 80


# --- (g) purchasing ------------------------------------------------------------------------


def test_a_faith_purchase_belief_buys_a_categorys_building_with_faith_and_no_other():
    """With the follower belief unlocking building categories in force, a
    building of a covered district (requires_district) may be bought with
    faith -- through `GameEnvironment.purchase`, appended like a built one --
    while a building of an uncovered district may not; without the belief
    neither may. Breaks if `can_purchase` lacks the building branch or the
    category misreads the district."""
    name, effect = _belief_with(KIND_FAITH_PURCHASE, TIER_FOLLOWER)
    categories = [c for c in effect["categories"] if c in BUILDING_FAITH_CATEGORIES]
    if not categories:
        pytest.skip("the faith_purchase belief unlocks no building category")
    env = _env()
    player = env.players[0]
    city = player.cities[0]
    city.population = 9
    from civulator.game.availability import city_can_build_building
    sites = ring(env, city.coordinates, 2)

    def buildable(district):
        """The first building (sorted) of `district` the city could start
        once it holds that district complete, not faith-purchasable by its
        column; None when the district offers none (a government-tier gate)."""
        return next((b for b, d in sorted(BUILDING_REQUIRES_DISTRICT.items())
                     if d == district and "faith" not in BUILDING_PURCHASABLE.get(b, ())
                     and city_can_build_building(city, b)), None)

    covered_district = BUILDING_FAITH_CATEGORIES[categories[0]]
    _link(env, city, covered_district, sites[0])
    covered = buildable(covered_district)
    assert covered is not None, "fixture: the covered district has a buildable building"
    # The first uncovered district (sorted, never a set walk) with a
    # buildable building; its district is linked only once chosen.
    uncovered = uncovered_district = None
    for district in sorted(set(BUILDING_REQUIRES_DISTRICT.values()) - {None}):
        if district in BUILDING_FAITH_CATEGORIES.values():
            continue
        linked = _link(env, city, district, sites[1])
        uncovered = buildable(district)
        if uncovered is not None:
            uncovered_district = district
            break
        city.districts.remove(linked)
        env.map.get_tile(sites[1]).district = None
    assert uncovered is not None, "fixture: some uncovered district has a buildable building"
    player.faith = 10 ** 6
    assert not can_purchase(player, city, "building", covered, "faith")
    _give_religion(player, beliefs_of_tier(TIER_FOUNDER)[0], [name])
    assert can_purchase(player, city, "building", covered, "faith")
    assert not can_purchase(player, city, "building", uncovered, "faith")
    env.current_player = player
    assert env.purchase(city, "building", covered, "faith")
    assert covered in city.buildings
    assert not env.purchase(city, "building", uncovered, "faith")
    assert player.faith < 10 ** 6


# --- (h) the two combat beliefs ------------------------------------------------------------


def _conditional(attribute):
    name, effect = _belief_with(KIND_COMBAT_STRENGTH, TIER_ENHANCER, lambda e: e[attribute])
    return name, effect["amount"]


def test_crusade_applies_against_a_city_or_fortification_of_another_or_no_religion():
    """The `vs_city_of_other_religion` enhancer adds its amount to the
    founder's units attacking a city, or a fortified district, that follows
    another religion or none -- melee and ranged strength alike -- and
    nothing against a city following the founder's own religion, nothing
    against a unit, nothing when defending (v3 fixes L9). Breaks if the
    condition reads the owner instead of `City.religion`, misses the
    district's city, or is applied in one strength only."""
    name, amount = _conditional("vs_city_of_other_religion")
    env = _env()
    defender, attacker = env.players
    target_city = defender.cities[0]
    fort_type = next((n for n, s in district_model.DISTRICTS.items() if s.health is not None),
                     None)
    sites = ring(env, target_city.coordinates, 2)
    fort = _link(env, target_city, fort_type, sites[0]) if fort_type else None
    if fort is not None:
        fort.health = fort.max_health
    melee = stand(env, "Warrior", 1, (5, 4))
    archer = stand(env, "Archer", 1, (5, 5))
    enemy_unit = stand(env, "Warrior", 0, (6, 4))
    plain = (melee.get_combat_strength(True, target_city),
             archer.get_ranged_strength(target_city, True),
             melee.get_combat_strength(True, enemy_unit),
             melee.get_combat_strength(False, enemy_unit),
             None if fort is None else melee.get_combat_strength(True, fort))
    _give_religion(attacker, beliefs_of_tier(TIER_FOUNDER)[0], [], enhancer=name)
    boosted = (melee.get_combat_strength(True, target_city),
               archer.get_ranged_strength(target_city, True),
               melee.get_combat_strength(True, enemy_unit),
               melee.get_combat_strength(False, enemy_unit),
               None if fort is None else melee.get_combat_strength(True, fort))
    assert boosted[0] == plain[0] + amount
    assert boosted[1] == plain[1] + amount
    assert boosted[2:4] == plain[2:4]
    if fort is not None:
        assert boosted[4] == plain[4] + amount
    target_city.religion = attacker.player_index  # the city adopts the attacker's religion
    assert melee.get_combat_strength(True, target_city) == plain[0]
    assert archer.get_ranged_strength(target_city, True) == plain[1]
    if fort is not None:
        assert melee.get_combat_strength(True, fort) == plain[4]
    target_city.religion = defender.player_index  # another religion
    _give_religion(defender, beliefs_of_tier(TIER_FOUNDER)[1])
    assert melee.get_combat_strength(True, target_city) == plain[0] + amount


def test_defender_of_the_faith_reads_the_receiving_units_tile_in_both_roles():
    """The `in_follower_territory` enhancer adds its amount to a founder's
    unit standing on a tile owned by a city that follows the founder's
    religion -- whoever owns the city -- attacking and defending, melee and
    ranged; nothing on a tile owned by a secular city or unowned, nothing to
    the enemy standing on the follower tile (v3 fixes L9: the RECEIVING
    unit's tile and religion). Breaks if the condition reads the target's
    tile, the owner, or one role only."""
    name, amount = _conditional("in_follower_territory")
    env = _env()
    founder, other = env.players
    home = founder.cities[0]
    foreign = other.cities[0]
    on_home = next(p for p in ring(env, home.coordinates, 1))
    on_foreign = next(p for p in ring(env, foreign.coordinates, 1))
    nowhere = (7, 8)
    assert env.map.owner_id_at(on_home) == home.city_id
    assert env.map.owner_id_at(on_foreign) == foreign.city_id
    assert env.map.owner_id_at(nowhere) == -1
    unit_home = stand(env, "Warrior", 0, on_home)
    archer_home = stand(env, "Archer", 0, ring(env, home.coordinates, 1)[1])
    unit_foreign = stand(env, "Warrior", 0, on_foreign)
    unit_nowhere = stand(env, "Warrior", 0, nowhere)
    enemy = stand(env, "Warrior", 1, ring(env, home.coordinates, 1)[2])

    def strengths():
        return (unit_home.get_combat_strength(True, enemy),
                unit_home.get_combat_strength(False, enemy),
                archer_home.get_ranged_strength(enemy),
                unit_foreign.get_combat_strength(True, enemy),
                unit_nowhere.get_combat_strength(True, enemy),
                enemy.get_combat_strength(True, unit_home),
                enemy.get_combat_strength(False, unit_home))

    plain = strengths()
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [], enhancer=name)
    boosted = strengths()
    assert boosted[0] == plain[0] + amount and boosted[1] == plain[1] + amount
    assert boosted[2] == plain[2] + amount
    assert boosted[3:] == plain[3:]
    foreign.religion = founder.player_index  # the other player's city adopts it
    assert unit_foreign.get_combat_strength(True, enemy) == plain[3] + amount
    home.religion = None  # the founder's own city lapses into secularity
    assert unit_home.get_combat_strength(True, enemy) == plain[0]
    assert archer_home.get_ranged_strength(enemy) == plain[2]


def test_the_city_s_own_defence_takes_no_religious_condition(monkeypatch):
    """A `combat_strength` entry carrying a religious condition never
    reaches `City.get_combat_strength` (the loader refuses "city" in
    `applies_to`), and the unconditional city entries still do. Breaks if
    the conditions are evaluated for the city as a receiver."""
    env = _env()
    founder = env.players[0]
    city = founder.cities[0]
    base = city.get_combat_strength()
    name = _belief(monkeypatch, "Probe", TIER_ENHANCER,
                   [{"kind": "combat_strength", "applies_to": ["all"], "amount": 5,
                     "in_follower_territory": True}])
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [], enhancer=name)
    assert city.get_combat_strength() == base


# --- (i) religion_param: parsed, in force for the founder, consumer named for Q9 ----------


def test_religion_param_parses_is_in_force_for_the_founder_and_names_its_consumer(monkeypatch):
    """A `religion_param` enhancer parses to its three ints, is in force for
    the founder (player scope) and nowhere else, and `CONSUMERS` names its
    reader in `game/religion.py` (Q9's pressure rules); no kind is deferred.
    Breaks if the kind is dropped, read for a follower, or left without a
    named consumer."""
    env = _env()
    founder, other = env.players
    name = _belief(monkeypatch, "Probe", TIER_ENHANCER,
                   [{"kind": "religion_param", "range": 3, "cost_percent": -30}])
    _give_religion(founder, beliefs_of_tier(TIER_FOUNDER)[0], [], enhancer=name)
    other.cities[0].religion = founder.player_index
    in_force = active_effects(founder, kind=KIND_RELIGION_PARAM)
    assert [(e["range"], e["spread_amount_percent"], e["cost_percent"]) for e in in_force] \
        == [(3, 0, -30)]
    assert active_effects(other, other.cities[0], KIND_RELIGION_PARAM) == []
    assert "game/religion.py" in effects.CONSUMERS[KIND_RELIGION_PARAM]
    assert not effects.DEFERRED_KINDS


# --- (j) the engine defaults ----------------------------------------------------------------


def test_the_founding_default_takes_the_first_free_pair_in_config_order():
    """`default_found_religion` returns (first free founder belief, first
    free follower belief) in config order when the player may found, None
    otherwise; the economy phase applies it; after one player founds, the
    next default skips the taken beliefs. Breaks if the default reads a set,
    ranks differently, or founds when the predicate refuses."""
    env = _env()
    founders, followers = beliefs_of_tier(TIER_FOUNDER), beliefs_of_tier(TIER_FOLLOWER)
    first, second = env.players
    assert default_found_religion(first, env) is None
    _ready(env, first.player_index)
    first.faith -= 1
    assert default_found_religion(first, env) is None
    first.faith += 1
    assert default_found_religion(first, env) == (founders[0], followers[0])
    env.economy_phase(first)
    assert first.religion.beliefs == [founders[0], followers[0]]
    assert first.cities[0].religion == first.player_index
    _ready(env, second.player_index)
    assert default_found_religion(second, env) == (founders[1], followers[1])
    env.economy_phase(second)
    assert second.religion.beliefs == [founders[1], followers[1]]
    assert default_found_religion(second, env) is None


def test_the_belief_default_takes_the_first_free_belief_of_the_due_tier():
    """`default_add_belief` returns the first free belief of the due tier in
    config order when affordable (a second follower belief, then the
    enhancer), None when short of faith or once the ladder is climbed; the
    economy phase applies it. Breaks if the default skips the tier order or
    the predicate."""
    env = _env()
    followers, enhancers = beliefs_of_tier(TIER_FOLLOWER), beliefs_of_tier(TIER_ENHANCER)
    player = _found(env)
    assert default_add_belief(player, env) is None
    player.faith = belief_cost_tenths(0)
    assert default_add_belief(player, env) == followers[1]
    env.economy_phase(player)
    assert player.religion.follower_beliefs == [followers[0], followers[1]]
    player.faith = belief_cost_tenths(1) - 1
    assert default_add_belief(player, env) is None
    player.faith += 1
    assert default_add_belief(player, env) == enhancers[0]
    env.economy_phase(player)
    assert player.religion.enhancer_belief == enhancers[0]
    player.faith = 10 * belief_cost_tenths(1)
    assert default_add_belief(player, env) is None


def test_the_religion_step_runs_founding_belief_and_pay_in_order(monkeypatch):
    """One economy phase for a player with a seat and plenty of faith: it
    founds (the seat follows), buys the second follower belief, and is paid
    for its seat in the SAME step -- founder pay after the choices. Breaks
    if the step order changes or pay skips a religion founded this turn."""
    env = _env()
    player = _ready(env, 0, extra_faith=belief_cost_tenths(0))
    pays = _belief(monkeypatch, "Pays First", TIER_FOUNDER,
                   [{"kind": "per_follower_city", "gold": 1}])
    monkeypatch.setattr(religion_model, "BELIEFS",
                        {pays: religion_model.BELIEFS[pays],
                         **{n: s for n, s in BELIEFS.items() if s.tier != TIER_FOUNDER}})
    gold = player.gold
    env.economy_phase(player)
    assert player.religion.founder_belief == pays
    assert len(player.religion.follower_beliefs) == 2
    assert player.cities[0].religion == 0
    assert env.episode_stats[0]["founder_pay_tenths"] == 10
    assert player.gold >= gold + 10 - env.episode_stats[0]["gold_maintenance"]


def test_same_seed_same_religions():
    """Two seeded games, each player handed a seat, a pantheon and the
    founding and belief costs at the start: the same religions with the same
    beliefs are founded in the same cities. Breaks if a default draws
    randomness or iterates a set."""
    def play():
        env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=7)
        for player in env.players:
            player.pantheon = PANTHEON_ORDER[0]
            city = player.cities[0]
            city.buildings.append(SEAT_BUILDING)
            _link(env, city, SEAT_DISTRICT, ring(env, city.coordinates, 1)[0])
            player.faith = found_cost_tenths() + belief_cost_tenths(0)
        for _ in range(2 * 3):
            env.next_turn()
        return [(p.religion.beliefs if p.religion else None, p.faith,
                 [c.religion for c in p.cities]) for p in env.players]

    first = play()
    assert first == play()
    assert all(beliefs is not None for beliefs, _, _ in first)
    assert first[0][0] != first[1][0]
