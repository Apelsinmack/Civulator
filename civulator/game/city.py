"""City class with production, population, and buildings."""

from ..effects import (
    APPLIES_CITY,
    ITEM_BUILDING,
    ITEM_UNIT,
    KIND_CITY_RANGED_STRENGTH,
    KIND_GROWTH_PERCENT,
    KIND_POLICY_SLOTS,
    KIND_PRODUCTION_PERCENT,
    SOURCE_DISTRICT,
    active_effects,
    combat_strength_amounts,
    effects_of,
    percent_sum,
    target_matches,
)
from ..terrain_model import DOMAIN_WATER, can_enter
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
from .availability import city_can_build_building, player_can_build
from .culture import culture
from .districts import district_spec, district_yields, is_wonder, ship_spawn_districts
from .housing import housing
from .improvements import worker_has_work
from .loyalty import CAPTURED as LOYALTY_CAPTURED, FOUNDED as LOYALTY_FOUNDED
from .amenities import growth_percent as amenity_growth_percent
from .amenities import yield_percent as amenity_yield_percent
from .loyalty import growth_share, loyalty_percent
from .trade import TRADER_UNIT, end_routes_touching, trader_slot_free
from .yields import city_yield
from .unit import (
    Unit, WarriorUnit, SlingerUnit, ArcherUnit, SwordsmanUnit, SpearmanUnit,
    HorsemanUnit, CatapultUnit, BatteringRamUnit, SiegeTowerUnit,
    ManAtArmsUnit, PikemanUnit, CrossbowmanUnit, KnightUnit, TrebuchetUnit,
    MusketmanUnit, TraderUnit, SettlerUnit, WorkerUnit, GalleyUnit,
    QuadriremeUnit, CaravelUnit, MOVEMENT_DOMAIN, is_land_military, movement_domain,
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
        # The defender flag `Unit.attack` reads for the ranged penalty and the
        # floor at 0 (v0.9.0 Q3): a city and a fortified district answer True.
        self.is_fortification = True
        self.defense_strength = CITY_DEFENSE_STRENGTH
        self.buildings = []
        self.population = 1
        self.food_surplus = 0  # Growth bucket, in hundredths of food (issue #88)
        self.production = 0
        self.current_production = {"type": "unit", "unit_type": "Warrior"}
        self.worked_tiles = []  # List of (row, col) assigned to citizens
        # Culture (issue #87), all int tenths. border_culture is the city's
        # border pool; culture_this_round is what the border phase reads and
        # zeroes; _culture_round stamps the round of the last yield-phase
        # accrual (all four pool yields since #116).
        self.border_culture = 0
        self.culture_this_round = 0
        self._culture_round = None
        # Border cost index n (borders design §3.1): culture claims made so
        # far; founding claims don't count. Travels with the city on capture.
        self.border_claims = 0
        # Placed districts (issue #86), in placement order. Written only by
        # GameEnvironment.place_district / remove_city; travel with the city.
        self.districts = []
        # Loyalty (#116 P7, design §8.1), an int 0..[loyalty] maximum:
        # `[loyalty] founded` for a new city (GameEnvironment.create_city is
        # the engine's one constructor of a City), reset to `captured` by
        # set_owner, moved only by GameEnvironment._loyalty_phase. Travels
        # with the city.
        self.loyalty = LOYALTY_FOUNDED
        # Religion (v0.9.0 Q8, districts_religion_design §7.1, §7.5): the
        # founder index of the religion this city follows, None while
        # secular. Written by GameEnvironment.found_religion (the seat, v3
        # fixes L1), GameEnvironment._religion_phase (conversion) and
        # GameEnvironment.inquisition (v0.9.0 Q9). The city's, not the
        # owner's: it travels through set_owner (capture and flip) and
        # outlives its founder.
        self.religion = None
        # The religion engine's per-city state (v0.9.0 Q9, design §7.4, v3
        # fixes L6), all kept through set_owner like `religion`:
        # - directed-spread entries `(religion index, amount, rounds_left)`,
        #   in the order spread, appended by GameEnvironment.spread_religion,
        #   counted then decremented (removed at 0) by _religion_phase;
        self.spread_ledger = []
        # - the conversion streak `(candidate religion index, rounds)`,
        #   `(None, 0)` when none runs; written only by _religion_phase,
        #   found_religion (the seat) and inquisition;
        self.conversion_streak = (None, 0)
        # - inquisition immunity: phases left in which the city cannot
        #   convert; set by GameEnvironment.inquisition, decremented by
        #   _religion_phase.
        self.inquisition_rounds_left = 0

    def get_combat_strength(self, is_attacking=False, target=None):
        """Return the defensive combat strength of the city.

        Base defence plus every standing building's `defense_bonus` from
        config.toml `[buildings.*]` (issue #7), plus every `combat_strength`
        effect in force for this city with `applies_to` "city" (#116 P4, e.g.
        a policy card's +6). This is the number `Unit.attack` reads as the
        defender's strength when the target is a city, so a building's or an
        effect's defensive bonus is applied by the one combat path and not
        re-derived anywhere.
        """
        strength = self.defense_strength
        for building in self.buildings:
            strength += BUILDING_DEFENSE_BONUS.get(building, 0)
        for amount in combat_strength_amounts(self.player, APPLIES_CITY, city=self):
            strength += amount
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
        """The city's ranged strength (issue #84), `[city] ranged_strength`,
        plus every `city_ranged_strength` effect in force for this city
        (#116 P4; the one consumer of that kind).

        A flat number, unlike a unit's: Civ 6 derives it from the strongest
        ranged unit the civilization has built, which is not modelled (the
        tech tree exists since #116 P2; this rule does not), and it carries
        no health penalty -- a battered
        city shoots as hard as a fresh one. Both simplifications are named in
        the CHANGELOG.
        """
        strength = CITY_RANGED_STRENGTH
        for effect in active_effects(self.player, self, KIND_CITY_RANGED_STRENGTH):
            strength += effect["amount"]
        return strength

    def get_range(self):
        """Range of the city's ranged strike (`[city] ranged_range`)."""
        return CITY_RANGED_RANGE

    def can_produce_unit(self, unit_type):
        """Whether this city may start (or buy) a `unit_type`: its owner
        `player_can_build` it (#116 P2, P4), and -- for the trade unit
        (`[trade] unit`) -- the owner has a route slot no route or standing
        Trader fills (`trade.trader_slot_free`, #116 P5), and -- for the
        Worker -- the owner has a tile one could improve
        (`improvements.worker_has_work`, #116 P8): a Trader that could never
        be sent, a Worker with nothing to build, is an option that cannot pay
        off. The one unit predicate of `produce_unit`, the build mask and
        `purchase`.

        A water-domain unit (v0.9.0 Q5, districts_religion_design §6.4) is
        admitted only while the city has a spawn water tile
        (`ship_spawn_tiles`): a ship that could never be placed is an option
        that cannot pay off."""
        if not player_can_build(self.player, "unit", unit_type):
            return False
        if MOVEMENT_DOMAIN.get(unit_type) == DOMAIN_WATER:
            return bool(self.ship_spawn_tiles(unit_type, self.player.game_env))
        if unit_type == TRADER_UNIT:
            return trader_slot_free(self.player)
        if UNIT_CLASSES.get(unit_type) is WorkerUnit:
            return worker_has_work(self.player)
        return True

    def produce_unit(self, unit_type):
        """Start producing a unit. Refused (False, production unchanged)
        unless `can_produce_unit` holds."""
        if not self.can_produce_unit(unit_type):
            return False
        self.current_production = {"type": "unit", "unit_type": unit_type}
        return True

    def produce_building(self, building_type):
        """Start producing a building. Refused (False, production unchanged)
        unless `city_can_build_building` holds: a production cost (the
        Palace is granted, never built, #88), the owner's research, a
        complete required district and an owned required building (#116 P2)."""
        if not city_can_build_building(self, building_type):
            return False
        self.current_production = {"type": "building", "building_type": building_type}
        return True

    def _incomplete_district(self, district_type):
        """The city's oldest placed, unfinished district of this type, or None."""
        for district in self.districts:
            if district.type == district_type and not district.complete:
                return district
        return None

    def produce_district(self, district_type):
        """Resume building the city's placed, unfinished district of this type
        (oldest first). Refused (False) when there is none: placing is
        `GameEnvironment.place_district`, and a finished district cannot be
        built again (issue #86)."""
        if self._incomplete_district(district_type) is None:
            return False
        self.current_production = {"type": "district", "district_type": district_type}
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

        Only UNWORKABLE tiles are skipped — impassable ones (§3) and
        district tiles, placed or complete (issue #86).
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
                # A district replaces the tile's yields: never worked (#86).
                if tile and not tile.impassable and tile.district is None:
                    food, prod = tile.yields
                    scored.append((-food, -prod, pos))

        # Stable sort on (food, production) only: ties keep ring/(row, col) order.
        scored.sort(key=lambda entry: (entry[0], entry[1]))
        self.worked_tiles = [pos for _, _, pos in scored[:self.population]]

    def calculate_food(self, game_env):
        """Food this turn, whole points: `city_yield(city, "food")` -- the
        centre (always worked, free) plus worked tiles plus declared food
        sources such as building columns (#116). `game_env` is the city's own
        environment, which city_yield reads through `self.player`."""
        return city_yield(self, "food")

    def _production_item(self):
        """(item kind, type name) of what the city is producing, the input of
        a `production_percent` target (`effects.target_matches`); None when
        it produces nothing. A district's kind is its registry entry's
        (`district` or `wonder`, #116 P6)."""
        production = self.current_production
        if not production:
            return None
        if production["type"] == "unit":
            return ITEM_UNIT, production["unit_type"]
        if production["type"] == "building":
            return ITEM_BUILDING, production["building_type"]
        if production["type"] == "district":
            name = production["district_type"]
            return district_spec(name).kind, name
        return None

    def production_percent(self):
        """The summed `percent` of every `production_percent` effect in force
        for this city whose target matches its current production item (#116
        P4, design §2.3): unit name, unit class, unit era, building name,
        district, or item kind -- and, for a target with
        `no_specialty_district` (v0.9.0 Q7), this city having no complete
        specialty district. 0 when nothing matches."""
        item = self._production_item()
        if item is None:
            return 0
        return percent_sum(
            effect for effect in active_effects(self.player, self, KIND_PRODUCTION_PERCENT)
            if target_matches(effect["target"], *item, city=self)
        )

    def calculate_production(self, game_env):
        """Production this turn, whole points: `city_yield(city,
        "production")` -- centre plus worked tiles plus declared sources
        (building and district columns, the adjacency of complete districts
        yielding production, `city_yield` effects; #116) -- raised by the
        summed `production_percent` effects toward the current item, applied
        once with one integer floor (`base * (100 + percent) // 100`; the one
        consumer of that kind, #116 P4), then scaled once by the city's
        loyalty band (`loyalty.loyalty_percent`, integer floor; #116 P7) and
        then by its amenity band (`(100 + amenities.yield_percent) / 100`,
        integer floor; v0.9.0 Q2 -- production's amenity percent is applied
        here, beside its loyalty percent, not in `city_yield`), with a floor
        of 1, so a city can always build, slowly -- even in unrest."""
        base = city_yield(self, "production")
        raised = base * (100 + self.production_percent()) // 100
        scaled = raised * loyalty_percent(self) // 100
        return max(1, scaled * (100 + amenity_yield_percent(self, game_env)) // 100)

    def _growth_percent(self):
        """The summed `percent` of the `growth_percent` effects in force for
        this city (#116 P6; the Hanging Gardens' +15, scope player, reaches
        every city of its owner). Summed, then applied once in
        `growth_bucket_gain` (v2 fixes, N3)."""
        return percent_sum(active_effects(self.player, self, KIND_GROWTH_PERCENT))

    def growth_bucket_gain(self, food_net, housing_percent):
        """What a non-negative `food_net` adds to the growth bucket this turn,
        in hundredths of food (progression design "v2 fixes", yields):
        `food_net * housing_percent * growth_share * (100 + growth_percent)
        * amenity_growth // 1000000` -- the housing band (#88), the loyalty
        band's growth share (`loyalty.growth_share`, #116 P7), the summed
        `growth_percent` effects and the amenity band's growth percent
        (`amenities.growth_percent`, v0.9.0 Q2), one integer floor at the end.
        The one consumer of `growth_percent`. With no effect, full loyalty and
        a content city it is `food_net * housing_percent`, the v0.7 bucket
        exactly."""
        return (food_net * housing_percent * growth_share(self)
                * (100 + self._growth_percent())
                * amenity_growth_percent(self, self.player.game_env) // 1000000)

    def get_growth_threshold(self):
        """Food surplus needed to grow to next population level.

        Approximation of Civ 6: 15 + 10 * (pop - 1).
        Pop 1→2: 15, Pop 2→3: 25, Pop 3→4: 35, etc.
        """
        return 15 + 10 * (self.population - 1)

    def process_turn(self, game_env):
        """Process a game turn for this city.

        Order: repair → collect food → consume → growth/starvation → yields
        (science, culture, gold, faith) → collect production → build.
        """
        # --- Repair phase (issue #84) ---
        # Civ 6: a city heals 20 HP per turn unless it is under siege. A
        # besieged city does not repair, which is what makes surrounding one
        # worth the units it costs.
        if self.health < CITY_HEALTH and not game_env.is_city_under_siege(self):
            self.health = min(CITY_HEALTH, self.health + CITY_HEAL_PER_TURN)
        self._repair_fortified_districts(game_env)

        # --- Food phase ---
        food_produced = self.calculate_food(game_env)
        food_consumed = 2 * self.population
        food_net = food_produced - food_consumed

        # Housing (issue #88 s2), read at the start of the food phase. The
        # band key is housing - population in tenths.
        percent = growth_percent(housing(self) - 10 * self.population)

        # `food_surplus` is the growth bucket in HUNDREDTHS of food (exact
        # integer arithmetic; a 1-food surplus at 25 % still accumulates),
        # raised by the growth_percent effects in force (#116 P6).
        if food_net >= 0:
            self.food_surplus += self.growth_bucket_gain(food_net, percent)
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

        # Population growth. A 0 % band -- housing's, or loyalty's growth
        # share (#116 P7, Civ 6 Unrest: "no Population growth") -- is a hard
        # cap: no growth even with a full bucket (the bucket is kept).
        growth_threshold = 100 * self.get_growth_threshold()
        if (percent > 0 and growth_share(self) > 0
                and self.food_surplus >= growth_threshold):
            self.food_surplus -= growth_threshold
            self.population += 1
            self.assign_tiles(game_env)

        # --- Yield phase (issue #87 culture; #116 science, gold, faith) ---
        self._accrue_yields(game_env)

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

            elif self.current_production["type"] == "district":
                # Pays the cost locked at placement, like a building (#86).
                district = self._incomplete_district(self.current_production["district_type"])
                if district is None:
                    self.current_production = None
                elif self.production >= district.cost:
                    self.production -= district.cost
                    game_env.complete_district(self, district)

    def fortified_districts(self):
        """The city's fortified districts (v0.9.0 Q3): complete districts
        whose type has `health` (`District.is_fortification`), in placement
        order."""
        return [d for d in self.districts if d.is_fortification]

    def _repair_fortified_districts(self, game_env):
        """The repair of a fortified district (v0.9.0 Q3, districts_religion_
        design §4.2, "v2 fixes", "v3 fixes" L8), in the city's repair phase:
        `[city] heal_per_turn` up to its maximum unless its tile is besieged
        -- the same ring test as the centre, `is_city_under_siege` with the
        district's tile -- or an enemy unit stands on it (a breached
        Encampment does not mend under an occupier)."""
        for district in self.fortified_districts():
            if district.health >= district.max_health:
                continue
            if any(u.player is not self.player
                   for u in game_env.get_units_at(district.coordinates)):
                continue
            if game_env.is_city_under_siege(self, district.coordinates):
                continue
            district.health = min(district.max_health, district.health + CITY_HEAL_PER_TURN)

    def _accrue_yields(self, game_env):
        """The yield phase (#116 P1, progression design §2.2): add this
        turn's science, culture, gold and faith (int tenths) to the owner's
        pools and episode stats, at most once per round (the `_culture_round`
        stamp). Culture also fills the city's border pool and per-round
        counter (#87). A city captured after its old owner's turn therefore
        accrues once per round, for whoever processed it first.
        """
        if self._culture_round == game_env.turn_counter:
            return
        self._culture_round = game_env.turn_counter
        player = self.player
        stats = game_env.episode_stats[player.player_index]

        culture_tenths = culture(self)
        self.border_culture += culture_tenths
        self.culture_this_round += culture_tenths
        player.culture += culture_tenths
        stats["culture_produced"] += culture_tenths

        science_tenths = city_yield(self, "science")
        gold_tenths = city_yield(self, "gold")
        faith_tenths = city_yield(self, "faith")
        player.science += science_tenths
        player.gold += gold_tenths
        player.faith += faith_tenths
        stats["science_produced"] += science_tenths
        stats["gold_produced"] += gold_tenths
        stats["faith_produced"] += faith_tenths

        # The raw adjacency score per yield (#86 s5), unscaled; same guard.
        for name, score in district_yields(self).items():
            stats[f"district_yield_{name}"] += score

    def get_unit_cost(self, unit_type):
        """Get the production cost for a unit type."""
        temp_unit = Unit(None, None, unit_type)
        return temp_unit.get_production_cost()

    def get_building_cost(self, building_type):
        """Get the production cost for a building type."""
        return self.BUILDING_COSTS[building_type]

    def ship_spawn_tiles(self, unit_type, game_env):
        """The tiles a new water-domain `unit_type` of this city's owner may
        appear on, in candidate order (v0.9.0 Q5, districts_religion_design
        §6.4): the tile of each complete `ship_spawn` district of the city
        (the Harbor), then the water tiles adjacent to the centre in
        `Map.get_adjacent_coords` order -- each one the unit's movement
        domain for its owner can enter (`movement_domain`), never a land
        tile, no tile twice. A Lake beside the centre counts. Occupancy is
        not read: this is where the city COULD put a ship (the build
        predicate); `complete_unit_production` takes the first free one."""
        if game_env is None:
            return []
        domain = movement_domain(unit_type, self.player)
        tiles = []
        for district in ship_spawn_districts(self):
            tiles.append(tuple(district.coordinates))
        tiles += [tuple(pos) for pos in game_env.map.get_adjacent_coords(self.coordinates)]
        out = []
        for pos in tiles:
            if pos not in out and can_enter(domain, game_env.map.get_tile(pos)):
                out.append(pos)
        return out

    def complete_unit_production(self, unit_type, game_env):
        """Place a newly produced unit on the city tile or first empty adjacent tile.

        Priority: city center > the city's complete fortified districts (an
        Encampment; v0.9.0 Q3, districts_religion_design §4.1 -- for a land
        military unit only, `unit.is_land_military`: never a civilian or
        siege support, never a water-domain unit) >
        adjacent tiles. Every candidate goes through the canonical
        terrain-domain check (§3.3, §9.10) — production may not drop a land
        unit into a lake or onto a mountain — and a fortified-district tile,
        like an adjacent one, must hold no unit at all.
        A water-domain unit (v0.9.0 Q5, §6.4) goes to the first free tile of
        `ship_spawn_tiles` (the Harbor, then the adjacent water tiles), never
        to land; it counts `episode_stats["naval_units_built"]`.
        If none is available, returns False (unit deferred to next turn).
        """
        domain = movement_domain(unit_type, self.player)

        if MOVEMENT_DOMAIN.get(unit_type) == DOMAIN_WATER:
            for pos in self.ship_spawn_tiles(unit_type, game_env):
                if game_env.is_valid_position(pos) and not game_env.is_occupied(pos):
                    unit = _create_unit(unit_type, self.player, pos)
                    self.player.units.append(unit)
                    game_env.add_unit_to_tile(unit, pos)
                    game_env.episode_stats[self.player.player_index]["naval_units_built"] += 1
                    return True
            return False

        # Try city center first
        friendly_on_center = any(
            u.player == self.player for u in game_env.get_units_at(self.coordinates)
        )
        if not friendly_on_center and can_enter(domain, game_env.map.get_tile(self.coordinates)):
            unit = _create_unit(unit_type, self.player, self.coordinates)
            self.player.units.append(unit)
            game_env.add_unit_to_tile(unit, self.coordinates)
            return True

        # The Encampment (v0.9.0 Q3): land military units only -- the one
        # "land military" definition (fighting class AND land domain, Q5).
        if is_land_military(unit_type):
            for district in self.fortified_districts():
                pos = district.coordinates
                if not can_enter(domain, game_env.map.get_tile(pos)):
                    continue
                if game_env.is_occupied(pos):
                    continue
                unit = _create_unit(unit_type, self.player, pos)
                self.player.units.append(unit)
                game_env.add_unit_to_tile(unit, pos)
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

    def place_or_queue_unit(self, unit_type, game_env):
        """Place a `unit_type` the owner is owed here -- a purchased unit,
        a returning Trader (#116 P5) -- through `complete_unit_production`;
        if it cannot be placed, append `(city_id, unit_type)` to the owner's
        `queued_units`, which `Player.start_turn` places later. Returns True
        if the unit stands on the board now."""
        if self.complete_unit_production(unit_type, game_env):
            return True
        self.player.queued_units.append((self.city_id, unit_type))
        return False

    def set_owner(self, new_player):
        """Transfer city ownership to a new player -- the one place a city
        changes hands, by force (`GameEnvironment._capture_city`) or by loyalty
        (`GameEnvironment._flip_city`, #116 P7). Either way its loyalty resets
        to `[loyalty] captured` (design §8.1, "v2 fixes": a conquest must be
        consolidated), and every complete fortified district's health to its
        `captured_health_percent` of the maximum (v0.9.0 Q3).

        Its districts and wonders go with it as they are (#86; #116 P6): a
        complete wonder's player-scoped effects serve the new owner from now
        on (`effects.active_effects` reads the owner's cities), and nothing
        fires -- one-shot effects fire only in
        `GameEnvironment.complete_district`, which a complete wonder never
        reaches again.

        Borders design §2.3: the city keeps all its tiles and they change
        player with it — `Map.city_changed_player` moves the per-player tile
        counters and bumps territory_epoch. Culture pools go along untouched.
        #116 P5 (design "v2 fixes", flips and captures): the old owner's
        queued units for this city are dropped, and every trade route of any
        player that starts or ends here ends (`trade.end_routes_touching`):
        a route whose origin its owner still holds returns its Trader there,
        one whose origin was this city is lost.
        #116 P9 (wonder rulings): when the city holds a complete wonder that
        grants policy slots (`holds_policy_slot_wonder`), both players' slots
        changed, so both loadouts are re-fit through the engine's government
        and loadout defaults -- the old owner's falls back to what its slots
        hold, the new owner's fills the new slot.
        v0.9.0 Q8 (districts_religion_design §7.5): `religion` is the city's,
        not the owner's -- it is kept through either door, so the follower
        beliefs keep holding here and the founder keeps being paid for it;
        v0.9.0 Q9: so are its `spread_ledger`, `conversion_streak` and
        `inquisition_rounds_left` (nothing here touches them).
        """
        old_player = self.player
        if old_player:
            old_player.cities.remove(self)
        new_player.cities.append(self)
        self.player = new_player
        self.loyalty = LOYALTY_CAPTURED
        # Fortified districts go with the city at `captured_health_percent`
        # of their maximum (v0.9.0 Q3, districts_religion_design §4.2),
        # through either door -- capture or loyalty flip.
        for district in self.fortified_districts():
            spec = district_spec(district.type)
            district.health = spec.health * spec.captured_health_percent // 100
        game_env = new_player.game_env
        game_env.map.city_changed_player(
            self, old_player.player_index if old_player else None
        )
        if old_player is not None:
            old_player.queued_units = [
                entry for entry in old_player.queued_units if entry[0] != self.city_id
            ]
        end_routes_touching(game_env, self.city_id)
        self.assign_tiles(game_env)
        if self.holds_policy_slot_wonder():
            for player in (old_player, new_player):
                if player is not None:
                    game_env._government_and_loadout_defaults(player, refit=True)

    def holds_policy_slot_wonder(self):
        """Whether the city holds a COMPLETE wonder (`kind = "wonder"`) whose
        effects include `policy_slots`: one whose change of hands changes the
        slots of both its old and its new owner (`set_owner`)."""
        return any(
            district.complete and is_wonder(district.type)
            and any(effect.kind == KIND_POLICY_SLOTS
                    for effect in effects_of(SOURCE_DISTRICT, district.type))
            for district in self.districts
        )


# Unit type name -> its Unit subclass (#116 P3): the one exported registry of
# "which class does this type instantiate". `_create_unit` builds from it, and
# so do scripts/matchup_matrix.py and civulator/tools/recording.py -- a unit
# type is added here once, beside its [units.*] table (CLAUDE.md, Unit system
# row), never in a second dict. tests/test_combat_classes.py asserts it covers
# every configured unit type and nothing else.
UNIT_CLASSES = {
    "Warrior": WarriorUnit,
    "Slinger": SlingerUnit,
    "Archer": ArcherUnit,
    "Swordsman": SwordsmanUnit,
    "Spearman": SpearmanUnit,
    "Horseman": HorsemanUnit,
    "Catapult": CatapultUnit,
    "BatteringRam": BatteringRamUnit,
    "SiegeTower": SiegeTowerUnit,
    "Man-At-Arms": ManAtArmsUnit,
    "Pikeman": PikemanUnit,
    "Crossbowman": CrossbowmanUnit,
    "Knight": KnightUnit,
    "Trebuchet": TrebuchetUnit,
    "Musketman": MusketmanUnit,
    "Trader": TraderUnit,
    "Settler": SettlerUnit,
    "Worker": WorkerUnit,
    "Galley": GalleyUnit,
    "Quadrireme": QuadriremeUnit,
    "Caravel": CaravelUnit,
}


def _create_unit(unit_type, player, coordinates):
    """Factory function to create the appropriate unit subclass.

    A type with no entry in UNIT_CLASSES raises: a silent fall-back to the
    bare `Unit` would strip a ranged unit of its ranged attack and a siege
    unit of its rules, and look like a working unit.
    """
    try:
        cls = UNIT_CLASSES[unit_type]
    except KeyError:
        raise ValueError(
            f"unknown unit type {unit_type!r}: not in UNIT_CLASSES (game/city.py)"
        ) from None
    return cls(player, coordinates)
