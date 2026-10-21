"""Issue #116 P6: wonders (docs/progression_design.md §9, §3's one-shot kinds,
"v2 fixes" -- Wonders, District registry readers, Yields -- and the §14 rows
"A wonder is refused anywhere once any player completed it ..." and
"Wonders are not `district = "any"` sources ...").

A wonder is a district-registry table with `kind = "wonder"`, so most rules
here are exercised through a synthetic registry patched where every reader
looks (`game/districts.DISTRICTS`, read through `district_spec`): one plain
slot district (Marker, and Marker Two), two adjacency probes (Probe: +3 gold
per adjacent wonder; Generic: +1 culture per adjacent district), and the
wonders each test declares. The real registry is checked by properties over
every `kind == "wonder"` entry; no test names a configured wonder or pins
how many there are.
"""

import ast
import pathlib

import pytest

from civulator import district_model, effects, research_model, unit_model
from civulator.effects import (
    ITEM_BUILDING,
    ITEM_UNIT,
    ONE_SHOT_KINDS,
    active_effects,
    parse_effect,
    slot_counts,
    target_matches,
)
from civulator.game import districts as districts_mod
from civulator.game.districts import (
    District,
    adjacency_score,
    can_place_district,
    completed_wonder_city,
    district_cost,
    specialty_districts,
)
from civulator.game.city import City
from civulator.game.housing import housing
from civulator.game.unit import movement_domain
from civulator.game.yields import city_yield
from civulator.research_model import CIVIC_ORDER, CIVICS
from civulator.terrain_model import BASE_TABLE, FEATURE_TABLE, RELIEF_TABLE, RESOURCE_TABLE
from civulator import terrain_model

from conftest import grant_all, synthetic_government, synthetic_policy
from test_districts import _player_with_completed, board, make_city, neighbours, own, ring

WONDER = district_model.KIND_WONDER
CONSOLATION = district_model.CONSOLATION_PERCENT
# A civic with no effects of its own, to unlock synthetic cards and governments.
QUIET = next(c for c in CIVIC_ORDER if not CIVICS[c].effects)
REPO = pathlib.Path(__file__).resolve().parents[1]


def _wonder_table(**extra):
    table = {"kind": "wonder", "era": "Ancient", "production_cost": 100,
             "cost_model": "fixed", "counts_toward_limit": False, "max_per_city": 1}
    table.update(extra)
    return table


def synthetic(monkeypatch, **wonders):
    """The synthetic registry of the module docstring, plus `wonders`
    (name -> extra columns of a minimal wonder table)."""
    cfg = {
        "population_per_district": 3, "cost_progress_factor": 9,
        "removable_features": ["Woods"], "allowed_features": [],
        "Marker": {"production_cost": 10},
        "Marker Two": {"production_cost": 10},
        "Probe": {"production_cost": 10, "adjacency_yield": "gold",
                  "adjacency": [{"amount": 3, "wonder": "any"}]},
        "Generic": {"production_cost": 10, "adjacency_yield": "culture",
                    "adjacency": [{"amount": 1, "district": "any"}]},
    }
    for name, extra in wonders.items():
        cfg[name] = _wonder_table(**extra)
    reg = district_model.parse_districts(cfg)
    monkeypatch.setattr(districts_mod, "DISTRICTS", reg.districts)
    return reg


def put(env, city, name, pos, complete=True, cost=10):
    """Fixture only: link a District by hand (bypasses placement)."""
    district = District(name, city.city_id, pos, complete=complete, cost=cost)
    env.map.get_tile(pos).district = district
    city.districts.append(district)
    return district


def site(env, city, index=0, distance=2):
    """An owned tile at `distance` from the city's centre."""
    pos = ring(env, city.coordinates, distance)[index]
    own(env, city, pos)
    return pos


def outer_neighbours(env, city, pos):
    """Neighbours of `pos` that are not the city's centre or adjacent to it."""
    centre = tuple(city.coordinates)
    return [n for n in neighbours(env, pos)
            if n != centre and n not in env.map.get_adjacent_coords(centre)]


def land_unit():
    """A land unit type with combat strength (from the unit tables)."""
    return next(u for u in sorted(unit_model.UNIT_NAMES)
                if movement_domain(u) == "land" and unit_model.BASE_COMBAT_STRENGTH[u] > 0)


def owned_units(player, unit_type):
    """Units of `unit_type` the player has standing or queued."""
    return (sum(1 for u in player.units if u.unit_type == unit_type)
            + sum(1 for _, t in player.queued_units if t == unit_type))


# --- (a) world-unique: refused once any player completed it -------------------------


