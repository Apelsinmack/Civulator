"""Religion in the engine (v0.9.0 Q7, docs/districts_religion_design.md §7, §9).

Q7 holds the pantheon predicate; founding, beliefs, pressure, conversion,
upkeep and inquisition (their predicates and pure helpers) arrive in Q8/Q9.
The registry -- `[religion]`, `[pantheons.*]`, `[beliefs.*]` -- is read only
through `civulator/religion_model.py`.

Pure: reads the player and the registry, mutates nothing. The one writer of
`Player.pantheon` is `GameEnvironment.choose_pantheon`. No RNG anywhere.
"""

from ..religion_model import PANTHEON_COST, PANTHEONS


def pantheon_cost_tenths():
    """The faith a pantheon costs, in the faith pool's unit (int tenths):
    `[religion] pantheon_cost` whole points x 10."""
    return 10 * PANTHEON_COST


def can_choose_pantheon(player, name, env=None):
    """Whether `player` may choose pantheon `name` now (design §9, the mask's
    predicate; every refusal reason is here): the player has no pantheon yet
    (a pantheon is permanent), `name` is a `[pantheons.*]` table, and the
    faith pool holds `[religion] pantheon_cost`. `env` is accepted for the
    predicate family's uniform signature; Q7's clauses do not read it."""
    if player is None or getattr(player, "is_dead", False):
        return False
    if player.pantheon is not None:
        return False
    if name not in PANTHEONS:
        return False
    return player.faith >= pantheon_cost_tenths()
