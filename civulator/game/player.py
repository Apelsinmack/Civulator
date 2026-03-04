"""Player class managing units, cities, and turn logic."""


class Player:
    """Represents a player in the game."""

    def __init__(self, name, player_index, game_env):
        self.name = name
        self.player_index = player_index
        self.game_env = game_env
        self.cities = []
        self.units = []
        self.queued_units = []
        self.is_dead = False
        self.gold = 0
        self.science = 0
        self.culture = 0
        self.technologies = []
        self.policies = []

    def start_turn(self):
        """Process the start of a player's turn."""
        for unit in self.units:
            unit.reset_movement()
            unit.heal()

        for city in self.cities:
            city.process_turn(self.game_env)

        # Try to place queued units
        queued_copy = self.queued_units.copy()
        self.queued_units = []
        for queued_unit in queued_copy:
            city = queued_unit["city"]
            unit_type = queued_unit["type"]
            placed = city.complete_unit_production(unit_type, self.game_env)
            if not placed:
                self.queued_units.append(queued_unit)

    def end_turn(self):
        """Process the end of a player's turn."""
        if len(self.cities) == 0:
            self.is_dead = True
            units_copy = self.units.copy()
            for unit in units_copy:
                self.game_env.delete_unit(unit)

    def remove_unit(self, unit):
        """Remove a unit from the player's control."""
        if unit in self.units:
            self.units.remove(unit)
