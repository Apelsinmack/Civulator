"""Tests for civulator.mapgen's P4 river/floodplains/oasis/resources/
fresh-water stages (design doc §5, §11 P4 deliverable 8).

Oracle lettering below matches the P4 task list exactly, so each is easy to
trace back to its requirement.
"""

import collections

import numpy as np
import pytest

from civulator import hexmath, mapgen
from civulator.mapgen import earthlike, rivers
from civulator.terrain_model import check_on

STANDARD = (24, 48)
DUEL = (12, 24)
WATER_BASES = ("Coast", "Lake", "Ocean")


# --- Geometry self-check: the corner-junction graph itself ------------------
# Not one of the lettered oracles, but the foundation every other test here
# relies on -- hand-verified against the derivation in the P4 report (rivers.py
# module docstring), independent of the "no river edge on this tile" business
# logic tested below.


class TestJunctionGeometry:
    def test_s_corner_touches_self_sw_se(self):
        junctions = rivers.all_junctions(12, 24)
        assert junctions[(2, 3, "S")] == ((2, 3), (3, 2), (3, 3))

    def test_n_corner_touches_self_nw_ne(self):
        junctions = rivers.all_junctions(12, 24)
        assert junctions[(3, 3, "N")] == ((3, 3), (2, 3), (2, 4))

    def test_s_corner_wraps_columns_cylindrically(self):
        junctions = rivers.all_junctions(12, 24)
        assert junctions[(2, 0, "S")] == ((2, 0), (3, 23), (3, 0))

    def test_row0_has_no_n_corner_and_last_row_has_no_s_corner(self):
        rows, cols = 12, 24
        junctions = rivers.all_junctions(rows, cols)
        for q in range(cols):
            assert (0, q, "N") not in junctions
            assert (rows - 1, q, "S") not in junctions
        # every OTHER row has both (design doc §5: only the true r-boundary is excluded)
        for r in range(1, rows - 1):
            for q in range(cols):
                assert (r, q, "N") in junctions
                assert (r, q, "S") in junctions

    def test_neighbor_junctions_match_hand_derived_formula(self):
        """Cross-checks the GENERIC shared-touching-tile-pair adjacency
        derivation (rivers.junction_adjacency) against the CLOSED-FORM
        formula worked out by hand in the P4 report: neighbors of (r, q, S)
        are exactly [(r+1, q-1, N), (r+1, q, N), (r+2, q-1, N)] (when all
        three are in-bounds) -- two independently-derived routes to the
        same graph agreeing is strong evidence neither has a transcription
        bug.
        """
        rows, cols = 12, 24
        junctions = rivers.all_junctions(rows, cols)
        neighbors, edge_tile_pair = rivers.junction_adjacency(junctions)

        r, q = 4, 5
        expected = {(r + 1, q - 1, "N"), (r + 1, q, "N"), (r + 2, q - 1, "N")}
        assert set(neighbors[(r, q, "S")]) == expected

        # And the tile-pair for the (S)-(N) edge shared with its SW neighbor
        # is exactly {(r,q), (r+1,q-1)} -- the two tiles common to both
        # junctions' touching sets.
        pair = edge_tile_pair[frozenset(((r, q, "S"), (r + 1, q - 1, "N")))]
        assert set(pair) == {(r, q), (r + 1, q - 1)}

    def test_every_junction_has_at_most_3_neighbors(self):
        junctions = rivers.all_junctions(*STANDARD)
        neighbors, _ = rivers.junction_adjacency(junctions)
        assert all(len(nbs) <= 3 for nbs in neighbors.values())
        assert max(len(nbs) for nbs in neighbors.values()) == 3, "vacuous if nothing reaches the interior max"


# --- (a) river connectivity/termination oracle -------------------------------


