"""Unit classes for all game units."""

import math
import random

import numpy as np

from ..config import CFG
from ..terrain_model import can_enter

# Rivers cost this much extra to cross, per edge (design doc D23) — the single
# source, replacing the two hardcoded +1s this file used to carry. A* does not
# see it until patch P6 (E3).
RIVER_CROSSING_COST = CFG.get("terrain", {}).get("river", {}).get("crossing_cost", 1)

NUM_UNIT_SLOTS = 4  # Military, Civilian, Siege Support, Great Person

# Which slot each unit type occupies
# Each slot can hold at most one unit per tile.
# Units in different slots can stack freely on the same tile.
UNIT_SLOT = {
    "Warrior": 0,      # military
    "Archer": 0,
    "Swordsman": 0,
    "Spearman": 0,
    "Horseman": 0,
    "Settler": 1,      # civilian
    "Worker": 1,
    "Catapult": 0,     # military (siege weapon, not siege support)
    "BatteringRam": 2, # siege support (stacks with military)
    "SiegeTower": 2,   # siege support
    # Great people (slot 3) — future
}

# Movement domain per unit type (design doc §3.3) — the sixth unit data table.
# Everything is land in 0.6; naval units and embarkation are the seam this
# leaves open (a new domain value + a capability check inside can_enter).
MOVEMENT_DOMAIN = {
    "Warrior": "land",
    "Archer": "land",
    "Swordsman": "land",
    "Spearman": "land",
    "Horseman": "land",
    "Settler": "land",
    "Worker": "land",
    "Catapult": "land",
    "BatteringRam": "land",
    "SiegeTower": "land",
}


def movement_domain(unit_type):
    """Movement domain of a unit type — for callers placing a unit that doesn't exist yet."""
    return MOVEMENT_DOMAIN.get(unit_type, "land")


class Unit:
    """Base class for all units in the game."""

    # --- Static data tables ---

    MAX_MOVEMENT = {
        "Warrior": 2,
        "Archer": 2,
        "Swordsman": 2,
        "Spearman": 2,
        "Horseman": 4,
        "Settler": 2,
        "Worker": 2,
        "Catapult": 2,
    }

    BASE_COMBAT_STRENGTH = {
        "Warrior": 20,
        "Archer": 15,
        "Swordsman": 35,
        "Spearman": 25,
        "Horseman": 35,
        "Settler": 0,
        "Worker": 0,
        "Catapult": 23,
    }

    BASE_RANGED_STRENGTH = {
        "Archer": 25,
        "Catapult": 35,
        "Warrior": 0,
        "Swordsman": 0,
        "Spearman": 0,
        "Horseman": 0,
        "Settler": 0,
        "Worker": 0,
    }

    RANGE_VALUES = {
        "Archer": 2,
        "Catapult": 2,
        "Warrior": 1,
        "Swordsman": 1,
        "Spearman": 1,
        "Horseman": 1,
        "Settler": 0,
        "Worker": 0,
    }

    PRODUCTION_COST = {
        "Warrior": 40,
        "Archer": 60,
        "Swordsman": 90,
        "Spearman": 65,
        "Horseman": 80,
        "Settler": 120,
        "Worker": 50,
        "Catapult": 120,
    }

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

        +10 HP base, +20 HP if fortified. Capped at 100.
        """
        if self.health >= 100:
            return
        if self.fortification > 0:
            self.health = min(100, self.health + 20)
        else:
            self.health = min(100, self.health + 10)

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

        # Health penalty: -10 * (100 - HP) / 100
        hp_penalty = -10 * (100 - self.health) / 100
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
            fort_bonus = 3 if self.fortification == 1 else 6
            strength += fort_bonus

        # Unit class advantages — applied whether this unit attacks or defends
        # (issue #63). Gating them behind is_attacking meant a Spearman standing
        # still and being charged got no anti-cavalry bonus, which is the one
        # thing the unit exists to do. Civ 6 applies these in both directions.
        if target:
            if self.unit_type == "Spearman" and target.unit_type == "Horseman":
                strength += 10  # Anti-cavalry
            if self.unit_type in ["Warrior", "Swordsman"] and target.unit_type == "Spearman":
                strength += 5  # Melee vs anti-cavalry

        return max(0, strength)

    def get_ranged_strength(self, target=None, is_city=False):
        """Calculate ranged strength including modifiers."""
        if self.get_base_ranged_strength() == 0:
            return 0

        strength = self.get_base_ranged_strength()

        # Health penalty
        hp_penalty = -10 * (100 - self.health) / 100
        strength += hp_penalty

        if is_city:
            strength -= 17  # Penalty against cities

        if target and target.unit_type == "Horseman" and self.unit_type == "Archer":
            strength -= 5  # Archers less effective vs cavalry

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
        """
        Calculate damage using the Civ6 formula.

        Damage(HP) = 30 * e^(0.04 * StrengthDifference) * random(80%, 120%)

        The roll draws from rng (the game's seeded RNG) when given, so combat
        outcomes are reproducible; falls back to the global random module.
        """
        strength_diff = attacker_strength - defender_strength
        base_damage = 30 * math.exp(0.04 * strength_diff)
        random_factor = (rng if rng is not None else random).uniform(0.8, 1.2)
        damage = base_damage * random_factor
        return max(1, min(100, damage))

    def attack(self, target, game_env, is_ranged=False):
        """
        Attack another unit.

        Returns:
            tuple: (damage_dealt, damage_received, target_killed, attacker_killed)
        """
        if self.movement_points < 0.25:
            return 0, 0, False, False

        if is_ranged and self.unit_type == "Catapult" and self.movement_points < 1:
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


class ArcherUnit(Unit):
    """Basic ranged combat unit."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Archer")

    def attack(self, target, game_env):
        """Archers perform ranged attacks."""
        distance = game_env.map.distance_function(self.coordinates, target.coordinates)
        if distance > self.get_range():
            return 0, 0, False, False

        has_los = game_env.check_line_of_sight(self.coordinates, target.coordinates)
        if not has_los and distance > 1:
            return 0, 0, False, False

        return super().attack(target, game_env, is_ranged=True)


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


class CatapultUnit(Unit):
    """Siege unit effective against cities."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Catapult")

    def attack(self, target, game_env):
        """Catapults perform bombard attacks."""
        distance = game_env.map.distance_function(self.coordinates, target.coordinates)
        if distance > self.get_range():
            return 0, 0, False, False

        has_los = game_env.check_line_of_sight(self.coordinates, target.coordinates)
        if not has_los and distance > 1:
            return 0, 0, False, False

        return super().attack(target, game_env, is_ranged=True)


class SettlerUnit(Unit):
    """Unit for founding new cities."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Settler")

    def found_city(self, game_env, name="New City"):
        """Found a new city at the unit's current location."""
        if not game_env.can_found_city_at(self.coordinates):
            return None

        from .city import City

        city = City(self.player, self.coordinates, name)
        self.player.cities.append(city)
        game_env.add_city(city)
        self.player.remove_unit(self)

        return city


class WorkerUnit(Unit):
    """Unit for tile improvements."""

    def __init__(self, player, coordinates):
        super().__init__(player, coordinates, "Worker")

    def build_improvement(self, improvement_type, game_env):
        """Build an improvement on the current tile."""
        if not game_env.can_build_improvement_at(self.coordinates, improvement_type):
            return False

        game_env.build_improvement(self.coordinates, improvement_type)
        self.movement_points = 0
        return True
