# config.py
"""
Central configuration loader for ta_lab2.

- Reads config/default.yaml (or any YAML path)
- Normalizes relative paths to project root
- Converts nested mappings into typed dataclasses
- Supports safe forward-compatibility (unknown keys ignored)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os
import yaml


# -----------------------------
# Small, typed sub-configs
# -----------------------------
@dataclass
class CalendarSettings:
    """Calendar & seasonality feature options."""
    expand_columns: list[str] = field(default_factory=lambda: ["timestamp"])
    add_moon: bool = True
    us_week_start_sunday: bool = True


@dataclass
class TrendSettings:
    """Slope-based trend labeling settings."""
    window: int = 21
    mode: str = "flat_zone"      # "binary" | "three_state" | "flat_zone"
    flat_thresh: float = 0.0     # 0 => auto percentile threshold


@dataclass
class SegmentsSettings:
    """Regime segmentation parameters."""
    price_col: str = "close"
    state_col: str = "trend_state"


@dataclass
class VolRealizedSettings:
    """Range-based (realized) volatility estimators."""
    estimators: list[str] = field(
        default_factory=lambda: ["parkinson", "rogers_satchell", "garman_klass", "atr"]
    )
    windows: list[int] = field(default_factory=lambda: [10, 21, 50])


@dataclass
class VolHistoricalSettings:
    """Return-based (historical) volatility parameters."""
    modes: list[str] = field(default_factory=lambda: ["log", "pct"])
    windows: list[int] = field(default_factory=lambda: [10, 21, 50])
    annualize: bool = True


@dataclass
class VolatilitySettings:
    """Combined realized + historical volatility settings."""
    realized: VolRealizedSettings = field(default_factory=VolRealizedSettings)
    historical: VolHistoricalSettings = field(default_factory=VolHistoricalSettings)


@dataclass
class PipelineSettings:
    """Global pipeline options."""
    resample: str | None = None           # e.g., "1H", "1D"
    returns_modes: list[str] = field(default_factory=lambda: ["log", "pct"])
    returns_windows: list[int] = field(default_factory=lambda: [10, 21, 50])


# -----------------------------
# Top-level Settings
# -----------------------------
@dataclass
class Settings:
    """
    Root configuration object for ta_lab2.
    This dataclass holds everything parsed from YAML.
    """

    # Required
    data_csv: str

    # Optional
    out_dir: str = "artifacts"
    ema_windows: list[int] = field(default_factory=lambda: [21, 50, 100, 200])

    # Nested groups (dictionaries or dataclasses)
    indicators: dict[str, Any] | None = None
    correlations: dict[str, Any] | None = None
    volatility: VolatilitySettings = field(default_factory=VolatilitySettings)
    calendar: CalendarSettings = field(default_factory=CalendarSettings)
    trend: TrendSettings = field(default_factory=TrendSettings)
    segments: SegmentsSettings = field(default_factory=SegmentsSettings)
    pipeline: PipelineSettings = field(default_factory=PipelineSettings)


# -----------------------------
# Helpers
# -----------------------------
def project_root(start: str | Path | None = None) -> Path:
    """
    Walk upward from 'start' (or this file) until a folder containing pyproject.toml is found.
    """
    cur = Path(start or __file__).resolve()
    for p in [cur, *cur.parents]:
        if (p / "pyproject.toml").exists():
            return p
    return Path(__file__).resolve().parent


def _as(obj: Any, cls: Any):
    """
    Minimal recursive 'constructor' to turn nested dicts into dataclass instances.
    Ignores unknown keys so YAML can be slightly ahead of code.
    """
    if obj is None or isinstance(obj, cls):
        return obj if obj is not None else cls()
    if isinstance(obj, dict):
        hints = {f.name for f in cls.__dataclass_fields__.values()}
        kwargs = {k: v for k, v in obj.items() if k in hints}
        for name, field_info in cls.__dataclass_fields__.items():
            typ = field_info.type
            if isinstance(kwargs.get(name), dict) and hasattr(typ, "__dataclass_fields__"):
                kwargs[name] = _as(kwargs[name], typ)
        return cls(**kwargs)
    return cls()


def load_settings(yaml_path: str | Path = "config/default.yaml") -> Settings:
    """
    Load YAML into Settings, normalize paths to project root,
    and coerce nested mappings into typed dataclasses.
    Also merges environment overrides if set (DATA_CSV, OUT_DIR).

    Gracefully accepts either 'config/default.yaml' or 'configs/default.yaml'.
    """
    root = project_root()
    yml = Path(yaml_path)
    p = (root / yml).resolve() if not yml.is_absolute() else yml

    if not p.exists():
        # Try swapping 'configs' <-> 'config'
        parts = list(yml.parts)
        if "configs" in parts:
            parts[parts.index("configs")] = "config"
        elif "config" in parts:
            parts[parts.index("config")] = "configs"
        alt = (root / Path(*parts)).resolve()
        if alt.exists():
            p = alt
        else:
            raise FileNotFoundError(f"Configuration file not found: {p}")

    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

    # --- Environment variable overrides ---
    if os.getenv("DATA_CSV"):
        data["data_csv"] = os.getenv("DATA_CSV")
    if os.getenv("OUT_DIR"):
        data["out_dir"] = os.getenv("OUT_DIR")

    # --- Top-level scalars ---
    data_csv = data.get("data_csv")
    if not data_csv:
        raise ValueError("`data_csv` is required in config/default.yaml")

    out_dir = data.get("out_dir", "artifacts")
    ema_windows = data.get("ema_windows", [21, 50, 100, 200])
    indicators = data.get("indicators")
    correlations = data.get("correlations")

    # --- Structured sections ---
    volatility = _as(data.get("volatility"), VolatilitySettings)
    calendar = _as(data.get("calendar"), CalendarSettings)
    trend = _as(data.get("trend"), TrendSettings)
    segments = _as(data.get("segments"), SegmentsSettings)
    pipeline = _as(data.get("pipeline"), PipelineSettings)

    # --- Build Settings object ---
    settings = Settings(
        data_csv=str(data_csv),
        out_dir=str(out_dir),
        ema_windows=list(ema_windows),
        indicators=indicators,
        correlations=correlations,
        volatility=volatility,
        calendar=calendar,
        trend=trend,
        segments=segments,
        pipeline=pipeline,
    )

    # --- Normalize paths ---
    dc = Path(settings.data_csv)
    settings.data_csv = str((root / dc).resolve()) if not dc.is_absolute() else str(dc)
    od = Path(settings.out_dir)
    settings.out_dir = str((root / od).resolve()) if not od.is_absolute() else str(od)
    return settings


def preview_settings(settings: Settings) -> None:
    """
    Pretty-print a summary of the current config for debugging / CLI startup.
    """
    import pprint
    print("=== ta_lab2 Configuration ===")
    flat = {
        "data_csv": settings.data_csv,
        "out_dir": settings.out_dir,
        "ema_windows": settings.ema_windows,
        "returns_modes": settings.pipeline.returns_modes,
        "returns_windows": settings.pipeline.returns_windows,
    }
    pprint.pprint(flat)
    print("Nested groups:")
    for grp in ["volatility", "calendar", "trend", "segments"]:
        print(f"  - {grp}: {getattr(settings, grp)}")
