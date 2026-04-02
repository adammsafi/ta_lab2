"""
Lead-lag IC matrix for CTF features across all tier-1 asset pairs.

Tests whether Asset A's CTF features at time t predict Asset B's forward returns
at t+horizon across all (asset_a, asset_b) pairs for horizons [1, 3, 5] bars.

Applies Benjamini-Hochberg FDR correction across all computed p-values and
persists results to the lead_lag_ic table. Generates a CSV report of significant
lead-lag pairs sorted by |IC|.

Usage:
    python -m ta_lab2.scripts.analysis.run_ctf_lead_lag_ic --dry-run
    python -m ta_lab2.scripts.analysis.run_ctf_lead_lag_ic
    python -m ta_lab2.scripts.analysis.run_ctf_lead_lag_ic --base-tf 1D --horizons 1,3,5
    python -m ta_lab2.scripts.analysis.run_ctf_lead_lag_ic --workers 4
"""

from __future__ import annotations

import argparse
import logging
import math
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from statsmodels.stats.multitest import multipletests

from ta_lab2.features.cross_timeframe import load_ctf_features
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum overlapping observations to compute IC for a (pair, feature, horizon)
MIN_OBS = 30

# Default tier-1 asset IDs (BTC, ETH, SOL, XRP, BNB, LINK, HYPE)
# If the DB has no config, fall back to these 7 CMC-tracked assets
_TIER1_FALLBACK_IDS = [1, 1027, 5426, 52, 1839, 1975, 32196]


# ---------------------------------------------------------------------------
# Picklable worker task (frozen dataclass -- MANDATORY for Windows spawn)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeadLagWorkerTask:
    """
    Task for a single lead-lag IC worker process.

    Frozen dataclass with only picklable types (no engine/connection objects).
    Each worker creates its own NullPool engine from db_url.
    """

    asset_a_id: int
    asset_b_id: int
    base_tf: str
    horizons: tuple  # tuple[int, ...] for pickling
    db_url: str
    venue_id: int = 1


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------


def _to_utc(val) -> pd.Timestamp:
    """Convert a DB-returned timestamp to tz-aware UTC pd.Timestamp."""
    ts = pd.Timestamp(val)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _to_python(v):
    """
    Normalize a value for SQL binding.

    - numpy scalars -> Python float/int via .item()
    - pd.Timestamp -> Python datetime
    - NaN float -> None (SQL NULL)
    - Everything else: unchanged
    """
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    try:
        if math.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


def _load_tier1_assets(engine, base_tf: str, venue_id: int = 1) -> list[int]:
    """
    Load tier-1 asset IDs: assets that have CTF data for the given base_tf.

    Falls back to _TIER1_FALLBACK_IDS if no data found.
    """
    with engine.connect() as conn:
        sql = text(
            """
            SELECT DISTINCT id AS asset_id
            FROM public.ctf
            WHERE base_tf = :base_tf
              AND venue_id = :venue_id
              AND alignment_source = 'multi_tf'
            ORDER BY id
            """
        )
        df = pd.read_sql(sql, conn, params={"base_tf": base_tf, "venue_id": venue_id})

    if df.empty:
        logger.warning(
            "No CTF data for base_tf=%s venue_id=%d — using fallback tier-1 IDs",
            base_tf,
            venue_id,
        )
        return _TIER1_FALLBACK_IDS

    asset_ids = df["asset_id"].tolist()
    logger.info(
        "Discovered %d assets with CTF data for base_tf=%s venue_id=%d: %s",
        len(asset_ids),
        base_tf,
        venue_id,
        asset_ids,
    )
    return asset_ids


