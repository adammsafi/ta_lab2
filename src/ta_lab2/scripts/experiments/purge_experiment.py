"""CLI: purge experiment results for a feature from the database.

Removes experiment result rows from cmc_feature_experiments and optionally
updates or deletes the dim_feature_registry entry. By default (without
--force), the registry entry is deprecated rather than deleted, preserving
the audit trail.

Usage::

    # Dry-run (show what would be deleted without deleting)
    python -m ta_lab2.scripts.experiments.purge_experiment --feature vol_ratio_30_7 --dry-run

    # Purge results, deprecate registry entry (safe default)
    python -m ta_lab2.scripts.experiments.purge_experiment --feature vol_ratio_30_7 --yes

    # Purge results AND delete registry entry (hard delete)
    python -m ta_lab2.scripts.experiments.purge_experiment --feature vol_ratio_30_7 --force --yes
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="purge_experiment",
        description=(
            "Purge experiment results for a feature from cmc_feature_experiments. "
            "By default, preserves the dim_feature_registry entry by deprecating it."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--feature",
        required=True,
        metavar="NAME",
        help="Feature name to purge from cmc_feature_experiments.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Also DELETE from dim_feature_registry (hard delete). "
            "Default (without --force): set lifecycle='deprecated' instead."
        ),
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Show what would be deleted without actually deleting.",
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

    try:
        return _run(engine, args)
    finally:
        engine.dispose()


def _run(engine, args: argparse.Namespace) -> int:
    feature_name = args.feature

    with engine.connect() as conn:
        # Count rows in cmc_feature_experiments
        row_count_result = conn.execute(
            text(
                "SELECT COUNT(*) FROM public.cmc_feature_experiments "
                "WHERE feature_name = :name"
            ),
            {"name": feature_name},
        )
        n_rows = row_count_result.scalar() or 0

        # Check dim_feature_registry entry
        reg_result = conn.execute(
            text(
                "SELECT lifecycle FROM public.dim_feature_registry "
                "WHERE feature_name = :name"
            ),
            {"name": feature_name},
        )
        reg_row = reg_result.fetchone()
        registry_lifecycle = reg_row[0] if reg_row else None

    # Print plan
    print(f"Feature: '{feature_name}'")
    print(f"  cmc_feature_experiments rows to delete: {n_rows}")

    if registry_lifecycle is not None:
        if args.force:
            print(
                f"  dim_feature_registry: DELETE (current lifecycle='{registry_lifecycle}')"
            )
        else:
            print(
                f"  dim_feature_registry: DEPRECATE "
                f"(lifecycle '{registry_lifecycle}' -> 'deprecated')"
            )
    else:
        print("  dim_feature_registry: no entry found (nothing to update)")

    if args.dry_run:
        print("\n[dry-run] No changes made.")
        return 0

    if n_rows == 0 and registry_lifecycle is None:
        print("\nNothing to purge.")
        return 0

    # Confirmation prompt
    if not args.yes:
        answer = (
            input(f"\nPurge experiment results for '{feature_name}'? [y/N]: ")
            .strip()
            .lower()
        )
        if answer not in ("y", "yes"):
            print("Purge cancelled.")
            return 0

    # Execute purge
    with engine.begin() as conn:
        # Delete experiment rows
        del_result = conn.execute(
            text(
                "DELETE FROM public.cmc_feature_experiments WHERE feature_name = :name"
            ),
            {"name": feature_name},
        )
        deleted_rows = del_result.rowcount

        # Handle registry entry
        registry_action = "no entry"
        if registry_lifecycle is not None:
            if args.force:
                conn.execute(
                    text(
                        "DELETE FROM public.dim_feature_registry "
                        "WHERE feature_name = :name"
                    ),
                    {"name": feature_name},
                )
                registry_action = "deleted"
            else:
                conn.execute(
                    text(
                        """
                        UPDATE public.dim_feature_registry
                        SET lifecycle = 'deprecated',
                            updated_at = NOW()
                        WHERE feature_name = :name
                        """
                    ),
                    {"name": feature_name},
                )
                registry_action = "deprecated"

    # Summary
    print(
        f"\nPurge complete: {deleted_rows} row(s) deleted from cmc_feature_experiments. "
        f"Registry entry {registry_action}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