class TestRiverConnectivity:
    @staticmethod
    def _touching_tiles(junction, rows, cols):
        """Independent (from rivers.py's internal generic derivation)
        transcription of design doc §5's own N/S-corner definition, used
        here only to ask "does the terminal junction of this chain touch
        water" -- not a re-test of the adjacency machinery (see
        TestJunctionGeometry for that).
        """
        r, q, kind = junction
        if kind == "S":
            return [(r, q), (r + 1, (q - 1) % cols), (r + 1, q % cols)]
        return [(r, q), (r - 1, q % cols), (r - 1, (q + 1) % cols)]

    def test_every_river_edge_lies_on_a_path_terminating_at_water(self):
        checked_chains = 0
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            rows, cols = md.rows, md.cols

            downstream_of = {}
            for edge in md.rivers.values():
                assert edge.upstream not in downstream_of, "a junction has 2 outgoing river edges"
                downstream_of[edge.upstream] = edge.downstream

            for start in downstream_of:
                j = start
                visited = set()
                while j in downstream_of:
                    assert j not in visited, f"seed {seed}: cycle at {j}"
                    visited.add(j)
                    j = downstream_of[j]
                # j is now terminal within the selected set (design doc: it
                # must reach a global sink, which the sink-fill's own
                # construction guarantees is water-touching -- see the P4
                # report's proof).
                touching = self._touching_tiles(j, rows, cols)
                assert any(md.base_terrain[t] in WATER_BASES for t in touching), (
                    f"seed {seed}: chain from {start} ends at {j}, "
                    f"which touches no Coast/Lake/Ocean tile: {touching}"
                )
                checked_chains += 1
        assert checked_chains > 0, "no river chains found across 5 seeds -- test is vacuous"


# --- (b) minimum river length ------------------------------------------------


class TestMinLength:
    def test_no_river_component_shorter_than_configured_minimum(self):
        min_length = earthlike.DEFAULT_PARAMS["river_min_length"]
        checked = 0
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            adjacency = collections.defaultdict(set)
            for edge in md.rivers.values():
                adjacency[edge.upstream].add(edge.downstream)
                adjacency[edge.downstream].add(edge.upstream)

            visited = set()
            for start in adjacency:
                if start in visited:
                    continue
                stack, component = [start], set()
                visited.add(start)
                while stack:
                    cur = stack.pop()
                    component.add(cur)
                    for nb in adjacency[cur]:
                        if nb not in visited:
                            visited.add(nb)
                            stack.append(nb)
                comp_edges = sum(
                    1 for edge in md.rivers.values()
                    if edge.upstream in component and edge.downstream in component
                )
                assert comp_edges >= min_length, f"seed {seed}: river component of size {comp_edges} < {min_length}"
                checked += 1
        assert checked > 0, "no river components found across 5 seeds -- test is vacuous"


# --- (c) flux monotone downstream --------------------------------------------


class TestFluxMonotonic:
    def test_flux_never_decreases_downstream(self):
        checked = 0
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            flux_at = {edge.upstream: edge.flux for edge in md.rivers.values()}
            for edge in md.rivers.values():
                if edge.downstream in flux_at:
                    assert flux_at[edge.downstream] >= edge.flux, (
                        f"seed {seed}: flux dropped from {edge.flux} at {edge.upstream} "
                        f"to {flux_at[edge.downstream]} at {edge.downstream}"
                    )
                    checked += 1
        assert checked > 0, "no downstream-downstream pairs found across 5 seeds -- test is vacuous"


# --- (d) boundary rows are river-free ----------------------------------------


class TestBoundaryRowsRiverFree:
    def test_no_same_row_river_edge_at_row_0_or_last_row(self):
        """The precise, provable claim behind design doc §5's "boundary rows
        are river-free by construction" (see rivers.py's module docstring
        and TestJunctionGeometry above): row 0 has no N corner and the last
        row has no S corner, which means no SAME-ROW (E/W) edge exists at
        either boundary row -- a tile IN row 0 or the last row can still be
        one endpoint of a cross-row edge reaching row 1 / the second-to-last
        row, so this checks the precise claim, not "row 0 touches no rivers
        at all".
        """
        same_row_edges = 0
        for seed in range(10):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            rows = md.rows
            for (a, b) in md.rivers:
                if a[0] == b[0]:
                    assert a[0] not in (0, rows - 1), f"seed {seed}: same-row edge {a}-{b} at boundary row"
                    same_row_edges += 1
        # Same-row edges are common INLAND (the interior rows have both a
        # valid N and S corner at every column) -- if none showed up at all
        # across 10 Standard seeds, the boundary-exclusion assertion above
        # would have been vacuously true, so this confirms it wasn't.
        assert same_row_edges > 0, "no same-row river edges seen across 10 seeds -- boundary check was vacuous"


