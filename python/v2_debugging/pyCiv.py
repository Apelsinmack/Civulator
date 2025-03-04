"""
simple version of civ in python
Version 2 of pyCiv implements classes for map tiles:
    units and cities are referenced in the tiles (in addition to being referenced in the player class)
    This means you can pick a tile and see if there is a unit standing on it, as well as pick a player and see where all their units are
    Allows for different terrain types with different yields and defencive bonuses, hopefully also rivers can be implemented.
    EXAMPLE tile.rivers = [river1, river2], where river1 = ['NE', 'S'] could mean we have 2 rivers flowing on the tile, river1 exits the tile to the north east and the south.
"""
import math
import random
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt

class Terrain:
    """Represents different terrain types and their combat modifiers."""
    
    # Terrain defense modifiers
    DEFENSE_MODIFIERS = {
        "Plains": 0,
        "Grassland": 0,
        "Desert": 0,
        "Tundra": 0,
        "Snow": 0,
        "Hills": 3,
        "Woods": 3,
        "Rainforest": 3,
        "Marsh": -2,
        "Floodplains": -2,
        "Mountain": 0,  # Usually impassable, but included for completeness
        "Ocean": 0,
        "Coast": 0,
        "Lake": 0,
    }
    
    # Movement cost modifiers
    MOVEMENT_COSTS = {
        "Plains": 1,
        "Grassland": 1,
        "Desert": 1,
        "Tundra": 1,
        "Snow": 1,
        "Hills": 2,
        "Woods": 2,
        "Rainforest": 2,
        "Marsh": 2,
        "Floodplains": 1,
        "Mountain": 999,  # Impassable
        "Ocean": 1,  # For naval units
        "Coast": 1,  # For naval units
        "Lake": 1,   # For naval units
    }
    
    # Production values (food, production)
    PRODUCTION_VALUES = {
        "Plains": np.array([1, 1]),
        "Grassland": np.array([2, 0]),
        "Desert": np.array([0, 0]),
        "Tundra": np.array([1, 0]),
        "Snow": np.array([0, 0]),
        "Hills": np.array([0, 2]),
        "Woods": np.array([1, 1]),
        "Rainforest": np.array([2, 0]),
        "Marsh": np.array([1, 0]),
        "Floodplains": np.array([3, 0]),
        "Mountain": np.array([0, 0]),
        "Ocean": np.array([1, 0]),
        "Coast": np.array([1, 0]),
        "Lake": np.array([2, 0]),
    }


class Tile:
    """Represents a single tile on the map."""
    
    def __init__(self, row, column, terrain_type="Plains"):
        self.row = row
        self.column = column
        self.coordinates = (row, column)
        self.terrain_type = terrain_type
        self.features = []  # Additional features like forests, rivers, etc.
        self.improvements = []  # Man-made improvements
        self.resource = None  # Resource on this tile
        self.units = []  # Units on this tile
        self.city = None  # City on this tile
        
        # Set terrain-based properties
        self.update_terrain_properties()
    
    def update_terrain_properties(self):
        """Update the tile properties based on terrain type."""
        self.defense_bonus = Terrain.DEFENSE_MODIFIERS.get(self.terrain_type, 0)
        self.movement_cost = Terrain.MOVEMENT_COSTS.get(self.terrain_type, 1)
        self.production_value = Terrain.PRODUCTION_VALUES.get(self.terrain_type, np.array([0, 0]))
        
        # Apply features modifiers
        if "Woods" in self.features:
            self.defense_bonus += 3
            self.movement_cost += 1
        if "Rainforest" in self.features:
            self.defense_bonus += 3
            self.movement_cost += 1
    
    def add_unit(self, unit):
        """Add a unit to this tile."""
        self.units.append(unit)
    
    def remove_unit(self, unit):
        """Remove a unit from this tile."""
        if unit in self.units:
            self.units.remove(unit)
    
    def add_feature(self, feature):
        """Add a feature to this tile."""
        if feature not in self.features:
            self.features.append(feature)
            self.update_terrain_properties()
    
    def remove_feature(self, feature):
        """Remove a feature from this tile."""
        if feature in self.features:
            self.features.remove(feature)
            self.update_terrain_properties()
    
    def add_improvement(self, improvement):
        """Add an improvement to this tile."""
        if improvement not in self.improvements:
            self.improvements.append(improvement)
    
    def remove_improvement(self, improvement):
        """Remove an improvement from this tile."""
        if improvement in self.improvements:
            self.improvements.remove(improvement)
    
    def set_city(self, city):
        """Set a city on this tile."""
        self.city = city
    
    def is_passable(self):
        """Check if this tile is passable by units."""
        return self.terrain_type != "Mountain" and self.movement_cost < 999
    
    def is_water(self):
        """Check if this tile is a water tile."""
        return self.terrain_type in ["Ocean", "Coast", "Lake"]
    
    def has_feature(self, feature):
        """Check if this tile has a specific feature."""
        return feature in self.features
    
    def has_river(self):
        """Check if this tile has a river."""
        return "River" in self.features


