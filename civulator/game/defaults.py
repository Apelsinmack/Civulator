"""Engine defaults where no agent chooses yet (issue #116, docs/progression_design.md
§13 and "v2 fixes").

Each default is one deterministic function (no RNG) that `GameEnvironment`
calls in place of an agent action that does not exist yet (#99); an agent
action replaces exactly one call. P2 ships the research default; P4 the
civic, government and policy-loadout defaults; P5 the Trader's
(`default_trade`, which acts through the same public paths an agent would:
`GameEnvironment.establish_trade_route` and `Unit.move`); P8 the Worker's
(`default_workers`: `WorkerUnit.build_improvement` and `Unit.move`). The two
unit defaults that walk share one step rule, `step_toward`.

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
from .improvements import best_improvement, worker_targets
from .trade import (
    TRADER_UNIT,
    eligible_destinations,
    origin_city,
    pair_yields,
    route_capacity,
)
from .unit import WorkerUnit


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


# --- The Trader (#116 P5, design §7.4, §13 and "v2 fixes") ---------------------


def best_destination(trader, env):
    """The city the engine sends `trader` to from the own city centre it
    stands on: among `trade.eligible_destinations`, the one whose route would
    yield the origin the most, every yield counted equally (food,
    production, gold, science, culture, faith; summed in tenths, the order
    whole points give), ties to the lower city id. None when the Trader is
    not on an own city centre or nothing is eligible."""
    origin = origin_city(trader, env)
    if origin is None:
        return None
    best, best_key = None, None
    for destination in eligible_destinations(trader, env):
        total = sum(pair_yields(trader.player, origin, destination).values())
        key = (-total, destination.city_id)
        if best_key is None or key < best_key:
            best, best_key = destination, key
    return best


def step_toward(unit, target, env):
    """The one step the engine takes `unit` toward `target` (a tile): the
    adjacent tile `Unit.move` would accept -- enterable, no unit of another
    player, no own unit in the unit's slot, no enemy city barring it,
    `Unit.step_cost` payable -- that is strictly nearer the target by
    `distance_function`, the nearest first, ties by (row, col). Never
    `path_finder`. None when no such tile exists (the unit waits). The step
    rule of every default that walks a unit (`trader_step`,
    `default_workers`); the caller moves the unit through `Unit.move`."""
    here = tuple(unit.coordinates)
    current = env.distance_function(here, target)
    best, best_key = None, None
    for pos in env.map.get_adjacent_coords(here):
        pos = tuple(pos)
        tile = env.map.get_tile(pos)
        if tile is None or not unit.can_enter(tile):
            continue
        units = env.get_units_at(pos)
        if any(u.player is not unit.player for u in units):
            continue
        if any(u.slot == unit.slot for u in units):
            continue
        if unit.enemy_city_blocks(pos, env):
            continue
        if unit.step_cost(here, pos, env) > unit.movement_points:
            continue
        distance = env.distance_function(pos, target)
        if distance >= current:
            continue
        key = (distance, pos)
        if best_key is None or key < best_key:
            best, best_key = pos, key
    return best


def trader_step(trader, env):
    """The one step the engine takes `trader` (not on an own city centre)
    toward home: the target is the own city centre nearest it by
    `distance_function` (ties by the centre's (row, col)), the step is
    `step_toward` it. None when the Trader has no city or no step exists (it
    waits)."""
    player = trader.player
    if not player.cities:
        return None
    here = tuple(trader.coordinates)
    target = min((tuple(c.coordinates) for c in player.cities),
                 key=lambda pos: (env.distance_function(here, pos), pos))
    return step_toward(trader, target, env)


def default_trade(player, env):
    """The idle-Trader default, once per own turn in the economy phase after
    route expiry (design §13 as amended by v2). In `player.units` order:
    a Trader standing on an own city centre with all its movement and not
    having acted this turn is sent, while a route slot is free
    (`route_capacity` > routes), to `best_destination` through
    `GameEnvironment.establish_trade_route`; a Trader elsewhere takes
    `trader_step` through `Unit.move`. Returns the number of routes opened."""
    opened = 0
    for trader in [u for u in player.units if u.unit_type == TRADER_UNIT]:
        if origin_city(trader, env) is not None:
            if trader.has_acted or trader.movement_points < trader.get_max_movement():
                continue
            if len(player.routes) >= route_capacity(player):
                continue
            destination = best_destination(trader, env)
            if destination is not None and env.establish_trade_route(trader, destination):
                opened += 1
        else:
            step = trader_step(trader, env)
            if step is not None:
                trader.move(step, env)
    return opened


# --- The Worker (#116 P8, design §13 and "v2 fixes": Worker default) ----------------


def worker_target(worker, env, claimed=frozenset()):
    """The tile `worker` is headed for: the nearest by `distance_function`
    (ties by (row, col)) of `improvements.worker_targets` -- the owner's
    tiles where an improvement may be built, with no foreign unit and no own
    Worker standing -- leaving out the `claimed` tiles (the ones an earlier
    Worker of the same pass chose). None when there is none."""
    here = tuple(worker.coordinates)
    candidates = (pos for pos in worker_targets(worker.player, env) if pos not in claimed)
    return min(candidates, key=lambda pos: (env.distance_function(here, pos), pos),
               default=None)


def default_workers(player, env):
    """The idle-Worker default, once per own turn, the last step of the
    economy phase (after the Trader default; design §13 as amended by v2).
    In `player.units` order, every Worker that is idle -- all its movement
    and not having acted, so a Worker an agent ordered is left alone --
    does exactly one of:

    (a) it stands on a tile where its owner may build an improvement
        (`improvements.best_improvement`: `can_player_build_improvement_at`,
        so ownership, research and the tile predicate; the largest gain,
        ties by config order; none on a tile that holds one already) and
        builds that one through `WorkerUnit.build_improvement`;
    (b) otherwise it takes one step, `step_toward`, through `Unit.move`
        toward the nearest `worker_target`. A tile a Worker chose earlier in
        the same pass is not chosen again, so Workers that start together
        spread over the land instead of queueing for one tile;
    (c) with nothing to build or reach it stays.

    Never `path_finder`, no RNG. Returns the number of improvements built."""
    built = 0
    claimed = set()
    for worker in [u for u in player.units if isinstance(u, WorkerUnit)]:
        if worker.has_acted or worker.movement_points < worker.get_max_movement():
            continue
        name = best_improvement(player, worker.coordinates, env)
        if name is not None:
            built += bool(worker.build_improvement(name, env))
            continue
        target = worker_target(worker, env, claimed)
        if target is None:
            continue
        claimed.add(target)
        step = step_toward(worker, target, env)
        if step is not None:
            worker.move(step, env)
    return built