# --- (e) all-land world -------------------------------------------------------


class TestAllLandWorld:
    def test_generation_succeeds_with_empty_rivers_and_no_floodplains(self):
        """Design doc P4 deliverable 8(e): "all-land world (land_percent=1.0)
        -> empty rivers, no Floodplains, generation succeeds." Floodplains
        is structurally impossible here (its own eligibility IS
        river-adjacency, and rivers are empty) — Oasis is NOT asserted
        empty: its eligibility rule is purely local absence-of-water/river/
        neighbor-Oasis, which an all-land world satisfies vacuously
        everywhere, so Oasis legitimately CAN appear (observed during
        implementation; see the P4 report's ambiguities section — the
        design doc does not say "no Oasis" for this case, only "no
        Floodplains").
        """
        md = mapgen.generate(1, DUEL, params={"land_percent": 1.0}, map_type="earthlike")
        assert md.rivers == {}
        assert not np.any(md.feature == "Floodplains")


# --- (f) floodplains determinism ---------------------------------------------


class TestFloodplainsDeterminism:
    def test_floodplains_set_equals_flat_desert_touching_a_river_exactly(self):
        checked_worlds = 0
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            river_touch = rivers.river_adjacent_mask(md.rivers, md.rows, md.cols)
            actual = {
                (r, c) for r in range(md.rows) for c in range(md.cols)
                if md.feature[r, c] == "Floodplains"
            }
            expected = {
                (r, c) for r in range(md.rows) for c in range(md.cols)
                if bool(river_touch[r, c])
                and md.base_terrain[r, c] == "Desert"
                and md.relief[r, c] == "flat"
            }
            assert actual == expected, f"seed {seed}: floodplains set mismatch"
            checked_worlds += 1
        assert checked_worlds == 5


# --- (g) oasis constraints ----------------------------------------------------


class TestOasisConstraints:
    def test_every_oasis_satisfies_all_eligibility_conditions(self):
        checked_oases = 0
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            rows, cols = md.rows, md.cols
            river_touch = rivers.river_adjacent_mask(md.rivers, rows, cols)

            for r in range(rows):
                for c in range(cols):
                    if md.feature[r, c] != "Oasis":
                        continue
                    checked_oases += 1
                    assert check_on("feature", "Oasis", md.base_terrain[r, c], md.relief[r, c], None)
                    assert not river_touch[r, c], f"seed {seed}: Oasis at ({r},{c}) sits on a river edge"
                    for nr, nc in hexmath.adjacent_coords((r, c), rows, cols):
                        assert md.base_terrain[nr, nc] not in WATER_BASES, (
                            f"seed {seed}: Oasis at ({r},{c}) adjacent to water tile ({nr},{nc})"
                        )
                        assert md.feature[nr, nc] not in ("Oasis", "Floodplains"), (
                            f"seed {seed}: Oasis at ({r},{c}) adjacent to {md.feature[nr, nc]} at ({nr},{nc})"
                        )
        # Not asserted > 0: oases are rare by design (~1% of land) and a run
        # of unlucky seeds could legitimately produce zero; the important
        # guarantee is "whenever one exists, it is valid".


# --- (h) resource validity + count band ---------------------------------------


