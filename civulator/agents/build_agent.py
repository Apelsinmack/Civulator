"""Build agent: decides what each city produces using a separate DQN."""

import random

import torch
import torch.nn as nn
import torch.nn.functional as F

from .networks import horizontal_wrap_padding
from .replay_memory import ReplayMemory, Transition
from ..game.unit import Unit
from ..game.city import City


# Build options — index in this list = action index
BUILD_OPTIONS = [
    "Warrior", "Spearman", "Archer", "Horseman", "Catapult",
    "Settler", "Granary",
]
NUM_BUILD_OPTIONS = len(BUILD_OPTIONS)

# Number of extra channels added to combat state for build decisions
# 6 turns-to-complete + current_production + progress + city_marker = 9
NUM_BUILD_CHANNELS = 9


class BuildNetwork(nn.Module):
    """Small CNN that outputs Q-values over build options.

    Input: combat state + build info channels + city marker = [batch, d, n, m]
    Output: [batch, NUM_BUILD_OPTIONS]
    """

    def __init__(self, n, m, d, kernel_size=3, conv_channels=(16, 32)):
        super().__init__()

        self.padding_size = kernel_size // 2
        padded_n = n + 2 * self.padding_size
        padded_m = m + 2 * self.padding_size

        c1, c2 = conv_channels

        self.conv1 = nn.Conv2d(d, c1, kernel_size=kernel_size, padding=0)
        self.bn1 = nn.BatchNorm2d(c1)
        self.conv2 = nn.Conv2d(c1, c2, kernel_size=kernel_size, padding=0)
        self.bn2 = nn.BatchNorm2d(c2)

        conv1_out_n = padded_n - kernel_size + 1
        conv1_out_m = padded_m - kernel_size + 1
        conv2_out_n = conv1_out_n - kernel_size + 1
        conv2_out_m = conv1_out_m - kernel_size + 1
        flattened = c2 * conv2_out_n * conv2_out_m

        self.fc = nn.Linear(flattened, NUM_BUILD_OPTIONS)

    def forward(self, state):
        padded = horizontal_wrap_padding(state, self.padding_size)
        x = F.relu(self.bn1(self.conv1(padded)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = x.view(x.size(0), -1)
        return self.fc(x)


def encode_build_state(combat_state, city, game_env):
    """Add build-info channels and city marker to the combat state tensor.

    Args:
        combat_state: [d, n, m] tensor from any StateEncoder
        city: City instance making the build decision
        game_env: GameEnvironment

    Returns:
        [d + 9, n, m] tensor
    """
    d, n, m = combat_state.shape
    device = combat_state.device

    extra = torch.zeros(NUM_BUILD_CHANNELS, n, m, device=device)

    ci, cj = city.coordinates
    prod_per_turn = max(1, city.calculate_production(game_env))
    max_turns_norm = 50.0

    # Channels 0-4: turns to complete each unit type
    for idx, option in enumerate(BUILD_OPTIONS[:5]):
        cost = Unit.PRODUCTION_COST.get(option, 40)
        # Subtract current stockpile if already building this type
        effective_cost = max(0, cost - city.production)
        turns = effective_cost / prod_per_turn
        extra[idx, ci, cj] = min(turns, max_turns_norm) / max_turns_norm

    # Channel 5: turns to settler
    settler_cost = Unit.PRODUCTION_COST.get("Settler", 120)
    effective_cost = max(0, settler_cost - city.production)
    turns = effective_cost / prod_per_turn
    extra[5, ci, cj] = min(turns, max_turns_norm) / max_turns_norm

    # Channel 6: turns to granary
    granary_cost = City.BUILDING_COSTS.get("Granary", 60)
    effective_cost = max(0, granary_cost - city.production)
    turns = effective_cost / prod_per_turn
    extra[6, ci, cj] = min(turns, max_turns_norm) / max_turns_norm

    # Channel 7: current production progress (0→1)
    if city.current_production:
        if city.current_production["type"] == "unit":
            total_cost = city.get_unit_cost(city.current_production["unit_type"])
        else:
            total_cost = city.get_building_cost(city.current_production["building_type"])
        extra[7, ci, cj] = min(city.production / max(1, total_cost), 1.0)

    # Channel 8: city marker (1.0 at this city)
    extra[8, ci, cj] = 1.0

    return torch.cat([combat_state, extra], dim=0)


def get_valid_build_mask(city, device=None):
    """Which build options are valid for this city.

    Returns:
        [NUM_BUILD_OPTIONS] tensor
    """
    if device is None:
        device = torch.device("cpu")

    mask = torch.zeros(NUM_BUILD_OPTIONS, device=device)

    # Unit types: always valid
    for i in range(5):  # Warrior through Catapult
        mask[i] = 1.0

    # Settler: requires pop >= 3
    if city.population >= 3:
        mask[5] = 1.0

    # Granary: only if not already built
    if "Granary" not in city.buildings:
        mask[6] = 1.0

    return mask


class BuildAgent:
    """DQN agent for city production decisions.

    Separate from the combat DQNAgent — different state space, action space,
    and time scale (once per turn per city vs many steps per turn).
    """

    def __init__(self, n, m, d_combat, memory_size=5000, gamma=0.95,
                 learning_rate=0.001):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.n = n
        self.m = m
        self.d_combat = d_combat
        self.gamma = gamma

        d_build = d_combat + NUM_BUILD_CHANNELS
        self.network = BuildNetwork(n, m, d_build).to(self.device)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=learning_rate)
        self.criterion = nn.MSELoss()
        self.memory = ReplayMemory(memory_size)

        # Pending transitions: (build_state, action) waiting for next-turn reward
        self.pending = []

    def select_build(self, combat_state, city, game_env, epsilon=0.3):
        """Choose what to build in a city.

        Args:
            combat_state: [d, n, m] combat state tensor
            city: City to make decision for
            game_env: GameEnvironment
            epsilon: Exploration rate

        Returns:
            int: index into BUILD_OPTIONS
        """
        build_state = encode_build_state(combat_state, city, game_env)
        mask = get_valid_build_mask(city, self.device)

        if random.random() < epsilon:
            valid = torch.where(mask > 0)[0].tolist()
            action = random.choice(valid) if valid else 0
        else:
            with torch.no_grad():
                self.network.eval()
                q = self.network(build_state.unsqueeze(0)).squeeze(0)
                self.network.train()
                q[mask == 0] = float('-inf')
                action = q.argmax().item()

        # Store pending transition with the city that made the decision
        self.pending.append((build_state, action, city))
        return action

    def complete_pending(self, reward, next_combat_state, game_env, done):
        """Complete pending transitions with the reward from this turn.

        Each pending transition remembers which city made the decision,
        so multi-city states are handled correctly.
        """
        if not self.pending:
            return

        for build_state, action, city in self.pending:
            # Check if this city still exists
            if not done and city in game_env.current_player.cities:
                next_build_state = encode_build_state(
                    next_combat_state, city, game_env
                )
            else:
                next_build_state = build_state.clone().zero_()

            self.memory.push(build_state, action, reward, next_build_state, done)

        self.pending = []

    def optimize(self, batch_size=32):
        """Run one optimization step."""
        if len(self.memory) < batch_size:
            return

        transitions = self.memory.sample(batch_size)
        batch = Transition(*zip(*transitions))

        state_batch = torch.stack(batch.state)
        action_batch = torch.tensor(batch.action, dtype=torch.long, device=self.device)
        reward_batch = torch.tensor(batch.reward, dtype=torch.float32, device=self.device)
        next_state_batch = torch.stack(batch.next_state)
        done_batch = torch.tensor(batch.done, dtype=torch.float32, device=self.device)

        # Current Q-values
        q_values = self.network(state_batch).gather(1, action_batch.unsqueeze(1))

        # Target Q-values
        with torch.no_grad():
            next_q = self.network(next_state_batch).max(1)[0]
            target = reward_batch + self.gamma * next_q * (1 - done_batch)

        loss = self.criterion(q_values.squeeze(1), target)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
