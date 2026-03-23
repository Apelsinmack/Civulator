# Civulator – Design Notes

---

## On Balance: The Chess Question

**Why is chess still balanced after ~1500 years with no patches?**

Possible answers worth exploring:
- Chess balance doesn't come from unit stats — it comes from *structural constraints*. You can't choose your army composition. The board and starting positions are fixed. Balance is baked into the *rules*, not the *numbers*.
- No patch needed because there's no metagame drift — the game has no resource economy that can be exploited to snowball into a dominant strategy early.
- Asymmetry exists (White moves first, slight advantage) — and *that's accepted*. Competitive chess acknowledges it at high levels. This raises the question: **does a game need to be perfectly balanced, or just interestingly imbalanced?**

**What does balance actually mean?**

- **Statistical balance**: Win rates across strategies converge toward 50/50
- **Perceived balance**: Players feel their choices matter and that losing was their fault, not the game's
- **Strategic balance**: No single dominant strategy (no "always build queens") — many paths are viable
- **Temporal balance**: Balance changes as players get better; a design balanced for novices breaks at expert level (or vice versa)

**Chess and the "no priority issue":**

Chess avoids the classic 4X problem of "just build the best unit." You can't choose — you work with what you have. This forces players to optimize *use* rather than optimize *composition*. In a civ game, this is the harder problem: how do you make weaker units feel worth using?

Possible mechanics:
- Units have situational bonuses that make them best-in-slot for specific terrain, opponents, or strategies
- Upkeep/maintenance costs that make all-elite armies prohibitive
- Synergy systems that reward mixed compositions

---

## Core Design Goal: Build Variety over Civ Variety

**Insight:** More interesting to have *fewer civs with more build paths* than many civs with narrow identities.

Goals:
- Many meaningful choices at each decision point
- All paths viable *under some circumstances* — no strictly dominant strategies
- Room for obscure, emergent tactics that players discover themselves

**The Dark Souls 2 question:**

DS2 has builds that feel absurd relative to the core loop (e.g., powerstance whips, hex-heavy cleric, torch-only runs). How?
- Stats have interaction depth — everything cross-references everything else
- No single "correct" scaling path; multiple stats feed into damage in non-obvious ways
- The community discovers these, not the tutorials — the game *trusts* the player
- Designer intent seems deliberate: design a system rich enough that obscure combos *emerge from the rules*, then stay out of the way

**For Civulator:** Design the economic/military system with enough interaction depth that players can find non-obvious synergies. Don't hand-hold toward the "right" build.

---

## Mechanical Ideas

### Semi-Simultaneous Turns
- Not for combat (too chaotic/gameable)
- **For building/infrastructure**: players plan and execute builds simultaneously → faster games, less waiting
- **Enforce military-first resolution order** to speed up online play and reduce analysis paralysis

### "City Builder Mode" (Governor Mode)
- A mode where the player handles *only* building, settling, and development
- AI handles all combat decisions
- Unusual, risky to implement well, but genuinely novel
- Could appeal to a different player type (city-builder fans who bounce off 4X combat)

### Leveling Units — Dual Track
- Units level in both **strength** (stats, abilities) and **AI behavior** (smarter pathfinding, target selection, formation keeping)
- Gives players a reason to protect veteran units
- Unit AI improvement as a *visible* system — players can watch their army get smarter
- Potential: units with very high AI level can be set to "full auto" in battle while player micromanages others

---

## Open Questions

- What's the minimum number of civs to feel like a real "civilization" game?
- How do you make obscure tactics *discoverable* without making them obvious? (Hint systems? Community integration?)
- If all paths are viable, what makes players feel like they made *their* build and not just picked from a menu?
- Semi-simultaneous turns: how do you handle conflicts (two players settling the same tile at the same time)?
- Unit AI leveling: does this blur the line between RTS and 4X in a good or bad way?

---

---

## What Civ6 Gets Right (and How to Learn From It)

### Science & Culture Trees

Civ6's tech and civics trees are largely **good design** — they give players a satisfying sense of progression and meaningful choices about priorities.

The problem: **bloat**. Many techs and civics exist as filler — incremental bonuses that don't meaningfully change what you can do. They're speed bumps, not decisions.

**Design direction for Civulator:**
- Keep the *shape* of a branching tech/culture tree
- Ruthlessly cut anything that doesn't unlock a new capability, strategic option, or change how you play
- Each node should feel like a real inflection point — "now I can do X I couldn't before"
- Fewer nodes, higher impact per node → more meaningful tree navigation

**Open question:** Should science and culture be separate trees, or one unified "development" tree with different flavors? Civ6 keeps them separate for thematic reasons — worth examining if that's mechanically justified.

### Wonders

Wonders stay. They are one of the best mechanics in the genre because they create:
- **High-stakes commitment**: you invest production over many turns toward a single goal
- **Player-driven assessment**: you must read the room — are other civs racing for this?
- **Emotional payoff**: building one feels earned; losing the race feels genuinely bad (which is good design — stakes matter)
- **Natural interaction**: Wonders create conflict and diplomatic tension without requiring direct combat

**The penalty problem:**

Losing a Wonder race is currently too punishing in Civ6 — you've sunk production into something that vanishes entirely. This discourages Wonder attempts for risk-averse players, which reduces the interesting interaction.

Possible fixes:
- **Partial consolation**: losing civ gets a fraction of the production refunded as a different bonus (lesser building, gold, culture burst)
- **Fallback unlock**: failed Wonder attempt unlocks a unique building only available to civs that *didn't* build the Wonder — turns the loss into a different path rather than a dead end
- **Wonder tiers**: some Wonders are "contested" (classic race mechanic), others are "exclusive" (only one civ can even attempt them based on prerequisites) — reduces frustration for unwinnable races you didn't know were happening

The goal: maintain the tension and stakes while ensuring the *decision to attempt* a Wonder is always strategically interesting rather than a trap.

---

*Date: 2026-03-22*
