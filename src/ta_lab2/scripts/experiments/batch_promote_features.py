"""Batch promote features from promotion_decisions.csv.

Reads the CSV, filters for action_taken='promote_recommended',
and calls FeaturePromoter.promote_feature() for each feature.

Usage:
    python -m ta_lab2.scripts.experiments.batch_promote_features
    python -m ta_lab2.scripts.experiments.batch_promote_features --dry-run
    python -m ta_lab2.scripts.experiments.batch_promote_features --csv-path path/to/decisions.csv
"""

import argparse

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from ta_lab2.experiments import FeaturePromoter, PromotionRejectedError
from ta_lab2.scripts.refresh_utils import resolve_db_url


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch promote features from decisions CSV"
    )
    parser.add_argument(
        "--csv-path",
        default="reports/evaluation/promotion_decisions.csv",
        help="Path to promotion_decisions.csv (default: reports/evaluation/promotion_decisions.csv)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check BH gate without promoting — reads IC data and validates gate, no DB writes",
    )
    parser.add_argument(
        "--source",
        choices=["auto", "feature_experiments", "ic_results"],
        default="auto",
        help=(
            "IC data source table. "
            "'auto' (default): try cmc_feature_experiments first, fall back to cmc_ic_results. "
            "'feature_experiments': query cmc_feature_experiments only. "
            "'ic_results': query cmc_ic_results only (for bar-level features from run_ic_sweep.py)."
        ),
    )
    args = parser.parse_args()

    df = pd.read_csv(args.csv_path)
    to_promote = df[df["action_taken"] == "promote_recommended"][
        "feature_name"
    ].tolist()
    print(f"Found {len(to_promote)} features to promote from {args.csv_path}")

    engine = create_engine(resolve_db_url(), poolclass=NullPool)
    promoter = FeaturePromoter(engine)
    promoted, rejected, errors = [], [], []

    for i, name in enumerate(to_promote, 1):
        try:
            if args.dry_run:
                ic_df = promoter._load_experiment_results(name, source=args.source)
                if ic_df.empty:
                    print(
                        f"[{i}/{len(to_promote)}] DRY-RUN {name}: "
                        f"NO DATA (no experiment results in source='{args.source}')"
                    )
                    continue
                passed, bh_df, reason = promoter.check_bh_gate(ic_df)
                status = "PASS" if passed else "FAIL"
                print(
                    f"[{i}/{len(to_promote)}] DRY-RUN {name}: BH gate {status} — {reason}"
                )
            else:
                promoter.promote_feature(name, confirm=False, source=args.source)
                promoted.append(name)
                print(f"[{i}/{len(to_promote)}] PROMOTED {name}")
        except PromotionRejectedError as exc:
            rejected.append((name, exc.reason))
            print(f"[{i}/{len(to_promote)}] REJECTED {name}: {exc.reason}")
        except Exception as exc:
            errors.append((name, str(exc)))
            print(f"[{i}/{len(to_promote)}] ERROR {name}: {exc}")

    if not args.dry_run:
        print(
            f"\nSummary: {len(promoted)} promoted, {len(rejected)} rejected, {len(errors)} errors"
        )
        if rejected:
            print("\nRejected features:")
            for name, reason in rejected:
                print(f"  {name}: {reason}")
        if errors:
            print("\nErrored features:")
            for name, msg in errors:
                print(f"  {name}: {msg}")


if __name__ == "__main__":
    main()
