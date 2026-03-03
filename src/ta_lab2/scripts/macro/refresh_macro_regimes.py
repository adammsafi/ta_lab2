"""refresh_macro_regimes.py

CLI script for macro regime classification and upsert into cmc_macro_regimes.

Reads daily macro features from fred.fred_macro_features (Phase 65-66),
classifies each day into 4-dimensional regime labels (monetary_policy,
liquidity, risk_appetite, carry), applies hysteresis, computes composite
regime keys and bucketed macro_state, and upserts results to cmc_macro_regimes.

Follows the same patterns as refresh_macro_features.py (watermark-based
incremental, temp table + ON CONFLICT upsert, dry-run support).

Usage:
    python -m ta_lab2.scripts.macro.refresh_macro_regimes              # incremental
    python -m ta_lab2.scripts.macro.refresh_macro_regimes --dry-run    # compute only, no write
    python -m ta_lab2.scripts.macro.refresh_macro_regimes --full       # recompute from 2000-01-01
    python -m ta_lab2.scripts.macro.refresh_macro_regimes --verbose    # DEBUG logging
    python -m ta_lab2.scripts.macro.refresh_macro_regimes --profile conservative
    python -m ta_lab2.scripts.macro.refresh_macro_regimes --start-date 2020-01-01 --end-date 2026-01-01
    python -m ta_lab2.scripts.macro.refresh_macro_regimes --config path/to/config.yaml
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from ta_lab2.io import get_engine
from ta_lab2.macro.regime_classifier import (
    MacroRegimeClassifier,
    load_macro_regime_config,
)

logger = logging.getLogger(__name__)

# Full history start date (used with --full or when no watermark exists)
FULL_HISTORY_START = "2000-01-01"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for macro regime classification."""
    p = argparse.ArgumentParser(
        description=(
            "Classify daily macro features into 4-dimensional regime labels "
            "and upsert results to cmc_macro_regimes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Incremental refresh (default -- uses watermark)
  python -m ta_lab2.scripts.macro.refresh_macro_regimes

  # Dry run: compute regimes, print summary, do NOT write to DB
  python -m ta_lab2.scripts.macro.refresh_macro_regimes --dry-run

  # Full history recompute from 2000-01-01
  python -m ta_lab2.scripts.macro.refresh_macro_regimes --full

  # Use conservative profile instead of YAML active_profile
  python -m ta_lab2.scripts.macro.refresh_macro_regimes --profile conservative

  # Custom date range
  python -m ta_lab2.scripts.macro.refresh_macro_regimes --start-date 2020-01-01 --end-date 2026-01-01

  # Override config file path
  python -m ta_lab2.scripts.macro.refresh_macro_regimes --config path/to/config.yaml

  # Verbose / debug logging
  python -m ta_lab2.scripts.macro.refresh_macro_regimes --verbose
        """,
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute regimes but do NOT write to DB. Print summary of what would be written.",
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
        "--profile",
        metavar="PROFILE",
        default=None,
        help="Override active_profile from YAML config (default: use YAML's active_profile).",
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
    p.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Override path to macro_regime_config.yaml (default: auto-discover via project_root).",
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
    print("MACRO REGIME CLASSIFICATION")
    print(f"{'=' * 70}")
    if args.dry_run:
        print("[DRY RUN] Regimes will be computed but NOT written to DB")

    # Load config
    try:
        config = load_macro_regime_config(args.config)
    except FileNotFoundError as exc:
        print(f"[ERROR] Config file not found: {exc}")
        return 1
    except ValueError as exc:
        print(f"[ERROR] Invalid config: {exc}")
        return 1

    profile = args.profile or config["active_profile"]
    print(f"[INFO] Using profile: {profile}")

    # Connect to DB
    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ERROR] Could not create DB engine: {exc}")
        return 1

    # Create classifier
    try:
        classifier = MacroRegimeClassifier(engine, config=config, profile=profile)
    except ValueError as exc:
        print(f"[ERROR] Classifier initialization failed: {exc}")
        return 1

    if args.dry_run:
        # Dry-run path: use internal methods to classify without writing.
        # Determine compute window (mirrors classifier.classify logic)
        import pandas as pd

        end_date = args.end_date or pd.Timestamp.now("UTC").strftime("%Y-%m-%d")
        if args.start_date:
            start_date = args.start_date
        elif args.full:
            start_date = FULL_HISTORY_START
        else:
            watermark = classifier._get_watermark()
            if watermark is not None:
                start_date = (pd.Timestamp(watermark) - pd.Timedelta(days=60)).strftime(
                    "%Y-%m-%d"
                )
            else:
                start_date = FULL_HISTORY_START

        print(f"[INFO] Compute window: {start_date} to {end_date}")
        print("[INFO] Loading macro features...")

        try:
            df_features = classifier._load_features(start_date, end_date)
        except ValueError as exc:
            print(f"[ERROR] Column validation failed: {exc}")
            return 1

        if df_features.empty:
            print(
                "[WARN] No macro features found -- FRED data may not be available. "
                "Run refresh_macro_features.py to populate."
            )
            elapsed = time.perf_counter() - t0
            print(f"\n[DONE] Elapsed: {elapsed:.1f}s (0 rows)")
            return 0

        print(f"[INFO] Loaded {len(df_features)} feature rows")
        print("[INFO] Classifying (dry-run)...")

        # Load hysteresis state for accurate dry-run labels
        from ta_lab2.macro.regime_classifier import _load_hysteresis_state

        _load_hysteresis_state(engine, profile, classifier.tracker)

        result_df = classifier._classify_dataframe(df_features)

        print(
            f"\n[DRY RUN] Would upsert {len(result_df)} rows to cmc_macro_regimes (profile={profile})"
        )

        if "macro_state" in result_df.columns:
            state_counts = result_df["macro_state"].value_counts()
            print(f"\nMacro state distribution:\n{state_counts.to_string()}")

        # Show dimension label distributions
        for dim in ["monetary_policy", "liquidity", "risk_appetite", "carry"]:
            if dim in result_df.columns:
                dist = result_df[dim].value_counts()
                print(f"\n{dim}:\n{dist.to_string()}")

        print("\nSample output (last 10 rows):")
        print(result_df.tail(10).to_string())

        elapsed = time.perf_counter() - t0
        print(
            f"\n[DRY RUN DONE] Elapsed: {elapsed:.1f}s "
            f"({len(result_df)} rows classified, 0 rows written)"
        )
        return 0

    # Live path: classify and upsert via the public API
    print("[INFO] Starting macro regime classification...")
    try:
        n_upserted = classifier.classify(
            start_date=args.start_date,
            end_date=args.end_date,
            full=args.full,
        )
    except ValueError as exc:
        print(f"[ERROR] Classification failed (column validation): {exc}")
        return 1
    except Exception as exc:
        print(f"[ERROR] Classification failed: {exc}")
        logger.exception("classify() raised an exception")
        return 1

    elapsed = time.perf_counter() - t0

    if n_upserted == 0:
        print(
            "[INFO] No new regime rows to write (up to date or no features available)"
        )
        print(f"\n[DONE] Elapsed: {elapsed:.1f}s (0 rows upserted)")
    else:
        print(
            f"\n[OK] Macro regime classification complete in {elapsed:.1f}s: "
            f"{n_upserted} rows upserted to cmc_macro_regimes (profile={profile})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
