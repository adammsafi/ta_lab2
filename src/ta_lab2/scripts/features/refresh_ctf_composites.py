"""
refresh_ctf_composites.py -- Cross-Asset CTF Composite Script (Phase 98 Plan 03).

Computes three cross-asset CTF composite types:
  1. Sentiment (cross-asset mean + PCA first component)
  2. Relative-value (cross-sectional z-score)
  3. Leader-follower (lagged cross-correlation scoring)

All composites are persisted to the ``ctf_composites`` table via temp table + upsert.
Top composites (sentiment_mean, relative_value) are optionally materialized to the
``features`` table via UPDATE (if the composite columns exist there).

Data flow:
  1. Load promoted CTF feature names from configs/feature_selection.yaml
     (ctf_promoted section written by refresh_ctf_promoted.py).
  2. For each base_tf in config.base_tfs:
     a. Load CTF data for all tier-1 assets via load_ctf_features().
     b. Build per-feature multi-asset pivot (rows=ts, cols=asset_id).
     c. Compute composites.
  3. Persist to ctf_composites (temp table + INSERT ON CONFLICT upsert).
  4. Materialize to features if columns exist (UPDATE pattern).

Usage:
    python -m ta_lab2.scripts.features.refresh_ctf_composites --dry-run
    python -m ta_lab2.scripts.features.refresh_ctf_composites
    python -m ta_lab2.scripts.features.refresh_ctf_composites --composite sentiment_mean
    python -m ta_lab2.scripts.features.refresh_ctf_composites --base-tf 1D
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import datetime  # noqa: F401 (reserved for future use in output timestamps)
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

try:
    from ta_lab2.config import TARGET_DB_URL, project_root  # type: ignore[import]
except Exception:  # pragma: no cover

    def project_root() -> Path:  # type: ignore[misc]
        p = Path(__file__).resolve()
        for parent in [p, *p.parents]:
            if (parent / "pyproject.toml").exists():
                return parent
        return Path(__file__).resolve().parents[4]

    import os

    TARGET_DB_URL = os.environ.get("TARGET_DB_URL", "")

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

try:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SKLEARN_AVAILABLE = False

from ta_lab2.features.cross_timeframe import load_ctf_features
from ta_lab2.regimes.comovement import lead_lag_max_corr

logger = logging.getLogger(__name__)

# =============================================================================
# Constants
# =============================================================================

_DEFAULT_VENUE_ID = 1
_DEFAULT_ALIGNMENT_SOURCE = "multi_tf"
_CONFIG_PATH_REL = "configs/ctf_composites_config.yaml"
_FEATURE_SELECTION_PATH_REL = "configs/feature_selection.yaml"

# Full history window for loading CTF data.
_FULL_HISTORY_START = pd.Timestamp("2010-01-01", tz="UTC")
_FULL_HISTORY_END = pd.Timestamp.now(tz="UTC")

# =============================================================================
# Config loading
# =============================================================================


def _load_config() -> dict:
    """Load configs/ctf_composites_config.yaml."""
    if yaml is None:
        raise ImportError("PyYAML is required. Install with: pip install pyyaml")

    config_path = project_root() / _CONFIG_PATH_REL
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data:
        raise ValueError(f"Config is empty: {config_path}")

    return data


def _load_promoted_features_from_yaml() -> list[str]:
    """Load promoted CTF feature names from feature_selection.yaml.

    Returns the ctf_promoted.features list written by refresh_ctf_promoted.py.
    Falls back to an empty list with a warning if section is missing.

    Returns
    -------
    List of promoted CTF feature column names (e.g. 'rsi_14_7d_slope').
    """
    if yaml is None:
        raise ImportError("PyYAML is required.")

    yaml_path = project_root() / _FEATURE_SELECTION_PATH_REL
    if not yaml_path.exists():
        raise FileNotFoundError(f"feature_selection.yaml not found: {yaml_path}")

    with open(yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not data or "ctf_promoted" not in data:
        logger.warning(
            "ctf_promoted section missing from feature_selection.yaml. "
            "Run refresh_ctf_promoted.py first. Returning empty feature list."
        )
        return []

    features = data["ctf_promoted"].get("features", [])
    names = [f["name"] for f in features if isinstance(f, dict) and "name" in f]

    logger.info(
        "Loaded %d promoted CTF features from feature_selection.yaml", len(names)
    )
    return names


# =============================================================================
# CTF data loading
# =============================================================================


def _get_ctf_asset_ids(engine: Engine, base_tf: str, venue_id: int) -> list[int]:
    """Return asset IDs that have CTF data for the given base_tf."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT DISTINCT id
                FROM public.ctf
                WHERE base_tf = :base_tf
                  AND venue_id = :venue_id
                  AND alignment_source = :alignment_source
                ORDER BY id
                """
            ),
            {
                "base_tf": base_tf,
                "venue_id": venue_id,
                "alignment_source": _DEFAULT_ALIGNMENT_SOURCE,
            },
        )
        return [int(row[0]) for row in result]


def _load_multi_asset_pivot(
    engine: Engine,
    asset_ids: list[int],
    base_tf: str,
    promoted_features: list[str],
    venue_id: int,
) -> dict[str, pd.DataFrame]:
    """Load CTF features for all assets and build per-feature pivots.

    For each promoted feature name, returns a DataFrame with:
      - rows = timestamps (UTC)
      - columns = asset_id (integer)

    Only assets with non-null values for that feature are included.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    asset_ids:
        List of asset IDs to load.
    base_tf:
        Base timeframe string (e.g. '1D').
    promoted_features:
        List of promoted CTF feature column names.
    venue_id:
        Venue ID filter (default 1 = CMC_AGG).

    Returns
    -------
    Dict mapping feature_name -> pd.DataFrame (ts x asset_id).
    """
    logger.info(
        "Loading CTF data for %d assets, base_tf=%s, venue_id=%d",
        len(asset_ids),
        base_tf,
        venue_id,
    )

    # Collect per-asset DataFrames
    asset_dfs: dict[int, pd.DataFrame] = {}

    with engine.connect() as conn:
        for asset_id in asset_ids:
            df = load_ctf_features(
                conn,
                asset_id=asset_id,
                base_tf=base_tf,
                train_start=_FULL_HISTORY_START,
                train_end=_FULL_HISTORY_END,
                alignment_source=_DEFAULT_ALIGNMENT_SOURCE,
                venue_id=venue_id,
            )
            if df.empty:
                logger.debug(
                    "No CTF data for asset_id=%d, base_tf=%s", asset_id, base_tf
                )
                continue

            # Ensure UTC tz-aware index
            if not isinstance(df.index, pd.DatetimeIndex):
                logger.warning(
                    "Unexpected index type for asset_id=%d, skipping", asset_id
                )
                continue
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            else:
                df.index = df.index.tz_convert("UTC")

            # Filter to only promoted columns that exist in this asset's data
            available_promoted = [c for c in promoted_features if c in df.columns]
            if not available_promoted:
                logger.debug(
                    "No promoted columns found for asset_id=%d, base_tf=%s",
                    asset_id,
                    base_tf,
                )
                continue

            asset_dfs[asset_id] = df[available_promoted]
            logger.debug(
                "asset_id=%d: loaded %d rows, %d promoted columns",
                asset_id,
                len(df),
                len(available_promoted),
            )

    if not asset_dfs:
        logger.warning("No CTF data loaded for base_tf=%s", base_tf)
        return {}

    logger.info(
        "Loaded CTF data for %d/%d assets, base_tf=%s",
        len(asset_dfs),
        len(asset_ids),
        base_tf,
    )

    # Build per-feature pivot: ts x asset_id
    pivots: dict[str, pd.DataFrame] = {}
    for feat_name in promoted_features:
        feat_series: dict[int, pd.Series] = {}
        for asset_id, df in asset_dfs.items():
            if feat_name in df.columns:
                feat_series[asset_id] = df[feat_name]

        if len(feat_series) < 2:
            # Need at least 2 assets for cross-asset composites
            continue

        pivot = pd.DataFrame(feat_series)  # index=ts, columns=asset_id
        # Drop rows where all assets have NaN
        pivot = pivot.dropna(how="all")
        if pivot.empty:
            continue

        pivots[feat_name] = pivot

    logger.info(
        "Built pivots for %d/%d promoted features, base_tf=%s",
        len(pivots),
        len(promoted_features),
        base_tf,
    )
    return pivots


# =============================================================================
# Composite computation
# =============================================================================


def compute_sentiment_mean(
    pivots: dict[str, pd.DataFrame],
    min_assets: int,
    base_tf: str,
    venue_id: int,
) -> pd.DataFrame:
    """Compute cross-asset mean composite for each promoted feature.

    For each (ts, feature): mean of non-NaN asset values at that timestamp.
    Timestamps with fewer than min_assets non-NaN values are set to NaN.
    Uses vectorized operations across all features for performance.

    Parameters
    ----------
    pivots:
        Dict of feature_name -> pd.DataFrame (ts x asset_id).
    min_assets:
        Minimum number of assets with non-NaN value required per timestamp.
    base_tf:
        Base timeframe (stored in output rows).
    venue_id:
        Venue ID (stored in output rows).

    Returns
    -------
    pd.DataFrame with columns: ts, tf, venue_id, composite_name, method, value, n_assets.
    """
    all_dfs: list[pd.DataFrame] = []

    for feat_name, pivot in pivots.items():
        composite_name = f"sentiment_mean_{feat_name}"

        n_valid = pivot.notna().sum(axis=1)  # Series indexed by ts
        mean_val = pivot.mean(axis=1)  # cross-asset mean per ts (ignores NaN)

        # Filter to timestamps with sufficient assets
        mask = n_valid >= min_assets
        if not mask.any():
            continue

        ts_vals = pivot.index[mask]
        values = mean_val[mask].values
        n_assets_vals = n_valid[mask].values

        feat_df = pd.DataFrame(
            {
                "ts": ts_vals,
                "tf": base_tf,
                "venue_id": venue_id,
                "composite_name": composite_name,
                "method": "cross_asset_mean",
                "value": values.astype(float),
                "n_assets": n_assets_vals.astype(int),
            }
        )
        all_dfs.append(feat_df)

    if not all_dfs:
        logger.warning(
            "sentiment_mean: no rows produced (all below min_assets=%d)", min_assets
        )
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    logger.info(
        "Computed %d rows for sentiment_mean method=cross_asset_mean, base_tf=%s",
        len(result),
        base_tf,
    )
    return result


def compute_sentiment_pca(
    pivots: dict[str, pd.DataFrame],
    min_assets: int,
    base_tf: str,
    venue_id: int,
) -> pd.DataFrame:
    """Compute PCA first component composite for each promoted feature.

    For each feature: standardize the (ts x asset_id) pivot, fit PCA(n_components=1),
    apply sign correction to align the first component with the majority-sign of loadings.

    Timestamps with fewer than min_assets non-NaN values are excluded before PCA.

    Parameters
    ----------
    pivots:
        Dict of feature_name -> pd.DataFrame (ts x asset_id).
    min_assets:
        Minimum number of assets required at each timestamp.
    base_tf:
        Base timeframe.
    venue_id:
        Venue ID.

    Returns
    -------
    pd.DataFrame with columns: ts, tf, venue_id, composite_name, method, value, n_assets.
    """
    if not _SKLEARN_AVAILABLE:
        logger.warning(
            "sklearn not available, skipping sentiment_pca composite. "
            "Install scikit-learn: pip install scikit-learn"
        )
        return pd.DataFrame()

    rows = []
    for feat_name, pivot in pivots.items():
        composite_name = f"sentiment_pca_{feat_name}"

        # Only keep timestamps where at least min_assets assets have non-NaN values
        n_valid = pivot.notna().sum(axis=1)
        pivot_filtered = pivot[n_valid >= min_assets].copy()

        if len(pivot_filtered) < 10:
            logger.debug(
                "sentiment_pca: %s has only %d rows after filtering (min_assets=%d), skipping",
                feat_name,
                len(pivot_filtered),
                min_assets,
            )
            continue

        # Forward-fill then drop remaining NaN for PCA (need complete rows)
        pivot_filled = pivot_filtered.ffill().dropna(axis=0)
        if len(pivot_filled) < 5:
            logger.debug(
                "sentiment_pca: %s has only %d complete rows after ffill, skipping",
                feat_name,
                len(pivot_filled),
            )
            continue

        # Standardize and fit PCA
        scaler = StandardScaler()
        X = scaler.fit_transform(pivot_filled.values.astype(float))

        pca = PCA(n_components=1)
        scores = pca.fit_transform(X)[:, 0]

        # Sign correction: align with the dominant loading (largest absolute loading)
        loadings = pca.components_[0]
        dominant_sign = np.sign(loadings[np.abs(loadings).argmax()])
        if dominant_sign != 0:
            scores = scores * dominant_sign

        n_assets_per_ts = pivot_filled.notna().sum(axis=1).values

        for i, (ts, _) in enumerate(pivot_filled.iterrows()):
            rows.append(
                {
                    "ts": ts,
                    "tf": base_tf,
                    "venue_id": venue_id,
                    "composite_name": composite_name,
                    "method": "pca_1",
                    "value": float(scores[i]),
                    "n_assets": int(n_assets_per_ts[i]),
                }
            )

    if not rows:
        logger.warning("sentiment_pca: no rows produced")
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    logger.info(
        "Computed %d rows for sentiment_pca method=pca_1, base_tf=%s",
        len(result),
        base_tf,
    )
    return result


def compute_relative_value(
    pivots: dict[str, pd.DataFrame],
    min_assets: int,
    base_tf: str,
    venue_id: int,
) -> pd.DataFrame:
    """Compute cross-sectional z-score composite for each promoted feature.

    For each (ts, feature, asset): z-score relative to cross-section of all assets.
    Timestamps with fewer than min_assets non-NaN values are skipped.

    Uses vectorized operations. The composite_name encodes both feature and asset:
    ``relative_value_{feat_name}_{asset_id}`` to ensure unique PK entries.

    Parameters
    ----------
    pivots:
        Dict of feature_name -> pd.DataFrame (ts x asset_id).
    min_assets:
        Minimum number of assets required per timestamp.
    base_tf:
        Base timeframe.
    venue_id:
        Venue ID.

    Returns
    -------
    pd.DataFrame with columns: ts, tf, venue_id, composite_name, method, value, n_assets.
    """
    all_dfs: list[pd.DataFrame] = []

    for feat_name, pivot in pivots.items():
        n_valid = pivot.notna().sum(axis=1)
        cs_mean = pivot.mean(axis=1)
        cs_std = pivot.std(axis=1, ddof=0)  # population std for cross-sectional

        # Filter timestamps with sufficient assets and non-zero std
        mask = (n_valid >= min_assets) & (cs_std > 0) & cs_std.notna()
        if not mask.any():
            continue

        pivot_filtered = pivot.loc[mask]
        cs_mean_f = cs_mean.loc[mask]
        cs_std_f = cs_std.loc[mask]
        n_valid_f = n_valid.loc[mask]

        # Vectorized z-score: (value - cross_section_mean) / cross_section_std
        z_df = pivot_filtered.subtract(cs_mean_f, axis=0).divide(cs_std_f, axis=0)

        # Melt to long format for each asset
        for asset_col in z_df.columns:
            asset_series = z_df[asset_col].dropna()
            if asset_series.empty:
                continue

            composite_name = f"relative_value_{feat_name}_{asset_col}"
            ts_vals = asset_series.index
            n_assets_vals = n_valid_f.loc[ts_vals].values

            feat_asset_df = pd.DataFrame(
                {
                    "ts": ts_vals,
                    "tf": base_tf,
                    "venue_id": venue_id,
                    "composite_name": composite_name,
                    "method": "cs_zscore",
                    "value": asset_series.values.astype(float),
                    "n_assets": n_assets_vals.astype(int),
                }
            )
            all_dfs.append(feat_asset_df)

    if not all_dfs:
        logger.warning(
            "relative_value: no rows produced (all below min_assets=%d)", min_assets
        )
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    logger.info(
        "Computed %d rows for relative_value method=cs_zscore, base_tf=%s",
        len(result),
        base_tf,
    )
    return result


def compute_leader_follower(
    pivots: dict[str, pd.DataFrame],
    lags: list[int],
    min_assets: int,
    top_n_leaders: int,
    base_tf: str,
    venue_id: int,
) -> pd.DataFrame:
    """Compute lagged cross-correlation leader score for each asset.

    For each promoted feature, computes pairwise lagged correlations across all asset pairs.
    Assets that consistently lead others (best_lag < 0 = col_a leads col_b) receive a
    higher leader score.

    Leader score for asset A = average best_corr across all pairs where A is the leader
    (i.e., best_lag < 0 when A is col_a).

    Result stored as one row per (ts, composite_name) where ts is the LAST timestamp in the
    data window (since leader score is computed over the full history, not per-timestamp).
    The composite_name encodes both feature and asset: ``leader_score_{feat_name}_{asset_id}``.

    Parameters
    ----------
    pivots:
        Dict of feature_name -> pd.DataFrame (ts x asset_id).
    lags:
        List of lag values to evaluate (positive and negative).
    min_assets:
        Minimum number of assets required for pairwise computation.
    top_n_leaders:
        Number of top leaders to persist per feature (rest discarded).
    base_tf:
        Base timeframe.
    venue_id:
        Venue ID.

    Returns
    -------
    pd.DataFrame with columns: ts, tf, venue_id, composite_name, method, value, n_assets.
    """
    # Convert lags list to range-like for lead_lag_max_corr
    lag_range = range(min(lags) * -1, max(lags) + 1) if lags else range(-5, 6)

    rows = []
    for feat_name, pivot in pivots.items():
        asset_ids = list(pivot.columns)
        n_assets = len(asset_ids)

        if n_assets < min_assets:
            logger.debug(
                "leader_follower: %s has only %d assets < min_assets=%d, skipping",
                feat_name,
                n_assets,
                min_assets,
            )
            continue

        # Compute pairwise lagged correlations
        # leader_scores[asset_id] = list of best_corr values where this asset led
        leader_scores: dict[int, list[float]] = {aid: [] for aid in asset_ids}

        # Use a joint DataFrame for lead_lag_max_corr
        combined = pivot.dropna(how="all")
        if len(combined) < 20:
            logger.debug(
                "leader_follower: %s has only %d rows after dropna, skipping",
                feat_name,
                len(combined),
            )
            continue

        for i, asset_a in enumerate(asset_ids):
            for asset_j in range(i + 1, len(asset_ids)):
                asset_b = asset_ids[asset_j]

                # Get the overlapping non-NaN rows for this pair
                pair_df = combined[[asset_a, asset_b]].dropna()
                if len(pair_df) < 20:
                    continue

                # Rename columns for lead_lag_max_corr (expects string column names)
                col_a_name = f"a_{asset_a}"
                col_b_name = f"b_{asset_b}"
                pair_df = pair_df.copy()
                pair_df.columns = [col_a_name, col_b_name]  # type: ignore[assignment]

                result = lead_lag_max_corr(
                    pair_df,
                    col_a=col_a_name,
                    col_b=col_b_name,
                    lags=lag_range,
                )
                best_lag = result["best_lag"]
                best_corr = result["best_corr"]

                if np.isnan(best_corr):
                    continue

                # Convention: best_lag < 0 means col_a (asset_a) LEADS col_b (asset_b)
                if best_lag < 0:
                    leader_scores[asset_a].append(float(best_corr))
                elif best_lag > 0:
                    # col_b leads col_a
                    leader_scores[asset_b].append(float(best_corr))
                # best_lag == 0: contemporaneous, no clear leader

        # Compute average leader score for each asset
        scored_assets = [
            (asset_id, float(np.mean(scores)))
            for asset_id, scores in leader_scores.items()
            if scores
        ]

        if not scored_assets:
            logger.debug(
                "leader_follower: %s no leader pairs found, skipping", feat_name
            )
            continue

        # Sort by leader score descending, take top N
        scored_assets.sort(key=lambda x: x[1], reverse=True)
        top_leaders = scored_assets[:top_n_leaders]

        # Use the last timestamp as the "snapshot" timestamp
        last_ts = combined.index[-1]

        for asset_id, score in top_leaders:
            composite_name = f"leader_score_{feat_name}_{asset_id}"
            rows.append(
                {
                    "ts": last_ts,
                    "tf": base_tf,
                    "venue_id": venue_id,
                    "composite_name": composite_name,
                    "method": "lagged_corr",
                    "value": score,
                    "n_assets": n_assets,
                }
            )

    if not rows:
        logger.warning("leader_follower: no leader rows produced")
        return pd.DataFrame()

    result = pd.DataFrame(rows)
    logger.info(
        "Computed %d rows for leader_follower method=lagged_corr, base_tf=%s",
        len(result),
        base_tf,
    )
    return result


# =============================================================================
# Persistence
# =============================================================================


_PERSIST_CHUNK_SIZE = 50_000  # rows per temp-table upsert batch


def _persist_composites(engine: Engine, df: pd.DataFrame, dry_run: bool) -> int:
    """Persist composite rows to ctf_composites via chunked temp table + upsert.

    Processes in chunks of _PERSIST_CHUNK_SIZE rows to avoid large single transactions
    (following the project convention for large tables).

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with columns: ts, tf, venue_id, composite_name, method, value, n_assets.
    dry_run:
        If True, skip persistence and just log.

    Returns
    -------
    Number of rows upserted.
    """
    if df.empty:
        logger.info("No composite rows to persist.")
        return 0

    # Ensure ts is UTC tz-aware
    if "ts" in df.columns:
        df = df.copy()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)

    if dry_run:
        logger.info("[dry-run] Would upsert %d rows to ctf_composites", len(df))
        return 0

    total_rows = len(df)
    total_upserted = 0
    n_chunks = (total_rows + _PERSIST_CHUNK_SIZE - 1) // _PERSIST_CHUNK_SIZE

    logger.info(
        "Persisting %d rows to ctf_composites in %d chunks of %d",
        total_rows,
        n_chunks,
        _PERSIST_CHUNK_SIZE,
    )

    for chunk_idx in range(n_chunks):
        start = chunk_idx * _PERSIST_CHUNK_SIZE
        end = min(start + _PERSIST_CHUNK_SIZE, total_rows)
        chunk = df.iloc[start:end].copy()

        # Write chunk to temp table then upsert
        chunk.to_sql(
            "_tmp_ctf_composites",
            engine,
            schema="public",
            if_exists="replace",
            index=False,
            chunksize=10_000,
            method="multi",
        )

        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO public.ctf_composites
                        (ts, tf, venue_id, composite_name, method, value, n_assets)
                    SELECT ts, tf, venue_id::smallint, composite_name, method, value, n_assets
                    FROM public._tmp_ctf_composites
                    ON CONFLICT (ts, tf, venue_id, composite_name, method) DO UPDATE SET
                        value      = EXCLUDED.value,
                        n_assets   = EXCLUDED.n_assets,
                        computed_at = now()
                    """
                )
            )
            conn.execute(text("DROP TABLE IF EXISTS public._tmp_ctf_composites"))

        total_upserted += end - start
        logger.info(
            "Chunk %d/%d persisted (%d/%d rows)",
            chunk_idx + 1,
            n_chunks,
            total_upserted,
            total_rows,
        )

    logger.info("Upserted %d rows to ctf_composites", total_upserted)
    return total_upserted


