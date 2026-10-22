---
name: civulator-game-design
description: How to design game content for Civulator as its lead game designer — Erik's principles (meaningful choices, no braindead micro, trees that compete, Civ 6 as reference not model), the standing rulings that constrain every new mechanic, the design-doc contract (rulings table, Systems section, open calls, lens table), and the rule that balance is a dial measured later. Load before designing a district, unit, tree node, belief, victory rule or any mechanic; before answering "what would Erik want here"; and when a design issue (#93–#97, #102) is picked up.
---

# Civulator game design: the designer's procedure

The *developer's* procedure (load order, touch lists, oracle, dials, turn
order) is the sibling skill `civulator-progression`. This skill is what comes
before it: how a mechanic is chosen and written down so that an implementer
can build it without re-deriving it. Rules live in the project `CLAUDE.md`;
designs in `docs/*_design.md`; Erik's rulings in those docs' rulings tables
and the GitHub issues they cite.

## 1. Erik's principles (every design is checked against all of them)

1. **Meaningful choices, few nodes.** A mechanic exists only if it changes
   how a player strategizes (issue #41's rule). "The district that gives
   production" is the least interesting reading of a district; a yield is
   never the feature, the *placement decision* or the *trade-off* is.
2. **No braindead micro.** Nothing per-unit-per-turn that has one right
   answer (Erik, 2026-10-22: missionaries "were not that fun to press spread
   religion so many times each turn"). Spend a resource once on a *choice*;
   let the engine carry it out. If an action would be issued every turn the
   same way, it is an engine default, not an action.
3. **Science, culture and religion compete** (#93). Going for all three is
   hard because they share district slots, production and faith — never
   because a combination is forbidden.
4. **Shared benefits are a trade-off** (#93, 2026-10-11): a religion that
   spreads strengthens whoever adopts it; the founder is paid for spreading
   anyway. Design the reason to spread *and* the cost of spreading.
5. **Content stops where Civ 6 stops being fun**: Knight, Musketman,
   Medieval wonders, Renaissance only where a cut tech blocks something Erik
   asked for (Cartography for ocean trade).
6. **Civ 6 is a reference, not a model.** Copy a mechanic's *values* when
   Erik confirmed its fun (adjacency, Encampment, amenities, pantheons); name
   the source (`docs/civ6_progression_reference.md`, the dumps in
   `docs/districts_design.md`). Replace, never adapt, what he rejected:
   missionaries, apostles, theological combat, Great People, barbarians,
   city-states, stockpiles.
7. **Config, not code; one seam per effect.** A new thing is a table read by
   one interpreter; an effect kind has exactly one consumer. If a design
   needs an `if name == "X"`, it is wrong.
8. **Reasonable starting numbers, balance later.** Every number is a dial
   in `config.toml`, listed in the design's dial table with the stat that
   measures it; the design promises no effect ("effect NOT yet measured").
9. **Determinism is a design constraint.** No mechanic draws RNG unless it
   is combat; anything order-dependent is a round-end phase over phase-start
   state in city-id order; nothing iterates a set.
10. **The state space is designed separately** (Erik, 2026-10-22): a design
    lists what an encoder will need to see and stops there. Rewards likewise
    (#123/#124: held value pays; no event payments).
11. **Routes to success are "builds", and builds should counter and
    reinforce each other** (Erik, 2026-10-22 evening: "it's great that you
    can focus on different paths to success now, like different builds … I
    wonder if we can get some rock-paper-scissors dynamic between the
    routes, as well as some synergetic effects"). When a design adds a
    mechanic, it says which build it strengthens, which build it is a
    counter to, and which other build it synergises with (religion → war
    through Crusade; trade → gold → purchased armies; culture → loyalty
    flips against a wide empire). A mechanic that strengthens every build
    equally is a flat yield and fails principle 1.

## 2. Standing rulings (do not reopen without Erik)

| Ruling | Source |
|---|---|
| Minimum city distance 4 (three tiles between centres) | #74, Erik 2026-10-22 |
| One improvement per tile; a build replaces; a district on an improvement leaves only the district | #126; Erik 2026-10-22 |
| A district on a strategic resource grants the resource, discovered or not | Erik 2026-10-22 (`docs/districts_religion_design.md` §2.3) |
| Neighborhood declined; Harbor, ships and sea trade in | Erik 2026-10-22 |
| Domination off by default; a player is out with no city and no Settler | #126 |
| Every district stays with its city on capture, Government Plaza included | #86 §9 |
| Alliances are not civic-gated; next version (#62) | Erik 2026-10-21 |
| Wonders: consolation 0, `max_per_player = 1`, Oracle Ancient | #116 P9 |
| Loyalty flips pay no event reward; the potential reward covers it | #116 → #124 |
| Embarkation (#76) and fair starts (#85, #112) are designed and shipped before the 0.9 bump | Erik 2026-10-22 evening (C10) |
| Religions capped by the four founder beliefs (`exclusive = true`) | Erik 2026-10-22 evening (C11) |
| Engine RNG moves to the shared `philox32` kit (Q0) | Erik 2026-10-22 evening |
| Barbarians kill units and capture Settlers/Workers, never settle or build; clearing a camp pays gold; goodie huts join them in one design session; pillage is optional, not core | Erik 2026-10-22 evening (#129) |
| City-states come with diplomacy (envoy-style investment bonuses), designed in the diplomacy session, not before | Erik 2026-10-22 evening (#130) |

## 3. The design-doc contract

A design doc (`docs/<topic>_design.md`) has, in this order: status line
(version, what is awaiting whom) · goal · **rulings table** (Erik's rulings
with date, source and the consequence in this design; Claude's calls marked
and flagged where they constrain later design) · principles applied · scope
and an **out-of-scope table** with `ACCEPTED GAP:` where a gap is a
decision · the mechanics, each with its Civ 6 source or "ours" · interactions
checked · **tests as properties** (each naming the change that breaks it) ·
what the state-space pass will need · dial table · patch plan (one system
per patch, gate, model tier, HUMAN-TEST markers) · **Systems** ((a) existing
canonical systems used, (b) new systems with draft CLAUDE.md rows, (c) rows
amended) · **open calls for Erik** with a recommendation each · the lens
table for the critique round. Examples: `docs/progression_design.md`,
`docs/districts_design.md`, `docs/districts_religion_design.md`.

Erik rules on the open calls in chat or on the issue; the rulings go into
the rulings table *with their reason*, and the doc version bumps. The
critique round (`autonomous-patch-workflow`: one Opus critic per lens, one
at a time, verdict on disk before the next) runs on the version Erik has
seen, then the doc is the build contract and is not critiqued again.

## 4. Questions worth asking Erik, and questions not to ask

Ask: anything that changes what the game *is* (a new victory path, a unit
class, which Civ 6 mechanic to keep), a lasting name, a number he has a
feeling about (city distance, costs of the thing he just played). Decide
yourself: data layout, which seam carries an effect, test shape, patch
order, defaults for agentless games — and say so in the doc as "Claude's
call". One question extracts one ruling, and every ruling tends to spawn a
patch: batch them into the open-calls table, never a stream.
