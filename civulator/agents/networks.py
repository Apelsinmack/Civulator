"""Neural network architectures for the Select-and-Move DQN agent.

Select action space: n*m*NUM_SLOTS + 1
    Each tile has NUM_SLOTS selection options (military, civilian, siege support, great person).
    The last action is end-turn.
    Masking ensures only slots with valid units are selectable.

Move action space: n*m (unchanged — destination is a tile, not a slot)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

from ..game.unit import NUM_UNIT_SLOTS


def horizontal_wrap_padding(state, padding_size=1):
    """
    Pad a state tensor with horizontal wrapping to handle the cylindrical map.

    Copies edge columns to the opposite side so that the CNN correctly
    perceives adjacency across the map boundary.

    Args:
        state: Input tensor, either [batch, d, n, m] or [d, n, m]
        padding_size: Number of columns to pad on each side

    Returns:
        Padded tensor with horizontal wrapping and zero-padded top/bottom
    """
    if len(state.shape) == 4:
        batch_size, d, n, m = state.shape
        device = state.device

        padded = torch.zeros(
            batch_size, d, n + padding_size * 2, m + padding_size * 2, device=device
        )

        # Copy original state to center
        padded[:, :, padding_size : n + padding_size, padding_size : m + padding_size] = state

        # Wrap left/right edges
        for i in range(padding_size):
            padded[:, :, padding_size : n + padding_size, i] = state[:, :, :, m - (padding_size - i)]
            padded[:, :, padding_size : n + padding_size, m + padding_size + i] = state[:, :, :, i]

    else:
        d, n, m = state.shape
        device = state.device

        padded = torch.zeros(d, n + padding_size * 2, m + padding_size * 2, device=device)

        padded[:, padding_size : n + padding_size, padding_size : m + padding_size] = state

        for i in range(padding_size):
            padded[:, padding_size : n + padding_size, i] = state[:, :, m - (padding_size - i)]
            padded[:, padding_size : n + padding_size, m + padding_size + i] = state[:, :, i]

    return padded


class SelectAndMoveNetwork(nn.Module):
    """DQN with two heads: one for selecting a unit, one for choosing where to move.

    Both heads use cylindrical wrap padding before convolution.

    Args:
        n: Map height (rows)
        m: Map width (columns)
        d: State tensor depth (channels)
        kernel_size: Convolution kernel size (default 3)
    """

    def __init__(self, n, m, d, kernel_size=3, conv_channels=(16, 32), fc_hidden=None):
        """
        Args:
            n: Map height (rows)
            m: Map width (columns)
            d: State tensor depth (channels)
            kernel_size: Convolution kernel size (default 3)
            conv_channels: Tuple of (conv1_out, conv2_out) channel counts
            fc_hidden: Optional hidden layer size between conv and output (None = direct)
        """
        super().__init__()

        self.padding_size = kernel_size // 2
        self.padded_n = n + 2 * self.padding_size
        self.padded_m = m + 2 * self.padding_size
        self.n = n
        self.m = m

        c1, c2 = conv_channels

        # Select head convolutions
        self.conv1_select = nn.Conv2d(d, c1, kernel_size=kernel_size, stride=1, padding=0)
        self.bn1_select = nn.BatchNorm2d(c1)
        self.conv2_select = nn.Conv2d(c1, c2, kernel_size=kernel_size, stride=1, padding=0)
        self.bn2_select = nn.BatchNorm2d(c2)

        # Move head convolutions
        self.conv1_move = nn.Conv2d(d, c1, kernel_size=kernel_size, stride=1, padding=0)
        self.bn1_move = nn.BatchNorm2d(c1)
        self.conv2_move = nn.Conv2d(c1, c2, kernel_size=kernel_size, stride=1, padding=0)
        self.bn2_move = nn.BatchNorm2d(c2)

        # Calculate flattened size after two convolutions
        conv1_out_n = self.padded_n - kernel_size + 1
        conv1_out_m = self.padded_m - kernel_size + 1
        conv2_out_n = conv1_out_n - kernel_size + 1
        conv2_out_m = conv1_out_m - kernel_size + 1
        self.flattened_size = c2 * conv2_out_n * conv2_out_m

        # Select output: n*m*NUM_SLOTS + 1 (one Q-value per tile-slot + end turn)
        select_out = n * m * NUM_UNIT_SLOTS + 1
        self.fc_hidden = fc_hidden
        if fc_hidden:
            self.fc_select_hidden = nn.Linear(self.flattened_size, fc_hidden)
            self.fc_select = nn.Linear(fc_hidden, select_out)
            self.fc_move_hidden = nn.Linear(self.flattened_size + 1, fc_hidden)
            self.fc_move = nn.Linear(fc_hidden, n * m)
        else:
            self.fc_select = nn.Linear(self.flattened_size, select_out)
            self.fc_move = nn.Linear(self.flattened_size + 1, n * m)

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile-slot index (optional)

        Returns:
            select_qvalues: [batch, n*m*NUM_SLOTS+1] Q-values for tile-slot selection + end turn
            move_qvalues: [batch, n*m] raw Q-values for move targets (None if selected_pos not given)
        """
        padded_state = horizontal_wrap_padding(state, self.padding_size)

        # Select head
        x_select = F.relu(self.bn1_select(self.conv1_select(padded_state)))
        x_select = F.relu(self.bn2_select(self.conv2_select(x_select)))
        x_select = x_select.view(x_select.size(0), -1)
        if self.fc_hidden:
            x_select = F.relu(self.fc_select_hidden(x_select))
        select_qvalues = self.fc_select(x_select)

        if selected_pos is not None:
            # Move head
            x_move = F.relu(self.bn1_move(self.conv1_move(padded_state)))
            x_move = F.relu(self.bn2_move(self.conv2_move(x_move)))
            x_move = x_move.view(x_move.size(0), -1)

            selected_pos = selected_pos.float().view(-1, 1)
            x_move = torch.cat([x_move, selected_pos], dim=1)
            if self.fc_hidden:
                x_move = F.relu(self.fc_move_hidden(x_move))
            move_qvalues = self.fc_move(x_move)
            return select_qvalues, move_qvalues

        return select_qvalues, None


