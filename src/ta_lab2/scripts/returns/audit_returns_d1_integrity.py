from __future__ import annotations

r"""
audit_returns_d1_integrity.py

Integrity audit for public.cmc_returns_d1 built from public.cmc_price_histories7.

Checks:
  1) Coverage: returns rows per id == price_histories rows per id - 1
  2) No duplicate (id, time_close)
  3) Spacing sanity: gap_days >= 1 and mostly 1; report any > 1
  4) Null policy: prev_close is never NULL; ret_* not NULL except for edge cases (zeros/negatives)
  5) Time alignment: returns timestamps are within price_histories7 timestamps

runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_d1_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args=""
)

Outputs:
  - Prints summary tables to stdout
"""

import argparse
import os
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_RET_TABLE = "public.cmc_returns_d1"


def _print(msg: str) -> None:
    print(f"[audit_returns_d1] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


@dataclass(frozen=True)
class AuditConfig:
    db_url: str
    daily_table: str
    ret_table: str


def _df(engine: Engine, sql: str) -> pd.DataFrame:
    with engine.begin() as cxn:
        return pd.read_sql(text(sql), cxn)


def main() -> None:
    p = argparse.ArgumentParser(description="Audit integrity for cmc_returns_d1.")
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE)
    p.add_argument("--ret-table", default=DEFAULT_RET_TABLE)
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    cfg = AuditConfig(
        db_url=db_url, daily_table=args.daily_table, ret_table=args.ret_table
    )
    engine = _get_engine(cfg.db_url)

    _print(f"daily={cfg.daily_table}")
    _print(f"ret={cfg.ret_table}")

    # 1) Coverage (per id)
    coverage_sql = f"""
    WITH ph AS (
      SELECT id, COUNT(*) AS n_ph
      FROM {cfg.daily_table}
      GROUP BY 1
    ),
    rt AS (
      SELECT id, COUNT(*) AS n_rt
      FROM {cfg.ret_table}
      GROUP BY 1
    )
    SELECT
      ph.id,
      ph.n_ph,
      COALESCE(rt.n_rt, 0) AS n_rt,
      (ph.n_ph - 1) AS expected_rt,
      (COALESCE(rt.n_rt, 0) - (ph.n_ph - 1)) AS diff
    FROM ph
    LEFT JOIN rt USING (id)
    ORDER BY ph.id;
    """
    cov = _df(engine, coverage_sql)
    _print("Coverage (n_rt vs n_ph-1):")
    print(cov.to_string(index=False))

    bad_cov = cov[cov["diff"] != 0]
    if not bad_cov.empty:
        _print("FAIL: coverage mismatches found:")
        print(bad_cov.to_string(index=False))
    else:
        _print("PASS: coverage matches for all ids.")

    # 2) Duplicate keys
    dup_sql = f"""
    SELECT id, time_close, COUNT(*) AS n
    FROM {cfg.ret_table}
    GROUP BY 1,2
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, time_close
    LIMIT 50;
    """
    dups = _df(engine, dup_sql)
    if len(dups) > 0:
        _print("FAIL: duplicate (id,time_close) found (showing up to 50):")
        print(dups.to_string(index=False))
    else:
        _print("PASS: no duplicate (id,time_close).")

    # 3) Gap days sanity
    gap_sql = f"""
    SELECT
      id,
      COUNT(*) AS n_rows,
      SUM((gap_days IS NULL)::int) AS n_gap_null,
      SUM((gap_days < 1)::int) AS n_gap_lt1,
      SUM((gap_days = 1)::int) AS n_gap_eq1,
      SUM((gap_days > 1)::int) AS n_gap_gt1,
      MAX(gap_days) AS max_gap_days
    FROM {cfg.ret_table}
    GROUP BY 1
    ORDER BY id;
    """
    gaps = _df(engine, gap_sql)
    _print("Gap days summary:")
    print(gaps.to_string(index=False))

    # Show a small sample of gap anomalies
    gap_anom_sql = f"""
    SELECT id, time_close, gap_days, prev_close, close, ret_arith, ret_log
    FROM {cfg.ret_table}
    WHERE gap_days IS NULL OR gap_days < 1 OR gap_days > 1
    ORDER BY id, time_close
    LIMIT 50;
    """
    gap_anom = _df(engine, gap_anom_sql)
    if len(gap_anom) > 0:
        _print("WARN: gap anomalies (showing up to 50):")
        print(gap_anom.to_string(index=False))
    else:
        _print("PASS: no gap anomalies (all gap_days == 1).")

    # 4) Null policy checks
    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      SUM((prev_close IS NULL)::int) AS n_prev_close_null,
      SUM((ret_arith IS NULL)::int) AS n_ret_arith_null,
      SUM((ret_log IS NULL)::int) AS n_ret_log_null
    FROM {cfg.ret_table};
    """
    nulls = _df(engine, nulls_sql)
    _print("Null counts:")
    print(nulls.to_string(index=False))

    # 5) Alignment: every returns timestamp exists in price table for same id
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {cfg.ret_table} r
    LEFT JOIN {cfg.daily_table} p
      ON p.id = r.id AND p.timeclose = r.time_close
    WHERE p.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _print(
            f"FAIL: {n_missing} returns rows have no matching (id,timeclose) in price_histories7."
        )
    else:
        _print("PASS: all returns timestamps align to price_histories7.")

    _print("Audit complete.")


if __name__ == "__main__":
    main()
