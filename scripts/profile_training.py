"""Per-subsystem wall-clock profiling harness for DQN training (issue #34).

Answers ONE question before any engine subsystem gets ported to C++ (issue
#32's bit-exact, oracle-gated port strategy): during REAL training, where
does wall-clock time actually go? If it's mostly torch/GPU, no engine port
will meaningfully shorten a training night; if it's mostly Python engine
code (world gen, state encoding, env.step, pathfinding, combat, replay
memory), THAT is the port candidate.

Runs a real (but short) slice of `civulator.training.trainer.train_agents`
-- the exact function `scripts/train.py` calls for the real 1000-episode
baseline -- through TWO independent measurement techniques over the same
configuration, so they can cross-check each other:

  (a) Instrumented buckets: perf_counter wrapped, NON-INVASIVELY (monkey-
      patched from this script only -- nothing under civulator/ is edited),
      around the real seams in trainer.py / dqn_agent.py / build_agent.py /
      environment.py / unit.py / replay_memory.py. Bucket accounting is
      EXCLUSIVE (self-time, like cProfile's "tottime"): a `BucketTimer`
      stack pauses the parent bucket's clock whenever a nested bucket is
      entered, so shares sum to ~100% of the wall-clock measured around
      the `train_agents(...)` call, with the untracked remainder reported
      as `other_overhead` instead of being silently double-counted.

  (b) A cProfile pass over a freshly-reseeded run of the same
      configuration (patches restored first, so cProfile sees the real
      call graph, not this script's wrapper closures) -- the cross-check.
      Both an "engine-side" view (frames whose file lives under
      civulator/) and an unrestricted global view (to see whether
      torch/numpy internals dominate) are reported, sorted by tottime,
      top ~30.

GPU note: instrumented buckets are separated by a `torch.cuda.synchronize()`
(when CUDA is available) at every bucket boundary, so a bucket's reported
time reflects actual GPU completion, not just async CPU-side kernel
dispatch. This makes the instrumented pass measurably SLOWER than an
unsynced real run would be (lost CPU/GPU overlap) -- an accepted,
documented tradeoff for attribution accuracy. cProfile, by contrast, does
NOT force synchronization (it cannot see inside a CUDA stream) and adds
substantial per-call overhead of its own -- expect the two views to
disagree exactly on GPU-heavy, high-call-count regions; the report calls
this out rather than treating either view as ground truth.

A separate, simpler micro-benchmark (independent of the two techniques
above) times `Map.generate_map()` -- the "mapgen generate()" call
`GameEnvironment.reset()` makes every episode -- in isolation, at Duel and
Standard size, mean over 20 calls (1 discarded warmup call first).

Both real `train_agents()` passes run with `save_checkpoints=False` and
with the process cwd redirected to a scratch temp directory for their
duration, so this throwaway profiling slice never writes into the repo's
real weights/ or stats/ (the scientific record -- see project CLAUDE.md).

Usage:
    python scripts/profile_training.py
    python scripts/profile_training.py --episodes 50 --size standard --players 6
    python scripts/profile_training.py --no-cprofile --no-mapgen-bench   # fast iteration
"""

import argparse
import contextlib
import functools
import os
import pstats
import random
import shutil
import statistics
import sys
import tempfile
import time
import cProfile
from collections import defaultdict

import numpy as np
import torch

# Add project root to path (same pattern as every other scripts/*.py)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)
_CIVULATOR_DIR = os.path.join(_PROJECT_ROOT, "civulator")

from civulator.config import CFG
from civulator.game import GameEnvironment, Map, resolve_size_and_players
from civulator.game.unit import Unit
from civulator.agents import DQNAgent, BuildAgent, BasicStateEncoder, EnhancedStateEncoder
from civulator.agents import dqn_agent as _dqn_agent_mod
from civulator.agents import build_agent as _build_agent_mod
from civulator.agents.networks import (
    SelectAndMoveNetwork, SharedBackboneNetwork, FullyConvNetwork, FullyConvSeparateNetwork,
)
from civulator.agents.replay_memory import ReplayMemory
from civulator.rng import PortableRNG
from civulator.training import train_agents

