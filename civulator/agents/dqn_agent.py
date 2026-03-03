"""DQN Agent with Select-and-Move action architecture."""

import random

import torch

from .networks import (
    SelectAndMoveNetwork,
    get_valid_select_mask,
    adjust_mask_for_end_turn,
    get_valid_moves_mask,
)
from .replay_memory import ReplayMemory, Transition
from .state_encoders import BasicStateEncoder


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

    def __init__(self, n, m, d, memory, gamma=0.9, learning_rate=0.001):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")
        self.n = n
        self.m = m
        self.d = d
        self.gamma = gamma
        self.memory = memory
        self.network = SelectAndMoveNetwork(n, m, d).to(self.device)
        self.optimizer = torch.optim.Adam(self.network.parameters(), lr=learning_rate)
        self.criterion = torch.nn.MSELoss()
        self.pending_transitions = []
        self.state_encoder = BasicStateEncoder()

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

    def select_action(self, state, epsilon=0.1):
        """Select an action using epsilon-greedy policy.

        Returns:
            tuple: (selected_pos, move_pos) as integer indices
        """
        if random.random() < epsilon:
            return self._random_action(state)
        else:
            return self._greedy_action(state)

    def _random_action(self, state):
        """Select a random valid action."""
        original_mask = get_valid_select_mask(state)
        adjusted_mask = adjust_mask_for_end_turn(original_mask)
        valid_positions = torch.where(adjusted_mask > 0)[0].tolist()

        if not valid_positions:
            return (self.n * self.m, random.randint(0, self.n * self.m - 1))

        selected_pos = random.choice(valid_positions)

        if selected_pos == self.n * self.m:
            move_pos = random.randint(0, self.n * self.m - 1)
        else:
            valid_moves_mask = get_valid_moves_mask(state, selected_pos)
            valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
            move_pos = random.choice(valid_moves) if valid_moves else random.randint(0, self.n * self.m - 1)

        return (selected_pos, move_pos)

    def _greedy_action(self, state):
        """Select the best action according to the network."""
        with torch.no_grad():
            state_tensor = state.unsqueeze(0)

            select_probs, _ = self.network(state_tensor)
            select_probs = select_probs.squeeze(0)

            original_mask = get_valid_select_mask(state)
            select_probs_masked = select_probs * adjust_mask_for_end_turn(original_mask)

            if select_probs_masked.sum().item() <= 0:
                return (self.n * self.m, random.randint(0, self.n * self.m - 1))

            select_probs_masked = select_probs_masked / select_probs_masked.sum()
            selected_pos = torch.multinomial(select_probs_masked, 1).item()

            if selected_pos == self.n * self.m:
                move_pos = random.randint(0, self.n * self.m - 1)
            else:
                _, move_probs = self.network(
                    state_tensor,
                    torch.tensor([[selected_pos]], device=state.device).float(),
                )
                move_probs = move_probs.squeeze(0)

                valid_moves_mask = get_valid_moves_mask(state, selected_pos)
                move_probs_masked = move_probs * valid_moves_mask

                if move_probs_masked.sum().item() <= 0:
                    valid_moves = torch.where(valid_moves_mask > 0)[0].tolist()
                    move_pos = random.choice(valid_moves) if valid_moves else selected_pos
                else:
                    move_probs_masked = move_probs_masked / move_probs_masked.sum()
                    move_pos = torch.multinomial(move_probs_masked, 1).item()

        return (selected_pos, move_pos)

    def store_transition(self, state, action, reward, next_state, done):
        self.memory.push(state, action, reward, next_state, done)

    def compute_loss(self, batch_size):
        """Compute DQN loss from a batch of replay memory."""
        transitions = self.memory.sample(batch_size)
        batch = Transition(*zip(*transitions))

        state_batch = torch.stack(batch.state)
        action_batch = list(zip(*batch.action))
        reward_batch = torch.tensor(batch.reward, device=self.device)
        next_state_batch = torch.stack(batch.next_state)
        done_batch = torch.tensor(batch.done, dtype=torch.float32, device=self.device)

        selected_positions = action_batch[0]
        selected_positions_tensor = torch.tensor(
            selected_positions, dtype=torch.long, device=state_batch.device
        ).unsqueeze(1)

        # Current Q-values
        select_probs, move_probs = self.network(state_batch, selected_positions_tensor)
        if move_probs is None:
            move_probs = select_probs

        q_values = (
            select_probs.gather(1, torch.tensor(action_batch[0], device=self.device).unsqueeze(1))
            + move_probs.gather(1, torch.tensor(action_batch[1], device=self.device).unsqueeze(1))
        )

        # Next state Q-values
        next_select_probs, _ = self.network(next_state_batch)
        next_select_probs_norm = next_select_probs / next_select_probs.sum()
        selected_pos = torch.multinomial(next_select_probs_norm, 1)

        _, next_move_probs = self.network(next_state_batch, selected_pos)
        if next_move_probs is None:
            next_move_probs = next_select_probs

        next_q_values = next_select_probs.max(1)[0] + next_move_probs.max(1)[0]
        expected_q_values = reward_batch + self.gamma * next_q_values * (1 - done_batch)

        loss = self.criterion(q_values, expected_q_values.unsqueeze(1))
        return loss

    def optimize(self, batch_size):
        """Run one optimization step."""
        loss = self.compute_loss(batch_size)
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
