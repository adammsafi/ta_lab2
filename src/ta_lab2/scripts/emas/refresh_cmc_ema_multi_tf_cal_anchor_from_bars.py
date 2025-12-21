from __future__ import annotations

"""
refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py

Runner for anchored calendar EMA refresh (US / ISO) WITH state tables.

Writes to:
  public.cmc_ema_multi_tf_cal_anchor_us
  public.cmc_ema_multi_tf_cal_anchor_iso

State tables (per scheme):
  public.cmc_ema_multi_tf_cal_anchor_us_state
  public.cmc_ema_multi_tf_cal_anchor_iso_state

Incremental logic:
  - Track last canonical close per (id, tf, period)
  - For CAL_ANCHOR, canonical closes are: roll_bar = FALSE
  - If state exists: dirty window start = MIN(last_canonical_ts) (scoped to selected ids)
  - If no state (or --full-refresh): run from --start

Hardening added vs the earlier pasted version:
  1) State table tolerant of nullable last_canonical_ts (CREATE won't "fix" existing tables).
     Runner drops NULL watermarks before computing dirty window.
  2) Watermark is scoped to selected ids (so unrelated ids can't drag start backward).
  3) State update validates that output table contains required columns (ts + roll_bar).
     (Optionally supports alternate timestamp column names if you extend TS_CANDIDATES.)
"""

import argparse
import os
import sys
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.features.m_tf.ema_multi_tf_cal_anchor import (
    write_multi_timeframe_ema_cal_anchor_to_db,
)


# ---------------------------------------------------------------------
# Environment / IPython helper
# ---------------------------------------------------------------------

def _in_ipython() -> bool:
    try:
        from IPython import get_ipython  # type: ignore
        return get_ipython() is not None
    except Exception:
        return False


def _resolve_db_url() -> str:
    db_url = os.getenv("TARGET_DB_URL") or os.getenv("MARKETDATA_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL (preferred) or MARKETDATA_DB_URL must be set.")
    src = "TARGET_DB_URL" if os.getenv("TARGET_DB_URL") else "MARKETDATA_DB_URL"
    print(f"[ema_anchor] Using DB URL from {src} env.")
    return db_url


# ---------------------------------------------------------------------
# Basic helpers
# ---------------------------------------------------------------------

def _load_ids(engine: Engine, schema: str, daily_table: str, ids_arg: str) -> List[int]:
    ids_arg = (ids_arg or "").strip().lower()
    if ids_arg in {"all", "*"}:
        sql = text(f"SELECT DISTINCT id FROM {schema}.{daily_table} ORDER BY id ASC")
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return [int(r[0]) for r in rows]

    parts = [p.strip() for p in ids_arg.split(",") if p.strip()]
    if not parts:
        raise ValueError("No ids provided. Use --ids all or --ids 1,52,1027,...")
    return [int(p) for p in parts]


def _load_periods_from_lut(
    engine: Engine,
    *,
    schema: str = "public",
    table: str = "ema_alpha_lookup",
) -> List[int]:
    sql = text(f"SELECT DISTINCT period FROM {schema}.{table} ORDER BY period ASC")
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


# ---------------------------------------------------------------------
# Output schema validation (ts + roll_bar)
# ---------------------------------------------------------------------

# If you ever rename the timestamp column, add candidates here.
TS_CANDIDATES = ("ts",)  # could extend to: ("ts", "time_close", "time_end")


