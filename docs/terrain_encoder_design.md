# Terrain-Aware State Encoder (#40) — implementation spec

> Authored 2026-08-25 (overnight autonomous session, ERIK_LENOVO). Design settled
> with Erik in chat + the #40 issue sketch. This doc is the locked contract for
> the implementing patch; re-planning happens at patch boundaries only.

## Goal

A measured experiment: does terrain-aware state help the agent settle and fight
better? Trained on the SAME world sequence as the v0.6.0 baseline
(`duel_25ch_1000ep`, seed_base=390000) and evaluated as win-rate-vs-baseline +
episodes-to-50%. FullyConv is channel-count agnostic — this is
StateEncoder-subclass work only.

## Class

`TerrainAwareStateEncoder(EnhancedStateEncoder)` in
`civulator/agents/state_encoders.py`.

The parent's channel block is the UNCHANGED PREFIX — channels 0..24 (no fog)
or 0..26 (fog, incl. the two mask channels) must stay bit-identical to
`EnhancedStateEncoder.encode()` output. The terrain block is appended after.

## Terrain block — 27 channels, offsets relative to block start

| Offset | Content | Encoding |
|--------|---------|----------|
| +0..+7 | Base terrain one-hot | Order pinned as class attr: Grassland, Plains, Desert, Tundra, Snow, Coast, Lake, Ocean. `__init__` verifies every base in config's BASE_TABLE is covered; unknown base at encode time → error, never silence. |
| +8..+9 | Relief | hills, mountain (flat = both 0) |
| +10..+16 | Feature one-hot | Woods, Rainforest, Marsh, Floodplains, Oasis, Reef, Ice (none = all 0); same coverage check as bases |
| +17 | Resource presence | 1.0 if tile.resource is not None |
| +18..+20 | River on owned edge E, SE, SW | Straight from `Map._river_flags_grid()` bits (canonical owned-edge convention: every tile owns 3 of its 6 edges; lossless — a 3x3 receptive field reconstructs all 6 edges from neighbors) |
| +21 | Water access ordinal | 1.0 fresh (`Map._fresh_water_grid()`); else 0.5 if any hex neighbor (via `hexmath.adjacent_coords`) has water domain; else 0.0. Mirrors the three city-housing tiers (Erik, 2026-08-25). |
| +22 | Composed defense | `tile.defense_bonus / max_defense`, clamped [0,1] |
| +23..+24 | Composed yields food, production | `tile.yields / max_food`, `/ max_production`, clamped [0,1] |
| +25..+26 | LoS obstacle, vantage | `tile.los / max_obstacle`, `/ max_vantage`, clamped [0,1] |

Depth: 25+27 = **52** (no fog), 27+27 = **54** (fog).

## Normalization — derived, not magic

At `__init__`, each scalar max is derived from the config terrain tables as the
sum of per-table maxima (max over base entries + max over relief + max over
feature + max over resource, missing keys contribute 0), floored at 1.0.
Deterministic given config; the manifest already pins config per run.

## Caching & fog

All 27 terrain channels are static per `(map_uid, terrain_epoch)` — build the
whole block once, cached exactly like the parent's `_get_terrain_layer`
(design doc §3.4 cache pattern). Under fog, multiply the entire terrain block
by the `explored` mask (same rule the parent applies to ch24); the parent's
visible/explored mask channels keep their existing positions inside the prefix.

## Wiring

- Encoder registry: `get_encoder(name, fog_of_war=None)` in
  `state_encoders.py` — `"enhanced"` → EnhancedStateEncoder, `"terrain_aware"`
  → TerrainAwareStateEncoder. Scripts stop hard-instantiating encoder classes.
- `config.toml [training] encoder = "enhanced"` (default; keeps every existing
  run reproducing byte-identically).
- `scripts/run_baseline.py` gains an `--encoder` flag (default from config) so
  the SAME script runs the comparison on the same seed schedule; run naming
  uses the channel count (`duel_52ch_...`) per the manifest naming convention.

## Oracle (gate for auto-merge)

New tests (tests/test_terrain_encoder.py), plus the full suite green:

1. Prefix bit-identity: on a generated world (fog on AND off), terrain-aware
   output[:parent_depth] `torch.equal` parent encoder output.
2. One-hot exclusivity + coverage: exactly one base channel set per tile; at
   most one feature; relief channels match tile.relief.
3. River losslessness: reconstructing the edge set from the 3 owned-edge
   channels (tile + bit → edge) reproduces `Map.rivers`' edge set exactly.
4. Water ordinal: cases for fresh (river-adjacent), coastal-only, inland,
   oasis; a lake-adjacent tile is fresh, not 0.5.
5. Scalar channels ∈ [0,1]; spot-check one known composite (e.g. hills+Woods
   defense) against `terrain_model.compose`.
6. Fog: terrain block zero on unexplored tiles, intact on explored.
7. Determinism: same seed → identical tensor; cache invalidates on
   `Tile.set_layers` (terrain_epoch bump).

## Systems

**Existing canonical systems this design uses** (project CLAUDE.md inventory):
terrain_model composed properties (via `tile.composed` — never re-summing
layers); `Map._river_flags_grid` / `Map._fresh_water_grid` (the single river /
fresh-water representations); `civulator.hexmath` adjacency; the §3.4
`(map_uid, terrain_epoch)` cache pattern; manifest-stamped artifacts; the
seed-schedule runner (`run_baseline.py`).

**New systems created** (draft rules → project CLAUDE.md at implementation):
- Encoder registry: *"State encoders are selected by name via
  `state_encoders.get_encoder()`; scripts and trainer never instantiate
  encoder classes directly."*
- TerrainAwareStateEncoder: *"Terrain state channels come from
  TerrainAwareStateEncoder (52/54ch); extend its terrain block rather than
  adding ad-hoc terrain channels to other encoders."*

## ACCEPTED GAPS

- Resource identity (8-wide one-hot) deferred — presence bit only, per the
  issue sketch's minimal option; revisit when resources differ mechanically.
- Improvements not encoded — none affect gameplay yet.
- Per-resource yields ARE folded into the composed yield channels (compose()
  includes the resource layer), so the presence bit + yields carry most signal.
