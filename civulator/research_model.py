"""Pure interpreter of the research trees (issue #116 P2, docs/progression_design.md
§4.1-§4.3, §5 and "v2 fixes").

The only module that reads `[research]`, `[techs.*]`, `[civics.*]`,
`[governments.*]` and `[policies.*]` from config.toml (#116 P4 added the last
three). A civics table parses with `parse_tree` exactly like the tech table,
because both share the prerequisite vocabulary (a cost, an era, `requires`,
raw `effects`).

Load order (v2 fixes, "Load order and config ownership"): this module comes
FIRST. It imports only `config` -- never unit_model, terrain_model or
district_model -- and validates nothing that names a unit, building or
district. The item registries then validate their own `requires_tech` /
`requires_civic` columns against `TECHS` / `CIVICS` (through
`validate_tech_name` / `validate_civic_name`), and the effects interpreter
(`civulator/effects.py`) validates the raw `effects` lists this module keeps.

Config schema (config.toml):

    [research]
    tech_cost_percent = 75      # one dial per tree (design §12)
    civic_cost_percent = 75

    [techs.Writing]             # a [civics.<Name>] table has exactly this shape
    cost = 50                   # Civ 6 base science (culture), positive int
    era = "Ancient"             # one of ERAS
    requires = ["Pottery"]      # nodes of the same tree; absent or [] = a start node
    # effects = [...]           # optional, kept raw (effects.py interprets)

    [governments.Chiefdom]
    requires_civic = "Code of Laws"   # the civic that unlocks it
    tier = 0                          # int >= 0, read by requires_government_tier
    effects = [...]                   # its policy_slots and inherent bonus, raw

    [policies."God King"]
    type = "economic"                 # one of POLICY_TYPES
    requires_civic = "Code of Laws"   # the civic that unlocks it
    obsolete_with = "Theology"        # optional: the civic that retires it
    effects = [...]                   # raw

Validation (raises ValueError at import): unknown keys, a non-positive or
non-int cost, an unknown era, a `requires` entry naming nothing or named
twice, and a prerequisite graph that is cyclic or has a node no research
order can reach (one check: learning every node whose prerequisites are
known, round after round, must learn them all). A government or policy
naming no civic, a tier that is not an int >= 0, a policy type outside
POLICY_TYPES, and an `obsolete_with` that is the card's own civic or one of
its prerequisites (a card retired before it could ever be slotted) raise too.
"""

from dataclasses import dataclass

from .config import CFG

# The eras of this block's span, in order (design §4.2).
ERAS = ("Ancient", "Classical", "Medieval", "Renaissance")

# Keys a tree node, a government and a policy may carry, and the keys of
# [research].
_NODE_KEYS = frozenset({"cost", "era", "requires", "effects"})
_RESEARCH_KEYS = frozenset({"tech_cost_percent", "civic_cost_percent"})
_GOVERNMENT_KEYS = frozenset({"requires_civic", "tier", "effects"})
_POLICY_KEYS = frozenset({"type", "requires_civic", "obsolete_with", "effects"})

# Policy card types (design §5.3). Civ 6's diplomatic slots are folded into
# wildcard slots and no diplomatic card exists (there are no city-states,
# design §5.2). A typed slot holds a card of its own type; a wildcard slot
# holds a card of any type; a card of type wildcard fits a wildcard slot only.
POLICY_MILITARY = "military"
POLICY_ECONOMIC = "economic"
POLICY_WILDCARD = "wildcard"
POLICY_TYPES = (POLICY_MILITARY, POLICY_ECONOMIC, POLICY_WILDCARD)


@dataclass(frozen=True)
class NodeSpec:
    """One node of a research tree (a tech or a civic).

    `cost` is the unscaled Civ 6 cost in whole points; `requires` the names
    of its prerequisites, in config order; `effects` the raw `effects` list
    (validated by the effects interpreter, `civulator/effects.py`), empty
    when absent.
    """

    name: str
    cost: int
    era: str
    requires: tuple
    effects: tuple


@dataclass(frozen=True)
class GovernmentSpec:
    """One `[governments.*]` table: the civic that unlocks it, its tier (what
    a building's `requires_government_tier` compares with), and its raw
    `effects` -- its `policy_slots` and its inherent bonus."""

    name: str
    requires_civic: str
    tier: int
    effects: tuple


@dataclass(frozen=True)
class PolicySpec:
    """One `[policies.*]` table: its card type (POLICY_TYPES), the civic that
    unlocks it, the civic that makes it obsolete (None: never) and its raw
    `effects`."""

    name: str
    type: str
    requires_civic: str
    obsolete_with: object
    effects: tuple


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} must be a positive int, got {value!r}")
    return value


