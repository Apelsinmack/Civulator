# Civulator Design Document

> **Author**: Erik (with Claude)
> **Created**: 2026-03-03
> **Last updated**: 2026-03-07
> **Status**: Refactoring complete. Now a living reference for architecture decisions.

---

## 1. Design Philosophy

The simulation should know nothing about RL. The agent should know nothing about game internals beyond what it observes. This separation lets us:

- **Compare agents** with different state representations playing the same game
- **Test the game** independently of any learning algorithm
- **Swap RL algorithms** without touching game code

### Three Clean Layers

```
+---------------------------+
|    Training / Experiment   |  Orchestrates episodes, logging, checkpoints
+---------------------------+
|         Agent(s)           |  Owns: StateEncoder, Network, ActionDecoder, ReplayMemory
+---------------------------+
|    Game Environment        |  Pure simulation. step() / reset() / render()
+---------------------------+
```

---

## 2. Game Environment (pyCiv)

### 2.1 Responsibilities

- Manage the game state: map, players, units, cities, terrain, turn order
- Accept actions and return observations, rewards, done flag (Gym-like interface)
- Provide raw state access so agents can build their own representations
- Enforce game rules (movement, combat, city founding, production)

### 2.2 Interface

```python
class GameEnvironment:
    def reset() -> RawGameState
    def step(action: Action) -> (RawGameState, reward: float, done: bool, info: dict)
    def get_valid_actions() -> list[Action]
    def render(mode='ascii')

    # Properties
    @property map: Map
    @property players: list[Player]
    @property current_player: Player
    @property done: bool
```

### 2.3 Action Format

Currently: `action_matrix = [select_coords, order_coords]` as numpy arrays.

Proposed: keep this simple format but add an explicit `EndTurn` action type rather than encoding it as selecting tile `(n, 0)`.

```python
@dataclass
class Action:
    action_type: str  # "move", "attack", "fortify", "end_turn", "found_city"
    unit_coords: tuple | None
    target_coords: tuple | None
```

**Discussion point**: Is a richer action format worth it, or does it complicate the action space for the RL agent? For now, the agent can still work with (select, move) indices internally and the environment translates.

### 2.4 Key Classes

#### Map
- Hexagonal grid stored as `np.ndarray` of `Tile` objects
- Cylindrical wrapping (horizontal wrap, no vertical wrap)
- Hex adjacency with even/odd row offsets (already implemented, works well)
- Pathfinding (current greedy algorithm works but should eventually use A* for terrain costs)
- Distance function for hex + cylindrical wrap
- **Note**: Consider sharing the Tile/Map pattern with Breach (see Section 6)

#### Tile
- Coordinates, terrain type, features (Woods, Rivers), improvements
- References to units and city on the tile
- Terrain-derived properties: defense bonus, movement cost, production values

#### Unit
- Position, health, movement points, fortification level
- Combat: Civ6-inspired damage formula `30 * e^(0.04 * strength_diff) * random(0.8, 1.2)`
- Unit types define stats via lookup dicts (combat strength, ranged strength, range, movement, production cost)
- Subclasses for special behavior: ArcherUnit (ranged attack), CatapultUnit (siege), SettlerUnit (found city)

#### City
- Health, population, food, production, buildings, build queue
- Produces units and buildings over turns
- Can be captured (ownership transfer)

#### Player
- Owns units and cities
- Turn processing: start_turn (reset movement, process cities), end_turn (check defeat)
- Dead when no cities remain

### 2.5 Things to Fix in the Game

1. **Remove all PyTorch/RL imports** from pyCiv.py. The game module should not depend on torch.
2. **Clean up commented-out code**. Hundreds of lines of old implementations are commented out.
3. **Pathfinding**: Current greedy pathfinder doesn't account for terrain costs or obstacles. Works for simple cases but will need A* eventually.
4. **`done` attribute**: Not initialized in `__init__`, only set in `reset()`. Should be initialized.
5. **`reset()` bug**: References `self.__class__.Player` instead of just `Player`.
6. **Map generation**: All map types (`continents`, `archipelago`, `pangaea`) currently fall through to `_generate_basic_map()`. Fine for now, but should be noted.
7. **Unit placement from cities**: Uses 8-directional grid search instead of hex adjacency.

