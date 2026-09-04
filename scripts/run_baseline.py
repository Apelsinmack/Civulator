"""Fixed, reproducible launcher for the #39 baseline run (GitHub issue #39).

The #39 experiment configuration AS CODE. Deliberately does NOT read most
of its configuration from live config.toml -- config.toml is mutable and
this run's whole point is to be the fixed control arm every follower
experiment (#40's terrain-aware encoder, and others after it) is measured
against ("Same worlds, same seeds, same budget" -- issue #39's own
sequencing comment). Two knobs that are genuinely shared, rarely-touched,
and NOT part of what any of these experiments varies are still read from
config.toml (max_turns, batch_size, learning_rate, gamma) -- see "Pinned
configuration" below for exactly which is which.

Pinned configuration (NOT sourced from config.toml):
    size / players: the "duel" preset -- [map.sizes.duel] = 24x12, 2
        players (its own default_players, not overridden here either --
        this file only pins the PRESET NAME).
    map_type:   "earthlike"
    fully_conv: True (FullyConvNetwork -- map-size independent, so it
        accepts whichever encoder's channel count without modification)
    seed_base:  390000 -- THE #39 episode-seed schedule. See
        civulator.training.trainer.train_agents's `seed_base` parameter
        and `_seeded_reset`'s docstring for the exact running-cursor
        scheme and its determinism argument. Every follower experiment
        that must train on literally the same world sequence reuses this
        exact constant.

Encoder (issue #40 wiring -- this is the one knob this script is DESIGNED
to vary between comparison runs): `--encoder`, default from config.toml
[training].encoder (repo default "enhanced" -- the #39 baseline, 25
channels, fog_of_war=false). Selected via `civulator.agents.get_encoder`
(the encoder registry -- this script never instantiates an encoder class
directly), so `--encoder terrain_aware` runs the SAME seed schedule against
the 52-channel TerrainAwareStateEncoder (docs/terrain_encoder_design.md,
#40) for a controlled comparison. Network depth and output filenames
(`duel_{channels}ch_...`) follow the chosen encoder automatically.

Agent architecture note (a judgment call -- issue #39's text pins the
world/seed config but says nothing about network width or per-player
hyperparameters): both players get IDENTICAL hyperparameters,
read from config.toml's [training] section (learning_rate, gamma; epsilon
schedule and target_update_freq come from there automatically inside
DQNAgent's own constructor). This is a deliberate departure from the
asymmetric 8-slot AGENT_CONFIGS tournament table scripts/train.py and
scripts/profile_training.py use: issue #39's comment says the finished
baseline gets "frozen into the opponent pool" as a single reference
agent, which should not itself be two differently-tuned agents. conv_
channels=(16, 32) ("medium") is this script's own pinned choice -- config.
toml has no key for it; it matches weights/trained/manifest.md's most
fully-documented prior entry (medium_16x32_1000ep.pth).

Output layout:
    --tag baseline (the default -- the real run): writes into the repo's
        real weights/ (per-episode checkpoints, trainer's own existing,
        already-gitignored behavior), weights/trained/duel_{channels}ch_
        {episodes}ep.pth (this script's own final combined save, WITH
        manifest, via civulator.meta.save_weights -- {channels} is the
        chosen encoder's channel count, e.g. 25 for the #39 baseline or 52
        for --encoder terrain_aware), and stats/ (win-history + build-order
        artifacts, trainer's own existing behavior; also this script's own
        JSON run summary) -- the actual scientific record.
    any other --tag (e.g. "smoke"): every one of those paths is instead
        rooted under runs/{tag}/ (mirrored weights/, weights/trained/,
        stats/ subtree) so a smoke test can never pollute the real
        weights/trained/ or stats/. --outdir overrides this default
        explicitly either way, for both the default tag and any other.

Variant runs (issue #46 wiring): `--variant rw2` names a follower run that
varies something OTHER than the encoder (e.g. the reward table) --
weights/stats filenames gain the variant token (duel_25ch_rw2_1000ep.pth)
so a same-encoder follower can never clobber the baseline artifact. The
run summary also records the live [training.rewards] table, since that is
exactly what such a variant varies (the weights manifest embeds the full
config already).

Mid-training checkpoints (`--checkpoint-every`, default 100): periodic
combined snapshots under weights/checkpoints/ (gitignored side of
weights/), so episodes-to-50%-vs-baseline is computable after the fact --
the #40 eval's secondary metric that its run couldn't provide.

Usage:
    python scripts/run_baseline.py                          # real 1000-episode run (25ch)
    python scripts/run_baseline.py --encoder terrain_aware   # #40 comparison run (52ch)
    python scripts/run_baseline.py --variant rw2             # #46 reward-v2 follower run
    python scripts/run_baseline.py --episodes 3 --tag smoke  # fast smoke test
    python scripts/run_baseline.py --outdir D:/scratch/run1  # explicit output root
"""

