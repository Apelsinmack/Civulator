"""Issue #116 P4: civics, governments and policy loadouts (docs/progression_design.md
§5, §13, "v2 fixes"; the §14 rows on loadouts, the defaults and
`game_progress`).

No test pins which civics, governments or cards exist, how many, or in what
order: each asserts the rule every configured one -- or every state along a
seeded game -- obeys. Rules about one card or government use synthetic ones
added to the registries for one test (tests/conftest.py).
"""

import random

import pytest

from civulator import research_model
from civulator.effects import card_available, loadout_is_legal, policies_in_force, slot_counts
from civulator.game import districts as districts_mod
from civulator.game.availability import NO_GOVERNMENT_TIER, government_tier
from civulator.game.defaults import default_civic, default_government, default_loadout
from civulator.game.environment import GameEnvironment
from civulator.game.yields import city_yield
from civulator.research_model import (
    CIVIC_COST_PERCENT,
    CIVIC_INDEX,
    CIVIC_ORDER,
    CIVICS,
    ERAS,
    GOVERNMENTS,
    POLICIES,
    POLICY_TYPES,
    TECHS,
    parse_governments,
    parse_policies,
    parse_research,
    parse_tree,
    scaled_civic_cost,
)

from conftest import grant_all, grant_civic, synthetic_civic, synthetic_government, synthetic_policy
from test_districts import board, make_city

# Two civics with no effects of their own (so granting them changes nothing
# but what they unlock); LATER also has prerequisites.
QUIET = next(c for c in CIVIC_ORDER if not CIVICS[c].effects)
LATER = next(c for c in reversed(CIVIC_ORDER)
             if c != QUIET and not CIVICS[c].effects and CIVICS[c].requires)
GOV = "Synthetic Government"


def _available(known):
    """Available civics, re-derived: not known, every prerequisite known."""
    return [c for c in CIVICS if c not in known and all(r in known for r in CIVICS[c].requires)]


