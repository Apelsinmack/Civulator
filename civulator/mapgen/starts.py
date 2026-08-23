"""Starting locations (design doc §6, D13, §11 P5): fertility scoring ->
region division -> d_min placement -> additive normalization ->
`MapData.starts`.

Pure: numpy + stdlib + `civulator.hexmath` + `civulator.terrain_model` (+ this
package's own `resources.RESOURCE_ORDER`) only (design doc §4.1) -- no
`civulator.config`. `[map.starts]`'s weights/thresholds are read by the
CALLER (`Map.generate_map` / the preview CLI) and passed down as `params`,
the same "read config once at the call boundary" contract every other mapgen
stage follows (see `earthlike.py`'s own params handling).

UNLIKE every other per-tile mapgen stage, this one needs NO randomness at all
(no `seeding.stage_seed`/`tile_roll01` calls): every choice below -- which
tile scores best, how a landmass splits, which candidate wins a distance
tie, which tile a normalization bonus lands on -- has an explicit, fully
specified tie-break (design doc §4.2 rule 6: "total sort keys everywhere";
§6 gives the exact tuple for the candidate-ranking case). `seeding.py`
reserves stage id 11 ("starts") in its ledger for documentation completeness;
this module never actually calls `mix64`/`tile_roll01`.

Algorithm (design doc §6, verbatim -- this module follows its numbered list):
  1. Fertility scoring (`tile_fertility`): ring 0-2 weighted composed-yield
     sum (ring 2 at half weight) + fresh-water/coastal bonuses, all dyadic
     weights (design doc §4.2 rule 6) so score sums are exact.
  2. Region division (`divide_into_regions`): landmasses = connected
     land-domain components; players allocated to landmasses by
     largest-remainder apportionment on total fertility; within a
     landmass, recursive fertility-median bisection (`_bisect_region`).
  3. Placement (`place_starts`): best (score, r, q) candidate per region at
     pairwise distance >= d_min from every already-placed start, soft
     crunch penalty, relax-and-retry down to a floor, raising
     `StartPlacementError` if a region is exhausted.
  4. Normalization (`normalize_starts`): additive bonus resources when a
     start's ring-1 food/production falls below a config threshold.

Entry point: `generate_starts(...)` runs all four stages and returns
`(starts, resource)` -- the `MapData.starts` list (design doc: "in player
order" -- see `divide_into_regions`'s docstring for exactly what that order
is, before `GameEnvironment.reset`'s own engine-RNG shuffle scrambles it) and
a NEW resource grid with normalization's bonuses folded in.
"""

import math

import numpy as np

from .. import hexmath
from ..terrain_model import BASE_TABLE, RESOURCE_TABLE, can_enter, compose, matches
from .resources import RESOURCE_ORDER

# --- defaults (mirrored into config.toml's [map.starts], design doc §11 P5
# deliverable 1: "Weights as config keys under [map.starts]") --------------
#
# Magnitude reasoning for the two bonuses (see the P5 implementation report
# for the full derivation): a typical candidate's ring 0-2 yield-only score
# lands roughly in the 15-35 range (most base terrains sum to 0-2 food+
# production; ~18 ring-1/ring-2 tiles contribute). `fresh_water_weight = 8`
# is a strong, but not map-dominating, differentiator at that scale;
# `coastal_weight` is exactly half, per spec. Both are dyadic (design doc
# §4.2 rule 6): 8 = 2**3, 4 = 2**2, 0.5 = 2**-1.
DEFAULT_PARAMS = {
    "ring2_weight": 0.5,
    "fresh_water_weight": 8.0,
    "coastal_weight": 4.0,
    "min_passable_ring1": 3,
    "d_min_players_factor": 3.5,
    "d_min_floor": 3,
    # Normalization thresholds -- see the P5 report / config.toml comment
    # for the Civ6-to-our-yield-scale derivation.
    "food_total_min": 6.0,
    "food_best_min": 18.0 / 7.0,
    "prod_total_min": 0.75,
    "prod_best_min": 0.3,
}

_RESOURCE_NAMES_IN_ORDER = [name for name, _purpose_id in RESOURCE_ORDER]
# Food/production resource priority lists, DERIVED from the single canonical
# `resources.RESOURCE_ORDER` (never a second hardcoded priority list) by
# filtering on which yield axis is positive -- config-driven, so if
# yields ever change in config.toml these lists follow automatically.
_FOOD_RESOURCES = [
    name for name in _RESOURCE_NAMES_IN_ORDER
    if RESOURCE_TABLE.get(name, {}).get("yields", (0, 0))[0] > 0
]
_PROD_RESOURCES = [
    name for name in _RESOURCE_NAMES_IN_ORDER
    if RESOURCE_TABLE.get(name, {}).get("yields", (0, 0))[1] > 0
]

