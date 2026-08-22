"""E2E repro for issue #29: fortify must be reachable via the slot-aware select.

The trainer issues actions as ((row, col, slot), (row, col)). The fortify
branch compared the 3-tuple select to the 2-tuple order — never equal — so
the DQN agent could never fortify: every attempt fell through to a
move-to-own-tile, which fails and returns invalid_action.
"""

from civulator.game.environment import REWARDS
from civulator.game.unit import WarriorUnit

from test_combat_range import make_flat_env, place


def test_fortify_via_slot_aware_select():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (2, 2))

    _, reward, _ = env.step([(2, 2, 0), (2, 2)])

    assert reward == REWARDS["fortify"], "slot-aware same-tile select must fortify"
    assert warrior.fortification == 1
    assert warrior.movement_points == 0


def test_fortify_via_legacy_select_still_works():
    env = make_flat_env()
    warrior = place(env, WarriorUnit, 0, (3, 3))

    _, reward, _ = env.step([(3, 3), (3, 3)])

    assert reward == REWARDS["fortify"]
    assert warrior.fortification == 1
