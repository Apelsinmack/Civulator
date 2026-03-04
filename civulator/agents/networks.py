"""Neural network architecture for the Select-and-Move DQN agent."""

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


def get_valid_select_mask(state):
    """Generate a mask for valid unit selections.

    Valid = tile has a unit (health > 0) with movement points remaining.
    """
    unit_health_layer = state[1, :, :]
    movement_layer = state[2, :, :]

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
    """
    d, n, m = state.shape
    device = state.device

    if selected_pos >= n * m:
        return torch.zeros(n * m, device=device)

    row = selected_pos // m
    col = selected_pos % m

    valid_move_mask = torch.zeros(n, m, device=device)

    unit_health = state[1, row, col].item()
    movement_points = state[2, row, col].item()

    if unit_health <= 0 or movement_points <= 0:
        return valid_move_mask.flatten()

    enemy_units_layer = state[4, :, :]

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

        friendly_unit = state[1, new_row, new_col].item() > 0
        enemy_unit = enemy_units_layer[new_row, new_col].item() < 0

        if not friendly_unit or enemy_unit:
            valid_move_mask[new_row, new_col] = 1

    # Current tile is valid (fortify)
    valid_move_mask[row, col] = 1

    return valid_move_mask.flatten()