_tcfg = CFG.get("training", {})
_map_cfg = CFG.get("map", {})
_SIZE_CHOICES = sorted(_map_cfg.get("sizes", {}).keys()) or None

# Same tournament-style per-player configs scripts/train.py uses for a real
# run -- reused verbatim so network sizes (and therefore forward/backward
# cost) match what "tonight's" baseline actually trains, not a made-up
# lighter stand-in.
AGENT_CONFIGS = [
    {"name": "Small-Aggr",    "conv": (8, 16),  "lr": 0.001, "eps_end": 0.01, "eps_decay": 2000},
    {"name": "Small-Patient", "conv": (8, 16),  "lr": 0.001, "eps_end": 0.05, "eps_decay": 8000},
    {"name": "Med-Aggr",      "conv": (16, 32), "lr": 0.001, "eps_end": 0.01, "eps_decay": 2000},
    {"name": "Med-Patient",   "conv": (16, 32), "lr": 0.001, "eps_end": 0.05, "eps_decay": 8000},
    {"name": "Large-Aggr",    "conv": (32, 64), "lr": 0.001, "eps_end": 0.01, "eps_decay": 2000},
    {"name": "Large-Patient", "conv": (32, 64), "lr": 0.001, "eps_end": 0.05, "eps_decay": 8000},
    {"name": "Med-FastLR",    "conv": (16, 32), "lr": 0.003, "eps_end": 0.01, "eps_decay": 2000},
    {"name": "Med-FastLR-P",  "conv": (16, 32), "lr": 0.003, "eps_end": 0.05, "eps_decay": 8000},
]

# The fixed bucket taxonomy this harness reports against (issue #34).
TOP_LEVEL_BUCKETS = [
    "world_gen", "state_encoding", "action_selection", "env_step",
    "learning_step", "replay_memory_ops",
]


# ---------------------------------------------------------------------------
# Exclusive-time bucket accounting
# ---------------------------------------------------------------------------

class BucketTimer:
    """Stack-based EXCLUSIVE (self-time) wall-clock accounting.

    Entering a nested bucket pauses the parent's running clock (crediting
    it with elapsed time up to that instant) and resumes it on exit -- so
    `totals` never double-counts nested work, and `sum(totals.values())`
    is exactly the wall-clock time spent inside ANY tracked bucket. The
    gap between that and the true wall-clock measured around the whole
    run is the untracked "other/overhead" (computed by the caller).

    `sync_cuda=True` calls `torch.cuda.synchronize()` at every bucket
    boundary so a bucket's reported time reflects actual GPU completion,
    not just async dispatch -- see module docstring.
    """

    def __init__(self, sync_cuda=False):
        self.totals = defaultdict(float)
        self.counts = defaultdict(int)
        self._stack = []  # list of [name, slice_start_perf_counter]
        self.sync_cuda = sync_cuda

    def _sync(self):
        if self.sync_cuda:
            torch.cuda.synchronize()

    def current_bucket(self):
        """Name of the innermost currently-active bucket, or None."""
        return self._stack[-1][0] if self._stack else None

    @contextlib.contextmanager
    def track(self, name):
        self._sync()
        now = time.perf_counter()
        if self._stack:
            parent_name, parent_slice_start = self._stack[-1]
            self.totals[parent_name] += now - parent_slice_start
        self._stack.append([name, now])
        self.counts[name] += 1
        try:
            yield
        finally:
            self._sync()
            now = time.perf_counter()
            leaf_name, leaf_slice_start = self._stack.pop()
            self.totals[leaf_name] += now - leaf_slice_start
            if self._stack:
                self._stack[-1][1] = now  # parent's next slice starts here

    def subtree_total(self, prefix):
        """Sum of `prefix` and every `prefix.*` child bucket's exclusive time."""
        return sum(
            v for k, v in self.totals.items()
            if k == prefix or k.startswith(prefix + ".")
        )


