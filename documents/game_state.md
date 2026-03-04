# Civulator — Current Game State

> **Last updated**: 2026-03-04

This document describes exactly what is currently implemented and active in the game,
what exists in code but isn't used yet, and the roadmap for what comes next.

---

## Currently Active (What the agents actually play)

### Map
- **4 rows x 8 columns** hex grid with cylindrical wrapping (horizontal wrap, no vertical)
- **Terrain types**: Plains (30%), Grassland (30%), Desert (10%), Tundra (10%), Hills (10%), Woods (5%), Mountain (5%)
- **Features**: Woods and Rainforest randomly placed on eligible terrain (~20% and ~10% chance)
- **Terrain effects**: Movement costs (Hills/Woods/Rainforest = 2 MP, Mountain = impassable), defense modifiers (Hills/Woods/Rainforest = +3, Marsh = -2)
- **Note**: Terrain IS affecting gameplay but the agent state encoder does NOT include terrain — agents are blind to it

### Players
- **2 players**, each starting with:
  - 1 city (capital)
  - 3 Warriors placed on adjacent hex tiles

### Units (Active)
- **Only Warriors** are spawned (starting 3 + city production)
  - Movement: 2 MP/turn
  - Combat strength: 20
  - Health: 100 HP
  - Can fortify (+3/+6 defense bonus after 1/2 turns)
  - Can attack (melee only)
  - **Healing**: +10 HP/turn base, +20 HP/turn if fortified, capped at 100

### Combat
- **Civ6 formula**: `damage = 30 * e^(0.04 * strength_diff) * random(0.8, 1.2)`
- Melee only (attacker and defender both take damage)
- Health penalty: `-10 * (100 - HP) / 100` applied to combat strength
- Terrain defense modifiers apply when defending
- Fortification bonus applies when defending
- Unit killed when health <= 0

### Cities
- **Health**: 200 HP, **Defense**: 20
- **Production**: 1 + population per turn (starts at 2/turn with pop 1)
- **Food**: 2 * population per turn
- **Growth**: population +1 when food >= population * 20
- **Auto-produces Warriors** (cost 40, ~20 turns at pop 1), auto-queues next after completion
- New units spawn ON the city tile (Civ-style stacking)
- City capture: walk a unit onto enemy city tile → ownership transfers
- Player eliminated when all cities lost

### Win Conditions
- **Elimination**: destroy all enemy cities (other player has 0 cities)
- **Turn limit** (250): highest score wins (10 * cities + units), tie = no winner

### Agent Architecture
- **DQN with Select-and-Move**: two-headed CNN
  - Select head: picks which unit to activate (or end turn)
  - Move head: picks where that unit goes
  - Q-value decomposition: Q(s, a_select, a_move) = Q_select + Q_move
- **State tensor**: 5 channels on 4x8 grid
  - [0] Own cities (100 at city tiles)
  - [1] Own unit health (raw HP value)
  - [2] Own unit movement points
  - [3] Enemy cities (-100)
  - [4] Enemy unit health (negative)
- **36,001 parameters** total (both heads combined)
- **Epsilon-greedy** with epsilon=0.3
- **Replay memory**: 10,000 transitions per agent

### Training
- Fixed random seed (42)
- Adam optimizer, lr=0.001
- Gamma (discount): 0.9
- Batch size: 32
- MSE loss on Bellman equation
- Checkpoints saved every episode to `weights/`

---

## Implemented But Not Active

These classes/systems exist in code but are not spawned or used during training:

### Unit Types (code exists in `civulator/game/unit.py`)
| Unit | Melee Str | Ranged Str | Range | Move | Cost | Class |
|------|-----------|------------|-------|------|------|-------|
| Warrior | 20 | - | 1 | 2 | 40 | Melee |
| Archer | 15 | 25 | 2 | 2 | 60 | Ranged |
| Swordsman | 35 | - | 1 | 2 | 90 | Melee |
| Spearman | 25 | - | 1 | 2 | 50 | Anti-cavalry |
| Horseman | 36 | - | 1 | 4 | 80 | Cavalry |
| Catapult | 25 | 45 | 2 | 2 | 120 | Siege |
| Settler | 0 | - | 0 | 2 | 120 | Civilian |
| Worker | 0 | - | 0 | 2 | 50 | Civilian |

