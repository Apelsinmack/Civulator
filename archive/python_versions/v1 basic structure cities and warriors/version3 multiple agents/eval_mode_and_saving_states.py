# -*- coding: utf-8 -*-
"""
Created on Tue Aug 13 10:32:12 2024

@author: steen
"""

# Filename: generate_game_states.py

import os
import numpy as np
import torch
from pyCiv import GameEnvironment
from GlobalDQNetworkSelectingAndMovingMultipleAgents import DQNAgent, ReplayMemory



# Ensure the directory for saving game states exists
save_dir = 'replay_states'
if not os.path.exists(save_dir):
    os.makedirs(save_dir)

# Initialize environment and agents
n, m = 10, 8
number_of_players = 2
d = 2 * number_of_players + 1

env = GameEnvironment(n, m, number_of_players)

# Create a separate agent for each player (adjust gamma and learning rate as needed)
agents = [
    DQNAgent(n, m, d, ReplayMemory(10000), gamma=0.99, learning_rate=0.001),
    DQNAgent(n, m, d, ReplayMemory(10000), gamma=0.95, learning_rate=0.0005),
    DQNAgent(n, m, d, ReplayMemory(10000), gamma=0.9, learning_rate=0.0001)
]

# Load pre-trained model weights for each agent
for i, agent in enumerate(agents[:(number_of_players-1)]):
    model_path = f'weights/agent_{i}_episode_63.pth'  # Replace with your actual model paths
    checkpoint = torch.load(model_path)
    agent.network.load_state_dict(checkpoint['model_state_dict'])
    agent.network.eval()  # Set the agent's network to evaluation mode
    print(f"Loaded model for Agent {i} from {model_path}")

# Generate and save game states
game_states = []

next_state = env.reset()
done = False

while not done:
    current_player_index = env.current_player.player_index
    current_agent = agents[current_player_index]
    action = current_agent.select_action(next_state, epsilon=0)  # No exploration
    action_matrix = [np.array([action[0] // m, action[0] % m]), np.array([action[1] // m, action[1] % m])]
    
    # Save the current state
    game_states.append(next_state.cpu().numpy())  # Convert the state to a numpy array and store it
    
    next_state, reward, done = env.step(action_matrix)

# Save game states to a file for later use
np.save(os.path.join(save_dir, 'game_states.npy'), np.array(game_states))

print(f"Game states saved in directory: {save_dir}")