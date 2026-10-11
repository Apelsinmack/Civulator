"""A Settler is consumed when it founds a city (#113)."""

from civulator.game.unit import SettlerUnit, WarriorUnit

from test_combat_range import make_flat_env, place


def _units_on_tiles(env):
    return [u for row in env.map.tiles for tile in row for u in tile.units]


def test_founding_settler_leaves_no_unit_behind_on_the_map():
    """Property: after a Settler founds a city through `step`, every unit on
    a map tile is a live unit of its player, and the city tile's civilian slot
    is free again. Breaks if `SettlerUnit.found_city` removes the Settler from
    its player but not from its tile (the #113 phantom)."""
    env = make_flat_env()
    settler = place(env, SettlerUnit, 0, (4, 4))
    escort = place(env, WarriorUnit, 0, (4, 4))
    env.current_player, env.current_player_index = env.players[0], 0

    env.step([(4, 4, settler.slot), (4, 4)])

    assert env.map.get_tile((4, 4)).city is not None
    for unit in _units_on_tiles(env):
        assert unit in unit.player.units, f"{unit.unit_type} on a tile but not alive"
    assert settler not in env.map.get_tile((4, 4)).units
    assert escort in env.map.get_tile((4, 4)).units
    assert not env.is_slot_occupied((4, 4), settler.slot)
