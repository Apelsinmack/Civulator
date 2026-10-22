"""Issue #116 P4: the effects interpreter (docs/progression_design.md §3, §5,
"v2 fixes"; the §14 rows "Every effects entry ... raises at load", "Each
effect kind is consumed exactly where §3 says", and the summing rule N3).

Every kind is exercised through a synthetic source added to the registries
for one test only (a policy card, or a civic for `policy_slots`, which no
card may carry): the test slots it on a player and shows that the kind's one
consumer moves -- and that nothing else a consumer computes does. No test
pins which effects, cards, governments or civics are configured, or how
many; the real config is checked by properties over its registries.
"""

import pytest

from civulator import district_model, effects, research_model, unit_model
from civulator.effects import (
    APPLIES_ALL,
    APPLIES_CITY,
    COMBAT_STRENGTH_CLASSES,
    CONSUMERS,
    DEFERRED_KINDS,
    KINDS,
    RULE_FLANKING,
    active_effects,
    effects_of,
    parse_effect,
    rule_enabled,
    slot_counts,
)
from civulator import religion_model
from civulator.game import amenities, districts as districts_mod, territory
from civulator.game.housing import housing
from civulator.game.loyalty import loyalty_delta
from civulator.game.maintenance import maintenance_due
from civulator.game.purchasing import faith_purchase_categories, purchase_cost
from civulator.game.religion import Religion, founder_pay_tenths
from civulator.game.trade import DURATION_TURNS, TradeRoute, route_capacity, route_yields
from civulator.game.unit import MOVEMENT_DOMAIN, is_land_military
from civulator.game.upgrades import upgrade_cost
from civulator.game.yields import city_yield
from civulator.research_model import CIVIC_ORDER, CIVICS
from civulator.unit_model import CAPITAL_BUILDING, YIELD_COLUMNS

from conftest import stand, synthetic_civic, synthetic_government, synthetic_policy
from test_districts import board, make_city, neighbours, own, ring


# v0.9.0 Q2: this module pins other rules' exact arithmetic, not the amenity band.
pytestmark = pytest.mark.usefixtures("neutral_amenities")

# A civic with no effects of its own: what the synthetic sources unlock with,
# so no configured civic effect is in force on the staged player.
QUIET = next(c for c in CIVIC_ORDER if not CIVICS[c].effects)
CARD = "Synthetic Card"
GOVERNMENT = "Synthetic Government"


def _registry(monkeypatch):
    """A synthetic district registry: Probe (+3 gold per adjacent Marker),
    Marker (no yield), Aside (takes no population slot: not a specialty
    district), Relic (a wonder, for `per_wonder`; v0.9.0 Q8). Patched where
    every reader looks (`districts.district_spec`)."""
    reg = district_model.parse_districts({
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Probe": {"production_cost": 10, "adjacency_yield": "gold",
                  "adjacency": [{"amount": 3, "district": ["Marker"]}]},
        "Marker": {"production_cost": 10},
        "Aside": {"production_cost": 10, "counts_toward_limit": False},
        "Relic": {"kind": "wonder", "era": "Ancient", "production_cost": 100,
                  "cost_model": "fixed", "counts_toward_limit": False, "max_per_city": 1,
                  "max_per_player": 1},
    })
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    return reg


def _put(env, city, name, pos, complete=True):
    """Fixture only: link a District by hand (synthetic types bypass placement)."""
    district = districts_mod.District(name, city.city_id, pos, complete=complete, cost=10)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def _unit_types():
    """(fighter, shooter): a land melee-strength unit with an upgrade, and a
    land ranged unit of another fighting class -- derived from the unit
    tables. Land (`is_land_military`, v0.9.0 Q5): the stage is a land board,
    where a ship could be neither built nor stood."""
    fighter = next(
        u for u in sorted(unit_model.UPGRADES_TO)
        if unit_model.BASE_COMBAT_STRENGTH[u] > 0 and unit_model.BASE_RANGED_STRENGTH[u] == 0
        and unit_model.COMBAT_CLASS[u] in COMBAT_STRENGTH_CLASSES and is_land_military(u))
    shooter = next(
        u for u in sorted(unit_model.UNIT_NAMES)
        if unit_model.BASE_RANGED_STRENGTH[u] > 0 and is_land_military(u)
        and unit_model.COMBAT_CLASS[u] in COMBAT_STRENGTH_CLASSES
        and unit_model.COMBAT_CLASS[u] != unit_model.COMBAT_CLASS[fighter])
    return fighter, shooter


