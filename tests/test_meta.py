"""Tests for issue #28: saved artifacts must carry an embedded manifest recording
which game version/config produced them.
"""

import torch

import civulator
from civulator.config import CFG
from civulator.meta import build_manifest, load_weights, save_weights


def test_manifest_has_all_keys_and_matches_current_state():
    # The shape gained `git_dirty` in issue #75: a commit hash alone does not
    # identify the code that produced an artifact, because a run can be
    # launched from a working tree with uncommitted edits (2026-09-04 — a
    # 13-hour run trained under combat constants that were in no commit).
    # Loaders only ever read `game_version`, so an added key is backward
    # compatible; this pin exists to make schema changes deliberate.
    assert set(build_manifest().keys()) == {
        "game_version", "git_commit", "git_dirty", "config", "date",
    }
    manifest = build_manifest()
    assert manifest["game_version"] == civulator.__version__
    assert manifest["config"] == CFG


def test_save_and_load_weights_round_trip(tmp_path):
    state_dict = {"w": torch.zeros(2)}
    path = tmp_path / "weights.pth"

    save_weights(state_dict, str(path))
    loaded_state_dict, manifest = load_weights(str(path))

    assert torch.equal(loaded_state_dict["w"], state_dict["w"])
    assert manifest is not None
    assert manifest["game_version"] == civulator.__version__


def test_load_weights_tolerates_legacy_bare_state_dict(tmp_path):
    state_dict = {"w": torch.ones(2)}
    path = tmp_path / "legacy_weights.pth"

    torch.save(state_dict, str(path))
    loaded_state_dict, manifest = load_weights(str(path))

    assert torch.equal(loaded_state_dict["w"], state_dict["w"])
    assert manifest is None
