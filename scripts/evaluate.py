"""Head-to-head evaluation harness (PROTOCOL v1, ratification pending) — issue #40.

Successor to `scripts/tournament.py`'s `play_match` (legacy pre-0.6: 4x8 map,
no seeded worlds, no build agents). This script mirrors the REAL game loop —
`civulator.training.trainer.train_agents` — as closely as possible, minus
everything that only exists to serve LEARNING (replay-memory pushes,
`optimize()`, epsilon decay). It never reinvents turn/action/build mechanics;
see `_play_game` below for exactly what was dropped and why.

Usage:
    python scripts/evaluate.py --a weights/trained/duel_52ch_1000ep.pth \\
        --a-encoder terrain_aware \\
        --b weights/trained/duel_25ch_1000ep.pth --b-encoder enhanced

PROTOCOL v1 (locked for the #40 run; ratification — i.e. promotion to a
permanent, versioned contract other experiments can cite — is still
pending):

- CLI: --a/--a-encoder, --b/--b-encoder (weights path + encoder registry
  name, via `civulator.agents.get_encoder` — never a hard-instantiated
  encoder class), --games (default 200), --seed-base (default 990000),
  --epsilon (default 0.05).
- World: the "duel" size preset, `map_type="earthlike"`, `max_turns` read
  from config.toml [training] (same knob `run_baseline.py` pins its runs
  to) — i.e. THE SAME max_turns the baseline/follower were trained under.
- Episode-seed schedule: reuses `civulator.training.trainer._seeded_reset`
  verbatim (running-cursor scheme, skip-on-StartPlacementError) rather than
  re-implementing it — see that function's own docstring for the exact
  scheme and its determinism argument.
- Side balance: game i seats A on player 0 when i is even, player 1 when i
  is odd (B takes the other seat). Games are drawn in WORLD PAIRS: game 2k
  and 2k+1 replay the identical world (same seed, drawn once per pair via
  the schedule) with sides swapped, so every world is judged from both
  seats — the standard control for first-move / seating advantage.
- Each side loads BOTH of its trained seats (`payload["agents"][0]` and
  `[1]`, one DQNAgent each, likewise `payload["build_agents"]`) from its own
  weights file and encoder, and always plays with the seat-matched network
  for whichever player index it currently occupies (never seat 0's network
  playing seat 1, even mid-run) — this is "each side's own trained policy",
  not "seat 0's policy" specifically.
- Both networks in `.eval()` mode, `torch.no_grad()`, epsilon FIXED at
  --epsilon for the whole run (no decay, no `agent.get_epsilon()`), no
  `store_transition`/`optimize()` calls anywhere.
- Output: per-side win/loss/draw totals, the same split BY WHICH SEAT A
  HELD (first-move-advantage check), mean/min/max game length in turns, and
  a JSON summary (`stats/eval_<Atag>_vs_<Btag>_<timestamp>.json`) with the
  full per-game result list (seed, seats, winner, turns, truncated) plus both
  weight files' manifest key fields (game_version, git_commit, date).
- Truncation (issue #51): a game stopped by the STEP_LIMIT guard instead of
  ending on its own is NOT a result. It is flagged per game as
  `truncated: true` and counted in the summary's `truncated_games`. Such
  games are also in `totals["draws"]` — determine_winner has no other verdict
  for a game cut off mid-play — so any reading of the run must subtract them
  first. Summaries written before #51 have neither field; treat a missing
  `truncated` as false and consult the run log's `Step limit exceeded` lines.

Design decisions NOT nailed down by the task spec (documented here since
this is the "as-code" record of protocol v1):

- BuildAgent exploration: `train_agents` hardcodes epsilon=0.3 for build
  decisions (a training-exploration constant, not a policy choice). This
  harness instead reuses the SAME --epsilon for build decisions as for
  combat action selection — an evaluation run wants minimal, fixed
  exploration everywhere, not the training schedule's epsilon.
- `BuildAgent.select_build` unconditionally appends to `self.pending` (a
  training bookkeeping list `complete_pending` would normally drain via a
  memory push). Since this harness never calls `complete_pending`, `_play_game`
  clears `.pending` after each turn-boundary's build decisions itself —
  otherwise it would grow for the life of the whole run (up to 200 games x
  ~250 turns), a slow leak with no compensating benefit here.
- State recomputation: `train_agents` carries a `next_state` variable across
  loop iterations purely so it can hand training a correct (state, action,
  reward, next_state) tuple. Build decisions never change anything a combat
  encoder reads (they only set `City.current_production` metadata), so
  recomputing `current_agent.build_state_tensor(env)` fresh right before
  each action selection is exactly equivalent output — simpler, without the
  training-only carryover machinery.
- Per-game RNG: besides the world (seeded via `env.rng`, a `PortableRNG`
  fully independent of Python's global `random`/`numpy.random`), the only
  other randomness is DQNAgent/BuildAgent epsilon rolls and tie-break
  fallbacks, which read the global `random` module. Each game reseeds
  `random`/`numpy.random`/`torch` from `seed_base + game_index` before
  playing, so a run is reproducible call-to-call regardless of what ran
  immediately before it in the same process (required by the smoke test).
"""

