# config.py (at repo root)
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml

@dataclass
class Settings:
    # required
    data_csv: str
    # optional
    out_dir: str = "out"
    ema_windows: list[int] = field(default_factory=lambda: [21, 50, 100])
    resample: dict[str, Any] = field(default_factory=lambda: {"weekly": "W-SUN", "monthly": "MS"})
    indicators: dict[str, Any] | None = None
    correlations: dict[str, Any] | None = None

def project_root(start: str | Path | None = None) -> Path:
    """Walk up from 'start' (or this file) until we find a folder containing pyproject.toml."""
    cur = Path(start or __file__).resolve()
    for p in [cur, *cur.parents]:
        if (p / "pyproject.toml").exists():
            return p
    # fallback: repo root is parent of this file
    return Path(__file__).resolve().parent

def load_settings(yaml_path: str | Path) -> Settings:
    """Load YAML into Settings, then normalize relative paths against the project root."""
    root = project_root()
    p = (root / yaml_path).resolve() if not Path(yaml_path).is_absolute() else Path(yaml_path)
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    # Build Settings
    s = Settings(**data)

    # Normalize paths (make absolute, anchored to repo root)
    s.data_csv = str((root / s.data_csv).resolve()) if not Path(s.data_csv).is_absolute() else s.data_csv
    s.out_dir  = str((root / s.out_dir).resolve())  if not Path(s.out_dir).is_absolute()  else s.out_dir

    return s
