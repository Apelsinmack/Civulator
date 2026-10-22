"""The sea (v0.9.0 Q5, docs/districts_religion_design.md §6.1-§6.5, §6.7,
"v2 fixes" B5): naval techs and civic, the ships and their classes, coast and
ocean passability, building and placing ships, combat across domains, the
Great Lighthouse.

Every test names the property it protects and the change that breaks it
(§11 rows 17-21 and the Q5 brief). Unit types are read from the registries
(`MOVEMENT_DOMAIN`, `COMBAT_CLASS`), never listed, so a further ship joins
these tests by its tables alone.
"""

import numpy as np
import pytest

from civulator import district_model, research_model, unit_model
from civulator.agents.build_agent import BUILD_OPTIONS, get_valid_build_mask
from civulator.agents.networks import _valid_order_mask_np
from civulator.agents.state_encoders import CLASS_CHANNEL, UNIT_CLASS_INDEX
from civulator.effects import RULE_OCEAN_NAVIGATION, effects_of, rule_enabled, target_matches
from civulator.game import map as map_mod
from civulator.game.environment import REWARDS
from civulator.game.loyalty import is_garrisoned
from civulator.game.unit import MOVEMENT_DOMAIN, is_land_military, movement_domain
from civulator.terrain_model import BASE_TABLE, can_enter
from civulator.unit_model import STRENGTH_RANGED, class_bonus_amounts

from conftest import stand
from test_districts import board, make_city, neighbours, own, ring

# The tech whose `enables` effect carries the ocean rule, read from the tree.
OCEAN_TECHS = [name for name in research_model.TECH_ORDER
               if any(e.kind == "enables" and RULE_OCEAN_NAVIGATION in e["rules"]
                      for e in effects_of("tech", name))]
# Config order: `COMBAT_CLASS` is a dict in table order (`UNIT_NAMES` is a
# set, whose order follows the hash seed).
SHIPS = [u for u in unit_model.COMBAT_CLASS if MOVEMENT_DOMAIN[u] == "water"]
LAND_UNITS = [u for u in unit_model.COMBAT_CLASS if MOVEMENT_DOMAIN[u] == "land"]
NAVAL_MELEE = [u for u in SHIPS if unit_model.BASE_RANGED_STRENGTH[u] == 0]
CENTRE = (3, 3)


def set_base(env, pos, base):
    """Fixture only: one tile's base terrain, through the Tile's own writer."""
    env.map.get_tile(pos).set_layers(base, map_ref=env.map)


def sea_board(ocean=False):
    """board() (all Plains, both trees known) with the ocean rule removed
    from both players unless `ocean`."""
    env = board()
    if not ocean:
        for player in env.players:
            for tech in OCEAN_TECHS:
                if tech in player.techs:
                    player.techs.remove(tech)
    return env


def order(env, unit, target):
    """One order through the real dispatcher (`_step_inner`, without the
    reward shaping `step` adds, so a refusal reads exactly
    REWARDS["invalid_action"])."""
    r, c = unit.coordinates
    return env._step_inner([np.array([r, c, unit.slot]), np.array(list(target))])


def galley():
    """A naval melee unit not gated on the ocean rule's tech (the Galley
    today), so a board without ocean navigation can build it."""
    return next(u for u in NAVAL_MELEE
                if unit_model.UNIT_REQUIRES_TECH.get(u) not in OCEAN_TECHS)


def test_the_fixture_has_ships_and_one_ocean_tech():
    """Fixture guard: the registry holds water-domain units of both naval
    classes and exactly one place grants the ocean rule. Breaks if the ships
    or the Cartography rule leave the config."""
    assert SHIPS and NAVAL_MELEE
    assert {unit_model.COMBAT_CLASS[u] for u in SHIPS} == {"naval_melee", "naval_ranged"}
    assert OCEAN_TECHS


# --- Techs, civic, cards (§6.1) -------------------------------------------------------