def _materialize_to_features(
    engine: Engine,
    df: pd.DataFrame,
    composite_type: str,
    base_tf: str,
    dry_run: bool,
) -> int:
    """Materialize composite values to features table via UPDATE (if column exists).

    Only materializes if the composite column exists in the features table.
    If column is missing, logs a warning and skips (no error).

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        Composite rows (from ctf_composites, wide-format after pivot).
    composite_type:
        Composite type name (e.g. 'sentiment_mean').
    base_tf:
        Base timeframe string.
    dry_run:
        If True, skip actual write.

    Returns
    -------
    Number of rows updated.
    """
    if df.empty:
        return 0

    # Check which composite columns exist in features
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'features'"
            )
        )
        existing_cols = {row[0] for row in result}

    # Find composite columns that exist in features table
    composite_cols = [
        c
        for c in df.columns
        if c not in ("ts", "tf", "venue_id", "alignment_source", "id")
        and c in existing_cols
    ]

    if not composite_cols:
        logger.warning(
            "[%s] No composite columns found in features table. "
            "Composites fully available in ctf_composites table.",
            composite_type,
        )
        return 0

    if dry_run:
        logger.info(
            "[dry-run] Would UPDATE features for %d composite columns, %d rows",
            len(composite_cols),
            len(df),
        )
        return 0

    set_clauses = ", ".join(f"{col} = :{col}" for col in composite_cols)
    sql = text(
        f"""
        UPDATE public.features
        SET {set_clauses}
        WHERE id = :id
          AND ts = :ts
          AND tf = :tf
          AND venue_id = :venue_id
          AND alignment_source = :alignment_source
        """
    )

    rows = df[
        ["id", "ts", "tf", "venue_id", "alignment_source"] + composite_cols
    ].to_dict("records")

    total = 0
    _BATCH_SIZE = 5000
    with engine.begin() as conn:
        for i in range(0, len(rows), _BATCH_SIZE):
            batch = rows[i : i + _BATCH_SIZE]
            result = conn.execute(sql, batch)
            total += result.rowcount

    logger.info(
        "[%s] Updated %d features rows with %d composite columns",
        composite_type,
        total,
        len(composite_cols),
    )
    return total


