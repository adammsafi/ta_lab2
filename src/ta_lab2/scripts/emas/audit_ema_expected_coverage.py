from __future__ import annotations
# -*- coding: utf-8 -*-

"""
audit_ema_expected_coverage.py

Coverage audit: compare expected (id, tf, period) combos vs what exists in each EMA table.

Fixes (2025-12-21):
- dim_timeframe.calendar_anchor is now BOOLEAN (NULL for tf_day, TRUE for anchored, FALSE for aligned).
- CAL_US/CAL_ISO TF selection MUST NOT use roll_policy != 'calendar_anchor' (that returned 0 before).
- CAL vs CAL_ANCHOR is now selected using calendar_anchor boolean + TF naming rules:
    * Weeks: scheme-specific suffixes: *_CAL_US, *_CAL_ISO, *_CAL_ANCHOR_US, *_CAL_ANCHOR_ISO
    * Months/Years: scheme-agnostic: *_CAL and *_CAL_ANCHOR

Expected TFs:
- multi_tf: dim_timeframe alignment_type='tf_day'
- cal_us/cal_iso: dim_timeframe alignment_type='calendar', calendar_anchor=FALSE
- cal_anchor_us/cal_anchor_iso: dim_timeframe alignment_type='calendar', calendar_anchor=TRUE

Expected periods:
- default: from public.ema_alpha_lookup (distinct period)
  (override with --periods "10,21,50")
"""

import argparse
import os
from datetime import UTC, datetime
from typing import List

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ta_lab2.features.m_tf.polars_helpers import read_sql_polars


DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_DIM_TF = "public.dim_timeframe"
DEFAULT_LUT = "public.ema_alpha_lookup"

EMA_TABLES = {
    "public.cmc_ema_multi_tf": "TF_DAY",
    "public.cmc_ema_multi_tf_cal_us": "CAL_US",
    "public.cmc_ema_multi_tf_cal_iso": "CAL_ISO",
    "public.cmc_ema_multi_tf_cal_anchor_us": "ANCHOR_US",
    "public.cmc_ema_multi_tf_cal_anchor_iso": "ANCHOR_ISO",
}


def _log(msg: str) -> None:
    print(f"[ema_cov] {msg}")


def get_engine() -> Engine:
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL env var is required.")
    _log("Using DB URL from TARGET_DB_URL env.")
    return create_engine(db_url, future=True)


def parse_ids(engine: Engine, ids_arg: str, daily_table: str) -> List[int]:
    if ids_arg.strip().lower() == "all":
        df = read_sql_polars(
            f"SELECT DISTINCT id FROM {daily_table} ORDER BY id", engine
        )
        ids = [int(x) for x in df["id"].tolist()]
        _log(f"Loaded ALL ids from {daily_table}: {len(ids)}")
        return ids

    ids: List[int] = []
    for p in ids_arg.split(","):
        p = p.strip()
        if p:
            ids.append(int(p))
    if not ids:
        raise ValueError("No ids parsed.")
    return ids


def load_periods(engine: Engine, periods_arg: str, lut_table: str) -> List[int]:
    s = (periods_arg or "").strip().lower()
    if s == "lut":
        df = read_sql_polars(
            f"SELECT DISTINCT period::int AS period FROM {lut_table} ORDER BY period",
            engine,
        )
        periods = [int(x) for x in df["period"].tolist()]
        _log(f"Loaded periods from {lut_table}: {len(periods)}")
        return periods

    periods: List[int] = []
    for p in s.split(","):
        p = p.strip()
        if p:
            periods.append(int(p))
    if not periods:
        raise ValueError("No periods parsed.")
    return periods


