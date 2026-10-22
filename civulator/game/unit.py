"""Unit classes for all game units."""

import math
import random

import numpy as np

from ..config import CFG
from ..effects import (
    KIND_BUILD_CHARGES,
    KIND_BUILD_CHARGES_TRAINED,
    RULE_FLANKING,
    amount_sum,
    combat_strength_amounts,
    rule_enabled,
)
from ..terrain_model import can_enter
from ..unit_model import (
    BASE_COMBAT_STRENGTH as _BASE_COMBAT_STRENGTH,
    BASE_RANGED_STRENGTH as _BASE_RANGED_STRENGTH,
    BUILD_CHARGES as _BUILD_CHARGES,
    COMBAT_CLASS as _COMBAT_CLASS,
    DAMAGE_BASE,
    DAMAGE_EXPONENT_COEFFICIENT,
    DAMAGE_ROLL_MAX,
    DAMAGE_ROLL_MIN,
    FLANKING_BONUS,
    FORTIFICATION_BONUS,
    HEAL_FORTIFIED,
    HEAL_NORMAL,
    HP_PENALTY_COEFFICIENT,
    MAX_MOVEMENT as _MAX_MOVEMENT,
    PRODUCTION_COST as _PRODUCTION_COST,
    RANGED_CITY_PENALTY,
    RANGE_VALUES as _RANGE_VALUES,
    STRENGTH_COMBAT,
    STRENGTH_RANGED,
    ZOC_FROM_RANGED,
    class_bonus_amounts,
)

# Rivers cost this much extra to cross, per edge (design doc D23) — the single
# source, replacing the two hardcoded +1s this file used to carry. A* does not
# see it until patch P6 (E3).
RIVER_CROSSING_COST = CFG.get("terrain", {}).get("river", {}).get("crossing_cost", 1)

NUM_UNIT_SLOTS = 4  # Military, Civilian, Siege Support, Great Person

# Which slot each unit type occupies
# Each slot can hold at most one unit per tile.
# Units in different slots can stack freely on the same tile.
#
# NUM_UNIT_SLOTS and UNIT_SLOT stay here, NOT in config.toml (issue #64):
# this is action-space architecture, not a tunable gameplay number —
# NUM_UNIT_SLOTS is welded into the neural network output shape
# (agents/networks.py:100, :281), so changing either invalidates every
# trained .pth.
UNIT_SLOT = {
    "Warrior": 0,      # military
    "Slinger": 0,
    "Archer": 0,
    "Swordsman": 0,
    "Spearman": 0,
    "Horseman": 0,
    "Settler": 1,      # civilian
    "Worker": 1,
    "Catapult": 0,     # military (siege weapon, not siege support)
    "BatteringRam": 2, # siege support (stacks with military)
    "SiegeTower": 2,   # siege support
    "Man-At-Arms": 0,  # military (#116 P3)
    "Pikeman": 0,
    "Crossbowman": 0,
    "Knight": 0,
    "Trebuchet": 0,    # military, like the Catapult
    "Musketman": 0,
    "Trader": 1,       # civilian
    # Great people (slot 3) — future
}

# Movement domain per unit type (design doc §3.3) — the sixth unit data table.
# Everything is land in 0.6; naval units and embarkation are the seam this
# leaves open (a new domain value + a capability check inside can_enter).
#
# Stays here, NOT in config.toml (issue #64): it is about to stop being a
# static table once tech/embarkation exists (issue #76), so freezing today's
# shape into config would commit to the wrong shape.
MOVEMENT_DOMAIN = {
    "Warrior": "land",
    "Slinger": "land",
    "Archer": "land",
    "Swordsman": "land",
    "Spearman": "land",
    "Horseman": "land",
    "Settler": "land",
    "Worker": "land",
    "Catapult": "land",
    "BatteringRam": "land",
    "SiegeTower": "land",
    "Man-At-Arms": "land",
    "Pikeman": "land",
    "Crossbowman": "land",
    "Knight": "land",
    "Trebuchet": "land",
    "Musketman": "land",
    "Trader": "land",
}


