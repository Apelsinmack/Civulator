"""Training orchestration for multi-agent DQN training."""

import logging
import os
import time

import numpy as np
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend — no GUI window
import matplotlib.pyplot as plt

from ..agents.networks import get_valid_select_mask
from ..agents.build_agent import BUILD_OPTIONS
from ..game.city import City
from ..game.environment import REWARDS
from ..game.unit import NUM_UNIT_SLOTS
from ..mapgen.starts import StartPlacementError
from ..meta import build_manifest, save_weights

logger = logging.getLogger(__name__)

# Infinite-loop guard for the episode-seed schedule below (issue #39): the
# documented start-placement failure rate is ~2% of seeds (design doc D26),
# so consuming this many CONSECUTIVE failures without a single success is
# not "unlucky", it's pathological (e.g. a corrupt seed_base range or a
# broken generator) — abort loudly instead of spinning forever.
_MAX_CONSECUTIVE_SEED_SKIPS = 1000


def _seeded_reset(env, seed_cursor, episode, seed_base, skip_log=None):
    """`env.reset(seed=seed_cursor)`, walking the cursor forward past any
    seeds `GameEnvironment.reset` rejects with `StartPlacementError` (the
    ~2% of seeds mapgen's start-placement ladder cannot place — `reset
    (seed=N)` raises on these BY DESIGN, on the first and only attempt,
    per that method's own docstring; it never silently resamples the way
    an unseeded reset does).

    Scheme — RUNNING SEED CURSOR, the simplest scheme that provably
    matches across runs (issue #39 experiment-design requirement: every
    follower experiment must train on literally the same sequence of
    worlds as the baseline): a single cursor starts at `seed_base` for
    episode 0. Each episode tries `env.reset(seed=cursor)`; on success
    the returned seed is consumed and the cursor left one past it for the
    NEXT episode. On `StartPlacementError` the failed seed is logged and
    the cursor advances by 1 and retries, as many times as needed, before
    the episode counts as started.

    Determinism argument: `reset(seed=N)` starts by calling
    `self.rng.seed(N)`, which fully re-seeds the engine RNG — so whether
    seed N places successfully is a pure function of N and the current
    code, never of prior episodes' history or which run is asking. Two
    runs with the same seed_base and the same code therefore walk the
    EXACT same cursor sequence and skip the EXACT same seeds: episode k
    always maps to the same world in every run. In the common case (no
    skips before episode k) that world's seed is `seed_base + k`; each
    earlier skip permanently shifts every later episode's seed up by
    one — this is why "episode k's seed" has no closed-form formula
    exposed outside this function, only the reproducibility property
    (same seed_base -> same episode->world sequence) is the public
    contract callers rely on.

    Returns:
        (episode_seed, next_cursor): the seed that actually produced this
        episode's world, and where the search for the NEXT episode should
        resume.

    skip_log: optional list; every skipped seed is appended to it, so the
        caller can PERSIST the full skip set into the run's stats/manifest.
        Console warnings proved insufficient as a record: the #39 baseline's
        manifest hand-transcribed only the last 3 of 19 skip warnings
        surviving in scrollback, which spawned issue #44's phantom
        cross-machine-divergence hunt (resolved 2026-09-02: all machines
        and commits agree seed-for-seed).
    """
    cursor = seed_cursor
    skips = 0
    while True:
        try:
            env.reset(seed=cursor)
            return cursor, cursor + 1
        except StartPlacementError as exc:
            if skip_log is not None:
                skip_log.append(cursor)
            logger.warning(
                "episode seed schedule (seed_base=%d): episode %d seed %d "
                "failed start placement, skipping to %d: %s",
                seed_base, episode, cursor, cursor + 1, exc,
            )
            cursor += 1
            skips += 1
            if skips > _MAX_CONSECUTIVE_SEED_SKIPS:
                raise RuntimeError(
                    f"episode seed schedule (seed_base={seed_base}): "
                    f"{_MAX_CONSECUTIVE_SEED_SKIPS} CONSECUTIVE seeds failed "
                    f"start placement (last tried {cursor - 1}) while looking "
                    f"for episode {episode}'s world — the documented failure "
                    f"rate is ~2% of seeds (design doc D26), so this run looks "
                    f"pathological rather than unlucky; aborting instead of "
                    f"looping forever"
                ) from exc


