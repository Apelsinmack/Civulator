#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>
#include <cstdint>
#include "hex_grid.h"
#include "hex_astar.h"

namespace py = pybind11;

PYBIND11_MODULE(civulator_core, m) {
    m.doc() = "Civulator C++ core — hex grid utilities and A* pathfinding";

    // --- Hex distance function ---
    m.def("hex_distance", [](int q1, int r1, int q2, int r2, int map_width) {
        return hex_distance({q1, r1}, {q2, r2}, map_width);
    }, "Hex distance with cylindrical wrapping",
       py::arg("q1"), py::arg("r1"), py::arg("q2"), py::arg("r2"), py::arg("map_width"));

    // --- A* pathfinding ---
    m.def("hex_astar", [](
        py::array_t<float> cost_grid,
        int start_q, int start_r,
        int goal_q, int goal_r,
        py::object occupied_obj,
        py::object river_flags_obj,
        float crossing_cost)
    {
        auto cost = cost_grid.unchecked<2>();
        int height = cost.shape(0);
        int width = cost.shape(1);

        const bool* occ_ptr = nullptr;
        py::array_t<bool> occupied_arr;
        if (!occupied_obj.is_none()) {
            occupied_arr = occupied_obj.cast<py::array_t<bool>>();
            occ_ptr = occupied_arr.unchecked<2>().data(0, 0);
        }

        const uint8_t* river_ptr = nullptr;
        py::array_t<uint8_t> river_arr;
        if (!river_flags_obj.is_none()) {
            river_arr = river_flags_obj.cast<py::array_t<uint8_t>>();
            river_ptr = river_arr.unchecked<2>().data(0, 0);
        }

        AStarResult result = hex_astar(
            cost.data(0, 0),
            width, height,
            {start_q, start_r},
            {goal_q, goal_r},
            occ_ptr,
            river_ptr,
            crossing_cost
        );

        // Convert path to list of (q, r) tuples
        py::list path;
        for (const auto& c : result.path) {
            path.append(py::make_tuple(c.q, c.r));
        }
        return py::make_tuple(path, result.total_cost);
    },
    "A* pathfinding on axial hex grid with cylindrical wrapping.\n\n"
    "Args:\n"
    "    cost_grid: 2D float array [height][width] of terrain movement costs.\n"
    "               Values >= 99 are impassable.\n"
    "    start_q, start_r: Start position (axial coordinates)\n"
    "    goal_q, goal_r: Goal position (axial coordinates)\n"
    "    occupied: Optional 2D bool array [height][width] of blocked tiles\n"
    "    river_flags: Optional 2D uint8 array [height][width] of per-tile\n"
    "                 river-edge bit flags (3 bits; see civulator.game.map.\n"
    "                 RIVER_EDGE_DIRECTIONS for the bit layout, mirrored here\n"
    "                 as RIVER_OWNED_DIRECTIONS). None or all-zero reproduces\n"
    "                 pre-P6 (river-blind) behavior.\n"
    "    crossing_cost: Extra cost added when a step crosses a flagged river\n"
    "                   edge (design doc D23, [terrain.river].crossing_cost).\n\n"
    "Returns:\n"
    "    (path, total_cost) where path is list of (q, r) tuples (start excluded, goal included).\n"
    "    Empty path and cost=-1 if no path exists.",
    py::arg("cost_grid"),
    py::arg("start_q"), py::arg("start_r"),
    py::arg("goal_q"), py::arg("goal_r"),
    py::arg("occupied") = py::none(),
    py::arg("river_flags") = py::none(),
    py::arg("crossing_cost") = 0.0f);
}
