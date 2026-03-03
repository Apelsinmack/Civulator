"""State encoders that convert raw game state to agent-specific tensor representations.

Each agent can use a different encoder, enabling experiments that compare
different state representations against each other.
"""

from abc import ABC, abstractmethod

import torch


class StateEncoder(ABC):
    """Abstract base class for state encoders."""

    @abstractmethod
    def encode(self, game_env, player_index, device=None):
        """Convert raw game state to a tensor for the network.

        Args:
            game_env: The GameEnvironment instance
            player_index: Index of the player whose perspective to encode
            device: Torch device to place the tensor on

        Returns:
            torch.Tensor of shape [depth, height, width]
        """

    @abstractmethod
    def get_depth(self, num_players):
        """Return the depth (channel count) of the output tensor."""


class BasicStateEncoder(StateEncoder):
    """The current encoder: cities, unit health, and movement per player.

    Tensor layout (d = 2 * num_players + 1):
        Layer 0: Current player's cities (100 at city tiles)
        Layer 1: Current player's unit health
        Layer 2: Current player's unit movement points
        Layer 3: Enemy 1 cities (-100)
        Layer 4: Enemy 1 unit health (negative)
        ... (repeat for additional enemies)
    """

    def get_depth(self, num_players):
        return 2 * num_players + 1

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        n, m = game_env.n, game_env.m
        num_players = len(game_env.players)
        d = self.get_depth(num_players)

        state_tensor = torch.zeros(d, n, m, device=device)

        current_player = game_env.players[player_index]

        # Layer 0: Current player's cities
        for city in current_player.cities:
            i, j = city.coordinates
            state_tensor[0, i, j] = 100

        # Layer 1: Current player's unit health
        # Layer 2: Current player's unit movement points
        for unit in current_player.units:
            i, j = unit.coordinates
            state_tensor[1, i, j] = unit.health
            state_tensor[2, i, j] = unit.movement_points

        # Enemy layers
        layer_index = 3
        for player in game_env.players:
            if player == current_player:
                continue

            for city in player.cities:
                i, j = city.coordinates
                state_tensor[layer_index, i, j] = -100

            for unit in player.units:
                i, j = unit.coordinates
                state_tensor[layer_index + 1, i, j] = -unit.health

            layer_index += 2

        return state_tensor