def test_a_wonder_is_refused_everywhere_once_any_player_completed_it(monkeypatch):
    """While copies are only placed, every city may place one (the race);
    once one is complete, every city of every player is refused on every
    tile -- the completing player's other cities too -- and the rule is read
    from live state, so it holds after the holder changes hands. Breaks if
    uniqueness counts placed copies, only refuses the completing player, or
    is cached."""
    synthetic(monkeypatch, Marvel={})
    env = board()
    a = make_city(env, (3, 3))
    b = make_city(env, (3, 11), player_index=1)
    c = make_city(env, (7, 7))
    sites = {city: site(env, city) for city in (a, b, c)}
    assert env.place_district(a, "Marvel", sites[a])
    assert can_place_district(b, "Marvel", sites[b]), "a placed copy elsewhere refuses nothing"
    assert env.place_district(b, "Marvel", sites[b])
    assert completed_wonder_city(env, "Marvel") is None

    env.complete_district(a, a.districts[0])
    assert completed_wonder_city(env, "Marvel") is a
    for city in (a, b, c):
        assert not any(can_place_district(city, "Marvel", pos)
                       for pos in env.map.tiles_of_city(city.city_id)), city.name
    a.set_owner(env.players[1])
    assert completed_wonder_city(env, "Marvel") is a
    assert not any(can_place_district(city, "Marvel", pos)
                   for city in (b, c) for pos in env.map.tiles_of_city(city.city_id))


# --- (b) the race: removal and consolation --------------------------------------------


def test_completion_removes_every_other_copy_and_refunds_the_consolation(monkeypatch):
    """A wonder paid for in process_turn completes through complete_district,
    which removes every other placed copy -- other players' and the
    completer's own other cities' -- frees its tile (assign_tiles re-runs, so
    a good tile is worked again), bumps district_epoch, refunds exactly
    floor(consolation_percent * locked cost / 100) into that city's
    production pool and clears its production item only where it pointed
    at the wonder; the stats count one completion and each lost copy.
    Breaks if a copy survives, the refund is computed on anything but the
    locked cost, the epoch or assign_tiles is skipped, or a loser keeps
    producing a removed wonder."""
    synthetic(monkeypatch, Marvel={})
    env = board()
    a = make_city(env, (3, 3))
    b = make_city(env, (3, 11), player_index=1)
    c = make_city(env, (7, 7))
    for city in (a, b, c):
        assert env.place_district(city, "Marvel", site(env, city))
    b_copy, c_copy = b.districts[0], c.districts[0]
    b_copy.cost, c_copy.cost = 101, 37            # odd locked costs: the floor shows
    freed = b_copy.coordinates
    env.map.get_tile(freed).set_layers("Grassland", resource="Cattle", map_ref=env.map)
    b.assign_tiles(env)
    assert freed not in b.worked_tiles
    assert c.produce_unit(land_unit())              # c switched away from its copy
    b.production, c.production = 7, 3
    epoch = env.map.district_epoch

    a.production = a.districts[0].cost
    env.turn_counter += 1
    a.process_turn(env)

    assert a.districts[0].complete
    for loser, copy, pool in ((b, b_copy, 7), (c, c_copy, 3)):
        assert copy not in loser.districts
        assert env.map.get_tile(copy.coordinates).district is None
        assert loser.production == pool + copy.cost * CONSOLATION // 100
    assert b.production == 7 + 101 * CONSOLATION // 100
    assert b.current_production is None
    assert c.current_production == {"type": "unit", "unit_type": land_unit()}
    assert freed in b.worked_tiles
    assert env.map.district_epoch >= epoch + 2
    assert env.episode_stats[0]["wonders_completed"] == 1
    assert env.episode_stats[1]["wonders_completed"] == 0
    assert env.episode_stats[1]["wonder_races_lost"] == 1
    assert env.episode_stats[0]["wonder_races_lost"] == 1


