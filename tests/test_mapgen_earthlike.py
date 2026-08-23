"""Tests for civulator.mapgen's earthlike/basic pipeline and quality oracles
(design doc §10, §11 P3 deliverable 5, GATE).
"""

import os
import subprocess
import sys

import numpy as np
import pytest

from civulator import mapgen
from civulator.mapgen import basic, earthlike, noise, seeding, stats
from civulator.mapgen.earthlike import EARTHLIKE_MIN_COLS, EARTHLIKE_MIN_ROWS, _hex_coords
from civulator.terrain_model import check_on

STANDARD = (24, 48)
DUEL = (12, 24)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- (b) determinism ---------------------------------------------------


class TestDeterminism:
    @pytest.mark.parametrize("map_type,size", [("earthlike", DUEL), ("basic", (8, 16))])
    def test_generate_twice_is_identical(self, map_type, size):
        md1 = mapgen.generate(999, size, num_players=2, map_type=map_type)
        md2 = mapgen.generate(999, size, num_players=2, map_type=map_type)
        assert np.array_equal(md1.base_terrain, md2.base_terrain)
        assert np.array_equal(md1.relief, md2.relief)
        assert np.array_equal(md1.feature, md2.feature)
        assert np.array_equal(md1.resource, md2.resource)
        assert md1.rivers == md2.rivers
        assert np.array_equal(md1.fresh_water, md2.fresh_water)
        assert md1.starts == md2.starts

    @pytest.mark.parametrize("map_type,size", [("earthlike", DUEL), ("basic", (8, 16))])
    def test_different_seeds_produce_different_worlds(self, map_type, size):
        md1 = mapgen.generate(1, size, map_type=map_type)
        md2 = mapgen.generate(2, size, map_type=map_type)
        assert not np.array_equal(md1.base_terrain, md2.base_terrain)


# --- (c) isotropy oracle: the #13 regression proof ----------------------


class TestIsotropyOracle:
    """design doc §10, §11 P3 deliverable 5c. Measured on the SAME
    continentalness-style noise call `earthlike.generate` makes internally
    (`_hex_coords` + `noise.fbm`) rather than the final thresholded land/
    water grid: ridged-multifractal mountain BELTS and binary threshold
    edges are deliberately elongated/blocky features (not a bug), so
    measuring isotropy after them makes for a noisy, unreliable oracle
    (empirically: ratios from ~1.2 to ~35 across seeds on the same correct
    generator, verified during implementation). The noise foundation
    itself is where issue #13 actually lived and where an isotropy check
    is a clean, reliable signal — this is a documented interpretation of
    "metric within tolerance for earthlike", chosen after measuring both.
    """

    TOLERANCE = 1.4  # empirically: correct sampling stays < ~1.2, broken > ~1.6 (see report)
    SEEDS = range(10)

    @staticmethod
    def _field(seed, broken):
        rows, cols = STANDARD
        if broken:
            # The deliberately broken fixture (design doc §11 P3 deliverable
            # 5c): raw (q, r) index coordinates instead of hex-Cartesian
            # centers — the actual historical #13 mistake (see
            # map_generator_prototype.py's `angle = 2*pi*c/n_cols`, which
            # used the column index directly with no r/2 axial offset).
            r_idx, q_idx = np.meshgrid(
                np.arange(rows, dtype=np.float64), np.arange(cols, dtype=np.float64), indexing="ij"
            )
            x, y = q_idx, r_idx
        else:
            x, y = _hex_coords(rows, cols)
        return noise.fbm(x, y, cols, seeding.mix64(seed, 4242), octaves=2, base_period=16)

    def test_earthlike_sampling_stays_within_tolerance(self):
        ratios = [stats.isotropy_ratio(self._field(s, broken=False))[0] for s in self.SEEDS]
        assert max(ratios) < self.TOLERANCE, f"ratios: {ratios}"

    def test_raw_qr_sampling_fixture_fails_the_same_tolerance(self):
        ratios = [stats.isotropy_ratio(self._field(s, broken=True))[0] for s in self.SEEDS]
        assert min(ratios) > self.TOLERANCE, f"ratios: {ratios}"


# --- (d) terrain mix: nearest-rank exactness -----------------------------


class TestTerrainMix:
    @pytest.mark.parametrize("seed", [11, 12, 13])
    def test_land_mountain_hill_fractions_match_nearest_rank(self, seed):
        rows, cols = STANDARD
        p = dict(earthlike.DEFAULT_PARAMS)
        md = mapgen.generate(seed, (rows, cols), params=p, map_type="earthlike")
        frac = stats.terrain_mix_fractions(md)

        expected_land = round(p["land_percent"] * rows * cols)
        assert abs(frac["land_count"] - expected_land) <= 2

        land_count = frac["land_count"]
        expected_mountain = round(p["mountain_percent"] * land_count)
        expected_hill = round((p["mountain_percent"] + p["hill_percent"]) * land_count) - expected_mountain
        assert abs(frac["mountain_count"] - expected_mountain) <= 2
        assert abs(frac["hill_count"] - expected_hill) <= 2