# Unit types that have complete stats but are deliberately NOT in
# agents/build_agent.py's BUILD_OPTIONS (issue #67). Statted-but-unbuildable
# is exactly the failure this registry exists to make explicit rather than
# implicit: the Swordsman sat in the tables unbuildable for an entire epoch
# because nothing said whether that was a decision or an oversight.
#
# tests/test_build_options.py asserts the partition is total: every statted
# unit type is either a BUILD_OPTIONS entry or named here.
DEFERRED_BUILD_UNITS = {
    # BatteringRam / SiegeTower: stats exist (issue #66) but their Civ 6
    # mechanic — an adjacency that changes how ANOTHER unit's attack resolves
    # against a city's walls — does not, and cannot until there is a wall model
    # to break. Offering them today would be a build option that cannot pay
    # off. They come out of here in the same patch that gives them the
    # adjacency rule.
    "BatteringRam",
    "SiegeTower",
    # (The Trader sat here from #116 P3 until P5 gave it trade routes; it is a
    # build option now, offered only while its owner has a free route slot.
    # The Worker sat here until #116 P8 gave it the engine default that builds
    # improvements; it is a build option now, offered only while its owner has
    # a tile one could improve -- improvements.worker_has_work.)
}


def movement_domain(unit_type):
    """Movement domain of a unit type — for callers placing a unit that doesn't exist yet."""
    return MOVEMENT_DOMAIN.get(unit_type, "land")


def calculate_damage(attacker_strength, defender_strength, rng=None):
    """
    Calculate damage using the Civ6 formula.

    Damage(HP) = 30 * e^(0.04 * StrengthDifference) * random(80%, 120%)

    The roll draws from rng (the game's seeded RNG) when given, so combat
    outcomes are reproducible; falls back to the global random module.

    Module level, not a Unit method, because a city's ranged attack (issue
    #84) resolves through the same formula and a City is not a Unit. This is
    the one damage formula in the engine (CLAUDE.md canonical Combat row);
    `Unit.calculate_damage` delegates here.
    """
    strength_diff = attacker_strength - defender_strength
    base_damage = DAMAGE_BASE * math.exp(DAMAGE_EXPONENT_COEFFICIENT * strength_diff)
    random_factor = (rng if rng is not None else random).uniform(DAMAGE_ROLL_MIN, DAMAGE_ROLL_MAX)
    damage = base_damage * random_factor
    return max(1, min(100, damage))


