"""
simple version of civ in python
the map is always cylindrical in this mode
"""


class Unit:
    def __init__(self, team, location, unit_type='Warrior', health=100):
        self.unit_type = unit_type
        self.health = health
        self.team = team
        self.location = location
        self.movement_points = self.default_movement_points(unit_type)
        self.attack_power = 25
        self.promotion = 0
        self.xp = 0

    def __str__(self):
        return f"Type: {self.unit_type}, Health: {self.health}, Team: {self.team}, Location: {self.location}"

    # Example methods you might want to add
    def move(self, new_location):
        self.location = new_location
        # retrieve defence value
        print(f"Moving to {self.location}")
    
    def attack(self, target: 'Unit'):
        # Example attack logic
        
    
        # The target takes damage from the attacker
        target.take_damage(self.attack_power)
        print(f"{self.unit_type} attacks {target.unit_type} for {self.attack_power} damage.")
    
        # The attacker takes retaliatory damage from the target
        # This could be conditional, based on whether the target is still alive, etc.
        if target.health > 0:
            self.take_damage(abs(target.attack_power - 10))
            print(f"{target.unit_type} retaliates against {self.unit_type} for {abs(target.attack_power - 10)} damage.")


    def take_damage(self, damage):
        self.health -= damage
        print(f"{self.unit_type} took {damage} damage. Health now {self.health}")
        if self.health <= 0:
            print(f"{self.unit_type} died.")
            self.location = (-1,-1) # graveyard. # Flyttas till egen funtion!

    def heal(self, amount):
        self.health += amount
        print(f"{self.unit_type} healed by {amount}. Health now {self.health}")
        
    def default_movement_points(self, unit_type):
        if unit_type == 'Warrior':
            return 1
    
    def end_of_turn_action(self):
        if self.movement_points == self.default_movement_points(self.unit_type):
            self.heal(10) # change depending on location etc.
            # add fortify bonus here
        self.movement_points = self.default_movement_points(self.unit_type)










"""
environment class

def reset():
    set game map
    set number of teams
    provide units for all teams and starting locations
    Provide a city for each team.
    
    Logic for who is the current player / agent
    
    def step():
        recieves an action (selection and movement)
        returns the new state, including info of units lost etc.

"""

class Civilization:
    def __init__(self, team):
        self.team = team
        self.units = []
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.faith = 0


class GameEnvironment:
    def __init__(self, n, m, d, teams):
        self.n = n
        self.m = m
        self.d = 2 # dimensionality for game state.
        self.teams = teams
        self.turn_counter = 0


    def reset(self):
        
        # calculate starting locations
        
        # for each team, assign 3 warriors at the starting location.
        
        
        for team in teams:
            for i in range(3): # Add 3 warrior type units to each team
                units = {
                    team : [].append}

















"""
Game Loop

"""

# initialize the game
game_over = False
# create map
n = 10 # rows in map
m = 15 # columns in map

# crate teams
teams = ['Team 1', 'Team 2']

# create units
team_1_units = []
team_2_units = []


team_units = {
    teams[0] : team_1_units,
    teams[1] : team_2_units
}


for i in range(3):
    team_units['Team 1'].append(Unit('Team 1', (n//2, m // 3 + i)))
    team_units['Team 2'].append(Unit('Team 2', (n//2, m - m//3-i)))



# start game
while game_over == False:
    for team in teams:
        #while not end of turn
            
            #recieve action
            
            #update end of turn
            

# send state to player 1
# recieve    
    
    
    
    