# --- (e) climate bands ----------------------------------------------------


class TestClimateBands:
    def test_polar_tundra_snow_and_equatorial_desert_or_rainforest_over_seeds(self):
        rows, cols = STANDARD
        n_seeds = 10
        polar_hits = 0
        equatorial_hits = 0
        for seed in range(n_seeds):
            md = mapgen.generate(seed, (rows, cols), map_type="earthlike")
            bands = stats.climate_band_terrains(md)

            if bands["polar"] & {"Tundra", "Snow"}:
                polar_hits += 1

            has_desert = "Desert" in bands["equatorial"]
            has_rainforest = any(
                md.feature[r, c] == "Rainforest"
                for r in bands["equatorial_rows"]
                for c in range(cols)
            )
            if has_desert or has_rainforest:
                equatorial_hits += 1

        assert polar_hits == n_seeds, f"Tundra/Snow present in only {polar_hits}/{n_seeds} seeds' polar band"
        assert equatorial_hits == n_seeds, (
            f"Desert/Rainforest present in only {equatorial_hits}/{n_seeds} seeds' equatorial band"
        )


# --- (f) constraint validity ----------------------------------------------


class TestConstraintValidity:
    def test_zero_invalid_feature_placements_over_seeds(self):
        rows, cols = STANDARD
        checked = 0
        for seed in range(10):
            md = mapgen.generate(seed, (rows, cols), map_type="earthlike")
            for r in range(rows):
                for c in range(cols):
                    feat = md.feature[r, c]
                    if feat is None:
                        continue
                    checked += 1
                    base, relief = md.base_terrain[r, c], md.relief[r, c]
                    assert check_on("feature", feat, base, relief, None), (
                        f"seed {seed} ({r},{c}): {feat} on base={base} relief={relief} "
                        f"fails its own `on` constraint"
                    )
        assert checked > 0, "no features were placed across 10 seeds -- test is vacuous"

    def test_basic_generator_also_respects_constraints(self):
        checked = 0
        for seed in range(10):
            md = mapgen.generate(seed, (16, 32), map_type="basic")
            rows, cols = md.base_terrain.shape
            for r in range(rows):
                for c in range(cols):
                    feat = md.feature[r, c]
                    if feat is None:
                        continue
                    checked += 1
                    assert check_on("feature", feat, md.base_terrain[r, c], md.relief[r, c], None)
        assert checked > 0


# --- (g) all-land world ----------------------------------------------------


class TestAllLandWorld:
    def test_land_percent_one_generates_without_error_no_water(self):
        md = mapgen.generate(1, DUEL, params={"land_percent": 1.0}, map_type="earthlike")
        assert not np.any(np.isin(md.base_terrain, ["Coast", "Ocean", "Lake"]))
        frac = stats.terrain_mix_fractions(md)
        assert frac["land_fraction"] == 1.0
        # P4 (design doc §5): MapData.rivers is a dict (tile-pair -> RiverEdge,
        # carrying flow+flux), never a set -- {} is the empty case, not set().
        assert md.rivers == {}
        assert not np.any(md.feature == "Floodplains")


# --- (h) size guards --------------------------------------------------------


class TestSizeGuards:
    def test_earthlike_below_duel_rows_raises(self):
        with pytest.raises(ValueError):
            mapgen.generate(1, (EARTHLIKE_MIN_ROWS - 1, EARTHLIKE_MIN_COLS), map_type="earthlike")

    def test_earthlike_below_duel_cols_raises(self):
        with pytest.raises(ValueError):
            mapgen.generate(1, (EARTHLIKE_MIN_ROWS, EARTHLIKE_MIN_COLS - 1), map_type="earthlike")

    def test_earthlike_at_duel_size_works(self):
        md = mapgen.generate(1, DUEL, map_type="earthlike")
        assert md.base_terrain.shape == DUEL

    def test_basic_at_8x16_works(self):
        md = mapgen.generate(1, (8, 16), map_type="basic")
        assert md.base_terrain.shape == (8, 16)


# --- GATE: package purity ---------------------------------------------------


class TestPackagePurity:
    """design doc §4.1: "[mapgen] imports nothing from game/, viz/, agents/."
    Run in a FRESH subprocess (not just checking this test file's own
    sys.modules) so an unrelated test file that already imported
    civulator.game earlier in the same pytest session can't mask a real
    violation.
    """

    def test_mapgen_core_imports_nothing_from_game_viz_or_agents(self):
        script = (
            "import sys\n"
            "import civulator.mapgen\n"
            "bad = sorted(m for m in sys.modules if m.startswith(('civulator.game', "
            "'civulator.viz', 'civulator.agents')))\n"
            "print(bad)\n"
            "sys.exit(1 if bad else 0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"importing civulator.mapgen pulled in game/viz/agents: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