import argparse
import json
import os
import random
import sys
import time

import numpy as np
import torch

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from civulator.agents import DQNAgent, BuildAgent, ReplayMemory, get_encoder
from civulator.agents.action_space import decode_action, end_turn_index
from civulator.agents.networks import conv_channels_from_state_dict
from civulator.agents.build_agent import BUILD_OPTIONS
from civulator.config import CFG
from civulator.game import GameEnvironment, resolve_size_and_players
from civulator.game.city import City
from civulator.game.unit import NUM_UNIT_SLOTS
from civulator.meta import load_weights
from civulator.training.trainer import _seeded_reset, determine_winner

# --- Pinned world/architecture config (protocol v1) -------------------------
# Same pins run_baseline.py trains under (see that script's module docstring
# "Pinned configuration") — an evaluation run must use the SAME world/network
# shape the compared weights were trained with, not whatever config.toml
# currently says.
SIZE_PRESET = "duel"
MAP_TYPE = "earthlike"
FULLY_CONV = True
# conv_channels is NOT pinned here: each side's architecture is inferred
# from its checkpoint's weight shapes (conv_channels_from_state_dict), so
# arbitrary-depth #48 capacity-ladder runs evaluate with no extra flags.

DEFAULT_GAMES = 200
DEFAULT_SEED_BASE = 990000
DEFAULT_EPSILON = 0.05

# Safety net for a game that will not end on its own. Reaching it is a bug
# (issue #51), not a legitimate outcome, so a game that hits it is flagged
# `truncated` rather than quietly handed to determine_winner. A module-level
# constant so tests can lower it; mirrors trainer.STEP_LIMIT.
STEP_LIMIT = 10000

_tcfg = CFG.get("training", {})
DEFAULT_MAX_TURNS = _tcfg.get("max_turns", 250)

_ENCODER_CHOICES = ["basic", "enhanced", "terrain_aware", "city_distance", "full"]


def _load_side(weights_path, encoder_name, n, m, num_players, device):
    """Load one side's payload (`{"agents": [...], "build_agents": [...]}`,
    `civulator.meta.save_weights`/`run_baseline.py`'s shape) into one
    DQNAgent + BuildAgent PER SEAT (player_index), keyed by seat.

    Returns:
        (agents_by_seat, build_agents_by_seat, manifest)
    """
    payload, manifest = load_weights(weights_path, map_location=device)
    d = get_encoder(encoder_name).get_depth(num_players)

    agents_by_seat = {}
    side_conv_channels = None
    for entry in payload["agents"]:
        seat = entry["player_index"]
        # Architecture comes from the checkpoint itself (issue #48 capacity
        # ladder): conv_channels is inferred from the saved weight shapes,
        # so deeper/wider runs evaluate without any extra CLI flags.
        entry_channels = conv_channels_from_state_dict(entry["model_state_dict"])
        if side_conv_channels is None:
            side_conv_channels = entry_channels
        elif side_conv_channels != entry_channels:
            raise ValueError(
                f"{weights_path!r}: seats disagree on conv_channels "
                f"({side_conv_channels} vs {entry_channels})"
            )
        agent = DQNAgent(
            n, m, d, ReplayMemory(1), encoder=encoder_name,
            fully_conv=FULLY_CONV, conv_channels=entry_channels,
        )
        agent.network.load_state_dict(entry["model_state_dict"])
        agent.network.eval()
        agents_by_seat[seat] = agent

    build_agents_by_seat = {}
    for entry in payload["build_agents"]:
        seat = entry["player_index"]
        build_agent = BuildAgent(n, m, d)
        build_agent.network.load_state_dict(entry["model_state_dict"])
        build_agent.network.eval()
        build_agents_by_seat[seat] = build_agent

    missing = set(range(num_players)) - set(agents_by_seat)
    if missing:
        raise ValueError(
            f"{weights_path!r}: payload is missing combat agent(s) for seat(s) "
            f"{sorted(missing)} (num_players={num_players})"
        )
    missing = set(range(num_players)) - set(build_agents_by_seat)
    if missing:
        raise ValueError(
            f"{weights_path!r}: payload is missing build agent(s) for seat(s) "
            f"{sorted(missing)} (num_players={num_players})"
        )

    return agents_by_seat, build_agents_by_seat, manifest, side_conv_channels


