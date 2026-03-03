# Civulator - Project CLAUDE.md

> **Last updated**: 2026-03-03

## What Is This?

Civulator is a **research project** exploring deep reinforcement learning in a simplified Civilization-like strategy game. The goal is not just to build a working agent, but to **systematically measure what works and what doesn't** -- comparing architectures, state representations, reward functions, and training configurations through controlled experiments.

Every change should be accompanied by evidence: training curves, win rate plots, and documented comparisons against previous versions. We improve incrementally by measuring performance, not by guessing.

The game simulates hex-grid turn-based strategy with cities, units, combat, and terrain. RL agents learn to play via DQN with a Select-and-Move action architecture.

**Origin**: Started as a collaboration between Erik (Python/RL) and Patrik (C# game engine). Patrik has left the project. The C# code is archived/legacy -- only the Python codebase is active.

## Research Methodology

- **Baseline first**: Before changing anything, establish a measurable baseline (win rate, training curve shape, convergence speed).
- **One variable at a time**: When testing a new idea (e.g., different state encoder, new reward function), change only that variable and compare against the baseline.
- **Document everything**: Each experiment should record: what was changed, hypothesis, training parameters, results (plots), and conclusions.
- **Keep old results**: Training plots and win histories are saved in `stats/`. Never delete previous results -- they are the project's scientific record.
- **Reproducibility**: Use fixed random seeds. Log hyperparameters. Save model checkpoints so experiments can be replicated or resumed.

## Project Location

`C:\fatboy\Civulator\Civulator`

## Current State (as of 2026-03-03)

- **Codebase**: Refactored into `civulator/` package (game, agents, training, utils)
- **Old versions**: Archived in `archive/python_versions/` and `archive/csharp/`
- **GPU**: PyTorch 2.6.0+cu124, RTX 3070 confirmed working
- **Training status**: Agents train but learning is unstable. No baseline measurements yet -- establishing these is the first research priority.

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
