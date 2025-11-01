# src/ta_lab2/config.py
"""
Thin shim so callers can do:
    from ta_lab2.config import load_settings, project_root, Settings
while the real loader lives at the repo root (config.py).

This allows imports to stay consistent inside the ta_lab2 package,
even though config.py actually resides at the project root.
"""

from importlib import import_module as _imp

# Dynamically import the root-level config.py module
_cfg = _imp("config")

# Re-export key symbols for compatibility
load_settings = _cfg.load_settings
project_root = _cfg.project_root
Settings = _cfg.Settings  # type: ignore[attr-defined]

# Optional: expose all root-level names if needed
__all__ = ["load_settings", "project_root", "Settings"]
