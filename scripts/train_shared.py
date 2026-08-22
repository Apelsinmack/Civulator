"""Train with shared weights — one Large-Patient agent, all 8 players update it.

Usage:
    python scripts/train_shared.py --episodes 1000

Loads Large-Patient (agent_5) weights from episode 35 as starting point.
All 8 players share the same network and replay buffer.
Memory-safe: ~2.3 GB instead of ~18 GB.
"""

import os
import sys
import re
import random
import gc

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.config import CFG
from civulator.game import GameEnvironment
from civulator.agents import DQNAgent, BuildAgent, BasicStateEncoder, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents
from civulator.meta import load_weights

_tcfg = CFG.get("training", {})
_mcfg = CFG.get("map", {})
_gcfg = CFG.get("game", {})


def main(num_episodes=1000, max_turns=200, batch_size=32):
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)

    n = _mcfg.get("rows", 24)
    m = _mcfg.get("columns", 48)
    number_of_players = _gcfg.get("num_players", 8)

    d = EnhancedStateEncoder().get_depth(number_of_players)
    env = GameEnvironment(n, m, number_of_players)
    env.max_turns = max_turns

    # --- One shared agent: Large-Patient config ---
    shared_memory = ReplayMemory(10000)
    shared_agent = DQNAgent(
        n, m, d, shared_memory,
        learning_rate=0.001,
        encoder="enhanced",
        fully_conv=True,
        conv_channels=(16, 32),  # Medium (all saved weights are Medium)
    )
    shared_agent.set_epsilon_schedule(1.0, 0.05, 8000)  # Patient
    shared_agent.config_name = "Large-Patient-Shared"

    # Load weights from tournament's Large-Patient (agent_5, episode 35)
    weight_path = "weights/agent_5_episode_35.pth"
    if os.path.exists(weight_path):
        print(f"Loading weights from {weight_path}")
        checkpoint, _manifest = load_weights(weight_path)
        shared_agent.network.load_state_dict(checkpoint['model_state_dict'])
        shared_agent.target_network.load_state_dict(checkpoint['model_state_dict'])
        if 'optimizer_state_dict' in checkpoint:
            shared_agent.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        print("Weights loaded successfully")
    else:
        print(f"WARNING: {weight_path} not found, starting from scratch")

    # All players reference the same agent
    agents = [shared_agent] * number_of_players

    # Build agents — also shared
    shared_build_agent = BuildAgent(n, m, d, learning_rate=0.001)
    build_agents = [shared_build_agent] * number_of_players

    print(f"\n=== Shared-Weight Training ===")
    print(f"  Model: Large-Patient (conv=(32,64), lr=0.001, eps=1.0->0.05/8000)")
    print(f"  Players: {number_of_players} (all sharing one network)")
    print(f"  Replay buffer: 1 x 10000 (shared)")
    print(f"  Episodes: {num_episodes}")
    print(f"  Map: {n}x{m}")
    print()

    train_agents(
        env, agents, num_episodes=num_episodes, batch_size=batch_size,
        debug=False, build_agents=build_agents,
    )

    # Clean up
    gc.collect()
    torch.cuda.empty_cache()

    print("\nTraining complete!")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=1000)
    parser.add_argument("--max-turns", type=int, default=200)
    args = parser.parse_args()
    main(num_episodes=args.episodes, max_turns=args.max_turns)
