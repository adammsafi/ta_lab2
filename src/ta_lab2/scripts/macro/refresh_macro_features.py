"""refresh_macro_features.py

CLI script for incremental FRED macro feature computation and upsert into
fred.fred_macro_features.

Follows the same patterns as other refreshers in the project (run_all_bar_builders.py,
run_all_ema_refreshes.py, etc.):
  - Watermark-based incremental computation with configurable warmup window
  - Temp table + ON CONFLICT (date) DO UPDATE upsert strategy
  - FRED staleness check: warns at 48h but does not block
  - Numpy scalar / NaN safety before psycopg2 binding

Usage:
    python -m ta_lab2.scripts.macro.refresh_macro_features              # incremental
    python -m ta_lab2.scripts.macro.refresh_macro_features --dry-run    # compute only, no write
    python -m ta_lab2.scripts.macro.refresh_macro_features --full       # recompute from 2000-01-01
    python -m ta_lab2.scripts.macro.refresh_macro_features --verbose    # DEBUG logging
    python -m ta_lab2.scripts.macro.refresh_macro_features --start-date 2020-01-01 --end-date 2026-01-01
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sys
import time
from typing import Any

import pandas as pd
from sqlalchemy import text

from ta_lab2.io import get_engine
from ta_lab2.macro.feature_computer import compute_macro_features

logger = logging.getLogger(__name__)

# Warmup window: covers 365-day rolling z-score (FRED-12) + margin for
# forward-fill propagation. On incremental runs, we recompute this many
# days before watermark to ensure feature correctness at the boundary.
WARMUP_DAYS = 400

# Full history start date (used with --full or when no watermark exists)
FULL_HISTORY_START = "2000-01-01"

# FRED staleness warning threshold (hours)
FRED_STALENESS_WARN_HOURS = 48.0

# Feature groups for structured summary log (CONTEXT.md requirement)
_FEATURE_GROUPS = [
    ("FRED-03 net_liquidity", ["net_liquidity"]),
    (
        "FRED-04 rate_spreads",
        ["us_jp_rate_spread", "us_ecb_rate_spread", "us_jp_10y_spread"],
    ),
    ("FRED-05 yc_dynamics", ["yc_slope_change_5d"]),
    ("FRED-06 vix_regime", ["vix_regime"]),
    ("FRED-07 dollar_strength", ["dtwexbgs_5d_change", "dtwexbgs_20d_change"]),
    (
        "FRED-08 credit_stress",
        ["hy_oas_level", "hy_oas_5d_change", "hy_oas_30d_zscore"],
    ),
    ("FRED-09 fin_conditions", ["nfci_level", "nfci_4wk_direction"]),
    ("FRED-10 m2", ["m2_yoy_pct"]),
    (
        "FRED-11 carry_trade",
        [
            "dexjpus_level",
            "dexjpus_5d_pct_change",
            "dexjpus_20d_vol",
            "dexjpus_daily_zscore",
        ],
    ),
    ("FRED-12 net_liq_zscore", ["net_liquidity_365d_zscore", "net_liquidity_trend"]),
    (
        "FRED-13/16 fed_regime",
        [
            "fed_regime_structure",
            "fed_regime_trajectory",
            "target_mid",
            "target_spread",
        ],
    ),
    ("FRED-14 carry_momentum", ["carry_momentum"]),
    ("FRED-15 cpi_proxy", ["cpi_surprise_proxy"]),
]

# Critical columns for staleness check (recent rows should not be all-NaN)
_STALENESS_CHECK_COLS = [
    "hy_oas_level",
    "nfci_level",
    "dexjpus_level",
    "fed_regime_structure",
]


# ---------------------------------------------------------------------------
# Watermark helpers
# ---------------------------------------------------------------------------


def get_compute_window(engine: Any, full: bool = False) -> tuple[str, str]:
    """Return (start_date, end_date) for the next compute run.

    On first run (no watermark), returns FULL_HISTORY_START as start.
    On incremental runs, subtracts WARMUP_DAYS from the watermark to ensure
    forward-fill and rolling features are correct at the boundary.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    full:
        If True, ignore watermark and return FULL_HISTORY_START as start.

    Returns
    -------
    (start_date, end_date) as ISO-format date strings.
    """
    end = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")

    if full:
        return FULL_HISTORY_START, end

    with engine.connect() as conn:
        max_date = conn.execute(
            text("SELECT MAX(date) FROM fred.fred_macro_features")
        ).scalar()

    if max_date is None:
        logger.info(
            "No watermark found in fred.fred_macro_features -- using full history start %s",
            FULL_HISTORY_START,
        )
        return FULL_HISTORY_START, end

    start = (pd.Timestamp(max_date) - pd.Timedelta(days=WARMUP_DAYS)).strftime(
        "%Y-%m-%d"
    )
    logger.info(
        "Watermark: %s | Warmup start: %s | End: %s",
        max_date,
        start,
        end,
    )
    return start, end


# ---------------------------------------------------------------------------
# FRED staleness check
# ---------------------------------------------------------------------------


def check_fred_staleness(
    engine: Any, warn_hours: float = FRED_STALENESS_WARN_HOURS
) -> tuple[bool, str]:
    """Check if fred.series_values has recent DFF data.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    warn_hours:
        Warn if DFF max_date is older than this many hours.

    Returns
    -------
    (is_fresh, message) -- is_fresh=False means stale but does NOT raise.
    Stale data triggers a WARNING log only (warn-and-continue per project convention).
    """
    try:
        with engine.connect() as conn:
            max_date = conn.execute(
                text("SELECT MAX(date) FROM fred.series_values WHERE series_id = 'DFF'")
            ).scalar()
    except Exception as exc:  # noqa: BLE001
        msg = f"Could not query fred.series_values: {exc}"
        logger.warning(msg)
        return False, msg

    if max_date is None:
        msg = "fred.series_values has no DFF data -- FRED sync may not have run yet"
        logger.warning(msg)
        return False, msg

    now_utc = pd.Timestamp.now("UTC")
    max_ts = pd.Timestamp(max_date).tz_localize("UTC")
    age_hours = (now_utc - max_ts).total_seconds() / 3600.0

    if age_hours > warn_hours:
        msg = (
            f"FRED staleness WARNING: DFF max_date={max_date} is {age_hours:.1f}h old "
            f"(threshold={warn_hours}h). Run sync_fred_from_vm.py to refresh."
        )
        logger.warning(msg)
        return False, msg

    msg = f"FRED data is fresh: DFF max_date={max_date} ({age_hours:.1f}h old)"
    logger.debug(msg)
    return True, msg


# ---------------------------------------------------------------------------
# Numpy / pandas type safety
# ---------------------------------------------------------------------------


def _to_python(v: Any) -> Any:
    """Convert numpy scalars and NaN to native Python types for psycopg2 safety.

    Per project gotcha: numpy scalars are not directly bindable by psycopg2
    on all versions. NaN must become None for nullable DB columns.
    """
    if v is None:
        return None
    # numpy scalar -> Python scalar
    if hasattr(v, "item"):
        v = v.item()
    # Python float NaN -> None
    if isinstance(v, float) and (v != v):  # NaN check without math import
        return None
    return v


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Convert DataFrame values to native Python types safe for psycopg2.

    - NaN -> None (for nullable SQL columns)
    - numpy scalars -> Python scalars
    - pandas Timestamps -> datetime.date objects for date column
    """
    # NaN -> None for all columns
    df = df.where(df.notna(), None)

    # Convert each column using _to_python per-element where needed
    # This is belt-and-suspenders; pandas where(notna(), None) handles most cases
    for col in df.columns:
        if df[col].dtype == object:
            # object columns may still contain numpy types; leave as-is (strings are fine)
            continue
        # Force-convert any remaining numpy scalars via applymap equivalent
        try:
            df[col] = df[col].apply(_to_python)
        except Exception:  # noqa: BLE001
            pass  # leave column as-is; psycopg2 will raise if truly incompatible

    return df


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------


