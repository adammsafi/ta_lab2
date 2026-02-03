from __future__ import annotations

r"""
audit_returns_ema_multi_tf_cal_anchor_integrity.py

Integrity audit for calendar-anchored EMA returns:

Source EMA tables:
  public.cmc_ema_multi_tf_cal_anchor_us
  public.cmc_ema_multi_tf_cal_anchor_iso

Returns tables:
  public.cmc_returns_ema_multi_tf_cal_anchor_us
  public.cmc_returns_ema_multi_tf_cal_anchor_iso

Key semantics:
  - Returns computed per (id, tf, period, series, roll), ordered by ts
  - Coverage expectation per key:
      n_ret == n_src - 1
    where n_src is count of source EMA points for that series+roll:
      series='ema'     uses source columns (ema, roll)
      series='ema_bar' uses source columns (ema_bar, roll_bar)
  - No duplicate PK rows in returns
  - Gap sanity:
      gap_days >= 1
      optionally flag gap_days > gap_mult * tf_days_nominal (when dim_timeframe provides it)
  - Alignment:
      every returns row key exists in EMA source at same (id, tf, period, ts) for the same roll-series mapping
  - Null policy:
      prev_ema, ret_arith, ret_log should be non-null (builder only inserts valid rows)

CSV output:
  Writes (if --out-dir is provided):
    <out_dir>/<base>_{scheme}_coverage.csv
    <out_dir>/<base>_{scheme}_dups.csv
    <out_dir>/<base>_{scheme}_gaps_summary.csv
    <out_dir>/<base>_{scheme}_gap_anomalies.csv
    <out_dir>/<base>_{scheme}_nulls.csv
    <out_dir>/<base>_{scheme}_align.csv

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_ema_multi_tf_cal_anchor_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--scheme both --out-dir audits/returns --strict"
)
"""

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_DIM_TF = "public.dim_timeframe"

DEFAULT_EMA_US = "public.cmc_ema_multi_tf_cal_anchor_us"
DEFAULT_EMA_ISO = "public.cmc_ema_multi_tf_cal_anchor_iso"

DEFAULT_RET_US = "public.cmc_returns_ema_multi_tf_cal_anchor_us"
DEFAULT_RET_ISO = "public.cmc_returns_ema_multi_tf_cal_anchor_iso"


