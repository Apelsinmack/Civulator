"""Issue #67: a statted unit that no agent can build, and a missing Slinger.

Two rule changes are pinned here.

1. **The Swordsman is buildable.** It had a full stat line — 35 strength, 90
   production, the +5 vs Spearman class bonus — and was absent from
   `BUILD_OPTIONS`, so across an entire training epoch no agent could produce
   the strongest melee unit in the game. It appears in no build-mix statistic
   because it could not be built.

2. **The Slinger exists.** Civ 6's Ancient-era ranged starter, which the game
   was missing entirely.

The test that would have caught #67 in the first place is
`test_every_statted_unit_is_buildable_or_deliberately_deferred`: the partition
between "buildable" and "deliberately not buildable" must be total, so
statted-but-unreachable can never again be an accident that looks like a
decision.

No availability gate is asserted beyond cost and the Settler's population
requirement — research does not exist yet (#41/#76), so an ungated unit is a
genuinely state-changing action and CLAUDE.md's mask invariant holds.
"""

import pytest
import torch

from civulator.agents.build_agent import (
    BUILD_OPTIONS,
    NUM_BUILD_CHANNELS,
    NUM_BUILD_OPTIONS,
    BuildAgent,
    encode_build_state,
    get_valid_build_mask,
    options_for_width,
)
from civulator.agents.state_encoders import EnhancedStateEncoder
from civulator.game.city import City, _create_unit
from civulator.game.unit import (
    DEFERRED_BUILD_UNITS,
    MOVEMENT_DOMAIN,
    UNIT_SLOT,
    SlingerUnit,
    SwordsmanUnit,
    Unit,
    WarriorUnit,
)

from test_combat_range import make_flat_env, place


# --- 1. Both units are reachable through the build system -------------------


@pytest.mark.parametrize("unit_type", ["Slinger", "Swordsman"])
def test_unit_is_a_build_option(unit_type):
    assert unit_type in BUILD_OPTIONS


@pytest.mark.parametrize("unit_type,expected_cls", [
    ("Slinger", SlingerUnit),
    ("Swordsman", SwordsmanUnit),
])
def test_city_can_actually_produce_the_unit(unit_type, expected_cls):
    """E2E: the whole path an agent walks — pick the option, pay for it, and
    a unit of the right class is standing on the map afterwards."""
    env = make_flat_env()
    city = env.create_city(env.players[0], (3, 3), "Test City")

    city.produce_unit(unit_type)
    city.production = city.get_unit_cost(unit_type)
    city.process_turn(env)

    produced = [u for u in env.players[0].units if u.unit_type == unit_type]
    assert produced, f"city never produced a {unit_type}"
    assert isinstance(produced[0], expected_cls)


@pytest.mark.parametrize("unit_type", ["Slinger", "Swordsman"])
def test_the_build_mask_offers_the_unit(unit_type):
    """The mask must offer it — an option no mask ever exposes is the same as
    no option at all, which is what #67 was."""
    env = make_flat_env()
    city = City(env.players[0], (3, 3), "Test City")

    mask = get_valid_build_mask(city)
    assert mask[BUILD_OPTIONS.index(unit_type)] == 1.0


@pytest.mark.parametrize("unit_type", ["Slinger", "Swordsman"])
def test_create_unit_factory_knows_the_type(unit_type):
    """_create_unit must not silently fall back to the plain Unit base — that
    would strip a ranged unit of its ranged attack."""
    unit = _create_unit(unit_type, None, (0, 0))
    assert type(unit) is not Unit
    assert unit.unit_type == unit_type


# --- 2. The six unit tables (CLAUDE.md's unit-system row) -------------------


@pytest.mark.parametrize("unit_type", ["Slinger", "Swordsman"])
def test_all_six_unit_tables_carry_the_type(unit_type):
    """CLAUDE.md: adding a unit type touches the 6 tables incl. MOVEMENT_DOMAIN
    and UNIT_SLOT. Miss one and the unit is subtly broken rather than absent."""
    assert unit_type in Unit.MAX_MOVEMENT
    assert unit_type in Unit.BASE_COMBAT_STRENGTH
    assert unit_type in Unit.BASE_RANGED_STRENGTH
    assert unit_type in Unit.RANGE_VALUES
    assert unit_type in Unit.PRODUCTION_COST
    assert unit_type in MOVEMENT_DOMAIN
    assert unit_type in UNIT_SLOT