class Stage:
    """A player with a synthetic government of two wildcard slots and no
    card slotted; its capital (population 3) holds a complete Probe beside a
    complete Marker (two specialty districts, gold adjacency 3) and an
    Aside, and is producing the fighter; a fighter and a shooter of its own
    stand beside an enemy, with no other unit near it (no flanking). The
    capital runs one trade route to a city of the other player (#116 P5)."""

    def __init__(self, monkeypatch):
        _registry(monkeypatch)
        self.env = env = board()
        self.player = player = env.players[0]
        player.civics[:] = [QUIET]
        synthetic_government(monkeypatch, GOVERNMENT, {"wildcard": 2}, requires_civic=QUIET)
        self.city = city = make_city(env, (3, 4), population=3)
        city.assign_tiles(env)
        probe = ring(env, city.coordinates, 2)[0]
        marker = next(n for n in neighbours(env, probe) if n != tuple(city.coordinates)
                      and env.map.get_tile(n).city is None)
        aside = next(p for p in ring(env, city.coordinates, 2) if p not in (probe, marker))
        _put(env, city, "Probe", probe)
        _put(env, city, "Marker", marker)
        _put(env, city, "Aside", aside)
        self.fighter_type, self.shooter_type = _unit_types()
        assert city.produce_unit(self.fighter_type)
        self.fighter = stand(env, self.fighter_type, 0, (6, 10))
        self.enemy = stand(env, self.fighter_type, 1, (6, 11))
        self.shooter = stand(env, self.shooter_type, 0, (2, 13))
        self.partner = make_city(env, (0, 8), player_index=1)
        self.route = TradeRoute(city.city_id, self.partner.city_id, player.player_index,
                                DURATION_TURNS)
        player.routes.append(self.route)
        assert env.set_government(player, GOVERNMENT)
        assert env.set_policies(player, [])

    def slot(self, monkeypatch, entries, card_type="economic", name=CARD):
        synthetic_policy(monkeypatch, name, entries, type=card_type, requires_civic=QUIET)
        assert self.env.set_policies(self.player, [*self.player.policies, name]), entries

    def fingerprint(self):
        """Everything a wired consumer computes for this stage."""
        env, city = self.env, self.city
        out = {f"yield {y}": city_yield(city, y) for y in YIELD_COLUMNS}
        out["production"] = city.calculate_production(env)
        out["housing"] = housing(city)
        out["fighter attack"] = self.fighter.get_combat_strength(True, self.enemy)
        out["fighter defence"] = self.fighter.get_combat_strength(False, self.enemy)
        out["shooter ranged"] = self.shooter.get_ranged_strength(self.enemy)
        out["shooter defence"] = self.shooter.get_combat_strength(False, self.enemy)
        # v0.9.0 Q8: the same two strengths aimed at the other player's city
        # (what `vs_city_of_other_religion` reads).
        out["fighter attack on city"] = self.fighter.get_combat_strength(True, self.partner)
        out["shooter ranged on city"] = self.shooter.get_ranged_strength(self.partner, True)
        out["city defence"] = city.get_combat_strength()
        out["city ranged"] = city.get_ranged_strength()
        out["slots"] = tuple(sorted(slot_counts(self.player).items()))
        out["upgrade cost"] = upgrade_cost(self.fighter)
        out["flanking"] = rule_enabled(self.player, RULE_FLANKING)
        # The #116 P5 consumers.
        out["maintenance"] = maintenance_due(self.player)
        for resource in unit_model.PURCHASE_RESOURCES:
            out[f"purchase {resource}"] = purchase_cost(self.player, "unit", self.fighter_type,
                                                        resource)
        out["faith categories"] = faith_purchase_categories(self.player, city)
        out["route capacity"] = route_capacity(self.player)
        out["route yields"] = tuple(sorted(route_yields(self.route, env).items()))
        # The #116 P6 consumer: what 7 surplus food at the 100 % housing band
        # adds to the growth bucket (hundredths).
        out["growth gain"] = city.growth_bucket_gain(7, 100)
        # The #116 P7 consumer: the capital's loyalty delta this round.
        out["loyalty delta"] = loyalty_delta(city, env)
        # The v0.9.0 Q2 consumer: the capital's amenity supply (its band is
        # neutralised by this module, so supply moves nothing downstream).
        out["amenity supply"] = amenities.supply(city, env)
        # The v0.9.0 Q5 consumer: the units' movement points per turn.
        out["fighter max movement"] = self.fighter.get_max_movement()
        out["shooter max movement"] = self.shooter.get_max_movement()
        out["enemy max movement"] = self.enemy.get_max_movement()
        # The v0.9.0 Q7 consumer of border_cost_percent: what the capital's
        # next culture claim costs in the border phase (tenths).
        out["border claim cost"] = territory.claim_cost(
            env.border_cost, city.border_claims + 1,
            territory.border_cost_percent(self.player))
        # The v0.9.0 Q8 consumer of per_follower_city: what the player's
        # founder belief pays this turn (yield -> tenths; empty without one).
        out["founder pay"] = tuple(sorted(founder_pay_tenths(self.player, env).items()))
        return out


def _moved(before, after):
    return {key for key in before if before[key] != after[key]}


# --- (a) every wired kind moves its one consumer, and nothing else -------------------


def test_the_stage_has_what_the_kind_tests_need(monkeypatch):
    """Fixture guard: the capital produces, has gold adjacency, two specialty
    districts, a nonzero upgrade price, and no flanking in force."""
    stage = Stage(monkeypatch)
    assert districts_mod.district_yields(stage.city)["gold"] == 3
    assert len(districts_mod.specialty_districts(stage.city)) == 2
    assert city_yield(stage.city, "production") >= 2
    assert upgrade_cost(stage.fighter) > 0
    assert not rule_enabled(stage.player, RULE_FLANKING)
    assert stage.fighter.flanking_count(stage.enemy) == 0


