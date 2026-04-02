"""
Backfill Monte Carlo Sharpe confidence intervals on strategy_bakeoff_results.

Populates mc_sharpe_lo, mc_sharpe_hi, mc_sharpe_median for every
strategy_bakeoff_results row where these columns are NULL. Reads fold-level
Sharpe values from fold_metrics_json, runs 1000 bootstrap resamples of
the fold Sharpe distribution, and writes back the 5th/95th percentile and median.

This approach is statistically appropriate because:
- BakeoffOrchestrator stores per-fold Sharpe in fold_metrics_json
- Bootstrap resampling of fold-level Sharpes gives CI on the mean Sharpe estimate
- No trade-level data from backtest_trades is needed (the bakeoff pipeline
  does not write to backtest_trades)

Usage:
    python -m ta_lab2.scripts.backtests.backfill_mc_bands
    python -m ta_lab2.scripts.backtests.backfill_mc_bands --dry-run
    python -m ta_lab2.scripts.backtests.backfill_mc_bands --batch-size 100
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from typing import List, Optional, Tuple

import numpy as np
from sqlalchemy import NullPool, create_engine, text

from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bootstrap helper
# ---------------------------------------------------------------------------


def _bootstrap_fold_sharpes(
    sharpes: List[float],
    n_samples: int = 1000,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """
    Bootstrap resample fold-level Sharpe values and return CI.

    Parameters
    ----------
    sharpes : list of float
        Valid (non-NaN) fold-level Sharpe values.
    n_samples : int
        Number of bootstrap resamples (default 1000).
    seed : int
        Random seed for reproducibility (default 42).

    Returns
    -------
    tuple of (mc_lo, mc_hi, mc_median) : (float, float, float)
        5th percentile, 95th percentile, and median of bootstrapped mean Sharpes.
    """
    rng = np.random.default_rng(seed=seed)
    n_folds = len(sharpes)
    sharpe_arr = np.array(sharpes, dtype=float)

    # Vectorized: draw all bootstrap samples at once (n_samples x n_folds)
    indices = rng.integers(0, n_folds, size=(n_samples, n_folds))
    boot_means = sharpe_arr[indices].mean(axis=1)

    mc_lo = float(np.percentile(boot_means, 5))
    mc_hi = float(np.percentile(boot_means, 95))
    mc_median = float(np.median(boot_means))

    return mc_lo, mc_hi, mc_median


# ---------------------------------------------------------------------------
# Main backfill
# ---------------------------------------------------------------------------


def _check_mc_columns_exist(engine) -> bool:
    """Check that mc_sharpe_lo/hi/median columns exist on strategy_bakeoff_results."""
    sql = text(
        """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'strategy_bakeoff_results'
          AND column_name IN ('mc_sharpe_lo', 'mc_sharpe_hi', 'mc_sharpe_median')
        """
    )
    with engine.connect() as conn:
        count = conn.execute(sql).scalar() or 0
    return count == 3


def backfill_mc_bands(
    engine,
    batch_size: int = 500,
    n_samples: int = 1000,
    dry_run: bool = False,
) -> None:
    """
    Populate mc_sharpe_lo/hi/median for all strategy_bakeoff_results rows
    where these columns are NULL and fold_metrics_json is not NULL.

    Parameters
    ----------
    engine : sqlalchemy.Engine
        Database engine.
    batch_size : int
        Number of rows to process per commit (default 500).
    n_samples : int
        Bootstrap resamples per row (default 1000).
    dry_run : bool
        If True, count NULL rows and exit without processing.
    """
    # --- Pre-flight: verify migration has been applied ---
    if not _check_mc_columns_exist(engine):
        raise RuntimeError(
            "MC columns (mc_sharpe_lo, mc_sharpe_hi, mc_sharpe_median) do not exist "
            "on public.strategy_bakeoff_results. "
            "Run 'alembic upgrade head' to apply migration s3t4u5v6w7x8 first."
        )

    # --- Count NULL rows ---
    count_sql = text(
        """
        SELECT COUNT(*)
        FROM public.strategy_bakeoff_results
        WHERE mc_sharpe_lo IS NULL
          AND fold_metrics_json IS NOT NULL
        """
    )
    with engine.connect() as conn:
        null_count = conn.execute(count_sql).scalar() or 0

    logger.info(
        f"strategy_bakeoff_results: {null_count} rows with NULL mc_sharpe_lo "
        f"and non-NULL fold_metrics_json"
    )

    if dry_run:
        print(f"\nDry run: {null_count} rows need MC band backfill\n")
        # Also report current non-null count
        nonnull_sql = text(
            """
            SELECT COUNT(*)
            FROM public.strategy_bakeoff_results
            WHERE mc_sharpe_lo IS NOT NULL
            """
        )
        with engine.connect() as conn:
            nonnull_count = conn.execute(nonnull_sql).scalar() or 0
        print(f"Already populated: {nonnull_count} rows")
        print("No changes made (dry-run mode).\n")
        return

    if null_count == 0:
        logger.info("No rows need backfill. Exiting.")
        return

    # --- Process in streaming batches (no full fetchall) ---
    select_sql = text(
        """
        SELECT id, fold_metrics_json
        FROM public.strategy_bakeoff_results
        WHERE mc_sharpe_lo IS NULL
          AND fold_metrics_json IS NOT NULL
        ORDER BY id
        """
    )

    logger.info(f"Processing ~{null_count} rows in batches of {batch_size}...")

    updates: List[Tuple[int, Optional[float], Optional[float], Optional[float]]] = []
    n_processed = 0
    n_skipped = 0
    n_committed = 0
    import time

    t0 = time.time()

    with engine.connect() as conn:
        result = conn.execution_options(stream_results=True).execute(select_sql)
        for row in result:
            row_id = row[0]
            fold_metrics_raw = row[1]

            # Parse fold_metrics_json
            try:
                if isinstance(fold_metrics_raw, str):
                    fold_metrics = json.loads(fold_metrics_raw)
                else:
                    fold_metrics = fold_metrics_raw  # already a dict/list from JSONB
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    f"Row {row_id}: failed to parse fold_metrics_json: {exc}"
                )
                n_skipped += 1
                continue

            if not isinstance(fold_metrics, list):
                logger.warning(
                    f"Row {row_id}: fold_metrics_json is not a list; skipping"
                )
                n_skipped += 1
                continue

            # Extract valid fold-level Sharpe values
            sharpes: List[float] = []
            for fm in fold_metrics:
                if not isinstance(fm, dict):
                    continue
                sharpe_val = fm.get("sharpe")
                if sharpe_val is None:
                    continue
                try:
                    s = float(sharpe_val)
                except (TypeError, ValueError):
                    continue
                if not math.isnan(s) and not math.isinf(s):
                    sharpes.append(s)

            # Skip rows with fewer than 3 valid fold Sharpes
            if len(sharpes) < 3:
                logger.debug(
                    f"Row {row_id}: only {len(sharpes)} valid fold Sharpes "
                    f"(need >= 3); skipping"
                )
                n_skipped += 1
                continue

            # Bootstrap
            try:
                mc_lo, mc_hi, mc_median = _bootstrap_fold_sharpes(
                    sharpes, n_samples=n_samples
                )
            except Exception as exc:
                logger.warning(f"Row {row_id}: bootstrap failed: {exc}")
                n_skipped += 1
                continue

            updates.append((row_id, mc_lo, mc_hi, mc_median))
            n_processed += 1

            # Commit batch
            if len(updates) >= batch_size:
                _commit_batch(engine, updates)
                n_committed += len(updates)
                elapsed = time.time() - t0
                rate = n_committed / elapsed if elapsed > 0 else 0
                eta = (null_count - n_committed) / rate if rate > 0 else 0
                logger.info(
                    f"Progress: {n_committed:,}/{null_count:,} "
                    f"({100 * n_committed / null_count:.1f}%) "
                    f"| {rate:.0f} rows/s | ETA {eta / 60:.1f}m"
                )
                updates = []

    # Commit remaining
    if updates:
        _commit_batch(engine, updates)
        n_committed += len(updates)

    logger.info(f"Backfill complete: {n_committed} rows updated, {n_skipped} skipped")

    # Final stats
    with engine.connect() as conn:
        final_null = conn.execute(
            text(
                "SELECT COUNT(*) FROM public.strategy_bakeoff_results "
                "WHERE mc_sharpe_lo IS NULL"
            )
        ).scalar()
        final_nonnull = conn.execute(
            text(
                "SELECT COUNT(*) FROM public.strategy_bakeoff_results "
                "WHERE mc_sharpe_lo IS NOT NULL"
            )
        ).scalar()

    logger.info(
        f"Final state: {final_nonnull} rows with mc_sharpe_lo, "
        f"{final_null} rows still NULL"
    )


def _commit_batch(
    engine,
    updates: List[Tuple[int, Optional[float], Optional[float], Optional[float]]],
) -> None:
    """Commit a batch of (id, mc_lo, mc_hi, mc_median) updates."""
    if not updates:
        return

    update_sql = text(
        """
        UPDATE public.strategy_bakeoff_results
        SET mc_sharpe_lo = :mc_lo,
            mc_sharpe_hi = :mc_hi,
            mc_sharpe_median = :mc_median
        WHERE id = :row_id
        """
    )
    with engine.begin() as conn:
        conn.execute(
            update_sql,
            [
                {
                    "row_id": row_id,
                    "mc_lo": mc_lo,
                    "mc_hi": mc_hi,
                    "mc_median": mc_median,
                }
                for row_id, mc_lo, mc_hi, mc_median in updates
            ],
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill Monte Carlo Sharpe CI on strategy_bakeoff_results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count NULL rows without processing.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows to process per commit (default 500).",
    )
    parser.add_argument(
        "--n-samples",
        type=int,
        default=1000,
        help="Bootstrap resamples per row (default 1000).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if not TARGET_DB_URL:
        print(
            "ERROR: TARGET_DB_URL not set. Check db_config.env or environment.",
            file=sys.stderr,
        )
        sys.exit(1)

    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    backfill_mc_bands(
        engine,
        batch_size=args.batch_size,
        n_samples=args.n_samples,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