# ---------------------------------------------------------------------------
# Non-invasive instrumentation: monkeypatches installed/restored by THIS
# script only. Nothing under civulator/ is ever edited.
# ---------------------------------------------------------------------------

def _wrap_method(cls, method_name, bucket_name, timer, patches):
    original = getattr(cls, method_name)

    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        with timer.track(bucket_name):
            return original(self, *args, **kwargs)

    setattr(cls, method_name, wrapper)
    patches.append((cls, method_name, original))


def _wrap_function(owner, func_name, bucket_name, timer, patches):
    """`owner` is a MODULE whose attribute `func_name` is a bare function.

    `from .networks import X` binds X into the IMPORTING module's own
    namespace; callers resolve the bare name from THAT module's globals at
    call time, so the attribute must be patched there (on `owner`), not on
    `civulator.agents.networks` itself, or the already-bound reference the
    callers actually use is unaffected.
    """
    original = getattr(owner, func_name)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        with timer.track(bucket_name):
            return original(*args, **kwargs)

    setattr(owner, func_name, wrapper)
    patches.append((owner, func_name, original))


def _wrap_forward_context_aware(cls, timer, patches):
    """Network forward passes get their own sub-bucket, but only when
    called from action selection or the learning step -- the only two
    places any network's forward() runs in this codebase (greedy action
    selection, and compute_loss/optimize on the live + target networks).
    Elsewhere (there is no "elsewhere" today) the call passes through
    untimed rather than being mis-attributed to the wrong parent.
    """
    original = cls.forward

    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        top = timer.current_bucket()
        if top == "action_selection":
            with timer.track("action_selection.net_forward"):
                return original(self, *args, **kwargs)
        elif top == "learning_step":
            with timer.track("learning_step.net_forward"):
                return original(self, *args, **kwargs)
        return original(self, *args, **kwargs)

    cls.forward = wrapper
    patches.append((cls, "forward", original))


def install_patches(timer):
    """Monkeypatch the training-loop seams described in the module
    docstring. Returns a list of (owner, attr_name, original) so
    `restore_patches` can put everything back exactly as found.
    """
    patches = []

    # --- engine: world gen, env.step, pathfinding, combat, turn advance ---
    _wrap_method(GameEnvironment, "reset", "world_gen", timer, patches)
    _wrap_method(GameEnvironment, "step", "env_step", timer, patches)
    _wrap_method(GameEnvironment, "next_turn", "env_step.turn_advance", timer, patches)
    _wrap_method(GameEnvironment, "_execute_attack", "env_step.combat", timer, patches)
    _wrap_method(Unit, "move", "env_step.pathfinding", timer, patches)

    # --- agents: state encoding, action selection, learning ---
    _wrap_method(DQNAgent, "build_state_tensor", "state_encoding", timer, patches)
    _wrap_method(DQNAgent, "select_action", "action_selection", timer, patches)
    _wrap_method(DQNAgent, "optimize", "learning_step", timer, patches)
    _wrap_method(BuildAgent, "select_build", "action_selection", timer, patches)
    _wrap_method(BuildAgent, "optimize", "learning_step", timer, patches)

    _wrap_function(_dqn_agent_mod, "get_valid_select_mask", "action_selection.mask_building", timer, patches)
    _wrap_function(_dqn_agent_mod, "get_valid_moves_mask", "action_selection.mask_building", timer, patches)
    _wrap_function(_build_agent_mod, "get_valid_build_mask", "action_selection.mask_building", timer, patches)

    for network_cls in (SelectAndMoveNetwork, SharedBackboneNetwork, FullyConvNetwork, FullyConvSeparateNetwork):
        _wrap_forward_context_aware(network_cls, timer, patches)
    _wrap_forward_context_aware(_build_agent_mod.BuildNetwork, timer, patches)

    # --- replay memory ---
    _wrap_method(ReplayMemory, "push", "replay_memory_ops", timer, patches)
    _wrap_method(ReplayMemory, "sample", "replay_memory_ops", timer, patches)

    return patches


