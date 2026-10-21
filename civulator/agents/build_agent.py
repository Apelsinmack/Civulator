"""Build agent: decides what each city produces using a separate DQN."""

import random

import torch
import torch.nn as nn
import torch.nn.functional as F

from .networks import horizontal_wrap_padding
from .replay_memory import ReplayMemory, Transition
from ..game.availability import city_can_build_building
from ..game.unit import Unit
from ..game.city import City
from ..torch_env import resolve_device


# Build options — index in this list = action index.
#
# Every entry is either a key of City.BUILDING_COSTS (a building) or a unit
# type with complete stats in the six unit tables; tests/test_build_options.py
# is the gate for that, and for the converse — a statted unit is either here or
# named in game/unit.py's DEFERRED_BUILD_UNITS with a reason (issue #67).
#
# Availability (#116 P2, P4, P5): an option is offered only when the city could
# start it -- the owner's techs and civics, for buildings the required
# government tier, district and building, for the Trader a free route slot
# (get_valid_build_mask) -- so the mask invariant (CLAUDE.md) holds: an offered
# option always changes the city's production.
#
# Changing this list changes the BuildNetwork output width and therefore
# invalidates previously saved build-agent weights. APPEND ONLY (#67): the
# #116 P2 buildings follow the v0.7 list, the #116 P3 units follow them, the
# #116 P4 civic- and government-gated buildings follow those, and #116 P5
# appends the Market, the Lighthouse and the Trader (which left game/unit.py's
# DEFERRED_BUILD_UNITS with the trade routes it makes).
BUILD_OPTIONS = [
    "Warrior", "Spearman", "Archer", "Horseman", "Catapult",
    "Settler", "Granary", "Slinger", "Swordsman", "Walls",
    "Monument", "Library", "University", "Shrine", "Barracks",
    "Medieval Walls", "Workshop",
    "Man-At-Arms", "Pikeman", "Crossbowman", "Knight", "Trebuchet",
    "Musketman",
    "Temple", "Amphitheater", "Ancestral Hall", "Grand Master's Chapel",
    "Market", "Lighthouse", "Trader",
]
NUM_BUILD_OPTIONS = len(BUILD_OPTIONS)

# Extra channels added to the combat state for build decisions: one
# turns-to-complete channel per build option, plus current-production progress
# and the city marker. Derived from BUILD_OPTIONS rather than hardcoded, so
# adding an option cannot silently leave it without an input channel.
NUM_BUILD_CHANNELS = NUM_BUILD_OPTIONS + 2


def options_for_width(num_options):
    """The build-option list a network of this output width plays.

    New options are only ever APPENDED to BUILD_OPTIONS, so index k means the
    same thing it always did and the first `num_options` entries are exactly
    the list a narrower (older) agent was trained on. That is what makes a
    pre-existing weights file still evaluable after a rule change adds an
    option: it keeps playing its own 7-option policy rather than being padded
    with fabricated Q-values for options it never saw.
    """
    if not 1 <= num_options <= NUM_BUILD_OPTIONS:
        raise ValueError(
            f"num_options={num_options} is outside 1..{NUM_BUILD_OPTIONS}; a "
            "wider payload than BUILD_OPTIONS means options were removed or "
            "reordered, which breaks the append-only index contract"
        )
    return BUILD_OPTIONS[:num_options]


def build_channels_for_width(num_options):
    """Extra state channels a build agent of this output width consumes."""
    return num_options + 2


