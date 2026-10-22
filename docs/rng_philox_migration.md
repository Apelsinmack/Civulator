# Engine RNG → philox32 (patch Q0 of the 0.9 block): design

> **Status: v1, Erik's go given (2026-10-22 evening: "I agree with Q0 …
> probably we'll need some randomness in breach eventually too").** The one
> design decision is Erik's; the rest is implementation strategy (Claude's).
> Runs **before Q1** of `docs/districts_religion_design.md` §14, so goldens,
> the fixture and the frozen RNG vectors re-baseline once with the 0.9.0 bump.

## 1. Goal and what it is not

One deterministic generator for Erik's simulation projects: `philox32`
(`https://github.com/eriiiko/philox32`, Philox-4x32-10, integer-only,
bit-identical C++/CUDA/Python, gated on Random123's known-answer vectors).
Civulator adopts it as its engine RNG so that a fix or an extension to the
kit reaches every consumer, and so that a future C++ or CUDA subsystem draws
the same words from `philox32.h` without a port.

**Not a bug fix.** The cross-machine divergence Erik remembers (#44, 2026-08)
was closed as a record error: the skip schedule was bit-identical across
machines; `PortableRNG` (PCG32, `civulator/rng.py`, #33) is integer
arithmetic and already machine-independent. Nothing measured changes for the
better here except shared ownership; the CHANGELOG says so.

## 2. The seam today

`PortableRNG` is the only randomness in episode simulation (CLAUDE.md "Engine
RNG" row). Its surface, from the call sites (`environment.py`, `map.py`,
`territory.py`, `unit.py` damage rolls, `mapgen/seeding.py`'s one master-seed
draw, `tools/recording.py`, `scripts/evaluate.py`, `matchup_matrix.py`,
`profile_training.py`, `training/trainer.py`): `PortableRNG(seed=None)`,
`.seed(seed)`, `.random()`, `.randint(a, b)`, `.uniform(a, b)`,
`.shuffle(list)`, `.choices(population, weights)`, `.next_uint32()`,
`.next_uint64()`. The derived draws are documented in the module docstring
and frozen by `tests/test_rng.py`. Mapgen's noise (`mapgen/noise.py`) is a
coordinate hash, **not** the engine RNG, and is untouched here.

## 3. The replacement

`civulator/rng.py` keeps its name and exports **`PhiloxRNG`** with the same
method set; `PortableRNG` becomes an alias of it for one release so no call
site changes (then the alias goes, with the CHANGELOG line).

Stream layout (philox32's recommended one): `key = (seed_lo, seed_hi)` =
the 64-bit seed split into two words; `counter = (block, 0, STREAM_SALT, 0)`
where `block` is the number of blocks drawn so far and `STREAM_SALT` is a
fixed engine constant (the role `_SEQUENCE = 54` plays today; "change only
with a CHANGELOG entry"). Each block yields four words, buffered;
`next_uint32()` pops one; `seed()` resets `block = 0` and the buffer.
Unseeded construction draws the seed from `os.urandom` exactly as today.

Derived draws — the kit's mapping where the kit has one, today's otherwise:

| Draw | Rule | Why |
|---|---|---|
| `random()` | `next_uint32() / 2**32` | as today (32-bit floats) |
| `randint(a, b)` | `a + philox32_below(next_uint32(), b - a + 1)` | the kit's Lemire multiply-shift; no modulo; one word per draw, so the stream stays accountable |
| `uniform(a, b)` | `a + (b - a) * random()` | as today |
| `shuffle` | Fisher–Yates from the top with `randint` | as today |
| `choices` | `r = random() * total`, linear cumulative scan | as today |
| `next_uint64()` | two words, high then low | as today |

Every rule is written into the module docstring as the contract a C++ twin
implements, exactly as the PCG32 docstring did.

## 4. Dependency

`pip install "philox32 @ git+https://github.com/eriiiko/philox32@<commit>"`
pinned to a commit (the repo has no tags yet — Erik: tag `v0.1.0` and the
pin becomes the tag), listed in the project's requirements beside numpy and
torch. Not vendored: a fix in the kit must reach civulator by a version
bump, not by a copy. `civulator/meta.py build_manifest` records
`rng = {"kind": "philox32", "version": philox32.__version__}` in every
artifact, next to the game version, so a weight or scenario says which
stream it was made under. `conda`/`environment.md`: one line per machine
env (the `machine-env` skill's file).

## 5. What breaks, by design (the epoch)

Every seeded world changes (mapgen takes its master seed from the engine
RNG at reset), every damage roll, every shuffle. So, in Q0 itself:

- `__version__` → `0.9.0` (the districts design's B9 moves here; Q1 keeps
  the bump) and `tests/fixtures/scenario_fixture.json` regenerated;
  `check_version` then refuses 0.8 scenarios and recordings, which is
  correct — a 0.8 recording re-simulated under a new stream diverges.
- `tests/test_mapgen_golden.py` `CEREMONY_SHA256` re-baselined with the
  **re-inspection ceremony** (terrain *does* change this time — the terrain
  design doc's ceremony applies, not the field-diff shortcut).
- `tests/test_rng.py`: the PCG32 reference vectors go; the kit's KAT vectors
  gate the block function (imported from `philox32`'s tests or pinned here);
  the derived-draw and engine-world frozen vectors are regenerated once and
  frozen again.
- The #39 episode-seed skip set and every "N games" claim in `stats/` are
  pre-0.9 facts; nothing is comparable across the change (#78: a new rules
  epoch anyway).
- `weights/trained/manifest.md` gains the epoch line.

## 6. Tests (properties, each naming the change that breaks it)

| Property | Breaks if |
|---|---|
| `PhiloxRNG(seed).next_uint32()` reproduces philox32's KAT words for the layout in §3 | the counter/key layout or salt drifts |
| Two generators with the same seed produce identical streams; `seed()` replays | buffering or block count leaks state |
| `randint(a, b)` is in `[a, b]`; `shuffle` is a permutation; `choices` honours zero weights | a mapping changes |
| One word per `randint` / `random` (the stream is accountable: `block` advances by exactly ⌈draws/4⌉) | a rejection loop is introduced |
| `test_engine_world_is_frozen_across_versions` holds on the regenerated vector | anything in reset draws differently |
| Full suite green; seeded smoke run; `scripts/evaluate.py` on two seeds reproduces itself | a call site bypasses the seam |

## 7. Patch

| # | Patch | Gate | Tier |
|---|---|---|---|
| Q0 | `PhiloxRNG` + alias, dependency pin, manifest field, version bump, fixture, goldens (ceremony), `test_rng` re-freeze, CHANGELOG 0.9.0 opened with this entry, CLAUDE.md "Engine RNG" row amended | §6; full suite; smoke | Sonnet (oracle-gated: KAT vectors, frozen vectors, suite) |

## Systems

(a) Engine RNG (the seam replaced in place) · Artifact manifests
(`build_manifest`, `check_version`) · World generation (master-seed draw;
golden re-baseline ceremony) · Combat (damage roll reads `rng.uniform`) ·
Gameplay config (nothing: the salt is a module constant, as `_SEQUENCE` is).

(b) Amended row: **Engine RNG** — `PhiloxRNG` (`civulator/rng.py`, the
`philox32` kit pinned in requirements) is the only randomness in episode
simulation; the stream layout and derived draws in its docstring are the
contract any C++/CUDA consumer implements through `philox32.h`; the salt
changes only with a CHANGELOG entry. Breach adopts the same kit when its
simulation needs randomness (nothing to migrate there today).
