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

def distance(locA, locB):
    iA, jA = locA
    iB, jB = locB
    return abs(iB - iA) + abs(jB - jA) - abs((iB-iA)//2)


            

