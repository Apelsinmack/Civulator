"""City class with production, population, and buildings."""

from ..terrain_model import can_enter
from ..unit_model import (
    BUILDING_COSTS as _BUILDING_COSTS,
    BUILDING_DEFENSE_BONUS,
    CITY_DEFENSE_STRENGTH,
    CITY_HEAL_PER_TURN,
    CITY_HEALTH,
    CITY_RANGED_BUILDING,
    CITY_RANGED_RANGE,
    CITY_RANGED_STRENGTH,
    growth_percent,
)
from . import territory
from .culture import culture
from .housing import housing
from .unit import (
    Unit, WarriorUnit, SlingerUnit, ArcherUnit, SwordsmanUnit, SpearmanUnit,
    HorsemanUnit, CatapultUnit, BatteringRamUnit, SiegeTowerUnit,
    SettlerUnit, WorkerUnit, movement_domain,
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

    # Values live in config.toml [buildings.*], interpreted once at import by
    # civulator/unit_model.py (the same discipline #64 applied to the unit
    # tables); aliased here so existing call sites (City.BUILDING_COSTS across
    # trainer.py, evaluate.py, watch.py, build_agent.py) keep working.
    BUILDING_COSTS = _BUILDING_COSTS

    def __init__(self, player, coordinates, name):
        self.player = player
        self.coordinates = coordinates
        self.name = name
        # Per-environment id, assigned only by GameEnvironment.create_city
        # (borders design §2); the key into Map.owner_city / env.city_by_id.
        self.city_id = None
        self.health = CITY_HEALTH
        self.is_city = True
        self.defense_strength = CITY_DEFENSE_STRENGTH
        self.buildings = []
        self.population = 1
        self.food_surplus = 0  # Growth bucket, in hundredths of food (issue #88)
        self.production = 0
        self.current_production = {"type": "unit", "unit_type": "Warrior"}
        self.worked_tiles = []  # List of (row, col) assigned to citizens
        # Culture (issue #87), all int tenths. border_culture is the city's
        # border pool; culture_this_round is what the border phase reads and
        # zeroes; _culture_round stamps the round of the last accrual.
        self.border_culture = 0
        self.culture_this_round = 0
        self._culture_round = None
        # Border cost index n (borders design §3.1): culture claims made so
        # far; founding claims don't count. Travels with the city on capture.
        self.border_claims = 0

    def get_combat_strength(self, is_attacking=False, target=None):
        """Return the defensive combat strength of the city.

        Base defence plus every standing building's `defense_bonus` from
        config.toml `[buildings.*]` (issue #7). This is the number
        `Unit.attack` reads as the defender's strength when the target is a
        city, so a building's defensive effect is applied by the one combat
        path and not re-derived anywhere.
        """
        strength = self.defense_strength
        for building in self.buildings:
            strength += BUILDING_DEFENSE_BONUS.get(building, 0)
        return strength

    def can_make_ranged_attack(self):
        """Whether this city may bombard (issue #84).

        Civ 6 gates the city ranged strike on Walls -- "once a city has walls,
        it can make ranged attacks"; a garrison alone is not enough. The
        building that unlocks it is `[city] ranged_building` in config.toml,
        so a second fortification is a config line rather than a name in an
        `if`. A city reduced to 0 health has stopped fighting and does not
        shoot.
        """
        return self.health > 0 and CITY_RANGED_BUILDING in self.buildings

    def get_ranged_strength(self):
        """The city's ranged strength (issue #84), `[city] ranged_strength`.

        A flat number, unlike a unit's: Civ 6 derives it from the strongest
        ranged unit the civilization has built, which needs a tech tree we do
        not have (#41/#76), and it carries no health penalty -- a battered
        city shoots as hard as a fresh one. Both simplifications are named in
        the CHANGELOG.
        """
        return CITY_RANGED_STRENGTH

    def get_range(self):
        """Range of the city's ranged strike (`[city] ranged_range`)."""
        return CITY_RANGED_RANGE

    def produce_unit(self, unit_type):
        """Start producing a unit."""
        self.current_production = {"type": "unit", "unit_type": unit_type}
        return True

    def produce_building(self, building_type):
        """Start producing a building. Refused (False) for a name with no
        production cost - the Palace is granted, never built (#88)."""
        if building_type not in self.BUILDING_COSTS:
            return False
        self.current_production = {"type": "building", "building_type": building_type}
        return True

    def assign_tiles(self, game_env):
        """Assign citizens to the best tiles this city owns within work radius.

        Candidates (borders design §4): tiles whose `Map.owner_city` is this
        city, at hex distance 1..`[territory] work_radius` from the centre
        (rings from the canonical `Map.get_ring_coords`), and workable. The
        centre is worked free and is never a candidate. A city therefore never
        works a neutral or enemy tile, nor an owned tile beyond the radius;
        both would break by reading ring 1 only or by dropping the ownership
        test.

        Priority: food descending, then production descending. Ties between
        equal-yield tiles are deterministic and independent of set/dict
        iteration: candidates are enumerated nearest ring first, each ring in
        (row, col) order (`hexmath.hex_rings`), and a stable sort keeps that
        order among equals — nearer tiles are worked first, then lower
        (row, col). Each pop works one extra tile. Called on city founding,
        population change, and whenever the city gains or loses a tile.

        Only UNWORKABLE tiles are skipped — that is impassable ones (§3).
        Water is workable: a coastal city works its Coast and Lake tiles even
        though no land unit can walk on them.
        """
        self.worked_tiles = []
        if self.city_id is None or self.population <= 0:
            return
        game_map = game_env.map
        owner = game_map.owner_city
        # Read through the module so the radius is the live config value.
        rings = game_map.get_ring_coords(self.coordinates, territory.WORK_RADIUS)

        scored = []  # (-food, -production, pos) in canonical enumeration order
        for ring in rings[1:]:
            for pos in ring:
                if owner[pos] != self.city_id:
                    continue
                tile = game_map.get_tile(pos)
                if tile and not tile.impassable:
                    food, prod = tile.yields
                    scored.append((-food, -prod, pos))

        # Stable sort on (food, production) only: ties keep ring/(row, col) order.
        scored.sort(key=lambda entry: (entry[0], entry[1]))
        self.worked_tiles = [pos for _, _, pos in scored[:self.population]]

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

        Order: repair → collect food → consume → growth/starvation → culture →
        collect production → build.
        """
        # --- Repair phase (issue #84) ---
        # Civ 6: a city heals 20 HP per turn unless it is under siege. A
        # besieged city does not repair, which is what makes surrounding one
        # worth the units it costs.
        if self.health < CITY_HEALTH and not game_env.is_city_under_siege(self):
            self.health = min(CITY_HEALTH, self.health + CITY_HEAL_PER_TURN)

        # --- Food phase ---
        food_produced = self.calculate_food(game_env)
        food_consumed = 2 * self.population
        food_net = food_produced - food_consumed

        # Housing (issue #88 s2), read at the start of the food phase. The
        # band key is housing - population in tenths.
        percent = growth_percent(housing(self) - 10 * self.population)

        # `food_surplus` is the growth bucket in HUNDREDTHS of food (exact
        # integer arithmetic; a 1-food surplus at 25 % still accumulates).
        if food_net >= 0:
            self.food_surplus += food_net * percent
            if food_net > 0 and percent < 100:
                game_env.episode_stats[self.player.player_index]["growth_slowed_turns"] += 1
        else:
            # Starvation (never scaled by housing): drain the bucket first
            self.food_surplus += 100 * food_net  # food_net is negative
            if self.food_surplus < 0:
                self.food_surplus = 0
                if self.population > 1:
                    self.population -= 1
                    self.assign_tiles(game_env)

        # Population growth. The 0 % band is a hard cap: no growth even with
        # a full bucket (the bucket is kept).
        growth_threshold = 100 * self.get_growth_threshold()
        if percent > 0 and self.food_surplus >= growth_threshold:
            self.food_surplus -= growth_threshold
            self.population += 1
            self.assign_tiles(game_env)

        # --- Culture phase (issue #87) ---
        self._accrue_culture(game_env)

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

    def _accrue_culture(self, game_env):
        """Add this turn's culture (int tenths) to the border pool, the
        per-round counter and the owner's civic pool; at most once per round.
        """
        if self._culture_round == game_env.turn_counter:
            return
        self._culture_round = game_env.turn_counter
        yield_tenths = culture(self)
        self.border_culture += yield_tenths
        self.culture_this_round += yield_tenths
        self.player.culture += yield_tenths
        game_env.episode_stats[self.player.player_index]["culture_produced"] += yield_tenths

    def get_unit_cost(self, unit_type):
        """Get the production cost for a unit type."""
        temp_unit = Unit(None, None, unit_type)
        return temp_unit.get_production_cost()

    def get_building_cost(self, building_type):
        """Get the production cost for a building type."""
        return self.BUILDING_COSTS[building_type]

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
        """Transfer city ownership to a new player (the one capture hook).

        Borders design §2.3: the city keeps all its tiles and they change
        player with it — `Map.city_changed_player` moves the per-player tile
        counters and bumps territory_epoch. Culture pools go along untouched.
        """
        old_player = self.player
        if old_player:
            old_player.cities.remove(self)
        new_player.cities.append(self)
        self.player = new_player
        game_env = new_player.game_env
        game_env.map.city_changed_player(
            self, old_player.player_index if old_player else None
        )
        self.assign_tiles(game_env)


def _create_unit(unit_type, player, coordinates):
    """Factory function to create the appropriate unit subclass."""
    unit_classes = {
        "Warrior": WarriorUnit,
        "Slinger": SlingerUnit,
        "Archer": ArcherUnit,
        "Swordsman": SwordsmanUnit,
        "Spearman": SpearmanUnit,
        "Horseman": HorsemanUnit,
        "Catapult": CatapultUnit,
        "BatteringRam": BatteringRamUnit,
        "SiegeTower": SiegeTowerUnit,
        "Settler": SettlerUnit,
        "Worker": WorkerUnit,
    }
    cls = unit_classes.get(unit_type, Unit)
    if cls == Unit:
        return Unit(player, coordinates, unit_type)
    return cls(player, coordinates)
