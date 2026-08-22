"""Train FullyConvSeparateNetwork (separate backbones) for comparison.

Trains 500 episodes with separate backbone fully conv network.
Saves weights to weights/separate_backbone/ for later tournament
against the shared backbone model.

Usage:
    python scripts/train_separate_backbone.py
"""

import os
import sys
import random

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.game import GameEnvironment
from civulator.agents import DQNAgent, BuildAgent
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents
from civulator.meta import save_weights


def set_seeds(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def main():
    set_seeds(42)

    N, M = 4, 8
    NUM_PLAYERS = 2
    NUM_EPISODES = 500
    MAX_TURNS = 200

    # Use basic encoder (same as overnight shared backbone run)
    from civulator.agents import BasicStateEncoder
    D = BasicStateEncoder().get_depth(NUM_PLAYERS)

    env = GameEnvironment(N, M, NUM_PLAYERS)
    env.max_turns = MAX_TURNS

    memories = [ReplayMemory(10000) for _ in range(NUM_PLAYERS)]
    agents = [
        DQNAgent(N, M, D, memories[i], learning_rate=0.001,
                 fully_conv=True, separate_backbone=True)
        for i in range(NUM_PLAYERS)
    ]

    build_agents = [
        BuildAgent(N, M, D, learning_rate=0.001)
        for _ in range(NUM_PLAYERS)
    ]

    print(f"Network: FullyConvSeparateNetwork")
    print(f"Parameters: {sum(p.numel() for p in agents[0].network.parameters()):,}")
    print(f"Episodes: {NUM_EPISODES}, Max turns: {MAX_TURNS}")
    print(f"Device: {agents[0].device}")
    print()

    # Save weights to separate directory
    os.makedirs("weights/separate_backbone", exist_ok=True)

    win_counts, win_history = train_agents(
        env, agents, num_episodes=NUM_EPISODES, batch_size=32,
        debug=False, build_agents=build_agents, save_checkpoints=False,
    )

    # Save final weights
    for i, agent in enumerate(agents):
        save_weights(
            {
                "model_state_dict": agent.network.state_dict(),
                "optimizer_state_dict": agent.optimizer.state_dict(),
            },
            f"weights/separate_backbone/agent_{i}.pth",
        )

    print("\nTraining complete!")
    print(f"Final: {win_counts}")
    print("Weights saved to weights/separate_backbone/")


if __name__ == "__main__":
    main()