@pytest.mark.parametrize("entries, expected", [
    ([{"kind": "city_yield", "science": 1}], {"yield science": 10}),
    ([{"kind": "city_yield", "food": 1}], {"yield food": 1}),
    ([{"kind": "city_yield", "production": 2}], {"yield production": 2, "production": None}),
    ([{"kind": "adjacency_percent", "district": "Probe", "percent": 100}], {"yield gold": 30}),
    ([{"kind": "city_ranged_strength", "amount": 5}], {"city ranged": 5}),
    ([{"kind": "combat_strength", "applies_to": "city", "amount": 6}], {"city defence": 6}),
    ([{"kind": "housing_if_districts", "amount": 1, "min_districts": 2}], {"housing": 10}),
    ([{"kind": "housing_with_building", "building": CAPITAL_BUILDING, "amount": 1.5}],
     {"housing": 15}),
    ([{"kind": "enables", "rules": [RULE_FLANKING]}], {"flanking": True}),
])
def test_each_wired_kind_moves_exactly_its_consumer(monkeypatch, entries, expected):
    """One synthetic card per kind, slotted: exactly the consumer's output
    moves, by exactly the effect's amount (yields in tenths for the four
    pools, whole points for food and production); `None` = moves, value
    checked elsewhere. Breaks if a kind gains a second consumer or loses
    its one (§14 row 6)."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    stage.slot(monkeypatch, entries)
    after = stage.fingerprint()
    assert _moved(before, after) == set(expected), entries
    for key, delta in expected.items():
        if delta is True:
            assert after[key] is True
        elif delta is not None:
            assert after[key] - before[key] == delta, key


def test_production_percent_moves_production_toward_a_matching_item_only(monkeypatch):
    """+50 % toward the unit the city produces raises calculate_production to
    base * 150 // 100 and nothing else; toward another item it moves
    nothing. Breaks if the percent is applied to every item or elsewhere."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    base = city_yield(stage.city, "production")
    stage.slot(monkeypatch, [{"kind": "production_percent",
                              "target": {"unit": stage.shooter_type}, "percent": 50}])
    assert stage.fingerprint() == before, "the city produces another unit"
    stage.slot(monkeypatch, [{"kind": "production_percent",
                              "target": {"unit": stage.fighter_type}, "percent": 50}],
               name="Second Card")
    after = stage.fingerprint()
    assert _moved(before, after) == {"production"}
    assert after["production"] == max(1, base * 150 // 100)


@pytest.mark.parametrize("applies", ["fighter class", APPLIES_ALL])
def test_combat_strength_reaches_its_classes_in_both_roles(monkeypatch, applies):
    """A +4 `combat_strength` for the fighter's class raises its attack and
    its defence by 4 -- against a unit and against a city alike -- and
    leaves the shooter (another class) and the city alone; for "all" it
    raises every unit, the shooter's ranged strength included (at a unit and
    at a city), and still not the city. Breaks if the bonus is applied in one
    role only or reaches the wrong units."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    target = unit_model.COMBAT_CLASS[stage.fighter_type] if applies != APPLIES_ALL else APPLIES_ALL
    stage.slot(monkeypatch, [{"kind": "combat_strength", "applies_to": [target], "amount": 4}])
    after = stage.fingerprint()
    expected = {"fighter attack", "fighter defence", "fighter attack on city"}
    if applies == APPLIES_ALL:
        expected |= {"shooter ranged", "shooter defence", "shooter ranged on city"}
    assert _moved(before, after) == expected
    for key in expected:
        assert after[key] - before[key] == 4, key


def test_upgrade_cost_percent_moves_only_the_upgrade_price(monkeypatch):
    """-50 % on upgrades halves the price (floored) and moves nothing else.
    Breaks if the hook stays 0 or the percent leaks into another price."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    base = unit_model.base_upgrade_cost(stage.fighter_type)
    stage.slot(monkeypatch, [{"kind": "upgrade_cost_percent", "percent": -50}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"upgrade cost"}
    assert after["upgrade cost"] == base * 50 // 100


def test_policy_slots_from_a_civic_move_only_the_slot_counts(monkeypatch):
    """A known civic's `policy_slots` adds to the government's slots and
    moves nothing else (no card may carry the kind, so a civic carries it
    here). Breaks if slot_counts ignores non-government sources."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    synthetic_civic(monkeypatch, "Synthetic Civic", [{"kind": "policy_slots", "military": 1}])
    stage.player.civics.append("Synthetic Civic")
    after = stage.fingerprint()
    assert _moved(before, after) == {"slots"}
    assert dict(after["slots"])["military"] == dict(before["slots"])["military"] + 1


@pytest.mark.parametrize("entries, expected", [
    # Every unit of the stage with positive upkeep pays 1 gold less (the
    # exact per-unit rule: tests/test_gold.py).
    ([{"kind": "unit_maintenance_delta", "amount": -1}], {"maintenance": None}),
    ([{"kind": "purchase_percent", "resource": "faith", "percent": -15}],
     {"purchase faith": None}),
    ([{"kind": "faith_purchase", "categories": list(effects.FAITH_PURCHASE_CATEGORIES)}],
     {"faith categories": None}),
    ([{"kind": "trade_route_capacity", "amount": 1}], {"route capacity": 1}),
    ([{"kind": "route_yield", "gold": 2}], {"yield gold": 20, "route yields": None}),
])
def test_each_p5_kind_moves_exactly_its_consumer(monkeypatch, entries, expected):
    """The five kinds consumed from #116 P5 (deferred in P4), one synthetic
    card each, slotted: exactly their consumer's output moves -- maintenance,
    the purchase price in the card's resource, the faith-purchase
    categories, the route capacity, the route's yields (and through them the
    origin's city_yield) -- and nothing a P4 consumer computes. Breaks if a
    P5 kind gains a second consumer, loses its one, or leaks into another
    price (§14 row 6, restated from the P4 deferred-kinds test)."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    stage.slot(monkeypatch, entries)
    after = stage.fingerprint()
    assert _moved(before, after) == set(expected), entries
    for key, delta in expected.items():
        if delta is not None:
            assert after[key] - before[key] == delta, key
    if "maintenance" in expected:
        assert after["maintenance"] < before["maintenance"], "a -1 delta lowers upkeep"
    if "purchase faith" in expected:
        assert after["purchase faith"] < before["purchase faith"], "-15 % lowers the price"
    if "faith categories" in expected:
        assert after["faith categories"] == tuple(effects.FAITH_PURCHASE_CATEGORIES)
    if "route yields" in expected:
        assert dict(after["route yields"])["gold"] - dict(before["route yields"])["gold"] == 20


@pytest.mark.parametrize("entry, garrisoned, gain", [
    ({"kind": "loyalty", "amount": 2}, False, 2),
    ({"kind": "loyalty", "amount": 1, "per_population": True}, False, 3),   # population 3
    ({"kind": "loyalty", "amount": 2, "requires_garrison": True}, True, 2),
    ({"kind": "loyalty", "amount": 2, "requires_garrison": True}, False, 0),
])
def test_loyalty_moves_exactly_the_loyalty_delta(monkeypatch, entry, garrisoned, gain):
    """#116 P7 (restated from the P4-P6 deferred-kinds test, retired with
    the last deferred kind): a `loyalty` card moves only the city's loyalty
    delta, by its amount -- times the population with `per_population`, and
    only while a fighting unit of the owner stands on the centre with
    `requires_garrison` -- and nothing else any consumer computes. Breaks if
    the kind gains a second consumer, loses its one, or drops a condition."""
    stage = Stage(monkeypatch)
    if garrisoned:
        stand(stage.env, stage.fighter_type, 0, stage.city.coordinates)
    before = stage.fingerprint()
    stage.slot(monkeypatch, [entry])
    after = stage.fingerprint()
    assert _moved(before, after) == ({"loyalty delta"} if gain else set()), entry
    assert after["loyalty delta"] - before["loyalty delta"] == gain
    assert [e.kind for e in active_effects(stage.player)
            if e.source == ("policy", CARD)] == [entry["kind"]], "the card is in force"


@pytest.mark.parametrize("entry, garrisoned, gain", [
    ({"kind": "amenity", "amount": 2}, False, 2),
    ({"kind": "amenity", "amount": 1, "min_districts": 2}, False, 1),     # the stage has two
    ({"kind": "amenity", "amount": 1, "min_districts": 3}, False, 0),
    ({"kind": "amenity", "amount": 3, "requires_garrison": True}, True, 3),
    ({"kind": "amenity", "amount": 3, "requires_garrison": True}, False, 0),
])
def test_amenity_moves_exactly_the_amenity_supply(monkeypatch, entry, garrisoned, gain):
    """v0.9.0 Q2: an `amenity` card moves only `amenities.supply` of the city,
    by its amount, honouring `min_districts` and `requires_garrison`; with the
    band table neutralised (this module's fixture) nothing a band feeds
    (yields, production, growth, loyalty) moves, because supply reaches them
    only through the band. Breaks if the kind gains a second consumer, loses
    its one, or drops a condition."""
    stage = Stage(monkeypatch)
    if garrisoned:
        stand(stage.env, stage.fighter_type, 0, stage.city.coordinates)
    before = stage.fingerprint()
    stage.slot(monkeypatch, [entry], card_type="military")
    after = stage.fingerprint()
    assert _moved(before, after) == ({"amenity supply"} if gain else set()), entry
    assert after["amenity supply"] - before["amenity supply"] == gain
    assert [e.kind for e in active_effects(stage.player)
            if e.source == ("policy", CARD)] == [entry["kind"]], "the card is in force"


@pytest.mark.parametrize("yields, expected", [
    ({"production": 1}, {"yield production": 1, "production": None}),
    ({"production": 1, "gold": 2, "faith": 0.5}, {"yield production": 1, "production": None,
                                                    "yield gold": 20, "yield faith": 5}),
])
def test_regional_yield_moves_exactly_the_regional_term(monkeypatch, yields, expected):
    """v0.9.0 Q4: a `regional_yield` building carried by ANOTHER city of the
    owner, within its range, moves only the yields it names in
    `city_yield` (tenths for the pools, whole points for production, which
    reaches `calculate_production` through it) and nothing any other
    consumer computes. Breaks if the kind gains a second consumer, pays a
    yield it does not name, or is read by a non-yield consumer."""
    stage = Stage(monkeypatch)
    carrier = make_city(stage.env, (3, 8), population=3)
    reach = stage.env.map.distance_function(carrier.coordinates, stage.city.coordinates)
    entry = {"kind": "regional_yield", **yields, "range": reach, "scope": "player"}
    monkeypatch.setitem(unit_model.BUILDING_EFFECTS, "Monument", (entry,))
    before = stage.fingerprint()
    carrier.buildings.append("Monument")
    after = stage.fingerprint()
    assert _moved(before, after) == set(expected), yields
    for key, delta in expected.items():
        if delta is not None:
            assert after[key] - before[key] == delta, key
    assert after["production"] - before["production"] == 1


@pytest.mark.parametrize("domain", ["water", "land"])
def test_movement_delta_moves_exactly_the_max_movement_of_its_domain(monkeypatch, domain):
    """v0.9.0 Q5: a `movement_delta` card (the Great Lighthouse's kind)
    adds its amount to `Unit.get_max_movement` for its owner's units of the
    domain it names -- a ship for "water", the land fighter and shooter for
    "land" -- and moves nothing else: not the enemy's units, not another
    consumer. Breaks if the kind gains a second reader, ignores the domain or
    reaches another player."""
    stage = Stage(monkeypatch)
    ship_type = next(u for u in unit_model.UNIT_NAMES if MOVEMENT_DOMAIN[u] == "water")
    ship = stand(stage.env, ship_type, 0, (0, 0))
    enemy_ship = stand(stage.env, ship_type, 1, (0, 2))

    def fingerprint():
        out = stage.fingerprint()
        out["ship max movement"] = ship.get_max_movement()
        out["enemy ship max movement"] = enemy_ship.get_max_movement()
        return out

    before = fingerprint()
    stage.slot(monkeypatch, [{"kind": "movement_delta", "domain": domain, "amount": 1}])
    after = fingerprint()
    expected = ({"ship max movement"} if domain == "water"
                else {"fighter max movement", "shooter max movement"})
    assert _moved(before, after) == expected
    for key in expected:
        assert after[key] == before[key] + 1, key


def test_growth_percent_moves_exactly_the_growth_bucket(monkeypatch):
    """#116 P6 (restated from the deferred-kinds test): a +15 % and a +10 %
    `growth_percent` card move only the growth gain, to `food_net *
    housing_percent * 100 * (100 + 25) // 10000` -- summed, then applied
    once with one floor. Breaks if the kind gains a second consumer, loses
    its one, or the percents are compounded."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    assert before["growth gain"] == 7 * 100, "no effect: the v0.7 bucket"
    stage.slot(monkeypatch, [{"kind": "growth_percent", "percent": 15}])
    stage.slot(monkeypatch, [{"kind": "growth_percent", "percent": 10}], name="Second Card")
    after = stage.fingerprint()
    assert _moved(before, after) == {"growth gain"}
    assert after["growth gain"] == 7 * 100 * 100 * 125 // 10000
    assert stage.city.growth_bucket_gain(3, 25) == 3 * 25 * 100 * 125 // 10000


def _with_pantheon(monkeypatch, stage, entries):
    """v0.9.0 Q7: hand the stage's player a synthetic pantheon carrying
    `entries` (the pantheon source; the action is tests/test_religion.py's)."""
    name = "Synthetic Pantheon"
    monkeypatch.setitem(religion_model.PANTHEONS, name,
                        religion_model.PantheonSpec(name=name, effects=tuple(entries)))
    stage.player.pantheon = name


def test_border_cost_percent_moves_exactly_the_border_claim_cost(monkeypatch):
    """v0.9.0 Q7: a -15 % `border_cost_percent` pantheon moves only the cost
    of the owner's next culture claim, to `cost(n) * 85 // 100`. Breaks if
    the kind gains a second reader or loses its one."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    _with_pantheon(monkeypatch, stage, [{"kind": "border_cost_percent", "percent": -15}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"border claim cost"}
    assert after["border claim cost"] == max(1, before["border claim cost"] * 85 // 100)


@pytest.mark.parametrize("yields, expected", [
    ({"food": 1, "production": 1}, {"yield food": 1, "yield production": 1, "production": None}),
    ({"faith": 2, "culture": 1}, {"yield faith": 20, "yield culture": 10}),
])
def test_improvement_yield_moves_exactly_the_yields_it_names(monkeypatch, yields, expected):
    """v0.9.0 Q7: an `improvement_yield` pantheon, with one worked tile of
    the capital carrying its improvement, moves only the yields it names in
    `city_yield` (production reaching `calculate_production`) and nothing any
    other consumer computes. Breaks if the kind gains a second reader (say
    `Tile.yields`, read by the encoder and claim ranking) or pays a yield it
    does not name."""
    stage = Stage(monkeypatch)
    improvement = sorted(district_model.terrain_model.IMPROVEMENT_NAMES)[0]
    stage.env.map.get_tile(stage.city.worked_tiles[0]).improvements.append(improvement)
    before = stage.fingerprint()
    _with_pantheon(monkeypatch, stage, [{"kind": "improvement_yield",
                                         "improvement": improvement, **yields}])
    after = stage.fingerprint()
    assert _moved(before, after) == set(expected)
    for key, delta in expected.items():
        if delta is not None:
            assert after[key] - before[key] == delta, key


def test_adjacency_row_moves_exactly_the_districts_adjacency_yield(monkeypatch):
    """v0.9.0 Q7: an `adjacency_row` pantheon for Probe (+1 per six adjacent
    tiles of the board's base terrain -- the stage board is one terrain, so
    exactly +1) moves only the gold Probe's adjacency yields, by 1 point (10
    tenths). Breaks if the kind gains a second reader or the row reaches
    another district type."""
    stage = Stage(monkeypatch)
    base = stage.env.map.get_tile(stage.city.coordinates).base_terrain
    before = stage.fingerprint()
    _with_pantheon(monkeypatch, stage, [{"kind": "adjacency_row", "district": "Probe",
                                         "amount": 1, "per": 6,
                                         "terrain": {"bases": [base]}}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"yield gold"}
    assert after["yield gold"] - before["yield gold"] == 10


def _with_religion(monkeypatch, stage, follower=(), enhancer=None, founder=None):
    """v0.9.0 Q8: hand the stage's player a religion of synthetic beliefs --
    `founder` (per_follower_city entries; default: a `foreign`-counting one,
    which pays nothing while only the capital follows), `follower` (entries of
    one follower belief) and `enhancer` (entries of one enhancer belief) --
    with the capital following it. The actions are tests/test_religion_
    beliefs.py's; this is the `belief` source."""
    def belief(name, tier, entries, counts=None):
        monkeypatch.setitem(religion_model.BELIEFS, name, religion_model.BeliefSpec(
            name=name, tier=tier, effects=tuple(entries), counts=counts))
        return name

    founder_name = belief("Synthetic Founder", religion_model.TIER_FOUNDER,
                          founder or [{"kind": "per_follower_city", "faith": 1}],
                          religion_model.COUNTS_ALL if founder else religion_model.COUNTS_FOREIGN)
    followers = [belief("Synthetic Follower", religion_model.TIER_FOLLOWER, follower)] \
        if follower else []
    enhancer_name = belief("Synthetic Enhancer", religion_model.TIER_ENHANCER, enhancer) \
        if enhancer else None
    stage.player.religion = Religion(founder=stage.player.player_index,
                                     founder_belief=founder_name, follower_beliefs=followers,
                                     enhancer_belief=enhancer_name)
    stage.city.religion = stage.player.player_index


def test_cross_yield_moves_exactly_the_named_yield_by_the_floored_share(monkeypatch):
    """v0.9.0 Q8: a `cross_yield` follower belief paying 33 % of Probe's
    adjacency (3) as science moves only the capital's science, by
    floor(10 * 3 * 33 / 100) = 9 tenths -- the gold Probe yields is untouched.
    Breaks if the kind gains a second reader, skips the floor, or pays the
    district's own yield."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    _with_religion(monkeypatch, stage, follower=[{"kind": "cross_yield", "from_district": "Probe",
                                                  "to": "science", "percent": 33}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"yield science"}
    assert after["yield science"] - before["yield science"] == 9


def test_per_follower_city_moves_exactly_the_founder_pay(monkeypatch):
    """v0.9.0 Q8: a founder belief paying 1 gold and 0.5 culture per follower
    city (the capital follows) moves only the founder pay, to exactly those
    tenths; no yield, strength or price moves. Breaks if the kind gains a
    second reader or the pay is read into a yield."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    _with_religion(monkeypatch, stage, founder=[{"kind": "per_follower_city", "gold": 1,
                                                 "culture": 0.5}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"founder pay"}
    assert after["founder pay"] == (("culture", 5), ("gold", 10))


