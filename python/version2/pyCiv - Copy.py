"""
simple version of civ in python
the map is always cylindrical in this mode
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
        self.movement_points = self.default_movement_points(unit_type)
        self.max_movement_points = self.movement_points
        self.attack_power = 50
        self.promotion = 0
        self.xp = 0
        self.verbose = True
        self.level = 1
        self.defence_bonus = 0
        
    def __str__(self):
        return f"Type: {self.unit_type}, Health: {self.health}, Team: {self.player.name}, Location: {self.location}"
    
    def attack(self, target: 'Unit'):
        kill = False
        if self.xp > 100:
            self.attack_power += 3
            self.xp = 0
            self.level +=1
            print(f"{self.player.name} {self.unit_type} is now level {self.level}")
        target.take_damage(self.attack_power)
        self.xp += 10
        if target.dead == True:
            self.location = target.location # does not take into account for ranged attacks.
            self.xp += 20
            kill = True
        self.movement_points = 0
        self.take_damage(target.attack_power//2)
        if self.verbose:
            print(f"{self.player.name} {self.unit_type} attacks {target.player.name} {target.unit_type} for {self.attack_power} damage.")
        return kill


    def take_damage(self, damage): # WE USE THIS
        self.health -= damage
        if self.verbose:
            print(f"{self.unit_type} took {damage} damage. Health now {self.health}")
        if self.health <= 0:
            self.dead = True
            self.player.remove_unit(self)
            if self.verbose:
                print(f"{self.player.name} {self.unit_type} died.")
            # self.location = np.array([-1,-1]) # graveyard. # Flyttas till egen funtion!

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

#     def fortify(self):

#         if self.defence_bonus <= 3:
#             self.defence_bonus += 3

#         self.defence_bonus += 3
#         self.defence_bonus = min(self.defence_bonus, 6)
# >>>>>>> 06cb28a975e57a05145499c0f16921296617339b
#         self.movement_points = 0
    
    def end_of_turn_action(self):
        if self.movement_points == self.max_movement_points:
            # calculate healing amout
            self.heal(10)
            self.fortify()
        else: 
            self.defence_bonus = 0 # change to the tile defence in question
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
        self.units = [] 
        self.player_index = player_index
        self.units = []
        self.cities = []
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.faith = 0
        self.income = 0
        self.starting_location = (0,0)
        self.player_is_dead = False
        self.units_with_no_movement = []
        
        
    def add_unit(self, location, map_size, unit_type='Warrior'):
        self.units.append(Unit(self, location, unit_type))
    
    def add_city(self, location):
        city_name = self.name + ' City'
        self.cities.append(City(self, location, city_name))
    
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
    def check_if_player_is_dead(self):
        if len(self.cities) == 0:
            print(f"{self.name} is dead.")
            self.player_is_dead = True
        
    def get_unmoved_positions(self):
        untouched_locations = []
        for unit in self.units:
            if unit.movement_points > 0:
                untouched_locations.append(unit.location)
        return untouched_locations
                    


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
        
        self.kill_reward = 10
        self.damage_reward = 3
        self.city_capture_reward = 60
        self.win_reward = 1000
        self.reward = {"Capture Enemy City": 1000}
        


    def check_if_done(self):
        # updates the list of players to contain only players with cities left.
        self.players = [player for player in self.players if len(player.cities) > 0]
        if len(self.players) == 1:
            self.done = True

                
    
    def add_player(self, name):
        self.players.append(Player(name, len(self.players)))

    def reset(self, number_of_players):
        self.done = False
        # Clear existing players and add new ones
        self.map = Map(self.n, self.m)
        self.map.generate_map()
        self.players.clear()
        self.turn_counter = 1
        self.number_of_players = number_of_players
        for i in range(number_of_players):
            self.add_player(f"Player {i+1}")
        
        self.state = torch.zeros(self.d,self.n,self.m)
        
        # calculate starting locations
        if number_of_players == 2:
            self.players[0].starting_location = np.array([random.randint(1,self.n-1), random.randint(1, self.m//2-1)])
            self.players[1].starting_location = np.array([random.randint(1,self.n-1), random.randint(self.m//2, self.m-1)])
        else:
            for player in self.players:
                player.starting_location =(random.randint(0,self.n),random.randint(0,self.m)) #needs work, might create players on top of each other!!!!
                # make this like 2playter version but partition the map in equal parts.
            
                
        for player in self.players:
            offset1 = np.array([1, 1])
            offset2 = np.array([0, 1])
            map_size = np.array([self.n,self.m])
            player.add_unit(player.starting_location% map_size, map_size)
            player.add_unit((player.starting_location + offset1)% map_size, map_size)
            player.add_unit((player.starting_location + offset2)% map_size, map_size)
            player.add_city(player.starting_location)
            
        self.current_player = self.players[0] # Player 1 starts the game
        self.update_state_tensor()
        return self.state
    
    def delete_unit(self, unit):
        # Remove from the tile
        tile = self.map.tiles[unit.coordinates]
        if unit in tile.units:
            tile.units.remove(unit)
        
        # Remove from the player
        player = unit.player
        if unit in player.units:
            player.units.remove(unit)
    
        # Additional cleanup (if necessary)
        del unit  # Optional, not strictly necessary in Python due to garbage collection
    
    


    def execute(self, unit, order):
        reward = 0
        
            
        if unit.unit_type == 'Warrior':
            if order == unit.coordinates:
                unit.fortify()
                unit.movement_points = 0
                
            else:
               path = self.pathfinder(unit.coordinates, order) 
               while unit.movement_points > 0: 
                   next_tile_coord = path.pop(0)
                   
                   if len(self.map.tiles[next_tile_coord].units)==0:
                       # Tile free, let's move there
                       self.map.tiles[unit.coordinates].units.remove(unit)
                       unit.coordinates = next_tile_coord
                       self.map.tiles[unit.coorinates].units.append(unit)
                       unit.movement_points -= self.map.tiles[next_tile_coord].movement_cost
                   else:
                       # Tile occupied by a unit, check if friendly or hostile:
                       if unit.player == self.map.tiles[next_tile_coord].units[0].player:
                           #Friendly Unit Detected - Setting movement points to zero - Not an ideal solution but will work for now.
                           self.movement_points = 0
                       else:
                           #Enemy unit detected, attack!
                           enemy_unit = self.map.tiles[next_tile_coord].units[0]
                           # Attack Logic
                           enemy_unit_defence_modifier = 1 - (self.map.tiles[enemy_unit.coordinates].defence_bonus + enemy_unit.defence_bonus)/10
                           enemy_unit.take_damage(unit.attack_power * unit.health / unit.max_health * enemy_unit_defence_modifier) 
                           unit.take_damage(enemy_unit.attack_power * enemy_unit.health / enemy_unit.max_health)
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
                               self.map.tiles[unit.coordinates].units.remove(unit)
                               unit.coordinates = next_tile_coord
                               self.map.tiles[unit.coorinates].units.append(unit)
                               unit.movement_points = 0
                               
                               
                           elif unit.health <= 0 and enemy_unit.health > 0:
                              #ONLY DEFENDER SURVIVED
                              enemy_unit.xp += self.kill_XP
                              self.delete_unit(unit)
                              return reward
               
               #Check if we captured a new city
               if self.map.tiles[unit.coordinates].city:
                   if self.map.tiles[unit.coordinates].city.player != unit.player:
                      self.map.tiles[unit.coordinates].city.set_owner(unit.player)
                      reward += self.city_capture_reward
                       
                   
               
               return reward               
                                       
                               
                                
                                      
                                   
                                   
                              
                                   
                                      
                            
                            
    
                                 
                       
                       # if next tile friendly unit: Pass - (Set movement points to zero)
                       # if next tile enemy unit: Attack
                       # if next tile empty: Move
                       # check if we captured a city     
                       
                       
    def pathfinder(self, p1, p2):
        """ At the moment very simple version"""
        dx, dy = p2[0]-p1[0], p2[1] - p1[1]
        orders = []
        # while abs(dx) + abs(dy) > 0:
        while abs(p2-p1) > 0:
            while dx > 0 and dy > 0:
                # orders.append('SE')
                p1 += np.array([1,1])
                orders.append(p1)
                dx -= 1
                dy -= 1
            while dx < 0 and dy < 0:
                # orders.append('NW')
                p1 -= np.array([1,1])
                orders.append(p1)
                dx += 1
                dy += 1
            while dx > 0 and dy == 0:
                # orders.append('E')
                p1[0] += 1
                orders.append(p1)
                dx -= 1
            while dx < 0 and dy==0:
                # orders.append('W')
                p1[0] -= 1
                orders.append(p1)
                dx += 1
            while dy > 0:
                # orders.append('SW')
                p1[1] += 1
                orders.append(p1)
                dy -= 1
            while dy < 0:
                # orders.append('NE')
                p1[1] -= 1
                orders.append(p1)
                dy += 1
        return orders      
    # def get_next_tile(self, p1, p2):
    #     #unit wants to move from position p1 to p2, this function returns the next tile in the path.
    #     dx, dy = p2[0]-p1[0], p2[1]-p1[1]
    #     if np.linalg.norm(p2-p1) == 1:
    #         return p2
    #     # while abs(dx) + abs(dy) > 0:
    #     if np.linalg.norm(p2-p1) > 0:
    #         if dx > 0 and dy > 0:
    #             # orders.append('SE')
    #             p1 += np.array([1,1])
                
    #             dx -= 1
    #             dy -= 1
    #         if dx < 0 and dy < 0:
    #             # orders.append('NW')
    #             p1 -= np.array([1,1])
                
    #             dx += 1
    #             dy += 1
    #         if dx > 0 and dy == 0:
    #             # orders.append('E')
    #             p1[0] += 1
                
    #             dx -= 1
    #         if dx < 0 and dy==0:
    #             # orders.append('W')
    #             p1[0] -= 1
               
    #             dx += 1
    #         if dy > 0:
    #             # orders.append('SW')
    #             p1[1] += 1
               
    #             dy -= 1
    #         if dy < 0:
    #             # orders.append('NE')
    #             p1[1] -= 1
                
    #             dy += 1
    #     return p1                

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
        if self.current_player.check_if_player_is_dead():
            next_player = self.get_next_player(self.current_player)
            self.players.remove(self.current_player)
            self.number_of_players -= 1
            self.current_player = next_player
            # remove current player and get the next player and update number of players (or remove this attribute), 
            print('one player is dead')
            print('Check if game is over!')
            self.check_if_done()
        reward = 0
        select = action[0]  # FIX SELECT AND ORDER TO BE i, j indexes - 8/8 -24 erik
        order = action[1]
        # CHECK IF END TURN <- Could be moved into execute order as well
        if (action[0] == [self.n,0]).all():
            # print(f"{self.current_player.name} End Turn")
            self.current_player.end_turn()
            self.current_player = self.get_next_player(self.current_player)
            if self.current_player == self.players[0]: #We've cycld through all players, time to increase turn counter
                self.turn_counter += 1
                #OPTIONAL PRINT STATEMENT
                if self.turn_counter % 10 == 0:
                    print(f"Turn {self.turn_counter}")
        
        """SELECT UNIT FROM MAP """
        if len(self.map.tiles[select].units) == 1: # Check that we've selected a unit- we should have! Maybe assert? Maybe remove this all together?
            reward += self.execute(self.map.tiles[select].units[0], order)
            
            """ #this function should contain pathfinding, what to do if the tile is empty, 
                has enemy or has friendly unit as well as capturing city (and anything else)"""
        else:
            print('Selected empty tile :(')
        # Calculate new state
        self.update_state_tensor()
        self.check_if_done()
        return self.state, reward, self.done

    def update_state_tensor(self):
        # Assuming self.n, self.m, and self.d are already defined
        self.state = torch.zeros(self.d, self.n, self.m)
        
        # Assuming self.current_player and self.players are defined
        # Update for current player's units
        player = self.current_player
        layer_index = 0  # Assuming the current player's units are friendly and go in the 0th layer of d
        for city in player.cities: 
            i, j = city.location
            self.state[0 ,i, j] = 100
        for unit in player.units:
            i, j = unit.location  # Assuming unit.location is a tuple or list with 2 elements
            self.state[1,i, j] = unit.health  # Update health for friendly unit at (i, j)
            self.state[2,i, j] = unit.movement_points  # Update move_points for friendly unit at (i, j)
            
        layer_index = 3
        # Update for other players' units
        """
            Borde kunna updatera detta för att enbart cycla genom players, skippa current player.
        """
        for player_index, player in enumerate(self.players):
            if player == self.current_player:
                continue  # Skip the current player
              # Different layer for each player
            for city in player.cities:
                i, j = city.location
                self.state[layer_index, i, j] = -city.worth
            for unit in player.units:
                i, j = unit.location
                self.state[layer_index+1, i, j] = -unit.health  # Negative health for enemy units
            layer_index += 2
    

        



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