def _manifest_summary(manifest):
    """The 'key fields' (task spec) of a save_weights manifest — never the
    full embedded config.toml snapshot."""
    if not manifest:
        return None
    return {k: manifest[k] for k in ("game_version", "git_commit", "date") if k in manifest}


def _play_game(env, agents_by_seat, build_agents_by_seat, epsilon):
    """Play one episode to completion on `env` (already reset onto the
    world this game should use). Mirrors `civulator.training.trainer.
    train_agents`'s per-episode while-loop exactly for turn/action/build
    mechanics — see this module's docstring for exactly what was dropped
    (learning-only bookkeeping) and why.

    Args:
        agents_by_seat: {player_index: DQNAgent} for THIS game's seating.
        build_agents_by_seat: {player_index: BuildAgent} for this seating.
        epsilon: fixed exploration rate for BOTH combat action selection
            and build decisions (see module docstring's design-decisions
            section).

    Returns:
        (winner_seat, turns, builds_by_seat, combat_by_seat, truncated):
        winner_seat is a player_index or None (draw, `determine_winner`'s
        own contract); turns is `env.turn_counter` when the episode ended;
        builds_by_seat maps each player_index to {build_option: count} for
        this game (what each side actually produced -- surfaced in the run
        summary's build_distribution); combat_by_seat is the engine's
        per-player episode counters; `truncated` is True when the game hit
        the step-limit guard instead of ending on its own.

        Truncation must be reported, never left implicit (issue #51): a
        livelocked game breaks out of the loop with both players alive and
        below the turn cap, so `determine_winner` returns None and the game
        is indistinguishable from a genuine draw in the run record. 50 of
        200 games in one #48 evaluation were such phantom draws.
    """
    end_turn_idx = end_turn_index(env.n, env.m)
    last_player_index = -1
    done = False
    step_counter = 0
    truncated = False
    builds_by_seat = {seat: {} for seat in agents_by_seat}

    while not done:
        step_counter += 1
        if step_counter > STEP_LIMIT:
            print("WARNING: Step limit exceeded, breaking loop")
            truncated = True
            break

        current_player_index = env.current_player.player_index
        current_agent = agents_by_seat[current_player_index]

        # --- Build decisions at turn boundary (trainer.py's own condition) ---
        if current_player_index != last_player_index:
            build_agent = build_agents_by_seat[current_player_index]
            combat_state = current_agent.build_state_tensor(env)

            for city in env.current_player.cities:
                if city.current_production is None:
                    action_idx = build_agent.select_build(
                        combat_state, city, env, epsilon=epsilon
                    )
                    option = BUILD_OPTIONS[action_idx]
                    counts = builds_by_seat[current_player_index]
                    counts[option] = counts.get(option, 0) + 1
                    if option in City.BUILDING_COSTS:
                        city.produce_building(option)
                    else:
                        city.produce_unit(option)

            # No training here -- discard what select_build queued for
            # complete_pending() rather than let it grow all run (see
            # module docstring).
            build_agent.pending = []
            last_player_index = current_player_index

        state = current_agent.build_state_tensor(env)
        selected_pos, move_pos = current_agent.select_action(
            state, epsilon=epsilon, game_env=env
        )

        if selected_pos == end_turn_idx:
            env.current_player.end_turn()
            env.next_turn()
            done = env.done
        else:
            action_matrix = decode_action(selected_pos, move_pos, env.n, env.m)
            try:
                _, _reward, done = env.step(action_matrix)
            except AttributeError as e:
                print(f"AttributeError during step: {e}")
                done = env.done

    winner = determine_winner(env)
    # Snapshot the engine's per-player episode counters (kills, losses,
    # damage, cities founded/captured, civilians captured) for aggregation.
    combat_by_seat = {seat: dict(env.episode_stats[seat]) for seat in agents_by_seat}
    return winner, env.turn_counter, builds_by_seat, combat_by_seat, truncated


