"""The one culture computation (issue #87, spec docs/borders_culture_design.md s1).

Pure engine code: reads only config-derived tables from civulator/unit_model.py.
All values are integer tenths of a culture point.
"""

from ..unit_model import BUILDING_CULTURE, CULTURE_BASE, CULTURE_PER_POP


def culture(city):
    """Culture a city produces per turn, in integer tenths.

    base + per_pop * population + sum of each source's `culture`. Sources are
    anything the city has that declares a culture value (today its buildings).
    """
    return (
        CULTURE_BASE
        + CULTURE_PER_POP * city.population
        + sum(BUILDING_CULTURE.get(b, 0) for b in city.buildings)
    )
