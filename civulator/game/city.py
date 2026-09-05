"""City class with production, population, and buildings."""

from ..terrain_model import can_enter
from ..unit_model import CITY_DEFENSE_STRENGTH, CITY_HEALTH
from .unit import (
    Unit, WarriorUnit, ArcherUnit, SwordsmanUnit, SpearmanUnit,
    HorsemanUnit, CatapultUnit, SettlerUnit, WorkerUnit, movement_domain,
)


class City:
    """Represents a city in the game.

    Economy model:
    - City center tile is always worked (free, no pop needed)
    - Each population works one additional adjacent tile
    - Tiles are assigned by priority: food desc, then production desc
    - Food consumed per turn: 2 * population
    - Surplus food accumulates toward growth threshold
    - Growth threshold: 15 + 10 * (pop - 1)
    - Starvation: if food output < consumption, lose accumulated surplus
    """

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
        self.health = CITY_HEALTH
        self.is_city = True
        self.defense_strength = CITY_DEFENSE_STRENGTH
        self.buildings = []
        self.population = 1
        self.food_surplus = 0  # Accumulated surplus toward growth
        self.production = 0
        self.current_production = {"type": "unit", "unit_type": "Warrior"}
        self.worked_tiles = []  # List of (row, col) assigned to citizens

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

    def assign_tiles(self, game_env):
        """Assign citizens to the best adjacent tiles.

        Priority: sort by food descending, then production descending.
        City center is always worked (free). Each pop works one extra tile.
        Called on city founding and population change.

        Only UNWORKABLE tiles are skipped — that is impassable ones (§3).
        Water is workable: a coastal city works its Coast and Lake tiles even
        though no land unit can walk on them.
        """
        adj_coords = game_env.map.get_adjacent_coords(self.coordinates)

        # Score each adjacent tile: (food, production, coords)
        tile_scores = []
        for pos in adj_coords:
            tile = game_env.map.get_tile(pos)
            if tile and not tile.impassable:
                food, prod = tile.yields
                tile_scores.append((food, prod, pos))

        # Sort: food desc, then production desc
        tile_scores.sort(key=lambda x: (x[0], x[1]), reverse=True)

        # Assign: population workers (city center is free, doesn't consume a pop)
        workers = self.population
        self.worked_tiles = []
        for food, prod, pos in tile_scores:
            if workers <= 0:
                break
            self.worked_tiles.append(pos)
            workers -= 1

    def calculate_food(self, game_env):
        """Calculate total food from city center + worked tiles."""
        # City center (always worked, free)
        center_tile = game_env.map.get_tile(self.coordinates)
        total_food = center_tile.yields[0]

        # Worked tiles
        for pos in self.worked_tiles:
            tile = game_env.map.get_tile(pos)
            if tile:
                total_food += tile.yields[0]

        return total_food

    def calculate_production(self, game_env):
        """Calculate total production from city center + worked tiles."""
        center_tile = game_env.map.get_tile(self.coordinates)
        total_prod = center_tile.yields[1]

        for pos in self.worked_tiles:
            tile = game_env.map.get_tile(pos)
            if tile:
                total_prod += tile.yields[1]

        # Minimum 1 production per turn (so cities can always build, just slowly)
        return max(1, total_prod)

    def get_growth_threshold(self):
        """Food surplus needed to grow to next population level.

        Approximation of Civ 6: 15 + 10 * (pop - 1).
        Pop 1→2: 15, Pop 2→3: 25, Pop 3→4: 35, etc.
        """
        return 15 + 10 * (self.population - 1)

    def process_turn(self, game_env):
        """Process a game turn for this city.

        Order: collect food → consume → growth/starvation → collect production → build.
        """
        # --- Food phase ---
        food_produced = self.calculate_food(game_env)
        food_consumed = 2 * self.population
        food_net = food_produced - food_consumed

        if food_net >= 0:
            self.food_surplus += food_net
        else:
            # Starvation: lose accumulated surplus first
            self.food_surplus += food_net  # food_net is negative
            if self.food_surplus < 0:
                self.food_surplus = 0
                if self.population > 1:
                    self.population -= 1
                    self.assign_tiles(game_env)

        # Population growth
        growth_threshold = self.get_growth_threshold()
        if self.food_surplus >= growth_threshold:
            self.food_surplus -= growth_threshold
            self.population += 1
            self.assign_tiles(game_env)

        # --- Production phase ---
        self.production += self.calculate_production(game_env)

        # Process current production
        if self.current_production:
            if self.current_production["type"] == "unit":
                unit_type = self.current_production["unit_type"]
                unit_cost = self.get_unit_cost(unit_type)
                if self.production >= unit_cost:
                    placed = self.complete_unit_production(unit_type, game_env)
                    if placed:
                        self.production -= unit_cost
                        # Build agent decides next production
                        self.current_production = None

            elif self.current_production["type"] == "building":
                building_type = self.current_production["building_type"]
                building_cost = self.get_building_cost(building_type)
                if self.production >= building_cost:
                    self.production -= building_cost
                    self.buildings.append(building_type)
                    self.current_production = None

    def get_unit_cost(self, unit_type):
        """Get the production cost for a unit type."""
        temp_unit = Unit(None, None, unit_type)
        return temp_unit.get_production_cost()

    def get_building_cost(self, building_type):
        """Get the production cost for a building type."""
        return self.BUILDING_COSTS.get(building_type, 100)

    def complete_unit_production(self, unit_type, game_env):
        """Place a newly produced unit on the city tile or first empty adjacent tile.

        Priority: city center > adjacent tiles. Every candidate goes through
        the canonical terrain-domain check (§3.3, §9.10) — production may not
        drop a land unit into a lake or onto a mountain.
        If none is available, returns False (unit deferred to next turn).
        """
        domain = movement_domain(unit_type)

        # Try city center first
        friendly_on_center = any(
            u.player == self.player for u in game_env.get_units_at(self.coordinates)
        )
        if not friendly_on_center and can_enter(domain, game_env.map.get_tile(self.coordinates)):
            unit = _create_unit(unit_type, self.player, self.coordinates)
            self.player.units.append(unit)
            game_env.add_unit_to_tile(unit, self.coordinates)
            return True

        # Try adjacent tiles
        adj_coords = game_env.map.get_adjacent_coords(self.coordinates)
        for pos in adj_coords:
            if not can_enter(domain, game_env.map.get_tile(pos)):
                continue
            if game_env.is_valid_position(pos) and not game_env.is_occupied(pos):
                unit = _create_unit(unit_type, self.player, pos)
                self.player.units.append(unit)
                game_env.add_unit_to_tile(unit, pos)
                return True

        # All tiles occupied or unreachable — defer to next turn
        return False

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
