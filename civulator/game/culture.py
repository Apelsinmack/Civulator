"""A city's culture (issue #87, spec docs/borders_culture_design.md s1).

Since #116 P1 an alias of the one yield computation, `city_yield(city,
"culture")` (game/yields.py): kept so the name every culture reader uses
(the yield phase in `City.process_turn`, border growth, tests) stays put.
All values are integer tenths of a culture point.
"""

from .yields import city_yield


def culture(city):
    """Culture a city produces per turn, in integer tenths:
    `city_yield(city, "culture")` -- `[culture] base + per_pop * population`
    plus every declared culture source (building and district columns, the
    adjacency of complete districts yielding culture)."""
    return city_yield(city, "culture")
