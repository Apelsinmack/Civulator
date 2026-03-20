"""Hex grid map with cylindrical wrapping.

Coordinate system: axial (q, r) stored as (row, col) in a 2D array.
The array is a skewed rectangle — this is intentional and accepted.
Distance = max(|dq|, |dr|, |dq + dr|) with cylindrical wrapping on q-axis (columns).
"""

import os
import sys
import random

import numpy as np

from .tile import Tile
from .terrain import Terrain

# Try to load C++ module for fast pathfinding
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'cpp', 'build', 'Release'))
    import civulator_core
    HAS_CPP_CORE = True
except ImportError:
    HAS_CPP_CORE = False

# Axial hex directions — same for every tile, no even/odd branching
HEX_DIRECTIONS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


class Map:
    """Represents the game map composed of hex tiles."""

    def __init__(self, n_rows, m_columns):
        self.n = n_rows
        self.m = m_columns
        self.tiles = np.empty((self.n, self.m), dtype=object)
        self.rivers = set()

    def generate_map(self, map_type="basic"):
        """Generate a map with random terrain."""
        terrain_types = [
            "Plains", "Grassland", "Desert", "Tundra",
            "Hills", "Woods", "Mountain",
        ]
        weights = [0.3, 0.3, 0.1, 0.1, 0.1, 0.05, 0.05]

        for i in range(self.n):
            for j in range(self.m):
                terrain = np.random.choice(terrain_types, p=weights)
                self.tiles[i, j] = Tile(i, j, terrain)

                # Randomly add features
                if terrain in ["Plains", "Grassland", "Tundra"] and random.random() < 0.2:
                    self.tiles[i, j].add_feature("Woods")
                elif terrain in ["Plains", "Grassland"] and random.random() < 0.1:
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
        """Get coordinates of all adjacent tiles (axial hex + cylindrical wrapping)."""
        row, col = coordinates
        coords = []
        for dr, dc in HEX_DIRECTIONS:
            new_row = row + dr
            new_col = (col + dc) % self.m  # Cylindrical wrap on q-axis
            if 0 <= new_row < self.n:
                coords.append((new_row, new_col))
        return coords

    def distance_function(self, p1, p2):
        """Hex distance with cylindrical wrapping.

        d = max(|dq|, |dr|, |dq + dr|)  where dq picks the shorter wrap path.
        """
        dq_direct = p2[1] - p1[1]
        # Check if wrapping is shorter
        if dq_direct > 0:
            dq_wrapped = dq_direct - self.m
        else:
            dq_wrapped = dq_direct + self.m
        dq = dq_direct if abs(dq_direct) <= abs(dq_wrapped) else dq_wrapped

        dr = p2[0] - p1[0]
        return max(abs(dq), abs(dr), abs(dq + dr))

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

    def check_line_of_sight(self, from_coords, to_coords):
        """Check if there's a clear line of sight between two coordinates.

        Currently simple: mountains block, everything else is transparent.
        TODO: Implement elevation-based LoS (hills see over plains, etc.)
        using config-driven obstacle/vantage levels.
        """
        from_tile = self.get_tile(from_coords)
        to_tile = self.get_tile(to_coords)

        if not from_tile or not to_tile:
            return False

        # Can't see from or to a mountain
        if from_tile.terrain_type == "Mountain" or to_tile.terrain_type == "Mountain":
            return False

        # For adjacent tiles, always visible
        if self.distance_function(from_coords, to_coords) <= 1:
            return True

        # Check intermediate tiles along a straight line
        # Use the A* path as approximation for now
        path = self.path_finder(np.array(from_coords), np.array(to_coords))
        for coord in path[:-1]:  # Don't check the destination itself
            tile = self.get_tile(tuple(coord))
            if tile and tile.terrain_type == "Mountain":
                return False

        return True
