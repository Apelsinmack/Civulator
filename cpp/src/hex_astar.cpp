#include "hex_astar.h"
#include <array>
#include <queue>
#include <unordered_map>
#include <limits>

namespace {

// Same 3-of-6 canonical directions as civulator/game/map.py's
// RIVER_EDGE_DIRECTIONS (there expressed as (delta_row, delta_col); here as
// (delta_q, delta_r) — civulator/game/map.py bit k is (+1,0),(+1,-1),(0,-1)
// in (row,col) form, which is (dq=0,dr=1),(dq=-1,dr=1),(dq=-1,dr=0) here).
// The other 3 HEX_DIRECTIONS entries are each one of these negated, so
// ownership is total and unambiguous — see map.py for the full writeup.
// Bit k (1 << k) set on a tile means: a river edge crosses its border
// toward RIVER_OWNED_DIRECTIONS[k]. Change one side, change both.
constexpr std::array<HexCoord, 3> RIVER_OWNED_DIRECTIONS = {{
    {0, 1}, {-1, 1}, {-1, 0}
}};

inline int river_bit_index(int dq, int dr) {
    for (int i = 0; i < 3; ++i) {
        if (RIVER_OWNED_DIRECTIONS[i].q == dq && RIVER_OWNED_DIRECTIONS[i].r == dr)
            return i;
    }
    return -1;
}

// Extra cost for stepping current -> neighbor (already-wrapped, adjacent
// tiles reached via direction (dq, dr)) if that edge is flagged as a river
// crossing; 0 otherwise. dq/dr must be one of the 6 hex unit directions —
// guaranteed by callers, which pass the HEX_DIRECTIONS entry they just used.
inline float river_edge_cost(
    const uint8_t* river_flags, int width,
    HexCoord current, HexCoord neighbor,
    int dq, int dr, float crossing_cost)
{
    if (!river_flags || crossing_cost == 0.0f)
        return 0.0f;

    int bit = river_bit_index(dq, dr);
    if (bit >= 0) {
        uint8_t flags = river_flags[current.r * width + current.q];
        return (flags & (1 << bit)) ? crossing_cost : 0.0f;
    }
    // -dq/-dr is guaranteed to be one of the 3 owned directions (every hex
    // direction is either owned or the exact opposite of an owned one).
    bit = river_bit_index(-dq, -dr);
    uint8_t flags = river_flags[neighbor.r * width + neighbor.q];
    return (flags & (1 << bit)) ? crossing_cost : 0.0f;
}

}  // namespace

AStarResult hex_astar(
    const float* cost_grid,
    int width,
    int height,
    HexCoord start,
    HexCoord goal,
    const bool* occupied,
    const uint8_t* river_flags,
    float crossing_cost)
{
    // Priority queue: (f_score, coord)
    using PQEntry = std::pair<float, HexCoord>;
    auto cmp = [](const PQEntry& a, const PQEntry& b) { return a.first > b.first; };
    std::priority_queue<PQEntry, std::vector<PQEntry>, decltype(cmp)> open(cmp);

    std::unordered_map<HexCoord, float, HexCoordHash> g_score;
    std::unordered_map<HexCoord, HexCoord, HexCoordHash> came_from;

    g_score[start] = 0.0f;
    float h = static_cast<float>(hex_distance(start, goal, width));
    open.push({h, start});

    while (!open.empty()) {
        auto [f, current] = open.top();
        open.pop();

        // Reached the goal — reconstruct path
        if (current == goal) {
            AStarResult result;
            result.total_cost = static_cast<int>(g_score[goal]);

            // Trace back from goal to start (exclusive)
            HexCoord node = goal;
            while (node != start) {
                result.path.push_back(node);
                node = came_from[node];
            }
            // Reverse to get start→goal order (start excluded)
            std::reverse(result.path.begin(), result.path.end());
            return result;
        }

        float current_g = g_score[current];

        // Skip if we've already found a better path to this node
        if (current_g > f - static_cast<float>(hex_distance(current, goal, width)) + 0.01f) {
            // This is a stale entry — but since we use the simpler "re-add" approach,
            // just check if g_score has been improved since this was added
            auto it = g_score.find(current);
            if (it != g_score.end() && it->second < current_g)
                continue;
        }

        // Explore neighbors
        for (const auto& dir : HEX_DIRECTIONS) {
            HexCoord neighbor = {current.q + dir.q, current.r + dir.r};

            // Wrap q-axis (cylindrical)
            neighbor.q = wrap_q(neighbor.q, width);

            // Check bounds (r-axis does NOT wrap)
            if (neighbor.r < 0 || neighbor.r >= height)
                continue;

            // Look up terrain cost
            int idx = neighbor.r * width + neighbor.q;
            float terrain_cost = cost_grid[idx];

            // Skip impassable terrain
            if (terrain_cost >= IMPASSABLE_THRESHOLD)
                continue;

            // Skip occupied tiles (unless it's the goal — we want to path TO it)
            if (occupied && occupied[idx] && neighbor != goal)
                continue;

            float step_cost = terrain_cost + river_edge_cost(
                river_flags, width, current, neighbor, dir.q, dir.r, crossing_cost);
            float tentative_g = current_g + step_cost;

            auto it = g_score.find(neighbor);
            if (it == g_score.end() || tentative_g < it->second) {
                g_score[neighbor] = tentative_g;
                came_from[neighbor] = current;
                float h_n = static_cast<float>(hex_distance(neighbor, goal, width));
                open.push({tentative_g + h_n, neighbor});
            }
        }
    }

    // No path found
    return AStarResult{{}, -1};
}