def upsert_macro_features(engine: Any, df: pd.DataFrame) -> int:
    """Upsert macro feature DataFrame into fred.fred_macro_features.

    Uses temp table + INSERT ... ON CONFLICT (date) DO UPDATE pattern
    matching project conventions (same as feature writer, EMA upserts, etc.).

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with DatetimeIndex (name="date") and columns matching
        fred.fred_macro_features schema. Returned by compute_macro_features().

    Returns
    -------
    Number of rows upserted.
    """
    if df.empty:
        logger.warning("upsert_macro_features: empty DataFrame, nothing to write")
        return 0

    # Reset index so 'date' becomes a column
    df = df.reset_index()

    # Convert date column to datetime.date objects (not pd.Timestamp)
    # psycopg2 binds datetime.date directly; pd.Timestamp may fail on some versions
    df["date"] = df["date"].apply(
        lambda x: x.date() if isinstance(x, (pd.Timestamp, datetime.datetime)) else x
    )

    # NaN -> None and numpy scalar -> Python scalar safety
    df = _sanitize_dataframe(df)

    # Build ON CONFLICT SET clause: all columns except 'date', plus ingested_at
    non_date_cols = [c for c in df.columns if c != "date"]
    set_clause = ", ".join(f"{col} = EXCLUDED.{col}" for col in non_date_cols)
    set_clause += ", ingested_at = now()"

    col_list = ", ".join(["date"] + non_date_cols)

    with engine.begin() as conn:
        # Create staging temp table matching target schema
        conn.execute(
            text(
                "CREATE TEMP TABLE _macro_staging "
                "(LIKE fred.fred_macro_features INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
        )

        # Write DataFrame to staging table
        df.to_sql(
            "_macro_staging",
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )

        # Upsert from staging into target
        result = conn.execute(
            text(
                f"INSERT INTO fred.fred_macro_features ({col_list}) "
                f"SELECT {col_list} FROM _macro_staging "
                f"ON CONFLICT (date) DO UPDATE SET {set_clause}"
            )
        )
        row_count = result.rowcount

    logger.info("upsert_macro_features: %d rows upserted", row_count)
    return row_count


# ---------------------------------------------------------------------------
# Structured summary log
# ---------------------------------------------------------------------------


def _print_feature_summary(df: pd.DataFrame) -> None:
    """Print structured summary of feature groups computed.

    Shows per-group population status and staleness warnings for critical
    columns. Called after both dry-run and live upsert for visibility
    (CONTEXT.md requirement: feature groups computed, columns populated,
    staleness warnings).
    """
    print(f"\n[SUMMARY] Feature groups: {len(_FEATURE_GROUPS)}")
    for name, cols in _FEATURE_GROUPS:
        populated = sum(1 for c in cols if c in df.columns and df[c].notna().any())
        status = (
            "[OK]" if populated == len(cols) else f"[PARTIAL {populated}/{len(cols)}]"
        )
        print(f"  {status} {name}: {populated}/{len(cols)} columns populated")

    # Staleness check: warn if critical columns are all-NaN in last 7 rows
    recent = df.tail(7)
    stale_cols = []
    for col in _STALENESS_CHECK_COLS:
        if col in recent.columns and recent[col].isna().all():
            stale_cols.append(col)
    if stale_cols:
        print(
            f"[WARN] Staleness: {', '.join(stale_cols)} "
            "all-NaN in last 7 rows -- check FRED sync"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for incremental FRED macro feature refresh."""
    p = argparse.ArgumentParser(
        description="Incrementally compute and upsert FRED macro features into fred.fred_macro_features.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Incremental refresh (default -- uses watermark)
  python -m ta_lab2.scripts.macro.refresh_macro_features

  # Dry run: compute features, print sample, do NOT write to DB
  python -m ta_lab2.scripts.macro.refresh_macro_features --dry-run

  # Full history recompute from 2000-01-01
  python -m ta_lab2.scripts.macro.refresh_macro_features --full

  # Custom date range
  python -m ta_lab2.scripts.macro.refresh_macro_features --start-date 2020-01-01 --end-date 2026-01-01

  # Verbose / debug logging
  python -m ta_lab2.scripts.macro.refresh_macro_features --verbose
        """,
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute features but do NOT write to DB. Print row count and sample.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help=f"Ignore watermark; recompute full history from {FULL_HISTORY_START}.",
    )
    p.add_argument(
        "--start-date",
        metavar="DATE",
        default=None,
        help="Override compute window start date (ISO format: YYYY-MM-DD).",
    )
    p.add_argument(
        "--end-date",
        metavar="DATE",
        default=None,
        help="Override compute window end date (ISO format: YYYY-MM-DD).",
    )

    args = p.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    t0 = time.perf_counter()

    print(f"\n{'=' * 70}")
    print("FRED MACRO FEATURE REFRESH")
    print(f"{'=' * 70}")
    if args.dry_run:
        print("[DRY RUN] Features will be computed but NOT written to DB")

    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ERROR] Could not create DB engine: {exc}")
        return 1

    # Step 1: FRED staleness check (warn-and-continue, never blocks)
    is_fresh, staleness_msg = check_fred_staleness(engine)
    if not is_fresh:
        print(f"[WARN] {staleness_msg}")
    else:
        print(f"[OK] {staleness_msg}")

    # Step 2: Determine compute window
    if args.start_date or args.end_date:
        start_date = args.start_date or FULL_HISTORY_START
        end_date = args.end_date or pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
        print(f"[INFO] Using explicit date range: {start_date} to {end_date}")
    else:
        try:
            start_date, end_date = get_compute_window(engine, full=args.full)
        except Exception as exc:
            print(f"[ERROR] Failed to determine compute window: {exc}")
            return 1

    print(f"[INFO] Compute window: {start_date} to {end_date}")

    # Step 3: Compute features
    print("[INFO] Computing macro features...")
    try:
        df = compute_macro_features(engine, start_date=start_date, end_date=end_date)
    except Exception as exc:
        print(f"[ERROR] compute_macro_features failed: {exc}")
        logger.exception("compute_macro_features raised an exception")
        return 1

    if df.empty:
        print(
            "[WARN] No macro features computed -- FRED data may not be available. "
            "Run sync_fred_from_vm.py to populate fred.series_values."
        )
        elapsed = time.perf_counter() - t0
        print(f"\n[DONE] Elapsed: {elapsed:.1f}s (0 rows computed, 0 rows upserted)")
        return 0

    rows_computed = len(df)
    print(
        f"[INFO] Computed {rows_computed} rows "
        f"({df.index.min().date()} to {df.index.max().date()}, "
        f"{len(df.columns)} columns)"
    )

    if args.dry_run:
        print("\n[DRY RUN] Sample output (first 5 rows):")
        pd.set_option("display.max_columns", 10)
        pd.set_option("display.width", 120)
        print(df.head().to_string())
        _print_feature_summary(df)
        elapsed = time.perf_counter() - t0
        print(
            f"\n[DRY RUN DONE] Elapsed: {elapsed:.1f}s "
            f"({rows_computed} rows computed, 0 rows written)"
        )
        return 0

    # Step 4: Upsert to DB
    print("[INFO] Upserting to fred.fred_macro_features...")
    try:
        rows_upserted = upsert_macro_features(engine, df)
    except Exception as exc:
        print(f"[ERROR] upsert_macro_features failed: {exc}")
        logger.exception("upsert_macro_features raised an exception")
        return 1

    _print_feature_summary(df)

    elapsed = time.perf_counter() - t0
    print(
        f"\n[OK] FRED macro feature refresh complete in {elapsed:.1f}s: "
        f"{rows_computed} rows computed, {rows_upserted} rows upserted"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
