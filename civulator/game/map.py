"""Hex grid map with cylindrical wrapping."""

import random

import numpy as np

from .tile import Tile


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
        """Get all adjacent tiles using hex adjacency with even/odd row offsets."""
        row, col = coordinates

        if row % 2 == 0:  # Even row
            directions = [
                (-1, -1), (-1, 0),
                (0, -1), (0, 1),
                (1, -1), (1, 0),
            ]
        else:  # Odd row
            directions = [
                (-1, 0), (-1, 1),
                (0, -1), (0, 1),
                (1, 0), (1, 1),
            ]

        adjacent = []
        for dr, dc in directions:
            new_row, new_col = row + dr, col + dc
            new_col = new_col % self.m  # Horizontal wrapping
            if 0 <= new_row < self.n:
                tile = self.get_tile((new_row, new_col))
                if tile is not None:
                    adjacent.append(tile)

        return adjacent

    def get_adjacent_coords(self, coordinates):
        """Get coordinates of all adjacent tiles (hex adjacency + wrapping)."""
        row, col = coordinates

        if row % 2 == 0:
            directions = [
                (-1, -1), (-1, 0),
                (0, -1), (0, 1),
                (1, -1), (1, 0),
            ]
        else:
            directions = [
                (-1, 0), (-1, 1),
                (0, -1), (0, 1),
                (1, 0), (1, 1),
            ]

        coords = []
        for dr, dc in directions:
            new_row, new_col = row + dr, col + dc
            new_col = new_col % self.m
            if 0 <= new_row < self.n:
                coords.append((new_row, new_col))

        return coords

    def distance_function(self, p1, p2):
        """
        Calculate the distance between two points on a hex grid
        with cylindrical wrapping.
        """
        dx = p2[1] - p1[1]

        # Check if wrapping is shorter
        dx_wrapped = dx
        if abs(dx) > self.m / 2:
            if dx > 0:
                dx_wrapped = dx - self.m
            else:
                dx_wrapped = dx + self.m

        dx = min(dx, dx_wrapped)
        dy = p2[0] - p1[0]

        if dx * dy > 0:
            d = max(abs(dx), abs(dy))
        else:
            d = abs(dx) + abs(dy)

        return d

    def path_finder(self, p1, p2):
        """
        Find a path between two points on the hex grid.

        Uses a greedy approach -- follows the shortest direction each step.
        TODO: Replace with A* for terrain-cost-aware pathfinding.

        Args:
            p1: Start coordinates as numpy array [row, col]
            p2: Destination coordinates as numpy array [row, col]

        Returns:
            list: List of numpy arrays representing the path (excluding start)
        """
        orders = []
        current_position = p1.copy()
        destination = p2.copy()

        # Check if wrapping is shorter
        if self.distance_function(p1, destination) > self.distance_function(
            p1, destination + np.array([0, self.m])
        ):
            destination = destination + np.array([0, self.m])
        if self.distance_function(p1, destination) > self.distance_function(
            p1, destination - np.array([0, self.m])
        ):
            destination = destination - np.array([0, self.m])

        dx, dy = destination - current_position
        modulus = np.array([self.n, self.m])

        while self.distance_function(destination, current_position) > 0:
            if dx > 0 and dy > 0:
                current_position += np.array([1, 1])
                dx -= 1
                dy -= 1
            elif dx < 0 and dy < 0:
                current_position -= np.array([1, 1])
                dx += 1
                dy += 1
            elif dx > 0 and dy == 0:
                current_position += np.array([1, 0])
                dx -= 1
            elif dx < 0 and dy == 0:
                current_position -= np.array([1, 0])
                dx += 1
            elif dy > 0:
                current_position += np.array([0, 1])
                dy -= 1
            elif dy < 0:
                current_position -= np.array([0, 1])
                dy += 1

            orders.append(current_position.copy() % modulus)

        return orders

    def check_line_of_sight(self, from_coords, to_coords):
        """Check if there's a clear line of sight between two coordinates."""
        from_tile = self.get_tile(from_coords)
        to_tile = self.get_tile(to_coords)

        if (
            not from_tile
            or not to_tile
            or from_tile.terrain_type == "Mountain"
            or to_tile.terrain_type == "Mountain"
        ):
            return False

        path = self.path_finder(np.array(from_coords), np.array(to_coords))

        for coord in path[1:-1]:
            tile = self.get_tile(tuple(coord))
            if tile and tile.terrain_type == "Mountain":
                return False

        return True
