# -*- coding: utf-8 -*-
"""
Created on Tue Aug 13 10:43:09 2024

@author: steen
"""

import matplotlib.pyplot as plt

# def plot_state(state, filename, player_colors=['red', 'blue', 'green']):
#     plt.figure(figsize=(10, 8))
    
#     # Plot cities and units for each player
#     for i, color in enumerate(player_colors):
#         city_layer = state[0 + 2*i]
#         unit_layer = state[1 + 2*i]
        
#         for (x, y), value in np.ndenumerate(city_layer):
#             if value > 0:
#                 plt.scatter(y, x, marker='s', color=color, s=100)
        
#         for (x, y), value in np.ndenumerate(unit_layer):
#             if value > 0:
#                 plt.scatter(y, x, marker='o', color=color, s=100)
    
#     # Optional: Add labels, grids, etc.
#     plt.grid(True)
#     plt.gca().invert_yaxis()
#     plt.title("Game State")
    
#     plt.savefig(filename)
#     plt.close()

# # Plot each state and save it as an image
# for i, state in enumerate(game_states):
#     plot_state(state, os.path.join(save_dir, f'state_{i:04d}.png'))

# plot_game_states.py

# Implement: sortera states, kolla var huvudstaden för player1 ligger i state 1, sen plotta bara states där huvudsta1 ligger där


import os
import numpy as np
import matplotlib.pyplot as plt

# Function to plot a single game state
def plot_state(state, filename, player_colors=['red', 'blue']):
    plt.figure(figsize=(10, 8))
    
    # Plot cities and units for each player
    for i, color in enumerate(player_colors):
        if i == 0:
            city_layer = state[0 + 2*i]
            unit_layer = state[1 + 2*i]
        else:
            city_layer = state[0 + 2*i +1]
            unit_layer = state[1 + 2*i +1]
        
        for (r, c), value in np.ndenumerate(city_layer):
            if value != 0:
                plt.scatter(c, r, marker='s', color=color, s=100)  # Plot cities as squares
        
        for (x, y), value in np.ndenumerate(unit_layer):
            if value != 0:
                plt.scatter(y, x, marker='o', color=color, s=100)  # Plot units as circles
    
    # Optional: Add labels, grids, etc.
    plt.grid(True)
    plt.xlim(0,8)
    plt.ylim(0,10)
    plt.gca().invert_yaxis()
    plt.title("Game State")
    
    # Save the plot as an image file
    plt.savefig(filename)
    # plt.show()
    plt.close()

# Load the game states from the .npy file
game_states = np.load('replay_states/game_states.npy')

# Ensure the directory for saving plots exists
plot_dir = 'plots'
if not os.path.exists(plot_dir):
    os.makedirs(plot_dir)

# plot_state(game_states[0], 'yo')


# Plot each state and save it as an image
for i, state in enumerate(game_states):
    plot_filename = os.path.join(plot_dir, f'state_{i:04d}.png')
    plot_state(state, plot_filename)

print(f"Plots saved in directory: {plot_dir}")