def _pool_cost(civic):
    """The culture pool (tenths) a civic costs: 10 * (cost * percent // 100)."""
    return 10 * (CIVICS[civic].cost * CIVIC_COST_PERCENT // 100)


def _fresh_player(env, index=0):
    """A board player with no civics and no government (board() grants both trees)."""
    player = env.players[index]
    player.civics.clear()
    player.current_civic = None
    player.government = None
    player.policies = []
    return player


# --- The tree, governments and cards ---------------------------------------------------


def test_the_civics_graph_is_acyclic_and_every_civic_is_reachable():
    """Every prerequisite is a civic and learning whatever is available,
    round after round, learns the whole tree from its start set. Breaks on a
    dead or unreachable civic (design §14)."""
    assert CIVICS, "fixture: a civics tree is configured"
    for spec in CIVICS.values():
        assert all(r in CIVICS for r in spec.requires) and spec.era in ERAS
        assert isinstance(spec.cost, int) and spec.cost > 0
    known = []
    while True:
        ready = _available(known)
        if not ready:
            break
        known.extend(ready)
    assert sorted(known) == sorted(CIVICS)


def test_every_government_and_card_is_reachable_and_slottable():
    """Every government and card names a civic (so it is reachable: every
    civic is), every card's type is a slot type, no card is obsolete the
    moment it unlocks, and every card fits some government's slots. Breaks
    on a government or card no game can ever use (§14 row 'every government
    is reachable')."""
    assert GOVERNMENTS and POLICIES, "fixture: governments and cards are configured"
    for spec in GOVERNMENTS.values():
        assert spec.requires_civic in CIVICS and isinstance(spec.tier, int) and spec.tier >= 0
    for spec in POLICIES.values():
        assert spec.requires_civic in CIVICS and spec.type in POLICY_TYPES
        if spec.obsolete_with is not None:
            assert spec.obsolete_with in CIVICS
            assert spec.obsolete_with != spec.requires_civic
            assert spec.obsolete_with not in research_model.ancestors(CIVICS, spec.requires_civic)
    env = board()
    player = env.players[0]
    fits = set()
    for name in GOVERNMENTS:
        assert env.set_government(player, name)
        for card in POLICIES:
            if card_available(player, card) and loadout_is_legal(player, [card]):
                fits.add(card)
    obsolete_at_end = {c for c in POLICIES if not card_available(player, c)}
    assert fits | obsolete_at_end == set(POLICIES)


@pytest.mark.parametrize("parse", [
    lambda: parse_governments({"G": {"requires_civic": "Nowhere", "tier": 0}}, CIVICS),
    lambda: parse_governments({"G": {"requires_civic": QUIET, "tier": -1}}, CIVICS),
    lambda: parse_governments({"G": {"requires_civic": QUIET, "tier": True}}, CIVICS),
    lambda: parse_governments({"G": {"requires_civic": QUIET}}, CIVICS),
    lambda: parse_governments({"G": {"requires_civic": QUIET, "tier": 0, "slots": 2}}, CIVICS),
    lambda: parse_governments({"G": {"requires_civic": QUIET, "tier": 0, "effects": {}}}, CIVICS),
    lambda: parse_governments({}, CIVICS),
    lambda: parse_policies({"P": {"type": "diplomatic", "requires_civic": QUIET}}, CIVICS),
    lambda: parse_policies({"P": {"type": "economic", "requires_civic": "Nowhere"}}, CIVICS),
    lambda: parse_policies({"P": {"type": "economic"}}, CIVICS),
    lambda: parse_policies({"P": {"type": "economic", "requires_civic": QUIET,
                                  "obsolete_with": "Nowhere"}}, CIVICS),
    lambda: parse_policies({"P": {"type": "economic", "requires_civic": QUIET,
                                  "obsolete_with": QUIET}}, CIVICS),
    lambda: parse_policies({"P": {"type": "economic", "requires_civic": LATER,
                                  "obsolete_with": sorted(
                                      research_model.ancestors(CIVICS, LATER))[0]}}, CIVICS),
    lambda: parse_policies({"P": {"type": "economic", "requires_civic": QUIET,
                                  "cost": 5}}, CIVICS),
    lambda: parse_research({"tech_cost_percent": 75}),
    lambda: parse_research({"tech_cost_percent": 75, "civic_cost_percent": 0}),
    lambda: parse_tree({"A": {"cost": 10, "era": ERAS[0], "requires": ["A"]}}, "civics"),
])
def test_a_malformed_government_card_or_civic_raises_at_load(parse):
    """A government or card naming no civic, a bad tier or type, an
    obsolete_with known before the card unlocks, an unknown key, a missing
    civic_cost_percent and a cyclic civics tree raise. Breaks if any of it
    is accepted."""
    with pytest.raises(ValueError):
        parse()


# --- (g) civic resolution mirrors research ---------------------------------------------


def test_a_civic_completes_exactly_when_the_pool_reaches_the_scaled_cost():
    """One point short: nothing. At the cost plus a remainder: the civic
    completes, exactly the cost is paid, the remainder stays, the choice
    clears and the counter rises by one. Breaks if resolution drifts from
    10 * scaled cost or drops the overflow."""
    env = board()
    player = _fresh_player(env)
    civic = _available(player.civics)[0]
    assert env.set_civic(player, civic)
    cost = _pool_cost(civic)
    stats = env.episode_stats[player.player_index]
    player.culture = cost - 1
    assert env.resolve_civic(player) is None
    assert player.civics == [] and player.culture == cost - 1 and player.current_civic == civic
    player.culture = cost + 7
    assert env.resolve_civic(player) == civic
    assert player.civics == [civic] and player.culture == 7 and player.current_civic is None
    assert stats["civics_researched"] == 1


def test_at_most_one_civic_completes_per_turn_and_the_overflow_waits():
    """A pool large enough for the whole tree completes exactly one civic per
    own turn, paying exactly its cost. Breaks if civic resolution loops
    within a turn."""
    env = board()
    player = _fresh_player(env)
    assert not player.cities
    huge = 2 * sum(_pool_cost(c) for c in CIVICS)
    player.culture = huge
    paid = 0
    for turn in range(1, 4):
        env.turn_counter += 1
        player.start_turn()
        assert len(player.civics) == turn
        paid += _pool_cost(player.civics[-1])
        assert player.culture == huge - paid


def test_completion_order_is_kept_and_every_completed_civic_was_available():
    """`Player.civics` lists completed civics in completion order, each
    after its prerequisites; the whole tree completes and the counter
    matches. Breaks if civics become a set or the prerequisite check goes."""
    env = board()
    player = _fresh_player(env)
    player.culture = 2 * sum(_pool_cost(c) for c in CIVICS)
    while env.resolve_civic(player) is not None:
        pass
    assert sorted(player.civics) == sorted(CIVICS)
    for i, civic in enumerate(player.civics):
        assert all(r in player.civics[:i] for r in CIVICS[civic].requires), civic
    assert env.episode_stats[player.player_index]["civics_researched"] == len(CIVICS)
    assert default_civic(player) is None and player.current_civic is None


def test_set_civic_refuses_an_unavailable_civic_and_changes_nothing():
    """set_civic refuses an unknown name, a civic behind an unknown
    prerequisite and a known civic, keeping the current choice; it accepts
    an available one, and switching keeps the pool. Breaks if an agent could
    develop civics out of order or twice."""
    env = board()
    player = _fresh_player(env)
    start = _available(player.civics)
    assert env.set_civic(player, start[0])
    locked = [c for c in CIVICS if c not in start]
    assert locked, "fixture: some civic sits behind a prerequisite"
    for bad in ["Alchemy", locked[0]]:
        assert env.set_civic(player, bad) is False and player.current_civic == start[0]
    player.civics.append(start[0])
    assert env.set_civic(player, start[0]) is False
    follow = _available(player.civics)[0]
    player.culture = _pool_cost(follow)
    assert env.set_civic(player, follow) and player.culture == _pool_cost(follow)
    assert env.resolve_civic(player) == follow


def test_the_default_picks_the_cheapest_available_civic_by_cost_then_config_order():
    """With no choice made the default is the available civic minimising
    (scaled cost, config index), in every state along seeded random orders;
    None once the tree is known. Breaks if it reads set order, ignores
    prerequisites or the scaling."""
    rng = random.Random(116)
    for _ in range(20):
        known = []
        while True:
            options = _available(known)
            player = type("P", (), {"civics": known})()
            if not options:
                assert default_civic(player) is None
                break
            expected = min(options, key=lambda c: (
                CIVICS[c].cost * CIVIC_COST_PERCENT // 100, list(CIVICS).index(c)))
            assert default_civic(player) == expected
            known = known + [rng.choice(options)]


def test_this_turns_culture_counts_toward_this_turns_civic():
    """A culture pool one turn's yield short of the default civic's cost
    completes it during that turn's start: the yield phase accrues first.
    Breaks if civics resolve before the cities."""
    env = board()
    player = _fresh_player(env)
    city = make_city(env, (3, 4))
    gain = city_yield(city, "culture")
    assert gain > 0
    civic = default_civic(player)
    player.culture = _pool_cost(civic) - gain
    env.turn_counter += 1
    player.start_turn()
    assert player.civics == [civic] and player.culture == 0


def test_civics_researched_is_a_declared_int_counter():
    """`civics_researched` is declared at 0 for every player. Breaks if the
    key is created lazily."""
    env = board()
    for stats in env.episode_stats.values():
        assert stats["civics_researched"] == 0 and type(stats["civics_researched"]) is int


def test_the_scaled_civic_cost_is_whole_points_of_the_percent():
    """Every civic costs cost * [research] civic_cost_percent // 100 whole
    culture. Breaks on float arithmetic or the tech dial being used."""
    for civic, spec in CIVICS.items():
        assert scaled_civic_cost(civic) == spec.cost * CIVIC_COST_PERCENT // 100
        assert type(scaled_civic_cost(civic)) is int
    assert research_model.CIVIC_ORDER == tuple(research_model.CFG["civics"])
    assert all(CIVIC_ORDER[CIVIC_INDEX[c]] == c for c in CIVICS)


# --- Governments: adoption and slots ------------------------------------------------


def test_set_government_needs_the_civic_and_refuses_anything_else():
    """set_government refuses an unknown name and a government whose civic
    is not known (False, nothing changed), and accepts one whose civic is.
    Breaks if a government could be adopted before its civic."""
    env = board()
    player = _fresh_player(env)
    for name, spec in GOVERNMENTS.items():
        assert env.set_government(player, name) is False and player.government is None
        grant_civic(player, spec.requires_civic)
        assert env.set_government(player, name) is True and player.government == name
        player.civics.clear()
        player.government = None
    assert env.set_government(player, "Anarchy") is False and player.government is None


def test_slot_counts_are_the_governments_slots_plus_every_other_slot_effect(monkeypatch):
    """slot_counts = the government's `policy_slots` + every other
    `policy_slots` effect in force (here a known civic's); no government
    = only the other effects. Every configured government's slots are its
    own effect. Breaks if a source is ignored or counted twice."""
    env = board()
    player = _fresh_player(env)
    grant_civic(player, QUIET)
    assert slot_counts(player) == dict.fromkeys(POLICY_TYPES, 0)
    synthetic_government(monkeypatch, GOV, {"military": 1, "economic": 2, "wildcard": 3},
                         requires_civic=QUIET)
    assert env.set_government(player, GOV)
    assert slot_counts(player) == {"military": 1, "economic": 2, "wildcard": 3}
    synthetic_civic(monkeypatch, "Synthetic Civic", [{"kind": "policy_slots", "wildcard": 1}])
    grant_civic(player, "Synthetic Civic")
    assert slot_counts(player) == {"military": 1, "economic": 2, "wildcard": 4}
    player.government = None
    assert slot_counts(player) == {"military": 0, "economic": 0, "wildcard": 1}
    player.civics.remove("Synthetic Civic")
    from civulator.effects import effects_of
    for name in GOVERNMENTS:
        grant_civic(player, GOVERNMENTS[name].requires_civic)
        assert env.set_government(player, name)
        expected = dict.fromkeys(POLICY_TYPES, 0)
        for effect in effects_of("government", name):
            if effect.kind == "policy_slots":
                for t, n in effect["slots"].items():
                    expected[t] += n
        civic_slots = dict.fromkeys(POLICY_TYPES, 0)
        for civic in player.civics:
            for effect in effects_of("civic", civic):
                if effect.kind == "policy_slots":
                    for t, n in effect["slots"].items():
                        civic_slots[t] += n
        assert slot_counts(player) == {t: expected[t] + civic_slots[t] for t in POLICY_TYPES}


def test_the_government_tier_is_minus_one_without_a_government():
    """No government is below every tier (a tier gate refuses), and with
    one the tier is its config tier. Breaks if None reads as tier 0."""
    env = board()
    player = _fresh_player(env)
    assert government_tier(player) == NO_GOVERNMENT_TIER < min(g.tier for g in GOVERNMENTS.values())
    for name, spec in GOVERNMENTS.items():
        player.government = name
        assert government_tier(player) == spec.tier


# --- (d) loadout legality -----------------------------------------------------------


class Loadout:
    """A player under a synthetic government of `slots`, knowing QUIET only,
    with synthetic cards: Econ (+1 science), Econ2 (+1 culture), Mil (+1
    gold), Old (+1 faith; obsolete with LATER), Locked (+1 food; unlocked by
    LATER), all but Locked unlocked by QUIET."""

    def __init__(self, monkeypatch, slots):
        self.env = env = board()
        self.player = player = _fresh_player(env)
        grant_civic(player, QUIET)
        self.city = make_city(env, (3, 4), population=3)
        for name, card_type, y, civic, obsolete in (
            ("Econ", "economic", "science", QUIET, None),
            ("Econ2", "economic", "culture", QUIET, None),
            ("Mil", "military", "gold", QUIET, None),
            ("Old", "economic", "faith", QUIET, LATER),
            ("Locked", "economic", "food", LATER, None),
        ):
            synthetic_policy(monkeypatch, name, [{"kind": "city_yield", y: 1}], type=card_type,
                             requires_civic=civic, obsolete_with=obsolete)
        synthetic_government(monkeypatch, GOV, slots, requires_civic=QUIET)
        assert env.set_government(player, GOV)
        assert env.set_policies(player, [])

    def yields(self):
        return {y: city_yield(self.city, y) for y in ("science", "culture", "gold", "faith", "food")}


@pytest.mark.parametrize("slots, loadout, why", [
    ({"economic": 1}, ["Mil"], "a military card in an economic slot"),
    ({"economic": 2}, ["Econ", "Econ"], "a card twice"),
    ({"economic": 1}, ["Econ", "Econ2"], "more cards than slots"),
    ({"economic": 1, "wildcard": 1}, ["Econ", "Econ2", "Mil"], "more cards than slots"),
    ({"economic": 1}, ["Locked"], "a card whose civic is unknown"),
    ({"economic": 1}, ["Nowhere"], "a card that does not exist"),
    ({"economic": 1}, [3], "not a card name"),
])
def test_set_policies_refuses_an_illegal_loadout_and_changes_nothing(monkeypatch, slots, loadout,
                                                                    why):
    """set_policies refuses (False) a wrong type, a duplicate, an overfull
    loadout, a locked or unknown card; the loadout and every yield stay as
    they were. Breaks if the legality check drifts (§14 'a card of the wrong
    type, ... set_policies refuses an illegal loadout')."""
    stage = Loadout(monkeypatch, slots)
    before = stage.yields()
    assert stage.env.set_policies(stage.player, loadout) is False, why
    assert stage.player.policies == [] and stage.yields() == before, why


@pytest.mark.usefixtures("neutral_amenities")  # v0.9.0 Q2: not about the amenity band
def test_an_obsolete_card_is_refused_and_has_no_effect_even_if_slotted(monkeypatch):
    """Once its obsolete_with civic is known a card cannot be slotted, and a
    card already in the list (written there directly) has no effect.
    Breaks if obsolescence is checked only at slotting time."""
    stage = Loadout(monkeypatch, {"economic": 1})
    base = stage.yields()
    assert stage.env.set_policies(stage.player, ["Old"])
    assert stage.yields()["faith"] == base["faith"] + 10
    grant_civic(stage.player, LATER)
    assert stage.yields()["faith"] == base["faith"], "an obsolete card has no effect"
    assert policies_in_force(stage.player) == []
    stage.player.policies = []
    assert stage.env.set_policies(stage.player, ["Old"]) is False


@pytest.mark.usefixtures("neutral_amenities")  # v0.9.0 Q2: not about the amenity band
def test_only_slotted_legal_cards_have_effects(monkeypatch):
    """An unlocked but unslotted card has no effect; a slotted one has; a
    wildcard slot takes a card of any type; cards written past the slots
    directly have no effect beyond the ones that fit, oldest first. Breaks
    if effects are gathered from unlocked cards or from the raw list."""
    stage = Loadout(monkeypatch, {"economic": 1, "wildcard": 1})
    base = stage.yields()
    assert all(card_available(stage.player, c) for c in ("Econ", "Econ2", "Mil", "Old"))
    assert stage.yields() == base, "unlocked, unslotted cards do nothing"
    assert stage.env.set_policies(stage.player, ["Econ", "Mil"])
    after = stage.yields()
    assert after["science"] == base["science"] + 10 and after["gold"] == base["gold"] + 10
    assert after["culture"] == base["culture"]
    stage.player.policies = ["Econ", "Mil", "Econ2"]   # bypassing set_policies
    assert policies_in_force(stage.player) == ["Econ", "Mil"]
    assert stage.yields() == after


# --- Defaults (§13 as amended by v2) --------------------------------------------------


def test_default_loadout_keeps_legal_cards_then_fills_newest_first(monkeypatch):
    """default_loadout keeps the current legal cards in order, then fills
    each empty typed slot with the newest unlocked card of that type, then
    wildcard slots with the newest of any type -- newest = unlocked by the
    later civic in completion order, then config order. Breaks if it
    reorders kept cards, fills from config order alone, or leaves a slot
    empty while a card could fill it."""
    env = board()
    player = _fresh_player(env)
    first, second = QUIET, LATER
    grant_civic(player, first, second)
    for name, card_type, civic in (("Old M", "military", first), ("Old E", "economic", first),
                                   ("New M", "military", second), ("New E", "economic", second),
                                   ("New E2", "economic", second)):
        synthetic_policy(monkeypatch, name, [], type=card_type, requires_civic=civic)
    monkeypatch.setattr(research_model, "POLICIES", {
        n: s for n, s in research_model.POLICIES.items()
        if n in ("Old M", "Old E", "New M", "New E", "New E2")})
    synthetic_government(monkeypatch, GOV, {"military": 1, "economic": 1, "wildcard": 1},
                         requires_civic=first)
    player.government = GOV
    player.policies = ["Old E"]
    assert default_loadout(player) == ["Old E", "New M", "New E"]
    player.policies = []
    assert default_loadout(player) == ["New M", "New E", "New E2"]
    for loadout in (["Old E"], []):
        player.policies = loadout
        result = default_loadout(player)
        assert loadout_is_legal(player, result)
        spare = [c for c in research_model.POLICIES if c not in result and card_available(player, c)]
        assert not any(loadout_is_legal(player, result + [c]) for c in spare), "maximal"


def test_set_government_refits_the_loadout_when_the_slots_change(monkeypatch):
    """Adopting a government with fewer slots drops the newest-slotted cards
    that no longer fit and keeps the rest in order; adopting one with more
    fills the new slots by the default. The loadout is legal after every
    change. Breaks if a government change can leave an illegal loadout."""
    stage = Loadout(monkeypatch, {"economic": 2})
    env, player = stage.env, stage.player
    assert env.set_policies(player, ["Econ2", "Econ"])
    synthetic_government(monkeypatch, "Small", {"economic": 1}, requires_civic=QUIET)
    assert env.set_government(player, "Small")
    assert player.policies == ["Econ2"] and loadout_is_legal(player, player.policies)
    synthetic_government(monkeypatch, "Large", {"economic": 1, "military": 1, "wildcard": 1},
                         requires_civic=QUIET)
    assert env.set_government(player, "Large")
    assert player.policies[0] == "Econ2" and len(player.policies) == 3
    assert loadout_is_legal(player, player.policies)


def test_default_government_takes_the_highest_tier_known_above_the_current_one():
    """default_government names the highest-tier government whose civic is
    known and whose tier exceeds the current one (ties: config order), or
    None. Breaks if it downgrades, ignores the civic, or reads set order."""
    env = board()
    player = _fresh_player(env)
    assert default_government(player) is None
    for civic in CIVIC_ORDER:
        grant_civic(player, civic)
        current = government_tier(player)
        known = [g for g in GOVERNMENTS.values() if g.requires_civic in player.civics]
        better = [g for g in known if g.tier > current]
        choice = default_government(player)
        if not better:
            assert choice is None
            continue
        top = max(g.tier for g in better)
        assert choice == next(g.name for g in better if g.tier == top)
        player.government = choice


def _play(seed, rounds, culture=0):
    env = GameEnvironment(8, 16, num_players=2, map_type="basic").reset(seed=seed)
    for player in env.players:
        player.culture += culture
    log = []
    for _ in range(rounds * len(env.players)):
        before = {p.player_index: (list(p.civics), government_tier(p)) for p in env.players}
        env.next_turn()
        player = env.current_player
        log.append((player.player_index, before[player.player_index], list(player.civics),
                    player.government, list(player.policies)))
    return env, log


def test_a_seeded_game_with_no_choice_adopts_governments_and_slots_cards_by_the_rules():
    """A seeded two-player game where nobody chooses (a culture grant makes
    one civic complete per turn): after every own turn the government is
    the best the known civics allow (default_government has nothing
    better), a civic that unlocks a higher tier is adopted the same turn it
    completes, and the loadout is legal and full (no unslotted card could
    be added). By the end the top tier is reached. Two runs of the same seed
    give identical civics, governments and cards. Breaks if a default is
    dormant, late or non-deterministic (§14 'Defaults')."""
    grant = 2 * sum(_pool_cost(c) for c in CIVICS)
    env, log = _play(7, len(CIVICS) + 3, culture=grant)
    adopted_tiers = set()
    for index, (old_civics, old_tier), civics, government, policies in log:
        new = [c for c in civics if c not in old_civics]
        assert len(new) <= 1
        tier = GOVERNMENTS[government].tier if government else NO_GOVERNMENT_TIER
        best_known = max((g.tier for g in GOVERNMENTS.values() if g.requires_civic in civics),
                         default=NO_GOVERNMENT_TIER)
        assert tier == max(best_known, old_tier), (civics, government)
        adopted_tiers.add(tier)
    for player in env.players:
        assert sorted(player.civics) == sorted(CIVICS)
        assert government_tier(player) == max(g.tier for g in GOVERNMENTS.values())
        assert loadout_is_legal(player, player.policies) and player.policies
        spare = [c for c in POLICIES if c not in player.policies and card_available(player, c)]
        assert not any(loadout_is_legal(player, player.policies + [c]) for c in spare)
    assert {g.tier for g in GOVERNMENTS.values()} <= adopted_tiers, "every tier was adopted"
    _, again = _play(7, len(CIVICS) + 3, culture=grant)
    assert again == log


def test_a_seeded_game_without_grants_develops_civics_and_adopts_a_government():
    """With only turn ends played and no grant, every player completes a
    civic, adopts a government and slots a card within 40 rounds, and the
    counter matches. Breaks if the civic default is dormant in real play."""
    env, _ = _play(5, 40)
    for player in env.players:
        assert player.civics and player.government is not None and player.policies
        assert env.episode_stats[player.player_index]["civics_researched"] == len(player.civics)


def test_reset_clears_civics_government_and_policies():
    """Player.reset_state declares every P4 field: after play, reset(seed)
    gives a player with no civic, no government and no card. Breaks if a
    field leaks across episodes."""
    env, _ = _play(5, 30)
    assert any(p.civics for p in env.players)
    env.reset(seed=5)
    for player in env.players:
        assert (player.civics, player.current_civic, player.government, player.policies) == \
            ([], None, None, [])


# --- (i) game_progress ------------------------------------------------------------------


def test_game_progress_is_the_larger_tree_fraction_ties_to_techs():
    """game_progress = the larger of (techs known, techs) and (civics known,
    civics), compared without floats; a tie is the tech fraction. Breaks if
    the civic tree is ignored or the comparison rounds."""
    from types import SimpleNamespace
    t_total, c_total = len(TECHS), len(CIVICS)
    for t in range(t_total + 1):
        for c in range(c_total + 1):
            player = SimpleNamespace(techs=[None] * t, civics=[None] * c)
            result = districts_mod.game_progress(player)
            if c * t_total > t * c_total:
                assert result == (c, c_total), (t, c)
            else:
                assert result == (t, t_total), (t, c)


def test_grant_all_knows_both_trees():
    """The shared helper grants every tech and every civic (tests/conftest).
    Breaks if it drifts from the trees."""
    env = board()
    player = _fresh_player(env)
    grant_all(player)
    assert sorted(player.civics) == sorted(CIVICS) and sorted(player.techs) == sorted(TECHS)
    assert default_civic(player) is None
