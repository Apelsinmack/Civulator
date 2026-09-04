"""The flat action encoding shared by every loop that steps the game.

A network emits two flat indices — a slot-aware selection and a move target
— which `GameEnvironment.step` cannot consume directly: it wants
`[array([row, col, slot]), array([row, col])]`. Translating between the two
is three lines, which is exactly why it was written out three times (the
trainer, the evaluation harness, the viewer) and a fourth time, WRONGLY, in
four pre-0.6 scripts.

Those scripts tested end-of-turn with `action[0] == n * m`, the sentinel
from before units had stacking slots. After slots the real index is
`n * m * NUM_UNIT_SLOTS`, so `n * m` became a legal *selection*: an ordinary
unit selection was read as "end turn", the true end-turn index decoded to an
off-map row, and a bare `except Exception: pass` swallowed the result. The
scripts did not crash — they spun to their step cap and scored every game a
draw, which reads like a modelling result rather than a decoding bug
(issue #53; they now live in `archive/scripts_pre_0.6/`).

One definition, so a change to the action space can only be made in one
place (issue #54).
"""

import numpy as np

from ..game.unit import NUM_UNIT_SLOTS


def end_turn_index(n, m):
    """The single action index meaning "end my turn".

    It sits one past the last (tile, slot) pair, so every index below it is
    a real selection. `adjust_mask_for_end_turn` appends the matching
    always-valid entry to the selection mask.
    """
    return n * m * NUM_UNIT_SLOTS


def decode_action(selected_pos, move_pos, n, m):
    """Flat (selection, move) indices -> the `action_matrix` `env.step` takes.

    Args:
        selected_pos: `tile_index * NUM_UNIT_SLOTS + slot`.
        move_pos: `row * m + col` of the order's target tile.
        n, m: map rows and columns.

    Returns:
        `[np.array([row, col, slot]), np.array([row, col])]`, or **None**
        when `selected_pos` is `end_turn_index(n, m)` — callers must handle
        that case by ending the turn rather than stepping the env.
    """
    if selected_pos == end_turn_index(n, m):
        return None
    tile_idx = selected_pos // NUM_UNIT_SLOTS
    slot = selected_pos % NUM_UNIT_SLOTS
    return [
        np.array([tile_idx // m, tile_idx % m, slot]),
        np.array([move_pos // m, move_pos % m]),
    ]