# =============================================================================
# Main orchestrator
# =============================================================================


def run_composites(
    engine: Engine,
    config: dict,
    promoted_features: list[str],
    base_tf: str,
    composite_filter: Optional[str],
    dry_run: bool,
) -> dict[str, int]:
    """Run all composite computations for a single base_tf.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    config:
        Loaded ctf_composites_config.yaml dict.
    promoted_features:
        List of promoted CTF feature names.
    base_tf:
        Base timeframe to process.
    composite_filter:
        If set, only run this single composite type.
    dry_run:
        If True, skip persistence writes.

    Returns
    -------
    Dict mapping composite_type -> rows_written.
    """
    venue_id = int(config.get("venue_id", _DEFAULT_VENUE_ID))
    composites_cfg = config.get("composites", {})
    materialize_list = config.get("materialize_to_features", [])

    if not promoted_features:
        logger.error("No promoted features loaded. Run refresh_ctf_promoted.py first.")
        return {}

    # Load CTF data for all assets
    asset_ids = _get_ctf_asset_ids(engine, base_tf=base_tf, venue_id=venue_id)
    if not asset_ids:
        logger.warning(
            "No assets with CTF data for base_tf=%s, venue_id=%d", base_tf, venue_id
        )
        return {}

    logger.info(
        "Found %d assets with CTF data for base_tf=%s",
        len(asset_ids),
        base_tf,
    )

    # Build multi-asset pivots (expensive: loads all CTF data)
    pivots = _load_multi_asset_pivot(
        engine,
        asset_ids=asset_ids,
        base_tf=base_tf,
        promoted_features=promoted_features,
        venue_id=venue_id,
    )

    if not pivots:
        logger.warning("No pivots built for base_tf=%s", base_tf)
        return {}

    results: dict[str, int] = {}
    all_composite_dfs: list[pd.DataFrame] = []

    # --- sentiment_mean ---
    if composite_filter in (None, "sentiment_mean"):
        sm_cfg = composites_cfg.get("sentiment_mean", {})
        min_assets = int(sm_cfg.get("min_assets", 3))
        df_sm = compute_sentiment_mean(
            pivots, min_assets=min_assets, base_tf=base_tf, venue_id=venue_id
        )
        if not df_sm.empty:
            all_composite_dfs.append(df_sm)
            results["sentiment_mean"] = len(df_sm)
            logger.info(
                "sentiment_mean: %d rows computed for base_tf=%s",
                len(df_sm),
                base_tf,
            )

    # --- sentiment_pca ---
    if composite_filter in (None, "sentiment_pca"):
        sp_cfg = composites_cfg.get("sentiment_pca", {})
        min_assets = int(sp_cfg.get("min_assets", 5))
        df_sp = compute_sentiment_pca(
            pivots, min_assets=min_assets, base_tf=base_tf, venue_id=venue_id
        )
        if not df_sp.empty:
            all_composite_dfs.append(df_sp)
            results["sentiment_pca"] = len(df_sp)
            logger.info(
                "sentiment_pca: %d rows computed for base_tf=%s",
                len(df_sp),
                base_tf,
            )

    # --- relative_value ---
    if composite_filter in (None, "relative_value"):
        rv_cfg = composites_cfg.get("relative_value", {})
        min_assets = int(rv_cfg.get("min_assets", 3))
        df_rv = compute_relative_value(
            pivots, min_assets=min_assets, base_tf=base_tf, venue_id=venue_id
        )
        if not df_rv.empty:
            all_composite_dfs.append(df_rv)
            results["relative_value"] = len(df_rv)
            logger.info(
                "relative_value: %d rows computed for base_tf=%s",
                len(df_rv),
                base_tf,
            )

    # --- leader_follower ---
    if composite_filter in (None, "leader_follower"):
        lf_cfg = composites_cfg.get("leader_follower", {})
        lags = list(lf_cfg.get("lags", [1, 3, 5]))
        min_assets = int(lf_cfg.get("min_assets", 3))
        top_n = int(lf_cfg.get("top_n_leaders", 10))
        df_lf = compute_leader_follower(
            pivots,
            lags=lags,
            min_assets=min_assets,
            top_n_leaders=top_n,
            base_tf=base_tf,
            venue_id=venue_id,
        )
        if not df_lf.empty:
            all_composite_dfs.append(df_lf)
            results["leader_follower"] = len(df_lf)
            logger.info(
                "leader_follower: %d rows computed for base_tf=%s",
                len(df_lf),
                base_tf,
            )

    # Persist all composites together
    if all_composite_dfs:
        combined_df = pd.concat(all_composite_dfs, ignore_index=True)
        _persist_composites(engine, combined_df, dry_run=dry_run)
    else:
        logger.warning("No composite rows produced for base_tf=%s", base_tf)

    # Materialize to features (if configured)
    if (
        not dry_run
        and "sentiment_mean" in materialize_list
        and "sentiment_mean" in results
    ):
        # Materialization requires composite columns to exist in features table.
        # Since these are composite aggregates (not per-asset), they don't map
        # directly to features rows (which are per-asset). Log and skip.
        logger.info(
            "Skipping features materialization: composite aggregates (cross-asset means) "
            "do not map to per-asset features rows. Composites fully available in "
            "ctf_composites table."
        )

    return results