# `_axis_cut`'s bounded connectivity search (performance, not correctness --
# see its docstring): a full exhaustive scan is O(tiles^2) per bisection
# call, fine at Duel/Standard scale but too slow at Large/Huge/Colossal's
# thousand-plus-tile regions. Not config-exposed (a performance knob, not a
# gameplay one) -- tuned during P5 implementation to keep worst-case
# generation time on Colossal in the low single-digit seconds while barely
# moving the fallback-to-_repair_disconnected_cut rate versus an exhaustive scan.
_AXIS_CUT_SEARCH_RADIUS = 150


class StartPlacementError(RuntimeError):
    """Raised when the d_min relax-and-retry ladder is exhausted for some
    region (design doc §6.3/E5: exhausted ladder raises deterministically --
    "no silent degradation" -- this module ALWAYS raises here; it never
    catches or resamples anything itself). Also the exception
    `GameEnvironment._reset_attempt` raises (design doc §3.3/§9.10) if a
    delivered start somehow fails `found_city` -- a contract violation this
    module's own guarantees should make unreachable in practice.

    D26 amendment (§11 P7.5): what happens to this exception once it leaves
    mapgen is now `GameEnvironment.reset`'s decision, not automatically
    fatal. `reset(seed=N)` still lets it propagate unchanged (a specific
    seed either works or fails loudly). Unseeded `reset()` catches it, logs
    a warning, and resamples a fresh world from the engine's own continuing
    RNG stream, bounded by config `[map] max_world_retries` -- see
    `GameEnvironment.reset`'s own docstring for the full policy.
    """


def merge_params(params):
    """`DEFAULT_PARAMS` overridden by `params` (or DEFAULT_PARAMS verbatim
    if `params` is falsy) -- public (not `_`-prefixed) because callers that
    build a `MapData.params` manifest echo (design doc D16) need the fully
    RESOLVED dict, the same way `earthlike.py`/`basic.py` record their own
    fully-merged params rather than the caller's raw override.
    """
    merged = dict(DEFAULT_PARAMS)
    if params:
        merged.update(params)
    return merged


# =====================================================================
# 1. Fertility (design doc §6.1)
# =====================================================================


def _yield_sum_grid(base_terrain, relief, feature, resource, rows, cols):
    """(rows, cols) int64 array: composed food+production, ONE compose()
    call per tile -- not per ring-visit. A tile is looked at as somebody's
    ring-0 once, ring-1 up to 6 times, and ring-2 up to 12 times across all
    candidates on the map, so precomputing this grid once and reusing it via
    plain array lookups avoids large-multiple redundant
    `terrain_model.compose()` calls.
    """
    out = np.zeros((rows, cols), dtype=np.int64)
    for r in range(rows):
        for c in range(cols):
            composed = compose(base_terrain[r, c], relief[r, c], feature[r, c], resource[r, c])
            out[r, c] = composed.yields[0] + composed.yields[1]
    return out


def tile_fertility(coords, yield_sum, fresh_water, base_terrain, rows, cols, p):
    """f(candidate) (design doc §6.1): ring 0-2 weighted composed-yield sum
    (ring 0/1 at weight 1, ring 2 at `p["ring2_weight"]`) + a fresh-water
    bonus (own tile, from `MapData.fresh_water`) + a coastal bonus (any
    ring-1 neighbor is Coast) -- HALF the fresh-water weight, per spec.

    All weights dyadic (design doc §4.2 rule 6): `yield_sum` entries are
    small non-negative ints, so every term added here is an EXACT float64
    value (int * power-of-two, or an int itself) -- the sum is exact and
    order-independent regardless of ring-walk order.

    Defined for ANY land tile (not just start-ELIGIBLE ones, design doc
    §6.1's "reject" rule -- see `is_start_eligible`): region division needs
    a fertility value for every tile in a landmass, including ones (a
    mountain, a cramped peninsula) that could never themselves host a
    capital.
    """
    rings = hexmath.hex_rings(coords, 2, rows, cols)
    score = 0.0
    for tile in rings[0]:
        score += yield_sum[tile]
    for tile in rings[1]:
        score += yield_sum[tile]
    for tile in rings[2]:
        score += yield_sum[tile] * p["ring2_weight"]

    r, c = coords
    if fresh_water[r, c]:
        score += p["fresh_water_weight"]
    if any(base_terrain[tr, tc] == "Coast" for tr, tc in rings[1]):
        score += p["coastal_weight"]
    return score


