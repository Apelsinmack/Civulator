"""Rivers via corner-junction flow accumulation (design doc §5, D12, D23,
§11 P4) — corner-junction graph -> ε-Planchon–Darboux sink fill -> flow
direction -> integer flux accumulation -> nearest-rank selection ->
MapData.rivers. Also the fresh-water definition (§5, §3.4), reused verbatim
by `civulator.game.map.Map` (design doc: "surfaced on Map as the engine's
only fresh-water query" — ONE definition, not two).

Pure: numpy + stdlib + `civulator.hexmath` only (no `civulator.config`,
same purity contract as every other mapgen module, design doc §4.1).

--------------------------------------------------------------------------
The corner-junction graph (design doc §5: "every tile owns its N and S
corners")
--------------------------------------------------------------------------
Rendering is forced pointy-top (design doc D24/§7.5): each hex has exactly
two vertices that sit directly above/below its center — the "N corner" (top)
and "S corner" (bottom) — each shared by exactly 3 hexes:

    N corner of (r, q): shared by (r, q), its NW neighbor (r-1, q), and its
        NE neighbor (r-1, q+1). Exists only if r-1 >= 0 (row 0 has no N
        corner — nothing is above it).
    S corner of (r, q): shared by (r, q), its SW neighbor (r+1, q-1), and
        its SE neighbor (r+1, q). Exists only if r+1 <= rows-1 (the last
        row has no S corner).

Every OTHER vertex in the grid (the 4 "side" corners of a hexagon) is
provably the tracked N-or-S corner of a DIFFERENT nearby tile (worked out
geometrically during implementation — see the P4 report), so enumerating
every tile's N and S corner this way covers every interior vertex of the
whole grid exactly once, with no double-counting — this is the precise
meaning of "boundary rows are river-free by construction" (§5): row 0's N
corner and row (rows-1)'s S corner are the ONLY corner instances that don't
exist, which in turn means no same-row (E/W) edge exists at row 0 or row
(rows-1) (both of a same-row edge's 2 endpoint junctions turn out to
require exactly one N-corner-at-that-row and one S-corner-at-that-row,
worked out below) — tiles IN those rows can still be an endpoint of a
cross-row river edge reaching row 1 / row (rows-2).

Each junction touches exactly 3 tiles and has up to 3 neighbor junctions —
one across each of the 3 edges radiating from it, each such edge being the
shared border of exactly 2 of those 3 tiles. This module derives junction
adjacency GENERICALLY (any two junctions that share exactly 2 of their 3
touching tiles are neighbors, connected by the edge between those 2 tiles)
rather than by hand-transcribed direction formulas — self-verifying by
construction (a transcription bug would show up as missing/extra edges,
not silently wrong ones) and directly gives the tile-pair for every
junction-junction edge, which is exactly `MapData.rivers`' key shape.
"""

import heapq
import math
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from .. import hexmath
from .seeding import (
    PURPOSE_JUNCTION_JITTER_N,
    PURPOSE_JUNCTION_JITTER_S,
    STAGE_RIVERS,
    stage_seed,
    tile_roll01,
)

# Fixed-point scale for flux accumulation (design doc §4.2 rule 8 / §4.2.8):
# raw moisture (an fBm field, roughly within [-2, 2] for the default 4-octave
# moisture stage — amplitudes 1 + 0.5 + 0.25 + 0.125 = 1.875 at most) is
# clamped to >= 0 (flux is a physical accumulation — "how much water passes
# this edge" can't be negative, design doc §5; raw moisture can be, being an
# unclamped fBm field used elsewhere only for RANKING) then multiplied by
# this scale and rounded to the nearest integer ONCE per tile; every
# downstream sum from then on is exact integer addition (no float drift
# possible) — the "integer-scaled moisture" §4.2.8 asks for. 10_000 gives 4
# decimal digits of moisture precision, comfortably more than the noise
# field's own effective resolution, with headroom against overflow that
# doesn't matter anyway (Python ints are arbitrary-precision).
FLUX_SCALE = 10_000

# Not read from config.toml directly (mapgen core takes no config
# dependency, design doc §4.1) — mirrored into config.toml's
# `[map.earthlike]` as `river_pd_epsilon`/`river_altitude_jitter`
# (earthlike.DEFAULT_PARAMS is the merge point, same pattern as every other
# knob in that module). Values chosen and reported in the P4 implementation
# report: the smoothed elevation field this module receives is O(1) in
# magnitude (continentalness + amp*orogeny*ridged, amp default 1.5) so both
# constants sit many orders of magnitude below it.
DEFAULT_PD_EPSILON = 1e-4        # ε: Planchon-Darboux sink-fill step (design doc §4.2 rule 5)
DEFAULT_ALTITUDE_JITTER = 1e-7   # δ: per-junction altitude jitter magnitude, δ << ε


