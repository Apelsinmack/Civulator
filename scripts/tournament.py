"""Train multiple model sizes and run a round-robin tournament.

Usage:
    python scripts/tournament.py --episodes 500
    python scripts/tournament.py --play-only  # skip training, just tournament
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
from civulator.meta import save_weights, load_weights


# Model configurations: name -> (conv_channels, fc_hidden)
MODEL_CONFIGS = {
    "Small":  ((16, 32),   None),
    "Medium": ((32, 64),   128),
    "Large":  ((64, 128),  256),
    "XL":     ((128, 256), 512),
}

N, M = 4, 8
NUM_PLAYERS = 2
D = 2 * NUM_PLAYERS + 1


def set_seeds(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)


def train_model(model_name, conv_channels, fc_hidden, num_episodes, batch_size=32):
    """Train a model and save its final weights."""
    print(f"\n{'='*60}")
    print(f"Training {model_name} model ({conv_channels}, fc_hidden={fc_hidden})")
    print(f"{'='*60}")

    set_seeds(42)

    env = GameEnvironment(N, M, NUM_PLAYERS)
    env.max_turns = 250

    memories = [ReplayMemory(10000) for _ in range(NUM_PLAYERS)]
    agents = [
        DQNAgent(N, M, D, memories[i], learning_rate=0.001,
                 conv_channels=conv_channels, fc_hidden=fc_hidden)
        for i in range(NUM_PLAYERS)
    ]

    total_params = sum(p.numel() for p in agents[0].network.parameters())
    print(f"Parameters: {total_params:,}")

    t0 = time.perf_counter()
    win_counts, win_history = train_agents(
        env, agents, num_episodes=num_episodes, batch_size=batch_size, debug=False,
        save_checkpoints=False
    )
    elapsed = time.perf_counter() - t0
    print(f"\nTraining complete in {elapsed:.0f}s ({elapsed/num_episodes:.2f}s/ep)")
    print(f"Win counts: P1={win_counts[0]}, P2={win_counts[1]}")

    # Save final weights
    os.makedirs("weights/tournament", exist_ok=True)
    for i in range(NUM_PLAYERS):
        path = f"weights/tournament/{model_name}_agent_{i}.pth"
        save_weights({
            "model_state_dict": agents[i].network.state_dict(),
            "optimizer_state_dict": agents[i].optimizer.state_dict(),
            "config": {"conv_channels": conv_channels, "fc_hidden": fc_hidden},
        }, path)

    return win_counts, win_history


def load_agent(model_name, agent_idx):
    """Load a trained agent from tournament weights."""
    path = f"weights/tournament/{model_name}_agent_{agent_idx}.pth"
    checkpoint, _manifest = load_weights(path)
    cfg = checkpoint["config"]

    memory = ReplayMemory(100)
    agent = DQNAgent(N, M, D, memory, conv_channels=cfg["conv_channels"],
                     fc_hidden=cfg["fc_hidden"])
    agent.network.load_state_dict(checkpoint["model_state_dict"])
    agent.network.eval()
    return agent


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


def run_tournament(model_names):
    """Round-robin tournament between all trained models."""
    print(f"\n{'='*60}")
    print("ROUND-ROBIN TOURNAMENT")
    print(f"{'='*60}\n")

    results = {}
    for name in model_names:
        results[name] = {"wins": 0, "losses": 0, "draws": 0}

    for i, name_a in enumerate(model_names):
        for j, name_b in enumerate(model_names):
            if i >= j:
                continue

            print(f"{name_a} vs {name_b}...", end=" ", flush=True)

            # Each model plays as both P1 and P2
            agent_a = load_agent(name_a, 0)
            agent_b = load_agent(name_b, 0)

            # 50 games as P1, 50 as P2
            a_wins_1, b_wins_1, draws_1 = play_match(agent_a, agent_b, num_games=50)
            b_wins_2, a_wins_2, draws_2 = play_match(agent_b, agent_a, num_games=50)

            total_a = a_wins_1 + a_wins_2
            total_b = b_wins_1 + b_wins_2
            total_draws = draws_1 + draws_2

            results[name_a]["wins"] += total_a
            results[name_a]["losses"] += total_b
            results[name_a]["draws"] += total_draws
            results[name_b]["wins"] += total_b
            results[name_b]["losses"] += total_a
            results[name_b]["draws"] += total_draws

            print(f"{name_a} {total_a}-{total_b} {name_b} ({total_draws} draws)")

    # Print standings
    print(f"\n{'='*60}")
    print("FINAL STANDINGS")
    print(f"{'='*60}")
    print(f"{'Model':10s} {'Wins':>6s} {'Losses':>8s} {'Draws':>7s} {'Win%':>6s}")
    print("-" * 40)

    standings = sorted(results.items(), key=lambda x: x[1]["wins"], reverse=True)
    for name, r in standings:
        total = r["wins"] + r["losses"] + r["draws"]
        win_pct = r["wins"] / total * 100 if total > 0 else 0
        print(f"{name:10s} {r['wins']:6d} {r['losses']:8d} {r['draws']:7d} {win_pct:5.1f}%")

    # Save results
    os.makedirs("stats", exist_ok=True)
    timestamp = int(time.time())

    # Bar chart
    names = [s[0] for s in standings]
    wins = [s[1]["wins"] for s in standings]
    losses = [s[1]["losses"] for s in standings]

    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(names))
    ax.bar([i - 0.2 for i in x], wins, 0.4, label="Wins", color="green")
    ax.bar([i + 0.2 for i in x], losses, 0.4, label="Losses", color="red")
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("Games")
    ax.set_title("Tournament Results by Model Size")
    ax.legend()
    plt.savefig(f"stats/tournament_{timestamp}.png")
    plt.close()
    print(f"\nTournament plot saved to stats/tournament_{timestamp}.png")

    return results


def main():
    parser = argparse.ArgumentParser(description="Model size tournament")
    parser.add_argument("--episodes", type=int, default=500, help="Training episodes per model")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--play-only", action="store_true", help="Skip training, just run tournament")
    parser.add_argument("--models", nargs="+", default=list(MODEL_CONFIGS.keys()),
                        help="Which models to include")
    args = parser.parse_args()

    if not args.play_only:
        for name in args.models:
            conv_channels, fc_hidden = MODEL_CONFIGS[name]
            train_model(name, conv_channels, fc_hidden, args.episodes, args.batch_size)

    run_tournament(args.models)


if __name__ == "__main__":
    main()