def _load_promoted_features(engine) -> list[str]:
    """
    Load promoted CTF feature names from ic_results (cross-asset median IC > 0.02).

    Uses PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) as cross-asset median.
    Falls back to all CTF-pattern features if no promoted features found.
    """
    ctf_suffixes = (
        "_slope",
        "_divergence",
        "_agreement",
        "_crossover",
        "_ref_value",
        "_base_value",
    )
    conditions = " OR ".join(f"feature LIKE '%{s}'" for s in ctf_suffixes)

    sql = text(
        f"""
        SELECT feature,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) AS median_abs_ic,
               COUNT(DISTINCT asset_id) AS n_assets
        FROM public.ic_results
        WHERE horizon = 1
          AND return_type = 'arith'
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
          AND ({conditions})
        GROUP BY feature
        HAVING PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > 0.02
        ORDER BY median_abs_ic DESC
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        logger.warning(
            "No promoted CTF features found (median IC > 0.02) — "
            "check ic_results table for CTF features"
        )
        return []

    feature_names = df["feature"].tolist()
    logger.info(
        "Loaded %d promoted CTF features (median IC > 0.02)", len(feature_names)
    )
    return feature_names


def _load_ctf_for_asset(
    engine, asset_id: int, base_tf: str, venue_id: int = 1
) -> pd.DataFrame:
    """
    Load CTF features for a single asset, spanning its full CTF history.

    Returns a wide-format DataFrame indexed by UTC timestamps.
    Empty DataFrame if no data.
    """
    with engine.connect() as conn:
        # Get date range from ctf table
        sql = text(
            """
            SELECT MIN(ts) AS ts_min, MAX(ts) AS ts_max
            FROM public.ctf
            WHERE id = :asset_id
              AND base_tf = :base_tf
              AND venue_id = :venue_id
              AND alignment_source = 'multi_tf'
            """
        )
        result = conn.execute(
            sql, {"asset_id": asset_id, "base_tf": base_tf, "venue_id": venue_id}
        )
        row = result.fetchone()

        if row is None or row[0] is None:
            logger.debug(
                "No CTF rows for asset_id=%d base_tf=%s venue_id=%d",
                asset_id,
                base_tf,
                venue_id,
            )
            return pd.DataFrame()

        train_start = _to_utc(row[0])
        train_end = _to_utc(row[1])

        ctf_df = load_ctf_features(
            conn,
            asset_id,
            base_tf,
            train_start,
            train_end,
            alignment_source="multi_tf",
            venue_id=venue_id,
        )

    return ctf_df


def _load_forward_returns_for_asset(
    engine,
    asset_id: int,
    base_tf: str,
    horizons: list[int],
    venue_id: int = 1,
) -> dict[int, pd.Series]:
    """
    Load forward returns for each horizon from returns_bars_multi_tf_u.

    For each horizon h: ret at time t = close[t+h]/close[t] - 1.

    Returns dict {horizon: pd.Series indexed by UTC ts}.
    Uses close prices from features table to compute forward returns if
    returns_bars_multi_tf_u is empty for this asset/tf.
    """
    # Attempt to load close from features for forward return computation
    sql = text(
        """
        SELECT ts, close
        FROM public.features
        WHERE id = :asset_id
          AND tf = :base_tf
          AND venue_id = :venue_id
        ORDER BY ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={"asset_id": asset_id, "base_tf": base_tf, "venue_id": venue_id},
        )

    if df.empty:
        logger.debug(
            "No close prices for asset_id=%d base_tf=%s in features",
            asset_id,
            base_tf,
        )
        return {h: pd.Series(dtype=float) for h in horizons}

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    close = df["close"]

    result: dict[int, pd.Series] = {}
    for horizon in horizons:
        # Forward arithmetic return: close[t+h]/close[t] - 1 = shift(-h)
        fwd_ret = close.shift(-horizon) / close - 1.0
        fwd_ret.name = f"fwd_ret_h{horizon}"
        result[horizon] = fwd_ret

    return result


# ---------------------------------------------------------------------------
# IC computation for a single (asset_a, asset_b, feature, horizon) tuple
# ---------------------------------------------------------------------------