class Map:
    """Represents the game map composed of tiles."""
    
    def __init__(self, n_rows, m_columns):
        self.n = n_rows
        self.m = m_columns
        self.tiles = np.empty((self.n, self.m), dtype=object)
        self.rivers = set()  # Set of (tile1, tile2) tuples representing rivers between tiles
    
    def generate_map(self, map_type="continents"):
        """Generate a map based on the specified type."""
        if map_type == "continents":
            self._generate_continents_map()
        elif map_type == "archipelago":
            self._generate_archipelago_map()
        elif map_type == "pangaea":
            self._generate_pangaea_map()
        else:
            self._generate_basic_map()
    
    def _generate_basic_map(self):
        """Generate a basic map with random terrain."""
        terrain_types = ["Plains", "Grassland", "Desert", "Tundra", "Hills", "Woods", "Mountain"]
        weights = [0.3, 0.3, 0.1, 0.1, 0.1, 0.05, 0.05]  # Probability weights
        
        for i in range(self.n):
            for j in range(self.m):
                terrain = np.random.choice(terrain_types, p=weights)
                self.tiles[i, j] = Tile(i, j, terrain)
                
                # Randomly add features
                if terrain in ["Plains", "Grassland", "Tundra"] and random.random() < 0.2:
                    self.tiles[i, j].add_feature("Woods")
                elif terrain in ["Plains", "Grassland"] and random.random() < 0.1:
                    self.tiles[i, j].add_feature("Rainforest")
    
    def _generate_continents_map(self):
        """Generate a map with several continents."""
        # Implement continent generation algorithm
        # This is a placeholder - would need a more sophisticated algorithm
        self._generate_basic_map()
    
    def _generate_archipelago_map(self):
        """Generate a map with many islands."""
        # Implement archipelago generation algorithm
        # This is a placeholder - would need a more sophisticated algorithm
        self._generate_basic_map()
    
    def _generate_pangaea_map(self):
        """Generate a map with one large continent."""
        # Implement pangaea generation algorithm
        # This is a placeholder - would need a more sophisticated algorithm
        self._generate_basic_map()
    
    def add_river(self, tile1_coords, tile2_coords):
        """Add a river between two tiles."""
        # Make sure we store the river reference in a consistent order
        if tile1_coords < tile2_coords:
            self.rivers.add((tile1_coords, tile2_coords))
        else:
            self.rivers.add((tile2_coords, tile1_coords))
    
    def has_river_between(self, tile1_coords, tile2_coords):
        """Check if there's a river between two tiles."""
        # Check for the river in a consistent order
        if tile1_coords < tile2_coords:
            return (tile1_coords, tile2_coords) in self.rivers
        else:
            return (tile2_coords, tile1_coords) in self.rivers
    
    def get_tile(self, coordinates):
        """Get the tile at the specified coordinates, handling map wrapping."""
        row, col = coordinates
        wrapped_col = col % self.m  # Handle horizontal wrapping
        if 0 <= row < self.n:
            return self.tiles[row, wrapped_col]
        return None
    
    def get_adjacent_tiles(self, coordinates):
        """Get all adjacent tiles to the specified coordinates."""
        row, col = coordinates
        adjacent_coords = []
        
        # Based on hexagonal grid, different even/odd row adjacency patterns
        if row % 2 == 0:  # Even row
            directions = [
                (-1, -1), (-1, 0),
                (0, -1), (0, 1),
                (1, -1), (1, 0)
            ]
        else:  # Odd row
            directions = [
                (-1, 0), (-1, 1),
                (0, -1), (0, 1),
                (1, 0), (1, 1)
            ]
        
        for dr, dc in directions:
            new_row, new_col = row + dr, col + dc
            # Handle horizontal wrapping
            new_col = new_col % self.m
            
            if 0 <= new_row < self.n:
                adjacent_coords.append((new_row, new_col))
        
        return [self.get_tile(coord) for coord in adjacent_coords]
    
    def distance_function(self, p1, p2):
        """
        Calculate the distance between two points on a hexagonal grid with cylindrical wrapping.
        
        Args:
            p1: First point (row, col)
            p2: Second point (row, col)
            
        Returns:
            int: Distance between the points
        """
        # Calculate direct dx
        dx = p2[1] - p1[1]
        
        # Check if wrapping around the map is shorter
        dx_wrapped = dx
        if abs(dx) > self.m / 2:  # If more than halfway across map
            if dx > 0:
                dx_wrapped = dx - self.m  # Wrap around left
            else:
                dx_wrapped = dx + self.m  # Wrap around right
        
        # Use the shorter horizontal distance
        dx = min(dx, dx_wrapped)
        
        # Calculate vertical distance
        dy = p2[0] - p1[0]
        
        # Calculate hex distance
        if dx*dy > 0:
            d = max(abs(dx), abs(dy))
        else:
            d = abs(dx) + abs(dy)
        
        return d
    
    def path_finder(self, p1, p2):
        """
        Find a path between start and destination on the map.
        
        Args:
            start: Starting coordinates (row, col) as numpy array
            destination: Destination coordinates (row, col) as numpy array
            
        Returns:
            list: List of coordinates representing the path
        """
        orders = []
        current_position = p1.copy()  # Create a copy of p1 to work with
        destination = p2.copy()
        
        
        if self.distance_function(p1, destination) > self.distance_function(p1, (destination + np.array([0, self.m]))):
            destination = destination + np.array([0, self.m])
        if self.distance_function(p1, destination) > self.distance_function(p1, (destination - np.array([0, self.m]))):
            destination = destination - np.array([0, self.m])
        
        
        dx, dy = destination - current_position
        modulus = np.array([self.n,self.m])
        
        
        while self.distance_function(destination, current_position) > 0:
            if dx > 0 and dy > 0:
                current_position += np.array([1, 1])
                orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
                dx -= 1
                dy -= 1
            elif dx < 0 and dy < 0:
                current_position -= np.array([1, 1])
                orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
                dx += 1
                dy += 1
            elif dx > 0 and dy == 0:
                current_position += np.array([1, 0])
                orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
                dx -= 1
            elif dx < 0 and dy == 0:
                current_position -= np.array([1, 0])
                orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
                dx += 1
            elif dy > 0:
                current_position += np.array([0, 1])
                orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
                dy -= 1
            elif dy < 0:
                current_position -= np.array([0, 1])
                orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
                dy += 1
    
        return orders
    # def path_finder(self, start, destination):
        
        
    #     # Check if wrapping around the map is shorter
    #     modulus = np.array([self.n, self.m])
        
    #     # Handle cylindrical map - check if crossing the edge is shorter
    #     if self.distance_function(start, destination) > self.distance_function(start, (destination + np.array([0, self.m]))):
    #         destination = destination + np.array([0, self.m])
    #     if self.distance_function(start, destination) > self.distance_function(start, destination - np.array([0, self.m])):
    #         destination = destination - np.array([0, self.m])
        
    #     # Create a path using a simple algorithm (could be replaced with A* later)
    #     current_position = start.copy()
    #     orders = [current_position.copy() % modulus]  # Start with initial position
        
    #     # Calculate differences
    #     dx = destination[0] - current_position[0]
    #     dy = destination[1] - current_position[1]
        
    #     # Move step by step toward the destination
    #     while self.distance_function(destination, current_position) > 0:
    #         if dx > 0 and dy > 0:
    #             current_position += np.array([1, 1])
    #             orders.append(current_position.copy() % modulus)
    #             dx -= 1
    #             dy -= 1
    #         elif dx < 0 and dy < 0:
    #             current_position -= np.array([1, 1])
    #             orders.append(current_position.copy() % modulus)
    #             dx += 1
    #             dy += 1
    #         elif dx > 0 and dy == 0:
    #             current_position += np.array([0, 1])
    #             orders.append(current_position.copy() % modulus)
    #             dx -= 1
    #         elif dx < 0 and dy == 0:
    #             current_position -= np.array([0, 1])
    #             orders.append(current_position.copy() % modulus)
    #             dx += 1
    #         elif dy > 0:
    #             current_position += np.array([1, 0])
    #             orders.append(current_position.copy() % modulus)
    #             dy -= 1
    #         elif dy < 0:
    #             current_position -= np.array([0, 1])
    #             orders.append(current_position.copy() % modulus)
    #             dy += 1
        
    #     return orders
    
    def check_line_of_sight(self, from_coords, to_coords):
        """Check if there's a clear line of sight between two coordinates."""
        # Get the tiles
        from_tile = self.get_tile(from_coords)
        to_tile = self.get_tile(to_coords)
        
        # Check if either tile doesn't exist or is a mountain
        if not from_tile or not to_tile or from_tile.terrain_type == "Mountain" or to_tile.terrain_type == "Mountain":
            return False
        
        # For simplicity, we'll check if there are any mountains in tiles along the path
        path = self.path_finder(np.array(from_coords), np.array(to_coords))
        
        # Skip the first and last coordinates (they're the from and to tiles)
        for coord in path[1:-1]:
            tile = self.get_tile(tuple(coord))
            if tile and tile.terrain_type == "Mountain":
                return False
        
        return True

