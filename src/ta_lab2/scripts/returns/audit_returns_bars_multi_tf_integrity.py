from __future__ import annotations

r"""
audit_returns_bars_multi_tf_integrity.py

Integrity audit for bar-based returns:
  public.cmc_returns_bars_multi_tf
built from:
  public.cmc_price_bars_multi_tf

Checks:
  1) Coverage: per (id, tf) returns rows == bars rows - 1
  2) No duplicate (id, tf, bar_seq)
  3) Gap sanity: gap_bars >= 1, typically 1; report any > 1
  4) Null policy: prev_close should never be NULL; ret_* should rarely be NULL (only if zeros/negatives)
  5) Alignment: every returns (id, tf, bar_seq) exists in bars table for same key

CSV output:
  If --out is provided, writes:
    <out>_coverage.csv
    <out>_dups.csv
    <out>_gaps_summary.csv
    <out>_gap_anomalies.csv
    <out>_nulls.csv
    <out>_align.csv

New:
  --out-dir lets you choose the directory for CSVs, while --out remains just the base filename.
  Example:
    args="--out audit_returns_bars_multi_tf_20251222 --out-dir audits/returns"

  This writes:
    audits/returns/audit_returns_bars_multi_tf_20251222_coverage.csv
    audits/returns/audit_returns_bars_multi_tf_20251222_dups.csv
    ...

runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_bars_multi_tf_integrity.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--out audit_returns_bars_multi_tf_20251222 --out-dir audits/returns"
)
"""

import argparse
import os
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf"
DEFAULT_RET_TABLE = "public.cmc_returns_bars_multi_tf"


def _print(msg: str) -> None:
    print(f"[audit_ret_bars_multi_tf] {msg}")


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
        description="Audit integrity for cmc_returns_bars_multi_tf."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    p.add_argument("--ret-table", default=DEFAULT_RET_TABLE)

    # Base filename (no extension). If you include a path here, it still works,
    # but recommended usage is: --out <name> and --out-dir <dir>.
    p.add_argument(
        "--out", default="", help="Base filename for CSV outputs (no extension)."
    )

    # New: output directory for CSVs (default: current directory)
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

    out_base = None
    if out_name:
        out_base = out_dir / out_name

    _print(f"bars={bars_table}")
    _print(f"ret={ret_table}")
    if out_base:
        _print(f"CSV out dir={out_dir}")
        _print(f"CSV base name={out_name}")

    # 1) Coverage
    coverage_sql = f"""
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
    cov = _df(engine, coverage_sql)
    _print("Coverage (n_ret vs n_bars-1):")
    print(cov.head(20).to_string(index=False))
    if len(cov) > 20:
        _print(f"(coverage truncated in console; total rows={len(cov)})")

    bad_cov = cov[cov["diff"] != 0]
    if not bad_cov.empty:
        _print(f"FAIL: coverage mismatches found: {len(bad_cov)}")
        print(bad_cov.head(50).to_string(index=False))
    else:
        _print("PASS: coverage matches for all (id, tf).")

    # 2) Duplicates
    dup_sql = f"""
    SELECT id, tf, bar_seq, COUNT(*) AS n
    FROM {ret_table}
    GROUP BY 1,2,3
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, bar_seq
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) > 0:
        _print(f"FAIL: duplicate (id,tf,bar_seq) found: {len(dups)} (showing up to 50)")
        print(dups.head(50).to_string(index=False))
    else:
        _print("PASS: no duplicate (id,tf,bar_seq).")

    # 3) Gap summary
    gap_sql = f"""
    SELECT
      id,
      tf,
      COUNT(*) AS n_rows,
      SUM((gap_bars IS NULL)::int) AS n_gap_null,
      SUM((gap_bars < 1)::int) AS n_gap_lt1,
      SUM((gap_bars = 1)::int) AS n_gap_eq1,
      SUM((gap_bars > 1)::int) AS n_gap_gt1,
      MAX(gap_bars) AS max_gap_bars
    FROM {ret_table}
    GROUP BY 1,2
    ORDER BY id, tf;
    """
    gaps = _df(engine, gap_sql)
    _print("gap_bars summary (first 20 rows):")
    print(gaps.head(20).to_string(index=False))
    if len(gaps) > 20:
        _print(f"(gaps summary truncated in console; total rows={len(gaps)})")

    # Gap anomalies
    anom_sql = f"""
    SELECT id, tf, bar_seq, gap_bars, time_close, prev_close, close, ret_arith, ret_log
    FROM {ret_table}
    WHERE gap_bars IS NULL OR gap_bars < 1 OR gap_bars > 1
    ORDER BY id, tf, bar_seq
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql)
    if len(anom) > 0:
        _print(f"WARN: gap anomalies found: {len(anom)} (showing up to 50)")
        print(anom.head(50).to_string(index=False))
    else:
        _print("PASS: no gap anomalies (all gap_bars == 1).")

    # 4) Null policy
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

    # 5) Alignment
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {bars_table} b
      ON b.id = r.id AND b.tf = r.tf AND b.bar_seq = r.bar_seq
    WHERE b.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _print(
            f"FAIL: {n_missing} returns rows have no matching (id,tf,bar_seq) in bars table."
        )
    else:
        _print("PASS: all returns keys align to bars table.")

    # Write CSVs
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
