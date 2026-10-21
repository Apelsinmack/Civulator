"""Engine defaults where no agent chooses yet (issue #116, docs/progression_design.md
§13 and "v2 fixes").

Each default is one deterministic function (no RNG) that `GameEnvironment`
calls in place of an agent action that does not exist yet (#99); an agent
action replaces exactly one call. P2 ships the research default; P4 adds the
civic, government and policy defaults, P5 the Trader's, P8 the Worker's.
"""

from ..research_model import TECH_INDEX, TECHS, available, scaled_tech_cost


def default_research(player):
    """The tech `player` researches when nothing is chosen: the cheapest
    available one by (scaled cost, config index), or None once no tech is
    available (the tree is exhausted). Available = not known, every
    prerequisite known."""
    candidates = available(TECHS, player.techs)
    if not candidates:
        return None
    return min(candidates, key=lambda name: (scaled_tech_cost(name), TECH_INDEX[name]))