class BuildNetwork(nn.Module):
    """Small CNN that outputs Q-values over build options.

    Input: combat state + build info channels + city marker = [batch, d, n, m]
    Output: [batch, num_options]
    """

    def __init__(self, n, m, d, kernel_size=3, conv_channels=(16, 32),
                 num_options=NUM_BUILD_OPTIONS):
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

        self.num_options = num_options
        self.fc = nn.Linear(flattened, num_options)

    def forward(self, state):
        padded = horizontal_wrap_padding(state, self.padding_size)
        x = F.relu(self.bn1(self.conv1(padded)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = x.view(x.size(0), -1)
        return self.fc(x)


def encode_build_state(combat_state, city, game_env, options=None):
    """Add build-info channels and city marker to the combat state tensor.

    Args:
        combat_state: [d, n, m] tensor from any StateEncoder
        city: City instance making the build decision
        game_env: GameEnvironment
        options: build-option list to encode. Defaults to BUILD_OPTIONS; a
            legacy agent loaded from a narrower checkpoint passes its own
            prefix (see options_for_width).

    Returns:
        [d + len(options) + 2, n, m] tensor
    """
    if options is None:
        options = BUILD_OPTIONS
    num_options = len(options)

    d, n, m = combat_state.shape
    device = combat_state.device

    extra = torch.zeros(build_channels_for_width(num_options), n, m, device=device)

    ci, cj = city.coordinates
    prod_per_turn = max(1, city.calculate_production(game_env))
    max_turns_norm = 50.0

    # Channels 0..num_options-1: turns to complete each build option, in
    # BUILD_OPTIONS order. Buildings and units are looked up in their own
    # cost table; the current stockpile is subtracted either way.
    for idx, option in enumerate(options):
        if option in City.BUILDING_COSTS:
            cost = City.BUILDING_COSTS[option]
        else:
            cost = Unit.PRODUCTION_COST.get(option, 40)
        # Subtract current stockpile if already building this type
        effective_cost = max(0, cost - city.production)
        turns = effective_cost / prod_per_turn
        extra[idx, ci, cj] = min(turns, max_turns_norm) / max_turns_norm

    # Penultimate channel: current production progress (0→1)
    if city.current_production:
        if city.current_production["type"] == "unit":
            total_cost = city.get_unit_cost(city.current_production["unit_type"])
        elif city.current_production["type"] == "district":
            raise NotImplementedError(
                "district production has no build-state encoding yet: "
                "agents get a district action with #99")
        else:
            total_cost = city.get_building_cost(city.current_production["building_type"])
        extra[num_options, ci, cj] = min(city.production / max(1, total_cost), 1.0)

    # Last channel: city marker (1.0 at this city)
    extra[num_options + 1, ci, cj] = 1.0

    return torch.cat([combat_state, extra], dim=0)


def get_valid_build_mask(city, device=None, options=None):
    """Which build options are valid for this city.

    Driven by BUILD_OPTIONS rather than by hardcoded indices, so a new option
    is masked by the rule that applies to it and never by position:

    - buildings (keys of City.BUILDING_COSTS): valid iff
      `city_can_build_building` (the owner's techs and civics, its
      government's tier, a complete required district, an owned required
      building; #116 P2, P4) and not already built —
      re-producing one it owns could not change the city's state (CLAUDE.md's
      mask invariant, #51)
    - units: valid iff `City.can_produce_unit` -- the owner
      `player_can_build` them (their `requires_tech` / `requires_civic`,
      #116 P2, P4: the opening web is Warrior, Slinger and Settler), and the
      Trader only while its owner's route capacity exceeds its routes plus
      its standing Traders (#116 P5: a Trader that could never be sent
      cannot pay off); the Settler also needs population >= 3

    The same predicates `City.produce_unit` / `produce_building` apply, so
    an option the mask offers is never refused by production.

    Returns:
        [len(options)] tensor, defaulting to NUM_BUILD_OPTIONS wide
    """
    if device is None:
        device = torch.device("cpu")
    if options is None:
        options = BUILD_OPTIONS

    mask = torch.zeros(len(options), device=device)

    for idx, option in enumerate(options):
        if option in City.BUILDING_COSTS:
            valid = option not in city.buildings and city_can_build_building(city, option)
        else:
            valid = city.can_produce_unit(option)
            if option == "Settler":
                valid = valid and city.population >= 3
        if valid:
            mask[idx] = 1.0

    return mask


class BuildAgent:
    """DQN agent for city production decisions.

    Separate from the combat DQNAgent — different state space, action space,
    and time scale (once per turn per city vs many steps per turn).
    """

    def __init__(self, n, m, d_combat, memory_size=5000, gamma=0.95,
                 learning_rate=0.001, num_options=NUM_BUILD_OPTIONS,
                 device=None):
        """num_options: how many BUILD_OPTIONS entries this agent plays.

        Defaults to all of them. A checkpoint saved before a rule change added
        an option is loaded with ITS width (scripts/evaluate.py infers it from
        the saved fc layer), so an archived run keeps evaluating the policy it
        actually learned instead of failing to load — see options_for_width.

        device: Optional torch.device to pin the network to. None (default)
            resolves via civulator.torch_env.resolve_device().
        """
        self.device = device if device is not None else resolve_device()
        self.n = n
        self.m = m
        self.d_combat = d_combat
        self.gamma = gamma
        self.options = options_for_width(num_options)
        self.num_options = num_options

        d_build = d_combat + build_channels_for_width(num_options)
        self.network = BuildNetwork(n, m, d_build, num_options=num_options).to(self.device)
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
            int: index into BUILD_OPTIONS (== self.options, which is a prefix
            of it, so the index means the same thing at any width)
        """
        build_state = encode_build_state(combat_state, city, game_env, self.options)
        mask = get_valid_build_mask(city, self.device, self.options)

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
                    next_combat_state, city, game_env, self.options
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