class TestResourceValidity:
    def test_zero_invalid_placements_and_count_in_a_sane_band(self):
        totals = []
        for seed in range(10):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            rows, cols = md.rows, md.cols
            count = 0
            for r in range(rows):
                for c in range(cols):
                    res = md.resource[r, c]
                    if res is None:
                        continue
                    count += 1
                    assert check_on(
                        "resource", res, md.base_terrain[r, c], md.relief[r, c], md.feature[r, c]
                    ), f"seed {seed}: invalid {res} at ({r},{c})"
            totals.append(count)

        mean = sum(totals) / len(totals)
        assert 10 <= mean <= 40, (
            f"mean resource count {mean} outside a sane band (design doc §11 P4 "
            f"deliverable 5's ~15-30 target, seeds: {totals})"
        )

    def test_basic_generator_never_runs_the_regular_resource_stage(self):
        """basic.py's original docstring commitment (design doc §11 P3/P4:
        "No water, no rivers, no resources") still holds for the REGULAR
        resource stage -- `resources.place_resources()` is never wired into
        basic.py (a regression guard against that happening by accident).

        Amended by design doc §11 P5 (basic.py's own updated module
        docstring): starts.py's additive normalization (§6.4) DOES run on
        basic worlds too ("same starts stage" as earthlike, design doc
        §4.1) and may place a FEW bonus resources near a weak start -- at
        most 2 per player (one food, one production). That is nowhere near
        `resources.place_resources()`'s own target density (~15-30 on a
        Standard-sized earthlike map, design doc §11 P4 deliverable 5), so
        bounding the count well below that band still catches the regular
        stage ever getting wired in by accident, without wrongly asserting
        zero.
        """
        num_players = 2
        for seed in range(5):
            md = mapgen.generate(seed, (16, 32), num_players=num_players, map_type="basic")
            count = int(np.sum(md.resource != None))  # noqa: E711 (elementwise is-not-None on an object array)
            assert count <= 2 * num_players, (
                f"seed {seed}: {count} resources on a basic world -- looks like the "
                f"REGULAR resources.place_resources() stage ran, not just start "
                f"normalization's additive bonuses"
            )


# --- (i) fresh water matches its definition ------------------------------------


class TestFreshWater:
    def test_mapdata_fresh_water_matches_the_shared_function(self):
        """Wiring check: earthlike.py actually stores what rivers.fresh_water_mask
        computes (catches e.g. an intermediate variable getting used by mistake)."""
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            expected = rivers.fresh_water_mask(md.rivers, md.base_terrain, md.feature, md.rows, md.cols)
            assert np.array_equal(md.fresh_water, expected)

    def test_fresh_water_matches_the_design_doc_definition_directly(self):
        """Independent per-tile recomputation of design doc §5's definition
        (river-adjacent OR Lake-adjacent-or-on OR Oasis), not a call into
        rivers.fresh_water_mask itself -- verifies the FUNCTION, not just
        that earthlike.py calls it.
        """
        checked = 0
        for seed in range(5):
            md = mapgen.generate(seed, STANDARD, map_type="earthlike")
            rows, cols = md.rows, md.cols
            river_touch = rivers.river_adjacent_mask(md.rivers, rows, cols)
            for r in range(rows):
                for c in range(cols):
                    near_lake = md.base_terrain[r, c] == "Lake" or any(
                        md.base_terrain[nr, nc] == "Lake"
                        for nr, nc in hexmath.adjacent_coords((r, c), rows, cols)
                    )
                    expected = bool(river_touch[r, c]) or near_lake or (md.feature[r, c] == "Oasis")
                    assert bool(md.fresh_water[r, c]) == expected, f"seed {seed} ({r},{c})"
                    checked += 1
        assert checked == 5 * STANDARD[0] * STANDARD[1]


# --- (j) determinism, including flow/flux/resources ---------------------------


class TestDeterminism:
    def test_generate_twice_identical_including_river_flow_flux_and_resources(self):
        md1 = mapgen.generate(555, STANDARD, num_players=6, map_type="earthlike")
        md2 = mapgen.generate(555, STANDARD, num_players=6, map_type="earthlike")

        assert md1.rivers == md2.rivers
        assert md1.rivers, "test is vacuous if seed 555 produced no rivers on a Standard board"
        for edge in md1.rivers.values():
            assert edge.upstream is not None and edge.downstream is not None
            assert isinstance(edge.flux, int)

        assert np.array_equal(md1.base_terrain, md2.base_terrain)
        assert np.array_equal(md1.feature, md2.feature)
        assert np.array_equal(md1.resource, md2.resource)
        assert np.array_equal(md1.fresh_water, md2.fresh_water)
        assert np.any(md1.resource != None)  # noqa: E711


# --- (k) rivers actually exist on earthlike Standard --------------------------