def restore_patches(patches):
    for owner, attr_name, original in reversed(patches):
        setattr(owner, attr_name, original)


# ---------------------------------------------------------------------------
# Training-object construction (mirrors scripts/train.py's tournament-mode
# setup exactly, so this profiles the real configured path, not a stand-in)
# ---------------------------------------------------------------------------

def set_random_seeds(seed=42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)


def build_training_objects(args):
    """Construct env + combat agents + build agents exactly the way
    scripts/train.py does for a real tournament-mode run: same
    AGENT_CONFIGS table (so network sizes match production), same
    resolve_size_and_players / encoder-depth resolution.

    Returns (env, agents, build_agents, n, m, num_players).
    """
    n, m, num_players = resolve_size_and_players(size=args.size, num_players=args.players)

    if args.encoder == "enhanced":
        d = EnhancedStateEncoder().get_depth(num_players)
    else:
        d = BasicStateEncoder().get_depth(num_players)

    env = GameEnvironment(n, m, num_players, map_type=args.map_type, seed=args.seed)
    env.max_turns = args.max_turns

    configs = AGENT_CONFIGS[:num_players]
    agents = []
    for cfg in configs:
        mem = ReplayMemory(10000)
        agent = DQNAgent(n, m, d, mem, learning_rate=cfg["lr"], encoder=args.encoder,
                          fully_conv=args.fully_conv, conv_channels=cfg["conv"])
        agent.set_epsilon_schedule(1.0, cfg["eps_end"], cfg["eps_decay"])
        agent.config_name = cfg["name"]
        agents.append(agent)

    build_agents = [
        BuildAgent(n, m, d, learning_rate=configs[i]["lr"])
        for i in range(num_players)
    ]

    return env, agents, build_agents, n, m, num_players


def warmup_run(env, agents, build_agents, batch_size):
    """One untimed episode so CUDA context creation / cuDNN algorithm
    selection happens BEFORE the timed region -- otherwise a short slice
    would attribute a one-time few-hundred-ms GPU warmup cost to episode
    1's action_selection/learning_step buckets, which is real for THIS
    run but irrelevant (a rounding error) at 1000-episode scale. Also
    gives replay memory a head start, slightly softening the "memory too
    small, optimize() skipped" cold-start bias a short slice otherwise
    over-represents relative to a full night.
    """
    train_agents(env, agents, num_episodes=1, batch_size=batch_size, debug=False,
                 save_checkpoints=False, build_agents=build_agents)
    if torch.cuda.is_available():
        torch.cuda.synchronize()


@contextlib.contextmanager
def _chdir(path):
    """Redirect train_agents()'s relative weights/ and stats/ writes into a
    scratch directory for the duration of the `with` block, so a throwaway
    profiling slice never touches the repo's real scientific record."""
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


# ---------------------------------------------------------------------------
# (a) Instrumented pass
# ---------------------------------------------------------------------------

def run_instrumented(args, workdir):
    set_random_seeds(args.seed)
    t0 = time.perf_counter()
    env, agents, build_agents, n, m, num_players = build_training_objects(args)
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    setup_seconds = time.perf_counter() - t0

    sync_cuda = torch.cuda.is_available()
    with _chdir(workdir):
        warmup_run(env, agents, build_agents, args.batch_size)

        timer = BucketTimer(sync_cuda=sync_cuda)
        patches = install_patches(timer)
        try:
            t1 = time.perf_counter()
            win_counts, win_history = train_agents(
                env, agents, num_episodes=args.episodes, batch_size=args.batch_size,
                debug=False, save_checkpoints=False, build_agents=build_agents,
            )
            elapsed = time.perf_counter() - t1
        finally:
            restore_patches(patches)

    return timer, elapsed, setup_seconds, win_counts, win_history, (n, m, num_players)


