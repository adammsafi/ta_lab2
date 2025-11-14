# src/ta_lab2/config.py
"""
Shim so callers can do:
    from ta_lab2.config import load_settings, project_root, Settings
while the real loader lives at the project root (./config.py).

We explicitly add the project root to sys.path so that importing this module
works even when Python resolves from inside the installed package path.

This module also provides a small helper, `load_local_env()`, which loads
KEY=VALUE pairs from a local env file (e.g. db_config.env) in the project root
and injects them into os.environ if they are not already set.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from importlib import import_module as _imp

# This file lives at <repo>/src/ta_lab2/config.py
# -> project root is two parents above: <repo>
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Import the real root-level config.py
_cfg = _imp("config")

# Re-export key symbols from the root config module
load_settings = _cfg.load_settings
project_root = _cfg.project_root
Settings = _cfg.Settings  # type: ignore[attr-defined]


def load_local_env(filename: str = "db_config.env") -> None:
    """
    Load simple KEY=VALUE pairs from a local env file in the project root.

    This is intended for local secrets like database URLs that should not be
    committed to version control. It only sets variables that are not already
    present in os.environ.

    Expected format (one per line):
        KEY=VALUE
        # comments and blank lines are ignored

    Parameters
    ----------
    filename :
        Name of the env file in the project root. Defaults to ``db_config.env``.
    """
    path = _PROJECT_ROOT / filename
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        key, sep, value = line.partition("=")
        if not sep:
            # Not a KEY=VALUE line; skip it.
            continue

        key = key.strip()
        value = value.strip()

        if not key:
            continue

        # Do not override existing environment variables.
        if key not in os.environ:
            os.environ[key] = value


__all__ = ["load_settings", "project_root", "Settings", "load_local_env"]
