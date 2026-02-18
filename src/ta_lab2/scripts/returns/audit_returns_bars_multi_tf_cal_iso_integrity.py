from __future__ import annotations

r"""
audit_returns_bars_multi_tf_cal_iso_integrity.py

Integrity audit for wide-column bar returns:
  public.cmc_returns_bars_multi_tf_cal_iso
built from:
  public.cmc_price_bars_multi_tf_cal_iso

Checks:
  1) Coverage: n_ret == n_bars - 1 per (id, tf) (counts ALL rows: canonical + snapshot)
  2) Duplicates: no duplicate (id, "timestamp", tf) — the PK
  3) Gaps: gap_bars on roll=FALSE rows: should be >= 1, flag anomalies > 1
  4) Null policy:
       - _roll columns should never be NULL (populated on all rows)
       - canonical columns should never be NULL on roll=FALSE rows
       - range/true_range same split
  5) Alignment: every returns (id, tf, "timestamp") exists in source bar table

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\audit_returns_bars_multi_tf_cal_iso_integrity.py",
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


DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_iso"
DEFAULT_RET_TABLE = "public.cmc_returns_bars_multi_tf_cal_iso"

_PRINT_PREFIX = "audit_ret_bars_cal_iso"


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}")


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
        description="Audit integrity for cmc_returns_bars_multi_tf_cal_iso (wide-column, dual-LAG)."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
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
        "--gap-mult",
        type=float,
        default=1.5,
        help="Flag gaps where gap_bars > gap_mult * tf_days.",
    )

    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    engine = _get_engine(db_url)
    bars_table = args.bars_table
    ret_table = args.ret_table
    gap_mult = float(args.gap_mult)
    strict = bool(args.strict)

    default_prefix = _PRINT_PREFIX
    out_name = _resolve_out_name(args.out, default_prefix)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_base = out_dir / out_name

    _print(f"bars={bars_table}")
    _print(f"ret={ret_table}")
    _print(f"gap_mult={gap_mult}")
    _print(f"strict={strict}")
    _print(f"CSV out dir={out_dir}")
    _print(f"CSV base name={out_name}")

    # 1) Coverage: n_ret == n_bars - 1 per (id, tf) — both sides count ALL rows
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
      b.id, b.tf,
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
        _print(f"FAIL: coverage mismatches found: {len(bad_cov)} (showing up to 50)")
        print(bad_cov.head(50).to_string(index=False))
        _write_csv(bad_cov, Path(str(out_base) + "_coverage_bad.csv"))
        _fail_or_warn(strict, f"FAIL: coverage mismatches found: {len(bad_cov)}")
    else:
        _print("PASS: coverage matches for all (id,tf).")

    # 2) Duplicates: no duplicate (id, "timestamp", tf) — the PK
    dup_sql = f"""
    SELECT id, tf, "timestamp", COUNT(*) AS n
    FROM {ret_table}
    GROUP BY 1,2,3
    HAVING COUNT(*) > 1
    ORDER BY n DESC, id, tf, "timestamp"
    LIMIT 5000;
    """
    dups = _df(engine, dup_sql)
    if len(dups) > 0:
        _print(f"FAIL: duplicate return keys found: {len(dups)} (showing up to 50)")
        print(dups.head(50).to_string(index=False))
        _fail_or_warn(strict, f"FAIL: duplicate return keys found: {len(dups)}")
    else:
        _print('PASS: no duplicate (id,"timestamp",tf) in returns.')

    # 3) Gaps: gap_bars on roll=FALSE rows
    gap_sql = f"""
    SELECT
      id, tf,
      COUNT(*) AS n_rows,
      SUM((gap_bars IS NULL)::int) AS n_gap_null,
      SUM((gap_bars < 1)::int) AS n_gap_lt1,
      SUM((gap_bars = 1)::int) AS n_gap_eq1,
      SUM((gap_bars > 1)::int) AS n_gap_gt1,
      MAX(gap_bars) AS max_gap_bars
    FROM {ret_table}
    WHERE roll = FALSE
    GROUP BY 1,2
    ORDER BY id, tf;
    """
    gaps = _df(engine, gap_sql)
    _print("gap_bars summary on roll=FALSE rows (first 20 rows):")
    print(gaps.head(20).to_string(index=False))
    if len(gaps) > 20:
        _print(f"(gaps summary truncated in console; total rows={len(gaps)})")

    # Exclude the first canonical row per key (gap_bars IS NULL is expected for bar_seq=1)
    anom_sql = f"""
    SELECT
      id, tf, tf_days, roll, "timestamp", bar_seq, gap_bars,
      delta1_roll, ret_arith_roll, ret_log_roll
    FROM {ret_table}
    WHERE roll = FALSE
      AND gap_bars IS NOT NULL
      AND (gap_bars < 1 OR gap_bars > 1)
    ORDER BY id, tf, "timestamp"
    LIMIT 5000;
    """
    anom = _df(engine, anom_sql)
    if len(anom) > 0:
        _print(
            f"WARN: gap anomalies found on roll=FALSE: {len(anom)} (showing up to 50)"
        )
        print(anom.head(50).to_string(index=False))
    else:
        _print("PASS: no gap anomalies on roll=FALSE (all gap_bars == 1).")

    # 4) Null policy
    # Note: the first canonical row per (id,tf) will always have NULL canonical columns
    # (no previous canonical to LAG from), so we exclude those via gap_bars IS NOT NULL.
    nulls_sql = f"""
    SELECT
      COUNT(*) AS n_rows,
      -- _roll columns should never be NULL (populated on all rows)
      SUM((ret_arith_roll IS NULL)::int) AS n_null_arith_roll,
      SUM((ret_log_roll IS NULL)::int) AS n_null_log_roll,
      SUM((range_roll IS NULL)::int) AS n_null_range_roll,
      SUM((true_range_roll IS NULL)::int) AS n_null_true_range_roll,
      -- canonical columns should not be NULL on roll=FALSE rows (excluding first per key)
      SUM(CASE WHEN NOT roll AND gap_bars IS NOT NULL AND ret_arith IS NULL THEN 1 ELSE 0 END) AS n_null_arith_canon,
      SUM(CASE WHEN NOT roll AND gap_bars IS NOT NULL AND ret_log IS NULL THEN 1 ELSE 0 END) AS n_null_log_canon,
      SUM(CASE WHEN NOT roll AND gap_bars IS NOT NULL AND range IS NULL THEN 1 ELSE 0 END) AS n_null_range_canon,
      SUM(CASE WHEN NOT roll AND gap_bars IS NOT NULL AND true_range IS NULL THEN 1 ELSE 0 END) AS n_null_true_range_canon
    FROM {ret_table};
    """
    nulls = _df(engine, nulls_sql)
    _print("Null counts:")
    print(nulls.to_string(index=False))

    roll_nulls = sum(
        int(nulls.iloc[0][c])
        for c in [
            "n_null_arith_roll",
            "n_null_log_roll",
            "n_null_range_roll",
            "n_null_true_range_roll",
        ]
    )
    canon_nulls = sum(
        int(nulls.iloc[0][c])
        for c in [
            "n_null_arith_canon",
            "n_null_log_canon",
            "n_null_range_canon",
            "n_null_true_range_canon",
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

    # 5) Alignment: every returns (id, tf, "timestamp") exists in source bar table
    align_sql = f"""
    SELECT COUNT(*) AS n_missing
    FROM {ret_table} r
    LEFT JOIN {bars_table} b
      ON b.id = r.id
     AND b.tf = r.tf
     AND b."timestamp" = r."timestamp"
    WHERE b.id IS NULL;
    """
    align = _df(engine, align_sql)
    n_missing = int(align.iloc[0]["n_missing"])
    if n_missing != 0:
        _print(
            f"FAIL: {n_missing} returns rows have no matching bar row in source table."
        )
        _fail_or_warn(strict, f"FAIL: alignment missing bar rows: {n_missing}")
    else:
        _print("PASS: all returns timestamps/keys align to bar source table.")

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
