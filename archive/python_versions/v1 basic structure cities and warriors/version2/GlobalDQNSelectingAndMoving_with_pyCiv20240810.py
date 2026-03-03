"""
For Version2
"""
import pyCiv20240810
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

        # Convolutional layers for feature extraction
        self.conv1 = nn.Conv2d(d, 16, kernel_size=3, stride=1, padding=1)
        self.bn1 = nn.BatchNorm2d(16)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1)
        self.bn2 = nn.BatchNorm2d(32)

        # Fully connected layers for unit selection and movement decision
        self.fc_select = nn.Linear(n * m * 32, n * m + 1)
        self.fc_move = nn.Linear(n * m * 32 + 1, n * m)  # +1 for the selected unit's position's index -< this i don't understand!!!

    def forward(self, state, selected_pos=None):
        x = F.relu(self.bn1(self.conv1(state)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = x.view(x.size(0), -1)  # flatten

        # Unit selection
        select_probs = F.softmax(self.fc_select(x), dim=1)
        
        # If a position has been selected, determine where to move it
        if selected_pos is not None:
            
            selected_pos = selected_pos.float().view(-1, 1) 
            x = torch.cat([x, selected_pos], dim=1)  # append selected position to feature vector
            move_probs = F.softmax(self.fc_move(x), dim=1)
            # print("move_probs:", move_probs)  # Add this line to debug
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
    valid_select_mask = (movement_points_layer > 0.1).float()  # Convert boolean mask to float
    
     
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
    if selected_pos >= 0 and selected_pos < valid_move_mask.size(0):
        valid_move_mask[selected_pos] = 1.0  # Ensure the selected position is always valid
    else:
        if (selected_pos==30).all():
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
    def __init__(self, n, m, d, memory, gamma = 0.9):
        # We might want to rething having n, m and d as self variables here. These are the height, width of tha map, d is how many units are supported.
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")
        self.n = n
        self.m = m
        self.d = d
        self.gamma = gamma
        self.memory = memory
        self.network = SelectAndMoveNetwork(n, m, d).to(self.device)
        self.optimizer = torch.optim.Adam(self.network.parameters())
        self.criterion = nn.MSELoss()

    def select_action(self, state, epsilon=0.1):
        if random.uniform(0, 1) < epsilon:  # Exploration
            # Generate valid selection mask
            valid_select_mask = get_valid_select_mask(state)
            valid_positions = torch.where(valid_select_mask > 0)[0].tolist()  # Get valid positions
            
            if len(valid_positions) > 0:
                # Randomly select a valid position
                selected_pos = random.choice(valid_positions)
            else:
                selected_pos = random.choice(range(self.n * self.m))  # Fallback to random choice if no valid positions found
            
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



class MockEnvironment: # has a step function that returns a random new game state, reward and boolean done variable for any action.
    def __init__(self, n, m, d):
        self.n = n
        self.m = m
        self.d = d
        self.state = None

    def reset(self):
        #todo : recieve state from from server
        #todo2: translate server state to matrix format.
        self.state = torch.rand((self.d, self.n, self.m))  # Random state initialization
        return self.state

    def step(self, action):
        # send action to server
        # recieve reward-information inclding game over and next state
        # Action could be any, for simplicity let's just move to a next random state
        next_state = torch.rand((self.d, self.n, self.m))
        
        # Simplified reward - random for demonstration
        reward = np.random.rand()
        
        # Randomly decide if the game is done
        done = np.random.choice([True, False], p=[0.1, 0.9])
        
        # For simplicity, no info dict is returned
        return next_state, reward, done



""" TRAINING LOOP """
# GlobalDQNSelectingAndMoving_with_pyCiv20240810.py

if __name__ == "__main__":
    # Any code here will run only if this script is executed directly.
    # Example: Your training or gameplay loop
        
    
    # env = YourGameEnvironmentHere()
    n, m = 5, 6
    d = 5 #
    number_of_players = 2
    # env = MockEnvironment(n, m, d)
    env = pyCiv20240810.GameEnvironment(n, m, number_of_players)
    # reset?
    agent = DQNAgent(n, m, d, ReplayMemory(10000)) # example capacity
    NUM_EPISODES = 64 
    BATCH_SIZE = 32
    states = []
    for episode in range(NUM_EPISODES):
        print(f"Starting episode {episode}")
        next_state = env.reset()
        done = False
        while not done: # We need 2 variables, one for end turn and one for end game. - in order to introduce more agents to the mix.
    
            state = next_state
            action = agent.select_action(state)
            action_matrix = [np.array([action[0] // m, action[0] % m]), np.array([action[1] // m, action[1] % m])]
    
            states.append(state)
            next_state, reward, done = env.step(action_matrix)
            agent.store_transition(state, action, reward, next_state, done)
        
       
            if len(agent.memory) > BATCH_SIZE:
                agent.optimize(BATCH_SIZE)
                # Save the model weights after each episode
                if not os.path.exists('weights'):  # Check if the directory exists
                    os.makedirs('weights')  # Create the directory if it does not exist
                current_dir = os.getcwd()
                save_path = os.path.join(current_dir, f'weights/model_episode_{episode}.pth')
                torch.save(agent.network.state_dict(), save_path)        


#%%
# def evaluate_model(env, agent, num_games):
#     states = []
#     player_turn = []
#     episode_num = 0
#     for _ in range(num_games):
#         state = env.reset(2)
#         states.append(state)
#         player_turn.append(env.current_player.name)
#         done = False
#         step_num = 0
#         while not done:
#             action = agent.select_action(state, epsilon=0)  # Use greedy policy for evaluation
#             action_matrix = [np.array([action[0] // m, action[0] % n]), np.array([action[1] // m, action[1] % n])]
#             next_state, reward, done = env.step(action_matrix)
            
#             state = next_state
#             step_num +=1
#             states.append(state)
#             player_turn.append(env.current_player.name)
#             if env.turn_counter > 20:
#                 done = True
        
#         episode_num+=1
        
#     return states, player_turn


# # Assuming you have already defined agent and env somewhere in your script

# # Put the network in evaluation mode
# agent.network.eval()
# with torch.no_grad():
#     states, player_turn = evaluate_model(env, agent, num_games=3)  # Run 3 evaluation games

#%%

# import matplotlib.pyplot as plt

# def coords(i,j):
#     x = j - np.cos(np.pi/3) * i
#     y = j * np.sin(np.pi/3)
#     return x, y

# for k in range(40):
#     fig, ax = plt.subplots(1,1,figsize=(5,5), dpi=100)
#     state = states[k]
#     # player=player_turn[k]

#     for (i, j), value in np.ndenumerate(state[0]):
#         if value > 0:  # Assuming positive values indicate cities
#             x, y = coords(i,j)
#             ax.plot(x, y, '*', color='red', markersize=10)  # Plot cities as red stars
#     for (i, j), value in np.ndenumerate(state[1]):
#         if value > 0:
#             x,y = coords(i,j)
#             ax.plot(x, y, 'x', color='red', markersize=14)  
#     for (i, j), value in np.ndenumerate(state[3]):
#         if value < 0:
#             x, y = coords(i,j)
#             ax.plot(x, y, '*', color='blue', markersize=10)  # Plot cities as red stars
#     for (i, j), value in np.ndenumerate(state[4]):
#         if value < 0:
#             x, y = coords(i,j)
#             ax.plot(x, y, 'x', color='blue', markersize=14)  # Plot cities as red stars
        
    
#     ax.set_aspect('equal')
#     ax.set_ylim(0,5)
#     ax.set_xlim(0,6)
#     # ax.invert_yaxis()  # Invert the y-axis to get the origin at the top-left corner as in most map displays
#     plt.show()
#     plt.clf()
        