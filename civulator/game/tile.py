"""Tile class representing a single hex on the game map."""

from dataclasses import dataclass
from typing import Optional

import numpy as np

from .terrain import Terrain
from ..terrain_model import compose, validate


@dataclass
class TileLayers:
    """The v0.6 composable layers (design doc §3): base x relief x feature x resource.

    Holds only the new-model state. Kept off Tile's existing `resource` and
    `features` attributes on purpose — those are legacy and stay authoritative
    for gameplay until the P2a engine re-point, so nothing here may collide
    with or change their behavior. Set exclusively via Tile.set_layers();
    read the derived gameplay numbers from Tile.composed.
    """

    base: Optional[str] = None
    relief: Optional[str] = None
    feature: Optional[str] = None
    resource: Optional[str] = None


class Tile:
    """Represents a single tile on the map."""

    def __init__(self, row, column, terrain_type="Plains"):
        self.row = row
        self.column = column
        self.coordinates = (row, column)
        self.terrain_type = terrain_type
        self.features = []
        self.improvements = []
        self.resource = None
        self.units = []
        self.city = None

        # v0.6 composable layers (design doc §3) — additive, new state only.
        # Unset until set_layers() is called; unused by gameplay until P2a.
        self.layers = TileLayers()
        self.composed = None

        self.update_terrain_properties()

    def update_terrain_properties(self):
        """Update the tile properties based on terrain type and features."""
        self.defense_bonus = Terrain.DEFENSE_MODIFIERS.get(self.terrain_type, 0)
        self.movement_cost = Terrain.MOVEMENT_COSTS.get(self.terrain_type, 1)
        self.production_value = Terrain.PRODUCTION_VALUES.get(
            self.terrain_type, np.array([0, 0])
        )

        if "Woods" in self.features:
            self.defense_bonus += 3
            self.movement_cost += 1
        if "Rainforest" in self.features:
            self.defense_bonus += 3
            self.movement_cost += 1

    def add_unit(self, unit):
        """Add a unit to this tile."""
        self.units.append(unit)

    def remove_unit(self, unit):
        """Remove a unit from this tile."""
        if unit in self.units:
            self.units.remove(unit)

    def add_feature(self, feature):
        """Add a feature to this tile."""
        if feature not in self.features:
            self.features.append(feature)
            self.update_terrain_properties()

    def remove_feature(self, feature):
        """Remove a feature from this tile."""
        if feature in self.features:
            self.features.remove(feature)
            self.update_terrain_properties()

    def add_improvement(self, improvement):
        """Add an improvement to this tile."""
        if improvement not in self.improvements:
            self.improvements.append(improvement)

    def remove_improvement(self, improvement):
        """Remove an improvement from this tile."""
        if improvement in self.improvements:
            self.improvements.remove(improvement)

    def set_city(self, city):
        """Set a city on this tile."""
        self.city = city

    def is_passable(self):
        """Check if this tile is passable by land units."""
        return self.terrain_type != "Mountain" and self.movement_cost < 999

    def is_water(self):
        """Check if this tile is a water tile."""
        return self.terrain_type in ["Ocean", "Coast", "Lake"]

    def has_feature(self, feature):
        """Check if this tile has a specific feature."""
        return feature in self.features

    def has_river(self):
        """Check if this tile has a river."""
        return "River" in self.features

    def set_layers(self, base, relief=None, feature=None, resource=None, map_ref=None):
        """Set the v0.6 composable layers (design doc §3.1) — the only mutator for them.

        Validates the combination via terrain_model.validate() (raises
        ValueError on an invalid `on` placement — e.g. a feature on a base it
        can't grow on), then stores it on self.layers and recomputes
        self.composed via terrain_model.compose(). Bumps map_ref.terrain_epoch
        (design doc §3.4) when a Map is given, so its terrain-derived caches
        know to invalidate.

        Does not touch terrain_type, features, resource, or
        update_terrain_properties() — those legacy attributes keep driving all
        gameplay unchanged until the P2a engine re-point.
        """
        validate(base, relief=relief, feature=feature, resource=resource)
        self.layers = TileLayers(base=base, relief=relief, feature=feature, resource=resource)
        self.composed = compose(base, relief=relief, feature=feature, resource=resource)
        if map_ref is not None:
            map_ref.terrain_epoch += 1
