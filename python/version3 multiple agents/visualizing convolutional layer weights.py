# -*- coding: utf-8 -*-
"""
Created on Tue Aug 13 06:55:33 2024

@author: steen
"""

import torch
import matplotlib.pyplot as plt
from GlobalDQNSelectingAndMoving_with_pyCiv20240813 import *


def visualize_conv_weights(layer, num_filters=8, num_channels=5, figsize=(15, 8)):
    weights = layer.weight.data.cpu().numpy()
    
    num_filters = min(num_filters, weights.shape[0])
    num_channels = min(num_channels, weights.shape[1])
    
    fig, axes = plt.subplots(num_filters, num_channels, figsize=figsize)
    
    for i in range(num_filters):
        for j in range(num_channels):
            ax = axes[i, j]
            filter_slice = weights[i, j]
            ax.imshow(filter_slice, cmap='gray')
            ax.axis('off')
            ax.set_title(f'Filter {i+1}, Channel {j+1}')
    
    plt.show()

# Example values for n, m, and d (you should replace these with the actual values)
n = 10  # Number of rows
m = 8  # Number of columns
d = 5  # Number of channels (depth)

# Initialize ReplayMemory
memory = ReplayMemory(10000)

# Instantiate the agent
agent = DQNAgent(n, m, d, memory)


#  Load the model weights
model_path = 'weights/model_episode_63.pth'
state_dict = torch.load(model_path)
agent.network.load_state_dict(state_dict)


# Visualize the first convolutional layer weights for selection
conv_layer_select = agent.network.conv1_select
visualize_conv_weights(conv_layer_select, num_filters=8, num_channels=5)

# Visualize the first convolutional layer weights for movement
conv_layer_move = agent.network.conv1_move
visualize_conv_weights(conv_layer_move, num_filters=8, num_channels=5)