import argparse
import contextlib
import json
import os
import sys
import time

# Add project root to path (same pattern as every other scripts/*.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from civulator.config import CFG
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.game.environment import REWARDS
from civulator.agents import DQNAgent, BuildAgent, ReplayMemory, get_encoder
from civulator.training import train_agents
from civulator.meta import load_weights, save_weights

# --- The #39 pinned configuration (see module docstring) -------------------
SIZE_PRESET = "duel"
MAP_TYPE = "earthlike"
FULLY_CONV = True
CONV_CHANNELS = (16, 32)
SEED_BASE = 390000          # THE #39 schedule -- do not change per-run
DEFAULT_EPISODES = 1000
DEFAULT_TAG = "baseline"
PROGRESS_REPORT_EVERY = 100

_tcfg = CFG.get("training", {})
# Encoder default sourced from config.toml [training].encoder (issue #40
# wiring) -- everything else above stays pinned in code, see module
# docstring. Repo default is "enhanced" (the #39 baseline, unchanged).
DEFAULT_ENCODER = _tcfg.get("encoder", "enhanced")


@contextlib.contextmanager
def _chdir(path):
    """Redirect train_agents()'s relative weights/ and stats/ writes (and
    this script's own weights/trained/ save) into `path` for the duration
    of the `with` block -- same pattern scripts/profile_training.py uses
    to keep a throwaway run out of the repo's real scientific record.
    """
    os.makedirs(path, exist_ok=True)
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _format_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def make_progress_callback(report_every=PROGRESS_REPORT_EVERY,
                           checkpoint_every=0, checkpoint_saver=None):
    """episode_callback for train_agents (civulator/training/trainer.py):
    prints one elapsed/ETA line every `report_every` episodes, plus
    always on the final episode. train_agents does not compute timing
    itself (see its docstring) -- this closure keeps its own clock.

    checkpoint_saver(completed_episodes), when given, is additionally
    called every `checkpoint_every` episodes (never on the final episode
    -- the run's own final save covers that) for mid-training snapshots.
    """
    start = time.perf_counter()

    def callback(episode, num_episodes, win_counts):
        completed = episode + 1
        if (checkpoint_saver is not None and checkpoint_every
                and completed % checkpoint_every == 0
                and completed != num_episodes):
            checkpoint_saver(completed)
        if completed % report_every != 0 and completed != num_episodes:
            return
        elapsed = time.perf_counter() - start
        rate = elapsed / completed
        eta = rate * (num_episodes - completed)
        print(
            f"[progress] episode {completed}/{num_episodes} "
            f"({100.0 * completed / num_episodes:5.1f}%)  "
            f"elapsed={_format_hms(elapsed)}  "
            f"avg={rate:.2f}s/ep  "
            f"ETA={_format_hms(eta)}  "
            f"win_counts={dict(win_counts)}"
        )

    return callback