def _compute_lead_lag_ic(
    feature_series: pd.Series,
    fwd_return_series: pd.Series,
) -> dict:
    """
    Compute Spearman IC between feature_series (leader) and fwd_return_series (follower).

    Aligns on timestamp (inner join), drops NaN, skips if fewer than MIN_OBS.

    Returns dict with: ic, ic_p_value, n_obs (or NaN/None if insufficient data).
    """
    # Align on shared timestamps
    aligned = pd.concat(
        [feature_series.rename("feature"), fwd_return_series.rename("fwd_ret")],
        axis=1,
        join="inner",
    ).dropna()

    n_obs = len(aligned)
    if n_obs < MIN_OBS:
        return {"ic": np.nan, "ic_p_value": np.nan, "n_obs": n_obs}

    # Guard against constant series (would give undefined Spearman)
    if aligned["feature"].std() == 0 or aligned["fwd_ret"].std() == 0:
        return {"ic": np.nan, "ic_p_value": np.nan, "n_obs": n_obs}

    result = spearmanr(aligned["feature"].values, aligned["fwd_ret"].values)
    ic = float(result.statistic)
    p_value = float(result.pvalue)

    return {"ic": ic, "ic_p_value": p_value, "n_obs": n_obs}


# ---------------------------------------------------------------------------
# BH FDR correction
# ---------------------------------------------------------------------------


def _apply_bh_correction(ic_rows: list[dict]) -> list[dict]:
    """
    Apply Benjamini-Hochberg FDR correction to all IC p-values.

    Rows with ic_p_value = None/NaN are assigned ic_p_bh=None, is_significant=False.
    Correction is applied only to rows with a valid p-value.
    """
    if not ic_rows:
        return ic_rows

    # Identify rows with valid p-values
    valid_indices = [
        i
        for i, row in enumerate(ic_rows)
        if row.get("ic_p_value") is not None
        and not (isinstance(row["ic_p_value"], float) and math.isnan(row["ic_p_value"]))
    ]

    if not valid_indices:
        logger.warning("No valid p-values found — BH correction skipped")
        for row in ic_rows:
            row["ic_p_bh"] = None
            row["is_significant"] = False
        return ic_rows

    # Extract valid p-values
    pvals = [float(ic_rows[i]["ic_p_value"]) for i in valid_indices]

    # Apply BH FDR correction
    reject, p_corrected, _, _ = multipletests(pvals, alpha=0.05, method="fdr_bh")

    # Write corrected values back to the matching rows
    for j, i in enumerate(valid_indices):
        ic_rows[i]["ic_p_bh"] = float(p_corrected[j])
        ic_rows[i]["is_significant"] = bool(reject[j])

    # Fill in None for rows that had no valid p-value
    for i, row in enumerate(ic_rows):
        if i not in valid_indices:
            row["ic_p_bh"] = None
            row["is_significant"] = False

    n_sig = sum(row["is_significant"] for row in ic_rows)
    logger.info(
        "BH correction: %d significant pairs out of %d total (%.1f%%)",
        n_sig,
        len(ic_rows),
        100.0 * n_sig / len(ic_rows) if ic_rows else 0.0,
    )
    return ic_rows


# ---------------------------------------------------------------------------
# DB persistence (temp table + upsert)
# ---------------------------------------------------------------------------


