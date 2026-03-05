# Civulator — State Space Reference

> **Last updated**: 2026-03-05
> **Purpose**: Complete specification of all tensor representations used by neural networks.
> Intended as the definitive reference for both implementation and paper write-up.

---

## 1. Combat State Space (EnhancedStateEncoder)

**Shape**: `[25, n, m]` (25 channels on an n×m hex grid)

Used by the Select-and-Move DQN for tactical decisions (which unit to move, where).

### Channel Layout

| Ch | Name | Range | Description |
|----|------|-------|-------------|
| **Own unit class one-hot** | | | |
| 0 | own_melee | {0, 1} | Warrior or Swordsman present |
| 1 | own_spear | {0, 1} | Spearman present |
| 2 | own_ranged | {0, 1} | Archer present |
| 3 | own_cavalry | {0, 1} | Horseman present |
| 4 | own_siege | {0, 1} | Catapult present |
| **Own unit stats** | | | |
| 5 | own_hp | [0, 1] | health / 100 |
| 6 | own_melee_str | [0, 1] | base_combat_strength / 50 |
| 7 | own_ranged_str | [0, 1] | base_ranged_strength / 50 |
| 8 | own_range | [0, 1] | range / 2 |
| 9 | own_movement | [0, 1] | movement_points / 4 |
| 10 | own_defense_bonus | [0, 1] | (fortification + terrain) / 12 |
| **Enemy unit class one-hot** | | | |
| 11 | enemy_melee | {0, 1} | |
| 12 | enemy_spear | {0, 1} | |
| 13 | enemy_ranged | {0, 1} | |
| 14 | enemy_cavalry | {0, 1} | |
| 15 | enemy_siege | {0, 1} | |
| **Enemy unit stats** | | | |
| 16 | enemy_hp | [0, 1] | health / 100 |
| 17 | enemy_melee_str | [0, 1] | base_combat_strength / 50 |
| 18 | enemy_ranged_str | [0, 1] | base_ranged_strength / 50 |
| 19 | enemy_range | [0, 1] | range / 2 |
| 20 | enemy_movement | [0, 1] | movement_points / 4 |
| 21 | enemy_defense_bonus | [0, 1] | (fortification + terrain) / 12 |
| **Cities and terrain** | | | |
| 22 | own_cities | {0, 1} | 1.0 at own city tiles |
| 23 | enemy_cities | {0, 1} | 1.0 at enemy city tiles |
| 24 | terrain_cost | [0, 1] | movement_cost / 3 |

### Design Decisions

- **Relationship-based encoding**: "Own" vs "enemy" rather than player IDs. Player 1
  and Player 2 are arbitrary labels; the agent should see the world in terms of
  friend/foe. Extends to N players with own/ally/neutral/enemy groupings.
- **Normalization**: All stats normalized to [0, 1] using known maximums.
  Ensures no channel dominates by magnitude.
- **One-hot unit class**: Lets the CNN distinguish unit types spatially.
  A tile with a Spearman next to a Horseman creates specific activation patterns
  that the network can learn to interpret as "anti-cavalry advantage here."
- **Sparse**: Most tiles are zero in most channels. Only tiles with units/cities
  have non-zero values. The CNN handles this naturally.

### Legacy: BasicStateEncoder

**Shape**: `[5, n, m]` (for 2 players)

| Ch | Name | Description |
|----|------|-------------|
| 0 | own_cities | 100 at own city tiles |
| 1 | own_unit_hp | Raw health value |
| 2 | own_movement | Raw movement points |
| 3 | enemy_cities | -100 at enemy city tiles |
| 4 | enemy_unit_hp | Negative raw health |

Used for initial experiments. No unit type distinction, no terrain, no normalization.

---

## 2. Build State Space (planned)

**Shape**: `[25 + 8, n, m]` = `[33, n, m]`

Extends the combat state tensor with 8 additional channels encoding city production
information. Non-zero only at own city tiles.

### Additional Channels (at own city tiles only)

| Ch | Name | Value | Description |
|----|------|-------|-------------|
| 25 | turns_to_warrior | cost / prod / max_turns | Normalized build time |
| 26 | turns_to_spearman | cost / prod / max_turns | |
| 27 | turns_to_archer | cost / prod / max_turns | |
| 28 | turns_to_horseman | cost / prod / max_turns | |
| 29 | turns_to_settler | cost / prod / max_turns | |
| 30 | turns_to_granary | cost / prod / max_turns | |
| 31 | current_production | index / num_options | What's being built (normalized) |
| 32 | production_progress | accumulated / cost | 0→1 as build completes |

