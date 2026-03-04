"""City class with production, population, and buildings."""

from .unit import (
    Unit, WarriorUnit, ArcherUnit, SwordsmanUnit, SpearmanUnit,
    HorsemanUnit, CatapultUnit, SettlerUnit, WorkerUnit,
)


class City:
    """Represents a city in the game."""

    BUILDING_COSTS = {
        "Granary": 60,
        "Monument": 50,
        "Walls": 100,
        "Workshop": 120,
        "Factory": 240,
    }

    def __init__(self, player, coordinates, name):
        self.player = player
        self.coordinates = coordinates
        self.name = name
        self.health = 200
        self.is_city = True
        self.defense_strength = 20
        self.buildings = []
        self.population = 1
        self.food = 0
        self.production = 0
        self.current_production = {"type": "unit", "unit_type": "Warrior"}

    def get_combat_strength(self, is_attacking=False, target=None):
        """Return the defensive combat strength of the city."""
        strength = self.defense_strength
        for building in self.buildings:
            if building == "Walls":
                strength += 30
            elif building == "Castle":
                strength += 20
        return strength

    def produce_unit(self, unit_type):
        """Start producing a unit."""
        self.current_production = {"type": "unit", "unit_type": unit_type}
        return True

    def produce_building(self, building_type):
        """Start producing a building."""
        self.current_production = {"type": "building", "building_type": building_type}
        return True

    def process_turn(self, game_env):
        """Process a game turn for this city."""
        self.food += self.calculate_food(game_env)
        self.production += self.calculate_production(game_env)

        # Population growth
        if self.food >= self.population * 20:
            self.food -= self.population * 20
            self.population += 1

        # Process current production
        if self.current_production:
            if self.current_production["type"] == "unit":
                unit_type = self.current_production["unit_type"]
                unit_cost = self.get_unit_cost(unit_type)
                if self.production >= unit_cost:
                    self.production -= unit_cost
                    self.complete_unit_production(unit_type, game_env)
                    # Auto-queue next warrior (rule-based placeholder)
                    self.current_production = {"type": "unit", "unit_type": "Warrior"}

            elif self.current_production["type"] == "building":
                building_type = self.current_production["building_type"]
                building_cost = self.get_building_cost(building_type)
                if self.production >= building_cost:
                    self.production -= building_cost
                    self.buildings.append(building_type)
                    self.current_production = None

    def calculate_food(self, game_env):
        """Calculate food production for this turn."""
        return 2 * self.population

    def calculate_production(self, game_env):
        """Calculate production output for this turn."""
        return 1 + self.population

    def get_unit_cost(self, unit_type):
        """Get the production cost for a unit type."""
        temp_unit = Unit(None, None, unit_type)
        return temp_unit.get_production_cost()

    def get_building_cost(self, building_type):
        """Get the production cost for a building type."""
        return self.BUILDING_COSTS.get(building_type, 100)

    def complete_unit_production(self, unit_type, game_env):
        """Place a newly produced unit on the city tile (Civ-style stacking).

        New unit spawns on the city tile even if another unit is there.
        The new unit must move before the existing one can.
        """
        unit = _create_unit(unit_type, self.player, self.coordinates)
        self.player.units.append(unit)
        game_env.add_unit_to_tile(unit, self.coordinates)
        return True

    def set_owner(self, new_player):
        """Transfer city ownership to a new player."""
        if self.player:
            self.player.cities.remove(self)
        new_player.cities.append(self)
        self.player = new_player


def _create_unit(unit_type, player, coordinates):
    """Factory function to create the appropriate unit subclass."""
    unit_classes = {
        "Warrior": WarriorUnit,
        "Archer": ArcherUnit,
        "Swordsman": SwordsmanUnit,
        "Spearman": SpearmanUnit,
        "Horseman": HorsemanUnit,
        "Catapult": CatapultUnit,
        "Settler": SettlerUnit,
        "Worker": WorkerUnit,
    }
    cls = unit_classes.get(unit_type, Unit)
    if cls == Unit:
        return Unit(player, coordinates, unit_type)
    return cls(player, coordinates)
