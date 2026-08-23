"""Tests for design doc §11 P7: the version gate (`meta.check_version`) and
manifest-pinned scenario rebuilds (design doc §8, D16, Systems (b) "Version
gate" row).

Covers:
  (a) the refusal matrix: missing manifest, version major.minor mismatch,
      and override=True bypassing both with a logged warning;
  (b) a manifest whose params are simply absent (the archived 005-009
      shape: a real, version-matching manifest that predates this key)
      hitting the SAME refusal path -- "One gate implementation";
  (c) the manifest-pinned rebuild itself surviving a live config.toml
      mapgen-knob mutation, with a control proving the knob is not inert;
  (d) paint -> save -> reload identity (world + entities) through the REAL
      painter save path;
  (e) painter numbering skipping archived indices.

See tests/test_recording.py for the day-to-day scenario-loading tests (the
fixture scenario, the synthetic combat scenarios) that also now exercise
the gate's default (non-override) manifest-pinned path.
"""

import os
import sys

import pytest

from civulator.config import CFG
from civulator.game.environment import GameEnvironment
from civulator.meta import VersionGateError, build_manifest, check_version
from civulator.tools.recording import build_env_from_scenario, load_scenario

SCENARIO_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenarios"
)
ARCHIVE_DIR = os.path.join(SCENARIO_DIR, "archive_v0.5")
SCRIPTS_DIR = os.path.join(os.path.dirname(SCENARIO_DIR), "scripts")


def _layers(tile):
    """A tile's whole terrain state (design doc §3) as a comparable tuple."""
    return (tile.base_terrain, tile.relief, tile.feature, tile.resource)


def _terrain_grid(env):
    return [[_layers(env.map.tiles[r, c]) for c in range(env.m)] for r in range(env.n)]


# --- (a) check_version refusal matrix ---------------------------------------


def test_check_version_refuses_a_missing_manifest():
    with pytest.raises(VersionGateError):
        check_version(None)


def test_check_version_refuses_a_manifest_with_no_game_version_key():
    with pytest.raises(VersionGateError):
        check_version({"config": {}})


def test_check_version_refuses_a_major_minor_mismatch():
    manifest = build_manifest()
    manifest["game_version"] = "9.9.0"
    with pytest.raises(VersionGateError):
        check_version(manifest)


def test_check_version_accepts_a_matching_manifest():
    check_version(build_manifest())  # must not raise


def test_check_version_override_bypasses_a_missing_manifest_with_a_warning(caplog):
    with caplog.at_level("WARNING"):
        check_version(None, override=True)  # must not raise
    assert "override" in caplog.text.lower()


def test_check_version_override_bypasses_a_mismatch_with_a_warning(caplog):
    manifest = build_manifest()
    manifest["game_version"] = "9.9.0"
    with caplog.at_level("WARNING"):
        check_version(manifest, override=True)  # must not raise
    assert "override" in caplog.text.lower()


# --- (b) present-but-unpinned manifest -> same refusal path -----------------


def test_manifest_without_pinned_params_is_refused_like_a_missing_one():
    """design doc §11 P7 deliverable 2: 'A scenario whose manifest lacks the
    params -> same refusal path (pre-0.6 files)' -- this is exactly the
    shape of archived scenarios 005-009: a real, version-matching manifest
    saved before `mapgen_params` existed at all.
    """
    manifest = build_manifest()  # current version, but no mapgen_params
    assert "mapgen_params" not in manifest
    scenario = {
        "seed": 1, "map_rows": 8, "map_cols": 8, "map_type": "basic",
        "units": [], "cities": [], "manifest": manifest,
    }

    with pytest.raises(VersionGateError):
        build_env_from_scenario(scenario)

    env = build_env_from_scenario(scenario, override=True)  # must not raise
    assert (env.n, env.m) == (8, 8)