class Unit:
    """Base class for all units in the game"""
    
    def __init__(self, player, coordinates, unit_type, terrain=None):
        self.player = player
        self.coordinates = coordinates
        self.unit_type = unit_type
        self.health = 100.0
        self.movement_points = self.get_max_movement()
        self.terrain = terrain  # Current terrain the unit is on
        self.fortification = 0  # Fortification level (0, 1, or 2)
    
    def __str__(self):
        return f"Type: {self.unit_type}, Health: {self.health}, Team: {self.player.name}, Location: {self.location}"
    
    def get_max_movement(self):
        """Return the maximum movement points for this unit type."""
        movement_points = {
            "Warrior": 2,
            "Archer": 2,
            "Swordsman": 2,
            "Spearman": 2,
            "Horseman": 4,
            "Settler": 2,
            "Worker": 2,
            "Catapult": 2
        }
        return movement_points.get(self.unit_type, 2)
    
    
    def get_base_combat_strength(self):
        """Return the base combat strength of this unit."""
        combat_strength = {
            "Warrior": 20,
            "Archer": 15,  # Lower melee defense
            "Swordsman": 35,
            "Spearman": 25,
            "Horseman": 36,
            "Settler": 0,
            "Worker": 0,
            "Catapult": 25  # When forced into melee
        }
        return combat_strength.get(self.unit_type, 10)
    
    def get_base_ranged_strength(self):
        """Return the base ranged strength of this unit."""
        ranged_strength = {
            "Archer": 25,
            "Catapult": 45,  # High against cities
            "Warrior": 0,
            "Swordsman": 0,
            "Spearman": 0, 
            "Horseman": 0,
            "Settler": 0,
            "Worker": 0
        }
        return ranged_strength.get(self.unit_type, 0)
    
    def get_range(self):
        """Return the attack range of this unit."""
        range_values = {
            "Archer": 2,
            "Catapult": 2,
            "Warrior": 1,
            "Swordsman": 1,
            "Spearman": 1,
            "Horseman": 1,
            "Settler": 0,
            "Worker": 0
        }
        return range_values.get(self.unit_type, 1)
    
    def get_production_cost(self):
        """Return the production cost of this unit."""
        cost_values = {
            "Warrior": 40,
            "Archer": 60,
            "Swordsman": 90,
            "Spearman": 50,
            "Horseman": 80,
            "Settler": 120,
            "Worker": 50,
            "Catapult": 120
        }
        return cost_values.get(self.unit_type, 40)
    
    def reset_movement(self):
       """Reset movement points at the start of a new turn."""
       self.movement_points = self.get_max_movement()
       # Increase fortification if unit didn't move last turn
       if self.fortification < 2:
           self.fortification += 1
           
    def get_combat_strength(self, is_attacking=False, target=None):
        """
        Calculate the total combat strength accounting for all modifiers.
        
        Args:
            is_attacking (bool): True if the unit is attacking, False if defending
            target (Unit): The opposing unit in combat
            
        Returns:
            float: The final combat strength value
        """
        # Start with base strength
        strength = self.get_base_combat_strength()
        
        # Apply health penalty
        # Formula: -10 * (100 - HP) / 100
        hp_penalty = -10 * (100 - self.health) / 100
        strength += hp_penalty
        
        # Apply terrain modifiers if defending
        if not is_attacking and self.terrain:
            terrain_mod = Terrain.DEFENSE_MODIFIERS.get(self.terrain, 0)
            strength += terrain_mod
            
            # Hills with Woods or Rainforest stack
            if self.terrain == "Hills" and (self.player.game_env.has_feature(self.coordinates, "Woods") or 
                                            self.player.game_env.has_feature(self.coordinates, "Rainforest")):
                strength += 3  # Additional +3 for Woods/Rainforest on Hills
        
        # Apply fortification bonus if defending
        if not is_attacking and self.fortification > 0:
            fort_bonus = 3 if self.fortification == 1 else 6
            strength += fort_bonus
        
        # Apply unit class advantages if there's a target
        if target and is_attacking:
            # Spearmen get bonus against cavalry
            if self.unit_type == "Spearman" and target.unit_type == "Horseman":
                strength += 10  # Anti-cavalry bonus
            
            # Melee units get bonus against anti-cavalry
            if self.unit_type in ["Warrior", "Swordsman"] and target.unit_type == "Spearman":
                strength += 5
        
        # Make sure strength doesn't go below 0
        return max(0, strength)
    
    def get_ranged_strength(self, target=None, is_city=False):
        """Calculate the total ranged strength including modifiers."""
        if self.get_base_ranged_strength() == 0:
            return 0
        
        strength = self.get_base_ranged_strength()
        
        # Apply health penalty
        hp_penalty = -10 * (100 - self.health) / 100
        strength += hp_penalty
        
        # Apply ranged attack penalties
        if is_city:
            strength -= 17  # -17 against cities
        
        # Apply unit-specific modifiers
        if target and target.unit_type == "Horseman" and self.unit_type == "Archer":
            strength -= 5  # Archers less effective against fast cavalry
        
        return max(0, strength)
    
    def move(self, new_coordinates, game_env):
        """
        Move the unit to new coordinates using the pathfinder.
        
        Args:
            new_coordinates (tuple): The (row, col) destination coordinates
            game_env: The game environment with terrain data
            
        Returns:
            bool: True if the move was successful (at least partially), False otherwise
            list: The coordinates the unit moved to (could be the destination or an intermediate point)
        """
        # Convert coordinates to numpy arrays for the pathfinder
        start_pos = np.array(self.coordinates)
        dest_pos = np.array(new_coordinates)
        
        # Get the path from current position to destination
        path = game_env.path_finder(start_pos, dest_pos)
        
        # If no path found or path is empty, return False
        if not path or len(path) <= 1:  # Path includes starting position
            return False, self.coordinates
        
        # Remove the first position (current position) from the path
        path = path[1:]  # Start from the first move
        
        # Initialize remaining movement points
        remaining_mp = self.movement_points
        
        # Track our current position as we move along the path
        current_pos = np.array(self.coordinates)
        final_pos = current_pos.copy()  # Default to not moving if we can't move at all
        
        # Move along the path as far as movement points allow
        for next_pos in path:
            # Convert to tuple for consistency
            next_pos_tuple = tuple(next_pos)
            current_pos_tuple = tuple(current_pos)
            
            # Get terrain at the next position
            terrain_at_next = game_env.get_terrain_at(next_pos_tuple)
            movement_cost = Terrain.MOVEMENT_COSTS.get(terrain_at_next, 1)
            
            # Check for river crossing
            river_crossing = game_env.is_river_between(current_pos_tuple, next_pos_tuple)
            if river_crossing:
                movement_cost += 1  # Additional cost for crossing rivers
            
            # Check if we can move to this tile
            if remaining_mp < movement_cost:
                break  # Not enough movement points to continue
            
            # Check if the tile is occupied by another unit
            if game_env.is_occupied(next_pos_tuple) and next_pos_tuple != new_coordinates:
                break  # Can't move through occupied tiles
            
            # Move to this position
            remaining_mp -= movement_cost
            current_pos = next_pos
            final_pos = current_pos.copy()
            
            # If we've reached the destination, we're done
            if tuple(current_pos) == tuple(dest_pos):
                break
        
        # If we didn't move at all, return False
        if np.array_equal(final_pos, self.coordinates):
            return False, self.coordinates
        
        # Remove the unit from its current tile
        game_env.remove_unit_from_tile(self, self.coordinates)
        
        # Update unit's position and movement points
        self.coordinates = tuple(final_pos)
        self.movement_points = remaining_mp
        
        # Add the unit to its new tile
        game_env.add_unit_to_tile(self, self.coordinates)
        
        # Reset fortification when moving
        self.fortification = 0
        
        # Return True if we moved at all, along with the final position
        return True, self.coordinates
    
    def fortify(self):
        """Fortify the unit, increasing its defensive capabilities."""
        if self.movement_points > 0:
            self.fortification = 1
            self.movement_points = 0
            return True
        return False
    
    def fortify_until_healed(self):
        """Fortify the unit until it heals to full health."""
        if self.movement_points > 0:
            self.fortification = 1
            self.movement_points = 0
            return True
        return False
    
    def calculate_damage(self, attacker_strength, defender_strength):
        """
        Calculate damage using the Civ6 formula.
        
        Damage(HP) = 30 * e^(0.04 * StrengthDifference) * random(80%, 120%)
        
        Returns:
            float: Amount of damage to be inflicted
        """
        strength_diff = attacker_strength - defender_strength
        base_damage = 30 * math.exp(0.04 * strength_diff)
        
        # Apply random factor between 80% and 120%
        random_factor = random.uniform(0.8, 1.2)
        damage = base_damage * random_factor
        
        return max(1, min(100, damage))  # Ensure damage is between 1 and 100
    
    def attack(self, target, game_env, is_ranged=False):
        """
        Attack another unit.
        
        Args:
            target (Unit): The unit being attacked
            game_env: The game environment
            is_ranged (bool): Whether this is a ranged attack
            
        Returns:
            tuple: (damage_dealt, damage_received, target_killed, attacker_killed)
        """
        # Check if unit has enough movement points to attack
        if self.movement_points < 0.25:  # Require at least 0.25 MP to attack
            return 0, 0, False, False
        
        # For ranged units, check if they have the necessary movement points
        if is_ranged and self.unit_type == "Catapult" and self.movement_points < 1:
            return 0, 0, False, False  # Catapults can't attack after moving unless they have Expert Crew
        
        # Calculate combat strengths
        if is_ranged:
            is_city = hasattr(target, 'is_city') and target.is_city
            attacker_strength = self.get_ranged_strength(target, is_city)
            # No counterattack for ranged
            damage_received = 0
        else:
            attacker_strength = self.get_combat_strength(True, target)
            defender_counterattack_strength = target.get_combat_strength(True, self)
        
        defender_strength = target.get_combat_strength(False, self)
        
        # Calculate damage
        damage_dealt = self.calculate_damage(attacker_strength, defender_strength)
        
        # Apply damage to target
        target.health -= damage_dealt
        target_killed = target.health <= 0
        
        # For melee attacks, calculate counterattack damage
        attacker_killed = False
        if not is_ranged and not target_killed:
            # Counterattack damage
            damage_received = self.calculate_damage(defender_counterattack_strength, attacker_strength)
            self.health -= damage_received
            attacker_killed = self.health <= 0
        else:
            damage_received = 0
        
        # Consume movement points
        if is_ranged:
            self.movement_points = 0  # Ranged attacks end turn
        else:
            self.movement_points = 0  # Melee attacks end turn
        
        # Reset fortification status when attacking
        self.fortification = 0
        
        return damage_dealt, damage_received, target_killed, attacker_killed

    def take_damage(self, damage): # WE USE THIS
        self.health -= damage

    # def heal(self, amount):
    #     self.movement_points = 0
    #     if self.health == self.max_health:
    #         return
    #     self.health += amount
    #     self.health = min(self.health, self.max_health)
    #     if self.verbose:
    #         print(f"{self.player.name} {self.unit_type} healed by {amount}. Health now {self.health}")
            
        
        
    # def default_movement_points(self):
    #     if self.unit_type == 'Warrior':
    #         return 1
    #     else:
    #         return 1

    # def fortify(self):
    #     if self.defence_bonus <= 3:
    #         self.defence_bonus += 3
    
    # def end_of_turn_action(self):
    #     if self.movement_points == self.max_movement_points:
    #         # calculate healing amout
    #         self.heal(10)
    #     else: 
    #         self.defence_bonus = 0
    #     self.movement_points = self.max_movement_points
    
