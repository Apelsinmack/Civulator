import torch
from torch import nn

"""

# Define the Convolutional Neural Network model
class QNetwork(nn.Module):
    def __init__(self, state_size, action_size, seed):
        super(QNetwork, self).__init__()
        self.seed = torch.manual_seed(seed)
        
        # The first CNN layer
        self.conv1 = nn.Conv2d(state_size, 32, kernel_size=5, stride=2)
        self.bn1 = nn.BatchNorm2d(32)
        self.relu1 = nn.ReLU()

        # The second CNN layer
        self.conv2 = nn.Conv2d(32, 64, kernel_size=5, stride=2)
        self.bn2 = nn.BatchNorm2d(64)
        self.relu2 = nn.ReLU()
        
        # A final fully connected layer to get Q values
        self.fc1 = nn.Linear(64 * (map_size//4) * (map_size//4), action_size)

    def forward(self, state):
        x = self.conv1(state)
        x = self.bn1(x)
        x = self.relu1(x)

        x = self.conv2(x)
        x = self.bn2(x)
        x = self.relu2(x)

        # Flatten the tensor
        x = x.view(x.size(0), -1)

        return self.fc1(x)


state_size = 2  # as each tile is represented by a 3-dimensional vector (HP of my warrior, HP of enemy warriors, and the terrain type)
action_size = 19  # as the unit can move in 8 directions

seed = 0 # for reproducibility

model = QNetwork(state_size, action_size, seed)

print('done')

"""