def run_evaluation(a_weights, a_encoder, b_weights, b_encoder,
                    games=DEFAULT_GAMES, seed_base=DEFAULT_SEED_BASE,
                    epsilon=DEFAULT_EPSILON, max_turns=None,
                    size_preset=SIZE_PRESET, map_type=MAP_TYPE, verbose=True):
    """Run PROTOCOL v1 head-to-head evaluation. Pure function — no file I/O
    (the CLI `main()` below handles writing the JSON summary) — so tests can
    call it directly against tiny settings.

    Args:
        max_turns: override for `[training] max_turns` (config.toml
            default) — the smoke test shrinks this for speed.
        verbose: per-game progress line to stdout.

    Returns:
        dict: the JSON-serializable run summary (see module docstring
        "Output").
    """
    if max_turns is None:
        max_turns = DEFAULT_MAX_TURNS

    n, m, num_players = resolve_size_and_players(size=size_preset)
    if num_players != 2:
        raise ValueError(
            f"evaluate.py protocol v1 is a head-to-head (2-player) harness; "
            f"size preset {size_preset!r} resolves to {num_players} players"
        )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    a_agents, a_builds, a_manifest, a_channels = _load_side(
        a_weights, a_encoder, n, m, num_players, device)
    b_agents, b_builds, b_manifest, b_channels = _load_side(
        b_weights, b_encoder, n, m, num_players, device)

    env = GameEnvironment(n, m, num_players, map_type=map_type)
    env.max_turns = max_turns

    seed_cursor = seed_base
    pending_seed = None

    totals = {"a_wins": 0, "b_wins": 0, "draws": 0}
    by_a_seat = {
        seat: {"a_wins": 0, "b_wins": 0, "draws": 0, "games": 0}
        for seat in range(num_players)
    }
    games_detail = []
    turns_list = []
    truncated_games = 0
    build_totals = {"a": {}, "b": {}}
    combat_totals = {"a": {}, "b": {}}

    for i in range(games):
        a_seat = 0 if i % 2 == 0 else 1
        b_seat = 1 - a_seat

        # World-pair schedule: draw a new world every even game (advancing
        # the shared cursor via the SAME schedule train_agents uses), reuse
        # it unchanged for the following odd game with sides swapped.
        if i % 2 == 0:
            episode_seed, seed_cursor = _seeded_reset(env, seed_cursor, i, seed_base)
            pending_seed = episode_seed
        else:
            episode_seed = pending_seed
            env.reset(seed=episode_seed)

        # Deterministic per-game agent-side RNG (module docstring's
        # "Per-game RNG" design decision) -- independent of the world seed,
        # which lives entirely in env.rng (PortableRNG).
        game_rng_seed = seed_base + i
        random.seed(game_rng_seed)
        np.random.seed(game_rng_seed)
        torch.manual_seed(game_rng_seed)

        agents_by_seat = {a_seat: a_agents[a_seat], b_seat: b_agents[b_seat]}
        build_agents_by_seat = {a_seat: a_builds[a_seat], b_seat: b_builds[b_seat]}

        with torch.no_grad():
            winner_seat, turns, builds_by_seat, combat_by_seat, truncated = _play_game(
                env, agents_by_seat, build_agents_by_seat, epsilon)

        for side, seat in (("a", a_seat), ("b", b_seat)):
            for option, count in builds_by_seat[seat].items():
                build_totals[side][option] = build_totals[side].get(option, 0) + count
            for stat, value in combat_by_seat[seat].items():
                combat_totals[side][stat] = combat_totals[side].get(stat, 0) + value

        if winner_seat is None:
            outcome = "draw"
            totals["draws"] += 1
            by_a_seat[a_seat]["draws"] += 1
        elif winner_seat == a_seat:
            outcome = "a"
            totals["a_wins"] += 1
            by_a_seat[a_seat]["a_wins"] += 1
        else:
            outcome = "b"
            totals["b_wins"] += 1
            by_a_seat[a_seat]["b_wins"] += 1
        by_a_seat[a_seat]["games"] += 1
        turns_list.append(turns)
        if truncated:
            truncated_games += 1

        # `truncated` is a new field (issue #51); readers of older summaries
        # (scripts/watch.py) must keep working, so nothing else in the entry
        # moved and consumers should treat a missing key as False.
        games_detail.append({
            "game_index": i,
            "seed": episode_seed,
            "a_seat": a_seat,
            "b_seat": b_seat,
            "winner_seat": winner_seat,
            "outcome": outcome,
            "turns": turns,
            "truncated": truncated,
        })

        if verbose:
            print(
                f"[eval] game {i + 1}/{games} seed={episode_seed} "
                f"A@seat{a_seat} outcome={outcome} turns={turns}"
                + (" TRUNCATED" if truncated else "")
            )

    summary = {
        "protocol_version": "v1",
        "games": games,
        "seed_base": seed_base,
        "epsilon": epsilon,
        "size_preset": size_preset,
        "map_dims": {"rows": n, "cols": m},
        "num_players": num_players,
        "map_type": map_type,
        "max_turns": max_turns,
        "a_conv_channels": list(a_channels),
        "b_conv_channels": list(b_channels),
        "fully_conv": FULLY_CONV,
        "a_weights": a_weights,
        "a_encoder": a_encoder,
        "b_weights": b_weights,
        "b_encoder": b_encoder,
        "totals": totals,
        # Games cut off by the step-limit guard rather than ending on their
        # own (issue #51). They are ALSO counted in totals["draws"] —
        # determine_winner has no other verdict for a game stopped mid-play
        # — so a nonzero value here means that many "draws" are not results
        # and the run should be recounted without them.
        "truncated_games": truncated_games,
        "by_a_seat": {str(k): v for k, v in by_a_seat.items()},
        "game_length": {
            "mean_turns": (sum(turns_list) / len(turns_list)) if turns_list else 0.0,
            "min_turns": min(turns_list) if turns_list else 0,
            "max_turns_observed": max(turns_list) if turns_list else 0,
        },
        "build_distribution": {
            side: dict(sorted(counts.items(), key=lambda kv: -kv[1]))
            for side, counts in build_totals.items()
        },
        "combat_stats": combat_totals,
        "games_detail": games_detail,
        "manifest_a": _manifest_summary(a_manifest),
        "manifest_b": _manifest_summary(b_manifest),
    }
    return summary


