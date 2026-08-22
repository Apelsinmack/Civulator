"""Tests for issue #28: saved artifacts must carry an embedded manifest recording
which game version/config produced them.
"""

import torch

import civulator
from civulator.config import CFG
from civulator.meta import build_manifest, load_weights, save_weights


def test_manifest_has_all_keys_and_matches_current_state():
    manifest = build_manifest()
    assert set(manifest.keys()) == {"game_version", "git_commit", "config", "date"}
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
