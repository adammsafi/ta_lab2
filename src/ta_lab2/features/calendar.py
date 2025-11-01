# src/ta_lab2/features/calendar.py
from __future__ import annotations
import numpy as np
import pandas as pd

try:
    import astronomy as astro   # from astronomy-engine
    _HAS_ASTRONOMY = True
except Exception:
    _HAS_ASTRONOMY = False


def _session_bucket(hour: int) -> str:
    """
    Example bucketizer for trading-style sessions (UTC-based):
    - 01-08: 'pre'
    - 09-20: 'regular'
    - 21-24/00: 'after'
    Tweak to your venue/timezone as needed.
    """
    if 1 <= hour <= 8:
        return "pre"
    if 9 <= hour <= 20:
        return "regular"
    return "after"


def expand_datetime_features_inplace(
    df: pd.DataFrame,
    base_timestamp_col: str,
    prefix: str = None,
    *,
    to_utc: bool = True,
    add_moon: bool = True,
    us_week_start_sunday: bool = True
) -> None:
    if base_timestamp_col not in df.columns:
        print(f"Warning: Column '{base_timestamp_col}' not found. Skipping.")
        return

    dt = pd.to_datetime(df[base_timestamp_col], errors="coerce")

    # Normalize to UTC for deterministic astronomy calcs
    if getattr(dt.dt, "tz", None) is not None:
        if to_utc:
            dt = dt.dt.tz_convert("UTC")
    else:
        try:
            dt = dt.dt.tz_localize("UTC", nonexistent="NaT", ambiguous="NaT")
        except Exception:
            dt = dt.dt.tz_localize("UTC")

    if prefix is None:
        prefix = base_timestamp_col
    valid = dt.notna()

    # US vs ISO weekday numbering
    if us_week_start_sunday:
        # Sun=1..Sat=7
        dow_num = ((dt.dt.dayofweek + 1) % 7 + 1).astype("Int64")
        week_of_year = dt.dt.isocalendar().week.astype("Int64")  # still ISO for comparability
        iso_year = dt.dt.isocalendar().year.astype("Int64")
    else:
        # Mon=1..Sun=7 (ISO)
        dow_num = dt.dt.isocalendar().day.astype("Int64")
        week_of_year = dt.dt.isocalendar().week.astype("Int64")
        iso_year = dt.dt.isocalendar().year.astype("Int64")

    # Unix seconds
    unix_ns = dt.astype("int64")
    unix_ns = pd.Series(unix_ns, index=df.index).where(valid)
    unix_s  = (unix_ns // 10**9).astype("Int64")

    # Days in month and nth day of month
    # (via month boundaries difference)
    month_start = dt.dt.to_period("M").dt.start_time
    month_end   = dt.dt.to_period("M").dt.end_time
    # careful: end_time is end-of-month at 23:59:59; use normalize for date arith
    days_in_month = (month_end.dt.normalize() - month_start.dt.normalize()).dt.days.add(1).astype("Int64")
    nth_day_of_month = dt.dt.day.astype("Int64")

    # Week-of-month (1..5): 1st week = week number of first day baseline
    wom = (
        (dt.dt.day.add((dt.dt.to_period("M").dt.start_time.dt.dayofweek + 1) % 7) + 6) // 7
    ).astype("Int64")

    out = {
        f"{prefix}_date": dt.dt.date,
        f"{prefix}_time": dt.dt.time,

        f"{prefix}_year":   dt.dt.year.astype("Int64"),
        f"{prefix}_month":  dt.dt.month.astype("Int64"),
        f"{prefix}_day":    dt.dt.day.astype("Int64"),

        f"{prefix}_day_name": dt.dt.day_name(),
        f"{prefix}_day_of_week_num": dow_num,         # Sun=1..Sat=7 or Mon=1..Sun=7 (ISO)
        f"{prefix}_iso_year": iso_year,               # ISO year (useful around New Year)
        f"{prefix}_week_of_year": week_of_year,       # ISO weeks 1..53
        f"{prefix}_week_of_month": wom,               # 1..5 (approx, aligns well in practice)

        f"{prefix}_hour":   dt.dt.hour.astype("Int64"),
        f"{prefix}_minute": dt.dt.minute.astype("Int64"),
        f"{prefix}_second": dt.dt.second.astype("Int64"),

        f"{prefix}_unix": unix_s,

        f"{prefix}_quarter":   dt.dt.quarter.astype("Int64"),
        f"{prefix}_year_half": ((dt.dt.quarter - 1) // 2 + 1).astype("Int64"),

        # Boundary flags
        f"{prefix}_is_month_start": dt.dt.is_month_start.astype("Int8"),
        f"{prefix}_is_month_end":   dt.dt.is_month_end.astype("Int8"),
        f"{prefix}_is_quarter_start": dt.dt.is_quarter_start.astype("Int8"),
        f"{prefix}_is_quarter_end":   dt.dt.is_quarter_end.astype("Int8"),
        f"{prefix}_is_year_start":    dt.dt.is_year_start.astype("Int8"),
        f"{prefix}_is_year_end":      dt.dt.is_year_end.astype("Int8"),

        # Day-of-year and business-day flag (Mon–Fri, not holiday-aware)
        f"{prefix}_day_of_year": dt.dt.dayofyear.astype("Int64"),
        f"{prefix}_is_business_day": pd.Series(
            np.is_busday(dt.dt.date.astype("datetime64[D]"), weekmask='Mon Tue Wed Thu Fri'),
            index=df.index
        ).astype("Int8"),

        # Session bucket (example; adjust to your venue)
        f"{prefix}_session": dt.dt.hour.map(_session_bucket),
        f"{prefix}_days_in_month": days_in_month,
        f"{prefix}_nth_day_of_month": nth_day_of_month,
    }

    # Seasons (exact if astronomy present; else approx)
    def _season_boundaries(year: int):
        s = astro.Seasons(year)
        s_prev = astro.Seasons(year - 1)
        return dict(
            spring=s.mar_equinox.Utc().date(),
            summer=s.jun_solstice.Utc().date(),
            fall=s.sep_equinox.Utc().date(),
            winter=s.dec_solstice.Utc().date(),
            winter_prev=s_prev.dec_solstice.Utc().date(),
        )

    if _HAS_ASTRONOMY:
        cache: dict[int, dict[str, object]] = {}
        def _season_exact(ts: pd.Timestamp):
            if pd.isna(ts): return np.nan
            y = ts.year
            b = cache.get(y)
            if b is None:
                b = _season_boundaries(y)
                cache[y] = b
            d = ts.date()
            if b["spring"] <= d < b["summer"]: return "Spring"
            if b["summer"] <= d < b["fall"]:   return "Summer"
            if b["fall"]   <= d < b["winter"]: return "Fall"
            return "Winter"
        season_exact = dt.apply(_season_exact)
        out[f"{prefix}_season_exact"] = season_exact
    else:
        m = dt.dt.month; d = dt.dt.day
        conds = [
            ((m == 3) & (d >= 20)) | m.between(4, 5) | ((m == 6) & (d < 21)),
            ((m == 6) & (d >= 21)) | m.between(7, 8) | ((m == 9) & (d < 22)),
            ((m == 9) & (d >= 22)) | m.between(10, 11) | ((m == 12) & (d < 21)),
        ]
        out[f"{prefix}_season"] = pd.Series(
            np.select(conds, ["Spring","Summer","Fall"], default="Winter"),
            index=df.index
        ).where(valid)

    # Moon (noon UTC, via Time.Make)
    if add_moon and _HAS_ASTRONOMY:
        noon_utc = dt.dt.normalize() + pd.Timedelta(hours=12)
        def _moon_deg(ts_noon: pd.Timestamp):
            if pd.isna(ts_noon): return np.nan
            sec = ts_noon.second + ts_noon.microsecond / 1_000_000.0
            t = astro.Time.Make(int(ts_noon.year), int(ts_noon.month), int(ts_noon.day),
                                int(ts_noon.hour), int(ts_noon.minute), float(sec))
            return float(astro.MoonPhase(t))
        def _phase_name(a):
            if not np.isfinite(a): return np.nan
            a = a % 360.0
            def near(x): return abs((a - x + 180) % 360 - 180) <= 5
            if near(0):   return "New Moon"
            if near(90):  return "First Quarter"
            if near(180): return "Full Moon"
            if near(270): return "Last Quarter"
            if 0 < a < 90:    return "Waxing Crescent"
            if 90 < a < 180:  return "Waxing Gibbous"
            if 180 < a < 270: return "Waning Gibbous"
            return "Waning Crescent"
        def _illum(a):
            if not np.isfinite(a): return np.nan
            return (1.0 - np.cos(np.deg2rad(a))) / 2.0
        moon_deg = noon_utc.apply(_moon_deg)
        out[f"{prefix}_moon_phase_deg"]  = moon_deg
        out[f"{prefix}_moon_phase_name"] = moon_deg.apply(_phase_name)
        out[f"{prefix}_moon_illum_frac"] = moon_deg.apply(_illum)

    df[list(out.keys())] = pd.DataFrame(out, index=df.index)


def expand_multiple_timestamps(
    df: pd.DataFrame,
    cols: list[str],
    *,
    to_utc: bool = True,
    add_moon: bool = True,
    us_week_start_sunday: bool = True
) -> None:
    """
    Convenience wrapper to expand several timestamp columns at once,
    using each column name as its own prefix.
    """
    for c in cols:
        expand_datetime_features_inplace(
            df, base_timestamp_col=c, prefix=c,
            to_utc=to_utc, add_moon=add_moon,
            us_week_start_sunday=us_week_start_sunday
        )
