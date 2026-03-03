"""
simple version of civ in python
Version 2 of pyCiv implements classes for map tiles:
    units and cities are referenced in the tiles (in addition to being referenced in the player class)
    This means you can pick a tile and see if there is a unit standing on it, as well as pick a player and see where all their units are
    Allows for different terrain types with different yields and defencive bonuses, hopefully also rivers can be implemented.
    EXAMPLE tile.rivers = [river1, river2], where river1 = ['NE', 'S'] could mean we have 2 rivers flowing on the tile, river1 exits the tile to the north east and the south.
"""
import random
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt

class Map:
    def __init__(self, nbr_rows, nbr_columns):
        self.n = nbr_rows
        self.m = nbr_columns
        self.tiles = np.empty((self.n, self.m), dtype=object)
    
    def generate_map(self):
        for i in range(self.n):
            for j in range(self.m):
                self.tiles[i,j] = Tile(i,j)


class Tile:
    def __init__(self, row, column):
        self.row = row
        self.column = column
        self.defence_bonus = 0
        self.movement_cost = 1
        self.production_value = np.array([2,1]) # food, production
        self.resourse_luxiry_or_strategic = None
        self.units = []
        self.general = []
        self.siege_units = []
        self.settlers = []
        self.city = None

class Unit:
    def __init__(self, player, coordinates ,unit_type='Warrior', health=100):
        self.unit_type = unit_type
        self.health = health
        self.max_health = health
        self.player = player
        self.coordinates = coordinates
        self.order = None
        self.movement_points = self.default_movement_points()
        self.max_movement_points = self.movement_points
        self.attack_power = self.default_attack_power()
        self.ranged_attack_power = self.default_ranged_power()
        self.range = self.default_range()
        self.promotion = 0
        self.xp = 0
        self.verbose = False
        self.level = 1
        self.defence_bonus = 0
        
        
    def __str__(self):
        return f"Type: {self.unit_type}, Health: {self.health}, Team: {self.player.name}, Location: {self.location}"
    
    def default_attack_power(self):
        ap = {'Warrior' : 50,
              'Archer' : 15,
              'Horseman' : 75,
              'Spearman': 50, 
              'Settler' : 0}
        return ap[self.unit_type]
    def default_ranged_power(self):
        ranged_ap = {'Warrior' : 0,
              'Archer' : 50,
              'Horseman' : 0,
              'Spearman': 0,
              'Settler' : 0}
        return ranged_ap
        
    def default_range(self):
        attack_range = {'Warrior' : 1,
              'Archer' : 2,
              'Horseman' : 1,
              'Spearman': 1,
              'Settler' : 0}
        return attack_range[self.unit_type]
    # def attack(self, target: 'Unit'):
    #     kill = False
    #     if self.xp > 100:
    #         self.attack_power += 3
    #         self.xp = 0
    #         self.level +=1
    #         print(f"{self.player.name} {self.unit_type} is now level {self.level}")
    #     target.take_damage(self.attack_power)
    #     self.xp += 10
    #     if target.dead == True:
    #         self.location = target.location # does not take into account for ranged attacks.
    #         self.xp += 20
    #         kill = True
    #     self.movement_points = 0
    #     self.take_damage(target.attack_power//2)
    #     if self.verbose:
    #         print(f"{self.player.name} {self.unit_type} attacks {target.player.name} {target.unit_type} for {self.attack_power} damage.")
    #     return kill


    def take_damage(self, damage): # WE USE THIS
        self.health -= damage


    def heal(self, amount):
        self.movement_points = 0
        if self.health == self.max_health:
            return
        self.health += amount
        self.health = min(self.health, self.max_health)
        if self.verbose:
            print(f"{self.player.name} {self.unit_type} healed by {amount}. Health now {self.health}")
            
        
        
    def default_movement_points(self):
        if self.unit_type == 'Warrior':
            return 1
        else:
            return 1

    def fortify(self):
        if self.defence_bonus <= 3:
            self.defence_bonus += 3
    
    def end_of_turn_action(self):
        if self.movement_points == self.max_movement_points:
            # calculate healing amout
            self.heal(10)
        else: 
            self.defence_bonus = 0
        self.movement_points = self.max_movement_points

class City:
    def __init__(self, player, coordinates, name, health=1):
        self.player = player
        self.coordinates = coordinates
        self.name = name
        
        self.max_health = health
        self.health = health
        self.population = 1
        
        self.production = 0
        self.food = 0
        self.science = 0
        self.culture = 0
        self.faith = 0
        self.worth = 100 # This could be used sometime maybe.
        
        
    def set_owner(self, new_player):
        # Check if the city is owned by a player
        if self.player:
            self.player.cities.remove(self)       
        
        new_player.cities.append(self)
        self.player = new_player

