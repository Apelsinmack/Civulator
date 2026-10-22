"""Religion I (v0.9.0 Q7, docs/districts_religion_design.md §7.2, §7.6, §9, §11):
the religion registry, pantheons, the pantheon action and its engine default,
and the three effect kinds pantheons brought (`border_cost_percent`,
`improvement_yield`, `adjacency_row`) plus the `no_specialty_district` target
attribute of `production_percent`.

Every test asserts a property and names the change that breaks it. Nothing
here pins the number, order or names of the configured pantheons: registry
tests iterate over whatever `[pantheons.*]` holds.
"""

import ast
import pathlib

import pytest

from civulator import district_model, effects, religion_model, terrain_model
from civulator.effects import SOURCE_PANTHEON, active_effects, effects_of
from civulator.game import districts as districts_mod
from civulator.game import territory
from civulator.game.defaults import default_pantheon
from civulator.game.environment import GameEnvironment
from civulator.game.religion import can_choose_pantheon, pantheon_cost_tenths
from civulator.game.yields import city_yield
from civulator.religion_model import (
    PANTHEON_ORDER,
    PANTHEONS,
    PantheonSpec,
    check_pressure_weights,
    parse_beliefs,
    parse_pantheons,
    parse_religion,
)
from civulator.unit_model import YIELD_COLUMNS

from conftest import grant_all
from test_districts import board, make_city, neighbours, own, ring

pytestmark = pytest.mark.usefixtures("neutral_amenities")

PROBE = "Probe Pantheon"


def _pantheon(monkeypatch, entries, name=PROBE):
    """A synthetic `[pantheons.*]` entry for one test, in the registry every
    reader sees (`religion_model.PANTHEONS`)."""
    monkeypatch.setitem(religion_model.PANTHEONS, name,
                        PantheonSpec(name=name, effects=tuple(entries)))
    return name


def _religion_table(**overrides):
    table = dict(pantheon_cost=25, found_cost=200, belief_costs=[300, 500], max_religions=0,
                 exclusive=True, range=9, citizen_weight=10, secular_weight=2,
                 conversion_margin=25, conversion_rounds=3, spread_cost=100,
                 spread_cost_step=25, spread_amount=60, spread_rounds=10,
                 upkeep_per_follower_city=1, inquisition_cost=75, inquisition_rounds=10,
                 foreign_religion_loyalty=-1)
    table.update(overrides)
    return {k: v for k, v in table.items() if v is not None}


# --- (a) [religion] validation ------------------------------------------------------


def test_the_configured_religion_table_parses():
    """The shipped `[religion]` table is valid and its pantheon cost is what
    the pantheon predicate charges. Breaks if the config gains a junk key or
    the predicate reads a second cost."""
    assert religion_model.RULES == parse_religion(dict(religion_model.CFG["religion"]))
    assert pantheon_cost_tenths() == 10 * religion_model.RULES.pantheon_cost


@pytest.mark.parametrize("key, bad", [
    ("pantheon_cost", -1), ("found_cost", -1), ("max_religions", -1), ("range", 0),
    ("secular_weight", -1), ("conversion_margin", -1), ("conversion_rounds", 0),
    ("spread_cost", -1), ("spread_cost_step", -1), ("spread_amount", 0), ("spread_rounds", 0),
    ("upkeep_per_follower_city", -1), ("inquisition_cost", -1), ("inquisition_rounds", 0),
    ("pantheon_cost", 2.5), ("foreign_religion_loyalty", True), ("exclusive", 1),
    ("belief_costs", [300]), ("belief_costs", [300, 500, 700]), ("belief_costs", [300, -1]),
    ("belief_costs", 300),
])
def test_each_religion_bound_raises(key, bad):
    """Every `[religion]` value outside its bound (design §7.6) raises at
    load. Breaks if a bound is dropped from `religion_model.parse_religion`."""
    with pytest.raises(ValueError):
        parse_religion(_religion_table(**{key: bad}))


