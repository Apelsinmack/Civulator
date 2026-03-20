"""Terrain types and their gameplay modifiers.

Values are loaded from config.toml when available, with hardcoded defaults
as fallback. Edit config.toml to tune gameplay without touching code.
"""

import numpy as np

from ..config import CFG

# --- Load from config.toml with fallbacks ---

_cfg_movement = CFG.get("terrain", {}).get("movement_costs", {})
_cfg_defense = CFG.get("terrain", {}).get("defense_modifiers", {})
_cfg_los = CFG.get("terrain", {}).get("los", {})


class Terrain:
    """Represents different terrain types and their combat/movement/production modifiers."""

    # Defaults — overridden by config.toml values
    _DEFAULT_DEFENSE = {
        "Plains": 0, "Grassland": 0, "Desert": 0, "Tundra": 0, "Snow": 0,
        "Hills": 3, "Woods": 3, "Rainforest": 3, "Marsh": -2, "Floodplains": -2,
        "Mountain": 0, "Ocean": 0, "Coast": 0, "Lake": 0,
    }

    _DEFAULT_MOVEMENT = {
        "Plains": 1, "Grassland": 1, "Desert": 1, "Tundra": 1, "Snow": 1,
        "Hills": 2, "Woods": 2, "Rainforest": 2, "Marsh": 2, "Floodplains": 1,
        "Mountain": 999, "Ocean": 1, "Coast": 1, "Lake": 1,
    }

    # Merge: config.toml values override defaults
    DEFENSE_MODIFIERS = {**_DEFAULT_DEFENSE, **_cfg_defense}
    MOVEMENT_COSTS = {**_DEFAULT_MOVEMENT, **_cfg_movement}

    # Line of sight: [obstacle_level, vantage_level] per terrain
    # obstacle_level: how much this terrain blocks sight passing through
    # vantage_level: how much extra sight you get standing on it
    _DEFAULT_LOS = {
        "Plains": [0, 0], "Grassland": [0, 0], "Desert": [0, 0],
        "Tundra": [0, 0], "Snow": [0, 0], "Hills": [1, 1],
        "Woods": [1, 0], "Rainforest": [1, 0], "Marsh": [0, 0],
        "Floodplains": [0, 0], "Mountain": [2, 0],
        "Ocean": [0, 0], "Coast": [0, 0], "Lake": [0, 0],
    }
    LOS = {**_DEFAULT_LOS, **{k: v for k, v in _cfg_los.items()}}

    PRODUCTION_VALUES = {
        "Plains": np.array([1, 1]),
        "Grassland": np.array([2, 0]),
        "Desert": np.array([0, 0]),
        "Tundra": np.array([1, 0]),
        "Snow": np.array([0, 0]),
        "Hills": np.array([0, 2]),
        "Woods": np.array([1, 1]),
        "Rainforest": np.array([2, 0]),
        "Marsh": np.array([1, 0]),
        "Floodplains": np.array([3, 0]),
        "Mountain": np.array([0, 0]),
        "Ocean": np.array([1, 0]),
        "Coast": np.array([1, 0]),
        "Lake": np.array([2, 0]),
    }