def _tag_from_path(path):
    return os.path.splitext(os.path.basename(path))[0]


def main():
    parser = argparse.ArgumentParser(
        description="Head-to-head evaluation harness (protocol v1, ratification pending) -- issue #40."
    )
    parser.add_argument("--a", required=True, help="Side A weights file (payload saved by meta.save_weights).")
    parser.add_argument("--a-encoder", required=True, choices=_ENCODER_CHOICES,
                        help="Side A's state encoder (civulator.agents.get_encoder registry name).")
    parser.add_argument("--b", required=True, help="Side B weights file.")
    parser.add_argument("--b-encoder", required=True, choices=_ENCODER_CHOICES,
                        help="Side B's state encoder.")
    parser.add_argument("--games", type=int, default=DEFAULT_GAMES,
                        help=f"Total games (default {DEFAULT_GAMES}; must be even for a clean "
                             "100%% world-pair split, see module docstring).")
    parser.add_argument("--seed-base", type=int, default=DEFAULT_SEED_BASE,
                        help=f"Episode-seed schedule base (default {DEFAULT_SEED_BASE}).")
    parser.add_argument("--epsilon", type=float, default=DEFAULT_EPSILON,
                        help=f"Fixed exploration rate, combat + build (default {DEFAULT_EPSILON}).")
    args = parser.parse_args()

    print("=" * 72)
    print("Civulator head-to-head evaluation (protocol v1, ratification pending) -- issue #40")
    print("=" * 72)
    print(f"A: {args.a}  (encoder={args.a_encoder})")
    print(f"B: {args.b}  (encoder={args.b_encoder})")
    print(f"games={args.games}  seed_base={args.seed_base}  epsilon={args.epsilon}")
    print(f"size_preset={SIZE_PRESET}  map_type={MAP_TYPE}  max_turns={DEFAULT_MAX_TURNS}")
    print("=" * 72)

    t0 = time.perf_counter()
    summary = run_evaluation(
        a_weights=args.a, a_encoder=args.a_encoder,
        b_weights=args.b, b_encoder=args.b_encoder,
        games=args.games, seed_base=args.seed_base, epsilon=args.epsilon,
    )
    elapsed = time.perf_counter() - t0
    summary["elapsed_seconds"] = elapsed

    a_tag = _tag_from_path(args.a)
    b_tag = _tag_from_path(args.b)
    stats_dir = os.path.join(PROJECT_ROOT, "stats")
    os.makedirs(stats_dir, exist_ok=True)
    stats_path = os.path.join(stats_dir, f"eval_{a_tag}_vs_{b_tag}_{int(time.time())}.json")
    with open(stats_path, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 72)
    print(f"Done: {args.games} games in {elapsed:.0f}s ({elapsed / args.games:.2f}s/game)")
    print(f"Totals: {summary['totals']}")
    print(f"By A's seat: {summary['by_a_seat']}")
    print(f"Game length (turns): {summary['game_length']}")
    print(f"Builds A: {summary['build_distribution']['a']}")
    print(f"Builds B: {summary['build_distribution']['b']}")
    print(f"Combat A: {summary['combat_stats']['a']}")
    print(f"Combat B: {summary['combat_stats']['b']}")
    print(f"Summary written to: {stats_path}")
    print("=" * 72)

    return summary


if __name__ == "__main__":
    main()
