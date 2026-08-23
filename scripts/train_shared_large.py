"""Train Large (32,64) network with shared weights. Standard preset (6
players by default, design doc D14/§6, §11 P5), 1000 episodes."""

import os
import sys
import random
import gc

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.config import CFG
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.agents import DQNAgent, BuildAgent, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents


def main(num_episodes=1000, max_turns=200, batch_size=32):
    random.seed(42)
    np.random.seed(42)
    torch.manual_seed(42)

    # Size preset (design doc D14/§6, §11 P5): one resolver shared with the
    # engine and every other run script, instead of this file's own
    # divergent rows/cols/num_players fallbacks.
    n, m, number_of_players = resolve_size_and_players()

    d = EnhancedStateEncoder().get_depth(number_of_players)
    env = GameEnvironment(n, m, number_of_players)
    env.max_turns = max_turns

    shared_memory = ReplayMemory(10000)
    shared_agent = DQNAgent(
        n, m, d, shared_memory,
        learning_rate=0.001,
        encoder="enhanced",
        fully_conv=True,
        conv_channels=(32, 64),  # Large
    )
    shared_agent.set_epsilon_schedule(1.0, 0.05, 8000)
    shared_agent.config_name = "Large-Shared"

    # Fresh random weights — no checkpoint to load for Large
    agents = [shared_agent] * number_of_players

    shared_build_agent = BuildAgent(n, m, d, learning_rate=0.001)
    build_agents = [shared_build_agent] * number_of_players

    print(f"\n=== Shared-Weight Training (Large) ===")
    print(f"  Model: Large (conv=(32,64), lr=0.001, eps=1.0->0.05/8000)")
    print(f"  Players: {number_of_players} (all sharing one network)")
    print(f"  Replay buffer: 1 x 10000 (shared)")
    print(f"  Episodes: {num_episodes}")
    print(f"  Map: {n}x{m}")
    print(f"  Starting from: random weights")
    print()

    train_agents(
        env, agents, num_episodes=num_episodes, batch_size=batch_size,
        debug=False, build_agents=build_agents,
    )

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