def build_training_objects(n, m, num_players, learning_rate, gamma, encoder,
                           conv_channels=CONV_CHANNELS):
    """Both players get IDENTICAL hyperparameters -- see module docstring
    'Agent architecture note'. Mirrors DQNAgent/BuildAgent construction in
    scripts/train.py and scripts/profile_training.py, minus their
    per-player AGENT_CONFIGS asymmetry.

    `encoder` is a registry name (civulator.agents.get_encoder) -- this
    script never instantiates an encoder class directly (issue #40 wiring).
    FullyConvNetwork is channel-count agnostic, so `d` alone is enough to
    make DQNAgent/BuildAgent match whichever encoder was selected.
    """
    d = get_encoder(encoder).get_depth(num_players)

    env = GameEnvironment(n, m, num_players, map_type=MAP_TYPE)

    agents = []
    build_agents = []
    for i in range(num_players):
        agent = DQNAgent(
            n, m, d, ReplayMemory(10000), gamma=gamma, learning_rate=learning_rate,
            encoder=encoder, fully_conv=FULLY_CONV, conv_channels=conv_channels,
        )
        agent.config_name = f"Baseline-P{i + 1}"
        agents.append(agent)
        build_agents.append(BuildAgent(n, m, d, learning_rate=learning_rate))

    return env, agents, build_agents, d


def load_resume_weights(agents, build_agents, path):
    """Continue training from an earlier run's combined payload.

    Loads combat and build networks (and their optimizer states) per seat
    from a `save_final_weights` artifact — so "another 1000 episodes on top
    of the last run" is one flag rather than a new script.

    What is deliberately NOT restored: the epsilon schedule position
    (`DQNAgent.episode_count`) and the replay memory. A continuation
    therefore re-runs the epsilon decay from the start, which for a
    `[training] epsilon_decay_episodes` of 800 means the resumed run
    explores hard again before settling. That is a real experimental
    choice, not an oversight — say so in the run's manifest row, and pass
    a smaller `epsilon_start` in config if a pure exploitation continuation
    is wanted instead.
    """
    payload, manifest = load_weights(path, map_location=agents[0].device)
    for entry in payload["agents"]:
        agent = agents[entry["player_index"]]
        agent.network.load_state_dict(entry["model_state_dict"])
        agent.target_network.load_state_dict(entry["model_state_dict"])
        if "optimizer_state_dict" in entry:
            agent.optimizer.load_state_dict(entry["optimizer_state_dict"])
    for entry in payload.get("build_agents", []):
        build_agent = build_agents[entry["player_index"]]
        build_agent.network.load_state_dict(entry["model_state_dict"])
        if "optimizer_state_dict" in entry:
            build_agent.optimizer.load_state_dict(entry["optimizer_state_dict"])
    version = manifest["game_version"] if manifest else "pre-manifest"
    print(f"[resume] loaded {len(payload['agents'])} combat + "
          f"{len(payload.get('build_agents', []))} build networks from {path} "
          f"(game_version {version}); epsilon schedule and replay memory start fresh")
    return manifest


