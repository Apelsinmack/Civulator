"""Game configuration loader — reads config.toml from project root."""

import os

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Fallback for older Python


def _find_config():
    """Find config.toml by walking up from this file to the project root."""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):  # Walk up at most 5 levels
        candidate = os.path.join(d, "config.toml")
        if os.path.exists(candidate):
            return candidate
        d = os.path.dirname(d)
    return None


def load_config():
    """Load and return the config dict from config.toml."""
    path = _find_config()
    if path is None:
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


# Singleton — loaded once on import
CFG = load_config()
