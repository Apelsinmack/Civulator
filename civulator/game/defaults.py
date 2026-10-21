"""Engine defaults where no agent chooses yet (issue #116, docs/progression_design.md
§13 and "v2 fixes").

Each default is one deterministic function (no RNG) that `GameEnvironment`
calls in place of an agent action that does not exist yet (#99); an agent
action replaces exactly one call. P2 ships the research default; P4 the
civic, government and policy-loadout defaults; P5 adds the Trader's, P8 the
Worker's.

"Newest" (v2 fixes, N2): a card unlocked by a civic later in
`player.civics` (completion order) is newer; among the cards of one civic,
the one earlier in config order is taken first.
"""

from .. import research_model
from ..effects import card_available, policies_in_force, slot_counts
from ..research_model import (
    CIVIC_INDEX,
    CIVICS,
    POLICY_WILDCARD,
    TECH_INDEX,
    TECHS,
    available,
    scaled_civic_cost,
    scaled_tech_cost,
)
from .availability import government_tier


def default_research(player):
    """The tech `player` researches when nothing is chosen: the cheapest
    available one by (scaled cost, config index), or None once no tech is
    available (the tree is exhausted). Available = not known, every
    prerequisite known."""
    candidates = available(TECHS, player.techs)
    if not candidates:
        return None
    return min(candidates, key=lambda name: (scaled_tech_cost(name), TECH_INDEX[name]))


def default_civic(player):
    """The civic `player` develops when nothing is chosen: the cheapest
    available one by (scaled cost, config index), or None once the civics
    tree is exhausted -- the research rule, on the civics tree (design §5.1,
    §13)."""
    candidates = available(CIVICS, player.civics)
    if not candidates:
        return None
    return min(candidates, key=lambda name: (scaled_civic_cost(name), CIVIC_INDEX[name]))


def default_government(player):
    """The government the engine adopts for `player`, or None to keep the
    current one (design §13 as amended by v2): among the governments whose
    civic is known and whose tier is above the current government's (no
    government: below every tier), the highest tier, ties by config order --
    Chiefdom on Code of Laws, the first Tier-1 on Political Philosophy, the
    first Tier-2 on Divine Right."""
    current = government_tier(player)
    candidates = [spec for spec in research_model.GOVERNMENTS.values()
                  if spec.requires_civic in player.civics and spec.tier > current]
    if not candidates:
        return None
    best = max(spec.tier for spec in candidates)
    return next(spec.name for spec in candidates if spec.tier == best)


def _newest_first(player, names):
    """`names` (cards whose civic is known) ordered newest first: the latest
    unlocking civic in `player.civics`, then config order."""
    order = {name: index for index, name in enumerate(research_model.POLICIES)}
    position = {civic: index for index, civic in enumerate(player.civics)}
    return sorted(names, key=lambda name: (
        -position[research_model.POLICIES[name].requires_civic], order[name]))


def _free_slots(card_types, counts):
    """Slot type -> slots left once cards of `card_types` (a legal loadout)
    are seated: typed cards in their own slots first, then in wildcard slots;
    wildcard cards in wildcard slots."""
    free = dict(counts)
    for card_type in card_types:
        if card_type != POLICY_WILDCARD and free[card_type] > 0:
            free[card_type] -= 1
        else:
            free[POLICY_WILDCARD] -= 1
    return free


def default_loadout(player):
    """The loadout the engine slots for `player` (design §5.4, §13): keep the
    legal cards of the current loadout, in their order (an obsolete card, a
    repeat, and -- when the slots shrank -- the newest-slotted cards that no
    longer fit fall out: `effects.policies_in_force`); then fill each empty
    typed slot with the newest unlocked, unslotted card of that type; then
    each empty wildcard slot with the newest unlocked, unslotted card of any
    type. Returns the new list of card names; mutates nothing."""
    counts = slot_counts(player)
    kept = policies_in_force(player)
    free = _free_slots([research_model.POLICIES[n].type for n in kept], counts)
    candidates = _newest_first(player, [
        name for name in research_model.POLICIES
        if name not in kept and card_available(player, name)
    ])
    for slot_type in research_model.POLICY_TYPES:
        if slot_type == POLICY_WILDCARD:
            continue
        for name in candidates:
            if free[slot_type] <= 0:
                break
            if name not in kept and research_model.POLICIES[name].type == slot_type:
                kept.append(name)
                free[slot_type] -= 1
    for name in candidates:
        if free[POLICY_WILDCARD] <= 0:
            break
        if name not in kept:
            kept.append(name)
            free[POLICY_WILDCARD] -= 1
    return kept
