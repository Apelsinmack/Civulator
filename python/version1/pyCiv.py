"""
simple version of civ in python
the map is always cylindrical in this mode
"""
import random
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

class Tile:
    def __init__(self, row, column):
        self.row = row
        self.column = column
        self.defence.bonus = 0
        self.movement_cost = 1
        self.production_value = np.array([2,1]) # food, production
        self.resourse_luxiry_or_strategic = None
        #something to implement in the future - should be able to help offload some stuff.

class Unit:
    def __init__(self, player, location ,unit_type='Warrior', health=100):
        self.unit_type = unit_type
        self.health = health
        self.max_health = health
        self.player = player
        self.location = location
        self.order = None
        self.movement_points = self.default_movement_points(unit_type)
        self.max_movement_points = self.movement_points
        self.attack_power = 25
        self.promotion = 0
        self.xp = 0
        self.defence_bonus = 0
        self.verbose = True
        self.dead = False
        self.map_size = None # dont think this is the place for this. Unused atm.
        self.level = 1
        


    def __str__(self):
        return f"Type: {self.unit_type}, Health: {self.health}, Team: {self.player.name}, Location: {self.location}"

    # Example methods you might want to add
    def teleport(self, new_location):
        self.location = new_location % self.map_size
        # retrieve defence value
        if self.verbose:
            print(f"Teleporting to {self.location}")
    
    def move(self, new_location): # No pathfinding.
        if (new_location == self.location).all():
            self.movement_points = 0
            
            return
        self.location = new_location
        self.movement_points -= 1
    
    
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




    def take_damage(self, damage):
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
        if self.health == self.max_health:
            return
        self.health += amount
        self.health = min(self.health, self.max_health)
        if self.verbose:
            print(f"{self.player.name} {self.unit_type} healed by {amount}. Health now {self.health}")
        
        
    def default_movement_points(self, unit_type):
        #
        if unit_type == 'Warrior':
            return 1.

    def fortify(self):
        self.defence_bonus += 3
        self.defence_bonus = min(self.defence_bonus, 6)
    
    def end_of_turn_action(self):
        if self.movement_points == self.max_movement_points:
            # calculate healing amout
            self.heal(10)
            self.fortify()
        else: 
            self.defence_bonus = 0 # change to the tile defence in question
        self.movement_points = self.max_movement_points

