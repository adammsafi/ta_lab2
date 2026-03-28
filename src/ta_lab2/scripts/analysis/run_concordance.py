"""
CLI for comparing IC-IR feature rankings with MDA feature importance rankings.

Computes Spearman rank concordance between two complementary feature scoring
methods:
- IC-IR ranking: rank correlation of features with forward returns (loaded from
  ic_results table via load_ic_ranking)
- MDA ranking: permutation importance from a RandomForest classifier via
  PurgedKFoldSplitter (leakage-free, no look-ahead)

Features that appear in both top-20 lists are flagged as "high-confidence" --
agreement between two independent measurement methods is strong evidence of
genuine predictive power. Disagreements are surfaced for investigation.

Feature clusters (correlated groups) are identified via cluster_features()
and the best-per-cluster (highest IC-IR) is selected to eliminate redundancy.

Usage
-----
    python -m ta_lab2.scripts.analysis.run_concordance \\
        --asset-ids 1,1027 \\
        --tf 1D \\
        --start 2024-01-01 \\
        --end 2025-12-31 \\
        --top-n 30 \\
        --n-splits 5 \\
        --output-csv reports/concordance/ic_vs_mda_concordance.csv

Notes
-----
- Uses NullPool for SQLAlchemy engine (no connection pooling in CLI process).
- All timestamp columns loaded with pd.to_datetime(utc=True) per MEMORY.md.
- IC-IR ranking takes precedence when IC-IR and MDA disagree (per CONTEXT.md).
- MDA failures (insufficient data, all folds purged) degrade gracefully --
  concordance report falls back to IC-IR-only mode with a warning.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Columns that are never used as features
# ---------------------------------------------------------------------------

_EXCLUDE_COLS = frozenset(
    [
        "id",
        "ts",
        "tf",
        "ingested_at",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "alignment_source",
        "asset_class",
        "venue",
        "ret_arith",  # label source -- excluded from feature matrix
        "ret_log",
        "updated_at",
    ]
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_concordance",
        description=(
            "Compare IC-IR feature rankings with MDA importance rankings. "
            "Identifies high-confidence features (top-20 in both methods) "
            "and resolves correlated feature clusters."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--asset-ids",
        required=True,
        help="Comma-separated asset IDs for MDA computation. E.g., '1,1027' for BTC/ETH.",
    )
    parser.add_argument(
        "--tf",
        default="1D",
        help="Timeframe string, e.g. '1D' or '4H' (default: '1D')",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Training start date ISO format, e.g. '2024-01-01'",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="Training end date ISO format, e.g. '2025-12-31'",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=1,
        help="IC horizon for ranking comparison (default: 1)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=30,
        help="Top N features from IC-IR ranking to include in concordance (default: 30)",
    )
    parser.add_argument(
        "--n-splits",
        type=int,
        default=5,
        help="Number of purged K-fold splits for MDA (default: 5)",
    )
    parser.add_argument(
        "--cluster-threshold",
        type=float,
        default=0.5,
        help="Spearman correlation distance threshold for feature clustering (default: 0.5)",
    )
    parser.add_argument(
        "--output-csv",
        default=None,
        help="Optional: path to write concordance CSV",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _build_engine() -> Any:
    """Build NullPool SQLAlchemy engine from ta_lab2 config."""
    from ta_lab2.scripts.refresh_utils import resolve_db_url

    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=NullPool)


def _load_features_for_mda(
    engine: Any,
    asset_ids: list[int],
    tf: str,
    start: str,
    end: str,
    feature_cols: list[str],
) -> pd.DataFrame:
    """
    Load feature data for MDA computation.

    Only loads the specified feature_cols plus ret_arith (for labels) and ts.
    Skips features not present in the features table, returning only those
    columns that actually exist.

    Returns DataFrame with UTC-aware ts column.
    """
    ids_literal = "{" + ",".join(str(i) for i in asset_ids) + "}"

    # First load ts, ret_arith, and the requested feature columns
    # Use SELECT * then filter in Python to avoid brittle column-list SQL
    sql = text(
        """
        SELECT *
        FROM public.features
        WHERE id = ANY(CAST(:ids AS INTEGER[]))
          AND tf = :tf
          AND ts BETWEEN CAST(:start AS TIMESTAMPTZ) AND CAST(:end AS TIMESTAMPTZ)
        ORDER BY id, ts
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"ids": ids_literal, "tf": tf, "start": start, "end": end}
        )

    if df.empty:
        return df

    # CRITICAL: UTC-aware timestamps (MEMORY.md pitfall)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    return df


