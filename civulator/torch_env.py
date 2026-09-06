"""Torch device resolution — the one place this repo decides cuda vs cpu.

Not part of the engine: `civulator/game/` must never import this module (or
torch at all — the engine is a pure simulation, see the project CLAUDE.md).
It exists for agents/scripts that construct torch tensors and modules.
"""

import torch


def resolve_device():
    """Return the torch device this process should use.

    `torch.cuda.is_available()` alone is not enough: it can be True while
    `torch.cuda.device_count()` is 0 (e.g. `CUDA_VISIBLE_DEVICES=""` masks
    every GPU), and then any `.to("cuda")` allocation fails. Only claim cuda
    when a device is actually enumerable; fall back to cpu otherwise (issue
    #81).
    """
    if torch.cuda.is_available() and torch.cuda.device_count() > 0:
        return torch.device("cuda")
    return torch.device("cpu")