def test_unknown_and_missing_religion_keys_raise():
    """Strict keys: a typo or a missing key raises. Breaks if the key list
    loosens."""
    with pytest.raises(ValueError):
        parse_religion({**_religion_table(), "pantheon_costs": 25})
    table = _religion_table()
    del table["spread_rounds"]
    with pytest.raises(ValueError):
        parse_religion(table)


@pytest.mark.parametrize("weight, reach, ok", [(10, 9, True), (9, 9, False), (5, 9, False)])
def test_citizen_weight_must_exceed_range(weight, reach, ok):
    """v3 fixes L3: `citizen_weight > range`, at load and through the
    two-number check Q8/Q9 re-run after a `religion_param`. Breaks if the
    check becomes `>=` or is skipped."""
    if ok:
        check_pressure_weights(weight, reach)
        parse_religion(_religion_table(citizen_weight=weight, range=reach))
    else:
        with pytest.raises(ValueError):
            check_pressure_weights(weight, reach)
        with pytest.raises(ValueError):
            parse_religion(_religion_table(citizen_weight=weight, range=reach))


# --- (b) the pantheon and belief registries -----------------------------------------


def test_every_configured_pantheon_parses_with_player_scope_effects_only():
    """Registry property over `[pantheons.*]`: every table validates through
    the effects interpreter, carries at least one effect, every effect has a
    consumer and is player-scoped (a pantheon stands in no city). Breaks if a
    pantheon names an unknown kind or the source admits city scope."""
    assert PANTHEONS, "fixture: pantheons are configured"
    for name in PANTHEONS:
        parsed = effects_of(SOURCE_PANTHEON, name)
        assert parsed, name
        for effect in parsed:
            assert effect.scope == effects.SCOPE_PLAYER, name
            assert effect.kind in effects.CONSUMERS, name
            assert effect.kind not in effects.ONE_SHOT_KINDS, name


def test_a_city_scoped_or_one_shot_pantheon_effect_raises():
    """A pantheon effect cannot be city-scoped or a one-shot. Breaks if the
    pantheon source joins the city sources or the one-shot rule."""
    with pytest.raises(ValueError):
        effects.parse_effect({"kind": "growth_percent", "percent": 5, "scope": "city"},
                             SOURCE_PANTHEON, "X")
    with pytest.raises(ValueError):
        effects.parse_effect({"kind": "free_tech", "count": 1}, SOURCE_PANTHEON, "X")


@pytest.mark.parametrize("table", [
    {"effects": []}, {}, {"effects": [{"kind": "growth_percent", "percent": 5}], "tier": "x"},
    {"effects": [{"kind": "growth_percent", "percent": 5}], "description": 3},
])
def test_a_malformed_pantheon_table_raises(table):
    """A pantheon is `effects` (non-empty) plus an optional description --
    nothing else. Breaks if the strict keys loosen."""
    with pytest.raises(ValueError):
        parse_pantheons({"Bad": table})


def test_belief_tables_validate_tier_counts_and_building():
    """The `[beliefs.*]` shape Q8 fills: a tier of three, `counts` required on
    a founder belief and refused elsewhere, `requires_building` a building.
    Breaks if the parser loosens before Q8 relies on it."""
    effect = [{"kind": "growth_percent", "percent": 5}]
    building = next(iter(religion_model.BUILDING_NAMES))
    ok = parse_beliefs({
        "F": {"tier": "founder", "counts": "foreign", "effects": effect},
        "W": {"tier": "follower", "requires_building": building, "effects": effect},
        "E": {"tier": "enhancer", "effects": effect},
    })
    assert [s.tier for s in ok.values()] == ["founder", "follower", "enhancer"]
    for bad in ({"tier": "founder", "effects": effect},
                {"tier": "follower", "counts": "all", "effects": effect},
                {"tier": "prophet", "effects": effect},
                {"tier": "follower", "requires_building": "No Such", "effects": effect},
                {"tier": "follower", "effects": []},
                {"tier": "follower", "effects": effect, "junk": 1}):
        with pytest.raises(ValueError):
            parse_beliefs({"B": bad})