def test_slinger_stats_match_the_civ6_ancient_era_reference():
    """Civ 6 Slinger: 5 melee / 15 ranged / range 1 / movement 2 / 35 production.

    Production is on the wiki scale, the one this repo already uses (Warrior
    40, Archer 60, Catapult 120). The Civ 6 Analyst table quotes a different,
    smaller scale (Slinger 25, Archer 33) and is not comparable — see the
    CHANGELOG entry.
    """
    assert Unit.BASE_COMBAT_STRENGTH["Slinger"] == 5
    assert Unit.BASE_RANGED_STRENGTH["Slinger"] == 15
    assert Unit.RANGE_VALUES["Slinger"] == 1
    assert Unit.MAX_MOVEMENT["Slinger"] == 2
    assert Unit.PRODUCTION_COST["Slinger"] == 35


def test_slinger_is_the_cheap_weak_predecessor_of_the_archer():
    """The relationship the unit exists for, asserted as a relationship so it
    survives a rebalance: cheaper, weaker, shorter-ranged than the Archer."""
    assert Unit.PRODUCTION_COST["Slinger"] < Unit.PRODUCTION_COST["Archer"]
    assert Unit.BASE_RANGED_STRENGTH["Slinger"] < Unit.BASE_RANGED_STRENGTH["Archer"]
    assert Unit.RANGE_VALUES["Slinger"] < Unit.RANGE_VALUES["Archer"]


def test_slinger_occupies_the_military_slot():
    assert UNIT_SLOT["Slinger"] == UNIT_SLOT["Archer"] == 0


def test_slinger_is_in_the_encoder_class_channels():
    """A buildable combat unit the encoder cannot see is invisible to the
    policy that has to decide whether to build it."""
    assert EnhancedStateEncoder.CLASS_INDEX["Slinger"] >= 0
    assert (
        EnhancedStateEncoder.CLASS_INDEX["Slinger"]
        == EnhancedStateEncoder.CLASS_INDEX["Archer"]
    ), "the Slinger shares the Archer's ranged class channel"


# --- 3. The Slinger really is ranged, at range 1 ---------------------------


def test_slinger_shoots_an_adjacent_enemy_without_taking_a_counterattack():
    """Ranged attacks take no counterattack — that, not the distance, is what
    makes the Slinger a ranged unit at range 1."""
    env = make_flat_env()
    slinger = place(env, SlingerUnit, 0, (3, 3))
    target = place(env, WarriorUnit, 1, (3, 4))

    damage_dealt, damage_received, _, _ = slinger.attack(target, env)

    assert damage_dealt > 0
    assert damage_received == 0
    assert slinger.health == 100.0


def test_slinger_cannot_shoot_at_hex_distance_2():
    """Range 1: the Archer's reach is exactly what the Slinger lacks."""
    env = make_flat_env()
    slinger = place(env, SlingerUnit, 0, (3, 3))
    target = place(env, WarriorUnit, 1, (3, 5))
    assert env.map.distance_function(slinger.coordinates, target.coordinates) == 2

    damage_dealt, _, killed, _ = slinger.attack(target, env)

    assert damage_dealt == 0 and not killed
    assert target.health == 100.0


def test_environment_resolves_a_slinger_attack_as_ranged():
    """The engine decides melee-vs-ranged from base ranged strength; the
    Slinger must land on the ranged side of that fork."""
    env = make_flat_env()
    slinger = place(env, SlingerUnit, 0, (3, 3))
    target = place(env, WarriorUnit, 1, (3, 4))

    env.current_player = env.players[0]
    env._execute_attack(slinger, target)

    assert target.health < 100.0
    assert slinger.health == 100.0, "a ranged attacker must take no counterattack"


# --- 4. The invariant that would have caught #67 ---------------------------


def test_every_build_option_is_a_known_unit_or_building():
    for option in BUILD_OPTIONS:
        if option in City.BUILDING_COSTS:
            continue
        assert option in Unit.PRODUCTION_COST, (
            f"{option} is offered as a build option but has no production cost"
        )
        assert option in Unit.MAX_MOVEMENT
        assert option in MOVEMENT_DOMAIN
        assert option in UNIT_SLOT
        assert type(_create_unit(option, None, (0, 0))) is not Unit


def test_every_statted_unit_is_buildable_or_deliberately_deferred():
    """The #67 gate. A unit with a full stat line is either something an agent
    can build, or is named in DEFERRED_BUILD_UNITS with a reason. There is no
    third state — that third state is the bug."""
    for unit_type in Unit.PRODUCTION_COST:
        assert unit_type in BUILD_OPTIONS or unit_type in DEFERRED_BUILD_UNITS, (
            f"{unit_type} has stats but is neither buildable nor listed in "
            "DEFERRED_BUILD_UNITS — say which it is (issue #67)"
        )


