"""Matchup-matrix harness (issue #65) -- MEASURE every unit pairing in the
real engine, instead of deriving it from config.toml's constants and the
damage formula.

Why: every balance claim made so far (CHANGELOG v0.6.2, issues #60/#63) is a
DERIVATION -- read the constants, run the Civ6 formula by hand. Project
CLAUDE.md's reporting rule requires a quantitative claim to name a committed
artifact and a sample size; a derivation is neither. This script plays out
real attack exchanges through `GameEnvironment` and records what actually
happens -- which also catches bugs arithmetic cannot: the attack-only
class-bonus bug (#63) would have shown up here as a visibly ASYMMETRIC
matrix (Horseman->Spearman != Spearman->Horseman) well before anyone had to
read the code to find it.

This measures RULES, not agents. `scripts/evaluate.py` measures trained
agents playing full games; this measures the combat rules in isolation, one
attack exchange at a time, with no agent, no policy, and no full episode
anywhere in it. They must never merge -- see the "Rules measurement" row
project CLAUDE.md's canonical-systems table adds for this script.

Scope (agreed with Erik on #65 -- do not widen):

- Headline run (the default, no flags): all 36 ordered pairings of the six
  COMBAT units -- Warrior, Archer, Swordsman, Spearman, Horseman, Catapult
  -- on flat terrain, unfortified, both at full HP. Ordered, because A
  attacking B and B attacking A differ, and that difference is the entire
  point of #60/#63.
- Settler and Worker (combat_strength 0, config.toml [units.*]) are
  EXCLUDED from the matrix: they cannot attack, and attacking one captures
  rather than fights -- a different engine mechanic this harness does not
  model.
- One measurement = one attack exchange: the attacker attacks, the defender
  counterattacks IF the engine's own rules give it one (a ranged attack
  never draws a counter -- see "Why _execute_attack" below). Fight-to-death
  is explicitly out of scope.
- N duels per pairing (--duels, default 200) average out the engine's
  0.8-1.2 damage roll (config.toml [combat] damage_roll_min/max).
- Conditions are opt-in flags, each adding ONE more matrix to the same JSON
  artifact, one variable away from the headline at a time (project
  CLAUDE.md's "one variable at a time" research-method rule, applied to the
  flags themselves): --terrain flat,hills,woods (changes the DEFENDER's
  tile only -- terrain defense bonus is a defending-side stat, see
  `Unit.get_combat_strength`), --fortified (defender at max
  fortification), --damaged (both units start at half HP -- see "Judgment
  calls" below). The default run is flat / unfortified / full HP only, so
  the headline table stays readable.

Engine contract used (go through GameEnvironment only -- never hand-roll
the damage math):

- The real `Unit` subclasses (`WarriorUnit`, `ArcherUnit`, ...) so a ranged
  attacker runs its OWN `attack()` override (the real range + line-of-sight
  check) rather than the base melee path.
- `GameEnvironment._execute_attack(attacker, defender)` -- the exact seam
  project CLAUDE.md's Combat row names ("All damage flows through this
  path") -- runs the real melee adjacency check, the real ranged
  range/LOS check (inside the subclass), `Unit.attack` -> `calculate_damage`
  (the real Civ6 formula and the real seeded roll), and the real
  counterattack branch. Nothing in this file computes a strength or a
  damage number itself.

Why `_execute_attack` directly, not the public `env.step()`:
`env.step()` is the two-click interface a real turn uses, but its
post-attack `_check_game_end()` auto-advances the turn whenever the acting
player's only unit has 0 movement points left -- which is every attacker,
always (`_execute_attack` unconditionally zeroes it). This scenario's
players own no cities (there is nothing here to found or capture, by
design), so `Player.end_turn()`'s "0 cities -> is_dead, delete every unit"
rule fires immediately, and the `next_turn()` that follows calls the
DEFENDER's `start_turn()` -- which calls `heal()` -- before this script
ever gets to read the defender's post-attack HP. That would silently add HP
back onto the exact number being measured. `_execute_attack` is the correct
atomic unit for "one attack exchange"; the turn/elimination/heal bookkeeping
around it belongs to a full game, not a duel.

Seeding (issue #44 caveat): `GameEnvironment(..., seed=N)` seeds the
engine's `PortableRNG` once; every duel's damage roll draws from that same
continuing stream, so one full run (every condition, every pairing, every
duel) is bit-for-bit reproducible under one seed -- on the SAME machine.
Cross-machine reproduction is not guaranteed even though PortableRNG's
algorithm is portable in principle: the surrounding Python float arithmetic
is not pinned across platforms.

Judgment calls the issue left open (flagged here, not hidden):

- Cost-normalised ratio := (mean_dealt / attacker_cost) / (mean_taken /
  defender_cost) -- "damage dealt per production point spent on the
  attacker" divided by "damage taken per production point spent on the
  defender" (`production_cost`, config.toml [units.*]). Above 1 means the
  ATTACKER is the more cost-efficient side of this exchange; below 1 means
  the DEFENDER is -- even when the raw exchange_ratio is dead even. This is
  what makes Spearman (cost 65) vs Horseman (cost 80) favour the Spearman
  on both directions of the matrix despite a level 35 vs 35 raw fight
  (issue #60: "the counter web lives in cost, not strength"). Undefined
  when there is no counterattack (always true for a ranged attacker --
  damage itself is never 0, `calculate_damage`'s own floor is 1 HP) is
  reported as JSON `null`, shown as an em dash in markdown.
- `--damaged` sets BOTH attacker and defender to the same fixed HP (50,
  half) rather than only one side: `HP_PENALTY_COEFFICIENT` in
  `get_combat_strength` is symmetric in ROLE (it fires for whichever unit
  the health belongs to, attacking or defending), so damaging only one side
  would silently conflate "a weak defender" with "a weak attacker" under
  one flag name.
- `--fortified` sets the DEFENDER to max fortification (level 2). The
  attacker's own fortification is irrelevant by construction --
  `get_combat_strength` only ever adds `FORTIFICATION_BONUS` when
  `not is_attacking` -- so there is nothing for an "attacker fortified"
  condition to measure.
- Melee pairs sit at true hex distance 1 ((row, col) / (row, col+1));
  ranged pairs sit at true hex distance 2 ((row, col) / (row, col+2)), on a
  separate row so the line-of-sight path between them never crosses a tile
  a melee pairing is also using for its (possibly non-flat) terrain
  condition. This is deliberate: in this engine `is_ranged` is intrinsic to
  the unit TYPE (`_execute_attack` reads `get_base_ranged_strength() > 0`),
  not to the actual attack distance -- so placing every ranged attacker at
  melee range would still show "no counterattack" but would never exercise
  the real range-2 + line-of-sight code path the real game uses for a
  ranged attack (the #24 ranged-attack bug lived exactly there).

tests/test_matchup_matrix.py is the automated gate: the harness runs
end-to-end on a tiny unit set, results are reproducible under a fixed seed,
the matrix is genuinely asymmetric where it must be (a ranged attacker
takes no counterattack), and the #63 regression gate -- Spearman's
anti-cavalry bonus must land the same whichever direction the charge comes
from -- expressed as a measurement rather than a single `unit.attack()`
call.

Usage:
    python scripts/matchup_matrix.py
    python scripts/matchup_matrix.py --duels 500 --terrain flat,hills,woods --fortified --damaged
"""

