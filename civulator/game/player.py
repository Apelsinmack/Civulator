"""Player class managing units, cities, and turn logic."""

from .unit import SettlerUnit


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
        # Units owed but not yet placed (#116 P5, revived): `(city_id,
        # unit_type)` entries, in the order they were owed -- a purchased
        # unit, a returning Trader -- appended by City.place_or_queue_unit
        # when the city has no room, placed by start_turn.
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
        # Civics (#116 P4): completed civics in completion order (membership
        # tests only) and the civic the culture pool is spent on (None: the
        # engine default picks one in GameEnvironment.resolve_civic); the
        # government (a [governments.*] name, None until one is adopted) and
        # the slotted policy cards, in slotting order -- written only by
        # GameEnvironment.set_government / set_policies and the engine
        # defaults.
        self.civics = []
        self.current_civic = None
        self.government = None
        self.policies = []
        # Trade routes from this player's cities (#116 P5): game/trade.py
        # TradeRoute records, in establishment order; written only by
        # GameEnvironment.establish_trade_route, trade.expire_routes and
        # trade.end_routes_touching.
        self.routes = []
        # Religion (v0.9.0 Q7, districts_religion_design §7.1): the chosen
        # [pantheons.*] name, None until one is chosen; permanent once set
        # (Civ 6: kept whatever happens to the cities). Written only by
        # GameEnvironment.choose_pantheon. Q8/Q9 add the founded religion,
        # the spread-use counter and the lapsed flag here, beside it.
        self.pantheon = None

    def start_turn(self):
        """Process the start of a player's turn: exploration -> unit reset and
        heal -> cities -> economy phase (#116: maintenance, bankruptcy, the
        religion step (v0.9.0 Q7),
        research, civics, government and loadout defaults, route expiry, the
        Trader default; GameEnvironment.economy_phase lists the order) ->
        city ranged strikes (per city: the centre, then each fortified
        district, v0.9.0 Q3) -> queued units."""
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
        # A walled city's Encampment fires too, after the centre (v0.9.0
        # Q3, GameEnvironment.fortification_ranged_attack).
        for city in list(self.cities):
            self.game_env.city_ranged_attack(city)
            for district in city.fortified_districts():
                self.game_env.fortification_ranged_attack(district)

        self.place_queued_units()

    def place_queued_units(self):
        """Place every queued `(city_id, unit_type)` entry through its city's
        `complete_unit_production` (#116 P5): the city is looked up in
        `GameEnvironment.city_by_id`, an entry whose city no longer stands or
        is no longer this player's is dropped, and one that still cannot be
        placed stays queued, in order."""
        env = self.game_env
        queued, self.queued_units = self.queued_units, []
        for city_id, unit_type in queued:
            city = env.city_by_id.get(city_id)
            if city is None or city.player is not self:
                continue
            if not city.complete_unit_production(unit_type, env):
                self.queued_units.append((city_id, unit_type))

    def has_lost(self):
        """Whether the player is out of the game: no city and no Settler left
        to found one (#126, Erik 2026-10-22). Losing the capital, or every
        city while a Settler lives, does not end a player."""
        return not self.cities and not any(isinstance(unit, SettlerUnit)
                                           for unit in self.units)

    def end_turn(self):
        """Process the end of a player's turn: a player that `has_lost` dies
        and its remaining units are removed."""
        if self.has_lost():
            self.is_dead = True
            units_copy = self.units.copy()
            for unit in units_copy:
                self.game_env.delete_unit(unit)

    def remove_unit(self, unit):
        """Remove a unit from the player's control."""
        if unit in self.units:
            self.units.remove(unit)