def test_the_naval_techs_sit_where_the_design_puts_them():
    """§6.1: Sailing is a starting tech; Shipbuilding needs Sailing; Celestial
    Navigation needs Sailing and Astrology; the ocean tech needs Shipbuilding
    and Celestial Navigation; Fishing Boats and the Colossus moved to Sailing
    and Shipbuilding; each ship is gated on a tech of the tree. Breaks if a
    prerequisite or a moved gate points elsewhere."""
    techs = research_model.TECHS
    assert techs["Sailing"].requires == ()
    assert techs["Shipbuilding"].requires == ("Sailing",)
    assert set(techs["Celestial Navigation"].requires) == {"Sailing", "Astrology"}
    assert set(techs[OCEAN_TECHS[0]].requires) == {"Shipbuilding", "Celestial Navigation"}
    from civulator.terrain_model import IMPROVEMENT_REQUIRES_TECH
    assert IMPROVEMENT_REQUIRES_TECH["Fishing Boats"] == "Sailing"
    assert district_model.DISTRICTS["Colossus"].requires_tech == "Shipbuilding"
    for ship in SHIPS:
        assert unit_model.UNIT_REQUIRES_TECH[ship] in techs, ship


def test_maritime_industries_targets_ancient_and_classical_ships_only():
    """§6.1: Naval Tradition (after Defensive Tactics) unlocks Maritime
    Industries, whose production bonus targets the naval classes of the
    Ancient and Classical eras, and Naval Infrastructure, which doubles the
    Harbor's adjacency. Breaks if the target drifts to land units or to a
    later era, or the cards leave the civic."""
    assert research_model.CIVICS["Naval Tradition"].requires == ("Defensive Tactics",)
    cards = {n: s for n, s in research_model.POLICIES.items()
             if s.requires_civic == "Naval Tradition"}
    assert {"Maritime Industries", "Naval Infrastructure"} <= set(cards)
    (bonus,) = effects_of("policy", "Maritime Industries")
    for unit in unit_model.UNIT_NAMES:
        expected = (MOVEMENT_DOMAIN[unit] == "water"
                    and unit_model.UNIT_ERA[unit] in ("Ancient", "Classical"))
        assert target_matches(bonus["target"], "unit", unit) == expected, unit
    (adjacency,) = effects_of("policy", "Naval Infrastructure")
    assert adjacency["district"] == "Harbor" and adjacency["percent"] == 100


# --- Classes and the encoder (§6.2, v2 non-blocking) ----------------------------------


def test_the_naval_classes_ride_the_melee_and_ranged_channels():
    """The two naval classes map onto the existing melee and ranged class
    channels, so no encoder grows a channel (the depth test in
    test_combat_classes pins the depths). Breaks if a naval class gets its
    own index or none."""
    assert CLASS_CHANNEL["naval_melee"] == CLASS_CHANNEL["melee"]
    assert CLASS_CHANNEL["naval_ranged"] == CLASS_CHANNEL["ranged"]
    for ship in SHIPS:
        assert UNIT_CLASS_INDEX[ship] >= 0, ship


def test_every_ship_is_appended_to_the_build_options():
    """§6.2 / #67: every water-domain unit is a build option, after every
    land option that existed before it (append-only). Breaks if a ship is
    deferred silently or inserted before an older option."""
    first_ship = min(BUILD_OPTIONS.index(s) for s in SHIPS)
    assert all(s in BUILD_OPTIONS for s in SHIPS)
    assert all(o in SHIPS for o in BUILD_OPTIONS[first_ship:])


# --- Passability (§6.3, §11 row 17) ---------------------------------------------------


def test_only_the_ocean_is_deep():
    """§6.3: `deep` is declared on Ocean and on no other base, and only a
    water base may carry it. Breaks if the column moves or spreads."""
    deep = {name for name, entry in BASE_TABLE.items() if entry.get("deep", False)}
    assert deep == {"Ocean"}
    assert all(BASE_TABLE[name]["domain"] == "water" for name in deep)