def save_final_weights(agents, build_agents, path):
    """The run's one combined, manifest-carrying artifact (civulator.meta.
    save_weights already embeds build_manifest() -- game_version,
    git_commit, config, date). Both players' combat AND build networks
    are bundled into a single file (task's own naming example is
    singular: duel_25ch_1000ep.pth) so 'the baseline' -- issue #39: to be
    'frozen into the opponent pool' as one reference -- reloads as one
    coherent artifact rather than scattered per-agent files needing
    manual pairing.

    Payload shape mirrors trainer._save_checkpoints's existing per-agent
    {"model_state_dict", "optimizer_state_dict"} pair, just listed per
    player instead of one file per player.
    """
    payload = {
        "agents": [
            {
                "player_index": i,
                "config_name": getattr(agent, "config_name", None),
                "model_state_dict": agent.network.state_dict(),
                "optimizer_state_dict": agent.optimizer.state_dict(),
            }
            for i, agent in enumerate(agents)
        ],
        "build_agents": [
            {
                "player_index": i,
                "model_state_dict": ba.network.state_dict(),
                "optimizer_state_dict": ba.optimizer.state_dict(),
            }
            for i, ba in enumerate(build_agents)
        ],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_weights(payload, path)


def main(episodes, tag, outdir, encoder=DEFAULT_ENCODER, variant=None,
         checkpoint_every=100, conv_channels=CONV_CHANNELS, resume=None):
    conv_channels = tuple(conv_channels)
    n, m, num_players = resolve_size_and_players(size=SIZE_PRESET)
    max_turns = _tcfg.get("max_turns", 250)
    batch_size = _tcfg.get("batch_size", 32)
    learning_rate = _tcfg.get("learning_rate", 0.001)
    gamma = _tcfg.get("gamma", 0.9)

    # Channel count drives both the output filename and (inside
    # build_training_objects) the network depth -- get_encoder() is the one
    # registry both go through (issue #40 wiring), never a hard-instantiated
    # encoder class.
    d = get_encoder(encoder).get_depth(num_players)

    if outdir is None:
        outdir = PROJECT_ROOT if tag == DEFAULT_TAG else os.path.join(PROJECT_ROOT, "runs", tag)

    suffix = "" if tag == DEFAULT_TAG else f"_{tag}"
    variant_token = f"{variant}_" if variant else ""
    weights_filename = f"duel_{d}ch_{variant_token}{episodes}ep{suffix}.pth"

    print("=" * 72)
    print("Civulator #39 baseline launcher (issue #39)")
    print("=" * 72)
    print(f"tag={tag!r}  variant={variant!r}  outdir={outdir}")
    print(f"rewards={REWARDS}  (live [training.rewards] -- also pinned in the "
          f"run summary and the weights manifest)")
    print(f"map: size={SIZE_PRESET} ({m}x{n}) players={num_players} map_type={MAP_TYPE}")
    print(f"encoder={encoder} ({d}ch) fully_conv={FULLY_CONV} conv_channels={conv_channels}")
    print(f"episodes={episodes} max_turns={max_turns} batch_size={batch_size}")
    print(f"learning_rate={learning_rate} gamma={gamma}")
    print(f"seed_base={SEED_BASE}  (episode-indexed seed schedule, issue #39 -- "
          f"see train_agents/_seeded_reset docstrings for the exact scheme)")
    print(f"final weights -> weights/trained/{weights_filename}  (relative to outdir)")
    print("=" * 72)

    with _chdir(outdir):
        env, agents, build_agents, d = build_training_objects(
            n, m, num_players, learning_rate, gamma, encoder, conv_channels
        )
        resume_manifest = None
        if resume:
            # Path is resolved against the ORIGINAL cwd, not the tag's
            # output root that _chdir moved us into.
            resume_path = resume if os.path.isabs(resume) else os.path.join(PROJECT_ROOT, resume)
            resume_manifest = load_resume_weights(agents, build_agents, resume_path)
        env.max_turns = max_turns

        def checkpoint_saver(completed):
            ck_path = os.path.join(
                "weights", "checkpoints",
                weights_filename.replace(".pth", f"_ck{completed}.pth"),
            )
            save_final_weights(agents, build_agents, ck_path)
            print(f"[checkpoint] episode {completed} -> {ck_path}")

        t0 = time.perf_counter()
        skipped_seeds = []  # persisted below — console warnings are not a record (#44 lesson)
        truncated_episodes = []  # step-limit breaks — same reason (#51 lesson)
        win_counts, win_history = train_agents(
            env, agents, num_episodes=episodes, batch_size=batch_size, debug=False,
            build_agents=build_agents, seed_base=SEED_BASE,
            episode_callback=make_progress_callback(
                checkpoint_every=checkpoint_every,
                checkpoint_saver=checkpoint_saver,
            ),
            skipped_seeds=skipped_seeds,
            truncated_episodes=truncated_episodes,
        )
        elapsed = time.perf_counter() - t0

        weights_path = os.path.join("weights", "trained", weights_filename)
        save_final_weights(agents, build_agents, weights_path)

        stats_path = os.path.join(
            "stats",
            f"baseline_{tag}_{variant_token}{episodes}ep_{int(time.time())}.json",
        )
        os.makedirs("stats", exist_ok=True)
        summary = {
            "issue": 39,
            "tag": tag,
            "variant": variant,
            "rewards": dict(REWARDS),
            "episodes": episodes,
            "seed_base": SEED_BASE,
            "size_preset": SIZE_PRESET,
            "map_dims": {"rows": n, "cols": m},
            "num_players": num_players,
            "map_type": MAP_TYPE,
            "encoder": encoder,
            "encoder_channels": d,
            "fully_conv": FULLY_CONV,
            "conv_channels": list(conv_channels),
            "max_turns": max_turns,
            "batch_size": batch_size,
            "learning_rate": learning_rate,
            "gamma": gamma,
            "resumed_from": resume,
            "skipped_schedule_seeds": skipped_seeds,
            # Episodes cut off by the step-limit guard (#51): their entry in
            # win_history is an artifact of where the loop was cut, not a
            # result. Empty is the healthy case.
            "truncated_episodes": truncated_episodes,
            "win_counts": {str(k): v for k, v in win_counts.items()},
            "win_history": [int(w) for w in win_history],
            "elapsed_seconds": elapsed,
            "seconds_per_episode": elapsed / episodes if episodes else 0.0,
            "weights_path": weights_path,
        }
        with open(stats_path, "w") as f:
            json.dump(summary, f, indent=2)

    print("\n" + "=" * 72)
    print(f"Done: {episodes} episodes in {_format_hms(elapsed)} "
          f"({elapsed / episodes:.2f}s/episode)")
    print(f"Win counts: {dict(win_counts)}")
    print(f"Final weights: {os.path.join(outdir, weights_path)}")
    print(f"Run summary:   {os.path.join(outdir, stats_path)}")
    print("=" * 72)

    return win_counts, win_history


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Launch the #39 baseline (or a smoke test of it) — issue #39."
    )
    parser.add_argument("--episodes", type=int, default=DEFAULT_EPISODES,
                        help=f"Number of episodes (default: {DEFAULT_EPISODES}, the real baseline). "
                             "Lower for a smoke test.")
    parser.add_argument("--tag", type=str, default=DEFAULT_TAG,
                        help=f"Run tag (default: {DEFAULT_TAG!r} = the real run, writing into the "
                             "repo's actual weights/trained/ and stats/). Any other tag writes "
                             "under runs/{tag}/ instead, unless --outdir overrides it.")
    parser.add_argument("--outdir", type=str, default=None,
                        help="Explicit output root (weights/, weights/trained/, stats/ are created "
                             "under it). Overrides the --tag-based default either way.")
    parser.add_argument("--encoder", type=str, default=DEFAULT_ENCODER,
                        choices=["basic", "enhanced", "terrain_aware", "city_distance", "full", "settle"],
                        help=f"State encoder, selected via civulator.agents.get_encoder "
                             f"(default: {DEFAULT_ENCODER!r}, from config.toml [training].encoder). "
                             "'terrain_aware' (52ch/54ch fog, issue #40) runs the SAME seed schedule "
                             "against the terrain-aware encoder for a controlled comparison against "
                             "the #39 'enhanced' (25ch) baseline.")
    parser.add_argument("--variant", type=str, default=None,
                        help="Name token for a follower run varying something other than the "
                             "encoder (e.g. 'rw2' for the #46 reward table): filenames become "
                             "duel_{ch}ch_{variant}_{episodes}ep.* so a same-encoder follower "
                             "never clobbers the baseline artifact.")
    parser.add_argument("--checkpoint-every", type=int, default=100,
                        help="Save a combined mid-training snapshot under weights/checkpoints/ "
                             "every N episodes (default 100; 0 disables) -- enables the "
                             "episodes-to-50%%-vs-baseline secondary metric.")
    parser.add_argument("--conv-channels", type=str, default=None,
                        help="Comma-separated per-layer channel counts for the FullyConv "
                             "backbone (issue #48 capacity ladder), e.g. '32,64,64'. "
                             f"Default: the pinned baseline {CONV_CHANNELS}. Deeper/wider "
                             "runs should also pass --variant (encoder channel count alone "
                             "no longer distinguishes the artifact name).")
    parser.add_argument("--resume", type=str, default=None,
                        help="Continue training from a combined weights payload "
                             "(e.g. weights/trained/duel_53ch_net128x6_1000ep.pth). "
                             "Encoder and --conv-channels must match the payload. "
                             "The epsilon schedule and replay memory start fresh — "
                             "see load_resume_weights' docstring.")
    args = parser.parse_args()

    conv_channels = (
        tuple(int(c) for c in args.conv_channels.split(","))
        if args.conv_channels else CONV_CHANNELS
    )
    main(episodes=args.episodes, tag=args.tag, outdir=args.outdir, encoder=args.encoder,
         variant=args.variant, checkpoint_every=args.checkpoint_every,
         conv_channels=conv_channels, resume=args.resume)
