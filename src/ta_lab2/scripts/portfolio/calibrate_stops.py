"""Calibrate stop-loss and take-profit levels from bake-off MAE/MFE data.

Reads (asset_id, signal_id, strategy) combinations from backtest_runs,
calls calibrate_stops_from_mae_mfe() for each combination, and persists
the resulting percentile-based stop levels to the stop_calibrations table.

Assets/strategies with fewer than MIN_TRADES_FOR_CALIBRATION (30) trades
are skipped -- they will continue to use global defaults from portfolio.yaml.

ASCII-only file -- no UTF-8 box-drawing characters.

Usage:
    python -m ta_lab2.scripts.portfolio.calibrate_stops --ids all --dry-run
    python -m ta_lab2.scripts.portfolio.calibrate_stops --ids 1,52,825 --verbose
    python -m ta_lab2.scripts.portfolio.calibrate_stops --ids all --tf 1D
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _resolve_db_url(db_url_arg: Optional[str]) -> str:
    """Resolve DB URL from argument, env, or config file."""
    if db_url_arg:
        return db_url_arg

    url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
    if url:
        return url

    config_path = "db_config.env"
    try:
        p = Path(config_path)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("TARGET_DB_URL=") or line.startswith(
                    "DATABASE_URL="
                ):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass

    raise RuntimeError(
        "No database URL found. Set TARGET_DB_URL env var or pass --db-url."
    )


def _make_engine(db_url: str):
    """Create a NullPool SQLAlchemy engine (batch script pattern)."""
    return create_engine(db_url, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Asset ID resolution
# ---------------------------------------------------------------------------


def _resolve_asset_ids(ids_arg: str, engine) -> list[int]:
    """Resolve asset IDs from 'all' or comma-separated list."""
    if ids_arg.lower() == "all":
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT asset_id "
                    "FROM public.backtest_runs "
                    "ORDER BY asset_id"
                )
            ).fetchall()
        ids = [r[0] for r in rows]
        logger.info("Resolved %d distinct asset IDs from backtest_runs", len(ids))
        return ids

    try:
        return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]
    except ValueError as exc:
        raise ValueError(
            f"Invalid --ids value {ids_arg!r}. "
            "Use 'all' or a comma-separated list of integers."
        ) from exc


# ---------------------------------------------------------------------------
# Combinations loader
# ---------------------------------------------------------------------------


def _load_run_combinations(engine, asset_ids: list[int]) -> list[dict[str, Any]]:
    """Load distinct (asset_id, signal_id, strategy) from backtest_runs.

    strategy is read from dim_signals.strategy_type if available,
    falling back to signal_id cast to string.

    Returns list of dicts with keys: asset_id, signal_id, strategy.
    """
    # First try joining dim_signals for the strategy name
    try:
        sql = text(
            """
            SELECT DISTINCT
                br.asset_id,
                br.signal_id,
                COALESCE(ds.strategy_type, br.signal_id::TEXT) AS strategy
            FROM public.backtest_runs br
            LEFT JOIN public.dim_signals ds ON ds.signal_id = br.signal_id
            WHERE br.asset_id = ANY(:asset_ids)
              AND br.signal_id IS NOT NULL
            ORDER BY br.asset_id, br.signal_id
            """
        )
        with engine.connect() as conn:
            rows = conn.execute(sql, {"asset_ids": asset_ids}).fetchall()

        combinations = [
            {"asset_id": r[0], "signal_id": r[1], "strategy": str(r[2])} for r in rows
        ]
        logger.info(
            "Loaded %d (asset_id, signal_id, strategy) combinations from backtest_runs",
            len(combinations),
        )
        return combinations

    except Exception as exc:
        logger.warning(
            "_load_run_combinations: query failed (dim_signals join): %s -- "
            "falling back to signal_id as strategy",
            exc,
        )

    # Fallback: no dim_signals join
    sql_fallback = text(
        """
        SELECT DISTINCT
            br.asset_id,
            br.signal_id,
            br.signal_id::TEXT AS strategy
        FROM public.backtest_runs br
        WHERE br.asset_id = ANY(:asset_ids)
          AND br.signal_id IS NOT NULL
        ORDER BY br.asset_id, br.signal_id
        """
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql_fallback, {"asset_ids": asset_ids}).fetchall()

        combinations = [
            {"asset_id": r[0], "signal_id": r[1], "strategy": str(r[2])} for r in rows
        ]
        logger.info(
            "Loaded %d combinations (fallback, no dim_signals join)",
            len(combinations),
        )
        return combinations
    except Exception as exc2:
        logger.error("_load_run_combinations: fallback query also failed: %s", exc2)
        return []


# ---------------------------------------------------------------------------
# Main calibration logic
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Entry point for stop calibration CLI.

    Returns 0 on success, non-zero on error.
    """
    parser = argparse.ArgumentParser(
        description="Calibrate stop/TP levels from bake-off MAE/MFE data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--ids",
        default="all",
        help="Asset IDs to calibrate: 'all' or comma-separated integers (default: all)",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe filter (informational; filtering is by signal_id) (default: 1D)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute calibrations but do NOT write to DB",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="SQLAlchemy database URL (overrides TARGET_DB_URL env var)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    logger.info(
        "calibrate_stops: ids=%s tf=%s dry_run=%s",
        args.ids,
        args.tf,
        args.dry_run,
    )

    try:
        db_url = _resolve_db_url(args.db_url)
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    engine = _make_engine(db_url)

    # Resolve asset IDs
    try:
        asset_ids = _resolve_asset_ids(args.ids, engine)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    if not asset_ids:
        logger.warning("No asset IDs found -- nothing to calibrate")
        return 0

    # Load (asset_id, signal_id, strategy) combinations
    combinations = _load_run_combinations(engine, asset_ids)
    if not combinations:
        logger.warning("No backtest_runs combinations found -- nothing to calibrate")
        return 0

    # Import calibration functions
    from ta_lab2.analysis.stop_calibration import (
        MIN_TRADES_FOR_CALIBRATION,
        calibrate_stops_from_mae_mfe,
        persist_calibrations,
    )

    # Run calibration for each combination
    total_checked = len(combinations)
    calibrations: list[dict[str, Any]] = []
    skipped = 0

    for combo in combinations:
        asset_id = combo["asset_id"]
        signal_id = combo["signal_id"]
        strategy = combo["strategy"]

        result = calibrate_stops_from_mae_mfe(engine, asset_id, strategy, signal_id)
        if result is None:
            skipped += 1
            continue

        result["id"] = asset_id
        result["strategy"] = strategy
        calibrations.append(result)

    written = 0
    if calibrations:
        if args.dry_run:
            logger.info(
                "DRY-RUN: would write %d calibration rows (skipped %d combinations "
                "with < %d trades)",
                len(calibrations),
                skipped,
                MIN_TRADES_FOR_CALIBRATION,
            )
            written = 0
        else:
            written = persist_calibrations(engine, calibrations)
    else:
        logger.info(
            "No calibration rows to write (all %d combinations had < %d trades)",
            total_checked,
            MIN_TRADES_FOR_CALIBRATION,
        )

    print(
        f"calibrate_stops: checked={total_checked} "
        f"calibrated={len(calibrations)} "
        f"skipped={skipped} "
        f"written={'DRY-RUN' if args.dry_run else written}"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