def test_a_galley_keeps_to_coast_and_lake_until_its_owner_knows_ocean_navigation():
    """§11 row 17: a Galley may enter Coast and Lake, never Ocean or land,
    until its owner holds the `ocean_navigation` rule; then Ocean too (land
    never). Read through `Unit.can_enter` and an actual `Unit.move`. Breaks if
    `deep` or the domain switch is bypassed."""
    for ocean in (False, True):
        env = sea_board(ocean=ocean)
        start = (3, 9)
        set_base(env, start, "Coast")
        lake, deep, land = neighbours(env, start)[:3]
        set_base(env, lake, "Lake")
        set_base(env, deep, "Ocean")
        ship = stand(env, galley(), 0, start)
        assert rule_enabled(env.players[0], RULE_OCEAN_NAVIGATION) == ocean
        assert ship.can_enter(env.map.get_tile(lake))
        assert ship.can_enter(env.map.get_tile(deep)) == ocean
        assert not ship.can_enter(env.map.get_tile(land))
        moved, _ = ship.move(deep, env)
        assert moved == ocean
        moved, _ = ship.move(land, env)
        assert not moved


def test_movement_domain_is_player_dependent_and_the_unit_agrees():
    """B5: `movement_domain(unit_type, player)` is the one source: "land" for
    every land unit whoever owns it; "coast" for a water unit whose owner
    lacks the ocean rule, "water" once it has it; `get_movement_domain`
    returns the same for a standing unit. Breaks if the two drift or the
    domain stops reading the owner."""
    env = sea_board()
    without, with_rule = env.players
    with_rule.techs.extend(OCEAN_TECHS)
    for unit_type in unit_model.UNIT_NAMES:
        for player in (without, with_rule):
            unit = stand(env, unit_type, player.player_index, (0, 0))
            domain = movement_domain(unit_type, player)
            assert unit.get_movement_domain() == domain
            if MOVEMENT_DOMAIN[unit_type] == "land":
                assert domain == "land"
            else:
                assert domain == ("water" if player is with_rule else "coast")
            env.delete_unit(unit)


def test_coast_and_water_cost_grids_differ_exactly_on_deep_tiles():
    """§11 row 17: the "coast" grid is the "water" grid with every deep tile
    blocked -- a third grid, player-blind, keyed by the domain string. Breaks
    if `can_enter("coast")` reads anything but `deep`."""
    env = sea_board()
    for col in range(8, 16):
        for row in range(env.n):
            set_base(env, (row, col), "Ocean" if (row + col) % 3 == 0 else "Coast")
    set_base(env, (1, 1), "Lake")
    coast = env.map._build_cost_grid("coast")
    water = env.map._build_cost_grid("water")
    deep = np.array([[env.map.tiles[r, c].deep for c in range(env.m)] for r in range(env.n)])
    assert deep.any() and (~deep & (water < map_mod.BLOCKED_COST)).any()
    assert np.array_equal(coast != water, deep)
    assert (coast[deep] >= map_mod.BLOCKED_COST).all()


@pytest.mark.parametrize("cpp", [True, False])
def test_the_coast_path_goes_round_the_ocean_and_the_water_path_crosses_it(monkeypatch, cpp):
    """`path_finder(..., domain)` works with the "coast" domain unchanged:
    a strait of Ocean between two coasts is crossed by a "water" path and
    walked round by a "coast" path, on the Python A* and (where the module
    is built) the C++ one -- both read the same cost grid. Breaks if the
    grid builder or an A* adapter special-cases the domain."""
    if cpp and not map_mod.HAS_CPP_CORE:
        pytest.skip("civulator_core is not built on this machine")
    monkeypatch.setattr(map_mod, "HAS_CPP_CORE", cpp)
    env = sea_board()
    for row in range(env.n):
        for col in range(6, 13):
            set_base(env, (row, col), "Ocean" if col in (9, 10) and row < 6 else "Coast")
    start, goal = (2, 7), (2, 12)
    by_water = env.path_finder(start, goal, domain="water")
    by_coast = env.path_finder(start, goal, domain="coast")
    assert by_water and by_coast
    assert any(env.map.get_tile(tuple(p)).deep for p in by_water)
    assert not any(env.map.get_tile(tuple(p)).deep for p in by_coast)
    assert len(by_coast) > len(by_water)