def _raw_effects(table, where):
    effects = table.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError(f"{where}: effects must be a list, got {effects!r}")
    return tuple(effects)


def _table(table, allowed, where):
    if not isinstance(table, dict):
        raise ValueError(f"{where} must be a table")
    unknown = set(table) - allowed
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")


def _parse_node(name, table, where):
    _table(table, _NODE_KEYS, where)
    if "cost" not in table or "era" not in table:
        raise ValueError(f"{where}: `cost` and `era` are required")
    era = table["era"]
    if era not in ERAS:
        raise ValueError(f"{where}: era {era!r} not in {ERAS}")
    requires = table.get("requires", [])
    if not isinstance(requires, list) or not all(isinstance(r, str) for r in requires):
        raise ValueError(f"{where}: requires must be a list of names, got {requires!r}")
    if len(set(requires)) != len(requires):
        raise ValueError(f"{where}: requires names a prerequisite twice: {requires!r}")
    return NodeSpec(
        name=name,
        cost=_positive_int(table["cost"], f"{where} cost"),
        era=era,
        requires=tuple(requires),
        effects=_raw_effects(table, where),
    )


def parse_tree(tables, table_name):
    """Parse one research tree: `tables` maps node name -> config table
    (`CFG["techs"]` or `CFG["civics"]`). Returns name -> NodeSpec in config
    order. Raises ValueError on any malformed node, on a prerequisite naming
    no node of the same tree, and on a graph that is cyclic or has a node no
    research order reaches.
    """
    if not isinstance(tables, dict) or not tables:
        raise ValueError(f"[{table_name}.*]: at least one node is required")
    tree = {
        name: _parse_node(name, table, f"[{table_name}.{name}]")
        for name, table in tables.items()
    }
    for spec in tree.values():
        missing = [r for r in spec.requires if r not in tree]
        if missing:
            raise ValueError(f"[{table_name}.{spec.name}] requires unknown {missing}")
    # Reachability and acyclicity in one pass: learn, round by round, every
    # node whose prerequisites are all learned. A node left over sits on a
    # cycle or behind one.
    learned = set()
    while True:
        ready = [n for n, s in tree.items()
                 if n not in learned and all(r in learned for r in s.requires)]
        if not ready:
            break
        learned.update(ready)
    stuck = [n for n in tree if n not in learned]
    if stuck:
        raise ValueError(
            f"[{table_name}.*]: prerequisite cycle or unreachable node(s) {stuck}"
        )
    return tree


def parse_research(table):
    """`[research]` -> {key: positive int percent}; exactly the known keys."""
    if not isinstance(table, dict):
        raise ValueError("[research] must be a table")
    unknown = set(table) - _RESEARCH_KEYS
    missing = _RESEARCH_KEYS - set(table)
    if unknown or missing:
        raise ValueError(
            f"[research]: unknown key(s) {sorted(unknown)}, missing key(s) {sorted(missing)}"
        )
    return {key: _positive_int(table[key], f"[research] {key}") for key in table}


def _civic_column(table, column, civics, where):
    value = table.get(column)
    if not isinstance(value, str) or value not in civics:
        raise ValueError(f"{where}: {column} {value!r} is not a civic")
    return value


def parse_governments(tables, civics):
    """`[governments.*]` -> name -> GovernmentSpec, in config order. Every
    government names a civic of the `civics` tree and a tier (int >= 0);
    unknown keys raise. `effects` stay raw (effects.py validates them).
    Every civic is reachable (`parse_tree`), so every government is too."""
    if not isinstance(tables, dict) or not tables:
        raise ValueError("[governments.*]: at least one government is required")
    out = {}
    for name, table in tables.items():
        where = f"[governments.{name}]"
        _table(table, _GOVERNMENT_KEYS, where)
        tier = table.get("tier")
        if isinstance(tier, bool) or not isinstance(tier, int) or tier < 0:
            raise ValueError(f"{where}: tier must be an int >= 0, got {tier!r}")
        out[name] = GovernmentSpec(
            name=name,
            requires_civic=_civic_column(table, "requires_civic", civics, where),
            tier=tier,
            effects=_raw_effects(table, where),
        )
    return out


def ancestors(tree, name):
    """Every node `name` of `tree` requires, directly or transitively."""
    seen, stack = set(), list(tree[name].requires)
    while stack:
        node = stack.pop()
        if node not in seen:
            seen.add(node)
            stack.extend(tree[node].requires)
    return seen


