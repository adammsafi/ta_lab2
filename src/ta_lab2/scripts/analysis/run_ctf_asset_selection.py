# -*- coding: utf-8 -*-
"""
run_ctf_asset_selection.py -- Per-asset CTF feature selection (Phase 98 Plan 02).

Evaluates CTF features on a per-asset basis and writes asset-specific tier rows
to `dim_feature_selection_asset`. Features passing IC > ic_threshold for a specific
asset get tier='asset_specific'.

Algorithm:
  1. Load global promoted features: query ic_results for cross-asset median IC >
     ic_threshold CTF features (same PERCENTILE_CONT query as refresh_ctf_promoted.py).
  2. For each tier-1 asset (distinct asset_id in ic_results with CTF features):
       a. Query per-asset IC: CTF features where ABS(ic) > ic_threshold for this asset.
       b. Compute total = global_features ∪ asset_specific_additions.
       c. Insert only asset_specific_additions rows (not global features).
  3. Upsert to dim_feature_selection_asset with ON CONFLICT (feature_name, asset_id) DO UPDATE.
  4. Log summary per asset.

Output:
  dim_feature_selection_asset rows with tier='asset_specific'

Critical constraints:
  - DO NOT touch dim_feature_selection (the global table -- save_to_db TRUNCATEs it).
  - DO NOT call save_to_db() from feature_selection.py.
  - Superset relationship: effective features for any asset =
      global tier (dim_feature_selection) UNION asset-specific (dim_feature_selection_asset).

Usage:
    python -m ta_lab2.scripts.analysis.run_ctf_asset_selection --dry-run
    python -m ta_lab2.scripts.analysis.run_ctf_asset_selection
    python -m ta_lab2.scripts.analysis.run_ctf_asset_selection --asset-id 1
    python -m ta_lab2.scripts.analysis.run_ctf_asset_selection --ic-threshold 0.03
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_DEFAULT_IC_THRESHOLD = 0.02
_DEFAULT_VENUE_ID = 1

# CTF composite suffixes (must match refresh_ctf_promoted.py)
_CTF_SUFFIXES = (
    "_slope",
    "_divergence",
    "_agreement",
    "_crossover",
    "_ref_value",
    "_base_value",
)

# SQL to discover globally promoted CTF features (cross-asset median IC > threshold).
# Same query as refresh_ctf_promoted.py _IC_DISCOVERY_SQL.
_GLOBAL_PROMOTION_SQL = """
    SELECT
        feature,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) AS median_abs_ic,
        COUNT(DISTINCT asset_id) AS n_assets
    FROM public.ic_results
    WHERE horizon = 1
      AND return_type = 'arith'
      AND regime_col = 'all'
      AND regime_label = 'all'
      AND ic IS NOT NULL
      AND (
           feature LIKE '%_slope'
        OR feature LIKE '%_divergence'
        OR feature LIKE '%_agreement'
        OR feature LIKE '%_crossover'
        OR feature LIKE '%_ref_value'
        OR feature LIKE '%_base_value'
      )
    GROUP BY feature
    HAVING PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > :threshold
    ORDER BY median_abs_ic DESC
"""

# SQL to get distinct asset IDs that have CTF features in ic_results.
_DISTINCT_ASSETS_SQL = """
    SELECT DISTINCT asset_id
    FROM public.ic_results
    WHERE horizon = 1
      AND return_type = 'arith'
      AND regime_col = 'all'
      AND regime_label = 'all'
      AND ic IS NOT NULL
      AND (
           feature LIKE '%_slope'
        OR feature LIKE '%_divergence'
        OR feature LIKE '%_agreement'
        OR feature LIKE '%_crossover'
        OR feature LIKE '%_ref_value'
        OR feature LIKE '%_base_value'
      )
    ORDER BY asset_id
"""

# SQL to get per-asset IC for a single asset.
_PER_ASSET_IC_SQL = """
    SELECT
        feature,
        ABS(ic) AS abs_ic,
        ic AS raw_ic
    FROM public.ic_results
    WHERE asset_id = :asset_id
      AND horizon = 1
      AND return_type = 'arith'
      AND regime_col = 'all'
      AND regime_label = 'all'
      AND ic IS NOT NULL
      AND (
           feature LIKE '%_slope'
        OR feature LIKE '%_divergence'
        OR feature LIKE '%_agreement'
        OR feature LIKE '%_crossover'
        OR feature LIKE '%_ref_value'
        OR feature LIKE '%_base_value'
      )
    ORDER BY abs_ic DESC