def _print(msg: str) -> None:
    print(f"[audit_ret_ema_cal_anchor] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _df(engine: Engine, sql: str, params: Optional[dict] = None) -> pd.DataFrame:
    with engine.begin() as cxn:
        return pd.read_sql(text(sql), cxn, params=params or {})


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _resolve_out_base(prefix: str) -> str:
    return f"{prefix}_{_today_yyyymmdd()}"


@dataclass(frozen=True)
class SchemeSpec:
    name: str
    ema_table: str
    ret_table: str


def _schemes(scheme: str) -> list[SchemeSpec]:
    s = scheme.strip().lower()
    if s == "us":
        return [SchemeSpec("us", DEFAULT_EMA_US, DEFAULT_RET_US)]
    if s == "iso":
        return [SchemeSpec("iso", DEFAULT_EMA_ISO, DEFAULT_RET_ISO)]
    if s == "both":
        return [
            SchemeSpec("us", DEFAULT_EMA_US, DEFAULT_RET_US),
            SchemeSpec("iso", DEFAULT_EMA_ISO, DEFAULT_RET_ISO),
        ]
    raise ValueError("--scheme must be one of: us, iso, both")


def _fail_or_warn(strict: bool, msg: str) -> None:
    if strict:
        raise SystemExit(msg)
    _print(msg)


def _audit_one(
    engine: Engine,
    spec: SchemeSpec,
    dim_tf: str,
    gap_mult: float,
    strict: bool,
    out_dir: Optional[Path],
    out_base: str,
) -> None:
    scheme = spec.name
    ema_table = spec.ema_table
    ret_table = spec.ret_table

    _print(f"=== scheme={scheme.upper()} ===")
    _print(f"ema={ema_table}")
    _print(f"ret={ret_table}")

    # Coverage: compare returns counts to source series counts (ema vs ema_bar, roll vs roll_bar)
    coverage_sql = f"""
    WITH src AS (
      SELECT
        id,
        tf,
        period,
        'ema'::text AS series,
        roll::boolean AS roll,
        COUNT(*) AS n_src
      FROM {ema_table}
      GROUP BY 1,2,3,4,5

      UNION ALL

      SELECT
        id,
        tf,
        period,
        'ema_bar'::text AS series,
        roll_bar::boolean AS roll,
        COUNT(*) AS n_src
      FROM {ema_table}
      GROUP BY 1,2,3,4,5
    ),
    r AS (
      SELECT id, tf, period, series, roll, COUNT(*) AS n_ret
      FROM {ret_table}
      GROUP BY 1,2,3,4,5
    )
    SELECT
      s.id,
      s.tf,
      s.period,
      s.series,
      s.roll,
      s.n_src,
      COALESCE(r.n_ret, 0) AS n_ret,
      (s.n_src - 1) AS expected_ret,
      (COALESCE(r.n_ret, 0) - (s.n_src - 1)) AS diff
    FROM src s
    LEFT JOIN r USING (id, tf, period, series, roll)
    ORDER BY s.id, s.tf, s.period, s.series, s.roll;
    """
    cov = _df(engine, coverage_sql)
    bad_cov = cov[cov["diff"] != 0]
    if bad_cov.empty:
        _print("PASS: coverage matches for all (id,tf,period,series,roll).")
    else:
        _print(f"FAIL: coverage mismatches found: {len(bad_cov)} (showing up to 50)")
        print(bad_cov.head(50).to_string(index=False))
        if out_dir is not None:
            _write_csv(bad_cov, out_dir / f"{out_base}_{scheme}_coverage_bad.csv")
        _fail_or_warn(
            strict,
            f"FAIL: coverage mismatches found for scheme={scheme}: {len(bad_cov)}",
        )

    # Duplicates
    dup_sql = f"""
    SELECT id, tf, period, series, roll, ts, COUNT(*) AS n
    FROM {ret_table}
    GROUP BY 1,2,3,4,5,6
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, period, series, roll, ts
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) == 0:
        _print("PASS: no duplicate return keys.")
    else:
        _print(f"FAIL: duplicate return keys found: {len(dups)} (showing up to 50)")
        print(dups.head(50).to_string(index=False))
        _fail_or_warn(
            strict, f"FAIL: duplicate return keys for scheme={scheme}: {len(dups)}"
        )

    # Gaps summary
    gap_sql = f"""
    SELECT
      id,
      tf,
      period,
      series,
      roll,
      COUNT(*) AS n_rows,
      SUM((gap_days IS NULL)::int) AS n_gap_null,
      SUM((gap_days < 1)::int) AS n_gap_lt1,
      SUM((gap_days = 1)::int) AS n_gap_eq1,
      SUM((gap_days > 1)::int) AS n_gap_gt1,
      MAX(gap_days) AS max_gap_days
    FROM {ret_table}
    GROUP BY 1,2,3,4,5
    ORDER BY id, tf, period, series, roll;
    """
    gaps = _df(engine, gap_sql)

    # Gap anomalies (NULL/<1 or > gap_mult * tf_days_nominal when available)
    anom_sql = f"""
    WITH r AS (
      SELECT id, tf, period, series, roll, ts, gap_days, prev_ema, ema, ret_arith, ret_log
      FROM {ret_table}
    ),
    tfm AS (
      SELECT tf, tf_days_nominal::double precision AS tf_days_nominal
      FROM {dim_tf}
    )
    SELECT
      r.*,
      tfm.tf_days_nominal,
      (tfm.tf_days_nominal * :gap_mult)::double precision AS gap_thresh
    FROM r
    LEFT JOIN tfm USING (tf)
    WHERE
      r.gap_days IS NULL
      OR r.gap_days < 1
      OR (tfm.tf_days_nominal IS NOT NULL AND r.gap_days > (tfm.tf_days_nominal * :gap_mult))
    ORDER BY r.id, r.tf, r.period, r.series, r.roll, r.ts
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql, {"gap_mult": gap_mult})
    if len(anom) == 0:
        _print(
            f"PASS: no gap anomalies (>=1 and not >{gap_mult}x tf_days_nominal when available)."
        )
    else:
        _print(f"FAIL: gap anomalies found: {len(anom)} (showing up to 50)")
        print(anom.head(50).to_string(index=False))
        _fail_or_warn(strict, f"FAIL: gap anomalies for scheme={scheme}: {len(anom)}")

    # Null policy
    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      SUM((prev_ema IS NULL)::int) AS n_prev_ema_null,
      SUM((ret_arith IS NULL)::int) AS n_ret_arith_null,
      SUM((ret_log IS NULL)::int) AS n_ret_log_null
    FROM {ret_table};
    """
    nulls = _df(engine, nulls_sql)
    n_prev_ema_null = int(nulls.iloc[0]["n_prev_ema_null"])
    n_ret_arith_null = int(nulls.iloc[0]["n_ret_arith_null"])
    n_ret_log_null = int(nulls.iloc[0]["n_ret_log_null"])

    if n_prev_ema_null == 0 and n_ret_arith_null == 0 and n_ret_log_null == 0:
        _print("PASS: prev_ema/ret_arith/ret_log are never NULL.")
    else:
        _print("FAIL: NULLs present in returns:")
        print(nulls.to_string(index=False))
        _fail_or_warn(strict, f"FAIL: NULLs present for scheme={scheme}")

    # Alignment: returns rows should exist in EMA source at same ts and correct roll mapping per series
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {ema_table} e
      ON e.id = r.id
     AND e.tf = r.tf
     AND e.period = r.period
     AND e.ts = r.ts
     AND (
          (r.series = 'ema'     AND e.roll     = r.roll)
       OR (r.series = 'ema_bar' AND e.roll_bar = r.roll)
     )
    WHERE e.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing == 0:
        _print("PASS: alignment to EMA source table.")
    else:
        _print(f"FAIL: {n_missing} returns rows have no matching EMA source row.")
        _fail_or_warn(
            strict, f"FAIL: alignment missing rows for scheme={scheme}: {n_missing}"
        )

    # Write CSVs
    if out_dir is not None:
        _write_csv(cov, out_dir / f"{out_base}_{scheme}_coverage.csv")
        _write_csv(dups, out_dir / f"{out_base}_{scheme}_dups.csv")
        _write_csv(gaps, out_dir / f"{out_base}_{scheme}_gaps_summary.csv")
        _write_csv(anom, out_dir / f"{out_base}_{scheme}_gap_anomalies.csv")
        _write_csv(nulls, out_dir / f"{out_base}_{scheme}_nulls.csv")
        _write_csv(align, out_dir / f"{out_base}_{scheme}_align.csv")
        _print("Wrote CSV outputs.")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit integrity for calendar-anchored EMA returns (US/ISO)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--scheme", default="both", help="us | iso | both")
    p.add_argument(
        "--dim-timeframe",
        default=DEFAULT_DIM_TF,
        help="dim_timeframe table (for tf_days_nominal).",
    )
    p.add_argument(
        "--gap-mult",
        type=float,
        default=1.5,
        help="Flag gaps where gap_days > gap_mult * tf_days_nominal (when available).",
    )
    p.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any FAIL checks occur."
    )
    p.add_argument(
        "--out-dir",
        default="",
        help="Directory to write CSV outputs. If empty, no CSVs are written.",
    )
    p.add_argument(
        "--out",
        default="",
        help="Base filename prefix (no extension). Defaults to dated name if omitted.",
    )

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    engine = _get_engine(db_url)

    scheme = args.scheme.strip().lower()
    dim_tf = args.dim_timeframe.strip()
    gap_mult = float(args.gap_mult)
    strict = bool(args.strict)

    out_dir = (
        Path(args.out_dir).expanduser().resolve() if args.out_dir.strip() else None
    )
    out_base = (
        args.out.strip()
        if args.out.strip()
        else _resolve_out_base("audit_returns_ema_multi_tf_cal_anchor")
    )

    _print(f"scheme={scheme}")
    _print(f"dim_timeframe={dim_tf}")
    _print(f"gap_mult={gap_mult}")
    _print(f"strict={strict}")
    if out_dir is not None:
        _print(f"CSV out dir={out_dir}")
        _print(f"CSV base name={out_base}")

    for spec in _schemes(scheme):
        _audit_one(engine, spec, dim_tf, gap_mult, strict, out_dir, out_base)

    _print("Audit complete.")


if __name__ == "__main__":
    main()