class WarriorUnit(Unit):
    """Basic melee combat unit."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Warrior", terrain)

class ArcherUnit(Unit):
    """Basic ranged combat unit."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Archer", terrain)
    
    def attack(self, target, game_env):
        """Archers perform ranged attacks."""
        # Check range
        distance = abs(target.coordinates[0] - self.coordinates[0]) + abs(target.coordinates[1] - self.coordinates[1])
        if distance > self.get_range():
            return 0, 0, False, False  # Target out of range
        
        # Check line of sight (simplified)
        has_line_of_sight = game_env.check_line_of_sight(self.coordinates, target.coordinates)
        if not has_line_of_sight and distance > 1:  # Always can attack adjacent tiles
            return 0, 0, False, False  # No line of sight
        
        # Perform ranged attack
        return super().attack(target, game_env, is_ranged=True)

class SwordsmanUnit(Unit):
    """Advanced melee combat unit."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Swordsman", terrain)

class SpearmanUnit(Unit):
    """Anti-cavalry unit."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Spearman", terrain)

class HorsemanUnit(Unit):
    """Fast cavalry unit."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Horseman", terrain)

class CatapultUnit(Unit):
    """Siege unit effective against cities."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Catapult", terrain)
    
    def attack(self, target, game_env):
        """Catapults perform bombard attacks."""
        # Check if target is a city
        is_city = hasattr(target, 'is_city') and target.is_city
        
        # Check range
        distance = abs(target.coordinates[0] - self.coordinates[0]) + abs(target.coordinates[1] - self.coordinates[1])
        if distance > self.get_range():
            return 0, 0, False, False  # Target out of range
        
        # Check line of sight (simplified)
        has_line_of_sight = game_env.check_line_of_sight(self.coordinates, target.coordinates)
        if not has_line_of_sight and distance > 1:  # Always can attack adjacent tiles
            return 0, 0, False, False  # No line of sight
        
        # Perform bombard attack
        return super().attack(target, game_env, is_ranged=True)

class SettlerUnit(Unit):
    """Unit for founding new cities."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Settler", terrain)
    
    def found_city(self, game_env, name="New City"):
        """
        Found a new city at the unit's current location.
        
        Args:
            game_env: The game environment
            name (str): The name for the new city
            
        Returns:
            City: The newly founded city, or None if founding failed
        """
        # Check if we can found a city here
        if not game_env.can_found_city_at(self.coordinates):
            return None
        
        # Create a new city
        city = City(self.player, self.coordinates, name)
        
        # Add the city to the player's list of cities
        self.player.cities.append(city)
        
        # Add the city to the game environment
        game_env.add_city(city)
        
        # Remove the settler unit
        self.player.remove_unit(self)
        
        return city
    
    
class WorkerUnit(Unit):
    """Unit for tile improvements."""
    
    def __init__(self, player, coordinates, terrain=None):
        super().__init__(player, coordinates, "Worker", terrain)
    
    def build_improvement(self, improvement_type, game_env):
        """
        Build an improvement on the current tile.
        
        Args:
            improvement_type (str): The type of improvement to build
            game_env: The game environment
            
        Returns:
            bool: True if improvement was built, False otherwise
        """
        # Check if we can build this improvement here
        if not game_env.can_build_improvement_at(self.coordinates, improvement_type):
            return False
        
        # Build the improvement
        game_env.add_improvement(self.coordinates, improvement_type)
        
        # Consume movement points
        self.movement_points = 0
        
        return True

class City:
    """Represents a city in the game."""
    
    def __init__(self, player, coordinates, name):
        self.player = player
        self.coordinates = coordinates
        self.name = name
        self.health = 200
        self.is_city = True
        self.defense_strength = 20  # Base defense strength
        self.buildings = []
        self.population = 1
        self.food = 0
        self.production = 0
        self.current_production = None
    
    def get_combat_strength(self, is_attacking=False, target=None):
        """Return the defensive combat strength of the city."""
        # Base city defense value
        strength = self.defense_strength
        
        # Add bonuses for walls and other defensive buildings
        for building in self.buildings:
            if building == "Walls":
                strength += 30
            elif building == "Castle":
                strength += 20
        
        return strength
    
    def produce_unit(self, unit_type):
        """
        Start producing a unit.
        
        Args:
            unit_type (str): The type of unit to produce
            
        Returns:
            bool: True if production started, False otherwise
        """
        self.current_production = {"type": "unit", "unit_type": unit_type}
        return True
    
    def produce_building(self, building_type):
        """
        Start producing a building.
        
        Args:
            building_type (str): The type of building to produce
            
        Returns:
            bool: True if production started, False otherwise
        """
        self.current_production = {"type": "building", "building_type": building_type}
        return True
    
    def process_turn(self, game_env):
        """
        Process a game turn for this city.
        
        Args:
            game_env: The game environment
        """
        # Generate resources
        self.food += self.calculate_food(game_env)
        self.production += self.calculate_production(game_env)
        
        # Check for population growth
        if self.food >= self.population * 20:
            self.food -= self.population * 20
            self.population += 1
        
        # Process current production
        if self.current_production:
            if self.current_production["type"] == "unit":
                unit_type = self.current_production["unit_type"]
                unit_cost = self.get_unit_cost(unit_type)
                
                if self.production >= unit_cost:
                    self.production -= unit_cost
                    self.complete_unit_production(unit_type, game_env)
                    self.current_production = None
            
            elif self.current_production["type"] == "building":
                building_type = self.current_production["building_type"]
                building_cost = self.get_building_cost(building_type)
                
                if self.production >= building_cost:
                    self.production -= building_cost
                    self.buildings.append(building_type)
                    self.current_production = None
    
    def calculate_food(self, game_env):
        """Calculate food production for this turn."""
        # Base food production
        food = 2 * self.population
        
        # Add food from worked tiles
        # This is a simplified version - a real implementation would check tiles
        return food
    
    def calculate_production(self, game_env):
        """Calculate production output for this turn."""
        # Base production
        production = 1 + self.population
        
        # Add production from worked tiles and buildings
        for building in self.buildings:
            if building == "Workshop":
                production += 3
            elif building == "Factory":
                production += 5
        
        return production
    
    def get_unit_cost(self, unit_type):
        """Get the production cost for a unit type."""
        # Create a temporary unit to get its cost
        temp_unit = Unit(None, None, unit_type)
        return temp_unit.get_production_cost()
    
    def get_building_cost(self, building_type):
        """Get the production cost for a building type."""
        costs = {
            "Granary": 60,
            "Monument": 50,
            "Walls": 100,
            "Workshop": 120,
            "Factory": 240
        }
        return costs.get(building_type, 100)
    
    def complete_unit_production(self, unit_type, game_env):
        """
        Complete production of a unit.
        
        Args:
            unit_type (str): The type of unit produced
            game_env: The game environment
        """
        # Find an unoccupied adjacent tile to place the unit
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                
                new_coords = (self.coordinates[0] + dx, self.coordinates[1] + dy)
                if game_env.is_valid_position(new_coords) and not game_env.is_occupied(new_coords):
                    # Create the appropriate unit type
                    if unit_type == "Warrior":
                        unit = WarriorUnit(self.player, new_coords)
                    elif unit_type == "Archer":
                        unit = ArcherUnit(self.player, new_coords)
                    elif unit_type == "Swordsman":
                        unit = SwordsmanUnit(self.player, new_coords)
                    elif unit_type == "Spearman":
                        unit = SpearmanUnit(self.player, new_coords)
                    elif unit_type == "Horseman":
                        unit = HorsemanUnit(self.player, new_coords)
                    elif unit_type == "Catapult":
                        unit = CatapultUnit(self.player, new_coords)
                    elif unit_type == "Settler":
                        unit = SettlerUnit(self.player, new_coords)
                    elif unit_type == "Worker":
                        unit = WorkerUnit(self.player, new_coords)
                    else:
                        # Default case
                        unit = Unit(self.player, new_coords, unit_type)
                    
                    # Add the unit to the player's list
                    self.player.units.append(unit)
                    return True
        
        # If we couldn't place the unit, store it for later placement
        self.player.queued_units.append({"type": unit_type, "city": self})
        return False
        
        
    def set_owner(self, new_player):
        # Check if the city is owned by a player
        if self.player:
            self.player.cities.remove(self)       
        
        new_player.cities.append(self)
        self.player = new_player

class Player:
    """Represents a player in the game."""
    
    def __init__(self, name, player_index, game_env):
        self.name = name
        self.player_index = player_index
        self.game_env = game_env
        self.cities = []
        self.units = []
        self.queued_units = []
        self.is_dead = False
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.technologies = []
        self.policies = []
    
    def start_turn(self):
        """Process the start of a player's turn."""
        # Reset movement points for all units
        for unit in self.units:
            unit.reset_movement()
        
        # Process city production
        for city in self.cities:
            city.process_turn(self.game_env)
        
        # Try to place queued units
        queued_units_copy = self.queued_units.copy()
        self.queued_units = []
        
        for queued_unit in queued_units_copy:
            city = queued_unit["city"]
            unit_type = queued_unit["type"]
            
            # Try again to place the unit
            placed = city.complete_unit_production(unit_type, self.game_env)
            
            if not placed:
                # If still can't place, re-queue
                self.queued_units.append(queued_unit)
    
    def end_turn(self):
        """Process the end of a player's turn."""
        # Check if player is defeated (no cities left)
        if len(self.cities) == 0:
            self.is_dead = True
            # Remove all units when a player is defeated
            units_copy = self.units.copy()
            for unit in units_copy:
                self.game_env.delete_unit(unit)
    
    def remove_unit(self, unit):
        """Remove a unit from the player's control."""
        if unit in self.units:
            self.units.remove(unit)
            
