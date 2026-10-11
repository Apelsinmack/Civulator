"""Territory rules (issue #87, spec docs/borders_culture_design.md §2, §3.2, §3.4).

The only reader of `[territory]` in config.toml, and home of the §3.2
tile-choice ranking (used by the founding claim's replacements now and by
border growth in P3). Pure engine code: hexmath for every radius/ring/
adjacency, the composed tile yields for value, `PortableRNG` (passed in) for
the tiebreak. The ownership grid itself and its mutation API live on `Map`.
"""

from .. import hexmath
from ..config import CFG

_TERRITORY_CFG = CFG["territory"]
CLAIM_RADIUS = int(_TERRITORY_CFG["claim_radius"])
WORK_RADIUS = int(_TERRITORY_CFG["work_radius"])
FOUNDING_RING = int(_TERRITORY_CFG["founding_ring"])

NEUTRAL = -1


def _has_resource(tile):
    return tile is not None and bool(tile.resource)


def claim_candidates(game_map, city, claim_radius=None):
    """§3.2 candidates at minimum distance: neutral tiles within
    `claim_radius` of the city centre (canonical wrap distance), adjacent to a
    tile this city owns, restricted to the nearest ring that has any.

    Returns a list of (row, col), sorted by (row, col); empty if none.
    """
    radius = CLAIM_RADIUS if claim_radius is None else claim_radius
    owner = game_map.owner_city
    rows, cols = game_map.n, game_map.m
    rings = hexmath.hex_rings(city.coordinates, radius, rows, cols)
    for ring in rings[1:]:
        found = [
            pos for pos in ring
            if owner[pos] == NEUTRAL
            and any(owner[adj] == city.city_id for adj in hexmath.adjacent_coords(pos, rows, cols))
        ]
        if found:
            return sorted(found)
    return []


def claim_rank(game_map, pos):
    """§3.2 value key, larger is better: (has a resource, adjacent to a
    resource tile of any owner, food + production composed through the
    terrain model)."""
    tile = game_map.get_tile(pos)
    adjacent_resource = any(
        _has_resource(game_map.get_tile(adj))
        for adj in hexmath.adjacent_coords(pos, game_map.n, game_map.m)
    )
    food, production = tile.yields
    return (_has_resource(tile), adjacent_resource, food + production)


def choose_claim_tile(game_map, city, rng, claim_radius=None):
    """The tile `city` claims next by §3.2, or None if there is no candidate.

    Minimum distance first (the ring rule), then `claim_rank`; ties left
    after ranking are sorted by (row, col) and, only when two or more remain,
    shuffled with the engine RNG (§3.4) — the first is taken.
    """
    candidates = claim_candidates(game_map, city, claim_radius)
    if not candidates:
        return None
    ranked = [(claim_rank(game_map, pos), pos) for pos in candidates]
    best = max(key for key, _ in ranked)
    tied = sorted(pos for key, pos in ranked if key == best)
    if len(tied) >= 2:
        rng.shuffle(tied)
    return tied[0]