class Unit:
    """Base class for all units in the game."""

    # --- Static data tables ---
    # Values live in config.toml [units.*] (issue #64), interpreted once at
    # import by civulator/unit_model.py; aliased here so existing call sites
    # (Unit.MAX_MOVEMENT etc., across agents/build_agent.py, tests, ...) keep
    # working unchanged.

    MAX_MOVEMENT = _MAX_MOVEMENT
    BASE_COMBAT_STRENGTH = _BASE_COMBAT_STRENGTH
    BASE_RANGED_STRENGTH = _BASE_RANGED_STRENGTH
    RANGE_VALUES = _RANGE_VALUES
    PRODUCTION_COST = _PRODUCTION_COST
    # unit type -> combat class (#116 P3): the one class registry. Every rule
    # that treats units by role reads it (class_bonuses rows, the siege
    # rules, civilian capture, the encoder's class channel).
    COMBAT_CLASS = _COMBAT_CLASS

    def __init__(self, player, coordinates, unit_type):
        self.player = player
        self.coordinates = coordinates
        self.unit_type = unit_type
        self.health = 100.0
        self.movement_points = self.get_max_movement()
        self.fortification = 0  # 0, 1, or 2
        self.has_acted = False  # Did this unit act this turn?

    def __str__(self):
        return (
            f"Type: {self.unit_type}, Health: {self.health}, "
            f"Team: {self.player.name}, Location: {self.coordinates}"
        )

    @property
    def slot(self):
        """Unit slot index for tile stacking rules."""
        return UNIT_SLOT.get(self.unit_type, 0)

    @property
    def combat_class(self):
        """This unit's combat class (`[units.<Type>] combat_class`), or None
        for a type with no table."""
        return self.COMBAT_CLASS.get(self.unit_type)

    def is_civilian(self):
        """Whether this unit is a civilian: captured, not killed, when beaten
        (`GameEnvironment._execute_attack`). Keyed on the class, so a Trader
        is one without being named anywhere."""
        return self.combat_class == "civilian"

    def get_max_movement(self):
        return self.MAX_MOVEMENT.get(self.unit_type, 2)

    def get_movement_domain(self):
        return movement_domain(self.unit_type)

    def can_enter(self, tile):
        """Whether this unit's domain may stand on `tile` (design doc §3.3).

        Terrain only — occupancy (slots) is a separate check. Delegates to the
        one canonical implementation in terrain_model.
        """
        return can_enter(self.get_movement_domain(), tile)

    def step_cost(self, from_coords, to_coords, game_env):
        """Movement points one step from `from_coords` to the ADJACENT
        `to_coords` costs: the destination tile's cost plus the river-crossing
        surcharge (D23) when a river runs along the shared edge.

        The single source for "what does this step cost" — `move()` (both its
        adjacent fast path and its pathfinder walk) and the action masks
        (`agents/networks.py`) read it, so the mask can never offer a step the
        unit cannot pay for (issue #51).
        """
        cost = game_env.map.get_tile(to_coords).movement_cost
        if game_env.is_river_between(from_coords, to_coords):
            cost += RIVER_CROSSING_COST
        return cost

    def current_tile(self):
        """The tile this unit stands on, or None when it has no environment yet."""
        env = self.player.game_env if self.player is not None else None
        return env.map.get_tile(self.coordinates) if env is not None else None

    def get_base_combat_strength(self):
        return self.BASE_COMBAT_STRENGTH.get(self.unit_type, 10)

    def get_base_ranged_strength(self):
        return self.BASE_RANGED_STRENGTH.get(self.unit_type, 0)

    def get_range(self):
        return self.RANGE_VALUES.get(self.unit_type, 1)

    def get_production_cost(self):
        return self.PRODUCTION_COST.get(self.unit_type, 40)

    def can_capture_city(self):
        """Whether this unit may occupy an enemy city and take it (issue #84).

        Civ 6's rule: only a melee-capable land unit captures. A ranged unit
        bombards a city to 0 HP but cannot hold the ground; a civilian or a
        siege support unit (combat strength 0) cannot take it either. The
        three clauses are exactly that — land domain, it fights, and it
        fights in melee.

        Read by `Unit.move` (which refuses to enter an enemy city tile this
        returns False for), by `GameEnvironment._capture_city`, and by the
        action mask, so no mask-legal order can be a capture the engine then
        refuses (#51).
        """
        return (
            self.get_movement_domain() == "land"
            and self.get_base_combat_strength() > 0
            and self.get_base_ranged_strength() == 0
        )

    def enemy_city_blocks(self, coordinates, game_env):
        """Whether an enemy city on `coordinates` refuses this unit entry.

        The engine precondition behind the capture gate (issue #84): a city
        may be entered only once its health is 0, and only by a unit that can
        capture it. Everything else is barred, so a ranged unit can never end
        up standing in an enemy city it is not allowed to own.
        """
        tile = game_env.map.get_tile(coordinates)
        city = getattr(tile, "city", None)
        if city is None or city.player is self.player:
            return False
        return city.health > 0 or not self.can_capture_city()

    def projects_zone_of_control(self):
        """Whether this unit exerts zone of control (issue #84).

        A land military unit does: land domain and combat strength above 0,
        which excludes Settlers, Workers and the siege support units. Ranged
        units do not, unless `[combat] zone_of_control_from_ranged` says
        otherwise -- Civ 6 projects ZoC from melee, anti-cavalry and mounted
        units only.

        ZoC exists in this engine for exactly one purpose: deciding whether a
        city is under siege (`GameEnvironment.is_city_under_siege`). Its
        movement effect -- entering an enemy ZoC ends a unit's movement -- is
        NOT implemented, and nothing should assume it is.
        """
        return (
            self.get_movement_domain() == "land"
            and self.get_base_combat_strength() > 0
            and (ZOC_FROM_RANGED or self.get_base_ranged_strength() == 0)
        )

    def is_siege_class(self):
        """Whether this unit belongs to the siege class (issue #66).

        Declared per unit type by `combat_class = "siege"` in config.toml
        `[units.*]` (#116 P3; it was a boolean `siege_class` column), so a
        further siege unit is a config line rather than a name in an `if`.
        The class decides both siege rules: exemption from the flat ranged
        penalty against cities, and the movement the bombard needs (`attack`).
        Read from the class registry at call time, with `is_civilian`: the two
        queries whose whole job is to name a class.
        """
        return self.combat_class == "siege"

    def reset_movement(self):
        """Reset movement points at the start of a new turn.

        Fortification only builds up if the unit didn't act last turn.
        Moving or attacking resets fortification to 0.
        """
        self.movement_points = self.get_max_movement()
        if not self.has_acted:
            # Unit stayed still — fortify
            if self.fortification < 2:
                self.fortification += 1
        else:
            # Unit moved or attacked — lose fortification
            self.fortification = 0
        self.has_acted = False

    def heal(self):
        """Heal at start of turn. Fortified units heal more.

        +HEAL_NORMAL HP base, +HEAL_FORTIFIED HP if fortified. Capped at 100.
        """
        if self.health >= 100:
            return
        if self.fortification > 0:
            self.health = min(100, self.health + HEAL_FORTIFIED)
        else:
            self.health = min(100, self.health + HEAL_NORMAL)

    def get_combat_strength(self, is_attacking=False, target=None):
        """
        Calculate total combat strength with all modifiers.

        Uses Civ6-inspired modifier stacking:
        - Health penalty
        - Terrain defense bonus (when defending)
        - Fortification bonus (when defending)
        - Unit class advantages
        """
        strength = self.get_base_combat_strength()

        # Health penalty: HP_PENALTY_COEFFICIENT * (100 - HP) / 100 — the same
        # coefficient used in get_ranged_strength below (config.toml [combat]).
        hp_penalty = HP_PENALTY_COEFFICIENT * (100 - self.health) / 100
        strength += hp_penalty

        # Terrain defense (only when defending) — the CURRENT tile's composed
        # value, which stacks relief and feature by construction (§3.1). The
        # pre-0.6 spawn-time terrain snapshot froze this at the spawn tile
        # (§9.7) and needed a hand-written Hills+Woods special case.
        if not is_attacking:
            tile = self.current_tile()
            if tile is not None:
                strength += tile.defense_bonus

        # Fortification bonus (only when defending)
        if not is_attacking and self.fortification > 0:
            fort_bonus = FORTIFICATION_BONUS[self.fortification - 1]
            strength += fort_bonus

        # Unit class advantages — applied whether this unit attacks or defends
        # (issue #63). Gating them behind is_attacking meant a Spearman standing
        # still and being charged got no anti-cavalry bonus, which is the one
        # thing the unit exists to do. Civ 6 applies these in both directions.
        #
        # `target` may be a City, which has no unit_type — class bonuses are
        # unit-vs-unit, so a city simply matches none of them. Read through
        # getattr rather than assuming: before #7 made Walls buildable no
        # engine order ever aimed at a city, and this line raised
        # AttributeError the moment one did.
        #
        # The rows are `[combat] class_bonuses` with strength = "combat"
        # (#116 P3): matched by unit name or combat class, never by a name
        # written here. Ranged-strength rows are get_ranged_strength's.
        target_type = getattr(target, "unit_type", None)
        if target_type is not None:
            for amount in class_bonus_amounts(STRENGTH_COMBAT, self.unit_type, target_type):
                strength += amount

        # `combat_strength` effects in force for the owner (#116 P4: a
        # government's or a policy card's bonus to a combat class, or to
        # every unit), in BOTH roles like the class bonuses, added one by one.
        # Matched by class through the effects interpreter, never by a name
        # written here.
        for amount in self._effect_strength_amounts():
            strength += amount

        # Flanking (issue #59): the unit that is STRIKING gets a bonus per
        # neighbouring tile of its target that holds one of its own
        # combat-capable units. See flanking_count for the exact rule and for
        # why it is the striker rather than the defender who gets it. Since
        # #116 P4 the rule is a civic unlock (Civ 6's Military Tradition):
        # it holds only while an `enables` effect in force for the striker's
        # owner names it.
        if is_attacking and FLANKING_BONUS and rule_enabled(self.player, RULE_FLANKING):
            strength += FLANKING_BONUS * self.flanking_count(target)

        return max(0, strength)

    def _effect_strength_amounts(self):
        """The `combat_strength` effect amounts in force for this unit's owner
        that apply to its combat class (or to every unit), in order; none
        without an owner. Read by get_combat_strength and get_ranged_strength."""
        if self.player is None:
            return []
        return combat_strength_amounts(self.player, self.combat_class)

    def flanking_count(self, target):
        """How many tiles adjacent to `target` hold a flanking unit of ours.

        Counted per TILE, not per unit: a tile can stack up to four units in
        different slots (a Warrior, a Settler, a siege support), and a stack is
        one position pressing on the defender, not three. A tile counts when it
        holds at least one unit that

        - belongs to this unit's player,
        - is not this unit itself (Civ 6 counts the *other* units around the
          defender; the attacker is already in the exchange), and
        - has a base combat strength above 0, so Settlers and Workers being
          escorted alongside an army do not flank.

        Adjacency comes from `Map.get_adjacent_coords`, which delegates to the
        canonical hex kernels in `civulator/hexmath.py` — wrap included. No
        neighbour arithmetic is written here; that is the invariant the
        ranged-attack bug (#24) was caused by breaking.

        Returns 0 whenever the answer cannot be known (no environment, or a
        target with no position), so a unit built outside a game never raises.
        """
        env = self.player.game_env if self.player is not None else None
        target_coords = getattr(target, "coordinates", None)
        if env is None or target_coords is None:
            return 0

        count = 0
        for pos in env.map.get_adjacent_coords(target_coords):
            for other in env.get_units_at(pos):
                if (
                    other is not self
                    and other.player is self.player
                    and other.get_base_combat_strength() > 0
                ):
                    count += 1
                    break
        return count

    def get_ranged_strength(self, target=None, is_city=False):
        """Calculate ranged strength including modifiers."""
        if self.get_base_ranged_strength() == 0:
            return 0

        strength = self.get_base_ranged_strength()

        # Health penalty (same coefficient as get_combat_strength above)
        hp_penalty = HP_PENALTY_COEFFICIENT * (100 - self.health) / 100
        strength += hp_penalty

        # Penalty against cities — but not for the siege class (issue #66).
        # The flat penalty stands in for a wall model we have not built, and
        # was being applied to the one class Civ 6 exempts from exactly this
        # reduction: a Catapult exists to break fortifications, and until #66's
        # wall model lands the honest approximation is that it does so at full
        # strength while other ranged units do not.
        if is_city and not self.is_siege_class():
            strength -= RANGED_CITY_PENALTY

        # Class-pair modifiers of the SHOOTER (`[combat] class_bonuses` rows
        # with strength = "ranged", #116 P3): a row applies to this unit as the
        # one firing, never to a defender -- the archer penalty vs cavalry is
        # exactly that. getattr, not target.unit_type: the target may be a City
        # (see the note in get_combat_strength).
        target_type = getattr(target, "unit_type", None)
        if target_type is not None:
            for amount in class_bonus_amounts(STRENGTH_RANGED, self.unit_type, target_type):
                strength += amount

        # `combat_strength` effects apply to the shooter's ranged strength
        # too (#116 P4, design §3: "both roles").
        for amount in self._effect_strength_amounts():
            strength += amount

        return max(0, strength)

    def move(self, new_coordinates, game_env):
        """
        Move the unit to new coordinates.

        For adjacent tiles (distance 1), moves directly without pathfinding.
        For longer moves, uses the pathfinder to determine the route.

        Returns:
            tuple: (moved: bool, final_position: tuple)
        """
        dest = tuple(new_coordinates)
        if dest == self.coordinates:
            return False, self.coordinates

        # Check terrain at destination
        dest_tile = game_env.map.get_tile(dest)
        if not self.can_enter(dest_tile):
            return False, self.coordinates

        # A standing enemy city bars the way, and a unit that cannot capture
        # never enters one at all (issue #84).
        if self.enemy_city_blocks(dest, game_env):
            return False, self.coordinates

        # Check if destination is adjacent (distance 1) — bypass pathfinder
        adj_coords = game_env.map.get_adjacent_coords(self.coordinates)
        if dest in adj_coords:
            movement_cost = self.step_cost(self.coordinates, dest, game_env)

            if self.movement_points < movement_cost:
                return False, self.coordinates

            # Check slot-based occupancy: can move if our slot is free (friendly)
            units_at_dest = game_env.get_units_at(dest)
            friendly_in_slot = any(
                u.player == self.player and u.slot == self.slot
                for u in units_at_dest
            )
            if friendly_in_slot:
                return False, self.coordinates  # Same slot occupied by friendly

            game_env.remove_unit_from_tile(self, self.coordinates)
            self.coordinates = dest
            self.movement_points -= movement_cost
            game_env.add_unit_to_tile(self, self.coordinates)
            self.fortification = 0
            self.has_acted = True
            return True, self.coordinates

        # Non-adjacent: use pathfinder
        start_pos = np.array(self.coordinates)
        dest_pos = np.array(new_coordinates)
        path = game_env.path_finder(start_pos, dest_pos, domain=self.get_movement_domain())

        if not path:
            return False, self.coordinates

        remaining_mp = self.movement_points
        current_pos = np.array(self.coordinates)
        final_pos = current_pos.copy()

        for next_pos in path:
            next_pos_tuple = tuple(next_pos)
            current_pos_tuple = tuple(current_pos)

            next_tile = game_env.map.get_tile(next_pos_tuple)
            if not self.can_enter(next_tile):
                break
            # Same enemy-city gate as the adjacent fast path (#84) — a walk
            # must not slip a unit into a city an order could not.
            if self.enemy_city_blocks(next_pos_tuple, game_env):
                break
            movement_cost = self.step_cost(current_pos_tuple, next_pos_tuple, game_env)

            if remaining_mp < movement_cost:
                break

            # Check if our slot is blocked by a friendly unit (except at destination)
            if next_pos_tuple != dest:
                units_there = game_env.get_units_at(next_pos_tuple)
                if any(u.player == self.player and u.slot == self.slot for u in units_there):
                    break

            remaining_mp -= movement_cost
            current_pos = next_pos
            final_pos = current_pos.copy()

            if tuple(current_pos) == tuple(dest_pos):
                break

        if np.array_equal(final_pos, self.coordinates):
            return False, self.coordinates

        game_env.remove_unit_from_tile(self, self.coordinates)
        self.coordinates = tuple(final_pos)
        self.movement_points = remaining_mp
        game_env.add_unit_to_tile(self, self.coordinates)
        self.fortification = 0
        self.has_acted = True

        return True, self.coordinates

    def fortify(self):
        """Fortify the unit, increasing defensive capabilities."""
        if self.movement_points > 0:
            self.fortification = 1
            self.movement_points = 0
            self.has_acted = True
            return True
        return False

    def calculate_damage(self, attacker_strength, defender_strength, rng=None):
        """The Civ6 damage formula — see module-level `calculate_damage`.

        Kept as a method because every existing caller reaches it through a
        unit; it holds no per-unit state and simply delegates, so a city's
        bombard (issue #84) can use the same formula without pretending to
        be a Unit.
        """
        return calculate_damage(attacker_strength, defender_strength, rng=rng)

    def attack(self, target, game_env, is_ranged=False):
        """
        Attack another unit.

        Returns:
            tuple: (damage_dealt, damage_received, target_killed, attacker_killed)
        """
        if self.movement_points < 0.25:
            return 0, 0, False, False

        # The siege class may fire only with a full movement point left (Civ 6:
        # a Catapult cannot attack after moving). Keyed on the class (#116 P3),
        # so the Trebuchet obeys it without being named.
        if is_ranged and self.is_siege_class() and self.movement_points < 1:
            return 0, 0, False, False

        # Calculate strengths
        if is_ranged:
            is_city = hasattr(target, "is_city") and target.is_city
            attacker_strength = self.get_ranged_strength(target, is_city)
            damage_received = 0
        else:
            attacker_strength = self.get_combat_strength(True, target)
            defender_counterattack_strength = target.get_combat_strength(True, self)

        defender_strength = target.get_combat_strength(False, self)

        # Calculate and apply damage
        rng = getattr(game_env, "rng", None)
        damage_dealt = self.calculate_damage(attacker_strength, defender_strength, rng=rng)
        target.health -= damage_dealt

        # A city is never destroyed (issue #84): its health floors at 0 and it
        # waits to be occupied, so `target_killed` — which means "remove this
        # from the board" to every caller — is always False for a city. The
        # signal that a city has fallen is `city.health == 0`, which is what
        # the capture gate and the action mask both read.
        if getattr(target, "is_city", False):
            target.health = max(0, target.health)
            target_killed = False
        else:
            target_killed = target.health <= 0

        # Counterattack for melee
        attacker_killed = False
        if not is_ranged and not target_killed:
            damage_received = self.calculate_damage(
                defender_counterattack_strength, attacker_strength, rng=rng
            )
            self.health -= damage_received
            attacker_killed = self.health <= 0
        else:
            damage_received = 0

        self.movement_points = 0
        self.fortification = 0
        self.has_acted = True

        return damage_dealt, damage_received, target_killed, attacker_killed

    def take_damage(self, damage):
        self.health -= damage


