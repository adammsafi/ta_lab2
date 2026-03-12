"""
Cross-sectional normalization refresh for features.

Computes cross-sectional z-scores and PERCENT_RANK values for 3 pilot feature
columns by running PostgreSQL window functions partitioned by (ts, tf).

Pilot columns:
    - ret_arith   -> ret_arith_cs_zscore,        ret_arith_cs_rank
    - rsi_14      -> rsi_14_cs_zscore,            rsi_14_cs_rank
    - vol_parkinson_20 -> vol_parkinson_20_cs_zscore, vol_parkinson_20_cs_rank

Safety guards:
    - n_assets >= 5: timestamps with fewer than 5 assets with non-NULL source
      values are skipped (CS norms are meaningless with a handful of points).
    - NULLIF(cs_std, 0): division by zero when all assets share the same value
      (e.g. a synthetic constant-close asset) produces NULL, not NaN/Inf.

Usage:
    python -m ta_lab2.scripts.features.refresh_cs_norms --tf 1D
    python -m ta_lab2.scripts.features.refresh_cs_norms --all-tfs
    python -m ta_lab2.scripts.features.refresh_cs_norms --tf 4H --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)

# =============================================================================
# Pilot column configuration
# =============================================================================

PILOT_COLUMNS = [
    "ret_arith",
    "rsi_14",
    "vol_parkinson_20",
]

# SQL template executed once per source column per TF.
# Window function computes mean/std/percent_rank in a single pass over the
# filtered rows (NULL source values excluded), then UPDATEs the base table.
_CS_NORMS_SQL_TEMPLATE = """
WITH cs_stats AS (
    SELECT
        id,
        ts,
        tf,
        {src_col},
        AVG({src_col})      OVER (PARTITION BY ts, tf) AS cs_mean,
        STDDEV({src_col})   OVER (PARTITION BY ts, tf) AS cs_std,
        PERCENT_RANK()      OVER (PARTITION BY ts, tf ORDER BY {src_col}) AS cs_prank,
        COUNT(*)            OVER (PARTITION BY ts, tf) AS n_assets
    FROM public.features
    WHERE {src_col} IS NOT NULL
      AND tf = :tf
)
UPDATE public.features f
SET
    {src_col}_cs_zscore = CASE
        WHEN cs.n_assets >= 5
        THEN (cs.{src_col} - cs.cs_mean) / NULLIF(cs.cs_std, 0)
        ELSE NULL
    END,
    {src_col}_cs_rank = CASE
        WHEN cs.n_assets >= 5 THEN cs.cs_prank
        ELSE NULL
    END
FROM cs_stats cs
WHERE f.id = cs.id
  AND f.ts = cs.ts
  AND f.tf = cs.tf;
"""


# =============================================================================
# Core callable
# =============================================================================


def refresh_cs_norms(engine: Engine, tf: str = "1D") -> int:
    """Refresh cross-sectional normalization columns in features for one TF.

    Runs one UPDATE statement per pilot column (3 total) inside a single
    transaction.  Each UPDATE sets <col>_cs_zscore and <col>_cs_rank using
    PostgreSQL PARTITION BY window functions.

    Args:
        engine: SQLAlchemy engine connected to the target database.
        tf:     Timeframe string (e.g. '1D', '4H').  Rows with this tf are
                processed; other TFs are untouched.

    Returns:
        Total number of rows updated (sum of cursor.rowcount for all 3 UPDATE
        statements).  May be 0 if no source data exists for the given TF.
    """
    total_rows = 0
    t0 = time.time()

    logger.info(f"CS norms refresh starting (tf={tf})")

    with engine.begin() as conn:
        for src_col in PILOT_COLUMNS:
            sql = _CS_NORMS_SQL_TEMPLATE.format(src_col=src_col)
            result = conn.execute(text(sql), {"tf": tf})
            rows = result.rowcount if result.rowcount is not None else 0
            total_rows += rows
            logger.info(
                f"  {src_col} -> {src_col}_cs_zscore / {src_col}_cs_rank: {rows} rows updated"
            )

    elapsed = time.time() - t0
    logger.info(
        f"CS norms refresh complete (tf={tf}): {total_rows} total rows in {elapsed:.2f}s"
    )
    return total_rows


# =============================================================================
# CLI
# =============================================================================


def _get_all_tfs(engine: Engine) -> list[str]:
    """Return list of distinct TF values present in features."""
    sql = "SELECT DISTINCT tf FROM public.features ORDER BY tf"
    with engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    return [r[0] for r in rows]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Refresh cross-sectional z-scores and ranks for 3 pilot features in features. "
            "Uses PARTITION BY (ts, tf) window functions. Timestamps with fewer than 5 assets "
            "are skipped (n_assets >= 5 guard)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Refresh CS norms for 1D timeframe (default)
  python -m ta_lab2.scripts.features.refresh_cs_norms --tf 1D

  # Refresh CS norms for all timeframes in features
  python -m ta_lab2.scripts.features.refresh_cs_norms --all-tfs

  # Preview SQL without executing (dry-run)
  python -m ta_lab2.scripts.features.refresh_cs_norms --tf 1D --dry-run

Pilot columns refreshed:
  ret_arith          -> ret_arith_cs_zscore,        ret_arith_cs_rank
  rsi_14             -> rsi_14_cs_zscore,            rsi_14_cs_rank
  vol_parkinson_20   -> vol_parkinson_20_cs_zscore,  vol_parkinson_20_cs_rank
""",
    )

    # Timeframe selection
    tf_group = parser.add_mutually_exclusive_group()
    tf_group.add_argument(
        "--tf",
        default="1D",
        help="Single timeframe to process (default: 1D)",
    )
    tf_group.add_argument(
        "--all-tfs",
        action="store_true",
        help="Process all timeframes present in features",
    )

    # Dry-run
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL statements but do not execute them",
    )

    # Logging
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if not TARGET_DB_URL:
        logger.error("TARGET_DB_URL not set")
        return 1

    # Dry-run: just print SQL and exit
    if args.dry_run:
        tfs = ["<all TFs>"] if args.all_tfs else [args.tf]
        for tf in tfs:
            print(f"\n--- TF: {tf} ---")
            for src_col in PILOT_COLUMNS:
                sql = _CS_NORMS_SQL_TEMPLATE.format(src_col=src_col)
                print(f"\n-- {src_col} --")
                print(sql)
        print("\n[dry-run] No changes made.")
        return 0

    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    try:
        if args.all_tfs:
            tfs = _get_all_tfs(engine)
            logger.info(f"Processing {len(tfs)} timeframes: {tfs}")
        else:
            tfs = [args.tf]
            logger.info(f"Processing timeframe: {args.tf}")

        grand_total = 0
        for tf in tfs:
            rows = refresh_cs_norms(engine, tf=tf)
            grand_total += rows

        print(
            f"\nCS norms refresh complete: {grand_total} total rows updated across {len(tfs)} TF(s)"
        )
        return 0

    except Exception as exc:
        logger.error(f"CS norms refresh failed: {exc}", exc_info=True)
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
