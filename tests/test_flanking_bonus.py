"""Issue #59: a strength bonus per friendly unit adjacent to the defender.

The motivation is measured, not aesthetic: the 2026-09-04 cross-model
evaluation found six of eight trained models recording zero kills across 200
games, and the one model that fights losing its exchanges 69:169. Attacking is
close to pure downside. Flanking is a lever inside the combat system that makes
a coordinated two-unit attack better than two separate ones — the behaviour no
agent has yet learned.

**Who gets the bonus.** The unit that is STRIKING, counting its own units
around the unit it strikes. That covers the initial attack and, symmetrically,
the melee counterattack (where the defender is the one striking, counting its
friends around the attacker). It is deliberately NOT applied to a unit's
defensive strength: flanking is about pressure on the target of a blow, and
v0.6.2's lesson (#63) was that a modifier must be applied in every role it
belongs in — not that every modifier belongs in every role.

**Config-gated.** `[combat] flanking_bonus`; 0 disables the rule completely.
"""

import pytest

from civulator import unit_model
from civulator.game import unit as unit_module
from civulator.game.city import City
from civulator.game.unit import (
    HorsemanUnit,
    SettlerUnit,
    SpearmanUnit,
    SwordsmanUnit,
    WarriorUnit,
)

from test_combat_range import make_flat_env, place


class FixedRoll:
    def uniform(self, lo, hi):
        return 1.0


BONUS = unit_model.FLANKING_BONUS


@pytest.fixture
def flanking_on(monkeypatch):
    """Pin the rule on at the configured value, whatever config says."""
    monkeypatch.setattr(unit_module, "FLANKING_BONUS", 2)
    return 2


# --- The rule ---------------------------------------------------------------


def test_configured_bonus_is_the_civ6_value():
    assert unit_model.FLANKING_BONUS == 2, "Civ 6 uses +2 per flanking unit"


def test_one_friendly_unit_beside_the_defender_adds_the_bonus(flanking_on):
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))

    alone = attacker.get_combat_strength(is_attacking=True, target=defender)

    place(env, WarriorUnit, 0, (3, 5))  # adjacent to the defender, not the attacker
    flanked = attacker.get_combat_strength(is_attacking=True, target=defender)

    assert flanked == alone + flanking_on


def test_the_bonus_scales_with_the_number_of_flanking_tiles(flanking_on):
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))
    base = attacker.get_combat_strength(is_attacking=True, target=defender)

    neighbours = env.map.get_adjacent_coords(defender.coordinates)
    free = [pos for pos in neighbours if pos != attacker.coordinates]

    for n, pos in enumerate(free[:3], start=1):
        place(env, WarriorUnit, 0, pos)
        assert attacker.get_combat_strength(is_attacking=True, target=defender) == (
            base + n * flanking_on
        )


def test_the_attacker_does_not_flank_itself(flanking_on):
    """The attacker is adjacent to the defender by definition in a melee
    attack; counting itself would make the bonus unconditional."""
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))

    assert attacker.flanking_count(defender) == 0
    assert attacker.get_combat_strength(is_attacking=True, target=defender) == 20


def test_a_friend_beside_the_attacker_does_not_count(flanking_on):
    """The bonus is about pressure on the DEFENDER, not on standing in a
    crowd. (3,2) neighbours the attacker at (3,3) but not the defender."""
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 5))
    place(env, WarriorUnit, 0, (3, 2))

    assert env.map.distance_function((3, 2), defender.coordinates) > 1
    assert attacker.flanking_count(defender) == 0


def test_enemy_units_beside_the_defender_do_not_flank_it(flanking_on):
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))
    place(env, WarriorUnit, 1, (3, 5))  # the defender's OWN friend

    assert attacker.flanking_count(defender) == 0


def test_civilians_do_not_flank(flanking_on):
    """A Settler being escorted alongside an army is not pressing on anybody:
    combat strength 0, no flank."""
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))
    place(env, SettlerUnit, 0, (3, 5))

    assert attacker.flanking_count(defender) == 0


def test_a_stack_on_one_tile_counts_once(flanking_on):
    """Slots let several units share a tile. One tile is one position pressing
    on the defender, however many units stand on it."""
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))

    place(env, WarriorUnit, 0, (3, 5))   # military slot
    place(env, SettlerUnit, 0, (3, 5))   # civilian slot, same tile

    assert attacker.flanking_count(defender) == 1


def test_flanking_uses_the_canonical_hex_adjacency_including_the_seam(flanking_on):
    """Adjacency comes from Map.get_adjacent_coords (hexmath), so it wraps.
    Hand-rolled neighbour arithmetic is what caused #24."""
    env = make_flat_env()  # 8 rows x 16 cols cylinder
    attacker = place(env, WarriorUnit, 0, (3, 1))
    defender = place(env, WarriorUnit, 1, (3, 0))
    flanker = place(env, WarriorUnit, 0, (3, 15))  # across the seam

    assert env.map.distance_function(flanker.coordinates, defender.coordinates) == 1
    assert attacker.flanking_count(defender) == 1


