"""refresh_cross_asset_agg.py

CLI script for cross-asset aggregation refresh (Phase 70, XAGG-01 through XAGG-04).

Orchestrates all four cross-asset signal computations in sequence:
  XAGG-01/02: BTC/ETH 30d correlation + average pairwise correlation with
              high_corr_flag -> cross_asset_agg
  XAGG-03:   Aggregate funding rate with 30d/90d z-scores -> funding_rate_agg
  XAGG-04:   Crypto-macro correlation regime with sign-flip detection
             -> crypto_macro_corr_regimes + macro_regimes.crypto_macro_corr

Follows the same patterns as refresh_macro_regimes.py and refresh_macro_analytics.py:
watermark-based incremental refresh, temp table + ON CONFLICT upsert, dry-run support.

Usage:
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg              # incremental
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --dry-run    # compute only, no write
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --full       # recompute from 2020-01-01
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --verbose    # DEBUG logging
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --start-date 2024-01-01 --end-date 2026-01-01
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --config path/to/config.yaml
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --skip-corr      # skip XAGG-01/02
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --skip-funding   # skip XAGG-03
    python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --skip-macro-corr  # skip XAGG-04
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from ta_lab2.io import get_engine
from ta_lab2.macro.cross_asset import (
    compute_btc_equity_corr,
    compute_cross_asset_corr,
    compute_crypto_macro_corr,
    compute_funding_rate_agg,
    load_cross_asset_config,
    upsert_cross_asset_agg,
    upsert_crypto_macro_corr,
    upsert_funding_rate_agg,
    update_macro_regime_corr,
)

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for cross-asset aggregation refresh."""
    p = argparse.ArgumentParser(
        description=(
            "Compute cross-asset aggregation signals (XAGG-01 through XAGG-04) "
            "and upsert results to cross_asset_agg, funding_rate_agg, "
            "and crypto_macro_corr_regimes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Incremental refresh (default -- uses watermarks)
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg

  # Dry run: compute all 4 XAGG outputs, print summary, do NOT write to DB
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --dry-run

  # Full history recompute from 2020-01-01
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --full

  # Custom date range
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --start-date 2024-01-01 --end-date 2026-01-01

  # Skip specific computations
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --skip-corr
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --skip-funding
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --skip-macro-corr

  # Override config file path
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --config path/to/config.yaml

  # Verbose / debug logging
  python -m ta_lab2.scripts.macro.refresh_cross_asset_agg --verbose
        """,
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Compute all 4 XAGG outputs but do NOT write to DB. "
            "Print summary of what would be written."
        ),
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Ignore watermarks; recompute full history from 2020-01-01.",
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
        help=(
            "Override path to cross_asset_config.yaml "
            "(default: auto-discover via project_root)."
        ),
    )
    p.add_argument(
        "--skip-corr",
        action="store_true",
        help="Skip XAGG-01/02: cross-asset correlation computation.",
    )
    p.add_argument(
        "--skip-funding",
        action="store_true",
        help="Skip XAGG-03: aggregate funding rate computation.",
    )
    p.add_argument(
        "--skip-macro-corr",
        action="store_true",
        help="Skip XAGG-04: crypto-macro correlation regime computation.",
    )

    args = p.parse_args(argv)

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    t0_total = time.perf_counter()

    print(f"\n{'=' * 70}")
    print("CROSS-ASSET AGGREGATION REFRESH (Phase 70)")
    print(f"{'=' * 70}")
    if args.dry_run:
        print("[DRY RUN] Outputs will be computed but NOT written to DB")

    # Load config
    try:
        config = load_cross_asset_config(args.config)
    except FileNotFoundError as exc:
        print(f"[ERROR] Config file not found: {exc}")
        return 1
    except ValueError as exc:
        print(f"[ERROR] Invalid config: {exc}")
        return 1

    print(
        f"[INFO] high_corr_threshold={config['cross_asset']['high_corr_threshold']}, "
        f"sign_flip_threshold={config['crypto_macro']['sign_flip_threshold']}, "
        f"corr_window={config['crypto_macro']['corr_window']}d"
    )

    # Resolve date range for all steps (passed through to individual functions)
    start_date = args.start_date
    end_date = args.end_date
    if args.full:
        start_date = "2020-01-01"
        print(f"[INFO] Full history mode: start_date forced to {start_date}")

    # Connect to DB
    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ERROR] Could not create DB engine: {exc}")
        return 1

    any_failure = False

    # -----------------------------------------------------------------------
    # XAGG-01/02: Cross-asset correlation
    # -----------------------------------------------------------------------
    if not args.skip_corr:
        print(f"\n{'-' * 70}")
        print("XAGG-01/02: Cross-Asset Correlation (BTC/ETH + Average Pairwise)")
        print(f"{'-' * 70}")
        t0 = time.perf_counter()
        try:
            corr_df = compute_cross_asset_corr(
                engine, config, start_date=start_date, end_date=end_date
            )
            elapsed = time.perf_counter() - t0

            if corr_df.empty:
                print(
                    "[WARN] No cross-asset correlation data computed "
                    "(no returns data available?)"
                )
            else:
                print(
                    f"[INFO] Computed {len(corr_df)} rows "
                    f"({corr_df['date'].min()} to {corr_df['date'].max()})"
                )
                print(
                    f"[INFO] BTC/ETH corr non-null: {corr_df['btc_eth_corr_30d'].notna().sum()}"
                )
                print(
                    f"[INFO] High-corr flag days: "
                    f"{corr_df['high_corr_flag'].sum() if corr_df['high_corr_flag'].notna().any() else 0}"
                )

                if args.dry_run:
                    print(
                        f"\n[DRY RUN] Would upsert {len(corr_df)} rows to cross_asset_agg"
                    )
                    print("\nSample output (last 5 rows):")
                    print(corr_df.tail(5).to_string())
                else:
                    n = upsert_cross_asset_agg(engine, corr_df)
                    print(
                        f"[OK] XAGG-01/02 complete: {n} rows upserted in {elapsed:.1f}s"
                    )

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"[ERROR] XAGG-01/02 failed after {elapsed:.1f}s: {exc}")
            logger.exception("XAGG-01/02 raised an exception")
            any_failure = True
    else:
        print("\n[SKIP] XAGG-01/02 cross-asset correlation (--skip-corr)")

    # -----------------------------------------------------------------------
    # XAGG-03: Aggregate funding rate
    # -----------------------------------------------------------------------
    if not args.skip_funding:
        print(f"\n{'-' * 70}")
        print("XAGG-03: Aggregate Funding Rate (30d/90d z-scores)")
        print(f"{'-' * 70}")
        t0 = time.perf_counter()
        try:
            funding_df = compute_funding_rate_agg(
                engine, config, start_date=start_date, end_date=end_date
            )
            elapsed = time.perf_counter() - t0

            if funding_df.empty:
                print(
                    "[WARN] No funding rate data computed "
                    "(funding_rates may not be populated?)"
                )
            else:
                print(
                    f"[INFO] Computed {len(funding_df)} rows for "
                    f"{funding_df['symbol'].nunique()} symbols"
                )

                if args.dry_run:
                    print(
                        f"\n[DRY RUN] Would upsert {len(funding_df)} rows to "
                        "funding_rate_agg"
                    )
                    print("\nSample output (last 10 rows):")
                    print(funding_df.tail(10).to_string())
                else:
                    n = upsert_funding_rate_agg(engine, funding_df)
                    print(f"[OK] XAGG-03 complete: {n} rows upserted in {elapsed:.1f}s")

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"[ERROR] XAGG-03 failed after {elapsed:.1f}s: {exc}")
            logger.exception("XAGG-03 raised an exception")
            any_failure = True
    else:
        print("\n[SKIP] XAGG-03 funding rate aggregation (--skip-funding)")

    # -----------------------------------------------------------------------
    # XAGG-04: Crypto-macro correlation regime
    # -----------------------------------------------------------------------
    if not args.skip_macro_corr:
        print(f"\n{'-' * 70}")
        print("XAGG-04: Crypto-Macro Correlation Regime (sign-flip detection)")
        print(f"{'-' * 70}")
        t0 = time.perf_counter()
        try:
            macro_corr_df, macro_regime_df = compute_crypto_macro_corr(
                engine, config, start_date=start_date, end_date=end_date
            )
            elapsed = time.perf_counter() - t0

            if macro_corr_df.empty:
                print(
                    "[WARN] No crypto-macro correlation data computed "
                    "(returns or FRED data may not be available?)"
                )
            else:
                n_flips = (
                    int(macro_corr_df["sign_flip_flag"].sum())
                    if "sign_flip_flag" in macro_corr_df.columns
                    else 0
                )
                print(
                    f"[INFO] Computed {len(macro_corr_df)} correlation rows for "
                    f"{macro_corr_df['asset_id'].nunique()} assets x "
                    f"{macro_corr_df['macro_var'].nunique()} macro vars"
                )
                print(f"[INFO] Sign-flip events detected: {n_flips}")
                print(f"[INFO] Macro regime labels: {len(macro_regime_df)} rows")

                if args.dry_run:
                    print(
                        f"\n[DRY RUN] Would upsert {len(macro_corr_df)} rows to "
                        "crypto_macro_corr_regimes"
                    )
                    print(
                        f"[DRY RUN] Would update {len(macro_regime_df)} rows in "
                        "macro_regimes.crypto_macro_corr"
                    )
                    print("\nSample correlation output (last 10 rows):")
                    print(macro_corr_df.tail(10).to_string())
                    if not macro_regime_df.empty:
                        print("\nSample regime labels (last 5 rows):")
                        print(macro_regime_df.tail(5).to_string())
                else:
                    n_corr = upsert_crypto_macro_corr(engine, macro_corr_df)
                    n_regime = update_macro_regime_corr(engine, macro_regime_df)
                    print(
                        f"[OK] XAGG-04 complete: {n_corr} correlation rows upserted, "
                        f"{n_regime} macro_regime rows updated in {elapsed:.1f}s"
                    )

        except Exception as exc:
            elapsed = time.perf_counter() - t0
            print(f"[ERROR] XAGG-04 failed after {elapsed:.1f}s: {exc}")
            logger.exception("XAGG-04 raised an exception")
            any_failure = True

        # -------------------------------------------------------------------
        # XAGG-05: BTC-equity multi-window correlation (Phase 97)
        # -------------------------------------------------------------------
        if "btc_equity" in config and not any_failure:
            print(f"\n{'-' * 70}")
            print("XAGG-05: BTC-Equity Multi-Window Correlation (30/60/90/180d)")
            print(f"{'-' * 70}")
            t0 = time.perf_counter()
            try:
                btc_equity_df = compute_btc_equity_corr(
                    engine, config, start_date=start_date, end_date=end_date
                )
                elapsed = time.perf_counter() - t0

                if btc_equity_df.empty:
                    print(
                        "[WARN] No BTC-equity correlation data computed "
                        "(BTC returns or equity macro data not available?)"
                    )
                else:
                    n_windows = (
                        btc_equity_df["window"].nunique()
                        if "window" in btc_equity_df.columns
                        else "?"
                    )
                    n_vars = btc_equity_df["macro_var"].nunique()
                    print(
                        f"[INFO] Computed {len(btc_equity_df)} rows for "
                        f"{n_vars} equity vars x {n_windows} windows"
                    )

                    if args.dry_run:
                        print(
                            f"\n[DRY RUN] Would upsert {len(btc_equity_df)} rows to "
                            "crypto_macro_corr_regimes"
                        )
                        print("\nSample output (last 10 rows):")
                        print(
                            btc_equity_df[
                                [
                                    "date",
                                    "macro_var",
                                    "window",
                                    "corr_60d",
                                    "equity_vol_regime",
                                    "divergence_flag",
                                ]
                            ]
                            .tail(10)
                            .to_string()
                        )
                    else:
                        n_eq = upsert_crypto_macro_corr(engine, btc_equity_df)
                        print(
                            f"[OK] XAGG-05 complete: {n_eq} BTC-equity corr rows "
                            f"upserted in {elapsed:.1f}s"
                        )

            except Exception as exc:
                elapsed = time.perf_counter() - t0
                print(f"[ERROR] XAGG-05 failed after {elapsed:.1f}s: {exc}")
                logger.exception("XAGG-05 raised an exception")
                any_failure = True

    else:
        print("\n[SKIP] XAGG-04/05 crypto-macro correlation (--skip-macro-corr)")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    total_elapsed = time.perf_counter() - t0_total
    print(f"\n{'=' * 70}")
    if args.dry_run:
        print(f"[DRY RUN DONE] Elapsed: {total_elapsed:.1f}s (0 rows written)")
    elif any_failure:
        print(
            f"[PARTIAL] Cross-asset aggregation completed with errors in {total_elapsed:.1f}s"
        )
        print("Check log above for details on which XAGG computations failed.")
    else:
        print(f"[OK] Cross-asset aggregation complete in {total_elapsed:.1f}s")
    print(f"{'=' * 70}")

    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
