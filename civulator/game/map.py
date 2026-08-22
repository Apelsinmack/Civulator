"""Hex grid map with cylindrical wrapping.

Coordinate system: axial (q, r) stored as (row, col) in a 2D array.
The array is a skewed rectangle — this is intentional and accepted.
Distance = max(|dq|, |dr|, |dq + dr|) with cylindrical wrapping on q-axis (columns).
"""

import itertools
import os
import sys

import numpy as np

from .. import hexmath
from ..hexmath import HEX_DIRECTIONS  # re-exported: civulator.agents.networks imports it from here
from ..rng import PortableRNG

from .tile import Tile
from .terrain import Terrain

# Try to load C++ module for fast pathfinding
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'cpp', 'build', 'Release'))
    import civulator_core
    HAS_CPP_CORE = True
except ImportError:
    HAS_CPP_CORE = False


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
        self.rivers = set()
        # Terrain/feature randomness draws from here; pass the owning
        # GameEnvironment's rng for reproducible maps.
        self.rng = rng if rng is not None else PortableRNG()
        # Per-tile visibility cache — terrain is static for the Map's lifetime,
        # so what a tile can see never changes within an episode.
        self._visible_cache = {}
        self.map_uid = next(Map._uid_counter)
        self.terrain_epoch = 0

    def generate_map(self, map_type="basic"):
        """Generate a map with random terrain. Weights from config.toml."""
        from ..config import CFG

        cfg_weights = CFG.get("map", {}).get("terrain_weights", {})
        cfg_features = CFG.get("map", {}).get("features", {})

        if cfg_weights:
            terrain_types = list(cfg_weights.keys())
            raw_weights = [cfg_weights[t] for t in terrain_types]
            total = sum(raw_weights)
            weights = [w / total for w in raw_weights]
        else:
            terrain_types = [
                "Plains", "Grassland", "Desert", "Tundra",
                "Hills", "Woods", "Mountain",
            ]
            weights = [0.3, 0.3, 0.1, 0.1, 0.1, 0.05, 0.05]

        woods_chance = cfg_features.get("woods_chance", 0.2)
        rainforest_chance = cfg_features.get("rainforest_chance", 0.1)

        for i in range(self.n):
            for j in range(self.m):
                terrain = self.rng.choices(terrain_types, weights=weights, k=1)[0]
                self.tiles[i, j] = Tile(i, j, terrain)

                if terrain in ["Plains", "Grassland", "Tundra"] and self.rng.random() < woods_chance:
                    self.tiles[i, j].add_feature("Woods")
                elif terrain in ["Plains", "Grassland"] and self.rng.random() < rainforest_chance:
                    self.tiles[i, j].add_feature("Rainforest")

    def add_river(self, tile1_coords, tile2_coords):
        """Add a river between two tiles."""
        if tile1_coords < tile2_coords:
            self.rivers.add((tile1_coords, tile2_coords))
        else:
            self.rivers.add((tile2_coords, tile1_coords))

    def has_river_between(self, tile1_coords, tile2_coords):
        """Check if there's a river between two tiles."""
        if tile1_coords < tile2_coords:
            return (tile1_coords, tile2_coords) in self.rivers
        else:
            return (tile2_coords, tile1_coords) in self.rivers

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

    def _build_cost_grid(self):
        """Build a 2D cost array from terrain for A* pathfinding."""
        cost = np.ones((self.n, self.m), dtype=np.float32)
        for r in range(self.n):
            for q in range(self.m):
                tile = self.tiles[r, q]
                if tile is not None:
                    cost[r, q] = Terrain.MOVEMENT_COSTS.get(tile.terrain_type, 1)
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

    def path_finder(self, p1, p2):
        """A* pathfinding on the hex grid with terrain costs.

        Uses C++ civulator_core when available, falls back to Python A*.

        Args:
            p1: Start coordinates as numpy array or tuple [row, col]
            p2: Destination coordinates as numpy array or tuple [row, col]

        Returns:
            list: List of numpy arrays representing the path (excluding start)
        """
        start = (int(p1[0]), int(p1[1]))
        goal = (int(p2[0]), int(p2[1]))

        if start == goal:
            return []

        cost_grid = self._build_cost_grid()
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
                if terrain_cost >= 99:
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

        Base range is 2 tiles. Vantage level adds extra range.
        Configured via terrain.los in config.toml.
        """
        tile = self.get_tile(coordinates)
        if tile is None:
            return 0
        los = Terrain.LOS.get(tile.terrain_type, [0, 0])
        vantage = los[1]
        return 2 + vantage  # Base sight range + vantage bonus

    def check_line_of_sight(self, from_coords, to_coords):
        """Check if there's a clear line of sight between two coordinates.

        Uses obstacle_level and vantage_level from Terrain.LOS (config.toml).
        - Adjacent tiles are always visible.
        - Standing on high ground (vantage > 0) lets you see over low obstacles.
        - An obstacle blocks if its obstacle_level > observer's vantage_level.
        """
        from_tile = self.get_tile(from_coords)
        to_tile = self.get_tile(to_coords)

        if not from_tile or not to_tile:
            return False

        # Can't see from impassable terrain (mountains)
        from_los = Terrain.LOS.get(from_tile.terrain_type, [0, 0])
        if Terrain.MOVEMENT_COSTS.get(from_tile.terrain_type, 1) >= 999:
            return False

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
            obstacle = Terrain.LOS.get(tile.terrain_type, [0, 0])[0]
            if obstacle > observer_vantage:
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
        its unit/city positions — no line-of-sight walks.
        """
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
