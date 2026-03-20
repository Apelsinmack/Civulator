"""Entry point for training Civulator agents.

Training parameters default to config.toml values, overridden by CLI args.
"""

import os
import re
import sys
import argparse
import random

import numpy as np
import torch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.config import CFG
from civulator.game import GameEnvironment
from civulator.agents import DQNAgent, BuildAgent, BasicStateEncoder, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents

# Defaults from config.toml
_tcfg = CFG.get("training", {})
_mcfg = CFG.get("map", {})
_gcfg = CFG.get("game", {})


def set_random_seeds(seed=42):
    """Set random seeds for reproducibility."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)


def main(resume_training=False, checkpoint_episode=None, num_episodes=64,
         batch_size=32, max_turns=250, debug=True, encoder="basic",
         fully_conv=False):
    """Main training function.

    Args:
        resume_training: Whether to resume from a checkpoint
        checkpoint_episode: Specific episode to resume from (None = latest)
        num_episodes: Number of training episodes
        batch_size: Batch size for optimization
        max_turns: Maximum turns per game before forced end
        debug: Enable debug output (ASCII map display)
        encoder: State encoder type ("basic" or "enhanced")
    """
    set_random_seeds()

    # Environment setup — from config.toml
    n = _mcfg.get("rows", 4)
    m = _mcfg.get("columns", 8)
    number_of_players = _gcfg.get("num_players", 2)

    # Get depth from encoder
    if encoder == "enhanced":
        d = EnhancedStateEncoder().get_depth(number_of_players)
    else:
        d = BasicStateEncoder().get_depth(number_of_players)

    env = GameEnvironment(n, m, number_of_players)
    env.max_turns = max_turns

    # Create agents
    memories = [ReplayMemory(10000) for _ in range(number_of_players)]
    agents = [
        DQNAgent(n, m, d, memories[i], learning_rate=0.001, encoder=encoder,
                 fully_conv=fully_conv)
        for i in range(number_of_players)
    ]

    # Create build agents
    build_agents = [
        BuildAgent(n, m, d, learning_rate=0.001)
        for _ in range(number_of_players)
    ]

    # Load checkpoints if resuming
    if resume_training:
        if checkpoint_episode is not None:
            checkpoint_paths = [
                f"weights/agent_{i}_episode_{checkpoint_episode}.pth"
                for i in range(number_of_players)
            ]
        else:
            weight_files = os.listdir("weights") if os.path.exists("weights") else []
            episodes = []
            for file in weight_files:
                match = re.match(r"agent_0_episode_(\d+)\.pth", file)
                if match:
                    episodes.append(int(match.group(1)))

            if episodes:
                latest_episode = max(episodes)
                print(f"Found latest checkpoint at episode {latest_episode}")
                checkpoint_paths = [
                    f"weights/agent_{i}_episode_{latest_episode}.pth"
                    for i in range(number_of_players)
                ]
            else:
                print("No checkpoints found. Starting fresh.")
                resume_training = False

        if resume_training:
            for i, agent in enumerate(agents):
                try:
                    checkpoint = torch.load(checkpoint_paths[i])
                    agent.network.load_state_dict(checkpoint["model_state_dict"])
                    agent.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
                    print(f"Loaded checkpoint for Agent {i}")
                except Exception as e:
                    print(f"Failed to load checkpoint for Agent {i}: {e}")

    # Train
    win_counts, win_history = train_agents(
        env, agents, num_episodes=num_episodes, batch_size=batch_size, debug=debug,
        build_agents=build_agents,
    )

    print("\nTraining complete!")
    print("Final win counts:")
    for i, count in win_counts.items():
        print(f"  Player {i+1}: {count} wins")

    return win_counts, win_history


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Civulator DQN agents")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--episode", type=int, help="Specific checkpoint episode to load")
    parser.add_argument("--episodes", type=int, default=_tcfg.get("episodes", 64),
                        help="Number of episodes")
    parser.add_argument("--batch-size", type=int, default=_tcfg.get("batch_size", 32),
                        help="Batch size")
    parser.add_argument("--max-turns", type=int, default=_tcfg.get("max_turns", 250),
                        help="Max turns per game")
    parser.add_argument("--debug", action="store_true", help="Enable debug output")
    parser.add_argument("--encoder", choices=["basic", "enhanced"],
                        default=_tcfg.get("encoder", "enhanced"),
                        help="State encoder type")
    parser.add_argument("--fully-conv", action="store_true",
                        help="Use fully convolutional network (map-size independent)")
    args = parser.parse_args()

    main(
        resume_training=args.resume,
        checkpoint_episode=args.episode,
        num_episodes=args.episodes,
        batch_size=args.batch_size,
        max_turns=args.max_turns,
        debug=args.debug,
        encoder=args.encoder,
        fully_conv=args.fully_conv,
    )