# --- Unit subclasses ---


class WarriorUnit(Unit):
    """Basic melee combat unit."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Warrior")


class RangedUnit(Unit):
    """A unit that attacks at range instead of meleeing.

    The one implementation of "shoot if in range and in sight" — the Archer,
    the Slinger (#67) and the Catapult all resolve their attack through this
    method, so a change to ranged attack resolution cannot land on one of
    them and miss the others.

    Range and line of sight are read per unit type, so a range-1 shooter (the
    Slinger) and a range-2 one (Archer, Catapult) share the same code path.
    """

    def attack(self, target, game_env):
        distance = game_env.map.distance_function(self.coordinates, target.coordinates)
        if distance > self.get_range():
            return 0, 0, False, False

        has_los = game_env.check_line_of_sight(self.coordinates, target.coordinates)
        if not has_los and distance > 1:
            return 0, 0, False, False

        return super().attack(target, game_env, is_ranged=True)


class SlingerUnit(RangedUnit):
    """Ancient-era ranged starter (issue #67).

    Civ 6's Slinger: strength 5, ranged 15, range 1, movement 2, 35
    production — weaker and shorter-ranged than the Archer it upgrades into,
    but the cheapest way to put ranged damage on the board.
    """

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Slinger")


class ArcherUnit(RangedUnit):
    """Basic ranged combat unit."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Archer")


class SwordsmanUnit(Unit):
    """Advanced melee combat unit."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Swordsman")


class SpearmanUnit(Unit):
    """Anti-cavalry unit."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Spearman")