import argparse
import json
import os
import statistics
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from civulator.game.environment import GameEnvironment
from civulator.game.unit import (
    ArcherUnit,
    CatapultUnit,
    HorsemanUnit,
    SpearmanUnit,
    SwordsmanUnit,
    WarriorUnit,
)
from civulator.meta import build_manifest
from civulator.unit_model import BASE_RANGED_STRENGTH, PRODUCTION_COST

# --- Headline scope (issue #65) ---------------------------------------------

COMBAT_UNITS = ["Warrior", "Archer", "Swordsman", "Spearman", "Horseman", "Catapult"]
EXCLUDED_CIVILIANS = ["Settler", "Worker"]  # combat_strength 0 -- see module docstring

UNIT_CLASSES = {
    "Warrior": WarriorUnit,
    "Archer": ArcherUnit,
    "Swordsman": SwordsmanUnit,
    "Spearman": SpearmanUnit,
    "Horseman": HorsemanUnit,
    "Catapult": CatapultUnit,
}

# --- Scenario geometry (module docstring, "Melee pairs sit at...") ---------

BOARD_ROWS = 16
BOARD_COLS = 16
ATK_MELEE, DEF_MELEE = (5, 5), (5, 6)      # hex distance 1
ATK_RANGED, DEF_RANGED = (10, 5), (10, 7)  # hex distance 2, separate row

# --- Condition constants (judgment calls, see module docstring) -----------

DAMAGED_HP = 50.0
FORTIFIED_LEVEL = 2

TERRAIN_CONDITIONS = {
    "flat": {"base": "Plains", "relief": "flat", "feature": None},
    "hills": {"base": "Plains", "relief": "hills", "feature": None},
    "woods": {"base": "Plains", "relief": "flat", "feature": "Woods"},
}