# --- Building and placing ships (§6.4, §11 row 18) ------------------------------------


def test_a_city_builds_a_ship_only_with_a_spawn_water_tile():
    """§11 row 18: an inland city cannot start, be offered or buy a ship; a
    water tile beside its centre (a Lake counts) makes it buildable. Breaks
    if `can_produce_unit` ignores the domain, or the mask disagrees."""
    for ship in SHIPS:
        env = sea_board(ocean=True)
        city = make_city(env, CENTRE)
        index = BUILD_OPTIONS.index(ship)
        assert not city.can_produce_unit(ship)
        assert get_valid_build_mask(city)[index] == 0.0
        assert not city.produce_unit(ship)
        set_base(env, neighbours(env, CENTRE)[2], "Lake")
        assert city.can_produce_unit(ship)
        assert get_valid_build_mask(city)[index] == 1.0
        assert city.produce_unit(ship)


def test_a_deep_neighbour_is_no_spawn_tile_without_the_ocean_rule():
    """§6.4: the spawn tile must be one the ship could enter: Ocean beside
    the centre does not admit a Galley before the ocean rule. Breaks if
    `ship_spawn_tiles` skips the domain check."""
    env = sea_board()
    city = make_city(env, CENTRE)
    set_base(env, neighbours(env, CENTRE)[0], "Ocean")
    assert not city.can_produce_unit(galley())
    env.players[0].techs.extend(OCEAN_TECHS)
    assert city.can_produce_unit(galley())


def harbor_city():
    """Player 0's city at CENTRE (population 3) with a complete Harbor on a
    ring-2 Coast tile and one Coast tile beside the centre, everything else
    Plains. Returns (env, city, harbor tile, adjacent coast tile)."""
    env = sea_board()
    harbor = ring(env, CENTRE, 2)[0]
    set_base(env, harbor, "Coast")
    coast = next(n for n in neighbours(env, CENTRE) if n not in neighbours(env, harbor))
    set_base(env, coast, "Coast")
    city = make_city(env, CENTRE, population=3)
    own(env, city, harbor)
    assert env.place_district(city, "Harbor", harbor), "fixture: the Harbor must be placeable"
    env.complete_district(city, city.districts[-1])
    return env, city, harbor, coast


def produce(env, city, unit_type):
    """Start `unit_type`, pay for it, run the city's turn: True if it stands."""
    before = len(env.players[0].units)
    assert city.produce_unit(unit_type), unit_type
    city.production = city.get_unit_cost(unit_type)
    city.process_turn(env)
    return len(env.players[0].units) > before


def test_a_ship_appears_on_the_harbor_first_then_beside_the_centre_never_on_land():
    """§11 row 18 and §6.4: the first ship stands on the Harbor, the next on
    the free water tile beside the centre, and with both taken the ship
    waits (deferred) rather than landing. Counted in `naval_units_built`.
    Breaks if the candidate order changes or a ship can spawn on land."""
    env, city, harbor, coast = harbor_city()
    ship = galley()
    assert produce(env, city, ship)
    assert [u.unit_type for u in env.get_units_at(harbor)] == [ship]
    assert produce(env, city, ship)
    assert [u.unit_type for u in env.get_units_at(coast)] == [ship]
    assert not produce(env, city, ship)
    for unit in env.players[0].units:
        assert env.map.get_tile(unit.coordinates).domain == "water"
    assert env.episode_stats[0]["naval_units_built"] == 2


@pytest.mark.parametrize("unit_type", sorted(u for u in LAND_UNITS
                                             if u in BUILD_OPTIONS))
def test_a_land_unit_never_spawns_on_the_harbor(unit_type):
    """§6.4: with the centre taken, a land unit goes to a land tile -- never
    to the Harbor, whatever its class. Breaks if a land candidate reads the
    ship-spawn tiles."""
    env, city, harbor, coast = harbor_city()
    stand(env, LAND_UNITS[0], 0, CENTRE)
    city.complete_unit_production(unit_type, env)
    assert all(u.unit_type != unit_type for u in env.get_units_at(harbor))
    assert all(u.unit_type != unit_type for u in env.get_units_at(coast))