def test_deferred_units_are_real_unit_types():
    """The registry must not accumulate names of units that no longer exist."""
    for unit_type in DEFERRED_BUILD_UNITS:
        assert unit_type in Unit.PRODUCTION_COST
        assert unit_type not in BUILD_OPTIONS


def test_every_buildable_unit_has_an_encoder_class_channel():
    civilian = {"Settler", "Worker"}
    for option in BUILD_OPTIONS:
        if option in City.BUILDING_COSTS or option in civilian:
            continue
        assert EnhancedStateEncoder.CLASS_INDEX.get(option, -1) >= 0, (
            f"{option} is buildable but has no encoder class channel"
        )


# --- 5. The build agent's tensors scale with the option list ---------------


def test_build_channels_are_derived_from_the_option_list():
    assert NUM_BUILD_CHANNELS == NUM_BUILD_OPTIONS + 2


def test_encode_build_state_gives_every_option_its_own_channel():
    """Regression guard on the old hardcoded `BUILD_OPTIONS[:5]` slicing: with
    the city's stockpile empty, every option's turns-to-complete channel must
    be populated, and a costlier option must read higher than a cheaper one."""
    env = make_flat_env()
    city = env.create_city(env.players[0], (3, 3), "Test City")
    city.assign_tiles(env)
    city.current_production = None

    encoder = EnhancedStateEncoder(fog_of_war=False)
    combat_state = encoder.encode(env, 0)
    build_state = encode_build_state(combat_state, city, env)

    assert build_state.shape[0] == combat_state.shape[0] + NUM_BUILD_CHANNELS
    d = combat_state.shape[0]
    ci, cj = city.coordinates

    for idx, option in enumerate(BUILD_OPTIONS):
        assert build_state[d + idx, ci, cj] > 0, (
            f"{option} (index {idx}) has an empty turns-to-complete channel"
        )

    slinger_ch = d + BUILD_OPTIONS.index("Slinger")
    swordsman_ch = d + BUILD_OPTIONS.index("Swordsman")
    assert build_state[swordsman_ch, ci, cj] > build_state[slinger_ch, ci, cj], (
        "the 90-production Swordsman must read as slower than the 35-production Slinger"
    )

    assert build_state[d + NUM_BUILD_OPTIONS + 1, ci, cj] == 1.0, "city marker channel"


def test_build_mask_width_matches_the_option_list():
    env = make_flat_env()
    city = City(env.players[0], (3, 3), "Test City")
    mask = get_valid_build_mask(city)
    assert mask.shape == torch.Size([NUM_BUILD_OPTIONS])


# --- 6. Archived weights survive the option list growing -------------------


def test_new_options_are_appended_so_old_indices_keep_their_meaning():
    """The contract that makes a pre-#67 build agent still evaluable: the
    seven options it was trained on are still the first seven, in order."""
    assert BUILD_OPTIONS[:7] == [
        "Warrior", "Spearman", "Archer", "Horseman", "Catapult",
        "Settler", "Granary",
    ]


def test_a_narrower_legacy_agent_loads_and_plays_its_own_option_list():
    """Loading a pre-#67 checkpoint must not fail with a size mismatch, and
    must not be padded with fabricated Q-values for options it never saw —
    scripts/evaluate.py infers the width from the saved fc layer."""
    legacy = BuildAgent(8, 16, 25, num_options=7)

    assert legacy.options == BUILD_OPTIONS[:7]
    assert legacy.network.fc.out_features == 7
    assert legacy.network.conv1.in_channels == 25 + 7 + 2

    env = make_flat_env()
    city = env.create_city(env.players[0], (3, 3), "Test City")
    city.assign_tiles(env)

    encoder = EnhancedStateEncoder(fog_of_war=False)
    combat_state = encoder.encode(env, 0).to(legacy.device)
    action = legacy.select_build(combat_state, city, env, epsilon=0.0)

    assert 0 <= action < 7
    assert BUILD_OPTIONS[action] in BUILD_OPTIONS[:7]


def test_options_for_width_rejects_a_width_wider_than_the_option_list():
    with pytest.raises(ValueError):
        options_for_width(NUM_BUILD_OPTIONS + 1)
    with pytest.raises(ValueError):
        options_for_width(0)