---

## 3. Agent Architecture

### 3.1 Responsibilities

Each agent independently:
- **Encodes** the raw game state into its own tensor representation
- **Selects actions** via its policy network
- **Stores experience** in replay memory
- **Learns** from batched experience

### 3.2 StateEncoder (new abstraction)

This is the key decoupling. Currently `build_state_tensor()` is a method on `DQNAgent`. It should be a separate, swappable component.

```python
class StateEncoder(ABC):
    @abstractmethod
    def encode(self, game_env: GameEnvironment, player_index: int) -> torch.Tensor:
        """Convert raw game state to a tensor for the network."""

    @abstractmethod
    def get_tensor_shape(self) -> tuple:
        """Return (depth, height, width) of the output tensor."""

class BasicStateEncoder(StateEncoder):
    """Current encoder: [d, n, m] with cities, health, movement per player."""

class TerrainAwareEncoder(StateEncoder):
    """Adds terrain channels to the state tensor."""

class FogOfWarEncoder(StateEncoder):
    """Only encodes tiles the player has explored/can see."""
```

This lets us run experiments like:
- Agent A uses `BasicStateEncoder` (5 channels)
- Agent B uses `TerrainAwareEncoder` (8 channels)
- Both play the same game, we compare win rates

### 3.3 Network Architecture

Current: `SelectAndMoveNetwork` with two CNN heads (select head + move head).

**Issues to address**:
1. **Q-value summation**: `q = select_q + move_q` is not principled. The combined (select, move) pair is one action -- it should have one Q-value.
2. **No target network**: Dropped from v1. Should be reinstated for training stability.
3. **Softmax output**: Using softmax + multinomial sampling, but this is a DQN (value-based), not policy gradient. Should output raw Q-values and use epsilon-greedy on them.

**Proposed fix for Q-values**: Treat the network as computing advantage functions. The select head picks which unit, then the move head (conditioned on selection) picks where. The Q-value is the move head's output only (since the selection is already committed). This is cleaner than summing.

### 3.4 Cylindrical Wrap Padding

The `horizontal_wrap_padding()` function is a genuine innovation -- it copies edge columns to the opposite side before convolution, so the CNN correctly perceives the cylindrical topology. Keep this.

### 3.5 Move Masking Bug

`get_valid_moves_mask()` currently uses 8-directional adjacency:
```python
for dr in [-1, 0, 1]:
    for dc in [-1, 0, 1]:
```
This is a regular grid, not hex. Should use the same hex adjacency as `Map.get_adjacent_tiles()` with even/odd row offsets.

---

## 4. Training Layer

### 4.1 Responsibilities
- Episode loop: reset env, run until done, collect stats
- Manage multiple agents (one per player)
- Epsilon scheduling
- Checkpoint saving/loading
- Win rate tracking and plotting

### 4.2 Pending Transitions

The multi-agent pending transition mechanism is correct in concept: when Player 1 acts, we don't know Player 1's next state until it's Player 1's turn again. The `store_pending_transition` / `complete_pending_transition` pattern handles this. Keep it.

---

## 5. Architecture Decisions (Historical + Current)

### 5.1 City Production — RESOLVED (v0.4.0)

**Chosen**: Option A — Separate BuildAgent (DQN) with its own network, replay memory,
and optimizer. Runs at turn boundaries. See `civulator/agents/build_agent.py`.

### 5.2 Unit Encoding — RESOLVED (v0.3.1)

**Chosen**: Class-based hybrid (EnhancedStateEncoder, 25 channels).
5 class one-hot + 6 stat channels per player side + cities + terrain.
See `documents/state_spaces.md`.

### 5.3 Multiple Units Per Tile — PARTIALLY RESOLVED

Unit spawn stacking bug fixed in v0.3.1 (try center → adjacent → defer).
State tensor still overwrites if two units share a tile.
Enforcing one-military-unit-per-tile (Civ 5/6 style) is the planned fix.

### 5.4 FullyConvNetwork Architecture (v0.4.0)

Map-size independent design using only conv layers (no FC).
Shared backbone: one set of conv layers, separate 1x1 conv heads.
Same weights work on any map size — critical for future scaling.