class Player:
    def __init__(self, name):
        self.name = name
        self.units = []
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.faith = 0
        self.income = 0
        self.starting_location = (0,0)
        self.player_is_dead = False
        self.units_with_no_movement = []
        # kanske ändra till en dict som heter typ resources som innehåller guld, science etc samt en dict som heter incomes som innehåller samma sak.
        
        # We will need a dict or list of locations of interest, this should contain all units and cities.
        
    def add_unit(self, location, map_size, unit_type='Warrior'):
        self.units.append(Unit(self, location, unit_type))
    
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
        if len(self.units) == 0:
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
        self.n = n
        self.m = m
        self.d = number_of_players + 1 # friendly units, movement points, enemy units. 
        self.turn_counter = 0
        self.current_player = None
        self.players = [] # the dictionary should be ordered. (comment for later cython implementation)
        self.done = False
        self.state = torch.zeros(self.d,self.n,self.m)
        self.number_of_players = number_of_players # needs to be fixed!

    def check_if_done(self):
        self.players = [player for player in self.players if len(player.units) > 0]
        if len(self.players) == 1:
            self.done = True

                
    
    def add_player(self, name):
        self.players.append(Player(name))

    def reset(self, number_of_players):   
        # Clear existing players and add new ones
        self.players.clear()
        self.turn_counter = 1
        self.number_of_players = number_of_players
        for i in range(number_of_players):
            self.add_player(f"Player {i+1}")
        
        self.state = torch.zeros(self.d,self.n,self.m)
        
        # calculate starting locations
        if number_of_players == 2:
            starting_locations = []
            
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
            
        self.current_player = self.players[0]
        return self.state
    
    
    def get_next_tile(self, p1, p2):
        #unit wants to move from position p1 to p2, this function returns the next tile in the path.
        dx, dy = p2[0]-p1[0], p2[1]-p1[1]
        if np.linalg.norm(p2-p1) == 1:
            return p2
        # while abs(dx) + abs(dy) > 0:
        if np.linalg.norm(p2-p1) > 0:
            if dx > 0 and dy > 0:
                # orders.append('SE')
                p1 += np.array([1,1])
                
                dx -= 1
                dy -= 1
            if dx < 0 and dy < 0:
                # orders.append('NW')
                p1 -= np.array([1,1])
                
                dx += 1
                dy += 1
            if dx > 0 and dy == 0:
                # orders.append('E')
                p1[0] += 1
                
                dx -= 1
            if dx < 0 and dy==0:
                # orders.append('W')
                p1[0] -= 1
               
                dx += 1
            if dy > 0:
                # orders.append('SW')
                p1[1] += 1
               
                dy -= 1
            if dy < 0:
                # orders.append('NE')
                p1[1] -= 1
                
                dy += 1
        return p1     
    
    def simple_pathfinder(p1, p2):
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

    def get_next_player(self, player): 
        # Find the next player in the dictionary
        "needs work"
        if player in self.players:
            current_index = self.players.index(player)
            next_index = (current_index + 1) % len(self.players)  # Use modulo for cycling
            return self.players[next_index]
        else:
            return self.players[0]  # Default to first player if not set
    
    def get_enemy_units(self, player = None):
        if player is None:
            player = self.current_player
        enemy_units = []
        for i in range(self.number_of_players - 1):
            player = self.get_next_player(player)
            for unit in player.units: 
                enemy_units.append(unit)
        return enemy_units
    
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
        
        reward = 0
        select = action[0]
        order = action[1]
        if (action[0] == [0,0]).all():
            print(f"{self.current_player.name} End Turn")
            self.current_player.end_turn()
            self.current_player = self.get_next_player(self.current_player)
            if self.current_player == self.players[0]:
                self.turn_counter += 1
                print(f"Turn {self.turn_counter}")
        else:
            for unit in self.current_player.units:
                if (select == unit.location).all(): # we need a function that keeps track of all the locations of all the units
                    # Unit Selected!
                    unit.order = order
                    # check if it's move or attack!
                    enemy_units = self.get_enemy_units(self.current_player)
                    while unit.movement_points > 0:
                        next_tile = self.get_next_tile(unit.location,unit.order)
                        attack = False
                        # Attack Check!
                        for enemy in enemy_units: # here we need the same function again -keep track of all units!
                            if (enemy.location == next_tile).all():
                                #we are attacking
                                attack = True
                                reward += 0.25
                                kill = unit.attack(enemy)
                                if kill:
                                    reward += 1
                                break
                        if not attack:
                            unit.move(next_tile)
        # Calculate new state
        self.update_state_tensor()
        

        return self.state, reward, self.done
        
    """
    
    UPDATE TO d=3
    
    """
    def update_state_tensor(self):
        # Assuming self.n, self.m, and self.d are already defined
        self.state = torch.zeros(self.d, self.n, self.m)
        
        # Assuming self.current_player and self.players are defined
        # Update for current player's units
        player = self.current_player
        layer_index = 0  # Assuming the current player's units are friendly and go in the 0th layer of d
        for unit in player.units:
            i, j = unit.location  # Assuming unit.location is a tuple or list with 2 elements
            self.state[layer_index,i, j] = unit.health  # Update health for friendly unit at (i, j)
            self.state[-1,i, j] = unit.movement_points  # Update move_points for friendly unit at (i, j)
        
        # Update for other players' units
        for player_index, player in enumerate(self.players):
            if player == self.current_player:
                continue  # Skip the current player
            layer_index += 1  # Different layer for each player
            for unit in player.units:
                i, j = unit.location
                self.state[layer_index, i, j] = -unit.health  # Negative health for enemy units




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