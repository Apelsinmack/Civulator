# Combat Training Tool — Design Document

> **Status**: Design — not yet implemented
> **Date**: 2026-04-01
> **Purpose**: Generate expert demonstration data for imitation learning.
> Human players create combat scenarios, play optimal moves, and the
> (state, action) sequences are recorded for training.

---

## Overview

Two tools that work together:

1. **Scenario Painter** — create combat setups (place units, cities, terrain)
2. **Order Recorder** — play through scenarios, recording every action

The output is a dataset of (state_tensor, select_q_r, move_q_r) tuples
that can train the combat network via imitation learning.

---

## Tool 1: Scenario Painter

### Interface
- Raylib window showing hex grid (reuse rendering from `watch.py`)
- Left panel: unit palette
  - Unit types: Warrior, Archer, Spearman, Horseman, Catapult, Battering Ram
  - Team toggle: Team 1 (blue) / Team 2 (red)
  - Fortified toggle (checkbox)
  - HP slider (default: full)
  - City placement mode
- Click hex → place selected unit/city
- Right-click hex → remove unit/city
- Terrain is randomly generated on startup

### Workflow
1. Start tool → random terrain generated
2. Place Team 2 units first (the "enemy" position)
3. Place Team 1 units (the player's army)
4. Optionally place cities
5. Click "Save Scenario" → saves to JSON, generates new random terrain
6. Repeat — create many scenarios in one sitting

### Terrain Generation
- New random terrain each time a scenario is saved
- Seed displayed on screen (reproducible)
- Optional: "Regenerate Terrain" button to get a different map without saving
- Map size: configurable, default 16x16 (small, focused on combat)

### Scenario File Format (JSON)
```json
{
  "seed": 42,
  "map_width": 16,
  "map_height": 16,
  "units": [
    {"type": "archer", "team": 2, "q": 5, "r": 3, "fortified": true, "hp": 100},
    {"type": "warrior", "team": 1, "q": 7, "r": 5, "fortified": false, "hp": 100}
  ],
  "cities": [
    {"team": 2, "q": 5, "r": 2, "hp": 200, "walls": false}
  ]
}
```

### Storage
```
civulator/scenarios/
├── scenario_001.json
├── scenario_002.json
└── ...
```

### Multiplayer / Friends
- Anyone with the repo can run the Scenario Painter
- Save scenarios, commit to git, push
- Others pull and play them in the Order Recorder
- No networking needed — just shared files

---

## Tool 2: Order Recorder

### Interface
- Same raylib hex grid renderer as Scenario Painter
- Load a scenario → `GameEnvironment` is initialized with the scenario state
- It is always Player 1's turn
- Player 2's units are stationary (end-turn mode, some may be fortified)

### Interaction (same as agent's action space)
- **Select unit**: click a Team 1 unit's tile → highlights valid moves/attacks
- **Move**: click a valid empty tile → unit moves there
- **Attack (melee)**: click an adjacent enemy tile → unit attacks
- **Attack (ranged)**: click an enemy tile within range → unit shoots
- **Fortify**: click the selected unit's own tile → unit fortifies
- **Skip unit**: either explicitly fortify, or untouched units auto-fortify
  at end of turn

The key: **the human uses the exact same (select_q_r, move_q_r) interface
as the agent.** No translation layer needed. What you click is what gets
recorded.

### Action Resolution
After each action:
1. Record `(state_tensor_before, select_q_r, move_q_r)`
2. Execute the action in `GameEnvironment` (damage applied, unit moved, etc.)
3. The board updates — next action sees the new state
4. Repeat until player clicks "End Turn" or all units have acted

This means **order matters**: "shoot with archer first, then charge with
warrior" produces different intermediate states than the reverse. The network
learns the sequencing too.

### Recording Format
Each played scenario produces a sequence:
```json
{
  "scenario_file": "scenario_001.json",
  "actions": [
    {
      "state_tensor": "tensor_001.npy",
      "select": [7, 5],
      "move": [6, 4]
    },
    {
      "state_tensor": "tensor_002.npy",
      "select": [3, 8],
      "move": [5, 3]
    }
  ]
}
```

State tensors saved as .npy files (same format the training pipeline uses).

### Replaying a Scenario Multiple Times
- A scenario can be played more than once
- Different orderings, different strategies — all valid training data
- Store all versions, not just the "best" one
- The network benefits from seeing multiple reasonable approaches to the
  same position

### Storage
```
civulator/demonstrations/
├── scenario_001_play_001.json
├── scenario_001_play_001_state_000.npy
├── scenario_001_play_001_state_001.npy
├── scenario_001_play_002.json    ← same scenario, different play
└── ...
```

---

## Rotation (6-fold hex symmetry)

After recording a played scenario, rotate all positions 5 times to produce
6 total versions (original + 5 rotations).

### Axial rotation (60° clockwise)
```
(q, r) → (-r, q + r)
```

Apply 5 times to get all 6 orientations:
```
0°:   (q, r)
60°:  (-r, q+r)
120°: (-q-r, q)
180°: (-q, -r)
240°: (r, -q-r)
300°: (q+r, -q)
```

### What gets rotated
- All unit positions in the scenario
- All city positions
- The select and move coordinates in each action
- The state tensor must be regenerated from the rotated positions
  (not rotated directly — the tensor channels depend on absolute positions)

### Result
- 5 units × 6 rotations = **30 training examples** from one scenario play
- With multiple plays per scenario, this multiplies further

---

## Integration with Training Pipeline

### Data Loading
```python
class DemonstrationDataset:
    """Loads recorded demonstrations for imitation learning."""
    
    def __init__(self, demo_dir):
        # Load all play files + their state tensors
        # Apply 6-fold rotation augmentation
        # Return (state_tensor, select_index, move_index) tuples
    
    def __getitem__(self, idx):
        # Returns one training example
        pass
```

### Training
- Imitation learning: minimize cross-entropy between network output and
  demonstrated actions
- Can pretrain the combat network on demonstrations before RL fine-tuning
- Or mix demonstrations into the replay buffer alongside RL experience
  (DQfD — Deep Q-learning from Demonstrations)

---

## Implementation Plan

### Phase 1: Scenario Painter (~1 session)
1. Fork `watch.py` renderer as starting point
2. Add unit palette UI (raylib buttons/panels)
3. Add click-to-place, right-click-to-remove
4. Add terrain generation (reuse existing map gen)
5. Save to JSON
6. Auto-regenerate terrain on save

### Phase 2: Order Recorder (~1-2 sessions)
1. Load scenario JSON → init `GameEnvironment`
2. Highlight valid moves on unit select (need: `get_valid_moves(unit)`)
3. Record (state_tensor, select, move) on each action
4. Execute action in game engine, update display
5. "End Turn" button → save recording
6. This builds reusable selection/movement UI for future actual gameplay

### Phase 3: Rotation + Dataset (~0.5 session)
1. Implement axial rotation function
2. Apply to recorded scenarios (positions + actions)
3. Regenerate state tensors for rotated versions
4. Build `DemonstrationDataset` loader

### Phase 4: Training Integration (~0.5 session)
1. Imitation learning training loop
2. Or inject demonstrations into replay buffer (DQfD)
3. Compare combat performance before/after

---

## Sprites

Unit sprites available in `civulator/art/`:
- `icon_unit_archer.png` — white silhouette, transparent bg
- `icon_unit_catapult.png` — white silhouette, transparent bg
- `icon_unit_spearman.png` — white silhouette, transparent bg
- `icon_unit_swordsman.png` — white silhouette, transparent bg (use for Warrior too)
- `icon_unit_horseman.png` — white on black bg (needs bg removal or special handling)

Missing: Warrior (use swordsman), Battering Ram, Settler, city icon.

Tint white sprites with team colour in raylib:
```python
rl.draw_texture_ex(sprite, pos, 0, scale, team_color)
```

---

## Open Questions

1. **Map size for scenarios**: 16x16 is small and focused on combat. Should
   we support larger maps for strategic scenarios? Probably not yet.

2. **Partial HP units**: Should the painter allow placing damaged units?
   Yes — realistic scenarios often involve weakened units. HP slider.

3. **Terrain influence**: Some scenarios should test terrain bonuses
   (hills, forests). The random terrain handles this naturally.

4. **City defense**: Cities should be placeable with optional walls.
   Important for siege scenarios.

5. **How many scenarios do we need?** Start with 20-30 diverse scenarios,
   each played 2-3 times = 40-90 plays × 6 rotations × ~5 actions =
   1200-2700 training examples. A good starting point.
