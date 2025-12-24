from __future__ import annotations

r"""
audit_returns_ema_multi_tf_integrity.py

Integrity audit for EMA-returns built from:
  public.cmc_ema_multi_tf
into:
  public.cmc_returns_ema_multi_tf

Checks:
  1) Coverage: n_ret == n_ema - 1 per (id, tf, period, roll)
  2) Duplicates: no duplicate (id, tf, period, roll, ts) in returns
  3) Gaps:
       - baseline: gap_days >= 1
       - optional threshold: gap_days <= gap_mult * tf_days_nominal (if dim_timeframe provides tf_days_nominal)
  4) Null policy:
       - prev_ema should never be NULL
       - ret_arith / ret_log should never be NULL (given builder filters invalid cases)
  5) Alignment: every returns row must match an EMA row on (id, tf, period, roll, ts)

CSV output:
  Always writes (auto-dated base name if --out omitted):
    <out_dir>/<out>_coverage.csv
    <out_dir>/<out>_coverage_bad.csv   (only if mismatches exist)
    <out_dir>/<out>_dups.csv
    <out_dir>/<out>_gaps_summary.csv
    <out_dir>/<out>_gap_anomalies.csv
    <out_dir>/<out>_nulls.csv
    <out_dir>/<out>_align.csv

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
    p = argparse.ArgumentParser(description="Audit integrity for cmc_returns_ema_multi_tf.")
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""), help="DB URL (or set TARGET_DB_URL).")
    p.add_argument("--ema-table", default=DEFAULT_EMA_TABLE)
    p.add_argument("--ret-table", default=DEFAULT_RET_TABLE)

    p.add_argument("--out", default="", help="Base filename for CSV outputs (no extension). If empty, auto-dated.")
    p.add_argument("--out-dir", default=".", help="Directory to write CSV outputs.")

    p.add_argument("--strict", action="store_true", help="Exit non-zero if any FAIL checks occur.")
    p.add_argument("--dim-timeframe", default=DEFAULT_DIM_TIMEFRAME, help="dim_timeframe table (for gap thresholds).")
    p.add_argument(
        "--gap-mult",
        type=float,
        default=1.5,
        help="Flag gaps where gap_days > gap_mult * tf_days_nominal (when available in dim_timeframe).",
    )

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit("ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL.")

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
      SELECT id, tf, period, roll, COUNT(*) AS n_ema
      FROM {ema_table}
      GROUP BY 1,2,3,4
    ),
    r AS (
      SELECT id, tf, period, roll, COUNT(*) AS n_ret
      FROM {ret_table}
      GROUP BY 1,2,3,4
    )
    SELECT
      e.id,
      e.tf,
      e.period,
      e.roll,
      e.n_ema,
      COALESCE(r.n_ret, 0) AS n_ret,
      (e.n_ema - 1) AS expected_ret,
      (COALESCE(r.n_ret, 0) - (e.n_ema - 1)) AS diff
    FROM e
    LEFT JOIN r USING (id, tf, period, roll)
    ORDER BY e.id, e.tf, e.period, e.roll;
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
      _print("PASS: coverage matches for all (id,tf,period,roll).")

    # 2) Duplicates
    dup_sql = f"""
    SELECT id, tf, period, roll, ts, COUNT(*) AS n
    FROM {ret_table}
    GROUP BY 1,2,3,4,5
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, period, roll, ts
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) > 0:
        _print(f"FAIL: duplicate return keys found: {len(dups)} (showing up to 50)")
        print(dups.head(50).to_string(index=False))
        _fail_or_warn(strict, f"FAIL: duplicate return keys found: {len(dups)}")
    else:
        _print("PASS: no duplicate (id,tf,period,roll,ts) in returns.")

    # 3) Gaps summary + anomalies
    gap_sql = f"""
    SELECT
      id,
      tf,
      period,
      roll,
      COUNT(*) AS n_rows,
      SUM((gap_days IS NULL)::int) AS n_gap_null,
      SUM((gap_days < 1)::int) AS n_gap_lt1,
      SUM((gap_days = 1)::int) AS n_gap_eq1,
      SUM((gap_days > 1)::int) AS n_gap_gt1,
      MAX(gap_days) AS max_gap_days
    FROM {ret_table}
    GROUP BY 1,2,3,4
    ORDER BY id, tf, period, roll;
    """
    gaps = _df(engine, gap_sql)
    _print("gap_days summary (first 20 rows):")
    print(gaps.head(20).to_string(index=False))
    if len(gaps) > 20:
        _print(f"(gaps summary truncated in console; total rows={len(gaps)})")

    anom_sql = f"""
    WITH r AS (
      SELECT id, tf, period, roll, ts, gap_days, prev_ema, ema, ret_arith, ret_log
      FROM {ret_table}
    ),
    tfm AS (
      SELECT tf, tf_days_nominal::double precision AS tf_days_nominal
      FROM {dim_tf}
    )
    SELECT
      r.id, r.tf, r.period, r.roll, r.ts, r.gap_days, r.prev_ema, r.ema, r.ret_arith, r.ret_log,
      tfm.tf_days_nominal,
      CASE
        WHEN tfm.tf_days_nominal IS NULL THEN NULL
        ELSE (tfm.tf_days_nominal * {gap_mult})
      END AS gap_thresh
    FROM r
    LEFT JOIN tfm USING (tf)
    WHERE
      r.gap_days IS NULL
      OR r.gap_days < 1
      OR (tfm.tf_days_nominal IS NOT NULL AND r.gap_days > (tfm.tf_days_nominal * {gap_mult}))
    ORDER BY r.id, r.tf, r.period, r.roll, r.ts
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql)
    if len(anom) > 0:
        _print(
            f"FAIL: gap anomalies found (gap_days NULL/<1 or >{gap_mult}x tf_days_nominal when available): "
            f"{len(anom)} (showing up to 50)"
        )
        print(anom.head(50).to_string(index=False))
        _fail_or_warn(strict, f"FAIL: gap anomalies found: {len(anom)}")
    else:
        _print(f"PASS: no gap anomalies (gap_days>=1, and not >{gap_mult}x tf_days_nominal when available).")

    # 4) Null policy
    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      SUM((prev_ema IS NULL)::int) AS n_prev_ema_null,
      SUM((ret_arith IS NULL)::int) AS n_ret_arith_null,
      SUM((ret_log IS NULL)::int) AS n_ret_log_null
    FROM {ret_table};
    """
    nulls = _df(engine, nulls_sql)
    _print("Null counts:")
    print(nulls.to_string(index=False))

    n_prev_ema_null = int(nulls.iloc[0]["n_prev_ema_null"])
    if n_prev_ema_null != 0:
        _print(f"FAIL: prev_ema NULL rows found: {n_prev_ema_null}")
        _fail_or_warn(strict, f"FAIL: prev_ema NULL rows found: {n_prev_ema_null}")
    else:
        _print("PASS: prev_ema is never NULL.")

    n_ret_arith_null = int(nulls.iloc[0]["n_ret_arith_null"])
    n_ret_log_null = int(nulls.iloc[0]["n_ret_log_null"])
    if n_ret_arith_null != 0 or n_ret_log_null != 0:
        _print(f"FAIL: return NULL rows found: ret_arith_null={n_ret_arith_null}, ret_log_null={n_ret_log_null}")
        _fail_or_warn(strict, "FAIL: returns contain NULLs unexpectedly.")
    else:
        _print("PASS: ret_arith and ret_log are never NULL.")

    # 5) Alignment
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {ema_table} e
      ON e.id = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.roll = r.roll
     AND e.ts = r.ts
    WHERE e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _print(f"FAIL: {n_missing} returns rows have no matching EMA row in source table.")
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
