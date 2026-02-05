from __future__ import annotations
# src/ta_lab2/bars/common_snapshot_contract.py

"""
Shared snapshot-contract utilities for ta_lab2 bar builders.

Design intent (do NOT violate this):
- Shared code standardizes invariants + mechanics (tie-breaks, diagnostics, schema, carry-forward, DB upsert plumbing).
- Builders own semantics (bar boundaries, bar_start_day_local, bar_seq assignment, window membership).

Option B contract decisions:
- roll is NOT first-class (implicit via is_partial_end + count_days_remaining in bar tables)
- missing-days diagnostics are SIMPLE (is_missing_days, count_days, count_missing_days)
- shared code must NOT encode rolling/calendar semantics (no tf_days logic, no mode-specific math)
"""

import argparse
import math
import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# =============================================================================
# 1) Base invariant: exactly 1 row per local day
# =============================================================================


def assert_one_row_per_local_day(
    df: pd.DataFrame,
    *,
    ts_col: str = "ts",
    tz: str = "America/New_York",
    id_col: str | None = None,
) -> None:
    """
    Enforce that base daily data has exactly 1 row per local calendar day.

    This must run *before* any bar/window logic.
    """
    if df.empty:
        return
    if ts_col not in df.columns:
        raise ValueError(f"Missing required timestamp column: {ts_col}")

    ts = pd.to_datetime(df[ts_col], utc=True, errors="coerce")
    if ts.isna().any():
        bad = df.loc[ts.isna()].head(5)
        raise ValueError(f"{ts_col} contains NaT/invalid timestamps. Sample:\n{bad}")

    local_day = ts.dt.tz_convert(tz).dt.date
    vc = local_day.value_counts()
    dups = vc[vc > 1]
    if not dups.empty:
        dup_day = dups.index[0]
        sample = df.loc[local_day == dup_day]
        if id_col and id_col in df.columns:
            sample = sample.sort_values([id_col, ts_col]).head(10)
        else:
            sample = sample.sort_values(ts_col).head(10)
        id_note = (
            f" across ids (showing `{id_col}`)"
            if (id_col and id_col in df.columns)
            else ""
        )
        raise ValueError(
            f"Base daily invariant violated: {int(dups.iloc[0])} rows for local day {dup_day} ({tz}){id_note}. "
            f"Sample:\n{sample}"
        )


# =============================================================================
# 2) Deterministic extrema timestamps: earliest among ties + fallback to ts
# =============================================================================


