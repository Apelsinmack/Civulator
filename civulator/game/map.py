"""Hex grid map with cylindrical wrapping.

Coordinate system: axial (q, r) stored as (row, col) in a 2D array.
The array is a skewed rectangle — this is intentional and accepted.
Distance = max(|dq|, |dr|, |dq + dr|) with cylindrical wrapping on q-axis (columns).
"""

import itertools
import os
import sys

import numpy as np

from .. import hexmath, mapgen
from ..hexmath import HEX_DIRECTIONS  # re-exported: civulator.agents.networks imports it from here
from ..rng import PortableRNG
from ..terrain_model import can_enter

from .tile import Tile

# Try to load C++ module for fast pathfinding
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'cpp', 'build', 'Release'))
    import civulator_core
    HAS_CPP_CORE = True
except ImportError:
    HAS_CPP_CORE = False

# A* adapter encoding: the C++ hex_astar wire format treats cost >= 99 as
# blocked (design doc §3.3). Only the cost-grid builder writes it, and only the
# two A* implementations read it — no gameplay code compares magic costs.
BLOCKED_COST = 99.0


class Map:
    """Represents the game map composed of hex tiles."""

    # Process-unique map_uid source (design doc §3.4): id() reuse after GC would
    # let two different Map objects alias the same cache key, which a plain
    # id()-keyed cache cannot detect. Nothing reads map_uid/terrain_epoch yet in
    # P1 — the caches they will key (LoS, cost grids, encoder layers) re-point
    # to them in P2a.
    _uid_counter = itertools.count()

    def __init__(self, n_rows, m_columns, rng=None):
        self.n = n_rows
        self.m = m_columns
        self.tiles = np.empty((self.n, self.m), dtype=object)
        # {(coords1, coords2): mapgen.rivers.RiverEdge} (design doc §5, P4)
        # — a dict (not a set) so each edge carries flow direction + flux;
        # has_river_between/draw_river_edges/add_river all only ever touch
        # the keys, which iterate/compare identically to the old set of
        # plain tile-pair tuples (see add_river/has_river_between below).
        self.rivers = {}
        # Terrain/feature randomness draws from here; pass the owning
        # GameEnvironment's rng for reproducible maps.
        self.rng = rng if rng is not None else PortableRNG()
        self.map_uid = next(Map._uid_counter)
        self.terrain_epoch = 0
        # Terrain-derived caches, all keyed by (map_uid, terrain_epoch) per
        # design doc §3.4 — set_layers bumps the epoch and they rebuild.
        self._visible_cache = {}
        self._visible_cache_epoch = 0
        self._cost_grids = {}
        self._fresh_water_cache = None
        self._fresh_water_cache_epoch = None

    def generate_map(self, map_type="basic", num_players=2):
        """Generate a map via `civulator.mapgen` (design doc §4.1, §11 P3).

        Draws exactly ONE master seed from `self.rng` (`civulator.rng.
        PortableRNG`, shared with the owning `GameEnvironment` — design doc
        §4.2.1: "reset(seed) makes ONE documented draw from PortableRNG").
        Everything mapgen does with it from there is pure integer/coordinate
        hashing (`mapgen.seeding.mix64`), never a further stream draw (D19)
        — this is the only place `self.rng` is touched during world
        synthesis. Unseeded resets keep working because `self.rng`'s stream
        simply continues from wherever the previous episode left it (§4.2.1:
        "unseeded resets draw the next master from the engine stream"),
        which is exactly what `tests/test_determinism.py`'s seeded-then-
        unseeded replay sequence exercises.

        Reads config.toml ONCE here — the "call boundary" mapgen's own
        purity contract expects (design doc §4.1: "generate must be pure
        given its inputs — read config once at call boundary, pass down")
        — and translates it into the explicit `params` dict each generator
        expects; `civulator.mapgen` itself never imports `civulator.config`
        (so tests can pin exact params without touching global config,
        design doc §8/D21).

        REPLACES the P2a interim shim wholesale (`_LEGACY_TERRAIN_LAYERS`
        and this method's own `self.rng.choices`/`.random()` draws) —
        `mapgen.basic` is its coordinate-hashed, `on`-constraint-respecting
        successor (see its module docstring for the exact correspondence).
        """
        from ..config import CFG

        map_cfg = CFG.get("map", {})
        if map_type == "earthlike":
            params = map_cfg.get("earthlike", {})
        else:
            params = {}
            if map_cfg.get("terrain_weights"):
                params["terrain_weights"] = map_cfg["terrain_weights"]
            features_cfg = map_cfg.get("features", {})
            feature_chance = {}
            if "woods_chance" in features_cfg:
                feature_chance["woods"] = features_cfg["woods_chance"]
            if "rainforest_chance" in features_cfg:
                feature_chance["rainforest"] = features_cfg["rainforest_chance"]
            if feature_chance:
                params["feature_chance"] = feature_chance

        master_seed = self.rng.next_uint64()
        map_data = mapgen.generate(
            master_seed, (self.n, self.m), num_players=num_players,
            params=params, map_type=map_type,
        )

        for r in range(self.n):
            for c in range(self.m):
                self.tiles[r, c] = Tile(
                    r, c, map_data.base_terrain[r, c],
                    relief=map_data.relief[r, c],
                    feature=map_data.feature[r, c],
                    resource=map_data.resource[r, c],
                )

        self.rivers = dict(map_data.rivers)
        # Seed the fresh-water cache directly from what mapgen already
        # computed (design doc §5/§3.4) rather than recomputing it — same
        # function, same inputs (is_fresh_water's docstring), this just
        # skips the redundant pass over every tile.
        self._fresh_water_cache = map_data.fresh_water
        self._fresh_water_cache_epoch = self.terrain_epoch

    def add_river(self, tile1_coords, tile2_coords, flux=0):
        """Add a river between two tiles (§7.5 item 4's hand-built-edge API).

        `flux` defaults to 0: this API only ever supplies a tile pair, not
        the corner-junction flow data mapgen's own generator produces
        (design doc §5) — a hand-built edge (tests, before/without real
        generated data) gets a RiverEdge with `upstream=downstream=None`
        rather than fabricated junction ids.

        Bumps terrain_epoch like Tile.set_layers does (design doc §3.4):
        river edges are terrain state, and the cost grids/fresh-water mask
        become river-aware. A* stays river-blind until P6 (design doc E3).
        """
        if tile1_coords < tile2_coords:
            edge = (tile1_coords, tile2_coords)
        else:
            edge = (tile2_coords, tile1_coords)
        self.rivers[edge] = mapgen.rivers.RiverEdge(upstream=None, downstream=None, flux=flux)
        self.terrain_epoch += 1

    def has_river_between(self, tile1_coords, tile2_coords):
        """Check if there's a river between two tiles."""
        if tile1_coords < tile2_coords:
            return (tile1_coords, tile2_coords) in self.rivers
        else:
            return (tile2_coords, tile1_coords) in self.rivers

    def is_fresh_water(self, coordinates):
        """Whether this tile is fresh water (design doc §5, §3.4): adjacent
        to a river edge, adjacent to (or on) Lake, or carries Oasis — the
        engine's only fresh-water query. Cached per (map_uid, terrain_epoch)
        like every other terrain-derived cache (§3.4); recomputed from
        CURRENT tiles/rivers via the SAME function mapgen used to produce
        MapData.fresh_water (`mapgen.rivers.fresh_water_mask`) whenever the
        epoch has moved on, so there is one fresh-water definition, not two,
        and it stays correct if rivers/terrain mutate after generation
        (add_river, Tile.set_layers).
        """
        mask = self._fresh_water_grid()
        row, col = coordinates
        return bool(mask[row, col % self.m])

    def _fresh_water_grid(self):
        if self._fresh_water_cache is None or self._fresh_water_cache_epoch != self.terrain_epoch:
            base_terrain = np.empty((self.n, self.m), dtype=object)
            feature = np.empty((self.n, self.m), dtype=object)
            for r in range(self.n):
                for c in range(self.m):
                    tile = self.tiles[r, c]
                    base_terrain[r, c] = tile.base_terrain if tile is not None else None
                    feature[r, c] = tile.feature if tile is not None else None
            self._fresh_water_cache = mapgen.rivers.fresh_water_mask(
                self.rivers, base_terrain, feature, self.n, self.m
            )
            self._fresh_water_cache_epoch = self.terrain_epoch
        return self._fresh_water_cache

    def get_tile(self, coordinates):
        """Get the tile at the specified coordinates, handling horizontal wrapping."""
        row, col = coordinates
        wrapped_col = col % self.m
        if 0 <= row < self.n:
            return self.tiles[row, wrapped_col]
        return None

    def get_adjacent_tiles(self, coordinates):
        """Get all adjacent tiles using axial hex directions + cylindrical wrapping."""
        adjacent = []
        for coord in self.get_adjacent_coords(coordinates):
            tile = self.get_tile(coord)
            if tile is not None:
                adjacent.append(tile)
        return adjacent

    def get_adjacent_coords(self, coordinates):
        """Get coordinates of all adjacent tiles (axial hex + cylindrical wrapping).

        Thin wrapper: delegates to civulator.hexmath, the canonical hex-math
        implementation (design doc §11 P1; CLAUDE.md hex-math row).
        """
        return hexmath.adjacent_coords(coordinates, self.n, self.m)

    def distance_function(self, p1, p2):
        """Hex distance with cylindrical wrapping.

        d = max(|dq|, |dr|, |dq + dr|)  where dq picks the shorter wrap path.

        Thin wrapper: delegates to civulator.hexmath, the canonical hex-math
        implementation (design doc §11 P1; CLAUDE.md hex-math row).
        """
        return hexmath.distance(p1, p2, self.m)

    def _build_cost_grid(self, domain):
        """2D movement-cost array for one movement domain, cached per terrain epoch.

        Tiles the domain cannot enter (wrong domain or impassable — decided by
        the canonical check, never by a cost comparison) are written as
        BLOCKED_COST: the A* adapter encoding, per design doc §3.3. Cached on
        (map_uid, terrain_epoch, domain) — Tile.set_layers bumps the epoch.
        """
        key = (self.map_uid, self.terrain_epoch, domain)
        cached = self._cost_grids.get(key)
        if cached is not None:
            return cached

        cost = np.ones((self.n, self.m), dtype=np.float32)
        for r in range(self.n):
            for q in range(self.m):
                tile = self.tiles[r, q]
                if tile is None:
                    continue
                cost[r, q] = tile.movement_cost if can_enter(domain, tile) else BLOCKED_COST
        # Keep one grid per domain for the current epoch; drop stale epochs.
        self._cost_grids = {
            k: v for k, v in self._cost_grids.items() if k[1] == self.terrain_epoch
        }
        self._cost_grids[key] = cost
        return cost

    def _build_occupied_grid(self, goal=None):
        """Build a 2D bool array of occupied tiles (for A* blocking)."""
        occupied = np.zeros((self.n, self.m), dtype=bool)
        for r in range(self.n):
            for q in range(self.m):
                tile = self.tiles[r, q]
                if tile is not None and len(tile.units) > 0:
                    occupied[r, q] = True
        # Goal tile is allowed (A* needs to path TO it)
        if goal is not None:
            occupied[goal[0], goal[1] % self.m] = False
        return occupied

    def path_finder(self, p1, p2, domain="land"):
        """A* pathfinding on the hex grid with terrain costs.

        Uses C++ civulator_core when available, falls back to Python A*.
        River crossing costs are per-edge and stay invisible here until patch
        P6 extends both A* implementations (design doc E3).

        Args:
            p1: Start coordinates as numpy array or tuple [row, col]
            p2: Destination coordinates as numpy array or tuple [row, col]
            domain: Movement domain of the traveller ("land" | "water").

        Returns:
            list: List of numpy arrays representing the path (excluding start)
        """
        start = (int(p1[0]), int(p1[1]))
        goal = (int(p2[0]), int(p2[1]))

        if start == goal:
            return []

        cost_grid = self._build_cost_grid(domain)
        occupied = self._build_occupied_grid(goal)

        if HAS_CPP_CORE:
            # C++ A*: coords are (q, r) but our arrays are [row][col] = [r][q]
            path_tuples, total_cost = civulator_core.hex_astar(
                cost_grid,
                start[1], start[0],  # q=col, r=row
                goal[1], goal[0],
                occupied
            )
            if total_cost < 0:
                return []  # No path found
            # Convert back to (row, col) numpy arrays
            return [np.array([r, q]) for q, r in path_tuples]
        else:
            # Python fallback A*
            return self._python_astar(start, goal, cost_grid, occupied)

    def _python_astar(self, start, goal, cost_grid, occupied):
        """Pure Python A* fallback."""
        import heapq

        open_set = [(0, start)]
        g_score = {start: 0}
        came_from = {}

        while open_set:
            f, current = heapq.heappop(open_set)

            if current == goal:
                # Reconstruct path
                path = []
                node = goal
                while node != start:
                    path.append(np.array(node))
                    node = came_from[node]
                path.reverse()
                return path

            current_g = g_score[current]
            if current_g > g_score.get(current, float('inf')):
                continue

            for neighbor in self.get_adjacent_coords(current):
                r, q = neighbor
                terrain_cost = cost_grid[r, q]
                if terrain_cost >= BLOCKED_COST:  # A* adapter encoding, see BLOCKED_COST
                    continue
                if occupied[r, q] and neighbor != goal:
                    continue

                tentative_g = current_g + terrain_cost
                if tentative_g < g_score.get(neighbor, float('inf')):
                    g_score[neighbor] = tentative_g
                    came_from[neighbor] = current
                    h = self.distance_function(neighbor, goal)
                    heapq.heappush(open_set, (tentative_g + h, neighbor))

        return []  # No path found

    def get_vision_range(self, coordinates):
        """Get how far a unit at these coordinates can see.

        Base range is 2 tiles. The tile's composed vantage adds extra range.
        """
        tile = self.get_tile(coordinates)
        if tile is None:
            return 0
        return 2 + tile.los[1]  # Base sight range + vantage bonus

    def check_line_of_sight(self, from_coords, to_coords):
        """Check if there's a clear line of sight between two coordinates.

        Uses the tiles' composed (obstacle, vantage) line-of-sight values.
        - Adjacent tiles are always visible.
        - Standing on high ground (vantage > 0) lets you see over low obstacles.
        - An obstacle blocks if its obstacle_level > observer's vantage_level.
        """
        from_tile = self.get_tile(from_coords)
        to_tile = self.get_tile(to_coords)

        if not from_tile or not to_tile:
            return False

        # Can't see from impassable terrain (mountains) — nobody stands there
        if from_tile.impassable:
            return False
        from_los = from_tile.los

        # Adjacent tiles: always visible
        dist = self.distance_function(from_coords, to_coords)
        if dist <= 1:
            return True

        # Beyond vision range?
        vision_range = self.get_vision_range(from_coords)
        if dist > vision_range:
            return False

        observer_vantage = from_los[1]

        # Check intermediate tiles — use hex line drawing
        path = self._hex_line(from_coords, to_coords)
        for coord in path[1:-1]:  # Skip start and end
            tile = self.get_tile(coord)
            if tile is None:
                return False
            if tile.los[0] > observer_vantage:
                return False

        return True

    def _hex_line(self, p1, p2):
        """Draw an approximate line between two hex tiles.

        Returns list of (row, col) coordinates from p1 to p2 inclusive.
        Uses linear interpolation in axial coordinates.
        """
        dist = self.distance_function(p1, p2)
        if dist == 0:
            return [p1]

        # Handle cylindrical wrapping for interpolation
        dq = p2[1] - p1[1]
        dq_wrapped = dq - self.m if dq > 0 else dq + self.m
        if abs(dq_wrapped) < abs(dq):
            dq = dq_wrapped

        dr = p2[0] - p1[0]

        points = []
        for i in range(dist + 1):
            t = i / dist
            q = p1[1] + dq * t
            r = p1[0] + dr * t
            # Round to nearest hex
            rq = round(q)
            rr = round(r)
            points.append((rr, int(rq) % self.m))

        return points

    def visible_from(self, coordinates):
        """Cached tiles visible from a position (terrain-static per episode).

        First call for a tile computes get_visible_tiles once; afterwards a
        player's whole visibility mask is just a union of cached sets over
        its unit/city positions — no line-of-sight walks. Terrain edits
        (Tile.set_layers) bump terrain_epoch and drop the cache (§3.4).
        """
        if self._visible_cache_epoch != self.terrain_epoch:
            self._visible_cache = {}
            self._visible_cache_epoch = self.terrain_epoch

        key = (coordinates[0], coordinates[1] % self.m)
        cached = self._visible_cache.get(key)
        if cached is None:
            cached = tuple(self.get_visible_tiles(key))
            self._visible_cache[key] = cached
        return cached

    def get_visible_tiles(self, coordinates):
        """Get all tiles visible from a position. Returns list of (row, col)."""
        vision_range = self.get_vision_range(coordinates)
        visible = []
        row, col = coordinates

        # Check all tiles within vision range
        for dr in range(-vision_range, vision_range + 1):
            for dq in range(-vision_range, vision_range + 1):
                r = row + dr
                q = (col + dq) % self.m
                if r < 0 or r >= self.n:
                    continue
                target = (r, q)
                if self.distance_function(coordinates, target) <= vision_range:
                    if self.check_line_of_sight(coordinates, target):
                        visible.append(target)

        return visible