DEFAULT_DUELS = 200
DEFAULT_SEED = 652026  # arbitrary, fixed -- #65 matchup matrix


# --- Scenario setup ----------------------------------------------------------


def _prepare_board(env):
    """Flat, uniform Plains everywhere (mirrors tests/test_combat_range.py's
    make_flat_env) -- terrain is then overridden per-condition on exactly the
    defender tiles, below."""
    for r in range(env.n):
        for c in range(env.m):
            env.map.tiles[r, c].set_layers("Plains", map_ref=env.map)


def _apply_terrain_condition(env, terrain_name):
    """Set the DEFENDER's tile (both the melee and ranged defender positions)
    to the named terrain. Attacker tiles are never touched after
    `_prepare_board` -- they stay flat Plains, since attacking-side terrain
    never enters `get_combat_strength` (only the defender's `current_tile()`
    does)."""
    layer = TERRAIN_CONDITIONS[terrain_name]
    for r, c in (DEF_MELEE, DEF_RANGED):
        env.map.tiles[r, c].set_layers(
            layer["base"], relief=layer["relief"], feature=layer["feature"], map_ref=env.map
        )


def _verify_geometry(env):
    """One-time sanity check that the fixed coordinates actually have the
    hex distance this harness relies on (canonical hex math, never
    hand-derived)."""
    d_melee = env.map.distance_function(ATK_MELEE, DEF_MELEE)
    d_ranged = env.map.distance_function(ATK_RANGED, DEF_RANGED)
    if d_melee != 1:
        raise AssertionError(f"melee scenario positions are hex distance {d_melee}, expected 1")
    if d_ranged != 2:
        raise AssertionError(f"ranged scenario positions are hex distance {d_ranged}, expected 2")


def _is_ranged_type(unit_type):
    return BASE_RANGED_STRENGTH.get(unit_type, 0) > 0


def _positions_for_attacker(attacker_type):
    return (ATK_RANGED, DEF_RANGED) if _is_ranged_type(attacker_type) else (ATK_MELEE, DEF_MELEE)


def _place(env, unit_cls, player_index, coords):
    player = env.players[player_index]
    unit = unit_cls(player, coords)
    player.units.append(unit)
    env.add_unit_to_tile(unit, coords)
    return unit


def _clear_combatants(env):
    """Remove whatever is left from the previous duel -- a melee kill moves
    the attacker into the defender's tile and deletes the defender, so this
    cannot assume the two fixed positions are what's occupied."""
    for player in env.players:
        for unit in list(player.units):
            env.delete_unit(unit)


# --- One duel / one pairing / one condition ---------------------------------


def run_duel(env, attacker_type, defender_type, fortified=False, damaged=False):
    """One attack exchange through `GameEnvironment._execute_attack` (see
    module docstring for why this method and not `env.step()`).

    Returns (damage_dealt, damage_taken) read from the units' own HP before
    and after the call -- never from the reward, which is a training signal
    mixed with kill/capture bonuses, not a damage measurement.
    """
    atk_pos, def_pos = _positions_for_attacker(attacker_type)
    _clear_combatants(env)
    attacker = _place(env, UNIT_CLASSES[attacker_type], 0, atk_pos)
    defender = _place(env, UNIT_CLASSES[defender_type], 1, def_pos)

    if damaged:
        attacker.health = DAMAGED_HP
        defender.health = DAMAGED_HP
    if fortified:
        defender.fortification = FORTIFIED_LEVEL

    hp_atk_before = attacker.health
    hp_def_before = defender.health

    env._execute_attack(attacker, defender)

    damage_dealt = hp_def_before - defender.health
    damage_taken = hp_atk_before - attacker.health
    return damage_dealt, damage_taken


def run_pairing(env, attacker_type, defender_type, duels, fortified=False, damaged=False):
    """`duels` independent exchanges for one ordered (attacker, defender)
    pair; returns the per-cell summary the matrix and the JSON artifact
    both read from."""
    dealt, taken = [], []
    for _ in range(duels):
        d, t = run_duel(env, attacker_type, defender_type, fortified=fortified, damaged=damaged)
        dealt.append(d)
        taken.append(t)

    mean_dealt = statistics.fmean(dealt)
    mean_taken = statistics.fmean(taken)

    # No counterattack (always true for a ranged attacker -- see module
    # docstring): the ratio is undefined, not zero or infinite.
    exchange_ratio = (mean_dealt / mean_taken) if mean_taken > 0 else None
    cost_atk = PRODUCTION_COST[attacker_type]
    cost_def = PRODUCTION_COST[defender_type]
    cost_ratio = (
        (mean_dealt / cost_atk) / (mean_taken / cost_def) if mean_taken > 0 else None
    )

    return {
        "attacker": attacker_type,
        "defender": defender_type,
        "duels": duels,
        "mean_damage_dealt": mean_dealt,
        "mean_damage_taken": mean_taken,
        "exchange_ratio": exchange_ratio,
        "cost_normalized_ratio": cost_ratio,
    }


