"""MapData — the generator <-> engine/preview/C++ contract (design doc §4.1,
Systems (b)). Every field mapgen produces lives here; fields change only
with a golden re-baseline (D21). Pure: numpy + stdlib only.
"""

import json
from dataclasses import dataclass, field

import numpy as np


@dataclass
class MapData:
    """Everything one call to `mapgen.generate()` produces.

    Grids are all shape (rows, cols), row-major, matching the engine's
    storage convention (project CLAUDE.md: axial (q, r) stored as
    (row=r, col=q)) so `Map.generate_map` can index them directly.

    Attributes:
        base_terrain: (rows, cols) str array -- Grassland/Plains/Desert/
            Tundra/Snow/Coast/Lake/Ocean.
        relief: (rows, cols) str array -- "flat"/"hills"/"mountain". Water
            tiles are always "flat" (design doc §3).
        feature: (rows, cols) object array of str-or-None (<=1 feature/tile).
        resource: (rows, cols) object array of str-or-None. Always all-None
            in 0.6's P3 (resources are P5 scope) -- a clean stub.
        rivers: set of ((row1, col1), (row2, col2)) edges, each pair
            ordered (a < b) the same way `Map.rivers` stores them. Empty in
            P3 (rivers are P4 scope).
        fresh_water: (rows, cols) bool array. All False in P3 (no rivers
            yet to be fresh water adjacent to) -- a clean stub; P4 fills it.
        starts: list of (row, col) candidate start positions, in player
            order. Empty in P3 (starts are P5 scope; `reset` keeps its
            current random placement until then, per design doc §11 P3).
        params: echo of the generation inputs (seed, rows, cols,
            num_players, map_type, and the resolved knob dict actually
            used) -- NOT the live config (design doc §8: world identity is
            manifest-pinned params, never live config); this is that data,
            ready for a future manifest to embed verbatim.
    """

    base_terrain: np.ndarray
    relief: np.ndarray
    feature: np.ndarray
    resource: np.ndarray
    rivers: set
    fresh_water: np.ndarray
    starts: list
    params: dict = field(default_factory=dict)

    @property
    def rows(self):
        return self.base_terrain.shape[0]

    @property
    def cols(self):
        return self.base_terrain.shape[1]

    def canonical_bytes(self) -> bytes:
        """Deterministic byte serialization of every field (design doc §4.1,
        §8: "Canonical serialization helper (stable bytes for future
        SHA-256 goldens)"). A future SHA-256 golden (P8) freezes THIS exact
        byte layout -- treat it as append-only from here: changing the
        layout invalidates every golden that hashed it.

        Fixed field order; string grids as newline-joined UTF-8 rows (a
        missing feature/resource cell serializes as the literal "None", so
        it round-trips distinctly from an actual base-terrain string) --
        this avoids depending on numpy's `.tobytes()` layout for object
        arrays (not stable: it pickles), or on `repr()` (not guaranteed
        stable across numpy versions). `rivers`/`starts` are sorted before
        joining so set/list iteration order never leaks into the hash.
        `params` goes through `json.dumps(..., sort_keys=True, default=str)`
        for the same reason.
        """
        parts = [
            _grid_bytes(self.base_terrain),
            _grid_bytes(self.relief),
            _grid_bytes(self.feature),
            _grid_bytes(self.resource),
            self.fresh_water.astype(np.uint8).tobytes(),
            "|".join(
                f"{a[0]},{a[1]}-{b[0]},{b[1]}" for a, b in sorted(self.rivers)
            ).encode("utf-8"),
            "|".join(f"{r},{c}" for r, c in self.starts).encode("utf-8"),
            json.dumps(self.params, sort_keys=True, default=str).encode("utf-8"),
        ]
        return b"\x00\x00".join(parts)


def _grid_bytes(grid: np.ndarray) -> bytes:
    """One (rows, cols) str/object grid -> stable UTF-8 bytes, row-joined."""
    rows = [
        "\t".join("None" if v is None else str(v) for v in grid[r])
        for r in range(grid.shape[0])
    ]
    return "\n".join(rows).encode("utf-8")


def empty_grids(rows: int, cols: int):
    """(base_terrain, relief, feature, resource) grids, allocated but unfilled.

    base_terrain/relief as numpy `object` arrays (not fixed-width `<U..`)
    so every cell can hold an ordinary python str, matching what
    `Tile.set_layers` and `terrain_model` expect (they compare against
    plain str layer names, not numpy str scalars) -- avoids the subtle
    "np.str_ != str after all" surprise fixed-width string dtypes invite.
    feature/resource start out None (numpy object arrays default-fill to
    None already, but this is explicit).
    """
    base_terrain = np.empty((rows, cols), dtype=object)
    relief = np.full((rows, cols), "flat", dtype=object)
    feature = np.full((rows, cols), None, dtype=object)
    resource = np.full((rows, cols), None, dtype=object)
    return base_terrain, relief, feature, resource


def resolve_size(size, sizes_table=None):
    """(rows, cols) from either an explicit tuple or a named preset (design
    doc §6, §4.1: "size = (rows, cols) tuple or preset name").

    Pure: `sizes_table` is an explicit {name: {"rows":.., "cols":..}} dict
    the CALLER supplies (from config.toml's `[map.sizes.*]`, read once at
    the engine/CLI call boundary) -- mapgen core never reads
    civulator.config itself (design doc §4.1: imports nothing outside
    numpy/stdlib/hexmath/terrain_model), so preset-name lookups must be
    resolved before crossing into `mapgen.generate()`. `mapgen.generate()`
    itself always requires an already-resolved (rows, cols) tuple; this
    helper is what `Map.generate_map` and the preview CLI call first.

    Raises KeyError if `size` is a string not present in `sizes_table` (or
    no table was given at all) -- never silently guesses a size.
    """
    if isinstance(size, str):
        if not sizes_table or size not in sizes_table:
            raise KeyError(f"Unknown map size preset: {size!r}")
        entry = sizes_table[size]
        return int(entry["rows"]), int(entry["cols"])
    rows, cols = size
    return int(rows), int(cols)