def test_archived_pre_06_scenarios_are_refused_without_override_and_load_with_it():
    """The real archived files (design doc §11 P7 deliverable 4) exercise
    both refusal reasons: scenario_001.json has no manifest at all,
    scenario_005.json has a real 0.5.1 manifest that predates
    `mapgen_params`. Both must refuse by default and load under override.
    """
    for name in ("scenario_001.json", "scenario_005.json"):
        scenario = load_scenario(os.path.join(ARCHIVE_DIR, name))
        with pytest.raises(VersionGateError):
            build_env_from_scenario(scenario)
        env = build_env_from_scenario(scenario, override=True)
        assert env is not None
        assert env.current_player is env.players[0]


# --- (c) manifest-pinned rebuild closes the config-drift hole (design §8) --


def test_manifest_pinned_reload_survives_a_live_config_knob_mutation(monkeypatch):
    """design doc §8's central fix: 'a same-version mapgen-knob tune can no
    longer silently rewrite archived worlds.' Save a scenario, mutate a
    LIVE config.toml mapgen knob, reload -- the rebuilt world must be
    IDENTICAL to the world at save time. Control: the SAME knob mutation
    changes a freshly-generated (unpinned) world at the same seed/dims, so
    the identity above isn't just the knob being inert.
    """
    seed, rows, cols = 4242, 10, 10
    env = GameEnvironment(rows, cols, num_players=2, map_type="basic", seed=seed)
    original_terrain = _terrain_grid(env)

    scenario = {
        "seed": seed, "terrain_seeded": True, "map_rows": rows, "map_cols": cols,
        "map_type": "basic", "units": [], "cities": [],
        "manifest": build_manifest(mapgen_params=env.map.mapgen_params),
    }

    # Config drift between save and load: force every tile to Hills (still
    # workable/settleable everywhere, unlike all-Desert or all-Mountain,
    # which starve start placement of any fertile tile at all and raise
    # instead of just producing "a different" world) -- about as loud a
    # terrain-distribution change as one knob mutation can make while
    # staying a valid, generatable world.
    mutated_weights = {"Plains": 0.0, "Grassland": 0.0, "Desert": 0.0, "Tundra": 0.0,
                        "Hills": 1.0, "Woods": 0.0, "Mountain": 0.0}
    monkeypatch.setitem(CFG["map"], "terrain_weights", mutated_weights)

    reloaded = build_env_from_scenario(scenario)  # no override -- manifest-pinned
    assert _terrain_grid(reloaded) == original_terrain

    # Control: a brand-new world at the same seed/dims DOES read the
    # mutated live config.toml and DOES come out different.
    fresh = GameEnvironment(rows, cols, num_players=2, map_type="basic", seed=seed)
    assert _terrain_grid(fresh) != original_terrain


def test_manifest_pinned_reload_is_seed_reproducible_across_repeated_loads():
    """Sanity companion to the mutation test above: with NO config drift at
    all, reloading twice still gives the identical world (the pinned path
    doesn't introduce its own nondeterminism).
    """
    seed, rows, cols = 99, 12, 12
    env = GameEnvironment(rows, cols, num_players=2, map_type="basic", seed=seed)
    scenario = {
        "seed": seed, "terrain_seeded": True, "map_rows": rows, "map_cols": cols,
        "map_type": "basic", "units": [], "cities": [],
        "manifest": build_manifest(mapgen_params=env.map.mapgen_params),
    }
    first = build_env_from_scenario(scenario)
    second = build_env_from_scenario(scenario)
    assert _terrain_grid(first) == _terrain_grid(second) == _terrain_grid(env)


# --- (d) paint -> save -> reload identity E2E, through the REAL painter ----


