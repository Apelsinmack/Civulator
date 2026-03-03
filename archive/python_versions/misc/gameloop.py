# -*- coding: utf-8 -*-
"""
Created on Sat Jun 17 18:03:38 2023

@author: steen
"""

# a new turn starts. Increase  turn count by 1

# update units list, each unit will get their max movement points and heal if they are eligable for that


# Produce gamestate rep for Q function
# place all units in the map represented by health and attack score, enemy units will be represented as their negative health*attack score

# calculate all possible actions, the action space and make estimation on each actions worth with the Q function, remember end turn should be a viable action
# Is there any way to choose in what order to calculate this? Maybe look into forced moves

    # implement movement action so that if a firendly unit walks into a tile with another friendly unit, they change place just as in civ. Check if both units have movement points to do this
    # implement attack enemy unit, if victory the attacking unit moves to where the enemy unit was standing


# choose action according to policy for Q function and update gamespace
# loop this process until end of turn
# 


# Q imlement the Q function with abstact reward function R. Optionally give reward for killing enemy units or damaging them, also give rewards for having multiple units at the same distance from enemy capital with increasing rewards the closer you get..


import numpy as np





import numpy as np


class Unit:
    def __init__(self, location, team, health=10, attack=2, max_move_points=2, name='Warrior'):
        self.location = location
        self.team = team
        self.health = health
        self.attack = attack
        self.max_move_points = max_move_points
        self.move_points = max_move_points
        self.name = name

    def heal(self, amount):
        self.health += amount

    def reset_move_points(self):
        self.move_points = self.max_move_points


class City:
    def __init__(self, team, location, health=30, building_queue=None):
        self.team = team
        self.location = location
        self.health = health
        if building_queue is None:
            self.building_queue = []
        else:
            self.building_queue = building_queue
        self.building_turns_remaining = 0

    def heal(self):
        self.health += 1

    def process_building_queue(self):
        if self.building_turns_remaining > 0:
            self.building_turns_remaining -= 1
        elif self.building_queue:
            building = self.building_queue.pop(0)
            if building == 'Warrior':
                self.team.units.append(Unit(location=self.location, team=self.team))
                self.building_turns_remaining = 4


class Team:
    def __init__(self, team_id):
        self.team_id = team_id
        self.units = []
        self.cities = []


class Game:
    def __init__(self):
        self.turn_count = 0
        self.teams = [Team(1), Team(2)]
        self.map_size = (10, 10)
        self.game_map = np.zeros(self.map_size, dtype=int)
        self.initialize_game()

    def initialize_game(self):
        # Place cities
        self.teams[0].cities.append(City(team=self.teams[0], location=(5, 1)))
        self.teams[1].cities.append(City(team=self.teams[1], location=(5, 7)))

        # Spawn warriors
        self.teams[0].units.append(Unit(location=(5, 2), team=self.teams[0]))
        self.teams[0].units.append(Unit(location=(4, 2), team=self.teams[0]))
        self.teams[1].units.append(Unit(location=(5, 7), team=self.teams[1]))
        self.teams[1].units.append(Unit(location=(4, 7), team=self.teams[1]))

    def start_new_turn(self):
        self.turn_count += 1
        for team in self.teams:
            for unit in team.units:
                unit.reset_move_points()
                if unit.health < 10:  # assuming max health is 10
                    unit.heal(1)
            for city in team.cities:
                city.heal()
                city.process_building_queue()

    def generate_game_state(self):
        for team in self.teams:
            for unit in team.units:
                x, y = unit.location
                score = unit.health * unit.attack
                if team.team_id == 2:
                    score *= -1
                self.game_map[x, y] = score
        return self.game_map

    def calculate_possible_actions(self):
        # Placeholder function to calculate possible actions
        return []

    def choose_action(self, possible_actions):
        # Placeholder function to choose an action
        return None

    def play_turn(self):
        self.start_new_turn()
        game_state = self.generate_game_state()
        possible_actions = self.calculate_possible_actions()
        chosen_action = self.choose_action(possible_actions)
        # other logic like updating the Q-function goes here


# Example usage:
game = Game()
game.play_turn()
