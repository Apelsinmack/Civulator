import torch
import torch.nn as nn

"""
We'll use three Conv2D layers followed by two fully connected layers. 
We'll use the ReLU activation function for all layers except the last one, 
which doesn't need an activation function because we want the raw Q-values.

Note: I'm assuming that your game state is an nm4 tensor, 
where n and m are the height and width of the game map respectively. 
You need to replace these with the actual dimensions of your game map. 
The number of actions is set to 10 as per your description.
"""

class DQN(nn.Module):
    def __init__(self, h, w, outputs):
        super(DQN, self).__init__()
        self.conv1 = nn.Conv2d(4, 16, kernel_size=5, stride=1, padding=2)
        self.bn1 = nn.BatchNorm2d(16)
        self.conv2 = nn.Conv2d(16, 32, kernel_size=5, stride=1, padding=2)
        self.bn2 = nn.BatchNorm2d(32)
        self.conv3 = nn.Conv2d(32, 32, kernel_size=5, stride=1, padding=2)
        self.bn3 = nn.BatchNorm2d(32)

        def conv2d_size_out(size, kernel_size = 5, stride = 1, padding = 2):
            return (size - kernel_size + 2*padding) // stride  + 1

        convw = conv2d_size_out(conv2d_size_out(conv2d_size_out(w)))
        convh = conv2d_size_out(conv2d_size_out(conv2d_size_out(h)))
        linear_input_size = convw * convh * 32
        self.head = nn.Linear(linear_input_size, outputs)

    def forward(self, x):
        x = nn.functional.relu(self.bn1(self.conv1(x)))
        x = nn.functional.relu(self.bn2(self.conv2(x)))
        x = nn.functional.relu(self.bn3(self.conv3(x)))
        return self.head(x.view(x.size(0), -1))

"""
Next, let's define the Replay Memory. 
We'll use a Python deque which is a type of list where adding 
an element to a full deque automatically removes an element from the opposite end.
"""
import random
from collections import namedtuple, deque

# A single transition in our environment
Transition = namedtuple('Transition', ('state', 'action', 'next_state', 'reward'))

class ReplayMemory(object):
    def __init__(self, capacity):
        self.memory = deque([], maxlen=capacity)

    def push(self, *args):
        """Save a transition"""
        self.memory.append(Transition(*args))

    def sample(self, batch_size):
        return random.sample(self.memory, batch_size)

    def __len__(self):
        return len(self.memory)


"""
Lastly, let's define the DQN Agent. This is a complex class, 
and we might have to revise it as we try to integrate with your game.
For now, let's keep it simple. We'll initialize our agent with 
an instance of the DQN network and Replay Memory. The select_action method 
will implement the epsilon-greedy policy. The step method will add the 
experience to the memory and decide when to trigger learning. 
The learn method will sample a batch of experiences from the memory
and use them to update the DQN network. This learning process involves 
computing the current Q-value estimates, computing the target Q-values, 
and then updating the DQN network weights using backpropagation to 
minimize the difference between the current and target Q-values. 
The update_target_network method is used to synchronize the weights 
of the target network with the primary network every few steps.
"""
class DQNAgent():
    def __init__(self, state_size, action_size, device, learning_rate=1e-3, batch_size=64, gamma=0.99, start_epsilon=1, end_epsilon=0.01, epsilon_decay=0.995, target_update=10, memory_size=10000):
        self.state_size = state_size
        self.action_size = action_size
        self.device = device

        self.batch_size = batch_size
        self.gamma = gamma
        self.target_update = target_update

        self.primary_network = DQN(state_size[0], state_size[1], action_size).to(device)
        self.target_network = DQN(state_size[0], state_size[1], action_size).to(device)
        self.target_network.load_state_dict(self.primary_network.state_dict())
        self.target_network.eval()  # Set the target network to evaluation mode

        self.memory = ReplayMemory(memory_size)

        self.optimizer = torch.optim.Adam(self.primary_network.parameters(), lr=learning_rate)

        self.steps_done = 0
        self.epsilon = start_epsilon
        self.end_epsilon = end_epsilon
        self.epsilon_decay = epsilon_decay

    def select_action(self, state):
        sample = random.random()
        self.steps_done += 1
        self.epsilon = max(self.end_epsilon, self.epsilon * self.epsilon_decay)
        if sample > self.epsilon:
            with torch.no_grad():
                return self.primary_network(state).max(1)[1].view(1, 1)
        else:
            return torch.tensor([[random.randrange(self.action_size)]], device=self.device, dtype=torch.long)

    def step(self, state, action, next_state, reward, done):
        self.memory.push(state, action, next_state, reward)
        if len(self.memory) > self.batch_size:
            self.learn()

        if done:
            self.steps_done = 0
            self.target_network.load_state_dict(self.primary_network.state_dict())

    def learn(self):
        if len(self.memory) < self.batch_size:
            return

        transitions = self.memory.sample(self.batch_size)
        batch = Transition(*zip(*transitions))

        state_batch = torch.cat(batch.state)
        action_batch = torch.cat(batch.action)
        reward_batch = torch.cat(batch.reward)

        non_final_next_states = torch.cat([s for s in batch.next_state if s is not None])
        non_final_mask = torch.tensor(tuple(map(lambda s: s is not None, batch.next_state)), device=self.device, dtype=torch.bool)

        current_q_values = self.primary_network(state_batch).gather(1, action_batch)
        next_q_values = torch.zeros(self.batch_size, device=self.device)
        next_q_values[non_final_mask] = self.target_network(non_final_next_states).max(1)[0].detach()
        target_q_values = (next_q_values * self.gamma) + reward_batch

        loss = nn.functional.smooth_l1_loss(current_q_values, target_q_values.unsqueeze(1))

        self.optimizer.zero_grad()
        loss.backward()
        for param in self.primary_network.parameters():
            param.grad.data.clamp_(-1, 1)
        self.optimizer.step()




