"""
simple version of civ in python
the map is always cylindrical in this mode
"""
import random
import np as np
import torch
import torch.nn as nn
import torch.nn.functional as F

class Unit:
    def __init__(self, player, location, unit_type='Warrior', health=100):
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


    def __str__(self):
        return f"Type: {self.unit_type}, Health: {self.health}, Team: {self.player}, Location: {self.location}"

    # Example methods you might want to add
    def teleport(self, new_location):
        self.location = new_location
        # retrieve defence value
        if self.verbose:
            print(f"Teleporting to {self.location}")
    
    def move(self, new_location): # No pathfinding.
        self.location = new_location
        self.movement_points -= 1
    
    
    def attack(self, target: 'Unit'):
        kill = False
        target.take_damage(self.attack_power)
        if target.dead == True:
            self.location = target.location # does not take into account for ranged attacks.
            self.xp += 10
            kill = True
        self.movement_points = 0
        self.take_damage(target.attack_power//2)
        if self.verbose:
            print(f"{self.player} {self.unit_type} attacks {target.player} {target.unit_type} for {self.attack_power} damage.")
        return kill




    def take_damage(self, damage):
        self.health -= damage
        if self.verbose:
            print(f"{self.unit_type} took {damage} damage. Health now {self.health}")
        if self.health <= 0:
            self.dead = True
            if self.verbose:
                print(f"{self.player} {self.unit_type} died.")
            # self.location = np.array([-1,-1]) # graveyard. # Flyttas till egen funtion!

    def heal(self, amount):
        self.health += amount
        self.health = min(self.health, self.max_health)
        if self.verbose:
            print(f"{self.unit_type} healed by {amount}. Health now {self.health}")
        
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

class Civilization:
    def __init__(self, name):
        self.name = name
        self.units = []
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.faith = 0
        self.income = 0
        self.starting_location = (0,0)
        # kanske ändra till en dict som heter typ resources som innehåller guld, science etc samt en dict som heter incomes som innehåller samma sak.
        
        # We will need a dict or list of locations of interest, this should contain all units and cities.
        
        def add_unit(self, location, unit_type='Warrior'):
            self.units.append(Unit(self.name, location, unit_type))
            
        def get_unit_at_pos(position):
            for unit in self.units:
                if unit.position == position:
                    return unit
            return
        
        def end_turn(self):
            for unit in self.units:
                unit.end_of_turn_action()
                    


class GameEnvironment:
    def __init__(self, n, m, d):
        self.n = n
        self.m = m
        self.d = 1 # dimensionality for game state. (multiplied by nbr of players)
        self.turn_counter = 0
        self.current_player = ''
        self.players = {} # the dictionary should be ordered. (comment for later cython implementation)
        self.done = False
        self.state = None

    
    def add_civ(self, name):
        self.players[name] = Civilization(name)

    def reset(self, number_of_players):   
        # Clear existing players and add new ones
        self.players.clear()
        for i in range(number_of_players):
            self.add_civ(f"Player {i+1}")
        
        self.state = torch.zeros(self.n,self.m, self.d*number_of_players)
        
        # calculate starting locations
        if number_of_players == 2:
            starting_locations = []
            self.players[0].starting_location = np.array([random.randint(1,n-1), random.randint(1, m//2)])
            self.players[1].starting_location = np.array([random.randint(1,n-1), random.randint(m//2+1, m)])
        else:
            for player in self.players:
                player.starting_location =(random.randint(0,n),random.randint(0,m)) #needs work, might create players on top of each other!!!!
                # make this like 2playter version but partition the map in equal parts.
            
                
        for player_name, player in self.players.items():
            offset1 = np.array([1, 1])
            offset2 = np.array([0, 1])
            player.add_unit(player.starting_location)
            player.add_unit(player.starting_location + offset1)
            player.add_unit(player.starting_location + offset2)
            
        self.current_player = self.players[0].name
    
    
    def get_next_tile(p1, p2):
        #unit wants to move from position p1 to p2, this function returns the next tile in the path.
        dx, dy = p2[0]-p1[0], p2[1]-p1[1]
        
        # while abs(dx) + abs(dy) > 0:
        if abs(p2-p1) > 0:
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
        keys = list(self.players.keys())
        if player.name in keys:
            current_index = keys.index(self.current_player)
            next_index = (current_index + 1) % len(keys)  # Use modulo for cycling
            return keys[next_index]
        else:
            return keys[0]  # Default to first player if not set
    
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
        select = action[0]
        order = action[1]
        for unit in self.players[self.current_player].units:
            if select == unit.location:
                # Unit Selected!
                unit.order = order
                # check if it's move or attack!
                enemy_units = self.get_enemy_units()
                while unit.movement_points > 0:
                    next_tile = self.get_next_tile(unit.location,unit.order)
                    # Attack Check!
                    for enemy in enemy_units:
                        if enemy.position == next_tile:
                            #we are attacking
                            attack = True
                            kill = unit.attack(enemy)
                            if kill:
                                reward = 1
                            break
                    if not attack:
                        unit.move(next_tile)
        # Calculate new state
        self.update_state()
                
                
                
                
                
                
                
                # calc path / next move
                
        
        # find the unit
        
        
        # prepare next move / attack
        # if action[1] is an attack order explicitly, attack, otherwise cancel the order just as in civ6. we want the agent to confirm any attacks.
        
        # calculate action response
        
        # calc new state
        # calculate rewards
        
        # check if end of turn
        # check if game over
        
        state, reward, done = 0, 0, False
        return 
        

















"""
Game Loop

"""

# initialize the game
game_over = False
# create map
n = 10 # rows in map
m = 15 # columns in map
d = 2


env = GameEnvironment(n, m, d)
env.reset(2)


    
    
    
    