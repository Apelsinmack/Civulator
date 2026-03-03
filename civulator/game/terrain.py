"""Terrain types and their gameplay modifiers."""

import numpy as np


class Terrain:
    """Represents different terrain types and their combat/movement/production modifiers."""

    DEFENSE_MODIFIERS = {
        "Plains": 0,
        "Grassland": 0,
        "Desert": 0,
        "Tundra": 0,
        "Snow": 0,
        "Hills": 3,
        "Woods": 3,
        "Rainforest": 3,
        "Marsh": -2,
        "Floodplains": -2,
        "Mountain": 0,
        "Ocean": 0,
        "Coast": 0,
        "Lake": 0,
    }

    MOVEMENT_COSTS = {
        "Plains": 1,
        "Grassland": 1,
        "Desert": 1,
        "Tundra": 1,
        "Snow": 1,
        "Hills": 2,
        "Woods": 2,
        "Rainforest": 2,
        "Marsh": 2,
        "Floodplains": 1,
        "Mountain": 999,  # Impassable
        "Ocean": 1,
        "Coast": 1,
        "Lake": 1,
    }

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
