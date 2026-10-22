# Civulator — the game in half a page

> Reusable boilerplate: appended verbatim to every experiment report so each
> report is self-contained. Update ONLY when gameplay rules change, and stamp
> the game version. Current: **0.9.0 (in progress; not yet released —
> embarkation and fair starts pending)** (updated 2026-10-23). The last
> released version is v0.8.1.

Civulator is a simplified Civilization-like strategy game on a **hex map that
wraps east–west** (a cylinder). Experiments use the **Duel** preset: 12×24
tiles, 2 players, procedurally generated "earthlike" worlds (seeded and
exactly reproducible). Each player starts with one capital city (it holds the
Palace) and three Warriors.

**Terrain** is layered — base (grassland, desert, coast, ocean, …), relief
(hills, mountains), features (woods, marsh, …), resources, and rivers — and
determines movement cost, defense bonuses, yields, and line of sight.
**Resources** come in three classes. Bonus resources add yield. **Strategic**
resources (Horses, Iron, Niter) gate units: a player builds a Horseman or a
Swordsman only with access, i.e. an owned tile holding the resource that is
improved, under a district or a city centre. **Luxuries** give amenities.
Every start region gets Horses and Iron nearby. Workers improve owned tiles on
their own.

**Cities** produce one thing at a time: units (Warrior to Musketman, siege,
Settlers, Workers, Traders, and three ships), buildings, districts, or a
wonder (world-unique: the first to finish it keeps it). Food grows
population, capped by housing; a city owns tiles (centre and ring 1 at
founding, more as its culture grows) and works the owned ones within three
hexes. Each city yields **science, culture, gold and faith** into four player
pools, scaled by its **loyalty** and its **amenities**. Pressed by a bigger
neighbour, a city loses loyalty, and at 0 it flips to that neighbour. A city
short of amenities (luxuries, an Entertainment Complex, some policies and
beliefs) yields and grows less. Science buys a **tech tree** (25 techs),
culture a **civics tree** (20) that unlocks governments and policy cards;
engine defaults choose research, government and cards. Gold pays upkeep (a
bankrupt player's units are disbanded); gold and faith buy items; Traders'
routes yield more.

**The sea.** A city with a Harbor builds ships, which sail coast and lakes
and the ocean once their owner knows the right tech. A trade route between
two Harbors runs by sea, and one that crosses to **another landmass doubles
its yields**. Land units cannot embark yet, so that jump fires only on routes
to an opponent on another continent.

**Districts** add specialist yields from adjacency (Campus, Theater Square,
Holy Site, Harbor, Industrial Zone, …). The **Encampment** is a forward wall:
enemies cannot pass it until they batter it to 0 health, and with Walls it
shoots.

**Religion.** Faith buys a pantheon. A city with a Holy Site and a Temple can
found a **religion** (one founder belief, follower beliefs, an enhancer; each
belief belongs to one religion). A religion spreads on its own: every city
that follows it presses the cities around it, by population, distance and
its Holy Site, Shrine and Temple. A city converts after three rounds under a
clearly stronger pressure, whoever owns it. Its founder pays faith upkeep
per follower city; an unpaid religion stops spreading and stops paying its
founder. Agents may also spend faith to spread to a chosen city or to purge
their own city (no engine default does either). Following a religion your
owner did not found costs a city 1 loyalty per round. Followers get the
follower beliefs, and the founder is paid per follower city.

**Combat** uses a Civ6-style strength formula: units have 100 HP, melee and
ranged attacks, fortification, terrain and class bonuses; ranged units need
line of sight; ships fight across the shore without moving in. A city is
besieged to 0 health, then occupied by a melee land unit.

**A game ends** by elimination (a player is out with no city and no Settler
left), or at the 250-turn cap, where the highest score wins (cities ×10,
units, population, techs ×2, civics ×2, wonders ×10); equal scores are a
draw. **Domination** (one player holds every Palace) and a **religious
victory** (one religion followed by most of every living player's cities)
exist but are off by default (`[game] domination_victory`,
`religious_victory`).

**The agents**: each player is two networks — a combat DQN that picks a unit
and gives it an order (move/attack/fortify/end turn) from an encoded map
view, and a separate build network that chooses city production. They learn
by self-play against each other. Religion, amenities, resources and the sea
are not yet in the agents' state encoding (one design pass later).
