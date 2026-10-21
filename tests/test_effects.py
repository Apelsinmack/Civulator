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
from civulator.game import districts as districts_mod
from civulator.game.housing import housing
from civulator.game.maintenance import maintenance_due
from civulator.game.purchasing import faith_purchase_categories, purchase_cost
from civulator.game.trade import DURATION_TURNS, TradeRoute, route_capacity, route_yields
from civulator.game.upgrades import upgrade_cost
from civulator.game.yields import city_yield
from civulator.research_model import CIVIC_ORDER, CIVICS
from civulator.unit_model import CAPITAL_BUILDING, YIELD_COLUMNS

from conftest import stand, synthetic_civic, synthetic_government, synthetic_policy
from test_districts import board, make_city, neighbours, ring

# A civic with no effects of its own: what the synthetic sources unlock with,
# so no configured civic effect is in force on the staged player.
QUIET = next(c for c in CIVIC_ORDER if not CIVICS[c].effects)
CARD = "Synthetic Card"
GOVERNMENT = "Synthetic Government"


def _registry(monkeypatch):
    """A synthetic district registry: Probe (+3 gold per adjacent Marker),
    Marker (no yield), Aside (takes no population slot: not a specialty
    district). Patched where every reader looks (`districts.district_spec`)."""
    reg = district_model.parse_districts({
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Probe": {"production_cost": 10, "adjacency_yield": "gold",
                  "adjacency": [{"amount": 3, "district": ["Marker"]}]},
        "Marker": {"production_cost": 10},
        "Aside": {"production_cost": 10, "counts_toward_limit": False},
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
    """(fighter, shooter): a melee-strength unit with an upgrade, and a
    ranged unit of another fighting class -- derived from the unit tables."""
    fighter = next(
        u for u in sorted(unit_model.UPGRADES_TO)
        if unit_model.BASE_COMBAT_STRENGTH[u] > 0 and unit_model.BASE_RANGED_STRENGTH[u] == 0
        and unit_model.COMBAT_CLASS[u] in COMBAT_STRENGTH_CLASSES)
    shooter = next(
        u for u in sorted(unit_model.UNIT_NAMES)
        if unit_model.BASE_RANGED_STRENGTH[u] > 0
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
    its defence by 4 and leaves the shooter (another class) and the city
    alone; for "all" it raises every unit, the shooter's ranged strength
    included, and still not the city. Breaks if the bonus is applied in one
    role only or reaches the wrong units."""
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    target = unit_model.COMBAT_CLASS[stage.fighter_type] if applies != APPLIES_ALL else APPLIES_ALL
    stage.slot(monkeypatch, [{"kind": "combat_strength", "applies_to": [target], "amount": 4}])
    after = stage.fingerprint()
    expected = {"fighter attack", "fighter defence"}
    if applies == APPLIES_ALL:
        expected |= {"shooter ranged", "shooter defence"}
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


@pytest.mark.parametrize("entry", [
    {"kind": "loyalty", "amount": 2, "requires_garrison": True},
    {"kind": "growth_percent", "percent": 15},
])
def test_a_deferred_kind_is_validated_and_moves_nothing_yet(monkeypatch, entry):
    """The kinds whose consumers land in P6-P7 parse on a card and change
    nothing a P4 or P5 consumer computes. Breaks if one of them is read
    early by the wrong consumer."""
    assert entry["kind"] in DEFERRED_KINDS
    stage = Stage(monkeypatch)
    before = stage.fingerprint()
    stage.slot(monkeypatch, [entry])
    assert stage.fingerprint() == before
    assert [e.kind for e in active_effects(stage.player)
            if e.source == ("policy", CARD)] == [entry["kind"]], "the card is in force"


def test_every_kind_names_its_one_consumer():
    """The closed set of kinds is exactly the set with a named consumer, and
    every deferred kind is a kind. Breaks if a kind is added without a
    consumer or a consumer entry outlives its kind."""
    assert set(KINDS) == set(CONSUMERS)
    assert DEFERRED_KINDS <= set(KINDS)
    assert all(CONSUMERS[k].startswith("#116 P") for k in DEFERRED_KINDS)
    assert not any(CONSUMERS[k].startswith("#116 P") for k in set(KINDS) - DEFERRED_KINDS)


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
])
def test_a_malformed_effect_raises_at_load(entry, source):
    """The loader refuses an unknown kind or attribute, a malformed value, a
    name that is no unit / building / district / class / era / rule /
    resource / category, a target that can match nothing, a `city_yield` on
    a building, city scope where no city exists, slots on a card and a
    one-shot off a wonder (§14 row 5). Breaks if any junk is accepted."""
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


def test_scope_defaults_to_the_city_on_buildings_and_districts_only():
    """A building's and a district's effects default to city scope, every
    other source's to player scope; a building may declare player. Breaks
    if the default flips."""
    entry = {"kind": "city_ranged_strength", "amount": 5}
    for source in effects.SOURCES:
        expected = "city" if source in ("building", "district") else "player"
        assert parse_effect(entry, source, "Probe").scope == expected, source
    assert parse_effect({**entry, "scope": "player"}, "building", "Probe").scope == "player"


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
