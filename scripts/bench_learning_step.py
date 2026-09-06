"""Gate 1 microbenchmark (issue #22, `docs/training_throughput_design.md`
Section 7): is `DQNAgent.optimize()` at batch 32 LAUNCH-BOUND or
COMPUTE-BOUND?

This is the single decisive measurement the design doc's whole patch
sequence (Section 8) hinges on:

    - FLAT   (ms/call roughly constant as batch grows 32 -> 1024) => the
      learner is launch-bound. Lever A's CUDA graphs will pay off, and
      lever B's "one big-batch step instead of N small ones" scheme gives
      close to the derived N-fold speedup (Section 4B).
    - LINEAR (ms/call grows ~proportionally with batch) => the learner is
      compute-bound. Lever B collapses: a batch-32N step then costs
      roughly N times a batch-32 step, so collecting N transitions and
      doing one big update buys nothing over doing N small updates. In
      that world the honest recommendation is lever A items 2-3 (fuse the
      double target-network forward, cut H2D transfers), not parallel
      envs or CUDA graphs.

This script does NOT train anything. No gameplay changes anywhere. It:

  1. Builds one DQNAgent at the CURRENT config (duel preset, config.toml's
     [training] encoder via the encoder registry, fully_conv per config,
     the (16, 32) conv_channels `civulator.training.trainer`'s own pinned
     baseline (`CONV_CHANNELS`) and `DQNAgent`'s own constructor default
     both use) -- the same network construction path `scripts/run_baseline.py`
     / `scripts/train.py` use, not a made-up stand-in.
  2. Fills its ReplayMemory with >=1100 REAL transitions by rolling out a
     seeded duel (2 players, each with their own DQNAgent/ReplayMemory,
     mirroring `civulator.training.trainer.train_agents`'s per-step loop
     exactly -- lazy pending-transition completion, terminal rewards,
     store_transition vs store_pending_transition) at epsilon=1.0, i.e.
     PURELY RANDOM actions drawn through the real `select_action` ->
     `get_valid_select_mask`/`get_valid_moves_mask` path. No hand-built
     tensors, no fabricated shapes.
  3. Times `optimize(batch_size)` at batch sizes 32/64/128/256/512/1024:
     ~20 warmup calls then ~100 timed calls per batch size, with
     `torch.cuda.synchronize()` immediately before starting and before
     stopping each timed call's clock (so async CUDA dispatch never hides
     inside the "next" call's measurement).
  4. Refuses to run if the GPU looks busy (nvidia-smi utilization.gpu
     above a small threshold) -- a compute-bound background job would
     contaminate every timing.
  5. Prints a table (batch -> ms/call mean+-std -> transitions/s) and the
     ms(1024)/ms(32) ratio, states the flat/linear verdict as DATA (the
     ratio and what the design doc's decision rule says it implies, never
     a forced binary), and writes the raw numbers plus an embedded
     manifest (`civulator.meta.build_manifest`) to
     `stats/bench_learning_step_<unix-timestamp>.json`.

Usage:
    C:/Users/steen/anaconda3/python.exe scripts/bench_learning_step.py
    C:/Users/steen/anaconda3/python.exe scripts/bench_learning_step.py --seed 123 --skip-gpu-check
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time

import torch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from civulator.agents import DQNAgent, ReplayMemory, get_encoder
from civulator.config import CFG
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.meta import build_manifest
from civulator.torch_env import resolve_device
from civulator.training.trainer import _seeded_reset, _terminal_rewards, determine_winner

# --- Pinned config for this measurement ------------------------------------
# "The current config" (task spec): duel preset, config.toml's own
# [training].encoder / .fully_conv (never hardcoded here -- if either is
# edited in config.toml, this bench measures the new setting automatically),
# and the (16, 32) conv_channels that BOTH `civulator.training.trainer.
# CONV_CHANNELS` (the pinned baseline every `run_baseline.py` run starts
# from) and `DQNAgent`'s own constructor default already agree on -- there
# is no config.toml key for conv_channels (`scripts/run_baseline.py`'s own
# docstring: "config.toml has no key for it"), so this is the one width
# that is genuinely "current" rather than a specific capacity-ladder
# experiment's pinned choice.
SIZE_PRESET = "duel"
MAP_TYPE = "earthlike"
CONV_CHANNELS = (16, 32)

_tcfg = CFG.get("training", {})
ENCODER_NAME = _tcfg.get("encoder", "enhanced")
FULLY_CONV = _tcfg.get("fully_conv", True)
LEARNING_RATE = _tcfg.get("learning_rate", 0.001)
GAMMA = _tcfg.get("gamma", 0.9)
MAX_TURNS = _tcfg.get("max_turns", 250)

REPLAY_CAPACITY = 10000  # matches scripts/profile_training.py / run_baseline.py
MIN_TRANSITIONS = 1100
BATCH_SIZES = [32, 64, 128, 256, 512, 1024]
WARMUP_CALLS = 20
TIMED_CALLS = 100
STEP_LIMIT = 10000  # per-episode safety net, mirrors trainer.py/evaluate.py

GPU_IDLE_UTIL_THRESHOLD_PCT = 5


# ---------------------------------------------------------------------------
# GPU idle check
# ---------------------------------------------------------------------------

def check_gpu_idle(threshold_pct=GPU_IDLE_UTIL_THRESHOLD_PCT):
    """Abort with a clear message if the GPU is not essentially idle.

    Reads `nvidia-smi --query-gpu=utilization.gpu`, NOT
    `--query-compute-apps`: on a Windows desktop box the compute-apps list
    is populated by ordinary GPU-accelerated desktop windows (Explorer,
    browsers, the Windows shell, Discord, ...) even when nothing is doing
    real work on the device -- it is not a reliable "is something training
    on this GPU" signal. `utilization.gpu` is: a idle 3070 reads 0%.

    Returns (gpu_name, util_pct, mem_used_mib, mem_total_mib) on success.
    Raises SystemExit with a clear message if nvidia-smi is unavailable or
    the GPU looks busy.
    """
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.STDOUT,
        ).decode().strip()
    except Exception as exc:
        raise SystemExit(
            f"bench_learning_step: could not run nvidia-smi to verify the GPU "
            f"is idle before timing ({exc!r}). Refusing to guess -- run on a "
            f"box with nvidia-smi available, or pass --skip-gpu-check if you "
            f"have independently verified the GPU is idle."
        )

    first_line = out.splitlines()[0]
    name, util_str, mem_used_str, mem_total_str = [p.strip() for p in first_line.split(",")]
    util_pct = float(util_str)
    mem_used = float(mem_used_str)
    mem_total = float(mem_total_str)

    if util_pct > threshold_pct:
        raise SystemExit(
            f"bench_learning_step: GPU '{name}' shows {util_pct:.0f}% utilization "
            f"(threshold {threshold_pct}%) -- something else appears to be running "
            f"compute on it. Aborting rather than measuring a contaminated timing. "
            f"nvidia-smi output: {first_line!r}"
        )

    print(
        f"GPU idle check: '{name}' utilization={util_pct:.0f}% "
        f"memory={mem_used:.0f}/{mem_total:.0f} MiB -- OK (<= {threshold_pct}%)"
    )
    return name, util_pct, mem_used, mem_total


# ---------------------------------------------------------------------------
# Real-transition replay-memory fill (mirrors train_agents' per-step loop:
# lazy pending-transition completion, terminal rewards, store_transition vs
# store_pending_transition -- see civulator/training/trainer.py's
# train_agents for the canonical version this deliberately shadows without
# forking the learning-specific pieces, i.e. no build agents, no optimize()
# calls during the fill).
# ---------------------------------------------------------------------------

def fill_replay_memory(env, agents, target_size, seed_base, agent_index=0):
    """Roll out episodes with PURELY RANDOM actions (epsilon=1.0) through the
    real action-selection/masking path until `agents[agent_index].memory`
    holds at least `target_size` real transitions.

    Returns the number of episodes it took.
    """
    from civulator.agents.action_space import decode_action, end_turn_index

    seed_cursor = seed_base
    episode = 0

    while len(agents[agent_index].memory) < target_size:
        _episode_seed, seed_cursor = _seeded_reset(env, seed_cursor, episode, seed_base)
        done = False

        current_player_index = env.current_player.player_index
        current_agent = agents[current_player_index]
        next_state = current_agent.build_state_tensor(env)

        terminal_by_agent = None
        terminal_paid = set()
        step_counter = 0

        while not done:
            step_counter += 1
            if step_counter > STEP_LIMIT:
                break

            current_player_index = env.current_player.player_index
            current_agent = agents[current_player_index]
            state = next_state

            if current_agent.pending_transitions:
                current_agent.complete_pending_transition(state, False)

            action = current_agent.select_action(state, epsilon=1.0, game_env=env)
            end_turn_idx = end_turn_index(env.n, env.m)
            selected_pos, move_pos = action

            if selected_pos == end_turn_idx:
                env.current_player.end_turn()
                env.next_turn()
                reward = 0
                done = env.done
            else:
                action_matrix = decode_action(selected_pos, move_pos, env.n, env.m)
                try:
                    _, reward, done = env.step(action_matrix)
                except AttributeError:
                    reward = 0
                    done = env.done

            if done and terminal_by_agent is None:
                terminal_by_agent = _terminal_rewards(determine_winner(env), len(agents))
                reward += terminal_by_agent[current_player_index]
                terminal_paid.add(current_player_index)

            next_state = current_agent.build_state_tensor(env)

            if env.current_player.player_index == current_player_index:
                current_agent.store_transition(state, action, reward, next_state, done)
            else:
                current_agent.store_pending_transition(state, action, reward)

            if env.current_player.player_index != current_player_index:
                next_player_index = env.current_player.player_index
                next_player_agent = agents[next_player_index]
                next_state = next_player_agent.build_state_tensor(env)

        if terminal_by_agent is None:
            terminal_by_agent = _terminal_rewards(determine_winner(env), len(agents))
        for i, agent in enumerate(agents):
            extra = 0.0 if i in terminal_paid else terminal_by_agent[i]
            terminal_paid.add(i)
            while agent.pending_transitions:
                final_state = agent.build_state_tensor(env)
                agent.complete_pending_transition(final_state, True, extra_reward=extra)
                extra = 0.0

        episode += 1

    return episode


# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

def time_optimize(agent, batch_size, device, warmup_calls=WARMUP_CALLS, timed_calls=TIMED_CALLS):
    """Mean/std wall-clock seconds per `agent.optimize(batch_size)` call,
    CUDA-synced immediately before starting and before stopping each timed
    call's clock so async dispatch from one call cannot bleed into the
    next call's measurement.
    """
    is_cuda = device.type == "cuda"

    for _ in range(warmup_calls):
        agent.optimize(batch_size)
    if is_cuda:
        torch.cuda.synchronize()

    samples = []
    for _ in range(timed_calls):
        if is_cuda:
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        agent.optimize(batch_size)
        if is_cuda:
            torch.cuda.synchronize()
        t1 = time.perf_counter()
        samples.append(t1 - t0)

    mean_s = statistics.mean(samples)
    stdev_s = statistics.stdev(samples) if len(samples) > 1 else 0.0
    return mean_s, stdev_s, samples


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Gate 1 microbenchmark (issue #22): DQNAgent.optimize() batch-size scaling."
    )
    parser.add_argument("--seed", type=int, default=20220001,
                         help="Seed base for the replay-memory-filling rollout (default reproducible run).")
    parser.add_argument("--min-transitions", type=int, default=MIN_TRANSITIONS)
    parser.add_argument("--warmup-calls", type=int, default=WARMUP_CALLS)
    parser.add_argument("--timed-calls", type=int, default=TIMED_CALLS)
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=BATCH_SIZES)
    parser.add_argument("--skip-gpu-check", action="store_true",
                         help="Skip the nvidia-smi idle check (only if you have verified it yourself).")
    args = parser.parse_args()

    print("=" * 72)
    print("Gate 1: DQNAgent.optimize() batch-scaling microbenchmark (issue #22)")
    print("docs/training_throughput_design.md Section 7")
    print("=" * 72)

    torch_version = torch.__version__
    cuda_version = torch.version.cuda
    cuda_available = torch.cuda.is_available()
    device = resolve_device()
    gpu_name = torch.cuda.get_device_name(0) if device.type == "cuda" else None

    print(f"torch={torch_version} cuda_version={cuda_version} cuda_available={cuda_available}")
    print(f"resolved device: {device}" + (f" ({gpu_name})" if gpu_name else ""))

    gpu_info = None
    if device.type == "cuda" and not args.skip_gpu_check:
        gpu_info = check_gpu_idle()
    elif args.skip_gpu_check:
        print("GPU idle check: SKIPPED (--skip-gpu-check)")

    n, m, num_players = resolve_size_and_players(size=SIZE_PRESET)
    d = get_encoder(ENCODER_NAME).get_depth(num_players)
    print(
        f"config: size={SIZE_PRESET} ({m}x{n}) players={num_players} encoder={ENCODER_NAME} "
        f"({d}ch) fully_conv={FULLY_CONV} conv_channels={CONV_CHANNELS} map_type={MAP_TYPE} "
        f"max_turns={MAX_TURNS}"
    )

    env = GameEnvironment(n, m, num_players, map_type=MAP_TYPE)
    env.max_turns = MAX_TURNS

    agents = []
    for _ in range(num_players):
        mem = ReplayMemory(REPLAY_CAPACITY)
        agent = DQNAgent(
            n, m, d, mem, gamma=GAMMA, learning_rate=LEARNING_RATE,
            conv_channels=CONV_CHANNELS, encoder=ENCODER_NAME, fully_conv=FULLY_CONV,
            device=device,
        )
        agents.append(agent)

    bench_agent = agents[0]

    print(
        f"\nFilling replay memory with >= {args.min_transitions} REAL transitions "
        f"(seeded duel rollout, epsilon=1.0 i.e. purely random actions through the "
        f"real select_action/mask path, seed_base={args.seed})..."
    )
    t0 = time.perf_counter()
    episodes_used = fill_replay_memory(env, agents, args.min_transitions, args.seed)
    fill_elapsed = time.perf_counter() - t0
    print(
        f"  filled agent[0].memory to {len(bench_agent.memory)} transitions "
        f"over {episodes_used} episodes in {fill_elapsed:.2f}s"
    )

    max_batch = max(args.batch_sizes)
    if len(bench_agent.memory) < max_batch:
        raise SystemExit(
            f"bench_learning_step: replay memory only holds {len(bench_agent.memory)} "
            f"transitions, need >= {max_batch} for the largest requested batch size."
        )

    print(
        f"\nTiming optimize() at batch sizes {args.batch_sizes} "
        f"({args.warmup_calls} warmup + {args.timed_calls} timed calls each)..."
    )

    results = {}
    for batch_size in args.batch_sizes:
        mean_s, stdev_s, samples = time_optimize(
            bench_agent, batch_size, device,
            warmup_calls=args.warmup_calls, timed_calls=args.timed_calls,
        )
        transitions_per_s = batch_size / mean_s if mean_s > 0 else float("inf")
        results[batch_size] = {
            "mean_ms": mean_s * 1000.0,
            "stdev_ms": stdev_s * 1000.0,
            "transitions_per_s": transitions_per_s,
            "samples_s": samples,
        }
        print(
            f"  batch={batch_size:5d}  mean={mean_s * 1000:8.3f} ms  "
            f"stdev={stdev_s * 1000:7.3f} ms  transitions/s={transitions_per_s:10.1f}"
        )

    print("\n" + "-" * 72)
    print(f"{'batch':>8s} {'ms/call mean':>14s} {'ms/call std':>13s} {'transitions/s':>15s}")
    print("-" * 72)
    for batch_size in args.batch_sizes:
        r = results[batch_size]
        print(f"{batch_size:8d} {r['mean_ms']:14.3f} {r['stdev_ms']:13.3f} {r['transitions_per_s']:15.1f}")
    print("-" * 72)

    ms_32 = results[32]["mean_ms"] if 32 in results else None
    ms_1024 = results[1024]["mean_ms"] if 1024 in results else None
    ratio = None
    if ms_32 is not None and ms_1024 is not None and ms_32 > 0:
        ratio = ms_1024 / ms_32

    print("\n=== Verdict data (docs/training_throughput_design.md Section 7 decision rule) ===")
    if ratio is not None:
        print(f"ms(1024)/ms(32) = {ms_1024:.3f} / {ms_32:.3f} = {ratio:.2f}x")
        print(
            "Design doc's rule: FLAT (ratio close to 1x, i.e. 1024 costs about what 32 "
            "costs) => launch-bound => lever A's CUDA graphs pay off and lever B's "
            "big-batch scheme gives ~N x as derived in Section 4B. LINEAR (ratio close "
            "to 32x, i.e. cost scales with batch size) => compute-bound => lever B "
            "collapses: a batch-32N step costs ~N x a batch-32 step and parallel-env "
            "throughput gain is zero; only lever A items 2-3 (fuse the double "
            "target-network forward, cut H2D transfers) remain worth doing."
        )
        print(
            f"Measured ratio {ratio:.2f}x against a 32x batch-size increase places this "
            f"run {'closer to the FLAT/launch-bound end' if ratio < 8 else 'closer to the LINEAR/compute-bound end' if ratio > 16 else 'in between -- neither cleanly flat nor cleanly linear'} "
            "of that range; see the full table above for the actual shape of the curve "
            "rather than reading this one ratio in isolation."
        )
    else:
        print("Could not compute ms(1024)/ms(32) -- one of batch 32 or 1024 was not measured.")

    # --- write stats JSON -----------------------------------------------
    manifest = build_manifest()
    timestamp = int(time.time())
    stats_dir = os.path.join(PROJECT_ROOT, "stats")
    os.makedirs(stats_dir, exist_ok=True)
    stats_path = os.path.join(stats_dir, f"bench_learning_step_{timestamp}.json")

    summary = {
        "issue": 22,
        "gate": 1,
        "description": "DQNAgent.optimize() batch-size scaling microbenchmark",
        "seed": args.seed,
        "min_transitions_requested": args.min_transitions,
        "transitions_filled": len(bench_agent.memory),
        "fill_episodes": episodes_used,
        "fill_elapsed_seconds": fill_elapsed,
        "warmup_calls": args.warmup_calls,
        "timed_calls": args.timed_calls,
        "batch_sizes": args.batch_sizes,
        "size_preset": SIZE_PRESET,
        "map_dims": {"rows": n, "cols": m},
        "num_players": num_players,
        "map_type": MAP_TYPE,
        "max_turns": MAX_TURNS,
        "encoder": ENCODER_NAME,
        "encoder_channels": d,
        "fully_conv": FULLY_CONV,
        "conv_channels": list(CONV_CHANNELS),
        "learning_rate": LEARNING_RATE,
        "gamma": GAMMA,
        "replay_capacity": REPLAY_CAPACITY,
        "device": str(device),
        "torch_version": torch_version,
        "cuda_version": cuda_version,
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
        "gpu_idle_check": (
            {"utilization_pct": gpu_info[1], "memory_used_mib": gpu_info[2],
             "memory_total_mib": gpu_info[3]}
            if gpu_info is not None else "skipped"
        ),
        "results": {
            str(batch_size): {
                "mean_ms": r["mean_ms"],
                "stdev_ms": r["stdev_ms"],
                "transitions_per_s": r["transitions_per_s"],
                "samples_s": r["samples_s"],
            }
            for batch_size, r in results.items()
        },
        "ratio_ms1024_over_ms32": ratio,
        "manifest": manifest,
    }

    with open(stats_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\nStats written to: {stats_path}")
    print("=== Done ===")


if __name__ == "__main__":
    main()