# --- (c) the pantheon action --------------------------------------------------------


def _env():
    env = board()
    make_city(env, (3, 4))
    make_city(env, (5, 12), player_index=1)
    return env


def test_choose_pantheon_refuses_without_faith_twice_or_unknown():
    """`can_choose_pantheon` and `choose_pantheon` refuse a player short of
    `pantheon_cost` faith, a second pantheon, and a name that is no pantheon
    -- and a refusal changes nothing. Breaks if the predicate drops a clause
    (§11 pantheon refusals)."""
    env = _env()
    player = env.players[0]
    first, second = PANTHEON_ORDER[0], PANTHEON_ORDER[-1]
    player.faith = pantheon_cost_tenths() - 1
    assert not can_choose_pantheon(player, first, env)
    assert not env.choose_pantheon(player, first)
    assert (player.faith, player.pantheon) == (pantheon_cost_tenths() - 1, None)
    player.faith = 3 * pantheon_cost_tenths()
    assert not env.choose_pantheon(player, "No Such Pantheon")
    assert player.pantheon is None
    assert env.choose_pantheon(player, first)
    faith = player.faith
    assert not can_choose_pantheon(player, second, env)
    assert not env.choose_pantheon(player, second)
    assert (player.pantheon, player.faith) == (first, faith)


def test_choosing_debits_exactly_the_cost_and_is_permanent():
    """Choosing debits exactly `pantheon_cost` (tenths), sets the pantheon,
    counts it, and the pantheon outlives the player's every city (Civ 6).
    Breaks if the debit is off, the counters miss it, or a city's removal
    clears it."""
    env = _env()
    player = env.players[0]
    player.faith = pantheon_cost_tenths() + 7
    name = PANTHEON_ORDER[0]
    assert env.choose_pantheon(player, name)
    assert player.faith == 7
    assert player.pantheon == name
    stats = env.episode_stats[0]
    assert stats["pantheons_chosen"] == 1
    assert stats["faith_spent_religion"] == pantheon_cost_tenths()
    for city in list(player.cities):
        env.remove_city(city)
    assert player.pantheon == name


def test_the_pantheons_effects_are_in_force_for_the_player_and_every_city(monkeypatch):
    """The chosen pantheon is an effects source: its entries are in force
    for its player and in every one of its cities, never for another player.
    Breaks if `active_effects` misses the pantheon source or leaks it."""
    env = _env()
    player, other = env.players
    make_city(env, (6, 7))
    name = _pantheon(monkeypatch, [{"kind": "growth_percent", "percent": 5}])
    player.pantheon = name  # fixture: the action is tested above
    source = (SOURCE_PANTHEON, name)
    assert source in [e.source for e in active_effects(player)]
    for city in player.cities:
        assert source in [e.source for e in active_effects(player, city)]
    assert source not in [e.source for e in active_effects(other)]
    for city in other.cities:
        assert source not in [e.source for e in active_effects(other, city)]


# --- (d) the engine default -----------------------------------------------------------


def test_the_default_takes_the_first_affordable_pantheon_in_config_order():
    """`default_pantheon` picks the first pantheon of config order when the
    player can afford one, nothing when it cannot or already has one; the
    economy phase applies it. Breaks if the default reads a set, ranks
    differently, spends what the player does not have, or leaves the
    economy phase."""
    env = _env()
    player = env.players[0]
    player.faith = pantheon_cost_tenths() - 1
    assert default_pantheon(player, env) is None
    player.faith = pantheon_cost_tenths()
    assert default_pantheon(player, env) == PANTHEON_ORDER[0]
    env.economy_phase(player)
    assert player.pantheon == PANTHEON_ORDER[0]
    assert player.faith == 0
    player.faith = 5 * pantheon_cost_tenths()
    assert default_pantheon(player, env) is None
    env.economy_phase(player)
    assert player.faith == 5 * pantheon_cost_tenths()