# --- Not land military (v2 non-blocking: the domain filter) ---------------------------


def test_a_ship_fights_but_is_not_land_military():
    """A ship is of a fighting class but not land military: no faith
    category, no garrison on a centre, no zone of control. Breaks if a
    FIGHTING_CLASSES consumer loses its domain filter."""
    env = sea_board()
    city = make_city(env, CENTRE)
    for ship in SHIPS:
        assert unit_model.COMBAT_CLASS[ship] in unit_model.FIGHTING_CLASSES
        assert not is_land_military(ship)
        assert unit_model.faith_category(ship, MOVEMENT_DOMAIN[ship]) is None
        unit = stand(env, ship, 0, CENTRE)      # fixture: stood there by hand
        assert not is_garrisoned(city, env)
        assert not unit.projects_zone_of_control()
        neighbour = neighbours(env, CENTRE)[0]
        assert not env.tile_under_zone_of_control(neighbour, env.players[0])
        env.delete_unit(unit)
    land = next(u for u in LAND_UNITS if unit_model.COMBAT_CLASS[u] in unit_model.FIGHTING_CLASSES)
    stand(env, land, 0, CENTRE)
    assert is_garrisoned(city, env), "fixture: a land unit garrisons"


# --- Combat across domains (§6.5, §11 rows 19-20) -------------------------------------


def coast_duel(attacker_type, attacker_seat, defender_type, ocean=False):
    """A ship on a Coast tile at (3, 9) beside a land tile (3, 8); the
    attacker of `attacker_seat` (0 or 1, player 0 to move) on one, the
    defender on the other -- whichever is its domain. A reserve keeps the
    turn open. Returns (env, attacker, defender)."""
    env = sea_board(ocean=ocean)
    sea, land = (3, 9), (3, 8)
    set_base(env, sea, "Coast")
    a_pos = sea if MOVEMENT_DOMAIN[attacker_type] == "water" else land
    d_pos = land if a_pos == sea else sea
    attacker = stand(env, attacker_type, attacker_seat, a_pos)
    defender = stand(env, defender_type, 1 - attacker_seat, d_pos)
    stand(env, LAND_UNITS[0], 0, (7, 0))
    return env, attacker, defender


@pytest.mark.parametrize("ship", NAVAL_MELEE)
@pytest.mark.parametrize("ship_attacks", [True, False])
def test_melee_crosses_domains_both_ways_and_never_moves_in(ship, ship_attacks):
    """§11 row 19, B5: a naval melee unit attacks an adjacent land unit and
    a land melee unit attacks an adjacent ship -- the mask offers it (the
    enemy is tested before `can_enter`) and the order lands damage; a kill
    leaves the attacker where it stood, since it cannot enter the tile.
    Breaks if the mask gates the attack on terrain or the move-in loses its
    `can_enter` clause."""
    land = next(u for u in LAND_UNITS if unit_model.COMBAT_CLASS[u] == "melee")
    attacker_type, defender_type = (ship, land) if ship_attacks else (land, ship)
    env, attacker, defender = coast_duel(attacker_type, 0, defender_type)
    start = attacker.coordinates
    defender.health = 1
    mask = _valid_order_mask_np(attacker, env, env.n, env.m)
    assert mask[defender.coordinates] == 1
    target = defender.coordinates
    reward = order(env, attacker, target)[1]
    assert reward != REWARDS["invalid_action"]
    assert defender not in env.players[1].units, "fixture: the blow kills"
    assert attacker.coordinates == start
    assert not any(u is attacker for u in env.get_units_at(target))