def train_agents(env, agents, num_episodes=64, batch_size=32, debug=False,
                  save_checkpoints=True, build_agents=None, seed_base=None,
                  episode_callback=None, skipped_seeds=None):
    """Train multiple agents with proper state tracking and win counting.

    Args:
        env: The GameEnvironment
        agents: List of DQNAgent instances (one per player)
        num_episodes: Number of training episodes
        batch_size: Batch size for optimization
        debug: Whether to display debug information
        build_agents: Optional list of BuildAgent instances (one per player)
        seed_base: Optional int. When given, episode k resets on a
            deterministic world drawn from the episode-seed schedule (see
            `_seeded_reset` above for the exact scheme and its
            determinism argument) instead of an unseeded resample —
            required whenever a follower experiment must train on
            literally the same sequence of worlds as this run (issue
            #39). Defaults to None: today's original, fully
            backward-compatible behavior — every episode calls
            `env.reset()` unseeded, and `GameEnvironment` resamples on
            its own bounded retry policy (`[map] max_world_retries`).
            There is no config.toml fallback read inside this function —
            like every other run parameter here (num_episodes,
            batch_size, ...), callers resolve their own value (CLI flag,
            `[training] seed_base`, or a literal) and pass it in.
        skipped_seeds: Optional list, filled in place with every schedule
            seed the seeded-reset walk skipped (see _seeded_reset's
            skip_log) — callers persist it into the run record.
        episode_callback: Optional callable `(episode, num_episodes,
            win_counts)`, invoked once at the end of each completed
            episode (after that episode's winner is recorded). Non-
            invasive opt-in loop seam for callers that want progress
            reporting (elapsed/ETA, periodic logging, ...) without
            train_agents itself taking on that responsibility — it does
            not compute or pass timing; the caller has its own clock.

    Returns:
        tuple: (win_counts dict, win_history list)
    """
    win_counts = {i: 0 for i in range(len(agents))}
    win_history = []
    use_build = build_agents is not None
    seed_cursor = seed_base  # None => unseeded (unchanged original behavior)

    # Build order tracking: per-player list of build sequences per episode
    # build_orders[player_idx] = list of lists, one per episode
    build_orders = {i: [] for i in range(len(agents))} if use_build else None

    for episode in range(num_episodes):
        if seed_cursor is None:
            print(f"Starting episode {episode}")
            env.reset()
        else:
            episode_seed, seed_cursor = _seeded_reset(
                env, seed_cursor, episode, seed_base, skip_log=skipped_seeds)
            print(f"Starting episode {episode} (seed={episode_seed})")
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

        # Terminal win/loss/draw rewards (issue #46): computed once when the
        # game ends; terminal_paid tracks which agents already received
        # theirs in-loop so the post-loop pending resolution never pays twice.
        terminal_by_agent = None
        terminal_paid = set()

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
                    build_agent.complete_pending(
                        turn_reward_accum[current_player_index],
                        combat_state, env, done
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

            # Lazy pending completion (issue #46): an agent's previous
            # transition is completed here, at its own next action, with the
            # state it actually acts from — not at player-switch time. This
            # keeps the agent's FINAL transition pending until episode end,
            # where it gets done=True plus its terminal reward (previously a
            # decisive game's loser never received a done=True transition
            # and bootstrapped past the game end).
            if current_agent.pending_transitions:
                current_agent.complete_pending_transition(state, False)

            epsilon = current_agent.get_epsilon()
            action = current_agent.select_action(state, epsilon=epsilon, game_env=env)
            last_action_by_agent[current_player_index] = action

            # Decode slot-aware action to coordinates
            end_turn_idx = env.n * env.m * NUM_UNIT_SLOTS
            selected_pos = action[0]
            move_pos = action[1]

            if selected_pos != end_turn_idx:
                tile_idx = selected_pos // NUM_UNIT_SLOTS
                slot = selected_pos % NUM_UNIT_SLOTS
                sel_row, sel_col = tile_idx // env.m, tile_idx % env.m
                action_matrix = [
                    np.array([sel_row, sel_col, slot]),
                    np.array([move_pos // env.m, move_pos % env.m]),
                ]
            else:
                action_matrix = None

            # Execute action
            if selected_pos == end_turn_idx:
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

            # Deliver the acting player's terminal reward (issue #46) so it
            # lands in the final transition stored below (and in the build
            # accumulator). The other agents' terminal rewards are delivered
            # post-loop through their still-pending final transitions.
            if done and terminal_by_agent is None:
                terminal_by_agent = _terminal_rewards(
                    determine_winner(env), len(agents)
                )
                reward += terminal_by_agent[current_player_index]
                terminal_paid.add(current_player_index)

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

            # On player switch, rebuild next_state from the incoming player's
            # perspective — it becomes their acting state next iteration.
            # (Their pending transition is NOT completed here anymore: lazy
            # completion above handles it at their next action, or the
            # post-loop resolution at episode end — issue #46.)
            if env.current_player.player_index != current_player_index:
                next_player_index = env.current_player.player_index
                next_player_agent = agents[next_player_index]
                next_state = next_player_agent.build_state_tensor(env)

            # Optimize
            if len(current_agent.memory) > batch_size:
                current_agent.optimize(batch_size)

        # Resolve remaining pending transitions with done=True and each
        # agent's terminal reward (issue #46). terminal_by_agent is None only
        # on the abnormal step-limit break — treat that as a draw-equivalent
        # terminal here. An agent that already got its terminal in-loop
        # (terminal_paid) is completed without extra reward.
        if terminal_by_agent is None:
            terminal_by_agent = _terminal_rewards(determine_winner(env), len(agents))
        # Agents paid in-loop got their terminal through the shared `reward`,
        # which also reached their build accumulator — snapshot before the
        # combat resolution below marks everyone as paid.
        build_terminal_paid = set(terminal_paid)
        for i, agent in enumerate(agents):
            extra = 0.0 if i in terminal_paid else terminal_by_agent[i]
            terminal_paid.add(i)
            while agent.pending_transitions:
                final_state = agent.build_state_tensor(env)
                agent.complete_pending_transition(final_state, True, extra_reward=extra)
                extra = 0.0

        # Resolve remaining build transitions (terminal rewards flow into the
        # build accumulators too; the in-loop actor's accumulator already
        # received its share through the shared `reward` accumulation).
        if use_build:
            for i, build_agent in enumerate(build_agents):
                if i not in build_terminal_paid:
                    turn_reward_accum[i] += terminal_by_agent[i]
                    build_terminal_paid.add(i)
                if build_agent.pending:
                    dummy_state = agents[i].build_state_tensor(env)
                    build_agent.complete_pending(
                        turn_reward_accum[i], dummy_state, env, True
                    )

        # Update epsilon decay counters
        for agent in agents:
            agent.on_episode_end()

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

        # Opt-in progress-reporting seam (see episode_callback's docstring above)
        if episode_callback is not None:
            episode_callback(episode, num_episodes, win_counts)

    save_win_history(win_history, num_episodes)
    if use_build:
        save_build_stats(build_orders, num_episodes)
    return win_counts, win_history


def _terminal_rewards(winner, num_agents):
    """Per-agent terminal reward (issue #46): win/loss by outcome, draw for
    all when there is no winner. Defaults are 0 — a no-op unless config.toml
    [training.rewards] sets win/loss/draw."""
    if winner is None:
        return {i: REWARDS["draw"] for i in range(num_agents)}
    return {
        i: REWARDS["win"] if i == winner else REWARDS["loss"]
        for i in range(num_agents)
    }


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
        save_weights(
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

    np.save(
        f"stats/win_history_{timestamp}.npy",
        {"win_history": np.array(win_history), "manifest": build_manifest()},
        allow_pickle=True,
    )

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
    np.save(
        f"stats/build_orders_{timestamp}.npy",
        {"build_orders": build_orders, "manifest": build_manifest()},
        allow_pickle=True,
    )

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