def _condition_name(terrain, fortified, damaged):
    if terrain == "flat" and not fortified and not damaged:
        return "headline"
    bits = []
    if terrain != "flat":
        bits.append(f"terrain={terrain}")
    if fortified:
        bits.append("fortified")
    if damaged:
        bits.append("damaged")
    return "+".join(bits)


def run_condition(env, units, duels, terrain="flat", fortified=False, damaged=False):
    """Every ordered pairing among `units` under one fixed condition."""
    _apply_terrain_condition(env, terrain)
    pairings = [
        run_pairing(env, attacker_type, defender_type, duels, fortified=fortified, damaged=damaged)
        for attacker_type in units
        for defender_type in units
    ]
    return {
        "name": _condition_name(terrain, fortified, damaged),
        "terrain": terrain,
        "fortified": fortified,
        "damaged": damaged,
        "pairings": pairings,
    }


def build_conditions_spec(terrain_list, fortified_flag, damaged_flag):
    """The headline flat/unfortified/full-HP condition, always first, plus
    one condition per opt-in flag (module docstring: "one variable at a time
    "). Each flag changes exactly one axis away from the headline -- no
    pairwise combinations, by design (out of scope, would combinatorially
    blow up the artifact and the report both)."""
    conditions = [{"terrain": "flat", "fortified": False, "damaged": False}]
    seen = {("flat", False, False)}

    for terrain in terrain_list:
        if terrain not in TERRAIN_CONDITIONS:
            raise ValueError(
                f"unknown --terrain value {terrain!r}; known: {sorted(TERRAIN_CONDITIONS)}"
            )
        key = (terrain, False, False)
        if key not in seen:
            conditions.append({"terrain": terrain, "fortified": False, "damaged": False})
            seen.add(key)

    if fortified_flag and ("flat", True, False) not in seen:
        conditions.append({"terrain": "flat", "fortified": True, "damaged": False})
        seen.add(("flat", True, False))

    if damaged_flag and ("flat", False, True) not in seen:
        conditions.append({"terrain": "flat", "fortified": False, "damaged": True})
        seen.add(("flat", False, True))

    return conditions


def run_matrix(units=None, duels=DEFAULT_DUELS, seed=DEFAULT_SEED, terrain=("flat",),
               fortified=False, damaged=False):
    """Run the full harness and return the plain-dict result (JSON-ready
    apart from wrapping in a manifest, which the CLI adds).

    `units` overrides the headline six -- intended for tests that want a
    tiny, fast configuration; the real headline run always uses all six
    COMBAT_UNITS (the CLI never exposes this override).
    """
    units = list(units) if units is not None else list(COMBAT_UNITS)
    unknown = [u for u in units if u not in UNIT_CLASSES]
    if unknown:
        raise ValueError(f"unknown unit type(s) for the matchup harness: {unknown}")

    env = GameEnvironment(BOARD_ROWS, BOARD_COLS, num_players=2, map_type="basic", seed=seed)
    _prepare_board(env)
    _verify_geometry(env)

    conditions_spec = build_conditions_spec(list(terrain), fortified, damaged)
    conditions = [
        run_condition(env, units, duels, terrain=c["terrain"], fortified=c["fortified"], damaged=c["damaged"])
        for c in conditions_spec
    ]

    return {
        "units": units,
        "excluded_civilians": EXCLUDED_CIVILIANS,
        "duels_per_pairing": duels,
        "seed": seed,
        "board": {"rows": BOARD_ROWS, "cols": BOARD_COLS},
        "positions": {
            "melee": {"attacker": list(ATK_MELEE), "defender": list(DEF_MELEE)},
            "ranged": {"attacker": list(ATK_RANGED), "defender": list(DEF_RANGED)},
        },
        "conditions": conditions,
    }


# --- Markdown rendering -------------------------------------------------


def _fmt(value, ndigits=2):
    # ASCII only -- Windows consoles are not reliably UTF-8 (no existing
    # script in scripts/ prints non-ASCII, so this doesn't set a new
    # precedent).
    return "n/a" if value is None else f"{value:.{ndigits}f}"


