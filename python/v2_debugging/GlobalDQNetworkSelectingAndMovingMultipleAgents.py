"""
For Version2
"""
import pyCiv
from ascii_map_display import *
import torch
import torch.nn as nn
import torch.nn.functional as F
import random
from collections import namedtuple
import numpy as np
import os
print('py Torch version:')
print(torch.__version__)
print('Cuda is available: ')
print(torch.cuda.is_available())

# Define the Transition namedtuple
Transition = namedtuple('Transition', ('state', 'action', 'reward', 'next_state', 'done'))

# class SelectAndMoveNetwork(nn.Module):
#     def __init__(self, n, m, d):
#         super(SelectAndMoveNetwork, self).__init__()

#         # Convolutional layers for unit selection
#         self.conv1_select = nn.Conv2d(d, 16, kernel_size=3, stride=1, padding=0)
#         self.bn1_select = nn.BatchNorm2d(16)
#         self.conv2_select = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=0)
#         self.bn2_select = nn.BatchNorm2d(32)

#         # Convolutional layers for movement decision
#         self.conv1_move = nn.Conv2d(d, 16, kernel_size=3, stride=1, padding=1)
#         self.bn1_move = nn.BatchNorm2d(16)
#         self.conv2_move = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1)
#         self.bn2_move = nn.BatchNorm2d(32)

#         # Fully connected layers for unit selection and movement decision
#         self.fc_select = nn.Linear(n * m * 32, n * m + 1)
#         self.fc_move = nn.Linear(n * m * 32 + 1, n * m)  # +1 for the selected unit's position's index

#     # def forward(self, state, selected_pos=None):
#     #     # Forward pass through selection convolutional layers
#     #     x_select = F.relu(self.bn1_select(self.conv1_select(state)))
#     #     x_select = F.relu(self.bn2_select(self.conv2_select(x_select)))
#     #     x_select = x_select.view(x_select.size(0), -1)  # flatten
#     #     select_probs = F.softmax(self.fc_select(x_select), dim=1)
#     def forward(self, state, selected_pos=None):
#         # Apply custom padding
#         kernel_size = 3  # Assuming this is your max kernel size
#         padding_size = kernel_size // 2
#         padded_state = horizontal_wrap_padding(state, padding_size)
        
#         # Forward pass through selection convolutional layers (with padding=0)
#         x_select = F.relu(self.bn1_select(self.conv1_select(padded_state)))
#         x_select = F.relu(self.bn2_select(self.conv2_select(x_select)))

#         if selected_pos is not None:
#             # Forward pass through movement convolutional layers
#             x_move = F.relu(self.bn1_move(self.conv1_move(state)))
#             x_move = F.relu(self.bn2_move(self.conv2_move(x_move)))
#             x_move = x_move.view(x_move.size(0), -1)  # flatten
            
#             selected_pos = selected_pos.float().view(-1, 1) 
#             x_move = torch.cat([x_move, selected_pos], dim=1)  # append selected position to feature vector
#             move_probs = F.softmax(self.fc_move(x_move), dim=1)
#             return select_probs, move_probs
        
