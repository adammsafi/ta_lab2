from __future__ import annotations

r"""
audit_returns_bars_multi_tf_cal_us_integrity.py

Integrity audit for bar-based returns (time_close keyed):
  public.cmc_returns_bars_multi_tf_cal_us
built from:
  public.cmc_price_bars_multi_tf_cal_us

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_bars_multi_tf_cal_us_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--out-dir audits/returns --out audit_returns_bars_multi_tf_cal_us"
)

Optional:
- Custom output base name (no extension):
  args="--out-dir audits/returns --out audit_returns_bars_multi_tf_cal_us"

- Override tables:
  args="--bars-table public.cmc_price_bars_multi_tf_cal_us --ret-table public.cmc_returns_bars_multi_tf_cal_us --out-dir audits/returns"
"""

import argparse
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_us"
DEFAULT_RET_TABLE = "public.cmc_returns_bars_multi_tf_cal_us"


def _print(msg: str) -> None:
    print(f"[audit_ret_bars_cal_us] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _df(engine: Engine, sql: str) -> pd.DataFrame:
    with engine.begin() as cxn:
        return pd.read_sql(text(sql), cxn)


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit integrity for bar returns (time_close keyed)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    p.add_argument("--ret-table", default=DEFAULT_RET_TABLE)
    p.add_argument(
        "--out", default="", help="Base filename for CSV outputs (no extension)."
    )
    p.add_argument("--out-dir", default=".", help="Directory to write CSV outputs.")
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    engine = _get_engine(db_url)
    bars_table = args.bars_table
    ret_table = args.ret_table

    out_name = args.out.strip()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_base = (out_dir / out_name) if out_name else None

    _print(f"bars={bars_table}")
    _print(f"ret={ret_table}")
    if out_base:
        _print(f"CSV out dir={out_dir}")
        _print(f"CSV base name={out_name}")
    else:
        _print(f"CSV out dir={out_dir}")
        _print("CSV base name=(none; pass --out to write CSVs)")

    cov_sql = f"""
    WITH b AS (
      SELECT id, tf, COUNT(*) AS n_bars
      FROM {bars_table}
      GROUP BY 1,2
    ),
    r AS (
      SELECT id, tf, COUNT(*) AS n_ret
      FROM {ret_table}
      GROUP BY 1,2
    )
    SELECT
      b.id,
      b.tf,
      b.n_bars,
      COALESCE(r.n_ret, 0) AS n_ret,
      (b.n_bars - 1) AS expected_ret,
      (COALESCE(r.n_ret, 0) - (b.n_bars - 1)) AS diff
    FROM b
    LEFT JOIN r USING (id, tf)
    ORDER BY b.id, b.tf;
    """
    cov = _df(engine, cov_sql)
    bad = cov[cov["diff"] != 0]
    if bad.empty:
        _print("PASS: coverage matches for all (id, tf).")
    else:
        _print(f"FAIL: coverage mismatches: {len(bad)} (showing up to 50)")
        print(bad.head(50).to_string(index=False))

    dup_sql = f"""
    SELECT id, tf, time_close, COUNT(*) AS n
    FROM {ret_table}
    GROUP BY 1,2,3
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, time_close
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if dups.empty:
        _print("PASS: no duplicate (id,tf,time_close).")
    else:
        _print(f"FAIL: duplicates found: {len(dups)} (showing up to 50)")
        print(dups.head(50).to_string(index=False))

    gaps_sql = f"""
    SELECT
      id,
      tf,
      COUNT(*) AS n_rows,
      SUM((gap_days IS NULL)::int) AS n_gap_null,
      SUM((gap_days <= 0)::int) AS n_gap_le0,
      MAX(gap_days) AS max_gap_days
    FROM {ret_table}
    GROUP BY 1,2
    ORDER BY id, tf;
    """
    gaps = _df(engine, gaps_sql)
    _print("gap_days summary (first 20):")
    print(gaps.head(20).to_string(index=False))

    anom_sql = f"""
    SELECT id, tf, time_close, gap_days, prev_close, close, ret_arith, ret_log
    FROM {ret_table}
    WHERE gap_days IS NULL OR gap_days <= 0
    ORDER BY id, tf, time_close
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql)
    if anom.empty:
        _print("PASS: no gap anomalies (gap_days > 0 where present).")
    else:
        _print(f"WARN: gap anomalies: {len(anom)} (showing up to 50)")
        print(anom.head(50).to_string(index=False))

    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      SUM((prev_close IS NULL)::int) AS n_prev_close_null,
      SUM((ret_arith IS NULL)::int) AS n_ret_arith_null,
      SUM((ret_log IS NULL)::int) AS n_ret_log_null
    FROM {ret_table};
    """
    nulls = _df(engine, nulls_sql)
    _print("Null counts:")
    print(nulls.to_string(index=False))

    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {bars_table} b
      ON b.id = r.id AND b.tf = r.tf AND b.time_close = r.time_close
    WHERE b.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing == 0:
        _print("PASS: all returns keys align to bars.")
    else:
        _print(f"FAIL: {n_missing} returns rows missing in bars table.")

    if out_base:
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
