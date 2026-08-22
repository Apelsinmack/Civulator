"""Human-facing tools built on top of the engine (scenario recording, etc.).

Unlike `civulator/game/`, this package MAY import torch, numpy and
`civulator.agents` — it is tooling around the simulation, not the simulation.
It must never be imported by `civulator/game/`.

It must also stay UI-free (no pyray): the raylib front-ends live in `scripts/`
and render through `civulator.viz.hex_render`.
"""
