# -*- coding: utf-8 -*-
"""
Created on Sat Jun 17 07:36:11 2023

@author: steen
"""

import numpy as np


def convert_matrix_indecies_to_vector_index(loc, mapwidth):
    return loc[0] + loc[1]*mapwidth
    
    

def moveEast(loc):
    i, j = loc
    j += 1
    return (i, j)
    
def moveWest(loc):
    i, j = loc
    j -= 1
    return (i, j)
        
def moveNorthEast(loc):
    i, j = loc
    i -=1
    if i % 2 == 0:
        j += 1
    return (i, j)

def moveNorthWest(loc):
    i, j = loc
    i -= 1
    if i % 2 == 1:
        j -= 1
    return (i,j)
        
def moveSouthEast(loc):
    i, j = loc
    i += 1
    if i % 2 == 0:
        j += 1
    return (i, j)

def moveSouthWest(loc):
    i, j = loc
    i += 1
    if i % 2 == 1:
        j -= 1
    return (i, j)


def getNeighbours(loc):
    return [moveEast(loc), moveNorthEast(loc), moveNorthWest(loc), moveWest(loc), moveSouthWest(loc), moveSouthEast(loc)]
def getAllTilesAtDistanceR(loc, R):
    # selects tiles in a hexagonal ring with radius R around loc.
    assert (R >= 0)
    
    # Helper functions for moving in hexagonal directions
    def moveEast(loc):
        x, y = loc
        return (x+1, y)
    
    def moveNorthEast(loc):
        x, y = loc
        return (x+1, y-1) if y % 2 == 0 else (x, y-1)
    
    def moveNorthWest(loc):
        x, y = loc
        return (x, y-1) if y % 2 == 0 else (x-1, y-1)
    
    def moveWest(loc):
        x, y = loc
        return (x-1, y)
    
    def moveSouthWest(loc):
        x, y = loc
        return (x, y+1) if y % 2 == 0 else (x-1, y+1)
    
    def moveSouthEast(loc):
        x, y = loc
        return (x+1, y+1) if y % 2 == 0 else (x, y+1)
    
    # Moving R steps east from the center to reach the starting position
    for i in range(R):
        loc = moveEast(loc)
    
    # List to store the tiles
    tiles = []
    
    # List of move functions in the sequence to move in a hexagonal loop
    move_functions = [moveNorthWest, moveWest, moveSouthWest, moveSouthEast, moveEast, moveNorthEast]
    
    # Loop through each direction and move R steps in that direction
    for move_function in move_functions:
        for i in range(R):
            loc = move_function(loc)
            tiles.append(loc)
    
    return tiles

# Example usage
center = (3, 3)
radius = 2
tiles_at_distance_2 = getAllTilesAtDistanceR(center, radius)
print(tiles_at_distance_2)

# def getAllTilesAtDistanceR(loc, R):
#     # selects tiles in a circle with radius R around loc.
#     assert (R >= 0)
#     for i in range(R):
#         loc = moveEast(loc)
#     tiles = [loc]
#     for i in range(R):
#         loc = moveNorthEast(loc)
#         tiles.append(loc)
#     for i in range(R):
#         loc = moveWest(loc)
#         tiles.append(loc)
#     for i in range(R):
#         loc = moveSouthWest(loc)
#         tiles.append(loc)
#     for i in range(R):
#         loc = moveSouthEast(loc)
#         tiles.append(loc)
#     for i in range(R):
#         loc = moveEast(loc)
#         tiles.append(loc)
#     for i in range(R-1):
#         loc = moveNorthEast(loc)
#         tiles.append(loc)
#     return tiles
            
        

def distance(locA, locB):
    iA, jA = locA
    iB, jB = locB
    return abs(iB - iA) + abs(jB - jA) - abs((iB-iA)//2)


            