def _is_settleable(coords, base_terrain, relief, feature, resource):
    r, c = coords
    composed = compose(base_terrain[r, c], relief[r, c], feature[r, c], resource[r, c])
    return composed.domain == "land" and not composed.impassable


def _passable_ring1_count(coords, base_terrain, relief, feature, resource, rows, cols):
    ring1 = hexmath.hex_rings(coords, 1, rows, cols)[1]
    count = 0
    for (r, c) in ring1:
        composed = compose(base_terrain[r, c], relief[r, c], feature[r, c], resource[r, c])
        if can_enter("land", composed):
            count += 1
    return count


def is_start_eligible(coords, base_terrain, relief, feature, resource, rows, cols, p):
    """Design doc §6.1's REJECT rule: must be settleable (land domain, not
    impassable) AND have >= `p["min_passable_ring1"]` land-domain-passable
    ring-1 tiles (tightened from Civ's fraction-based rule: "a start must be
    able to deploy its opening warriors").
    """
    if not _is_settleable(coords, base_terrain, relief, feature, resource):
        return False
    return _passable_ring1_count(
        coords, base_terrain, relief, feature, resource, rows, cols
    ) >= p["min_passable_ring1"]


# =====================================================================
# 2. Region division (design doc §6.2)
# =====================================================================


