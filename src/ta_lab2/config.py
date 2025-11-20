# src/ta_lab2/config.py
"""
Shim so callers can do:

    from ta_lab2.config import load_settings, project_root, Settings, load_local_env, TARGET_DB_URL

while the "real" config lives at the project root (./config.py).

This module:

- Locates the project root (two levels above src/ta_lab2).
- Imports the root-level config.py if present and re-exports:
    - Settings
    - load_settings
    - project_root
    - load_local_env
- Loads environment variables from db_config.env (if present).
- Exposes TARGET_DB_URL, taken from:
    1) environment (after loading db_config.env), or
    2) root config.TARGET_DB_URL if defined.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Locate project root and import root config.py (if it exists)
# ---------------------------------------------------------------------------

# src/ta_lab2/config.py -> src/ta_lab2 -> src -> project_root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Make sure project root is on sys.path so `import config` finds the root file
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import config as _root_cfg  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - very defensive
    _root_cfg = None


# ---------------------------------------------------------------------------
# Re-export Settings, load_settings, project_root, load_local_env
# ---------------------------------------------------------------------------

# Settings
if _root_cfg is not None and hasattr(_root_cfg, "Settings"):
    Settings = _root_cfg.Settings  # type: ignore[assignment]
else:
    # Fallback minimal Settings class so imports don't explode in odd environments
    class Settings:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)


# load_settings
if _root_cfg is not None and hasattr(_root_cfg, "load_settings"):
    def load_settings(*args: Any, **kwargs: Any) -> Settings:  # type: ignore[no-redef]
        """
        Thin wrapper around root-level config.load_settings.

        Accepts arbitrary positional/keyword arguments so callers can do either:

            load_settings()
            load_settings(path_to_yaml)

        without this shim causing a TypeError.
        """
        return _root_cfg.load_settings(*args, **kwargs)  # type: ignore[no-any-return]
else:
    def load_settings(*args: Any, **kwargs: Any) -> Settings:  # type: ignore[no-redef]
        """
        Fallback: ignore any arguments and return an empty Settings
        instance so imports still succeed in minimal environments.
        """
        return Settings()  # empty settings as a safe default


# project_root
if _root_cfg is not None and hasattr(_root_cfg, "project_root"):
    # Use the project_root symbol defined in the root config if present
    project_root = _root_cfg.project_root  # type: ignore[assignment]
else:
    # Simple function returning the resolved project root
    def project_root() -> Path:  # type: ignore[no-redef]
        return _PROJECT_ROOT


# load_local_env
if _root_cfg is not None and hasattr(_root_cfg, "load_local_env"):
    load_local_env = _root_cfg.load_local_env  # type: ignore[assignment]
else:
    def load_local_env(env_filename: str = "db_config.env") -> None:  # type: ignore[no-redef]
        """
        Minimal fallback: load KEY=VALUE lines from an env file at project root.
        Values are only set if the key is not already in os.environ.
        """
        env_path = _PROJECT_ROOT / env_filename
        if not env_path.exists():
            return

        for raw_line in env_path.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Load env + expose TARGET_DB_URL
# ---------------------------------------------------------------------------

# Load env file (if any) before we compute TARGET_DB_URL
try:
    load_local_env()  # type: ignore[misc]
except Exception:
    # Fail-soft; we still allow pure-env or root-config only
    pass

# Prefer explicit TARGET_DB_URL / DB_URL, but fall back to MARKETDATA_DB_URL.
_env_db_url = (
    os.environ.get("TARGET_DB_URL")
    or os.environ.get("DB_URL")
    or os.environ.get("MARKETDATA_DB_URL")
)

_cfg_db_url = getattr(_root_cfg, "TARGET_DB_URL", None) if _root_cfg is not None else None

# This is what ema_multi_timeframe.py (and your stats scripts) import
TARGET_DB_URL: Optional[str] = _env_db_url or _cfg_db_url

__all__ = [
    "Settings",
    "load_settings",
    "project_root",
    "load_local_env",
    "TARGET_DB_URL",
]
