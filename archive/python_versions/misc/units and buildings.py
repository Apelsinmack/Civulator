# -*- coding: utf-8 -*-
"""
Created on Sat Jun 17 18:26:32 2023

@author: steen
"""


class Warrior:
    
    def __init__(self, location, team, name="Warrior"):
        # Initial health of the warrior
        self.health = 100
        
        # Action points determine how many moves the warrior can make
        self.action_points = 2
        
        # Location of the warrior on the map as (x, y) coordinates
        self.location = location
        
        # Team to which the warrior belongs
        self.team = team
        
        # Name of the warrior
        self.name = name
        
    def move(self, new_location, movement_cost):
        """
        Move the warrior to a new location.
        Decreases the action points by 1 for each move.
        """
        if self.action_points >= movement_cost:
            self.location = new_location
            self.action_points -= movement_cost
            print(f"{self.name} moved to {new_location}.")
        else:
            print(f"{self.name} has no action points left.")
            
    def rename(self, new_name):
        """
        Rename the warrior.
        """
        self.name = new_name
        print(f"Warrior has been renamed to {self.name}.")
        
    def __str__(self):
        """
        String representation of the warrior.
        """
        return f"{self.name} (Team {self.team}) at {self.location} with {self.health} health and {self.action_points} action points."

# Example usage:
warrior1 = Warrior(location=(1, 1), team=1)
print(warrior1)

warrior1.move((2, 2))
print(warrior1)

warrior1.rename("Elite Warrior")
print(warrior1)
