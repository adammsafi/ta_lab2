"""refresh_macro_analytics.py

Unified CLI entry point for all Phase 68 HMM macro analytics tools.

Orchestrates three analytical modules in sequence:
  1. HMMClassifier      -- GaussianHMM secondary regime classifier (MREG-10)
  2. LeadLagAnalyzer    -- Macro-to-crypto lead-lag scanner (MREG-11)
  3. TransitionProbMatrix -- Regime transition probability matrices (MREG-12)

Each tool is wrapped in independent try/except so a failure in one does
not prevent the others from running. Exit code is 1 if any tool fails.

Follows the same pattern as refresh_macro_features.py and refresh_macro_regimes.py.

Usage:
    # Run all three tools (default)
    python -m ta_lab2.scripts.macro.refresh_macro_analytics

    # Dry run: compute but do NOT write to DB
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --dry-run

    # Force HMM refit + full lead-lag rescan
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --full

    # Verbose / debug logging
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --verbose

    # Run only HMM classifier
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --hmm-only

    # Run only lead-lag analysis
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --lead-lag-only

    # Run only transition probabilities
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --transition-only

    # Override HMM covariance type
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --covariance-type full

    # Force HMM model refit regardless of weekly cadence
    python -m ta_lab2.scripts.macro.refresh_macro_analytics --force-refit
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from ta_lab2.io import get_engine
from ta_lab2.macro.hmm_classifier import HMMClassifier
from ta_lab2.macro.lead_lag_analyzer import LeadLagAnalyzer
from ta_lab2.macro.transition_probs import TransitionProbMatrix

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    p = argparse.ArgumentParser(
        description=(
            "Run Phase 68 macro analytics: HMM classifier, lead-lag analysis, "
            "and transition probability matrices."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run all three tools (default)
  python -m ta_lab2.scripts.macro.refresh_macro_analytics

  # Dry run: compute but do NOT write to DB
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --dry-run

  # Force HMM refit + full lead-lag rescan
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --full

  # Verbose / debug logging
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --verbose

  # Run only HMM classifier
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --hmm-only

  # Run only lead-lag analysis
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --lead-lag-only

  # Run only transition probabilities
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --transition-only

  # Override HMM covariance type (default: diag)
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --covariance-type full

  # Force HMM model refit regardless of weekly cadence
  python -m ta_lab2.scripts.macro.refresh_macro_analytics --force-refit
        """,
    )

    # Mode flags
    p.add_argument(
        "--full",
        action="store_true",
        help=(
            "Force HMM refit (ignores weekly cadence) and full lead-lag rescan. "
            "Equivalent to --force-refit for HMM."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute results but do NOT write to DB.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    # Tool selection (if none specified, all three run)
    p.add_argument(
        "--hmm-only",
        action="store_true",
        help="Run only the HMM classifier (skip lead-lag and transition probs).",
    )
    p.add_argument(
        "--lead-lag-only",
        action="store_true",
        help="Run only lead-lag analysis (skip HMM and transition probs).",
    )
    p.add_argument(
        "--transition-only",
        action="store_true",
        help="Run only transition probability matrices (skip HMM and lead-lag).",
    )

    # HMM-specific options
    p.add_argument(
        "--covariance-type",
        choices=["full", "diag"],
        default="diag",
        help=(
            "HMM covariance type. Default: diag (safe for 38 features; "
            "avoids O(n^2) parameter instability). Use 'full' only if "
            "sufficient data and cross-feature correlations are desired."
        ),
    )
    p.add_argument(
        "--force-refit",
        action="store_true",
        help=(
            "Force HMM model refit regardless of weekly cadence. "
            "Useful for debugging or after major feature changes."
        ),
    )

    return p.parse_args(argv)


def setup_logging(verbose: bool) -> None:
    """Configure logging level."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for Phase 68 macro analytics refresh."""
    args = parse_args(argv)
    setup_logging(args.verbose)

    t0 = time.perf_counter()

    print(f"\n{'=' * 70}")
    print("MACRO ANALYTICS REFRESH (Phase 68)")
    print(f"{'=' * 70}")
    if args.dry_run:
        print("[DRY RUN] Results will be computed but NOT written to DB")

    try:
        engine = get_engine()
    except Exception as exc:
        print(f"[ERROR] Could not create DB engine: {exc}")
        return 1

    # Determine which tools to run
    run_all = not (args.hmm_only or args.lead_lag_only or args.transition_only)
    results: dict[str, str] = {}

    # ── 1. HMM Classifier ────────────────────────────────────────────────
    if run_all or args.hmm_only:
        print(f"\n{'=' * 70}")
        print("=== HMM Classifier ===")
        print(f"{'=' * 70}")
        try:
            hmm = HMMClassifier(engine, covariance_type=args.covariance_type)
            df_hmm = hmm.fit_and_predict(force_refit=args.force_refit or args.full)
            logger.info("HMM: %d rows computed", len(df_hmm))
            print(f"[INFO] HMM: {len(df_hmm)} rows computed")

            if not args.dry_run and not df_hmm.empty:
                count = hmm.upsert_results(df_hmm)
                logger.info("HMM: upserted %d rows", count)
                print(f"[OK] HMM: upserted {count} rows")
            elif args.dry_run and not df_hmm.empty:
                print(f"[DRY RUN] HMM: would upsert {len(df_hmm)} rows")

            # Optional: run rule-based comparison (warn if not available)
            try:
                comparison = hmm.compare_with_rule_based()
                kappa = comparison["kappa"]
                n_dates = comparison["n_aligned_dates"]
                logger.info("HMM vs rule-based: kappa=%.3f, n_dates=%d", kappa, n_dates)
                print(
                    f"[INFO] HMM vs rule-based: kappa={kappa:.3f}, "
                    f"n_aligned_dates={n_dates}"
                )
            except Exception as cmp_exc:  # noqa: BLE001
                logger.warning(
                    "HMM comparison skipped (rule-based data may not exist): %s",
                    cmp_exc,
                )
                print(f"[WARN] HMM vs rule-based comparison skipped: {cmp_exc}")

            results["hmm"] = "success"

        except Exception as exc:  # noqa: BLE001
            logger.error("HMM classifier failed: %s", exc)
            print(f"[ERROR] HMM classifier failed: {exc}")
            results["hmm"] = f"failed: {exc}"

    # ── 2. Lead-Lag Analysis ─────────────────────────────────────────────
    if run_all or args.lead_lag_only:
        print(f"\n{'=' * 70}")
        print("=== Lead-Lag Analysis ===")
        print(f"{'=' * 70}")
        try:
            lla = LeadLagAnalyzer(engine)
            df_ll = lla.scan_all()
            logger.info("Lead-lag: %d feature-asset pairs scanned", len(df_ll))
            print(f"[INFO] Lead-lag: {len(df_ll)} feature-asset pairs scanned")

            sig_count = int(df_ll["is_significant"].sum()) if not df_ll.empty else 0
            logger.info("Lead-lag: %d significant pairs", sig_count)
            print(f"[INFO] Lead-lag: {sig_count} significant pairs")

            if not args.dry_run and not df_ll.empty:
                count = lla.upsert_results(df_ll)
                logger.info("Lead-lag: upserted %d rows", count)
                print(f"[OK] Lead-lag: upserted {count} rows")
            elif args.dry_run and not df_ll.empty:
                print(f"[DRY RUN] Lead-lag: would upsert {len(df_ll)} rows")

            results["lead_lag"] = "success"

        except Exception as exc:  # noqa: BLE001
            logger.error("Lead-lag analysis failed: %s", exc)
            print(f"[ERROR] Lead-lag analysis failed: {exc}")
            results["lead_lag"] = f"failed: {exc}"

    # ── 3. Transition Probabilities ───────────────────────────────────────
    if run_all or args.transition_only:
        print(f"\n{'=' * 70}")
        print("=== Transition Probabilities ===")
        print(f"{'=' * 70}")
        try:
            tpm = TransitionProbMatrix(engine)
            df_tp = tpm.compute_all()
            logger.info("Transition probs: %d rows computed", len(df_tp))
            print(f"[INFO] Transition probs: {len(df_tp)} rows computed")

            if not args.dry_run and not df_tp.empty:
                count = tpm.upsert_results(df_tp)
                logger.info("Transition probs: upserted %d rows", count)
                print(f"[OK] Transition probs: upserted {count} rows")
            elif args.dry_run and not df_tp.empty:
                print(f"[DRY RUN] Transition probs: would upsert {len(df_tp)} rows")
            elif df_tp.empty:
                print(
                    "[WARN] Transition probs: no rows computed. "
                    "Ensure macro_regimes and/or hmm_regimes have data."
                )

            results["transition_probs"] = "success"

        except Exception as exc:  # noqa: BLE001
            logger.error("Transition probabilities failed: %s", exc)
            print(f"[ERROR] Transition probabilities failed: {exc}")
            results["transition_probs"] = f"failed: {exc}"

    # ── Summary ───────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - t0
    print(f"\n{'=' * 70}")
    print("MACRO ANALYTICS SUMMARY")
    print(f"{'=' * 70}")
    logger.info("Macro analytics complete: %s", results)

    failures = [k for k, v in results.items() if "failed" in str(v)]
    successes = [k for k, v in results.items() if v == "success"]

    for tool in successes:
        print(f"  [OK]     {tool}")
    for tool in failures:
        print(f"  [FAILED] {tool}: {results[tool]}")

    print(f"\n[DONE] Elapsed: {elapsed:.1f}s")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