def compute_time_high_low(
    df_window: pd.DataFrame,
    *,
    ts_col: str = "ts",
    high_col: str = "high",
    low_col: str = "low",
    timehigh_col: str = "timehigh",
    timelow_col: str = "timelow",
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Compute deterministic time_high / time_low for a bar window.

    Rules:
    - Choose earliest timestamp among all rows tied for the extrema (high/low).
    - Prefer timehigh/timelow columns if present; otherwise fall back to ts.
    - If timehigh/timelow is null/NaT on a tied row, fall back to ts on that row.
    """
    if df_window.empty:
        return pd.NaT, pd.NaT

    if ts_col not in df_window.columns:
        raise ValueError(f"Missing {ts_col} in df_window")

    ts = pd.to_datetime(df_window[ts_col], utc=True, errors="coerce")

    # High ties
    if high_col in df_window.columns:
        hi = pd.to_numeric(df_window[high_col], errors="coerce")
        hi_val = hi.max(skipna=True)
        hi_mask = hi == hi_val
    else:
        hi_mask = pd.Series([False] * len(df_window), index=df_window.index)

    # Low ties
    if low_col in df_window.columns:
        lo = pd.to_numeric(df_window[low_col], errors="coerce")
        lo_val = lo.min(skipna=True)
        lo_mask = lo == lo_val
    else:
        lo_mask = pd.Series([False] * len(df_window), index=df_window.index)

    # Candidate timestamps for ties (fallback to ts per row)
    if timehigh_col in df_window.columns:
        th = pd.to_datetime(df_window[timehigh_col], utc=True, errors="coerce")
        th = th.where(th.notna(), ts)
    else:
        th = ts

    if timelow_col in df_window.columns:
        tl = pd.to_datetime(df_window[timelow_col], utc=True, errors="coerce")
        tl = tl.where(tl.notna(), ts)
    else:
        tl = ts

    time_high = th.loc[hi_mask].min() if bool(hi_mask.any()) else pd.NaT
    time_low = tl.loc[lo_mask].min() if bool(lo_mask.any()) else pd.NaT

    return pd.to_datetime(time_high, utc=True, errors="coerce"), pd.to_datetime(
        time_low, utc=True, errors="coerce"
    )


# =============================================================================
# 3) Missing-days diagnostics (simple)
# =============================================================================


def _date_range_inclusive(a: date, b: date) -> list[date]:
    if b < a:
        return []
    n = (b - a).days
    return [a + timedelta(days=i) for i in range(n + 1)]


def compute_missing_days_diagnostics(
    *,
    bar_start_day_local: date,
    snapshot_day_local: date,
    observed_days_local: Iterable[date],
) -> dict[str, Any]:
    """
    Simple missing-days diagnostics per Option B:

    - expected days: inclusive range [bar_start_day_local, snapshot_day_local]
    - observed days: set(observed_days_local)
    """
    expected = _date_range_inclusive(bar_start_day_local, snapshot_day_local)
    observed = set(observed_days_local)

    missing = [d for d in expected if d not in observed]
    return {
        "is_missing_days": len(missing) > 0,
        "count_days": len(expected),
        "count_missing_days": len(missing),
        "first_missing_day": pd.to_datetime(missing[0]).tz_localize("UTC")
        if missing
        else pd.NaT,
        "last_missing_day": pd.to_datetime(missing[-1]).tz_localize("UTC")
        if missing
        else pd.NaT,
    }


# =============================================================================
# 4) Schema normalization
# =============================================================================

REQUIRED_COL_DEFAULTS: dict[str, Any] = {
    # Identity / time
    "id": None,
    "tf": None,
    "bar_seq": None,
    "time_open": pd.NaT,
    "time_close": pd.NaT,
    "time_high": pd.NaT,
    "time_low": pd.NaT,
    # OHLCV + market data
    "open": float("nan"),
    "high": float("nan"),
    "low": float("nan"),
    "close": float("nan"),
    "volume": float("nan"),
    "market_cap": float("nan"),
    # Snapshot bookkeeping
    "timestamp": pd.NaT,
    "last_ts_half_open": pd.NaT,
    # Completeness/bookkeeping
    "pos_in_bar": None,
    "is_partial_start": False,
    "is_partial_end": True,
    "count_days_remaining": 0,
    # Missing-days diagnostics (simple)
    "is_missing_days": False,
    "count_days": 0,
    "count_missing_days": 0,
    "first_missing_day": pd.NaT,
    "last_missing_day": pd.NaT,
}


def normalize_output_schema(
    df: pd.DataFrame,
    *,
    required_defaults: Mapping[str, Any] = REQUIRED_COL_DEFAULTS,
) -> pd.DataFrame:
    """Ensure all required columns exist (adds missing with defaults). Does not drop extras."""
    out = df.copy()
    for col, default in required_defaults.items():
        if col not in out.columns:
            out[col] = default
    return out


# =============================================================================
# 5) Carry-forward gate + updater (semantics-neutral)
# =============================================================================


@dataclass(frozen=True)
class CarryForwardInputs:
    last_snapshot_day_local: date
    today_local: date
    snapshot_day_local: date
    same_bar_identity: bool
    missing_days_tail_ok: bool


def can_carry_forward(inp: CarryForwardInputs) -> bool:
    """
    Shared strict gate:
    - last snapshot day == yesterday (local)
    - snapshot day == today (local)
    - missing days tail ok (builder computed)
    - same bar identity (builder computed)
    """
    yesterday = inp.today_local - timedelta(days=1)
    if inp.last_snapshot_day_local != yesterday:
        return False
    if inp.snapshot_day_local != inp.today_local:
        return False
    if not inp.missing_days_tail_ok:
        return False
    if not inp.same_bar_identity:
        return False
    return True


def apply_carry_forward(
    prior_row: Mapping[str, Any],
    *,
    new_daily_row: Mapping[str, Any],
    update_window_fields: Callable[[dict[str, Any], Mapping[str, Any]], None],
) -> dict[str, Any]:
    """
    Build a new snapshot row from prior snapshot row + today's daily close row.

    Mechanics only:
    - copy prior_row
    - overwrite daily-close fields
    - run builder-provided window update
    - normalize schema
    """
    out = dict(prior_row)

    # Daily-close overwrite (common)
    for k in ("time_close", "close", "volume", "market_cap"):
        if k in new_daily_row:
            out[k] = new_daily_row[k]

    # Snapshot bookkeeping overwrite if supplied
    for k in (
        "timestamp",
        "last_ts_half_open",
        "pos_in_bar",
        "is_partial_start",
        "is_partial_end",
        "count_days_remaining",
    ):
        if k in new_daily_row:
            out[k] = new_daily_row[k]

    # Builder hook: update per-bar aggregates using today's daily row
    update_window_fields(out, new_daily_row)

    out_df = normalize_output_schema(pd.DataFrame([out]))
    return out_df.iloc[0].to_dict()


# =============================================================================
# 6) Semantics-neutral DB / IO helpers (requested API)
# =============================================================================


def resolve_db_url(
    db_url: str | None,
    *,
    env_var: str = "TARGET_DB_URL",
    label: str = "TARGET_DB_URL",
) -> str:
    """
    Resolve DB URL from explicit value, db_config.env file, or environment variable.

    Priority order:
    1. Explicit --db-url argument
    2. db_config.env file in project root (searched up to 5 levels)
    3. Environment variable (TARGET_DB_URL or MARKETDATA_DB_URL) as fallback
    """
    if db_url:
        return db_url

    # Try loading from db_config.env file FIRST (highest priority after explicit arg)
    try:
        from pathlib import Path

        # Look for db_config.env in current directory and parent directories
        current = Path.cwd()
        for _ in range(5):  # Search up to 5 levels up
            env_file = current / "db_config.env"
            if env_file.exists():
                # Parse the .env file manually (no external dependencies)
                with open(env_file, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, value = line.split("=", 1)
                            key = key.strip()
                            value = value.strip().strip('"').strip("'")
                            if key in (env_var, "TARGET_DB_URL", "MARKETDATA_DB_URL"):
                                # Found URL in file - return it immediately without caching to env
                                return value
            current = current.parent
    except Exception:
        pass  # Silently continue if file reading fails

    # Fall back to environment variable if file doesn't exist or doesn't have the URL
    val = os.environ.get(env_var)
    if val:
        return val

    # Also check MARKETDATA_DB_URL as final fallback
    if env_var != "MARKETDATA_DB_URL":
        val = os.environ.get("MARKETDATA_DB_URL")
        if val:
            return val

    raise ValueError(
        f"Missing DB URL. Either:\n"
        f"  1. Pass --db-url argument\n"
        f"  2. Create db_config.env file with {label}=postgresql://...\n"
        f"  3. Set {label} or MARKETDATA_DB_URL environment variable"
    )


def get_engine(db_url: str) -> Engine:
    """Create a SQLAlchemy engine (future=True)."""
    return create_engine(db_url, future=True)


def resolve_num_processes(num_processes: int | None, *, default: int = 6) -> int:
    """Clamp processes to [1..cpu_count()]."""
    from multiprocessing import cpu_count

    ncpu = int(cpu_count())
    n = default if num_processes is None else int(num_processes)
    if n <= 0:
        n = 1
    if n > ncpu:
        n = ncpu
    return n


def load_all_ids(db_url: str, daily_table: str, *, id_col: str = "id") -> list[int]:
    """Load distinct ids from daily table."""
    e = get_engine(db_url)
    sql = text(f"SELECT DISTINCT {id_col} AS id FROM {daily_table} ORDER BY 1;")
    with e.connect() as c:
        rows = c.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


def parse_ids(ids_arg: str | list[str]) -> list[int] | Literal["all"]:
    """
    Parse ID argument from command line.

    Returns either a list of integer IDs or the string "all".
    Caller should check if result == "all" and call load_all_ids() if needed.

    Args:
        ids_arg: Either a list of strings or single string

    Returns:
        list[int] if specific IDs provided, or "all" string

    Examples:
        >>> parse_ids(["all"])
        "all"
        >>> parse_ids(["1", "2", "3"])
        [1, 2, 3]
        >>> parse_ids("all")
        "all"
    """
    # Handle list input
    if isinstance(ids_arg, list):
        if len(ids_arg) == 1 and ids_arg[0].lower() == "all":
            return "all"
        return [int(x) for x in ids_arg]

    # Handle single string input
    if ids_arg.lower() == "all":
        return "all"

    return [int(ids_arg)]


def load_daily_min_max(
    db_url: str,
    daily_table: str,
    ids: Sequence[int],
    *,
    ts_col: str = "ts",
    include_row_count: bool = False,
) -> pd.DataFrame:
    """Per-id daily MIN/MAX ts (and optionally COUNT)."""
    if not ids:
        cols = ["id", "daily_min", "daily_max"] + (
            ["row_count"] if include_row_count else []
        )
        return pd.DataFrame(columns=cols)

    e = get_engine(db_url)
    sel = [
        f"MIN({ts_col}) AS daily_min",
        f"MAX({ts_col}) AS daily_max",
    ]
    if include_row_count:
        sel.append("COUNT(*)::bigint AS row_count")

    sql = text(
        f"""
        SELECT id, {", ".join(sel)}
        FROM {daily_table}
        WHERE id = ANY(:ids)
        GROUP BY 1
        ORDER BY 1;
        """
    )
    with e.connect() as c:
        df = pd.read_sql(sql, c, params={"ids": list(ids)})

    if df.empty:
        return df

    df["daily_min"] = pd.to_datetime(df["daily_min"], utc=True, errors="coerce")
    df["daily_max"] = pd.to_datetime(df["daily_max"], utc=True, errors="coerce")
    return df


# =============================================================================
# 7) State table helpers (generic with_tz)
# =============================================================================


def _state_pk_cols(with_tz: bool) -> tuple[str, ...]:
    return ("id", "tf", "tz") if with_tz else ("id", "tf")


def ensure_state_table(db_url: str, state_table: str, *, with_tz: bool = False) -> None:
    """
    Ensure state table exists.

    Primary key is ALWAYS (id, tf).
    The with_tz parameter controls whether tz column is included (as NOT NULL metadata).
    """
    if with_tz:
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
    else:
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
          id               integer      NOT NULL,
          tf               text         NOT NULL,
          daily_min_seen   timestamptz  NULL,
          daily_max_seen   timestamptz  NULL,
          last_bar_seq     integer      NULL,
          last_time_close  timestamptz  NULL,
          updated_at       timestamptz  NOT NULL DEFAULT now(),
          PRIMARY KEY (id, tf)
        );
        """

    e = get_engine(db_url)
    with e.begin() as c:
        c.execute(text(ddl))


def load_state(
    db_url: str,
    state_table: str,
    ids: Sequence[int],
    *,
    with_tz: bool = False,
) -> pd.DataFrame:
    """Load state for ids. If with_tz=True, returns rows for all tz values present."""
    if not ids:
        return pd.DataFrame()

    cols = (
        "id, tf, tz, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at"
        if with_tz
        else "id, tf, daily_min_seen, daily_max_seen, last_bar_seq, last_time_close, updated_at"
    )
    sql = text(
        f"""
        SELECT {cols}
        FROM {state_table}
        WHERE id = ANY(:ids);
        """
    )
    e = get_engine(db_url)
    with e.connect() as c:
        df = pd.read_sql(sql, c, params={"ids": list(ids)})

    if df.empty:
        return df

    df["daily_min_seen"] = pd.to_datetime(
        df["daily_min_seen"], utc=True, errors="coerce"
    )
    df["daily_max_seen"] = pd.to_datetime(
        df["daily_max_seen"], utc=True, errors="coerce"
    )
    df["last_time_close"] = pd.to_datetime(
        df["last_time_close"], utc=True, errors="coerce"
    )
    return df


def upsert_state(
    db_url: str,
    state_table: str,
    rows: pd.DataFrame | Sequence[dict[str, Any]],
    *,
    with_tz: bool = False,
) -> None:
    """
    Upsert state rows.

    Primary key is ALWAYS (id, tf).
    The with_tz parameter controls whether tz column is included in INSERT/UPDATE.
    """
    if isinstance(rows, pd.DataFrame):
        if rows.empty:
            return
        payload = rows.to_dict("records")
    else:
        payload = list(rows)
        if not payload:
            return

    # CRITICAL: Conflict target is ALWAYS (id, tf), regardless of with_tz
    pk_cols = ["id", "tf"]

    # Build column lists based on with_tz
    base_data_cols = [
        "daily_min_seen",
        "daily_max_seen",
        "last_bar_seq",
        "last_time_close",
    ]

    if with_tz:
        # Include tz in INSERT columns (after tf, before data columns)
        insert_cols = ["id", "tf", "tz"] + base_data_cols
        # Include tz in UPDATE SET clause
        update_cols = ["tz"] + base_data_cols
    else:
        # No tz column
        insert_cols = pk_cols + base_data_cols
        update_cols = base_data_cols

    insert_cols_str = ", ".join(insert_cols)
    values_str = ", ".join([f":{c}" for c in insert_cols])

    # Update SET clause: all non-PK columns plus updated_at
    set_sql = ", ".join(
        [f"{c} = EXCLUDED.{c}" for c in update_cols] + ["updated_at = now()"]
    )

    # Conflict target is ALWAYS (id, tf)
    conflict_target = "id, tf"

    sql = text(
        f"""
        INSERT INTO {state_table} ({insert_cols_str})
        VALUES ({values_str})
        ON CONFLICT ({conflict_target}) DO UPDATE
        SET {set_sql};
        """
    )
    e = get_engine(db_url)
    with e.begin() as c:
        c.execute(sql, payload)


# =============================================================================
# 8) Upsert plumbing: make_upsert_sql, convert_nat_to_none, upsert_bars
# =============================================================================


def make_upsert_sql(
    bars_table: str,
    cols: Sequence[str],
    *,
    conflict_cols: Sequence[str] = ("id", "tf", "bar_seq", "time_close"),
) -> str:
    """Generate INSERT ... ON CONFLICT ... DO UPDATE SQL."""
    insert_cols = ", ".join(cols)
    values = ", ".join([f":{c}" for c in cols])

    conflict = ", ".join(conflict_cols)
    update_cols = [c for c in cols if c not in set(conflict_cols)]
    set_clause = ", ".join([f"{c} = EXCLUDED.{c}" for c in update_cols])

    return f"""
    INSERT INTO {bars_table} ({insert_cols})
    VALUES ({values})
    ON CONFLICT ({conflict}) DO UPDATE
    SET {set_clause};
    """


def convert_nat_to_none(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    """
    Convert pandas NaT/NaN-like values to Python None for given columns.

    IMPORTANT:
    - For datetime64 / datetime64[tz] columns, pandas cannot hold None, so we must
      cast to object first or the None will be coerced back into NaT.
    """
    if df.empty:
        return df

    out = df.copy()
    for c in cols:
        if c not in out.columns:
            continue

        s = out[c]

        # datetime64 or datetime64tz: must cast to object for None to persist
        if pd.api.types.is_datetime64_any_dtype(
            s
        ) or pd.api.types.is_datetime64tz_dtype(s):
            out[c] = s.astype("object").where(s.notna(), None)
        else:
            out[c] = s.where(s.notna(), None)

    return out


def _default_timestamp_cols_for_output(df: pd.DataFrame) -> list[str]:
    """
    Reasonable default list for NaT->None conversion:
    all timestamp-like required columns that exist in df.
    """
    candidates = [
        "time_open",
        "time_close",
        "time_high",
        "time_low",
        "timestamp",
        "last_ts_half_open",
        "first_missing_day",
        "last_missing_day",
    ]
    return [c for c in candidates if c in df.columns]


def upsert_bars(
    df: pd.DataFrame,
    *,
    db_url: str,
    bars_table: str,
    conflict_cols: Sequence[str] = ("id", "tf", "bar_seq", "time_close"),
    timestamp_cols: Sequence[str] | None = None,
    keep_rejects: bool = False,
    rejects_table: str | None = None,
) -> None:
    """
    Standard bar-table write pipeline (shared):
    - normalize schema
    - log OHLC violations (if keep_rejects=True)
    - enforce output invariants (OHLC sanity, bad time_low fix)
    - NaT -> None for timestamp cols
    - executemany upsert

    Args:
        df: DataFrame with bar data
        db_url: Database URL
        bars_table: Target bars table name
        conflict_cols: Columns for ON CONFLICT clause
        timestamp_cols: Columns to convert NaT to None
        keep_rejects: If True, log OHLC violations before repair
        rejects_table: Table name for rejects (required if keep_rejects=True)
    """
    if df.empty:
        return

    # Filter to only valid schema columns FIRST
    valid_cols = [
        "id",
        "tf",
        "tf_days",
        "bar_seq",
        "bar_anchor_offset",
        "time_open",
        "time_close",
        "time_high",
        "time_low",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "is_partial_start",
        "is_partial_end",
        "is_missing_days",
        "count_days",
        "count_days_remaining",
        "count_missing_days",
        "count_missing_days_start",
        "count_missing_days_end",
        "count_missing_days_interior",
        "missing_days_where",
        "first_missing_day",
        "last_missing_day",
    ]
    df = df[[c for c in valid_cols if c in df.columns]]

    df2 = normalize_output_schema(df)

    # Log OHLC violations before repair (if enabled)
    if keep_rejects and rejects_table:
        rejects = []
        for _, row in df2.iterrows():
            violations = detect_ohlc_violations(row.to_dict())
            for vtype, raction in violations:
                rejects.append(
                    {
                        "id": row["id"],
                        "tf": row["tf"],
                        "bar_seq": row["bar_seq"],
                        "timestamp": row["timestamp"],
                        "violation_type": vtype,
                        "repair_action": raction,
                        "original_open": row["open"],
                        "original_high": row["high"],
                        "original_low": row["low"],
                        "original_close": row["close"],
                    }
                )
        if rejects:
            engine = get_engine(db_url)
            log_to_rejects(engine, rejects_table, rejects)

    df2 = enforce_ohlc_sanity(df2)

    if timestamp_cols is None:
        timestamp_cols = _default_timestamp_cols_for_output(df2)
    df2 = convert_nat_to_none(df2, timestamp_cols)

    cols = list(df2.columns)
    sql = text(make_upsert_sql(bars_table, cols, conflict_cols=conflict_cols))
    payload = df2.to_dict("records")

    e = get_engine(db_url)
    with e.begin() as c:
        c.execute(sql, payload)


# =============================================================================
# 9) Output invariant patches: enforce_ohlc_sanity + bad time_low fix
# =============================================================================


def enforce_ohlc_sanity(df: pd.DataFrame) -> pd.DataFrame:
    """
    Semantics-neutral invariants for already-built rows.

    Includes the explicit "bad time_low > time_close" fix:
    - If time_low > time_close:
        - low := min(open, close)
        - time_low := time_open if open<=close else time_close

    Also enforces:
    - high >= max(open, close) (if high missing or too low -> clamp up)
    - low  <= min(open, close) (if low missing or too high -> clamp down, time_low consistent)
    """
    if df.empty:
        return df

    out = df.copy()

    # Normalize datetime cols if present
    for c in (
        "time_open",
        "time_close",
        "time_low",
        "time_high",
        "timestamp",
        "last_ts_half_open",
    ):
        if c in out.columns:
            out[c] = pd.to_datetime(out[c], utc=True, errors="coerce")

    required = {"open", "close", "high", "low", "time_open", "time_close", "time_low"}
    if not required.issubset(set(out.columns)):
        return out

    oc_min = out[["open", "close"]].min(axis=1, skipna=True)
    oc_max = out[["open", "close"]].max(axis=1, skipna=True)

    pick_open = (
        out["open"].notna() & out["close"].notna() & (out["open"] <= out["close"])
    )

    # --- BAD time_low FIX ---
    bad_tl = (
        out["time_low"].notna()
        & out["time_close"].notna()
        & (out["time_low"] > out["time_close"])
    )
    if bad_tl.any():
        out.loc[bad_tl, "low"] = oc_min.loc[bad_tl]
        out.loc[bad_tl & pick_open, "time_low"] = out.loc[
            bad_tl & pick_open, "time_open"
        ]
        out.loc[bad_tl & (~pick_open), "time_low"] = out.loc[
            bad_tl & (~pick_open), "time_close"
        ]

    # Clamp high up if it violates max(open, close)
    high_violate = oc_max.notna() & (out["high"].isna() | (out["high"] < oc_max))
    if high_violate.any():
        out.loc[high_violate, "high"] = oc_max.loc[high_violate]

    # Clamp low down if it violates min(open, close)
    low_violate = oc_min.notna() & (out["low"].isna() | (out["low"] > oc_min))
    if low_violate.any():
        out.loc[low_violate, "low"] = oc_min.loc[low_violate]
        out.loc[low_violate & pick_open, "time_low"] = out.loc[
            low_violate & pick_open, "time_open"
        ]
        out.loc[low_violate & (~pick_open), "time_low"] = out.loc[
            low_violate & (~pick_open), "time_close"
        ]

    return out


# =============================================================================
# 10) Shared utilities for EMA/audit scripts
# =============================================================================


def table_exists(engine: Engine, full_name: str) -> bool:
    """
    Check if a table exists in the database.

    Args:
        engine: SQLAlchemy engine
        full_name: Table name, optionally schema-qualified (e.g., "public.foo" or "foo")

    Returns:
        True if table exists, False otherwise
    """
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name

    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        result = conn.execute(q, {"schema": schema, "table": table})
        return result.fetchone() is not None


def get_columns(engine: Engine, full_name: str) -> list[str]:
    """
    Get list of column names for a table.

    Args:
        engine: SQLAlchemy engine
        full_name: Table name, optionally schema-qualified

    Returns:
        List of column names in ordinal order
    """
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name

    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
        """
    )
    with engine.connect() as conn:
        result = conn.execute(q, {"schema": schema, "table": table})
        return [row[0] for row in result.fetchall()]


def create_bar_builder_argument_parser(
    description: str,
    *,
    default_daily_table: str,
    default_bars_table: str,
    default_state_table: str,
    default_tz: str = "America/New_York",
    include_tz: bool = True,
    include_fail_on_gaps: bool = False,
) -> argparse.ArgumentParser:
    """
    Create standard argument parser for bar builders.

    Eliminates CLI parsing duplication across all 5 bar builders.
    Extracted Jan 2026 to save ~50 lines × 5 builders = 250 lines.

    Args:
        description: Script description for help text
        default_daily_table: Default daily price table name
        default_bars_table: Default output bars table name
        default_state_table: Default state tracking table name
        default_tz: Default timezone for calendar builders
        include_tz: Add --tz flag (for calendar builders)
        include_fail_on_gaps: Add --fail-on-internal-gaps (for anchored builders)

    Returns:
        Configured ArgumentParser with standard bar builder arguments

    Example:
        >>> ap = create_bar_builder_argument_parser(
        ...     description="Build multi-TF bars",
        ...     default_daily_table="public.cmc_price_histories7",
        ...     default_bars_table="public.cmc_price_bars_multi_tf",
        ...     default_state_table="public.cmc_price_bars_multi_tf_state",
        ...     include_tz=False,
        ... )
        >>> args = ap.parse_args()
    """
    import argparse

    ap = argparse.ArgumentParser(description=description)

    # Required arguments
    ap.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="'all' or list of ids (space/comma separated).",
    )

    # Optional DB/table arguments
    ap.add_argument(
        "--db-url",
        default=None,
        help="Optional DB URL override. Defaults to TARGET_DB_URL env.",
    )
    ap.add_argument(
        "--daily-table",
        default=default_daily_table,
        help=f"Daily price table (default: {default_daily_table})",
    )
    ap.add_argument(
        "--bars-table",
        default=default_bars_table,
        help=f"Output bars table (default: {default_bars_table})",
    )
    ap.add_argument(
        "--state-table",
        default=default_state_table,
        help=f"State tracking table (default: {default_state_table})",
    )

    # Optional timezone argument (for calendar builders)
    if include_tz:
        ap.add_argument(
            "--tz",
            default=default_tz,
            help=f"Timezone for calendar alignment (default: {default_tz})",
        )

    # Optional processing arguments
    ap.add_argument(
        "--num-processes",
        type=int,
        default=None,
        help="Worker processes (default: auto-detect, max 6)",
    )
    ap.add_argument(
        "--full-rebuild",
        action="store_true",
        help="If set, delete+rebuild snapshots for all requested ids/tfs.",
    )

    # Optional fail-on-gaps argument (for anchored builders)
    if include_fail_on_gaps:
        ap.add_argument(
            "--fail-on-internal-gaps",
            action="store_true",
            help="Fail if missing-days occur in the interior of a window.",
        )

    # Legacy compatibility flag
    ap.add_argument(
        "--parallel",
        action="store_true",
        help="(Legacy/no-op) Kept for pipeline compatibility",
    )

    return ap


def load_periods(
    engine: Engine,
    periods_arg: str,
    *,
    lut_table: str = "public.ema_alpha_lookup",
) -> list[int]:
    """
    Load EMA periods from argument or lookup table.

    Args:
        engine: SQLAlchemy engine
        periods_arg: Either comma-separated periods (e.g., "6,9,12") or "lut" to load from table
        lut_table: Table to query when periods_arg="lut" (default: public.ema_alpha_lookup)

    Returns:
        List of integer periods
    """
    if periods_arg.strip().lower() == "lut":
        with engine.begin() as conn:
            rows = conn.execute(
                text(f"SELECT DISTINCT period FROM {lut_table} ORDER BY 1;")
            ).fetchall()
        if not rows:
            raise RuntimeError(f"No periods found in {lut_table}.")
        return [int(r[0]) for r in rows]

    return [int(x.strip()) for x in periods_arg.split(",") if x.strip()]


# =============================================================================
# 11) Bar builder common database utilities (extracted from builders)
# =============================================================================


def load_daily_prices_for_id(
    *,
    db_url: str,
    daily_table: str,
    id_: int,
    ts_start: pd.Timestamp | None = None,
    tz: str = "America/New_York",
) -> pd.DataFrame:
    """
    Load daily OHLCV rows for a single id from the daily table.

    - If ts_start is provided, only loads rows with timestamp >= ts_start
    - Returns rows ordered ascending by timestamp
    - Normalizes to include a 'ts' column (tz-aware UTC)
    - Enforces 1-row-per-local-day invariant

    IDENTICAL across all 5 bar builders - extracted to eliminate duplication.

    Args:
        db_url: Database connection string
        daily_table: Daily price table name
        id_: Cryptocurrency ID
        ts_start: Optional start timestamp (only load rows >= this)
        tz: Timezone for local day validation (default: America/New_York)

    Returns:
        DataFrame with daily OHLCV data, ts column in UTC
    """
    if ts_start is None:
        where = "WHERE id = :id"
        params = {"id": int(id_)}
    else:
        where = 'WHERE id = :id AND "timestamp" >= :ts_start'
        params = {"id": int(id_), "ts_start": ts_start}

    sql = text(
        f"""
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
    """
    )

    eng = get_engine(db_url)
    with eng.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return df

    # Timestamp normalization: keep tz-aware UTC so tz_convert(tz) works downstream
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="raise")

    for col in ["timehigh", "timelow", "timeopen", "timeclose", "timestamp"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    # Hard invariant (shared contract)
    assert_one_row_per_local_day(df, ts_col="ts", tz=tz, id_col="id")

    return df


def delete_bars_for_id_tf(
    db_url: str,
    bars_table: str,
    *,
    id_: int,
    tf: str,
) -> None:
    """
    Delete all bar snapshots for a specific (id, tf) combination.

    Used in full rebuild mode to clear existing bars before regeneration.

    Args:
        db_url: Database connection string
        bars_table: Bar snapshots table name
        id_: Cryptocurrency ID
        tf: Timeframe string (e.g., "7d", "1w_iso")
    """
    sql = text(f"DELETE FROM {bars_table} WHERE id = :id AND tf = :tf;")
    eng = get_engine(db_url)
    with eng.begin() as conn:
        conn.execute(sql, {"id": int(id_), "tf": tf})


def load_last_snapshot_row(
    db_url: str,
    bars_table: str,
    *,
    id_: int,
    tf: str,
) -> dict | None:
    """
    Load the most recent snapshot row for (id, tf) by time_close DESC.

    Used for incremental updates to find the last known bar state.

    Args:
        db_url: Database connection string
        bars_table: Bar snapshots table name
        id_: Cryptocurrency ID
        tf: Timeframe string

    Returns:
        Dictionary of last snapshot row, or None if no rows exist
    """
    sql = text(
        f"""
      SELECT *
      FROM {bars_table}
      WHERE id = :id AND tf = :tf
      ORDER BY time_close DESC
      LIMIT 1;
    """
    )
    eng = get_engine(db_url)
    with eng.connect() as conn:
        row = conn.execute(sql, {"id": int(id_), "tf": tf}).mappings().first()
    return dict(row) if row else None


def load_last_snapshot_info_for_id_tfs(
    db_url: str,
    bars_table: str,
    *,
    id_: int,
    tfs: list[str],
) -> dict[str, dict]:
    """
    Batch-load latest snapshot info for a single id across multiple timeframes.

    Uses PostgreSQL DISTINCT ON for efficiency (1 query instead of N queries).
    Critical for performance in incremental mode.

    Args:
        db_url: Database connection string
        bars_table: Bar snapshots table name
        id_: Cryptocurrency ID
        tfs: List of timeframe strings to query

    Returns:
        Dictionary mapping tf -> {last_bar_seq, last_time_close}
        Empty dict if no snapshots found
    """
    if not tfs:
        return {}

    sql = text(
        f"""
      SELECT DISTINCT ON (tf)
        tf,
        bar_seq AS last_bar_seq,
        time_close AS last_time_close
      FROM {bars_table}
      WHERE id = :id AND tf = ANY(:tfs)
      ORDER BY tf, time_close DESC;
    """
    )
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


# =============================================================================
# 12) Multi-TF reject table utilities (GAP-C01: OHLC repair audit trail)
# =============================================================================


def create_rejects_table_ddl(table_name: str, schema: str = "public") -> str:
    """
    Generate DDL for multi-TF bar rejects table.

    Schema includes:
    - violation_type: What was wrong (high_lt_low, high_lt_oc_max, etc.)
    - repair_action: What was done to fix it (high_low_swapped, high_adjusted, etc.)
    - Original OHLCV values before repair for audit trail

    Args:
        table_name: Name of rejects table to create
        schema: Database schema (default: public)

    Returns:
        DDL string to create rejects table
    """
    full_name = f"{schema}.{table_name}" if schema else table_name
    return f"""
CREATE TABLE IF NOT EXISTS {full_name} (
    id                  INTEGER NOT NULL,
    tf                  TEXT NOT NULL,
    bar_seq             INTEGER NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    violation_type      TEXT NOT NULL,
    repair_action       TEXT NOT NULL,
    original_open       DOUBLE PRECISION,
    original_high       DOUBLE PRECISION,
    original_low        DOUBLE PRECISION,
    original_close      DOUBLE PRECISION,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, tf, bar_seq, timestamp, violation_type)
);
"""


def detect_ohlc_violations(row: dict) -> list[tuple[str, str]]:
    """
    Detect OHLC violations and return list of (violation_type, repair_action) tuples.

    Implementation logic (matching enforce_ohlc_sanity from lines 782-854):

    Args:
        row: Dictionary with OHLCV keys (open, high, low, close)

    Returns:
        List of (violation_type, repair_action) tuples for detected violations
    """
    violations = []
    o, h, low, c = (
        row.get("open"),
        row.get("high"),
        row.get("low"),
        row.get("close"),
    )

    # Skip if any value is None/NaN
    if any(
        v is None or (isinstance(v, float) and math.isnan(v)) for v in [o, h, low, c]
    ):
        return violations

    oc_min = min(o, c)
    oc_max = max(o, c)

    # Check 1: high < low (enforce_ohlc_sanity handles this via clamping which effectively swaps)
    if h < low:
        violations.append(("high_lt_low", "values_will_be_clamped"))

    # Check 2: high < max(open, close) -> high will be clamped up (line 839-841)
    if h < oc_max:
        violations.append(("high_lt_oc_max", "high_clamped_to_oc_max"))

    # Check 3: low > min(open, close) -> low will be clamped down (line 844-852)
    if low > oc_min:
        violations.append(("low_gt_oc_min", "low_clamped_to_oc_min"))

    return violations


def log_to_rejects(
    engine: Engine,
    rejects_table: str,
    records: list[dict],
    schema: str = "public",
) -> int:
    """
    Insert reject records to rejects table.

    Each record should have:
    - id, tf, bar_seq, timestamp
    - violation_type, repair_action
    - original_open, original_high, original_low, original_close (before repair)

    Args:
        engine: SQLAlchemy engine
        rejects_table: Name of rejects table
        records: List of reject record dictionaries
        schema: Database schema (default: public)

    Returns:
        Number of records inserted
    """
    if not records:
        return 0

    full_name = f"{schema}.{rejects_table}" if schema else rejects_table

    # Build INSERT statement
    sql = text(
        f"""
        INSERT INTO {full_name} (
            id, tf, bar_seq, timestamp, violation_type, repair_action,
            original_open, original_high, original_low, original_close
        )
        VALUES (
            :id, :tf, :bar_seq, :timestamp, :violation_type, :repair_action,
            :original_open, :original_high, :original_low, :original_close
        )
        ON CONFLICT (id, tf, bar_seq, timestamp, violation_type) DO NOTHING;
        """
    )

    with engine.begin() as conn:
        conn.execute(sql, records)

    return len(records)
