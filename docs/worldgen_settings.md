# World Generation — Settings Guide

> For the design rationale behind everything here, see `terrain_model_design.md`.
> This page is the practical manual: what each knob does, what's safe to touch,
> and what happens when you do.

## The one reassurance first

**Tuning knobs never corrupts anything saved.** Every scenario and recording
stores its own generator settings in its manifest and rebuilds from *those*,
not from the live `config.toml`. The golden tests pin their settings
internally too. So: change any value below, restart, and only *newly
generated* worlds are affected. Tweak fearlessly.

## Previewing your changes

```
python -m civulator.mapgen --seed 42 --size standard
```

Keys: **N** new seed · **S** screenshot · **T** toggle start markers ·
arrows/drag pan (scrolls seamlessly across the east-west wrap) · wheel zoom.
Flags: `--size duel|tiny|small|standard|large|huge` · `--players N` ·
`--type basic|earthlike` · `--seed N` · `--png out.png` (headless render) ·
`--rows R --cols C` (explicit dimensions).

## `[map]` — top level

| Key | Meaning |
|---|---|
| `type` | `"earthlike"` (default — the full pipeline) or `"basic"` (iid test worlds, any size, no rivers) |
| `size` | Named preset from `[map.sizes.*]`; sets dimensions *and* default player count |
| `max_world_retries` | Unseeded `reset()` redraws this many times (logged) if a world can't place fair starts (~2% of seeds), then raises. Seeded resets never retry — a specific seed either works or fails loudly |

## `[map.sizes.*]` — presets

Each preset: `rows`, `cols`, `default_players`, `max_players`.
Duel 24×12/2 · Tiny 32×16/3 · Small 40×20/4 · **Standard 48×24/6** ·
Large 64×32/8 · Huge 84×42/12. Earthlike needs at least Duel size.

## `[map.earthlike]` — the world's character

**Land and continents**

| Knob (default) | What it does |
|---|---|
| `land_percent` (0.45) | Fraction of the map that is land — exact by construction (nearest-rank). Lower = more ocean, more fragmented land; below ~0.40 start placement begins failing noticeably |
| `continent_wavelength` (3) | How many big landmass-scale features fit across the map. Smaller = fewer, larger continents |
| `warp_amp` (4.0) | Domain warping strength — folds and shears coastlines. 0 = smooth blobs; large = marbled |
| `octaves` ("auto") | Noise detail levels; auto = log2(width)−2. More octaves add roughness, never structure — crank only on huge experimental maps |

**Relief** (mountain/hill *counts* are exact fractions of land; these knobs shape *where*)

| Knob (default) | What it does |
|---|---|
| `mountain_percent` (0.08), `hill_percent` (0.20) | Fractions of land that are mountain/hill relief |
| `mountain_amp_relief` (1.5) | Ridged-noise strength in the relief field — higher = relief clusters into belt-like uplands; 0 = scattered |
| `mountain_amp_coast` (0.0) | Ridged-noise bleed into the *coastline* field. Keep 0: raising it re-fragments continents (this was the 27.7%-failure bug) |
| `mountain_belt_percent` (0.35), `mountain_wavelength` (5) | How much of the map lies in orogeny belts, and their scale |
| `smooth_iterations` (3), `talus_slope`, `diffusion_coeff` | Elevation smoothing — rarely worth touching |

**Climate & biomes** (thresholds are percentiles — the *mix* stays stable across seeds)

| Knob (default) | What it does |
|---|---|
| `temp_lapse_rate` (0.8) | How much altitude cools a tile (snowy peaks) |
| `temp_wobble_amp` (0.3) | How much climate-band boundaries meander |
| `temp_snow_percentile` (0.25), `temp_tundra_percentile` (0.30) | Cold-band sizes |
| `moisture_desert_percentile` (0.36), `moisture_plains_percentile` (0.56) | Dry-band sizes |
| `feature_chance.*` | Per-feature placement probability on eligible tiles (woods, rainforest, marsh, ice, reef, oasis) |

**Rivers**

| Knob (default) | What it does |
|---|---|
| `river_percent` (0.18) | Fraction of drainage edges that become rivers |
| `river_min_length` (2) | Suppress shorter rivers |
| `river_moisture_bonus` (0.1) | Extra moisture near rivers before biome classification — green valleys |

## Terrain gameplay tables

Yields, movement, defense, line-of-sight, and placement rules for every base
terrain, relief, feature, and resource live in `[terrain.base.*]`,
`[terrain.relief.*]`, `[terrain.feature.*]`, `[terrain.resource.*]` — all
additive contributions, all with `on = {...}` placement constraints. Adding
a bonus resource later is one config entry, zero code. River crossing cost:
`[terrain.river] crossing_cost`.

## When a golden test breaks

The frozen-world tests (`tests/test_mapgen_golden.py`, `tests/test_rng.py`)
fail **only** when generator *code* changes what a pinned seed produces —
never from knob tuning. If one fails: that's a version bump + CHANGELOG + a
deliberate re-baseline with a human look at the new world (design doc §8).
Never paste in the new hash casually.
