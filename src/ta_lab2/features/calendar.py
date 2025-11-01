# src/ta_lab2/features/calendar.py
"""
Calendar/date-time feature expansion utilities.

`expand_datetime_features_inplace(df, base_timestamp_col, prefix=None, *, to_utc=True, add_moon=True)`
- Parses timestamps (NaT-safe), normalizes to UTC (for deterministic astronomy).
- Adds a rich set of date/time parts, ISO week, day-of-year, business-day flag, etc.
- Optionally adds season and moon features (if `astronomy` package available).

`expand_multiple_timestamps(df, cols, *, to_utc=True, add_moon=False)`
- Convenience wrapper that expands several timestamp columns in one call.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# Optional astronomy support (exact seasonal bounds + moon phase)
_HAS_ASTRONOMY = False
try:  # pragma: no cover - optional dependency
    import astronomy as astro  # type: ignore
    _HAS_ASTRONOMY = True
except Exception:  # pragma: no cover - optional
    _HAS_ASTRONOMY = False


def expand_datetime_features_inplace(
    df: pd.DataFrame,
    base_timestamp_col: str,
    prefix: str | None = None,
    *,
    to_utc: bool = True,
    add_moon: bool = True,
) -> None:
    """
    One-call datetime feature expansion.

    Parameters
    ----------
    df : pd.DataFrame
    base_timestamp_col : str
        Column name of the timestamp to expand.
    prefix : str | None
        Prefix for generated columns. Defaults to `base_timestamp_col`.
    to_utc : bool
        If True, normalize timezone-aware timestamps to UTC and localize naive
        timestamps to UTC. Astronomy/season boundaries are computed in UTC.
    add_moon : bool
        If True and `astronomy` is available, adds moon phase features.

    Notes
    -----
    - NaT-safe: rows with unparseable timestamps will yield NA features.
    - Restores legacy fields:
        * `<prefix>_week_of_year` (ISO week)
        * `<prefix>_day_of_year`
    """
    if base_timestamp_col not in df.columns:
        print(f"Warning: Column '{base_timestamp_col}' not found. Skipping.")
        return

    # Parse
    dt = pd.to_datetime(df[base_timestamp_col], errors="coerce")

    # Normalize to UTC for deterministic season/moon
    if getattr(dt.dt, "tz", None) is not None:
        if to_utc:
            dt = dt.dt.tz_convert("UTC")
    else:
        # localize naive as UTC (NaT-safe)
        try:
            dt = dt.dt.tz_localize("UTC", nonexistent="NaT", ambiguous="NaT")
        except Exception:  # pandas < 2.2 fallback
            dt = dt.dt.tz_localize("UTC")

    if prefix is None:
        prefix = base_timestamp_col

    valid = dt.notna()

    # --- Base parts ---
    us_dow = ((dt.dt.dayofweek + 1) % 7 + 1).astype("Int64")  # Sun=1..Sat=7

    # unix seconds (preserve NaT -> <NA>)
    unix_ns = dt.view("int64")
    unix_ns = pd.Series(unix_ns, index=df.index).where(valid)
    unix_s = (unix_ns // 10**9).astype("Int64")

    # Month boundaries (tz drop warnings are harmless for derived features)
    month_start = dt.dt.to_period("M").dt.start_time
    month_end = dt.dt.to_period("M").dt.end_time

    # Business-day flag
    bd_array = np.full(len(df), np.nan, dtype="float64")
    if len(df) > 0:
        norm_days = dt.dt.normalize().values.astype("datetime64[D]")
        bd = np.is_busday(norm_days, weekmask="Mon Tue Wed Thu Fri")
        bd_array = bd.astype("float64")
    is_bus = pd.Series(bd_array, index=df.index).where(valid).astype("Int64")

    # ISO calendar parts for week-of-year
    iso = dt.dt.isocalendar()
    iso_week = iso.week.astype("Int64")

    out = {
        f"{prefix}_date": dt.dt.date,
        f"{prefix}_time": dt.dt.time,

        f"{prefix}_year":   dt.dt.year.astype("Int64"),
        f"{prefix}_month":  dt.dt.month.astype("Int64"),
        f"{prefix}_day":    dt.dt.day.astype("Int64"),

        f"{prefix}_day_name": dt.dt.day_name(),
        f"{prefix}_day_of_week_num": us_dow,  # Sun=1..Sat=7

        f"{prefix}_hour":   dt.dt.hour.astype("Int64"),
        f"{prefix}_minute": dt.dt.minute.astype("Int64"),
        f"{prefix}_second": dt.dt.second.astype("Int64"),

        f"{prefix}_unix": unix_s,

        f"{prefix}_quarter":   dt.dt.quarter.astype("Int64"),
        f"{prefix}_year_half": ((dt.dt.quarter - 1) // 2 + 1).astype("Int64"),

        # Legacy fields expected downstream/tests
        f"{prefix}_day_of_year": dt.dt.day_of_year.astype("Int64"),
        f"{prefix}_week_of_year": iso_week,

        # Convenience flags
        f"{prefix}_is_month_start": (dt == month_start).astype("Int64").where(valid),
        f"{prefix}_is_month_end":   (dt == month_end).astype("Int64").where(valid),
        f"{prefix}_is_business_day": is_bus,
    }

    # --- Seasons ---
    if _HAS_ASTRONOMY:
        _season_cache: dict[int, dict[str, pd.Timestamp]] = {}

        def _bounds(year: int):
            s = _season_cache.get(year)
            if s is None:
                sy = astro.Seasons(year)
                sy1 = astro.Seasons(year - 1)
                s = {
                    "spring":      sy.mar_equinox.Utc().date(),
                    "summer":      sy.jun_solstice.Utc().date(),
                    "fall":        sy.sep_equinox.Utc().date(),
                    "winter":      sy.dec_solstice.Utc().date(),
                    "winter_prev": sy1.dec_solstice.Utc().date(),
                }
                _season_cache[year] = s
            return s

        def _season_exact(ts: pd.Timestamp):
            if pd.isna(ts):
                return np.nan
            y = ts.year
            b = _bounds(y)
            d = ts.date()
            if b["spring"] <= d < b["summer"]:
                return "Spring"
            if b["summer"] <= d < b["fall"]:
                return "Summer"
            if b["fall"] <= d < b["winter"]:
                return "Fall"
            return "Winter"

        out[f"{prefix}_season_exact"] = dt.apply(_season_exact)
    else:
        # Approximate Northern Hemisphere rule
        m = dt.dt.month
        d = dt.dt.day
        conds = [
            ((m == 3) & (d >= 20)) | m.between(4, 5) | ((m == 6) & (d < 21)),
            ((m == 6) & (d >= 21)) | m.between(7, 8) | ((m == 9) & (d < 22)),
            ((m == 9) & (d >= 22)) | m.between(10, 11) | ((m == 12) & (d < 21)),
        ]
        out[f"{prefix}_season"] = pd.Series(
            np.select(conds, ["Spring", "Summer", "Fall"], default="Winter"),
            index=df.index,
        ).where(valid)

    # --- Moon (snap to noon UTC) ---
    if add_moon and _HAS_ASTRONOMY:
        noon_utc = dt.dt.normalize() + pd.Timedelta(hours=12)

        def _moon_deg(ts_noon: pd.Timestamp):
            if pd.isna(ts_noon):
                return np.nan
            sec = ts_noon.second + ts_noon.microsecond / 1_000_000.0
            t = astro.Time.Make(
                int(ts_noon.year), int(ts_noon.month), int(ts_noon.day),
                int(ts_noon.hour), int(ts_noon.minute), float(sec),
            )
            return float(astro.MoonPhase(t))

        def _phase_name(a):
            if not np.isfinite(a):
                return np.nan
            a = a % 360.0

            def near(x):  # within ±5°
                return abs((a - x + 180) % 360 - 180) <= 5

            if near(0):   return "New Moon"
            if near(90):  return "First Quarter"
            if near(180): return "Full Moon"
            if near(270): return "Last Quarter"
            if 0   < a < 90:   return "Waxing Crescent"
            if 90  < a < 180:  return "Waxing Gibbous"
            if 180 < a < 270:  return "Waning Gibbous"
            return "Waning Crescent"

        def _illum(a):
            if not np.isfinite(a):
                return np.nan
            # (1 - cos(theta)) / 2 maps 0->0 (new) and 180->1 (full)
            return (1.0 - np.cos(np.deg2rad(a))) / 2.0

        moon_deg = noon_utc.apply(_moon_deg)
        out[f"{prefix}_moon_phase_deg"]  = moon_deg
        out[f"{prefix}_moon_phase_name"] = moon_deg.apply(_phase_name)
        out[f"{prefix}_moon_illum_frac"] = moon_deg.apply(_illum)

    # --- Assign back ---
    df[list(out.keys())] = pd.DataFrame(out, index=df.index)


def expand_multiple_timestamps(
    df: pd.DataFrame,
    cols: Iterable[str] | Sequence[str],
    *,
    to_utc: bool = True,
    add_moon: bool = False,
) -> None:
    """
    Expand several timestamp columns in one call (legacy test helper).
    """
    for c in cols:
        if c in df.columns:
            expand_datetime_features_inplace(
                df, base_timestamp_col=c, prefix=c, to_utc=to_utc, add_moon=add_moon
            )
        else:
            print(f"Warning: Column '{c}' not found. Skipping.")


__all__ = [
    "expand_datetime_features_inplace",
    "expand_multiple_timestamps",
]