def print_share_table(timer, elapsed, setup_seconds):
    print("\n=== (a) Instrumented per-subsystem wall-clock shares ===")
    print(f"train_agents() wall-clock: {elapsed:.2f}s over the timed episodes "
          f"(one-time agent/env construction: {setup_seconds:.2f}s, excluded -- "
          f"O(1) per run, not O(episodes))")

    tracked = sum(timer.totals.values())
    overhead = max(0.0, elapsed - tracked)

    print(f"\n{'bucket':32s} {'seconds':>10s} {'share':>8s} {'calls':>10s}")
    print("-" * 64)
    for name in TOP_LEVEL_BUCKETS:
        total = timer.subtree_total(name)
        share = 100.0 * total / elapsed if elapsed > 0 else 0.0
        calls = timer.counts.get(name, 0)
        print(f"{name:32s} {total:10.3f} {share:7.2f}% {calls:>10d}")

        children = sorted(
            (k for k in timer.totals if k.startswith(name + ".")),
            key=lambda k: -timer.totals[k],
        )
        for child in children:
            child_total = timer.totals[child]
            child_share = 100.0 * child_total / elapsed if elapsed > 0 else 0.0
            label = "  " + child
            print(f"{label:32s} {child_total:10.3f} {child_share:7.2f}% {timer.counts.get(child, 0):>10d}")

    overhead_share = 100.0 * overhead / elapsed if elapsed > 0 else 0.0
    print(f"{'other_overhead':32s} {overhead:10.3f} {overhead_share:7.2f}% {'':>10s}")
    print("-" * 64)
    print(f"{'TOTAL':32s} {elapsed:10.3f} {100.0:7.2f}%")
    return overhead


# ---------------------------------------------------------------------------
# (b) cProfile cross-check
# ---------------------------------------------------------------------------

def run_cprofile(args, workdir):
    set_random_seeds(args.seed)
    env, agents, build_agents, n, m, num_players = build_training_objects(args)

    with _chdir(workdir):
        warmup_run(env, agents, build_agents, args.batch_size)

        profiler = cProfile.Profile()
        t0 = time.perf_counter()
        profiler.enable()
        train_agents(
            env, agents, num_episodes=args.episodes, batch_size=args.batch_size,
            debug=False, save_checkpoints=False, build_agents=build_agents,
        )
        profiler.disable()
        elapsed = time.perf_counter() - t0

    return profiler, elapsed


def _is_engine_file(filename):
    if not filename or filename.startswith("<"):
        return False
    try:
        abspath = os.path.abspath(filename)
    except Exception:
        return False
    return abspath == _CIVULATOR_DIR or abspath.startswith(_CIVULATOR_DIR + os.sep)


def _shorten_path(filename):
    try:
        return os.path.relpath(os.path.abspath(filename), _PROJECT_ROOT)
    except Exception:
        return filename


def extract_stats(profiler, engine_only, top_n):
    """Returns (top_n rows sorted by tottime desc, total tottime of the
    selected set, total tottime across ALL profiled functions)."""
    stats = pstats.Stats(profiler)
    all_rows = []
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        filename, lineno, funcname = func
        all_rows.append((tt, ct, nc, cc, filename, lineno, funcname))

    total_tt_all = sum(r[0] for r in all_rows)
    selected = [r for r in all_rows if _is_engine_file(r[4])] if engine_only else all_rows
    selected.sort(key=lambda r: r[0], reverse=True)
    total_tt_selected = sum(r[0] for r in selected)
    return selected[:top_n], total_tt_selected, total_tt_all


def print_cprofile_table(rows, title):
    print(f"\n--- {title} ---")
    print(f"{'tottime':>10} {'cumtime':>10} {'ncalls':>12}  location")
    for tt, ct, nc, cc, filename, lineno, funcname in rows:
        short = _shorten_path(filename)
        calls = str(nc) if nc == cc else f"{nc}/{cc}"
        print(f"{tt:10.4f} {ct:10.4f} {calls:>12}  {short}:{lineno}({funcname})")


