"""
Things to think about:
    The selecting and then moving choices multiply in a combinatorial way, we need to adress this at some point.
    The current version is cheating but solves the problem for now (it's not testing all possabilities in the max(Q) - step)
"""
import pyCiv
import torch
import torch.nn as nn
import torch.nn.functional as F
import random
from collections import namedtuple
import numpy as np
import os
import matplotlib.pyplot as plt # For replayes, get this into its own script.
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

# def get_valid_select_mask(state):
#     """
#     Generate a mask indicating valid selections based on the game state.
#     Only units with movement points left are considered valid for selection.
#     """
#     # Extract the layer representing movement points of friendly units
#     movement_points_layer = state[-1, :, :]  # Shape: [n, m]
    
#     # Generate a mask where positions with movement points > 0 are marked as 1, else 0
#     valid_select_mask = (movement_points_layer > 0).float()  # Convert boolean mask to float
    
     
#     # Flatten the mask to match the shape [n*m], corresponding to flattened select_probs
#     return valid_select_mask.flatten().to(state.device)


def get_valid_moves_mask(state_batch):
    # Assuming the presence of entities is indicated in specific channels:
    # Example: Summing across specific channels to find where entities are present
    presence_mask = state_batch[:, entity_channels, :, :].sum(dim=1) > 0
    # Flatten the presence data to match the shape [batch_size, n*m]
    valid_moves_mask = presence_mask.view(state_batch.shape[0], -1).float()
    return valid_moves_mask

def get_valid_select_mask(state_batch):
    # Similar logic as get_valid_moves_mask
    select_mask = state_batch[:, entity_channels, :, :].sum(dim=1) > 0
    valid_select_mask = select_mask.view(state_batch.shape[0], -1).float()
    return valid_select_mask

def adjust_mask_for_end_turn(original_mask):
    # Assuming original_mask has shape [batch_size, num_options]
    # We need to add a tensor of shape [batch_size, 1] to match the dimensions
    end_turn_action = torch.tensor([1.0], device=original_mask.device).expand(original_mask.size(0), 1)
    end_turn_mask = torch.cat([original_mask, end_turn_action], dim=1)
    return end_turn_mask


def select_and_move(network, game_state):
    # Ensure game_state has a batch dimension
    if game_state.dim() == 3:
        game_state = game_state.unsqueeze(0)  # Add a batch dimension

    select_probs, _ = network(game_state)  # Now game_state is [1, channels, height, width] if it was a single state
    select_mask = get_valid_select_mask(game_state_batch)
    select_probs *= select_mask
    select_probs /= select_probs.sum(dim=1, keepdim=True)  # Normalize across actions

    selected_positions = torch.multinomial(select_probs, 1, replacement=True)
    _, move_probs = network(game_state_batch, selected_positions)
    move_mask = get_valid_moves_mask(game_state_batch)
    move_probs *= move_mask
    move_probs /= move_probs.sum(dim=1, keepdim=True)

    move_positions = torch.multinomial(move_probs, 1, replacement=True)
    return selected_positions, move_positions



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

    def select_action(self, state, epsilon=0.1, eval_mode=False):
        if eval_mode:
            epsilon = 0  # Set epsilon to 0 in eval mode to disable exploration
        if random.uniform(0, 1) < epsilon: # Exploration
            # Randomly select and move
            return (random.choice(range(self.n * self.m)), random.choice(range(self.n * self.m)))
        else: # Exploitation
            selected_pos, move_pos = select_and_move(self.network, state)
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
        select_probs = select_probs * get_valid_select_mask(next_state_batch)
        
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

# for replays

def load_weights_for_evaluation(weights_path, agent):
    if os.path.exists(weights_path):
        checkpoint = torch.load(weights_path)
        agent.network.load_state_dict(checkpoint['model_state_dict'])
        print(f"Loaded weights from {weights_path} for evaluation.")
    else:
        print("Weights file not found, please check the path.")
        return False  # Indicate failure to load weights
    return True  # Indicate successful loading of weights

def evaluate_agent(env, agent, num_games):
    results = []
    for _ in range(num_games):
        state = env.reset(2)
        game_states = [state]  # List to store states for visualization
        actions_taken = []  # List to store actions for visualization
        done = False
        while not done:
            action = agent.select_action(state, eval_mode=True)  # Ensure select_action supports eval_mode
            actions_taken.append(action)
            action_matrix = [np.array([action[0] // m, action[0] % n]), np.array([action[0] // m, action[1] % n])]
            state, reward, done = env.step(action_matrix)
            game_states.append(state)
        results.append((game_states, actions_taken))  # Store games' states and actions
    return results



def plot_game(game_states, actions_taken):
    fig, ax = plt.subplots()
    for i, state in enumerate(game_states):
        ax.clear()
        ax.imshow(state.squeeze(0), cmap='hot')  # Assuming state is a PyTorch tensor
        ax.set_title(f"Action: {actions_taken[i]}")
        plt.pause(0.1)  # Pause a bit for each frame
    plt.show()


""" TRAINING LOOP """

# env = YourGameEnvironmentHere()
n, m = 5, 6
d = 5 #
number_of_players = 2
# env = MockEnvironment(n, m, d)
env = pyCiv.GameEnvironment(n, m, number_of_players)
# reset?
agent = DQNAgent(n, m, d, ReplayMemory(10000)) # example capacity
weights_path = os.getcwd()+ '\\weights\\model_episode_199.pth'

if os.path.exists(weights_path):
    checkpoint = torch.load(weights_path)
    agent.network.load_state_dict(checkpoint['model_state_dict'])
    agent.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
    print("Loaded model and optimizer from:", weights_path)
else:
    print("No saved weights found, initializing with random weights.")


NUM_EPISODES = 1
BATCH_SIZE = 32

for episode in range(NUM_EPISODES):
    print(f"Starting episode {episode}")
    next_state = env.reset(2)
    done = False
    while not done: # We need 2 variables, one for end turn and one for end game. - in order to introduce more agents to the mix.
        state = next_state
        action = agent.select_action(state)
        action_matrix = [np.array([action[0] // m, action[0] % n]), np.array([action[0] // m, action[1] % n])]
        next_state, reward, done = env.step(action_matrix)
        agent.store_transition(state, action, reward, next_state, done)
    
   
        if len(agent.memory) > BATCH_SIZE:
            agent.optimize(BATCH_SIZE)
            # Save the model weights after each episode
            if not os.path.exists('weights'):  # Check if the directory exists
                os.makedirs('weights')  # Create the directory if it does not exist
            current_dir = os.getcwd()
            save_path = os.path.join(current_dir, f'weights/model_episode_{episode}.pth')
            # torch.save(agent.network.state_dict(), save_path)
            torch.save({'model_state_dict': agent.network.state_dict(),
                        'optimizer_state_dict': agent.optimizer.state_dict(),
                        }, save_path)

