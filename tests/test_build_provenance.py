"""Tests for issue #47: civulator_core build provenance.

The C++ build stamps its own commit (+ dirty flag, build date) at CMake
configure time, exposed as `civulator_core.build_info()`. `civulator.game.map`
is the one site that loads the module and reads that info; `meta.build_manifest`
reads it back off that module's state (never a second `import civulator_core`).

Deliberately does NOT assert `build_info()["commit"] == HEAD` — that pin would
go stale on every commit that doesn't happen to trigger a pyd rebuild, which
is precisely the situation issue #47 accepts as normal (the import-site
warning in civulator/game/map.py is the detector for that gap, not a test).
"""

import pytest

import civulator.game.map as game_map
from civulator.meta import build_manifest


@pytest.mark.skipif(
    not (game_map.HAS_CPP_CORE and hasattr(game_map.civulator_core, "build_info")),
    reason="civulator_core not built, or built from a pre-#47 pyd without build_info()",
)
def test_build_info_has_sane_types():
    info = game_map.civulator_core.build_info()

    assert set(info.keys()) == {"commit", "dirty", "build_date"}
    assert isinstance(info["commit"], str) and info["commit"] != ""
    assert info["dirty"] is None or isinstance(info["dirty"], bool)
    assert isinstance(info["build_date"], str) and info["build_date"] != ""


def test_build_manifest_carries_civulator_core_commit():
    manifest = build_manifest()

    assert "civulator_core_commit" in manifest
    commit = manifest["civulator_core_commit"]
    # None is explicitly allowed: no C++ core present, or a pre-#47 pyd.
    assert commit is None or isinstance(commit, str)
    # Whatever build_manifest saw is exactly what the map.py import site
    # currently holds — same value, no second read site.
    assert commit == game_map.civulator_core_commit


class _FakeCoreWithBuildInfo:
    """Stand-in for a civulator_core module that HAS build_info() (issue #47
    shape), used to test the normal (non-tolerance) branch without touching
    the real extension module.
    """

    @staticmethod
    def build_info():
        return {"commit": "deadbeef" * 5, "dirty": False, "build_date": "2026-01-01T00:00:00Z"}


class _FakeCoreWithoutBuildInfo:
    """Stand-in for an old pyd predating #47 -- no build_info attribute at
    all. `_read_civulator_core_commit` must tolerate this (hasattr guard),
    never raise, and report None rather than guessing.
    """


def test_read_civulator_core_commit_absent_build_info_tolerated():
    # (c): the old-pyd / no-build_info path is exactly what production code
    # takes when civulator_core exists but predates issue #47 -- must not
    # raise, and must report None rather than fabricating a commit.
    assert game_map._read_civulator_core_commit(_FakeCoreWithoutBuildInfo()) is None


def test_read_civulator_core_commit_present_build_info_reads_through():
    commit = game_map._read_civulator_core_commit(_FakeCoreWithBuildInfo())
    assert commit == "deadbeef" * 5


def test_build_manifest_civulator_core_commit_none_when_cpp_core_absent(monkeypatch):
    # Simulates running with no C++ core at all (pure-Python fallback):
    # meta.build_manifest must still succeed and report None, never raise.
    monkeypatch.setattr(game_map, "civulator_core_commit", None)

    manifest = build_manifest()

    assert manifest["civulator_core_commit"] is None
