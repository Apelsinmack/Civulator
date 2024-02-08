# -*- coding: utf-8 -*-
"""
Created on Wed Dec 27 12:14:42 2023

@author: steen
"""
import numpy as np


def array_index_to_matrix_index(array_index, width):
    # array_index should be a numpy array
    row = array_index // width # // = floor division = normal division for ints in C#.
    col = (row+1)//2 + array_index - row * width # First term accounts for utility tiles before real tiles
    return (row, col)

    
def matrix_index_to_array_index(row, col, width, height):
    return row * width + col - (row+1)//2   # Last term corrects for utility tiles before the real tiles

"""
The next function transforms an actualy array to the matrix representation and the next function after that does the inverse operation: Matrix -> array
These are mostly for debugging purposes and won't be used in game probably.'
"""

def array_to_matrix_map(map_array, height, width):
    """returns a (m x n) - matrix representaiton of the map
    height = map height in game
    width = map width in game"""
    map_matrix = -1 * np.ones((height, width + height//2))
    for row in range(height):
        tile_step = (row+1)//2
        print('step = ' + str(tile_step))
        print('Row = ' + str(row))
        map_matrix[row][tile_step:tile_step + width] = map_array[row*width : (row+1)*width]
    return map_matrix


def matrix_to_array_map(map_matrix, height, width):
    #This function is probably not needed
    map_array = np.zeros(height*width)
    current_row = 0
    for row in map_matrix:
        map_array[current_row*width:(current_row+1)*width-1] = row[current_row:-(height//2-current_row)]

def simple_pathfinder(dx, dy):
    # fundera på att ändra argument till punkterna P1, P2
    orders = []
    while abs(dx * dy) > 0:
        while dx > 0 and dy >0: 
            orders.append('SE')
            dx -= 1
            dy -= 1
        while dx < 0 and dy < 0:
            orders.append('NW')
            dx += 1
            dy += 1
        while dx > 0:
            orders.append('E')
            dx -= 1
        while dx < 0:
            orders.append('W')
            dx += 1
        while dy > 0:
            orders.append('S')
            dy -= 1
        while dy < 0:
            orders.append('N')
            dy += 1
    return orders
                

def distnace_function(p1, p2):
    dx = p2[1] - p1[1]
    dy  =p2[0] - p1[0]
    if dx*dy > 0:
        d = max(abs(dx), abs(dy))
    else:
        d = abs(dx) + abs(dy)
    return d

def distance_function_naive(p1, p2):
    #for debugging purposes only
    ds = p2 - p1
    dx = ds[1]
    dy = ds[0]
    return len(simple_pathfinder(dx, dy))

        



width = 7
height = 7
number_of_tiles = width*height

map_array = np.ones(width*height)
for i in range(len(map_array)):
    map_array[i]= int(i)

# for i in range(base*height):
#     map_array[i*base:(i+1)*base] = i
    
print(map_array)

map_matrix = array_to_matrix_map(map_array, height, width)


print(map_matrix)

# array index to map index:
array_index = np.array([1, 4, 8, 13,14,15])

row = array_index // width # Funkar
col = (row+1)//2 + array_index - row * width

row = array_index // width # Funkar
col = (row+1)//2 + array_index - row * width


print('Tile ' + str(array_index) + ' is in (row,col) = (' + str(row) + ',' + str(col) + ')')

map_matrix[array_index_to_matrix_index(array_index, width)] = 66
# print(map_matrix)
# print(map_matrix.shape)


orders_test = simple_pathfinder(15,-10)    
print(orders_test)
print(len(orders_test))
