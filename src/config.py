"""
BetVector Configuration Loader
===============================
Loads all YAML config files and exposes them as typed, dot-notation-accessible
objects.  Consuming code never touches raw dicts — every value is accessed via
attributes on the singleton ``config`` object.

Usage::

    from src.config import config

    # League data
    print(config.leagues[0].short_name)          # "EPL"
    print(config.leagues[0].seasons)             # ["2020-21", ...]

    # System settings
    print(config.settings.edge_threshold)        # 0.05 (shortcut)
    print(config.settings.bankroll.stake_percentage)  # 0.02

    # Email settings
    print(config.email.smtp.host)                # "smtp.gmail.com"

Config files are located relative to the project root (the directory that
contains ``config/``).  The loader resolves this automatically so it works
whether you run from the repo root, from ``src/``, or via ``pytest``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ============================================================================
# Project root resolution
# ============================================================================

def _find_project_root() -> Path:
    """Walk up from this file until we find the ``config/`` directory."""
    current = Path(__file__).resolve().parent  # src/
    for ancestor in [current, current.parent, *current.parents]:
        if (ancestor / "config").is_dir():
            return ancestor
    raise FileNotFoundError(
        "Could not locate project root (looked for a 'config/' directory "
        f"starting from {current})"
    )


PROJECT_ROOT = _find_project_root()
CONFIG_DIR = PROJECT_ROOT / "config"


# ============================================================================
# Dot-notation wrapper
# ============================================================================

class ConfigNamespace:
    """Wraps a nested dict so values are accessible via dot notation.

    Supports attribute access, key access, iteration, ``in`` checks, and
    pretty-printing.  Nested dicts become nested ``ConfigNamespace`` objects;
    lists of dicts become lists of ``ConfigNamespace`` objects.

    Example::

        ns = ConfigNamespace({"a": {"b": 1}})
        assert ns.a.b == 1
        assert ns["a"]["b"] == 1
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        for key, value in data.items():
            setattr(self, key, self._wrap(value))

    # --- internal helpers ---------------------------------------------------

    @staticmethod
    def _wrap(value: Any) -> Any:
        """Recursively wrap dicts and lists of dicts."""
        if isinstance(value, dict):
            return ConfigNamespace(value)
        if isinstance(value, list):
            return [
                ConfigNamespace(item) if isinstance(item, dict) else item
                for item in value
            ]
        return value

    # --- public API ---------------------------------------------------------

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def __repr__(self) -> str:
        fields = ", ".join(f"{k}=..." for k in self.__dict__)
        return f"ConfigNamespace({fields})"

    def to_dict(self) -> Dict[str, Any]:
        """Convert back to a plain dict (useful for serialisation)."""
        result: Dict[str, Any] = {}
        for key, value in self.__dict__.items():
            if isinstance(value, ConfigNamespace):
                result[key] = value.to_dict()
            elif isinstance(value, list):
                result[key] = [
                    item.to_dict() if isinstance(item, ConfigNamespace) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result


# ============================================================================
# YAML loading helpers
# ============================================================================

def _load_yaml(filename: str) -> Dict[str, Any]:
    """Load a YAML file from the config directory.

    Raises ``FileNotFoundError`` with a helpful message if the file is
    missing, and ``ValueError`` if the file is empty or malformed.
    """
    filepath = CONFIG_DIR / filename
    if not filepath.exists():
        raise FileNotFoundError(
            f"Config file not found: {filepath}.  "
            f"Expected config files in {CONFIG_DIR}/"
        )
    with open(filepath, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(
            f"Config file {filepath} must contain a YAML mapping at the top "
            f"level, got {type(data).__name__}"
        )
    return data


# ============================================================================
# Validation
# ============================================================================

def _validate_leagues(data: Dict[str, Any]) -> None:
    """Ensure leagues.yaml has required keys for every league entry."""
    required_league_keys = {
        "name", "short_name", "country", "football_data_code",
        "fbref_league_id", "api_football_id", "is_active", "seasons",
    }
    leagues = data.get("leagues")
    if not leagues or not isinstance(leagues, list):
        raise ValueError(
            "leagues.yaml must contain a 'leagues' key with a list of "
            "league definitions"
        )
    for idx, league in enumerate(leagues):
        missing = required_league_keys - set(league.keys())
        if missing:
            raise ValueError(
                f"League #{idx} ({league.get('name', 'UNNAMED')}) is missing "
                f"required keys: {', '.join(sorted(missing))}"
            )
        if not league.get("seasons"):
            raise ValueError(
                f"League '{league['name']}' must define at least one season"
            )


def _validate_settings(data: Dict[str, Any]) -> None:
    """Ensure settings.yaml has the critical top-level sections."""
    required_sections = [
        "database", "features", "value_betting", "bankroll",
        "safety", "self_improvement",
    ]
    missing = [s for s in required_sections if s not in data]
    if missing:
        raise ValueError(
            f"settings.yaml is missing required sections: "
            f"{', '.join(missing)}"
        )

    # Validate specific critical values exist and have sane types
    _check_type(data, "value_betting.edge_threshold", float)
    _check_type(data, "bankroll.starting_amount", (int, float))
    _check_type(data, "bankroll.stake_percentage", float)
    _check_type(data, "safety.max_bet_percentage", float)
    _check_type(data, "self_improvement.recalibration.min_sample_size", int)
    _check_type(data, "self_improvement.adaptive_weights.min_sample_size", int)
    _check_type(data, "self_improvement.retrain.degradation_threshold", float)


def _validate_email(data: Dict[str, Any]) -> None:
    """Ensure email_config.yaml has SMTP settings and no hardcoded creds."""
    if "smtp" not in data:
        raise ValueError("email_config.yaml must contain an 'smtp' section")
    if "schedule" not in data:
        raise ValueError("email_config.yaml must contain a 'schedule' section")

    # Guard against someone accidentally pasting credentials into the YAML
    yaml_text = yaml.dump(data)
    for forbidden in ["password:", "app_password:", "secret:"]:
        # Allow env-var reference keys like app_password_env
        lines = yaml_text.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(forbidden) and "_env" not in stripped:
                raise ValueError(
                    f"email_config.yaml appears to contain a raw credential "
                    f"(found '{forbidden}').  Credentials must be stored in "
                    f".env and referenced via environment variable names."
                )


def _check_type(
    data: Dict[str, Any],
    dotpath: str,
    expected_type: type | tuple,
) -> None:
    """Traverse a dotpath into a nested dict and check the value type."""
    keys = dotpath.split(".")
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            raise ValueError(
                f"settings.yaml: missing required key '{dotpath}'"
            )
        current = current[key]
    if not isinstance(current, expected_type):
        raise ValueError(
            f"settings.yaml: '{dotpath}' must be {expected_type}, "
            f"got {type(current).__name__} ({current!r})"
        )


# ============================================================================
# Main Config class
# ============================================================================

class BetVectorConfig:
    """Central configuration object.

    Loads and validates all three YAML files, then exposes them as typed
    attributes:

    - ``config.leagues``  — list of ``ConfigNamespace`` league objects
    - ``config.settings`` — ``ConfigNamespace`` with dot-notation access
    - ``config.email``    — ``ConfigNamespace`` with email settings

    The ``settings`` namespace also provides top-level shortcuts for the most
    commonly accessed values (e.g., ``config.settings.edge_threshold``).
    """

    def __init__(self) -> None:
        self._loaded = False
        self.leagues: List[ConfigNamespace] = []
        self.settings: ConfigNamespace = ConfigNamespace({})
        self.email: ConfigNamespace = ConfigNamespace({})
        self.load()

    def load(self) -> None:
        """(Re)load all config files from disk.

        Safe to call multiple times — useful in tests or after editing YAML.
        """
        self._load_leagues()
        self._load_settings()
        self._load_email()
        self._loaded = True

    # --- private loaders ----------------------------------------------------

    def _load_leagues(self) -> None:
        data = _load_yaml("leagues.yaml")
        _validate_leagues(data)
        self.leagues = [
            ConfigNamespace(league) for league in data["leagues"]
        ]

    def _load_settings(self) -> None:
        data = _load_yaml("settings.yaml")
        _validate_settings(data)

        self.settings = ConfigNamespace(data)

        # Convenience shortcuts — the most-accessed values available directly
        # on config.settings without drilling into nested namespaces.
        # These mirror the column defaults in the users table (MP §6).
        self.settings.edge_threshold = data["value_betting"]["edge_threshold"]
        self.settings.starting_bankroll = data["bankroll"]["starting_amount"]
        self.settings.stake_percentage = data["bankroll"]["stake_percentage"]
        self.settings.kelly_fraction = data["bankroll"]["kelly_fraction"]
        self.settings.staking_method = data["bankroll"]["staking_method"]

    def _load_email(self) -> None:
        data = _load_yaml("email_config.yaml")
        _validate_email(data)
        self.email = ConfigNamespace(data)

    # --- helpers ------------------------------------------------------------

    def get_active_leagues(self) -> List[ConfigNamespace]:
        """Return only leagues where ``is_active`` is True."""
        return [lg for lg in self.leagues if lg.is_active]

    def get_database_url(self) -> str:
        """Build a SQLAlchemy connection URL.

        Resolution order (matches ``db.py._build_connection_url()``):
          1. ``DATABASE_URL`` env var — cloud deployment (GitHub Actions, Docker)
          2. Config file SQLite path — local development fallback

        Note: Streamlit secrets are handled separately in ``db.py`` because
        this config module is loaded before Streamlit is available.
        """
        import os
        database_url = os.environ.get("DATABASE_URL")
        if database_url:
            return database_url
        # Fall back to config file (local SQLite)
        db_path = self.settings.database.path
        # Resolve relative paths against the project root
        full_path = PROJECT_ROOT / db_path
        return f"sqlite:///{full_path}"

    def get_enum(self, enum_name: str) -> Optional[List[str]]:
        """Look up an enum list by name from settings.yaml ``enums`` section.

        Returns None if the enum doesn't exist (caller should raise if
        that's unexpected).
        """
        if hasattr(self.settings, "enums") and hasattr(self.settings.enums, enum_name):
            return getattr(self.settings.enums, enum_name)
        return None

    def __repr__(self) -> str:
        n_leagues = len(self.leagues)
        active = len(self.get_active_leagues())
        return (
            f"BetVectorConfig(leagues={n_leagues} ({active} active), "
            f"loaded={self._loaded})"
        )


# ============================================================================
# Singleton instance — import this
# ============================================================================

config = BetVectorConfig()
