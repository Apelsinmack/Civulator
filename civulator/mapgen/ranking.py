"""Nearest-rank order statistics (design doc §4.2 rule 4) — the ONE place
that turns a continuous field into a percentile threshold or rank. Every
"percent of the map" / "percent of land" knob (sea level, mountain/hill
relief, orogeny mask, biome bands) goes through this module so they share
one tie-breaking discipline (design doc §4.2 rule 6: "total sort keys
everywhere"): ties broken by (row, col), never by numpy sort-algorithm
stability or float-set insertion order, so a result never depends on which
build of numpy computed it. `np.percentile`'s interpolation is explicitly
NOT used anywhere (design doc rule 4) — these are true order statistics on
the actual field values.
"""

import math

import numpy as np


def nearest_rank_threshold(values: np.ndarray, mask: np.ndarray, fraction: float) -> float:
    """The smallest value such that >= `round(fraction * N)` masked cells
    are `>= ` it, where N = count(mask) (design doc §4.2 rule 4). `fraction`
    is a plain ratio in [0, 1] (e.g. `land_percent`).

    Returns +inf if the rounded count is 0 (nothing qualifies -- every
    comparison `value >= threshold` then correctly comes out False) or the
    minimum masked value if `fraction >= 1` (everything qualifies).
    """
    idx = np.argwhere(mask)
    n = len(idx)
    if n == 0:
        return math.inf
    k = round(fraction * n)
    k = max(0, min(n, k))
    if k == 0:
        return math.inf
    vals = values[idx[:, 0], idx[:, 1]]
    order = np.lexsort((idx[:, 1], idx[:, 0], vals))  # ascending (value, row, col)
    return float(vals[order[n - k]])


def percentile_rank_field(values: np.ndarray, mask: np.ndarray = None) -> np.ndarray:
    """(rows, cols) float array: each masked cell's fractional rank among
    masked cells, nearest-rank order (0 < rank <= 1; the lowest masked
    value gets 1/N, the highest gets 1.0). Unmasked cells are 0.0 (callers
    re-check `mask` before trusting a rank; this is climate.py's shared
    building block for `temp_rank`/`moisture_rank`, design doc §4.4).
    """
    rows, cols = values.shape
    if mask is None:
        mask = np.ones((rows, cols), dtype=bool)
    idx = np.argwhere(mask)
    n = len(idx)
    out = np.zeros((rows, cols), dtype=np.float64)
    if n == 0:
        return out
    vals = values[idx[:, 0], idx[:, 1]]
    order = np.lexsort((idx[:, 1], idx[:, 0], vals))  # ascending (value, row, col)
    ranks = np.empty(n, dtype=np.float64)
    ranks[order] = np.arange(1, n + 1, dtype=np.float64) / n
    out[idx[:, 0], idx[:, 1]] = ranks
    return out


def round_log2(n: int) -> int:
    """round(log2(n)) via pure integer arithmetic — no libm (design doc
    §4.2.9): compares n**2 against lo*hi (the geometric mean of the two
    bracketing powers of two, squared to avoid sqrt), which is exactly
    equivalent to comparing log2(n) against their arithmetic mean in
    log-space. `n` must be a positive integer.
    """
    n = int(n)
    lo_exp = n.bit_length() - 1  # floor(log2(n))
    lo = 1 << lo_exp
    hi = lo << 1
    return lo_exp if n * n < lo * hi else lo_exp + 1
