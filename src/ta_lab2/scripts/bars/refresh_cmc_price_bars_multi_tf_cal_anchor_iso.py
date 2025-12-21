from __future__ import annotations
"""
# ======================================================================================
# refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py
#
# ISO calendar-ANCHORED price bars builder (append-only DAILY SNAPSHOTS):
#   public.cmc_price_bars_multi_tf_cal_anchor_iso
# from daily source:
#   public.cmc_price_histories7
#
# UPDATED SEMANTICS (Append-only daily snapshots + incremental),
# matching your anchored snapshot refactor pattern.
#
# TF SELECTION (dim_timeframe)
# ----------------------------
# We build a combined "calendar-anchored" set with ISO semantics for weeks:
#
#   A) ISO anchored weeks:
#        1W_CAL_ANCHOR_ISO, 2W_CAL_ANCHOR_ISO, ...
#      selected by:
#        alignment_type      = 'calendar'
#        roll_policy         = 'calendar_anchor'
#        allow_partial_start = TRUE
#        allow_partial_end   = TRUE
#        base_unit           = 'W'
#        calendar_scheme     = 'ISO'
#        tf LIKE '%_CAL_ANCHOR_ISO'
#
#   B) Anchored calendar months and years (NOT scheme-specific):
#        1M_CAL_ANCHOR, 2M_CAL_ANCHOR, 3M_CAL_ANCHOR, 6M_CAL_ANCHOR, 12M_CAL_ANCHOR, ...
#        1Y_CAL_ANCHOR, 2Y_CAL_ANCHOR, 3Y_CAL_ANCHOR, ... 20Y_CAL_ANCHOR
#      selected by:
#        alignment_type      = 'calendar'
#        roll_policy         = 'calendar_anchor'
#        allow_partial_start = TRUE
#        allow_partial_end   = TRUE
#        base_unit IN ('M','Y')
#        tf LIKE '%_CAL_ANCHOR%'
#
# This reflects your dim_timeframe design:
#   - Weeks are ISO-specific and explicitly labeled
#   - Months/years are globally calendar-anchored (no US/ISO suffix needed)
#
# OUTPUT SEMANTICS
# ----------------
# 1) Bars are emitted as APPEND-ONLY DAILY SNAPSHOTS per (id, tf, bar_seq, time_close):
#      - The same (id, tf, bar_seq) appears on multiple days while a window is forming.
#      - Each day produces a new snapshot row with a different time_close.
#      - Canonical window-close snapshot:
#          is_partial_end = FALSE (on the scheduled anchored window end-day)
#      - In-progress snapshots:
#          is_partial_end = TRUE
#
# 2) Anchored (fixed-endpoint) window definitions (NOT data-aligned):
#      - Weeks: ISO weeks (Monday–Sunday), close on Sunday.
#      - N-week windows: grouped on a deterministic global grid using
#          REF_MONDAY_ISO = 1970-01-05
#      - Months:
#          N-month windows grouped deterministically within the calendar year:
#            3M  => quarters (Jan–Mar, Apr–Jun, ...)
#            6M  => half-years (Jan–Jun, Jul–Dec)
#            12M => calendar year
#      - Years:
#          N-year windows grouped deterministically on calendar year boundaries.
#
# 3) Partial bars are allowed (both ends), but remain anchored:
#      - Partial START:
#          If data begins after the anchored window start, the first bar is partial-start:
#            bar_start_effective = max(window_start, daily_min_day)
#            is_partial_start = TRUE only for that first intersecting window.
#      - Partial END:
#          While the anchored window is still forming (today < window_end),
#          snapshots are partial-end.
#          If data ends mid-window, the last available snapshot days are also partial-end.
#
# 4) tf_days reflects the TRUE number of calendar days in the underlying anchored window:
#      tf_days = (window_end - window_start) + 1
#    This value is invariant for the window and does not change for partial-start bars.
#
# 5) Missing-days detection + breakdown:
#      For each snapshot day, expected local dates are:
#        [bar_start_effective, snapshot_day]
#      We compute:
#        - count_days
#        - count_days_remaining
#        - count_missing_days (with start / interior / end breakdown)
#        - missing_days_where
#      is_missing_days = TRUE iff count_missing_days > 0
#      Optional strict mode: --fail-on-internal-gaps
#
# 6) Incremental refresh semantics:
#      - Backfill-aware:
#          If daily_min_seen moves earlier than state.daily_min_seen => REBUILD (id, tf)
#      - Forward append-only:
#          New daily closes after last_time_close => APPEND snapshots only
#
#      Carry-forward rule:
#        Carry-forward aggregates are allowed ONLY if:
#          - same bar_seq
#          - last snapshot day == yesterday
#          - AND prior snapshot has is_missing_days = FALSE
#
# 7) State table:
#      public.cmc_price_bars_multi_tf_cal_anchor_iso_state stores per (id, tf):
#        tz,
#        daily_min_seen,
#        daily_max_seen,
#        last_bar_seq,
#        last_time_close,
#        updated_at
#
# IMPORTANT: STRICT
"""

import argparse
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# =============================================================================
# CONFIG
# =============================================================================

DEFAULT_TZ = "America/New_York"
DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_iso"
DEFAULT_STATE_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_iso_state"

# Global reference for anchored N-week grouping (ISO Monday)
REF_MONDAY_ISO = date(1970, 1, 5)

REQUIRED_DAILY_COLS = ["open", "high", "low", "close", "volume", "market_cap", "timehigh", "timelow"]


# =============================================================================
# DB helpers
# =============================================================================