#         return select_probs, None
class SelectAndMoveNetwork(nn.Module):
    def __init__(self, n, m, d, kernel_size=3):
        super(SelectAndMoveNetwork, self).__init__()
        
        # Calculate padding size based on kernel size
        self.padding_size = kernel_size // 2
        
        # Calculate the new dimensions after padding
        self.padded_n = n + 2 * self.padding_size
        self.padded_m = m + 2 * self.padding_size
        
        # Save original dimensions for cropping
        self.n = n
        self.m = m
        
        # Convolutional layers with no padding (we'll do custom padding)
        self.conv1_select = nn.Conv2d(d, 16, kernel_size=kernel_size, stride=1, padding=0)
        self.bn1_select = nn.BatchNorm2d(16)
        self.conv2_select = nn.Conv2d(16, 32, kernel_size=kernel_size, stride=1, padding=0)
        self.bn2_select = nn.BatchNorm2d(32)
        
        # Movement convolutional layers
        self.conv1_move = nn.Conv2d(d, 16, kernel_size=kernel_size, stride=1, padding=0)
        self.bn1_move = nn.BatchNorm2d(16)
        self.conv2_move = nn.Conv2d(16, 32, kernel_size=kernel_size, stride=1, padding=0)
        self.bn2_move = nn.BatchNorm2d(32)
        
        # Calculate the size of the convolutional output
        # For each conv layer with padding=0:
        # output_size = input_size - kernel_size + 1
        conv1_out_size_n = self.padded_n - kernel_size + 1
        conv1_out_size_m = self.padded_m - kernel_size + 1
        conv2_out_size_n = conv1_out_size_n - kernel_size + 1
        conv2_out_size_m = conv1_out_size_m - kernel_size + 1
        
        # Calculate flattened size for FC layer
        self.flattened_size = 32 * conv2_out_size_n * conv2_out_size_m
        
        # Fully connected layers
        self.fc_select = nn.Linear(self.flattened_size, n * m + 1)  # Original dimensions + end turn
        self.fc_move = nn.Linear(self.flattened_size + 1, n * m)    # Original dimensions
    
    def forward(self, state, selected_pos=None):
        # Apply custom padding
        padded_state = horizontal_wrap_padding(state, self.padding_size)
        
        # Forward pass through selection convolutional layers
        x_select = F.relu(self.bn1_select(self.conv1_select(padded_state)))
        x_select = F.relu(self.bn2_select(self.conv2_select(x_select)))
        x_select = x_select.view(x_select.size(0), -1)  # flatten
        
        # Apply selection FC layer
        select_probs = F.softmax(self.fc_select(x_select), dim=1)
        
        if selected_pos is not None:
            # Forward pass through movement convolutional layers
            x_move = F.relu(self.bn1_move(self.conv1_move(padded_state)))
            x_move = F.relu(self.bn2_move(self.conv2_move(x_move)))
            x_move = x_move.view(x_move.size(0), -1)  # flatten
            
            selected_pos = selected_pos.float().view(-1, 1) 
            x_move = torch.cat([x_move, selected_pos], dim=1)  # append selected position to feature vector
            move_probs = F.softmax(self.fc_move(x_move), dim=1)
            return select_probs, move_probs
        
        return select_probs, None

def get_valid_select_mask(state):
    """
    Generate a mask indicating valid selections based on the game state.
    Only units with movement points left are considered valid for selection.
    """
    # Extract the layers we need
    unit_health_layer = state[1, :, :]  # Shape: [n, m] - Current player's units health
    movement_points_layer = state[2, :, :]  # Shape: [n, m] - Current player's units movement points
    
    # Generate a mask where positions with movement points > 0 are marked as 1, else 0
    valid_select_mask = (movement_points_layer > 0.01).float()  # Convert boolean mask to float
    
    # Also check that there's a unit there (health > 0)
    unit_present_mask = (unit_health_layer > 0.01).float()
    
    # A valid selection needs both a unit and movement points
    combined_mask = valid_select_mask * unit_present_mask
    
    # Flatten the mask to match the shape [n*m], corresponding to flattened select_probs
    flattened_mask = combined_mask.flatten()
    
    return flattened_mask

def adjust_mask_for_end_turn(original_mask):
    """
    Modify the mask to include the "end turn" action.
    """
    # Get device of the original mask
    device = original_mask.device
    
    # Add a `1` at the end of the original mask to account for the "end turn" action
    end_turn_mask = torch.cat([original_mask, torch.tensor([1.0]).to(device)])
    
    return end_turn_mask

def get_valid_moves_mask(state, selected_pos):
    """
    Generate a mask for valid move positions based on the selected unit.
    """
    # Get dimensions from state
    d, n, m = state.shape
    device = state.device
    
    # Convert selected_pos to 2D coordinates
    if selected_pos >= n * m:
        # This is the end turn action, no valid moves
        return torch.zeros(n * m, device=device)
    
    row = selected_pos // m
    col = selected_pos % m
    
    # Create a mask initially filled with zeros
    valid_move_mask = torch.zeros(n, m, device=device)
    
    # Check if there's a unit at the selected position with movement points
    unit_health = state[1, row, col].item()
    movement_points = state[2, row, col].item()
    
    if unit_health <= 0 or movement_points <= 0:
        # No unit or no movement points, return empty mask
        return valid_move_mask.flatten()
    
    # Enemy units layer for the first enemy
    enemy_units_layer = state[4, :, :]  # Assuming layer 4 is the first enemy's units
    
    # Mark adjacent positions as valid if they're empty or have enemy units
    for dr in [-1, 0, 1]:
        for dc in [-1, 0, 1]:
            # Skip the current position
            if dr == 0 and dc == 0:
                continue
                
            # Calculate new position with wrapping
            new_row = (row + dr) % n
            new_col = (col + dc) % m
            
            # Check if the position is empty or has an enemy unit
            friendly_unit = state[1, new_row, new_col].item() > 0
            enemy_unit = enemy_units_layer[new_row, new_col].item() < 0
            
            if not friendly_unit or enemy_unit:
                valid_move_mask[new_row, new_col] = 1
    
    # Also mark the current position as valid (for fortify action)
    valid_move_mask[row, col] = 1
    
    # Flatten the mask
    flattened_mask = valid_move_mask.flatten()
    
    return flattened_mask
   
