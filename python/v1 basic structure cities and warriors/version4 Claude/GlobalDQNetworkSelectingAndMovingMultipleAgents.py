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

class SelectAndMoveNetwork(nn.Module):
    def __init__(self, n, m, d):
        super(SelectAndMoveNetwork, self).__init__()

        # Convolutional layers for unit selection
        self.conv1_select = nn.Conv2d(d, 16, kernel_size=3, stride=1, padding=1)
        self.bn1_select = nn.BatchNorm2d(16)
        self.conv2_select = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1)
        self.bn2_select = nn.BatchNorm2d(32)

        # Convolutional layers for movement decision
        self.conv1_move = nn.Conv2d(d, 16, kernel_size=3, stride=1, padding=1)
        self.bn1_move = nn.BatchNorm2d(16)
        self.conv2_move = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1)
        self.bn2_move = nn.BatchNorm2d(32)

        # Fully connected layers for unit selection and movement decision
        self.fc_select = nn.Linear(n * m * 32, n * m + 1)
        self.fc_move = nn.Linear(n * m * 32 + 1, n * m)  # +1 for the selected unit's position's index

    def forward(self, state, selected_pos=None):
        # Forward pass through selection convolutional layers
        x_select = F.relu(self.bn1_select(self.conv1_select(state)))
        x_select = F.relu(self.bn2_select(self.conv2_select(x_select)))
        x_select = x_select.view(x_select.size(0), -1)  # flatten
        select_probs = F.softmax(self.fc_select(x_select), dim=1)

        if selected_pos is not None:
            # Forward pass through movement convolutional layers
            x_move = F.relu(self.bn1_move(self.conv1_move(state)))
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
    # Extract the layer representing movement points of friendly units
    movement_points_layer = state[2, :, :]  # Shape: [n, m]
    
    # Generate a mask where positions with movement points > 0 are marked as 1, else 0
    valid_select_mask = (movement_points_layer > 0.01).float()  # Convert boolean mask to float
    
     
    # Flatten the mask to match the shape [n*m], corresponding to flattened select_probs
    return valid_select_mask.flatten().to(state.device)

def adjust_mask_for_end_turn(original_mask):
    # Add a `1` at the end of the original mask to account for the "end turn" action
    end_turn_mask = torch.cat([original_mask, torch.tensor([1.0]).to(original_mask.device)])
    return end_turn_mask

def get_valid_moves_mask(state, selected_pos):
    
    # The state has shape [d, n, m],
    # Create a mask of shape [n*m], which corresponds to the flattened shape of select_probs
    valid_move_mask = (state[1, :, :] <= 0).float()
    valid_move_mask = valid_move_mask.view(-1)  # Flatten the mask
    # Ensure the selected position is within valid range
    # Get the size of the flattened mask
    max_pos = valid_move_mask.size(0)
   
    # Ensure the selected position is within valid range
    if selected_pos >= 0 and selected_pos < max_pos:
        valid_move_mask[selected_pos] = 1.0  # Ensure the selected position is always valid
    else:
        if selected_pos == max_pos:  # This is now a more generalized check
            return valid_move_mask.to(state.device)  # Return the adjusted mask
        else:
            print("Warning: Selected position is out of valid range!")
    return valid_move_mask.to(state.device)  # Return the adjusted mask
    

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
        
        Args:
            game_env: The GameEnvironment instance
            
        Returns:
            torch.Tensor: State tensor representation
        """
        # Initialize a zero tensor with appropriate dimensions
        state_tensor = torch.zeros(self.d, self.n, self.m, device=self.device)
        
        # Get the current player
        current_player = game_env.current_player
        
        # Layer 0: Current player's cities
        for city in current_player.cities:
            i, j = city.coordinates
            state_tensor[0, i, j] = 100  # Assuming 100 is the "worth" of a city
        
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
        if random.uniform(0, 1) < epsilon:  # Exploration
            # Generate valid selection mask
            original_mask = get_valid_select_mask(state)
            adjusted_mask = adjust_mask_for_end_turn(original_mask)
            valid_positions = torch.where(adjusted_mask > 0)[0].tolist()  # Get valid positions
            
            if len(valid_positions) > 0:
                # Randomly select a valid position
                selected_pos = random.choice(valid_positions)
            else:
                selected_pos = random.choice(range(self.n * self.m))  # Fallback to random choice if no valid positions found
                print('No Valid Selection Found!')
            
            # Assuming you want to select a random move to a valid position (based on valid_moves_mask)
            valid_moves_mask = get_valid_moves_mask(state, selected_pos)
            valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
            
            if len(valid_moves) > 0:
                move_pos = random.choice(valid_moves)
            else:
                move_pos = random.choice(range(self.n * self.m))  # Fallback to random choice if no valid moves found
            
            return (selected_pos, move_pos)
        else:  # Exploitation
            selected_pos, move_pos = select_and_move(state, self.network)
            return (selected_pos.item(), move_pos.item())


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
        raw_env_state = env.reset()
        done = False
        
        # Get initial state tensor from the current player's agent
        current_player_index = env.current_player.player_index
        current_agent = agents[current_player_index]
        next_state = current_agent.build_state_tensor(raw_env_state)
        
        # Initialize a dict to track each agent's last observed state
        last_state_by_agent = {i: next_state for i in range(len(agents))}
        last_action_by_agent = {i: None for i in range(len(agents))}
        
        while not done:
            current_player_index = env.current_player.player_index
            current_agent = agents[current_player_index]
            
            # Get current state from the environment
            state = next_state
            
            # Update this agent's last observed state
            last_state_by_agent[current_player_index] = state
            
            # Select an action
            action = current_agent.select_action(state)
            last_action_by_agent[current_player_index] = action
            action_matrix = [np.array([action[0] // env.m, action[0] % env.m]), 
                             np.array([action[1] // env.m, action[1] % env.m])]
            
            # Take the action in the environment
            raw_next_env_state, reward, done = env.step(action_matrix)
            
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
    n, m = 10, 8
    number_of_players = 3
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


# class MockEnvironment:
#     def __init__(self, n, m, d):
#         self.n = n
#         self.m = m
#         self.d = d
#         self.state = None

#     def reset(self):
#         #todo : recieve state from from server
#         #todo2: translate server state to matrix format.
#         self.state = torch.rand((self.d, self.n, self.m))  # Random state initialization
#         return self.state

#     def step(self, action):
#         # send action to server
#         # recieve reward-information inclding game over and next state
#         # Action could be any, for simplicity let's just move to a next random state
#         next_state = torch.rand((self.d, self.n, self.m))
        
#         # Simplified reward - random for demonstration
#         reward = np.random.rand()
        
#         # Randomly decide if the game is done
#         done = np.random.choice([True, False], p=[0.1, 0.9])
        
#         # For simplicity, no info dict is returned
#         return next_state, reward, done


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


