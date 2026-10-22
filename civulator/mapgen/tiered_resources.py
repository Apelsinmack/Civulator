"""Strategic and luxury resource placement (v0.9.0 Q1,
docs/districts_religion_design.md §2.4 and "v2 fixes" B3): the THIRD
sequential mapgen stage, after `starts.generate_starts`.

Why after starts (B3): start fertility composes resources into tile yields,
and the fairness rule below is written over the start regions, which exist
only inside `generate_starts`. Running here, after it, leaves fertility,
regions and `starts` provably unchanged -- the golden diff of the change that
introduced this stage is `resource` and `params` only. Design doc
docs/terrain_model_design.md §4.2 rule 3 allows a sequential stage by name:
this is it. It reads the regions in start order and writes tiles one after
another, so a tile taken by an earlier step is never offered again.

Determinism (§4.2 rules 1, 6, 7): the only randomness is
`seeding.tile_roll01` under `STAGE_TIERED_RESOURCES` and the purpose ids of
`TIERED_PURPOSE`; every ranking uses a total sort key `(roll, row, col)`;
resources are walked in config order (`terrain_model.resources_of_class`),
tiles in row-major order, regions in start order -- never a set.

The stage, given the params of `[map.earthlike]` (`tiered_*`, mirrored in
`earthlike.DEFAULT_PARAMS`):

1. Strategic fairness: for every region, for every resource in
   `tiered_guaranteed` (Horses, Iron), the region holds at least
   `tiered_strategic_per_region` copies within `tiered_fair_radius` of a
   settleable tile of the region (`starts.is_settleable`). Candidates are
   the region's own tiles first, outside every start's founding ring
   (`tiered_founding_ring`); then the region's tiles inside a founding ring
   but never a start tile; then any tile within the radius of the region's
   settleable tiles. A region none of these can serve raises
   `StartPlacementError`: a Duel where only one seat can build a Swordsman
   is a world defect (design §2.4), and the reset policy already handles a
   world that fails to generate (seeded raises, unseeded resamples).
2. Luxuries, per region: `tiered_luxury_per_region` tiles of ONE luxury
   type where possible, the type chosen by `frequency` weight among the
   types that still have a candidate in the region's reach (its land tiles
   plus water tiles adjacent to them), preferring a type no earlier region
   got (so neighbours differ -- the trade incentive). A shortfall of the
   chosen type is filled by the next chosen type. Never inside a founding
   ring.
3. Extra strategics: `tiered_strategic_per_100_land` per 100 land tiles,
   split over the strategic resources by `frequency` (largest remainder,
   config order breaks ties), each placed on the best-ranked candidates of
   the whole map outside every founding ring. Niter's only source: it has
   no guarantee (design §2.4).

A tile that already carries a resource (the bonus tier, normalization's
bonuses, an earlier step here) is never a candidate: this stage never
overwrites. Pure: numpy + hexmath + terrain_model + this package only.
"""

from .. import hexmath
from ..terrain_model import BASE_TABLE, RESOURCE_FREQUENCY, check_on, resources_of_class
from .seeding import (
    PURPOSE_TIERED_COTTON,
    PURPOSE_TIERED_DYES,
    PURPOSE_TIERED_FURS,
    PURPOSE_TIERED_HORSES,
    PURPOSE_TIERED_IRON,
    PURPOSE_TIERED_LUXURY_TYPE,
    PURPOSE_TIERED_NITER,
    PURPOSE_TIERED_PEARLS,
    PURPOSE_TIERED_SALT,
    PURPOSE_TIERED_SILK,
    PURPOSE_TIERED_SILVER,
    PURPOSE_TIERED_WHALES,
    PURPOSE_TIERED_WINE,
    STAGE_TIERED_RESOURCES,
    mix64,
    stage_seed,
    tile_roll01,
)
from .starts import StartPlacementError, is_settleable

