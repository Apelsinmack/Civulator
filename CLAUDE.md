# Civulator - Project CLAUDE.md

> **Last updated**: 2026-03-03

## What Is This?

Civulator is a simplified Civilization-like game built as a training environment for deep reinforcement learning agents. The game simulates hex-grid turn-based strategy with cities, units, combat, and terrain. RL agents learn to play via DQN with a Select-and-Move action architecture.

**Origin**: Started as a collaboration between Erik (Python/RL) and Patrik (C# game engine). Patrik has left the project. The C# code is archived/legacy -- only the Python codebase is active.

## Project Location

`C:\fatboy\Civulator\Civulator`

## Current State (as of 2026-03-03)

- **Latest working version**: `python/v2_debugging/`
- **Older versions**: `python/v1 basic structure cities and warriors/version1-4` (kept for reference, not active)
- **C# code**: Legacy, archived. Not part of active development.
- **Training status**: Agents train but learning is unstable. No CUDA acceleration yet (RTX 3070 available).

## Architecture Overview

See `documents/design_document.md` for the full architectural vision and refactoring plan.

### Key Files (current, pre-refactor)

| File | Role |
|------|------|
| `python/v2_debugging/pyCiv.py` | Game environment: Terrain, Tile, Map, Unit, City, Player, GameEnvironment |
| `python/v2_debugging/GlobalDQNetworkSelectingAndMovingMultipleAgents.py` | DQN agent, network, replay memory, training loop |
| `python/v2_debugging/main_trainer.py` | Entry point with CLI args |
| `python/v2_debugging/ascii_map_display.py` | Debug visualization |
| `python/v2_debugging/debug_integration.py` | Debug versions of key functions |

### Core Concepts

- **Hexagonal grid** stored as a 2D matrix with offset coordinates (even/odd row adjacency)
- **Cylindrical map** wraps horizontally, not vertically
- **Select-and-Move action space**: agent first selects a unit tile, then selects a destination tile
- **State tensor**: `[d, n, m]` where `d = 2*num_players + 1` (cities, unit health, movement points per player)
- **Agent builds its own state**: `build_state_tensor(game_env)` -- the environment exposes raw state, agent decides representation

### Known Issues

See design document for full analysis. Key ones:
- Q-values for select and move are summed (not standard DQN)
- No target network (training instability)
- Multiple units on same tile overwrite in state tensor
- Adjacency in move masking uses 8-directional grid instead of hex neighbors
- Lots of commented-out old code in pyCiv.py

## Tech Stack

- Python 3 (anaconda base environment)
- PyTorch (needs CUDA reinstall for GPU training)
- NumPy, Matplotlib

## Related Projects

- **Breach** (another game with similar tile system -- can share tile/map design patterns)

## Development Notes

- All version folders (`v1/version1-4`, `v2_debugging`, `deepQlearningBot`, `pyCiv`, `misc`) are historical. The refactoring will consolidate into a single clean codebase.
- The game environment should remain a pure simulation with no RL dependencies.
- pyCiv currently imports torch, nn, F, plt -- these should be removed from the game module.
