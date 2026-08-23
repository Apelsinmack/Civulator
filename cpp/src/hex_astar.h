#pragma once
#include "hex_grid.h"
#include <cstdint>
#include <vector>

/*
 * A* pathfinding on an axial hex grid with:
 * - Terrain movement costs (per-tile)
 * - Cylindrical wrapping (q-axis only)
 * - Impassable tiles (cost >= IMPASSABLE_THRESHOLD)
 * - Occupied tile blocking (optional mask)
 * - Per-edge river crossing costs (optional; design doc §11 P6, E3, D23)
 *
 * The cost_grid is a 2D array indexed by [r][q] (row-major, matching numpy).
 * Returns a list of (q, r) coordinates from start (exclusive) to goal (inclusive).
 * Returns empty list if no path exists.
 */

constexpr int IMPASSABLE_THRESHOLD = 99;

struct AStarResult {
    std::vector<HexCoord> path;   // Empty if no path found
    int total_cost;               // Sum of terrain costs along path
};

AStarResult hex_astar(
    const float* cost_grid,       // 2D cost array [height][width], row-major
    int width,                    // Map width (q-axis, wraps)
    int height,                   // Map height (r-axis, no wrap)
    HexCoord start,
    HexCoord goal,
    const bool* occupied = nullptr,     // Optional: blocked tiles [height][width]
    const uint8_t* river_flags = nullptr, // Optional: per-tile river-edge bit
                                           // flags [height][width] — bit layout
                                           // documented in civulator/game/map.py
                                           // (RIVER_EDGE_DIRECTIONS) and mirrored
                                           // in hex_astar.cpp (RIVER_OWNED_DIRECTIONS).
                                           // nullptr reproduces pre-P6 behavior.
    float crossing_cost = 0.0f            // Extra cost added when a step crosses
                                           // a flagged river edge.
);