def test_a_naval_melee_unit_damages_a_coastal_city_but_never_takes_it():
    """§11 row 19, #84: a Caravel (any naval melee unit) attacks an enemy
    coastal city for damage; at health 0 the mask offers nothing there and a
    move order is refused -- `can_capture_city` stays a melee LAND unit.
    Breaks if the capture rule admits ships or the mask offers the walk-in."""
    env = sea_board(ocean=True)
    sea, centre = (3, 9), (3, 8)
    set_base(env, sea, "Coast")
    city = make_city(env, centre, player_index=1)
    ship = stand(env, NAVAL_MELEE[-1], 0, sea)
    stand(env, LAND_UNITS[0], 0, (7, 0))
    before = city.health
    assert _valid_order_mask_np(ship, env, env.n, env.m)[centre] == 1
    assert order(env, ship, centre)[1] != REWARDS["invalid_action"]
    assert city.health < before
    city.health = 0
    ship.movement_points = ship.get_max_movement()
    assert not ship.can_capture_city()
    assert _valid_order_mask_np(ship, env, env.n, env.m)[centre] == 0
    assert order(env, ship, centre)[1] == REWARDS["invalid_action"]
    assert city.player is env.players[1] and ship.coordinates == sea


def test_land_ranged_units_take_minus_17_against_every_naval_class_as_shooters_only():
    """§6.2: every land unit of the `ranged` class shoots at -17 against a
    unit of either naval class -- and only as the shooter: the ship's own
    strengths do not move, and siege units and ships shooting are untouched.
    Breaks if the rows name a unit, miss a naval class, or apply to the
    defender."""
    shooters = [u for u in LAND_UNITS if unit_model.COMBAT_CLASS[u] == "ranged"]
    others = [u for u in unit_model.COMBAT_CLASS
              if unit_model.BASE_RANGED_STRENGTH[u] > 0 and u not in shooters]
    assert shooters and others
    for ship in SHIPS:
        for shooter in shooters:
            assert class_bonus_amounts(STRENGTH_RANGED, shooter, ship) == [-17], (shooter, ship)
            assert class_bonus_amounts(STRENGTH_RANGED, ship, shooter) == [], (ship, shooter)
        for other in others:
            assert -17 not in class_bonus_amounts(STRENGTH_RANGED, other, ship), (other, ship)
    strongest = max(shooters, key=lambda u: unit_model.BASE_RANGED_STRENGTH[u])
    env, ship_unit, archer = coast_duel(SHIPS[0], 1, strongest)
    plain = stand(env, LAND_UNITS[0], 1, (0, 0))
    assert (archer.get_ranged_strength(ship_unit)
            == archer.get_ranged_strength(plain) - 17)
    assert (ship_unit.get_combat_strength(False, archer)
            == ship_unit.get_combat_strength(False, plain))


# --- Mask agreement and the #51 property ----------------------------------------------


def mixed_waters(ocean):
    """A Galley at (3, 9) on Coast; around it Coast, Lake, Ocean, Plains, a
    friendly ship on Coast (slot taken) and an enemy ship on Coast; a reserve
    far away. Rebuilt for every probe so each move is tried on a fresh
    board."""
    env = sea_board(ocean=ocean)
    start = (3, 9)
    set_base(env, start, "Coast")
    ring1 = neighbours(env, start)
    for pos, base in zip(ring1, ("Coast", "Lake", "Ocean", "Plains", "Coast", "Coast")):
        set_base(env, pos, base)
    ship = stand(env, galley(), 0, start)
    stand(env, galley(), 0, ring1[4])
    stand(env, galley(), 1, ring1[5])
    stand(env, LAND_UNITS[0], 0, (7, 0))
    return env, ship, ring1


@pytest.mark.parametrize("ocean", [False, True])
def test_the_ship_mask_offers_exactly_the_moves_unit_move_makes(ocean):
    """Action masking row: for a ship among Coast, Lake, Ocean, land, a
    friendly ship and an enemy ship, a neighbour is offered as a move iff
    `Unit.move` would make it (the enemy is an attack, checked apart).
    Breaks if the mask and `Unit.move` read different domains."""
    env, ship, ring1 = mixed_waters(ocean)
    mask = _valid_order_mask_np(ship, env, env.n, env.m)
    for i, pos in enumerate(ring1[:5]):
        fresh_env, fresh_ship, _ = mixed_waters(ocean)
        moved, _ = fresh_ship.move(pos, fresh_env)
        assert bool(mask[pos]) == moved, (i, pos)
    assert mask[ring1[5]] == 1


