# -*- coding: utf-8 -*-
"""
Phase 104 IC sweep runner: compute derivatives indicators IC, apply FDR
correction, and promote/reject features in dim_feature_registry.

End-to-end pipeline:
  Step 1: Verify Phase 102 artifacts are available
  Step 2: Run IC sweep for the 8 Phase 104 derivatives indicator columns
          across all HL-mapped CMC asset IDs
  Step 3: Apply Benjamini-Hochberg FDR control at alpha (default 5%)
  Step 4: Promote FDR passers to dim_feature_registry (lifecycle='promoted')
  Step 5: Log FDR rejects to dim_feature_registry (lifecycle='deprecated')
  Step 6: Print summary + write CSV to reports/derivatives/

Usage::

    # Full sweep across all HL-mapped assets
    python -m ta_lab2.scripts.analysis.run_phase104_ic

    # Dry run: sweep + FDR but no dim_feature_registry writes
    python -m ta_lab2.scripts.analysis.run_phase104_ic --dry-run

    # Custom FDR alpha
    python -m ta_lab2.scripts.analysis.run_phase104_ic --alpha 0.10

    # Restrict to specific asset IDs
    python -m ta_lab2.scripts.analysis.run_phase104_ic --assets 1 1027

    # Restrict to specific timeframe
    python -m ta_lab2.scripts.analysis.run_phase104_ic --tf 1D
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.multiple_testing import fdr_control
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase 104 derivatives indicator columns (8 total)
# ---------------------------------------------------------------------------

DERIVATIVES_COLS: list[str] = [
    "oi_mom_14",
    "oi_price_div_z",
    "funding_z_14",
    "funding_mom_14",
    "vol_oi_regime",
    "force_idx_deriv_13",
    "oi_conc_ratio",
    "liq_pressure",
]

# Tags written to dim_feature_registry for all Phase 104 derivatives features
_REGISTRY_TAGS: list[str] = [
    "source_type:derivatives",
    "venue:hyperliquid",
    "phase:104",
]

# Reports output directory
_REPORTS_DIR = Path("reports") / "derivatives"


# ---------------------------------------------------------------------------
# Step 1: Pre-requisite verification
# ---------------------------------------------------------------------------


def verify_prerequisites(engine) -> None:
    """Verify Phase 102 artifacts exist before running.

    Checks:
    - multiple_testing module is importable (Phase 102)
    - trial_registry table exists in the DB (Phase 102)

    Raises RuntimeError if either check fails.
    """
    # Check module importability
    try:
        from ta_lab2.analysis.multiple_testing import fdr_control as _fc  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "Phase 102 must be executed before Phase 104. "
            "Run phase 102 plans first. (multiple_testing module missing)"
        ) from exc

    # Check trial_registry table exists
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM trial_registry LIMIT 1"))
    except Exception as exc:
        raise RuntimeError(
            "Phase 102 must be executed before Phase 104. "
            "trial_registry table does not exist. Run phase 102 plans first."
        ) from exc

    logger.info("Pre-requisite check passed: Phase 102 artifacts available")


# ---------------------------------------------------------------------------
# Step 2: Get HL-mapped CMC asset IDs
# ---------------------------------------------------------------------------


def _get_hl_cmc_asset_ids(engine) -> list[int]:
    """Return distinct CMC asset IDs that have HL perp mappings.

    Uses the same JOIN logic as derivatives_input._get_hl_to_cmc_id_map().
    Only perp assets (asset_id < 20000) with confirmed CMC ids are returned.
    """
    sql = text("""
        SELECT DISTINCT dl.id AS cmc_id
        FROM hyperliquid.hl_assets ha
        JOIN dim_listings dl
            ON dl.ticker_on_venue = ha.symbol
           AND dl.venue = 'HYPERLIQUID'
        WHERE ha.asset_type = 'perp'
          AND ha.asset_id < 20000
          AND dl.id IS NOT NULL
        ORDER BY dl.id
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql).fetchall()
    ids = [int(r[0]) for r in rows]
    logger.info("Found %d HL-mapped CMC asset IDs", len(ids))
    return ids


