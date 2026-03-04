"""GameEnvironment -- the main game simulation interface."""

import random

from .map import Map
from .player import Player
from .city import City
from .unit import WarriorUnit
from .terrain import Terrain


class GameEnvironment:
    """Manages the game state and interactions between players, units, and the map.

    This is the central Gym-like interface:
        env.reset() -> raw game state
        env.step(action) -> (raw_state, reward, done, info)
    """

    def __init__(self, n, m, num_players=2, map_type="basic"):
        self.n = n
        self.m = m
        self.num_players = num_players
        self.map_type = map_type
        self.turn_counter = 1
        self.max_turns = 1000
        self.done = False
        self.players = []

        # Initialize map and players
        self.map = Map(n, m)
        self.map.generate_map(map_type)

        for i in range(num_players):
            player = Player(f"Player {i+1}", i, self)
            self.players.append(player)

        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]

    def reset(self, num_players=None):
        """Reset the game for a new episode.

        Returns:
            self: The reset game environment (agents extract what they need).
        """
        if num_players is not None:
            self.num_players = num_players

        self.turn_counter = 1
        self.done = False

        # Regenerate map
        self.map = Map(self.n, self.m)
        self.map.generate_map(self.map_type)

        # Reset or recreate players
        if num_players is not None:
            self.players = []
            for i in range(self.num_players):
                player = Player(f"Player {i+1}", i, self)
                self.players.append(player)
        else:
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
        starting_locations = self._calculate_starting_locations()

        # Place starting units and cities
        for i, player in enumerate(self.players):
            start_x, start_y = starting_locations[i]

            self.found_city(player, (start_x, start_y), f"{player.name}'s Capital")

            # Place warriors around the city using hex adjacency
            adj_coords = self.map.get_adjacent_coords((start_x, start_y))
            warriors_placed = 0
            for pos in adj_coords:
                if warriors_placed >= 3:
                    break
                if self.is_valid_position(pos) and not self.is_occupied(pos):
                    tile = self.map.get_tile(pos)
                    terrain = tile.terrain_type if tile else "Plains"
                    unit = WarriorUnit(player, pos, terrain)
                    player.units.append(unit)
                    self.add_unit_to_tile(unit, pos)
                    warriors_placed += 1

        self.current_player_index = 0
        self.current_player = self.players[self.current_player_index]

        return self

    def _calculate_starting_locations(self):
        """Calculate starting locations for all players, spread across the map."""
        if self.num_players == 2:
            p1_x = random.randint(0, self.n - 1)
            p1_y = random.randint(0, self.m // 2 - 1)
            p2_x = random.randint(0, self.n - 1)
            p2_y = random.randint(self.m // 2, self.m - 1)
            return [(p1_x, p1_y), (p2_x, p2_y)]
        else:
            locations = []
            partition = self.m // self.num_players
            for i in range(self.num_players):
                x = random.randint(0, self.n - 1)
                y = random.randint(i * partition, (i + 1) * partition - 1)
                locations.append((x, y))
            return locations

    def step(self, action_matrix):
        """Execute an action in the game environment.

        Interprets select + order as a player would with two mouse clicks:
        - Select own unit, order to empty tile → move
        - Select own unit, order to same tile → fortify
        - Select own unit, order to enemy unit → attack
        - Select own unit, order to enemy city (no unit) → move and capture

        Args:
            action_matrix: [select_position, order_position] as numpy arrays

        Returns:
            tuple: (self, reward, done)
        """
        reward = 0
        select_pos = tuple(action_matrix[0])
        order_pos = tuple(action_matrix[1])

        # End turn action
        if select_pos == (self.n, 0):
            self.current_player.end_turn()
            self.next_turn()
            return self, 0, self.done

        # Find the selected unit
        selected_unit = None
        for unit in self.current_player.units:
            if unit.coordinates == select_pos:
                selected_unit = unit
                break

        if not selected_unit:
            return self, -1, self.done

        if selected_unit.movement_points <= 0:
            return self, -1, self.done

        # Fortify if selecting own tile
        if select_pos == order_pos:
            success = selected_unit.fortify()
            return self, (0 if success else -1), self.done

        # Check if order targets an enemy unit → attack
        enemy_unit = self._get_enemy_unit_at(order_pos)
        if enemy_unit is not None:
            reward = self._execute_attack(selected_unit, enemy_unit)
            self._check_game_end()
            return self, reward, self.done

        # Otherwise → movement
        moved, final_pos = selected_unit.move(order_pos, self)

        if not moved:
            return self, -1, self.done

        # Check if we captured a city
        tile = self.map.get_tile(final_pos)
        if tile and tile.city and tile.city.player != self.current_player:
            tile.city.set_owner(self.current_player)
            reward += 20

        self._check_game_end()
        return self, reward, self.done

    def _get_enemy_unit_at(self, coordinates):
        """Get an enemy unit at the given position, or None."""
        units = self.get_units_at(coordinates)
        for unit in units:
            if unit.player != self.current_player:
                return unit
        return None

    def _execute_attack(self, attacker, defender):
        """Execute combat between attacker and defender. Returns reward."""
        reward = 0

        # Check adjacency — melee units must be adjacent to attack
        adj_coords = self.map.get_adjacent_coords(attacker.coordinates)
        if defender.coordinates not in adj_coords:
            return -1  # Not adjacent, can't attack

        damage_dealt, damage_received, target_killed, attacker_killed = \
            attacker.attack(defender, self)

        # Reward for damage dealt
        reward += damage_dealt * 0.1

        if target_killed:
            reward += 10
            self.delete_unit(defender)
            # Melee: attacker moves into vacated tile
            if not attacker_killed:
                self.move_unit(attacker, defender.coordinates)
                attacker.movement_points = 0
                # Check city capture
                tile = self.map.get_tile(attacker.coordinates)
                if tile and tile.city and tile.city.player != self.current_player:
                    tile.city.set_owner(self.current_player)
                    reward += 20

        if attacker_killed:
            reward -= 10
            self.delete_unit(attacker)

        return reward

    def _check_game_end(self):
        """Check if the game should end (all units spent, player eliminated, turn limit)."""
        # Auto-advance if all units spent
        if self.current_player.units:
            all_units_moved = all(u.movement_points == 0 for u in self.current_player.units)
            if all_units_moved:
                self.current_player.end_turn()
                self.next_turn()
        else:
            # Player has no units left, end their turn
            self.current_player.end_turn()
            self.next_turn()

        alive_players = [p for p in self.players if not p.is_dead]
        if len(alive_players) <= 1:
            self.done = True

        if self.turn_counter > self.max_turns:
            self.done = True

    def next_turn(self):
        """Advance to the next player's turn."""
        self.current_player.end_turn()

        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self.current_player = self.players[self.current_player_index]

        if self.current_player_index == 0:
            self.turn_counter += 1

        self.current_player.start_turn()

        alive_players = [p for p in self.players if not p.is_dead]
        if len(alive_players) <= 1:
            self.done = True

        if self.turn_counter > self.max_turns:
            self.done = True

    # --- Tile query helpers ---

    def get_terrain_at(self, coordinates):
        tile = self.map.get_tile(coordinates)
        return tile.terrain_type if tile else None

    def has_feature(self, coordinates, feature_type):
        tile = self.map.get_tile(coordinates)
        return tile is not None and tile.has_feature(feature_type)

    def is_river_between(self, coords1, coords2):
        return self.map.has_river_between(coords1, coords2)

    def check_line_of_sight(self, from_coords, to_coords):
        return self.map.check_line_of_sight(from_coords, to_coords)

    def is_valid_position(self, coordinates):
        return self.map.get_tile(coordinates) is not None

    def is_occupied(self, coordinates):
        tile = self.map.get_tile(coordinates)
        return tile is not None and len(tile.units) > 0

    def get_units_at(self, coordinates):
        tile = self.map.get_tile(coordinates)
        return tile.units if tile else []

    # --- Unit management ---

    def add_unit_to_tile(self, unit, coordinates):
        tile = self.map.get_tile(coordinates)
        if tile:
            tile.add_unit(unit)
            unit.coordinates = coordinates

    def remove_unit_from_tile(self, unit, coordinates):
        tile = self.map.get_tile(coordinates)
        if tile:
            tile.remove_unit(unit)

    def move_unit(self, unit, new_coordinates):
        self.remove_unit_from_tile(unit, unit.coordinates)
        self.add_unit_to_tile(unit, new_coordinates)

    def delete_unit(self, unit):
        """Delete a unit from the game entirely."""
        self.remove_unit_from_tile(unit, unit.coordinates)
        unit.player.remove_unit(unit)

    # --- City management ---

    def can_found_city_at(self, coordinates):
        tile = self.map.get_tile(coordinates)
        if not tile or tile.terrain_type in ["Mountain", "Ocean"] or tile.city:
            return False

        # Minimum distance from other cities
        for player in self.players:
            for city in player.cities:
                distance = self.map.distance_function(coordinates, city.coordinates)
                if distance < 3:
                    return False
        return True

    def found_city(self, player, coordinates, name="New City"):
        """Found a new city at the specified coordinates."""
        if not self.can_found_city_at(coordinates):
            return None

        city = City(player, coordinates, name)
        tile = self.map.get_tile(coordinates)
        tile.set_city(city)
        player.cities.append(city)
        return city

    def add_city(self, city):
        """Add a city to the map (used by SettlerUnit.found_city)."""
        tile = self.map.get_tile(city.coordinates)
        if tile:
            tile.set_city(city)

    # --- Improvements ---

    def can_build_improvement_at(self, coordinates, improvement_type):
        tile = self.map.get_tile(coordinates)
        if not tile or tile.city or improvement_type in tile.improvements:
            return False

        terrain_improvements = {
            "Farm": ["Plains", "Grassland", "Desert", "Floodplains"],
            "Mine": ["Hills", "Desert", "Tundra", "Snow"],
            "Plantation": ["Plains", "Grassland", "Desert"],
            "Camp": ["Plains", "Grassland", "Tundra", "Desert"],
            "Pasture": ["Plains", "Grassland", "Desert", "Tundra"],
            "Quarry": ["Plains", "Desert", "Grassland", "Tundra"],
            "Fishing Boats": ["Coast", "Lake"],
            "Oil Well": ["Desert", "Tundra", "Snow", "Coast", "Ocean"],
        }
        valid_terrains = terrain_improvements.get(improvement_type, [])
        return tile.terrain_type in valid_terrains

    def build_improvement(self, coordinates, improvement_type):
        """Build an improvement on the specified tile."""
        if not self.can_build_improvement_at(coordinates, improvement_type):
            return False
        tile = self.map.get_tile(coordinates)
        tile.add_improvement(improvement_type)
        return True

    # --- Pathfinding wrappers ---

    def path_finder(self, start, destination):
        return self.map.path_finder(start, destination)

    def distance_function(self, p1, p2):
        return self.map.distance_function(p1, p2)

    # --- Debug ---

    def debug_units_locations(self):
        """Print the locations of all units for debugging."""
        print("\nDEBUG: Unit Locations")
        for player_idx, player in enumerate(self.players):
            print(f"Player {player_idx + 1} ({player.name}) units:")
            for unit_idx, unit in enumerate(player.units):
                print(
                    f"  Unit {unit_idx}: {unit.unit_type} at {unit.coordinates} "
                    f"with {unit.movement_points} MP"
                )
                tile_units = self.get_units_at(unit.coordinates)
                if unit not in tile_units:
                    print(f"    WARNING: Unit not found at its tile!")
                if len(tile_units) > 1:
                    print(f"    WARNING: {len(tile_units)} units stacked at {unit.coordinates}")
