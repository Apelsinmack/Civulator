"""Layer-1 golden: the full MapData product sealed by SHA-256 (design D21).

The frozen world is THE ceremony world — Standard 48x24, seed 42, 6 players —
inspected in the live preview and pronounced good by Erik at the v0.6.0 P8
ceremony (2026-08-23). Params are pinned HERE, never read from config.toml
(which is hot-reloadable by design): this test fails only when the GENERATOR
changes, never when a knob is tuned. If it fails: version bump + CHANGELOG +
a deliberate re-baseline with a human inspection (design doc §8) — never
paste the new hash casually.

The engine-level twin (tests/test_rng.py::test_engine_world_is_frozen_across_
versions) guards the GameEnvironment wiring on top of the same contract.
"""

import hashlib

from civulator.mapgen import generate

CEREMONY_SHA256 = "73a79864106480f16ba70e7a701b48c3f154ef6a43279f9da233a3264ed5de4b"

# [map.earthlike] as of v0.6.0, frozen (D25 geometry: split elevation).
PINNED_PARAMS = {
    "continent_wavelength": 3,
    "octaves": "auto",
    "mountain_wavelength": 5,
    "mountain_belt_percent": 0.35,
    "mountain_amp_coast": 0.0,
    "mountain_amp_relief": 1.5,
    "warp_amp": 4.0,
    "warp_octaves": 3,
    "land_percent": 0.45,
    "mountain_percent": 0.08,
    "hill_percent": 0.2,
    "smooth_iterations": 3,
    "talus_slope": 0.08,
    "diffusion_coeff": 0.4,
    "lake_max_size": 12,
    "temp_wobble_amp": 0.3,
    "temp_wobble_wavelength": 4,
    "temp_lapse_rate": 0.8,
    "temp_snow_percentile": 0.25,
    "temp_tundra_percentile": 0.3,
    "moisture_wavelength": 5,
    "moisture_octaves": 4,
    "moisture_desert_percentile": 0.36,
    "moisture_plains_percentile": 0.56,
    "river_percent": 0.18,
    "river_moisture_bonus": 0.1,
    "river_min_length": 2,
    "river_pd_epsilon": 0.0001,
    "river_altitude_jitter": 1e-07,
    "feature_chance": {
        "woods": 0.35, "rainforest": 0.5, "marsh": 0.15,
        "ice": 0.7, "reef": 0.3, "oasis": 0.2,
    },
}


def _ceremony_world():
    return generate(42, (24, 48), num_players=6, params=PINNED_PARAMS,
                    map_type="earthlike")


def test_mapdata_fingerprint_is_frozen():
    md = _ceremony_world()
    assert hashlib.sha256(md.canonical_bytes()).hexdigest() == CEREMONY_SHA256, (
        "generator output changed — version bump + CHANGELOG + re-baseline "
        "ceremony required (design doc §8)"
    )


def test_ceremony_world_excerpt():
    """Human-readable excerpt so a fingerprint break points somewhere legible."""
    md = _ceremony_world()
    assert sorted(md.starts) == [
        (3, 45), (4, 7), (7, 0), (9, 38), (14, 17), (21, 25),
    ]
    assert len(md.rivers) == 359