# ---------------------------------------------------------------------------
# Step 2 (cont): IC sweep for derivatives columns
# ---------------------------------------------------------------------------


def run_ic_sweep_for_phase104(
    db_url: str,
    asset_ids: Optional[list[int]] = None,
    tf_filter: Optional[str] = None,
    min_bars: int = 200,
) -> int:
    """Run IC sweep restricted to Phase 104 derivatives feature columns.

    Operates on HL-mapped CMC asset IDs only (not the full features universe).
    Uses batch_compute_ic from the Phase 102/103 IC harness.

    Parameters
    ----------
    db_url:
        SQLAlchemy DB URL.
    asset_ids:
        Optional explicit list of CMC asset IDs to sweep. If None, all HL-mapped
        assets are used.
    tf_filter:
        Optional timeframe restriction (e.g. '1D').
    min_bars:
        Minimum non-null bar count for a (asset, tf) pair to qualify.
        Default 200 (lower than general IC sweep because derivatives data
        history may be shorter than price history).

    Returns
    -------
    int
        Total IC rows written to ic_results.
    """
    from ta_lab2.analysis.ic import (
        batch_compute_ic,
        save_ic_results,
    )
    from ta_lab2.analysis.multiple_testing import log_trials_to_registry
    from ta_lab2.scripts.analysis.run_ic_sweep import _rows_from_ic_df
    from ta_lab2.scripts.sync_utils import get_columns
    from ta_lab2.time.dim_timeframe import DimTimeframe

    engine = create_engine(db_url, poolclass=NullPool)

    # Load DimTimeframe for tf_days_nominal lookup
    try:
        dim = DimTimeframe.from_db(db_url)
        logger.info("DimTimeframe loaded: %d timeframes", len(list(dim.list_tfs())))
    except Exception as exc:
        logger.warning(
            "Failed to load DimTimeframe (%s) -- tf_days_nominal defaults to 1", exc
        )

        class _FallbackDim:
            def tf_days(self, tf: str) -> int:
                return 1

        dim = _FallbackDim()

    # Determine which derivatives cols exist in the features table
    try:
        all_cols = get_columns(engine, "public.features")
    except Exception:
        all_cols = []

    existing_deriv_cols = [c for c in DERIVATIVES_COLS if c in all_cols]
    missing_cols = [c for c in DERIVATIVES_COLS if c not in all_cols]

    if missing_cols:
        logger.warning(
            "Derivatives columns not found in features (migration may be pending): %s",
            missing_cols,
        )

    if not existing_deriv_cols:
        logger.error(
            "None of the Phase 104 derivatives columns exist in features table -- "
            "did you run the 104-01 Alembic migration?"
        )
        engine.dispose()
        return 0

    logger.info(
        "Found %d/%d derivatives columns in features table",
        len(existing_deriv_cols),
        len(DERIVATIVES_COLS),
    )

    # Resolve target asset IDs
    if asset_ids is None:
        target_asset_ids = _get_hl_cmc_asset_ids(engine)
    else:
        target_asset_ids = list(asset_ids)

    if not target_asset_ids:
        logger.warning("No HL-mapped CMC asset IDs found -- aborting IC sweep")
        engine.dispose()
        return 0

    target_set = set(target_asset_ids)

    # Discover qualifying (asset, tf) pairs for derivatives data
    # We query features directly, filtering to target assets, to check which
    # pairs have at least min_bars of non-null derivatives data.
    col_list_sql = ", ".join(f'"{c}"' for c in existing_deriv_cols)
    asset_ids_arr = list(target_set)

    try:
        with engine.connect() as conn:
            # Count non-null rows per (asset_id, tf) across all derivatives cols
            any_notnull = " OR ".join(f'"{c}" IS NOT NULL' for c in existing_deriv_cols)
            pairs_sql = text(f"""
                SELECT id AS asset_id, tf, COUNT(*) AS n_rows
                FROM public.features
                WHERE id = ANY(:asset_ids)
                  AND venue_id = 1
                  AND ({any_notnull})
                GROUP BY id, tf
                HAVING COUNT(*) >= :min_bars
                ORDER BY id, tf
            """)
            pairs_df = pd.read_sql(
                pairs_sql,
                conn,
                params={"asset_ids": asset_ids_arr, "min_bars": min_bars},
            )
    except Exception as exc:
        logger.error("Failed to discover derivatives pairs: %s", exc)
        engine.dispose()
        return 0

    if pairs_df.empty:
        logger.warning(
            "No qualifying (asset, tf) pairs with >= %d bars of derivatives data",
            min_bars,
        )
        engine.dispose()
        return 0

    # Apply tf filter
    if tf_filter:
        pairs_df = pairs_df[pairs_df["tf"] == tf_filter]

    pairs = list(zip(pairs_df["asset_id"], pairs_df["tf"], pairs_df["n_rows"]))
    logger.info(
        "IC sweep: %d (asset, tf) pairs to process for derivatives indicators",
        len(pairs),
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
                # Load derivatives feature columns for this asset/tf
                sql = text(
                    "SELECT ts, " + col_list_sql + ", close "
                    "FROM public.features "
                    "WHERE id = :asset_id AND tf = :tf AND venue_id = 1 "
                    "ORDER BY ts"
                )
                df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})

                if df.empty:
                    logger.debug(
                        "No feature data for asset_id=%d tf=%s -- skipping",
                        asset_id,
                        tf,
                    )
                    skipped += 1
                    continue

                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df = df.set_index("ts")

                close_series = df["close"].dropna()
                if close_series.empty:
                    skipped += 1
                    continue

                features_df = df[existing_deriv_cols]

                # Only include columns with at least some non-null values
                valid_cols = [
                    c for c in existing_deriv_cols if features_df[c].notna().any()
                ]
                if not valid_cols:
                    logger.debug(
                        "All derivatives columns null for asset_id=%d tf=%s -- skipping",
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


def _query_trial_registry_for_phase104(engine) -> pd.DataFrame:
    """Query trial_registry for Phase 104 derivatives indicator results.

    Returns a DataFrame with per-indicator aggregates:
    (indicator_name, mean_abs_ic, min_p_value, max_abs_ic, n_rows, avg_n_obs)

    Filters to horizon=1, return_type='arith', non-null p_values.
    Uses MIN(ic_p_value) per indicator -- most lenient / highest power for FDR.
    """
    col_list = ", ".join(f"'{c}'" for c in DERIVATIVES_COLS)

    sql = text(
        f"""
        SELECT
            indicator_name,
            AVG(ABS(ic_observed))                AS mean_abs_ic,
            MIN(ic_p_value)                      AS min_p_value,
            MAX(ABS(ic_observed))                AS max_abs_ic,
            COUNT(*)                             AS n_rows,
            AVG(n_obs)                           AS avg_n_obs
        FROM trial_registry
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
        logger.info(
            "trial_registry: found %d/%d derivatives indicators with IC results",
            len(df),
            len(DERIVATIVES_COLS),
        )
        return df
    except Exception as exc:
        logger.warning("trial_registry query failed: %s", exc)
        return pd.DataFrame()


def apply_fdr(
    registry_df: pd.DataFrame,
    alpha: float = 0.05,
) -> tuple[list[str], list[str], pd.DataFrame]:
    """Apply Benjamini-Hochberg FDR correction to Phase 104 IC results.

    Parameters
    ----------
    registry_df:
        DataFrame from _query_trial_registry_for_phase104().
    alpha:
        FDR control level (default 0.05).

    Returns
    -------
    (passers, rejects, enriched_df)
        passers: list of feature column names that pass FDR
        rejects: list of feature column names that fail FDR
        enriched_df: registry_df with 'passes_fdr' and 'fdr_p_adjusted' columns
    """
    if registry_df.empty:
        logger.warning(
            "No trial_registry rows found for Phase 104 derivatives indicators"
        )
        return [], [], registry_df

    p_values = registry_df["min_p_value"].fillna(1.0).tolist()

    fdr_result = fdr_control(p_values, alpha=alpha)
    rejected = fdr_result["rejected"]  # bool array: True = significant
    p_adjusted = fdr_result["p_adjusted"]

    enriched = registry_df.copy()
    enriched["passes_fdr"] = rejected
    enriched["fdr_p_adjusted"] = p_adjusted

    passers = list(enriched.loc[enriched["passes_fdr"], "indicator_name"])
    rejects = list(enriched.loc[~enriched["passes_fdr"], "indicator_name"])

    logger.info(
        "FDR at alpha=%.2f: %d/%d derivatives indicators pass",
        alpha,
        len(passers),
        len(registry_df),
    )

    return passers, rejects, enriched


# ---------------------------------------------------------------------------
# Steps 4+5: Promotion and rejection writes to dim_feature_registry
# ---------------------------------------------------------------------------


def _upsert_promoted(
    conn: Any,
    feature_name: str,
    best_ic: float,
    best_horizon: int,
    alpha: float,
    tags: list[str],
) -> None:
    """Upsert a feature as lifecycle='promoted' in dim_feature_registry.

    Writes tags as TEXT[] array alongside standard IC metadata.
    """
    now = datetime.now(timezone.utc)
    # Build the ARRAY literal for tags
    tag_array = "{" + ",".join(f'"{t}"' for t in tags) + "}"
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
                tags,
                updated_at
            ) VALUES (
                :feature_name,
                'promoted',
                :promoted_at,
                :promotion_alpha,
                :best_ic,
                :best_horizon,
                :tags,
                :updated_at
            )
            ON CONFLICT (feature_name) DO UPDATE SET
                lifecycle        = 'promoted',
                promoted_at      = EXCLUDED.promoted_at,
                promotion_alpha  = EXCLUDED.promotion_alpha,
                best_ic          = EXCLUDED.best_ic,
                best_horizon     = EXCLUDED.best_horizon,
                tags             = EXCLUDED.tags,
                updated_at       = EXCLUDED.updated_at
            """
        ),
        {
            "feature_name": feature_name,
            "promoted_at": now,
            "promotion_alpha": alpha,
            "best_ic": float(best_ic) if best_ic is not None else None,
            "best_horizon": int(best_horizon) if best_horizon is not None else 1,
            "tags": tag_array,
            "updated_at": now,
        },
    )


