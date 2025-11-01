# src/ta_lab2/config.py
"""
Shim so callers can do:
    from ta_lab2.config import load_settings, project_root, Settings
while the real loader lives at the project root (./config.py).

We explicitly add the project root to sys.path so that importing this module
works even when Python resolves from inside the installed package path.
"""

from __future__ import annotations
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

# Re-export key symbols
load_settings = _cfg.load_settings
project_root = _cfg.project_root
Settings = _cfg.Settings  # type: ignore[attr-defined]

__all__ = ["load_settings", "project_root", "Settings"]