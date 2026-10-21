"""Player class managing units, cities, and turn logic."""


class Player:
    """Represents a player in the game."""

    def __init__(self, name, player_index, game_env):
        # Identity: survives `GameEnvironment.reset` when players are kept.
        self.name = name
        self.player_index = player_index
        self.game_env = game_env
        self.reset_state()

    def reset_state(self):
        """Set every per-episode field to its start-of-game value.

        The one list of per-episode Player state (progression design, v2
        fixes, B3): called by `__init__` and by `GameEnvironment.reset` when
        it keeps its Player objects, so a field added here can never leak
        from one episode into the next. Every field other than the three
        identity fields set in `__init__` belongs here.
        """
        self.cities = []
        self.units = []
        self.queued_units = []
        self.is_dead = False
        self.palace_granted = False  # create_city grants the Palace once (#88)
        # Fog-of-war memory: (n, m) bool array of ever-seen tiles, owned by
        # the environment (see GameEnvironment.update_exploration)
        self.explored = None
        # The four pools, integer tenths (#87 culture; #116 P1 the rest),
        # filled by the yield phase in City.process_turn. Culture is the civic
        # pool; borders keep their own per-city pools.
        self.science = 0
        self.culture = 0
        self.gold = 0  # the treasury
        self.faith = 0
        # Research (#116 P2): completed techs in completion order (membership
        # tests only) and the tech the science pool is spent on (None: the
        # engine default picks one in GameEnvironment.resolve_research).
        self.techs = []
        self.current_tech = None
        # Declared for later #116 patches; nothing reads them yet.
        self.civics = []         # completed civics, in completion order (P4)
        self.current_civic = None  # P4
        self.government = None   # P4
        self.policies = []       # slotted policy cards (P4)
        self.routes = []         # trade routes from this player's cities (P5)

    def start_turn(self):
        """Process the start of a player's turn: exploration -> unit reset and
        heal -> cities -> economy phase (#116: research; later patches add
        their steps inside it) -> city ranged strike -> queued units."""
        self.game_env.update_exploration(self.player_index)

        for unit in self.units:
            unit.reset_movement()
            unit.heal()

        for city in self.cities:
            city.process_turn(self.game_env)

        # After every city has accrued this turn's yields (#116 P2).
        self.game_env.economy_phase(self)

        # A city with Walls shoots once at the start of its owner's turn
        # (issue #84). Automatic rather than an order, because the action
        # space selects units -- see GameEnvironment.city_ranged_attack.
        for city in list(self.cities):
            self.game_env.city_ranged_attack(city)

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
