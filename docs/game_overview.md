# Civulator — the game in half a page

> Reusable boilerplate: appended verbatim to every experiment report so each
> report is self-contained. Update ONLY when gameplay rules change, and stamp
> the game version. Current: **v0.8.0** (updated 2026-10-21).

Civulator is a simplified Civilization-like strategy game on a **hex map that
wraps east–west** (a cylinder). Experiments use the **Duel** preset: 12×24
tiles, 2 players, procedurally generated "earthlike" worlds (seeded and
exactly reproducible). Each player starts with one capital city (it holds the
Palace) and three Warriors.

**Terrain** is layered — base (grassland, desert, coast, ocean, …), relief
(hills, mountains), features (woods, marsh, …), resources, and rivers — and
determines movement cost, defense bonuses, yields, and line of sight. Workers
improve owned tiles on their own.

**Cities** produce one thing at a time: units (Warrior to Musketman, Settlers,
Workers, Traders), buildings, districts, or a wonder (world-unique: the first
to finish it keeps it). Food grows population, capped by housing; a city owns
tiles (centre and ring 1 at founding, more as its culture grows) and works the
owned ones within three hexes. Each city yields **science, culture, gold and
faith** into four player pools, scaled by its **loyalty** — pressed by a
bigger neighbour it loses loyalty, and at 0 it flips to that neighbour.
Science buys a **tech tree** (22 techs), culture a **civics tree** (19) that
unlocks governments and policy cards; engine defaults choose research,
government and cards. Gold pays upkeep (a bankrupt player's units are
disbanded); gold and faith buy items; Traders' routes yield more.

**Combat** uses a Civ6-style strength formula: units have 100 HP, melee and
ranged attacks, fortification, terrain and class bonuses; ranged units need
line of sight. A city is besieged to 0 health, then occupied by a melee unit.

**A game ends** by elimination; by **domination** (one player holds every
Palace — in a Duel, takes the enemy capital); or at the 250-turn cap, where
the highest score wins (cities ×10, units, population, techs ×2, civics ×2,
wonders ×10) — equal scores are a draw.

**The agents**: each player is two networks — a combat DQN that picks a unit
and gives it an order (move/attack/fortify/end turn) from an encoded map
view, and a separate build network that chooses city production. They learn
by self-play against each other.
