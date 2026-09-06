"""Regression tests for issue #81: `torch.cuda.is_available()` alone can be
True while `torch.cuda.device_count()` is 0 (GPUs masked, e.g.
`CUDA_VISIBLE_DEVICES=""`), so device resolution must check both. Monkeypatch
both functions rather than the environment variable -- that's what the
production code actually calls, and it exercises the exact conjunction
`resolve_device()` is supposed to check without depending on this machine's
real GPU state.
"""

import torch

from civulator.torch_env import resolve_device
from civulator.agents import DQNAgent, BuildAgent, ReplayMemory, BasicStateEncoder

BASIC_SIZE = (8, 16)


def test_resolve_device_masked_gpu_falls_back_to_cpu(monkeypatch):
    """is_available() True but device_count() == 0 -- the masked-GPU bug
    (issue #81) -- must resolve to cpu, not cuda."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    assert resolve_device() == torch.device("cpu")


def test_resolve_device_real_gpu_resolves_to_cuda(monkeypatch):
    """Both truthy -- the honest "a GPU is really there" case -- resolves to
    cuda."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 1)
    assert resolve_device() == torch.device("cuda")


def test_resolve_device_no_cuda_resolves_to_cpu(monkeypatch):
    """is_available() False -- no cuda build/driver at all -- resolves to
    cpu regardless of device_count()."""
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.cuda, "device_count", lambda: 0)
    assert resolve_device() == torch.device("cpu")


def test_dqn_agent_respects_explicit_device():
    """An explicit device= argument must be honored verbatim -- no need for
    a real CUDA device to test this, cpu is exercised directly."""
    d = BasicStateEncoder().get_depth(2)
    agent = DQNAgent(*BASIC_SIZE, d, ReplayMemory(100), conv_channels=(4, 8),
                      encoder="basic", fully_conv=False, device=torch.device("cpu"))
    assert agent.device == torch.device("cpu")
    assert next(agent.network.parameters()).device.type == "cpu"


def test_build_agent_respects_explicit_device():
    agent = BuildAgent(*BASIC_SIZE, 25, device=torch.device("cpu"))
    assert agent.device == torch.device("cpu")
    assert next(agent.network.parameters()).device.type == "cpu"