def load_tfs(engine: Engine, family: str, dim_tf_table: str) -> List[str]:
    """
    Return TF list per family using NEW dim_timeframe semantics:
      - tf_day: alignment_type='tf_day'
      - calendar aligned: calendar_anchor=FALSE
      - calendar anchored: calendar_anchor=TRUE

    Naming rules used (robust against roll_policy overloading):
      - Weeks are scheme-specific: *_CAL_US / *_CAL_ISO and *_CAL_ANCHOR_US / *_CAL_ANCHOR_ISO
      - Months/Years are scheme-agnostic: *_CAL and *_CAL_ANCHOR
    """
    if family == "TF_DAY":
        q = f"""
            SELECT tf
            FROM {dim_tf_table}
            WHERE alignment_type = 'tf_day'
              AND is_canonical = TRUE
            ORDER BY display_order, sort_order, tf
            """
        df = read_sql_polars(q, engine)
        return [str(x) for x in df["tf"].tolist()]

    if family in {"CAL_US", "CAL_ISO"}:
        scheme = "US" if family == "CAL_US" else "ISO"
        q = f"""
            SELECT tf
            FROM {dim_tf_table}
            WHERE alignment_type = 'calendar'
              AND calendar_anchor = FALSE
              AND is_canonical = TRUE
              AND allow_partial_start = FALSE
              AND allow_partial_end   = FALSE
              AND tf NOT LIKE '%\\_CAL\\_ANCHOR\\_%' ESCAPE '\\'
              AND tf NOT LIKE '%\\_ANCHOR%' ESCAPE '\\'
              AND (
                    -- scheme-specific weeks
                    (base_unit = 'W' AND tf ~ ('_CAL_' || :scheme || '$'))
                    OR
                    -- scheme-agnostic months/years
                    (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
                  )
            ORDER BY display_order, sort_order, tf
            """
        df = read_sql_polars(q, engine, params={"scheme": scheme})
        return [str(x) for x in df["tf"].tolist()]

    if family in {"ANCHOR_US", "ANCHOR_ISO"}:
        scheme = "US" if family == "ANCHOR_US" else "ISO"
        q = f"""
            SELECT tf
            FROM {dim_tf_table}
            WHERE alignment_type = 'calendar'
              AND calendar_anchor = TRUE
              AND is_canonical = TRUE
              AND allow_partial_start = TRUE
              AND allow_partial_end   = TRUE
              AND (
                    -- scheme-specific anchored weeks
                    (base_unit = 'W' AND tf ~ ('_CAL_ANCHOR_' || :scheme || '$'))
                    OR
                    -- scheme-agnostic anchored months/years
                    (base_unit IN ('M','Y') AND tf ~ '_CAL_ANCHOR$')
                  )
            ORDER BY display_order, sort_order, tf
            """
        df = read_sql_polars(q, engine, params={"scheme": scheme})
        return [str(x) for x in df["tf"].tolist()]

    raise ValueError(f"Unknown family: {family}")


def actual_combos(engine: Engine, ema_table: str, ids: List[int]) -> pd.DataFrame:
    # NOTE: using IN (...) is fine for your small id list (7). Keep it simple.
    in_clause = ",".join(str(int(i)) for i in ids)
    q = f"""
        SELECT DISTINCT id::int AS id, tf::text AS tf, period::int AS period
        FROM {ema_table}
        WHERE id IN ({in_clause})
        """
    return read_sql_polars(q, engine)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Coverage audit for EMA tables (expected vs actual combos)."
    )
    ap.add_argument("--ids", required=True, help="all OR comma-separated list")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE)
    ap.add_argument("--dim-tf", default=DEFAULT_DIM_TF)
    ap.add_argument("--lut", default=DEFAULT_LUT)
    ap.add_argument("--periods", default="lut", help="lut or comma list")
    ap.add_argument("--out", default="ema_expected_coverage.csv")
    args = ap.parse_args()

    eng = get_engine()
    ids = parse_ids(eng, args.ids, args.daily_table)
    periods = load_periods(eng, args.periods, args.lut)

    rows = []
    for ema_table, family in EMA_TABLES.items():
        tfs = load_tfs(eng, family, args.dim_tf)

        exp = len(ids) * len(tfs) * len(periods)
        act_df = actual_combos(eng, ema_table, ids)
        act = len(act_df)

        missing = max(exp - act, 0)
        miss_share = (missing / exp) if exp else 0.0

        rows.append(
            {
                "table_name": ema_table,
                "family": family,
                "n_ids": len(ids),
                "n_tfs": len(tfs),
                "n_periods": len(periods),
                "n_expected_combos": exp,
                "n_actual_combos": act,
                "n_missing_combos": missing,
                "missing_share": round(miss_share, 8),
                "audit_generated_at": datetime.now(UTC).isoformat(),
            }
        )

    out_df = pd.DataFrame(rows).sort_values(["table_name"]).reset_index(drop=True)
    out_df.to_csv(args.out, index=False)
    _log(f"Wrote {len(out_df)} rows -> {args.out}")


if __name__ == "__main__":
    main()