# =============================================================================
# CLI entry point
# =============================================================================


def main() -> int:
    """Main entry point for refresh_ctf_composites.

    Returns
    -------
    Exit code (0 = success, 1 = error).
    """
    parser = argparse.ArgumentParser(
        description="Compute and persist CTF cross-asset composites"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute composites but do not write to DB",
    )
    parser.add_argument(
        "--composite",
        type=str,
        choices=[
            "sentiment_mean",
            "sentiment_pca",
            "relative_value",
            "leader_follower",
        ],
        help="Run only a single composite type",
    )
    parser.add_argument(
        "--base-tf",
        type=str,
        default=None,
        help="Override base_tf (default: from config, typically '1D')",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    t0 = time.time()
    logger.info("refresh_ctf_composites starting (dry_run=%s)", args.dry_run)

    # Load config
    try:
        config = _load_config()
    except Exception as exc:
        logger.error("Failed to load config: %s", exc)
        return 1

    # Load promoted features from YAML
    try:
        promoted_features = _load_promoted_features_from_yaml()
    except Exception as exc:
        logger.error("Failed to load promoted features: %s", exc)
        return 1

    if not promoted_features:
        logger.error(
            "No promoted features found. Run refresh_ctf_promoted.py first to "
            "populate configs/feature_selection.yaml ctf_promoted section."
        )
        return 1

    # Determine base_tfs to process
    if args.base_tf:
        base_tfs = [args.base_tf]
    else:
        base_tfs = config.get("base_tfs", ["1D"])

    # Create engine
    engine = create_engine(TARGET_DB_URL, poolclass=NullPool)

    all_results: dict[str, dict[str, int]] = {}

    for base_tf in base_tfs:
        logger.info("=" * 60)
        logger.info("Processing base_tf=%s", base_tf)
        logger.info("=" * 60)

        try:
            tf_results = run_composites(
                engine=engine,
                config=config,
                promoted_features=promoted_features,
                base_tf=base_tf,
                composite_filter=args.composite,
                dry_run=args.dry_run,
            )
            all_results[base_tf] = tf_results
        except Exception as exc:
            logger.error("Error processing base_tf=%s: %s", base_tf, exc, exc_info=True)
            return 1

    # Summary
    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("refresh_ctf_composites complete in %.1fs", elapsed)
    for base_tf, tf_results in all_results.items():
        for composite_type, n_rows in tf_results.items():
            logger.info(
                "  base_tf=%s  %-20s  %d rows",
                base_tf,
                composite_type,
                n_rows,
            )
    logger.info("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
