"""3-way tournament: shared-500 vs shared-1000 vs separate-500.

Loads pre-trained weights and plays round-robin matches.

Usage:
    python scripts/tournament_backbone.py
"""

import os
import sys
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
from civulator.agents import DQNAgent, EnhancedStateEncoder
from civulator.agents.networks import FullyConvNetwork, FullyConvSeparateNetwork
from civulator.agents.replay_memory import ReplayMemory

N, M = 4, 8
NUM_PLAYERS = 2
D = EnhancedStateEncoder().get_depth(NUM_PLAYERS)
GAMES_PER_SIDE = 50  # 50 as P1 + 50 as P2 = 100 games per matchup


MODELS = {
    "Shared-500": {
        "path": "weights/agent_{i}_episode_499.pth",
        "network_cls": FullyConvNetwork,
        "fully_conv": True,
        "separate_backbone": False,
    },
    "Shared-1000": {
        "path": "weights/shared_backbone_1000/agent_{i}.pth",
        "network_cls": FullyConvNetwork,
        "fully_conv": True,
        "separate_backbone": False,
    },
    "Separate-500": {
        "path": "weights/separate_backbone/agent_{i}.pth",
        "network_cls": FullyConvSeparateNetwork,
        "fully_conv": True,
        "separate_backbone": True,
    },
}


def load_agent(model_cfg, agent_idx):
    path = model_cfg["path"].format(i=agent_idx)
    memory = ReplayMemory(100)
    agent = DQNAgent(
        N, M, D, memory, encoder="enhanced",
        fully_conv=model_cfg["fully_conv"],
        separate_backbone=model_cfg.get("separate_backbone", False),
    )
    checkpoint = torch.load(path, map_location=agent.device, weights_only=False)
    agent.network.load_state_dict(checkpoint["model_state_dict"])
    agent.network.eval()
    return agent


def play_match(agent_a, agent_b, num_games=50, epsilon=0.05):
    a_wins, b_wins, draws = 0, 0, 0

    for game in range(num_games):
        random.seed(game * 1000 + 7)
        np.random.seed(game * 1000 + 7)
        torch.manual_seed(game * 1000 + 7)

        env = GameEnvironment(N, M, NUM_PLAYERS)
        env.max_turns = 200
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
    print("=" * 60)
    print("3-WAY BACKBONE TOURNAMENT")
    print(f"  {GAMES_PER_SIDE * 2} games per matchup ({GAMES_PER_SIDE} as each side)")
    print("=" * 60)
    print()

    model_names = list(MODELS.keys())
    results = {name: {"wins": 0, "losses": 0, "draws": 0} for name in model_names}
    matchup_results = []

    for i, name_a in enumerate(model_names):
        for j, name_b in enumerate(model_names):
            if i >= j:
                continue

            print(f"{name_a} vs {name_b}...", end=" ", flush=True)

            agent_a = load_agent(MODELS[name_a], 0)
            agent_b = load_agent(MODELS[name_b], 0)

            # Each side plays as P1 and P2
            a_wins_1, b_wins_1, draws_1 = play_match(agent_a, agent_b, GAMES_PER_SIDE)
            b_wins_2, a_wins_2, draws_2 = play_match(agent_b, agent_a, GAMES_PER_SIDE)

            total_a = a_wins_1 + a_wins_2
            total_b = b_wins_1 + b_wins_2
            total_draws = draws_1 + draws_2

            results[name_a]["wins"] += total_a
            results[name_a]["losses"] += total_b
            results[name_a]["draws"] += total_draws
            results[name_b]["wins"] += total_b
            results[name_b]["losses"] += total_a
            results[name_b]["draws"] += total_draws

            matchup_results.append((name_a, name_b, total_a, total_b, total_draws))
            print(f"{name_a} {total_a}-{total_b} {name_b} ({total_draws} draws)")

    # Print standings
    print(f"\n{'=' * 60}")
    print("FINAL STANDINGS")
    print(f"{'=' * 60}")
    print(f"{'Model':16s} {'Wins':>6s} {'Losses':>8s} {'Draws':>7s} {'Win%':>6s}")
    print("-" * 46)

    standings = sorted(results.items(), key=lambda x: x[1]["wins"], reverse=True)
    for name, r in standings:
        total = r["wins"] + r["losses"] + r["draws"]
        win_pct = r["wins"] / total * 100 if total > 0 else 0
        print(f"{name:16s} {r['wins']:6d} {r['losses']:8d} {r['draws']:7d} {win_pct:5.1f}%")

    print(f"\nMatchup details:")
    for name_a, name_b, a_w, b_w, dr in matchup_results:
        print(f"  {name_a:16s} {a_w:3d} - {b_w:3d} {name_b:16s} ({dr} draws)")

    # Save plot
    os.makedirs("stats", exist_ok=True)
    timestamp = int(time.time())

    names = [s[0] for s in standings]
    wins = [s[1]["wins"] for s in standings]
    losses = [s[1]["losses"] for s in standings]
    draws_list = [s[1]["draws"] for s in standings]

    fig, ax = plt.subplots(figsize=(10, 6))
    x = range(len(names))
    width = 0.25
    ax.bar([i - width for i in x], wins, width, label="Wins", color="green")
    ax.bar(list(x), losses, width, label="Losses", color="red")
    ax.bar([i + width for i in x], draws_list, width, label="Draws", color="gray")
    ax.set_xticks(list(x))
    ax.set_xticklabels(names)
    ax.set_ylabel("Games")
    ax.set_title("Backbone Tournament: Shared vs Separate (v0.4.0 FullyConv)")
    ax.legend()
    plt.savefig(f"stats/backbone_tournament_{timestamp}.png")
    plt.close()
    print(f"\nPlot saved to stats/backbone_tournament_{timestamp}.png")


if __name__ == "__main__":
    main()