def create_unit(unit_type, player, coordinates):
    """Factory function to create the appropriate unit type."""
    from game_units import (
        WarriorUnit, ArcherUnit, SwordsmanUnit, SpearmanUnit,
        HorsemanUnit, CatapultUnit, SettlerUnit, WorkerUnit
    )
    
    # Get the terrain type
    tile = player.game_env.map.get_tile(coordinates)
    terrain = tile.terrain_type if tile else None
    
    # Create the appropriate unit type
    if unit_type == "Warrior":
        return WarriorUnit(player, coordinates, terrain)
    elif unit_type == "Archer":
        return ArcherUnit(player, coordinates, terrain)
    elif unit_type == "Swordsman":
        return SwordsmanUnit(player, coordinates, terrain)
    elif unit_type == "Spearman":
        return SpearmanUnit(player, coordinates, terrain)
    elif unit_type == "Horseman":
        return HorsemanUnit(player, coordinates, terrain)
    elif unit_type == "Catapult":
        return CatapultUnit(player, coordinates, terrain)
    elif unit_type == "Settler":
        return SettlerUnit(player, coordinates, terrain)
    elif unit_type == "Worker":
        return WorkerUnit(player, coordinates, terrain)
    else:
        # Default case - generic unit
        from game_units import Unit
        return Unit(player, coordinates, unit_type, terrain)

# class Player:
#     def __init__(self, name, player_index, game_env):
#         self.name = name
#         self.player_index = player_index
#         self.game_env = game_env
#         self.units = []
#         self.cities = []
#         self.queued_units = [] # I dont know about this? Should be in cities? Or is it generals?
#         self.gold = 0
#         self.science = 0
#         self.culture = 0
#         self.faith = 0
#         self.technologies = []
#         self.starting_location # I'll keep it for now, migt want to delete? It was a tuple (0,0)
#         self.is_dead = False
#         self.units_with_no_movement = [] # Might want to delete.
        
            
#     def add_unit(self, unit):
#         self.units.append(unit)
    
#     def add_city(self, city):
#         self.cities.append(city)
    
#     def remove_unit(self, unit):
#         if unit in self.units:
#             self.units.remove(unit)

        
#     # def get_unit_at_pos(self, position):
#     #     for unit in self.units:
#     #         if unit.position == position:
#     #             return unit
#     #     return I dont think this is used, if it is, it should state units since it could be many. let's try to remove it.
    
   
#     def start_turn(self):
#         """Process the start of a player's turn."""
#         # Reset movement points for all units
#         for unit in self.units:
#             unit.reset_movement()
        
#         # Process city production
#         for city in self.cities:
#             city.process_turn(self.game_env)
        
#         # Try to place queued units
#         queued_units_copy = self.queued_units.copy()
#         self.queued_units = []
        
#         for queued_unit in queued_units_copy:
#             city = queued_unit["city"]
#             unit_type = queued_unit["type"]
            
#             # Try again to place the unit
#             placed = city.complete_unit_production(unit_type, self.game_env)
            
#             if not placed:
#                 # If still can't place, re-queue
#                 self.queued_units.append(queued_unit)
        
#     # def get_unmoved_positions(self):
#     #     untouched_locations = []
#     #     for unit in self.units:
#     #         if unit.movement_points > 0:
#     #             untouched_locations.append(unit.location)
#     #     return untouched_locations
                    
#     # def end_turn(self):
#     #     for unit in self.units:
#     #         unit.end_of_turn_action()
    
#     def end_turn(self):
#         """Process the end of a player's turn."""
#         # Check if player is defeated
#         if len(self.cities) == 0:
#             self.is_dead = True
#             # Remove all units completely from the game
#             units_copy = self.units.copy()  # Create a copy to avoid modifying while iterating
#             for unit in units_copy:
#                 self.game_env.delete_unit(unit)  # This should handle updating the player's unit list too
    
 

