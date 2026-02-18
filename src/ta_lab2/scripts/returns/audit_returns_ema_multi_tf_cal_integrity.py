from __future__ import annotations

r"""
audit_returns_ema_multi_tf_cal_integrity.py

Integrity audit for unified CAL returns tables (US/ISO).

Unified timeline: _ema/_ema_bar + _roll value columns.
PK: (id, ts, tf, period) — roll is a regular boolean column.

Per (scheme, id, tf, period):
  - Coverage: n_ret == n_ema - 1
  - No duplicates on PK
  - Gaps: gap_days_roll >= 1; also flags gap_days_roll > gap_mult * tf_days_nominal
  - Nulls: _roll columns never NULL; canonical columns never NULL on roll=FALSE
  - Alignment: every returns row matches a source EMA row on (id, tf, period, ts)

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_ema_multi_tf_cal_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --out-dir audits/returns --strict"
)
"""

import argparse
import os
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_EMA_US = "public.cmc_ema_multi_tf_cal_us"
DEFAULT_EMA_ISO = "public.cmc_ema_multi_tf_cal_iso"
DEFAULT_RET_US = "public.cmc_returns_ema_multi_tf_cal_us"
DEFAULT_RET_ISO = "public.cmc_returns_ema_multi_tf_cal_iso"
DEFAULT_DIM_TF = "public.dim_timeframe"


def _print(msg: str) -> None:
    print(f"[audit_ret_ema_cal] {msg}")


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


def expand_scheme(s: str) -> list[str]:
    s = s.strip().lower()
    if s == "both":
        return ["us", "iso"]
    if s in ("us", "iso"):
        return [s]
    raise ValueError("scheme must be one of: us, iso, both")


def _audit_one(
    engine: Engine,
    ema_table: str,
    ret_table: str,
    dim_tf: str,
    out_base: Path,
    strict: bool,
    gap_mult: float,
    label: str,
) -> None:
    _print(f"=== scheme={label} ===")

    # 1) Coverage
    coverage_sql = f"""
    WITH e AS (
      SELECT id::bigint AS id, tf, period, COUNT(*) AS n_ema
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
    bad_cov = cov[cov["diff"] != 0]
    if not bad_cov.empty:
        _write_csv(bad_cov, Path(str(out_base) + f"_{label}_coverage_bad.csv"))
        _fail_or_warn(strict, f"FAIL: {label} coverage mismatches: {len(bad_cov)}")
    else:
        _print("PASS: coverage.")

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
        _fail_or_warn(strict, f"FAIL: {label} duplicate keys: {len(dups)}")
    else:
        _print("PASS: no duplicates.")

    # 3) Gaps anomalies
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
        _fail_or_warn(strict, f"FAIL: {label} gap anomalies: {len(anom)}")
    else:
        _print("PASS: gaps.")

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
    if total_null:
        _fail_or_warn(
            strict,
            f"FAIL: {label} nulls: roll_nulls={roll_nulls}, canon_nulls={canon_nulls}",
        )
    else:
        _print(
            "PASS: _roll columns never NULL; canonical columns never NULL on roll=FALSE."
        )

    # 5) Alignment
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {ema_table} e
      ON e.id::bigint = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.ts = r.ts
    WHERE e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _fail_or_warn(strict, f"FAIL: {label} alignment missing EMA rows: {n_missing}")
    else:
        _print("PASS: alignment.")

    # Write CSVs
    _write_csv(cov, Path(str(out_base) + f"_{label}_coverage.csv"))
    _write_csv(dups, Path(str(out_base) + f"_{label}_dups.csv"))
    _write_csv(anom, Path(str(out_base) + f"_{label}_gap_anomalies.csv"))
    _write_csv(nulls, Path(str(out_base) + f"_{label}_nulls.csv"))
    _write_csv(align, Path(str(out_base) + f"_{label}_align.csv"))

    _print("Wrote CSV outputs.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit unified CAL EMA returns (US/ISO, wide columns)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--scheme", default="both", help="us | iso | both")

    p.add_argument("--ema-us", default=DEFAULT_EMA_US)
    p.add_argument("--ema-iso", default=DEFAULT_EMA_ISO)
    p.add_argument("--ret-us", default=DEFAULT_RET_US)
    p.add_argument("--ret-iso", default=DEFAULT_RET_ISO)

    p.add_argument("--dim-timeframe", default=DEFAULT_DIM_TF)
    p.add_argument("--gap-mult", type=float, default=1.5)

    p.add_argument(
        "--out",
        default="",
        help="Base filename for CSV outputs (no extension). If empty, auto-dated.",
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

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_name = _resolve_out_name(args.out, "audit_returns_ema_multi_tf_cal")
    out_base = out_dir / out_name

    strict = bool(args.strict)
    schemes = expand_scheme(args.scheme)

    _print(f"scheme={args.scheme} strict={strict} gap_mult={args.gap_mult}")
    _print(f"CSV out dir={out_dir}")
    _print(f"CSV base name={out_name}")

    for sch in schemes:
        ema_table = args.ema_us if sch == "us" else args.ema_iso
        ret_table = args.ret_us if sch == "us" else args.ret_iso

        _audit_one(
            engine=engine,
            ema_table=ema_table,
            ret_table=ret_table,
            dim_tf=args.dim_timeframe,
            out_base=out_base,
            strict=strict,
            gap_mult=float(args.gap_mult),
            label=sch,
        )

    _print("Audit complete.")


if __name__ == "__main__":
    main()
