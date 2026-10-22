"""Pure interpreter of the religion config (v0.9.0 Q7, docs/districts_religion_design.md
§7.2, §7.3, §7.6 and its "v3 fixes" L3).

The only module that reads `[religion]`, `[pantheons.*]` and `[beliefs.*]`
from config.toml. It parses once at import, validates strictly (unknown keys
anywhere raise) and keeps every `effects` list RAW: `civulator/effects.py`,
which loads after this module, validates them from the specs parsed here
(never from `CFG`), as it does for every other registry.

Load order (civulator-progression skill §1): `research_model`, then the
`*_model` registries -- this one among them, after `unit_model`. It imports
only `config` and `unit_model` (for the building names a belief's
`requires_building` may use); never `effects` or `civulator.game`.

Config schema:

    [religion]                    # every key required, ints unless noted
    pantheon_cost = 25            # faith (whole points), >= 0
    found_cost = 200              # >= 0
    belief_costs = [300, 500]     # tier 2, tier 3: a list of exactly 2 ints >= 0
    max_religions = 0             # >= 0; 0 = unlimited
    exclusive = true              # bool
    range = 9                     # >= 1, pressure range in hexes
    citizen_weight = 10           # > range (check_pressure_weights)
    secular_weight = 2            # >= 0
    conversion_margin = 25        # percent, >= 0
    conversion_rounds = 3         # >= 1
    spread_cost = 100             # >= 0
    spread_cost_step = 25         # >= 0
    spread_amount = 60            # >= 1
    spread_rounds = 10            # >= 1
    upkeep_per_follower_city = 1  # >= 0
    inquisition_cost = 75         # >= 0
    inquisition_rounds = 10       # >= 1
    foreign_religion_loyalty = -1 # any int (0 disables the term)

    [pantheons.<Name>]            # a table of effects -- nothing else
    description = "..."           # optional, for people
    effects = [...]               # required, non-empty, raw

    [beliefs.<Name>]              # (shape only in Q7; the family is empty)
    tier = "founder"              # founder | follower | enhancer
    counts = "all"                # founder beliefs only, required there: all | foreign
    requires_building = "Shrine"  # optional, a [buildings.*] name
    description = "..."           # optional
    effects = [...]               # required, non-empty, raw

Q7 consumes only `pantheon_cost` (game/religion.py can_choose_pantheon,
GameEnvironment.choose_pantheon); the other `[religion]` keys are parsed and
validated now so Q8/Q9 only add readers.
"""

from dataclasses import dataclass

from .config import CFG
from .unit_model import BUILDING_NAMES

# --- [religion] --------------------------------------------------------------

# key -> minimum (None: any int). `belief_costs` and `exclusive` are checked
# on their own.
_INT_KEYS = {
    "pantheon_cost": 0,
    "found_cost": 0,
    "max_religions": 0,
    "range": 1,
    "citizen_weight": None,  # bound by check_pressure_weights
    "secular_weight": 0,
    "conversion_margin": 0,
    "conversion_rounds": 1,
    "spread_cost": 0,
    "spread_cost_step": 0,
    "spread_amount": 1,
    "spread_rounds": 1,
    "upkeep_per_follower_city": 0,
    "inquisition_cost": 0,
    "inquisition_rounds": 1,
    "foreign_religion_loyalty": None,
}
_RELIGION_KEYS = frozenset({*_INT_KEYS, "belief_costs", "exclusive"})
BELIEF_TIER_COUNT = 2  # `belief_costs`: tier 2, tier 3

_PANTHEON_KEYS = frozenset({"effects", "description"})
_BELIEF_KEYS = frozenset({"tier", "counts", "requires_building", "effects", "description"})

TIER_FOUNDER = "founder"
TIER_FOLLOWER = "follower"
TIER_ENHANCER = "enhancer"
TIERS = (TIER_FOUNDER, TIER_FOLLOWER, TIER_ENHANCER)
COUNTS_ALL = "all"
COUNTS_FOREIGN = "foreign"
COUNTS = (COUNTS_ALL, COUNTS_FOREIGN)


@dataclass(frozen=True)
class ReligionRules:
    """The parsed `[religion]` table, whole points (faith costs are whole
    faith; the faith pool is in tenths, so a reader compares with 10x)."""

    pantheon_cost: int
    found_cost: int
    belief_costs: tuple  # (tier 2, tier 3)
    max_religions: int
    exclusive: bool
    range: int
    citizen_weight: int
    secular_weight: int
    conversion_margin: int
    conversion_rounds: int
    spread_cost: int
    spread_cost_step: int
    spread_amount: int
    spread_rounds: int
    upkeep_per_follower_city: int
    inquisition_cost: int
    inquisition_rounds: int
    foreign_religion_loyalty: int


@dataclass(frozen=True)
class PantheonSpec:
    """One `[pantheons.<Name>]` table: its raw `effects` (validated by
    effects.py, scope player) and an optional description."""

    name: str
    effects: tuple
    description: str = ""


@dataclass(frozen=True)
class BeliefSpec:
    """One `[beliefs.<Name>]` table (design §7.3). `counts` is set for a
    founder belief only; `requires_building` is a building name or None."""

    name: str
    tier: str
    effects: tuple
    counts: object = None
    requires_building: object = None
    description: str = ""


