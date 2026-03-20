"""DQN Agent with Select-and-Move action architecture."""

import copy
import random

import torch

from ..config import CFG
from .networks import (
    SelectAndMoveNetwork,
    SharedBackboneNetwork,
    FullyConvNetwork,
    FullyConvSeparateNetwork,
    get_valid_select_mask,
    adjust_mask_for_end_turn,
    get_valid_moves_mask,
)
from .replay_memory import ReplayMemory, Transition
from .state_encoders import BasicStateEncoder, EnhancedStateEncoder
from ..game.unit import NUM_UNIT_SLOTS


class DQNAgent:
    """Deep Q-Network agent using the Select-and-Move architecture.

    Each agent has its own:
    - StateEncoder (converts raw game state to tensor)
    - SelectAndMoveNetwork (policy/value network)
    - ReplayMemory
    - Optimizer

    Args:
        n: Map height
        m: Map width
        d: State tensor depth
        memory: ReplayMemory instance (can be shared or per-agent)
        gamma: Discount factor
        learning_rate: Adam learning rate
    """

    def __init__(self, n, m, d, memory, gamma=0.9, learning_rate=0.001,
                 conv_channels=(16, 32), fc_hidden=None, shared_backbone=False,
                 encoder="basic", fully_conv=False, separate_backbone=False):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")
        self.n = n
        self.m = m
        self.d = d
        self.gamma = gamma
        self.memory = memory
        if fully_conv and separate_backbone:
            self.network = FullyConvSeparateNetwork(
                d, conv_channels=conv_channels
            ).to(self.device)
        elif fully_conv:
            self.network = FullyConvNetwork(
                d, conv_channels=conv_channels
            ).to(self.device)
        elif shared_backbone:
            self.network = SharedBackboneNetwork(
                n, m, d, conv_channels=conv_channels, fc_hidden=fc_hidden
            ).to(self.device)
        else:
            self.network = SelectAndMoveNetwork(
                n, m, d, conv_channels=conv_channels, fc_hidden=fc_hidden
            ).to(self.device)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=learning_rate)
        self.criterion = torch.nn.MSELoss()
        self.pending_transitions = []
        if encoder == "enhanced":
            self.state_encoder = EnhancedStateEncoder()
        else:
            self.state_encoder = BasicStateEncoder()

        # Target network — frozen copy updated every target_update_freq optimizations
        self.target_network = copy.deepcopy(self.network).to(self.device)
        self.target_network.eval()
        _tcfg = CFG.get("training", {})
        self.target_update_freq = _tcfg.get("target_update_freq", 100)
        self.optimize_count = 0

        # Epsilon decay — can be overridden per agent via set_epsilon_schedule()
        self.epsilon_start = _tcfg.get("epsilon_start", 1.0)
        self.epsilon_end = _tcfg.get("epsilon_end", 0.05)
        self.epsilon_decay_episodes = _tcfg.get("epsilon_decay_episodes", 5000)
        self.episode_count = 0

    def set_epsilon_schedule(self, start, end, decay_episodes):
        """Override the default epsilon schedule for this agent."""
        self.epsilon_start = start
        self.epsilon_end = end
        self.epsilon_decay_episodes = decay_episodes

    def get_epsilon(self):
        """Current epsilon based on episode count (linear decay)."""
        progress = min(1.0, self.episode_count / max(1, self.epsilon_decay_episodes))
        return self.epsilon_start + (self.epsilon_end - self.epsilon_start) * progress

    def on_episode_end(self):
        """Call at the end of each episode to update epsilon decay counter."""
        self.episode_count += 1

    def build_state_tensor(self, game_env):
        """Build a tensor representation using the agent's state encoder."""
        player_index = game_env.current_player.player_index
        return self.state_encoder.encode(game_env, player_index, self.device)

    def store_pending_transition(self, state, action, reward):
        """Store a transition waiting for the next state (multi-agent)."""
        self.pending_transitions.append((state, action, reward))

    def complete_pending_transition(self, next_state, done):
        """Complete a pending transition with the agent's actual next state."""
        if not self.pending_transitions:
            return
        state, action, reward = self.pending_transitions.pop(0)
        self.store_transition(state, action, reward, next_state, done)

    def select_action(self, state, epsilon=0.1, game_env=None):
        """Select an action using epsilon-greedy policy.

        Args:
            state: State tensor
            epsilon: Exploration rate
            game_env: GameEnvironment for precise masking (recommended)

        Returns:
            tuple: (selected_pos, move_pos) as integer indices
                selected_pos: tile_index * NUM_SLOTS + slot, or n*m*NUM_SLOTS for end turn
                move_pos: flat tile index
        """
        if random.random() < epsilon:
            return self._random_action(state, game_env)
        else:
            return self._greedy_action(state, game_env)

    def _end_turn_index(self):
        return self.n * self.m * NUM_UNIT_SLOTS

    def _random_action(self, state, game_env=None):
        """Select a random valid action."""
        original_mask = get_valid_select_mask(state, game_env)
        adjusted_mask = adjust_mask_for_end_turn(original_mask)
        valid_positions = torch.where(adjusted_mask > 0)[0].tolist()

        end_turn_idx = self._end_turn_index()

        if not valid_positions:
            return (end_turn_idx, random.randint(0, self.n * self.m - 1))

        selected_pos = random.choice(valid_positions)

        if selected_pos == end_turn_idx:
            move_pos = random.randint(0, self.n * self.m - 1)
        else:
            valid_moves_mask = get_valid_moves_mask(state, selected_pos, game_env)
            valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
            move_pos = random.choice(valid_moves) if valid_moves else random.randint(0, self.n * self.m - 1)

        return (selected_pos, move_pos)

    def _greedy_action(self, state, game_env=None):
        """Select the best action according to the network (argmax over Q-values)."""
        end_turn_idx = self._end_turn_index()

        with torch.no_grad():
            state_tensor = state.unsqueeze(0)

            select_qvalues, _ = self.network(state_tensor)
            select_qvalues = select_qvalues.squeeze(0)

            # Mask invalid selections with -inf so argmax ignores them
            original_mask = get_valid_select_mask(state, game_env)
            select_mask = adjust_mask_for_end_turn(original_mask)
            select_qvalues_masked = select_qvalues.clone()
            select_qvalues_masked[select_mask == 0] = float('-inf')

            if (select_qvalues_masked == float('-inf')).all():
                return (end_turn_idx, random.randint(0, self.n * self.m - 1))

            selected_pos = torch.argmax(select_qvalues_masked).item()

            if selected_pos == end_turn_idx:
                move_pos = random.randint(0, self.n * self.m - 1)
            else:
                _, move_qvalues = self.network(
                    state_tensor,
                    torch.tensor([[selected_pos]], device=state.device).float(),
                )
                move_qvalues = move_qvalues.squeeze(0)

                valid_moves_mask = get_valid_moves_mask(state, selected_pos, game_env)
                move_qvalues_masked = move_qvalues.clone()
                move_qvalues_masked[valid_moves_mask == 0] = float('-inf')

                if (move_qvalues_masked == float('-inf')).all():
                    valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
                    move_pos = random.choice(valid_moves) if valid_moves else selected_pos // NUM_UNIT_SLOTS
                else:
                    move_pos = torch.argmax(move_qvalues_masked).item()

        return (selected_pos, move_pos)

    def store_transition(self, state, action, reward, next_state, done):
        self.memory.push(state, action, reward, next_state, done)

    def compute_loss(self, batch_size):
        """Compute DQN loss from a batch of replay memory.

        Uses additive Q-value decomposition (branching DQN):
            Q(s, a_select, a_move) = Q_select(s, a_select) + Q_move(s, a_select, a_move)
        """
        transitions = self.memory.sample(batch_size)
        batch = Transition(*zip(*transitions))

        state_batch = torch.stack(batch.state)
        action_batch = list(zip(*batch.action))
        reward_batch = torch.tensor(batch.reward, device=self.device, dtype=torch.float32)
        next_state_batch = torch.stack(batch.next_state)
        done_batch = torch.tensor(batch.done, dtype=torch.float32, device=self.device)

        select_actions = torch.tensor(action_batch[0], dtype=torch.long, device=self.device)
        move_actions = torch.tensor(action_batch[1], dtype=torch.long, device=self.device)

        selected_positions_tensor = select_actions.unsqueeze(1)

        # Current Q-values: Q(s, a_s, a_m) = Q_select(s, a_s) + Q_move(s, a_s, a_m)
        select_qvalues, move_qvalues = self.network(state_batch, selected_positions_tensor)
        if move_qvalues is None:
            move_qvalues = select_qvalues

        q_values = (
            select_qvalues.gather(1, select_actions.unsqueeze(1))
            + move_qvalues.gather(1, move_actions.unsqueeze(1))
        )

        # Next state max Q-values from TARGET network (stable targets)
        with torch.no_grad():
            next_select_qvalues, _ = self.target_network(next_state_batch)
            best_select = next_select_qvalues.argmax(dim=1, keepdim=True)

            _, next_move_qvalues = self.target_network(next_state_batch, best_select)
            if next_move_qvalues is None:
                next_move_qvalues = next_select_qvalues

            next_q_values = next_select_qvalues.max(1)[0] + next_move_qvalues.max(1)[0]
            expected_q_values = reward_batch + self.gamma * next_q_values * (1 - done_batch)

        loss = self.criterion(q_values.squeeze(1), expected_q_values)
        return loss

    def optimize(self, batch_size):
        """Run one optimization step. Periodically syncs target network."""
        loss = self.compute_loss(batch_size)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        self.optimize_count += 1
        if self.optimize_count % self.target_update_freq == 0:
            self.target_network.load_state_dict(self.network.state_dict())
