from __future__ import annotations

r"""
audit_returns_ema_multi_tf_u_integrity.py

Integrity audit for unified EMA returns built from:
  public.cmc_ema_multi_tf_u
into:
  public.cmc_returns_ema_multi_tf_u

Keyed by:
  (id, tf, period, alignment_source, series, roll)

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
        description="Audit integrity for cmc_returns_ema_multi_tf_u."
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
      SELECT
        id, tf, period, alignment_source,
        'ema'::text AS series,
        roll,
        COUNT(*) AS n_ema
      FROM {ema_u}
      GROUP BY 1,2,3,4,5,6

      UNION ALL

      SELECT
        id, tf, period, alignment_source,
        'ema_bar'::text AS series,
        roll AS roll,
        COUNT(*) AS n_ema
      FROM {ema_u}
      WHERE ema_bar IS NOT NULL
      GROUP BY 1,2,3,4,5,6
    ),
    r AS (
      SELECT
        id, tf, period, alignment_source, series, roll,
        COUNT(*) AS n_ret
      FROM {ret}
      GROUP BY 1,2,3,4,5,6
    )
    SELECT
      e.id, e.tf, e.period, e.alignment_source, e.series, e.roll,
      e.n_ema,
      COALESCE(r.n_ret, 0) AS n_ret,
      (e.n_ema - 1) AS expected_ret,
      (COALESCE(r.n_ret, 0) - (e.n_ema - 1)) AS diff
    FROM e
    LEFT JOIN r USING (id, tf, period, alignment_source, series, roll)
    ORDER BY e.id, e.tf, e.period, e.alignment_source, e.series, e.roll;
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
    SELECT id, tf, period, alignment_source, series, roll, ts, COUNT(*) AS n
    FROM {ret}
    GROUP BY 1,2,3,4,5,6,7
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

    # 3) Gaps (>=1 and not > gap_mult * tf_days_nominal where available)
    anom_sql = f"""
    WITH tfm AS (
      SELECT tf, tf_days_nominal::double precision AS tf_days_nominal
      FROM {dim_tf}
    )
    SELECT
      r.id, r.tf, r.period, r.alignment_source, r.series, r.roll, r.ts,
      r.gap_days,
      tfm.tf_days_nominal,
      (tfm.tf_days_nominal * {gap_mult}) AS gap_thresh
    FROM {ret} r
    LEFT JOIN tfm USING (tf)
    WHERE
      r.gap_days IS NULL
      OR r.gap_days < 1
      OR (tfm.tf_days_nominal IS NOT NULL AND r.gap_days > (tfm.tf_days_nominal * {gap_mult}))
    ORDER BY r.id, r.tf, r.period, r.alignment_source, r.series, r.roll, r.ts
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
      SUM((ret_arith IS NULL)::int) AS n_ret_arith_null,
      SUM((ret_log IS NULL)::int) AS n_ret_log_null,
      SUM((delta1 IS NULL)::int) AS n_delta1_null,
      SUM((delta2 IS NULL)::int) AS n_delta2_null,
      SUM((delta_ret_arith IS NULL)::int) AS n_delta_ret_arith_null,
      SUM((delta_ret_log IS NULL)::int) AS n_delta_ret_log_null
    FROM {ret};
    """
    nulls = _df(engine, nulls_sql)
    n_ra = int(nulls.iloc[0]["n_ret_arith_null"])
    n_rl = int(nulls.iloc[0]["n_ret_log_null"])
    if n_ra == 0 and n_rl == 0:
        _print("PASS: nulls (ret_arith/ret_log).")
    else:
        _print(f"FAIL: null counts ret_arith={n_ra} ret_log={n_rl}")
        _fail_or_warn(strict, "FAIL: null policy violated.")

    _print(
        f"INFO: delta1_null={int(nulls.iloc[0]['n_delta1_null'])}, "
        f"delta2_null={int(nulls.iloc[0]['n_delta2_null'])}, "
        f"delta_ret_arith_null={int(nulls.iloc[0]['n_delta_ret_arith_null'])}, "
        f"delta_ret_log_null={int(nulls.iloc[0]['n_delta_ret_log_null'])}"
    )

    # 5) Alignment: every return row should exist in EMA_U source
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret} r
    LEFT JOIN {ema_u} e
      ON e.id = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.alignment_source = r.alignment_source
     AND e.ts = r.ts
     AND e.roll = r.roll
    WHERE e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing == 0:
        _print("PASS: alignment.")
    else:
        _print(f"FAIL: missing EMA_U rows for returns: {n_missing}")
        _fail_or_warn(strict, f"FAIL: alignment missing EMA_U rows: {n_missing}")

    # Write CSVs (summary-style)
    _write_csv(cov, Path(str(out_base) + "_coverage.csv"))
    _write_csv(dups, Path(str(out_base) + "_dups.csv"))
    _write_csv(anom, Path(str(out_base) + "_gap_anomalies.csv"))
    _write_csv(nulls, Path(str(out_base) + "_nulls.csv"))
    _write_csv(align, Path(str(out_base) + "_align.csv"))
    _print("Wrote CSV outputs.")
    _print("Audit complete.")


if __name__ == "__main__":
    main()