class GameEnvironment:
    """Manages the game state and interactions between players, units, and the map."""
    
    def __init__(self, n, m, num_players=2, map_type="continents"):
        self.n = n  # Grid rows
        self.m = m  # Grid columns
        self.turn_counter = 1
        self.players = []
        
        # Initialize the map
        self.map = Map(n, m)
        self.map.generate_map(map_type)
        
        # Create players
        for i in range(num_players):
            player = Player(f"Player {i+1}", i, self)
            self.players.append(player)
        
        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]
        self.max_turns = 1000
        
    def reset(self, num_players=None):
        """
        Reset the game environment to start a new game.
        
        Args:
            num_players (int, optional): Number of players for the new game. 
                                        If None, uses the current number of players.
        
        Returns:
            self: The reset game environment
        """
        # If num_players is provided, update the number of players
        if num_players is not None:
            self.players = []
        else:
            num_players = len(self.players)
            
        # Reset turn counter and done state
        self.turn_counter = 1
        self.done = False
        
        # Initialize or reinitialize the map
        self.map.generate_map()
        
        # Create or recreate players
        if not self.players:  # Only create new players if the list is empty
            for i in range(num_players):
                player = self.__class__.Player(f"Player {i+1}", i, self)
                self.players.append(player)
        else:
            # Reset existing players
            for player in self.players:
                player.units = []
                player.cities = []
                player.queued_units = []
                player.is_dead = False
                player.gold = 0
                player.science = 0
                player.culture = 0
                player.technologies = []
                player.policies = []
        
        # Calculate starting locations
        if num_players == 2:
            # For 2 players, place them on opposite sides of the map
            p1_x = random.randint(0, self.n-1)
            p1_y = random.randint(0, self.m//2-1)
            p2_x = random.randint(0, self.n-1)
            p2_y = random.randint(self.m//2, self.m-1)
            
            player1_start = (p1_x, p1_y)
            player2_start = (p2_x, p2_y)
            
            starting_locations = [player1_start, player2_start]
        else:
            # For more players, partition the map
            starting_locations = []
            for i in range(num_players):
                partition = self.m // num_players
                x = random.randint(0, self.n-1)
                y = random.randint(i * partition, (i + 1) * partition - 1)
                starting_locations.append((x, y))
        
        # Add starting units and cities for each player
        for i, player in enumerate(self.players):
            # Get starting location
            start_x, start_y = starting_locations[i]
            
            # Add city at starting location
            self.found_city(player, (start_x, start_y), f"{player.name}'s Capital")
            
            # Add initial units around the city
            unit_positions = [
                (start_x, (start_y + 1) % self.m),  # Right
                ((start_x + 1) % self.n, start_y),  # Down
                ((start_x + 1) % self.n, (start_y + 1) % self.m)  # Diagonal
            ]
            
            for pos in unit_positions:
                # Check if position is valid and not occupied
                if self.is_valid_position(pos) and not self.is_occupied(pos):
                    # Create a warrior unit
                    tile = self.map.get_tile(pos)
                    terrain = tile.terrain_type if tile else "Plains"
                    unit = WarriorUnit(player, pos, terrain)
                    player.units.append(unit)
                    self.add_unit_to_tile(unit, pos)
        
        # Set current player
        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]
        
        return self

    def step(self, action_matrix):
        """
        Execute an action in the game environment.
        
        Args:
            action_matrix: A list containing [select_position, order_position] as numpy arrays
            
        Returns:
            tuple: (self, reward, done) - The updated environment, reward gained, and whether the game is done
        """
        reward = 0
        select_pos = tuple(action_matrix[0])
        order_pos = tuple(action_matrix[1])
        
        # Check if "end turn" action
        if select_pos == (self.n, 0):
            self.current_player.end_turn()
            self.next_turn()
            return self, 0, self.done
        
        # Try to find the unit directly by coordinates
        selected_unit = None
        for unit in self.current_player.units:
            if unit.coordinates == select_pos:
                selected_unit = unit
                break
        
        if not selected_unit:
            return self, -1, self.done  # No unit found penalty
        
        # If unit has no movement points, return small penalty
        if selected_unit.movement_points <= 0:
            return self, -1, self.done
        
        # If select and order positions are the same, fortify
        if select_pos == order_pos:
            success = selected_unit.fortify()
            if success:
                return self, 0, self.done
            else:
                return self, -1, self.done
        
        # Movement logic
        moved, final_pos = selected_unit.move(order_pos, self)
        
        if moved:
            # Check if we captured a city
            tile = self.map.get_tile(final_pos)
            if tile and tile.city and tile.city.player != self.current_player:
                # Transfer ownership
                tile.city.set_owner(self.current_player)
                reward += 20  # Reward for capturing a city
        
        if not moved:
            return self, -1, self.done
        
        # Check if turn should end (all units have used their movement points)
        all_units_moved = all(u.movement_points == 0 for u in self.current_player.units)
        
        if all_units_moved:
            self.current_player.end_turn()
            self.next_turn()
        
        # Check turn limit
        if self.turn_counter > self.max_turns:
            self.done = True
        
        return self, 0, self.done  # Small reward for successful movement
    
    def debug_units_locations(self):
        """Print the locations of all units in the game for debugging."""
        print("\nDEBUG: Unit Locations")
        
        for player_idx, player in enumerate(self.players):
            print(f"Player {player_idx + 1} ({player.name}) units:")
            for unit_idx, unit in enumerate(player.units):
                print(f"  Unit {unit_idx}: {unit.unit_type} at {unit.coordinates} with {unit.movement_points} MP")
                
                # Check if the unit is actually in the tile it thinks it's in
                tile_units = self.get_units_at(unit.coordinates)
                if unit not in tile_units:
                    print(f"    ⚠️ WARNING: Unit thinks it's at {unit.coordinates} but is not found there!")
                    
                # Check if there are other units at the same coordinates
                if len(tile_units) > 1:
                    print(f"    ⚠️ Multiple units at {unit.coordinates}: {len(tile_units)} units")
    
    def get_terrain_at(self, coordinates):
        """Get the terrain type at the given coordinates."""
        tile = self.map.get_tile(coordinates)
        return tile.terrain_type if tile else None
    
    def has_feature(self, coordinates, feature_type):
        """Check if a tile has a specific feature."""
        tile = self.map.get_tile(coordinates)
        return tile and tile.has_feature(feature_type)
    
    def is_river_between(self, coords1, coords2):
        """Check if there's a river between two adjacent tiles."""
        return self.map.has_river_between(coords1, coords2)
    
    def check_line_of_sight(self, from_coords, to_coords):
        """Check if there's a clear line of sight between two coordinates."""
        return self.map.check_line_of_sight(from_coords, to_coords)
    
    def is_valid_position(self, coordinates):
        """Check if coordinates are within the grid."""
        return self.map.get_tile(coordinates) is not None
    
    def is_occupied(self, coordinates):
        """Check if a tile is occupied by a unit."""
        tile = self.map.get_tile(coordinates)
        return tile and len(tile.units) > 0
    
    def get_units_at(self, coordinates):
        """Get all units at the specified coordinates."""
        tile = self.map.get_tile(coordinates)
        return tile.units if tile else []
    
    def add_unit_to_tile(self, unit, coordinates):
        """Add a unit to a tile."""
        tile = self.map.get_tile(coordinates)
        if tile:
            tile.add_unit(unit)
            unit.coordinates = coordinates
    
    def remove_unit_from_tile(self, unit, coordinates):
        """Remove a unit from a tile."""
        tile = self.map.get_tile(coordinates)
        if tile:
            tile.remove_unit(unit)
    
    def move_unit(self, unit, new_coordinates):
        """Move a unit from its current tile to a new tile."""
        # Remove from current tile
        self.remove_unit_from_tile(unit, unit.coordinates)
        
        # Add to new tile
        self.add_unit_to_tile(unit, new_coordinates)
    
    def delete_unit(self, unit):
        """
        Delete a unit completely from the game.
        
        This removes the unit from both its tile and the player's units list.
        """
        # Remove from tile
        self.remove_unit_from_tile(unit, unit.coordinates)
        
        # Remove from player's units
        unit.player.remove_unit(unit)
    
    def can_found_city_at(self, coordinates):
        """Check if a city can be founded at the given coordinates."""
        tile = self.map.get_tile(coordinates)
        
        # Can't found on invalid tiles or mountains/ocean
        if not tile or tile.terrain_type in ["Mountain", "Ocean"] or tile.city:
            return False
        
        # Check minimum distance from other cities (usually 3 tiles in Civ)
        for player in self.players:
            for city in player.cities:
                distance = self.map.distance_function(coordinates, city.coordinates)
                if distance < 3:
                    return False
        
        return True
    
    def found_city(self, player, coordinates, name="New City"):
        """
        Found a new city at the specified coordinates.
        
        Args:
            player: The player founding the city
            coordinates: The coordinates for the new city
            name: The name for the new city
            
        Returns:
            City: The newly founded city, or None if founding failed
        """
        if not self.can_found_city_at(coordinates):
            return None
        
        # Create the city
        city = City(player, coordinates, name)
        
        # Set the city on the tile
        tile = self.map.get_tile(coordinates)
        tile.set_city(city)
        
        # Add to player's cities
        player.cities.append(city)
        
        return city
    
    def can_build_improvement_at(self, coordinates, improvement_type):
        """Check if an improvement can be built at the specified coordinates."""
        tile = self.map.get_tile(coordinates)
        
        # Basic checks
        if not tile or tile.city or improvement_type in tile.improvements:
            return False
        
        # Check terrain compatibility
        terrain_improvements = {
            "Farm": ["Plains", "Grassland", "Desert", "Floodplains"],
            "Mine": ["Hills", "Desert", "Tundra", "Snow"],
            "Plantation": ["Plains", "Grassland", "Desert"],
            "Camp": ["Plains", "Grassland", "Tundra", "Desert"],
            "Pasture": ["Plains", "Grassland", "Desert", "Tundra"],
            "Quarry": ["Plains", "Desert", "Grassland", "Tundra"],
            "Fishing Boats": ["Coast", "Lake"],
            "Oil Well": ["Desert", "Tundra", "Snow", "Coast", "Ocean"]
        }
        
        valid_terrains = terrain_improvements.get(improvement_type, [])
        return tile.terrain_type in valid_terrains
    
    def build_improvement(self, coordinates, improvement_type):
        """
        Build an improvement on the specified tile.
        
        Args:
            coordinates: The coordinates for the improvement
            improvement_type: The type of improvement to build
            
        Returns:
            bool: True if improvement was built, False otherwise
        """
        if not self.can_build_improvement_at(coordinates, improvement_type):
            return False
        
        # Add the improvement to the tile
        tile = self.map.get_tile(coordinates)
        tile.add_improvement(improvement_type)
        
        return True
    
    def next_turn(self):
        """Process the end of the current turn and move to the next player."""
        # Process end turn for current player
        self.current_player.end_turn()
        
        # Move to next player
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.current_player = self.players[self.current_player_index]
        
        # If we've gone through all players, increment turn counter
        if self.current_player_index == 0:
            self.turn_counter += 1
        
        # Process start turn for new current player
        self.current_player.start_turn()
        # Check if the game is over
        alive_players = [p for p in self.players if not p.is_dead]
        if len(alive_players) <= 1:
            self.done = True
            
        # Check turn limit
        if self.turn_counter > self.max_turns:
            self.done = True
    
    def path_finder(self, start, destination):
        """Wrapper for the map's path finder."""
        return self.map.path_finder(start, destination)
    
    def distance_function(self, p1, p2):
        """Wrapper for the map's distance function."""
        return self.map.distance_function(p1, p2)
# class GameEnvironment:
#     def __init__(self, n, m, number_of_players):
#         self.n = n #rows of map
#         self.m = m #cols of map
#         self.d = 2 * number_of_players + 1 # own cities, own units, movement points,  enemy cities, enemy units = Nplayers*2 +1 
#         self.turn_counter = 0
#         self.current_player = None
#         self.players = [] # the dictionary should be ordered. (comment for later cython implementation)
#         self.done = False
#         self.state = torch.zeros(self.d,self.n,self.m)
#         self.number_of_players = number_of_players # needs to be UPDATED WHEN SOMEONE DIES!!!!
#         self.map = None
        
#         self.attack_XP = 6
#         self.defend_XP = 3
#         self.kill_XP = 4
        
#         self.kill_reward = 50
#         self.damage_reward = 10
#         self.city_capture_reward = 60
#         self.win_reward = 100
#         self.reward = {"Capture Enemy City": 100}
#         self.max_turns = 250
        

#     def get_raw_state(self):
#         """
#         Returns the raw game state without converting to a tensor.
#         This will be used by agents to build their own state representations.
        
#         Returns:
#             self: The current game environment (agents can extract what they need)
#         """
#         # For now, we simply return the game environment instance itself
#         # Agents can extract the data they need from it
#         return self
    
#     def distance_function(self, p1, p2):
#         # Calculate direct dx
#         dx = p2[1] - p1[1]
        
#         # Check if wrapping around the map is shorter
#         dx_wrapped = dx
#         if abs(dx) > self.m / 2:  # If more than halfway across map
#             if dx > 0:
#                 dx_wrapped = dx - self.m  # Wrap around left
#             else:
#                 dx_wrapped = dx + self.m  # Wrap around right
        
#         # Use the shorter horizontal distance
#         dx = dx_wrapped
        
#         # Calculate vertical distance
#         dy = p2[0] - p1[0]
        
#         # Calculate hex distance
#         if dx*dy > 0:
#             d = max(abs(dx), abs(dy))
#         else:
#             d = abs(dx) + abs(dy)
        
#         return d
    
#     def path_finder(self, p1, p2):
#         orders = []
#         current_position = p1.copy()  # Create a copy of p1 to work with
#         destination = p2.copy()
        
        
#         if self.distance_function(current_position, destination) > self.distance_function(p1, (destination + np.array([0,self.m]))):
#             destination = destination + np.array([0, self.m])
        
        
#         dx, dy = destination - current_position
#         modulus = np.array([self.n,self.m])
        
        
#         while self.distance_function(destination, current_position) > 0:
#             if dx > 0 and dy > 0:
#                 current_position += np.array([1, 1])
#                 orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
#                 dx -= 1
#                 dy -= 1
#             elif dx < 0 and dy < 0:
#                 current_position -= np.array([1, 1])
#                 orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
#                 dx += 1
#                 dy += 1
#             elif dx > 0 and dy == 0:
#                 current_position += np.array([1, 0])
#                 orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
#                 dx -= 1
#             elif dx < 0 and dy == 0:
#                 current_position -= np.array([1, 0])
#                 orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
#                 dx += 1
#             elif dy > 0:
#                 current_position += np.array([0, 1])
#                 orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
#                 dy -= 1
#             elif dy < 0:
#                 current_position -= np.array([0, 1])
#                 orders.append(current_position.copy()%modulus)  # Append a copy of the updated position
#                 dy += 1
    
#         return orders
    
#     def check_if_done(self):
#         if self.max_turns:
#             if self.turn_counter > self.max_turns:
#                 self.done = True
        
#         #Check if alive twice : We want to print player is dead only the same turn the player died.
#         number_of_players_alive = 0
#         for player in self.players:            
#             if not player.is_dead:
#                 player.check_if_dead()
#                 if player.is_dead:
#                     print(f"{player.name} is dead.")
#             if not player.is_dead:
#                 number_of_players_alive += 1
                
        
#         if number_of_players_alive <= 1:
#             self.done = True
                       
#     def add_player(self, name):
#         self.players.append(Player(name, len(self.players)))
        
#     def add_unit(self, player, coordinates, unit_type):
#         unit = Unit(player, coordinates, unit_type)
#         player.add_unit(unit)
#         self.map.tiles[tuple(coordinates)].units.append(unit)
        
#     def add_city(self, player, coordinates):
#         city_name = player.name + ' City'
#         city = City(player, coordinates, city_name)
#         player.add_city(city)
#         self.map.tiles[tuple(coordinates)].city = city        
    
#     def reset(self):
#         self.done = False
#         # Clear existing players and add new ones
#         self.map = Map(self.n, self.m)
#         self.map.generate_map()
#         self.players.clear()
#         self.turn_counter = 1
#         for i in range(self.number_of_players):
#             self.add_player(f"Player {i+1}")
        
#         self.state = torch.zeros(self.d,self.n,self.m)
        
#         # calculate starting locations
#         if self.number_of_players == 2:
#             self.players[0].starting_location = np.array([random.randint(0,self.n-1), random.randint(0, self.m//2-1)])
#             self.players[1].starting_location = np.array([random.randint(0,self.n-1), random.randint(self.m//2, self.m-1)])
#         else:
#             for player in self.players:
#                 partition = self.m // self.number_of_players
#                 player.starting_location = np.array([random.randint(0,self.n-1), random.randint(player.player_index * partition , (player.player_index + 1) * partition - 1)]) #needs work, might create players on top of each other!!!!
#                 # make this like 2playter version but partition the map in equal parts.
            
                
#         for player in self.players:
#             map_size = np.array([self.n,self.m])
#             coord0 = player.starting_location % map_size
#             coord1 = (coord0 + np.array([1, 1])) % map_size
#             coord2 = (coord0 + np.array([0, 1])) % map_size
#             self.add_unit(player, coord0, 'Warrior')
#             self.add_unit(player, coord1, 'Warrior')
#             self.add_unit(player, coord2, 'Warrior')
#             self.add_city(player, player.starting_location)
            
#         self.current_player = self.players[0] # Player 1 starts the game
#         return self.get_raw_state()
    
#     def delete_unit(self, unit):
#         # Remove from the tile
#         tile = self.map.tiles[tuple(unit.coordinates)]
#         if unit in tile.units:
#             tile.units.remove(unit)
        
#         # Remove from the player
#         player = unit.player
#         if unit in player.units:
#             player.units.remove(unit)
            
#         # Print:
#         print(f'{unit.player.name} {unit.unit_type} deleted')
    
#         # Additional cleanup (if necessary)
#         del unit  # Optional, not strictly necessary in Python due to garbage collection
    
    


#     def execute(self, unit, order):
#         reward = 0
        
            
#         if unit.unit_type == 'Warrior':
#             if (order == unit.coordinates).all():
#                 unit.fortify()
#                 unit.movement_points = 0
                
#             else:
#                path = self.path_finder(unit.coordinates.copy(), order) 
#                while unit.movement_points > 0 and len(path) > 0: 
#                    next_tile_coord = path.pop(0)
                   
#                    #CHECK IF TILE IS FREE
#                    if len(self.map.tiles[tuple(next_tile_coord)].units)==0:
#                        # Tile free, let's move there
#                        if unit in self.map.tiles[tuple(unit.coordinates)].units:
#                            self.map.tiles[tuple(unit.coordinates)].units.remove(unit)
    
#                            # Update the unit's coordinates and move it to the new tile
#                            unit.coordinates = next_tile_coord
#                            self.map.tiles[tuple(next_tile_coord)].units.append(unit)
#                            # Reduce movement points based on the movement cost of the new tile
#                            unit.movement_points -= self.map.tiles[tuple(next_tile_coord)].movement_cost
#                    else:
#                        # Tile occupied by a unit, check if friendly or hostile:
#                        if unit.player == self.map.tiles[tuple(next_tile_coord)].units[0].player:
#                            #Friendly Unit Detected - Setting movement points to zero - Not an ideal solution but will work for now.
#                            unit.movement_points = 0
#                            reward -= 1
#                        else:
#                            #Enemy unit detected, attack!
#                            enemy_unit = self.map.tiles[tuple(next_tile_coord)].units[0]
                           
#                            # ATTACK LOGIC
#                            # ------------
                           
#                            print(f'{unit.player.name} {unit.unit_type} attacks {enemy_unit.player.name} {enemy_unit.unit_type}')
                           
#                            defence_modifier = 1 - (self.map.tiles[tuple(enemy_unit.coordinates)].defence_bonus + enemy_unit.defence_bonus)/10
#                            unit_attack_modifier = max(.6,(unit.health / unit.max_health))
                           
#                            enemy_unit.take_damage(unit.attack_power * unit_attack_modifier * defence_modifier)
#                            enemy_unit_attack_modifier = max(.6, enemy_unit.health / enemy_unit.max_health)
                           
#                            unit.take_damage(enemy_unit.attack_power * enemy_unit_attack_modifier)
#                            unit.xp += self.attack_XP
#                            enemy_unit.xp += self.defend_XP
                           
#                            if unit.health <= 0 and enemy_unit.health <= 0:
#                                # Special Case: Both died - Let the unit with the least negative health win, defender wins on tie
#                                if enemy_unit.health >= unit.health:
#                                    enemy_unit.health = 1
#                                else:
#                                    unit.health = 1
                                   
#                            if unit.health > 0 and enemy_unit.health > 0:
#                                #BOTH SURVIVED
#                                unit.move_points = 0
#                                reward += self.damage_reward
                               
                               
#                            elif unit.health > 0 and enemy_unit.health <= 0:
#                                #ONLY ATTACKER SURVIED!
#                                reward += self.kill_reward
#                                unit.xp += self.kill_XP
#                                self.delete_unit(enemy_unit)
#                                # Move the unit on the map
#                                self.map.tiles[tuple(unit.coordinates)].units.remove(unit)
#                                unit.coordinates = next_tile_coord
#                                self.map.tiles[tuple(unit.coordinates)].units.append(unit)
#                                unit.movement_points = 0
                               
                               
#                            elif unit.health <= 0 and enemy_unit.health > 0:
#                               #ONLY DEFENDER SURVIVED
#                               enemy_unit.xp += self.kill_XP
#                               self.delete_unit(unit)
#                               return reward
               
#                    #Check if we captured a new city
#                    if self.map.tiles[tuple(unit.coordinates)].city:
#                        if self.map.tiles[tuple(unit.coordinates)].city.player != unit.player:
#                            self.map.tiles[tuple(unit.coordinates)].city.set_owner(unit.player)
#                            reward += self.city_capture_reward
                       
                   
               
#         return reward               

#     def get_next_player(self, player): 
#         # Find the next player in the list
#         "needs work"
#         if player in self.players:
#             current_index = self.players.index(player)
#             next_index = (current_index + 1) % len(self.players)  # Use modulo for cycling
#             return self.players[next_index]
#         else:
#             print('the player was not in the list')
#             return self.players[0]  # Default to first player if not set
#         return self.players[(player.player_index+1) % len(self.players)]
    
#     # def get_enemy_units(self, player = None):
#     #     if player is None:
#     #         player = self.current_player
#     #     enemy_units = []
#     #     for i in range(self.number_of_players - 1):
#     #         player = self.get_next_player(player)
#     #         for unit in player.units: 
#     #             enemy_units.append(unit)
#     #     return enemy_units
    
#     def check_if_adjacent(p1,p2):
#         dp = p2-p1
#         if np.sign(dp[0]) == np.sign(dp[1]) and max(abs(dp[0]), abs(dp[1])) == 1 or dp[0]*dp[1] == 0 and max(abs(dp[0]), abs(dp[1])):
#             return True
#         else:
#             return False
            
#         # if dp == np.array([-1,0]) or dp == np.array([-1,-1]) or dp == np.array([0,-1]) or :
#         #     dp == np.array([0,1]) or dp == np.array([1,1]) or dp == np.array([1,0]):
#         #         return True
        
       
#     def step(self, action):
#         if self.current_player.is_dead:
#             reward = 0
#             self.current_player.end_turn()
#             next_player = self.get_next_player(self.current_player)
#             self.current_player = next_player
#             self.update_state_tensor()
#             return self.get_raw_state(), reward, self.done
#         reward = 0
#         select = action[0]  # FIX SELECT AND ORDER TO BE i, j indexes - 8/8 -24 erik
#         order = action[1]
#         # CHECK IF END TURN <- Could be moved into execute order as well
#         if (select.tolist() == [self.n,0]):
#             # print(f"{self.current_player.name} End Turn")
#             self.current_player.end_turn()
#             self.current_player = self.get_next_player(self.current_player)            
#             first_alive_player = next(player for player in self.players if not player.is_dead)
#             # Check if the current player is this first alive player
#             if self.current_player == first_alive_player:
#                 self.turn_counter += 1

#                 #OPTIONAL PRINT STATEMENT
#                 if self.turn_counter % 10 == 0:
#                     print(f"Turn {self.turn_counter}")
#             self.check_if_done()  # This was in update_state_tensor()
#             return self.get_raw_state(), reward, self.done
        
#         """SELECT UNIT FROM MAP """
#         if len(self.map.tiles[tuple(select)].units) == 1: # Check that we've selected a unit- we should have! Maybe assert? Maybe remove this all together?
#             reward += self.execute(self.map.tiles[tuple(select)].units[0], order)
            
#         else:
#             print('Selected empty tile :(')
#             print(f'state = {self.state} \nselect = {select}\norder = {order}')
#         # Calculate new state
#         # self.update_state_tensor(self)
#         return self.get_raw_state(), reward, self.done

#     def update_state_tensor(self):
#         """
#         DEPRECATED: This method is kept for backward compatibility.
#         State tensor building should now be handled by the agent.
#         """
#         # Original update_state_tensor code...
#         self.state = torch.zeros(self.d, self.n, self.m)
#         # Update for current player's units
#         player = self.current_player
#         layer_index = 0
#         for city in player.cities: 
#             i, j = city.coordinates
#             self.state[0, i, j] = 100
#         for unit in player.units:
#             i, j = unit.coordinates
#             self.state[1, i, j] = unit.health
#             self.state[2, i, j] = unit.movement_points
            
#         layer_index = 3
#         # Update for other players' units
#         for player_index, player in enumerate(self.players):
#             if player == self.current_player:
#                 continue
#             for city in player.cities:
#                 i, j = city.coordinates
#                 self.state[layer_index, i, j] = -city.worth
#             for unit in player.units:
#                 i, j = unit.coordinates
#                 self.state[layer_index+1, i, j] = -unit.health
#             layer_index += 2
        
#         self.check_if_done()
    

        



"""
Game Loop

"""

# # initialize the game
# game_over = False
# # create map
# n = 10 # rows in map
# m = 15 # columns in map
# number_of_players  = 2
# number_of_unit_types = 1
# d = number_of_players * number_of_unit_types + 1 (#for movement points)


# env = GameEnvironment(n, m, d)
# env.reset(number_of_players)

# p1warr = env.players[0].units[0]
# p2warr = env.players[1].units[0]

# # p1warr.teleport(p2warr.location + np.array([0,-1]))
# state, reward, done = env.step([p1warr.location, p2warr.location])


#%%
# for i in range(2):
#     for unit in env.players[i].units:
#         print(unit.location)