@dataclass(frozen=True)
class RiverEdge:
    """Flow direction + flux for one river edge (design doc §5, P4).

    `upstream`/`downstream`: the two corner JUNCTIONS this edge connects,
    each a (row, col, "N"|"S") triple (see this module's docstring) — NOT
    tile coordinates. A river flows ALONG the shared border between its two
    tiles, not INTO either one, so junction identity is the only physically
    correct "flow direction" to store. `None` for edges added directly via
    `Map.add_river`'s hand-built-edge API (tests before/without real
    generated flow data).

    `flux`: the integer-scaled accumulated flux carried across this edge —
    the upstream junction's total accumulated flux at selection time (0 for
    hand-built edges).
    """

    upstream: tuple | None
    downstream: tuple | None
    flux: int


# =====================================================================
# Corner-junction graph
# =====================================================================


def _s_corner_tiles(r, q, rows, width):
    """(self, SW, SE) tiles touching (r, q)'s S corner, or None if r is the
    last row (design doc §5: the owning tile's SW/SE neighbors would be
    off-map).
    """
    if r + 1 > rows - 1:
        return None
    return ((r, q), (r + 1, (q - 1) % width), (r + 1, q))


def _n_corner_tiles(r, q, rows, width):
    """(self, NW, NE) tiles touching (r, q)'s N corner, or None if r is the
    first row.
    """
    if r - 1 < 0:
        return None
    return ((r, q), (r - 1, q), (r - 1, (q + 1) % width))


def all_junctions(rows, width):
    """{(row, col, "N"|"S"): (tile1, tile2, tile3)} for every valid junction
    (design doc §5). Public (not underscore-prefixed): a meaningful,
    independently-testable geometric primitive — see
    tests/test_mapgen_rivers.py's hand-checked examples.
    """
    junctions = {}
    for r in range(rows):
        for q in range(width):
            s = _s_corner_tiles(r, q, rows, width)
            if s is not None:
                junctions[(r, q, "S")] = s
            n = _n_corner_tiles(r, q, rows, width)
            if n is not None:
                junctions[(r, q, "N")] = n
    return junctions


def junction_adjacency(junctions):
    """(neighbors, edge_tile_pair): junction adjacency derived GENERICALLY
    from shared touching-tile pairs (module docstring) rather than
    hand-transcribed direction formulas.

    neighbors: {junction_id: [neighbor_junction_id, ...]} (<= 3 entries).
    edge_tile_pair: {frozenset({j1, j2}): (tile_a, tile_b)} (tile_a < tile_b)
        — the tile-pair edge each junction-junction edge corresponds to;
        exactly `MapData.rivers`' key shape (design doc §5: "tile-pair
        edges").

    Every physical hex edge has exactly 2 endpoint vertices, so a given
    tile-pair can be shared by at most 2 junctions — asserted defensively
    (a violation would mean the touching-tile derivation above is wrong).
    """
    pair_owners = defaultdict(list)
    for jid, tiles in junctions.items():
        a, b, c = tiles
        for pair in (frozenset((a, b)), frozenset((a, c)), frozenset((b, c))):
            pair_owners[pair].append(jid)

    neighbors = {jid: [] for jid in junctions}
    edge_tile_pair = {}
    for pair, owners in pair_owners.items():
        assert len(owners) <= 2, f"tile-pair {pair} shared by >2 junctions: {owners}"
        if len(owners) == 2:
            j1, j2 = owners
            neighbors[j1].append(j2)
            neighbors[j2].append(j1)
            ta, tb = sorted(pair)
            edge_tile_pair[frozenset((j1, j2))] = (ta, tb)
    return neighbors, edge_tile_pair


# =====================================================================
# Junction altitude (design doc §5: "min of its <=3 touching tiles +
# deterministic jitter")
# =====================================================================


