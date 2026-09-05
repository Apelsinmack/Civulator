"""E2E repro for issue #63 + the Civ 6 alignment of #60.

The bug an end user sees: a Horseman charges a Spearman and the Spearman —
the dedicated anti-cavalry unit — takes roughly half again as much damage as
it should, because `get_combat_strength` gated every class advantage behind
`is_attacking`. A unit standing still and being attacked got no bonus at all,
so the anti-cavalry role only existed when the Spearman was the aggressor.

Civ 6 applies class bonuses in both directions, and its Ancient-era numbers
make each counter pair a dead-even fight decided by production cost:
Spearman (25 +10) vs Horseman (35) is 35 vs 35, and the Spearman wins on
price (65 vs 80). This file pins both halves — the bidirectional bonus and
the constants that make the counters land where they are supposed to.

Damage tolerances are wide enough to cover the full 0.8-1.2 damage roll and
still separate the two hypotheses: at mean roll the buggy exchange is 46.6
(band 37.3-55.9) and the correct one is 30.0 (band 24.0-36.0).
"""

from civulator.game.unit import (
    ArcherUnit,
    CatapultUnit,
    HorsemanUnit,
    SpearmanUnit,
    Unit,
    WarriorUnit,
)

from test_combat_range import make_flat_env, place


# --- The bug: class bonuses must apply when defending too (#63) ---


def test_defending_spearman_survives_a_cavalry_charge():
    """E2E: the damage a charging Horseman deals to a Spearman.

    Buggy: defender strength 25 (no +10) -> ~46.6 at mean roll.
    Correct: defender strength 35 -> ~30.0 at mean roll.
    """
    env = make_flat_env()
    horseman = place(env, HorsemanUnit, 0, (3, 3))
    spearman = place(env, SpearmanUnit, 1, (3, 4))

    damage_dealt, _, _, _ = horseman.attack(spearman, env)

    assert damage_dealt < 37.0, (
        f"charging Horseman dealt {damage_dealt:.1f} to a Spearman; the "
        "anti-cavalry bonus is not being applied on defence (#63)"
    )
    assert 24.0 <= damage_dealt <= 36.0


def test_anti_cavalry_bonus_is_in_the_defending_strength():
    """The same fact one level down, where the modifier is computed."""
    env = make_flat_env()
    horseman = place(env, HorsemanUnit, 0, (3, 3))
    spearman = place(env, SpearmanUnit, 1, (3, 4))

    defending = spearman.get_combat_strength(is_attacking=False, target=horseman)
    attacking = spearman.get_combat_strength(is_attacking=True, target=horseman)

    assert defending == attacking == 35, (
        "Spearman should reach 25 + 10 anti-cavalry in both roles, "
        f"got {defending} defending / {attacking} attacking"
    )


def test_defending_warrior_gets_its_bonus_against_a_spearman():
    """The other half of the web: melee units get +5 vs anti-cavalry, both ways."""
    env = make_flat_env()
    spearman = place(env, SpearmanUnit, 0, (3, 3))
    warrior = place(env, WarriorUnit, 1, (3, 4))

    assert warrior.get_combat_strength(is_attacking=False, target=spearman) == 25
    assert warrior.get_combat_strength(is_attacking=True, target=spearman) == 25


def test_bonus_still_requires_the_matching_target_class():
    """A bidirectional bonus must not become an unconditional one."""
    env = make_flat_env()
    warrior_a = place(env, WarriorUnit, 0, (3, 3))
    warrior_b = place(env, WarriorUnit, 1, (3, 4))

    assert warrior_a.get_combat_strength(is_attacking=False, target=warrior_b) == 20
    assert warrior_a.get_combat_strength(is_attacking=True, target=warrior_b) == 20
    assert warrior_a.get_combat_strength(is_attacking=False, target=None) == 20


# --- The counter web the bonuses are supposed to produce (#60) ---


def test_spearman_and_horseman_fight_even():
    """35 vs 35 in both directions: the counter is paid for in production cost,
    not in an exchange advantage. Charging cavalry no longer wins on strength.
    """
    env = make_flat_env()
    horseman = place(env, HorsemanUnit, 0, (3, 3))
    spearman = place(env, SpearmanUnit, 1, (3, 4))

    dealt, taken, _, _ = horseman.attack(spearman, env)

    assert 24.0 <= dealt <= 36.0
    assert 24.0 <= taken <= 36.0


