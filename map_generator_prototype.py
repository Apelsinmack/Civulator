"""Procedural hex map generator prototype — Civ 6 style.

Axial coordinates (q, r) matching Civulator's existing system.
Generates terrain via layered simplex noise, then rivers via
downhill flow along hex edges.

Run standalone for matplotlib preview:
    python map_generator_prototype.py
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.collections import PatchCollection, LineCollection
from hashlib import md5


# ---------------------------------------------------------------------------
# Pure-Python value noise (no C dependencies)
# ---------------------------------------------------------------------------

def _hash2d(ix, iy, seed=0):
    """Deterministic pseudo-random float in [-1, 1] from integer coords."""
    h = md5(f"{ix},{iy},{seed}".encode()).digest()
    return (int.from_bytes(h[:4], 'little') / 0xFFFFFFFF) * 2 - 1


def _lerp(a, b, t):
    return a + t * (b - a)


def _fade(t):
    """Quintic smoothstep."""
    return t * t * t * (t * (t * 6 - 15) + 10)


def _hash3d(ix, iy, iz, seed=0):
    """Deterministic pseudo-random float in [-1, 1] from integer 3D coords."""
    h = md5(f"{ix},{iy},{iz},{seed}".encode()).digest()
    return (int.from_bytes(h[:4], 'little') / 0xFFFFFFFF) * 2 - 1


def value_noise_3d(x, y, z, seed=0):
    """Single-octave 3D value noise. Returns roughly [-1, 1]."""
    ix, iy, iz = int(np.floor(x)), int(np.floor(y)), int(np.floor(z))
    fx, fy, fz = x - ix, y - iy, z - iz
    fx, fy, fz = _fade(fx), _fade(fy), _fade(fz)
    # Trilinear interpolation of 8 corners
    n000 = _hash3d(ix, iy, iz, seed)
    n100 = _hash3d(ix+1, iy, iz, seed)
    n010 = _hash3d(ix, iy+1, iz, seed)
    n110 = _hash3d(ix+1, iy+1, iz, seed)
    n001 = _hash3d(ix, iy, iz+1, seed)
    n101 = _hash3d(ix+1, iy, iz+1, seed)
    n011 = _hash3d(ix, iy+1, iz+1, seed)
    n111 = _hash3d(ix+1, iy+1, iz+1, seed)
    nx00 = _lerp(n000, n100, fx)
    nx10 = _lerp(n010, n110, fx)
    nx01 = _lerp(n001, n101, fx)
    nx11 = _lerp(n011, n111, fx)
    nxy0 = _lerp(nx00, nx10, fy)
    nxy1 = _lerp(nx01, nx11, fy)
    return _lerp(nxy0, nxy1, fz)


def fbm_cylinder(cx, cy, row, octaves=3, seed=0):
    """Fractal Brownian motion on a cylinder — (cx, cy) = circle, row = height."""
    val = 0.0
    amp = 1.0
    freq = 1.0
    total_amp = 0.0
    for i in range(octaves):
        val += amp * value_noise_3d(cx * freq, cy * freq, row * freq, seed + i * 37)
        total_amp += amp
        amp *= 0.5
        freq *= 2.0
    return val / total_amp


# ---------------------------------------------------------------------------
# Terrain generation
# ---------------------------------------------------------------------------

# Base terrain types (Civ 6 style)
# Determined by temperature × moisture lookup
TERRAIN_TABLE = {
    #           low moisture    mid moisture    high moisture
    "freezing": ("Snow",        "Snow",         "Snow"),
    "cold":     ("Tundra",      "Tundra",       "Tundra"),
    "cool":     ("Plains",      "Plains",       "Grassland"),
    "warm":     ("Plains",      "Grassland",    "Grassland"),
    "hot":      ("Desert",      "Plains",       "Plains"),
}

# Features layered on top of base terrain
# Hills: from elevation noise
# Woods: temperate + mid/high moisture + not desert
# Rainforest: hot + high moisture
# (Mountains handled separately via elevation threshold)

TERRAIN_COLORS = {
    "Ocean":          "#1a5276",
    "Coast":          "#2980b9",
    "Snow":           "#f0f0f0",
    "Tundra":         "#8b9e6b",
    "Plains":         "#c4a747",
    "Grassland":      "#4a8c3f",
    "Desert":         "#e8d5a3",
    "Mountain":       "#6b6b6b",
    # Feature overlays (slightly modify base color)
    "Plains+Hills":       "#b89a3a",
    "Grassland+Hills":    "#3d7a34",
    "Desert+Hills":       "#d4c090",
    "Tundra+Hills":       "#7a8d5e",
    "Snow+Hills":         "#d8d8d8",
    "Plains+Woods":       "#8a7a30",
    "Grassland+Woods":    "#2d6b24",
    "Tundra+Woods":       "#5a6e40",
    "Plains+Rainforest":  "#2d6b24",
    "Grassland+Rainforest": "#1a5c14",
}


def generate_map(n_rows, n_cols, seed=None):
    """Generate a hex map with climate-based terrain.

    Returns:
        terrain: (n_rows, n_cols) array of base terrain strings
        features: (n_rows, n_cols) array of feature strings (or "")
        rivers: set of ((r1,c1), (r2,c2)) edge pairs
    """
    if seed is not None:
        np.random.seed(seed)
        noise_seed = seed
    else:
        noise_seed = np.random.randint(0, 10000)

    terrain = np.empty((n_rows, n_cols), dtype=object)
    features = np.empty((n_rows, n_cols), dtype=object)
    elevation = np.zeros((n_rows, n_cols))
    moisture = np.zeros((n_rows, n_cols))
    temperature = np.zeros((n_rows, n_cols))

    # --- Generate noise fields ---
    # For cylindrical wrapping (Civ 6 style): map column onto a circle
    # in 3D noise space: (cos(θ), sin(θ), row). This makes left and right
    # edges seamless while preserving natural-looking terrain.
    TWO_PI = 2 * np.pi
    # Circle radius controls feature scale (larger = bigger, more varied features)
    R_elev = n_cols * 0.04 / TWO_PI * 4.0
    R_moist = n_cols * 0.05 / TWO_PI * 4.0

    for r in range(n_rows):
        for c in range(n_cols):
            angle = TWO_PI * c / n_cols
            cos_a, sin_a = np.cos(angle), np.sin(angle)

            # Elevation: 3D noise on cylinder surface
            elevation[r, c] = fbm_cylinder(
                cos_a * R_elev, sin_a * R_elev, r * 0.04,
                octaves=4, seed=noise_seed)

            # Moisture: independent 3D noise on cylinder
            moisture[r, c] = fbm_cylinder(
                cos_a * R_moist, sin_a * R_moist, r * 0.05,
                octaves=3, seed=noise_seed + 100)

            # Temperature: latitude gradient + noise
            lat = r / n_rows  # 0 = north pole, 1 = south pole
            temp_base = 1.2 - 2.4 * abs(lat - 0.5)  # >1 at equator, <-1 at poles
            temp_noise = 0.2 * fbm_cylinder(
                cos_a * R_moist, sin_a * R_moist, r * 0.06,
                octaves=2, seed=noise_seed + 200)
            temperature[r, c] = temp_base + temp_noise

    # --- Assign terrain ---
    sea_level = -0.05  # tune: negative = more land, positive = more water
    mountain_threshold = 0.55
    hill_threshold = 0.25

    for r in range(n_rows):
        for c in range(n_cols):
            e = elevation[r, c]
            t = temperature[r, c]
            m = moisture[r, c]

            # Water
            if e < sea_level:
                if e < sea_level - 0.3:
                    terrain[r, c] = "Ocean"
                else:
                    terrain[r, c] = "Coast"
                features[r, c] = ""
                continue

            # Mountains
            if e > mountain_threshold:
                terrain[r, c] = "Mountain"
                features[r, c] = ""
                continue

            # Temperature band
            if t < -0.6:
                t_band = "freezing"
            elif t < -0.2:
                t_band = "cold"
            elif t < 0.2:
                t_band = "cool"
            elif t < 0.6:
                t_band = "warm"
            else:
                t_band = "hot"

            # Moisture band (0=low, 1=mid, 2=high)
            if m < -0.15:
                m_idx = 0
            elif m < 0.15:
                m_idx = 1
            else:
                m_idx = 2

            base = TERRAIN_TABLE[t_band][m_idx]
            terrain[r, c] = base

            # Features
            feat = ""
            if e > hill_threshold:
                feat = "Hills"
            elif t_band in ("cool", "warm") and m > 0.0 and base != "Desert":
                feat = "Woods"
            elif t_band == "cold" and m > 0.2:
                feat = "Woods"
            elif t_band == "hot" and m > 0.1 and base != "Desert":
                feat = "Rainforest"

            features[r, c] = feat

    # --- Generate rivers ---
    rivers = generate_rivers(elevation, terrain, n_rows, n_cols, n_rivers=8, seed=noise_seed)

    return terrain, features, elevation, rivers


# ---------------------------------------------------------------------------
# River generation — flow along hex edges
# ---------------------------------------------------------------------------

# In axial coords, each hex (r, c) has 6 neighbours.
# A river is an EDGE between two adjacent hexes.
# We trace rivers by following downhill elevation from a source to the coast.

HEX_DIRS = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]


def _neighbors(r, c, n_rows, n_cols):
    """Yield valid (nr, nc) neighbors in axial coords."""
    for dr, dc in HEX_DIRS:
        nr, nc = r + dr, c + dc
        if 0 <= nr < n_rows and 0 <= nc < n_cols:
            yield nr, nc


def generate_rivers(elevation, terrain, n_rows, n_cols, n_rivers=8, seed=0):
    """Generate rivers as edge features between hex tiles (Civ 6 style).

    Rivers can cross any terrain (hills, plains, desert).
    They generally flow from high ground toward the coast, but with
    some randomness so they meander naturally.
    """
    rng = np.random.RandomState(seed + 500)
    rivers = set()

    # Find candidate sources: near mountains or high-ish land
    candidates = []
    for r in range(n_rows):
        for c in range(n_cols):
            if terrain[r, c] not in ("Ocean", "Coast"):
                # Prefer tiles near mountains or with moderate-high elevation
                has_mountain_neighbor = any(
                    terrain[nr, nc] == "Mountain"
                    for nr, nc in _neighbors(r, c, n_rows, n_cols)
                )
                if has_mountain_neighbor or elevation[r, c] > 0.2:
                    candidates.append((r, c))

    if not candidates:
        return rivers

    rng.shuffle(candidates)
    used_sources = set()  # avoid rivers starting too close together

    river_count = 0
    for source in candidates:
        if river_count >= n_rivers:
            break

        # Skip if too close to an existing river source
        if any(abs(source[0] - s[0]) + abs(source[1] - s[1]) < 5
               for s in used_sources):
            continue

        path_edges = []
        visited = set()
        cr, cc = source
        visited.add((cr, cc))
        reached_water = False

        for _ in range(60):  # max river length
            neighbors = list(_neighbors(cr, cc, n_rows, n_cols))
            if not neighbors:
                break

            # Score each neighbor: prefer lower elevation, but add randomness
            scored = []
            for nr, nc in neighbors:
                if (nr, nc) in visited:
                    continue
                e = elevation[nr, nc]
                # Bias toward downhill + random jitter for meandering
                score = e + rng.uniform(-0.15, 0.05)
                scored.append((score, nr, nc))

            if not scored:
                break

            scored.sort()
            # Usually pick the lowest, occasionally pick 2nd lowest
            idx = 0 if rng.random() < 0.7 or len(scored) == 1 else 1
            _, nr, nc = scored[idx]

            edge = tuple(sorted(((cr, cc), (nr, nc))))
            path_edges.append(edge)
            visited.add((nr, nc))

            if terrain[nr, nc] in ("Ocean", "Coast"):
                reached_water = True
                break

            cr, cc = nr, nc

        # Keep rivers that reached water and are long enough
        if reached_water and len(path_edges) >= 3:
            rivers.update(path_edges)
            used_sources.add(source)
            river_count += 1

    return rivers


# ---------------------------------------------------------------------------
# Matplotlib visualization
# ---------------------------------------------------------------------------

def axial_to_pixel(r, c, size=1.0):
    """Convert axial hex (r, c) to pixel center (x, y).

    Pointy-top orientation matching Civ 6.
    """
    x = size * (np.sqrt(3) * c + np.sqrt(3) / 2 * r)
    y = size * (3 / 2 * r)
    return x, y


def hex_vertices(cx, cy, size=1.0):
    """Return 6 vertices of a pointy-top hexagon centered at (cx, cy)."""
    angles = np.linspace(np.pi / 6, np.pi / 6 + 2 * np.pi, 7)[:-1]
    return [(cx + size * np.cos(a), cy + size * np.sin(a)) for a in angles]


def edge_midpoints(r1, c1, r2, c2, size=1.0):
    """Get the two hex-vertex endpoints of the edge between two adjacent tiles.

    The edge between hex A and hex B is the line segment connecting the two
    vertices shared by both hexagons.
    """
    cx1, cy1 = axial_to_pixel(r1, c1, size)
    cx2, cy2 = axial_to_pixel(r2, c2, size)
    v1 = set([(round(x, 4), round(y, 4)) for x, y in hex_vertices(cx1, cy1, size)])
    v2 = set([(round(x, 4), round(y, 4)) for x, y in hex_vertices(cx2, cy2, size)])
    shared = v1 & v2
    if len(shared) == 2:
        return list(shared)
    # Fallback: midpoint line
    mx, my = (cx1 + cx2) / 2, (cy1 + cy2) / 2
    return [(mx, my), (mx, my)]


def plot_map(terrain, features, rivers, size=1.0):
    """Render the hex map with matplotlib."""
    n_rows, n_cols = terrain.shape

    fig, ax = plt.subplots(1, 1, figsize=(max(16, n_cols * 0.5), max(10, n_rows * 0.4)))
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor("#1a3c5e")

    patches = []
    colors = []

    for r in range(n_rows):
        for c in range(n_cols):
            cx, cy = axial_to_pixel(r, c, size)
            verts = hex_vertices(cx, cy, size * 0.98)  # slight gap
            hex_patch = mpatches.Polygon(verts, closed=True)
            patches.append(hex_patch)

            t = terrain[r, c]
            f = features[r, c]

            # Look up color: try terrain+feature combo first
            key = f"{t}+{f}" if f else t
            color = TERRAIN_COLORS.get(key, TERRAIN_COLORS.get(t, "#ff00ff"))
            colors.append(color)

    pc = PatchCollection(patches, facecolors=colors, edgecolors="#00000020",
                         linewidths=0.3)
    ax.add_collection(pc)

    # Draw rivers
    if rivers:
        river_lines = []
        for (r1, c1), (r2, c2) in rivers:
            pts = edge_midpoints(r1, c1, r2, c2, size)
            if len(pts) == 2:
                river_lines.append(pts)
        if river_lines:
            lc = LineCollection(river_lines, colors="#3498db", linewidths=2.5,
                                zorder=5, capstyle="round")
            ax.add_collection(lc)

    ax.autoscale_view()
    ax.set_title("Procedural Hex Map — Civ 6 Style", fontsize=14, pad=10)

    # Legend
    legend_items = [
        ("Ocean", "#1a5276"), ("Coast", "#2980b9"), ("Snow", "#f0f0f0"),
        ("Tundra", "#8b9e6b"), ("Plains", "#c4a747"), ("Grassland", "#4a8c3f"),
        ("Desert", "#e8d5a3"), ("Mountain", "#6b6b6b"), ("Woods", "#2d6b24"),
        ("Rainforest", "#1a5c14"), ("River", "#3498db"),
    ]
    handles = [mpatches.Patch(facecolor=c, label=n, edgecolor="gray", linewidth=0.5)
               for n, c in legend_items]
    ax.legend(handles=handles, loc="upper right", fontsize=8, framealpha=0.8)

    plt.tight_layout()
    plt.savefig("map_preview.png", dpi=150, bbox_inches="tight")
    plt.show()
    print("Saved map_preview.png")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Generating map...")
    terrain, features, elevation, rivers = generate_map(
        n_rows=40, n_cols=60, seed=42
    )

    # Stats
    unique, counts = np.unique(terrain, return_counts=True)
    print("\nTerrain distribution:")
    for t, n in sorted(zip(unique, counts), key=lambda x: -x[1]):
        print(f"  {t:15s} {n:5d}  ({100*n/terrain.size:.1f}%)")

    n_river_edges = len(rivers)
    print(f"\nRiver edges: {n_river_edges}")

    print("\nRendering...")
    plot_map(terrain, features, rivers, size=1.0)