def _junction_altitudes(junctions, elevation, master_seed, jitter_delta):
    """{junction_id: float}. `elevation`: the PRE-THRESHOLD continuous
    field (earthlike.py's `smoothed`, after talus smoothing, before the
    nearest-rank land/mountain/hill cuts — design doc §5 is explicit:
    "(pre-threshold continuous) elevation").

    Jitter is `(roll*2-1) * delta` — zero-centered in [-delta, delta), a
    per-junction coordinate hash (design doc §4.2 rule 3) keyed by (r, q,
    N-or-S) via two purpose ids so a tile's N and S corner jitter
    independently (module docstring, PURPOSE_JUNCTION_JITTER_N/S). Purpose
    of the jitter: break exact ties between junctions whose 3 touching
    tiles happen to yield the same min() (e.g. two junctions sharing 2 of
    their 3 tiles) so sink-fill/flow-direction never face a genuine
    floating-point tie.
    """
    seed = stage_seed(master_seed, STAGE_RIVERS)
    altitude = {}
    for (r, q, kind), tiles in junctions.items():
        base_alt = min(elevation[t[0], t[1]] for t in tiles)
        purpose = PURPOSE_JUNCTION_JITTER_N if kind == "N" else PURPOSE_JUNCTION_JITTER_S
        roll = tile_roll01(seed, r, q, purpose)
        altitude[(r, q, kind)] = base_alt + (roll * 2.0 - 1.0) * jitter_delta
    return altitude


# =====================================================================
# ε-variant Planchon-Darboux sink fill (design doc §4.2 rule 5, §5),
# implemented as priority-flood (Barnes et al.) — the efficient equivalent:
# expand outward from the ocean-seeded frontier in ascending filled-altitude
# order, always raising a cell to at least (source + epsilon) so it never
# ties its filler, guaranteeing every reached junction has a strictly lower
# neighbor (proof in the P4 report) except the seeds themselves.
# =====================================================================


def _sink_fill(seed_junctions, neighbors, altitude, epsilon):
    """{junction_id: filled_altitude} for every junction reachable from
    `seed_junctions` (the whole graph, in practice — the junction adjacency
    graph is fully connected, mirroring the tile grid's own connectivity).
    Total sort key (design doc §4.2 rule 6): heap entries are
    `(candidate_altitude, row, col, kind)` — (row, col, kind) alone already
    uniquely identifies a junction, so ties in altitude are broken
    deterministically without needing a redundant tie-breaker.
    """
    filled = {}
    heap = []
    for jid in seed_junctions:
        filled[jid] = altitude[jid]
        heapq.heappush(heap, (filled[jid], jid[0], jid[1], jid[2]))

    visited = set()
    while heap:
        f, r, q, kind = heapq.heappop(heap)
        jid = (r, q, kind)
        if jid in visited:
            continue
        visited.add(jid)
        for nb in neighbors[jid]:
            if nb in visited:
                continue
            candidate = max(altitude[nb], f + epsilon)
            if nb not in filled or candidate < filled[nb]:
                filled[nb] = candidate
                heapq.heappush(heap, (candidate, nb[0], nb[1], nb[2]))
    return filled


# =====================================================================
# Flow direction + integer flux accumulation (design doc §5)
# =====================================================================


def _flow_directions(junctions, neighbors, filled_altitude):
    """{junction_id: downstream_junction_id or None}. Each junction flows to
    its lowest STRICTLY lower neighbor (design doc §5); total sort key
    `(altitude, r, q, N/S)` breaks ties among equally-low candidates.
    Junctions the sink fill never reached (should not happen — the junction
    graph is fully connected — kept defensive) are skipped entirely.
    """
    downstream = {}
    for jid in junctions:
        if jid not in filled_altitude:
            continue
        alt = filled_altitude[jid]
        candidates = [
            nb for nb in neighbors[jid]
            if nb in filled_altitude and filled_altitude[nb] < alt
        ]
        if not candidates:
            downstream[jid] = None
            continue
        candidates.sort(key=lambda nb: (filled_altitude[nb], nb[0], nb[1], nb[2]))
        downstream[jid] = candidates[0]
    return downstream


def _local_flux(junctions, filled_altitude, raw_moisture, scale):
    """{junction_id: int} — each reached junction's OWN contribution before
    accumulation: the integer-scaled, clamped->=0 sum of raw moisture over
    its touching tiles (design doc §4.2.8; module-level FLUX_SCALE docstring
    explains the clamp and the scale choice).
    """
    local = {}
    for jid, tiles in junctions.items():
        if jid not in filled_altitude:
            continue
        total = 0
        for (r, c) in tiles:
            total += int(round(max(0.0, float(raw_moisture[r, c])) * scale))
        local[jid] = total
    return local