def print_top3(engine_rows):
    print("\n=== Top-3 hottest engine-side functions (cProfile, by tottime) ===")
    for i, (tt, ct, nc, cc, filename, lineno, funcname) in enumerate(engine_rows[:3], 1):
        short = _shorten_path(filename)
        print(f"  {i}. {short}:{lineno}({funcname}) -- tottime={tt:.4f}s cumtime={ct:.4f}s ncalls={nc}")


# ---------------------------------------------------------------------------
# Deliverable 3: mapgen micro-benchmark (independent of the two passes above)
# ---------------------------------------------------------------------------

def mapgen_microbenchmark(sizes, n_calls, map_type, extra_warmup=1):
    print("\n=== Mapgen micro-benchmark: Map.generate_map() in isolation ===")
    results = {}
    for size_name in sizes:
        rows, cols, players = resolve_size_and_players(size=size_name)
        samples = []
        for i in range(extra_warmup + n_calls):
            m = Map(rows, cols, rng=PortableRNG(seed=i))
            t0 = time.perf_counter()
            m.generate_map(map_type, num_players=players)
            t1 = time.perf_counter()
            if i >= extra_warmup:
                samples.append(t1 - t0)
        mean_s = statistics.mean(samples)
        stdev_s = statistics.stdev(samples) if len(samples) > 1 else 0.0
        per_1000_episodes_s = mean_s * 1000
        results[size_name] = {
            "rows": rows, "cols": cols, "players": players,
            "mean_s": mean_s, "stdev_s": stdev_s, "n": len(samples),
            "per_1000_episodes_s": per_1000_episodes_s,
        }
        print(
            f"  {size_name:10s} ({cols}x{rows}, {players}p): "
            f"mean={mean_s * 1000:8.2f} ms/call  stdev={stdev_s * 1000:7.2f} ms  (n={len(samples)})  "
            f"->  {per_1000_episodes_s:8.1f}s ({per_1000_episodes_s / 60:5.2f} min) per 1000 episodes"
        )
    return results


# ---------------------------------------------------------------------------
# GPU / device report (deliverable 2)
# ---------------------------------------------------------------------------

def report_gpu_info():
    print("\n=== GPU / device ===")
    print(f"torch version: {torch.__version__}")
    cuda_ok = torch.cuda.is_available()
    print(f"torch.cuda.is_available(): {cuda_ok}")
    if cuda_ok:
        print(f"device: {torch.cuda.get_device_name(0)}")
    print(
        "DQNAgent/BuildAgent device resolution (civulator/agents/dqn_agent.py, "
        "build_agent.py) reads: torch.device(\"cuda\" if torch.cuda.is_available() "
        "else \"cpu\") -- unconditional, no CLI/config flag needed. The network AND "
        "its target-network deepcopy are both .to(self.device) at construction, so "
        f"the default training path runs on {'GPU' if cuda_ok else 'CPU'} automatically."
    )
    return cuda_ok


# ---------------------------------------------------------------------------
# Extrapolation + auto verdict
# ---------------------------------------------------------------------------