def test_per_wonder_moves_exactly_the_yield_per_complete_wonder(monkeypatch):
    """v0.9.0 Q8: a `city_yield` with `per_wonder` (+4 faith) moves nothing
    while the capital's wonder is unfinished and only its faith, by 40
    tenths, once the wonder is complete. Breaks if the multiplier counts
    placed wonders or anything but wonders."""
    stage = Stage(monkeypatch)
    site = next(p for p in ring(stage.env, stage.city.coordinates, 2)
                if stage.env.map.get_tile(p).district is None)
    relic = _put(stage.env, stage.city, "Relic", site, complete=False)
    before = stage.fingerprint()
    _with_religion(monkeypatch, stage, follower=[{"kind": "city_yield", "faith": 4,
                                                  "per_wonder": True}])
    assert _moved(before, stage.fingerprint()) == set()
    relic.complete = True
    without = stage.fingerprint()
    stage.city.religion = None
    base = stage.fingerprint()
    assert _moved(base, without) == {"yield faith"}
    assert without["yield faith"] - base["yield faith"] == 40


def test_vs_city_of_other_religion_moves_only_the_strengths_aimed_at_such_a_city(monkeypatch):
    """v0.9.0 Q8 (Crusade): a +10 `combat_strength` for all with
    `vs_city_of_other_religion` moves only the fighter's attack on the other
    player's (secular) city and the shooter's ranged strength on it, by 10;
    nothing against the enemy unit, nothing when defending, nothing once that
    city follows the player's religion. Breaks if the condition is read for a
    unit target, in one strength only, or from the owner."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    _with_religion(monkeypatch, stage, enhancer=[{"kind": "combat_strength", "applies_to": ["all"],
                                                  "amount": 10,
                                                  "vs_city_of_other_religion": True}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"fighter attack on city", "shooter ranged on city"}
    assert after["fighter attack on city"] - before["fighter attack on city"] == 10
    assert after["shooter ranged on city"] - before["shooter ranged on city"] == 10
    # The city adopts the player's religion: both strengths fall back to the
    # baseline (the founder belief now counts a foreign follower, which is
    # founder pay's business, not this kind's).
    stage.partner.religion = stage.player.player_index
    adopted = stage.fingerprint()
    assert adopted["fighter attack on city"] == before["fighter attack on city"]
    assert adopted["shooter ranged on city"] == before["shooter ranged on city"]
    assert _moved(before, adopted) <= {"founder pay"}


def test_in_follower_territory_moves_only_the_strengths_of_a_unit_on_a_follower_tile(monkeypatch):
    """v0.9.0 Q8 (Defender of the Faith): a +5 `combat_strength` for all with
    `in_follower_territory` moves only the strengths of the fighter standing
    on a tile the (following) capital owns -- attack, defence and attack on
    the city, all by 5 -- and not the shooter's, standing on unowned land.
    Breaks if the condition reads the target's tile, the owner, or one role
    only."""
    stage = Stage(monkeypatch)
    own(stage.env, stage.city, tuple(stage.fighter.coordinates))
    assert stage.env.map.owner_id_at(stage.shooter.coordinates) == -1
    before = stage.fingerprint()
    _with_religion(monkeypatch, stage, enhancer=[{"kind": "combat_strength", "applies_to": ["all"],
                                                  "amount": 5, "in_follower_territory": True}])
    after = stage.fingerprint()
    assert _moved(before, after) == {"fighter attack", "fighter defence", "fighter attack on city"}
    for key in _moved(before, after):
        assert after[key] - before[key] == 5, key
    stage.city.religion = None
    assert _moved(before, stage.fingerprint()) == set()


def test_religion_param_moves_nothing_a_wired_consumer_computes_yet(monkeypatch):
    """v0.9.0 Q8: a `religion_param` enhancer is in force for the founder but
    its consumer -- the pressure rules of game/religion.py -- is Q9's, so
    nothing any wired consumer computes today moves. Breaks if a consumer
    reads it before Q9 names itself (Q9 adds its pressure to the stage
    fingerprint and updates this test)."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    _with_religion(monkeypatch, stage, enhancer=[{"kind": "religion_param", "range": 3,
                                                  "spread_amount_percent": 50,
                                                  "cost_percent": -30}])
    assert _moved(before, stage.fingerprint()) == set()
    assert [e.kind for e in active_effects(stage.player, kind="religion_param")] == ["religion_param"]