def test_same_seed_same_pantheon_choices():
    """Two seeded games, each player handed the pantheon cost at the start:
    the same pantheons are chosen at the same faith. Breaks if the default
    draws randomness or iterates a set."""
    def play():
        env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=7)
        for player in env.players:
            player.faith = pantheon_cost_tenths()
        for _ in range(2 * 3):
            env.next_turn()
        return [(p.pantheon, p.faith) for p in env.players]

    first = play()
    assert first == play()
    assert all(pantheon is not None for pantheon, _ in first)


# --- (e) border_cost_percent ----------------------------------------------------------


def test_border_cost_percent_scales_the_claiming_players_cost_only(monkeypatch):
    """Two cities, one per player, each holding exactly the claim cost the
    pantheon makes: the pantheon's owner claims a tile and pays exactly the
    scaled cost; the other, paying the unscaled `cost(n)`, cannot. `cost(n)`
    itself is unchanged. Breaks if the percent is applied to `cost(n)`, to
    every player, or not at all."""
    env = _env()
    name = _pantheon(monkeypatch, [{"kind": "border_cost_percent", "percent": -15}])
    env.players[0].pantheon = name
    mine, theirs = env.players[0].cities[0], env.players[1].cities[0]
    n = mine.border_claims + 1
    assert theirs.border_claims + 1 == n
    base = env.border_cost(n)
    scaled = territory.claim_cost(env.border_cost, n, -15)
    assert scaled == max(1, base * 85 // 100) < base
    for city in (mine, theirs):
        city.border_culture = scaled
        city.culture_this_round = 0
    claims = territory.run_border_phase(env.map, [mine, theirs], env.border_cost, env.rng)
    assert [cid for cid, _ in claims] == [mine.city_id]
    assert mine.border_culture == 0
    assert theirs.border_culture == scaled
    assert env.border_cost(n) == base
    assert territory.border_cost_percent(env.players[1]) == 0


# --- (f) improvement_yield ------------------------------------------------------------


def _worked_city(env):
    city = env.players[0].cities[0]
    city.population = 2
    city.assign_tiles(env)
    assert len(city.worked_tiles) == 2
    return city


def _all_yields(city):
    out = {y: city_yield(city, y) for y in YIELD_COLUMNS}
    out["food (calculate_food)"] = city.calculate_food(city.player.game_env)
    return out


def test_improvement_yield_pays_worked_tiles_with_the_improvement_in_all_six_yields(monkeypatch):
    """An `improvement_yield` of 1 in every yield pays once per centre or
    worked tile carrying the improvement: +1 food and production (whole
    points, reaching `calculate_food`), +10 tenths of each pool. An owned
    but unworked tile with it, and a worked tile with another improvement,
    pay nothing. Breaks if the consumer reads `Tile.yields`, unworked
    tiles, or another improvement."""
    env = _env()
    city = _worked_city(env)
    improvement, other = sorted(terrain_model.IMPROVEMENT_NAMES)[:2]
    worked, second = city.worked_tiles
    env.map.get_tile(worked).improvements.append(improvement)
    env.map.get_tile(second).improvements.append(other)
    unworked = next(p for p in ring(env, city.coordinates, 1) if p not in city.worked_tiles)
    env.map.get_tile(unworked).improvements.append(improvement)
    name = _pantheon(monkeypatch, [{"kind": "improvement_yield", "improvement": improvement,
                                    **{y: 1 for y in YIELD_COLUMNS}}])
    before = _all_yields(city)
    production_before = city.calculate_production(env)
    tile_yields = env.map.get_tile(worked).yields
    env.players[0].pantheon = name
    after = _all_yields(city)
    for key in after:
        gain = 1 if key in ("food", "production", "food (calculate_food)") else 10
        assert after[key] - before[key] == gain, key
    assert city.calculate_production(env) > production_before
    assert env.map.get_tile(worked).yields == tile_yields, "Tile.yields stays player-blind"


def test_improvement_yield_honours_the_resource_class(monkeypatch):
    """With `resource_class`, only a worked improved tile whose resource is
    of that class pays; the same improvement on a resource of another class
    or on no resource does not. Breaks if the class condition is ignored."""
    env = _env()
    city = _worked_city(env)
    improvement = sorted(terrain_model.IMPROVEMENT_NAMES)[0]
    by_class = {}
    for res, table in terrain_model.RESOURCE_TABLE.items():
        by_class.setdefault(table["class"], res)
    wanted = "strategic"
    other_class = next(c for c in by_class if c != wanted)
    name = _pantheon(monkeypatch, [{"kind": "improvement_yield", "improvement": improvement,
                                    "resource_class": wanted, "faith": 1}])
    worked, second = city.worked_tiles
    for pos in (worked, second):
        env.map.get_tile(pos).improvements.append(improvement)
    env.map.get_tile(worked).resource = by_class[other_class]
    before = city_yield(city, "faith")
    env.players[0].pantheon = name
    assert city_yield(city, "faith") == before
    env.map.get_tile(second).resource = by_class[wanted]
    assert city_yield(city, "faith") == before + 10


# --- (g) adjacency_row ------------------------------------------------------------------


def _registry(monkeypatch):
    reg = district_model.parse_districts({
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Probe": {"production_cost": 10, "adjacency_yield": "gold",
                  "adjacency": [{"amount": 3, "district": ["Marker"]}]},
        "Marker": {"production_cost": 10},
    })
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    return reg


