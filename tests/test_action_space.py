"""The shared flat action encoding (issue #54).

`end_turn_index` / `decode_action` replace three hand-written copies (the
trainer, the eval harness, the viewer) of the same three lines — and a
fourth, wrong copy in four pre-0.6 scripts that tested end-of-turn with
`n * m`, the sentinel from before units had stacking slots. These tests pin
the property that made that bug possible: the end-turn index must sit
strictly above every legal selection index.
"""

import numpy as np
import pytest

from civulator.agents.action_space import decode_action, end_turn_index
from civulator.game.unit import NUM_UNIT_SLOTS


@pytest.mark.parametrize("n,m", [(8, 16), (12, 24), (24, 48), (4, 8)])
def test_end_turn_index_is_above_every_selection(n, m):
    """The pre-0.6 bug in one assertion: `n * m` is a LEGAL selection index
    (tile n*m//SLOTS, slot n*m%SLOTS), so using it as the end-turn sentinel
    silently reinterprets an ordinary unit selection as 'end turn'."""
    end = end_turn_index(n, m)
    assert end == n * m * NUM_UNIT_SLOTS
    assert end > n * m, "n*m must not be the sentinel -- it is a real selection"
    # Every selection index is decodable to an on-map tile.
    for selected in (0, n * m, end - 1):
        matrix = decode_action(selected, 0, n, m)
        assert matrix is not None
        row, col, slot = matrix[0]
        assert 0 <= row < n and 0 <= col < m and 0 <= slot < NUM_UNIT_SLOTS


def test_end_turn_decodes_to_none():
    n, m = 12, 24
    assert decode_action(end_turn_index(n, m), 0, n, m) is None


@pytest.mark.parametrize("row,col,slot", [(0, 0, 0), (3, 7, 2), (11, 23, 3)])
def test_selection_round_trips(row, col, slot):
    n, m = 12, 24
    selected = (row * m + col) * NUM_UNIT_SLOTS + slot
    matrix = decode_action(selected, 5 * m + 9, n, m)
    assert list(matrix[0]) == [row, col, slot]
    assert list(matrix[1]) == [5, 9]
    assert all(isinstance(part, np.ndarray) for part in matrix)


def test_matches_the_hand_written_decode_it_replaced():
    """Byte-for-byte agreement with the expression the three loops used, so
    this extraction cannot have changed behaviour."""
    n, m = 12, 24
    for selected in range(0, n * m * NUM_UNIT_SLOTS, 37):
        for move_pos in (0, 100, n * m - 1):
            tile_idx = selected // NUM_UNIT_SLOTS
            expected = [
                np.array([tile_idx // m, tile_idx % m, selected % NUM_UNIT_SLOTS]),
                np.array([move_pos // m, move_pos % m]),
            ]
            got = decode_action(selected, move_pos, n, m)
            assert list(got[0]) == list(expected[0])
            assert list(got[1]) == list(expected[1])
