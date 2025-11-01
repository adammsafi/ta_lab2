from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import yaml

@dataclass
class Settings:
    data_csv: str
    out_dir: str = "out"
    ema_windows: list[int] = field(default_factory=lambda: [21, 50, 100])
    resample: dict = field(default_factory=lambda: {"weekly": "W-SUN", "monthly": "MS"})

def load_settings(path: str | Path) -> Settings:
    p = Path(path)
    data = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Settings(**data)

def project_root(start: str | Path | None = None) -> Path:
    # walk up until we find pyproject.toml
    cur = Path(start or __file__).resolve()
    for ancestor in [cur, *cur.parents]:
        if (ancestor / "pyproject.toml").exists():
            return ancestor
    return cur  # fallback