def _put(env, city, name, pos):
    district = districts_mod.District(name, city.city_id, pos, complete=True, cost=10)
    district.city = city
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def test_adjacency_row_adds_a_floored_row_for_the_owners_districts_only(monkeypatch):
    """An `adjacency_row` (every adjacent Plains, per 4) adds floor(count /
    per) * amount to the owner's Probe -- in `adjacency_score` with the
    owner and in `district_yields` -- and nothing to the other player's
    identical Probe, to the score without an owner, or to the registry's own
    rows. Breaks if the rows reach every player, are summed before the
    floor, or edit the config rows."""
    reg = _registry(monkeypatch)
    env = _env()
    mine, theirs = env.players[0].cities[0], env.players[1].cities[0]
    probes = []
    for city in (mine, theirs):
        pos = ring(env, city.coordinates, 2)[0]
        own(env, city, pos)
        probes.append(_put(env, city, "Probe", pos))
    rows_before = reg.districts["Probe"].adjacency
    row = {"amount": 2, "per": 4, "terrain": {"bases": ["Plains"]}}
    name = _pantheon(monkeypatch, [{"kind": "adjacency_row", "district": "Probe", **row}])
    count = sum(1 for n in neighbours(env, probes[0].coordinates)
                if env.map.get_tile(n).base_terrain == "Plains")
    extra = (count // 4) * 2
    assert extra > 0, "fixture: the row pays"
    scores = {id(p): districts_mod.adjacency_score("Probe", p.coordinates, env.map, p.player)
              for p in probes}
    gold = [districts_mod.district_yields(c)["gold"] for c in (mine, theirs)]
    env.players[0].pantheon = name
    mine_probe, their_probe = probes
    assert districts_mod.adjacency_score("Probe", mine_probe.coordinates, env.map,
                                         env.players[0]) == scores[id(mine_probe)] + extra
    assert districts_mod.adjacency_score("Probe", mine_probe.coordinates,
                                         env.map) == scores[id(mine_probe)]
    assert districts_mod.adjacency_score("Probe", their_probe.coordinates, env.map,
                                         env.players[1]) == scores[id(their_probe)]
    assert districts_mod.district_yields(mine)["gold"] == gold[0] + extra
    assert districts_mod.district_yields(theirs)["gold"] == gold[1]
    assert reg.districts["Probe"].adjacency is rows_before


def test_an_adjacency_row_parses_through_the_district_row_grammar():
    """The effect's row is the config's row grammar: a bad source, a
    missing amount, and a district without an adjacency yield raise; a good
    one parses to the same `AdjacencyRow` the registry would build. Breaks if
    the effect grows its own row parser."""
    target = next(n for n, s in district_model.DISTRICTS.items()
                  if s.adjacency_yield != "none")
    flat = next(n for n, s in district_model.DISTRICTS.items()
                if s.adjacency_yield == "none" and s.kind == district_model.KIND_DISTRICT)
    row = {"amount": 1, "terrain": {"bases": ["Desert"]}}
    parsed = effects.parse_effect({"kind": "adjacency_row", "district": target, **row},
                                  SOURCE_PANTHEON, "X")
    assert parsed["row"] == district_model.parse_adjacency_row(row, "x",
                                                               district_model.DISTRICTS)
    for bad in ({"district": target, "terrain": {"bases": ["Desert"]}},
                {"district": target, "amount": 1, "terrain": {"bases": ["Nowhere"]}},
                {"district": target, "amount": 1},
                {"district": flat, **row}):
        with pytest.raises(ValueError):
            effects.parse_effect({"kind": "adjacency_row", **bad}, SOURCE_PANTHEON, "X")


def test_every_adjacency_score_call_in_the_engine_passes_the_owner():
    """Every caller of `adjacency_score` in the `civulator` package passes the
    district's owner (the fourth argument or `player=`), so the owner's rows
    are never silently dropped. Breaks if a new caller uses the three-argument
    form."""
    root = pathlib.Path(districts_mod.__file__).resolve().parents[1]
    calls = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and getattr(node.func, "id",
                                                       getattr(node.func, "attr", None))
                    == "adjacency_score"):
                calls.append((path.name, node))
    assert calls, "fixture: the engine calls adjacency_score"
    for name, node in calls:
        assert len(node.args) >= 4 or any(k.arg == "player" for k in node.keywords), name