# resource -> its permanent purpose id (seeding.py). A strategic or luxury
# resource missing here makes the stage raise: add a purpose id first.
TIERED_PURPOSE = {
    "Horses": PURPOSE_TIERED_HORSES,
    "Iron": PURPOSE_TIERED_IRON,
    "Niter": PURPOSE_TIERED_NITER,
    "Wine": PURPOSE_TIERED_WINE,
    "Silk": PURPOSE_TIERED_SILK,
    "Dyes": PURPOSE_TIERED_DYES,
    "Cotton": PURPOSE_TIERED_COTTON,
    "Salt": PURPOSE_TIERED_SALT,
    "Silver": PURPOSE_TIERED_SILVER,
    "Furs": PURPOSE_TIERED_FURS,
    "Pearls": PURPOSE_TIERED_PEARLS,
    "Whales": PURPOSE_TIERED_WHALES,
}

# The `[map.earthlike]` keys this stage reads (earthlike.DEFAULT_PARAMS holds
# their defaults; MapData.params records the resolved values).
PARAM_KEYS = (
    "tiered_luxury_per_region",
    "tiered_strategic_per_region",
    "tiered_guaranteed",
    "tiered_fair_radius",
    "tiered_strategic_per_100_land",
    "tiered_founding_ring",
)


def _purpose(name):
    try:
        return TIERED_PURPOSE[name]
    except KeyError:
        raise ValueError(
            f"tiered resource {name!r} has no purpose id: append one to "
            f"mapgen/seeding.py and mapgen/tiered_resources.TIERED_PURPOSE"
        ) from None


class _Stage:
    """The grids and derived masks one call works over."""

    def __init__(self, map_data, master_seed, params):
        self.md = map_data
        self.rows, self.cols = map_data.rows, map_data.cols
        self.seed = stage_seed(master_seed, STAGE_TIERED_RESOURCES)
        self.p = params
        ring = int(params["tiered_founding_ring"])
        self.near_start = set()   # tiles within the founding ring of any start
        for start in map_data.starts:
            for layer in hexmath.hex_rings(tuple(start), ring, self.rows, self.cols):
                self.near_start.update(layer)
        self.start_tiles = {tuple(s) for s in map_data.starts}

    def admits(self, name, coords):
        """`name` may be placed on `coords`: no resource there yet, and the
        resource's `on` admits the tile's base/relief/feature."""
        r, c = coords
        md = self.md
        if md.resource[r, c] is not None or md.base_terrain[r, c] is None:
            return False
        return check_on("resource", name, md.base_terrain[r, c], md.relief[r, c],
                        md.feature[r, c])

    def ranked(self, name, tiles):
        """`tiles` ranked best-first by the total key (roll, row, col)."""
        purpose = _purpose(name)
        return sorted(tiles, key=lambda t: (tile_roll01(self.seed, t[0], t[1], purpose), t[0], t[1]))

    def place(self, name, tiles, count):
        """Write `name` on the first `count` admitted tiles of `tiles` (best
        first); returns how many were placed."""
        placed = 0
        for coords in self.ranked(name, [t for t in tiles if self.admits(name, t)]):
            if placed >= count:
                break
            self.md.resource[coords] = name
            placed += 1
        return placed

    def is_land(self, coords):
        return BASE_TABLE.get(self.md.base_terrain[coords], {}).get("domain") == "land"


def fair_tiles(map_data, region, radius):
    """Every tile within `radius` (canonical wrap distance, through
    `hexmath.hex_rings`) of a settleable tile of `region`, sorted. The
    fairness rule's reach; tests read the same definition."""
    rows, cols = map_data.rows, map_data.cols
    reach = set()
    for coords in region:
        if is_settleable(coords, map_data.base_terrain, map_data.relief,
                         map_data.feature, map_data.resource):
            for layer in hexmath.hex_rings(tuple(coords), radius, rows, cols):
                reach.update(layer)
    return sorted(reach)


