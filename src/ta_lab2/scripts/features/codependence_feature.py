"""
codependence_feature.py - Pairwise codependence computation + DB writer.

Standalone script (NOT a BaseFeature subclass) that computes pairwise
codependence metrics (Pearson correlation, distance correlation, mutual
information, variation of information) for all asset pairs at a given
timeframe. Results are written to cmc_codependence.

Pattern follows refresh_regimes.py: load data, compute, write.
Historical snapshots are preserved via computed_at in the PK.

Usage:
    python -m ta_lab2.scripts.features.codependence_feature --ids 1,52,1027 --tf 1D
    python -m ta_lab2.scripts.features.codependence_feature --all --tf 1D --window 252
    python -m ta_lab2.scripts.features.codependence_feature --all --tf 1D --dry-run
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from itertools import combinations

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.features.microstructure import (
    distance_correlation,
    pairwise_mi,
    quantile_encode,
    variation_of_information,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_return_series(
    engine: Engine,
    ids: list[int],
    tf: str,
    window_bars: int,
) -> dict[int, np.ndarray]:
    """Load log-return series for each asset from returns_bars_multi_tf_u.

    Parameters
    ----------
    engine : Engine
        SQLAlchemy engine connected to PostgreSQL.
    ids : list[int]
        Asset IDs to load.
    tf : str
        Timeframe code (e.g. '1D').
    window_bars : int
        Number of most recent bars to load per asset.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping of asset id -> numpy array of ret_log values (chronological).
        Assets with fewer than window_bars * 0.5 non-NULL return bars are
        excluded.
    """
    min_obs = int(window_bars * 0.5)
    query = text("""
        SELECT id, "timestamp" AS ts, ret_log
        FROM public.returns_bars_multi_tf_u
        WHERE id = ANY(:ids)
          AND tf = :tf
          AND roll = FALSE
        ORDER BY id, "timestamp" DESC
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {"ids": ids, "tf": tf})
        rows = result.fetchall()

    if not rows:
        logger.warning("load_return_series: no rows returned for ids=%s tf=%s", ids, tf)
        return {}

    df = pd.DataFrame(rows, columns=["id", "ts", "ret_log"])

    series_dict: dict[int, np.ndarray] = {}
    for asset_id, group in df.groupby("id"):
        # Take most recent window_bars rows (already DESC sorted)
        subset = group.head(window_bars)
        vals = subset["ret_log"].values.astype(np.float64)

        # Count non-NaN observations
        n_valid = int(np.sum(~np.isnan(vals)))
        if n_valid < min_obs:
            logger.debug(
                "load_return_series: skipping id=%s, only %d/%d valid bars",
                asset_id,
                n_valid,
                window_bars,
            )
            continue

        # Reverse to chronological order (was DESC)
        series_dict[int(asset_id)] = vals[::-1].copy()

    logger.info(
        "load_return_series: loaded %d/%d assets (tf=%s, window=%d)",
        len(series_dict),
        len(ids),
        tf,
        window_bars,
    )
    return series_dict


# ---------------------------------------------------------------------------
# Pair generation
# ---------------------------------------------------------------------------


def generate_pairs(ids: list[int]) -> list[tuple[int, int]]:
    """Generate all unique pairs (id_a, id_b) where id_a < id_b.

    Parameters
    ----------
    ids : list[int]
        Asset IDs.

    Returns
    -------
    list[tuple[int, int]]
        Sorted list of (id_a, id_b) pairs.
    """
    sorted_ids = sorted(ids)
    return list(combinations(sorted_ids, 2))


# ---------------------------------------------------------------------------
# Codependence computation
# ---------------------------------------------------------------------------


