from __future__ import annotations

r"""
audit_returns_ema_multi_tf_cal_integrity.py

Integrity audit for unified CAL returns tables (US/ISO), containing both:
  series='ema'
  series='ema_bar'

Per (scheme, series, roll, id, tf, period):
  - Coverage: n_ret == n_ema - 1
  - No duplicates on PK
  - Gaps: gap_days >= 1; also flags gap_days > gap_mult * tf_days_nominal when available
  - Nulls: prev_ema/ret_* should be non-null (builder only inserts valid rows)
  - Alignment: every returns row matches a source EMA row at same (id,tf,period,ts) and roll mapping

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_ema_multi_tf_cal_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --series both --out-dir audits/returns --strict"
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


def expand_series(s: str) -> list[str]:
    s = s.strip().lower()
    if s == "both":
        return ["ema", "ema_bar"]
    if s in ("ema", "ema_bar"):
        return [s]
    raise ValueError("series must be one of: ema, ema_bar, both")


def _audit_one(engine: Engine, ema_table: str, ret_table: str, dim_tf: str, out_base: Path, strict: bool, gap_mult: float, label: str, series: str) -> None:
    _print(f"=== scheme={label} series={series} ===")

    # map source columns by series
    src_ema_col = "ema" if series == "ema" else "ema_bar"
    src_roll_col = "roll" if series == "ema" else "roll_bar"

    # 1) Coverage: group by key; returns has series column already
    coverage_sql = f"""
    WITH e AS (
      SELECT id::bigint AS id, tf, period, {src_roll_col}::boolean AS roll, COUNT(*) AS n_ema
      FROM {ema_table}
      GROUP BY 1,2,3,4
    ),
    r AS (
      SELECT id, tf, period, roll, COUNT(*) AS n_ret
      FROM {ret_table}
      WHERE series = '{series}'
      GROUP BY 1,2,3,4
    )
    SELECT
      e.id,
      e.tf,
      e.period,
      '{series}'::text AS series,
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
    bad_cov = cov[cov["diff"] != 0]
    if not bad_cov.empty:
        _write_csv(bad_cov, Path(str(out_base) + f"_{label}_{series}_coverage_bad.csv"))
        _fail_or_warn(strict, f"FAIL: {label}/{series} coverage mismatches: {len(bad_cov)}")
    else:
        _print("PASS: coverage.")

    # 2) Duplicates
    dup_sql = f"""
    SELECT id, tf, period, series, roll, ts, COUNT(*) AS n
    FROM {ret_table}
    WHERE series = '{series}'
    GROUP BY 1,2,3,4,5,6
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, period, roll, ts
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) > 0:
        _fail_or_warn(strict, f"FAIL: {label}/{series} duplicate keys: {len(dups)}")
    else:
        _print("PASS: no duplicates.")

    # 3) Gaps anomalies
    anom_sql = f"""
    WITH r AS (
      SELECT id, tf, period, series, roll, ts, gap_days, prev_ema, ema, ret_arith, ret_log
      FROM {ret_table}
      WHERE series = '{series}'
    ),
    tfm AS (
      SELECT tf, tf_days_nominal::double precision AS tf_days_nominal
      FROM {dim_tf}
    )
    SELECT
      r.*,
      tfm.tf_days_nominal,
      CASE WHEN tfm.tf_days_nominal IS NULL THEN NULL ELSE (tfm.tf_days_nominal * {gap_mult}) END AS gap_thresh
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
        _fail_or_warn(strict, f"FAIL: {label}/{series} gap anomalies: {len(anom)}")
    else:
        _print("PASS: gaps.")

    # 4) Null policy
    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      SUM((prev_ema IS NULL)::int) AS n_prev_ema_null,
      SUM((ret_arith IS NULL)::int) AS n_ret_arith_null,
      SUM((ret_log IS NULL)::int) AS n_ret_log_null
    FROM {ret_table}
    WHERE series = '{series}';
    """
    nulls = _df(engine, nulls_sql)
    n_prev_null = int(nulls.iloc[0]["n_prev_ema_null"])
    n_ra_null = int(nulls.iloc[0]["n_ret_arith_null"])
    n_rl_null = int(nulls.iloc[0]["n_ret_log_null"])
    if n_prev_null or n_ra_null or n_rl_null:
        _fail_or_warn(strict, f"FAIL: {label}/{series} nulls: prev={n_prev_null} arith={n_ra_null} log={n_rl_null}")
    else:
        _print("PASS: nulls.")

    # 5) Alignment: returns row should match source EMA row at same ts and roll mapping
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {ema_table} e
      ON e.id::bigint = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.ts = r.ts
     AND e.{src_roll_col}::boolean = r.roll
    WHERE r.series = '{series}'
      AND e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _fail_or_warn(strict, f"FAIL: {label}/{series} alignment missing EMA rows: {n_missing}")
    else:
        _print("PASS: alignment.")

    # Write CSVs
    _write_csv(cov, Path(str(out_base) + f"_{label}_{series}_coverage.csv"))
    _write_csv(dups, Path(str(out_base) + f"_{label}_{series}_dups.csv"))
    _write_csv(anom, Path(str(out_base) + f"_{label}_{series}_gap_anomalies.csv"))
    _write_csv(nulls, Path(str(out_base) + f"_{label}_{series}_nulls.csv"))
    _write_csv(align, Path(str(out_base) + f"_{label}_{series}_align.csv"))

    _print("Wrote CSV outputs.")


def main() -> None:
    p = argparse.ArgumentParser(description="Audit unified CAL EMA returns (US/ISO; ema + ema_bar).")
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""), help="DB URL (or set TARGET_DB_URL).")
    p.add_argument("--scheme", default="both", help="us | iso | both")
    p.add_argument("--series", default="both", help="ema | ema_bar | both")

    p.add_argument("--ema-us", default=DEFAULT_EMA_US)
    p.add_argument("--ema-iso", default=DEFAULT_EMA_ISO)
    p.add_argument("--ret-us", default=DEFAULT_RET_US)
    p.add_argument("--ret-iso", default=DEFAULT_RET_ISO)

    p.add_argument("--dim-timeframe", default=DEFAULT_DIM_TF)
    p.add_argument("--gap-mult", type=float, default=1.5)

    p.add_argument("--out", default="", help="Base filename for CSV outputs (no extension). If empty, auto-dated.")
    p.add_argument("--out-dir", default=".", help="Directory to write CSV outputs.")
    p.add_argument("--strict", action="store_true", help="Exit non-zero if any FAIL checks occur.")

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit("ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL.")

    engine = _get_engine(db_url)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_name = _resolve_out_name(args.out, "audit_returns_ema_multi_tf_cal")
    out_base = out_dir / out_name

    strict = bool(args.strict)
    schemes = expand_scheme(args.scheme)
    series_list = expand_series(args.series)

    _print(f"scheme={args.scheme} series={args.series} strict={strict} gap_mult={args.gap_mult}")
    _print(f"CSV out dir={out_dir}")
    _print(f"CSV base name={out_name}")

    for sch in schemes:
        ema_table = args.ema_us if sch == "us" else args.ema_iso
        ret_table = args.ret_us if sch == "us" else args.ret_iso

        for ser in series_list:
            _audit_one(
                engine=engine,
                ema_table=ema_table,
                ret_table=ret_table,
                dim_tf=args.dim_timeframe,
                out_base=out_base,
                strict=strict,
                gap_mult=float(args.gap_mult),
                label=sch,
                series=ser,
            )

    _print("Audit complete.")


if __name__ == "__main__":
    main()