def _upsert_deprecated(
    conn: Any,
    feature_name: str,
    tags: list[str],
) -> None:
    """Upsert a feature as lifecycle='deprecated' in dim_feature_registry."""
    now = datetime.now(timezone.utc)
    tag_array = "{" + ",".join(f'"{t}"' for t in tags) + "}"
    conn.execute(
        text(
            """
            INSERT INTO public.dim_feature_registry (
                feature_name,
                lifecycle,
                tags,
                updated_at
            ) VALUES (
                :feature_name,
                'deprecated',
                :tags,
                :updated_at
            )
            ON CONFLICT (feature_name) DO UPDATE SET
                lifecycle  = 'deprecated',
                tags       = EXCLUDED.tags,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {"feature_name": feature_name, "tags": tag_array, "updated_at": now},
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

    For passers: upsert lifecycle='promoted' with IC metadata and tags.
    For rejects: upsert lifecycle='deprecated' with tags.
    Also ensures every indicator (even those missing from trial_registry)
    gets a registry entry.

    When dry_run=True, logs what would be written without DB writes.
    """
    all_indicators = set(DERIVATIVES_COLS)
    swept_indicators = (
        set(enriched_df["indicator_name"].tolist()) if not enriched_df.empty else set()
    )
    unswept = all_indicators - swept_indicators

    if dry_run:
        logger.info(
            "[dry-run] Would promote %d, deprecate %d, log %d unswept as deprecated",
            len(passers),
            len(rejects),
            len(unswept),
        )
        if passers:
            logger.info("[dry-run] Promotions: %s", passers)
        if rejects:
            logger.info("[dry-run] Deprecations: %s", rejects)
        if unswept:
            logger.info("[dry-run] Unswept (would deprecate): %s", list(unswept))
        return

    # Build lookup: indicator_name -> row
    row_lookup: dict[str, Any] = {}
    if not enriched_df.empty:
        for _, row in enriched_df.iterrows():
            row_lookup[str(row["indicator_name"])] = row

    with engine.begin() as conn:
        # Promote FDR passers
        for feat in passers:
            row = row_lookup.get(feat, {})
            best_ic = float(row.get("max_abs_ic", 0.0)) if row else 0.0
            best_horizon = 1
            try:
                _upsert_promoted(
                    conn, feat, best_ic, best_horizon, alpha, _REGISTRY_TAGS
                )
                logger.info("Promoted: %s (best_ic=%.4f)", feat, best_ic)
            except Exception as exc:
                logger.error("Failed to promote %s: %s", feat, exc)

        # Log FDR rejects
        for feat in rejects:
            try:
                _upsert_deprecated(conn, feat, _REGISTRY_TAGS)
                logger.info("Deprecated: %s", feat)
            except Exception as exc:
                logger.error("Failed to deprecate %s: %s", feat, exc)

        # Log unswept indicators as deprecated (covers the case where a col had
        # no qualifying pairs -- every indicator must have a registry entry)
        for feat in unswept:
            try:
                _upsert_deprecated(conn, feat, _REGISTRY_TAGS)
                logger.info("Deprecated (no IC data): %s", feat)
            except Exception as exc:
                logger.error("Failed to deprecate unswept %s: %s", feat, exc)

    logger.info(
        "dim_feature_registry updated: %d promoted, %d deprecated (%d unswept)",
        len(passers),
        len(rejects) + len(unswept),
        len(unswept),
    )


# ---------------------------------------------------------------------------
# Step 6: Summary report
# ---------------------------------------------------------------------------


def _print_sweep_summary(
    passers: list[str],
    rejects: list[str],
    enriched_df: pd.DataFrame,
    alpha: float,
) -> None:
    """Print FDR sweep summary to console."""
    print("\n" + "=" * 70)
    print(f"PHASE 104 DERIVATIVES IC SWEEP SUMMARY (FDR alpha={alpha:.2f})")
    print("=" * 70)
    print(f"  Total derivatives indicators tested: {len(enriched_df)}")
    print(f"  FDR passers (promoted):              {len(passers)}")
    print(f"  FDR rejects (deprecated):            {len(enriched_df) - len(passers)}")

    if not enriched_df.empty:
        print("\n  Full results (sorted by mean |IC|):")
        print(
            f"  {'Indicator':<25} {'mean_abs_IC':>11} {'min_p':>10} "
            f"{'adj_p':>10} {'FDR pass':>9}"
        )
        print("  " + "-" * 69)
        for _, row in enriched_df.iterrows():
            passes_str = "YES" if row.get("passes_fdr", False) else "no"
            adj_p = row.get("fdr_p_adjusted", float("nan"))
            print(
                f"  {str(row['indicator_name']):<25} "
                f"{row['mean_abs_ic']:>11.4f} "
                f"{row['min_p_value']:>10.4f} "
                f"{adj_p:>10.4f} "
                f"{passes_str:>9}"
            )

    print("=" * 70 + "\n")


def write_csv_report(
    enriched_df: pd.DataFrame,
    passers: list[str],
    rejects: list[str],
    all_indicators: list[str],
    alpha: float,
) -> Path:
    """Write CSV summary report to reports/derivatives/phase104_ic_results.csv.

    Returns the path to the written file.
    """
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _REPORTS_DIR / "phase104_ic_results.csv"

    # Build one row per indicator (include all 8 even if not in enriched_df)
    passer_set = set(passers)

    rows = []
    lookup: dict[str, Any] = {}
    if not enriched_df.empty:
        for _, row in enriched_df.iterrows():
            lookup[str(row["indicator_name"])] = row

    for indicator in all_indicators:
        row = lookup.get(indicator)
        if row is not None:
            lifecycle = "promoted" if indicator in passer_set else "deprecated"
            rows.append(
                {
                    "indicator_name": indicator,
                    "mean_abs_ic": float(row.get("mean_abs_ic", float("nan"))),
                    "min_p_value": float(row.get("min_p_value", float("nan"))),
                    "max_abs_ic": float(row.get("max_abs_ic", float("nan"))),
                    "avg_n_obs": float(row.get("avg_n_obs", float("nan"))),
                    "n_trial_rows": int(row.get("n_rows", 0)),
                    "fdr_p_adjusted": float(row.get("fdr_p_adjusted", float("nan"))),
                    "passes_fdr": bool(row.get("passes_fdr", False)),
                    "lifecycle": lifecycle,
                    "fdr_alpha": alpha,
                }
            )
        else:
            # Indicator was not swept (no qualifying pairs)
            rows.append(
                {
                    "indicator_name": indicator,
                    "mean_abs_ic": float("nan"),
                    "min_p_value": float("nan"),
                    "max_abs_ic": float("nan"),
                    "avg_n_obs": float("nan"),
                    "n_trial_rows": 0,
                    "fdr_p_adjusted": float("nan"),
                    "passes_fdr": False,
                    "lifecycle": "deprecated",
                    "fdr_alpha": alpha,
                }
            )

    df_out = pd.DataFrame(rows)
    df_out.to_csv(out_path, index=False)
    logger.info("CSV report written to %s", out_path)
    return out_path


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_coverage(engine) -> dict[str, Any]:
    """Validate trial_registry and dim_feature_registry coverage.

    Checks:
    1. COUNT(DISTINCT indicator_name) in trial_registry for Phase 104 indicators
    2. lifecycle status in dim_feature_registry for all 8 derivatives columns

    Returns a dict with coverage stats.
    """
    print("\n" + "=" * 70)
    print("PHASE 104 COVERAGE VALIDATION")
    print("=" * 70)

    col_list = ", ".join(f"'{c}'" for c in DERIVATIVES_COLS)

    # --- trial_registry coverage ---
    try:
        with engine.connect() as conn:
            cnt_sql = text(
                f"SELECT COUNT(DISTINCT indicator_name) AS cnt "
                f"FROM trial_registry "
                f"WHERE indicator_name IN ({col_list})"
            )
            cnt_row = conn.execute(cnt_sql).fetchone()
            trial_count = int(cnt_row[0]) if cnt_row else 0

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
        trial_count = 0
        present_features = set()

    missing_from_trial = [c for c in DERIVATIVES_COLS if c not in present_features]

    print("\nTrial Registry Coverage:")
    print(
        f"  Distinct indicators with IC results: {trial_count}/{len(DERIVATIVES_COLS)}"
    )
    if missing_from_trial:
        print(f"  Missing from trial_registry: {missing_from_trial}")
    else:
        print("  All 8 derivatives indicators have trial_registry entries")

    # --- dim_feature_registry coverage ---
    try:
        with engine.connect() as conn:
            reg_sql = text(
                f"""
                SELECT feature_name, lifecycle, best_ic, best_horizon, tags
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
        print("  No Phase 104 derivatives features found in dim_feature_registry")
        n_promoted = 0
        n_deprecated = 0
        n_orphans = len(DERIVATIVES_COLS)
    else:
        n_promoted = int((reg_df["lifecycle"] == "promoted").sum())
        n_deprecated = int((reg_df["lifecycle"] == "deprecated").sum())
        registered = set(reg_df["feature_name"])
        orphans = [c for c in DERIVATIVES_COLS if c not in registered]
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
        "trial_registry_count": trial_count,
        "n_promoted": n_promoted,
        "n_deprecated": n_deprecated,
        "n_orphans": n_orphans,
        "missing_from_trial": missing_from_trial,
        "passes_coverage_check": trial_count == len(DERIVATIVES_COLS),
        "passes_registry_check": n_orphans == 0 and (n_promoted + n_deprecated) > 0,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Phase 104 IC sweep runner entry point. Returns exit code."""
    parser = argparse.ArgumentParser(
        prog="run_phase104_ic",
        description=(
            "Phase 104 IC sweep runner.\n\n"
            "Runs IC sweep for 8 derivatives indicator columns across all "
            "HL-mapped CMC assets, applies BH FDR correction at alpha (default "
            "5%), and promotes/rejects features in dim_feature_registry."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Scope
    parser.add_argument(
        "--assets",
        nargs="+",
        type=int,
        metavar="ID",
        dest="asset_ids",
        default=None,
        help="Specific CMC asset IDs to evaluate (default: all HL-mapped assets).",
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
        default=200,
        metavar="N",
        dest="min_bars",
        help="Minimum non-null bars for qualifying pairs (default: 200).",
    )

    # FDR
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.05,
        metavar="FLOAT",
        dest="alpha",
        help="FDR Benjamini-Hochberg alpha threshold (default: 0.05).",
    )

    # Behaviour
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help=(
            "Run sweep + FDR but do NOT write to dim_feature_registry. "
            "Useful for previewing outcomes."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        dest="validate_only",
        help="Only run validate_coverage() -- skip sweep and FDR.",
    )
    parser.add_argument(
        "--skip-sweep",
        action="store_true",
        dest="skip_sweep",
        help=(
            "Skip IC sweep (use existing trial_registry data) and go "
            "directly to FDR + promotion."
        ),
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

    sweep_start = time.time()
    db_url = resolve_db_url(args.db_url)
    engine = create_engine(db_url, poolclass=NullPool)

    # --- Step 1: Verify prerequisites ---
    try:
        verify_prerequisites(engine)
    except RuntimeError as exc:
        logger.error("%s", exc)
        engine.dispose()
        return 1

    # --- Validate-only mode ---
    if args.validate_only:
        result = validate_coverage(engine)
        engine.dispose()
        return 0 if result["passes_registry_check"] else 1

    # --- Step 2: IC sweep ---
    if not args.skip_sweep:
        logger.info(
            "Step 2: Running IC sweep for %d Phase 104 derivatives columns...",
            len(DERIVATIVES_COLS),
        )
        n_ic_rows = run_ic_sweep_for_phase104(
            db_url=db_url,
            asset_ids=args.asset_ids,
            tf_filter=args.tf_filter,
            min_bars=args.min_bars,
        )
        logger.info("IC sweep wrote %d rows to ic_results / trial_registry", n_ic_rows)
    else:
        logger.info("Step 2: Skipping IC sweep (--skip-sweep). Using existing data.")

    # --- Step 3: Apply FDR ---
    logger.info("Step 3: Applying FDR correction at alpha=%.2f...", args.alpha)
    registry_df = _query_trial_registry_for_phase104(engine)

    if registry_df.empty:
        logger.warning(
            "No trial_registry rows found for Phase 104 derivatives indicators -- "
            "FDR and promotion skipped."
        )
        # Still write all indicators as deprecated so every indicator has a registry entry
        passers: list[str] = []
        rejects: list[str] = []
        enriched_df = pd.DataFrame()
    else:
        passers, rejects, enriched_df = apply_fdr(registry_df, alpha=args.alpha)

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
        alpha=args.alpha,
        dry_run=args.dry_run,
    )

    # --- Step 6: Summary ---
    _print_sweep_summary(
        passers,
        rejects,
        enriched_df if not enriched_df.empty else pd.DataFrame(),
        alpha=args.alpha,
    )

    # Write CSV report
    report_path = write_csv_report(
        enriched_df, passers, rejects, DERIVATIVES_COLS, args.alpha
    )
    print(f"CSV report: {report_path}")

    # --- Validate coverage ---
    validate_coverage(engine)

    elapsed = time.time() - sweep_start
    logger.info("Phase 104 IC sweep pipeline complete in %.1fs", elapsed)

    engine.dispose()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