def compute_codependence(x: np.ndarray, y: np.ndarray) -> dict:
    """Compute all codependence metrics between two return series.

    Aligns x and y to common non-NaN indices before computing metrics.

    Parameters
    ----------
    x : np.ndarray
        1-D return series for asset A.
    y : np.ndarray
        1-D return series for asset B.

    Returns
    -------
    dict
        Keys: pearson_corr, distance_corr, mutual_info, variation_of_info,
        n_obs. All values are float or NaN if insufficient overlap.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)

    # Align to shortest
    min_len = min(len(x), len(y))
    x = x[-min_len:]
    y = y[-min_len:]

    # Common non-NaN mask
    mask = ~(np.isnan(x) | np.isnan(y))
    n_obs = int(mask.sum())

    if n_obs < 30:
        return {
            "pearson_corr": np.nan,
            "distance_corr": np.nan,
            "mutual_info": np.nan,
            "variation_of_info": np.nan,
            "n_obs": n_obs,
        }

    x_clean = x[mask]
    y_clean = y[mask]

    # 1. Pearson correlation
    corr_matrix = np.corrcoef(x_clean, y_clean)
    pearson = float(corr_matrix[0, 1])

    # 2. Distance correlation (from microstructure library)
    dcorr = distance_correlation(x_clean, y_clean)

    # 3. Mutual information (continuous, k-NN estimator)
    mi = pairwise_mi(x_clean, y_clean)

    # 4. Variation of information (requires discrete encoding)
    x_enc = quantile_encode(x_clean, n_bins=10)
    y_enc = quantile_encode(y_clean, n_bins=10)
    vi = variation_of_information(x_enc, y_enc)

    return {
        "pearson_corr": pearson,
        "distance_corr": dcorr,
        "mutual_info": mi,
        "variation_of_info": vi,
        "n_obs": n_obs,
    }


# ---------------------------------------------------------------------------
# Main computation loop
# ---------------------------------------------------------------------------


def refresh_codependence(
    engine: Engine,
    ids: list[int],
    tf: str = "1D",
    window_bars: int = 252,
    dry_run: bool = False,
) -> int:
    """Compute pairwise codependence for all asset pairs and write to DB.

    Parameters
    ----------
    engine : Engine
        SQLAlchemy engine connected to PostgreSQL.
    ids : list[int]
        Asset IDs to process.
    tf : str
        Timeframe code (e.g. '1D').
    window_bars : int
        Number of bars for the rolling window.
    dry_run : bool
        If True, compute but do not write to DB.

    Returns
    -------
    int
        Number of rows written (or would be written in dry-run mode).
    """
    # 1. Load return series
    series = load_return_series(engine, ids, tf, window_bars)
    available_ids = sorted(series.keys())

    if len(available_ids) < 2:
        logger.warning(
            "refresh_codependence: fewer than 2 assets with data, nothing to compute"
        )
        return 0

    # 2. Generate pairs from assets that have data
    pairs = generate_pairs(available_ids)
    n_pairs = len(pairs)
    logger.info(
        "refresh_codependence: %d assets -> %d pairs to compute (tf=%s, window=%d)",
        len(available_ids),
        n_pairs,
        tf,
        window_bars,
    )

    # 3. Single computed_at for the entire batch
    computed_at = datetime.now(timezone.utc)

    # 4. Process pairs SEQUENTIALLY (avoid OOM from distance matrices)
    results: list[dict] = []
    for i, (id_a, id_b) in enumerate(pairs):
        metrics = compute_codependence(series[id_a], series[id_b])

        results.append(
            {
                "id_a": id_a,
                "id_b": id_b,
                "tf": tf,
                "window_bars": window_bars,
                "computed_at": computed_at,
                "pearson_corr": metrics["pearson_corr"],
                "distance_corr": metrics["distance_corr"],
                "mutual_info": metrics["mutual_info"],
                "variation_of_info": metrics["variation_of_info"],
                "n_obs": metrics["n_obs"],
            }
        )

        if (i + 1) % 100 == 0 or (i + 1) == n_pairs:
            logger.info(
                "  progress: %d/%d pairs (%.1f%%)",
                i + 1,
                n_pairs,
                100.0 * (i + 1) / n_pairs,
            )

    # 5. Build DataFrame
    df = pd.DataFrame(results)
    n_rows = len(df)

    if n_rows == 0:
        logger.warning("refresh_codependence: no results to write")
        return 0

    # Summary stats
    n_valid = int(df["pearson_corr"].notna().sum())
    n_nan = n_rows - n_valid
    logger.info(
        "refresh_codependence: %d rows computed (%d valid, %d NaN/insufficient)",
        n_rows,
        n_valid,
        n_nan,
    )

    # 6. Write to DB (append mode - preserves history via computed_at in PK)
    if dry_run:
        logger.info("DRY RUN: would write %d rows to cmc_codependence", n_rows)
    else:
        df.to_sql(
            "cmc_codependence",
            engine,
            schema="public",
            if_exists="append",
            index=False,
            method="multi",
            chunksize=5000,
        )
        logger.info("refresh_codependence: wrote %d rows to cmc_codependence", n_rows)

    return n_rows


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _get_all_asset_ids(engine: Engine) -> list[int]:
    """Return asset IDs with pipeline_tier = 1 (full pipeline)."""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                "SELECT DISTINCT id FROM public.dim_assets "
                "WHERE pipeline_tier = 1 ORDER BY id"
            )
        )
        return [row[0] for row in result]


# ---------------------------------------------------------------------------
# Main / CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for codependence feature computation.

    Example usage:
        python -m ta_lab2.scripts.features.codependence_feature --ids 1,52,1027 --tf 1D
        python -m ta_lab2.scripts.features.codependence_feature --all --tf 1D --window 252
        python -m ta_lab2.scripts.features.codependence_feature --all --dry-run
    """
    parser = argparse.ArgumentParser(
        description=(
            "Compute pairwise codependence metrics (Pearson, distance correlation, "
            "mutual information, variation of information) and write to cmc_codependence."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    id_group = parser.add_mutually_exclusive_group(required=True)
    id_group.add_argument(
        "--ids",
        type=str,
        metavar="ID[,ID...]",
        help="Comma-separated asset IDs to process (e.g. '1,52,1027').",
    )
    id_group.add_argument(
        "--all",
        action="store_true",
        help="Process all active asset IDs from dim_assets.",
    )

    parser.add_argument(
        "--tf",
        type=str,
        default="1D",
        help="Timeframe code for returns (e.g. '1D', '7D').",
    )
    parser.add_argument(
        "--window",
        type=int,
        default=252,
        metavar="N",
        help="Number of bars for the rolling computation window.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute codependence but do not write to DB.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity level.",
    )
    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        metavar="URL",
        help="PostgreSQL connection URL. Defaults to TARGET_DB_URL env var.",
    )

    args = parser.parse_args(argv)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )

    # ------------------------------------------------------------------
    # DB connection
    # ------------------------------------------------------------------
    db_url = args.db_url or os.environ.get("TARGET_DB_URL")
    if not db_url:
        logger.error("No DB URL provided. Set TARGET_DB_URL or pass --db-url.")
        return 1

    engine = create_engine(db_url)

    # ------------------------------------------------------------------
    # Resolve asset IDs
    # ------------------------------------------------------------------
    if args.ids:
        asset_ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
    else:
        logger.info("Querying all active asset IDs...")
        asset_ids = _get_all_asset_ids(engine)

    logger.info("Processing %d assets: %s", len(asset_ids), asset_ids[:10])

    # ------------------------------------------------------------------
    # Run computation
    # ------------------------------------------------------------------
    t0 = time.perf_counter()

    try:
        n_rows = refresh_codependence(
            engine,
            ids=asset_ids,
            tf=args.tf,
            window_bars=args.window,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        logger.error("Codependence refresh FAILED: %s", exc, exc_info=True)
        return 1

    elapsed = time.perf_counter() - t0

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    mode_str = "[DRY RUN] " if args.dry_run else ""
    n_assets = len(asset_ids)
    n_possible_pairs = n_assets * (n_assets - 1) // 2

    print(
        f"\n{mode_str}Codependence refresh complete in {elapsed:.1f}s\n"
        f"  Assets requested  : {n_assets}\n"
        f"  Possible pairs    : {n_possible_pairs}\n"
        f"  Rows written      : {n_rows}\n"
        f"  Timeframe         : {args.tf}\n"
        f"  Window bars       : {args.window}\n"
    )

    return 0


if __name__ == "__main__":
    sys.exit(main())