class Player:
    def __init__(self, name, player_index):
        self.name = name
        self.player_index = player_index
        self.units = []
        self.cities = []
        self.settlers = []
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.faith = 0
        self.income = 0
        self.starting_location = (0,0)
        self.is_dead = False
        self.units_with_no_movement = []
        
            
    def add_unit(self, unit):
        self.units.append(unit)
    
    def add_city(self, city):
        self.cities.append(city)
    
    def remove_unit(self, unit):
        if unit in self.units:
            self.units.remove(unit)
        
    def get_unit_at_pos(self, position):
        for unit in self.units:
            if unit.position == position:
                return unit
        return
    
    def end_turn(self):
        for unit in self.units:
            unit.end_of_turn_action()
    def check_if_dead(self):
        if len(self.cities) == 0:
            
            self.is_dead = True
        
    # def get_unmoved_positions(self):
    #     untouched_locations = []
    #     for unit in self.units:
    #         if unit.movement_points > 0:
    #             untouched_locations.append(unit.location)
    #     return untouched_locations
                    


class GameEnvironment:
    def __init__(self, n, m, number_of_players):
        self.n = n #rows of map
        self.m = m #cols of map
        self.d = 2 * number_of_players + 1 # own cities, own units, movement points,  enemy cities, enemy units = Nplayers*2 +1 
        self.turn_counter = 0
        self.current_player = None
        self.players = [] # the dictionary should be ordered. (comment for later cython implementation)
        self.done = False
        self.state = torch.zeros(self.d,self.n,self.m)
        self.number_of_players = number_of_players # needs to be UPDATED WHEN SOMEONE DIES!!!!
        self.map = None
        
        self.attack_XP = 6
        self.defend_XP = 3
        self.kill_XP = 4
        
        self.kill_reward = 50
        self.damage_reward = 10
        self.city_capture_reward = 60
        self.win_reward = 100
        self.reward = {"Capture Enemy City": 100}
        self.max_turns = 250
        

    def get_raw_state(self):
        """
        Returns the raw game state without converting to a tensor.
        This will be used by agents to build their own state representations.
        
        Returns:
            self: The current game environment (agents can extract what they need)
        """
        # For now, we simply return the game environment instance itself
        # Agents can extract the data they need from it
        return self
    
    def distance_function(self, p1, p2):
        dx = p2[1] - p1[1]
        dy  =p2[0] - p1[0]
        if dx*dy > 0:
            d = max(abs(dx), abs(dy))
        else:
            d = abs(dx) + abs(dy)
        return d
    
    def path_finder(self, p1, p2):
        orders = []
        current_position = p1.copy()  # Create a copy of p1 to work with
        destination = p2.copy()
        
        
        if self.distance_function(current_position, destination) > self.distance_function(p1, (destination + np.array([0,self.m]))):
            destination = destination + np.array([0, self.m])
        
        
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
    
    def check_if_done(self):
        if self.max_turns:
            if self.turn_counter > self.max_turns:
                self.done = True
        
        #Check if alive twice : We want to print player is dead only the same turn the player died.
        number_of_players_alive = 0
        for player in self.players:            
            if not player.is_dead:
                player.check_if_dead()
                if player.is_dead:
                    print(f"{player.name} is dead.")
            if not player.is_dead:
                number_of_players_alive += 1
                
        
        if number_of_players_alive <= 1:
            self.done = True
                       
    def add_player(self, name):
        self.players.append(Player(name, len(self.players)))
        
    def add_unit(self, player, coordinates, unit_type):
        unit = Unit(player, coordinates, unit_type)
        player.add_unit(unit)
        self.map.tiles[tuple(coordinates)].units.append(unit)
        
    def add_city(self, player, coordinates):
        city_name = player.name + ' City'
        city = City(player, coordinates, city_name)
        player.add_city(city)
        self.map.tiles[tuple(coordinates)].city = city        
    
    def reset(self):
        self.done = False
        # Clear existing players and add new ones
        self.map = Map(self.n, self.m)
        self.map.generate_map()
        self.players.clear()
        self.turn_counter = 1
        for i in range(self.number_of_players):
            self.add_player(f"Player {i+1}")
        
        self.state = torch.zeros(self.d,self.n,self.m)
        
        # calculate starting locations
        if self.number_of_players == 2:
            self.players[0].starting_location = np.array([random.randint(0,self.n-1), random.randint(0, self.m//2-1)])
            self.players[1].starting_location = np.array([random.randint(0,self.n-1), random.randint(self.m//2, self.m-1)])
        else:
            for player in self.players:
                partition = self.m // self.number_of_players
                player.starting_location = np.array([random.randint(0,self.n-1), random.randint(player.player_index * partition , (player.player_index + 1) * partition - 1)]) #needs work, might create players on top of each other!!!!
                # make this like 2playter version but partition the map in equal parts.
            
                
        for player in self.players:
            map_size = np.array([self.n,self.m])
            coord0 = player.starting_location % map_size
            coord1 = (coord0 + np.array([1, 1])) % map_size
            coord2 = (coord0 + np.array([0, 1])) % map_size
            self.add_unit(player, coord0, 'Warrior')
            self.add_unit(player, coord1, 'Warrior')
            self.add_unit(player, coord2, 'Warrior')
            self.add_city(player, player.starting_location)
            
        self.current_player = self.players[0] # Player 1 starts the game
        return self.get_raw_state()
    
    def delete_unit(self, unit):
        # Remove from the tile
        tile = self.map.tiles[tuple(unit.coordinates)]
        if unit in tile.units:
            tile.units.remove(unit)
        
        # Remove from the player
        player = unit.player
        if unit in player.units:
            player.units.remove(unit)
            
        # Print:
        print(f'{unit.player.name} {unit.unit_type} deleted')
    
        # Additional cleanup (if necessary)
        del unit  # Optional, not strictly necessary in Python due to garbage collection
    
    


    def execute(self, unit, order):
        reward = 0
        
            
        if unit.unit_type == 'Warrior':
            if (order == unit.coordinates).all():
                unit.fortify()
                unit.movement_points = 0
                
            else:
               path = self.path_finder(unit.coordinates.copy(), order) 
               while unit.movement_points > 0 and len(path) > 0: 
                   next_tile_coord = path.pop(0)
                   
                   #CHECK IF TILE IS FREE
                   if len(self.map.tiles[tuple(next_tile_coord)].units)==0:
                       # Tile free, let's move there
                       if unit in self.map.tiles[tuple(unit.coordinates)].units:
                           self.map.tiles[tuple(unit.coordinates)].units.remove(unit)
    
                           # Update the unit's coordinates and move it to the new tile
                           unit.coordinates = next_tile_coord
                           self.map.tiles[tuple(next_tile_coord)].units.append(unit)
                           # Reduce movement points based on the movement cost of the new tile
                           unit.movement_points -= self.map.tiles[tuple(next_tile_coord)].movement_cost
                   else:
                       # Tile occupied by a unit, check if friendly or hostile:
                       if unit.player == self.map.tiles[tuple(next_tile_coord)].units[0].player:
                           #Friendly Unit Detected - Setting movement points to zero - Not an ideal solution but will work for now.
                           unit.movement_points = 0
                           reward -= 1
                       else:
                           #Enemy unit detected, attack!
                           enemy_unit = self.map.tiles[tuple(next_tile_coord)].units[0]
                           
                           # ATTACK LOGIC
                           # ------------
                           
                           print(f'{unit.player.name} {unit.unit_type} attacks {enemy_unit.player.name} {enemy_unit.unit_type}')
                           
                           defence_modifier = 1 - (self.map.tiles[tuple(enemy_unit.coordinates)].defence_bonus + enemy_unit.defence_bonus)/10
                           unit_attack_modifier = max(.6,(unit.health / unit.max_health))
                           
                           enemy_unit.take_damage(unit.attack_power * unit_attack_modifier * defence_modifier)
                           enemy_unit_attack_modifier = max(.6, enemy_unit.health / enemy_unit.max_health)
                           
                           unit.take_damage(enemy_unit.attack_power * enemy_unit_attack_modifier)
                           unit.xp += self.attack_XP
                           enemy_unit.xp += self.defend_XP
                           
                           if unit.health <= 0 and enemy_unit.health <= 0:
                               # Special Case: Both died - Let the unit with the least negative health win, defender wins on tie
                               if enemy_unit.health >= unit.health:
                                   enemy_unit.health = 1
                               else:
                                   unit.health = 1
                                   
                           if unit.health > 0 and enemy_unit.health > 0:
                               #BOTH SURVIVED
                               unit.move_points = 0
                               reward += self.damage_reward
                               
                               
                           elif unit.health > 0 and enemy_unit.health <= 0:
                               #ONLY ATTACKER SURVIED!
                               reward += self.kill_reward
                               unit.xp += self.kill_XP
                               self.delete_unit(enemy_unit)
                               # Move the unit on the map
                               self.map.tiles[tuple(unit.coordinates)].units.remove(unit)
                               unit.coordinates = next_tile_coord
                               self.map.tiles[tuple(unit.coordinates)].units.append(unit)
                               unit.movement_points = 0
                               
                               
                           elif unit.health <= 0 and enemy_unit.health > 0:
                              #ONLY DEFENDER SURVIVED
                              enemy_unit.xp += self.kill_XP
                              self.delete_unit(unit)
                              return reward
               
                   #Check if we captured a new city
                   if self.map.tiles[tuple(unit.coordinates)].city:
                       if self.map.tiles[tuple(unit.coordinates)].city.player != unit.player:
                           self.map.tiles[tuple(unit.coordinates)].city.set_owner(unit.player)
                           reward += self.city_capture_reward
                       
                   
               
        return reward               

    def get_next_player(self, player): 
        # Find the next player in the list
        "needs work"
        if player in self.players:
            current_index = self.players.index(player)
            next_index = (current_index + 1) % len(self.players)  # Use modulo for cycling
            return self.players[next_index]
        else:
            print('the player was not in the list')
            return self.players[0]  # Default to first player if not set
        return self.players[(player.player_index+1) % len(self.players)]
    
    # def get_enemy_units(self, player = None):
    #     if player is None:
    #         player = self.current_player
    #     enemy_units = []
    #     for i in range(self.number_of_players - 1):
    #         player = self.get_next_player(player)
    #         for unit in player.units: 
    #             enemy_units.append(unit)
    #     return enemy_units
    
    def check_if_adjacent(p1,p2):
        dp = p2-p1
        if np.sign(dp[0]) == np.sign(dp[1]) and max(abs(dp[0]), abs(dp[1])) == 1 or dp[0]*dp[1] == 0 and max(abs(dp[0]), abs(dp[1])):
            return True
        else:
            return False
            
        # if dp == np.array([-1,0]) or dp == np.array([-1,-1]) or dp == np.array([0,-1]) or :
        #     dp == np.array([0,1]) or dp == np.array([1,1]) or dp == np.array([1,0]):
        #         return True
        
       
    def step(self, action):
        if self.current_player.is_dead:
            reward = 0
            self.current_player.end_turn()
            next_player = self.get_next_player(self.current_player)
            self.current_player = next_player
            self.update_state_tensor()
            return self.get_raw_state(), reward, self.done
        reward = 0
        select = action[0]  # FIX SELECT AND ORDER TO BE i, j indexes - 8/8 -24 erik
        order = action[1]
        # CHECK IF END TURN <- Could be moved into execute order as well
        if (select.tolist() == [self.n,0]):
            # print(f"{self.current_player.name} End Turn")
            self.current_player.end_turn()
            self.current_player = self.get_next_player(self.current_player)            
            first_alive_player = next(player for player in self.players if not player.is_dead)
            # Check if the current player is this first alive player
            if self.current_player == first_alive_player:
                self.turn_counter += 1

                #OPTIONAL PRINT STATEMENT
                if self.turn_counter % 10 == 0:
                    print(f"Turn {self.turn_counter}")
            self.check_if_done()  # This was in update_state_tensor()
            return self.get_raw_state(), reward, self.done
        
        """SELECT UNIT FROM MAP """
        if len(self.map.tiles[tuple(select)].units) == 1: # Check that we've selected a unit- we should have! Maybe assert? Maybe remove this all together?
            reward += self.execute(self.map.tiles[tuple(select)].units[0], order)
            
        else:
            print('Selected empty tile :(')
            print(f'state = {self.state} \nselect = {select}\norder = {order}')
        # Calculate new state
        # self.update_state_tensor(self)
        return self.get_raw_state(), reward, self.done

    def update_state_tensor(self):
        """
        DEPRECATED: This method is kept for backward compatibility.
        State tensor building should now be handled by the agent.
        """
        # Original update_state_tensor code...
        self.state = torch.zeros(self.d, self.n, self.m)
        # Update for current player's units
        player = self.current_player
        layer_index = 0
        for city in player.cities: 
            i, j = city.coordinates
            self.state[0, i, j] = 100
        for unit in player.units:
            i, j = unit.coordinates
            self.state[1, i, j] = unit.health
            self.state[2, i, j] = unit.movement_points
            
        layer_index = 3
        # Update for other players' units
        for player_index, player in enumerate(self.players):
            if player == self.current_player:
                continue
            for city in player.cities:
                i, j = city.coordinates
                self.state[layer_index, i, j] = -city.worth
            for unit in player.units:
                i, j = unit.coordinates
                self.state[layer_index+1, i, j] = -unit.health
            layer_index += 2
        
        self.check_if_done()
    

        



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