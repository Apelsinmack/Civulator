# Civulator — Current Game State

> **Last updated**: 2026-03-07

This document describes exactly what is currently implemented and active in the game,
what exists in code but isn't used yet, and the roadmap for what comes next.

---

## Currently Active (What the agents actually play)

### Map
- **4 rows x 8 columns** hex grid with cylindrical wrapping (horizontal wrap, no vertical)
- **Terrain types**: Plains (30%), Grassland (30%), Desert (10%), Tundra (10%), Hills (10%), Woods (5%), Mountain (5%)
- **Features**: Woods and Rainforest randomly placed on eligible terrain (~20% and ~10% chance)
- **Terrain effects**: Movement costs (Hills/Woods/Rainforest = 2 MP, Mountain = impassable), defense modifiers (Hills/Woods/Rainforest = +3, Marsh = -2)
- **Terrain in state**: BasicStateEncoder does NOT include terrain; EnhancedStateEncoder includes terrain cost channel

### Players
- **2 players**, each starting with:
  - 1 city (capital)
  - 3 Warriors placed on adjacent hex tiles

### Units (Active)
All unit types are available via city production (build agent decides):

| Unit | Melee Str | Ranged Str | Range | Move | Cost | Class |
|------|-----------|------------|-------|------|------|-------|
| Warrior | 20 | - | 1 | 2 | 40 | Melee |
| Archer | 15 | 25 | 2 | 2 | 60 | Ranged |
| Swordsman | 35 | - | 1 | 2 | 90 | Melee |
| Spearman | 25 | - | 1 | 2 | 50 | Anti-cavalry |
| Horseman | 36 | - | 1 | 4 | 80 | Cavalry |
| Catapult | 25 | 45 | 2 | 2 | 120 | Siege |
| Settler | 0 | - | 0 | 2 | 120 | Civilian |

**Class advantages** (active):
- Spearman vs Horseman: +10 melee
- Warrior/Swordsman vs Spearman: +5 melee
- Archer vs Horseman: -5 ranged

**Unit abilities**:
- Fortify: +3/+6 defense bonus after 1/2 turns of inaction
- Healing: +10 HP/turn base, +20 HP/turn if fortified, capped at 100
- Ranged attack: Archers and Catapults attack at range 2, no counter-damage

### Combat
- **Civ6 formula**: `damage = 30 * e^(0.04 * strength_diff) * random(0.8, 1.2)`
- Melee: attacker and defender both take damage
- Ranged: no counter-damage to attacker
- Health penalty: `-10 * (100 - HP) / 100` applied to combat strength
- Terrain defense modifiers apply when defending
- Fortification bonus applies when defending
- Unit killed when health <= 0

### Cities & Economy
- **Health**: 200 HP, **Defense**: 20
- **Population**: starts at 1, grows with food surplus
- **Food**: city center + worked tiles, consumed 2 per pop per turn
- **Growth threshold**: 15 + 10 * (pop - 1) food surplus to grow
- **Starvation**: negative net food depletes surplus; at zero, lose 1 pop
- **Production**: city center + worked tiles, minimum 1 per turn
- **Tile assignment**: each pop works one adjacent tile (priority: food desc, prod desc)
- **Build agent** (DQN): decides what each city builds from BUILD_OPTIONS

### Build Options (agent-controlled)
| Index | Option | Cost | Requirement |
|-------|--------|------|-------------|
| 0 | Warrior | 40 | - |
| 1 | Spearman | 50 | - |
| 2 | Archer | 60 | - |
| 3 | Horseman | 80 | - |
| 4 | Catapult | 120 | - |
| 5 | Settler | 120 | pop >= 3 |
| 6 | Granary | 60 | not already built |

### City Founding (Settlers)
- Build agent can queue Settlers (requires pop >= 3)
- Select settler → order to same tile → founds city (+15 reward)
- Minimum 3 tiles from other cities
- New city starts with pop 1, no buildings
- Settler consumed on founding

