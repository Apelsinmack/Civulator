"""Make the civulator package importable when running `pytest tests -q` from the repo root.

Also the shared research helpers (#116 P2, progression design "v2 fixes",
pre-existing tests table): tests whose subject is not availability grant the
whole tech tree and the whole civics tree with `grant_all`, so a gate never
decides a test about something else. Import them as `from conftest import
grant_all` (the tests directory is on sys.path, as for `from
test_combat_range import ...`).

And the synthetic-source helpers (#116 P4): a policy card, government or
civic that exists for one test only, added to research_model's registries
through `monkeypatch` (so teardown removes it) and validated by the real
effects interpreter on first use.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def grant_all(player):
    """Every tech and every civic known (#116 P2, P4). Appended in config
    order, after whatever the player already knows. No government is
    adopted: the engine default does that in the next economy phase."""
    from civulator.research_model import CIVIC_ORDER, TECH_ORDER

    player.techs.extend(t for t in TECH_ORDER if t not in player.techs)
    player.civics.extend(c for c in CIVIC_ORDER if c not in player.civics)
    return player


def grant(player, *techs):
    """Exactly these techs added (prerequisites NOT implied): for tests of
    one gate."""
    player.techs.extend(t for t in techs if t not in player.techs)
    return player


def grant_civic(player, *civics):
    """Exactly these civics added (prerequisites NOT implied): for tests of
    one gate (#116 P4)."""
    player.civics.extend(c for c in civics if c not in player.civics)
    return player


def synthetic_policy(monkeypatch, name, effects, type="economic", requires_civic=None,
                     obsolete_with=None):
    """A policy card for one test: a PolicySpec in research_model.POLICIES,
    unlocked by `requires_civic` (default: the first civic of the tree)."""
    from civulator import research_model

    spec = research_model.PolicySpec(
        name=name, type=type,
        requires_civic=requires_civic or research_model.CIVIC_ORDER[0],
        obsolete_with=obsolete_with, effects=tuple(effects))
    monkeypatch.setitem(research_model.POLICIES, name, spec)
    return spec


def synthetic_government(monkeypatch, name, slots, effects=(), tier=0, requires_civic=None):
    """A government for one test: `slots` (slot type -> number) as its
    `policy_slots` effect, then `effects`, unlocked by `requires_civic`
    (default: the first civic of the tree)."""
    from civulator import research_model

    spec = research_model.GovernmentSpec(
        name=name, requires_civic=requires_civic or research_model.CIVIC_ORDER[0], tier=tier,
        effects=({"kind": "policy_slots", **slots}, *effects))
    monkeypatch.setitem(research_model.GOVERNMENTS, name, spec)
    return spec


def synthetic_civic(monkeypatch, name, effects, cost=10):
    """A civic for one test, with no prerequisite and these effects (it is
    not part of any test's tree walk: grant it with `grant_civic`)."""
    from civulator import research_model

    spec = research_model.NodeSpec(name=name, cost=cost, era=research_model.ERAS[0],
                                   requires=(), effects=tuple(effects))
    monkeypatch.setitem(research_model.CIVICS, name, spec)
    monkeypatch.setitem(research_model.CIVIC_INDEX, name, len(research_model.CIVIC_INDEX))
    return spec


def stand(env, unit_type, player_index, coordinates):
    """A real unit of `unit_type` standing on the board for player
    `player_index` (#116 P3): built through the engine's one factory
    (`_create_unit`), so the class, slot and subclass are the real ones, and
    registered in its player's list and on its tile like a produced unit."""
    from civulator.game.city import _create_unit

    unit = _create_unit(unit_type, env.players[player_index], coordinates)
    env.players[player_index].units.append(unit)
    env.add_unit_to_tile(unit, coordinates)
    return unit