def parse_policies(tables, civics):
    """`[policies.*]` -> name -> PolicySpec, in config order. Every card has a
    type of POLICY_TYPES and names its unlocking civic; an `obsolete_with`
    must be a civic that is neither the unlocking civic nor one of its
    prerequisites (such a card would be obsolete the moment it unlocked).
    Unknown keys raise; `effects` stay raw."""
    if not isinstance(tables, dict) or not tables:
        raise ValueError("[policies.*]: at least one policy is required")
    out = {}
    for name, table in tables.items():
        where = f"[policies.{name}]"
        _table(table, _POLICY_KEYS, where)
        if table.get("type") not in POLICY_TYPES:
            raise ValueError(f"{where}: type {table.get('type')!r} not in {POLICY_TYPES}")
        requires = _civic_column(table, "requires_civic", civics, where)
        obsolete = None
        if "obsolete_with" in table:
            obsolete = _civic_column(table, "obsolete_with", civics, where)
            if obsolete == requires or obsolete in ancestors(civics, requires):
                raise ValueError(
                    f"{where}: obsolete_with {obsolete!r} is known before the card unlocks")
        out[name] = PolicySpec(
            name=name,
            type=table["type"],
            requires_civic=requires,
            obsolete_with=obsolete,
            effects=_raw_effects(table, where),
        )
    return out


_RESEARCH = parse_research(CFG["research"])
TECH_COST_PERCENT = _RESEARCH["tech_cost_percent"]
CIVIC_COST_PERCENT = _RESEARCH["civic_cost_percent"]

# The tech tree, name -> NodeSpec, in config order (the auto-pick tie-break).
TECHS = parse_tree(CFG["techs"], "techs")
TECH_ORDER = tuple(TECHS)
TECH_INDEX = {name: index for index, name in enumerate(TECH_ORDER)}

# The civics tree (#116 P4, design §5.1): the same shape, the same parser.
CIVICS = parse_tree(CFG["civics"], "civics")
CIVIC_ORDER = tuple(CIVICS)
CIVIC_INDEX = {name: index for index, name in enumerate(CIVIC_ORDER)}

# Governments and policy cards (#116 P4, design §5.2-§5.3), name -> spec in
# config order (the defaults' tie-break).
GOVERNMENTS = parse_governments(CFG["governments"], CIVICS)
GOVERNMENT_ORDER = tuple(GOVERNMENTS)
POLICIES = parse_policies(CFG["policies"], CIVICS)
POLICY_ORDER = tuple(POLICIES)


def scaled_tech_cost(name):
    """Whole science points `name` costs: `cost * tech_cost_percent // 100`
    (design §4.3, §12). The pool is in tenths, so resolution compares the
    pool with 10 times this."""
    return TECHS[name].cost * TECH_COST_PERCENT // 100


def scaled_civic_cost(name):
    """Whole culture points civic `name` costs: `cost * civic_cost_percent
    // 100` (design §5.1, §12). The culture pool is in tenths, like science."""
    return CIVICS[name].cost * CIVIC_COST_PERCENT // 100


def validate_tech_name(name, where):
    """Return `name` if it is a tech; raise ValueError naming `where`
    otherwise. The item registries' one check of a `requires_tech` column."""
    if not isinstance(name, str) or name not in TECHS:
        raise ValueError(f"{where}: requires_tech {name!r} is not a tech")
    return name


def validate_civic_name(name, where):
    """Return `name` if it is a civic; raise ValueError naming `where`
    otherwise. The item registries' one check of a `requires_civic` column."""
    if not isinstance(name, str) or name not in CIVICS:
        raise ValueError(f"{where}: requires_civic {name!r} is not a civic")
    return name


def validate_government_tier(tier, where):
    """Return `tier` if it is an int >= 0 that some government reaches; raise
    ValueError naming `where` otherwise (a tier above every government's
    would make the item unbuildable forever). The one check of a
    `requires_government_tier` column."""
    if isinstance(tier, bool) or not isinstance(tier, int) or tier < 0:
        raise ValueError(f"{where}: requires_government_tier must be an int >= 0, got {tier!r}")
    if not any(g.tier >= tier for g in GOVERNMENTS.values()):
        raise ValueError(
            f"{where}: requires_government_tier {tier} is above every government's tier")
    return tier


def is_available(tree, name, known):
    """True iff `name` is a node of `tree`, not in `known`, and every
    prerequisite is in `known` (a list of completed node names). Pure."""
    spec = tree.get(name)
    if spec is None or name in known:
        return False
    return all(r in known for r in spec.requires)


def available(tree, known):
    """The nodes of `tree` available given `known`, in config order."""
    return [name for name in tree if is_available(tree, name, known)]
