"""Issue #127: build charges (Civ 6 Builder). A Worker starts with its type's
`build_charges` column plus the `build_charges_trained` effects in force when
it is made, gains the live `build_charges` effects for as long as they are in
force, spends one charge per build and is removed with none left.

The effect sources are stubbed where a test is about the Worker's arithmetic
(`civulator.game.unit.amount_sum`, the one call the Worker reads them
through); the configured cards and wonders are checked as properties over the
registry. No test names a configured policy or wonder or pins a charge count.
"""

import pytest

from civulator import district_model, effects, research_model, unit_model
from civulator.config import CFG
from civulator.effects import KIND_BUILD_CHARGES, KIND_BUILD_CHARGES_TRAINED, effects_of
from civulator.game import unit as unit_module
from civulator.game.unit import WorkerUnit
from civulator.unit_model import BUILD_CHARGES

from conftest import stand, synthetic_improvements
from test_worker_default import CENTRE, _table, new_turn, ring, scene


def stub_charges(monkeypatch, trained=0, live=0):
    """`amount_sum` as the Worker sees it: `trained` for the made-time kind,
    `live` for the live one. Returns the dict, so a test can change it."""
    amounts = {KIND_BUILD_CHARGES_TRAINED: trained, KIND_BUILD_CHARGES: live}
    monkeypatch.setattr(unit_module, "amount_sum", lambda player, kind: amounts[kind])
    return amounts


def build_until_gone(env, worker, tiles):
    """Have `worker` build on `tiles` one by one, as long as it exists; the
    number of builds it made."""
    built = 0
    for pos in tiles:
        if worker not in worker.player.units:
            break
        env.remove_unit_from_tile(worker, worker.coordinates)
        worker.coordinates = pos
        env.add_unit_to_tile(worker, pos)
        worker.reset_movement()
        built += bool(worker.build_improvement("Plot", env))
    return built


def test_a_worker_builds_its_charges_and_is_then_removed(monkeypatch):
    """With no effect in force a Worker makes exactly its type's
    `build_charges` builds; the last one removes it from its player and its
    tile. Breaks if a build spends no charge, or a spent Worker stays."""
    stub_charges(monkeypatch)
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        tiles = ring(env, CENTRE, 1)
        worker = stand(env, "Worker", 0, tiles[0])
        assert worker.charges_left() == BUILD_CHARGES["Worker"]
        assert build_until_gone(env, worker, tiles) == BUILD_CHARGES["Worker"]
        assert worker not in player.units
        assert all(worker not in env.map.get_tile(p).units for p in tiles)


def test_a_replacement_spends_a_charge_too(monkeypatch):
    """Replacing the improvement on a tile is a build like any other and
    spends one charge. Breaks if replacement is free."""
    stub_charges(monkeypatch)
    with synthetic_improvements({"Low": _table(food=1), "High": _table(food=2)}):
        env, player, city = scene()
        pos = ring(env, CENTRE, 1)[0]
        worker = stand(env, "Worker", 0, pos)
        start = worker.charges_left()
        assert worker.build_improvement("Low", env)
        worker.reset_movement()
        assert worker.build_improvement("High", env)
        assert env.map.get_tile(pos).improvements == ["High"]
        assert worker.charges_left() == start - 2


def test_trained_charges_are_fixed_when_the_worker_is_made(monkeypatch):
    """A `build_charges_trained` effect in force when a Worker is made adds to
    that Worker for good -- it keeps them when the effect leaves -- and a
    Worker made before the effect never gets them. Breaks if the made-time
    bonus is read live, or given to Workers that already existed."""
    amounts = stub_charges(monkeypatch)
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        tiles = ring(env, CENTRE, 1)
        before = stand(env, "Worker", 0, tiles[0])
        amounts[KIND_BUILD_CHARGES_TRAINED] = 2
        after = stand(env, "Worker", 0, tiles[1])
        amounts[KIND_BUILD_CHARGES_TRAINED] = 0
        assert after.charges_left() == before.charges_left() + 2


def test_live_charges_reach_every_worker_and_leave_with_their_source(monkeypatch):
    """A `build_charges` effect adds to every Worker of the player while it
    is in force, those made before it too; when it leaves, a Worker left
    with no charge is removed in its owner's economy phase. Breaks if the
    live bonus is fixed at making, or a Worker that can never build again
    lingers."""
    amounts = stub_charges(monkeypatch)
    with synthetic_improvements({"Plot": _table(food=1)}):
        env, player, city = scene()
        tiles = ring(env, CENTRE, 1)
        worker = stand(env, "Worker", 0, tiles[0])
        base = worker.charges_left()
        amounts[KIND_BUILD_CHARGES] = 1
        assert worker.charges_left() == base + 1
        assert build_until_gone(env, worker, tiles[:base]) == base
        assert worker in player.units and worker.charges_left() == 1
        amounts[KIND_BUILD_CHARGES] = 0
        new_turn(player)
        env.economy_phase(player)
        assert worker not in player.units


def test_the_configured_charge_effects_are_whole_positive_amounts():
    """Every configured `build_charges` / `build_charges_trained` entry
    parses to a positive amount on a player-scoped entry, and every unit
    with a `build_charges` column is one the engine builds improvements
    with. Breaks if a charge source is mistyped or given a city scope."""
    registries = (("policy", research_model.POLICIES), ("government", research_model.GOVERNMENTS),
                  ("civic", research_model.CIVICS), ("tech", research_model.TECHS),
                  ("building", unit_model.BUILDING_NAMES), ("district", district_model.DISTRICTS))
    entries = [e for source, names in registries for name in names
               for e in effects_of(source, name)
               if e.kind in (KIND_BUILD_CHARGES, KIND_BUILD_CHARGES_TRAINED)]
    for entry in entries:
        assert entry.scope == effects.SCOPE_PLAYER and entry["amount"] > 0
    from civulator.game.city import UNIT_CLASSES
    assert all(issubclass(UNIT_CLASSES[name], WorkerUnit) for name in BUILD_CHARGES)


def test_a_charge_effect_is_read_for_the_player_only():
    """A city-scoped charge effect raises at load: its consumer, the Worker,
    asks for its player only. Breaks if such an entry is accepted and then
    silently never read."""
    for kind in (KIND_BUILD_CHARGES, KIND_BUILD_CHARGES_TRAINED):
        with pytest.raises(ValueError):
            effects.parse_effect({"kind": kind, "amount": 1, "scope": "city"},
                                 "building", next(iter(CFG["buildings"])))