def test_paint_save_reload_identity_e2e(tmp_path, monkeypatch):
    """design doc §10's E2E oracle + §11 P7 gate: 'paint -> save -> reload
    -> identical world + entities' through the ACTUAL `PainterState.save()`
    path (not a hand-built scenario dict) -- proving the painter's own
    manifest-pinned save/reload round-trip end to end.
    """
    sys.path.insert(0, SCRIPTS_DIR)
    painter = pytest.importorskip("scenario_painter")  # skipped if pyray is unavailable

    # Redirect the painter's save location so this test never touches the
    # real scenarios/ directory.
    scen_dir = tmp_path / "scenarios"
    scen_dir.mkdir()
    monkeypatch.setattr(painter, "SCENARIO_DIR", str(scen_dir))
    monkeypatch.setattr(painter, "ARCHIVE_DIR", str(scen_dir / "archive_v0.5"))

    state = painter.PainterState()
    state.add_unit(0, 0)
    state.team = 1
    state.add_unit(1, 1)
    state.add_city(2, 2)

    original_terrain = [
        [_layers(state.game_map.tiles[r, c]) for c in range(painter.MAP_COLS)]
        for r in range(painter.MAP_ROWS)
    ]
    original_units = [dict(u) for u in state.units]
    original_cities = [dict(c) for c in state.cities]

    state.save()

    saved_path = str(scen_dir / "scenario_001.json")
    assert os.path.isfile(saved_path)

    scenario = load_scenario(saved_path)
    assert "mapgen_params" in scenario["manifest"]

    env = build_env_from_scenario(scenario)  # no override -- must be pinned
    assert _terrain_grid(env) == original_terrain

    for entry in original_units:
        row, col = entry["row"], entry["col"]
        player = env.players[entry["team"] - 1]
        matches = [u for u in player.units if u.coordinates == (row, col)]
        assert matches, f"no team-{entry['team']} unit at {(row, col)}"
        unit = matches[0]
        assert unit.unit_type == entry["type"]
        assert unit.health == entry["hp"]
        assert unit.fortification == (1 if entry["fortified"] else 0)
    assert sum(len(p.units) for p in env.players) == len(original_units)

    for entry in original_cities:
        row, col = entry["row"], entry["col"]
        player = env.players[entry["team"] - 1]
        assert any(c.coordinates == (row, col) for c in player.cities)
    assert sum(len(p.cities) for p in env.players) == len(original_cities)


# --- (e) painter numbering skips archived indices ---------------------------


def test_painter_numbering_skips_archived_indices(tmp_path, monkeypatch):
    """design doc §11 P7 deliverable 4: 'save() scans BOTH scenarios/ and
    scenarios/archive_v0.5/ for the max index and continues above it (no
    collisions with archived names).'
    """
    sys.path.insert(0, SCRIPTS_DIR)
    painter = pytest.importorskip("scenario_painter")

    scen_dir = tmp_path / "scenarios"
    archive_dir = scen_dir / "archive_v0.5"
    scen_dir.mkdir()
    archive_dir.mkdir()
    (scen_dir / "scenario_001.json").write_text("{}")
    (scen_dir / "scenario_002.json").write_text("{}")
    for i in range(1, 10):  # the archived legacy batch, 001-009
        (archive_dir / f"scenario_{i:03d}.json").write_text("{}")

    # The pure numbering helper, directly.
    assert painter.next_scenario_index(str(scen_dir), str(archive_dir)) == 10

    # And through the real save() path.
    monkeypatch.setattr(painter, "SCENARIO_DIR", str(scen_dir))
    monkeypatch.setattr(painter, "ARCHIVE_DIR", str(archive_dir))
    state = painter.PainterState()
    state.add_unit(0, 0)
    state.save()
    assert (scen_dir / "scenario_010.json").is_file()


def test_painter_numbering_with_no_archive_directory_yet(tmp_path):
    """The archive directory not existing at all (a brand-new checkout
    before anyone has archived anything locally) must not error.
    """
    sys.path.insert(0, SCRIPTS_DIR)
    painter = pytest.importorskip("scenario_painter")

    scen_dir = tmp_path / "scenarios"
    scen_dir.mkdir()
    (scen_dir / "scenario_001.json").write_text("{}")

    assert painter.next_scenario_index(str(scen_dir), str(scen_dir / "archive_v0.5")) == 2
