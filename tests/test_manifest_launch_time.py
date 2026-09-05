"""The manifest must describe the code that PRODUCED an artifact (issue #75).

`build_manifest()` reads `git_commit` from the repo at the moment it is
called, so a training run that saves thirteen hours after it launched
records whatever HEAD happens to be then. `game_version` and `config` are
bound at import and therefore already describe launch time; the commit is
the field that drifts, which is why `save_weights` now accepts a manifest
built at launch.
"""

import torch

from civulator import meta


def test_save_weights_uses_a_supplied_manifest_verbatim(tmp_path):
    """A manifest pinned at launch must survive to the artifact unchanged —
    otherwise the run records the repo's state at save time."""
    launch = meta.build_manifest()
    launch["git_commit"] = "launch0"

    path = tmp_path / "w.pth"
    meta.save_weights({"w": torch.zeros(1)}, str(path), manifest=launch)

    _, stored = meta.load_weights(str(path), map_location="cpu")
    assert stored["git_commit"] == "launch0"


def test_save_weights_without_a_manifest_still_builds_one(tmp_path):
    """Short-lived save sites keep the original behaviour."""
    path = tmp_path / "w.pth"
    meta.save_weights({"w": torch.zeros(1)}, str(path))

    _, stored = meta.load_weights(str(path), map_location="cpu")
    assert stored["game_version"] == meta.__version__
    assert "git_commit" in stored


def test_manifest_reports_whether_the_tree_was_dirty():
    """A commit hash alone does not identify the code that ran: a run can be
    launched from a tree with uncommitted edits, as happened 2026-09-04."""
    manifest = meta.build_manifest()
    assert "git_dirty" in manifest
    assert manifest["git_dirty"] in (True, False, None)


def test_a_later_commit_cannot_rewrite_a_pinned_manifest(tmp_path, monkeypatch):
    """The actual failure mode, simulated: the repo moves on mid-run, and the
    artifact must still name the commit it was launched from."""
    launch = meta.build_manifest()

    # The repo advances while training runs.
    monkeypatch.setattr(meta, "_git_commit", lambda: "deadbee")

    path = tmp_path / "w.pth"
    meta.save_weights({"w": torch.zeros(1)}, str(path), manifest=launch)
    _, stored = meta.load_weights(str(path), map_location="cpu")

    assert stored["git_commit"] == launch["git_commit"] != "deadbee"