"""

# Upsert SQL for dim_feature_selection_asset.
_UPSERT_SQL = """
    INSERT INTO public.dim_feature_selection_asset
        (feature_name, asset_id, tier, ic_ir_mean, pass_rate, stationarity,
         selected_at, yaml_version, rationale)
    VALUES
        (:feature_name, :asset_id, :tier, :ic_ir_mean, :pass_rate, :stationarity,
         :selected_at, :yaml_version, :rationale)
    ON CONFLICT (feature_name, asset_id) DO UPDATE SET
        tier        = EXCLUDED.tier,
        ic_ir_mean  = EXCLUDED.ic_ir_mean,
        selected_at = EXCLUDED.selected_at,
        rationale   = EXCLUDED.rationale
"""


# =============================================================================
# Pre-flight check
# =============================================================================


def _preflight_table_check(engine) -> None:
    """Verify dim_feature_selection_asset table exists.

    Raises RuntimeError if missing, instructing user to run Alembic migration.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = 'dim_feature_selection_asset'
                """
            )
        )
        count = result.scalar() or 0

    if count == 0:
        raise RuntimeError(
            "dim_feature_selection_asset table does not exist. "
            "Run Alembic migration first:\n"
            "  python -m alembic upgrade head\n"
            "(Migration r2s3t4u5v6w7 creates this table)"
        )

    logger.info("Pre-flight check passed: dim_feature_selection_asset table exists")


# =============================================================================
# Feature loaders
# =============================================================================


def _load_global_features(engine, ic_threshold: float) -> set[str]:
    """Load globally promoted CTF features (cross-asset median IC > threshold).

    Returns set of feature names passing the threshold.
    """
    with engine.connect() as conn:
        df = pd.read_sql(
            text(_GLOBAL_PROMOTION_SQL),
            conn,
            params={"threshold": ic_threshold},
        )

    if df.empty:
        logger.warning(
            "_load_global_features: no CTF features pass IC > %.4f threshold. "
            "Run run_ctf_ic_sweep first.",
            ic_threshold,
        )
        return set()

    global_set = set(df["feature"].tolist())
    logger.info(
        "_load_global_features: %d features pass cross-asset median IC > %.4f",
        len(global_set),
        ic_threshold,
    )
    return global_set


def _load_asset_ids(engine, asset_id_filter: int | None) -> list[int]:
    """Load all distinct asset IDs that have CTF features in ic_results.

    If asset_id_filter is set, returns a single-element list.
    """
    if asset_id_filter is not None:
        return [asset_id_filter]

    with engine.connect() as conn:
        result = conn.execute(text(_DISTINCT_ASSETS_SQL))
        asset_ids = [row[0] for row in result]

    logger.info(
        "_load_asset_ids: %d assets have CTF features in ic_results",
        len(asset_ids),
    )
    return asset_ids


def _load_per_asset_ic(engine, asset_id: int, ic_threshold: float) -> dict[str, float]:
    """Load per-asset IC for a single asset. Returns {feature: abs_ic} for passing features.

    Only returns CTF features where ABS(ic) > ic_threshold for this specific asset.
    Note: single-asset IC -- not median across assets.
    """
    with engine.connect() as conn:
        df = pd.read_sql(
            text(_PER_ASSET_IC_SQL),
            conn,
            params={"asset_id": asset_id},
        )

    if df.empty:
        return {}

    # Filter to features passing threshold
    passing = df[df["abs_ic"] > ic_threshold]
    return dict(zip(passing["feature"].tolist(), passing["abs_ic"].tolist()))


# =============================================================================
# Upsert writer
# =============================================================================


def _upsert_asset_rows(engine, rows: list[dict]) -> int:
    """Upsert rows to dim_feature_selection_asset.

    Uses ON CONFLICT (feature_name, asset_id) DO UPDATE.
    Returns count of rows written.
    """
    if not rows:
        return 0

    with engine.begin() as conn:
        conn.execute(text(_UPSERT_SQL), rows)

    return len(rows)


# =============================================================================
# Main per-asset processing
# =============================================================================


def _process_asset(
    engine,
    asset_id: int,
    global_features: set[str],
    ic_threshold: float,
    selected_at: datetime,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Process a single asset: load per-asset IC, compute asset-specific features, upsert.

    Returns (n_global, n_asset_specific, n_total_rows_written).
    """
    # Load per-asset IC for CTF features passing threshold
    per_asset_ic = _load_per_asset_ic(engine, asset_id, ic_threshold)
    per_asset_passing = set(per_asset_ic.keys())

    # Asset-specific additions = features that pass per-asset but NOT in global set
    asset_specific = per_asset_passing - global_features

    n_global = len(global_features)
    n_asset_specific = len(asset_specific)
    n_total = n_global + n_asset_specific

    logger.debug(
        "Asset %d: %d global features, %d per-asset passing, %d asset-specific additions, "
        "%d total effective features",
        asset_id,
        n_global,
        len(per_asset_passing),
        n_asset_specific,
        n_total,
    )

    if dry_run:
        return n_global, n_asset_specific, 0

    if not asset_specific:
        # Nothing to write -- zero asset-specific additions for this asset
        return n_global, 0, 0

    # Build rows for only the asset-specific additions
    rows = []
    for feature in sorted(asset_specific):
        abs_ic = per_asset_ic.get(feature, 0.0)
        rows.append(
            {
                "feature_name": feature,
                "asset_id": asset_id,
                "tier": "asset_specific",
                "ic_ir_mean": float(abs_ic),
                "pass_rate": None,
                "stationarity": None,
                "selected_at": selected_at,
                "yaml_version": None,
                "rationale": (
                    f"Per-asset IC={abs_ic:.4f} > {ic_threshold} for asset {asset_id}; "
                    "not in global cross-asset promoted tier"
                ),
            }
        )

    n_written = _upsert_asset_rows(engine, rows)
    return n_global, n_asset_specific, n_written


