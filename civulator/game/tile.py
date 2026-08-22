"""Tile class representing a single hex on the game map."""

from ..terrain_model import can_enter, compose, validate


class Tile:
    """One hex: the composable terrain layers plus what stands on them.

    Terrain state is exactly four layers (design doc §3) —
    `base_terrain` x `relief` x `feature` (<=1) x `resource` (<=1). Every
    gameplay number (yields, movement_cost, defense_bonus, los, domain,
    impassable) is DERIVED from them by terrain_model.compose(), never stored
    independently; `set_layers` is the only mutator.

    Rivers are not tile state — `Map.rivers` (edges) is the single river
    representation (§9.1).
    """

    def __init__(self, row, column, base_terrain="Plains", relief=None,
                 feature=None, resource=None):
        self.row = row
        self.column = column
        self.coordinates = (row, column)
        self.improvements = []
        self.units = []
        self.city = None

        self.set_layers(base_terrain, relief=relief, feature=feature, resource=resource)

    # --- Terrain layers (the only terrain state) ---

    def set_layers(self, base, relief=None, feature=None, resource=None, map_ref=None):
        """Set the composable layers (design doc §3.1) — the only terrain mutator.

        Validates the combination via terrain_model.validate() (raises
        ValueError on an invalid `on` placement — e.g. a feature on a base it
        can't grow on), then recomputes the composed properties. Bumps
        map_ref.terrain_epoch (§3.4) when a Map is given, so its
        terrain-derived caches (LoS, cost grids, encoder layers) invalidate.

        `relief=None` means flat.
        """
        relief = "flat" if relief is None else relief
        validate(base, relief=relief, feature=feature, resource=resource)
        self.base_terrain = base
        self.relief = relief
        self.feature = feature
        self.resource = resource
        self.composed = compose(base, relief=relief, feature=feature, resource=resource)
        if map_ref is not None:
            map_ref.terrain_epoch += 1

    @property
    def label(self):
        """Display/debug name for the terrain, e.g. "Grassland (Hills), Woods" (§3)."""
        text = self.base_terrain
        if self.relief != "flat":
            text += f" ({self.relief.capitalize()})"
        if self.feature:
            text += f", {self.feature}"
        return text

    # --- Composed properties (derived from the layers, never stored twice) ---

    @property
    def yields(self):
        """(food, production) — the additive sum of all layer contributions."""
        return self.composed.yields

    @property
    def movement_cost(self):
        return self.composed.movement

    @property
    def defense_bonus(self):
        return self.composed.defense

    @property
    def los(self):
        """(obstacle, vantage) — additive line-of-sight contributions."""
        return self.composed.los

    @property
    def domain(self):
        """"land" | "water" — from the base terrain."""
        return self.composed.domain

    @property
    def impassable(self):
        """Blocks every domain (mountain relief) and makes the tile unworkable (§3)."""
        return self.composed.impassable

    def is_passable(self, domain="land"):
        """Whether the terrain admits a unit of `domain` — the canonical check (§3.3)."""
        return can_enter(domain, self)

    def is_water(self):
        return self.domain == "water"

    # --- Occupants ---

    def add_unit(self, unit):
        """Add a unit to this tile."""
        self.units.append(unit)

    def remove_unit(self, unit):
        """Remove a unit from this tile."""
        if unit in self.units:
            self.units.remove(unit)

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