**Class advantages** (coded):
- Spearman vs Horseman: +10 melee
- Warrior/Swordsman vs Spearman: +5 melee
- Archer vs Horseman: -5 ranged

### City Production System
- `produce_unit(unit_type)` and `produce_building(building_type)` exist
- `complete_unit_production()` places units on city tile (Civ-style stacking)
- Building types defined: Granary (60), Monument (50), Walls (100), Workshop (120), Factory (240)
- **Partially active**: auto-produces Warriors; building production and diverse unit types not yet triggered

### Settler / City Founding
- `SettlerUnit.found_city()` exists
- `GameEnvironment.can_found_city_at()` checks terrain and min distance (3 tiles from other cities)
- **Not active because settlers aren't spawned**

### Workers / Improvements
- `WorkerUnit.build_improvement()` exists
- Farm, Mine, Plantation, Camp, Pasture, Quarry, Fishing Boats, Oil Well defined
- **Not active because workers aren't spawned**

### Ranged Combat
- Archer and Catapult have ranged `attack()` overrides with range checks and line-of-sight
- **Not active because only Warriors are spawned**

### Rivers
- `Map.rivers` set exists, `has_river_between()` works, movement cost +1 for crossing
- **Not active because `generate_map()` doesn't create rivers**

---

## Known Issues / Limitations

1. **No terrain in state** — agents can't see hills, mountains, forests
2. **Multiple units on same tile overwrite** — state tensor stores one health value per tile, second unit on same tile overwrites the first
3. **No target network** — DQN uses same network for current and target Q-values (known to cause instability)
4. **Q-value summation** — select + move Q-values are summed (branching DQN approach, documented, may need revisiting)
5. **Pathfinder is greedy** — doesn't account for terrain costs, should be A*
6. **Archer distance uses Manhattan** not hex distance (line 311-313 in unit.py)
7. ~~Cities don't build anything~~ — **Fixed**: auto-produce warriors
8. **Reward shaping limited** — combat rewards (damage * 0.1, +10 kill, -10 death, +20 capture) but no exploration or map control rewards

---

## Roadmap (Next Implementations)

### Phase 1: Core Military (next)
- [ ] Add Spearman, Archer, and Horseman to starting units (or city production)
- [ ] Activate city production queue (rule-based initially: produce warriors)
- [ ] Test that combat class advantages work in practice
- [ ] Verify ranged combat works correctly with hex distance

### Phase 2: City Building
- [ ] Implement settler spawning via city production
- [ ] Activate `found_city()` as an agent action
- [ ] Agent or rule decides what to build (start with rule-based)
- [ ] Production decisions become a neural network choice later

### Phase 3: State Space Redesign
- [ ] Add terrain layer to state tensor
- [ ] Unit encoding: ability-based features (HP, attack, defense, movement, range) + one-hot class (melee, spear, ranged, cavalry, siege)
- [ ] Handle multi-unit tiles properly (unit stacking)
- [ ] Consider adding a "threat map" or "visibility" layer

### Phase 4: Training Improvements
- [ ] Add target network (standard DQN stability technique)
- [ ] Reward shaping: damage dealt, proximity to enemy, map control
- [ ] Epsilon decay schedule
- [ ] Larger replay memory, prioritized replay

### Phase 5: Performance Profiling
- [ ] Profile simulation loop (timeit per operation: pathfinding, combat, state encoding, network forward/backward)
- [ ] Identify bottleneck — if one operation dominates, consider Cython for that specific piece
- [ ] Decisions on optimization approach driven by profiling results

### Phase 6: Scale
- [ ] Larger maps (8x16, 16x32)
- [ ] More players (3-4)
- [ ] Vectorized environments for faster training