# =============================================================================
# Verification query
# =============================================================================


def _query_counts(engine) -> tuple[int, int]:
    """Return (dim_feature_selection_asset count, dim_feature_selection count)."""
    with engine.connect() as conn:
        asset_count = (
            conn.execute(
                text("SELECT COUNT(*) FROM public.dim_feature_selection_asset")
            ).scalar()
            or 0
        )
        global_count = (
            conn.execute(
                text("SELECT COUNT(*) FROM public.dim_feature_selection")
            ).scalar()
            or 0
        )
    return int(asset_count), int(global_count)


# =============================================================================
# Main pipeline
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_ctf_asset_selection",
        description=(
            "Per-asset CTF feature selection (Phase 98 Plan 02).\n\n"
            "Evaluates CTF features per asset using direct IC > threshold comparison "
            "(not cross-asset median). Writes asset-specific winners to "
            "dim_feature_selection_asset with tier='asset_specific'.\n\n"
            "Does NOT touch dim_feature_selection (global table)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Show per-asset selections without writing to DB.",
    )
    parser.add_argument(
        "--asset-id",
        type=int,
        default=None,
        dest="asset_id",
        metavar="N",
        help="Process a single asset (default: all assets with CTF features).",
    )
    parser.add_argument(
        "--ic-threshold",
        type=float,
        default=_DEFAULT_IC_THRESHOLD,
        dest="ic_threshold",
        metavar="FLOAT",
        help=f"IC threshold for per-asset feature selection (default: {_DEFAULT_IC_THRESHOLD}).",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        dest="db_url",
        help="Database URL (overrides db_config.env and TARGET_DB_URL).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    pipeline_start = time.time()

    # -------------------------------------------------------------------------
    # Connect to DB
    # -------------------------------------------------------------------------
    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url, poolclass=NullPool)

    # -------------------------------------------------------------------------
    # Pre-flight check: dim_feature_selection_asset must exist
    # -------------------------------------------------------------------------
    if not args.dry_run:
        _preflight_table_check(engine)

    # -------------------------------------------------------------------------
    # Step 1: Load global promoted features (cross-asset median IC > threshold)
    # -------------------------------------------------------------------------
    logger.info(
        "Step 1: Loading global promoted CTF features (IC threshold=%.4f)...",
        args.ic_threshold,
    )
    global_features = _load_global_features(engine, args.ic_threshold)

    if not global_features:
        logger.warning(
            "No globally promoted CTF features found at IC > %.4f. "
            "Run run_ctf_ic_sweep first.",
            args.ic_threshold,
        )
        print(
            "\nNo CTF features in ic_results. Run:\n"
            "  python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --all"
        )
        return 1

    # -------------------------------------------------------------------------
    # Step 2: Load asset IDs to process
    # -------------------------------------------------------------------------
    asset_ids = _load_asset_ids(engine, args.asset_id)

    if not asset_ids:
        logger.warning("No assets found with CTF features in ic_results.")
        return 0

    # -------------------------------------------------------------------------
    # Step 3: Capture baseline dim_feature_selection count (verify no truncation)
    # -------------------------------------------------------------------------
    _, global_count_before = _query_counts(engine)
    logger.info(
        "dim_feature_selection rows before run: %d (will verify unchanged after)",
        global_count_before,
    )

    # -------------------------------------------------------------------------
    # Step 4: Process each asset
    # -------------------------------------------------------------------------
    selected_at = datetime.now(timezone.utc)

    total_rows_written = 0
    asset_summary: list[dict] = []

    if args.dry_run:
        print("\n--- Per-asset CTF feature selection (dry-run) ---")
        print(f"IC threshold: {args.ic_threshold}")
        print(f"Global promoted features: {len(global_features)}")
        print()

    for i, asset_id in enumerate(asset_ids):
        n_global, n_asset_specific, n_written = _process_asset(
            engine=engine,
            asset_id=asset_id,
            global_features=global_features,
            ic_threshold=args.ic_threshold,
            selected_at=selected_at,
            dry_run=args.dry_run,
        )
        total_rows_written += n_written
        asset_summary.append(
            {
                "asset_id": asset_id,
                "n_global": n_global,
                "n_asset_specific": n_asset_specific,
                "n_total": n_global + n_asset_specific,
                "n_written": n_written,
            }
        )

        if args.dry_run:
            # Show per-asset dry-run breakdown
            if n_asset_specific > 0:
                # Load the per-asset IC to show which features are asset-specific
                per_asset_ic = _load_per_asset_ic(engine, asset_id, args.ic_threshold)
                per_asset_passing = set(per_asset_ic.keys())
                asset_specific_set = per_asset_passing - global_features
                top_features = sorted(
                    asset_specific_set,
                    key=lambda f: per_asset_ic.get(f, 0.0),
                    reverse=True,
                )[:5]
                print(
                    f"  Asset {asset_id:>5}: {n_global:>4} global + "
                    f"{n_asset_specific:>4} asset-specific = {n_global + n_asset_specific:>4} total"
                )
                for feat in top_features:
                    ic_val = per_asset_ic.get(feat, 0.0)
                    print(f"             [asset-specific] {feat:<50} IC={ic_val:.4f}")
            else:
                print(
                    f"  Asset {asset_id:>5}: {n_global:>4} global + "
                    f"{n_asset_specific:>4} asset-specific = {n_global + n_asset_specific:>4} total"
                )
        else:
            logger.info(
                "Asset %d (%d/%d): %d global, %d asset-specific additions, "
                "%d rows written",
                asset_id,
                i + 1,
                len(asset_ids),
                n_global,
                n_asset_specific,
                n_written,
            )

    # -------------------------------------------------------------------------
    # Step 5: Verify dim_feature_selection unchanged
    # -------------------------------------------------------------------------
    asset_count_after, global_count_after = _query_counts(engine)

    if not args.dry_run:
        if global_count_after != global_count_before:
            logger.error(
                "CRITICAL: dim_feature_selection row count changed: %d -> %d. "
                "This should never happen -- investigate immediately.",
                global_count_before,
                global_count_after,
            )
        else:
            logger.info(
                "Verification: dim_feature_selection unchanged (%d rows)",
                global_count_after,
            )

    # -------------------------------------------------------------------------
    # Summary report
    # -------------------------------------------------------------------------
    elapsed = time.time() - pipeline_start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    n_assets_with_specific = sum(1 for s in asset_summary if s["n_asset_specific"] > 0)

    if args.dry_run:
        print()
        print(f"Total assets processed: {len(asset_ids)}")
        print(
            f"Assets with asset-specific additions: {n_assets_with_specific}/{len(asset_ids)}"
        )
        print(f"Global features: {len(global_features)}")
        print("(dry-run: no writes performed)")
        print(f"Duration: {minutes}m{seconds}s")
    else:
        logger.info(
            "run_ctf_asset_selection complete in %dm%ds: "
            "%d assets processed, %d have asset-specific additions, "
            "%d total rows written to dim_feature_selection_asset, "
            "dim_feature_selection unchanged (%d rows)",
            minutes,
            seconds,
            len(asset_ids),
            n_assets_with_specific,
            total_rows_written,
            global_count_after,
        )

        print(
            f"\nAsset-specific CTF feature selection complete.\n"
            f"  Assets processed:            {len(asset_ids)}\n"
            f"  With asset-specific features: {n_assets_with_specific}\n"
            f"  Rows written to dim_feature_selection_asset: {total_rows_written}\n"
            f"  dim_feature_selection (global): {global_count_after} rows (UNCHANGED)\n"
            f"  Duration: {minutes}m{seconds}s"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
