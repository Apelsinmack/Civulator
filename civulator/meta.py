"""Artifact manifests — record which game version/config produced a saved file.

Every site that saves trained weights, scenarios, or stats should embed a manifest
via `build_manifest()` so results can later be traced back to the code and config
that produced them (GitHub issue #28).

Not part of `civulator/game/`, which must stay torch-free — this module may import
torch freely since it only deals with saving/loading artifacts, never simulation.
"""

import copy
import logging
import os
import subprocess
from datetime import datetime, timezone

import torch

from . import __version__
from .config import CFG

logger = logging.getLogger(__name__)


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


def _git_dirty():
    """True when tracked files differ from HEAD, None when git can't be read.

    A commit hash alone does not identify the code that ran: a 13-hour
    training run can be launched from a working tree with uncommitted edits
    (this happened on 2026-09-04 — a run trained under combat constants that
    were never in any commit). The flag makes that visible in the artifact
    instead of leaving the manifest quietly wrong (issue #75).
    """
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=_find_repo_root(),
            stderr=subprocess.DEVNULL,
        )
        return bool(out.decode().strip())
    except Exception:
        return None


class VersionGateError(Exception):
    """Raised by `check_version` — and reused verbatim by anything that shares
    its refusal path (design doc §8, Systems (b) "Version gate" row: "the one
    gate... every scenario/recording loader calls it") — when an artifact
    cannot be trusted to rebuild identically under the current game version.
    `civulator.tools.recording.build_env_from_scenario` also raises this
    directly when a manifest passes the version check but still lacks the
    pinned mapgen params needed for an identical rebuild (design doc §8's
    central fix) — one exception type, one `override` escape hatch, no
    matter which of the two reasons triggered it.
    """


def _major_minor(version_string):
    """'0.6.1' -> '0.6' — the granularity `check_version` compares at (design
    doc §8: "The version check (major.minor) remains as a secondary guard
    for engine-logic drift").
    """
    parts = str(version_string).split(".")
    return ".".join(parts[:2])


def check_version(manifest, override=False):
    """The ONE version gate (design doc §8, D16, Systems (b)): refuse to
    trust `manifest` as version-compatible unless it carries a game_version
    matching the CURRENT major.minor. Every scenario/demo/future loader that
    cares about version compatibility calls this — do not hand-roll a second
    check (design doc: "used by recording.load_scenario ... and every future
    demo/scenario loader").

    Does NOT bump/read a different version than `build_manifest` already
    does (`civulator.__version__`) — P8 bumps that number; this gate just
    compares against whatever it currently is.

    Args:
        manifest: the artifact's embedded manifest dict (`build_manifest`'s
            shape), or None/missing entirely.
        override: bypass the refusal, logging a warning instead of raising.
            Never silent — the caller is explicitly choosing to accept a
            possibly-inconsistent load (design doc §8: "the same override").

    Raises:
        VersionGateError: if `manifest` is None, has no "game_version", or
            its major.minor differs from the current game_version's major.
            minor — unless `override` is True.
    """
    current = _major_minor(__version__)

    if not manifest or "game_version" not in manifest:
        message = (
            "artifact has no manifest (or no game_version in it) — cannot "
            f"verify it was produced by a compatible version (current "
            f"{__version__!r}); pass override=True to load it anyway"
        )
        if override:
            logger.warning("check_version override: %s", message)
            return
        raise VersionGateError(message)

    manifest_version = manifest["game_version"]
    manifest_major_minor = _major_minor(manifest_version)
    if manifest_major_minor != current:
        message = (
            f"artifact manifest game_version {manifest_version!r} (major.minor "
            f"{manifest_major_minor}) does not match the current game_version "
            f"{__version__!r} (major.minor {current}); pass override=True to "
            f"load it anyway"
        )
        if override:
            logger.warning("check_version override: %s", message)
            return
        raise VersionGateError(message)


def build_manifest(mapgen_params=None):
    """Build a manifest recording the game version/config that produced an artifact.

    Args:
        mapgen_params: optional — a world-bearing save site's own
            `Map.mapgen_params` (design doc §8, D16: "World identity =
            manifest-pinned params"), i.e. the generator's own echo of
            exactly what it used (seed/rows/cols/num_players/map_type/
            resolved knobs/starts params). Omitted (None, the default) for
            artifacts that carry no world of their own, e.g. trained
            weights — their manifest keeps exactly the pre-0.6 four-key
            shape (tests/test_meta.py pins this). When given, it is
            embedded under "mapgen_params" so `civulator.tools.recording.
            build_env_from_scenario` can rebuild the identical world
            without ever reading live config.toml.

    Returns:
        dict with keys: game_version, git_commit, config, date, and —
        only when `mapgen_params` is given — mapgen_params.
    """
    manifest = {
        "game_version": __version__,
        "git_commit": _git_commit(),
        "git_dirty": _git_dirty(),
        "config": copy.deepcopy(CFG),
        "date": datetime.now(timezone.utc).isoformat(),
    }
    if mapgen_params is not None:
        manifest["mapgen_params"] = mapgen_params
    return manifest


def save_weights(state_dict, path, manifest=None):
    """Save a state_dict (or checkpoint payload dict) with an embedded manifest.

    `state_dict` may be a plain torch state_dict, or a larger payload dict such as
    {"model_state_dict": ..., "optimizer_state_dict": ...} — whatever a call site
    used to pass straight to torch.save. It is wrapped as-is under "state_dict".

    `manifest`: pass one built at RUN START for anything long-running (issue
    #75). `build_manifest()` reads `git_commit` from the repo at the moment
    it is called, so a training run that saves 13 hours after it launched
    records whatever HEAD happens to be *then* — not the code that produced
    the weights. `game_version` and `config` are bound at import and so
    already describe launch time; the commit is the one field that drifts.
    Omitted (the default) keeps the original behaviour for short-lived save
    sites, which are the majority.
    """
    if manifest is None:
        manifest = build_manifest()
    torch.save({"state_dict": state_dict, "manifest": manifest}, path)


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