def _state(env):
    return ([(u.unit_type, tuple(u.coordinates), u.health, u.movement_points)
             for p in env.players for u in p.units], env.current_player_index)


@pytest.mark.parametrize("ocean", [False, True])
def test_every_order_the_mask_offers_a_ship_changes_the_state(ocean):
    """#51: an offered order that the engine refuses is a state-preserving
    no-op a greedy policy repeats forever. Every order the mask offers the
    ship -- moves, the attack on the enemy ship, fortify -- changes the state
    when stepped. Breaks if the mask offers an order `_step_inner` refuses."""
    env, ship, _ = mixed_waters(ocean)
    mask = _valid_order_mask_np(ship, env, env.n, env.m)
    offered = [tuple(int(v) for v in pos) for pos in np.argwhere(mask > 0)]
    assert len(offered) >= 3
    for pos in offered:
        fresh_env, fresh_ship, _ = mixed_waters(ocean)
        before = _state(fresh_env)
        reward = order(fresh_env, fresh_ship, pos)[1]
        assert reward != REWARDS["invalid_action"], pos
        assert _state(fresh_env) != before, pos


def test_same_seed_same_orders_same_state_with_ships():
    """Determinism with ships: the same seed and the same cross-domain
    orders, over turn rollovers (healing, city strikes on ships), give the
    same units, health and counters. Breaks if anything the sea adds draws
    from another RNG or iterates a set."""
    def run():
        env, ship, defender = coast_duel(galley(), 0, LAND_UNITS[0])
        env.rng.seed(4242)
        city = make_city(env, (3, 6), player_index=1)
        city.buildings.append(unit_model.CITY_RANGED_BUILDING)
        for _ in range(3):
            if ship in env.players[0].units and defender in env.players[1].units:
                ship.movement_points = ship.get_max_movement()
                order(env, ship, defender.coordinates)
            env.next_turn()
            env.next_turn()
        return ([(p.player_index, u.unit_type, tuple(u.coordinates), u.health)
                 for p in env.players for u in p.units],
                dict(env.episode_stats[0]), dict(env.episode_stats[1]), city.health)

    first, second = run(), run()
    assert first == second
    assert first[1]["damage_dealt"] > 0, "fixture: the ship fought"


# --- The Great Lighthouse (§6.1, digest §5) -------------------------------------------


def test_the_great_lighthouse_gives_its_owners_ships_one_movement_and_nothing_else():
    """The Great Lighthouse is placed on Coast beside land and a Harbor; once
    complete, its owner's water units move one more, its owner's land units
    and every other player's ships do not, and its city gains its gold.
    Breaks if `movement_delta` reaches the wrong domain or player, or the
    placement rule is not the Harbor relaxation."""
    env, city, harbor, coast = harbor_city()
    site = next(n for n in neighbours(env, harbor)
                if n != tuple(city.coordinates) and env.map.get_tile(n).district is None
                and n not in neighbours(env, CENTRE))
    set_base(env, site, "Coast")
    own(env, city, site)
    assert env.place_district(city, "Great Lighthouse", site)
    mine = stand(env, galley(), 0, (6, 12))
    theirs = stand(env, galley(), 1, (6, 14))
    walker = stand(env, LAND_UNITS[0], 0, (0, 0))
    before = (mine.get_max_movement(), theirs.get_max_movement(), walker.get_max_movement())
    env.complete_district(city, city.districts[-1])
    after = (mine.get_max_movement(), theirs.get_max_movement(), walker.get_max_movement())
    assert after == (before[0] + 1, before[1], before[2])
    assert before[0] == unit_model.MAX_MOVEMENT[galley()]
    assert district_model.DISTRICTS["Great Lighthouse"].yield_columns["gold"] == 30