def resolve_db_url(db_url: str | None) -> str:
    if db_url and db_url.strip():
        print("[bars_anchor_iso] Using DB URL from --db-url arg.")
        return db_url.strip()

    env_url = os.getenv("TARGET_DB_URL")
    if not env_url:
        raise SystemExit("No DB URL provided. Set TARGET_DB_URL env var or pass --db-url.")
    print("[bars_anchor_iso] Using DB URL from TARGET_DB_URL env.")
    return env_url.strip()


def get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def load_all_ids(db_url: str, daily_table: str) -> list[int]:
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(text(f"SELECT DISTINCT id FROM {daily_table} ORDER BY id;")).fetchall()
    return [int(r[0]) for r in rows]


def parse_ids(values: Sequence[str], db_url: str, daily_table: str) -> list[int]:
    if len(values) == 1 and values[0].strip().lower() == "all":
        ids = load_all_ids(db_url, daily_table)
        print(f"[bars_anchor_iso] Loaded ALL ids from {daily_table}: {len(ids)}")
        return ids

    out: list[int] = []
    for v in values:
        for part in v.split(","):
            part = part.strip()
            if part:
                out.append(int(part))

    # dedupe keep order
    seen: set[int] = set()
    ids2: list[int] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            ids2.append(x)
    return ids2


def ensure_state_table(db_url: str, state_table: str) -> None:
    eng = get_engine(db_url)
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {state_table} (
      id               integer      NOT NULL,
      tf               text         NOT NULL,
      tz               text         NOT NULL,
      daily_min_seen   timestamptz  NULL,
      daily_max_seen   timestamptz  NULL,
      last_bar_seq     integer      NULL,
      last_time_close  timestamptz  NULL,
      updated_at       timestamptz  NOT NULL DEFAULT now(),
      PRIMARY KEY (id, tf)
    );
    """
    with eng.begin() as conn:
        conn.execute(text(ddl))


def load_state(db_url: str, state_table: str, ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()

    sql = text(f"""
        SELECT id, tf, tz, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at
        FROM {state_table}
        WHERE id = ANY(:ids);
    """)

    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": ids})

    if df.empty:
        return df

    df["daily_min_seen"] = pd.to_datetime(df["daily_min_seen"], utc=True)
    df["daily_max_seen"] = pd.to_datetime(df["daily_max_seen"], utc=True)
    df["last_time_close"] = pd.to_datetime(df["last_time_close"], utc=True)
    return df


def upsert_state(db_url: str, state_table: str, rows: list[dict]) -> None:
    if not rows:
        return
    sql = text(f"""
      INSERT INTO {state_table} (id, tf, tz, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at)
      VALUES (:id, :tf, :tz, :daily_min_seen, :daily_max_seen, :last_bar_seq, :last_time_close, now())
      ON CONFLICT (id, tf) DO UPDATE SET
        tz              = EXCLUDED.tz,
        daily_min_seen  = EXCLUDED.daily_min_seen,
        daily_max_seen  = EXCLUDED.daily_max_seen,
        last_bar_seq    = EXCLUDED.last_bar_seq,
        last_time_close = EXCLUDED.last_time_close,
        updated_at      = now();
    """)
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, rows)


def load_daily_min_max(db_url: str, daily_table: str, ids: list[int]) -> pd.DataFrame:
    if not ids:
        return pd.DataFrame()
    sql = text(f"""
      SELECT id, MIN("timestamp") AS daily_min_ts, MAX("timestamp") AS daily_max_ts, COUNT(*) AS n_rows
      FROM {daily_table}
      WHERE id = ANY(:ids)
      GROUP BY id
      ORDER BY id;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params={"ids": ids})
    if df.empty:
        return df
    df["daily_min_ts"] = pd.to_datetime(df["daily_min_ts"], utc=True)
    df["daily_max_ts"] = pd.to_datetime(df["daily_max_ts"], utc=True)
    df["n_rows"] = df["n_rows"].astype(np.int64)
    return df


def _validate_daily_required_cols(df: pd.DataFrame, *, id_: int) -> None:
    if df.empty:
        return
    missing_cols = [c for c in REQUIRED_DAILY_COLS if c not in df.columns]
    if missing_cols:
        raise ValueError(f"[bars_anchor_iso] Daily frame missing required columns: {missing_cols}")

    bad = df[REQUIRED_DAILY_COLS].isna().any(axis=1)
    if bad.any():
        ex = df.loc[bad, ["id", "ts"] + REQUIRED_DAILY_COLS].head(8)
        raise ValueError(
            f"[bars_anchor_iso] NULLs in required daily columns for id={id_}. "
            f"Examples:\n{ex.to_string(index=False)}"
        )


def load_daily_prices_for_id(
    *,
    db_url: str,
    daily_table: str,
    id_: int,
    ts_start: pd.Timestamp | None = None,
) -> pd.DataFrame:
    if ts_start is None:
        where = 'WHERE id = :id'
        params = {"id": int(id_)}
    else:
        where = 'WHERE id = :id AND "timestamp" >= :ts_start'
        params = {"id": int(id_), "ts_start": ts_start}

    sql = text(f"""
      SELECT
        id,
        "timestamp" AS ts,
        timehigh,
        timelow,
        open,
        high,
        low,
        close,
        volume,
        marketcap AS market_cap
      FROM {daily_table}
      {where}
      ORDER BY "timestamp";
    """)

    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["timehigh"] = pd.to_datetime(df["timehigh"], utc=True)
    df["timelow"] = pd.to_datetime(df["timelow"], utc=True)

    _validate_daily_required_cols(df, id_=int(id_))
    return df


def delete_bars_for_id_tf(db_url: str, bars_table: str, id_: int, tf: str) -> None:
    sql = text(f"DELETE FROM {bars_table} WHERE id = :id AND tf = :tf;")
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, {"id": int(id_), "tf": tf})