def test_warrior_and_spearman_fight_even():
    """20 + 5 vs 25: also even, and the Warrior costs 40 against 65."""
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (3, 3))
    spearman = place(env, SpearmanUnit, 1, (3, 4))

    dealt, taken, _, _ = warrior.attack(spearman, env)

    assert 24.0 <= dealt <= 36.0
    assert 24.0 <= taken <= 36.0


# --- The constants themselves (#60): Civ 6 Ancient/Classical era ---


def test_unit_tables_match_the_civ6_reference():
    """Pins the four numbers changed in v0.6.2 and the ones deliberately left.

    Archer stays at 60 production rather than Civ 6's 50: the sources conflict
    (50 in the Analyst table, 60 on the wiki) and Erik chose to leave it until
    there is a signal worth rebalancing on.
    """
    strength = Unit.BASE_COMBAT_STRENGTH
    ranged = Unit.BASE_RANGED_STRENGTH
    cost = Unit.PRODUCTION_COST

    # Changed in v0.6.2
    assert cost["Spearman"] == 65
    assert strength["Horseman"] == 35
    assert strength["Catapult"] == 23
    assert ranged["Catapult"] == 35

    # Deliberately unchanged
    assert (strength["Warrior"], cost["Warrior"]) == (20, 40)
    assert (strength["Spearman"],) == (25,)
    assert (strength["Archer"], ranged["Archer"], cost["Archer"]) == (15, 25, 60)
    assert (strength["Swordsman"], cost["Swordsman"]) == (35, 90)
    assert cost["Horseman"] == 80
    assert cost["Catapult"] == 120
    assert Unit.MAX_MOVEMENT["Horseman"] == 4
    assert Unit.RANGE_VALUES["Archer"] == Unit.RANGE_VALUES["Catapult"] == 2


def test_warrior_is_cheaper_than_spearman_for_the_same_effective_strength():
    """The shape of the Civ 6 web: counters win on production, not on strength.

    Asserted as a relationship rather than as numbers, so it keeps holding
    through a future rebalance as long as the design intent is unchanged.
    """
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (3, 3))
    spearman = place(env, SpearmanUnit, 1, (3, 4))

    assert warrior.get_combat_strength(True, spearman) == spearman.get_combat_strength(
        False, warrior
    ), "Warrior + its anti-anti-cavalry bonus should match the Spearman exactly"
    assert Unit.PRODUCTION_COST["Warrior"] < Unit.PRODUCTION_COST["Spearman"]
    assert Unit.PRODUCTION_COST["Spearman"] < Unit.PRODUCTION_COST["Horseman"]


def test_catapult_now_bombards_cities_from_a_strength_deficit():
    """Pins a known, accepted consequence of this patch, so #66 has to change
    it deliberately rather than by accident.

    Copying Civ 6's ranged strength (45 -> 35) while keeping our ad-hoc flat
    `-17` vs cities drops the Catapult to 18 against a city defence of 20: it
    now attacks cities from a *deficit*, where before it had 28 against 20.
    Razing a 200 HP city goes from ~4.8 shots to ~7.2.

    Civ 6 has no such flat penalty — it models walls, and exempts the siege
    class from the reduction other units suffer. The `-17` was evidently tuned
    against our old 45. Replacing it with a real wall model is #66; until then
    the Catapult is still the better of the two siege options, just a weak one.
    """
    env = make_flat_env()
    catapult = place(env, CatapultUnit, 0, (3, 3))
    archer = place(env, ArcherUnit, 0, (5, 5))

    city_defence = 20  # City.defense_strength, city.py:37
    cat = catapult.get_ranged_strength(is_city=True)
    arc = archer.get_ranged_strength(is_city=True)

    assert cat == 35 - 17 == 18
    assert arc == 25 - 17 == 8
    assert cat > arc, "the Catapult must remain the better city attacker"
    assert cat < city_defence, (
        "expected the known #66 deficit; if this now passes, the -17 penalty "
        "or the city defence strength changed and this test should be updated "
        "together with that decision"
    )