class HorsemanUnit(Unit):
    """Fast cavalry unit."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Horseman")


class CatapultUnit(RangedUnit):
    """Siege unit effective against cities."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Catapult")


# --- Medieval and Renaissance units, and the Trader (#116 P3) ---
# Each is its table in config.toml plus this subclass; the behaviour that
# distinguishes a class (class bonuses, the siege rules, civilian capture)
# lives in the class registry, not here.


class ManAtArmsUnit(Unit):
    """Medieval melee unit (Civ 6: Apprenticeship); upgrades from the Swordsman."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Man-At-Arms")


class PikemanUnit(Unit):
    """Medieval anti-cavalry unit (Civ 6: Military Tactics)."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Pikeman")


class CrossbowmanUnit(RangedUnit):
    """Medieval ranged unit (Civ 6: Machinery): strength 40, range 2."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Crossbowman")


class KnightUnit(Unit):
    """Medieval heavy cavalry (Civ 6: Stirrups): strength 50, movement 4."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Knight")


class TrebuchetUnit(RangedUnit):
    """Medieval siege unit, the Catapult's successor: the same siege-class
    rules (full-strength bombard against cities, fires only with movement
    left), by class and not by name."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Trebuchet")


class MusketmanUnit(Unit):
    """Renaissance melee unit (Civ 6: Gunpowder); the top of the Warrior line."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Musketman")


