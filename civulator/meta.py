"""Artifact manifests — record which game version/config produced a saved file.

Every site that saves trained weights, scenarios, or stats should embed a manifest
via `build_manifest()` so results can later be traced back to the code and config
that produced them (GitHub issue #28).

Not part of `civulator/game/`, which must stay torch-free — this module may import
torch freely since it only deals with saving/loading artifacts, never simulation.
"""

import copy
import os
import subprocess
from datetime import datetime, timezone

import torch

from . import __version__
from .config import CFG


def _find_repo_root():
    """Walk up from this file looking for a .git directory."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        d = os.path.dirname(d)
    return os.path.dirname(os.path.abspath(__file__))


def _git_commit():
    """Return the short git commit hash, or 'unknown' on any failure."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_find_repo_root(),
            stderr=subprocess.DEVNULL,
        )
        return out.decode().strip()
    except Exception:
        return "unknown"


def build_manifest():
    """Build a manifest recording the game version/config that produced an artifact.

    Returns:
        dict with keys: game_version, git_commit, config, date.
    """
    return {
        "game_version": __version__,
        "git_commit": _git_commit(),
        "config": copy.deepcopy(CFG),
        "date": datetime.now(timezone.utc).isoformat(),
    }


def save_weights(state_dict, path):
    """Save a state_dict (or checkpoint payload dict) with an embedded manifest.

    `state_dict` may be a plain torch state_dict, or a larger payload dict such as
    {"model_state_dict": ..., "optimizer_state_dict": ...} — whatever a call site
    used to pass straight to torch.save. It is wrapped as-is under "state_dict".
    """
    torch.save({"state_dict": state_dict, "manifest": build_manifest()}, path)


def load_weights(path, map_location=None):
    """Load a weights file saved by `save_weights`, tolerating legacy bare files.

    Returns:
        (state_dict, manifest_or_None): manifest is None for files saved before
        artifact manifests existed (plain state_dict / checkpoint dict, no wrapper).
    """
    obj = torch.load(path, map_location=map_location, weights_only=True)
    if isinstance(obj, dict) and "state_dict" in obj:
        return obj["state_dict"], obj.get("manifest")
    return obj, None