def test_every_kind_names_its_one_consumer():
    """The closed set of kinds is exactly the set with a named consumer, and
    since #116 P7 no kind is deferred: every consumer is a reader in the
    code, none a patch still to come. Breaks if a kind is added without a
    consumer, a consumer entry outlives its kind, or a kind is validated
    but read by nothing."""
    assert set(KINDS) == set(CONSUMERS)
    assert not DEFERRED_KINDS
    assert not any(CONSUMERS[k].startswith("#116 P") for k in KINDS)


# --- city_yield's attributes -------------------------------------------------------------


def test_capital_only_holds_in_the_city_with_the_capital_building_only(monkeypatch):
    """`capital_only` = the city holding `[city] capital_building`: the
    capital gains the amount, an identical second city nothing. Breaks if
    'capital' is read from anything but the building."""
    stage = Stage(monkeypatch)
    other = make_city(stage.env, (3, 12), population=3)
    assert CAPITAL_BUILDING in stage.city.buildings and CAPITAL_BUILDING not in other.buildings
    before = (city_yield(stage.city, "faith"), city_yield(other, "faith"))
    stage.slot(monkeypatch, [{"kind": "city_yield", "faith": 1, "capital_only": True}])
    assert city_yield(stage.city, "faith") == before[0] + 10
    assert city_yield(other, "faith") == before[1]