def _get_table_columns(engine: Engine, schema: str, table: str) -> List[str]:
    sql = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name   = :table
        ORDER BY ordinal_position;
        """
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"schema": schema, "table": table}).fetchall()
    return [str(r[0]) for r in rows]


def _pick_ts_column(cols: List[str]) -> Optional[str]:
    cols_set = {c.lower() for c in cols}
    for cand in TS_CANDIDATES:
        if cand.lower() in cols_set:
            # return the canonical spelling from candidates
            return cand
    return None


def _require_output_schema(engine: Engine, schema: str, out_table: str) -> tuple[str, str]:
    """
    Returns (ts_col, roll_flag_col) after validating the output schema.
    """
    cols = _get_table_columns(engine, schema, out_table)
    cols_l = {c.lower() for c in cols}

    ts_col = _pick_ts_column(cols)
    if not ts_col:
        raise RuntimeError(
            f"[ema_anchor] Output table {schema}.{out_table} missing timestamp column. "
            f"Expected one of: {TS_CANDIDATES}. Found columns: {cols}"
        )

    roll_flag_col = "roll_bar"
    if roll_flag_col.lower() not in cols_l:
        raise RuntimeError(
            f"[ema_anchor] Output table {schema}.{out_table} missing '{roll_flag_col}' column. "
            f"Found columns: {cols}"
        )

    return ts_col, roll_flag_col


# ---------------------------------------------------------------------
# State handling (EMA state tables: (id, tf, period) -> last_canonical_ts)
# ---------------------------------------------------------------------

def _ensure_state_table(engine: Engine, schema: str, table: str) -> None:
    """
    Important: keep last_canonical_ts NULLABLE for compatibility with pre-existing tables
    that might have been created with NULL allowed.
    The runner will drop NULLs before computing dirty window.
    """
    sql = f"""
    CREATE TABLE IF NOT EXISTS {schema}.{table}
    (
        id integer NOT NULL,
        tf text NOT NULL,
        period integer NOT NULL,
        last_canonical_ts timestamp with time zone,
        updated_at timestamp with time zone NOT NULL DEFAULT now(),
        CONSTRAINT {table}_pkey PRIMARY KEY (id, tf, period)
    )
    """
    with engine.begin() as conn:
        conn.execute(text(sql))


def _load_state(engine: Engine, schema: str, table: str) -> pd.DataFrame:
    sql = text(f"SELECT id, tf, period, last_canonical_ts FROM {schema}.{table}")
    with engine.connect() as conn:
        try:
            df = pd.read_sql(sql, conn)
        except Exception:
            df = pd.DataFrame(columns=["id", "tf", "period", "last_canonical_ts"])
    return df


def _compute_dirty_start(
    state_df: pd.DataFrame,
    *,
    selected_ids: List[int],
    default_start: str,
    verbose: bool,
) -> str:
    """
    CAL-style conservative dirty window:
      start_ts = MIN(last_canonical_ts)
    but scoped to selected ids and ignoring NULL last_canonical_ts.
    """
    if state_df.empty:
        if verbose:
            print("[ema_anchor] No state found, running full history.")
        return default_start

    # Scope to ids being run, so other ids can't drag the run backward.
    if "id" in state_df.columns and selected_ids:
        state_df = state_df[state_df["id"].isin(selected_ids)]

    if state_df.empty:
        if verbose:
            print("[ema_anchor] State exists but has no rows for selected ids; running full history.")
        return default_start

    # Drop NULL/NaT watermarks
    state_df = state_df.dropna(subset=["last_canonical_ts"])
    if state_df.empty:
        if verbose:
            print("[ema_anchor] State has only NULL last_canonical_ts; running full history.")
        return default_start

    min_ts = pd.to_datetime(state_df["last_canonical_ts"]).min()
    if pd.isna(min_ts):
        if verbose:
            print("[ema_anchor] Computed min_ts is NaT; running full history.")
        return default_start

    if verbose:
        print(f"[ema_anchor] Dirty window start = {min_ts}")

    # The writer accepts strings; keep ISO format.
    return min_ts.isoformat()


def _update_state_anchor(engine: Engine, schema: str, state_table: str, out_table: str) -> None:
    """
    CAL_ANCHOR canonical closes are roll_bar = FALSE.
    This update assumes output table has the required columns; we validate first.
    """
    ts_col, roll_flag_col = _require_output_schema(engine, schema, out_table)

    sql = f"""
    INSERT INTO {schema}.{state_table} (id, tf, period, last_canonical_ts, updated_at)
    SELECT
        id,
        tf,
        period,
        max({ts_col}) AS last_canonical_ts,
        now()
    FROM {schema}.{out_table}
    WHERE {roll_flag_col} = FALSE
    GROUP BY id, tf, period
    ON CONFLICT (id, tf, period) DO UPDATE
      SET last_canonical_ts = EXCLUDED.last_canonical_ts,
          updated_at = now();
    """
    with engine.begin() as conn:
        conn.execute(text(sql))


# ---------------------------------------------------------------------
# CLI / Runner
# ---------------------------------------------------------------------

def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="refresh_cmc_ema_multi_tf_cal_anchor_from_bars")

    p.add_argument("--ids", default="all", help="all | comma-separated list, e.g. 1,52,1027")
    p.add_argument("--scheme", default="both", choices=["us", "iso", "both"], help="US, ISO, or both")

    p.add_argument("--schema", default="public")
    p.add_argument("--daily-table", default="cmc_price_histories7")

    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--end", default=None)

    p.add_argument(
        "--periods",
        default="6,9,10,12,14,17,20,21,26,30,50,52,77,100,200,252,365",
        help="comma-separated EMA periods, or 'lut' to load from public.ema_alpha_lookup",
    )

    p.add_argument("--no-update", action="store_true", help="If set, delete+rewrite range instead of upsert")
    p.add_argument("--full-refresh", action="store_true", help="Ignore state; run full history from --start.")
    p.add_argument("--quiet", action="store_true")

    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)

    try:
        db_url = _resolve_db_url()
    except Exception as e:
        print(f"[ema_anchor] ERROR: {e}", file=sys.stderr)
        return 1

    engine = create_engine(db_url, future=True)

    periods_arg = (args.periods or "").strip().lower()
    if periods_arg == "lut":
        periods = _load_periods_from_lut(engine, schema=args.schema, table="ema_alpha_lookup")
        if not periods:
            print("[ema_anchor] ERROR: ema_alpha_lookup returned no periods.", file=sys.stderr)
            return 1
    else:
        periods = [int(x.strip()) for x in args.periods.split(",") if x.strip()]

    scheme = args.scheme.upper()
    verbose = not args.quiet

    try:
        ids = _load_ids(engine, args.schema, args.daily_table, args.ids)
    except Exception as e:
        print(f"[ema_anchor] ERROR loading ids: {e}", file=sys.stderr)
        return 1

    if verbose:
        print(f"[ema_anchor] Loaded ids from {args.schema}.{args.daily_table}: {len(ids)}")
        print(f"[ema_anchor] schema={args.schema}")
        print(f"[ema_anchor] start={args.start} end={args.end}")
        print(f"[ema_anchor] periods={periods}")
        print(f"[ema_anchor] scheme={scheme.lower()}")

    total = 0

    def _run_one(s: str) -> int:
        out_table = f"cmc_ema_multi_tf_cal_anchor_{s.lower()}"
        state_table = f"{out_table}_state"  # cmc_ema_multi_tf_cal_anchor_us_state / _iso_state

        if verbose:
            print(f"[ema_anchor] === scheme={s} ===")
            print(f"[ema_anchor] out_table={args.schema}.{out_table}")
            print(f"[ema_anchor] state_table={args.schema}.{state_table}")

        _ensure_state_table(engine, args.schema, state_table)

        if args.full_refresh:
            if verbose:
                print("[ema_anchor] FULL REFRESH enabled.")
            start_ts = args.start
        else:
            state_df = _load_state(engine, args.schema, state_table)
            start_ts = _compute_dirty_start(
                state_df,
                selected_ids=ids,
                default_start=args.start,
                verbose=verbose,
            )

        # Optional: validate output schema *before* running writer
        # (Only do this if you are sure table exists. If the first run creates it, validation may fail.)
        # _require_output_schema(engine, args.schema, out_table)

        n = write_multi_timeframe_ema_cal_anchor_to_db(
            ids,
            calendar_scheme=s,
            start=start_ts,
            end=args.end,
            ema_periods=periods,
            db_url=db_url,
            schema=args.schema,
            daily_table=args.daily_table,
            out_table=out_table,
            update_existing=not args.no_update,
            verbose=verbose,
        )

        if verbose:
            print(f"[ema_anchor] scheme={s} wrote_rows={n}")

        # Update state AFTER write (requires output schema to match contract)
        _update_state_anchor(engine, args.schema, state_table, out_table)

        if verbose:
            print(f"[ema_anchor] state updated -> {state_table}")

        return int(n)

    try:
        if scheme == "BOTH":
            total += _run_one("US")
            total += _run_one("ISO")
        elif scheme == "US":
            total += _run_one("US")
        else:
            total += _run_one("ISO")

        if verbose:
            print(f"[ema_anchor] Done. total_written={total}")

        return 0
    except Exception as e:
        print(f"[ema_anchor] ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    code = main()

    # Avoid noisy "SystemExit: 0" in Spyder/IPython.
    if _in_ipython():
        pass
    else:
        raise SystemExit(code)