def load_last_snapshot_info_for_id_tfs(
    db_url: str,
    bars_table: str,
    id_: int,
    tfs: list[str],
) -> dict[str, dict]:
    """
    Latest snapshot row per tf for this id.
    We order by time_close DESC because time_close evolves daily for snapshots.
    """
    if not tfs:
        return {}

    sql = text(f"""
      SELECT DISTINCT ON (tf)
        tf,
        bar_seq AS last_bar_seq,
        time_close AS last_time_close
      FROM {bars_table}
      WHERE id = :id AND tf = ANY(:tfs)
      ORDER BY tf, time_close DESC;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql, {"id": int(id_), "tfs": list(tfs)}).mappings().all()

    out: dict[str, dict] = {}
    for r in rows:
        tf = str(r["tf"])
        out[tf] = {
            "last_bar_seq": int(r["last_bar_seq"]),
            "last_time_close": pd.to_datetime(r["last_time_close"], utc=True),
        }
    return out


def load_last_snapshot_row(db_url: str, bars_table: str, id_: int, tf: str) -> dict | None:
    sql = text(f"""
      SELECT *
      FROM {bars_table}
      WHERE id = :id AND tf = :tf
      ORDER BY time_close DESC
      LIMIT 1;
    """)
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(sql, {"id": int(id_), "tf": tf}).mappings().first()
    return dict(row) if row else None


# =============================================================================
# dim_timeframe-driven window specs
# =============================================================================

@dataclass(frozen=True)
class AnchorSpec:
    n: int
    unit: str  # 'W','M','Y'
    tf: str


from sqlalchemy import text

def load_anchor_specs_from_dim_timeframe(db_url: str) -> list[AnchorSpec]:
    """
    Selection policy (matches the pasted script #1):
      - Weeks: ISO calendar-ANCHORED weeks only
          tf LIKE '%_CAL_ANCHOR_ISO' AND base_unit='W' AND calendar_scheme='ISO'
      - Months/Years: ALL anchored months + anchored years (no ISO suffix required)
          tf LIKE '%_CAL_ANCHOR%' AND base_unit IN ('M','Y')

    Common constraints:
      - alignment_type      = 'calendar'
      - roll_policy         = 'calendar_anchor'
      - allow_partial_start = TRUE
      - allow_partial_end   = TRUE
      - base_unit IN ('W','M','Y')
    """
    sql = text(r"""
        SELECT tf, base_unit, tf_qty, sort_order
        FROM public.dim_timeframe
        WHERE alignment_type = 'calendar'
            AND calendar_anchor = TRUE
            AND roll_policy = 'calendar_anchor'
            AND allow_partial_start = TRUE
            AND allow_partial_end   = TRUE
            AND base_unit IN ('W','M','Y')
            AND (
                -- ISO anchored weeks: *_CAL_ANCHOR_ISO
                (base_unit = 'W' AND calendar_scheme = 'ISO' AND tf ~ '_CAL_ANCHOR_ISO$')
                OR
                -- Anchored months/years: *_CAL_ANCHOR (scheme-agnostic)
                (base_unit IN ('M','Y') AND tf ~ '_CAL_ANCHOR$')
                )
        ORDER BY sort_order, tf;
        """)


    eng = get_engine(db_url)
    with eng.connect() as conn:
        rows = conn.execute(sql).mappings().all()

    specs: list[AnchorSpec] = [
        AnchorSpec(n=int(r["tf_qty"]), unit=str(r["base_unit"]), tf=str(r["tf"]))
        for r in rows
    ]

    if not specs:
        raise RuntimeError(
            "No matching anchored-calendar TF specs found in public.dim_timeframe for this builder. "
            "Expected: ISO anchored weeks (*_CAL_ANCHOR_ISO) + anchored months/years (*_CAL_ANCHOR)."
        )

    return specs


# =============================================================================
# Calendar helpers (ISO anchored windows + generic CAL months/years)
# =============================================================================

def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _add_months(month_start: date, months: int) -> date:
    y = month_start.year + (month_start.month - 1 + months) // 12
    m = (month_start.month - 1 + months) % 12 + 1
    return date(y, m, 1)


def _week_start_iso_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_index_iso(d: date) -> int:
    ws = _week_start_iso_monday(d)
    return (ws - REF_MONDAY_ISO).days // 7


def _week_group_bounds_iso(d: date, n_weeks: int) -> tuple[date, date]:
    widx = _week_index_iso(d)
    gidx = widx // n_weeks
    group_start = REF_MONDAY_ISO + timedelta(days=7 * n_weeks * gidx)
    group_end = group_start + timedelta(days=7 * n_weeks - 1)  # ends Sunday
    return group_start, group_end


def _month_group_bounds_anchored(d: date, n_months: int) -> tuple[date, date]:
    g0 = ((d.month - 1) // n_months) * n_months + 1
    start = date(d.year, g0, 1)
    end_month_start = _add_months(start, n_months - 1)
    end = _last_day_of_month(end_month_start)
    return start, end


def _year_group_bounds_anchored(d: date, n_years: int) -> tuple[date, date]:
    start_year = d.year - ((d.year - 1) % n_years)
    start = date(start_year, 1, 1)
    end = date(start_year + n_years, 1, 1) - timedelta(days=1)
    return start, end


def anchor_window_for_day(d: date, spec: AnchorSpec) -> tuple[date, date]:
    if spec.unit == "W":
        return _week_group_bounds_iso(d, spec.n)
    if spec.unit == "M":
        return _month_group_bounds_anchored(d, spec.n)
    if spec.unit == "Y":
        return _year_group_bounds_anchored(d, spec.n)
    raise ValueError(f"Unsupported unit: {spec.unit}")


def _months_diff(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def bar_seq_for_window_start(first_window_start: date, window_start: date, spec: AnchorSpec) -> int:
    if window_start < first_window_start:
        raise ValueError("window_start earlier than first_window_start; backfill should trigger rebuild")

    if spec.unit == "W":
        step = 7 * spec.n
        return (window_start - first_window_start).days // step + 1

    if spec.unit == "M":
        return _months_diff(first_window_start, window_start) // spec.n + 1

    if spec.unit == "Y":
        return (window_start.year - first_window_start.year) // spec.n + 1

    raise ValueError(f"Unsupported unit: {spec.unit}")


def _expected_days(window_start: date, window_end: date) -> int:
    return (window_end - window_start).days + 1


def _count_days_remaining(window_end: date, cur_day: date) -> int:
    # days remaining until end of anchored window (exclusive of cur_day)
    return int((window_end - cur_day).days)


def _missing_days_stats(
    *,
    bar_start_eff: date,
    snapshot_day: date,
    idx_by_day: dict[date, int],
) -> tuple[bool, int, int, int, int, str | None]:
    """
    Returns:
      is_missing_days,
      count_missing_days,
      count_missing_days_start,
      count_missing_days_end,
      count_missing_days_interior,
      missing_days_where (nullable)
    """
    if snapshot_day < bar_start_eff:
        return False, 0, 0, 0, 0, None

    exp_n = (snapshot_day - bar_start_eff).days + 1
    missing_days: list[date] = []
    for k in range(exp_n):
        d = bar_start_eff + timedelta(days=k)
        if d not in idx_by_day:
            missing_days.append(d)

    if not missing_days:
        return False, 0, 0, 0, 0, None

    missing_set = set(missing_days)

    # start run
    start_run = 0
    for k in range(exp_n):
        d = bar_start_eff + timedelta(days=k)
        if d in missing_set:
            start_run += 1
        else:
            break

    # end run
    end_run = 0
    for k in range(exp_n - 1, -1, -1):
        d = bar_start_eff + timedelta(days=k)
        if d in missing_set:
            end_run += 1
        else:
            break

    interior = len(missing_days) - start_run - end_run
    if interior < 0:
        interior = 0

    where_bits: list[str] = []
    if start_run > 0:
        where_bits.append("start")
    if end_run > 0:
        where_bits.append("end")
    if interior > 0:
        where_bits.append("interior")

    where = ",".join(where_bits) if where_bits else None
    return True, int(len(missing_days)), int(start_run), int(end_run), int(interior), where


def _lookback_days_for_spec(spec: AnchorSpec) -> int:
    """
    Conservative lookback window (in local calendar days) to guarantee we can recompute
    aggregates from bar_start_effective when needed during incremental runs.
    """
    if spec.unit == "W":
        return int(7 * spec.n + 7)      # +1 week buffer
    if spec.unit == "M":
        return int(31 * spec.n + 10)    # month upper bound + buffer
    if spec.unit == "Y":
        return int(366 * spec.n + 10)   # leap-year-safe + buffer
    return 400


# =============================================================================
# Snapshot bar building helpers
# =============================================================================

def _make_day_time_open(ts: pd.Series) -> pd.Series:
    one_ms = pd.Timedelta(milliseconds=1)
    out = ts.shift(1) + one_ms
    if len(ts) > 0:
        out.iloc[0] = ts.iloc[0] - pd.Timedelta(days=1) + one_ms
    return out


def _assert_one_row_per_local_day(df: pd.DataFrame, *, id_: int, tf: str, tz: str) -> None:
    if df.empty:
        return
    ts_local = df["ts"].dt.tz_convert(tz)
    day_date = ts_local.dt.date
    if day_date.duplicated().any():
        dups = day_date[day_date.duplicated()].astype(str).unique()[:10]
        raise ValueError(
            f"[bars_anchor_iso] Duplicate local dates detected for id={id_}, tf={tf}, tz={tz}. "
            f"Examples={list(dups)}. This violates the 1-row-per-day assumption."
        )


def _build_snapshots_full_history_for_id_spec(
    df_id: pd.DataFrame,
    *,
    spec: AnchorSpec,
    tz: str,
    daily_min_day: date,
    fail_on_internal_gaps: bool,
) -> pd.DataFrame:
    if df_id.empty:
        return pd.DataFrame()

    df = df_id.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date
    df["day_time_open"] = _make_day_time_open(df["ts"])

    idx_by_day = {d: i for i, d in enumerate(df["day_date"].tolist())}

    first_day: date = df["day_date"].iloc[0]
    last_day: date = df["day_date"].iloc[-1]

    first_window_start, _ = anchor_window_for_day(daily_min_day, spec)

    id_val = int(df["id"].iloc[0])
    rows: list[dict] = []

    cur_day = first_day
    while cur_day <= last_day:
        j = idx_by_day.get(cur_day)
        if j is None:
            cur_day = cur_day + timedelta(days=1)
            continue

        win_start, win_end = anchor_window_for_day(cur_day, spec)
        bar_seq = bar_seq_for_window_start(first_window_start, win_start, spec)
        tf_days = _expected_days(win_start, win_end)

        bar_start_eff = max(win_start, daily_min_day)
        is_partial_start = (bar_start_eff > win_start)
        is_partial_end = (cur_day < win_end)

        is_missing_days, c_missing, c_m_start, c_m_end, c_m_int, where = _missing_days_stats(
            bar_start_eff=bar_start_eff, snapshot_day=cur_day, idx_by_day=idx_by_day
        )
        if is_missing_days and fail_on_internal_gaps:
            raise ValueError(
                f"[bars_anchor_iso] Missing daily row(s) inside snapshot range: "
                f"id={id_val}, tf={spec.tf}, window={win_start}..{win_end}, agg={bar_start_eff}..{cur_day}."
            )

        exp_to_date = (cur_day - bar_start_eff).days + 1
        idxs: list[int] = []
        for k in range(exp_to_date):
            d = bar_start_eff + timedelta(days=k)
            jj = idx_by_day.get(d)
            if jj is None:
                continue
            idxs.append(jj)

        if not idxs:
            cur_day = cur_day + timedelta(days=1)
            continue

        g = df.iloc[idxs]
        high_val = g["high"].max()
        low_val = g["low"].min()

        rows.append(
            {
                "id": id_val,
                "tf": spec.tf,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": g["day_time_open"].iloc[0],
                "time_close": df.loc[j, "ts"],
                "time_high": g.loc[g["high"] == high_val, "timehigh"].iloc[0],
                "time_low": g.loc[g["low"] == low_val, "timelow"].iloc[0],
                "open": float(g["open"].iloc[0]),
                "high": float(high_val),
                "low": float(low_val),
                "close": float(df.loc[j, "close"]),
                "volume": float(g["volume"].sum(skipna=True)),
                "market_cap": float(df.loc[j, "market_cap"]),
                "count_days": int(exp_to_date),
                "count_days_remaining": int(_count_days_remaining(win_end, cur_day)),
                "is_partial_start": bool(is_partial_start),
                "is_partial_end": bool(is_partial_end),
                "is_missing_days": bool(is_missing_days),
                "count_missing_days": int(c_missing),
                "count_missing_days_start": int(c_m_start),
                "count_missing_days_end": int(c_m_end),
                "count_missing_days_interior": int(c_m_int),
                "missing_days_where": where,
            }
        )

        cur_day = cur_day + timedelta(days=1)

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    out["count_days"] = out["count_days"].astype(np.int32)
    out["count_days_remaining"] = out["count_days_remaining"].astype(np.int32)
    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)
    out["count_missing_days"] = out["count_missing_days"].astype(np.int32)
    out["count_missing_days_start"] = out["count_missing_days_start"].astype(np.int32)
    out["count_missing_days_end"] = out["count_missing_days_end"].astype(np.int32)
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype(np.int32)
    return out


def _build_incremental_snapshots_for_id_spec(
    df_slice: pd.DataFrame,
    *,
    spec: AnchorSpec,
    tz: str,
    daily_min_day: date,
    first_window_start: date,
    start_day: date,
    end_day: date,
    last_snapshot_row: dict | None,
    fail_on_internal_gaps: bool,
) -> pd.DataFrame:
    if df_slice.empty or start_day > end_day:
        return pd.DataFrame()

    df = df_slice.sort_values("ts").reset_index(drop=True).copy()
    _assert_one_row_per_local_day(df, id_=int(df["id"].iloc[0]), tf=spec.tf, tz=tz)

    ts_local = df["ts"].dt.tz_convert(tz)
    df["day_date"] = ts_local.dt.date
    df["day_time_open"] = _make_day_time_open(df["ts"])

    df_by_date = {d: i for i, d in enumerate(df["day_date"].tolist())}

    id_val = int(df["id"].iloc[0])
    rows: list[dict] = []

    carry: dict | None = None
    if last_snapshot_row is not None:
        last_close_local_day = pd.to_datetime(last_snapshot_row["time_close"], utc=True).tz_convert(tz).date()
        carry = {
            "bar_seq": int(last_snapshot_row.get("bar_seq")) if last_snapshot_row.get("bar_seq") is not None else None,
            "time_open": pd.to_datetime(last_snapshot_row["time_open"], utc=True) if last_snapshot_row.get("time_open") is not None else None,
            "open": float(last_snapshot_row["open"]),
            "high": float(last_snapshot_row["high"]),
            "low": float(last_snapshot_row["low"]),
            "volume": float(last_snapshot_row["volume"]),
            "time_high": pd.to_datetime(last_snapshot_row["time_high"], utc=True),
            "time_low": pd.to_datetime(last_snapshot_row["time_low"], utc=True),
            "is_missing_days": bool(last_snapshot_row.get("is_missing_days", False)),
            "count_days": int(last_snapshot_row.get("count_days") or 0),
            "count_days_remaining": int(last_snapshot_row.get("count_days_remaining") or 0),
            "count_missing_days": int(last_snapshot_row.get("count_missing_days") or 0),
            "count_missing_days_start": int(last_snapshot_row.get("count_missing_days_start") or 0),
            "count_missing_days_end": int(last_snapshot_row.get("count_missing_days_end") or 0),
            "count_missing_days_interior": int(last_snapshot_row.get("count_missing_days_interior") or 0),
            "missing_days_where": last_snapshot_row.get("missing_days_where"),
            "last_day": last_close_local_day,
        }

    cur_day = start_day
    while cur_day <= end_day:
        j = df_by_date.get(cur_day)
        if j is None:
            cur_day = cur_day + timedelta(days=1)
            continue

        win_start, win_end = anchor_window_for_day(cur_day, spec)
        bar_seq = bar_seq_for_window_start(first_window_start, win_start, spec)
        tf_days = _expected_days(win_start, win_end)

        bar_start_eff = max(win_start, daily_min_day)
        is_partial_start = (bar_start_eff > win_start)
        is_partial_end = (cur_day < win_end)

        can_carry = (
            carry is not None
            and carry.get("bar_seq") == bar_seq
            and carry.get("last_day") == (cur_day - timedelta(days=1))
            and not bool(carry.get("is_missing_days", False))
        )

        if not can_carry:
            exp_to_date = (cur_day - bar_start_eff).days + 1

            is_missing_days, c_missing, c_m_start, c_m_end, c_m_int, where = _missing_days_stats(
                bar_start_eff=bar_start_eff,
                snapshot_day=cur_day,
                idx_by_day=df_by_date,
            )
            if is_missing_days and fail_on_internal_gaps:
                raise ValueError(
                    f"[bars_anchor_iso] Missing daily row(s) inside snapshot range: "
                    f"id={id_val}, tf={spec.tf}, window={win_start}..{win_end}, agg={bar_start_eff}..{cur_day}."
                )

            idxs: list[int] = []
            for k in range(exp_to_date):
                d = bar_start_eff + timedelta(days=k)
                jj = df_by_date.get(d)
                if jj is None:
                    continue
                idxs.append(jj)

            if not idxs:
                cur_day = cur_day + timedelta(days=1)
                continue

            g = df.iloc[idxs]
            high_val = g["high"].max()
            low_val = g["low"].min()

            carry = {
                "bar_seq": int(bar_seq),
                "time_open": g["day_time_open"].iloc[0],
                "open": float(g["open"].iloc[0]),
                "high": float(high_val),
                "low": float(low_val),
                "volume": float(g["volume"].sum(skipna=True)),
                "time_high": g.loc[g["high"] == high_val, "timehigh"].iloc[0],
                "time_low": g.loc[g["low"] == low_val, "timelow"].iloc[0],
                "is_missing_days": bool(is_missing_days),
                "count_days": int(exp_to_date),
                "count_days_remaining": int(_count_days_remaining(win_end, cur_day)),
                "count_missing_days": int(c_missing),
                "count_missing_days_start": int(c_m_start),
                "count_missing_days_end": int(c_m_end),
                "count_missing_days_interior": int(c_m_int),
                "missing_days_where": where,
                "last_day": cur_day,
            }
        else:
            day_high = float(df.loc[j, "high"])
            day_low = float(df.loc[j, "low"])

            if day_high > carry["high"]:
                carry["high"] = day_high
                carry["time_high"] = df.loc[j, "timehigh"]

            if day_low < carry["low"]:
                carry["low"] = day_low
                carry["time_low"] = df.loc[j, "timelow"]

            carry["volume"] = float(carry["volume"]) + float(df.loc[j, "volume"])
            carry["last_day"] = cur_day

            carry["count_days"] = int(carry.get("count_days", 0)) + 1
            carry["count_days_remaining"] = int(_count_days_remaining(win_end, cur_day))
            carry["is_missing_days"] = False
            carry["count_missing_days"] = 0
            carry["count_missing_days_start"] = 0
            carry["count_missing_days_end"] = 0
            carry["count_missing_days_interior"] = 0
            carry["missing_days_where"] = None

        rows.append(
            {
                "id": id_val,
                "tf": spec.tf,
                "tf_days": int(tf_days),
                "bar_seq": int(bar_seq),
                "time_open": carry["time_open"],
                "time_close": df.loc[j, "ts"],
                "time_high": carry["time_high"],
                "time_low": carry["time_low"],
                "open": float(carry["open"]),
                "high": float(carry["high"]),
                "low": float(carry["low"]),
                "close": float(df.loc[j, "close"]),
                "volume": float(carry["volume"]),
                "market_cap": float(df.loc[j, "market_cap"]),
                "count_days": int(carry.get("count_days", 0)),
                "count_days_remaining": int(carry.get("count_days_remaining", _count_days_remaining(win_end, cur_day))),
                "is_partial_start": bool(is_partial_start),
                "is_partial_end": bool(is_partial_end),
                "is_missing_days": bool(carry.get("is_missing_days", False)),
                "count_missing_days": int(carry.get("count_missing_days", 0)),
                "count_missing_days_start": int(carry.get("count_missing_days_start", 0)),
                "count_missing_days_end": int(carry.get("count_missing_days_end", 0)),
                "count_missing_days_interior": int(carry.get("count_missing_days_interior", 0)),
                "missing_days_where": carry.get("missing_days_where"),
            }
        )

        cur_day = cur_day + timedelta(days=1)

    out = pd.DataFrame.from_records(rows)
    if out.empty:
        return out

    out["bar_seq"] = out["bar_seq"].astype(np.int32)
    out["tf_days"] = out["tf_days"].astype(np.int32)
    out["count_days"] = out["count_days"].astype(np.int32)
    out["count_days_remaining"] = out["count_days_remaining"].astype(np.int32)
    out["is_partial_start"] = out["is_partial_start"].astype(bool)
    out["is_partial_end"] = out["is_partial_end"].astype(bool)
    out["is_missing_days"] = out["is_missing_days"].astype(bool)
    out["count_missing_days"] = out["count_missing_days"].astype(np.int32)
    out["count_missing_days_start"] = out["count_missing_days_start"].astype(np.int32)
    out["count_missing_days_end"] = out["count_missing_days_end"].astype(np.int32)
    out["count_missing_days_interior"] = out["count_missing_days_interior"].astype(np.int32)
    return out


# =============================================================================
# Upsert (append-only snapshots)
# =============================================================================

def upsert_bars(df_bars: pd.DataFrame, db_url: str, bars_table: str, batch_size: int = 25_000) -> None:
    if df_bars.empty:
        return

    upsert_sql = f"""
    INSERT INTO {bars_table} (
      id, tf, tf_days, bar_seq,
      time_open, time_close, time_high, time_low,
      open, high, low, close, volume, market_cap,
      count_days, count_days_remaining,
      is_partial_start, is_partial_end, is_missing_days,
      count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
      missing_days_where
    )
    VALUES (
      :id, :tf, :tf_days, :bar_seq,
      :time_open, :time_close, :time_high, :time_low,
      :open, :high, :low, :close, :volume, :market_cap,
      :count_days, :count_days_remaining,
      :is_partial_start, :is_partial_end, :is_missing_days,
      :count_missing_days, :count_missing_days_start, :count_missing_days_end, :count_missing_days_interior,
      :missing_days_where
    )
    ON CONFLICT (id, tf, bar_seq, time_close) DO UPDATE SET
      tf_days                     = EXCLUDED.tf_days,
      time_open                   = EXCLUDED.time_open,
      time_high                   = EXCLUDED.time_high,
      time_low                    = EXCLUDED.time_low,
      open                        = EXCLUDED.open,
      high                        = EXCLUDED.high,
      low                         = EXCLUDED.low,
      close                       = EXCLUDED.close,
      volume                      = EXCLUDED.volume,
      market_cap                  = EXCLUDED.market_cap,
      count_days                  = EXCLUDED.count_days,
      count_days_remaining        = EXCLUDED.count_days_remaining,
      is_partial_start            = EXCLUDED.is_partial_start,
      is_partial_end              = EXCLUDED.is_partial_end,
      is_missing_days             = EXCLUDED.is_missing_days,
      count_missing_days          = EXCLUDED.count_missing_days,
      count_missing_days_start    = EXCLUDED.count_missing_days_start,
      count_missing_days_end      = EXCLUDED.count_missing_days_end,
      count_missing_days_interior = EXCLUDED.count_missing_days_interior,
      missing_days_where          = EXCLUDED.missing_days_where,
      ingested_at                 = now();
    """

    eng = get_engine(db_url)
    payload = df_bars.to_dict(orient="records")

    with eng.begin() as conn:
        for i in range(0, len(payload), batch_size):
            conn.execute(text(upsert_sql), payload[i: i + batch_size])


# =============================================================================
# Incremental driver
# =============================================================================

def refresh_incremental(
    *,
    db_url: str,
    ids: list[int],
    tz: str,
    daily_table: str,
    bars_table: str,
    state_table: str,
    fail_on_internal_gaps: bool,
) -> None:
    ensure_state_table(db_url, state_table)

    specs = load_anchor_specs_from_dim_timeframe(db_url)
    tfs = [s.tf for s in specs]
    print(f"[bars_anchor_iso] tz={tz}")
    print(f"[bars_anchor_iso] specs size={len(specs)}")
    print(f"[bars_anchor_iso] specs: {tfs}")

    daily_mm = load_daily_min_max(db_url, daily_table, ids)
    if daily_mm.empty:
        print("[bars_anchor_iso] No daily data found for requested ids.")
        return

    state_df = load_state(db_url, state_table, ids)
    state_map: dict[tuple[int, str], dict] = {}
    if not state_df.empty:
        for r in state_df.to_dict(orient="records"):
            state_map[(int(r["id"]), str(r["tf"]))] = r

    mm_map = {int(r["id"]): r for r in daily_mm.to_dict(orient="records")}

    state_updates: list[dict] = []
    total_upsert = 0
    total_rebuild = 0
    total_append = 0
    total_noop = 0
    total_errors = 0

    for id_ in ids:
        mm = mm_map.get(int(id_))
        if mm is None:
            continue

        daily_min_ts: pd.Timestamp = mm["daily_min_ts"]
        daily_max_ts: pd.Timestamp = mm["daily_max_ts"]
        daily_min_day: date = daily_min_ts.tz_convert(tz).date()
        daily_max_day: date = daily_max_ts.tz_convert(tz).date()

        last_snap_map = load_last_snapshot_info_for_id_tfs(db_url, bars_table, id_=int(id_), tfs=tfs)

        for spec in specs:
            st = None
            try:
                key = (int(id_), spec.tf)
                st = state_map.get(key)
                last_snap = last_snap_map.get(spec.tf)

                daily_min_seen = (
                    pd.to_datetime(st["daily_min_seen"], utc=True)
                    if st is not None and pd.notna(st.get("daily_min_seen"))
                    else daily_min_ts
                )
                daily_max_seen = (
                    pd.to_datetime(st["daily_max_seen"], utc=True)
                    if st is not None and pd.notna(st.get("daily_max_seen"))
                    else daily_max_ts
                )

                first_window_start, _ = anchor_window_for_day(daily_min_day, spec)

                # First ever => full build
                if st is None and last_snap is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(
                        df_full,
                        spec=spec,
                        tz=tz,
                        daily_min_day=daily_min_day,
                        fail_on_internal_gaps=fail_on_internal_gaps,
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        total_rebuild += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                    else:
                        last_bar_seq = None
                        last_time_close = None

                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                # Bars missing but state exists (or vice versa) => rebuild
                if last_snap is None:
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(
                        df_full,
                        spec=spec,
                        tz=tz,
                        daily_min_day=daily_min_day,
                        fail_on_internal_gaps=fail_on_internal_gaps,
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        total_rebuild += 1
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                    else:
                        last_bar_seq = None
                        last_time_close = None

                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                last_time_close: pd.Timestamp = last_snap["last_time_close"]
                last_bar_seq = int(last_snap["last_bar_seq"])

                # BACKFILL
                if daily_min_ts < daily_min_seen:
                    print(
                        f"[bars_anchor_iso] Backfill detected: id={id_}, tf={spec.tf}, "
                        f"daily_min moved earlier {daily_min_seen} -> {daily_min_ts}. Rebuilding id/tf."
                    )
                    delete_bars_for_id_tf(db_url, bars_table, id_=int(id_), tf=spec.tf)
                    df_full = load_daily_prices_for_id(db_url=db_url, daily_table=daily_table, id_=int(id_))
                    bars = _build_snapshots_full_history_for_id_spec(
                        df_full,
                        spec=spec,
                        tz=tz,
                        daily_min_day=daily_min_day,
                        fail_on_internal_gaps=fail_on_internal_gaps,
                    )
                    if not bars.empty:
                        upsert_bars(bars, db_url, bars_table)
                        total_upsert += len(bars)
                        last_bar_seq = int(bars["bar_seq"].max())
                        last_time_close = pd.to_datetime(bars["time_close"].max(), utc=True)
                    total_rebuild += 1

                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": daily_min_ts,
                            "daily_max_seen": daily_max_ts,
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                # NOOP
                if daily_max_ts <= last_time_close:
                    total_noop += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                # APPEND new snapshot days
                start_day = last_time_close.tz_convert(tz).date() + timedelta(days=1)
                end_day = daily_max_day

                lookback = _lookback_days_for_spec(spec)
                slice_start_day = max(daily_min_day, start_day - timedelta(days=lookback))
                ts_start_local = pd.Timestamp(datetime.combine(slice_start_day, datetime.min.time()), tz=tz)
                ts_start = ts_start_local.tz_convert("UTC")

                df_slice = load_daily_prices_for_id(
                    db_url=db_url,
                    daily_table=daily_table,
                    id_=int(id_),
                    ts_start=ts_start,
                )
                if df_slice.empty:
                    total_noop += 1
                    state_updates.append(
                        {
                            "id": int(id_),
                            "tf": spec.tf,
                            "tz": tz,
                            "daily_min_seen": min(daily_min_seen, daily_min_ts),
                            "daily_max_seen": max(daily_max_seen, daily_max_ts),
                            "last_bar_seq": last_bar_seq,
                            "last_time_close": last_time_close,
                        }
                    )
                    continue

                last_row = load_last_snapshot_row(db_url, bars_table, id_=int(id_), tf=spec.tf)

                bars_new = _build_incremental_snapshots_for_id_spec(
                    df_slice,
                    spec=spec,
                    tz=tz,
                    daily_min_day=daily_min_day,
                    first_window_start=first_window_start,
                    start_day=start_day,
                    end_day=end_day,
                    last_snapshot_row=last_row,
                    fail_on_internal_gaps=fail_on_internal_gaps,
                )

                if not bars_new.empty:
                    upsert_bars(bars_new, db_url, bars_table)
                    total_upsert += len(bars_new)
                    total_append += 1
                    last_bar_seq2 = int(bars_new["bar_seq"].max())
                    last_time_close2 = pd.to_datetime(bars_new["time_close"].max(), utc=True)
                else:
                    last_bar_seq2 = last_bar_seq
                    last_time_close2 = last_time_close

                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": min(daily_min_seen, daily_min_ts),
                        "daily_max_seen": max(daily_max_seen, daily_max_ts),
                        "last_bar_seq": last_bar_seq2,
                        "last_time_close": last_time_close2,
                    }
                )

            except Exception as e:
                total_errors += 1
                print(f"[bars_anchor_iso] ERROR id={id_} tf={spec.tf}: {type(e).__name__}: {e}")

                last_keep = last_snap_map.get(spec.tf)
                state_updates.append(
                    {
                        "id": int(id_),
                        "tf": spec.tf,
                        "tz": tz,
                        "daily_min_seen": daily_min_ts if st is None else min(
                            pd.to_datetime(st["daily_min_seen"], utc=True) if pd.notna(st.get("daily_min_seen")) else daily_min_ts,
                            daily_min_ts,
                        ),
                        "daily_max_seen": daily_max_ts if st is None else max(
                            pd.to_datetime(st["daily_max_seen"], utc=True) if pd.notna(st.get("daily_max_seen")) else daily_max_ts,
                            daily_max_ts,
                        ),
                        "last_bar_seq": int(last_keep["last_bar_seq"]) if last_keep is not None else (st.get("last_bar_seq") if st is not None else None),
                        "last_time_close": pd.to_datetime(last_keep["last_time_close"], utc=True) if last_keep is not None else (
                            pd.to_datetime(st["last_time_close"], utc=True) if st is not None and pd.notna(st.get("last_time_close")) else None
                        ),
                    }
                )
                continue

    upsert_state(db_url, state_table, state_updates)
    print(
        f"[bars_anchor_iso] Done. upserted_rows={total_upsert:,} "
        f"rebuilds={total_rebuild} appends={total_append} noops={total_noop} errors={total_errors}"
    )


# =============================================================================
# CLI
# =============================================================================

def main(argv: Sequence[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Build ISO anchored weeks + calendar months/years (*_CAL) price bars (append-only daily snapshots, incremental)."
    )
    ap.add_argument("--ids", nargs="+", required=True, help="'all' or list of ids (space/comma separated).")
    ap.add_argument("--db-url", default=None, help="Optional DB URL override. Defaults to TARGET_DB_URL env.")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE)
    ap.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    ap.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    ap.add_argument("--tz", default=DEFAULT_TZ)
    ap.add_argument(
        "--fail-on-internal-gaps",
        action="store_true",
        help="Fail if any daily row is missing inside a snapshot aggregation range (recommended).",
    )
    args = ap.parse_args(list(argv) if argv is not None else None)

    db_url = resolve_db_url(args.db_url)
    ids = parse_ids(args.ids, db_url, args.daily_table)

    print(f"[bars_anchor_iso] daily_table={args.daily_table}")
    print(f"[bars_anchor_iso] bars_table={args.bars_table}")
    print(f"[bars_anchor_iso] state_table={args.state_table}")

    refresh_incremental(
        db_url=db_url,
        ids=ids,
        tz=args.tz,
        daily_table=args.daily_table,
        bars_table=args.bars_table,
        state_table=args.state_table,
        fail_on_internal_gaps=args.fail_on_internal_gaps,
    )


if __name__ == "__main__":
    main()