### 5.5 Scaling Architecture (future ideas, 2026-03-07)

**Specialist networks as state channels**: Lightweight networks that pre-digest
information on different timescales, feeding their output as extra channels to the
main policy:
- Settlement value heatmap (recomputed on city founding)
- Threat map (updated per step)
- Economic potential map (updated per turn)

**Terrain caching**: Terrain is static. Compute conv features for terrain channels
once at game start, cache and reuse every step.

**Sparse convolutions**: For large maps where units occupy <10% of tiles.
Libraries like MinkowskiEngine compute only at non-zero positions.

---

## 6. Refactoring Roadmap (Status as of v0.4.0)

### Phase 0: CUDA Support — DONE
PyTorch 2.6.0+cu124, RTX 3070 confirmed working.

### Phase 1: Clean Foundation — DONE (v0.1.0)
Package structure, module split, C# archived, bugs fixed.

### Phase 2: Agent Refactoring — MOSTLY DONE
- StateEncoder abstraction — DONE
- Hex adjacency in move masking — DONE
- Q-value summation — kept as branching DQN (documented, works)
- Target network — NOT DONE (Priority B4)
- Agent code cleanup — DONE

### Phase 3: Training Improvements — PARTIAL
- Reward shaping — basic combat rewards in place
- GPU training — DONE (~0.12s/episode)
- Evaluation framework — tournament script exists
- Tensorboard logging — NOT DONE

### Phase 4: Game Enrichment — MOSTLY DONE (v0.4.0)
- City production queue — DONE (build agent)
- All unit types — DONE
- Pathfinding — still greedy (A* TODO)
- Fog of war — NOT DONE
- Map generation — still basic random

### Phase 5: Performance Scaling (when needed)
- Vectorized environments (parallel games on CPU, batched GPU)
- Cython for hot paths (hex adjacency, pathfinding, combat)
- C++ game engine with Python bindings (only for large maps)
- Sparse convolutions for large maps
- Terrain feature caching

---

## 7. Shared Infrastructure with Breach

The Tile/Map system (hex grid, terrain, features, adjacency) could be shared between Civulator and Breach. Document the shared patterns and consider a common base module if the games converge enough.

Specific things to align:
- Tile representation (coordinates, terrain, features)
- Hex adjacency calculation (even/odd row offsets)
- Map wrapping behavior
- Terrain modifier system

For now: note the intent, revisit after the Civulator refactoring is complete and we can see what Breach needs.

---

## 8. File Structure After Refactoring

```
Civulator/
+-- CLAUDE.md                      # Project overview
+-- documents/
|   +-- design_document.md         # This file
+-- civulator/                     # Main package
|   +-- game/                      # Pure game simulation
|   |   +-- __init__.py
|   |   +-- environment.py         # GameEnvironment
|   |   +-- map.py                 # Map (hex grid)
|   |   +-- tile.py                # Tile
|   |   +-- terrain.py             # Terrain types and modifiers
|   |   +-- unit.py                # Unit + subclasses
|   |   +-- city.py                # City
|   |   +-- player.py              # Player
|   +-- agents/                    # RL agents
|   |   +-- __init__.py
|   |   +-- base_agent.py          # Abstract agent interface
|   |   +-- dqn_agent.py           # DQN implementation
|   |   +-- state_encoders.py      # StateEncoder ABC + implementations
|   |   +-- networks.py            # SelectAndMoveNetwork, wrap padding
|   |   +-- replay_memory.py       # ReplayMemory
|   +-- training/                  # Training orchestration
|   |   +-- __init__.py
|   |   +-- trainer.py             # Episode loop, multi-agent coordination
|   |   +-- evaluation.py          # Win rate tracking, plotting
|   +-- utils/                     # Shared utilities
|       +-- ascii_display.py       # ASCII map rendering
+-- scripts/
|   +-- train.py                   # CLI entry point
+-- weights/                       # Saved model weights
+-- stats/                         # Training statistics
+-- archive/                       # Old code kept for reference
|   +-- csharp/                    # Patrik's C# engine
|   +-- python_versions/           # v1/, v2/, deepQlearningBot/, etc.
+-- README.md
```
