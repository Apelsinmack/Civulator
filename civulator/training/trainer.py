"""Training orchestration for multi-agent DQN training."""

import os
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend — no GUI window
import matplotlib.pyplot as plt
import torch

from ..agents.networks import get_valid_select_mask
from ..agents.build_agent import BUILD_OPTIONS
from ..game.city import City


def train_agents(env, agents, num_episodes=64, batch_size=32, debug=False,
                  save_checkpoints=True, build_agents=None):
    """Train multiple agents with proper state tracking and win counting.

    Args:
        env: The GameEnvironment
        agents: List of DQNAgent instances (one per player)
        num_episodes: Number of training episodes
        batch_size: Batch size for optimization
        debug: Whether to display debug information
        build_agents: Optional list of BuildAgent instances (one per player)

    Returns:
        tuple: (win_counts dict, win_history list)
    """
    win_counts = {i: 0 for i in range(len(agents))}
    win_history = []
    use_build = build_agents is not None

    # Build order tracking: per-player list of build sequences per episode
    # build_orders[player_idx] = list of lists, one per episode
    build_orders = {i: [] for i in range(len(agents))} if use_build else None

    for episode in range(num_episodes):
        print(f"Starting episode {episode}")
        env.reset()
        done = False

        # Track builds this episode
        if use_build:
            episode_builds = {i: [] for i in range(len(agents))}

        current_player_index = env.current_player.player_index
        current_agent = agents[current_player_index]
        next_state = current_agent.build_state_tensor(env)

        last_state_by_agent = {i: next_state for i in range(len(agents))}
        last_action_by_agent = {i: None for i in range(len(agents))}

        # Track turn boundaries and per-turn rewards for build agent
        last_player_index = -1
        turn_reward_accum = {i: 0.0 for i in range(len(agents))}

        step_counter = 0

        while not done:
            step_counter += 1
            if step_counter > 10000:
                print("WARNING: Step limit exceeded, breaking loop")
                break

            current_player_index = env.current_player.player_index
            current_agent = agents[current_player_index]

            # --- Build decisions at turn boundary ---
            if use_build and current_player_index != last_player_index:
                build_agent = build_agents[current_player_index]
                combat_state = current_agent.build_state_tensor(env)

                # Complete pending build transitions from last turn
                if build_agent.pending:
                    cities = env.current_player.cities
                    first_city = cities[0] if cities else None
                    build_agent.complete_pending(
                        turn_reward_accum[current_player_index],
                        combat_state, first_city, env, done
                    )
                    turn_reward_accum[current_player_index] = 0.0

                # Make new build decisions for cities needing orders
                for city in env.current_player.cities:
                    if city.current_production is None:
                        action_idx = build_agent.select_build(
                            combat_state, city, env, epsilon=0.3
                        )
                        option = BUILD_OPTIONS[action_idx]
                        episode_builds[current_player_index].append(option)
                        if option in City.BUILDING_COSTS:
                            city.produce_building(option)
                        else:
                            city.produce_unit(option)

                # Optimize build agent
                build_agent.optimize(batch_size)

                last_player_index = current_player_index

            state = next_state
            last_state_by_agent[current_player_index] = state

            action = current_agent.select_action(state, epsilon=0.3)
            last_action_by_agent[current_player_index] = action

            # Convert action indices to coordinates
            action_matrix = [
                np.array([action[0] // env.m, action[0] % env.m]),
                np.array([action[1] // env.m, action[1] % env.m]),
            ]

            # Execute action
            if action[0] == env.n * env.m:
                # End turn
                env.current_player.end_turn()
                env.next_turn()
                reward = 0
                done = env.done
            else:
                try:
                    _, reward, done = env.step(action_matrix)
                except AttributeError as e:
                    print(f"AttributeError during step: {e}")
                    reward = 0
                    done = env.done

            # Accumulate reward for build agent
            if use_build:
                turn_reward_accum[current_player_index] += reward

            # Get next state
            next_state = current_agent.build_state_tensor(env)

            # Store transition
            if env.current_player.player_index == current_player_index:
                current_agent.store_transition(state, action, reward, next_state, done)
            else:
                current_agent.store_pending_transition(state, action, reward)

            # Complete pending transitions for the next player
            if env.current_player.player_index != current_player_index:
                next_player_index = env.current_player.player_index
                next_player_agent = agents[next_player_index]
                next_state = next_player_agent.build_state_tensor(env)

                if next_player_agent.pending_transitions:
                    next_player_agent.complete_pending_transition(next_state, done)

            # Optimize
            if len(current_agent.memory) > batch_size:
                current_agent.optimize(batch_size)

        # Resolve remaining pending transitions
        for agent in agents:
            while agent.pending_transitions:
                agent.complete_pending_transition(agent.pending_transitions[0][0], True)

        # Resolve remaining build transitions
        if use_build:
            for i, build_agent in enumerate(build_agents):
                if build_agent.pending:
                    dummy_state = agents[i].build_state_tensor(env)
                    cities = env.players[i].cities
                    first_city = cities[0] if cities else None
                    build_agent.complete_pending(
                        turn_reward_accum[i], dummy_state, first_city, env, True
                    )

        # Determine winner
        winner = determine_winner(env)
        if winner is not None:
            win_counts[winner] += 1
            win_history.append(winner)
        else:
            win_history.append(-1)

        print(
            f"Episode {episode} completed. "
            f"Winner: {'None' if winner is None else f'Player {winner+1}'}"
        )
        print(
            f"Win counts: "
            + ", ".join(f"Player {i+1}: {c}" for i, c in win_counts.items())
        )

        # Record build orders for this episode
        if use_build:
            for i in range(len(agents)):
                build_orders[i].append(episode_builds[i])

        # Save checkpoints
        if save_checkpoints:
            _save_checkpoints(agents, episode)

    save_win_history(win_history, num_episodes)
    if use_build:
        save_build_stats(build_orders, num_episodes)
    return win_counts, win_history


def determine_winner(env):
    """Determine the winner based on the environment state.

    Returns:
        int: Index of winning player, or None
    """
    alive_players = [i for i, p in enumerate(env.players) if not p.is_dead]

    if len(alive_players) == 1:
        return alive_players[0]

    if env.done and env.turn_counter >= env.max_turns:
        scores = []
        for player in env.players:
            if player.is_dead:
                scores.append(-1)
            else:
                scores.append(len(player.cities) * 10 + len(player.units))

        max_score = max(scores)
        if scores.count(max_score) == 1:
            return scores.index(max_score)

    return None


def _save_checkpoints(agents, episode):
    """Save model weights for all agents."""
    os.makedirs("weights", exist_ok=True)
    for i, agent in enumerate(agents):
        save_path = f"weights/agent_{i}_episode_{episode}.pth"
        torch.save(
            {
                "model_state_dict": agent.network.state_dict(),
                "optimizer_state_dict": agent.optimizer.state_dict(),
            },
            save_path,
        )


def save_win_history(win_history, num_episodes):
    """Save win history data and generate rolling win rate plot."""
    os.makedirs("stats", exist_ok=True)
    timestamp = int(time.time())

    np.save(f"stats/win_history_{timestamp}.npy", np.array(win_history))

    if len(win_history) >= 10:
        plt.figure(figsize=(10, 6))

        players = sorted(set(w for w in win_history if w >= 0))

        for player in players:
            window_size = 10
            rolling_wins = []
            for i in range(len(win_history) - window_size + 1):
                window = win_history[i : i + window_size]
                win_rate = window.count(player) / window_size
                rolling_wins.append(win_rate)

            plt.plot(
                range(window_size - 1, len(win_history)),
                rolling_wins,
                label=f"Player {player + 1}",
            )

        plt.title("Rolling Win Rate (Window: 10 Episodes)")
        plt.xlabel("Episode")
        plt.ylabel("Win Rate")
        plt.legend()
        plt.grid(True)
        plt.savefig(f"stats/win_rate_plot_{timestamp}.png")
        plt.close()

    print("Win history and analytics saved to stats/ directory")


def save_build_stats(build_orders, num_episodes):
    """Save build order statistics and generate summary plots.

    Args:
        build_orders: {player_idx: list of lists}, each inner list is
                      the sequence of build choices for one episode.
        num_episodes: Total number of episodes.
    """
    os.makedirs("stats", exist_ok=True)
    timestamp = int(time.time())

    num_players = len(build_orders)

    # Aggregate: count how often each option appears as 1st, 2nd, 3rd build
    max_slot = 5  # Track first 5 build slots
    # slot_counts[slot][option] = count across all players and episodes
    slot_counts = [{opt: 0 for opt in BUILD_OPTIONS} for _ in range(max_slot)]
    # Total builds per option (all slots combined)
    total_counts = {opt: 0 for opt in BUILD_OPTIONS}

    for player_idx in range(num_players):
        for ep_builds in build_orders[player_idx]:
            for slot, option in enumerate(ep_builds):
                total_counts[option] = total_counts.get(option, 0) + 1
                if slot < max_slot:
                    slot_counts[slot][option] += 1

    total_decisions = sum(total_counts.values())

    # Print summary
    print("\n--- Build Order Summary ---")
    print(f"Total build decisions: {total_decisions}")
    print(f"\nOverall build frequency:")
    for opt in BUILD_OPTIONS:
        count = total_counts[opt]
        pct = count / total_decisions * 100 if total_decisions > 0 else 0
        print(f"  {opt:12s}: {count:5d} ({pct:5.1f}%)")

    for slot in range(min(max_slot, 3)):
        slot_total = sum(slot_counts[slot].values())
        if slot_total == 0:
            continue
        print(f"\nBuild #{slot+1} popularity:")
        sorted_opts = sorted(slot_counts[slot].items(), key=lambda x: x[1], reverse=True)
        for opt, count in sorted_opts:
            pct = count / slot_total * 100 if slot_total > 0 else 0
            if count > 0:
                print(f"  {opt:12s}: {count:5d} ({pct:5.1f}%)")

    # Save raw data
    np.save(f"stats/build_orders_{timestamp}.npy", build_orders, allow_pickle=True)

    # Plot: overall build frequency
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Left: overall frequency bar chart
    options = list(BUILD_OPTIONS)
    counts = [total_counts[opt] for opt in options]
    colors = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#F44336', '#795548', '#607D8B']
    axes[0].bar(range(len(options)), counts, color=colors[:len(options)])
    axes[0].set_xticks(range(len(options)))
    axes[0].set_xticklabels(options, rotation=45, ha='right')
    axes[0].set_ylabel("Times Built")
    axes[0].set_title("Overall Build Frequency")

    # Right: first 3 build slots stacked
    slot_data = {}
    for opt in options:
        slot_data[opt] = [slot_counts[s][opt] for s in range(min(max_slot, 3))]

    x = np.arange(min(max_slot, 3))
    width = 0.12
    for idx, opt in enumerate(options):
        axes[1].bar(x + idx * width, slot_data[opt], width, label=opt,
                    color=colors[idx % len(colors)])
    axes[1].set_xticks(x + width * len(options) / 2)
    axes[1].set_xticklabels([f"Build #{s+1}" for s in range(min(max_slot, 3))])
    axes[1].set_ylabel("Count")
    axes[1].set_title("Build Order by Slot")
    axes[1].legend(fontsize=7, loc='upper right')

    plt.tight_layout()
    plt.savefig(f"stats/build_orders_{timestamp}.png")
    plt.close()

    print(f"Build order stats saved to stats/build_orders_{timestamp}.{{npy,png}}")