def _persist_to_lead_lag_ic(engine, ic_rows: list[dict], base_tf: str) -> int:
    """
    Persist lead-lag IC results to lead_lag_ic using temp table + INSERT ON CONFLICT upsert.

    Returns number of rows upserted.
    """
    if not ic_rows:
        return 0

    # Build DataFrame for temp table
    rows_for_df = []
    for row in ic_rows:
        rows_for_df.append(
            {
                "asset_a_id": int(row["asset_a_id"]),
                "asset_b_id": int(row["asset_b_id"]),
                "feature": str(row["feature"]),
                "horizon": int(row["horizon"]),
                "tf": base_tf,
                "venue_id": int(row.get("venue_id", 1)),
                "ic": _to_python(row.get("ic")),
                "ic_p_value": _to_python(row.get("ic_p_value")),
                "ic_p_bh": _to_python(row.get("ic_p_bh")),
                "is_significant": bool(row.get("is_significant", False)),
                "n_obs": int(row["n_obs"]) if row.get("n_obs") is not None else None,
            }
        )

    df = pd.DataFrame(rows_for_df)

    # Write to temp table
    df.to_sql(
        "_tmp_lead_lag_ic",
        engine,
        schema="public",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=5000,
    )

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO public.lead_lag_ic
                    (asset_a_id, asset_b_id, feature, horizon, tf, venue_id,
                     ic, ic_p_value, ic_p_bh, is_significant, n_obs)
                SELECT asset_a_id, asset_b_id, feature, horizon, tf, venue_id,
                       ic, ic_p_value, ic_p_bh, is_significant, n_obs
                FROM public._tmp_lead_lag_ic
                ON CONFLICT (asset_a_id, asset_b_id, feature, horizon, tf, venue_id)
                DO UPDATE SET
                    ic             = EXCLUDED.ic,
                    ic_p_value     = EXCLUDED.ic_p_value,
                    ic_p_bh        = EXCLUDED.ic_p_bh,
                    is_significant = EXCLUDED.is_significant,
                    n_obs          = EXCLUDED.n_obs,
                    computed_at    = now()
                """
            )
        )
        conn.execute(text("DROP TABLE IF EXISTS public._tmp_lead_lag_ic"))

    logger.info("Persisted %d rows to lead_lag_ic", len(rows_for_df))
    return len(rows_for_df)


# ---------------------------------------------------------------------------
# CSV report generation
# ---------------------------------------------------------------------------


def _generate_csv_report(ic_rows: list[dict], report_path: Path) -> None:
    """
    Write a CSV report of all rows, sorted by significant pairs first then |IC|.

    Prints summary statistics to stdout.
    """
    if not ic_rows:
        logger.warning("No IC rows to write CSV report")
        return

    report_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(ic_rows)

    # Add absolute IC column for sorting
    df["abs_ic"] = df["ic"].apply(
        lambda x: abs(x)
        if x is not None and not (isinstance(x, float) and math.isnan(x))
        else 0.0
    )

    # Sort: significant first, then by |IC| descending
    df_sorted = df.sort_values(
        ["is_significant", "abs_ic"],
        ascending=[False, False],
    ).drop(columns=["abs_ic"])

    # Write to CSV
    df_sorted.to_csv(report_path, index=False)

    # Summary
    n_total = len(ic_rows)
    n_computed = sum(
        1
        for row in ic_rows
        if row.get("ic") is not None
        and not (isinstance(row.get("ic"), float) and math.isnan(row.get("ic")))
    )
    n_significant = sum(row.get("is_significant", False) for row in ic_rows)

    pct = 100.0 * n_significant / n_computed if n_computed > 0 else 0.0
    print(
        f"\nFound {n_significant} significant lead-lag pairs "
        f"out of {n_computed} computed ({pct:.1f}%)"
    )
    print(f"Total pairs (including skipped): {n_total}")
    print(f"CSV report written: {report_path}")

    # Print top-10 significant pairs
    significant_df = df_sorted[df_sorted["is_significant"] == True]  # noqa: E712
    if not significant_df.empty:
        print("\nTop 10 significant lead-lag pairs by |IC|:")
        top10 = significant_df.head(10)
        for _, row in top10.iterrows():
            print(
                f"  asset_a={row['asset_a_id']} -> asset_b={row['asset_b_id']} "
                f"feature={row['feature']} horizon={row['horizon']} "
                f"IC={row['ic']:.4f} p_bh={row['ic_p_bh']:.4f}"
            )


# ---------------------------------------------------------------------------
# Sequential computation loop (single-process, tractable for ~2,520 tasks)
# ---------------------------------------------------------------------------


def _run_sequential(
    asset_ids: list[int],
    promoted_features: list[str],
    horizons: list[int],
    base_tf: str,
    engine,
    venue_id: int = 1,
) -> list[dict]:
    """
    Run lead-lag IC computation sequentially for all (asset_a, asset_b, feature, horizon).

    Pre-loads all CTF data and forward returns into memory, then iterates over
    all pairs. Returns list of result dicts (one per pair x feature x horizon).
    """
    logger.info(
        "Pre-loading CTF features for %d assets (base_tf=%s)...",
        len(asset_ids),
        base_tf,
    )

    # Pre-load CTF features for all assets
    ctf_cache: dict[int, pd.DataFrame] = {}
    for asset_id in asset_ids:
        ctf_df = _load_ctf_for_asset(engine, asset_id, base_tf, venue_id)
        if not ctf_df.empty:
            # Filter to only promoted features that exist in this asset's CTF data
            available_cols = [c for c in promoted_features if c in ctf_df.columns]
            if available_cols:
                ctf_cache[asset_id] = ctf_df[available_cols]
                logger.debug(
                    "asset_id=%d: %d promoted features available",
                    asset_id,
                    len(available_cols),
                )
            else:
                logger.debug(
                    "asset_id=%d: no promoted features in CTF data — skipping",
                    asset_id,
                )
        else:
            logger.debug("asset_id=%d: empty CTF data — skipping", asset_id)

    logger.info(
        "Pre-loading forward returns for %d assets (horizons=%s)...",
        len(asset_ids),
        horizons,
    )

    # Pre-load forward returns for all assets
    fwd_cache: dict[int, dict[int, pd.Series]] = {}
    for asset_id in asset_ids:
        fwd_by_horizon = _load_forward_returns_for_asset(
            engine, asset_id, base_tf, horizons, venue_id
        )
        non_empty = {h: s for h, s in fwd_by_horizon.items() if not s.empty}
        if non_empty:
            fwd_cache[asset_id] = non_empty

    # Determine valid asset_a (has CTF data) and valid asset_b (has forward returns)
    valid_a = [aid for aid in asset_ids if aid in ctf_cache]
    valid_b = [aid for aid in asset_ids if aid in fwd_cache]

    # Count total tasks for progress reporting
    n_tasks_total = len(valid_a) * len(valid_b) * len(promoted_features) * len(horizons)
    logger.info(
        "Running %d x %d pairs x %d features x %d horizons = ~%d tasks",
        len(valid_a),
        len(valid_b),
        len(promoted_features),
        len(horizons),
        n_tasks_total,
    )

    all_results: list[dict] = []
    n_done = 0
    n_computed = 0
    n_skipped = 0
    t_start = time.time()

    for asset_a_id in valid_a:
        ctf_a = ctf_cache[asset_a_id]

        for asset_b_id in valid_b:
            if asset_a_id == asset_b_id:
                continue  # Skip self-prediction

            fwd_b = fwd_cache.get(asset_b_id, {})
            if not fwd_b:
                continue

            for feature in promoted_features:
                if feature not in ctf_a.columns:
                    continue  # Feature not available for this asset

                feature_series = ctf_a[feature].dropna()
                if len(feature_series) < MIN_OBS:
                    continue

                for horizon in horizons:
                    fwd_series = fwd_b.get(horizon)
                    if fwd_series is None or fwd_series.empty:
                        continue

                    n_done += 1
                    result = _compute_lead_lag_ic(feature_series, fwd_series)

                    if result["n_obs"] >= MIN_OBS and not (
                        isinstance(result["ic"], float) and math.isnan(result["ic"])
                    ):
                        n_computed += 1
                    else:
                        n_skipped += 1

                    all_results.append(
                        {
                            "asset_a_id": asset_a_id,
                            "asset_b_id": asset_b_id,
                            "feature": feature,
                            "horizon": horizon,
                            "venue_id": venue_id,
                            "ic": result["ic"],
                            "ic_p_value": result["ic_p_value"],
                            "n_obs": result["n_obs"],
                        }
                    )

                    if n_done % 500 == 0:
                        elapsed = time.time() - t_start
                        rate = n_done / elapsed if elapsed > 0 else 0
                        logger.info(
                            "Progress: %d/%d tasks done (%.0f/s), "
                            "computed=%d skipped=%d",
                            n_done,
                            n_tasks_total,
                            rate,
                            n_computed,
                            n_skipped,
                        )

    elapsed = time.time() - t_start
    logger.info(
        "Computation done: %d results in %.1fs (computed=%d, skipped=%d)",
        len(all_results),
        elapsed,
        n_computed,
        n_skipped,
    )
    return all_results


# ---------------------------------------------------------------------------
# Module-level worker function (used when --workers > 1)
# ---------------------------------------------------------------------------


def _lead_lag_worker(task: LeadLagWorkerTask) -> list[dict]:
    """
    Worker function for parallel lead-lag IC computation.

    Processes all (feature, horizon) combinations for one (asset_a, asset_b) pair.
    Called by multiprocessing.Pool.imap_unordered().
    Must be module-level for pickling to work on Windows (spawn start method).

    Creates its own NullPool engine to prevent connection pooling issues.
    Returns list of result dicts for this pair.
    """
    _logger = logging.getLogger(f"lead_lag_worker.{task.asset_a_id}.{task.asset_b_id}")
    engine = None
    try:
        engine = create_engine(task.db_url, poolclass=NullPool)
        horizons = list(task.horizons)

        # Load CTF features for asset_a
        ctf_a = _load_ctf_for_asset(
            engine, task.asset_a_id, task.base_tf, task.venue_id
        )
        if ctf_a.empty:
            return []

        # Load forward returns for asset_b
        fwd_b = _load_forward_returns_for_asset(
            engine, task.asset_b_id, task.base_tf, horizons, task.venue_id
        )

        results = []
        for feature in ctf_a.columns:
            feature_series = ctf_a[feature].dropna()
            if len(feature_series) < MIN_OBS:
                continue

            for horizon in horizons:
                fwd_series = fwd_b.get(horizon)
                if fwd_series is None or fwd_series.empty:
                    continue

                result = _compute_lead_lag_ic(feature_series, fwd_series)
                results.append(
                    {
                        "asset_a_id": task.asset_a_id,
                        "asset_b_id": task.asset_b_id,
                        "feature": feature,
                        "horizon": horizon,
                        "venue_id": task.venue_id,
                        "ic": result["ic"],
                        "ic_p_value": result["ic_p_value"],
                        "n_obs": result["n_obs"],
                    }
                )

        return results

    except Exception as exc:
        _logger.error(
            "Failed pair (%d, %d): %s",
            task.asset_a_id,
            task.asset_b_id,
            exc,
            exc_info=True,
        )
        return []
    finally:
        if engine is not None:
            engine.dispose()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="run_ctf_lead_lag_ic",
        description=(
            "Lead-lag IC matrix for CTF features across all tier-1 asset pairs.\n\n"
            "Tests whether Asset A's CTF features predict Asset B's forward returns "
            "at horizons [1, 3, 5]. Applies BH FDR correction and persists results "
            "to lead_lag_ic table + CSV report."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Show task count without computing IC.",
    )
    parser.add_argument(
        "--base-tf",
        type=str,
        default="1D",
        dest="base_tf",
        help="Base timeframe for CTF features (default: 1D).",
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default="1,3,5",
        help="Comma-separated forward return horizons in bars (default: 1,3,5).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default: 1 = sequential). "
        "Use maxtasksperchild=1 on Windows.",
    )
    parser.add_argument(
        "--venue-id",
        type=int,
        default=1,
        dest="venue_id",
        help="Venue ID for CTF data and forward returns (default: 1 = CMC_AGG).",
    )
    parser.add_argument(
        "--report-path",
        type=str,
        default="reports/ctf/lead_lag_ic_report.csv",
        dest="report_path",
        help="Output path for CSV report (default: reports/ctf/lead_lag_ic_report.csv).",
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

    sweep_start = time.time()

    # Parse horizons
    try:
        horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]
    except ValueError as e:
        logger.error("Invalid --horizons value: %s", e)
        return 1

    if not horizons:
        logger.error("No horizons specified — aborting")
        return 1

    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=NullPool)

    # Load tier-1 assets
    asset_ids = _load_tier1_assets(engine, args.base_tf, args.venue_id)
    if not asset_ids:
        logger.error("No tier-1 assets found — aborting")
        return 1

    # Load promoted CTF features
    promoted_features = _load_promoted_features(engine)
    if not promoted_features:
        logger.error(
            "No promoted CTF features found in ic_results. "
            "Run run_ctf_ic_sweep.py first."
        )
        return 1

    # Count expected tasks (excluding self-pairs)
    n_pairs = len(asset_ids) * (len(asset_ids) - 1)
    n_tasks = n_pairs * len(promoted_features) * len(horizons)

    print(
        f"\nLead-Lag IC Matrix Setup:"
        f"\n  Assets:            {len(asset_ids)} ({asset_ids})"
        f"\n  Asset pairs:       {n_pairs} (all-vs-all, excl. self)"
        f"\n  Promoted features: {len(promoted_features)}"
        f"\n  Horizons:          {horizons}"
        f"\n  Base TF:           {args.base_tf}"
        f"\n  Estimated tasks:   {n_tasks:,}"
        f"\n  Workers:           {args.workers}"
    )

    if args.dry_run:
        print("\n[DRY RUN] Would compute up to", n_tasks, "IC pairs. Exiting.")
        return 0

    # -------------------------------------------------------------------
    # Run IC computation
    # -------------------------------------------------------------------
    all_results: list[dict]

    if args.workers > 1:
        # Parallel path: one task per (asset_a, asset_b) pair
        # Build task list with promoted feature filter already embedded
        # (workers load CTF for their assets and filter to promoted_features)
        tasks = []
        for asset_a_id in asset_ids:
            for asset_b_id in asset_ids:
                if asset_a_id == asset_b_id:
                    continue
                tasks.append(
                    LeadLagWorkerTask(
                        asset_a_id=asset_a_id,
                        asset_b_id=asset_b_id,
                        base_tf=args.base_tf,
                        horizons=tuple(horizons),
                        db_url=db_url,
                        venue_id=args.venue_id,
                    )
                )

        logger.info(
            "Starting parallel lead-lag IC: %d pair tasks, %d workers",
            len(tasks),
            args.workers,
        )

        all_results = []
        n_done = 0
        with Pool(processes=args.workers, maxtasksperchild=1) as pool:
            for result_chunk in pool.imap_unordered(_lead_lag_worker, tasks):
                all_results.extend(result_chunk)
                n_done += 1
                if n_done % 50 == 0 or n_done == len(tasks):
                    logger.info(
                        "Parallel progress: %d/%d pairs done, %d results so far",
                        n_done,
                        len(tasks),
                        len(all_results),
                    )
    else:
        # Sequential path (default, tractable for ~7 tier-1 assets)
        all_results = _run_sequential(
            asset_ids,
            promoted_features,
            horizons,
            args.base_tf,
            engine,
            venue_id=args.venue_id,
        )

    if not all_results:
        logger.warning(
            "No IC results computed — check CTF data and forward returns availability"
        )
        return 0

    logger.info("Total IC results before BH correction: %d", len(all_results))

    # -------------------------------------------------------------------
    # Apply BH FDR correction across ALL p-values
    # -------------------------------------------------------------------
    all_results = _apply_bh_correction(all_results)

    # -------------------------------------------------------------------
    # Persist to lead_lag_ic
    # -------------------------------------------------------------------
    n_written = _persist_to_lead_lag_ic(engine, all_results, args.base_tf)

    # -------------------------------------------------------------------
    # Generate CSV report
    # -------------------------------------------------------------------
    report_path = Path(args.report_path)
    _generate_csv_report(all_results, report_path)

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    sweep_elapsed = time.time() - sweep_start
    minutes = int(sweep_elapsed // 60)
    seconds = int(sweep_elapsed % 60)

    n_significant = sum(row.get("is_significant", False) for row in all_results)
    n_computed = sum(
        1
        for row in all_results
        if row.get("ic") is not None
        and not (isinstance(row.get("ic"), float) and math.isnan(row.get("ic")))
    )

    print(
        f"\n{'=' * 70}\n"
        f"LEAD-LAG IC MATRIX COMPLETE\n"
        f"{'=' * 70}\n"
        f"  Assets:          {len(asset_ids)}\n"
        f"  Pairs processed: {n_pairs}\n"
        f"  Features:        {len(promoted_features)}\n"
        f"  Horizons:        {horizons}\n"
        f"  Total results:   {len(all_results):,}\n"
        f"  IC computed:     {n_computed:,}\n"
        f"  Significant:     {n_significant:,} (BH p < 0.05)\n"
        f"  DB rows written: {n_written:,}\n"
        f"  CSV report:      {report_path}\n"
        f"  Elapsed:         {minutes}m{seconds:02d}s\n"
        f"{'=' * 70}\n"
    )

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