def extrapolate_and_verdict(timer, elapsed, episodes, mapgen_results, size_name):
    seconds_per_episode = elapsed / episodes
    hours_1000 = seconds_per_episode * 1000 / 3600.0

    print("\n=== Extrapolation to 1000 episodes ===")
    print(f"{seconds_per_episode:.3f} s/episode measured over {episodes} episodes")
    print(f"1000-episode night (unchanged): {hours_1000:.2f} hours")

    if size_name in mapgen_results:
        mg = mapgen_results[size_name]
        world_gen_total = timer.subtree_total("world_gen")
        implied_mean = world_gen_total / episodes if episodes else 0.0
        print(
            f"\nCross-check vs mapgen micro-benchmark at '{size_name}': isolated "
            f"generate_map() mean={mg['mean_s'] * 1000:.2f} ms/call; the full "
            f"world_gen bucket (reset() incl. capital + starting-warrior placement) "
            f"implies {implied_mean * 1000:.2f} ms/call in this run -- the gap is "
            "player/city/unit setup on top of pure mapgen."
        )

    # Candidate port targets: engine-side, non-torch, non-overhead buckets.
    # `action_selection` as a WHOLE subtree mixes a portable piece
    # (mask_building -- Python loop + trivial GPU scalar writes, no real
    # GPU compute) with net_forward (genuine GPU compute, not a C++-port
    # target) -- so mask_building is compared as its own leaf here rather
    # than inflating the candidate list with net_forward by including the
    # whole subtree.
    port_candidate_values = {
        "env_step": timer.subtree_total("env_step"),
        "state_encoding": timer.subtree_total("state_encoding"),
        "world_gen": timer.subtree_total("world_gen"),
        "replay_memory_ops": timer.subtree_total("replay_memory_ops"),
        "action_selection.mask_building": timer.totals.get("action_selection.mask_building", 0.0),
    }
    best_name, best_seconds = max(port_candidate_values.items(), key=lambda kv: kv[1])
    best_share = 100.0 * best_seconds / elapsed if elapsed > 0 else 0.0

    hours_1000_upper_bound_after_port = (elapsed - best_seconds) / episodes * 1000 / 3600.0
    saved_hours = hours_1000 - hours_1000_upper_bound_after_port

    torch_seconds = (
        timer.subtree_total("learning_step")
        + timer.totals.get("action_selection.net_forward", 0.0)
    )
    torch_share = 100.0 * torch_seconds / elapsed if elapsed > 0 else 0.0

    print(f"\nLargest engine-side (portable) bucket: {best_name} ({best_share:.1f}% of wall-clock)")
    print(
        f"If ELIMINATED ENTIRELY (upper bound, NOT a real port's expected result): "
        f"{hours_1000_upper_bound_after_port:.2f}h night "
        f"(saves {saved_hours:.2f}h, {100 * saved_hours / hours_1000:.1f}% shorter)"
    )
    print(f"Torch-side share (learning_step + action-selection net forward): {torch_share:.1f}% of wall-clock")

    return {
        "seconds_per_episode": seconds_per_episode,
        "hours_1000": hours_1000,
        "best_port_candidate": best_name,
        "best_port_share_pct": best_share,
        "hours_1000_upper_bound_after_port": hours_1000_upper_bound_after_port,
        "saved_hours_upper_bound": saved_hours,
        "torch_share_pct": torch_share,
    }


