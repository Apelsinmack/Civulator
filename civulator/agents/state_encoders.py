"""State encoders that convert raw game state to agent-specific tensor representations.

Each agent can use a different encoder, enabling experiments that compare
different state representations against each other.
"""

from abc import ABC, abstractmethod

import torch

from ..game.terrain import Terrain


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


class EnhancedStateEncoder(StateEncoder):
    """Rich state encoder with unit class one-hot, stats, terrain, and cities.

    Relationship-based encoding: own units get full detail, enemy units get
    full detail from opponent's perspective. Scales to N players by merging
    all enemies into the same enemy channels (2-player) or using
    own/ally/neutral/enemy groupings (future N-player).

    Tensor layout (25 channels for 2-player):
        Channels 0-4:   Own unit class one-hot (melee/spear/ranged/cavalry/siege)
        Channels 5-10:  Own unit stats (HP, melee_str, ranged_str, range, movement, defense_bonus)
        Channels 11-15: Enemy unit class one-hot
        Channels 16-21: Enemy unit stats
        Channel 22:     Own cities (1 at city tile)
        Channel 23:     Enemy cities (1 at city tile)
        Channel 24:     Terrain movement cost (normalized)
    """

    # Unit class to one-hot index mapping
    CLASS_INDEX = {
        "Warrior": 0,    # melee
        "Swordsman": 0,  # melee
        "Spearman": 1,   # spear
        "Archer": 2,     # ranged
        "Horseman": 3,   # cavalry
        "Catapult": 4,   # siege
    }

    # Normalization constants
    MAX_MELEE_STR = 50.0
    MAX_RANGED_STR = 50.0
    MAX_RANGE = 2.0
    MAX_MOVEMENT = 4.0  # Horseman has 4
    MAX_DEFENSE_BONUS = 12.0  # fort(6) + terrain(3) + walls(3)
    MAX_TERRAIN_COST = 3.0

    def get_depth(self, num_players):
        return 25

    def encode(self, game_env, player_index, device=None):
        if device is None:
            device = torch.device("cpu")

        n, m = game_env.n, game_env.m
        state = torch.zeros(25, n, m, device=device)

        current_player = game_env.players[player_index]

        # --- Own units (channels 0-10) ---
        for unit in current_player.units:
            i, j = unit.coordinates
            # Class one-hot (channels 0-4)
            cls_idx = self.CLASS_INDEX.get(unit.unit_type, 0)
            state[cls_idx, i, j] = 1.0
            # Stats (channels 5-10)
            state[5, i, j] = unit.health / 100.0
            state[6, i, j] = unit.get_base_combat_strength() / self.MAX_MELEE_STR
            state[7, i, j] = unit.get_base_ranged_strength() / self.MAX_RANGED_STR
            state[8, i, j] = unit.get_range() / self.MAX_RANGE
            state[9, i, j] = unit.movement_points / self.MAX_MOVEMENT
            # Defense bonus: fortification + terrain
            fort_bonus = 0
            if unit.fortification == 1:
                fort_bonus = 3
            elif unit.fortification >= 2:
                fort_bonus = 6
            terrain_bonus = 0
            tile = game_env.map.get_tile(unit.coordinates)
            if tile:
                terrain_bonus = Terrain.DEFENSE_MODIFIERS.get(tile.terrain_type, 0)
            state[10, i, j] = (fort_bonus + terrain_bonus) / self.MAX_DEFENSE_BONUS

        # --- Enemy units (channels 11-21) ---
        for player in game_env.players:
            if player == current_player:
                continue
            for unit in player.units:
                i, j = unit.coordinates
                # Class one-hot (channels 11-15)
                cls_idx = self.CLASS_INDEX.get(unit.unit_type, 0)
                state[11 + cls_idx, i, j] = 1.0
                # Stats (channels 16-21)
                state[16, i, j] = unit.health / 100.0
                state[17, i, j] = unit.get_base_combat_strength() / self.MAX_MELEE_STR
                state[18, i, j] = unit.get_base_ranged_strength() / self.MAX_RANGED_STR
                state[19, i, j] = unit.get_range() / self.MAX_RANGE
                state[20, i, j] = unit.movement_points / self.MAX_MOVEMENT
                # Defense bonus
                fort_bonus = 0
                if unit.fortification == 1:
                    fort_bonus = 3
                elif unit.fortification >= 2:
                    fort_bonus = 6
                terrain_bonus = 0
                tile = game_env.map.get_tile(unit.coordinates)
                if tile:
                    terrain_bonus = Terrain.DEFENSE_MODIFIERS.get(tile.terrain_type, 0)
                state[21, i, j] = (fort_bonus + terrain_bonus) / self.MAX_DEFENSE_BONUS

        # --- Own cities (channel 22) ---
        for city in current_player.cities:
            i, j = city.coordinates
            state[22, i, j] = 1.0

        # --- Enemy cities (channel 23) ---
        for player in game_env.players:
            if player == current_player:
                continue
            for city in player.cities:
                i, j = city.coordinates
                state[23, i, j] = 1.0

        # --- Terrain movement cost (channel 24) ---
        for i in range(n):
            for j in range(m):
                tile = game_env.map.get_tile((i, j))
                if tile:
                    cost = Terrain.MOVEMENT_COSTS.get(tile.terrain_type, 1)
                    state[24, i, j] = min(cost, self.MAX_TERRAIN_COST) / self.MAX_TERRAIN_COST

        return state
