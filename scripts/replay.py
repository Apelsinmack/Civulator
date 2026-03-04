"""Watch trained agents play a game with ASCII visualization."""

import os
import re
import sys
import argparse
import random

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from civulator.game import GameEnvironment
from civulator.agents import DQNAgent
from civulator.agents.replay_memory import ReplayMemory
from civulator.utils.ascii_display import display_map


def find_latest_checkpoint():
    """Find the latest checkpoint episode number."""
    if not os.path.exists("weights"):
        return None
    weight_files = os.listdir("weights")
    episodes = []
    for f in weight_files:
        match = re.match(r"agent_0_episode_(\d+)\.pth", f)
        if match:
            episodes.append(int(match.group(1)))
    return max(episodes) if episodes else None


def load_agents(n, m, d, num_players, episode):
    """Load trained agents from checkpoints."""
    memories = [ReplayMemory(100) for _ in range(num_players)]
    agents = [DQNAgent(n, m, d, memories[i], learning_rate=0.001) for i in range(num_players)]

    for i, agent in enumerate(agents):
        path = f"weights/agent_{i}_episode_{episode}.pth"
        checkpoint = torch.load(path, weights_only=True)
        agent.network.load_state_dict(checkpoint["model_state_dict"])
        agent.network.eval()
        print(f"Loaded agent {i} from episode {episode}")

    return agents


def play_game(env, agents, epsilon=0.05, pause=True):
    """Play a single game with ASCII display."""
    env.reset()
    display_map(env, debug=True)

    done = False
    step = 0
    last_turn = 0
    next_state = agents[env.current_player.player_index].build_state_tensor(env)

    while not done and step < 2000:
        step += 1
        current_agent = agents[env.current_player.player_index]
        state = next_state
        action = current_agent.select_action(state, epsilon=epsilon)

        action_matrix = [
            np.array([action[0] // env.m, action[0] % env.m]),
            np.array([action[1] // env.m, action[1] % env.m]),
        ]

        if action[0] == env.n * env.m:
            env.current_player.end_turn()
            env.next_turn()
            done = env.done
        else:
            try:
                _, reward, done = env.step(action_matrix)
            except Exception:
                pass

        next_state = agents[env.current_player.player_index].build_state_tensor(env)

        if env.turn_counter != last_turn:
            display_map(env, debug=True)
            last_turn = env.turn_counter
            if pause:
                input("  [Press Enter for next turn]")

    display_map(env, debug=True)

    alive = [p for p in env.players if not p.is_dead]
    if len(alive) == 1:
        print(f"\nGame over! Winner: {alive[0].name} after {env.turn_counter} turns")
    else:
        scores = [(len(p.cities) * 10 + len(p.units), p.name) for p in env.players if not p.is_dead]
        scores.sort(reverse=True)
        print(f"\nGame ended at turn {env.turn_counter} (limit). Scores: {scores}")


def main():
    parser = argparse.ArgumentParser(description="Watch trained agents play")
    parser.add_argument("--episode", type=int, help="Checkpoint episode to load (default: latest)")
    parser.add_argument("--epsilon", type=float, default=0.05, help="Exploration rate (default: 0.05)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for map generation")
    parser.add_argument("--no-pause", action="store_true", help="Don't pause between turns")
    args = parser.parse_args()

    episode = args.episode or find_latest_checkpoint()
    if episode is None:
        print("No checkpoints found in weights/")
        return

    if args.seed is not None:
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)

    n, m = 4, 8
    num_players = 2
    d = 2 * num_players + 1

    agents = load_agents(n, m, d, num_players, episode)
    env = GameEnvironment(n, m, num_players)
    env.max_turns = 250

    play_game(env, agents, epsilon=args.epsilon, pause=not args.no_pause)


if __name__ == "__main__":
    main()
