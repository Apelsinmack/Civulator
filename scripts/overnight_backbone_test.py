"""Overnight training: separate backbone + resume shared backbone.

Runs two training sessions sequentially:
1. Train FullyConvSeparateNetwork from scratch (500 episodes)
2. Resume FullyConvNetwork (shared backbone) from latest checkpoint for 500 more episodes

Saves weights for tournament comparison tomorrow:
- weights/separate_backbone/agent_{i}.pth  (500 eps from scratch)
- weights/shared_backbone_1000/agent_{i}.pth  (500+500 eps continued)
- The original shared backbone 500-ep weights are already in weights/

Usage:
    python scripts/overnight_backbone_test.py
"""

import os
import re
import sys
import time
import random

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.game import GameEnvironment
from civulator.agents import DQNAgent, BuildAgent, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents


N, M = 4, 8
NUM_PLAYERS = 2
NUM_EPISODES = 500
MAX_TURNS = 200
ENCODER = "enhanced"
D = EnhancedStateEncoder().get_depth(NUM_PLAYERS)


def set_seeds(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def train_separate_backbone():
    """Phase 1: Train separate backbone from scratch."""
    print("=" * 60)
    print("PHASE 1: Training FullyConvSeparateNetwork (500 episodes)")
    print("=" * 60)

    set_seeds(42)

    env = GameEnvironment(N, M, NUM_PLAYERS)
    env.max_turns = MAX_TURNS

    memories = [ReplayMemory(10000) for _ in range(NUM_PLAYERS)]
    agents = [
        DQNAgent(N, M, D, memories[i], learning_rate=0.001,
                 fully_conv=True, separate_backbone=True, encoder=ENCODER)
        for i in range(NUM_PLAYERS)
    ]
    build_agents = [
        BuildAgent(N, M, D, learning_rate=0.001)
        for _ in range(NUM_PLAYERS)
    ]

    params = sum(p.numel() for p in agents[0].network.parameters())
    print(f"Network: FullyConvSeparateNetwork ({params:,} params)")
    print(f"Device: {agents[0].device}")
    print()

    start = time.time()
    win_counts, _ = train_agents(
        env, agents, num_episodes=NUM_EPISODES, batch_size=32,
        debug=False, build_agents=build_agents, save_checkpoints=False,
    )
    elapsed = time.time() - start

    # Save final weights
    os.makedirs("weights/separate_backbone", exist_ok=True)
    for i, agent in enumerate(agents):
        torch.save(
            {"model_state_dict": agent.network.state_dict(),
             "optimizer_state_dict": agent.optimizer.state_dict()},
            f"weights/separate_backbone/agent_{i}.pth",
        )

    print(f"\nPhase 1 complete in {elapsed:.0f}s. Results: {win_counts}")
    print("Saved to weights/separate_backbone/")
    print()


def train_shared_backbone_continued():
    """Phase 2: Resume shared backbone training for 500 more episodes."""
    print("=" * 60)
    print("PHASE 2: Resuming FullyConvNetwork (shared) for 500 more episodes")
    print("=" * 60)

    set_seeds(123)  # Different seed for this phase

    env = GameEnvironment(N, M, NUM_PLAYERS)
    env.max_turns = MAX_TURNS

    memories = [ReplayMemory(10000) for _ in range(NUM_PLAYERS)]
    agents = [
        DQNAgent(N, M, D, memories[i], learning_rate=0.001, fully_conv=True, encoder=ENCODER)
        for i in range(NUM_PLAYERS)
    ]
    build_agents = [
        BuildAgent(N, M, D, learning_rate=0.001)
        for _ in range(NUM_PLAYERS)
    ]

    # Find latest checkpoint from previous training
    weight_files = os.listdir("weights") if os.path.exists("weights") else []
    episodes = []
    for f in weight_files:
        match = re.match(r"agent_0_episode_(\d+)\.pth", f)
        if match:
            episodes.append(int(match.group(1)))

    if not episodes:
        print("ERROR: No shared backbone checkpoints found in weights/")
        print("Cannot resume. Skipping phase 2.")
        return

    latest = max(episodes)
    print(f"Loading checkpoints from episode {latest}")

    for i, agent in enumerate(agents):
        path = f"weights/agent_{i}_episode_{latest}.pth"
        checkpoint = torch.load(path, map_location=agent.device)
        agent.network.load_state_dict(checkpoint["model_state_dict"])
        agent.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        print(f"  Loaded agent {i} from {path}")

    params = sum(p.numel() for p in agents[0].network.parameters())
    print(f"Network: FullyConvNetwork shared ({params:,} params)")
    print(f"Resuming from episode {latest}, training {NUM_EPISODES} more")
    print()

    start = time.time()
    win_counts, _ = train_agents(
        env, agents, num_episodes=NUM_EPISODES, batch_size=32,
        debug=False, build_agents=build_agents, save_checkpoints=False,
    )
    elapsed = time.time() - start

    # Save final weights
    os.makedirs("weights/shared_backbone_1000", exist_ok=True)
    for i, agent in enumerate(agents):
        torch.save(
            {"model_state_dict": agent.network.state_dict(),
             "optimizer_state_dict": agent.optimizer.state_dict()},
            f"weights/shared_backbone_1000/agent_{i}.pth",
        )

    print(f"\nPhase 2 complete in {elapsed:.0f}s. Results: {win_counts}")
    print("Saved to weights/shared_backbone_1000/")
    print()


if __name__ == "__main__":
    total_start = time.time()

    train_separate_backbone()
    train_shared_backbone_continued()

    total = time.time() - total_start
    print("=" * 60)
    print(f"ALL DONE in {total/60:.1f} minutes")
    print()
    print("Tournament tomorrow between:")
    print("  1. Shared backbone (500 eps)  — weights/agent_*_episode_499.pth")
    print("  2. Shared backbone (1000 eps) — weights/shared_backbone_1000/agent_*.pth")
    print("  3. Separate backbone (500 eps) — weights/separate_backbone/agent_*.pth")
    print("=" * 60)
