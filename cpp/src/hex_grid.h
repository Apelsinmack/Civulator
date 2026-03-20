#pragma once
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <array>

/*
 * Hex grid utilities using AXIAL coordinates (q, r).
 *
 * Axial coords map to a skewed rectangle in memory.
 * The implicit third coordinate s = -q - r completes the cube triple.
 *
 * Distance = max(|dq|, |dr|, |dq + dr|)
 *
 * Cylindrical wrapping: only q-axis wraps (horizontal).
 */

struct HexCoord {
    int q, r;

    bool operator==(const HexCoord& o) const { return q == o.q && r == o.r; }
    bool operator!=(const HexCoord& o) const { return !(*this == o); }
};

// Hash for use in unordered containers
struct HexCoordHash {
    size_t operator()(const HexCoord& c) const {
        // Combine q and r into a single hash
        return std::hash<int64_t>()(static_cast<int64_t>(c.q) << 32 | static_cast<uint32_t>(c.r));
    }
};

// The 6 axial direction vectors — same for every tile, no even/odd branching
constexpr std::array<HexCoord, 6> HEX_DIRECTIONS = {{
    { 1,  0}, { 1, -1}, { 0, -1},
    {-1,  0}, {-1,  1}, { 0,  1}
}};

// Hex distance on axial coordinates (no wrapping)
inline int hex_distance_raw(int dq, int dr) {
    return std::max({std::abs(dq), std::abs(dr), std::abs(dq + dr)});
}

// Hex distance with cylindrical wrapping on q-axis
inline int hex_distance(HexCoord a, HexCoord b, int map_width) {
    int dq_direct = b.q - a.q;

    // Check if wrapping is shorter
    int dq_wrapped;
    if (dq_direct > 0)
        dq_wrapped = dq_direct - map_width;
    else
        dq_wrapped = dq_direct + map_width;

    // Pick the shorter horizontal distance
    int dq = (std::abs(dq_direct) <= std::abs(dq_wrapped)) ? dq_direct : dq_wrapped;
    int dr = b.r - a.r;

    return hex_distance_raw(dq, dr);
}

// Wrap q coordinate to [0, map_width)
inline int wrap_q(int q, int map_width) {
    int r = q % map_width;
    return r < 0 ? r + map_width : r;
}