def test_per_district_counts_complete_specialty_districts_only(monkeypatch):
    """`per_district` multiplies by the city's complete districts that take a
    population slot: an incomplete one and a slotless one add nothing.
    Breaks if every district counts or the count is read from anything but
    specialty_districts."""
    stage = Stage(monkeypatch)
    base = city_yield(stage.city, "culture")
    stage.slot(monkeypatch, [{"kind": "city_yield", "culture": 1, "per_district": True}])
    assert city_yield(stage.city, "culture") == base + 2 * 10
    pending = _put(stage.env, stage.city, "Marker", ring(stage.env, stage.city.coordinates, 3)[0],
                   complete=False)
    assert city_yield(stage.city, "culture") == base + 2 * 10
    pending.complete = True
    assert city_yield(stage.city, "culture") == base + 3 * 10


# --- scope: where an effect holds -------------------------------------------------------


@pytest.mark.parametrize("scope, holds_in_other", [(None, False), ("player", True)])
def test_a_building_effect_holds_in_its_city_unless_scoped_to_the_player(monkeypatch, scope,
                                                                         holds_in_other):
    """A building's effect defaults to its own city; with `scope = "player"`
    it holds in every city of the owner. Breaks if the default scope or the
    gathering of player-scoped building effects drifts."""
    stage = Stage(monkeypatch)
    other = make_city(stage.env, (3, 12), population=3)
    entry = {"kind": "production_percent", "target": {"unit": stage.fighter_type},
             "percent": 100}
    if scope:
        entry["scope"] = scope
    assert other.produce_unit(stage.fighter_type)
    before = (stage.city.calculate_production(stage.env), other.calculate_production(stage.env))
    monkeypatch.setitem(unit_model.BUILDING_EFFECTS, CAPITAL_BUILDING, (entry,))
    assert stage.city.calculate_production(stage.env) > before[0]
    assert (other.calculate_production(stage.env) > before[1]) is holds_in_other


def test_entries_in_force_carry_the_city_holding_their_source(monkeypatch):
    """#116 P7: an entry `active_effects` returns from a building or a
    complete district carries the city that holds it (`source_city`) --
    the capital's own city-scoped entries and a player-scoped entry of
    another city alike -- and one from a policy carries None; the parsed
    entry itself carries none, and equality ignores it. Breaks if a ranged
    effect could not tell where it comes from, or the parse memo were
    bound to one city."""
    stage = Stage(monkeypatch)
    other = make_city(stage.env, (3, 12), population=3)
    probe = {"kind": "city_ranged_strength", "amount": 1}
    monkeypatch.setitem(unit_model.BUILDING_EFFECTS, CAPITAL_BUILDING, (probe,))
    monkeypatch.setitem(unit_model.BUILDING_EFFECTS, "Monument",
                        ({**probe, "scope": "player"},))
    other.buildings.append("Monument")
    stage.slot(monkeypatch, [probe])
    held = {e.source: e.source_city
            for e in active_effects(stage.player, stage.city, probe["kind"])}
    assert held == {("policy", CARD): None, ("building", CAPITAL_BUILDING): stage.city,
                    ("building", "Monument"): other}
    parsed = effects_of("building", CAPITAL_BUILDING)[0]
    assert parsed.source_city is None
    assert parsed == parsed.held_by(stage.city)