def _int(value, where, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{where} must be an int, got {value!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{where} must be >= {minimum}, got {value!r}")
    return value


def check_pressure_weights(citizen_weight, reach, where="[religion]"):
    """Raise ValueError unless `citizen_weight > reach` (v3 fixes L3, the
    loyalty parser's rule): a city at the edge of the pressure range must
    still weigh. Takes the two numbers so the check can be re-run after a
    `religion_param` raises either (Q8/Q9). Returns nothing."""
    _int(citizen_weight, f"{where} citizen_weight")
    _int(reach, f"{where} range")
    if citizen_weight <= reach:
        raise ValueError(f"{where}: citizen_weight ({citizen_weight}) must exceed "
                         f"range ({reach})")


def parse_religion(cfg):
    """Parse one `[religion]` table -> ReligionRules; raises ValueError on an
    unknown or missing key or a value out of its bound."""
    if not isinstance(cfg, dict):
        raise ValueError("[religion] must be a table")
    unknown = set(cfg) - _RELIGION_KEYS
    if unknown:
        raise ValueError(f"[religion]: unknown key(s) {sorted(unknown)}")
    missing = _RELIGION_KEYS - set(cfg)
    if missing:
        raise ValueError(f"[religion]: missing key(s) {sorted(missing)}")
    values = {key: _int(cfg[key], f"[religion] {key}", minimum)
              for key, minimum in _INT_KEYS.items()}
    costs = cfg["belief_costs"]
    if not isinstance(costs, list) or len(costs) != BELIEF_TIER_COUNT:
        raise ValueError(f"[religion] belief_costs must be a list of {BELIEF_TIER_COUNT} "
                         f"ints, got {costs!r}")
    values["belief_costs"] = tuple(_int(c, f"[religion] belief_costs[{i}]", 0)
                                   for i, c in enumerate(costs))
    if not isinstance(cfg["exclusive"], bool):
        raise ValueError(f"[religion] exclusive must be true or false, got {cfg['exclusive']!r}")
    values["exclusive"] = cfg["exclusive"]
    check_pressure_weights(values["citizen_weight"], values["range"])
    return ReligionRules(**values)


def _effects(table, where):
    effects = table.get("effects")
    if not isinstance(effects, list) or not effects:
        raise ValueError(f"{where}: effects must be a non-empty list, got {effects!r}")
    return tuple(effects)


def _description(table, where):
    text = table.get("description", "")
    if not isinstance(text, str):
        raise ValueError(f"{where}: description must be a string")
    return text


def parse_pantheons(cfg):
    """Parse the `[pantheons]` family -> {name: PantheonSpec}, config order.
    Each table holds `effects` (required, raw) and an optional `description`;
    any other key raises. Names are unique by TOML construction."""
    if not isinstance(cfg, dict):
        raise ValueError("[pantheons] must be a family of tables")
    out = {}
    for name, table in cfg.items():
        where = f"[pantheons.{name}]"
        if not isinstance(table, dict):
            raise ValueError(f"{where} must be a table")
        unknown = set(table) - _PANTHEON_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        out[name] = PantheonSpec(name=name, effects=_effects(table, where),
                                 description=_description(table, where))
    return out


def parse_beliefs(cfg, building_names=BUILDING_NAMES):
    """Parse the `[beliefs]` family -> {name: BeliefSpec}, config order
    (design §7.3). `tier` is one of TIERS; `counts` (one of COUNTS) is
    required on a founder belief and refused on any other; `requires_building`
    names a building of `building_names`; `effects` raw, non-empty."""
    if not isinstance(cfg, dict):
        raise ValueError("[beliefs] must be a family of tables")
    out = {}
    for name, table in cfg.items():
        where = f"[beliefs.{name}]"
        if not isinstance(table, dict):
            raise ValueError(f"{where} must be a table")
        unknown = set(table) - _BELIEF_KEYS
        if unknown:
            raise ValueError(f"{where}: unknown key(s) {sorted(unknown)}")
        tier = table.get("tier")
        if tier not in TIERS:
            raise ValueError(f"{where}: tier must be one of {TIERS}, got {tier!r}")
        counts = table.get("counts")
        if tier == TIER_FOUNDER:
            if counts not in COUNTS:
                raise ValueError(f"{where}: a founder belief declares counts, one of {COUNTS}; "
                                 f"got {counts!r}")
        elif "counts" in table:
            raise ValueError(f"{where}: counts is a founder-belief column")
        building = table.get("requires_building")
        if building is not None and building not in building_names:
            raise ValueError(f"{where}: requires_building {building!r} is not a building")
        out[name] = BeliefSpec(name=name, tier=tier, effects=_effects(table, where),
                               counts=counts, requires_building=building,
                               description=_description(table, where))
    return out


def _check_unique(pantheons, beliefs):
    """A name is a pantheon or a belief, never both (one namespace for the
    choices a player makes)."""
    shared = set(pantheons) & set(beliefs)
    if shared:
        raise ValueError(f"[pantheons] and [beliefs] share name(s) {sorted(shared)}")


RULES = parse_religion(CFG.get("religion"))
PANTHEON_COST = RULES.pantheon_cost

# name -> spec, in config order (the defaults' tie-break).
PANTHEONS = parse_pantheons(CFG.get("pantheons", {}))
PANTHEON_ORDER = tuple(PANTHEONS)
BELIEFS = parse_beliefs(CFG.get("beliefs", {}))
_check_unique(PANTHEONS, BELIEFS)
