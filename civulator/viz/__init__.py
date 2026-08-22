"""Shared raylib visualization helpers for civulator's standalone GUI tools.

This package is viz-only: it may depend on pyray/numpy but must never be
imported by civulator.game or civulator.agents (the engine stays viz-free),
and must never import torch.
"""