def _flux_accumulation(local_flux, downstream, filled_altitude):
    """{junction_id: int} — `local_flux` propagated downstream (design doc
    §5: "flux accumulates ... downstream"). Processed in DESCENDING total-
    sort-key order (§4.2 rule 6) so every junction's upstream contributors
    (strictly higher altitude, by the flow rule) are already folded in by
    the time it is processed — a single linear pass, no fixed point needed
    (the flow graph is a forest: each junction has at most one downstream
    target). Integer addition throughout: exact, order-of-summation-proof.
    """
    order = sorted(local_flux, key=lambda j: (filled_altitude[j], j[0], j[1], j[2]), reverse=True)
    flux = dict(local_flux)
    for jid in order:
        d = downstream.get(jid)
        if d is not None and d in flux:
            flux[d] += flux[jid]
    return flux


# =====================================================================
# Selection: nearest-rank flux threshold + minimum-length suppression
# (design doc §5)
# =====================================================================


def _nearest_rank_edge_threshold(ordered_values, fraction):
    """Nearest-rank threshold (design doc §4.2 rule 4) over a sequence of
    values in a FIXED, deterministic order (the caller's responsibility —
    see `_sorted_edge_items`): the smallest value such that >=
    round(fraction * N) entries are >= it.

    Not `ranking.nearest_rank_threshold`: that helper is shaped for (row,
    col) GRID populations (its own docstring: "every 'percent of the map'
    knob") and ties break by (row, col); river edges are a different
    population (junction-pairs, not tiles) with their own natural total
    order, so this mirrors that helper's exact algorithm/discipline
    (same k formula, same "ascending sort, take the n-k'th" construction)
    adapted to a plain ordered sequence instead of a grid.
    """
    n = len(ordered_values)
    if n == 0:
        return math.inf
    k = round(fraction * n)
    k = max(0, min(n, k))
    if k == 0:
        return math.inf
    order = sorted(range(n), key=lambda i: (ordered_values[i], i))  # ascending (value, fixed index)
    return ordered_values[order[n - k]]


def _sorted_edge_items(downstream, flux):
    """[((upstream, downstream), flux_value), ...] in a fixed, deterministic
    order (ascending (upstream_junction, downstream_junction) tuples — both
    already (row, col, kind) triples, directly comparable) — independent of
    dict iteration order, giving `_nearest_rank_edge_threshold`'s fixed-
    index tie-break a reproducible meaning.
    """
    pairs = sorted((jid, d) for jid, d in downstream.items() if d is not None)
    return [(p, flux[p[0]]) for p in pairs]


def _suppress_short_rivers(directed_edges, min_length):
    """Keep only edges belonging to a weakly-connected component (via shared
    junctions) of size >= `min_length` (design doc §5: "rivers shorter than
    river_min_length edges suppressed") — component MEMBERSHIP is a
    property of the graph, not of traversal order (same "flood fill --
    component-based, order-independent" discipline as
    elevation.py's `_water_components`), so the KEPT set never depends on
    scan order even though this uses a plain stack-based traversal.
    """
    adjacency = defaultdict(set)
    for (j1, j2) in directed_edges:
        adjacency[j1].add(j2)
        adjacency[j2].add(j1)

    visited = set()
    kept = []
    for start in adjacency:
        if start in visited:
            continue
        component = set()
        stack = [start]
        visited.add(start)
        while stack:
            cur = stack.pop()
            component.add(cur)
            for nb in adjacency[cur]:
                if nb not in visited:
                    visited.add(nb)
                    stack.append(nb)
        component_edges = [
            e for e in directed_edges if e[0] in component and e[1] in component
        ]
        if len(component_edges) >= min_length:
            kept.extend(component_edges)
    return kept


# =====================================================================
# Public entry point
# =====================================================================


