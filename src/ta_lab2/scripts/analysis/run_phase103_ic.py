# -*- coding: utf-8 -*-
"""
Phase 103 IC sweep runner: compute extended TA indicators, run IC sweep,
apply FDR correction, and promote/reject features in dim_feature_registry.

End-to-end pipeline:
  Step 1: Refresh TA features (optional; skip with --skip-refresh)
  Step 2: Run IC sweep for the ~35 Phase 103 feature columns
  Step 3: Apply Benjamini-Hochberg FDR control at alpha (default 5%)
  Step 4: Promote FDR passers to dim_feature_registry (lifecycle='promoted')
  Step 5: Log FDR rejects to dim_feature_registry (lifecycle='deprecated')
  Step 6: Print summary and validate coverage

Usage::

    # Full pipeline (refresh + sweep + FDR + promotion)
    python -m ta_lab2.scripts.analysis.run_phase103_ic --all

    # Skip feature refresh (if already computed)
    python -m ta_lab2.scripts.analysis.run_phase103_ic --all --skip-refresh

    # Dry run: sweep + FDR but no dim_feature_registry writes
    python -m ta_lab2.scripts.analysis.run_phase103_ic --all --dry-run

    # Validate coverage only (after sweep has run)
    python -m ta_lab2.scripts.analysis.run_phase103_ic --validate-only

    # Custom FDR alpha
    python -m ta_lab2.scripts.analysis.run_phase103_ic --all --fdr-alpha 0.10
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.multiple_testing import fdr_control
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 103 feature columns: the ~35 output columns from the 20 new indicators
# ---------------------------------------------------------------------------

# Indicator names (for trial_registry lookup)
_PHASE103_INDICATOR_NAMES: list[str] = [
    "ichimoku",
    "willr",
    "kc",
    "cci",
    "elder_ray",
    "fi",
    "vwap",
    "cmf",
    "chaikin_osc",
    "hurst",
    "vidya",
    "frama",
    "aroon",
    "trix",
    "uo",
    "vi",
    "emv",
    "mass_index",
    "kst",
    "coppock",
]

# Feature column names (output columns in the ta/features table)
_PHASE103_FEATURE_COLS: list[str] = [
    "ichimoku_tenkan",
    "ichimoku_kijun",
    "ichimoku_span_a",
    "ichimoku_span_b",
    "ichimoku_chikou",
    "willr_14",
    "kc_mid_20",
    "kc_upper_20",
    "kc_lower_20",
    "kc_width_20",
    "cci_20",
    "elder_bull_13",
    "elder_bear_13",
    "fi_1",
    "fi_13",
    "vwap_14",
    "vwap_dev_14",
    "cmf_20",
    "chaikin_osc",
    "hurst_100",
    "vidya_9",
    "frama_16",
    "aroon_up_25",
    "aroon_dn_25",
    "aroon_osc_25",
    "trix_15",
    "trix_signal_9",
    "uo_7_14_28",
    "vi_plus_14",
    "vi_minus_14",
    "emv_1",
    "emv_14",
    "mass_idx_25",
    "kst",
    "kst_signal",
    "coppock",
]


# ---------------------------------------------------------------------------
# Step 1: Feature refresh
# ---------------------------------------------------------------------------


def refresh_features(verbose: bool = False) -> None:
    """Shell out to run_all_feature_refreshes to compute TA features.

    Invokes the existing refresh pipeline so all 20 new indicator columns
    get written to the ta (features) table for all assets and timeframes.
    """
    logger.info("Step 1: Refreshing TA features via run_all_feature_refreshes...")
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.features.run_all_feature_refreshes",
        "--ta",
        "--all-tfs",
    ]
    if verbose:
        cmd.append("--verbose")

    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        logger.warning(
            "Feature refresh exited with code %d — sweep will proceed with existing data",
            result.returncode,
        )
    else:
        logger.info("Feature refresh completed successfully")


# ---------------------------------------------------------------------------
# Step 2: IC sweep for Phase 103 columns
# ---------------------------------------------------------------------------


def run_ic_sweep_for_phase103(
    db_url: str,
    asset_ids: Optional[list[int]] = None,
    tf_filter: Optional[str] = None,
    min_bars: int = 500,
    workers: int = 1,
    verbose: bool = False,
) -> int:
    """Run the IC sweep restricted to Phase 103 feature columns.

    Invokes the existing _run_features_sweep machinery from run_ic_sweep,
    passing the ~35 Phase 103 feature column names as the feature_cols filter.

    Returns total IC rows written.
    """
    logger.info(
        "Step 2: Running IC sweep for %d Phase 103 feature columns...",
        len(_PHASE103_FEATURE_COLS),
    )

    from ta_lab2.analysis.ic import (
        batch_compute_ic,
        save_ic_results,
    )
    from ta_lab2.analysis.multiple_testing import log_trials_to_registry
    from ta_lab2.scripts.analysis.run_ic_sweep import (
        _discover_features_pairs,
        _rows_from_ic_df,
    )
    from ta_lab2.scripts.sync_utils import get_columns
    from ta_lab2.time.dim_timeframe import DimTimeframe

    engine = create_engine(db_url, poolclass=NullPool)

    try:
        dim = DimTimeframe.from_db(db_url)
        logger.info("DimTimeframe loaded: %d timeframes", len(list(dim.list_tfs())))
    except Exception as exc:
        logger.warning(
            "Failed to load DimTimeframe (%s) — tf_days_nominal will default to 1", exc
        )

        class _FallbackDim:
            def tf_days(self, tf: str) -> int:
                return 1

        dim = _FallbackDim()

    # Discover qualifying pairs
    all_pairs = _discover_features_pairs(engine, min_bars)
    if asset_ids:
        asset_ids_set = set(asset_ids)
        pairs = [
            (aid, tf, n)
            for aid, tf, n in all_pairs
            if aid in asset_ids_set and (tf_filter is None or tf == tf_filter)
        ]
    else:
        pairs = [
            (aid, tf, n)
            for aid, tf, n in all_pairs
            if tf_filter is None or tf == tf_filter
        ]

    if not pairs:
        logger.warning("No qualifying (asset, tf) pairs found for IC sweep")
        return 0

    logger.info("IC sweep: %d (asset, tf) pairs to process", len(pairs))

    # Determine which Phase 103 columns actually exist in the features table
    try:
        all_cols = get_columns(engine, "public.features")
    except Exception:
        try:
            all_cols = get_columns(engine, "public.ta")
        except Exception:
            all_cols = []

    existing_phase103_cols = [c for c in _PHASE103_FEATURE_COLS if c in all_cols]
    missing_cols = [c for c in _PHASE103_FEATURE_COLS if c not in all_cols]

    if missing_cols:
        logger.warning(
            "Phase 103 columns not found in features table (migration may be pending): %s",
            missing_cols,
        )

    if not existing_phase103_cols:
        logger.error(
            "None of the Phase 103 feature columns exist in features table — "
            "did you run the 103-02 Alembic migration?"
        )
        return 0

    logger.info(
        "Found %d/%d Phase 103 columns in features table",
        len(existing_phase103_cols),
        len(_PHASE103_FEATURE_COLS),
    )

    # Standard IC sweep parameters (matching run_ic_sweep defaults)
    horizons = [1, 2, 3, 5, 10, 20, 60]
    return_types = ["arith", "log"]
    rolling_window = 63

    total_written = 0
    skipped = 0

    for idx, (asset_id, tf, n_rows) in enumerate(pairs):
        pair_start = time.time()
        logger.info(
            "[%d/%d] asset_id=%d tf=%s n_rows=%d",
            idx + 1,
            len(pairs),
            asset_id,
            tf,
            n_rows,
        )

        try:
            tf_days_nominal: int = dim.tf_days(tf)
        except (KeyError, AttributeError):
            tf_days_nominal = 1

        try:
            with engine.begin() as conn:
                # Load features for this asset/tf (Phase 103 columns only)
                sql = text(
                    "SELECT ts, "
                    + ", ".join(f'"{c}"' for c in existing_phase103_cols)
                    + ", close "
                    "FROM public.features "
                    "WHERE id = :asset_id AND tf = :tf AND venue_id = 1 "
                    "ORDER BY ts"
                )
                df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})

                if df.empty:
                    logger.debug(
                        "No feature data for asset_id=%d tf=%s — skipping", asset_id, tf
                    )
                    skipped += 1
                    continue

                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df = df.set_index("ts")

                close_series = df["close"].dropna()
                if close_series.empty:
                    skipped += 1
                    continue

                features_df = df[existing_phase103_cols]

                # Only include columns with at least some non-null values
                valid_cols = [
                    c for c in existing_phase103_cols if features_df[c].notna().any()
                ]
                if not valid_cols:
                    logger.debug(
                        "All Phase 103 columns null for asset_id=%d tf=%s — skipping",
                        asset_id,
                        tf,
                    )
                    skipped += 1
                    continue

                train_start = features_df.index.min()
                train_end = features_df.index.max()

                ic_df = batch_compute_ic(
                    features_df[valid_cols],
                    close_series,
                    train_start,
                    train_end,
                    feature_cols=valid_cols,
                    horizons=horizons,
                    return_types=return_types,
                    rolling_window=rolling_window,
                    tf_days_nominal=tf_days_nominal,
                )

                if ic_df.empty:
                    skipped += 1
                    continue

                # Add regime sentinel (full-sample only)
                if "regime_col" not in ic_df.columns:
                    ic_df["regime_col"] = "all"
                if "regime_label" not in ic_df.columns:
                    ic_df["regime_label"] = "all"

                all_ic_rows = _rows_from_ic_df(
                    ic_df, asset_id, tf, train_start, train_end, tf_days_nominal
                )

                n_written = 0
                if all_ic_rows:
                    n_written = save_ic_results(conn, all_ic_rows, overwrite=True)
                    total_written += n_written
                    try:
                        n_logged = log_trials_to_registry(
                            conn, all_ic_rows, source_table="ic_results"
                        )
                        logger.debug(
                            "Logged %d trials to trial_registry for asset_id=%d tf=%s",
                            n_logged,
                            asset_id,
                            tf,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to log trials to trial_registry for asset_id=%d tf=%s",
                            asset_id,
                            tf,
                            exc_info=True,
                        )

                elapsed = time.time() - pair_start
                logger.info(
                    "asset_id=%d tf=%s: %d IC rows written in %.1fs",
                    asset_id,
                    tf,
                    n_written,
                    elapsed,
                )

        except Exception as exc:
            logger.error(
                "Failed asset_id=%d tf=%s: %s", asset_id, tf, exc, exc_info=True
            )
            skipped += 1

    engine.dispose()
    logger.info(
        "IC sweep done: %d rows written, %d pairs skipped", total_written, skipped
    )
    return total_written


# ---------------------------------------------------------------------------
# Step 3: Query trial_registry and apply FDR
# ---------------------------------------------------------------------------


def _query_trial_registry_for_phase103(engine) -> pd.DataFrame:
    """Query trial_registry for Phase 103 indicator results.

    Returns a DataFrame with (indicator_name, ic_observed, ic_p_value, n_obs)
    aggregated by indicator_name (using mean |IC| cross-asset, min p-value).

    Uses MIN(ic_p_value) per indicator to surface the most significant result
    for FDR input — this is the most lenient (highest power) approach.
    For FDR purposes we want one p-value per indicator (the best cross-asset).
    """
    col_list = ", ".join(f"'{c}'" for c in _PHASE103_FEATURE_COLS)

    sql = text(
        f"""
        SELECT
            indicator_name,
            AVG(ABS(ic_observed))                           AS mean_abs_ic,
            MIN(ic_p_value)                                 AS min_p_value,
            MAX(ABS(ic_observed))                           AS max_abs_ic,
            (
                SELECT tf
                FROM trial_registry t2
                WHERE t2.indicator_name = t1.indicator_name
                  AND ABS(t2.ic_observed) = MAX(ABS(t1.ic_observed))
                LIMIT 1
            )                                               AS best_tf,
            COUNT(*)                                        AS n_rows,
            AVG(n_obs)                                      AS avg_n_obs
        FROM trial_registry t1
        WHERE indicator_name IN ({col_list})
          AND horizon = 1
          AND return_type = 'arith'
          AND ic_p_value IS NOT NULL
        GROUP BY indicator_name
        ORDER BY mean_abs_ic DESC NULLS LAST
        """
    )

    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn)
        return df
    except Exception as exc:
        logger.warning("trial_registry query failed: %s", exc)
        return pd.DataFrame()


def apply_fdr(
    registry_df: pd.DataFrame,
    alpha: float = 0.05,
) -> tuple[list[str], list[str], pd.DataFrame]:
    """Apply Benjamini-Hochberg FDR correction to Phase 103 IC results.

    Parameters
    ----------
    registry_df:
        DataFrame from _query_trial_registry_for_phase103().
    alpha:
        FDR control level (default 0.05).

    Returns
    -------
    (passers, rejects, enriched_df)
        passers: list of feature column names that pass FDR
        rejects: list of feature column names that fail FDR
        enriched_df: registry_df with 'passes_fdr' and 'fdr_p_adjusted' columns added
    """
    if registry_df.empty:
        logger.warning("No trial_registry rows found for Phase 103 indicators")
        return [], [], registry_df

    p_values = registry_df["min_p_value"].fillna(1.0).tolist()

    fdr_result = fdr_control(p_values, alpha=alpha)
    rejected = fdr_result[
        "rejected"
    ]  # bool array: True = hypothesis rejected (significant)
    p_adjusted = fdr_result["p_adjusted"]

    enriched = registry_df.copy()
    enriched["passes_fdr"] = rejected
    enriched["fdr_p_adjusted"] = p_adjusted

    passers = list(enriched.loc[enriched["passes_fdr"], "indicator_name"])
    rejects = list(enriched.loc[~enriched["passes_fdr"], "indicator_name"])

    logger.info(
        "FDR at alpha=%.2f: %d/%d features pass",
        alpha,
        len(passers),
        len(registry_df),
    )

    return passers, rejects, enriched


# ---------------------------------------------------------------------------
# Step 4+5: Promotion and rejection writes to dim_feature_registry
# ---------------------------------------------------------------------------


def _upsert_promoted(
    conn: Any, feature_name: str, best_ic: float, best_horizon: int, alpha: float
) -> None:
    """Upsert a feature as lifecycle='promoted' in dim_feature_registry."""
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            """
            INSERT INTO public.dim_feature_registry (
                feature_name,
                lifecycle,
                promoted_at,
                promotion_alpha,
                best_ic,
                best_horizon,
                updated_at
            ) VALUES (
                :feature_name,
                'promoted',
                :promoted_at,
                :promotion_alpha,
                :best_ic,
                :best_horizon,
                :updated_at
            )
            ON CONFLICT (feature_name) DO UPDATE SET
                lifecycle        = 'promoted',
                promoted_at      = EXCLUDED.promoted_at,
                promotion_alpha  = EXCLUDED.promotion_alpha,
                best_ic          = EXCLUDED.best_ic,
                best_horizon     = EXCLUDED.best_horizon,
                updated_at       = EXCLUDED.updated_at
            """
        ),
        {
            "feature_name": feature_name,
            "promoted_at": now,
            "promotion_alpha": alpha,
            "best_ic": float(best_ic) if best_ic is not None else None,
            "best_horizon": int(best_horizon) if best_horizon is not None else 1,
            "updated_at": now,
        },
    )


def _upsert_deprecated(conn: Any, feature_name: str) -> None:
    """Upsert a feature as lifecycle='deprecated' in dim_feature_registry."""
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            """
            INSERT INTO public.dim_feature_registry (
                feature_name,
                lifecycle,
                updated_at
            ) VALUES (
                :feature_name,
                'deprecated',
                :updated_at
            )
            ON CONFLICT (feature_name) DO UPDATE SET
                lifecycle  = 'deprecated',
                updated_at = EXCLUDED.updated_at
            """
        ),
        {"feature_name": feature_name, "updated_at": now},
    )


def write_promotion_results(
    engine,
    passers: list[str],
    rejects: list[str],
    enriched_df: pd.DataFrame,
    alpha: float,
    dry_run: bool = False,
) -> None:
    """Write FDR results to dim_feature_registry.

    For passers: upsert lifecycle='promoted' with IC metadata.
    For rejects: upsert lifecycle='deprecated'.

    When dry_run=True, logs what would be written without touching the DB.
    """
    if dry_run:
        logger.info(
            "[dry-run] Would promote %d features, deprecate %d features",
            len(passers),
            len(rejects),
        )
        if passers:
            logger.info("[dry-run] Promotions: %s", passers)
        if rejects:
            logger.info("[dry-run] Deprecations: %s", rejects)
        return

    # Build lookup: feature_name -> row data
    row_lookup: dict[str, Any] = {}
    if not enriched_df.empty:
        for _, row in enriched_df.iterrows():
            row_lookup[row["indicator_name"]] = row

    with engine.begin() as conn:
        # Promote passers
        for feat in passers:
            row = row_lookup.get(feat, {})
            best_ic = float(row.get("max_abs_ic", 0.0)) if row else 0.0
            best_horizon = 1  # horizon=1 is the primary evaluation horizon
            try:
                _upsert_promoted(conn, feat, best_ic, best_horizon, alpha)
                logger.info("Promoted: %s (best_ic=%.4f)", feat, best_ic)
            except Exception as exc:
                logger.error("Failed to promote %s: %s", feat, exc)

        # Log rejects
        for feat in rejects:
            try:
                _upsert_deprecated(conn, feat)
                logger.info("Deprecated: %s", feat)
            except Exception as exc:
                logger.error("Failed to deprecate %s: %s", feat, exc)

    logger.info(
        "dim_feature_registry updated: %d promoted, %d deprecated",
        len(passers),
        len(rejects),
    )


# ---------------------------------------------------------------------------
# Step 6 + Task 2: validate_coverage
# ---------------------------------------------------------------------------


def validate_coverage(engine) -> dict[str, Any]:
    """Validate trial_registry coverage and dim_feature_registry status.

    Checks:
    1. COUNT(DISTINCT indicator_name) in trial_registry for Phase 103 indicators
    2. lifecycle status in dim_feature_registry for all ~35 feature columns

    Prints a summary table and returns a dict with coverage stats.

    This function is the acceptance test for the must_haves:
    - COUNT(DISTINCT indicator_name) >= 20
    - All features have 'promoted' or 'deprecated' lifecycle
    """
    print("\n" + "=" * 70)
    print("PHASE 103 COVERAGE VALIDATION")
    print("=" * 70)

    # --- Trial registry coverage ---
    col_list = ", ".join(f"'{c}'" for c in _PHASE103_FEATURE_COLS)

    try:
        with engine.connect() as conn:
            # Check trial_registry by feature column names (indicator_name = feature col)
            cnt_sql = text(
                f"SELECT COUNT(DISTINCT indicator_name) AS cnt "
                f"FROM trial_registry "
                f"WHERE indicator_name IN ({col_list})"
            )
            cnt_row = conn.execute(cnt_sql).fetchone()
            trial_registry_count = int(cnt_row[0]) if cnt_row else 0

            # Also list which feature cols are present
            present_sql = text(
                f"SELECT DISTINCT indicator_name "
                f"FROM trial_registry "
                f"WHERE indicator_name IN ({col_list}) "
                f"ORDER BY indicator_name"
            )
            present_rows = conn.execute(present_sql).fetchall()
            present_features = {r[0] for r in present_rows}
    except Exception as exc:
        logger.warning("trial_registry query failed: %s", exc)
        trial_registry_count = 0
        present_features = set()

    missing_from_trial = [
        f for f in _PHASE103_FEATURE_COLS if f not in present_features
    ]

    print("\nTrial Registry Coverage:")
    print(
        f"  Distinct feature columns with IC results: {trial_registry_count}/{len(_PHASE103_FEATURE_COLS)}"
    )
    if missing_from_trial:
        print(f"  Missing (not yet swept): {missing_from_trial[:10]}")
        if len(missing_from_trial) > 10:
            print(f"    ... and {len(missing_from_trial) - 10} more")
    else:
        print("  All Phase 103 columns have trial_registry entries")

    # --- dim_feature_registry coverage ---
    try:
        with engine.connect() as conn:
            reg_sql = text(
                f"""
                SELECT feature_name, lifecycle, best_ic, best_horizon
                FROM public.dim_feature_registry
                WHERE feature_name IN ({col_list})
                ORDER BY lifecycle, feature_name
                """
            )
            reg_df = pd.read_sql(reg_sql, conn)
    except Exception as exc:
        logger.warning("dim_feature_registry query failed: %s", exc)
        reg_df = pd.DataFrame()

    print("\ndim_feature_registry Status:")
    if reg_df.empty:
        print("  No Phase 103 features found in dim_feature_registry")
        n_promoted = 0
        n_deprecated = 0
        n_orphans = len(_PHASE103_FEATURE_COLS)
    else:
        n_promoted = int((reg_df["lifecycle"] == "promoted").sum())
        n_deprecated = int((reg_df["lifecycle"] == "deprecated").sum())
        registered = set(reg_df["feature_name"])
        orphans = [f for f in _PHASE103_FEATURE_COLS if f not in registered]
        n_orphans = len(orphans)

        print(f"  Promoted:   {n_promoted}")
        print(f"  Deprecated: {n_deprecated}")
        print(f"  Orphans (not in registry): {n_orphans}")

        if not reg_df.empty:
            print(
                "\n"
                + reg_df[
                    ["feature_name", "lifecycle", "best_ic", "best_horizon"]
                ].to_string(index=False)
            )

        if orphans:
            print(f"\n  Orphan columns (no registry entry yet): {orphans}")

    print("\n" + "=" * 70)

    return {
        "trial_registry_count": trial_registry_count,
        "n_promoted": n_promoted,
        "n_deprecated": n_deprecated,
        "n_orphans": n_orphans,
        "missing_from_trial": missing_from_trial,
        "passes_coverage_check": trial_registry_count >= 20,
        "passes_registry_check": n_orphans == 0 and (n_promoted + n_deprecated) > 0,
    }


# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------


def _print_sweep_summary(
    passers: list[str],
    rejects: list[str],
    enriched_df: pd.DataFrame,
    alpha: float,
) -> None:
    """Print a summary of the FDR sweep results."""
    print("\n" + "=" * 70)
    print(f"PHASE 103 IC SWEEP SUMMARY (FDR alpha={alpha:.2f})")
    print("=" * 70)
    print(f"  Total features tested: {len(enriched_df)}")
    print(f"  FDR passers (promoted): {len(passers)}")
    print(f"  FDR rejects (deprecated): {len(rejects)}")

    if not enriched_df.empty and len(passers) > 0:
        top_passers = enriched_df[enriched_df["passes_fdr"]].nlargest(5, "mean_abs_ic")
        print("\n  Top 5 FDR passers by mean |IC|:")
        for _, row in top_passers.iterrows():
            print(
                f"    {row['indicator_name']:<30} mean_abs_ic={row['mean_abs_ic']:.4f}  "
                f"min_p={row['min_p_value']:.4f}  adj_p={row['fdr_p_adjusted']:.4f}"
            )

    print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Phase 103 IC sweep runner entry point. Returns exit code."""
    parser = argparse.ArgumentParser(
        prog="run_phase103_ic",
        description=(
            "Phase 103 IC sweep runner.\n\n"
            "Refreshes extended TA features, runs IC sweep for ~35 new Phase 103 "
            "feature columns, applies FDR correction at 5%, and promotes/rejects "
            "features in dim_feature_registry."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Scope
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_assets",
        help="Full sweep across all qualifying asset-TF pairs.",
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        type=int,
        metavar="ID",
        dest="asset_ids",
        default=None,
        help="Specific asset IDs to evaluate (e.g. --assets 1 1027).",
    )
    parser.add_argument(
        "--tf",
        type=str,
        metavar="TF",
        default=None,
        dest="tf_filter",
        help="Restrict sweep to this timeframe (e.g. --tf 1D).",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=500,
        metavar="N",
        dest="min_bars",
        help="Minimum bars for qualifying pairs (default: 500).",
    )

    # Behaviour
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        dest="skip_refresh",
        help="Skip Step 1 (feature refresh). Use if features already computed.",
    )
    parser.add_argument(
        "--fdr-alpha",
        type=float,
        default=0.05,
        metavar="FLOAT",
        dest="fdr_alpha",
        help="FDR Benjamini-Hochberg alpha threshold (default: 0.05).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Run refresh + sweep + FDR but do NOT write to dim_feature_registry. "
            "Useful for previewing outcomes."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        dest="validate_only",
        help=(
            "Only run validate_coverage() — skip refresh, sweep, and FDR. "
            "Useful after the sweep has already completed."
        ),
    )

    # Parallelism
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        metavar="N",
        dest="workers",
        help="Number of parallel IC sweep workers (default: 1).",
    )

    # DB
    parser.add_argument(
        "--db-url",
        metavar="URL",
        default=None,
        dest="db_url",
        help="SQLAlchemy DB URL (overrides db_config.env / environment).",
    )

    # Verbosity
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Require --all or --assets unless --validate-only
    if not args.validate_only and not args.all_assets and not args.asset_ids:
        parser.error("Provide --all, --assets <IDs>, or --validate-only")

    sweep_start = time.time()
    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url, poolclass=NullPool)

    # --- Validate-only mode ---
    if args.validate_only:
        result = validate_coverage(engine)
        engine.dispose()
        return 0 if result["passes_coverage_check"] else 1

    # --- Step 1: Refresh features ---
    if not args.skip_refresh:
        refresh_features(verbose=args.verbose)
    else:
        logger.info("Step 1: Skipping feature refresh (--skip-refresh)")

    # --- Step 2: IC sweep ---
    n_ic_rows = run_ic_sweep_for_phase103(
        db_url=db_url,
        asset_ids=args.asset_ids,
        tf_filter=args.tf_filter,
        min_bars=args.min_bars,
        workers=args.workers,
        verbose=args.verbose,
    )
    logger.info("IC sweep wrote %d rows to ic_results / trial_registry", n_ic_rows)

    # --- Step 3: Apply FDR ---
    logger.info("Step 3: Applying FDR correction at alpha=%.2f...", args.fdr_alpha)
    registry_df = _query_trial_registry_for_phase103(engine)

    if registry_df.empty:
        logger.warning(
            "No trial_registry rows found for Phase 103 features — "
            "FDR and promotion skipped. Run IC sweep first."
        )
        engine.dispose()
        return 1

    passers, rejects, enriched_df = apply_fdr(registry_df, alpha=args.fdr_alpha)

    # --- Steps 4+5: Promote / deprecate ---
    logger.info(
        "Steps 4+5: Writing promotion results to dim_feature_registry (dry_run=%s)...",
        args.dry_run,
    )
    write_promotion_results(
        engine,
        passers,
        rejects,
        enriched_df,
        alpha=args.fdr_alpha,
        dry_run=args.dry_run,
    )

    # --- Step 6: Summary ---
    _print_sweep_summary(passers, rejects, enriched_df, alpha=args.fdr_alpha)

    # --- Validate coverage ---
    validate_coverage(engine)

    elapsed = time.time() - sweep_start
    logger.info("Phase 103 IC sweep pipeline complete in %.1fs", elapsed)

    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
