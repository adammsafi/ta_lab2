from __future__ import annotations

r"""
audit_returns_ema_multi_tf_integrity.py

Integrity audit for EMA-returns built from:
  public.cmc_ema_multi_tf
into:
  public.cmc_returns_ema_multi_tf

Unified timeline: _ema/_ema_bar + _roll value columns.
PK: (id, ts, tf, period) — roll is a regular boolean column.

Checks:
  1) Coverage: n_ret == n_ema - 1 per (id, tf, period)
  2) Duplicates: no duplicate (id, ts, tf, period) in returns
  3) Gaps:
       - baseline: gap_days_roll >= 1
       - optional threshold: gap_days_roll <= gap_mult * tf_days_nominal
  4) Null policy:
       - _roll return columns should never be NULL (all rows)
       - non-roll return columns should never be NULL on roll=FALSE rows
  5) Alignment: every returns row must match an EMA row on (id, tf, period, ts)

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_ema_multi_tf_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--out-dir audits/returns --strict"
)
"""

import argparse
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_TABLE = "public.cmc_ema_multi_tf"
DEFAULT_RET_TABLE = "public.cmc_returns_ema_multi_tf"
DEFAULT_DIM_TIMEFRAME = "public.dim_timeframe"


def _print(msg: str) -> None:
    print(f"[audit_ret_ema_multi_tf] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _df(engine: Engine, sql: str) -> pd.DataFrame:
    with engine.begin() as cxn:
        return pd.read_sql(text(sql), cxn)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _resolve_out_name(out_arg: str, default_prefix: str) -> str:
    out_arg = (out_arg or "").strip()
    if out_arg:
        return out_arg
    return f"{default_prefix}_{_today_yyyymmdd()}"


def _fail_or_warn(strict: bool, msg: str) -> None:
    if strict:
        raise SystemExit(msg)
    _print(msg)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit integrity for cmc_returns_ema_multi_tf."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--ema-table", default=DEFAULT_EMA_TABLE)
    p.add_argument("--ret-table", default=DEFAULT_RET_TABLE)

    p.add_argument(
        "--out",
        default="",
        help="Base filename for CSV outputs (no extension). If empty, auto-dated.",
    )
    p.add_argument("--out-dir", default=".", help="Directory to write CSV outputs.")

    p.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any FAIL checks occur."
    )
    p.add_argument(
        "--dim-timeframe",
        default=DEFAULT_DIM_TIMEFRAME,
        help="dim_timeframe table (for gap thresholds).",
    )
    p.add_argument(
        "--gap-mult",
        type=float,
        default=1.5,
        help="Flag gaps where gap_days > gap_mult * tf_days_nominal.",
    )

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    engine = _get_engine(db_url)
    ema_table = args.ema_table
    ret_table = args.ret_table
    dim_tf = args.dim_timeframe
    gap_mult = float(args.gap_mult)
    strict = bool(args.strict)

    default_prefix = "audit_returns_ema_multi_tf"
    out_name = _resolve_out_name(args.out, default_prefix)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_base = out_dir / out_name

    _print(f"ema={ema_table}")
    _print(f"ret={ret_table}")
    _print(f"dim_timeframe={dim_tf}")
    _print(f"gap_mult={gap_mult}")
    _print(f"strict={strict}")
    _print(f"CSV out dir={out_dir}")
    _print(f"CSV base name={out_name}")

    # 1) Coverage
    coverage_sql = f"""
    WITH e AS (
      SELECT id, tf, period, COUNT(*) AS n_ema
      FROM {ema_table}
      GROUP BY 1,2,3
    ),
    r AS (
      SELECT id, tf, period, COUNT(*) AS n_ret
      FROM {ret_table}
      GROUP BY 1,2,3
    )
    SELECT
      e.id, e.tf, e.period,
      e.n_ema,
      COALESCE(r.n_ret, 0) AS n_ret,
      (e.n_ema - 1) AS expected_ret,
      (COALESCE(r.n_ret, 0) - (e.n_ema - 1)) AS diff
    FROM e
    LEFT JOIN r USING (id, tf, period)
    ORDER BY e.id, e.tf, e.period;
    """
    cov = _df(engine, coverage_sql)
    _print("Coverage (n_ret vs n_ema-1):")
    print(cov.head(20).to_string(index=False))
    if len(cov) > 20:
        _print(f"(coverage truncated in console; total rows={len(cov)})")

    bad_cov = cov[cov["diff"] != 0]
    if not bad_cov.empty:
        _print(f"FAIL: coverage mismatches found: {len(bad_cov)} (showing up to 50)")
        print(bad_cov.head(50).to_string(index=False))
        _write_csv(bad_cov, Path(str(out_base) + "_coverage_bad.csv"))
        _fail_or_warn(strict, f"FAIL: coverage mismatches found: {len(bad_cov)}")
    else:
        _print("PASS: coverage matches for all (id,tf,period).")

    # 2) Duplicates
    dup_sql = f"""
    SELECT id, tf, period, ts, COUNT(*) AS n
    FROM {ret_table}
    GROUP BY 1,2,3,4
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, period, ts
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) > 0:
        _print(f"FAIL: duplicate return keys found: {len(dups)} (showing up to 50)")
        print(dups.head(50).to_string(index=False))
        _fail_or_warn(strict, f"FAIL: duplicate return keys found: {len(dups)}")
    else:
        _print("PASS: no duplicate (id,ts,tf,period) in returns.")

    # 3) Gaps summary + anomalies
    gap_sql = f"""
    SELECT
      id, tf, period,
      COUNT(*) AS n_rows,
      SUM((gap_days_roll IS NULL)::int) AS n_gap_null,
      SUM((gap_days_roll < 1)::int) AS n_gap_lt1,
      SUM((gap_days_roll = 1)::int) AS n_gap_eq1,
      SUM((gap_days_roll > 1)::int) AS n_gap_gt1,
      MAX(gap_days_roll) AS max_gap_days
    FROM {ret_table}
    GROUP BY 1,2,3
    ORDER BY id, tf, period;
    """
    gaps = _df(engine, gap_sql)
    _print("gap_days summary (first 20 rows):")
    print(gaps.head(20).to_string(index=False))
    if len(gaps) > 20:
        _print(f"(gaps summary truncated in console; total rows={len(gaps)})")

    anom_sql = f"""
    SELECT
      id, tf, tf_days, period, roll, ts, gap_days_roll,
      delta1_ema_roll, ret_arith_ema_roll, ret_log_ema_roll,
      (tf_days * {gap_mult}) AS gap_thresh
    FROM {ret_table}
    WHERE
      gap_days_roll IS NULL
      OR gap_days_roll < 1
      OR gap_days_roll > (tf_days * {gap_mult})
    ORDER BY id, tf, period, roll, ts
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql)
    if len(anom) > 0:
        _print(
            f"FAIL: gap anomalies found (gap_days NULL/<1 or >{gap_mult}x tf_days_nominal): "
            f"{len(anom)} (showing up to 50)"
        )
        print(anom.head(50).to_string(index=False))
        _fail_or_warn(strict, f"FAIL: gap anomalies found: {len(anom)}")
    else:
        _print(
            f"PASS: no gap anomalies (gap_days>=1, and not >{gap_mult}x tf_days_nominal)."
        )

    # 4) Null policy
    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      -- _roll columns should never be NULL (populated on all rows)
      SUM((ret_arith_ema_roll IS NULL)::int) AS n_null_arith_roll,
      SUM((ret_arith_ema_bar_roll IS NULL)::int) AS n_null_arith_bar_roll,
      SUM((ret_log_ema_roll IS NULL)::int) AS n_null_log_roll,
      SUM((ret_log_ema_bar_roll IS NULL)::int) AS n_null_log_bar_roll,
      -- Non-roll columns should not be NULL on roll=FALSE rows
      SUM(CASE WHEN NOT roll AND ret_arith_ema IS NULL THEN 1 ELSE 0 END) AS n_null_arith_canon,
      SUM(CASE WHEN NOT roll AND ret_arith_ema_bar IS NULL THEN 1 ELSE 0 END) AS n_null_arith_bar_canon,
      SUM(CASE WHEN NOT roll AND ret_log_ema IS NULL THEN 1 ELSE 0 END) AS n_null_log_canon,
      SUM(CASE WHEN NOT roll AND ret_log_ema_bar IS NULL THEN 1 ELSE 0 END) AS n_null_log_bar_canon
    FROM {ret_table};
    """
    nulls = _df(engine, nulls_sql)
    _print("Null counts:")
    print(nulls.to_string(index=False))

    roll_nulls = sum(
        int(nulls.iloc[0][c])
        for c in [
            "n_null_arith_roll",
            "n_null_arith_bar_roll",
            "n_null_log_roll",
            "n_null_log_bar_roll",
        ]
    )
    canon_nulls = sum(
        int(nulls.iloc[0][c])
        for c in [
            "n_null_arith_canon",
            "n_null_arith_bar_canon",
            "n_null_log_canon",
            "n_null_log_bar_canon",
        ]
    )
    total_null = roll_nulls + canon_nulls
    if total_null != 0:
        _print(
            f"FAIL: return NULL rows found: roll_nulls={roll_nulls}, canon_nulls={canon_nulls}"
        )
        _fail_or_warn(strict, "FAIL: returns contain NULLs unexpectedly.")
    else:
        _print(
            "PASS: _roll columns never NULL; canonical columns never NULL on roll=FALSE."
        )

    # 5) Alignment
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {ema_table} e
      ON e.id = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.ts = r.ts
    WHERE e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _print(
            f"FAIL: {n_missing} returns rows have no matching EMA row in source table."
        )
        _fail_or_warn(strict, f"FAIL: alignment missing EMA rows: {n_missing}")
    else:
        _print("PASS: all returns timestamps/keys align to EMA source table.")

    # Write CSVs
    _write_csv(cov, Path(str(out_base) + "_coverage.csv"))
    _write_csv(dups, Path(str(out_base) + "_dups.csv"))
    _write_csv(gaps, Path(str(out_base) + "_gaps_summary.csv"))
    _write_csv(anom, Path(str(out_base) + "_gap_anomalies.csv"))
    _write_csv(nulls, Path(str(out_base) + "_nulls.csv"))
    _write_csv(align, Path(str(out_base) + "_align.csv"))
    _print("Wrote CSV outputs.")

    _print("Audit complete.")


if __name__ == "__main__":
    main()