def select_and_move(game_state, network):
    # network = SelectAndMoveNetwork(game_state.shape[1], game_state.shape[2], game_state.shape[0])
    
    # Get unit selection probabilities
    select_probs, _ = network(game_state.unsqueeze(0))
    # print(select_probs)
    
    # Mask invalid selections (e.g., tiles without units)
    original_mask = get_valid_select_mask(game_state)
    select_probs = select_probs * adjust_mask_for_end_turn(original_mask)
    
    # Normalize again after masking
    select_probs = select_probs / select_probs.sum()

    # Sample selected position
    selected_pos = torch.multinomial(select_probs, 1)
    
    # Now get movement probabilities for the selected unit
    _, move_probs = network(game_state.unsqueeze(0), selected_pos)
    
    # Mask invalid moves (e.g., tiles not adjacent to the selected unit)
    move_probs = move_probs * get_valid_moves_mask(game_state, selected_pos).unsqueeze(0)
    
    # Normalize again after masking
    move_probs = move_probs / move_probs.sum()
    
    # Sample move position
    move_pos = torch.multinomial(move_probs, 1)
    
    return selected_pos, move_pos

def horizontal_wrap_padding(state, padding_size=1):
    """
    Create a padded state that wraps horizontally.
    
    Args:
        state: The input state tensor, either (batch_size, d, n, m)
        padding_size: Number of cells to pad on each side
        
    Returns:
        padded_state: Tensor with horizontal wrapping padding
    """
    # Detect input shape
    if len(state.shape) == 4:
        # Batched input: [batch_size, channels, height, width]
        batch_size, d, n, m = state.shape
        device = state.device
        
        # Create a new tensor with padding
        padded_state = torch.zeros(batch_size, d, n + padding_size*2, m + padding_size*2, device=device)
        
        # Copy original state to center
        padded_state[:, :, padding_size:n+padding_size, padding_size:m+padding_size] = state
        
        # Pad top and bottom with zeros (already zeros)
        
        # Pad left and right with wrapped values
        for i in range(padding_size):
            # Right edge to left padding
            padded_state[:, :, padding_size:n+padding_size, i] = state[:, :, :, m-(padding_size-i)]
            # Left edge to right padding
            padded_state[:, :, padding_size:n+padding_size, m+padding_size+i] = state[:, :, :, i]
        
        # Corners remain as zeros
    else:
        # Non-batched input: [channels, height, width]
        d, n, m = state.shape
        device = state.device
        
        # Create a new tensor with padding
        padded_state = torch.zeros(d, n + padding_size*2, m + padding_size*2, device=device)
        
        # Copy original state to center
        padded_state[:, padding_size:n+padding_size, padding_size:m+padding_size] = state
        
        # Pad left and right with wrapped values
        for i in range(padding_size):
            # Right edge to left padding
            padded_state[:, padding_size:n+padding_size, i] = state[:, :, m-(padding_size-i)]
            # Left edge to right padding
            padded_state[:, padding_size:n+padding_size, m+padding_size+i] = state[:, :, i]
    
    return padded_state

class ReplayMemory:
    def __init__(self, capacity):
        self.capacity = capacity
        self.memory = []
        self.position = 0

    def push(self, state, action, reward, next_state, done):
        if len(self.memory) < self.capacity:
            self.memory.append(None)
        self.memory[self.position] = (state, action, reward, next_state, done)
        self.position = (self.position + 1) % self.capacity

    def sample(self, batch_size):
        return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)