def print_verdict(extrap):
    print("\n=== PORT VERDICT (auto-generated heuristic; see agent report for full reasoning) ===")
    if extrap["torch_share_pct"] >= 55:
        print(
            f"Torch/GPU ops account for {extrap['torch_share_pct']:.1f}% of wall-clock. "
            f"The largest engine-side candidate ({extrap['best_port_candidate']}) is only "
            f"{extrap['best_port_share_pct']:.1f}%, capping any C++ port's upper-bound saving "
            f"at {extrap['saved_hours_upper_bound']:.2f}h off a {extrap['hours_1000']:.2f}h night. "
            "Night is torch-bound; no engine port helps materially."
        )
    else:
        print(
            f"Engine-side Python ({extrap['best_port_candidate']}, "
            f"{extrap['best_port_share_pct']:.1f}% of wall-clock) outweighs torch/GPU "
            f"({extrap['torch_share_pct']:.1f}%). A bit-exact C++ port of "
            f"{extrap['best_port_candidate']} caps the night at "
            f"{extrap['hours_1000_upper_bound_after_port']:.2f}h (from {extrap['hours_1000']:.2f}h) "
            "in the best case -- worth scoping."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Per-subsystem wall-clock profiling harness for DQN training (issue #34)."
    )
    parser.add_argument("--episodes", type=int, default=30, help="Episodes in the timed slice")
    parser.add_argument("--size", default="duel", choices=_SIZE_CHOICES, help="[map.sizes.*] preset name")
    parser.add_argument("--players", type=int, default=None, help="Override the preset's default player count")
    parser.add_argument("--encoder", choices=["basic", "enhanced"], default=_tcfg.get("encoder", "enhanced"))
    parser.add_argument("--map-type", default=_map_cfg.get("type", "earthlike"), choices=["earthlike", "basic"])
    parser.add_argument("--max-turns", type=int, default=_tcfg.get("max_turns", 250))
    parser.add_argument("--batch-size", type=int, default=_tcfg.get("batch_size", 32))
    parser.add_argument("--fully-conv", action="store_true", help="Use FullyConvNetwork (map-size independent)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--cprofile-top", type=int, default=30, help="Top-N rows in the cProfile tables")
    parser.add_argument("--mapgen-calls", type=int, default=20, help="Calls averaged in the mapgen micro-benchmark")
    parser.add_argument("--mapgen-sizes", nargs="+", default=["duel", "standard"], choices=_SIZE_CHOICES)
    parser.add_argument("--no-cprofile", action="store_true", help="Skip the cProfile cross-check pass")
    parser.add_argument("--no-mapgen-bench", action="store_true", help="Skip the mapgen micro-benchmark")
    args = parser.parse_args()

    print("=" * 72)
    print("Civulator training-time profiling harness (issue #34)")
    print("=" * 72)
    n_preview, m_preview, players_preview = resolve_size_and_players(size=args.size, num_players=args.players)
    print(
        f"config: size={args.size} ({m_preview}x{n_preview}) players={players_preview} "
        f"encoder={args.encoder} map_type={args.map_type} max_turns={args.max_turns} "
        f"batch_size={args.batch_size} fully_conv={args.fully_conv} episodes={args.episodes} seed={args.seed}"
    )

    report_gpu_info()

    workdir = tempfile.mkdtemp(prefix="civulator_profile_")
    try:
        # --- (a) instrumented buckets ---
        timer, elapsed, setup_seconds, win_counts, win_history, dims = run_instrumented(args, workdir)
        print_share_table(timer, elapsed, setup_seconds)

        # --- (b) cProfile cross-check ---
        engine_rows = []
        if not args.no_cprofile:
            profiler, cprofile_elapsed = run_cprofile(args, workdir)
            engine_rows, engine_tt, total_tt_all = extract_stats(profiler, True, args.cprofile_top)
            global_rows, _, _ = extract_stats(profiler, False, 15)
            print_cprofile_table(
                engine_rows, f"(b) cProfile: engine-side (civulator/), top {len(engine_rows)} by tottime"
            )
            print_cprofile_table(
                global_rows, "(b) cProfile: global (unrestricted), top 15 by tottime -- torch/numpy context"
            )
            engine_pct = 100.0 * engine_tt / total_tt_all if total_tt_all > 0 else 0.0
            print(
                f"\nengine-side (civulator/) share of cProfile self-time: {engine_pct:.1f}% "
                f"({engine_tt:.2f}s of {total_tt_all:.2f}s total profiled self-time)"
            )
            print(
                f"cProfile wall-clock: {cprofile_elapsed:.2f}s vs instrumented {elapsed:.2f}s "
                f"({cprofile_elapsed / elapsed:.2f}x -- expected: cProfile's per-call overhead "
                "inflates high-call-count Python regions, and it does not force CUDA sync)"
            )
            print_top3(engine_rows)

        # --- deliverable 3: mapgen micro-benchmark ---
        mapgen_results = {}
        if not args.no_mapgen_bench:
            mapgen_results = mapgen_microbenchmark(args.mapgen_sizes, args.mapgen_calls, args.map_type)

        # --- extrapolation + verdict ---
        extrap = extrapolate_and_verdict(timer, elapsed, args.episodes, mapgen_results, args.size)
        print_verdict(extrap)

        print("\n=== Done ===")
        print(f"Episodes run: {args.episodes}  Win counts: {win_counts}")

    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
