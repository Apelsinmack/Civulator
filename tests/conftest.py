"""Make the civulator package importable when running `pytest tests -q` from the repo root.

Also the shared research helpers (#116 P2, progression design "v2 fixes",
pre-existing tests table): tests whose subject is not availability grant the
whole tree with `grant_all`, so a gate never decides a test about something
else. Import them as `from conftest import grant_all` (the tests directory
is on sys.path, as for `from test_combat_range import ...`).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def grant_all(player):
    """Every tech known (#116 P2; P4 extends it with every civic). Appended
    in config order, after whatever the player already knows."""
    from civulator.research_model import TECH_ORDER

    player.techs.extend(t for t in TECH_ORDER if t not in player.techs)
    return player


def grant(player, *techs):
    """Exactly these techs added (prerequisites NOT implied): for tests of
    one gate."""
    player.techs.extend(t for t in techs if t not in player.techs)
    return player


def stand(env, unit_type, player_index, coordinates):
    """A real unit of `unit_type` standing on the board for player
    `player_index` (#116 P3): built through the engine's one factory
    (`_create_unit`), so the class, slot and subclass are the real ones, and
    registered in its player's list and on its tile like a produced unit."""
    from civulator.game.city import _create_unit

    unit = _create_unit(unit_type, env.players[player_index], coordinates)
    env.players[player_index].units.append(unit)
    env.add_unit_to_tile(unit, coordinates)
    return unit
