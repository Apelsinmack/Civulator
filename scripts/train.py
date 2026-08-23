"""Entry point for training Civulator agents.

Training parameters default to config.toml values, overridden by CLI args.
"""

import os
import re
import sys
import time
import argparse
import random

import numpy as np
import torch

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.config import CFG
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.agents import DQNAgent, BuildAgent, BasicStateEncoder, EnhancedStateEncoder
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents
from civulator.meta import load_weights

# Defaults from config.toml
_tcfg = CFG.get("training", {})


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
         fully_conv=False, seed_base=None):
    """Main training function.

    Args:
        resume_training: Whether to resume from a checkpoint
        checkpoint_episode: Specific episode to resume from (None = latest)
        num_episodes: Number of training episodes
        batch_size: Batch size for optimization
        max_turns: Maximum turns per game before forced end
        debug: Enable debug output (ASCII map display)
        encoder: State encoder type ("basic" or "enhanced")
        seed_base: Optional int — enables train_agents's episode-indexed
            seed schedule (issue #39). None (default, and config.toml's
            own default) reproduces the original unseeded behavior.
    """
    set_random_seeds()

    # Environment setup — size preset (design doc D14/§6, §11 P5): one
    # resolver shared with the engine and every other run script, instead
    # of this file's own divergent rows/cols/num_players fallbacks.
    n, m, number_of_players = resolve_size_and_players()

    # Get depth from encoder
    if encoder == "enhanced":
        d = EnhancedStateEncoder().get_depth(number_of_players)
    else:
        d = BasicStateEncoder().get_depth(number_of_players)

    env = GameEnvironment(n, m, number_of_players)
    env.max_turns = max_turns

    # --- Agent configurations (tournament mode for 8 players) ---
    # Each agent has: name, conv_channels, learning_rate, epsilon schedule
    AGENT_CONFIGS = [
        {"name": "Small-Aggr",   "conv": (8, 16),  "lr": 0.001, "eps_end": 0.01, "eps_decay": 2000},
        {"name": "Small-Patient","conv": (8, 16),  "lr": 0.001, "eps_end": 0.05, "eps_decay": 8000},
        {"name": "Med-Aggr",     "conv": (16, 32), "lr": 0.001, "eps_end": 0.01, "eps_decay": 2000},
        {"name": "Med-Patient",  "conv": (16, 32), "lr": 0.001, "eps_end": 0.05, "eps_decay": 8000},
        {"name": "Large-Aggr",   "conv": (32, 64), "lr": 0.001, "eps_end": 0.01, "eps_decay": 2000},
        {"name": "Large-Patient","conv": (32, 64), "lr": 0.001, "eps_end": 0.05, "eps_decay": 8000},
        {"name": "Med-FastLR",   "conv": (16, 32), "lr": 0.003, "eps_end": 0.01, "eps_decay": 2000},
        {"name": "Med-FastLR-P", "conv": (16, 32), "lr": 0.003, "eps_end": 0.05, "eps_decay": 8000},
    ]

    # Trim to actual number of players
    configs = AGENT_CONFIGS[:number_of_players]

    print("\n=== Tournament Configuration ===")
    for i, cfg in enumerate(configs):
        print(f"  P{i+1}: {cfg['name']} — conv={cfg['conv']}, lr={cfg['lr']}, "
              f"eps={cfg['eps_end']} over {cfg['eps_decay']} episodes")
    print()

    # Create agents with per-player configs
    agents = []
    for i, cfg in enumerate(configs):
        mem = ReplayMemory(10000)
        agent = DQNAgent(n, m, d, mem, learning_rate=cfg["lr"], encoder=encoder,
                         fully_conv=fully_conv, conv_channels=cfg["conv"])
        agent.set_epsilon_schedule(1.0, cfg["eps_end"], cfg["eps_decay"])
        agent.config_name = cfg["name"]  # Tag for reporting
        agents.append(agent)

    # Create build agents (same LR as combat agent)
    build_agents = [
        BuildAgent(n, m, d, learning_rate=configs[i]["lr"])
        for i in range(number_of_players)
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
                    checkpoint, _manifest = load_weights(checkpoint_paths[i])
                    agent.network.load_state_dict(checkpoint["model_state_dict"])
                    agent.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
                    print(f"Loaded checkpoint for Agent {i}")
                except Exception as e:
                    print(f"Failed to load checkpoint for Agent {i}: {e}")

    # Train
    win_counts, win_history = train_agents(
        env, agents, num_episodes=num_episodes, batch_size=batch_size, debug=debug,
        build_agents=build_agents, seed_base=seed_base,
    )

    print("\nTraining complete!")
    print("\n=== Tournament Results ===")
    print(f"{'Player':<8} {'Config':<16} {'Wins':>5} {'Win%':>7}")
    print("-" * 40)
    total_games = sum(win_counts.values())
    results = []
    for i in range(number_of_players):
        name = configs[i]["name"] if i < len(configs) else f"Agent {i}"
        wins = win_counts.get(i, 0)
        pct = 100 * wins / max(1, total_games)
        print(f"  P{i+1:<5} {name:<16} {wins:>5} {pct:>6.1f}%")
        results.append({"player": i+1, "config": name, "wins": wins, "pct": pct})

    # Save tournament report
    import json
    report = {
        "episodes": num_episodes,
        "map_size": f"{n}x{m}",
        "num_players": number_of_players,
        "max_turns": max_turns,
        "configs": configs,
        "results": results,
        "win_history": [int(w) for w in win_history],
    }
    report_path = os.path.join("stats", f"tournament_{int(time.time())}.json")
    os.makedirs("stats", exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nTournament report saved to {report_path}")

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
    parser.add_argument("--seed-base", type=int, default=_tcfg.get("seed_base"),
                        help="Enable the episode-indexed seed schedule (issue #39), "
                             "starting at this seed. Omit (config default: absent) "
                             "for the original unseeded behavior.")
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
        seed_base=args.seed_base,
    )