def test_active_effects_come_in_the_documented_order(monkeypatch):
    """Government, slotted cards in loadout order, civics then techs in
    completion order, then the city's buildings. Breaks if the order comes
    from a set or a dict of the registries."""
    stage = Stage(monkeypatch)
    probe = {"kind": "city_ranged_strength", "amount": 1}
    synthetic_government(monkeypatch, GOVERNMENT, {"wildcard": 2}, requires_civic=QUIET,
                         effects=[probe])
    stage.slot(monkeypatch, [probe], name="Card B")
    stage.slot(monkeypatch, [probe], name="Card A")
    synthetic_civic(monkeypatch, "Civic Z", [probe])
    synthetic_civic(monkeypatch, "Civic Y", [probe])
    stage.player.civics.extend(["Civic Z", "Civic Y"])
    monkeypatch.setitem(unit_model.BUILDING_EFFECTS, CAPITAL_BUILDING, (probe,))
    kind = probe["kind"]
    sources = [e.source for e in active_effects(stage.player, stage.city, kind)]
    assert sources == [("government", GOVERNMENT), ("policy", "Card B"), ("policy", "Card A"),
                       ("civic", "Civic Z"), ("civic", "Civic Y"),
                       ("building", CAPITAL_BUILDING)]
    assert all(e.scope == "player" for e in active_effects(stage.player))
    assert ("building", CAPITAL_BUILDING) not in [e.source for e in active_effects(stage.player)]
    assert all(e.kind == kind for e in active_effects(stage.player, stage.city, kind))


# --- (c) one kind: summed, then applied once ------------------------------------------


def test_percent_effects_of_one_kind_are_summed_then_applied_once(monkeypatch):
    """Two +100 % production cards give base * 300 // 100, not base * 2 * 2;
    two -25 % upgrade cards give base * 50 // 100, not two successive 75 %
    floors. Breaks if a consumer compounds the effects of one kind (v2
    fixes, N3)."""
    stage = Stage(monkeypatch)
    base = city_yield(stage.city, "production")
    price = unit_model.base_upgrade_cost(stage.fighter_type)
    for name in ("Card A", "Card B"):
        stage.slot(monkeypatch, [
            {"kind": "production_percent", "target": {"unit": stage.fighter_type}, "percent": 100},
            {"kind": "upgrade_cost_percent", "percent": -25},
        ], name=name)
    assert stage.city.calculate_production(stage.env) == base * 300 // 100
    assert stage.city.calculate_production(stage.env) != base * 200 // 100 * 200 // 100
    assert upgrade_cost(stage.fighter) == price * 50 // 100
    assert upgrade_cost(stage.fighter) != price * 75 // 100 * 75 // 100


def test_adjacency_percents_of_one_district_are_summed_before_the_floor(monkeypatch):
    """Two +50 % cards on the Probe raise its 3 adjacency to 3 * 200 // 100.
    Breaks if the percents are applied per card or to the wrong district."""
    stage = Stage(monkeypatch)
    base = city_yield(stage.city, "gold")
    for name in ("Card A", "Card B"):
        stage.slot(monkeypatch, [{"kind": "adjacency_percent", "district": "Probe", "percent": 50}],
                   name=name)
    assert city_yield(stage.city, "gold") == base + 10 * (3 * 200 // 100 - 3)


# --- (b) junk raises at load -------------------------------------------------------------


def _warrior_like():
    return next(iter(sorted(unit_model.UNIT_NAMES)))


def _district_without_adjacency():
    return next(n for n, s in district_model.DISTRICTS.items() if s.adjacency_yield == "none")


@pytest.mark.parametrize("entry, source", [
    ({"kind": "teleport", "amount": 1}, "policy"),                                   # unknown kind
    ({"amount": 1}, "policy"),                                                        # no kind
    ("city_yield", "policy"),                                                         # not a table
    ({"kind": "city_yield", "science": 1, "bonus": 2}, "policy"),                    # unknown attribute
    ({"kind": "city_yield"}, "policy"),                                               # names no yield
    ({"kind": "city_yield", "science": 0.05}, "policy"),                             # not a tenth
    ({"kind": "city_yield", "science": 1}, "building"),                              # yield on a building
    ({"kind": "city_yield", "science": 1, "capital_only": "yes"}, "policy"),          # not a bool
    ({"kind": "production_percent", "percent": 50}, "policy"),                        # missing target
    ({"kind": "production_percent", "target": {"unit": "Dragon"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"unit_class": "wizard"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"unit_era": ["Space Age"]}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"building": "Spaceport"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"district": "Moonbase"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"in_district": "Moonbase"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"kind": "starship"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"colour": "red"}, "percent": 50}, "policy"),
    ({"kind": "production_percent", "target": {"unit_class": "melee", "building": CAPITAL_BUILDING},
      "percent": 50}, "policy"),                                                      # excludes every item
    ({"kind": "production_percent", "target": {"kind": "unit"}, "percent": 0.5}, "policy"),
    ({"kind": "adjacency_percent", "district": "Moonbase", "percent": 100}, "policy"),
    ({"kind": "combat_strength", "applies_to": "dragons", "amount": 4}, "policy"),
    ({"kind": "combat_strength", "applies_to": "civilian", "amount": 4}, "policy"),
    ({"kind": "combat_strength", "applies_to": ["melee"], "amount": 1.5}, "policy"),
    ({"kind": "enables", "rules": ["teleportation"]}, "civic"),
    ({"kind": "enables", "rules": "flanking"}, "civic"),
    ({"kind": "housing_with_building", "building": "Nowhere", "amount": 1}, "government"),
    ({"kind": "purchase_percent", "resource": "gems", "percent": -15}, "government"),
    ({"kind": "faith_purchase", "categories": ["naval"]}, "government"),
    ({"kind": "loyalty", "amount": 2, "range": -1}, "policy"),
    ({"kind": "loyalty", "amount": 2, "range": 6}, "policy"),                        # range needs a city
    ({"kind": "loyalty", "amount": 2, "range": 6, "scope": "city"}, "district"),     # a city scope has no reach
    ({"kind": "loyalty", "amount": 1}, "building"),                                  # flat: the column
    ({"kind": "loyalty", "amount": 1.5, "per_population": True}, "building"),        # whole points
    ({"kind": "trade_route_capacity", "amount": 0}, "civic"),
    ({"kind": "free_units", "units": [{"unit": "Dragon", "count": 1}]}, "district"),
    ({"kind": "free_units", "units": [{"unit": _warrior_like(), "count": 1}]}, "policy"),  # one-shot off a wonder
    ({"kind": "free_tech", "count": 1}, "civic"),
    ({"kind": "policy_slots", "wildcard": 1}, "policy"),                              # a card cannot add slots
    ({"kind": "policy_slots", "diplomatic": 1}, "government"),                        # no diplomatic slot
    ({"kind": "policy_slots", "wildcard": 1, "scope": "city"}, "building"),           # read for the player
    ({"kind": "city_ranged_strength", "amount": 5, "scope": "city"}, "policy"),       # a card has no city
    ({"kind": "city_ranged_strength", "amount": 5, "scope": "city"}, "government"),
    ({"kind": "city_ranged_strength", "amount": 5, "scope": "city"}, "tech"),
    ({"kind": "city_ranged_strength", "amount": 5, "scope": "galaxy"}, "building"),
    # regional_yield (v0.9.0 Q4): a building of scope player with a range and a yield
    ({"kind": "regional_yield", "production": 1, "range": 6, "scope": "player"}, "policy"),
    ({"kind": "regional_yield", "production": 1, "range": 6, "scope": "player"}, "district"),
    ({"kind": "regional_yield", "production": 1, "range": 6}, "building"),             # city scope
    ({"kind": "regional_yield", "production": 1, "scope": "player"}, "building"),     # no range
    ({"kind": "regional_yield", "production": 1, "range": 0, "scope": "player"}, "building"),
    ({"kind": "regional_yield", "range": 6, "scope": "player"}, "building"),          # no yield
    ({"kind": "regional_yield", "production": 1.05, "range": 6, "scope": "player"}, "building"),
    ({"kind": "regional_yield", "luck": 1, "range": 6, "scope": "player"}, "building"),
])
def test_a_malformed_effect_raises_at_load(entry, source):
    """The loader refuses an unknown kind or attribute, a malformed value, a
    name that is no unit / building / district / class / era / rule /
    resource / category, a target that can match nothing, a `city_yield` on
    a building, city scope where no city exists, slots on a card, a
    one-shot off a wonder (§14 row 5), and a `loyalty` entry whose reach is
    wrong or that says what the `loyalty` column says (#116 P7). Breaks if
    any junk is accepted."""
    with pytest.raises(ValueError):
        parse_effect(entry, source, "Probe")


