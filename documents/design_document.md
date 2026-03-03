# Civulator Design Document

> **Author**: Erik (with Claude)
> **Created**: 2026-03-03
> **Status**: Draft -- guiding the refactoring

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

## 5. Next Update Focus Areas

These are the priority items for the next development push. They span game logic, agent architecture, and state representation.

### 5.1 Settlers and City Building

The game environment already defines `SettlerUnit` with a `found_city()` method, and `City` has a `produce_unit()` / `produce_building()` system. But none of this is wired into training -- agents only control warriors, and cities are static after game start.

**What needs to happen**:
- Hook city production into the turn cycle (cities already have `process_turn()`, but `current_production` is never set)
- Let agents choose what to build (see 5.2)
- Let settler units found cities via an action
- Add the "found city" action to the agent's action space (a third action type beyond move and end-turn)
- Decide starting conditions: do players start with a settler, or with a city + warriors (current)?

### 5.2 City Production Decisions (New Action Type)

The agent currently only makes unit-level decisions (select unit, move unit). City production requires a fundamentally different kind of decision: "what should this city build?"

**Design options**:

**Option A: Separate production head on the network**
Add a third network head for city production. At the start of each turn (or when a city finishes production), the agent picks from a list of buildable items. The action space becomes:
```
Turn structure:
  1. For each city needing orders → pick production (from valid build list)
  2. For each unit with movement  → select + move (existing)
  3. End turn
```

**Option B: Unified action space**
Treat city tiles as "selectable" just like unit tiles. When the agent selects a city tile, the "move" head instead outputs a production choice. This keeps the two-step architecture but overloads its meaning.

**Option C: Separate policy for production**
A simpler secondary policy (even rule-based initially) handles production. The main DQN only handles unit actions. This is the easiest to implement and lets us test settlers without redesigning the network.

**Recommendation**: Start with **Option C** (rule-based production: always build warriors). Get settlers and city founding working in the game loop first. Then graduate to Option A once the game mechanics are solid.

### 5.3 Unit Encoding in the State Tensor

Currently, units are encoded as just health and movement points on the map grid. With multiple unit types (Warrior, Archer, Spearman, Horseman, Settler, etc.), the agent needs to know *what* is on each tile, not just *that something is there*.

**Three encoding strategies**:

**Pure one-hot**: Each unit type gets its own channel.
```
Layer layout per player:
  cities | warrior_health | archer_health | spearman_health | horseman_health | settler_health | movement
```
- Pro: Preserves discrete identity. Network can learn spearman-beats-horseman from experience.
- Con: Channels grow linearly with unit types. Doesn't generalize -- adding a new unit type means adding channels and retraining from scratch.
- Con: Sparse -- most channels are zero on most tiles.

**Pure ability encoding**: Encode unit stats directly.
```
Layer layout per player:
  cities | unit_health | unit_attack | unit_defense | unit_movement | unit_range | is_ranged
```
- Pro: Compact, generalizes. A new unit type with known stats works immediately.
- Pro: Network sees that 35-attack beats 20-attack without learning it from scratch.
- Con: Loses discrete identity. Can't easily learn "spearman gets +10 vs horseman" because it doesn't know *what* the unit is, only its stats.
- Con: Multiple units on one tile still problematic (stats overwrite).

**Hybrid (recommended)**: Ability encoding + type ID.
```
Layer layout per player:
  cities | unit_health | unit_attack | unit_defense | unit_movement | unit_range | unit_type_id
```
Where `unit_type_id` is a normalized integer (e.g., Warrior=0.2, Archer=0.4, Spearman=0.6, Horseman=0.8, Settler=1.0).

- Pro: Network gets continuous stats for general reasoning AND discrete identity for learning special interactions.
- Pro: Adding a unit type only requires assigning a new ID value, not adding channels.
- Con: The type ID is ordinal, which implies a meaningless ordering. Could mitigate by using multiple binary channels (a compact one-hot within the ability encoding), but this adds channels back.

**Alternative hybrid**: Ability encoding + a small one-hot block.
```
Layer layout per player:
  cities | unit_health | unit_attack | unit_defense | unit_movement | unit_range | is_melee | is_ranged | is_cavalry | is_siege | is_civilian
```
This encodes the *class* (5 categories) rather than the specific type (8+ types). The class captures the rock-paper-scissors dynamics (melee beats anti-cav, anti-cav beats cavalry, ranged is fragile in melee). Within a class, the stats differentiate (Warrior vs Swordsman = same class, different attack power).

**Recommendation**: Start with the **class-based hybrid**. It's compact (5 boolean channels + ~5 stat channels = ~10 channels per player), captures both stats and tactical identity, and doesn't explode when adding new units within existing classes.

### 5.4 Multiple Units Per Tile

All encoding schemes above still have the problem: if two friendly units stand on the same tile, they overwrite each other in the tensor. Options:
- **Game rule**: enforce one unit per tile (like Civ 5/6). Simplest.
- **Stacking channels**: e.g., unit_1 and unit_2 channels. Rigid.
- **Sum/max aggregation**: sum health values on a tile. Loses count info but cheap.

**Recommendation**: Enforce one military unit per tile (Civ 5/6 style). Civilians (settlers, workers) can share a tile with one military unit. This is the cleanest solution and matches the game's inspiration.

---

## 6. Refactoring Roadmap

### Phase 0: CUDA Support
- ~~Install PyTorch with CUDA 12.4~~ **DONE** (2026-03-03). PyTorch 2.6.0+cu124, RTX 3070 confirmed working.

### Phase 1: Clean Foundation (do first)

1. **Consolidate to one version**. Move `v2_debugging` contents to a clean `src/` or `civulator/` directory at the project root. Archive all old version folders.
2. **Archive C# code**. Move to an `archive/csharp/` folder.
3. **Clean pyCiv.py**:
   - Remove all `import torch`, `import torch.nn`, etc.
   - Remove all commented-out old code (hundreds of lines)
   - Fix the `done` initialization bug
   - Fix the `reset()` bug (`self.__class__.Player`)
   - Initialize `self.done = False` in `__init__`
4. **Split pyCiv.py into modules**:
   - `game/terrain.py` -- Terrain class
   - `game/tile.py` -- Tile class
   - `game/map.py` -- Map class (hex grid, adjacency, pathfinding, wrapping)
   - `game/unit.py` -- Unit base class + all unit subclasses
   - `game/city.py` -- City class
   - `game/player.py` -- Player class
   - `game/environment.py` -- GameEnvironment class
   - `game/__init__.py` -- public API

### Phase 2: Agent Refactoring

5. **Extract StateEncoder** as an abstract base class.
6. **Fix the move masking** to use hex adjacency.
7. **Fix Q-value computation** -- don't sum select + move Q-values.
8. **Reintroduce target network** for training stability.
9. ~~**CUDA support**~~ -- **DONE**. PyTorch 2.6.0+cu124 installed, RTX 3070 working.
10. **Clean up agent code**: remove duplicate `main()` from `GlobalDQNetworkSelectingAndMovingMultipleAgents.py` (keep only `main_trainer.py` entry point).

### Phase 3: Training Improvements

11. **Reward shaping** -- document and systematize the reward function.
12. **Longer training runs** with GPU acceleration.
13. **Evaluation framework** -- run trained agents against random/heuristic baselines.
14. **Tensorboard logging** for training curves.

### Phase 4: Game Enrichment

15. **Better pathfinding** (A* with terrain costs).
16. **Fog of war** in the Python environment.
17. **More map generation types** (currently all map types → basic random).
18. **Unit production queue** (cities produce units over multiple turns).

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
