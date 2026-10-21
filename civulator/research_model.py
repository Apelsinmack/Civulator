"""Pure interpreter of the research trees (issue #116 P2, docs/progression_design.md
§4.1-§4.3 and "v2 fixes").

The only module that reads `[research]` and `[techs.*]` from config.toml. P4
adds `[civics.*]`, `[governments.*]` and `[policies.*]` here; a civics table
parses with `parse_tree` exactly like the tech table, because both share the
prerequisite vocabulary (a cost, an era, `requires`, raw `effects`).

Load order (v2 fixes, "Load order and config ownership"): this module comes
FIRST. It imports only `config` -- never unit_model, terrain_model or
district_model -- and validates nothing that names a unit, building or
district. The item registries then validate their own `requires_tech`
columns against `TECHS` (through `validate_tech_name`), and the effects
interpreter (P4) validates the raw `effects` lists this module keeps.

Config schema (config.toml):

    [research]
    tech_cost_percent = 75      # one dial for the whole tree (design §12)

    [techs.Writing]
    cost = 50                   # Civ 6 base science, positive int
    era = "Ancient"             # one of ERAS
    requires = ["Pottery"]      # tech names; absent or [] = a start tech
    # effects = [...]           # optional, kept raw (P4's interpreter)

Validation (raises ValueError at import): unknown keys, a non-positive or
non-int cost, an unknown era, a `requires` entry naming nothing or named
twice, and a prerequisite graph that is cyclic or has a tech no research
order can reach (one check: learning every tech whose prerequisites are
known, round after round, must learn them all).
"""

from dataclasses import dataclass

from .config import CFG

# The eras of this block's span, in order (design §4.2).
ERAS = ("Ancient", "Classical", "Medieval", "Renaissance")

# Keys a tree node may carry, and the keys of [research]. P4 adds
# `civic_cost_percent` to the latter.
_NODE_KEYS = frozenset({"cost", "era", "requires", "effects"})
_RESEARCH_KEYS = frozenset({"tech_cost_percent"})


@dataclass(frozen=True)
class NodeSpec:
    """One node of a research tree (a tech; P4: a civic).

    `cost` is the unscaled Civ 6 cost in whole points; `requires` the names
    of its prerequisites, in config order; `effects` the raw `effects` list
    (validated by the effects interpreter, P4), empty when absent.
    """

    name: str
    cost: int
    era: str
    requires: tuple
    effects: tuple


def _positive_int(value, what):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{what} must be a positive int, got {value!r}")
    return value


def _parse_node(name, table, where):
    if not isinstance(table, dict):
        raise ValueError(f"{where} must be a table")
    unknown = set(table) - _NODE_KEYS
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
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
    effects = table.get("effects", [])
    if not isinstance(effects, list):
        raise ValueError(f"{where}: effects must be a list, got {effects!r}")
    return NodeSpec(
        name=name,
        cost=_positive_int(table["cost"], f"{where} cost"),
        era=era,
        requires=tuple(requires),
        effects=tuple(effects),
    )


def parse_tree(tables, table_name):
    """Parse one research tree: `tables` maps node name -> config table
    (`CFG["techs"]`; P4: `CFG["civics"]`). Returns name -> NodeSpec in config
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


_RESEARCH = parse_research(CFG["research"])
TECH_COST_PERCENT = _RESEARCH["tech_cost_percent"]

# The tech tree, name -> NodeSpec, in config order (the auto-pick tie-break).
TECHS = parse_tree(CFG["techs"], "techs")
TECH_ORDER = tuple(TECHS)
TECH_INDEX = {name: index for index, name in enumerate(TECH_ORDER)}


def scaled_tech_cost(name):
    """Whole science points `name` costs: `cost * tech_cost_percent // 100`
    (design §4.3, §12). The pool is in tenths, so resolution compares the
    pool with 10 times this."""
    return TECHS[name].cost * TECH_COST_PERCENT // 100


def validate_tech_name(name, where):
    """Return `name` if it is a tech; raise ValueError naming `where`
    otherwise. The item registries' one check of a `requires_tech` column."""
    if not isinstance(name, str) or name not in TECHS:
        raise ValueError(f"{where}: requires_tech {name!r} is not a tech")
    return name


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