def generate_rivers(smoothed_elevation, water_base, raw_moisture, master_seed, params, rows, cols):
    """The rivers stage (design doc §5, §11 P4): corner-junction flow
    accumulation -> {tile_pair: RiverEdge}.

    Args:
        smoothed_elevation: (rows, cols) float — pre-threshold continuous
            elevation (earthlike.py's `smoothed`).
        water_base: (rows, cols) object — None on land, else "Coast"/
            "Lake"/"Ocean" (earthlike.py's `water_base`, from
            elevation.classify_water — computed before rivers in the pinned
            DAG, design doc §4.2 rule 2).
        raw_moisture: (rows, cols) float — BEFORE the river bonus (design
            doc §5: "flux from RAW moisture").
        params: resolved earthlike params dict; reads "river_percent",
            "river_min_length", "river_pd_epsilon", "river_altitude_jitter".

    Returns:
        {} if there is no ocean junction anywhere on the map (design doc §5
        precondition: "an all-land world (basic, or land_percent = 1.0)
        skips the river stage entirely" — basic never calls this at all;
        earthlike's land_percent=1.0 case is what actually exercises this
        return path). Otherwise {(tile_a, tile_b): RiverEdge}, tile_a < tile_b.
    """
    junctions = all_junctions(rows, cols)
    if not junctions:
        return {}
    neighbors, edge_tile_pair = junction_adjacency(junctions)

    ocean_seeds = [
        jid for jid, tiles in junctions.items()
        if any(water_base[t[0], t[1]] == "Ocean" for t in tiles)
    ]
    if not ocean_seeds:
        return {}

    altitude = _junction_altitudes(
        junctions, smoothed_elevation, master_seed, params["river_altitude_jitter"]
    )
    filled = _sink_fill(ocean_seeds, neighbors, altitude, params["river_pd_epsilon"])
    downstream = _flow_directions(junctions, neighbors, filled)
    local_flux = _local_flux(junctions, filled, raw_moisture, FLUX_SCALE)
    flux = _flux_accumulation(local_flux, downstream, filled)

    edge_items = _sorted_edge_items(downstream, flux)
    if not edge_items:
        return {}
    values = [v for _, v in edge_items]
    # `river_percent` passed DIRECTLY as the selected fraction (matching
    # ranking.nearest_rank_threshold's own convention, verified against its
    # existing land_percent/mountain_percent callers in elevation.py: the
    # fraction argument IS the fraction that ends up >= the returned
    # threshold). Design doc §5 phrases this as "above the (1-river_percent)
    # nearest-rank quantile" -- statistics-quantile language for the exact
    # same cutoff value ("above the 0.82 quantile" = "in the top 18%"), not
    # an instruction to pass (1-river_percent) into a top-fraction function.
    threshold = _nearest_rank_edge_threshold(values, params["river_percent"])
    selected = [pair for pair, v in edge_items if v >= threshold]

    kept = _suppress_short_rivers(selected, params["river_min_length"])

    rivers = {}
    for (j_up, j_down) in kept:
        tile_pair = edge_tile_pair[frozenset((j_up, j_down))]
        rivers[tile_pair] = RiverEdge(upstream=j_up, downstream=j_down, flux=flux[j_up])
    return rivers


# =====================================================================
# Fresh water (design doc §5, §3.4)
# =====================================================================


def river_adjacent_mask(rivers, rows, cols):
    """(rows, cols) bool: tiles touching >= 1 river edge.

    The narrower, EARLIER-available piece of the full fresh-water
    definition (see `fresh_water_mask`): this is what feeds the river
    moisture bonus (design doc §5 / P4 deliverable 2: "+river_moisture_bonus
    where river-adjacent") immediately after the rivers stage, well before
    base_terrain/feature exist (biomes and Oasis come later in the pinned
    DAG, design doc §4.2 rule 2) — computing the FULL fresh-water mask that
    early is impossible (it needs Oasis, which needs biomes, which is what
    the moisture bonus is an input to). Also reused as Floodplains'
    river-adjacency eligibility condition (design doc §5).
    """
    mask = np.zeros((rows, cols), dtype=bool)
    for (a, b) in rivers:
        mask[a[0], a[1]] = True
        mask[b[0], b[1]] = True
    return mask


def fresh_water_mask(rivers, base_terrain, feature, rows, cols):
    """MapData.fresh_water (design doc §5, §3.4): a tile is fresh water iff
    it is adjacent to a river edge, or adjacent to (or on) Lake, or carries
    Oasis. Computed once, at the END of the earthlike pipeline (needs the
    FINISHED base_terrain and feature grids — Oasis is placed after
    floodplains, near the end of the DAG) and reused verbatim by
    `civulator.game.map.Map` (design doc §3.4: "surfaced on Map as the
    engine's only fresh-water query") so there is exactly one fresh-water
    definition, not two.
    """
    mask = river_adjacent_mask(rivers, rows, cols)

    is_lake = base_terrain == "Lake"
    mask = mask | is_lake
    for dr, dc in hexmath.HEX_DIRECTIONS:
        neighbor_lake = np.roll(is_lake, shift=(-dr, -dc), axis=(0, 1))
        valid = np.ones((rows, cols), dtype=bool)
        if dr > 0:
            valid[rows - dr:, :] = False
        elif dr < 0:
            valid[: -dr, :] = False
        mask = mask | (neighbor_lake & valid)

    mask = mask | (feature == "Oasis")
    return mask