class SiegeSupportUnit(Unit):
    """A support unit that occupies UNIT_SLOT 2 and fights with nobody.

    Civ 6's Battering Ram and Siege Tower change how an ADJACENT friendly
    melee unit's attack resolves against a city's walls; they have no attack of
    their own and combat strength 0. Issue #66 gives them their stats; the
    adjacency mechanic is deliberately still missing, because a Battering Ram
    is meaningless until walls mean something (#7 makes walls buildable, but a
    wall model with per-class damage is a separate rung). They are in
    DEFERRED_BUILD_UNITS until that lands.

    This class exists so the mechanic has one place to arrive and so
    `_create_unit` does not silently fall back to the bare `Unit`.
    """


class BatteringRamUnit(SiegeSupportUnit):
    """Ancient-era siege support (Civ 6: Masonry). Full damage to Ancient Walls
    for adjacent attacking melee units — mechanic not implemented."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "BatteringRam")


class SiegeTowerUnit(SiegeSupportUnit):
    """Classical-era siege support (Civ 6: Construction). Adjacent melee units
    ignore walls and hit the city directly — mechanic not implemented."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "SiegeTower")


class SettlerUnit(Unit):
    """Unit for founding new cities."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Settler")

    def found_city(self, game_env, name="New City"):
        """Found a new city at the unit's current location."""
        if not game_env.can_found_city_at(self.coordinates, self.player):
            return None

        city = game_env.create_city(self.player, self.coordinates, name)
        # Consumed: off its tile as well as out of its player's list (#113).
        game_env.delete_unit(self)

        return city