class SharedBackboneNetwork(nn.Module):
    """DQN with shared CNN backbone and separate FC heads for select/move.

    Same interface as SelectAndMoveNetwork (drop-in replacement).
    The conv layers process the board once; both heads read from the
    same feature representation.

    Args:
        n: Map height (rows)
        m: Map width (columns)
        d: State tensor depth (channels)
        kernel_size: Convolution kernel size (default 3)
        conv_channels: Tuple of (conv1_out, conv2_out) channel counts
        fc_hidden: Optional hidden layer size between conv and output (None = direct)
    """

    def __init__(self, n, m, d, kernel_size=3, conv_channels=(16, 32), fc_hidden=None):
        super().__init__()

        self.padding_size = kernel_size // 2
        self.padded_n = n + 2 * self.padding_size
        self.padded_m = m + 2 * self.padding_size
        self.n = n
        self.m = m

        c1, c2 = conv_channels

        # Shared backbone
        self.conv1 = nn.Conv2d(d, c1, kernel_size=kernel_size, stride=1, padding=0)
        self.bn1 = nn.BatchNorm2d(c1)
        self.conv2 = nn.Conv2d(c1, c2, kernel_size=kernel_size, stride=1, padding=0)
        self.bn2 = nn.BatchNorm2d(c2)

        # Calculate flattened size after two convolutions
        conv1_out_n = self.padded_n - kernel_size + 1
        conv1_out_m = self.padded_m - kernel_size + 1
        conv2_out_n = conv1_out_n - kernel_size + 1
        conv2_out_m = conv1_out_m - kernel_size + 1
        self.flattened_size = c2 * conv2_out_n * conv2_out_m

        # Separate FC heads — select output: n*m*NUM_SLOTS + 1
        select_out = n * m * NUM_UNIT_SLOTS + 1
        self.fc_hidden = fc_hidden
        if fc_hidden:
            self.fc_select_hidden = nn.Linear(self.flattened_size, fc_hidden)
            self.fc_select = nn.Linear(fc_hidden, select_out)
            self.fc_move_hidden = nn.Linear(self.flattened_size + 1, fc_hidden)
            self.fc_move = nn.Linear(fc_hidden, n * m)
        else:
            self.fc_select = nn.Linear(self.flattened_size, select_out)
            self.fc_move = nn.Linear(self.flattened_size + 1, n * m)

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile-slot index (optional)

        Returns:
            select_qvalues: [batch, n*m*NUM_SLOTS+1] Q-values for tile-slot selection + end turn
            move_qvalues: [batch, n*m] raw Q-values for move targets (None if no selected_pos)
        """
        padded_state = horizontal_wrap_padding(state, self.padding_size)

        # Shared backbone — computed once
        features = F.relu(self.bn1(self.conv1(padded_state)))
        features = F.relu(self.bn2(self.conv2(features)))
        features_flat = features.view(features.size(0), -1)

        # Select head
        if self.fc_hidden:
            x_select = F.relu(self.fc_select_hidden(features_flat))
        else:
            x_select = features_flat
        select_qvalues = self.fc_select(x_select)

        if selected_pos is not None:
            # Move head — reuses same backbone features
            selected_pos = selected_pos.float().view(-1, 1)
            x_move = torch.cat([features_flat, selected_pos], dim=1)
            if self.fc_hidden:
                x_move = F.relu(self.fc_move_hidden(x_move))
            move_qvalues = self.fc_move(x_move)
            return select_qvalues, move_qvalues

        return select_qvalues, None


class FullyConvNetwork(nn.Module):
    """Fully convolutional DQN — map-size independent.

    No FC layers. Q-values are produced spatially via 1x1 convolutions.
    The same trained weights work on any map size.

    Uses horizontal_wrap_padding before EACH conv layer to preserve
    spatial dimensions and maintain cylindrical map adjacency.

    Same interface as SelectAndMoveNetwork (drop-in replacement).

    Args:
        d: State tensor depth (channels)
        kernel_size: Convolution kernel size (default 3)
        conv_channels: Tuple of (conv1_out, conv2_out) channel counts
    """

    def __init__(self, d, kernel_size=3, conv_channels=(16, 32), **kwargs):
        super().__init__()

        self.padding_size = kernel_size // 2
        c1, c2 = conv_channels

        # Shared backbone — spatial size preserved via wrap padding before each layer
        self.conv1 = nn.Conv2d(d, c1, kernel_size=kernel_size, padding=0)
        self.bn1 = nn.BatchNorm2d(c1)
        self.conv2 = nn.Conv2d(c1, c2, kernel_size=kernel_size, padding=0)
        self.bn2 = nn.BatchNorm2d(c2)

        # Select head: 1x1 conv → NUM_SLOTS Q-values per tile + learnable end-turn Q
        self.select_conv = nn.Conv2d(c2, NUM_UNIT_SLOTS, kernel_size=1)
        self.end_turn_q = nn.Parameter(torch.zeros(1))

        # Move head: features + selected-position marker → 3x3 conv (spread marker)
        # → 1x1 conv → per-tile Q-value
        self.move_spread = nn.Conv2d(c2 + 1, c2, kernel_size=kernel_size, padding=0)
        self.move_bn = nn.BatchNorm2d(c2)
        self.move_conv = nn.Conv2d(c2, 1, kernel_size=1)

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile-slot index (optional)

        Returns:
            select_qvalues: [batch, n*m*NUM_SLOTS+1] Q-values for tile-slot selection + end turn
            move_qvalues: [batch, n*m] Q-values for move targets (None if no selected_pos)
        """
        # Backbone: pad → conv → pad → conv (preserves spatial dims)
        x = horizontal_wrap_padding(state, self.padding_size)
        x = F.relu(self.bn1(self.conv1(x)))
        x = horizontal_wrap_padding(x, self.padding_size)
        features = F.relu(self.bn2(self.conv2(x)))
        # features: [batch, c2, n, m] — same spatial size as input

        # Select head: spatial Q-values per slot + end-turn
        select_map = self.select_conv(features)  # [batch, NUM_SLOTS, n, m]
        select_flat = select_map.view(select_map.size(0), -1)  # [batch, NUM_SLOTS*n*m]
        end_turn = self.end_turn_q.expand(select_flat.size(0), 1)
        select_qvalues = torch.cat([select_flat, end_turn], dim=1)  # [batch, n*m*NUM_SLOTS+1]

        if selected_pos is not None:
            batch_size = features.size(0)
            n, m = features.size(2), features.size(3)

            # Create marker channel: 1.0 at selected tile position
            # selected_pos encodes tile*NUM_SLOTS+slot, extract tile position
            marker = torch.zeros(batch_size, 1, n, m, device=features.device)
            selected_pos_int = selected_pos.long().view(-1)
            for i in range(batch_size):
                tile_pos = selected_pos_int[i].item() // NUM_UNIT_SLOTS
                r, c = tile_pos // m, tile_pos % m
                if 0 <= r < n and 0 <= c < m:
                    marker[i, 0, r, c] = 1.0

            # Move head: concat marker, spread via 3x3 conv, then 1x1
            move_input = torch.cat([features, marker], dim=1)  # [batch, c2+1, n, m]
            move_input = horizontal_wrap_padding(move_input, self.padding_size)
            move_x = F.relu(self.move_bn(self.move_spread(move_input)))
            move_map = self.move_conv(move_x)  # [batch, 1, n, m]
            move_qvalues = move_map.view(move_map.size(0), -1)  # [batch, n*m]

            return select_qvalues, move_qvalues

        return select_qvalues, None


