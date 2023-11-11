import torch
import torch.nn as nn
import torch.nn.functional as F
import random


# Behöver göra mask-function
# Behöver göra end turn logik, ta hjälp av mask function.
# Behöver göra game environment : här ska logiken bakom skicka och ta emot finnas.
# Game environment måste också ge spelplanens storlek osv.

GAMMA = 0.99  # You can adjust this value based on your specific RL problem


class SelectAndMoveNetwork(nn.Module):
    def __init__(self, n, m, d):
        super(SelectAndMoveNetwork, self).__init__()

        # Convolutional layers for feature extraction
        self.conv1 = nn.Conv2d(d, 16, kernel_size=3, stride=1, padding=1)
        self.bn1 = nn.BatchNorm2d(16)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=3, stride=1, padding=1)
        self.bn2 = nn.BatchNorm2d(32)

        # Fully connected layers for unit selection and movement decision
        self.fc_select = nn.Linear(n * m * 32, n * m)
        self.fc_move = nn.Linear(n * m * 32 + 2, n * m)  # +2 for the selected unit's position

    def forward(self, state, selected_pos=None):
        x = F.relu(self.bn1(self.conv1(state)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = x.view(x.size(0), -1)  # flatten

        # Unit selection
        select_probs = F.softmax(self.fc_select(x), dim=1)
        
        # If a position has been selected, determine where to move it
        if selected_pos is not None:
            x = torch.cat([x, selected_pos], dim=1)  # append selected position to feature vector
            move_probs = F.softmax(self.fc_move(x), dim=1)
            return select_probs, move_probs
        
        return select_probs, None

def get_valid_moves_mask(state):
    """
    Generate a mask indicating valid moves based on the game state.
    For simplicity, this function just returns a tensor of ones, but you should modify it 
    based on your game's rules.
    """
    return torch.ones(state.shape[0], state.shape[1])

def select_and_move(game_state):
    network = SelectAndMoveNetwork(game_state.shape[0], game_state.shape[1], game_state.shape[2])
    
    # Get unit selection probabilities
    select_probs, _ = network(game_state.unsqueeze(0))
    
    # Mask invalid selections (e.g., tiles without units)
    select_probs = select_probs * get_valid_moves_mask(game_state)
    
    # Normalize again after masking
    select_probs = select_probs / select_probs.sum()

    # Sample selected position
    selected_pos = torch.multinomial(select_probs, 1)
    
    # Now get movement probabilities for the selected unit
    _, move_probs = network(game_state.unsqueeze(0), selected_pos)
    
    # Mask invalid moves (e.g., tiles not adjacent to the selected unit)
    move_probs = move_probs * get_valid_moves_mask(game_state)
    
    # Normalize again after masking
    move_probs = move_probs / move_probs.sum()
    
    # Sample move position
    move_pos = torch.multinomial(move_probs, 1)
    
    return selected_pos, move_pos


# I don't think this function is used atm. :-/
#def select_action(state, net, epsilon=0.1):
#    if random.random() < epsilon:
#        return random.randint(0, action_space_size - 1)  # replace action_space_size with the correct value
#    else:
#        with torch.no_grad():
#            return net(state).argmax().item()

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

class Transition:
    def __init__(self, state, action, reward, next_state, done):
        self.state = state
        self.action = action
        self.reward = reward
        self.next_state = next_state
        self.done = done

class DQNAgent:
    def __init__(self, n, m, d, memory):
        self.network = SelectAndMoveNetwork(n, m, d)
        self.memory = memory
        self.optimizer = torch.optim.Adam(self.network.parameters())
        self.criterion = nn.MSELoss()

    def select_action(self, state, epsilon=0.1):
        if random.uniform(0, 1) < epsilon: # Exploration
            # Randomly select and move
            return (random.choice(range(self.n * self.m)), random.choice(range(self.n * self.m)))
        else: # Exploitation
            selected_pos, move_pos = select_and_move(state)
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
        done_batch = torch.tensor(batch.done)

        # Compute Q-values for current state-action pairs
        select_probs, move_probs = self.network(state_batch)
        q_values = select_probs.gather(1, torch.tensor(action_batch[0]).unsqueeze(1)) + move_probs.gather(1, torch.tensor(action_batch[1]).unsqueeze(1))

        # Compute max Q-values for next states
        next_select_probs, next_move_probs = self.network(next_state_batch)
        next_q_values = next_select_probs.max(1)[0] + next_move_probs.max(1)[0]
        expected_q_values = reward_batch + GAMMA * next_q_values * (1 - done_batch)

        # Compute the loss
        loss = self.criterion(q_values, expected_q_values.unsqueeze(1))
        return loss

    def optimize(self, batch_size):
        loss = self.compute_loss(batch_size)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()


""" TRAINING LOOP """ # spelplan = base = 20, height = 10

env = YourGameEnvironmentHere()
agent = DQNAgent(n, m, d, ReplayMemory(10000)) # example capacity
NUM_EPISODES = 1000
BATCH_SIZE = 32

for episode in range(NUM_EPISODES):
    state = env.reset()
    done = False
    while not done:
        action = agent.select_action(state)
        next_state, reward, done, _ = env.step(action)
        agent.store_transition(state, action, reward, next_state, done)
        state = next_state

        if len(agent.memory) > BATCH_SIZE:
            agent.optimize(BATCH_SIZE)