# --- Who gets it: striker only ---------------------------------------------


def test_flanking_is_not_applied_to_defensive_strength(flanking_on):
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))
    place(env, WarriorUnit, 1, (3, 2))  # a friend of the defender, beside the attacker

    assert defender.get_combat_strength(is_attacking=False, target=attacker) == 20


def test_the_defenders_counterattack_is_flanked_symmetrically(flanking_on):
    """The counterattack is the defender striking back, so it is flanked by
    the defender's own units standing around the attacker."""
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))
    place(env, WarriorUnit, 1, (3, 2))

    assert defender.get_combat_strength(is_attacking=True, target=attacker) == 20 + flanking_on


def test_flanking_stacks_with_a_class_bonus(flanking_on):
    """Modifiers add, Civ 6 style: +5 melee vs anti-cavalry AND +2 flanking."""
    env = make_flat_env()
    swordsman = place(env, SwordsmanUnit, 0, (3, 3))
    spearman = place(env, SpearmanUnit, 1, (3, 4))
    place(env, HorsemanUnit, 0, (3, 5))

    assert swordsman.get_combat_strength(is_attacking=True, target=spearman) == (
        35 + 5 + flanking_on
    )


def test_a_city_can_be_flanked(flanking_on):
    """Cities have coordinates, so units around one flank an attack on it —
    but a city itself never flanks, having no units of its own."""
    env = make_flat_env()
    city = env.create_city(env.players[1], (3, 4), "Test City")

    attacker = place(env, WarriorUnit, 0, (3, 3))
    place(env, WarriorUnit, 0, (3, 5))

    assert attacker.flanking_count(city) == 1
    assert attacker.get_combat_strength(is_attacking=True, target=city) == 20 + flanking_on


# --- The behaviour it is meant to reward ------------------------------------


def test_a_coordinated_two_unit_attack_hits_harder_than_a_lone_one(flanking_on):
    """E2E, the point of the whole rule: identical attacker, identical
    defender, identical damage roll — the only difference is a second friendly
    unit standing beside the target."""
    env = make_flat_env()
    env.rng = FixedRoll()

    lone = place(env, WarriorUnit, 0, (2, 2))
    lone_target = place(env, WarriorUnit, 1, (2, 3))

    pair = place(env, WarriorUnit, 0, (6, 8))
    pair_target = place(env, WarriorUnit, 1, (6, 9))
    place(env, WarriorUnit, 0, (6, 10))

    lone_damage, lone_taken, _, _ = lone.attack(lone_target, env)
    pair_damage, pair_taken, _, _ = pair.attack(pair_target, env)

    assert pair_damage > lone_damage, (
        f"flanked attack dealt {pair_damage:.1f}, lone attack {lone_damage:.1f}"
    )
    assert pair_taken < lone_taken, (
        "the attacker's flanked strength is also what it defends with during "
        "the counterattack, so coordinating cuts the damage taken too"
    )


def test_flanking_does_not_change_an_unsupported_exchange(flanking_on):
    """The rule must not quietly become an unconditional attack bonus."""
    env = make_flat_env()
    env.rng = FixedRoll()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))

    dealt, taken, _, _ = attacker.attack(defender, env)

    assert dealt == pytest.approx(30.0)
    assert taken == pytest.approx(30.0)


# --- The off switch ---------------------------------------------------------


def test_zero_disables_the_rule_entirely(monkeypatch):
    monkeypatch.setattr(unit_module, "FLANKING_BONUS", 0)

    env = make_flat_env()
    env.rng = FixedRoll()
    attacker = place(env, WarriorUnit, 0, (3, 3))
    defender = place(env, WarriorUnit, 1, (3, 4))
    place(env, WarriorUnit, 0, (3, 5))

    assert attacker.get_combat_strength(is_attacking=True, target=defender) == 20
    dealt, _, _, _ = attacker.attack(defender, env)
    assert dealt == pytest.approx(30.0), "with the bonus off, the pre-#59 exchange"


def test_the_bonus_is_a_config_value():
    from civulator.config import CFG

    assert CFG["combat"]["flanking_bonus"] == unit_model.FLANKING_BONUS


# --- Degenerate inputs ------------------------------------------------------


def test_flanking_count_is_zero_without_an_environment():
    """Units are constructed outside a game in tools and tests; the rule must
    not raise there."""
    orphan = WarriorUnit(None, (0, 0))
    assert orphan.flanking_count(None) == 0
    assert orphan.get_combat_strength(is_attacking=True, target=None) == 20


def test_flanking_count_is_zero_for_a_target_without_a_position(flanking_on):
    env = make_flat_env()
    attacker = place(env, WarriorUnit, 0, (3, 3))

    class Positionless:
        coordinates = None

    assert attacker.flanking_count(Positionless()) == 0
