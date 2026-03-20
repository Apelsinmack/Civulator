# Map Generator — Notes (2026-03-20)

## Current state
- Prototype in `map_generator_prototype.py` — generates hex maps with climate zones, terrain, rivers
- Uses axial coordinates (q, r) matching Civulator's existing system
- Pure-Python value noise (no C dependencies)
- Cylindrical wrapping via 3D noise on (cos θ, sin θ, row)

## Issues to fix

### 1. Directional bias in terrain patterns
Terrain features streak along E-W and NE-SW axes. Nothing runs NW-SE.
**Cause**: cylindrical 3D noise mapping creates directional correlation between
the circle (cos θ, sin θ) and the row axis.
**Proposed fix**: Go back to flat 2D noise (which produced the best continent
shapes in first iteration) and blend left/right edges over a narrow strip to
fake seamless wrapping. Simpler and avoids directional artifacts.

### 2. No tundra or snow at poles
Temperature formula never goes below 0 — the latitude gradient range is wrong.
`1.2 - 2.4 * abs(lat - 0.5)` maxes out at 1.2 (equator) but only reaches 0
at poles. Needs to reach -1.2 at poles so the "freezing" and "cold" temperature
bands actually trigger.

### 3. Rivers
Should clearly start from highlands/mountains or lakes, and flow downhill
toward the sea. Current logic attempts this but results are hard to evaluate
because of the terrain shape issues. Revisit after fixing noise.
In Civ 6, rivers run on hex edges (borders between tiles) — the data model
already supports this (`Map.rivers` is a set of tile-pair edges).