# --- (h) no_specialty_district --------------------------------------------------------


def test_no_specialty_district_applies_only_without_a_complete_specialty_district(monkeypatch):
    """A `production_percent` toward districts with `no_specialty_district`
    raises a city's district production while it has no complete specialty
    district (an unfinished one does not count), and stops once one is
    complete; it never reaches a unit. Breaks if the condition reads placed
    districts, ignores the city, or the target leaks onto other items."""
    _registry(monkeypatch)
    env = _env()
    city = env.players[0].cities[0]
    grant_all(env.players[0])
    name = _pantheon(monkeypatch, [{"kind": "production_percent", "percent": 25,
                                    "target": {"kind": "district",
                                               "no_specialty_district": True}}])
    env.players[0].pantheon = name
    city.current_production = {"type": "district", "district_type": "Marker"}
    assert city.production_percent() == 25
    pos = ring(env, city.coordinates, 2)[0]
    own(env, city, pos)
    marker = _put(env, city, "Probe", pos)
    marker.complete = False
    assert city.production_percent() == 25
    marker.complete = True
    assert districts_mod.specialty_districts(city)
    assert city.production_percent() == 0
    city.districts.remove(marker)
    city.current_production = {"type": "unit", "unit_type": "Warrior"}
    assert city.production_percent() == 0
    assert not effects.target_matches({"kind": "district", "no_specialty_district": True},
                                      "district", "Marker")


def test_pantheon_entries_come_after_techs_and_before_buildings(monkeypatch):
    """The documented `active_effects` order: government, cards, civics,
    techs, then the pantheon, then the cities' buildings and districts.
    Breaks if the pantheon source moves or its order comes from a set."""
    env = _env()
    player = env.players[0]
    grant_all(player)
    name = _pantheon(monkeypatch, [{"kind": "growth_percent", "percent": 5}])
    player.pantheon = name
    kinds = [e.source[0] for e in active_effects(player)]
    at = kinds.index(SOURCE_PANTHEON)
    assert all(k in (effects.SOURCE_GOVERNMENT, effects.SOURCE_POLICY, effects.SOURCE_CIVIC,
                     effects.SOURCE_TECH) for k in kinds[:at])
    assert all(k in (effects.SOURCE_BUILDING, effects.SOURCE_DISTRICT) for k in kinds[at + 1:])
