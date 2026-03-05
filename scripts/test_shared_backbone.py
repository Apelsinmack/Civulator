"""Compare shared backbone vs separate backbone architectures.

Trains both, then plays head-to-head matches.

Usage:
    python scripts/test_shared_backbone.py --episodes 500
"""

import os
import sys
import argparse
import random
import time

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MPLBACKEND"] = "Agg"

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from civulator.game import GameEnvironment
from civulator.agents import DQNAgent
from civulator.agents.replay_memory import ReplayMemory
from civulator.training import train_agents

N, M = 4, 8
NUM_PLAYERS = 2
D = 2 * NUM_PLAYERS + 1

# Use Small config (tournament showed size doesn't matter much yet)
CONV_CHANNELS = (16, 32)
FC_HIDDEN = None


def set_seeds(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)


def train_variant(name, shared_backbone, num_episodes, batch_size=32):
    """Train a model variant and return agents + results."""
    print(f"\n{'='*60}")
    print(f"Training: {name} (shared_backbone={shared_backbone})")
    print(f"{'='*60}")

    set_seeds(42)

    env = GameEnvironment(N, M, NUM_PLAYERS)
    env.max_turns = 250

    memories = [ReplayMemory(10000) for _ in range(NUM_PLAYERS)]
    agents = [
        DQNAgent(N, M, D, memories[i], learning_rate=0.001,
                 conv_channels=CONV_CHANNELS, fc_hidden=FC_HIDDEN,
                 shared_backbone=shared_backbone)
        for i in range(NUM_PLAYERS)
    ]

    total_params = sum(p.numel() for p in agents[0].network.parameters())
    print(f"Parameters: {total_params:,}")
    print(f"Network type: {type(agents[0].network).__name__}")

    t0 = time.perf_counter()
    win_counts, win_history = train_agents(
        env, agents, num_episodes=num_episodes, batch_size=batch_size,
        debug=False, save_checkpoints=False
    )
    elapsed = time.perf_counter() - t0
    print(f"\nTraining complete in {elapsed:.0f}s ({elapsed/num_episodes:.2f}s/ep)")
    print(f"Win counts: P1={win_counts[0]}, P2={win_counts[1]}")

    # Save weights
    os.makedirs("weights/backbone_test", exist_ok=True)
    for i in range(NUM_PLAYERS):
        path = f"weights/backbone_test/{name}_agent_{i}.pth"
        torch.save({
            "model_state_dict": agents[i].network.state_dict(),
            "optimizer_state_dict": agents[i].optimizer.state_dict(),
            "config": {
                "conv_channels": CONV_CHANNELS,
                "fc_hidden": FC_HIDDEN,
                "shared_backbone": shared_backbone,
            },
        }, path)

    return agents, win_counts, win_history, elapsed


def play_match(agent_a, agent_b, num_games=100, epsilon=0.05):
    """Play num_games between two agents. Returns (a_wins, b_wins, draws)."""
    a_wins, b_wins, draws = 0, 0, 0

    for game in range(num_games):
        random.seed(game * 1000)
        np.random.seed(game * 1000)
        torch.manual_seed(game * 1000)

        env = GameEnvironment(N, M, NUM_PLAYERS)
        env.max_turns = 250
        env.reset()

        agents_in_game = [agent_a, agent_b]
        done = False
        state = agents_in_game[env.current_player.player_index].build_state_tensor(env)
        step = 0

        while not done and step < 5000:
            step += 1
            pi = env.current_player.player_index
            action = agents_in_game[pi].select_action(state, epsilon=epsilon)

            if action[0] == env.n * env.m:
                env.current_player.end_turn()
                env.next_turn()
                done = env.done
            else:
                try:
                    _, _, done = env.step([
                        np.array([action[0] // env.m, action[0] % env.m]),
                        np.array([action[1] // env.m, action[1] % env.m]),
                    ])
                except Exception:
                    pass

            state = agents_in_game[env.current_player.player_index].build_state_tensor(env)

        alive = [i for i, p in enumerate(env.players) if not p.is_dead]
        if len(alive) == 1:
            if alive[0] == 0:
                a_wins += 1
            else:
                b_wins += 1
        else:
            draws += 1

    return a_wins, b_wins, draws


def main():
    parser = argparse.ArgumentParser(description="Shared vs Separate backbone test")
    parser.add_argument("--episodes", type=int, default=500, help="Training episodes")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    args = parser.parse_args()

    # Train both variants
    separate_agents, sep_wins, sep_history, sep_time = train_variant(
        "Separate", shared_backbone=False, num_episodes=args.episodes,
        batch_size=args.batch_size
    )
    shared_agents, shr_wins, shr_history, shr_time = train_variant(
        "Shared", shared_backbone=True, num_episodes=args.episodes,
        batch_size=args.batch_size
    )

    # Head-to-head: 100 games (50 as each side)
    print(f"\n{'='*60}")
    print("HEAD-TO-HEAD: Separate vs Shared")
    print(f"{'='*60}")

    sep_agent = separate_agents[0]
    shr_agent = shared_agents[0]

    print("50 games: Separate as P1...", end=" ", flush=True)
    s1_w, h1_w, d1 = play_match(sep_agent, shr_agent, num_games=50)
    print(f"Separate {s1_w}-{h1_w} Shared ({d1} draws)")

    print("50 games: Shared as P1...", end=" ", flush=True)
    h2_w, s2_w, d2 = play_match(shr_agent, sep_agent, num_games=50)
    print(f"Shared {h2_w}-{s2_w} Separate ({d2} draws)")

    total_sep = s1_w + s2_w
    total_shr = h1_w + h2_w
    total_draws = d1 + d2

    print(f"\nFINAL: Separate {total_sep} - {total_shr} Shared ({total_draws} draws)")

    # Summary
    sep_params = sum(p.numel() for p in separate_agents[0].network.parameters())
    shr_params = sum(p.numel() for p in shared_agents[0].network.parameters())

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"{'':15s} {'Separate':>10s} {'Shared':>10s}")
    print("-" * 37)
    print(f"{'Parameters':15s} {sep_params:>10,} {shr_params:>10,}")
    print(f"{'Training time':15s} {sep_time:>9.0f}s {shr_time:>9.0f}s")
    print(f"{'s/episode':15s} {sep_time/args.episodes:>9.2f}s {shr_time/args.episodes:>9.2f}s")
    print(f"{'H2H wins':15s} {total_sep:>10d} {total_shr:>10d}")
    print(f"{'H2H draws':15s} {'':>10s} {total_draws:>10d}")

    # Save win rate comparison plot
    os.makedirs("stats", exist_ok=True)
    timestamp = int(time.time())

    fig, ax = plt.subplots(figsize=(10, 6))
    window = 20
    for history, label in [(sep_history, "Separate"), (shr_history, "Shared")]:
        if len(history) >= window:
            # Win rate for P1 (both agents play as P1 in self-play)
            rolling = []
            for i in range(len(history) - window + 1):
                w = history[i:i + window]
                rolling.append(sum(1 for x in w if x == 0) / window)
            ax.plot(range(window - 1, len(history)), rolling, label=f"{label} P1 win rate")

    ax.set_title("Training Win Rate: Shared vs Separate Backbone")
    ax.set_xlabel("Episode")
    ax.set_ylabel("P1 Win Rate (rolling 20)")
    ax.legend()
    ax.grid(True)
    plt.savefig(f"stats/backbone_comparison_{timestamp}.png")
    plt.close()
    print(f"\nPlot saved to stats/backbone_comparison_{timestamp}.png")


if __name__ == "__main__":
    main()