def _find_landmasses(base_terrain, rows, cols):
    """List of landmasses: each a sorted list of (row, col) land tiles
    (design doc §6.2: "connected land component; hexmath adjacency with
    wrap"). Land membership is DOMAIN, not passability/settleability -- a
    mountain still occupies space inside a continent and can bridge two
    grassland areas into one landmass (design doc §3: domain separates
    land/water; impassable is an orthogonal flag). Flood fill (BFS); the
    CALLER (`divide_into_regions`) imposes a fertility-based processing
    order -- finding components has no natural "player order" of its own.
    """
    domain_land = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            domain_land[r, c] = BASE_TABLE.get(base_terrain[r, c], {}).get("domain") == "land"

    visited = np.zeros((rows, cols), dtype=bool)
    landmasses = []
    for r in range(rows):
        for c in range(cols):
            if not domain_land[r, c] or visited[r, c]:
                continue
            component = []
            stack = [(r, c)]
            visited[r, c] = True
            while stack:
                tr, tc = stack.pop()
                component.append((tr, tc))
                for nr, nc in hexmath.adjacent_coords((tr, tc), rows, cols):
                    if domain_land[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        stack.append((nr, nc))
            component.sort()
            landmasses.append(component)
    return landmasses


def _apportion_players(landmass_fertilities, num_players):
    """Largest-remainder (Hare quota) apportionment (design doc §6.2:
    "players allocated to landmasses proportional to landmass total
    fertility (largest-remainder)"): each landmass first gets
    floor(quota), remaining seats go to the landmasses with the largest
    fractional remainder, ties broken by landmass index ascending -- the
    CALLER (`divide_into_regions`) has already sorted landmasses into a
    fixed fertility-descending order before this runs, so "index" is
    already a deterministic, documented key (design doc §4.2 rule 6).

    Returns a list of per-landmass seat counts, same order/length as
    `landmass_fertilities`.

    FP note (design doc §4.2 rule 6's "keep weights dyadic so score sums
    are exact" applies to `fertility`/`tile_fertility`, the values ranked
    against each other by `_best_candidate`; it does NOT extend to this
    function's `quotas` division): `num_players * f / total` is an ordinary
    float division, not necessarily an exact rational -- fine here, because
    its only consumer is `int(math.floor(q))` and a remainder SORT (a
    discrete decision with its own total order, `_apportion_players`'s own
    tie-break), never a value compared bit-for-bit against another world or
    re-summed into further gameplay state. Deterministic (same inputs,
    same IEEE754 float ops, same result on any platform) is the bar this
    needs to clear, not exact-as-a-fraction.
    """
    total = sum(landmass_fertilities)
    n = len(landmass_fertilities)
    if total <= 0:
        raise StartPlacementError("no landmass carries any fertility -- cannot allocate players")

    quotas = [num_players * f / total for f in landmass_fertilities]
    seats = [int(math.floor(q)) for q in quotas]
    remainder = num_players - sum(seats)

    order = sorted(range(n), key=lambda i: (-(quotas[i] - seats[i]), i))
    for i in order[:remainder]:
        seats[i] += 1
    return seats


def _unroll_cut_column(cols_present, width):
    """The column value that should map to 0 in an unrolled (non-wrapping)
    frame: the column right after the LARGEST circular gap between
    consecutive occupied columns -- the cylinder can only be treated as a
    line by cutting it somewhere nothing occupies (needed so the column
    axis's "extent"/median-cut logic in `_axis_cut` is never fooled by the
    seam). Ties (equal largest gap) broken by preferring the smaller
    candidate cut column (design doc §4.2 rule 6).
    """
    distinct = sorted(set(cols_present))
    if len(distinct) <= 1:
        return distinct[0] if distinct else 0

    best_gap = -1
    best_cut = distinct[0]
    for i, a in enumerate(distinct):
        b = distinct[(i + 1) % len(distinct)]
        gap = (b - a) % width
        if gap == 0:
            gap = width
        if gap > best_gap or (gap == best_gap and b < best_cut):
            best_gap = gap
            best_cut = b
    return best_cut


def _connected_components(tiles, rows, cols):
    """Connected components of `tiles` (a list of (row, col)) under
    land-domain adjacency RESTRICTED to `tiles` itself -- used to detect
    when an axis-aligned cut fractured a side (design doc §6.2 fallback).
    Each component sorted; components sorted by (-len, anchor) so callers
    get a fixed, deterministic processing order (largest first, ties by
    smallest tile).
    """
    tile_set = set(tiles)
    visited = set()
    components = []
    for start in tiles:
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        comp = []
        while stack:
            t = stack.pop()
            comp.append(t)
            for n in hexmath.adjacent_coords(t, rows, cols):
                if n in tile_set and n not in visited:
                    visited.add(n)
                    stack.append(n)
        comp.sort()
        components.append(comp)
    components.sort(key=lambda comp: (-len(comp), comp[0]))
    return components


def _axis_cut(tiles, k_lo, k_hi, fertility, rows, cols):
    """Split `tiles` into (side_lo, side_hi) along whichever axis (row or
    column) has the larger fertility-weighted extent (design doc §6.2:
    "axis with larger fertility-weighted extent, cut at the fertility
    median"), generalized to an UNEQUAL split: the IDEAL cut lands where
    cumulative fertility (walking the sorted axis) first reaches the
    `k_lo / (k_lo + k_hi)` fraction of the total -- exactly the true median
    when k_lo == k_hi (every EVEN player count, the common case), and the
    natural generalization when a landmass splits into an odd count.
    "Fertility-weighted extent" = fertility-weighted variance of the axis
    coordinate; column axis is unrolled at its largest circular gap first
    (`_unroll_cut_column`) so neither "extent" nor "sort by axis" is fooled
    by the wrap seam. Tie between the two axes' extents -> "row" (design
    doc §4.2 rule 6 lexicographic tie-break: a fixed, documented
    convention).

    Searches OUTWARD from the ideal fertility-target index (nearest first,
    ties toward the smaller index -- design doc §4.2 rule 6) for the
    nearest cut index that leaves BOTH sides connected, bounded to
    `_AXIS_CUT_SEARCH_RADIUS` steps each direction (a full exhaustive scan
    is O(tiles) candidates x O(tiles) connectivity check = O(tiles^2) --
    fine for a Duel-sized landmass, far too slow for Large/Huge/Colossal's
    thousand-plus-tile regions; bounding the search keeps generation fast
    while still covering the large majority of practically-occurring
    cases -- see the P5 report). ALWAYS returns a (side_lo, side_hi) pair,
    never None, and both are always non-empty: if nothing within the
    radius keeps both sides connected, returns the IDEAL cut UNCHECKED as
    a best effort -- the caller (`_bisect_region`) re-checks connectivity
    itself and repairs a disconnected result via
    `_repair_disconnected_cut` rather than this function silently
    returning nothing.

    Measured necessity (see the P5 report): the exact fertility-median
    index almost NEVER happens to also be the connectivity-preserving one
    -- hex coastlines from the noise pipeline are bays-and-peninsulas
    irregular, not simple convex blobs, so most exact-median cuts clip an
    isolated tendril on one side or the other. Searching NEAR the median
    for a valid cut (rather than trusting the single exact index) is what
    makes `_repair_disconnected_cut`'s fallback path a true rarity instead
    of the routine case an earlier version of this function hit on the
    large majority of real landmasses.
    """
    k = k_lo + k_hi
    cut_col = _unroll_cut_column([c for _, c in tiles], cols)

    def unrolled(col):
        return (col - cut_col) % cols

    fert = [fertility[t] for t in tiles]
    total_fert = sum(fert)

    # FP note (same scope caveat as `_apportion_players`): `weighted_variance`'s
    # division isn't exact-as-a-fraction, only deterministic -- its one
    # consumer is the row-vs-col AXIS CHOICE below, a discrete decision
    # that never itself becomes stored/compared world state. The plain
    # Python `sum()` calls here (not a numpy array reduction) are exactly
    # what design doc §4.2 rule 8 is fine with: a fixed left-to-right
    # accumulation order, the same on every platform, unlike numpy's
    # shape/build-dependent pairwise summation.
    def weighted_variance(coord_values):
        if total_fert <= 0:
            return 0.0
        mean = sum(w * x for w, x in zip(fert, coord_values)) / total_fert
        return sum(w * (x - mean) ** 2 for w, x in zip(fert, coord_values)) / total_fert

    row_extent = weighted_variance([r for r, _ in tiles])
    col_extent = weighted_variance([unrolled(c) for _, c in tiles])

    axis = "row" if row_extent >= col_extent else "col"
    if axis == "row":
        ordered = sorted(tiles, key=lambda t: (t[0], t[1]))
    else:
        ordered = sorted(tiles, key=lambda t: (unrolled(t[1]), t[0]))

    n = len(ordered)
    target = total_fert * k_lo / k

    # The ideal (unconstrained) index: first prefix whose cumulative
    # fertility reaches `target`.
    cum = 0.0
    ideal_index = n - 1
    for i in range(n - 1):
        cum += fertility[ordered[i]]
        if cum >= target:
            ideal_index = i + 1
            break

    def is_valid(cut_index):
        lo_side, hi_side = ordered[:cut_index], ordered[cut_index:]
        return (
            len(_connected_components(lo_side, rows, cols)) == 1
            and len(_connected_components(hi_side, rows, cols)) == 1
        )

    if is_valid(ideal_index):
        return ordered[:ideal_index], ordered[ideal_index:]

    for delta in range(1, _AXIS_CUT_SEARCH_RADIUS + 1):
        for cut_index in (ideal_index - delta, ideal_index + delta):
            if not (1 <= cut_index <= n - 1):
                continue
            if is_valid(cut_index):
                return ordered[:cut_index], ordered[cut_index:]

    # Nothing within the search radius kept both sides connected -- return
    # the IDEAL cut anyway (best fertility balance), UNCHECKED. Never None:
    # both slices are non-empty by construction (1 <= ideal_index <= n-1),
    # which is exactly what `_repair_disconnected_cut` below needs to stay
    # safe. This is deliberately a "best effort, checked by the caller"
    # result, not a validated one.
    return ordered[:ideal_index], ordered[ideal_index:]


def _repair_disconnected_cut(side_lo, side_hi, rows, cols):
    """Design doc §6.2: "if a cut disconnects a side, fall back to
    connected-component splitting of the larger side" -- repairs an
    `_axis_cut` result where `_connected_components` found more than one
    piece on `side_lo` and/or `side_hi` (its bounded search exhausted
    without finding a connectivity-preserving cut nearby -- design doc §6
    table's own extreme cases, or a landmass shaped so irregularly no
    straight cut bisects it cleanly at all).

    DOCUMENTED INTERPRETATION (the design doc's own words stop at that one
    phrase): take the LARGER of the two sides (by tile count); its BIGGEST
    connected component becomes the new version of that side (contiguous
    by construction); every other fragment of the larger side is
    reassigned to the OTHER (smaller) side. SAFE by construction -- unlike
    an earlier version of this repair that rebuilt from scratch by
    bin-packing components of the WHOLE pre-cut tile set (which produced a
    genuinely EMPTY side whenever that whole set turned out to already be
    one single connected piece, since a lone component has nothing to
    distribute -- caught by `test_terrain_repoint.py`'s existing spawn
    oracle during P5 implementation): both `side_lo`/`side_hi` coming in
    are already non-empty (`_axis_cut` never returns an empty slice), the
    larger side's biggest component is non-empty by definition, and the
    smaller side only ever GAINS tiles here -- so neither output can ever
    be empty.
    """
    if len(side_lo) >= len(side_hi):
        larger, smaller, larger_is_lo = side_lo, side_hi, True
    else:
        larger, smaller, larger_is_lo = side_hi, side_lo, False

    components = _connected_components(larger, rows, cols)
    new_larger = components[0]
    leftover = [t for comp in components[1:] for t in comp]
    new_smaller = sorted(smaller + leftover)

    return (new_larger, new_smaller) if larger_is_lo else (new_smaller, new_larger)


def _bisect_region(tiles, k, fertility, rows, cols):
    """Recursively split `tiles` (a connected tile set) into `k` contiguous
    (or, in the repair path, near-contiguous -- see
    `_repair_disconnected_cut`) groups of ~equal total fertility, one per
    player (design doc §6.2). Processing order (design doc: "one per
    player" -- the eventual `MapData.starts` order): lo-side (from
    `_axis_cut`) fully recursed before hi-side, at every split -- a fixed,
    deterministic in-order traversal.
    """
    if k < 1:
        raise StartPlacementError(f"cannot bisect {len(tiles)} tile(s) into {k} region(s)")
    if len(tiles) < k:
        raise StartPlacementError(
            f"landmass fragment has only {len(tiles)} tile(s) for {k} allocated player(s)"
        )
    if k == 1:
        return [tiles]

    k_lo = k // 2
    k_hi = k - k_lo
    side_lo, side_hi = _axis_cut(tiles, k_lo, k_hi, fertility, rows, cols)

    comps_lo = _connected_components(side_lo, rows, cols)
    comps_hi = _connected_components(side_hi, rows, cols)
    if len(comps_lo) > 1 or len(comps_hi) > 1:
        side_lo, side_hi = _repair_disconnected_cut(side_lo, side_hi, rows, cols)

    return (
        _bisect_region(side_lo, k_lo, fertility, rows, cols)
        + _bisect_region(side_hi, k_hi, fertility, rows, cols)
    )


def divide_into_regions(base_terrain, relief, feature, resource, yield_sum, fresh_water,
                         num_players, rows, cols, p):
    """`(regions, fertility)`: `regions` is a list of `num_players`
    contiguous tile-groups, one per player, in a fixed deterministic
    PROCESSING order (design doc §6.2) -- landmasses ordered by descending
    total fertility (ties by ascending anchor tile, design doc §4.2 rule
    6), each landmass's own allocated regions in the order `_bisect_region`
    naturally produces them. This order becomes `MapData.starts`' own
    "player order" (see `generate_starts`).

    `fertility` is a {(row, col): float} map covering every land tile on
    the map, REFINED to 0 on every tile that fails `is_start_eligible`
    (§6.1's reject rule) -- documented refinement beyond a literal reading
    of design doc §6.2's "proportional to landmass total fertility":
    without it, a thin/scattered landmass whose individual tiles are each
    surrounded mostly by water (few tiles ever qualify as an actual
    settle-candidate) can still accumulate a large RAW fertility total
    from many small contributions and win a player seat -- or win a
    bisected sub-region -- it can then never actually place a start in
    (measured during implementation: 20-40% of seeds failed `place_starts`
    entirely before this fix, across every preset tried). Zeroing
    ineligible tiles' weight steers both landmass apportionment
    (`_apportion_players`) and within-landmass bisection (`_bisect_region`)
    toward territory that can actually host a capital, while leaving every
    tile (eligible or not) in the region for its later worked-tile/
    territory role. `place_starts`' own candidate ranking is UNAFFECTED:
    `_best_candidate` only ever reads this map for tiles that already
    passed `is_start_eligible` themselves, where the refined value is
    identical to the raw `tile_fertility` score.
    """
    landmasses = _find_landmasses(base_terrain, rows, cols)
    if not landmasses:
        raise StartPlacementError("no land tiles at all -- cannot place any start")

    fertility = {}
    landmass_totals = []
    for landmass in landmasses:
        total = 0.0
        for t in landmass:
            f = tile_fertility(t, yield_sum, fresh_water, base_terrain, rows, cols, p)
            if not is_start_eligible(t, base_terrain, relief, feature, resource, rows, cols, p):
                f = 0.0
            fertility[t] = f
            total += f
        landmass_totals.append(total)

    order = sorted(range(len(landmasses)), key=lambda i: (-landmass_totals[i], landmasses[i][0]))
    landmasses = [landmasses[i] for i in order]
    landmass_totals = [landmass_totals[i] for i in order]

    seats = _apportion_players(landmass_totals, num_players)

    regions = []
    for landmass, k in zip(landmasses, seats):
        if k <= 0:
            continue
        regions.extend(_bisect_region(landmass, k, fertility, rows, cols))
    return regions, fertility


# =====================================================================
# 3. Placement (design doc §6.3)
# =====================================================================


def _compute_d_min(num_players, rows, cols, p):
    """design doc §6.3 (verbatim): d_min = round(sqrt(tiles / (players *
    d_min_players_factor))), floored at `p["d_min_floor"]`. The floor
    applies to the STARTING value too, not just the bottom of the
    relax-and-retry ladder in `place_starts` -- "relax... down to floor 3"
    only makes sense as a description if 3 is also the lowest value the
    un-relaxed formula could ever hand back. (The design doc's own §6 size
    table reproduces exactly with NO floor applied at all -- every listed
    preset's raw value is already >= 5 -- so this floor only ever bites
    outside that table, e.g. a deliberately tiny/crowded test world; see
    the P5 report for the floor-value discrepancy against this patch's own
    task brief, which named 5 instead of 3.)
    """
    tiles = rows * cols
    raw = round(math.sqrt(tiles / (num_players * p["d_min_players_factor"])))
    return max(p["d_min_floor"], raw)


def _crunch_penalty(candidate, placed, d_min, cols):
    """Σ max(0, d_min − dist + 1) over already-placed starts (design doc
    §6.3): a small, smoothly-vanishing penalty that discourages crowding
    even among candidates that already clear the hard d_min constraint
    (penalty is 1 exactly at the boundary dist == d_min, 0 from dist ==
    d_min + 1 onward).
    """
    return sum(
        max(0, d_min - hexmath.distance(candidate, other, cols) + 1)
        for other in placed
    )


def _best_candidate(region, placed, d_min, fertility, base_terrain, relief, feature,
                     resource, rows, cols, p):
    """Best (score, r, q) candidate in `region` (design doc §6.3): eligible
    (settleable, >= min_passable_ring1 -- `is_start_eligible`), at hex
    distance >= d_min from EVERY already-placed start, ranked by
    (fertility - soft crunch penalty) descending, ties broken by (r, q)
    ascending (design doc §4.2 rule 6: "start candidates (score, r, q)").
    Returns None if no eligible candidate clears the hard d_min constraint.
    """
    best = None
    best_key = None
    for coords in region:
        if not is_start_eligible(coords, base_terrain, relief, feature, resource, rows, cols, p):
            continue
        if any(hexmath.distance(coords, other, cols) < d_min for other in placed):
            continue
        penalty = _crunch_penalty(coords, placed, d_min, cols)
        score = fertility[coords] - penalty
        key = (-score, coords[0], coords[1])
        if best_key is None or key < best_key:
            best_key = key
            best = coords
    return best


def place_starts(regions, fertility, base_terrain, relief, feature, resource,
                  num_players, rows, cols, p):
    """One (row, col) start per region, in `regions`' own order (design doc
    §6.3): best-candidate selection at the global d_min, relax-and-retry
    (d_min - 1 per retry, floor `p["d_min_floor"]`) PER REGION if no
    candidate clears the current d_min. Each region's search restarts from
    the SAME global d_min -- a hard region does not permanently loosen the
    constraint for regions processed after it (design doc: "per region ...
    relax-and-retry", a region-scoped framing). Raises `StartPlacementError`
    if a region exhausts the ladder (design doc §6.3/E5: deterministic, no
    silent degradation).
    """
    d_min_start = _compute_d_min(num_players, rows, cols, p)
    floor = p["d_min_floor"]

    placed = []
    for region in regions:
        found = None
        d_min = d_min_start
        while True:
            found = _best_candidate(
                region, placed, d_min, fertility, base_terrain, relief, feature,
                resource, rows, cols, p,
            )
            if found is not None or d_min <= floor:
                break
            d_min -= 1
        if found is None:
            raise StartPlacementError(
                f"no eligible start candidate in a region of {len(region)} tile(s) "
                f"even at the relaxed floor d_min={floor}"
            )
        placed.append(found)
    return placed


# =====================================================================
# 4. Normalization (design doc §6.4) -- additive only, never terraform
# =====================================================================


def _ring1_totals(coords, base_terrain, relief, feature, resource, rows, cols):
    """(total_food, best_food, total_prod, best_prod) over JUST ring-1
    (design doc §6.4: Civ's own thresholds are "over 6 tiles", the ring-1
    tile count -- NOT the ring 0-2 weighted `tile_fertility` score used for
    candidate ranking, a deliberately different, simpler metric).
    """
    ring1 = hexmath.hex_rings(coords, 1, rows, cols)[1]
    total_food = total_prod = 0
    best_food = best_prod = 0
    for (r, c) in ring1:
        composed = compose(base_terrain[r, c], relief[r, c], feature[r, c], resource[r, c])
        food, prod = composed.yields
        total_food += food
        total_prod += prod
        best_food = max(best_food, food)
        best_prod = max(best_prod, prod)
    return total_food, best_food, total_prod, best_prod


def _find_normalization_tile(coords, resource_grid, base_terrain, relief, feature,
                              candidate_resources, rows, cols):
    """Best eligible ring-1/ring-2 tile for one axis (food or production) of
    normalization (design doc §6.4): ring-1 searched FULLY before ring-2
    (ring distance is the primary "best" preference), each ring's tiles in
    fixed sorted (row, col) order (from `hexmath.hex_rings`), each tile
    checked against `candidate_resources` in THEIR fixed priority order
    (`_FOOD_RESOURCES`/`_PROD_RESOURCES`, themselves derived from the single
    canonical `resources.RESOURCE_ORDER` -- never a second hardcoded list).
    First (tile, resource) match wins. A tile already carrying a resource is
    never a candidate (additive only, never overwrite).

    Returns (row, col, resource_name), or None if nothing is eligible.
    """
    rings = hexmath.hex_rings(coords, 2, rows, cols)
    for ring in (rings[1], rings[2]):
        for (r, c) in ring:
            if resource_grid[r, c] is not None:
                continue
            base, relief_here, feat = base_terrain[r, c], relief[r, c], feature[r, c]
            for name in candidate_resources:
                entry = RESOURCE_TABLE.get(name, {})
                if matches(entry.get("on"), base, relief_here, feat):
                    return r, c, name
    return None


def normalize_starts(starts, base_terrain, relief, feature, resource, rows, cols, p):
    """Additive-only normalization (design doc §6.4): for each start, IN
    ORDER (design doc §4.2 rule 3 names "start normalization" as one of the
    two genuinely sequential mapgen stages), place a food bonus resource if
    ring-1 total or best food is below threshold, then -- on the possibly-
    updated grid -- a production bonus resource under the same rule.
    Processing starts sequentially (rather than independently) means two
    starts with overlapping ring-1/ring-2 neighborhoods never double-claim
    one tile.

    Returns a NEW resource grid (the input is never mutated in place --
    same copy-then-return convention as `features.py`'s
    apply_floodplains/place_oasis).
    """
    resource = resource.copy()
    for coords in starts:
        total_food, best_food, total_prod, best_prod = _ring1_totals(
            coords, base_terrain, relief, feature, resource, rows, cols
        )

        if total_food < p["food_total_min"] or best_food < p["food_best_min"]:
            found = _find_normalization_tile(
                coords, resource, base_terrain, relief, feature, _FOOD_RESOURCES, rows, cols
            )
            if found is not None:
                r, c, name = found
                resource[r, c] = name

        # total_prod/best_prod are unaffected by the food placement above
        # (food resources never carry production yields), so they do not
        # need recomputing -- only the eligibility SEARCH below needs the
        # just-updated grid, so that it cannot double-claim a tile the food
        # pass just used.
        if total_prod < p["prod_total_min"] or best_prod < p["prod_best_min"]:
            found = _find_normalization_tile(
                coords, resource, base_terrain, relief, feature, _PROD_RESOURCES, rows, cols
            )
            if found is not None:
                r, c, name = found
                resource[r, c] = name

    return resource


# =====================================================================
# Entry point
# =====================================================================


def generate_starts(base_terrain, relief, feature, resource, fresh_water,
                     num_players, rows, cols, params=None):
    """`MapData.starts` (design doc §6, D13, §11 P5): fertility -> regions ->
    d_min placement -> additive normalization, run against the FINAL
    generated grids (after every other stage, resources included -- design
    doc §4.2 rule 2's pinned DAG puts "starts" last).

    Returns `(starts, resource)`: `starts` a list of `num_players` (row,
    col) tuples in the deterministic region-processing order documented on
    `divide_into_regions` -- this is what `MapData.starts`'s own docstring
    calls "player order", NOT the order players end up assigned to them
    (that is `GameEnvironment.reset`'s own engine-RNG shuffle, design doc
    §6.5). `resource` is a NEW grid (normalization's additive bonus
    resources folded in) that callers must use in place of their own
    pre-starts resource grid.
    """
    p = merge_params(params)
    yield_sum = _yield_sum_grid(base_terrain, relief, feature, resource, rows, cols)

    regions, fertility = divide_into_regions(
        base_terrain, relief, feature, resource, yield_sum, fresh_water,
        num_players, rows, cols, p,
    )
    starts = place_starts(
        regions, fertility, base_terrain, relief, feature, resource, num_players, rows, cols, p,
    )
    resource = normalize_starts(starts, base_terrain, relief, feature, resource, rows, cols, p)
    return starts, resource