# ---------------------------------------------------------------------------
# Feature matrix builder
# ---------------------------------------------------------------------------


def _build_feature_matrix(
    df: pd.DataFrame,
    requested_features: list[str],
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """
    Build the feature matrix X and binary labels y from a features DataFrame.

    Filters to only requested_features that exist in df and are numeric.
    Drops rows with NaN in any feature column (after forward-fill).

    Returns
    -------
    X : pd.DataFrame
        Feature matrix sorted by ts, shape (n_samples, n_features_available).
    available_features : list[str]
        Feature columns that were found and are usable.
    missing_features : list[str]
        Requested features not found in the features table.
    """
    # Identify which requested features are available in the table
    available = [
        c
        for c in requested_features
        if c in df.columns
        and c not in _EXCLUDE_COLS
        and pd.api.types.is_numeric_dtype(df[c])
        and df[c].notna().any()
    ]
    missing = [c for c in requested_features if c not in available]

    return available, missing


# ---------------------------------------------------------------------------
# Concordance computation
# ---------------------------------------------------------------------------


def _compute_concordance(
    ic_ranking: pd.DataFrame,
    mda_importance: pd.Series,
    top_n_overlap: int = 20,
) -> pd.DataFrame:
    """
    Compute the merged ranking DataFrame comparing IC-IR and MDA ranks.

    Parameters
    ----------
    ic_ranking : pd.DataFrame
        IC ranking with columns: feature, mean_abs_ic_ir (sorted desc).
    mda_importance : pd.Series
        MDA importance Series, index = feature name, values = importance score.
        May be None or empty.
    top_n_overlap : int
        Number of top features to use for overlap identification.

    Returns
    -------
    pd.DataFrame
        Columns: feature, ic_ir_value, mda_value, ic_ir_rank, mda_rank,
        agreement (AGREE/DIVERGE), confidence (HIGH/LOW).
    """
    # Build IC-IR ranks (1 = best)
    ic_df = ic_ranking.reset_index(drop=True).copy()
    ic_df["ic_ir_rank"] = range(1, len(ic_df) + 1)

    if mda_importance is None or mda_importance.empty:
        # MDA not available — return IC-only ranking
        ic_df["mda_value"] = np.nan
        ic_df["mda_rank"] = np.nan
        ic_df["agreement"] = "IC_ONLY"
        ic_df["confidence"] = "IC_ONLY"
        return ic_df[
            [
                "feature",
                "mean_abs_ic_ir",
                "mda_value",
                "ic_ir_rank",
                "mda_rank",
                "agreement",
                "confidence",
            ]
        ].rename(columns={"mean_abs_ic_ir": "ic_ir_value"})

    # Build MDA ranks (1 = best)
    mda_sorted = mda_importance.sort_values(ascending=False)
    mda_df = pd.DataFrame(
        {
            "feature": mda_sorted.index,
            "mda_value": mda_sorted.values,
            "mda_rank": range(1, len(mda_sorted) + 1),
        }
    )

    # Merge on feature
    merged = ic_df[["feature", "mean_abs_ic_ir", "ic_ir_rank"]].merge(
        mda_df, on="feature", how="left"
    )
    merged = merged.rename(columns={"mean_abs_ic_ir": "ic_ir_value"})

    # Agreement: AGREE if both in top-N, DIVERGE if only one is in top-N
    top_ic_features = set(ic_df[ic_df["ic_ir_rank"] <= top_n_overlap]["feature"])
    top_mda_features = set(mda_df[mda_df["mda_rank"] <= top_n_overlap]["feature"])

    def _label_agreement(row):
        in_ic_top = row["feature"] in top_ic_features
        in_mda_top = row["feature"] in top_mda_features and not pd.isna(row["mda_rank"])
        if in_ic_top and in_mda_top:
            return "AGREE"
        return "DIVERGE"

    def _label_confidence(row):
        in_ic_top = row["feature"] in top_ic_features
        in_mda_top = row["feature"] in top_mda_features and not pd.isna(row["mda_rank"])
        if in_ic_top and in_mda_top:
            return "HIGH"
        return "LOW"

    merged["agreement"] = merged.apply(_label_agreement, axis=1)
    merged["confidence"] = merged.apply(_label_confidence, axis=1)

    return merged


# ---------------------------------------------------------------------------
# Cluster summary
# ---------------------------------------------------------------------------


def _resolve_cluster_bests(
    clusters: dict[str, list[str]],
    ic_ranking: pd.DataFrame,
) -> list[dict]:
    """
    For each cluster, identify the best feature by IC-IR rank.

    Returns list of dicts with: cluster_id, members, best_feature, best_ic_ir.
    """
    # Build feature -> ic_ir_value lookup
    ic_lookup = dict(zip(ic_ranking["feature"], ic_ranking["mean_abs_ic_ir"]))
    ic_rank_lookup = {feat: rank + 1 for rank, feat in enumerate(ic_ranking["feature"])}

    results = []
    for cluster_id, members in clusters.items():
        if not members:
            continue
        # Best = highest IC-IR among cluster members that appear in IC ranking
        scored = [(m, ic_lookup.get(m, 0.0)) for m in members]
        scored.sort(key=lambda x: x[1], reverse=True)
        best_feature, best_ic_ir = scored[0]
        results.append(
            {
                "cluster_id": cluster_id,
                "members": members,
                "n_members": len(members),
                "best_feature": best_feature,
                "best_ic_ir": best_ic_ir,
                "best_ic_ir_rank": ic_rank_lookup.get(best_feature, -1),
            }
        )

    # Sort by number of members desc (largest clusters first), then by best IC-IR
    results.sort(key=lambda x: (-x["n_members"], -x["best_ic_ir"]))
    return results


# ---------------------------------------------------------------------------
# Report printing
# ---------------------------------------------------------------------------


def _print_concordance_report(
    merged: pd.DataFrame,
    spearman_rho: float | None,
    spearman_pvalue: float | None,
    high_confidence: list[str],
    ic_only: list[str],
    mda_only: list[str],
    cluster_summaries: list[dict],
    top_n_overlap: int = 20,
    mda_failed: bool = False,
) -> None:
    """Print the full concordance report to stdout."""
    print("\n" + "=" * 70)
    print("=== Concordance Report: IC-IR vs MDA ===")
    print("=" * 70)

    if mda_failed:
        print("\nWARNING: MDA computation failed or produced no valid results.")
        print("Showing IC-IR ranking only.\n")
    else:
        if spearman_rho is not None:
            pval_str = (
                f"{spearman_pvalue:.4f}" if spearman_pvalue is not None else "N/A"
            )
            print(f"\nIC-IR vs MDA Spearman rho: {spearman_rho:.4f} (p={pval_str})")

            if spearman_rho >= 0.6:
                interp = "Strong concordance"
            elif spearman_rho >= 0.4:
                interp = "Moderate concordance"
            elif spearman_rho >= 0.2:
                interp = "Weak concordance"
            elif spearman_rho >= 0.0:
                interp = "Near-zero concordance (methods measuring different aspects)"
            else:
                interp = "Negative concordance (unusual — investigate)"
            print(f"Interpretation: {interp}")
        else:
            print("\nSpearman rho: N/A (insufficient overlap for computation)")

        print(f"\nHigh-confidence (both top-{top_n_overlap}): {high_confidence}")
        print(f"IC-IR only (top-{top_n_overlap}):          {ic_only}")
        print(f"MDA only (top-{top_n_overlap}):            {mda_only}")

    # Feature clusters
    print("\n" + "=" * 70)
    print("=== Feature Clusters ===")
    print("=" * 70)

    multi_member = [c for c in cluster_summaries if c["n_members"] > 1]
    singletons = [c for c in cluster_summaries if c["n_members"] == 1]

    if multi_member:
        for cs in multi_member:
            members_str = ", ".join(cs["members"])
            print(
                f"{cs['cluster_id']}: [{members_str}] -> "
                f"Best: {cs['best_feature']} (IC-IR={cs['best_ic_ir']:.4f})"
            )
    else:
        print("No multi-feature clusters found (all features are unique/uncorrelated).")

    print(f"\nSingleton clusters (uncorrelated features): {len(singletons)}")

    # Merged ranking table
    print("\n" + "=" * 70)
    print("=== Merged Ranking ===")
    print("=" * 70)

    # Map feature -> cluster_id
    feat_to_cluster: dict[str, str] = {}
    for cs in cluster_summaries:
        for m in cs["members"]:
            feat_to_cluster[m] = cs["cluster_id"]

    # Build cluster assignment column for merged df
    merged_display = merged.copy()
    merged_display["cluster"] = (
        merged_display["feature"].map(feat_to_cluster).fillna("-")
    )

    # Format columns
    header = (
        f"{'Feature':<40} {'IC-IR Rank':>10} {'MDA Rank':>10} "
        f"{'Agreement':>10} {'Cluster':>12}"
    )
    print(header)
    print("-" * 85)

    for _, row in merged_display.iterrows():
        ic_rank_str = str(int(row["ic_ir_rank"]))
        mda_rank_val = row.get("mda_rank")
        if pd.isna(mda_rank_val):
            mda_rank_str = "N/A"
        else:
            mda_rank_str = str(int(mda_rank_val))

        agreement = str(row.get("agreement", "N/A"))
        cluster_str = str(row["cluster"])

        print(
            f"{row['feature']:<40} {ic_rank_str:>10} {mda_rank_str:>10} "
            f"{agreement:>10} {cluster_str:>12}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asset_ids = [int(x.strip()) for x in args.asset_ids.split(",")]
    logger.info(
        "run_concordance: asset_ids=%s tf=%s start=%s end=%s horizon=%d top_n=%d",
        asset_ids,
        args.tf,
        args.start,
        args.end,
        args.horizon,
        args.top_n,
    )

    t0 = time.time()

    # -----------------------------------------------------------------------
    # Step 1: Load IC-IR ranking
    # -----------------------------------------------------------------------
    logger.info("Connecting to database...")
    engine = _build_engine()

    logger.info("Loading IC-IR ranking (horizon=%d)...", args.horizon)
    from ta_lab2.analysis.feature_selection import load_ic_ranking

    ic_ranking = load_ic_ranking(engine, horizon=args.horizon)

    if ic_ranking.empty:
        logger.warning(
            "No ic_results data found for horizon=%d. "
            "Ensure run_ic_sweep.py has been executed first.",
            args.horizon,
        )
        print(
            "WARNING: No ic_results data found. "
            "Please run run_ic_sweep.py before concordance analysis."
        )
        sys.exit(0)

    logger.info("IC-IR ranking loaded: %d features", len(ic_ranking))

    # Limit to top-N features for concordance
    top_ic = ic_ranking.head(args.top_n).copy()
    top_features = top_ic["feature"].tolist()
    logger.info("Top-%d features from IC-IR: %s", args.top_n, top_features[:5])

    # -----------------------------------------------------------------------
    # Step 2: Load feature data for MDA
    # -----------------------------------------------------------------------
    logger.info("Loading feature data from DB...")
    df = _load_features_for_mda(
        engine,
        asset_ids=asset_ids,
        tf=args.tf,
        start=args.start,
        end=args.end,
        feature_cols=top_features,
    )

    mda_importance: pd.Series | None = None
    mda_failed = False
    missing_features: list[str] = []

    if df.empty:
        logger.warning(
            "No feature data found for asset_ids=%s tf=%s %s to %s. "
            "Skipping MDA — reporting IC-IR only.",
            asset_ids,
            args.tf,
            args.start,
            args.end,
        )
        mda_failed = True
    else:
        # Identify available vs missing features
        available_features, missing_features = _build_feature_matrix(df, top_features)

        if missing_features:
            logger.warning(
                "%d requested features not found in features table (will be skipped in MDA): %s",
                len(missing_features),
                missing_features,
            )

        if not available_features:
            logger.warning(
                "None of the top-%d IC features are present in the features table. "
                "Skipping MDA.",
                args.top_n,
            )
            mda_failed = True
        else:
            logger.info(
                "%d features available for MDA (%d missing from features table)",
                len(available_features),
                len(missing_features),
            )

            # Build feature matrix
            X_raw = df[available_features].copy()

            # Forward-fill, drop all-NaN columns
            X_raw = X_raw.ffill().dropna(axis=1, how="all")
            available_features = list(X_raw.columns)

            # Drop rows with any NaN remaining
            valid_mask = X_raw.notna().all(axis=1)
            X_raw = X_raw[valid_mask]
            df_valid = df[valid_mask].copy()

            if len(df_valid) == 0:
                logger.warning("All feature rows are NaN — skipping MDA.")
                mda_failed = True
            else:
                # Sort by ts for PurgedKFold
                sort_idx = df_valid["ts"].argsort()
                df_valid = df_valid.iloc[sort_idx].reset_index(drop=True)
                X = X_raw.iloc[sort_idx].reset_index(drop=True)

                logger.info(
                    "Feature matrix: %d rows x %d columns", len(X), len(X.columns)
                )

                # Binary labels from ret_arith
                if (
                    "ret_arith" not in df_valid.columns
                    or df_valid["ret_arith"].isna().all()
                ):
                    logger.warning("ret_arith not available — skipping MDA.")
                    mda_failed = True
                else:
                    y = (df_valid["ret_arith"] > 0).astype(int).values
                    logger.info(
                        "Labels: %d positive (%.1f%%), %d negative (%.1f%%)",
                        int(y.sum()),
                        100.0 * y.sum() / len(y),
                        int((y == 0).sum()),
                        100.0 * (y == 0).sum() / len(y),
                    )

                    # -----------------------------------------------------------
                    # Step 3: Build t1_series for PurgedKFold
                    # -----------------------------------------------------------
                    # CRITICAL (MEMORY.md): .values on tz-aware Series returns
                    # tz-naive numpy.datetime64. Use .tolist() to preserve tz-aware
                    # Timestamp objects for correct cv.py comparisons.
                    ts_series = df_valid["ts"].reset_index(drop=True)
                    t1_series = ts_series + pd.Timedelta(days=1)
                    t1_series.index = ts_series.tolist()

                    # Verify monotonically increasing (required by PurgedKFoldSplitter)
                    if not t1_series.index.is_monotonic_increasing:
                        logger.warning(
                            "t1_series index is not monotonically increasing — "
                            "re-sorting by ts."
                        )
                        sort_order = sorted(
                            range(len(t1_series)), key=lambda i: t1_series.index[i]
                        )
                        t1_series = t1_series.iloc[sort_order]
                        X = X.iloc[sort_order].reset_index(drop=True)
                        y = y[sort_order]

                    # -----------------------------------------------------------
                    # Step 4: Run MDA
                    # -----------------------------------------------------------
                    logger.info(
                        "Running MDA (n_splits=%d, n_repeats=3)...", args.n_splits
                    )
                    from sklearn.ensemble import RandomForestClassifier

                    from ta_lab2.ml.feature_importance import compute_mda

                    model = RandomForestClassifier(
                        n_estimators=100, max_depth=5, random_state=42, n_jobs=-1
                    )

                    try:
                        mda_importance = compute_mda(
                            model=model,
                            X=X,
                            y=y,
                            t1_series=t1_series,
                            n_splits=args.n_splits,
                            n_repeats=3,
                        )
                        logger.info(
                            "MDA complete. Top features: %s",
                            list(mda_importance.head(5).index),
                        )
                    except Exception as e:
                        logger.warning(
                            "MDA computation failed: %s. Reporting IC-IR ranking only.",
                            e,
                        )
                        mda_failed = True

    # -----------------------------------------------------------------------
    # Step 5: Compute concordance metrics
    # -----------------------------------------------------------------------
    top_n_overlap = min(20, args.top_n)

    # Spearman rho between IC-IR ranks and MDA ranks (only on features present in both)
    spearman_rho: float | None = None
    spearman_pvalue: float | None = None
    high_confidence: list[str] = []
    ic_only: list[str] = []
    mda_only: list[str] = []

    merged = _compute_concordance(top_ic, mda_importance, top_n_overlap=top_n_overlap)

    if not mda_failed and mda_importance is not None and not mda_importance.empty:
        # Compute Spearman on features that appear in both rankings
        overlap_mask = merged["mda_rank"].notna()
        overlap_df = merged[overlap_mask]

        if len(overlap_df) >= 3:
            rho_result = spearmanr(
                overlap_df["ic_ir_rank"].values,
                overlap_df["mda_rank"].values,
            )
            spearman_rho = float(rho_result.statistic)
            spearman_pvalue = float(rho_result.pvalue)
        else:
            logger.warning(
                "Too few overlapping features (%d) for Spearman rho computation.",
                len(overlap_df),
            )

        # Identify high-confidence, IC-only, MDA-only features
        top_ic_set = set(top_ic[top_ic.index < top_n_overlap]["feature"])
        if len(top_ic) >= top_n_overlap:
            top_ic_set = set(top_ic.head(top_n_overlap)["feature"])

        mda_sorted = mda_importance.sort_values(ascending=False)
        top_mda_set = set(mda_sorted.head(top_n_overlap).index)

        high_confidence = sorted(top_ic_set & top_mda_set)
        ic_only = sorted(top_ic_set - top_mda_set)
        mda_only = sorted(top_mda_set - top_ic_set)

    # -----------------------------------------------------------------------
    # Step 6: Feature clustering
    # -----------------------------------------------------------------------
    logger.info(
        "Computing feature clusters (threshold=%.2f)...", args.cluster_threshold
    )
    cluster_summaries: list[dict] = []

    # Use the features available in X for clustering
    if not mda_failed and "X" in dir() and not X.empty and len(X.columns) > 0:  # type: ignore[name-defined]
        try:
            from ta_lab2.ml.feature_importance import cluster_features

            # Use only top-N IC features that are available in the feature matrix
            cluster_features_list = [c for c in top_features if c in X.columns]  # type: ignore[name-defined]

            # Drop constant (zero-variance) features — they produce NaN in Spearman
            # correlation matrix and break the Ward linkage step
            if cluster_features_list:
                X_cluster = X[cluster_features_list]  # type: ignore[name-defined]
                non_constant = [
                    c for c in cluster_features_list if X_cluster[c].std() > 0
                ]
                if len(non_constant) < len(cluster_features_list):
                    dropped = set(cluster_features_list) - set(non_constant)
                    logger.warning(
                        "Dropping %d constant features from clustering: %s",
                        len(dropped),
                        sorted(dropped),
                    )
                cluster_features_list = non_constant

            if len(cluster_features_list) >= 2:
                clusters = cluster_features(
                    X[cluster_features_list],
                    threshold=args.cluster_threshold,  # type: ignore[name-defined]
                )
                cluster_summaries = _resolve_cluster_bests(clusters, top_ic)
                logger.info(
                    "Feature clusters: %d clusters for %d features",
                    len(clusters),
                    len(cluster_features_list),
                )
            else:
                logger.warning(
                    "Too few features for clustering (%d). Skipping.",
                    len(cluster_features_list),
                )
                cluster_summaries = [
                    {
                        "cluster_id": "cluster_1",
                        "members": cluster_features_list,
                        "n_members": len(cluster_features_list),
                        "best_feature": cluster_features_list[0]
                        if cluster_features_list
                        else "",
                        "best_ic_ir": 0.0,
                        "best_ic_ir_rank": 1,
                    }
                ]
        except Exception as e:
            logger.warning("Feature clustering failed: %s. Skipping.", e)
    else:
        # No feature matrix available — create trivial singleton clusters from IC ranking
        cluster_summaries = [
            {
                "cluster_id": f"cluster_{i + 1}",
                "members": [feat],
                "n_members": 1,
                "best_feature": feat,
                "best_ic_ir": float(row.get("mean_abs_ic_ir", 0.0)),
                "best_ic_ir_rank": i + 1,
            }
            for i, (_, row) in enumerate(top_ic.iterrows())
            for feat in [str(row["feature"])]
        ]

    # Add cluster_id column to merged DataFrame
    feat_to_cluster: dict[str, str] = {}
    for cs in cluster_summaries:
        for m in cs["members"]:
            feat_to_cluster[m] = cs["cluster_id"]
    merged["cluster_id"] = merged["feature"].map(feat_to_cluster).fillna("-")

    # -----------------------------------------------------------------------
    # Step 7: Print concordance report
    # -----------------------------------------------------------------------
    _print_concordance_report(
        merged=merged,
        spearman_rho=spearman_rho,
        spearman_pvalue=spearman_pvalue,
        high_confidence=high_confidence,
        ic_only=ic_only,
        mda_only=mda_only,
        cluster_summaries=cluster_summaries,
        top_n_overlap=top_n_overlap,
        mda_failed=mda_failed,
    )

    if missing_features:
        print(
            f"\nNOTE: {len(missing_features)} IC features not in features table (skipped in MDA):"
        )
        print(f"  {missing_features}")

    duration = time.time() - t0
    print(f"\nConcordance analysis complete in {duration:.1f} seconds.")

    # -----------------------------------------------------------------------
    # Step 8: Optional CSV output
    # -----------------------------------------------------------------------
    if args.output_csv:
        output_path = Path(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build final CSV columns
        csv_df = merged.rename(
            columns={"mean_abs_ic_ir": "ic_ir_value"}
            if "mean_abs_ic_ir" in merged.columns
            else {}
        )

        # Ensure consistent column naming
        if "ic_ir_value" not in csv_df.columns and "mean_abs_ic_ir" in csv_df.columns:
            csv_df = csv_df.rename(columns={"mean_abs_ic_ir": "ic_ir_value"})

        # Add MDA importance value if available
        if mda_importance is not None and not mda_importance.empty:
            mda_val_map = mda_importance.to_dict()
            if "mda_value" not in csv_df.columns:
                csv_df["mda_value"] = csv_df["feature"].map(mda_val_map)

        csv_df.to_csv(output_path, index=False)
        logger.info("Wrote concordance CSV to %s (%d rows)", output_path, len(csv_df))
        print(f"CSV written: {output_path}")


if __name__ == "__main__":
    main()
