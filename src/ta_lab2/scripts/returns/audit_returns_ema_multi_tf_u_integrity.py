from __future__ import annotations

r"""
audit_returns_ema_multi_tf_u_integrity.py

Integrity audit for unified EMA returns built from:
  public.cmc_ema_multi_tf_u
into:
  public.cmc_returns_ema_multi_tf_u

Unified timeline: _ema/_ema_bar + _roll value columns.
PK: (id, ts, tf, period, alignment_source) — roll is a regular boolean column.

Per (id, tf, period, alignment_source):
  - Coverage: n_ret == n_ema - 1
  - No duplicates on PK (id, ts, tf, period, alignment_source)
  - Gaps: gap_days_roll >= 1; also flags gap_days_roll > gap_mult * tf_days_nominal
  - Nulls: _roll columns never NULL; canonical columns never NULL on roll=FALSE
  - Alignment: every returns row matches a source EMA row on (id, tf, period, alignment_source, ts)

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_ema_multi_tf_u_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--out-dir audits/returns --strict"
)
"""

import argparse
import os
from pathlib import Path
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_U_TABLE = "public.cmc_ema_multi_tf_u"
DEFAULT_RET_TABLE = "public.cmc_returns_ema_multi_tf_u"
DEFAULT_DIM_TF = "public.dim_timeframe"


def _print(msg: str) -> None:
    print(f"[audit_ret_ema_u] {msg}")


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


def _resolve_out_name(out_arg: str, default_prefix: str) -> Optional[str]:
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
        description="Audit integrity for cmc_returns_ema_multi_tf_u (wide columns)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--ema-u-table", default=DEFAULT_EMA_U_TABLE)
    p.add_argument("--ret-table", default=DEFAULT_RET_TABLE)
    p.add_argument("--dim-timeframe", default=DEFAULT_DIM_TF)
    p.add_argument("--gap-mult", type=float, default=1.5)

    p.add_argument(
        "--out", default="", help="Base filename for CSV outputs (no extension)."
    )
    p.add_argument("--out-dir", default=".", help="Directory to write CSV outputs.")
    p.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any FAIL checks occur."
    )
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    engine = _get_engine(db_url)
    ema_u = args.ema_u_table
    ret = args.ret_table
    dim_tf = args.dim_timeframe
    gap_mult = float(args.gap_mult)
    strict = bool(args.strict)

    out_name = _resolve_out_name(args.out, "audit_returns_ema_multi_tf_u")
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_base = out_dir / out_name

    _print(f"ema_u={ema_u}")
    _print(f"ret={ret}")
    _print(f"dim_timeframe={dim_tf}")
    _print(f"gap_mult={gap_mult}")
    _print(f"strict={strict}")
    _print(f"CSV out dir={out_dir}")
    _print(f"CSV base name={out_name}")

    # 1) Coverage: per key returns rows == ema rows - 1
    coverage_sql = f"""
    WITH e AS (
      SELECT id, tf, period, alignment_source, COUNT(*) AS n_ema
      FROM {ema_u}
      GROUP BY 1,2,3,4
    ),
    r AS (
      SELECT id, tf, period, alignment_source, COUNT(*) AS n_ret
      FROM {ret}
      GROUP BY 1,2,3,4
    )
    SELECT
      e.id, e.tf, e.period, e.alignment_source,
      e.n_ema,
      COALESCE(r.n_ret, 0) AS n_ret,
      (e.n_ema - 1) AS expected_ret,
      (COALESCE(r.n_ret, 0) - (e.n_ema - 1)) AS diff
    FROM e
    LEFT JOIN r USING (id, tf, period, alignment_source)
    ORDER BY e.id, e.tf, e.period, e.alignment_source;
    """
    cov = _df(engine, coverage_sql)
    bad_cov = cov[cov["diff"] != 0]
    if bad_cov.empty:
        _print("PASS: coverage.")
    else:
        _print(f"FAIL: coverage mismatches found: {len(bad_cov)}")
        _write_csv(bad_cov, Path(str(out_base) + "_coverage_bad.csv"))
        _fail_or_warn(strict, f"FAIL: coverage mismatches found: {len(bad_cov)}")

    # 2) Duplicates
    dup_sql = f"""
    SELECT id, tf, period, alignment_source, ts, COUNT(*) AS n
    FROM {ret}
    GROUP BY 1,2,3,4,5
    HAVING COUNT(*) > 1
    ORDER BY n DESC
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) == 0:
        _print("PASS: no duplicates.")
    else:
        _print(f"FAIL: duplicate keys found: {len(dups)}")
        _fail_or_warn(strict, f"FAIL: duplicate keys found: {len(dups)}")

    # 3) Gaps
    anom_sql = f"""
    SELECT
      id, tf, tf_days, period, alignment_source, roll, ts,
      gap_days_roll,
      (tf_days * {gap_mult}) AS gap_thresh
    FROM {ret}
    WHERE
      gap_days_roll IS NULL
      OR gap_days_roll < 1
      OR gap_days_roll > (tf_days * {gap_mult})
    ORDER BY id, tf, period, alignment_source, roll, ts
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql)
    if len(anom) == 0:
        _print("PASS: gaps.")
    else:
        _print(f"FAIL: gap anomalies found: {len(anom)}")
        _fail_or_warn(strict, f"FAIL: gap anomalies found: {len(anom)}")

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
    FROM {ret};
    """
    nulls = _df(engine, nulls_sql)
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
    if total_null == 0:
        _print(
            "PASS: _roll columns never NULL; canonical columns never NULL on roll=FALSE."
        )
    else:
        _print(f"FAIL: null counts: roll_nulls={roll_nulls}, canon_nulls={canon_nulls}")
        _fail_or_warn(strict, "FAIL: null policy violated.")

    # 5) Alignment
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret} r
    LEFT JOIN {ema_u} e
      ON e.id = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.alignment_source = r.alignment_source
     AND e.ts = r.ts
    WHERE e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing == 0:
        _print("PASS: alignment.")
    else:
        _print(f"FAIL: missing EMA_U rows for returns: {n_missing}")
        _fail_or_warn(strict, f"FAIL: alignment missing EMA_U rows: {n_missing}")

    # Write CSVs
    _write_csv(cov, Path(str(out_base) + "_coverage.csv"))
    _write_csv(dups, Path(str(out_base) + "_dups.csv"))
    _write_csv(anom, Path(str(out_base) + "_gap_anomalies.csv"))
    _write_csv(nulls, Path(str(out_base) + "_nulls.csv"))
    _write_csv(align, Path(str(out_base) + "_align.csv"))
    _print("Wrote CSV outputs.")
    _print("Audit complete.")


if __name__ == "__main__":
    main()
