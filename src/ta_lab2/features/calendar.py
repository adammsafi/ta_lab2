
import numpy as np
import pandas as pd

try:
    import astronomy as astro   # from astronomy-engine
    _HAS_ASTRONOMY = True
except Exception:
    _HAS_ASTRONOMY = False

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

    # Day-of-week numbering
    if us_week_start_sunday:
        dow_num = ((dt.dt.dayofweek + 1) % 7 + 1).astype("Int64")   # Sun=1..Sat=7
    else:
        dow_num = dt.dt.isocalendar().day.astype("Int64")           # Mon=1..Sun=7

    unix_ns = dt.astype("int64")
    unix_ns = pd.Series(unix_ns, index=df.index).where(valid)
    unix_s  = (unix_ns // 10**9).astype("Int64")

    out = {
        f"{prefix}_date": dt.dt.date,
        f"{prefix}_time": dt.dt.time,
        f"{prefix}_year": dt.dt.year.astype("Int64"),
        f"{prefix}_month": dt.dt.month.astype("Int64"),
        f"{prefix}_day": dt.dt.day.astype("Int64"),
        f"{prefix}_day_name": dt.dt.day_name(),
        f"{prefix}_day_of_week_num": dow_num,
        f"{prefix}_hour": dt.dt.hour.astype("Int64"),
        f"{prefix}_minute": dt.dt.minute.astype("Int64"),
        f"{prefix}_second": dt.dt.second.astype("Int64"),
        f"{prefix}_unix": unix_s,
        f"{prefix}_quarter": dt.dt.quarter.astype("Int64"),
        f"{prefix}_year_half": ((dt.dt.quarter - 1) // 2 + 1).astype("Int64"),
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
        cache = {}
        def _season_exact(ts: pd.Timestamp):
            if pd.isna(ts): return np.nan
            y = ts.year
            if y not in cache:
                cache[y] = _season_boundaries(y)
            b = cache[y]; d = ts.date()
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