### Design Decisions

- **Embedded in map tensor**: City build info lives in the same spatial tensor as
  combat info. The CNN processes both in one pass, so the build head automatically
  sees nearby threats (enemy units) and opportunities (empty space for settlers).
- **"Turns to complete" encoding**: Rather than raw production values, the network
  sees "how many turns until I get a Warrior?" — a more meaningful signal.
  Normalized by a maximum (e.g., max 50 turns) so values stay in [0, 1].
- **Sparse**: Channels 25-32 are zero everywhere except own city tiles.
  For a 4×8 map with 2 cities, only 2 of 32 tiles are non-zero in these channels.
- **City position is implicit**: The CNN knows where each city is by *where in the
  grid* the production values appear. No explicit coordinates needed.

### Build Head Architecture

- Separate FC layers branching from shared or independent conv features
- Output: Q-values per build option, extracted at city tile positions
- One forward pass covers all cities simultaneously
- At turn start: for each own city, argmax over build options at that (row, col)

### Future Extensions

- **Population channel**: City population encoded at city tiles (pop / max_pop)
- **Building flags**: Binary channels for "has Granary", "has Walls", etc.
- **Food surplus**: Progress toward next population growth (surplus / threshold)
- **Receptive field scaling**: On larger maps (16×32+), build decisions need broader
  context. Options: larger kernels, stride > 1, or pooling layers. Stride reduces
  spatial resolution, which is acceptable since build Q-values are only needed at
  city locations.

---

## 3. Map Properties

- **Hex grid**: Offset coordinates with even/odd row adjacency patterns
- **Cylindrical wrapping**: Horizontal wrap (left↔right), no vertical wrap
- **Padding**: `horizontal_wrap_padding()` copies edge columns across the boundary
  so CNNs correctly perceive adjacency across the map seam. Top/bottom zero-padded.
- **Current size**: 4×8 (32 tiles). Planned scaling to 8×16, 16×32.

---

## 4. Mask Functions

### Select Mask
- **Shape**: `[n*m + 1]` — one entry per tile + end-turn action
- Valid if: own unit present (hp > 0) AND movement points remaining
- End-turn slot: always valid
- Auto-detects encoder by channel count (d=25 → enhanced channels)

### Move Mask
- **Shape**: `[n*m]` — one entry per tile
- Valid if: hex-adjacent to selected unit AND not occupied by friendly unit
- Current tile always valid (fortify action)
- Enemy-occupied tiles valid (attack)
- Auto-detects encoder by channel count

### Build Mask (planned)
- **Shape**: `[num_build_options]` per city
- Valid if: building not already built, unit type unlocked, settler requires pop ≥ 3
- Applied at city tile positions in the build head output

---

## 5. Terrain Yields

Used by the city economy for tile working assignments.

| Terrain | Food | Production | Movement Cost | Defense |
|---------|------|------------|---------------|---------|
| Plains | 1 | 1 | 1 | 0 |
| Grassland | 2 | 0 | 1 | 0 |
| Desert | 0 | 0 | 1 | 0 |
| Tundra | 1 | 0 | 1 | 0 |
| Snow | 0 | 0 | 1 | 0 |
| Hills | 0 | 2 | 2 | +3 |
| Woods | 1 | 1 | 2 | +3 |
| Rainforest | 2 | 0 | 2 | +3 |
| Marsh | 1 | 0 | 2 | -2 |
| Floodplains | 3 | 0 | 1 | -2 |
| Mountain | 0 | 0 | impassable | 0 |
| Coast | 1 | 0 | 1 | 0 |
| Lake | 2 | 0 | 1 | 0 |

### City Economy Rules

- **City center**: Always worked (free, no pop needed)
- **Tile assignment**: Each pop works one adjacent tile. Priority: food desc, prod desc.
- **Food consumption**: 2 per population per turn
- **Growth threshold**: 15 + 10 × (pop - 1) food surplus
- **Starvation**: Negative food net depletes surplus; at zero surplus, lose 1 pop
- **Minimum production**: 1 per turn (so cities can always build, just slowly)
