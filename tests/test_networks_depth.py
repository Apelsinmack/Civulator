"""FullyConvNetwork arbitrary-depth generalization (issue #48 capacity ladder).

Three contracts:
1. The default (16, 32) build is byte-compatible with history — exact
   state_dict key set, and the real frozen-baseline checkpoint
   (weights/trained/duel_25ch_1000ep.pth) strict-loads into a fresh net.
2. Deeper stacks produce correct output shapes (spatial dims preserved by
   the wrap-padded backbone at any depth).
3. conv_channels_from_state_dict round-trips — the canonical way loaders
   (scripts/evaluate.py) recover a checkpoint's architecture.
"""

import os

import pytest
import torch

from civulator.agents.networks import (
    FullyConvNetwork,
    conv_channels_from_state_dict,
)
from civulator.game.unit import NUM_UNIT_SLOTS
from civulator.meta import load_weights

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_WEIGHTS = os.path.join(
    _PROJECT_ROOT, "weights", "trained", "duel_25ch_1000ep.pth"
)

HISTORICAL_KEYS = {
    "conv1.weight", "conv1.bias",
    "bn1.weight", "bn1.bias", "bn1.running_mean", "bn1.running_var",
    "bn1.num_batches_tracked",
    "conv2.weight", "conv2.bias",
    "bn2.weight", "bn2.bias", "bn2.running_mean", "bn2.running_var",
    "bn2.num_batches_tracked",
    "select_conv.weight", "select_conv.bias",
    "end_turn_q",
    "move_spread.weight", "move_spread.bias",
    "move_bn.weight", "move_bn.bias", "move_bn.running_mean",
    "move_bn.running_var", "move_bn.num_batches_tracked",
    "move_conv.weight", "move_conv.bias",
}


def test_default_depth_keeps_historical_state_dict_keys():
    net = FullyConvNetwork(25)
    assert set(net.state_dict().keys()) == HISTORICAL_KEYS


def test_frozen_baseline_checkpoint_strict_loads():
    payload, _ = load_weights(BASELINE_WEIGHTS, map_location="cpu")
    net = FullyConvNetwork(25)
    net.load_state_dict(payload["agents"][0]["model_state_dict"])  # strict


@pytest.mark.parametrize("channels", [(8,), (8, 8, 8), (16, 32, 32, 32)])
def test_deeper_stacks_preserve_output_shapes(channels):
    n, m, d, batch = 6, 10, 26, 2
    net = FullyConvNetwork(d, conv_channels=channels)
    state = torch.randn(batch, d, n, m)
    selected = torch.zeros(batch, 1)

    select_q, move_q = net(state, selected)
    assert select_q.shape == (batch, n * m * NUM_UNIT_SLOTS + 1)
    assert move_q.shape == (batch, n * m)


@pytest.mark.parametrize("channels", [(16, 32), (8, 8, 8), (32, 64, 64)])
def test_conv_channels_roundtrip_through_state_dict(channels):
    net = FullyConvNetwork(25, conv_channels=channels)
    assert conv_channels_from_state_dict(net.state_dict()) == channels


def test_empty_conv_channels_raises():
    with pytest.raises(ValueError, match="at least one layer"):
        FullyConvNetwork(25, conv_channels=())
