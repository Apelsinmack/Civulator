"""Neural network architectures for the Select-and-Move DQN agent.

Select action space: n*m*NUM_SLOTS + 1
    Each tile has NUM_SLOTS selection options (military, civilian, siege support, great person).
    The last action is end-turn.
    Masking ensures only slots with valid units are selectable.

Move action space: n*m (unchanged — destination is a tile, not a slot)
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from ..game.unit import NUM_UNIT_SLOTS


def horizontal_wrap_padding(state, padding_size=1):
    """
    Pad a state tensor with horizontal wrapping to handle the cylindrical map.

    Copies edge columns to the opposite side so that the CNN correctly
    perceives adjacency across the map boundary. Rows (top/bottom) are
    zero-padded, not wrapped -- the map is cylindrical horizontally only.

    Implemented via two native F.pad calls (issue #42): a circular pad on
    the width axis only, then a zero pad on the height axis only. This
    replaces a hand-rolled Python loop that wrote each wrapped column with
    an individual tensor assignment (217k calls/30 episodes in profiling --
    the #1 engine-side hotspot). F.pad's circular mode pads the *last two*
    dims of the input regardless of how many leading (batch/channel) dims
    there are, so the same two-line body handles both the batched
    [batch, d, n, m] and unbatched [d, n, m] shapes without a branch.

    Args:
        state: Input tensor, either [batch, d, n, m] or [d, n, m]
        padding_size: Number of columns to pad on each side

    Returns:
        Padded tensor with horizontal wrapping and zero-padded top/bottom
    """
    padded = F.pad(state, (padding_size, padding_size, 0, 0), mode="circular")
    padded = F.pad(padded, (0, 0, padding_size, padding_size), mode="constant", value=0)
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
        conv_channels: Tuple of per-layer output channel counts. Any length
            >= 1 (issue #48 capacity ladder): each entry adds one
            wrap-padded conv+bn layer to the shared backbone, growing the
            receptive field by kernel_size//2 per layer. The default
            (16, 32) builds the EXACT historical two-layer network —
            parameter names conv{i}/bn{i} are generated to match, so every
            existing checkpoint loads unchanged (pinned by
            tests/test_networks_depth.py).
    """

    def __init__(self, d, kernel_size=3, conv_channels=(16, 32), **kwargs):
        super().__init__()

        self.padding_size = kernel_size // 2
        if not conv_channels:
            raise ValueError("conv_channels must have at least one layer")
        self.num_conv_layers = len(conv_channels)

        # Shared backbone — spatial size preserved via wrap padding before
        # each layer; attribute names conv1/bn1, conv2/bn2, ... keep the
        # historical state_dict keys for the default depth.
        in_channels = d
        for i, out_channels in enumerate(conv_channels, start=1):
            setattr(self, f"conv{i}",
                    nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, padding=0))
            setattr(self, f"bn{i}", nn.BatchNorm2d(out_channels))
            in_channels = out_channels
        c_last = in_channels

        # Select head: 1x1 conv → NUM_SLOTS Q-values per tile + learnable end-turn Q
        self.select_conv = nn.Conv2d(c_last, NUM_UNIT_SLOTS, kernel_size=1)
        self.end_turn_q = nn.Parameter(torch.zeros(1))

        # Move head: features + selected-position marker → 3x3 conv (spread marker)
        # → 1x1 conv → per-tile Q-value
        self.move_spread = nn.Conv2d(c_last + 1, c_last, kernel_size=kernel_size, padding=0)
        self.move_bn = nn.BatchNorm2d(c_last)
        self.move_conv = nn.Conv2d(c_last, 1, kernel_size=1)

    def forward(self, state, selected_pos=None):
        """Forward pass.

        Args:
            state: [batch, d, n, m] tensor
            selected_pos: [batch, 1] tensor of selected tile-slot index (optional)

        Returns:
            select_qvalues: [batch, n*m*NUM_SLOTS+1] Q-values for tile-slot selection + end turn
            move_qvalues: [batch, n*m] Q-values for move targets (None if no selected_pos)
        """
        # Backbone: (pad → conv → bn → relu) per layer (preserves spatial dims)
        x = state
        for i in range(1, self.num_conv_layers + 1):
            x = horizontal_wrap_padding(x, self.padding_size)
            x = F.relu(getattr(self, f"bn{i}")(getattr(self, f"conv{i}")(x)))
        features = x
        # features: [batch, c_last, n, m] — same spatial size as input

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


def conv_channels_from_state_dict(state_dict):
    """Infer a FullyConvNetwork's conv_channels tuple from a saved
    state_dict (the out-channel count of conv1.weight, conv2.weight, ...).

    The canonical way for loaders (scripts/evaluate.py) to reconstruct the
    right architecture for arbitrary-depth checkpoints (issue #48 capacity
    ladder) — no side-channel metadata needed, the weights themselves are
    the authority.
    """
    channels = []
    i = 1
    while f"conv{i}.weight" in state_dict:
        channels.append(int(state_dict[f"conv{i}.weight"].shape[0]))
        i += 1
    if not channels:
        raise ValueError(
            "state_dict has no conv{i}.weight keys — not a FullyConvNetwork payload"
        )
    return tuple(channels)


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


def _valid_order_mask_np(unit, game_env, n, m, stop_at_first=False):
    """The (n, m) numpy core behind `get_valid_moves_mask` — every order this
    returns is one that the engine will actually carry out.

    An offered order that the engine refuses is a *state-preserving* action:
    `_step_inner` returns REWARDS["invalid_action"] having consumed no
    movement, ended no turn and altered nothing, so a deterministic (greedy)
    policy whose argmax lands on it repeats it until the 10,000-step guard.
    That livelock truncated 85 training episodes and 50 of 200 eval games
    (issue #51). Two conditions therefore gate the mask that never used to:

      * **own tile** — fortify for every unit type, which always succeeds
        while movement_points > 0, EXCEPT for a Settler, for whom the own
        tile means *found city*: offered only when
        `game_env.can_found_city_at` agrees (the reproduced bug was a Settler
        inside `min_city_distance` of a city).
      * **affordability** — a neighbouring tile whose `Unit.step_cost`
        (terrain + river crossing) exceeds the unit's remaining movement
        points is a move that silently fails; e.g. 1 MP left with hills
        ahead. It is not offered. Affordability does NOT gate an *attack*:
        attacking is free, it only requires having movement points at all,
        and it always lands at least 1 HP of damage.

    Shared with `get_valid_select_mask`, which uses it to keep a Settler that
    has no valid order at all out of the selection mask — that caller passes
    `stop_at_first=True`, which returns as soon as one order is found because
    all it asks is `.any()`. The returned mask is then NOT complete and must
    only be tested for emptiness.
    """
    valid_move_mask = np.zeros((n, m), dtype=np.float32)
    if unit is None or unit.movement_points <= 0:
        return valid_move_mask

    row, col = unit.coordinates
    current_player = game_env.current_player

    # Current tile: fortify (always succeeds here), or found city for a
    # Settler — only where a city may actually be founded (issue #51).
    # Checked first so `stop_at_first` usually costs one call and no loop.
    if unit.unit_type != "Settler" or game_env.can_found_city_at((row, col)):
        valid_move_mask[row, col] = 1
        if stop_at_first:
            return valid_move_mask

    from ..game.map import HEX_DIRECTIONS
    for dr, dc in HEX_DIRECTIONS:
        new_row = row + dr
        new_col = (col + dc) % m
        if new_row < 0 or new_row >= n:
            continue
        dest = (new_row, new_col)

        # Terrain first: the unit's movement domain must admit the tile
        if not unit.can_enter(game_env.map.get_tile(dest)):
            continue

        # An enemy on the tile makes this an attack, not a move: no slot or
        # movement-cost rule applies, and the attack always changes state.
        enemy_there = any(
            u.player != current_player for u in game_env.get_units_at(dest)
        )
        if enemy_there:
            valid_move_mask[new_row, new_col] = 1
            if stop_at_first:
                return valid_move_mask
            continue

        # Plain move: our slot must be free and the step must be payable.
        if game_env.is_slot_occupied(dest, unit.slot, current_player):
            continue
        if unit.movement_points < unit.step_cost((row, col), dest, game_env):
            continue
        valid_move_mask[new_row, new_col] = 1
        if stop_at_first:
            return valid_move_mask

    # Ranged units: enemy-occupied tiles within range AND line of sight
    # are valid targets (rules-LoS — if the unit can shoot it, it can see
    # it, so this leaks nothing under fog of war)
    if unit.get_base_ranged_strength() > 0:
        attack_range = unit.get_range()
        for player in game_env.players:
            if player is current_player:
                continue
            for enemy in player.units:
                er, ec = enemy.coordinates
                if (
                    game_env.map.distance_function((row, col), (er, ec)) <= attack_range
                    and game_env.check_line_of_sight((row, col), (er, ec))
                ):
                    valid_move_mask[er, ec] = 1
                    if stop_at_first:
                        return valid_move_mask

    return valid_move_mask


def _settler_has_valid_order(unit, game_env, n, m):
    """Whether this Settler has any order it could actually give — the
    completeness half of issue #51.

    Every unit type except the Settler can always fortify on its own tile
    (`Unit.fortify` succeeds whenever movement_points > 0), so only a Settler
    can end up with an all-zero move mask: one that cannot found a city where
    it stands and cannot afford or reach any neighbour. Offering such a unit
    for selection reproduces the livelock — `DQNAgent._greedy_action` falls
    back to the unit's own tile when no move is valid, and that action
    changes nothing, forever.

    Only emptiness is asked, so `stop_at_first` returns after the first
    order found (usually the own tile, before any loop runs).
    """
    return bool(_valid_order_mask_np(unit, game_env, n, m, stop_at_first=True).any())


def get_valid_select_mask(state, game_env):
    """Generate a mask for valid unit selections with slot support.

    Output shape: [n*m*NUM_SLOTS] — one entry per tile-slot combination.
    Index encoding: tile_index * NUM_SLOTS + slot

    A unit is offered when it is alive, has movement points left, and has at
    least one order it could actually give — see `_settler_has_valid_order`
    for that last clause (issue #51) and `_valid_order_mask_np` for what
    "actually give" means.

    `game_env` is required: masking reads the actual unit data. (The old
    state-tensor fallback, which could not distinguish slots, was unreachable
    from live code and was deleted in P2a — design doc §3.3.)

    Building the mask is a numpy operation on CPU, with a single transfer to
    `state.device` at the end (issue #42) — the original wrote one scalar
    into a freshly-allocated CUDA tensor per unit (64.7k calls/30 episodes),
    each write its own GPU kernel launch/sync.
    """
    n, m = state.shape[1], state.shape[2]
    device = state.device

    mask_np = np.zeros(n * m * NUM_UNIT_SLOTS, dtype=np.float32)
    current_player = game_env.current_player
    units = current_player.units
    if units:
        rows = np.fromiter((u.coordinates[0] for u in units), dtype=np.int64, count=len(units))
        cols = np.fromiter((u.coordinates[1] for u in units), dtype=np.int64, count=len(units))
        slots = np.fromiter((u.slot for u in units), dtype=np.int64, count=len(units))
        # The selectability predicate, kept inline in the single pass #42
        # already made over the unit list. The Settler clause (issue #51,
        # `_settler_has_valid_order`) sits behind a short-circuited `and`, so
        # a side with no Settlers pays one extra string comparison per unit.
        valid = np.fromiter(
            (
                u.health > 0 and u.movement_points > 0
                and (
                    u.unit_type != "Settler"
                    or _settler_has_valid_order(u, game_env, n, m)
                )
                for u in units
            ),
            dtype=bool, count=len(units),
        )
        tile_idx = rows[valid] * m + cols[valid]
        mask_np[tile_idx * NUM_UNIT_SLOTS + slots[valid]] = 1.0
    return torch.from_numpy(mask_np).to(device)


def adjust_mask_for_end_turn(original_mask):
    """Append an always-valid end-turn action to the selection mask."""
    device = original_mask.device
    return torch.cat([original_mask, torch.tensor([1.0], device=device)])


def get_valid_moves_mask(state, selected_pos, game_env):
    """Generate a mask for valid move destinations from the selected unit.

    selected_pos: tile_index * NUM_SLOTS + slot (slot-aware encoding)

    Valid = adjacent tile (hex adjacency) the unit's movement domain may enter
    (design doc §3.3/§7 — terrain filtering the masks never had before; water
    and mountains are now unofferable rather than illegal-but-attemptable),
    where the unit's slot is not occupied by a friendly unit and whose step
    the unit can pay for, plus enemy-occupied tiles it can attack, plus the
    current tile when fortifying (any unit) or founding a city (a Settler,
    only where `can_found_city_at` allows) would actually happen.

    `game_env` is required; the old state-tensor fallback branch (unreachable
    from live code) was deleted in P2a.

    The rules live in `_valid_order_mask_np` — see its docstring for the
    issue-#51 no-op conditions and why `get_valid_select_mask` shares it.
    The mask is accumulated in a numpy array on CPU and transferred to
    `state.device` once at the end (issue #42) — the original wrote each
    entry (per hex direction, per ranged target) into a CUDA tensor
    directly, each write its own GPU kernel launch/sync. The per-tile game
    logic itself (terrain, slot occupancy, line of sight) calls back into
    `game_env`/`Unit` and can't be vectorized without duplicating those rules.
    """
    _, n, m = state.shape
    device = state.device

    # Decode tile-slot from selected_pos
    tile_pos = selected_pos // NUM_UNIT_SLOTS
    selected_slot = selected_pos % NUM_UNIT_SLOTS

    if tile_pos >= n * m:
        return torch.zeros(n * m, device=device)

    row = tile_pos // m
    col = tile_pos % m

    selected_unit = game_env.get_unit_in_slot(
        (row, col), selected_slot, game_env.current_player
    )
    valid_move_mask = _valid_order_mask_np(selected_unit, game_env, n, m)

    return torch.from_numpy(valid_move_mask.flatten()).to(device)