def test_an_adjacency_percent_on_a_district_without_adjacency_raises():
    """A district whose adjacency yields nothing cannot be raised by a
    percent: that target names nothing. Breaks if the check is dropped."""
    with pytest.raises(ValueError):
        parse_effect({"kind": "adjacency_percent", "district": _district_without_adjacency(),
                      "percent": 100}, "policy", "Probe")


def test_junk_in_a_registry_raises_when_the_interpreter_loads(monkeypatch):
    """The import-time pass validates every configured list: a junk entry
    on any card raises there, not at first use. Breaks if validation is
    lazy."""
    spec = research_model.PolicySpec(name="Junk", type="economic", requires_civic=QUIET,
                                     obsolete_with=None, effects=({"kind": "teleport"},))
    monkeypatch.setitem(research_model.POLICIES, "Junk", spec)
    with pytest.raises(ValueError):
        effects._validate_registries()


def test_scope_defaults_to_the_city_on_buildings_and_districts_only(monkeypatch):
    """A building's and a district's effects default to city scope, every
    other source's to player scope; a building may declare player. A belief
    (v0.9.0 Q8) is scoped by its tier: a follower belief's entries default to
    city, an enhancer's to player, and a name that is no belief cannot be
    parsed at all. Breaks if a default flips or a belief parses without its
    tier."""
    entry = {"kind": "city_ranged_strength", "amount": 5}
    for source in effects.SOURCES:
        if source == effects.SOURCE_BELIEF:
            continue
        expected = "city" if source in ("building", "district") else "player"
        assert parse_effect(entry, source, "Probe").scope == expected, source
    assert parse_effect({**entry, "scope": "player"}, "building", "Probe").scope == "player"
    with pytest.raises(ValueError):
        parse_effect(entry, effects.SOURCE_BELIEF, "Probe")
    for tier, expected in ((religion_model.TIER_FOLLOWER, "city"),
                           (religion_model.TIER_ENHANCER, "player")):
        monkeypatch.setitem(religion_model.BELIEFS, "Probe",
                            religion_model.BeliefSpec(name="Probe", tier=tier, effects=(entry,)))
        assert parse_effect(entry, effects.SOURCE_BELIEF, "Probe").scope == expected, tier


def test_valid_entries_normalise_their_values():
    """Yields and housing in tenths, name lists as tuples, defaults filled.
    Breaks if consumers would receive raw config values."""
    e = parse_effect({"kind": "city_yield", "gold": 1.5, "capital_only": True}, "policy", "P")
    assert dict(e["yields"]) == {"gold": 15} and e["capital_only"] and not e["per_district"]
    e = parse_effect({"kind": "housing_if_districts", "amount": 2, "min_districts": 3},
                     "policy", "P")
    assert e["amount"] == 20 and e["min_districts"] == 3
    e = parse_effect({"kind": "combat_strength", "applies_to": "melee", "amount": 4}, "policy", "P")
    assert e["applies_to"] == ("melee",)
    e = parse_effect({"kind": "policy_slots", "economic": 2}, "government", "G")
    assert dict(e["slots"]) == {t: (2 if t == "economic" else 0)
                                for t in research_model.POLICY_TYPES}


# --- (j) the real config ---------------------------------------------------------------


def test_every_configured_effect_validates_and_has_a_consumer():
    """Every tech, civic, government, policy, building and district effect
    in config.toml parses through the interpreter, and its kind has a
    named consumer. Breaks if config.toml gains an effect the engine would
    silently ignore."""
    seen = 0
    for source, names in ((effects.SOURCE_TECH, research_model.TECHS),
                          (effects.SOURCE_CIVIC, research_model.CIVICS),
                          (effects.SOURCE_GOVERNMENT, research_model.GOVERNMENTS),
                          (effects.SOURCE_POLICY, research_model.POLICIES),
                          (effects.SOURCE_BUILDING, unit_model.BUILDING_NAMES),
                          (effects.SOURCE_DISTRICT, district_model.DISTRICTS)):
        for name in names:
            for effect in effects_of(source, name):
                assert effect.kind in CONSUMERS
                assert effect.source == (source, name)
                seen += 1
    assert seen, "fixture: some effect is configured"


def test_every_policy_and_government_effect_validates_with_its_scope():
    """Every card's and government's entries validate and hold for the
    player (they have no city). Breaks if a card is given city scope."""
    for name in research_model.POLICIES:
        assert all(e.scope == "player" for e in effects_of(effects.SOURCE_POLICY, name)), name
    for name in research_model.GOVERNMENTS:
        assert all(e.scope == "player" for e in effects_of(effects.SOURCE_GOVERNMENT, name)), name


def test_rule_enabled_refuses_an_unknown_rule():
    """A consumer asking for a rule that no `enables` effect can name is a
    bug, so it raises. Breaks if a typo'd rule silently reads as off."""
    env = board()
    with pytest.raises(ValueError):
        rule_enabled(env.players[0], "teleportation")
    with pytest.raises(ValueError):
        active_effects(env.players[0], kind="teleport")
