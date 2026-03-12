"""CLI: promote an experimental feature to promoted lifecycle.

Applies the Benjamini-Hochberg correction gate against IC experiment results,
then writes the promotion record to dim_feature_registry and generates an
Alembic migration stub for adding the feature column to features.

Usage::

    # Dry-run (show BH gate results without promoting)
    python -m ta_lab2.scripts.experiments.promote_feature --feature vol_ratio_30_7 --dry-run

    # Interactive promotion (will prompt for confirmation)
    python -m ta_lab2.scripts.experiments.promote_feature --feature vol_ratio_30_7

    # Non-interactive promotion (skip confirmation)
    python -m ta_lab2.scripts.experiments.promote_feature --feature vol_ratio_30_7 --yes

    # With custom BH threshold and registry
    python -m ta_lab2.scripts.experiments.promote_feature \\
        --feature vol_ratio_30_7 \\
        --alpha 0.01 \\
        --min-pass-rate 0.5 \\
        --registry configs/experiments/features.yaml \\
        --yes
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.experiments import FeaturePromoter, PromotionRejectedError
from ta_lab2.scripts.refresh_utils import resolve_db_url


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="promote_feature",
        description=(
            "Promote an experimental feature to 'promoted' lifecycle via "
            "Benjamini-Hochberg significance gate."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--feature",
        required=True,
        metavar="NAME",
        help="Feature name to promote (must exist in feature_experiments).",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        metavar="FLOAT",
        help="Benjamini-Hochberg significance threshold (default: 0.05).",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.0,
        metavar="FLOAT",
        dest="min_pass_rate",
        help=(
            "Minimum fraction of test combos that must pass BH. "
            "Default 0.0 = at least one combo must pass."
        ),
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt (non-interactive mode).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show BH gate results without promoting. Nothing is written to DB.",
    )
    parser.add_argument(
        "--registry",
        metavar="PATH",
        default="configs/experiments/features.yaml",
        help=(
            "Path to features.yaml for description/metadata enrichment. "
            "Default: configs/experiments/features.yaml. "
            "If file doesn't exist, promotion proceeds without metadata."
        ),
    )
    parser.add_argument(
        "--db-url",
        metavar="URL",
        default=None,
        help="SQLAlchemy DB URL (overrides db_config.env / environment).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url, poolclass=NullPool)

    # Optionally load FeatureRegistry for metadata enrichment
    registry = None
    try:
        import os

        from ta_lab2.experiments import FeatureRegistry

        if os.path.exists(args.registry):
            registry = FeatureRegistry(args.registry)
            registry.load()
        else:
            print(
                f"[warn] Registry file not found: {args.registry}. "
                "Proceeding without metadata enrichment."
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] Could not load registry ({exc}). Proceeding without metadata.")

    promoter = FeaturePromoter(engine, registry)

    # --dry-run: show BH gate results and exit without writing
    if args.dry_run:
        return _handle_dry_run(promoter, args)

    # Full promotion
    try:
        stub_path = promoter.promote_feature(
            args.feature,
            alpha=args.alpha,
            min_pass_rate=args.min_pass_rate,
            confirm=not args.yes,
        )
        if stub_path:
            print(f"\nPromotion complete. Migration stub: {stub_path}")
            return 0
        else:
            # User declined confirmation
            print("Promotion cancelled by user.")
            return 0
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    except PromotionRejectedError as exc:
        print(f"\n[REJECTED] Feature '{args.feature}' failed BH gate:", file=sys.stderr)
        print(f"  {exc.reason}", file=sys.stderr)
        if not exc.bh_results.empty:
            print("\nBH results preview:", file=sys.stderr)
            cols = [
                c
                for c in ["horizon", "ic", "ic_p_value", "ic_p_value_bh"]
                if c in exc.bh_results.columns
            ]
            print(exc.bh_results[cols].to_string(index=False), file=sys.stderr)
        return 2
    finally:
        engine.dispose()


def _handle_dry_run(promoter: FeaturePromoter, args: argparse.Namespace) -> int:
    """Load experiment results, apply BH gate, print results, exit without writing."""
    print(f"[dry-run] BH gate check for feature '{args.feature}'")
    print(f"  alpha={args.alpha}, min_pass_rate={args.min_pass_rate}")
    print()

    try:
        # Load results directly via the promoter's internal helper
        ic_df = promoter._load_experiment_results(args.feature)
        if ic_df.empty:
            print(
                f"[error] No experiment results found for '{args.feature}'.",
                file=sys.stderr,
            )
            return 1

        passed, bh_df, reason = promoter.check_bh_gate(
            ic_df, alpha=args.alpha, min_pass_rate=args.min_pass_rate
        )

        gate_status = "PASSED" if passed else "REJECTED"
        print(f"Gate: {gate_status}")
        print(f"  {reason}")
        print()

        # Show BH-enriched results
        cols = [
            c
            for c in ["horizon", "tf", "ic", "ic_p_value", "ic_p_value_bh"]
            if c in bh_df.columns
        ]
        if cols:
            print("BH results:")
            print(bh_df[cols].to_string(index=False))

        return 0 if passed else 2

    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