class DQNAgent:
    def __init__(self, n, m, d, memory, gamma = 0.9, learning_rate = 0.001):
        # We might want to rething having n, m and d as self variables here. These are the height, width of tha map, d is how many units are supported.
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")
        self.n = n
        self.m = m
        self.d = d
        self.gamma = gamma
        self.memory = memory
        self.network = SelectAndMoveNetwork(n, m, d).to(self.device)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr = learning_rate)
        self.criterion = nn.MSELoss()
        self.pending_transitions = []  # Store transitions that are waiting for next state

    def store_pending_transition(self, state, action, reward):
        """Store a transition that's waiting for the next state from this agent's perspective"""
        self.pending_transitions.append((state, action, reward))
    
    def complete_pending_transition(self, next_state, done):
        """Complete a pending transition with the agent's actual next state"""
        if not self.pending_transitions:
            return  # Nothing to complete
            
        state, action, reward = self.pending_transitions.pop(0)  # Get oldest pending transition
        self.store_transition(state, action, reward, next_state, done)

    # New method to build state representation from raw game state
    def build_state_tensor(self, game_env):
        """
        Build a tensor representation of the game state from the raw game environment.
        """
        # Initialize a zero tensor with appropriate dimensions
        state_tensor = torch.zeros(self.d, self.n, self.m, device=self.device)
        
        # Get the current player
        current_player = game_env.current_player
        
        # Layer 0: Current player's cities
        for city in current_player.cities:
            i, j = city.coordinates
            state_tensor[0, i, j] = 100  # Use city health or a constant value
        
        # Layer 1: Current player's units (health)
        # Layer 2: Current player's units (movement points)
        for unit in current_player.units:
            i, j = unit.coordinates
            state_tensor[1, i, j] = unit.health
            state_tensor[2, i, j] = unit.movement_points
        
        # Layers for other players (enemies)
        layer_index = 3
        for player in game_env.players:
            if player == current_player:
                continue  # Skip the current player
                
            # Enemy cities
            for city in player.cities:
                i, j = city.coordinates
                state_tensor[layer_index, i, j] = -100  # Negative to indicate enemy
                
            # Enemy units
            for unit in player.units:
                i, j = unit.coordinates
                state_tensor[layer_index + 1, i, j] = -unit.health  # Negative health for enemies
                
            layer_index += 2  # Move to the next pair of layers
        
        return state_tensor
    
    def select_action(self, state, epsilon=0.1):
        """
        Select an action based on the current state.
        """
        # First, decide whether to explore or exploit
        if random.random() < epsilon:  # Exploration
            # Generate valid selection mask
            original_mask = get_valid_select_mask(state)
            adjusted_mask = adjust_mask_for_end_turn(original_mask)
            valid_positions = torch.where(adjusted_mask > 0)[0].tolist()
            
            if len(valid_positions) > 0:
                # Randomly select a valid position
                selected_pos = random.choice(valid_positions)
                
                # Check if this is the end turn action
                if selected_pos == self.n * self.m:
                    # For end turn, the move position doesn't matter
                    move_pos = random.randint(0, self.n * self.m - 1)
                else:
                    # Get valid moves for the selected position
                    valid_moves_mask = get_valid_moves_mask(state, selected_pos)
                    valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
                    
                    if len(valid_moves) > 0:
                        move_pos = random.choice(valid_moves)
                    else:
                        # If no valid moves, choose a random position
                        move_pos = random.randint(0, self.n * self.m - 1)
            else:
                # If no valid positions, default to end turn
                selected_pos = self.n * self.m  # End turn action
                move_pos = random.randint(0, self.n * self.m - 1)
            
            return (selected_pos, move_pos)
        
        else:  # Exploitation
            # Get network predictions
            with torch.no_grad():
                state_tensor = state.unsqueeze(0)  # Add batch dimension
                
                # Get unit selection probabilities
                select_probs, _ = self.network(state_tensor)
                select_probs = select_probs.squeeze(0)  # Remove batch dimension
                
                # Mask invalid selections
                original_mask = get_valid_select_mask(state)
                select_probs_masked = select_probs * adjust_mask_for_end_turn(original_mask)
                
                # If all selections are invalid (sum is 0), default to end turn
                if select_probs_masked.sum().item() <= 0:
                    selected_pos = self.n * self.m  # End turn action
                    move_pos = random.randint(0, self.n * self.m - 1)
                    return (selected_pos, move_pos)
                
                # Normalize masked probabilities
                select_probs_masked = select_probs_masked / select_probs_masked.sum()
                
                # Sample selection position
                selected_pos = torch.multinomial(select_probs_masked, 1).item()
                
                # Check if this is the end turn action
                if selected_pos == self.n * self.m:
                    # For end turn, the move position doesn't matter
                    move_pos = random.randint(0, self.n * self.m - 1)
                else:
                    # Now get movement probabilities for the selected unit
                    _, move_probs = self.network(state_tensor, torch.tensor([[selected_pos]], device=state.device).float())
                    move_probs = move_probs.squeeze(0)  # Remove batch dimension
                    
                    # Mask invalid moves
                    valid_moves_mask = get_valid_moves_mask(state, selected_pos)
                    move_probs_masked = move_probs * valid_moves_mask
                    
                    # If all moves are invalid, choose randomly from valid moves
                    if move_probs_masked.sum().item() <= 0:
                        valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
                        if valid_moves:
                            move_pos = random.choice(valid_moves)
                        else:
                            move_pos = selected_pos  # Default to staying in place
                    else:
                        # Normalize masked probabilities
                        move_probs_masked = move_probs_masked / move_probs_masked.sum()
                        
                        # Sample move position
                        move_pos = torch.multinomial(move_probs_masked, 1).item()
            
            return (selected_pos, move_pos)


    def store_transition(self, state, action, reward, next_state, done):
        self.memory.push(state, action, reward, next_state, done)

    def compute_loss(self, batch_size):
        # Sample from replay memory
        transitions = self.memory.sample(batch_size)
        batch = Transition(*zip(*transitions))

        # Separate the components of the transitions
        state_batch = torch.stack(batch.state)
        action_batch = list(zip(*batch.action)) # [(selected_1, move_1), ..., (selected_batch, move_batch)]
        reward_batch = torch.tensor(batch.reward)
        next_state_batch = torch.stack(batch.next_state)
        done_batch = torch.tensor(batch.done, dtype=torch.float32)
        # Assuming action_batch is a list of tuples [(selected_pos, move_pos), ...]
        selected_positions = action_batch[0]  # Extracts the first element of each tuple
        selected_positions_tensor = torch.tensor(selected_positions, dtype=torch.long, device=state_batch.device)
        # Assuming selected_positions_tensor needs to be concatenated along the feature dimension
        selected_positions_tensor = selected_positions_tensor.unsqueeze(1)  # Reshape from [2] to [2, 1] for batch_size = 2


        # Compute Q-values for current state-action pairs
        select_probs, move_probs = self.network(state_batch, selected_positions_tensor)
        if move_probs == None: # WE HAVE TO LOOK INTO THIS PROBLEM, SOMETHING IS HAPPENING AT END OF TRIANING
            print('Lenth of action_batch: ' + str(len(action_batch)))
            move_probs = select_probs
        if select_probs == None:
            
            print('Error?')
        # print(move_probs)
        q_values = select_probs.gather(1, torch.tensor(action_batch[0]).unsqueeze(1)) + move_probs.gather(1, torch.tensor(action_batch[1]).unsqueeze(1))
        
        
        """
            Please review this part of the code! I added a call to the network since we need to both select and move to perform an action so to speak. 
            I took inspiration from the select_and_move function defined earlier. Maybe we could even utilize it here?
        """
        
        
        # Compute max Q-values for next states
        next_select_probs, _ = self.network(next_state_batch)
        # Mask invalid selections (e.g., tiles without units)
        # select_probs = select_probs * get_valid_moves_mask(next_state_batch)
        
        # Normalize again after masking
        select_probs = select_probs / select_probs.sum()

        # Sample selected position
        selected_pos = torch.multinomial(select_probs, 1)
        
        
        _, next_move_probs = self.network(next_state_batch,selected_pos)
        if next_move_probs == None:# WE HAVE TO LOOK INTO THIS PROBLEM, SOMETHING IS HAPPENING AT END OF TRIANING
            print('Next Move Probs is None when computing Q-vals for NEXT state')
            next_move_probs = next_select_probs
        next_q_values = next_select_probs.max(1)[0] + next_move_probs.max(1)[0]
        expected_q_values = reward_batch + self.gamma * next_q_values * (1 - done_batch)

        # Compute the loss
        loss = self.criterion(q_values, expected_q_values.unsqueeze(1))
        return loss

    def optimize(self, batch_size):
        loss = self.compute_loss(batch_size)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