class FullyConvSeparateNetwork(nn.Module):
    """Fully convolutional DQN with SEPARATE backbones for select and move.

    Unlike FullyConvNetwork (shared backbone), this has independent conv layers
    for each head. Used for A/B testing shared vs separate feature extraction.

    Same interface as FullyConvNetwork (drop-in replacement).

    Args:
        d: State tensor depth (channels)
        kernel_size: Convolution kernel size (default 3)
        conv_channels: Tuple of (conv1_out, conv2_out) channel counts
    """

    def __init__(self, d, kernel_size=3, conv_channels=(16, 32), **kwargs):
        super().__init__()

        self.padding_size = kernel_size // 2
        c1, c2 = conv_channels

        # Select backbone
        self.select_conv1 = nn.Conv2d(d, c1, kernel_size=kernel_size, padding=0)
        self.select_bn1 = nn.BatchNorm2d(c1)
        self.select_conv2 = nn.Conv2d(c1, c2, kernel_size=kernel_size, padding=0)
        self.select_bn2 = nn.BatchNorm2d(c2)

        # Select head: 1x1 conv → NUM_SLOTS Q-values per tile + learnable end-turn Q
        self.select_conv = nn.Conv2d(c2, NUM_UNIT_SLOTS, kernel_size=1)
        self.end_turn_q = nn.Parameter(torch.zeros(1))

        # Move backbone
        self.move_conv1 = nn.Conv2d(d, c1, kernel_size=kernel_size, padding=0)
        self.move_bn1 = nn.BatchNorm2d(c1)
        self.move_conv2 = nn.Conv2d(c1, c2, kernel_size=kernel_size, padding=0)
        self.move_bn2 = nn.BatchNorm2d(c2)

        # Move head: features + selected-position marker → 3x3 conv → 1x1 conv
        self.move_spread = nn.Conv2d(c2 + 1, c2, kernel_size=kernel_size, padding=0)
        self.move_bn = nn.BatchNorm2d(c2)
        self.move_conv = nn.Conv2d(c2, 1, kernel_size=1)

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile indices (optional)

        Returns:
            select_qvalues: [batch, n*m+1] Q-values for tile selection + end turn
            move_qvalues: [batch, n*m] Q-values for move targets (None if no selected_pos)
        """
        # Select backbone
        x_s = horizontal_wrap_padding(state, self.padding_size)
        x_s = F.relu(self.select_bn1(self.select_conv1(x_s)))
        x_s = horizontal_wrap_padding(x_s, self.padding_size)
        select_features = F.relu(self.select_bn2(self.select_conv2(x_s)))

        # Select head — NUM_SLOTS Q-values per tile
        select_map = self.select_conv(select_features)  # [batch, NUM_SLOTS, n, m]
        select_flat = select_map.view(select_map.size(0), -1)  # [batch, NUM_SLOTS*n*m]
        end_turn = self.end_turn_q.expand(select_flat.size(0), 1)
        select_qvalues = torch.cat([select_flat, end_turn], dim=1)

        if selected_pos is not None:
            # Move backbone (separate conv layers)
            x_m = horizontal_wrap_padding(state, self.padding_size)
            x_m = F.relu(self.move_bn1(self.move_conv1(x_m)))
            x_m = horizontal_wrap_padding(x_m, self.padding_size)
            move_features = F.relu(self.move_bn2(self.move_conv2(x_m)))

            batch_size = move_features.size(0)
            n, m = move_features.size(2), move_features.size(3)

            # Create marker channel: 1.0 at selected tile position
            # selected_pos encodes tile*NUM_SLOTS+slot, extract tile position
            marker = torch.zeros(batch_size, 1, n, m, device=move_features.device)
            selected_pos_int = selected_pos.long().view(-1)
            for i in range(batch_size):
                tile_pos = selected_pos_int[i].item() // NUM_UNIT_SLOTS
                r, c = tile_pos // m, tile_pos % m
                if 0 <= r < n and 0 <= c < m:
                    marker[i, 0, r, c] = 1.0

            # Move head
            move_input = torch.cat([move_features, marker], dim=1)
            move_input = horizontal_wrap_padding(move_input, self.padding_size)
            move_x = F.relu(self.move_bn(self.move_spread(move_input)))
            move_map = self.move_conv(move_x)
            move_qvalues = move_map.view(move_map.size(0), -1)

            return select_qvalues, move_qvalues

        return select_qvalues, None


def get_valid_select_mask(state, game_env=None):
    """Generate a mask for valid unit selections with slot support.

    Output shape: [n*m*NUM_SLOTS] — one entry per tile-slot combination.
    Index encoding: tile_index * NUM_SLOTS + slot

    If game_env is provided, uses actual unit data for precise per-slot masking.
    Otherwise falls back to state tensor heuristic (own HP + movement channels).
    """
    d = state.shape[0]
    n, m = state.shape[1], state.shape[2]
    device = state.device

    if game_env is not None:
        # Precise masking from game state
        mask = torch.zeros(n * m * NUM_UNIT_SLOTS, device=device)
        current_player = game_env.current_player
        for unit in current_player.units:
            if unit.health > 0 and unit.movement_points > 0:
                r, c = unit.coordinates
                tile_idx = r * m + c
                mask[tile_idx * NUM_UNIT_SLOTS + unit.slot] = 1.0
        return mask
    else:
        # Fallback: use state tensor channels (can't distinguish slots)
        if d in (25, 27):  # enhanced encoder (27 = fog of war variant)
            hp_ch, move_ch = 5, 9
        else:
            hp_ch, move_ch = 1, 2

        unit_health = state[hp_ch, :, :]
        movement = state[move_ch, :, :]
        has_unit = ((movement > 0.01) * (unit_health > 0.01)).float()

        # Repeat for all slots (fallback can't distinguish — mark slot 0 only)
        mask = torch.zeros(n * m * NUM_UNIT_SLOTS, device=device)
        flat = has_unit.flatten()
        for i in range(n * m):
            if flat[i] > 0:
                mask[i * NUM_UNIT_SLOTS] = 1.0  # Slot 0 (military) as default
        return mask


def adjust_mask_for_end_turn(original_mask):
    """Append an always-valid end-turn action to the selection mask."""
    device = original_mask.device
    return torch.cat([original_mask, torch.tensor([1.0], device=device)])


def get_valid_moves_mask(state, selected_pos, game_env=None):
    """Generate a mask for valid move destinations from the selected unit.

    selected_pos: tile_index * NUM_SLOTS + slot (slot-aware encoding)

    Valid = adjacent tile (hex adjacency) where the unit's slot is not
    occupied by a friendly unit, plus the current tile (for fortify/found city).
    """
    d, n, m = state.shape
    device = state.device

    # Decode tile-slot from selected_pos
    tile_pos = selected_pos // NUM_UNIT_SLOTS
    selected_slot = selected_pos % NUM_UNIT_SLOTS

    if tile_pos >= n * m:
        return torch.zeros(n * m, device=device)

    row = tile_pos // m
    col = tile_pos % m

    valid_move_mask = torch.zeros(n, m, device=device)

    if game_env is not None:
        # Precise masking from game state
        selected_unit = game_env.get_unit_in_slot(
            (row, col), selected_slot, game_env.current_player
        )
        if selected_unit is None or selected_unit.movement_points <= 0:
            return valid_move_mask.flatten()

        from ..game.map import HEX_DIRECTIONS
        for dr, dc in HEX_DIRECTIONS:
            new_row = row + dr
            new_col = (col + dc) % m
            if new_row < 0 or new_row >= n:
                continue

            # Check if our slot is occupied by a friendly unit
            friendly_in_slot = game_env.is_slot_occupied(
                (new_row, new_col), selected_unit.slot, game_env.current_player
            )
            if not friendly_in_slot:
                valid_move_mask[new_row, new_col] = 1
            else:
                # Allow if enemy present (attack)
                enemy_there = any(
                    u.player != game_env.current_player
                    for u in game_env.get_units_at((new_row, new_col))
                )
                if enemy_there:
                    valid_move_mask[new_row, new_col] = 1

        # Ranged units: enemy-occupied tiles within range AND line of sight
        # are valid targets (rules-LoS — if the unit can shoot it, it can see
        # it, so this leaks nothing under fog of war)
        if selected_unit.get_base_ranged_strength() > 0:
            attack_range = selected_unit.get_range()
            for player in game_env.players:
                if player is game_env.current_player:
                    continue
                for enemy in player.units:
                    er, ec = enemy.coordinates
                    if (
                        game_env.map.distance_function((row, col), (er, ec)) <= attack_range
                        and game_env.check_line_of_sight((row, col), (er, ec))
                    ):
                        valid_move_mask[er, ec] = 1
    else:
        # Fallback: state tensor heuristic
        if d in (25, 27):  # enhanced encoder (27 = fog of war variant)
            hp_ch, enemy_hp_ch = 5, 16
            enemy_sign = 1
        else:
            hp_ch, enemy_hp_ch = 1, 4
            enemy_sign = -1

        from ..game.map import HEX_DIRECTIONS
        for dr, dc in HEX_DIRECTIONS:
            new_row = row + dr
            new_col = (col + dc) % m
            if new_row < 0 or new_row >= n:
                continue

            friendly = state[hp_ch, new_row, new_col].item() > 0.01
            enemy = state[enemy_hp_ch, new_row, new_col].item() * enemy_sign > 0.01
            if not friendly or enemy:
                valid_move_mask[new_row, new_col] = 1

    # Current tile is always valid (fortify / found city)
    valid_move_mask[row, col] = 1

    return valid_move_mask.flatten()