def test_remove_city_and_the_race_share_one_removal_helper():
    """`remove_city` deletes its districts through `_remove_district`, the
    helper the race uses, and the only other writer of `Tile.district` /
    `City.districts` is `place_district`. Breaks if a second removal path
    is written (design "v2 fixes", Wonders)."""
    source = (REPO / "civulator" / "game" / "environment.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    writers = set()
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in ("district", "districts"):
                    writers.add(func.name)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("append", "remove", "extend")
                    and isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr == "districts"):
                writers.add(func.name)
    assert writers == {"place_district", "_remove_district"}
    remove_city = next(f for f in ast.walk(tree)
                       if isinstance(f, ast.FunctionDef) and f.name == "remove_city")
    calls = {n.func.attr for n in ast.walk(remove_city)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_remove_district" in calls


# --- (c) one-shot effects fire exactly once --------------------------------------------


def _one_shot_board(monkeypatch):
    unit = land_unit()
    synthetic(monkeypatch, Marvel={"effects": [
        {"kind": "free_units", "units": [{"unit": unit, "count": 2}]},
        {"kind": "free_tech", "count": 1},
        {"kind": "free_civic", "count": 1},
        {"kind": "free_population", "amount": 1, "all_cities": True},
    ]})
    env = board()
    player = env.players[0]
    player.techs[:] = []
    player.civics[:] = []
    a = make_city(env, (3, 3), population=2)
    b = make_city(env, (7, 7), population=1)
    rival = make_city(env, (3, 11), player_index=1, population=1)
    assert env.place_district(a, "Marvel", site(env, a))
    player.science, player.culture = 55, 66
    return env, player, unit, a, b, rival


def _snapshot(env):
    return [(list(p.techs), list(p.civics), p.science, p.culture,
             [(u.unit_type, tuple(u.coordinates)) for u in p.units], list(p.queued_units),
             [(c.city_id, c.population, list(c.worked_tiles)) for c in p.cities])
            for p in env.players]


def test_one_shot_effects_fire_once_on_completion_never_again(monkeypatch):
    """On completion the owner gets the free units (placed or queued), the
    current-or-default tech and civic complete at no cost outside the
    one-per-turn rule (pools untouched, counters +1), and every city of the
    owner gains the population with its tiles re-assigned; a second
    complete_district raises and changes nothing; capturing the city fires
    nothing for either player, and the captured wonder cannot complete
    again. Breaks if a one-shot fires twice, on capture, at a cost, or
    misses a city."""
    env, player, unit, a, b, rival = _one_shot_board(monkeypatch)
    from civulator.game.defaults import default_civic, default_research
    tech, civic = default_research(player), default_civic(player)
    assert tech is not None and civic is not None
    units_before = owned_units(player, unit)
    pops = {a: a.population, b: b.population, rival: rival.population}

    env.complete_district(a, a.districts[0])

    assert owned_units(player, unit) == units_before + 2
    assert player.techs == [tech] and player.civics == [civic]
    assert (player.science, player.culture) == (55, 66), "free: the pools are untouched"
    assert env.episode_stats[0]["techs_researched"] == 1
    assert env.episode_stats[0]["civics_researched"] == 1
    assert (a.population, b.population) == (pops[a] + 1, pops[b] + 1)
    assert rival.population == pops[rival]
    for city in (a, b):
        assert len(city.worked_tiles) == city.population
    # the turn's own research still resolves afterwards (outside one-per-turn)
    player.science = 10 ** 6
    assert env.resolve_research(player) is not None
    assert len(player.techs) == 2

    state = _snapshot(env)
    with pytest.raises(ValueError):
        env.complete_district(a, a.districts[0])
    assert _snapshot(env) == state

    a.set_owner(env.players[1])
    after = _snapshot(env)
    for index in (0, 1):
        assert after[index][:6] == state[index][:6], "nothing fires on capture"
    assert a.population == pops[a] + 1
    with pytest.raises(ValueError):
        env.complete_district(a, a.districts[0])


def test_one_shot_effects_fire_from_complete_district_only():
    """`_one_shot_effects` is called from exactly one place in the engine,
    tools and scripts: `complete_district`. No loader rebuilds districts
    (civulator/tools/recording.py holds none), and anything that ever does
    sets `complete` directly, so a load can never fire a one-shot. Breaks
    if a second path (a loader, a capture hook) fires them."""
    callers = []
    for path in sorted((REPO / "civulator").rglob("*.py")) + sorted((REPO / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for func in ast.walk(tree):
            if isinstance(func, ast.FunctionDef):
                for node in ast.walk(func):
                    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                            and node.func.attr == "_one_shot_effects"):
                        callers.append((path.name, func.name))
    assert callers == [("environment.py", "complete_district")]
    recording = (REPO / "civulator" / "tools" / "recording.py").read_text(encoding="utf-8")
    assert "district" not in recording.lower()


def test_free_units_are_queued_when_the_city_has_no_room(monkeypatch):
    """A free unit that cannot be placed goes to `Player.queued_units`
    through `City.place_or_queue_unit` and stands on the board at the
    owner's next turn start once a tile frees. Breaks if a free unit is
    lost or placed outside the one placement path."""
    unit = land_unit()
    synthetic(monkeypatch, Marvel={"effects": [
        {"kind": "free_units", "units": [{"unit": unit, "count": 1}]}]})
    env = board()
    a = make_city(env, (3, 3))
    assert env.place_district(a, "Marvel", site(env, a))
    monkeypatch.setattr(City, "complete_unit_production", lambda self, t, e: False)
    env.complete_district(a, a.districts[0])
    assert a.player.queued_units == [(a.city_id, unit)]
    monkeypatch.undo()
    a.player.place_queued_units()
    assert a.player.queued_units == [] and owned_units(a.player, unit) >= 1


def test_a_wonder_that_grants_a_policy_slot_refits_the_loadout(monkeypatch):
    """A complete wonder's `policy_slots` (scope player) adds to
    slot_counts, and complete_district re-runs the loadout default at once,
    so the new slot is filled. Breaks if wonder slots are not counted or
    the default is not re-run on completion."""
    synthetic(monkeypatch, Marvel={"effects": [
        {"kind": "policy_slots", "wildcard": 1, "scope": "player"}]})
    env = board()
    player = env.players[0]
    player.civics[:] = [QUIET]
    synthetic_government(monkeypatch, "Synthetic Government", {"wildcard": 1},
                         requires_civic=QUIET)
    for name in ("Card A", "Card B"):
        synthetic_policy(monkeypatch, name, [{"kind": "city_ranged_strength", "amount": 1}],
                         requires_civic=QUIET)
    a = make_city(env, (3, 3))
    assert env.set_government(player, "Synthetic Government")
    assert len(player.policies) == 1
    assert env.place_district(a, "Marvel", site(env, a))
    before = slot_counts(player)["wildcard"]
    env.complete_district(a, a.districts[0])
    assert slot_counts(player)["wildcard"] == before + 1
    assert len(player.policies) == 2 and effects.loadout_is_legal(player, player.policies)


# --- (d) adjacency: `wonder = "any"` and `district = "any"` ----------------------------


def test_wonder_any_counts_complete_wonders_only_and_district_any_never_counts_them(monkeypatch):
    """`wonder = "any"` counts an adjacent wonder once it is complete, never
    a placed one and never a district; `district = "any"` counts the city
    centre and districts but no wonder, placed or complete. Breaks if
    adjacency double-counts wonders or counts unfinished ones."""
    synthetic(monkeypatch, Marvel={})
    env = board()
    city = make_city(env, (3, 4), population=10)
    probe = site(env, city, distance=2)
    n1, n2 = outer_neighbours(env, city, probe)[:2]
    wonder = put(env, city, "Marvel", n1, complete=False)
    assert adjacency_score("Probe", probe, env.map) == 0
    wonder.complete = True
    assert adjacency_score("Probe", probe, env.map) == 3
    put(env, city, "Marker", n2)
    assert adjacency_score("Probe", probe, env.map) == 3

    generic = next(p for p in ring(env, city.coordinates, 1))   # next to the centre
    assert adjacency_score("Generic", generic, env.map) == 1     # the centre counts
    far = next(n for n in neighbours(env, n1)
               if n not in (probe, n2) and env.map.distance_function(n, city.coordinates) >= 2
               and env.map.get_tile(n).district is None)
    env.map.get_tile(n1).district = None                         # no wonder at all
    base = adjacency_score("Generic", far, env.map)
    env.map.get_tile(n1).district = wonder
    for complete in (False, True):
        wonder.complete = complete
        assert adjacency_score("Generic", far, env.map) == base, complete
    marker = next(n for n in neighbours(env, far)
                  if n not in (n1, probe) and env.map.get_tile(n).district is None
                  and env.map.get_tile(n).city is None)
    put(env, city, "Marker", marker)
    assert adjacency_score("Generic", far, env.map) == base + 1   # a district does count


def test_the_configured_wonder_rows_count_complete_wonders_only():
    """Every configured adjacency row with a `wonder` source scores an
    adjacent wonder only once it is complete, and no configured
    `district = "any"` row scores one at all (real registry). Breaks if the
    config's wonder rows read placed copies or a district row reads wonders."""
    rows = [(n, r) for n, s in district_model.DISTRICTS.items() for r in s.adjacency
            if r.source.kind == "wonder"]
    if not rows:
        pytest.skip("no wonder row configured")
    wonder_type = next(n for n, s in district_model.DISTRICTS.items() if s.kind == WONDER)
    env = board()
    city = make_city(env, (3, 4), population=10)
    for name, row in rows:
        pos = site(env, city, distance=2)
        n1 = outer_neighbours(env, city, pos)[0]
        before = adjacency_score(name, pos, env.map)
        copy = put(env, city, wonder_type, n1, complete=False)
        assert adjacency_score(name, pos, env.map) == before, name
        copy.complete = True
        assert adjacency_score(name, pos, env.map) == before + (1 // row.per) * row.amount, name
        env.map.get_tile(n1).district = None
        city.districts.remove(copy)


# --- (e) requires_adjacent_all and river_on_tile ------------------------------------------


def test_requires_adjacent_all_needs_every_entry_and_requires_adjacent_any(monkeypatch):
    """`requires_adjacent_all` holds only when every listed source matches
    some neighbour; `requires_adjacent` with the same sources holds with
    any one. Breaks if the all-list is read as any, or ignored."""
    sources = [{"terrain": {"bases": ["Grassland"]}}, {"district": ["Marker"]}]
    synthetic(monkeypatch, Both={"requires_adjacent_all": sources},
              Either={"requires_adjacent": sources})
    env = board()
    city = make_city(env, (3, 4), population=10)
    pos = site(env, city)
    n1, n2 = outer_neighbours(env, city, pos)[:2]
    assert not can_place_district(city, "Both", pos)
    assert not can_place_district(city, "Either", pos)
    env.map.get_tile(n1).set_layers("Grassland", map_ref=env.map)
    assert not can_place_district(city, "Both", pos)
    assert can_place_district(city, "Either", pos)
    env.map.get_tile(n1).set_layers("Plains", map_ref=env.map)
    marker = put(env, city, "Marker", n2)
    assert not can_place_district(city, "Both", pos)
    assert can_place_district(city, "Either", pos)
    env.map.get_tile(n1).set_layers("Grassland", map_ref=env.map)
    assert can_place_district(city, "Both", pos)
    assert marker.complete


def test_river_on_tile_in_a_requires_list_is_any_edge_of_the_tile(monkeypatch):
    """`river_on_tile` in `requires_adjacent` / `requires_adjacent_all` is a
    tile test: a river on any edge of the tile qualifies -- the edge shared
    with the city centre included, unlike the Aqueduct's
    `river_edge_not_shared_with_center`. Breaks if the tile test is not
    accepted in requires lists or is read as the Aqueduct's."""
    synthetic(monkeypatch, Riverside={"requires_adjacent": [{"river_on_tile": True}]},
              Riverall={"requires_adjacent_all": [{"river_on_tile": True}]})
    for name in ("Riverside", "Riverall"):
        env = board()
        city = make_city(env, (3, 4), population=10)
        pos = ring(env, city.coordinates, 1)[0]
        assert not can_place_district(city, name, pos)
        env.map.add_river(pos, city.coordinates)
        assert can_place_district(city, name, pos), name


# --- (f) no slot, no escalation, no discount -----------------------------------------------


def test_a_wonder_takes_no_population_slot_and_never_escalates(monkeypatch):
    """A placed wonder does not use one of the city's district slots, and its
    cost is its base however far its owner is through the trees, while a
    district's escalates. Breaks if a wonder counts toward the limit or its
    cost scales."""
    synthetic(monkeypatch, Marvel={})
    env = board()
    city = make_city(env, (3, 4), population=1)
    s1, s2, s3 = (site(env, city, i) for i in range(3))
    assert env.place_district(city, "Marker", s1)          # the one slot
    assert not can_place_district(city, "Marker Two", s3)
    assert env.place_district(city, "Marvel", s2)           # no slot needed
    city.population = 1 + district_model.POPULATION_PER_DISTRICT   # two slots
    assert can_place_district(city, "Marker Two", s3), "the wonder took no slot"
    monkeypatch.setattr(districts_mod, "game_progress", lambda player: (5, 7))
    factor = districts_mod.COST_PROGRESS_FACTOR
    assert district_cost(city.player, "Marvel") == districts_mod.DISTRICTS["Marvel"].production_cost
    assert district_cost(city.player, "Marker") == 10 * (7 + factor * 5) // 7


def test_the_discount_and_specialty_districts_ignore_wonders():
    """Completed wonders never count toward the discount's B (real
    registry: A - 1 discounted districts plus every wonder leaves the last
    type full price; one more discounted district discounts it), and a
    complete wonder is no specialty district. Breaks if a wonder feeds the
    discount or the specialty count."""
    disc = list(district_model.DISCOUNTED_TYPES)
    wonders = [n for n, s in district_model.DISTRICTS.items() if s.kind == WONDER]
    assert wonders and not set(wonders) & set(disc)
    target = disc[-1]
    spec = district_model.DISTRICTS[target]
    held = _player_with_completed(disc[:-1] + wonders * 3)
    assert district_cost(held, target) == spec.production_cost
    held = _player_with_completed(disc[:-1] + wonders * 3 + [disc[0]])
    assert district_cost(held, target) == spec.production_cost * (100 - spec.discount_percent) // 100
    city = held.cities[0]
    assert all(d.type not in wonders for d in specialty_districts(city))
    assert len(specialty_districts(city)) == len(disc[:-1]) + 1


# --- (g) every configured wonder loads and is placeable on a board meeting its rule --------


def _valid(base, relief, feature, resource):
    try:
        terrain_model.validate(base, relief=relief, feature=feature, resource=resource)
    except ValueError:
        return False
    return True


def _layers_matching(mapping, bare=False):
    """(base, relief, feature, resource) that is valid and matches `mapping`
    (terrain_model `on` form); with `bare`, featureless, resourceless and
    passable (a district's own tile)."""
    reliefs = [r for r in RELIEF_TABLE if not (bare and RELIEF_TABLE[r].get("impassable"))]
    features = [None] if bare else [None, *FEATURE_TABLE]
    resources = [None] if bare else [None, *RESOURCE_TABLE]
    for base in BASE_TABLE:
        for relief in reliefs:
            for feature in features:
                for resource in resources:
                    if (_valid(base, relief, feature, resource)
                            and terrain_model.matches(mapping, base, relief, feature,
                                                      resource=resource)):
                        return base, relief, feature, resource
    raise AssertionError(f"no valid tile matches {mapping!r}")


def _dress(env, city, pos, source, neighbour):
    """Make `source` hold around `pos`, using `neighbour` where it needs one."""
    if source.kind == "terrain":
        base, relief, feature, resource = _layers_matching(source.value)
        env.map.get_tile(neighbour).set_layers(base, relief=relief, feature=feature,
                                               resource=resource, map_ref=env.map)
    elif source.kind == "improvement":
        env.map.get_tile(neighbour).add_improvement(source.value[0], map_ref=env.map)
    elif source.kind == "district":
        assert source.value != "any" and source.value[0] != district_model.CITY_CENTER
        put(env, city, source.value[0], neighbour)
    elif source.kind == "wonder":
        other = next(n for n, s in districts_mod.DISTRICTS.items() if s.kind == WONDER)
        put(env, city, other, neighbour)
    elif source.kind in ("river_on_tile", "river_edge_not_shared_with_center"):
        env.map.add_river(pos, neighbour)
    else:
        raise AssertionError(f"no fixture for source {source.kind!r}")


@pytest.mark.parametrize("name", [n for n, s in district_model.DISTRICTS.items()
                                  if s.kind == WONDER])
def test_every_configured_wonder_loads_and_is_placeable_where_its_rule_holds(name):
    """Every `kind == "wonder"` table carries the wonder invariants (an era
    of the tree, no slot, fixed cost, one per city, no adjacency) and valid
    effects, and on a board dressed to meet its own rule -- its `on`, its
    centre rule, one `requires_adjacent` source, every
    `requires_adjacent_all` source -- a city of a player knowing both trees
    may place it, for its base cost. Breaks if a configured wonder can never
    be placed or loads with a district's rules."""
    spec = district_model.DISTRICTS[name]
    assert spec.era in research_model.ERAS
    assert (spec.counts_toward_limit, spec.cost_model, spec.max_per_city) == (False, "fixed", 1)
    assert spec.adjacency_yield == "none" and spec.adjacency == ()
    effects.effects_of(effects.SOURCE_DISTRICT, name)        # validates

    env = board()
    city = make_city(env, (3, 4), population=10)
    pos = site(env, city, distance=1 if spec.adjacent_to_city_center else 2)
    if spec.on is not None:
        base, relief, _, _ = _layers_matching(spec.on, bare=True)
        env.map.get_tile(pos).set_layers(base, relief=relief, map_ref=env.map)
    spare = [n for n in neighbours(env, pos)
             if n != tuple(city.coordinates) and env.map.get_tile(n).city is None]
    for n in spare:
        own(env, city, n)
    needs = list(spec.requires_adjacent[:1]) + list(spec.requires_adjacent_all)
    assert len(needs) <= len(spare), "fixture: enough neighbours"
    for source, neighbour in zip(needs, spare):
        _dress(env, city, pos, source, neighbour)
    assert can_place_district(city, name, pos), name
    assert env.place_district(city, name, pos), name
    copy = city.districts[-1]
    assert copy.type == name and not copy.complete and copy.cost == spec.production_cost


# --- (h) scope: where a wonder's persistent effects hold -----------------------------------


def test_player_scoped_wonder_effects_reach_every_city_and_city_scoped_stay_home(monkeypatch):
    """Once complete, a wonder's `scope = "player"` effect holds in every city
    of its owner (another city included, no rival's), its city-scoped effect
    and its yield and housing columns in its own city only; while
    incomplete nothing holds; its one-shot entries are never among the
    effects in force. Breaks if wonder effects are gathered with the wrong
    scope, from incomplete copies, or one-shots are read as persistent."""
    synthetic(monkeypatch, Marvel={"culture": 2, "housing": 1.5, "effects": [
        {"kind": "city_ranged_strength", "amount": 5, "scope": "player"},
        {"kind": "combat_strength", "applies_to": ["city"], "amount": 6},
        {"kind": "free_tech", "count": 1},
    ]})
    env = board()
    a = make_city(env, (3, 3))
    b = make_city(env, (7, 7))
    rival = make_city(env, (3, 11), player_index=1)

    def measure():
        return {c: (c.get_ranged_strength(), c.get_combat_strength(), housing(c),
                    city_yield(c, "culture")) for c in (a, b, rival)}

    wonder = put(env, a, "Marvel", site(env, a), complete=False)
    before = measure()
    wonder.complete = True
    after = measure()
    assert after[a] == (before[a][0] + 5, before[a][1] + 6, before[a][2] + 15, before[a][3] + 20)
    assert after[b] == (before[b][0] + 5,) + before[b][1:]
    assert after[rival] == before[rival]
    assert not [e for e in active_effects(a.player, a) if e.kind in ONE_SHOT_KINDS]


def test_a_one_shot_kind_belongs_on_a_wonder_table_only():
    """The loader accepts a one-shot kind on a `kind = "wonder"` table and
    refuses it on a district table (and, as before, anywhere off the
    district registry). Breaks if a district could fire a one-shot."""
    wonder = next(n for n, s in district_model.DISTRICTS.items() if s.kind == WONDER)
    district = next(n for n, s in district_model.DISTRICTS.items()
                    if s.kind == district_model.KIND_DISTRICT)
    entry = {"kind": "free_tech", "count": 1}
    assert parse_effect(entry, "district", wonder).kind == "free_tech"
    with pytest.raises(ValueError):
        parse_effect(entry, "district", district)
    with pytest.raises(ValueError):
        parse_effect(entry, "building", "Probe")


def test_a_building_never_requires_a_wonder():
    """`[buildings.*] requires_district` names a `kind = "district"` entry:
    a wonder name raises, a district name passes. Breaks if a building
    could be gated on standing in a wonder."""
    wonder = next(n for n, s in district_model.DISTRICTS.items() if s.kind == WONDER)
    district = next(n for n, s in district_model.DISTRICTS.items()
                    if s.kind == district_model.KIND_DISTRICT)
    district_model.validate_building_districts({"Probe": district}, district_model.DISTRICTS)
    with pytest.raises(ValueError):
        district_model.validate_building_districts({"Probe": wonder}, district_model.DISTRICTS)


# --- (i) growth_percent scales the growth bucket exactly -------------------------------------


def test_growth_percent_scales_the_growth_bucket_exactly(monkeypatch):
    """With a complete wonder's +15 % growth (scope player), a city's turn
    adds food_net * housing_percent * 100 * 115 // 10000 hundredths to its
    bucket -- in another city of the owner too -- where it added food_net *
    housing_percent before; a rival's city is unchanged. Breaks if the
    percent misses the bucket, reaches the wrong cities, or is floored
    differently."""
    from civulator.unit_model import growth_percent
    synthetic(monkeypatch, Marvel={"effects": [
        {"kind": "growth_percent", "percent": 15, "scope": "player"}]})
    monkeypatch.setattr(City, "calculate_food", lambda self, env: 2 * self.population + 7)
    env = board()
    a = make_city(env, (3, 3))
    b = make_city(env, (7, 7))
    rival = make_city(env, (3, 11), player_index=1)
    wonder = put(env, a, "Marvel", site(env, a), complete=False)

    def gain(city):
        city.food_surplus = 0
        band = growth_percent(housing(city) - 10 * city.population)
        env.turn_counter += 1
        city.process_turn(env)
        return city.food_surplus, band

    for city in (a, b, rival):
        surplus, band = gain(city)
        assert band > 0, "fixture: the city may grow"
        assert surplus == 7 * band
    wonder.complete = True
    for city in (a, b):
        surplus, band = gain(city)
        assert surplus == 7 * band * 100 * 115 // 10000, city.name
    surplus, band = gain(rival)
    assert surplus == 7 * band


# --- (j) capture moves the wonder and its effects -----------------------------------------


def test_capture_moves_the_wonder_and_its_player_effects_and_fires_nothing(monkeypatch):
    """A captured city keeps its complete wonder; its player-scoped effect
    now serves the new owner's cities and no longer the old owner's; no
    one-shot fires for anyone. Breaks if set_owner drops the wonder, keeps
    its effects with the old owner, or re-fires a one-shot."""
    unit = land_unit()
    synthetic(monkeypatch, Marvel={"effects": [
        {"kind": "city_ranged_strength", "amount": 5, "scope": "player"},
        {"kind": "free_units", "units": [{"unit": unit, "count": 1}]},
    ]})
    env = board()
    a = make_city(env, (3, 3))
    b = make_city(env, (7, 7))
    rival = make_city(env, (3, 11), player_index=1)
    assert env.place_district(a, "Marvel", site(env, a))
    wonder = a.districts[0]
    env.complete_district(a, wonder)
    base = {c: c.get_ranged_strength() for c in (b, rival)}
    units = [owned_units(p, unit) for p in env.players]

    a.set_owner(env.players[1])

    assert a.districts == [wonder] and wonder.complete
    assert env.map.get_tile(wonder.coordinates).district is wonder
    assert b.get_ranged_strength() == base[b] - 5
    assert rival.get_ranged_strength() == base[rival] + 5
    assert [owned_units(p, unit) for p in env.players] == units


# --- (k) wonder eras in production_percent targets ------------------------------------------


def test_wonder_era_targets_match_wonders_of_those_eras_only():
    """Every configured `production_percent` target with `wonder_era`
    matches exactly the wonders whose `era` it lists, and no district, unit
    or building (the real registry; the Corvee and Gothic Architecture
    cards, found by their target). Breaks if a wonder's era is ignored or
    the target leaks onto other items."""
    targets = [e["target"] for name in research_model.POLICIES
               for e in effects.effects_of(effects.SOURCE_POLICY, name)
               if e.kind == effects.KIND_PRODUCTION_PERCENT and "wonder_era" in e["target"]]
    assert targets, "fixture: some card targets wonders by era"
    for target in targets:
        for name, spec in district_model.DISTRICTS.items():
            expected = spec.kind == WONDER and spec.era in target["wonder_era"]
            assert target_matches(target, spec.kind, name) == expected, name
        assert not any(target_matches(target, ITEM_UNIT, u) for u in unit_model.UNIT_NAMES)
        assert not any(target_matches(target, ITEM_BUILDING, b) for b in unit_model.BUILDING_NAMES)


def test_a_wonder_era_card_raises_production_toward_wonders_of_its_era_only(monkeypatch):
    """A slotted +50 % card for Ancient wonders raises production toward an
    Ancient wonder by exactly 50 % and leaves a Medieval one alone; the era
    is read from the wonder's own table. Breaks if calculate_production
    ignores the era or reads it from anything but the registry."""
    synthetic(monkeypatch, Old={"era": "Ancient"}, New={"era": "Medieval"})
    env = board()
    player = env.players[0]
    player.civics[:] = [QUIET]
    synthetic_government(monkeypatch, "Synthetic Government", {"wildcard": 1},
                         requires_civic=QUIET)
    synthetic_policy(monkeypatch, "Era Card", [{"kind": "production_percent",
                                                "target": {"kind": "wonder",
                                                           "wonder_era": ["Ancient"]},
                                                "percent": 50}], requires_civic=QUIET)
    city = make_city(env, (3, 4))
    assert env.set_government(player, "Synthetic Government")
    assert env.set_policies(player, ["Era Card"])
    for name in ("Old", "New"):
        put(env, city, name, site(env, city, index=len(city.districts)), complete=False)
    base = city_yield(city, "production")
    assert city.produce_district("Old")
    assert city.calculate_production(env) == max(1, base * 150 // 100)
    assert city.produce_district("New")
    assert city.calculate_production(env) == max(1, base)


@pytest.mark.parametrize("target", [
    {"wonder_era": ["Space Age"]},
    {"wonder_era": "Ancient", "unit": sorted(unit_model.UNIT_NAMES)[0]},
    {"wonder_era": ["Ancient"], "kind": "district"},
    {"wonder_era": ["Ancient"], "building": sorted(unit_model.BUILDING_NAMES)[0]},
    {"wonder_era": []},
])
def test_a_malformed_wonder_era_target_raises_at_load(target):
    """`wonder_era` names eras of the tree and combines (AND) with a wonder
    item only; an unknown era or a target it would make unmatchable raises.
    Breaks if junk era targets load."""
    with pytest.raises(ValueError):
        parse_effect({"kind": "production_percent", "target": target, "percent": 15},
                     "policy", "Probe")