def _guarantee_strategics(stage, regions):
    per_region = int(stage.p["tiered_strategic_per_region"])
    radius = int(stage.p["tiered_fair_radius"])
    strategic = set(resources_of_class("strategic"))
    for name in stage.p["tiered_guaranteed"]:
        if name not in strategic:
            raise ValueError(f"tiered_guaranteed names {name!r}, not a strategic resource")
    for index, region in enumerate(regions):
        reach = fair_tiles(stage.md, region, radius)
        reach_set = set(reach)
        own = [t for t in region if t in reach_set]
        own_set = set(own)
        for name in stage.p["tiered_guaranteed"]:
            held = sum(1 for t in own if stage.md.resource[t] == name)
            need = per_region - held
            if need <= 0:
                continue
            tiers = (
                [t for t in own if t not in stage.near_start],
                [t for t in own if t in stage.near_start and t not in stage.start_tiles],
                [t for t in reach if t not in own_set and t not in stage.start_tiles],
            )
            for candidates in tiers:
                need -= stage.place(name, candidates, need)
                if need <= 0:
                    break
            if need > 0 and not any(stage.md.resource[t] == name for t in reach):
                raise StartPlacementError(
                    f"region {index} ({len(region)} tiles) cannot reach any {name} "
                    f"within distance {radius} of a settleable tile (fairness rule)"
                )


def _weighted_pick(names, roll):
    """One of `names` (config order) by `frequency` weight: the first whose
    cumulative weight exceeds `roll * total`."""
    total = sum(RESOURCE_FREQUENCY[n] for n in names)
    target = roll * total
    cumulative = 0
    for name in names:
        cumulative += RESOURCE_FREQUENCY[name]
        if target < cumulative:
            return name
    return names[-1]


def _place_luxuries(stage, regions):
    per_region = int(stage.p["tiered_luxury_per_region"])
    luxuries = resources_of_class("luxury")
    used = []   # types earlier regions got, in placement order
    for index, region in enumerate(regions):
        reach = set(t for t in region if t not in stage.near_start)
        for coords in region:
            for adj in hexmath.adjacent_coords(coords, stage.rows, stage.cols):
                if not stage.is_land(adj) and adj not in stage.near_start:
                    reach.add(adj)
        reach = sorted(reach)
        start = tuple(stage.md.starts[index])
        remaining, step, chosen = per_region, 0, []
        while remaining > 0:
            types = [n for n in luxuries if n not in chosen
                     and any(stage.admits(n, t) for t in reach)]
            if not types:
                break
            fresh = [n for n in types if n not in used]
            roll = tile_roll01(mix64(stage.seed, step), start[0], start[1],
                               PURPOSE_TIERED_LUXURY_TYPE)
            name = _weighted_pick(fresh or types, roll)
            remaining -= stage.place(name, reach, remaining)
            chosen.append(name)
            if name not in used:
                used.append(name)
            step += 1


def _largest_remainder(total, names):
    """`total` split over `names` by `frequency`: floor shares, then one each
    to the largest remainders, config order breaking ties."""
    weights = [RESOURCE_FREQUENCY[n] for n in names]
    weight_sum = sum(weights)
    shares = [total * w // weight_sum for w in weights]
    remainders = [total * w % weight_sum for w in weights]
    order = sorted(range(len(names)), key=lambda i: (-remainders[i], i))
    for i in order[: total - sum(shares)]:
        shares[i] += 1
    return dict(zip(names, shares))


def _place_extra_strategics(stage):
    strategic = resources_of_class("strategic")
    if not strategic:
        return
    land = sum(1 for r in range(stage.rows) for c in range(stage.cols) if stage.is_land((r, c)))
    total = land * int(stage.p["tiered_strategic_per_100_land"]) // 100
    shares = _largest_remainder(total, list(strategic))
    candidates = [(r, c) for r in range(stage.rows) for c in range(stage.cols)
                  if (r, c) not in stage.near_start]
    for name in strategic:
        stage.place(name, candidates, shares[name])


def place_tiered_resources(map_data, regions, master_seed, params):
    """Write strategic and luxury resources into `map_data.resource` (the
    module docstring's three steps). `regions[i]` is the region of
    `map_data.starts[i]` (`starts.generate_starts(..., return_regions=True)`);
    `params` carries every key of PARAM_KEYS. Never overwrites a resource;
    raises StartPlacementError when the fairness rule cannot hold."""
    missing = [k for k in PARAM_KEYS if k not in params]
    if missing:
        raise ValueError(f"place_tiered_resources: missing params {missing}")
    if len(regions) != len(map_data.starts):
        raise ValueError("one region per start is required")
    stage = _Stage(map_data, master_seed, params)
    regions = [sorted(tuple(t) for t in region) for region in regions]
    _guarantee_strategics(stage, regions)
    _place_luxuries(stage, regions)
    _place_extra_strategics(stage)
