"""
Civulator C++ core — hex grid utilities and A* pathfinding
"""
from __future__ import annotations
import numpy
import numpy.typing
import typing
__all__: list[str] = ['build_info', 'hex_astar', 'hex_distance']
def build_info() -> dict:
    """
    Build provenance captured at CMake configure time (issue #47).
    
    Returns:
        dict with keys: commit (str, 'unknown' if git was unavailable at configure time), dirty (bool, or None if the dirty flag could not be determined), build_date (str, UTC).
    
    Captured at CONFIGURE time only -- an incremental build without re-running cmake can leave this stale. civulator.game.map's import site compares this against the running checkout's HEAD and warns on mismatch; it never blocks import.
    """
def hex_astar(cost_grid: typing.Annotated[numpy.typing.ArrayLike, numpy.float32], start_q: typing.SupportsInt | typing.SupportsIndex, start_r: typing.SupportsInt | typing.SupportsIndex, goal_q: typing.SupportsInt | typing.SupportsIndex, goal_r: typing.SupportsInt | typing.SupportsIndex, occupied: typing.Any = None, river_flags: typing.Any = None, crossing_cost: typing.SupportsFloat | typing.SupportsIndex = 0.0) -> tuple[list, int]:
    """
    A* pathfinding on axial hex grid with cylindrical wrapping.
    
    Args:
        cost_grid: 2D float array [height][width] of terrain movement costs.
                   Values >= 99 are impassable.
        start_q, start_r: Start position (axial coordinates)
        goal_q, goal_r: Goal position (axial coordinates)
        occupied: Optional 2D bool array [height][width] of blocked tiles
        river_flags: Optional 2D uint8 array [height][width] of per-tile
                     river-edge bit flags (3 bits; see civulator.game.map.
                     RIVER_EDGE_DIRECTIONS for the bit layout, mirrored here
                     as RIVER_OWNED_DIRECTIONS). None or all-zero reproduces
                     pre-P6 (river-blind) behavior.
        crossing_cost: Extra cost added when a step crosses a flagged river
                       edge (design doc D23, [terrain.river].crossing_cost).
    
    Returns:
        (path, total_cost) where path is list of (q, r) tuples (start excluded, goal included).
        Empty path and cost=-1 if no path exists.
    """
def hex_distance(q1: typing.SupportsInt | typing.SupportsIndex, r1: typing.SupportsInt | typing.SupportsIndex, q2: typing.SupportsInt | typing.SupportsIndex, r2: typing.SupportsInt | typing.SupportsIndex, map_width: typing.SupportsInt | typing.SupportsIndex) -> int:
    """
    Hex distance with cylindrical wrapping
    """