def train_agents(env, agents, num_episodes=64, batch_size=32, debug=False):
    """
    Train multiple agents with proper state tracking and win counting.
    With added debug prints to diagnose issues.
    
    Args:
        env: The game environment
        agents: List of DQNAgent instances
        num_episodes: Number of training episodes
        batch_size: Batch size for optimization
        debug: Whether to display debug information
    """
    # Initialize win counters for each agent
    win_counts = {i: 0 for i in range(len(agents))}
    win_history = []  # Track winners by episode
    
    for episode in range(num_episodes):
        print(f"Starting episode {episode}")
        # Use the reset method of the environment
        env.reset()
        raw_env_state = env  # The reset method returns the environment itself
        done = False
        
        # Get initial state tensor from the current player's agent
        current_player_index = env.current_player.player_index
        current_agent = agents[current_player_index]
        
        next_state = current_agent.build_state_tensor(raw_env_state)
        
        # Initialize a dict to track each agent's last observed state
        last_state_by_agent = {i: next_state for i in range(len(agents))}
        last_action_by_agent = {i: None for i in range(len(agents))}
        
        step_counter = 0  # To track how many turns have passed
        
        while not done:
            step_counter += 1
            if step_counter > 10000:  # Safety check to prevent infinite loops
                print("WARNING: Step limit exceeded, breaking loop")
                break
                
            current_player_index = env.current_player.player_index
            current_agent = agents[current_player_index]
                       
            # Get current state from the environment
            state = next_state
            
            # Update this agent's last observed state
            last_state_by_agent[current_player_index] = state
            
            # Get valid selection mask to see what can be selected
            valid_select_mask = get_valid_select_mask(state)
            valid_positions = torch.where(valid_select_mask > 0)[0].tolist()
            # print(f"Valid selection positions: {valid_positions}")
            
            # Select an action
            action = current_agent.select_action(state, epsilon=0.3)  # Increase exploration
            last_action_by_agent[current_player_index] = action
            
            # print(f"Agent selected action: select={action[0]}, move={action[1]}")
            
            # Convert the action indices to coordinates for the environment
            action_matrix = [
                np.array([action[0] // env.m, action[0] % env.m]), 
                np.array([action[1] // env.m, action[1] % env.m])
            ]
            
            # print(f"Converted to coordinates: select={action_matrix[0]}, move={action_matrix[1]}")
            
            # Check if action[0] is the end turn action (n*m index)
            if action[0] == env.n * env.m:
                # print("END TURN ACTION SELECTED")
                # End turn action
                env.current_player.end_turn()
                env.next_turn()
                raw_next_env_state = env
                reward = 0  # No immediate reward for ending turn
                done = env.done  # Check if game is done after turn
            else:
                # Take the action in the environment
                try:
                    # print(f"Executing step with action_matrix: {action_matrix}")
                    raw_next_env_state, reward, done = env.step(action_matrix)
                    # print(f"Step result: reward={reward}, done={done}")
                except AttributeError as e:
                    print(f"AttributeError during step: {e}")
                    # If step method doesn't exist or is incompatible, implement fallback
                    reward = 0
                    
                    # Try to find a unit at the selected position
                    select_row, select_col = action_matrix[0]
                    order_row, order_col = action_matrix[1]
                    
                    # Make sure coordinates are within bounds
                    select_row = select_row % env.n
                    select_col = select_col % env.m
                    order_row = order_row % env.n
                    order_col = order_col % env.m
                    
                    select_pos = (select_row, select_col)
                    order_pos = (order_row, order_col)
                    
                    print(f"Using fallback with select_pos={select_pos}, order_pos={order_pos}")
                    
                    # Get units at the selected position
                    units_at_pos = env.get_units_at(select_pos)
                    
                    # Check if there's a unit belonging to the current player
                    current_player_units = [u for u in units_at_pos if u.player == env.current_player]
                    
                    if current_player_units:
                        # Use the first unit found
                        unit = current_player_units[0]
                        print(f"Found unit: {unit.unit_type} with {unit.movement_points} MP")
                        
                        # If order is the same as selection, fortify
                        if select_pos == order_pos:
                            print(f"Fortifying unit at {select_pos}")
                            unit.fortify()
                        else:
                            # If there's a unit at the order position, try to attack
                            enemy_units = env.get_units_at(order_pos)
                            enemy_units = [u for u in enemy_units if u.player != env.current_player]
                            
                            if enemy_units:
                                # Attack the first enemy unit
                                target = enemy_units[0]
                                print(f"Attacking enemy {target.unit_type} at {order_pos}")
                                damage_dealt, damage_received, target_killed, attacker_killed = unit.attack(target, env)
                                print(f"Attack result: damage_dealt={damage_dealt}, target_killed={target_killed}")
                                
                                if target_killed:
                                    reward += 10  # Reward for killing enemy
                                    
                                if attacker_killed:
                                    reward -= 5  # Penalty for losing unit
                            else:
                                # Try to move
                                print(f"Moving unit from {select_pos} to {order_pos}")
                                moved, final_pos = unit.move(order_pos, env)
                                print(f"Move result: moved={moved}, final_pos={final_pos}")
                                
                                # Check if we captured a city
                                city_at_pos = None
                                for p in env.players:
                                    for c in p.cities:
                                        if c.coordinates == final_pos and p != env.current_player:
                                            city_at_pos = c
                                            break
                                
                                if city_at_pos:
                                    # Capture city
                                    print(f"Captured enemy city at {final_pos}")
                                    city_at_pos.set_owner(env.current_player)
                                    reward += 20  # Reward for capturing city
                    else:
                        print(f"No unit found at selected position {select_pos}")
                    
                    # Go to next player if all units have moved
                    all_units_moved = all(u.movement_points == 0 for u in env.current_player.units)
                    if all_units_moved:
                        print("All units have moved, advancing to next player")
                        env.next_turn()
                    
                    raw_next_env_state = env
                    done = env.done
            
            # Convert raw environment state to tensor for the current agent
            next_state = current_agent.build_state_tensor(raw_next_env_state)
            
            # If it's still this agent's turn, store the transition directly
            if env.current_player.player_index == current_player_index:
                current_agent.store_transition(state, action, reward, next_state, done)
            else:
                # Otherwise, store a pending transition
                current_agent.store_pending_transition(state, action, reward)
            
            # If we're now at a different player's turn, check if that player has pending transitions
            if env.current_player.player_index != current_player_index:
                next_player_index = env.current_player.player_index
                next_player_agent = agents[next_player_index]
                
                # Get the state tensor from the next player's perspective
                next_state = next_player_agent.build_state_tensor(raw_next_env_state)
                
                # Complete any pending transitions for the next player
                if next_player_agent.pending_transitions:
                    next_player_agent.complete_pending_transition(next_state, done)
            
            # Display the map if in debug mode
            if debug:
                display_map(env, debug=True)
            
            # Optimize if enough samples
            if len(current_agent.memory) > batch_size:
                current_agent.optimize(batch_size)
        
        # When episode is done, resolve any remaining pending transitions
        for agent in agents:
            while agent.pending_transitions:
                # For pending transitions at end of game, use last state with done=True
                agent.complete_pending_transition(agent.pending_transitions[0][0], True)
        
        # Determine the winner and update win counts
        winner = determine_winner(env)
        if winner is not None:
            win_counts[winner] += 1
            win_history.append(winner)
        else:
            # If no clear winner (e.g., turn limit reached), record as -1
            win_history.append(-1)
        
        # Print episode summary
        print(f"Episode {episode} completed. Winner: {'None' if winner is None else f'Player {winner+1}'}")
        print(f"Win counts so far: {', '.join([f'Player {i+1}: {count}' for i, count in win_counts.items()])}")
        
        # Save model weights
        for i, agent in enumerate(agents):
            # Create weights directory if it doesn't exist
            if not os.path.exists('weights'):
                os.makedirs('weights')
                
            save_path = f'weights/agent_{i}_episode_{episode}.pth'
            torch.save({
                'model_state_dict': agent.network.state_dict(),
                'optimizer_state_dict': agent.optimizer.state_dict(),
            }, save_path)
    
    # Save win history to file
    save_win_history(win_history, num_episodes)
    
    # Return win statistics
    return win_counts, win_history


def determine_winner(env):
    """
    Determine the winner of the game based on the environment state.
    
    Args:
        env: The game environment
        
    Returns:
        int: Index of the winning player, or None if no clear winner
    """
    # Check if there's only one player alive
    alive_players = [i for i, player in enumerate(env.players) if not player.is_dead]
    
    if len(alive_players) == 1:
        # Only one player is alive, they're the winner
        return alive_players[0]
    
    # If we reached turn limit, determine winner by most cities + units
    if env.done and env.turn_counter >= env.max_turns:
        # Calculate scores (here we use cities*10 + units as a simple metric)
        scores = []
        for player in env.players:
            if player.is_dead:
                scores.append(-1)  # Dead players get negative score
            else:
                # Cities are worth more than units
                score = len(player.cities) * 10 + len(player.units)
                scores.append(score)
        
        max_score = max(scores)
        if scores.count(max_score) == 1:  # Ensure there's no tie
            return scores.index(max_score)
    
    # No clear winner yet or there's a tie
    return None

def save_win_history(win_history, num_episodes):
    """
    Save the win history to a file for later analysis.
    
    Args:
        win_history: List recording the winner of each episode
        num_episodes: Total number of episodes
    """
    import os
    import time
    import numpy as np
    import matplotlib.pyplot as plt
    
    # Create directory if it doesn't exist
    if not os.path.exists('stats'):
        os.makedirs('stats')
    
    # Save raw data
    timestamp = int(time.time())
    np.save(f'stats/win_history_{timestamp}.npy', np.array(win_history))
    
    # Generate a rolling win rate plot (window of 10 episodes)
    if len(win_history) >= 10:
        plt.figure(figsize=(10, 6))
        
        # Get unique player indices excluding -1 (no winner)
        players = sorted(list(set([w for w in win_history if w >= 0])))
        
        for player in players:
            # Calculate rolling win rate for this player
            rolling_wins = []
            window_size = 10
            
            for i in range(len(win_history) - window_size + 1):
                window = win_history[i:i+window_size]
                win_rate = window.count(player) / window_size
                rolling_wins.append(win_rate)
            
            # Plot this player's rolling win rate
            plt.plot(range(window_size-1, len(win_history)), rolling_wins, 
                     label=f'Player {player+1}')
        
        plt.title('Rolling Win Rate (Window: 10 Episodes)')
        plt.xlabel('Episode')
        plt.ylabel('Win Rate')
        plt.legend()
        plt.grid(True)
        plt.savefig(f'stats/win_rate_plot_{timestamp}.png')
    
    print(f"Win history and analytics saved to stats/ directory")

def main(resume_training=False, checkpoint_episode=None):
    """
    Main training function that handles new training or resuming from a checkpoint.
    
    Args:
        resume_training (bool): Whether to resume from previous training
        checkpoint_episode (int): Episode number to resume from (if None, uses latest)
    """
    # Environment and agent setup
    n, m = 4, 8
    number_of_players = 2
    d = 2 * number_of_players + 1
    env = pyCiv.GameEnvironment(n, m, number_of_players)
    
    # Create memory for each agent
    memories = [ReplayMemory(10000) for _ in range(number_of_players)]
    
    # Create agents with different learning rates
    agents = [
        DQNAgent(n, m, d, memories[0], learning_rate=0.004),
        DQNAgent(n, m, d, memories[1], learning_rate=0.002),
    ]
    
    # Add a third agent if we have 3 players
    if number_of_players > 2:
        memories.append(ReplayMemory(10000))
        agents.append(DQNAgent(n, m, d, memories[2], learning_rate=0.0001))
    
    # Load checkpoints if resuming training
    if resume_training:
        # Determine checkpoint paths
        if checkpoint_episode is not None:
            checkpoint_paths = [f'weights/agent_{i}_episode_{checkpoint_episode}.pth' 
                              for i in range(number_of_players)]
        else:
            # Find latest episode checkpoint
            import os
            import re
            weight_files = os.listdir('weights') if os.path.exists('weights') else []
            episodes = []
            for file in weight_files:
                match = re.match(r'agent_0_episode_(\d+)\.pth', file)
                if match:
                    episodes.append(int(match.group(1)))
            
            if episodes:
                latest_episode = max(episodes)
                print(f"Found latest checkpoint at episode {latest_episode}")
                checkpoint_paths = [f'weights/agent_{i}_episode_{latest_episode}.pth'
                                 for i in range(number_of_players)]
            else:
                print("No checkpoints found. Starting with fresh weights.")
                resume_training = False
        
        # Load checkpoints
        if resume_training:
            for i, agent in enumerate(agents):
                try:
                    checkpoint = torch.load(checkpoint_paths[i])
                    agent.network.load_state_dict(checkpoint['model_state_dict'])
                    agent.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                    print(f"Successfully loaded checkpoint for Agent {i}")
                except Exception as e:
                    print(f"Failed to load checkpoint for Agent {i}: {e}")
                    print("Starting with fresh weights for this agent.")
    
    # Train agents
    win_counts, win_history = train_agents(env, agents, num_episodes=64, batch_size=32, debug=True)
    
    # Print final results
    print("\nTraining complete!")
    print("Final win counts:")
    for i, count in win_counts.items():
        print(f"Player {i+1}: {count} wins")
    
    return win_counts, win_history




if __name__ == "__main__":
    import argparse
    main(resume_training=True)
    # # Parse command line arguments
    # parser = argparse.ArgumentParser(description='Train agents for Civilization-like game')
    # parser.add_argument('--resume', action='store_true', help='Resume training from checkpoint')
    # parser.add_argument('--episode', type=int, help='Specific episode checkpoint to load')
    # args = parser.parse_args()
    
    # # Run main function with parsed arguments
    # main(resume_training=args.resume, checkpoint_episode=args.episode)


