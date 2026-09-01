# Civulator — the game in half a page

> Reusable boilerplate: appended verbatim to every experiment report so each
> report is self-contained. Update ONLY when gameplay rules change, and stamp
> the game version. Current: **v0.6.0** (updated 2026-09-02).

Civulator is a simplified Civilization-like strategy game on a **hex map that
wraps east–west** (a cylinder). Experiments use the **Duel** preset: 12×24
tiles, 2 players, procedurally generated "earthlike" worlds (seeded and
exactly reproducible). Each player starts with one capital city and three
Warriors.

**Terrain** is layered — base (grassland, desert, coast, ocean, …), relief
(hills, mountains), features (woods, marsh, …), resources, and rivers — and
determines movement cost, defense bonuses, food/production yields, and line
of sight.

**Cities** produce one thing at a time from seven options: five military
units (Warrior, Spearman, Archer, Horseman, Catapult), Settlers (found new
cities), and the Granary building (growth). Food accumulates into population
growth; a city works its surrounding tiles. An undefended city is captured by
moving a unit onto it.

**Combat** uses a Civ6-style strength formula: units have 100 HP, melee and
ranged attacks, fortification and terrain defense bonuses; ranged units need
line of sight.

**A game ends** by elimination, or at the 250-turn cap, where the winner is
decided by score (cities ×10 + units) — equal scores are a draw.

**The agents**: each player is two networks — a combat DQN that picks a unit
and gives it an order (move/attack/fortify/end turn) from an encoded map
view, and a separate build network that chooses city production. They learn
by self-play against each other.
