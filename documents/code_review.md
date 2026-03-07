# Civulator — Code Review Notes

> **Reviewed**: 2026-03-07
> **Scope**: All active code in `civulator/` package

---

## Overall Assessment

The codebase is **well-structured and easy to follow**. The package split (game/agents/training/utils) is clean, responsibilities are clear, and the code reads naturally. Most modules are small and focused. No major refactoring needed — the improvements below are incremental.

**Strengths**:
- Clean separation: game knows nothing about RL, agents know nothing about game internals
- Consistent style throughout
- Good docstrings on public methods
- State encoder abstraction allows easy experimentation

**Areas to improve**:
- Pathfinding (greedy → A*)
- Some dead code / unused features that could be trimmed
- A few places where logic is duplicated

---

## Module-by-Module Review

### `game/terrain.py` — Grade: A
- 59 lines, pure data. Three lookup dicts for defense, movement, and production.
- **No issues.** Clean, simple, does one thing.

### `game/tile.py` — Grade: A-
- 89 lines. Tile class with terrain, features, improvements, units, city.
- Well-structured. `update_terrain_properties()` correctly recalculates on feature changes.
- **Minor**: `import numpy as np` is only used for `production_value` default — the numpy arrays in `Terrain.PRODUCTION_VALUES` could just be tuples since they're only read as `[0]` and `[1]`. Would remove the numpy dependency from this module. Low priority.

