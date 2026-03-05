"""Neural network architectures for the Select-and-Move DQN agent."""

import torch
import torch.nn as nn
import torch.nn.functional as F


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

        # Fully connected layers (with optional hidden layer)
        self.fc_hidden = fc_hidden
        if fc_hidden:
            self.fc_select_hidden = nn.Linear(self.flattened_size, fc_hidden)
            self.fc_select = nn.Linear(fc_hidden, n * m + 1)
            self.fc_move_hidden = nn.Linear(self.flattened_size + 1, fc_hidden)
            self.fc_move = nn.Linear(fc_hidden, n * m)
        else:
            self.fc_select = nn.Linear(self.flattened_size, n * m + 1)  # +1 for end turn
            self.fc_move = nn.Linear(self.flattened_size + 1, n * m)  # +1 for selected position

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile indices (optional)

        Returns:
            select_qvalues: [batch, n*m+1] raw Q-values for tile selection + end turn
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

        # Separate FC heads
        self.fc_hidden = fc_hidden
        if fc_hidden:
            self.fc_select_hidden = nn.Linear(self.flattened_size, fc_hidden)
            self.fc_select = nn.Linear(fc_hidden, n * m + 1)
            self.fc_move_hidden = nn.Linear(self.flattened_size + 1, fc_hidden)
            self.fc_move = nn.Linear(fc_hidden, n * m)
        else:
            self.fc_select = nn.Linear(self.flattened_size, n * m + 1)
            self.fc_move = nn.Linear(self.flattened_size + 1, n * m)

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile indices (optional)

        Returns:
            select_qvalues: [batch, n*m+1] raw Q-values for tile selection + end turn
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

        # Select head: 1x1 conv → per-tile Q-value + learnable end-turn Q
        self.select_conv = nn.Conv2d(c2, 1, kernel_size=1)
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
            selected_pos: [batch, 1] tensor of selected tile indices (optional)

        Returns:
            select_qvalues: [batch, n*m+1] Q-values for tile selection + end turn
            move_qvalues: [batch, n*m] Q-values for move targets (None if no selected_pos)
        """
        # Backbone: pad → conv → pad → conv (preserves spatial dims)
        x = horizontal_wrap_padding(state, self.padding_size)
        x = F.relu(self.bn1(self.conv1(x)))
        x = horizontal_wrap_padding(x, self.padding_size)
        features = F.relu(self.bn2(self.conv2(x)))
        # features: [batch, c2, n, m] — same spatial size as input

        # Select head: spatial Q-values + end-turn
        select_map = self.select_conv(features)  # [batch, 1, n, m]
        select_flat = select_map.view(select_map.size(0), -1)  # [batch, n*m]
        end_turn = self.end_turn_q.expand(select_flat.size(0), 1)
        select_qvalues = torch.cat([select_flat, end_turn], dim=1)  # [batch, n*m+1]

        if selected_pos is not None:
            batch_size = features.size(0)
            n, m = features.size(2), features.size(3)

            # Create marker channel: 1.0 at selected position
            marker = torch.zeros(batch_size, 1, n, m, device=features.device)
            selected_pos_int = selected_pos.long().view(-1)
            for i in range(batch_size):
                pos = selected_pos_int[i].item()
                r, c = pos // m, pos % m
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


def get_valid_select_mask(state, hp_channel=None, move_channel=None):
    """Generate a mask for valid unit selections.

    Valid = tile has a unit (health > 0) with movement points remaining.
    Channel indices default to BasicStateEncoder layout (1=HP, 2=movement).
    For EnhancedStateEncoder use hp_channel=5, move_channel=9.
    """
    d = state.shape[0]
    if hp_channel is None:
        hp_channel = 5 if d == 25 else 1
    if move_channel is None:
        move_channel = 9 if d == 25 else 2

    unit_health_layer = state[hp_channel, :, :]
    movement_layer = state[move_channel, :, :]

    valid = (movement_layer > 0.01).float() * (unit_health_layer > 0.01).float()
    return valid.flatten()


def adjust_mask_for_end_turn(original_mask):
    """Append an always-valid end-turn action to the selection mask."""
    device = original_mask.device
    return torch.cat([original_mask, torch.tensor([1.0], device=device)])


def get_valid_moves_mask(state, selected_pos):
    """Generate a mask for valid move destinations from the selected unit.

    Valid = adjacent tile (hex adjacency) that is not occupied by a friendly unit,
    plus the current tile (for fortify).

    Auto-detects BasicStateEncoder (d=5) vs EnhancedStateEncoder (d=25).
    """
    d, n, m = state.shape
    device = state.device

    if selected_pos >= n * m:
        return torch.zeros(n * m, device=device)

    # Auto-detect encoder channels
    if d == 25:
        hp_ch = 5        # Own HP (normalized)
        move_ch = 9       # Own movement points (normalized)
        enemy_hp_ch = 16  # Enemy HP (normalized)
        hp_thresh = 0.01
        enemy_thresh = 0.01
        enemy_sign = 1    # Enhanced uses positive values for enemy
    else:
        hp_ch = 1         # Own HP (raw)
        move_ch = 2       # Own movement points (raw)
        enemy_hp_ch = 4   # Enemy HP (negative raw)
        hp_thresh = 0.01
        enemy_thresh = 0.01
        enemy_sign = -1   # Basic uses negative values for enemy

    row = selected_pos // m
    col = selected_pos % m

    valid_move_mask = torch.zeros(n, m, device=device)

    unit_health = state[hp_ch, row, col].item()
    movement_points = state[move_ch, row, col].item()

    if unit_health <= hp_thresh or movement_points <= hp_thresh:
        return valid_move_mask.flatten()

    enemy_units_layer = state[enemy_hp_ch, :, :]

    # Use hex adjacency with even/odd row offsets
    if row % 2 == 0:
        directions = [(-1, -1), (-1, 0), (0, -1), (0, 1), (1, -1), (1, 0)]
    else:
        directions = [(-1, 0), (-1, 1), (0, -1), (0, 1), (1, 0), (1, 1)]

    for dr, dc in directions:
        new_row = (row + dr) % n
        new_col = (col + dc) % m

        # Check bounds (vertical -- no wrapping)
        if row + dr < 0 or row + dr >= n:
            continue

        friendly_unit = state[hp_ch, new_row, new_col].item() > hp_thresh
        has_enemy = enemy_units_layer[new_row, new_col].item() * enemy_sign > enemy_thresh

        if not friendly_unit or has_enemy:
            valid_move_mask[new_row, new_col] = 1

    # Current tile is valid (fortify)
    valid_move_mask[row, col] = 1

    return valid_move_mask.flatten()