class TestRiversExistOnStandard:
    def test_rivers_nonempty_on_at_least_9_of_10_seeds(self):
        nonempty = sum(
            1 for seed in range(10)
            if mapgen.generate(seed, STANDARD, map_type="earthlike").rivers
        )
        assert nonempty >= 9, f"only {nonempty}/10 Standard seeds produced rivers"


# --- (l) engine wiring: crossing a REAL generated river costs extra -----------


class TestEngineRiverCrossingCost:
    def test_unit_crossing_a_generated_river_pays_crossing_cost(self):
        from civulator.game.environment import GameEnvironment
        from civulator.game.unit import RIVER_CROSSING_COST, WarriorUnit

        for seed in range(20):
            env = GameEnvironment(24, 48, num_players=2, map_type="earthlike", seed=seed)
            if not env.map.rivers:
                continue
            for (a, b) in env.map.rivers:
                tile_a, tile_b = env.map.get_tile(a), env.map.get_tile(b)
                if tile_a.domain != "land" or tile_a.impassable:
                    continue
                if tile_b.domain != "land" or tile_b.impassable:
                    continue
                # Needs to fit a Warrior's 2 movement points alongside the
                # crossing surcharge (design doc D6: additive, no cap) —
                # skip destinations too expensive to reach in one hop at
                # all (e.g. Hills: cost 2 + crossing 1 = 3 > max movement 2)
                # so this test is about the SURCHARGE, not movement budget.
                if tile_b.movement_cost + RIVER_CROSSING_COST > WarriorUnit.MAX_MOVEMENT["Warrior"]:
                    continue
                player = env.players[0]
                warrior = WarriorUnit(player, a)
                player.units.append(warrior)
                env.add_unit_to_tile(warrior, a)

                before = warrior.movement_points
                moved, pos = warrior.move(b, env)
                assert moved and pos == b
                assert warrior.movement_points == before - (tile_b.movement_cost + RIVER_CROSSING_COST)
                return
        pytest.fail("no seed in range(20) produced a land-land river edge usable by a Warrior")


# --- Engine fresh-water surface (design doc §5/§3.4 deliverable 7) ------------


class TestEngineFreshWaterSurface:
    def test_river_endpoint_tiles_report_fresh_water(self):
        from civulator.game.environment import GameEnvironment

        for seed in range(10):
            env = GameEnvironment(24, 48, num_players=2, map_type="earthlike", seed=seed)
            if not env.map.rivers:
                continue
            (a, b) = next(iter(env.map.rivers))
            assert env.map.is_fresh_water(a)
            assert env.map.is_fresh_water(b)
            return
        pytest.fail("no seed in range(10) produced any river")

    def test_is_fresh_water_updates_after_add_river(self):
        from civulator.game.environment import GameEnvironment

        env = GameEnvironment(8, 16, num_players=2, map_type="basic")
        coords_a, coords_b = (4, 8), (4, 9)
        assert not env.map.is_fresh_water(coords_a)
        assert not env.map.is_fresh_water(coords_b)

        env.map.add_river(coords_a, coords_b)

        assert env.map.is_fresh_water(coords_a)
        assert env.map.is_fresh_water(coords_b)
        # an unrelated tile elsewhere on the board is unaffected
        assert not env.map.is_fresh_water((0, 0))


# --- GATE: mapgen purity still holds with the new rivers/resources modules ---


class TestPackagePurityStillHolds:
    """Same subprocess-isolated check as test_mapgen_earthlike.py's
    TestPackagePurity — duplicated here (not imported from there) so this
    file stands alone as the P4 gate check the task description asks for:
    "subprocess purity test must still pass".
    """

    def test_mapgen_core_imports_nothing_from_game_viz_or_agents(self):
        import os
        import subprocess
        import sys

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = (
            "import sys\n"
            "import civulator.mapgen\n"
            "import civulator.mapgen.rivers, civulator.mapgen.resources\n"
            "bad = sorted(m for m in sys.modules if m.startswith(('civulator.game', "
            "'civulator.viz', 'civulator.agents')))\n"
            "print(bad)\n"
            "sys.exit(1 if bad else 0)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=repo_root, capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