def render_grid(units, pairings, metric_key, ndigits=2):
    lookup = {(p["attacker"], p["defender"]): p[metric_key] for p in pairings}
    header = "| Attacker \\ Defender | " + " | ".join(units) + " |"
    sep = "|" + "---|" * (len(units) + 1)
    lines = [header, sep]
    for attacker in units:
        row = [_fmt(lookup[(attacker, defender)], ndigits) for defender in units]
        lines.append(f"| **{attacker}** | " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_detail_table(pairings):
    lines = [
        "| Attacker | Defender | Mean dealt | Mean taken | Exchange ratio | Cost-normalised ratio |",
        "|---|---|---|---|---|---|",
    ]
    for p in pairings:
        lines.append(
            f"| {p['attacker']} | {p['defender']} | {p['mean_damage_dealt']:.2f} | "
            f"{p['mean_damage_taken']:.2f} | {_fmt(p['exchange_ratio'])} | "
            f"{_fmt(p['cost_normalized_ratio'])} |"
        )
    return "\n".join(lines)


def render_report(result):
    out = [
        f"# Matchup matrix (issue #65) -- seed={result['seed']}, "
        f"{result['duels_per_pairing']} duels/pairing",
        "",
        f"Units: {', '.join(result['units'])}. Civilians excluded from the matrix: "
        f"{', '.join(result['excluded_civilians'])} (combat_strength 0 -- cannot attack; "
        "attacking one captures rather than fights).",
    ]
    for cond in result["conditions"]:
        out.append("")
        out.append(
            f"## Condition: {cond['name']} "
            f"(terrain={cond['terrain']}, fortified={cond['fortified']}, damaged={cond['damaged']})"
        )
        out.append("")
        out.append("### Mean damage dealt per attack")
        out.append(
            "Ranged attackers (no counterattack) have no exchange ratio, so this is the "
            "only grid that describes them -- read it alongside the ratio grid below."
        )
        out.append("")
        out.append(render_grid(result["units"], cond["pairings"], "mean_damage_dealt"))
        out.append("")
        out.append("### Exchange ratio (mean damage dealt / mean damage taken)")
        out.append(render_grid(result["units"], cond["pairings"], "exchange_ratio"))
        out.append("")
        out.append("### Cost-normalised ratio -- (dealt / attacker cost) / (taken / defender cost)")
        out.append(render_grid(result["units"], cond["pairings"], "cost_normalized_ratio"))
        out.append("")
        out.append("### Full detail")
        out.append(render_detail_table(cond["pairings"]))
    return "\n".join(out)


# --- CLI ---------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Matchup-matrix harness (issue #65): measure every unit pairing "
        "in the real engine instead of deriving it from constants."
    )
    parser.add_argument("--duels", type=int, default=DEFAULT_DUELS,
                        help=f"Duels per ordered pairing (default {DEFAULT_DUELS}).")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help=f"Engine RNG seed (default {DEFAULT_SEED}); same seed, same "
                             "machine -> bit-identical run (issue #44).")
    parser.add_argument("--terrain", type=str, default="flat",
                        help="Comma-separated defender terrain conditions to run, each as "
                             "its own additional matrix (known: flat,hills,woods). The flat "
                             "headline always runs regardless of this flag.")
    parser.add_argument("--fortified", action="store_true",
                        help="Add one matrix with the defender at max fortification.")
    parser.add_argument("--damaged", action="store_true",
                        help="Add one matrix with both units starting at half HP.")
    args = parser.parse_args()

    terrain_list = [t.strip() for t in args.terrain.split(",") if t.strip()]

    print("=" * 72)
    print("Civulator matchup-matrix harness (issue #65) -- measuring, not deriving")
    print("=" * 72)
    print(f"duels/pairing={args.duels}  seed={args.seed}  terrain={terrain_list}  "
          f"fortified={args.fortified}  damaged={args.damaged}")
    print("=" * 72)

    t0 = time.perf_counter()
    result = run_matrix(
        duels=args.duels, seed=args.seed, terrain=terrain_list,
        fortified=args.fortified, damaged=args.damaged,
    )
    elapsed = time.perf_counter() - t0

    print()
    print(render_report(result))

    artifact = dict(result)
    artifact["manifest"] = build_manifest()
    artifact["elapsed_seconds"] = elapsed

    stats_dir = os.path.join(_PROJECT_ROOT, "stats")
    os.makedirs(stats_dir, exist_ok=True)
    stats_path = os.path.join(stats_dir, f"matchup_matrix_{args.seed}_{int(time.time())}.json")
    with open(stats_path, "w") as f:
        json.dump(artifact, f, indent=2)

    print()
    print("=" * 72)
    print(f"Done in {elapsed:.1f}s. Artifact written to: {stats_path}")
    print("=" * 72)

    return result


if __name__ == "__main__":
    main()
