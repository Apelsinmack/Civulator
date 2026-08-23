"""civulator.mapgen — the only world-synthesis system (design doc D17, §4.1,
Systems (b)): "civulator/mapgen/ (pure: numpy + hexmath + terrain_model) is
the only world synthesis; engine builds Tiles from its MapData; loaders
rebuild through it with manifest-pinned params; the preview CLI is the one
place mapgen meets hex_render."

Pure package: numpy + stdlib + `civulator.hexmath` + `civulator.terrain_model`
only. NEVER imports `civulator.game` / `civulator.viz` / `civulator.agents`,
and never `civulator.config` — callers (`Map.generate_map`, the preview CLI
`__main__.py`) read config.toml once and pass explicit `size`/`params` down
(design doc §4.1: "generate must be pure given its inputs — read config
once at call boundary, pass down"), so tests can pin exact params without
touching global config (design doc §8, D21). `__main__.py` is the one
module in this package allowed to import `civulator.viz` (design doc §11
P3: "the CLI `__main__.py` is the sole exception").
"""

from . import basic, earthlike, stats
from .data import MapData, resolve_size

_GENERATORS = {
    "earthlike": earthlike.generate,
    "basic": basic.generate,
}

#: Map-type names `generate`/`resolve_size`'s callers may pass — the same
#: set `[map] type` in config.toml is validated against (design doc E5).
MAP_TYPES = tuple(_GENERATORS)


def generate(seed, size, num_players=2, params=None, map_type="earthlike") -> MapData:
    """Generate one world (design doc §4.1): dispatches to the earthlike or
    basic generator by `map_type`. `size` must already be a (rows, cols)
    tuple — resolve a named preset (e.g. "standard") via `resolve_size`
    BEFORE calling this (mapgen core does not read config.toml's
    `[map.sizes.*]` itself). Earthlike raises ValueError below Duel size
    (design doc E5, enforced in `earthlike.generate`).
    """
    if map_type not in _GENERATORS:
        raise ValueError(f"Unknown map_type: {map_type!r} (expected one of {sorted(_GENERATORS)})")
    return _GENERATORS[map_type](seed, size, num_players=num_players, params=params)


__all__ = ["generate", "MapData", "resolve_size", "MAP_TYPES", "basic", "earthlike", "stats"]
