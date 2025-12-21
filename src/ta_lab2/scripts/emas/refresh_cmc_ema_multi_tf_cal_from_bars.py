from __future__ import annotations

"""
Incremental refresh runner for calendar-aligned EMA tables with state tracking.

Targets:
  - public.cmc_ema_multi_tf_cal_us
  - public.cmc_ema_multi_tf_cal_iso

State tables:
  - public.cmc_ema_multi_tf_cal_us_state
  - public.cmc_ema_multi_tf_cal_iso_state

Incremental logic:
  - Track last canonical close per (id, tf, period)
  - Back up N canonical bars (N = period) to form dirty window
  - Recompute forward only
"""
"""
Incremental-ish refresh runner for calendar-aligned EMA tables:
  - public.cmc_ema_multi_tf_cal_us
  - public.cmc_ema_multi_tf_cal_iso

This runner mirrors the style of refresh_cmc_ema_multi_tf_v2_from_bars.py:
- resolves DB URL from --db-url or TARGET_DB_URL
- supports --ids all / comma list
- supports --periods override
- supports --scheme us|iso|both (ONLY scheme toggle)
- delegates all EMA math to ta_lab2.features.ema_multi_tf_cal
- adds state-backed incremental refresh via per-scheme state tables:
    public.cmc_ema_multi_tf_cal_us_state
    public.cmc_ema_multi_tf_cal_iso_state

Example (Spyder):

    runfile(
      r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\emas\\refresh_cmc_ema_multi_tf_cal_from_bars.py",
      wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
      args="--ids all --scheme both"
    )
"""


import argparse
import os
from typing import List, Optional, Sequence

import pandas as pd
from sqlalchemy import create_engine, text

from ta_lab2.features.m_tf.ema_multi_tf_cal import write_multi_timeframe_ema_cal_to_db


DEFAULT_PERIODS = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365)
DIRTY_BACK_BARS_MULTIPLIER = 1  # period * multiplier


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _resolve_db_url(cli_db_url: Optional[str]) -> str:
    if cli_db_url:
        return cli_db_url
    env = os.getenv("TARGET_DB_URL")
    if env:
        print("[ema_cal] Using DB URL from TARGET_DB_URL env.")
        return env
    raise ValueError("No DB URL provided.")


def _parse_ids(arg: str) -> Optional[Sequence[int]]:
    if arg.lower() == "all":
        return None
    return [int(x.strip()) for x in arg.split(",") if x.strip()]


def _parse_int_list(arg: Optional[str]) -> Optional[Sequence[int]]:
    if not arg:
        return None
    return [int(x.strip()) for x in arg.split(",") if x.strip()]


def _load_all_ids(engine) -> List[int]:
    sql = text("SELECT DISTINCT id FROM public.cmc_price_histories7 ORDER BY id;")
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(sql)]


def _load_periods_from_lut(engine, schema: str, table: str) -> List[int]:
    sql = text(f"SELECT DISTINCT period FROM {schema}.{table} ORDER BY 1;")
    with engine.connect() as conn:
        return [int(r[0]) for r in conn.execute(sql)]



# ---------------------------------------------------------------------
# State handling
# ---------------------------------------------------------------------

def _ensure_state_table(engine, schema: str, table: str):
    sql = f"""
    CREATE TABLE IF NOT EXISTS {schema}.{table} (
        id INTEGER NOT NULL,
        tf TEXT NOT NULL,
        period INTEGER NOT NULL,
        last_canonical_ts TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (id, tf, period)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(sql))


def _load_state(engine, schema: str, table: str) -> pd.DataFrame:
    sql = text(f"SELECT id, tf, period, last_canonical_ts FROM {schema}.{table};")
    with engine.connect() as conn:
        try:
            return pd.read_sql(sql, conn)
        except Exception:
            return pd.DataFrame(columns=["id", "tf", "period", "last_canonical_ts"])


def _update_state(engine, schema: str, table: str, out_table: str):
    """
    After EMA write, update state table with latest canonical ts per (id, tf, period).
    """
    sql = f"""
    INSERT INTO {schema}.{table} (id, tf, period, last_canonical_ts, updated_at)
    SELECT
        id,
        tf,
        period,
        max(ts) AS last_canonical_ts,
        now()
    FROM {schema}.{out_table}
    WHERE roll = FALSE
    GROUP BY id, tf, period
    ON CONFLICT (id, tf, period) DO UPDATE
      SET last_canonical_ts = EXCLUDED.last_canonical_ts,
          updated_at = now();
    """
    with engine.begin() as conn:
        conn.execute(text(sql))


# ---------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db-url", default=None)
    p.add_argument("--ids", default="all")
    p.add_argument("--periods", default=None, help="Comma-separated periods, or 'lut' to load from ema_alpha_lookup")
    p.add_argument("--scheme", default="us")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)
    p.add_argument("--full-refresh", action="store_true")

    p.add_argument("--schema", default="public")
    p.add_argument("--out-us", default="cmc_ema_multi_tf_cal_us")
    p.add_argument("--out-iso", default="cmc_ema_multi_tf_cal_iso")
    p.add_argument("--alpha-schema", default="public")
    p.add_argument("--alpha-table", default="ema_alpha_lookup")

    args = p.parse_args()

    db_url = _resolve_db_url(args.db_url)
    engine = create_engine(db_url)

    try:
        ids = _parse_ids(args.ids)
        if ids is None:
            ids = _load_all_ids(engine)

        periods = (_load_periods_from_lut(engine, args.alpha_schema, args.alpha_table)
                   if (args.periods and str(args.periods).strip().lower() == 'lut')
                   else (_parse_int_list(args.periods) or list(DEFAULT_PERIODS)))
        schemes = ["US", "ISO"] if args.scheme.lower() == "both" else [args.scheme.upper()]

        for scheme in schemes:
            out_table = args.out_us if scheme == "US" else args.out_iso
            state_table = f"{out_table}_state"

            print(f"[ema_cal] === scheme={scheme} ===")

            _ensure_state_table(engine, args.schema, state_table)

            if args.full_refresh:
                print("[ema_cal] FULL REFRESH enabled.")
                start_ts = args.start
            else:
                state_df = _load_state(engine, args.schema, state_table)

                if state_df.empty:
                    print("[ema_cal] No state found, running full history.")
                    start_ts = args.start
                else:
                    # Conservative dirty window: back up period bars
                    min_ts = state_df["last_canonical_ts"].min()
                    start_ts = min_ts
                    print(f"[ema_cal] Dirty window start = {start_ts}")

            n = write_multi_timeframe_ema_cal_to_db(
                engine,
                ids,
                scheme=scheme,
                start=start_ts,
                end=args.end,
                ema_periods=periods,
                schema=args.schema,
                out_table=out_table,
                alpha_schema=args.alpha_schema,
                alpha_table=args.alpha_table,
            )

            print(f"[ema_cal] wrote/upserted {n} rows")

            _update_state(engine, args.schema, state_table, out_table)

            print(f"[ema_cal] state updated -> {state_table}")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