### Win Conditions
- **Elimination**: destroy all enemy cities (other player has 0 cities)
- **Turn limit** (200): highest score wins (10 * cities + units), tie = no winner

### Agent Architecture
- **DQN with Select-and-Move**: FullyConvNetwork (map-size independent)
  - Shared CNN backbone (2 conv layers with cylindrical wrap padding)
  - Select head: 1x1 conv → per-tile Q-value + learnable end-turn Q
  - Move head: backbone features + position marker → 3x3 conv → 1x1 conv
  - Q-value decomposition: Q(s, a_select, a_move) = Q_select + Q_move
- **Build agent**: Separate DQN (2 conv layers + FC → Q-values over build options)
- **State tensor**: 5 channels on 4x8 grid (BasicStateEncoder)
  - [0] Own cities (100 at city tiles)
  - [1] Own unit health (raw HP value)
  - [2] Own unit movement points
  - [3] Enemy cities (-100)
  - [4] Enemy unit health (negative)
- **~15,139 parameters** (FullyConvNetwork with shared backbone)
- **Epsilon-greedy** with epsilon=0.3 (no decay yet)
- **Replay memory**: 10,000 transitions per agent

### Training
- Fixed random seed (42)
- Adam optimizer, lr=0.001
- Gamma (discount): 0.9
- Batch size: 32
- MSE loss on Bellman equation
- ~0.12s per episode on RTX 3070

---

## Implemented But Not Active

### Worker Units
- `WorkerUnit.build_improvement()` exists
- Farm, Mine, Plantation, Camp, Pasture, Quarry, Fishing Boats, Oil Well defined
- **Not active because workers aren't in BUILD_OPTIONS**

### Rivers
- `Map.rivers` set exists, `has_river_between()` works, movement cost +1 for crossing
- **Not active because `generate_map()` doesn't create rivers**

### EnhancedStateEncoder (25 channels)
- Full unit class one-hot, stats, terrain, cities
- Implemented and tested but not used in current training runs
- See `documents/state_spaces.md` for channel layout

---

## Known Issues / Limitations

1. **No target network** — DQN uses same network for current and target Q-values (training instability)
2. **Q-value summation** — select + move Q-values are summed (branching DQN approach)
3. **Multiple units on same tile overwrite** — state tensor stores one health value per tile
4. **Pathfinder is greedy** — doesn't account for terrain costs, should be A*
5. **Archer distance uses Manhattan** not hex distance
6. **No build order tracking** — can't see what agents choose to build (TODO)
7. **Epsilon fixed at 0.3** — no decay schedule
8. **Settler usage unverified** — code is wired up but unclear if agents learn to use settlers

---

## Roadmap (Next Steps)

### Immediate
- [ ] Add build order tracking to trainer.py (what do agents build first/second?)
- [ ] Run shared vs separate backbone tournament
- [ ] Verify settlers are being built and used in training
- [ ] Update CHANGELOG.md with v0.4.0 results

### A5: Alliances and Diplomacy (next major feature)
- [ ] Add DiplomacyState tracking war/peace between all player pairs
- [ ] Add diplomacy actions to select head (declare war / propose peace)
- [ ] Update state encoder with relationship channels (own/ally/neutral/enemy)
- [ ] Add aggression tracking (windowed attack history)
- [ ] Start with 3-player games (N=3)
- See `implementation_plan.md` section A5 for full design

### B2: Hierarchical Q-Learning
- [ ] Select head aware of move quality: train using `max_{a_move} Q(s, a_select, a_move)`

### B3: Temporal State Stacking
- [ ] Stack last K state tensors as extra channels (like Atari DQN's 4 frames)

### B4: Training Improvements
- [ ] Target network
- [ ] Epsilon decay schedule
- [ ] Prioritized replay

### Scaling (future)
- [ ] Sparse convolutions for larger maps
- [ ] Terrain feature caching (static channels computed once)
- [ ] Specialist networks (settlement value, threat map) as state channels
- [ ] Larger maps (8x16, 16x32), more players (3-4)
