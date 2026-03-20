#include "hex_astar.h"
#include <queue>
#include <unordered_map>
#include <limits>

AStarResult hex_astar(
    const float* cost_grid,
    int width,
    int height,
    HexCoord start,
    HexCoord goal,
    const bool* occupied)
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

            float tentative_g = current_g + terrain_cost;

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