### `game/map.py` — Grade: B
- 217 lines. Hex grid, adjacency, pathfinding, line of sight.
- **Hex adjacency** (`get_adjacent_tiles`, `get_adjacent_coords`): duplicated logic. Both methods compute the same even/odd row directions. Could extract a `_hex_directions(row)` helper. Low priority.
- **`path_finder()`** (line 139-194): **Greedy and terrain-unaware.** This is the biggest issue in the game module. It walks straight toward the destination ignoring terrain costs, obstacles (mountains, other units), and hex topology properly. On a cluttered map with many units, this produces bad paths. **Needs A\* replacement.** See TODO below.
- **`distance_function()`** (line 114-137): Uses a formula that may not be correct for offset hex coordinates. The `dx * dy > 0` check is a heuristic. Should verify with hex distance formula: `(abs(dq) + abs(dr) + abs(ds)) / 2` using cube coordinates. Works for small maps but may have edge cases.
- **`check_line_of_sight()`**: Uses the greedy pathfinder to trace the line, which is not geometrically correct (a path isn't a line). Works for range-2 units on small maps but would need proper hex line drawing for larger maps/ranges.

### `game/unit.py` — Grade: A
- 462 lines. Base class + 8 subclasses.
- Well-organized: static data tables at top, methods below, subclasses at bottom.
- Combat formula is well-documented with Civ6 reference.
- `move()` handles both adjacent and pathfinder-based movement cleanly.
- **Minor**: `ArcherUnit.attack()` and `CatapultUnit.attack()` are identical — could be a shared `RangedUnit` mixin or method on the base class. Low priority.

### `game/city.py` — Grade: A-
- 246 lines. City with economy, production, growth.
- Economy model is clean and well-commented.
- `process_turn()` has clear phase ordering (food → consume → growth → production → build).
- `complete_unit_production()` correctly handles spawn placement (center → adjacent → defer).
- **Minor**: `get_unit_cost()` creates a temporary `Unit(None, None, unit_type)` just to call `get_production_cost()`. Could use `Unit.PRODUCTION_COST[unit_type]` directly. Very minor.

### `game/player.py` — Grade: B+
- 52 lines. Small and focused.
- `start_turn()` handles unit reset, healing, city processing, and queued unit placement.
- `end_turn()` handles death detection (no cities → dead, delete all units).
- **Unused fields**: `gold`, `science`, `culture`, `technologies`, `policies` are initialized but never used. These are placeholders for future features. Fine to keep but could add a comment noting they're placeholders.

### `game/environment.py` — Grade: B+
- 418 lines. Central game controller.
- `step()` is clean: select+order interpreted as move/fortify/attack/capture.
- `_execute_attack()` handles melee/ranged, city capture, unit capture (newly added).
- `_check_game_end()` auto-advances turn when all units spent — nice QoL.
- **`_calculate_starting_locations()`**: Simple random placement. P1 always gets left half, P2 right half. This creates a systematic first-mover advantage since P1 is always "west." Could randomize which half each player gets.
- **Settler founding**: Wired up correctly (select → same tile → found city). +15 reward.
- **Missing**: No validation that units can't stack (multiple military units on same tile). The state encoder overwrites, but the game doesn't prevent it.

### `agents/networks.py` — Grade: A-
- ~420 lines (after adding FullyConvSeparateNetwork). Four network classes.
- `horizontal_wrap_padding()` is clever and well-implemented.
- `FullyConvNetwork` is the cleanest architecture — spatial Q-values via 1x1 conv, no FC layers.
- `get_valid_select_mask()` and `get_valid_moves_mask()` auto-detect encoder type by channel count. Works but fragile — adding a new encoder with a different channel count would need updating these functions.
- **`get_valid_moves_mask()`** duplicates hex direction logic (also in `map.py`). Could import from map, but the mask function needs to work on tensors without a map reference. Acceptable duplication.

### `agents/dqn_agent.py` — Grade: A-
- 210 lines. Clean DQN agent with select-and-move.
- `select_action()` → `_random_action()` / `_greedy_action()` split is readable.
- `compute_loss()` with additive Q-value decomposition is well-documented.
- Pending transition mechanism for multi-agent turn handling works correctly.
- **No target network**: This is noted as a known issue. Standard DQN uses a separate target network updated periodically. Adding this would likely improve training stability.

### `agents/build_agent.py` — Grade: A-
- 243 lines. Separate DQN for build decisions.
- Clean design: `encode_build_state()` adds build-info channels to combat state.
- `get_valid_build_mask()` handles settler pop requirement and granary uniqueness.
- Pending transition mechanism handles delayed rewards (build decision → payoff turns later).
- **Hardcoded epsilon=0.3** in the trainer call. Should be configurable (same issue as combat agent).

### `agents/state_encoders.py` — Grade: A
- 214 lines. Two encoders: Basic (5ch) and Enhanced (25ch).
- `EnhancedStateEncoder` is thorough: unit class one-hot, normalized stats, terrain, defense bonuses.
- Clean normalization with documented constants.
- **Missing from EnhancedStateEncoder**: Settler and Worker unit types not in `CLASS_INDEX`. They'd default to index 0 (melee), which is wrong. Should add a civilian class or handle them explicitly.

### `agents/replay_memory.py` — Grade: A
- Small, standard implementation. Named tuple transitions, random sampling. No issues.

### `training/trainer.py` — Grade: B+
- ~270 lines (after build tracking). The training loop.
- Turn boundary detection for build agent works correctly.
- Build order tracking now captures what agents build.
- **Complexity**: The main loop handles combat agent transitions, build agent transitions, turn boundaries, and reward accumulation. It's getting complex but still readable.
- **Hardcoded hyperparameters**: epsilon=0.3, no decay. Should be parameterized.
- **No target network updates**: Would need to add periodic `target_net.load_state_dict(policy_net.state_dict())` calls.

### `utils/ascii_display.py` — Grade: B+
- 66 lines. Simple ASCII renderer.
- Shows unit type initial + player number + movement indicator.
- Shows health and player stats.
- **Only shows first character of unit type**: "W" for Warrior but also "W" for Worker. Could collide. Use "Wa"/"Wo" or a mapping.

---

## Priority Improvements

### High Priority
1. **A\* pathfinding** — Replace `map.path_finder()` greedy approach with proper A\* that respects terrain costs, avoids mountains, and handles unit blocking. Critical as maps get more units.
2. **Add Settler/Worker to EnhancedStateEncoder CLASS_INDEX** — Currently defaults to melee (index 0), hiding civilian units from the network.

### Medium Priority
3. **Target network** for both combat and build DQN agents.
4. **Epsilon decay** — configurable schedule instead of fixed 0.3.
5. **One-unit-per-tile enforcement** — prevent military unit stacking in game rules.
6. **Unified training CLI** (B5 in implementation plan).

### Low Priority
7. Extract hex direction helper in map.py to reduce duplication.
8. Fix `get_unit_cost()` in city.py to use static lookup instead of creating temp Unit.
9. Randomize starting position halves to reduce P1 bias.
10. ASCII display collision for unit type initials.

---

## A\* Pathfinding TODO

The current `map.path_finder()` is a greedy walker that:
- Ignores terrain movement costs
- Doesn't avoid mountains or impassable terrain
- Doesn't account for unit blocking
- Uses non-hex diagonal movement logic

**Replacement spec**:
- Standard A\* over the hex grid
- Cost function: terrain movement cost per tile + river crossing penalty
- Blocked tiles: mountains, friendly units (enemy units are attack targets, not obstacles for pathing)
- Heuristic: hex distance (admissible for hex grids)
- Respect cylindrical wrapping
- Return: list of coordinates from start to end (excluding start)

**Scope**: ~50-80 lines. Replace the body of `map.path_finder()`, keep the same interface. The rest of the codebase (unit.move(), check_line_of_sight()) calls path_finder() and would benefit automatically.