class TraderUnit(Unit):
    """Civilian that makes a trade route (#116 P5): standing on an own city
    centre it is consumed by `GameEnvironment.establish_trade_route` and
    reappears there when the route ends (game/trade.py). A civilian by
    class, so it is captured, not killed."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Trader")


class WorkerUnit(Unit):
    """Unit for tile improvements. Idle, it is run by the engine default
    `defaults.default_workers` (#116 P8); an agent action would replace that
    call (#99).

    Build charges (#127, Civ 6 Builder): a Worker starts with its type's
    `build_charges` column plus the `build_charges_trained` effects in force
    for its owner when it is made (`trained_charges`, fixed: Serfdom); the
    `build_charges` effects in force NOW add to every Worker of the owner,
    existing and future (Pyramids, lost with the wonder). Every build spends
    one (`charges_used`); a Worker with none left is removed."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Worker")
        self.trained_charges = (_BUILD_CHARGES.get(self.unit_type, 0)
                                + amount_sum(player, KIND_BUILD_CHARGES_TRAINED))
        self.charges_used = 0

    def charges_left(self):
        """Builds this Worker has left: its trained charges, plus the live
        `build_charges` effects of its owner, minus the builds made."""
        return (self.trained_charges + amount_sum(self.player, KIND_BUILD_CHARGES)
                - self.charges_used)

    def build_improvement(self, improvement_type, game_env):
        """Build an improvement on the current tile, if the owner may: a tile
        of one of its cities, the improvement's tech known, and the tile
        predicate (`GameEnvironment.can_player_build_improvement_at`, #116 P2).
        The build spends the Worker's movement, marks it acted and counts in
        `episode_stats["improvements_built"]` (#116 P8). It spends one
        charge, and the Worker is removed once it has none left (#127); a
        Worker without a charge builds nothing."""
        if self.charges_left() <= 0 or not game_env.can_player_build_improvement_at(
            self.player, self.coordinates, improvement_type
        ):
            return False

        game_env.build_improvement(self.coordinates, improvement_type)
        self.movement_points = 0
        self.has_acted = True
        self.charges_used += 1
        game_env.episode_stats[self.player.player_index]["improvements_built"] += 1
        if self.charges_left() <= 0:
            game_env.delete_unit(self)
        return True
