# -*- coding: utf-8 -*-
"""
Created on Sat Jun 17 10:48:51 2023

@author: steen
"""
import random
import numpy as np

def get_ascii_representation(cell):
    if cell == 0:  # Empty tile
        return "."
    elif cell == 1:  # Mountain
        return "#"
    elif cell == 2:  # Forest
        return "*"
    else:
        return "?"


def print_map(gamemap):
    for i, row in enumerate(gamemap):
        if i % 2 == 0:
            print(" ", end="")
        for cell in row:
            print(get_ascii_representation(cell), end=" ")
        print()
    print()

def randomize_matrix(gamemap):
    for i in range(len(gamemap)):
        for j in range(len(gamemap[i])):
            gamemap[i][j] = random.randint(0, 2)
            
gamemap = np.zeros(shape=(10,15), dtype=int)

randomize_matrix(gamemap)

print_map(gamemap)