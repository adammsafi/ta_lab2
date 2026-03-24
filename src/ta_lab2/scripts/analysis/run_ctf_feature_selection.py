# -*- coding: utf-8 -*-
"""
CTF feature selection: tier classification, AMA comparison, config pruning.

Pipeline steps:
  1. Load CTF IC ranking from ic_results (filter to CTF feature names)
  2. Run stationarity tests on top-N CTF features
  3. Run Ljung-Box on rolling IC series for top-N features
  4. Classify all CTF features into tiers (active/conditional/watch/archive)
  5. Compare CTF IC-IR vs AMA IC-IR (redundancy + head-to-head)
  6. Persist tier assignments to dim_ctf_feature_selection
  7. Write ctf_config_pruned.yaml (remove all-archive combos)
  8. Write comparison report (md + json)

Usage:
    python -m ta_lab2.scripts.analysis.run_ctf_feature_selection --all
    python -m ta_lab2.scripts.analysis.run_ctf_feature_selection --dry-run --top-n 50
    python -m ta_lab2.scripts.analysis.run_ctf_feature_selection --skip-stationarity
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.analysis.feature_selection import (
    classify_feature_tier,
    test_ljungbox_on_ic,
    test_stationarity,
)
from ta_lab2.analysis.ic import (
    compute_forward_returns,
    compute_rolling_ic,
)
from ta_lab2.features.cross_timeframe import load_ctf_features
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CTF_COMPOSITES = (
    "ref_value",
    "base_value",
    "slope",
    "divergence",
    "agreement",
    "crossover",
)

_CTF_COMPOSITE_SUFFIXES = tuple(f"_{c}" for c in _CTF_COMPOSITES)


# ---------------------------------------------------------------------------
# Timestamp utility
# ---------------------------------------------------------------------------


def _to_utc(val) -> pd.Timestamp:
    """Convert a DB-returned timestamp to tz-aware UTC pd.Timestamp."""
    ts = pd.Timestamp(val)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _to_python(v):
    """Normalize a value for SQL binding (numpy scalars -> Python, NaN -> None)."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


# ---------------------------------------------------------------------------
# CTF feature name helpers
# ---------------------------------------------------------------------------


def _get_ctf_feature_names(engine) -> set[str]:
    """
    Build the set of all CTF feature names using two strategies:

    Strategy A: Query dim_ctf_indicators for indicator names, then build all
                possible {indicator}_{ref_tf_lower}_{composite} patterns from
                the CTF config YAML timeframe_pairs.

    Strategy B: Fallback query on ic_results -- features matching CTF composite
                suffix patterns (slope, divergence, ref_value, etc.).

    Returns the union of both sets for robustness against config drift.
    """
    # Strategy A: config-based
    config_features: set[str] = set()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT indicator_name FROM public.dim_ctf_indicators ORDER BY indicator_name"
                )
            ).fetchall()
        indicator_names = [row[0] for row in rows]

        # Load CTF config for ref_tfs
        config_path = (
            Path(__file__).resolve().parents[4] / "configs" / "ctf_config.yaml"
        )
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                ctf_cfg = yaml.safe_load(f)
            all_ref_tfs: set[str] = set()
            for pair in ctf_cfg.get("timeframe_pairs", []):
                for ref_tf in pair.get("ref_tfs", []):
                    all_ref_tfs.add(ref_tf.lower())
        else:
            # Fallback: standard CTF ref_tfs
            all_ref_tfs = {"7d", "14d", "30d", "90d", "180d", "365d"}

        for ind in indicator_names:
            for ref_tf in all_ref_tfs:
                for composite in _CTF_COMPOSITES:
                    config_features.add(f"{ind}_{ref_tf}_{composite}")

        logger.debug(
            "_get_ctf_feature_names (strategy A): %d possible feature names from %d indicators x %d ref_tfs",
            len(config_features),
            len(indicator_names),
            len(all_ref_tfs),
        )
    except Exception as exc:
        logger.warning("_get_ctf_feature_names strategy A failed: %s", exc)

    # Strategy B: DB-based pattern match on ic_results
    db_features: set[str] = set()
    try:
        suffix_conditions = " OR ".join(
            f"feature LIKE '%{suffix}'" for suffix in _CTF_COMPOSITE_SUFFIXES
        )
        sql = text(
            f"SELECT DISTINCT feature FROM public.ic_results WHERE {suffix_conditions}"
        )
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        db_features = {row[0] for row in rows}
        logger.debug(
            "_get_ctf_feature_names (strategy B): %d features from ic_results",
            len(db_features),
        )
    except Exception as exc:
        logger.warning("_get_ctf_feature_names strategy B failed: %s", exc)

    combined = config_features | db_features
    logger.info(
        "_get_ctf_feature_names: %d total CTF feature names (A=%d, B=%d)",
        len(combined),
        len(config_features),
        len(db_features),
    )
    return combined


# ---------------------------------------------------------------------------
# IC ranking loaders
# ---------------------------------------------------------------------------


def _load_ctf_ic_ranking(
    engine,
    ctf_features: set[str],
    horizon: int = 1,
    return_type: str = "arith",
    ic_ir_cutoff: float = 0.5,
) -> pd.DataFrame:
    """
    Load CTF IC ranking from ic_results, filtered to CTF feature names.

    Aggregates mean absolute IC-IR across all (asset, tf) pairs for the given
    horizon and return type. Uses ic_ir_cutoff (0.5) for pass_rate computation.

    Returns DataFrame with columns: feature, mean_abs_ic_ir, mean_abs_ic,
    n_obs, pass_rate. Sorted by mean_abs_ic_ir descending.
    """
    if not ctf_features:
        logger.warning(
            "_load_ctf_ic_ranking: no CTF features -- returning empty DataFrame"
        )
        return pd.DataFrame()

    ctf_list = sorted(ctf_features)
    sql = text(
        """
        SELECT feature,
               AVG(ABS(ic_ir)) AS mean_abs_ic_ir,
               AVG(ABS(ic))    AS mean_abs_ic,
               COUNT(*)        AS n_obs,
               SUM(CASE WHEN ABS(ic_ir) >= :ic_ir_cutoff THEN 1 ELSE 0 END)::FLOAT
                   / NULLIF(COUNT(*), 0) AS pass_rate
        FROM public.ic_results
        WHERE horizon = :horizon
          AND return_type = :return_type
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
          AND feature = ANY(:ctf_features)
        GROUP BY feature
        ORDER BY mean_abs_ic_ir DESC NULLS LAST
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "horizon": horizon,
                "return_type": return_type,
                "ic_ir_cutoff": ic_ir_cutoff,
                "ctf_features": ctf_list,
            },
        )

    logger.info(
        "_load_ctf_ic_ranking: horizon=%d return_type=%s ic_ir_cutoff=%.2f -> %d CTF features",
        horizon,
        return_type,
        ic_ir_cutoff,
        len(df),
    )
    return df


def _load_ctf_ic_by_tf(
    engine,
    ctf_features: set[str],
    horizon: int = 1,
    return_type: str = "arith",
    ic_ir_cutoff: float = 0.5,
) -> pd.DataFrame:
    """
    Load CTF IC results grouped by (feature, tf) for per-(feature, base_tf) tier classification.

    Returns DataFrame with columns: feature, tf, mean_abs_ic_ir, mean_abs_ic,
    n_obs, pass_rate.
    """
    if not ctf_features:
        return pd.DataFrame()

    ctf_list = sorted(ctf_features)
    sql = text(
        """
        SELECT feature,
               tf,
               AVG(ABS(ic_ir)) AS mean_abs_ic_ir,
               AVG(ABS(ic))    AS mean_abs_ic,
               COUNT(*)        AS n_obs,
               SUM(CASE WHEN ABS(ic_ir) >= :ic_ir_cutoff THEN 1 ELSE 0 END)::FLOAT
                   / NULLIF(COUNT(*), 0) AS pass_rate
        FROM public.ic_results
        WHERE horizon = :horizon
          AND return_type = :return_type
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
          AND feature = ANY(:ctf_features)
        GROUP BY feature, tf
        ORDER BY tf, mean_abs_ic_ir DESC NULLS LAST
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "horizon": horizon,
                "return_type": return_type,
                "ic_ir_cutoff": ic_ir_cutoff,
                "ctf_features": ctf_list,
            },
        )

    return df


def _load_ama_ic_ranking(
    engine,
    ctf_features: set[str],
    horizon: int = 1,
    return_type: str = "arith",
) -> pd.DataFrame:
    """
    Load AMA/standard feature IC ranking (features NOT in ctf_features).

    Used for CTF vs AMA comparison.
    Returns DataFrame with columns: feature, mean_abs_ic_ir, mean_abs_ic,
    n_obs, pass_rate. Sorted by mean_abs_ic_ir descending.
    """
    ctf_list = sorted(ctf_features)
    sql = text(
        """
        SELECT feature,
               AVG(ABS(ic_ir))  AS mean_abs_ic_ir,
               AVG(ABS(ic))     AS mean_abs_ic,
               COUNT(*)         AS n_obs,
               SUM(CASE WHEN ABS(ic_ir) > 0.3 THEN 1 ELSE 0 END)::FLOAT
                   / NULLIF(COUNT(*), 0) AS pass_rate
        FROM public.ic_results
        WHERE horizon = :horizon
          AND return_type = :return_type
          AND regime_col = 'all'
          AND regime_label = 'all'
          AND ic IS NOT NULL
          AND feature != ALL(:ctf_features)
        GROUP BY feature
        ORDER BY mean_abs_ic_ir DESC NULLS LAST
        LIMIT 500
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "horizon": horizon,
                "return_type": return_type,
                "ctf_features": ctf_list,
            },
        )

    logger.info(
        "_load_ama_ic_ranking: horizon=%d return_type=%s -> %d AMA features",
        horizon,
        return_type,
        len(df),
    )
    return df


# ---------------------------------------------------------------------------
# CTF feature date range helper
# ---------------------------------------------------------------------------


def _get_ctf_date_range(
    engine, base_tf: str = "1D"
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Query MIN and MAX ts from ctf table for the given base_tf.

    Returns (train_start, train_end) as tz-aware UTC Timestamps.
    Falls back to ic_results if ctf has no data.
    """
    sql = text(
        "SELECT MIN(ts) AS min_ts, MAX(ts) AS max_ts FROM public.ctf WHERE base_tf = :base_tf"
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"base_tf": base_tf}).fetchone()

    if row is None or row[0] is None:
        # Fallback: use ic_results date range
        logger.warning(
            "_get_ctf_date_range: no ctf data for base_tf=%s, using ic_results fallback",
            base_tf,
        )
        now = pd.Timestamp.now("UTC")
        return now - pd.Timedelta(days=365 * 3), now

    return _to_utc(row[0]), _to_utc(row[1])


# ---------------------------------------------------------------------------
# Statistical test wrappers for CTF features
# ---------------------------------------------------------------------------


def _run_ctf_stationarity_tests(
    engine,
    features_list: list[str],
    base_tf: str,
    representative_asset_id: int,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> dict[str, dict]:
    """
    Run ADF/KPSS stationarity tests on CTF features for a representative asset.

    Loads features from the ctf table via load_ctf_features(). Each CTF feature
    is a column in the wide-format pivot output.

    Returns dict keyed by feature name with stationarity result dicts.
    """
    logger.info(
        "Step 2 (CTF): Stationarity for %d features (asset=%d, base_tf=%s)...",
        len(features_list),
        representative_asset_id,
        base_tf,
    )
    t0 = time.time()
    results: dict[str, dict] = {}

    # Load all CTF features at once for efficiency
    try:
        with engine.connect() as conn:
            ctf_df = load_ctf_features(
                conn,
                asset_id=representative_asset_id,
                base_tf=base_tf,
                train_start=train_start,
                train_end=train_end,
                venue_id=1,
            )
    except Exception as exc:
        logger.warning(
            "Step 2: load_ctf_features failed: %s — skipping stationarity", exc
        )
        return {}

    if ctf_df.empty:
        logger.warning(
            "Step 2: ctf_df empty for asset=%d base_tf=%s",
            representative_asset_id,
            base_tf,
        )
        return {}

    for i, feature in enumerate(features_list):
        if feature not in ctf_df.columns:
            results[feature] = {
                "result": "INSUFFICIENT_DATA",
                "adf_stat": float("nan"),
                "adf_pvalue": float("nan"),
                "kpss_stat": float("nan"),
                "kpss_pvalue": float("nan"),
            }
            continue
        try:
            stat_result = test_stationarity(ctf_df[feature])
            results[feature] = stat_result
            logger.debug(
                "  [%d/%d] %s -> %s",
                i + 1,
                len(features_list),
                feature,
                stat_result["result"],
            )
        except Exception as exc:
            logger.warning("  Stationarity failed for '%s': %s", feature, exc)
            results[feature] = {
                "result": "INSUFFICIENT_DATA",
                "adf_stat": float("nan"),
                "adf_pvalue": float("nan"),
                "kpss_stat": float("nan"),
                "kpss_pvalue": float("nan"),
            }

    elapsed = time.time() - t0
    result_counts: dict[str, int] = {}
    for r in results.values():
        k = r.get("result", "UNKNOWN")
        result_counts[k] = result_counts.get(k, 0) + 1
    logger.info("Step 2 complete (%.1fs): %s", elapsed, result_counts)
    return results


def _run_ctf_ljungbox_tests(
    engine,
    features_list: list[str],
    base_tf: str,
    representative_asset_id: int,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    horizon: int,
    return_type: str,
) -> dict[str, dict]:
    """
    Run Ljung-Box autocorrelation test on rolling IC series for CTF features.

    Loads CTF features via load_ctf_features(), computes rolling IC vs close
    forward returns, then tests for autocorrelation in the IC series.

    Returns dict keyed by feature name with Ljung-Box result dicts.
    """
    logger.info(
        "Step 3 (CTF): Ljung-Box for %d features (asset=%d, base_tf=%s)...",
        len(features_list),
        representative_asset_id,
        base_tf,
    )
    t0 = time.time()
    results: dict[str, dict] = {}
    log_flag = return_type == "log"

    try:
        with engine.connect() as conn:
            ctf_df = load_ctf_features(
                conn,
                asset_id=representative_asset_id,
                base_tf=base_tf,
                train_start=train_start,
                train_end=train_end,
                venue_id=1,
            )
            # Load close prices from price_bars_multi_tf
            close_sql = text(
                """
                SELECT ts, close FROM public.price_bars_multi_tf
                WHERE id = :asset_id AND tf = :tf AND venue_id = 1
                  AND ts >= :start AND ts <= :end
                ORDER BY ts
                """
            )
            close_df = pd.read_sql(
                close_sql,
                conn,
                params={
                    "asset_id": representative_asset_id,
                    "tf": base_tf,
                    "start": train_start,
                    "end": train_end,
                },
            )
    except Exception as exc:
        logger.warning("Step 3: data load failed: %s — skipping Ljung-Box", exc)
        return {}

    if ctf_df.empty or close_df.empty:
        logger.warning(
            "Step 3: empty data for asset=%d base_tf=%s",
            representative_asset_id,
            base_tf,
        )
        return {}

    close_df["ts"] = pd.to_datetime(close_df["ts"], utc=True)
    close_series = close_df.set_index("ts")["close"].astype(float)

    fwd_ret = compute_forward_returns(close_series, horizon=horizon, log=log_flag)

    for i, feature in enumerate(features_list):
        if feature not in ctf_df.columns:
            results[feature] = {"flag": False, "min_pvalue": None, "n_obs": 0}
            continue
        try:
            feature_series = ctf_df[feature].dropna()
            fwd_aligned = fwd_ret.reindex(feature_series.index).copy()

            # Null boundary bars (last 'horizon' bars have look-ahead)
            horizon_delta = pd.Timedelta(days=horizon)
            boundary_mask = (feature_series.index + horizon_delta) > train_end
            fwd_aligned.iloc[boundary_mask.values] = float("nan")

            rolling_ic_series, _, _ = compute_rolling_ic(
                feature_series, fwd_aligned, window=63
            )
            lb_result = test_ljungbox_on_ic(rolling_ic_series)
            results[feature] = lb_result

            logger.debug(
                "  [%d/%d] %s -> flag=%s",
                i + 1,
                len(features_list),
                feature,
                lb_result.get("flag"),
            )
        except Exception as exc:
            logger.warning("  Ljung-Box failed for '%s': %s", feature, exc)
            results[feature] = {"flag": False, "min_pvalue": None, "n_obs": 0}

    elapsed = time.time() - t0
    flagged = sum(1 for r in results.values() if r.get("flag", False))
    logger.info(
        "Step 3 complete (%.1fs): %d/%d features flagged for serial correlation",
        elapsed,
        flagged,
        len(results),
    )
    return results


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------


def save_ctf_to_db(engine, results: list[dict]) -> int:
    """
    Upsert CTF tier assignments to dim_ctf_feature_selection.

    Each dict must have: feature_name, base_tf, tier, ic_ir_mean, pass_rate,
    stationarity, ljung_box_flag, selected_at, yaml_version, rationale.

    Uses ON CONFLICT (feature_name, base_tf) DO UPDATE (upsert, NOT truncate).
    This is separate from save_to_db() which truncates dim_feature_selection.

    Returns count of rows written.
    """
    if not results:
        logger.warning("save_ctf_to_db: no rows to insert")
        return 0

    insert_sql = text(
        """
        INSERT INTO public.dim_ctf_feature_selection
            (feature_name, base_tf, tier, ic_ir_mean, pass_rate,
             stationarity, ljung_box_flag, selected_at, yaml_version, rationale)
        VALUES
            (:feature_name, :base_tf, :tier, :ic_ir_mean, :pass_rate,
             :stationarity, :ljung_box_flag, :selected_at, :yaml_version, :rationale)
        ON CONFLICT (feature_name, base_tf) DO UPDATE SET
            tier           = EXCLUDED.tier,
            ic_ir_mean     = EXCLUDED.ic_ir_mean,
            pass_rate      = EXCLUDED.pass_rate,
            stationarity   = EXCLUDED.stationarity,
            ljung_box_flag = EXCLUDED.ljung_box_flag,
            selected_at    = EXCLUDED.selected_at,
            yaml_version   = EXCLUDED.yaml_version,
            rationale      = EXCLUDED.rationale
        """
    )

    with engine.begin() as conn:
        conn.execute(insert_sql, results)

    logger.info(
        "save_ctf_to_db: upserted %d rows to dim_ctf_feature_selection", len(results)
    )
    return len(results)


# ---------------------------------------------------------------------------
# Comparison report builder
# ---------------------------------------------------------------------------


def _build_comparison_report(
    ctf_ranking: pd.DataFrame,
    ama_ranking: pd.DataFrame,
    tier_assignments: dict[str, str],
    ic_ir_cutoff: float,
) -> tuple[str, dict]:
    """
    Generate CTF vs AMA comparison report (markdown + JSON).

    Sections:
      1. Summary Statistics (tier counts for CTF vs AMA)
      2. Top CTF Features by IC-IR
      3. Redundancy Analysis (Spearman correlation of IC-IR vectors)
      4. Head-to-Head (best CTF IC-IR vs best AMA IC-IR)
      5. Pruning Recommendations
    """
    from scipy.stats import spearmanr

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Tier counts
    tier_counts: dict[str, int] = {
        "active": 0,
        "conditional": 0,
        "watch": 0,
        "archive": 0,
    }
    for tier in tier_assignments.values():
        if tier in tier_counts:
            tier_counts[tier] += 1

    n_ctf_total = len(tier_assignments)

    # AMA tier counts (using 0.3 cutoff for legacy comparison)
    ama_active_rate = 0.0
    ama_top_ic_ir = 0.0
    if not ama_ranking.empty and "mean_abs_ic_ir" in ama_ranking.columns:
        ama_top_ic_ir = float(ama_ranking["mean_abs_ic_ir"].max() or 0.0)
        ama_active_count = int((ama_ranking["mean_abs_ic_ir"] >= 0.3).sum())
        ama_active_rate = ama_active_count / max(1, len(ama_ranking))

    # CTF top IC-IR
    ctf_top_ic_ir = 0.0
    ctf_mean_ic_ir = 0.0
    if not ctf_ranking.empty and "mean_abs_ic_ir" in ctf_ranking.columns:
        ctf_top_ic_ir = float(ctf_ranking["mean_abs_ic_ir"].max() or 0.0)
        ctf_mean_ic_ir = float(ctf_ranking["mean_abs_ic_ir"].mean() or 0.0)

    # Redundancy analysis: Spearman rho between CTF IC-IR and AMA IC-IR
    # Match features that exist in BOTH rankings by indicator name prefix
    redundancy_pairs: list[tuple[str, str, float]] = []
    corr_value: float | None = None

    if not ctf_ranking.empty and not ama_ranking.empty:
        ctf_vals = ctf_ranking.set_index("feature")["mean_abs_ic_ir"].astype(float)
        ama_vals = ama_ranking.set_index("feature")["mean_abs_ic_ir"].astype(float)

        # Match CTF feature to its base indicator in AMA
        # e.g. rsi_14_7d_slope -> base indicator is rsi_14
        matched_ctf: list[float] = []
        matched_ama: list[float] = []
        for ctf_feat, ctf_val in ctf_vals.items():
            # Extract indicator by removing _{ref_tf}_{composite} suffix
            parts = ctf_feat.rsplit("_", 2)
            if len(parts) == 3:
                indicator_name = parts[0]
                # Find matching AMA feature (exact indicator name)
                if indicator_name in ama_vals.index:
                    matched_ctf.append(float(ctf_val))
                    matched_ama.append(float(ama_vals[indicator_name]))
                    if len(matched_ctf) <= 3:
                        redundancy_pairs.append(
                            (ctf_feat, indicator_name, float(ctf_val))
                        )

        if len(matched_ctf) >= 5:
            try:
                result = spearmanr(matched_ctf, matched_ama)
                corr_value = float(result.statistic)
                # Track count of near-identical pairs for report context (not used elsewhere)
                _ctf_redundant_count = sum(  # noqa: F841
                    1 for c, a in zip(matched_ctf, matched_ama) if abs(c - a) < 0.1
                )
            except Exception as exc:
                logger.warning("Spearman correlation failed: %s", exc)
                corr_value = None

    # Head-to-head summary
    ctf_active_count = tier_counts.get("active", 0)
    ctf_active_pct = 100.0 * ctf_active_count / max(1, n_ctf_total)

    # Pruning summary
    archive_pct = 100.0 * tier_counts.get("archive", 0) / max(1, n_ctf_total)

    # ---------- Build markdown ----------
    lines: list[str] = [
        "# CTF vs AMA Feature Selection Report",
        "",
        f"Generated: {now_str}  ",
        f"IC-IR cutoff (CTF): {ic_ir_cutoff}  ",
        "",
        "---",
        "",
        "## 1. Summary Statistics",
        "",
        "### CTF Tier Distribution",
        "",
        "| Tier | Count | Pct |",
        "|------|-------|-----|",
    ]
    for tier in ("active", "conditional", "watch", "archive"):
        cnt = tier_counts.get(tier, 0)
        pct = 100.0 * cnt / max(1, n_ctf_total)
        lines.append(f"| {tier} | {cnt} | {pct:.1f}% |")

    lines += [
        f"| **TOTAL** | **{n_ctf_total}** | 100% |",
        "",
        "### AMA (Phase 80) Reference",
        "",
        f"- Total AMA features ranked: {len(ama_ranking)}",
        f"- Best AMA IC-IR: {ama_top_ic_ir:.4f}",
        f"- AMA active rate (cutoff 0.3): {ama_active_rate:.1%}",
        "",
        "---",
        "",
        "## 2. Top CTF Features by IC-IR",
        "",
    ]

    if not ctf_ranking.empty:
        lines.append("| # | Feature | IC-IR | IC | Pass Rate | Tier |")
        lines.append("|---|---------|-------|----|-----------|------|")
        for rank_i, (_, row) in enumerate(ctf_ranking.head(20).iterrows(), 1):
            feat = str(row["feature"])
            ic_ir = float(row.get("mean_abs_ic_ir") or 0.0)
            ic_val = float(row.get("mean_abs_ic") or 0.0)
            pr = float(row.get("pass_rate") or 0.0)
            tier = tier_assignments.get(feat, "unknown")
            lines.append(
                f"| {rank_i} | {feat} | {ic_ir:.4f} | {ic_val:.4f} | {pr:.1%} | {tier} |"
            )
    else:
        lines.append("_No CTF features found in ic_results._")

    lines += [
        "",
        "---",
        "",
        "## 3. Redundancy Analysis",
        "",
        "Comparison methodology: Spearman rank correlation between CTF IC-IR values",
        "and their corresponding base indicator IC-IR values from AMA/Phase-80 features.",
        "",
        "A high correlation (rho > 0.7) indicates CTF features are redundant with",
        "their base indicators and add little new information.",
        "",
    ]

    if corr_value is not None:
        redundancy_verdict = (
            "HIGH redundancy"
            if corr_value > 0.7
            else ("MODERATE redundancy" if corr_value > 0.4 else "LOW redundancy")
        )
        lines += [
            f"**Spearman rho (CTF vs base indicator IC-IR):** {corr_value:.4f}",
            "",
            f"**Verdict:** {redundancy_verdict} (rho={corr_value:.4f})",
            "",
            "Interpretation:",
            "- rho > 0.7: CTF features largely replicate base indicator signal",
            "- rho 0.4-0.7: Mixed -- CTF adds some novel signal",
            "- rho < 0.4: CTF features provide substantially different signal",
        ]
    else:
        lines.append("_Insufficient data for redundancy analysis (< 5 matched pairs)._")

    lines += [
        "",
        "---",
        "",
        "## 4. CTF vs AMA Head-to-Head",
        "",
        "| Metric | CTF | AMA (Phase 80) |",
        "|--------|-----|----------------|",
        f"| Best IC-IR | {ctf_top_ic_ir:.4f} | {ama_top_ic_ir:.4f} |",
        f"| Mean IC-IR (all features) | {ctf_mean_ic_ir:.4f} | {float(ama_ranking['mean_abs_ic_ir'].mean() if not ama_ranking.empty else 0.0):.4f} |",
        f"| Active features (cutoff {ic_ir_cutoff}) | {ctf_active_count} ({ctf_active_pct:.1f}%) | N/A |",
        "",
    ]

    if ctf_top_ic_ir >= ama_top_ic_ir:
        verdict_line = "CTF best feature **matches or exceeds** AMA best IC-IR."
    elif ctf_top_ic_ir >= 0.5:
        verdict_line = "CTF top feature exceeds IC-IR cutoff (0.5) -- adds alpha."
    else:
        verdict_line = (
            "CTF features weaker than AMA -- primarily serve as context features."
        )

    lines += [
        f"**Head-to-head verdict:** {verdict_line}",
        "",
        "---",
        "",
        "## 5. Pruning Recommendations",
        "",
        f"- Archive tier: {tier_counts.get('archive', 0)} features ({archive_pct:.1f}%)",
        f"- Active+Conditional: {tier_counts.get('active', 0) + tier_counts.get('conditional', 0)} features retained",
        "",
    ]

    if tier_counts.get("active", 0) > 0:
        lines.append(
            "**Recommendation:** Include active CTF features in model training pipeline."
        )
        lines.append(
            "Active features show IC-IR >= cutoff and are non-redundant validators."
        )
    elif tier_counts.get("conditional", 0) > 0:
        lines.append(
            "**Recommendation:** Use conditional CTF features as regime-specific context only."
        )
    else:
        lines.append(
            "**Recommendation:** CTF features in watch/archive only -- monitor in future sweeps."
        )
        lines.append(
            "Current coverage limited to 2 assets (BTC+XRP 1D). Re-run after full --all sweep."
        )

    lines += [
        "",
        "---",
        "",
        "## 6. Data Coverage Note",
        "",
        f"CTF IC sweep ran on {len(ctf_ranking)} CTF features across available (asset, base_tf) pairs.",
        "Current coverage: 2 assets (BTC id=1, XRP id=1027) at base_tf=1D, ref_tf=7D only.",
        "Full coverage requires running `python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --all`",
        "after completing a full CTF feature refresh (`python -m ta_lab2.scripts.etl.run_ctf_refresh --all`).",
        "",
    ]

    md_content = "\n".join(lines)

    # ---------- Build JSON ----------
    json_data = {
        "generated_at": datetime.utcnow().isoformat(),
        "ic_ir_cutoff": ic_ir_cutoff,
        "ctf_summary": {
            "n_features": n_ctf_total,
            "tier_counts": tier_counts,
            "top_ic_ir": ctf_top_ic_ir,
            "mean_ic_ir": ctf_mean_ic_ir,
        },
        "ama_summary": {
            "n_features": len(ama_ranking),
            "top_ic_ir": ama_top_ic_ir,
            "active_rate_at_0_3": ama_active_rate,
        },
        "redundancy": {
            "spearman_rho": corr_value,
            "n_matched_pairs": len(matched_ctf) if "matched_ctf" in dir() else 0,
            "verdict": redundancy_verdict
            if "redundancy_verdict" in dir()
            else "insufficient_data",
        },
        "top_ctf_features": [
            {
                "rank": i + 1,
                "feature": str(row["feature"]),
                "mean_abs_ic_ir": float(row.get("mean_abs_ic_ir") or 0.0),
                "mean_abs_ic": float(row.get("mean_abs_ic") or 0.0),
                "pass_rate": float(row.get("pass_rate") or 0.0),
                "tier": tier_assignments.get(str(row["feature"]), "unknown"),
            }
            for i, (_, row) in enumerate(ctf_ranking.head(30).iterrows())
        ]
        if not ctf_ranking.empty
        else [],
    }

    return md_content, json_data


# ---------------------------------------------------------------------------
# Config pruning
# ---------------------------------------------------------------------------


def _prune_ctf_config(
    original_yaml_path: Path,
    archive_ref_tfs_by_indicator: dict[str, set[str]],
    output_path: Path,
) -> None:
    """
    Write ctf_config_pruned.yaml removing all-archive indicator x ref_tf combinations.

    Strategy:
    - Load original ctf_config.yaml
    - For each base_tf entry in timeframe_pairs, keep all ref_tfs that have at
      least ONE non-archive feature for ANY indicator
    - Per plan context: "Keep all 6 base TFs regardless of results"
    - Write to output_path with utf-8 encoding (Windows compatibility)

    Parameters
    ----------
    original_yaml_path:
        Path to configs/ctf_config.yaml
    archive_ref_tfs_by_indicator:
        Dict mapping indicator_name -> set of ref_tfs where ALL composites are archive.
        A ref_tf is pruned from a base_tf entry only if ALL indicators are archive for it.
    output_path:
        Destination path for pruned config.
    """
    with open(original_yaml_path, encoding="utf-8") as f:
        original_cfg = yaml.safe_load(f)

    # Build set of ref_tfs to prune: ref_tf is prunable only if ALL indicators are archive
    all_indicator_names = set(archive_ref_tfs_by_indicator.keys())

    def _should_prune_ref_tf(ref_tf: str) -> bool:
        """True if ALL indicators have this ref_tf as archive."""
        if not all_indicator_names:
            return False
        return all(
            ref_tf.lower()
            in {r.lower() for r in archive_ref_tfs_by_indicator.get(ind, set())}
            for ind in all_indicator_names
        )

    # Build pruned timeframe_pairs
    pruned_pairs = []
    pruned_count = 0
    for pair in original_cfg.get("timeframe_pairs", []):
        base_tf = pair["base_tf"]
        original_ref_tfs = pair.get("ref_tfs", [])
        kept_ref_tfs = [rf for rf in original_ref_tfs if not _should_prune_ref_tf(rf)]
        pruned_count += len(original_ref_tfs) - len(kept_ref_tfs)

        # Always keep the base_tf entry (even if ref_tfs is empty) per context decision
        pruned_pairs.append(
            {
                "base_tf": base_tf,
                "ref_tfs": kept_ref_tfs
                if kept_ref_tfs
                else original_ref_tfs,  # fallback to original if all pruned
            }
        )

    pruned_cfg = dict(original_cfg)
    pruned_cfg["timeframe_pairs"] = pruned_pairs
    pruned_cfg["_pruning_metadata"] = {
        "generated_at": datetime.utcnow().isoformat(),
        "pruned_ref_tfs_count": pruned_count,
        "source": "run_ctf_feature_selection.py",
        "note": "All 6 base_tfs retained per Phase 92 context decision.",
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# CTF Config Pruned -- generated by Phase 92 CTF Feature Selection\n")
        f.write("# Archive combinations removed. All 6 base_tfs retained.\n")
        yaml.dump(
            pruned_cfg, f, default_flow_style=False, allow_unicode=True, sort_keys=False
        )

    logger.info(
        "_prune_ctf_config: wrote %s (pruned %d ref_tf entries)",
        output_path,
        pruned_count,
    )


# ---------------------------------------------------------------------------
# Terminal summary printer
# ---------------------------------------------------------------------------


def _print_ctf_summary(
    ctf_ranking: pd.DataFrame,
    tier_assignments: dict[str, str],
    tier_by_tf: dict[str, dict[str, str]],
    db_rows_written: int,
    pruned_yaml_path: Optional[Path],
) -> None:
    """Print a human-readable CTF feature selection summary to stdout."""
    print()
    print("=" * 72)
    print("CTF FEATURE SELECTION SUMMARY")
    print("=" * 72)

    tier_order = ["active", "conditional", "watch", "archive"]
    tier_counts: dict[str, int] = {t: 0 for t in tier_order}
    for tier in tier_assignments.values():
        if tier in tier_counts:
            tier_counts[tier] += 1

    fmt_header = f"{'Tier':<14} {'Count':>6}  {'Example features (top 3)'}"
    print(fmt_header)
    print("-" * 72)

    # Group features by tier
    tier_features: dict[str, list[str]] = {t: [] for t in tier_order}
    if not ctf_ranking.empty:
        for _, row in ctf_ranking.iterrows():
            feat = str(row["feature"])
            tier = tier_assignments.get(feat, "archive")
            tier_features[tier].append(feat)

    for tier in tier_order:
        count = tier_counts[tier]
        examples_list = tier_features[tier][:3]
        examples = ", ".join(examples_list)
        if tier_counts[tier] > 3:
            examples += f", ... (+{count - 3} more)"
        print(f"{tier:<14} {count:>6}  {examples}")

    print("-" * 72)
    total = sum(tier_counts.values())
    print(f"{'TOTAL':<14} {total:>6}")
    print()

    # Top 10 active features
    active_feats = tier_features.get("active", [])
    if active_feats:
        print("Top active features (IC-IR cutoff 0.5):")
        for i, feat in enumerate(active_feats[:10], 1):
            if not ctf_ranking.empty and "feature" in ctf_ranking.columns:
                row_match = ctf_ranking[ctf_ranking["feature"] == feat]
                if not row_match.empty:
                    ic_ir = float(row_match.iloc[0].get("mean_abs_ic_ir") or 0.0)
                    print(f"  {i:>2}. {feat:<45} IC-IR={ic_ir:.4f}")
    else:
        print("No active features at IC-IR cutoff=0.5 (insufficient coverage).")
        print("Run full CTF sweep after --all CTF refresh for complete results.")

    print()
    print(f"DB rows upserted: {db_rows_written}")
    if pruned_yaml_path:
        print(f"Pruned config: {pruned_yaml_path}")
    print("=" * 72)
    print()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def main() -> int:  # noqa: C901
    parser = argparse.ArgumentParser(
        prog="run_ctf_feature_selection",
        description=(
            "CTF feature selection pipeline (Phase 92).\n\n"
            "Classifies CTF features into tiers using IC-IR from ic_results, "
            "compares CTF vs AMA IC-IR for redundancy analysis, persists tier "
            "assignments to dim_ctf_feature_selection, prunes ctf_config.yaml, "
            "and writes a comparison report."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Run full pipeline (required unless --dry-run).",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=1,
        metavar="N",
        help="IC horizon for ranking (default: 1).",
    )
    parser.add_argument(
        "--return-type",
        type=str,
        default="arith",
        dest="return_type",
        choices=["arith", "log"],
        help="IC return type (default: arith).",
    )
    parser.add_argument(
        "--ic-ir-cutoff",
        type=float,
        default=0.5,
        dest="ic_ir_cutoff",
        metavar="FLOAT",
        help="IC-IR cutoff for active tier classification (default: 0.5 per Phase 92 CONTEXT).",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=50,
        dest="top_n",
        metavar="N",
        help="Number of top features for stationarity/Ljung-Box tests (default: 50).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        dest="dry_run",
        help="Print ranking without writing to DB or files.",
    )
    parser.add_argument(
        "--skip-stationarity",
        action="store_true",
        default=False,
        dest="skip_stationarity",
        help="Skip ADF/KPSS stationarity tests.",
    )
    parser.add_argument(
        "--skip-ljungbox",
        action="store_true",
        default=False,
        dest="skip_ljungbox",
        help="Skip Ljung-Box autocorrelation tests.",
    )
    parser.add_argument(
        "--yaml-version",
        type=str,
        default="phase92_v1",
        dest="yaml_version",
        metavar="TAG",
        help="Version tag for dim_ctf_feature_selection.yaml_version (default: phase92_v1).",
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

    if not args.all and not args.dry_run:
        print(
            "Error: provide --all to run full pipeline or --dry-run to print ranking only."
        )
        return 1

    pipeline_start = time.time()

    # -----------------------------------------------------------------------
    # Connect to DB
    # -----------------------------------------------------------------------
    db_url = resolve_db_url()
    engine = create_engine(db_url, poolclass=NullPool)

    # -----------------------------------------------------------------------
    # Step 1: Get CTF feature names + load IC ranking
    # -----------------------------------------------------------------------
    logger.info(
        "Step 1: Loading CTF IC ranking (horizon=%d, return_type=%s)...",
        args.horizon,
        args.return_type,
    )
    t1 = time.time()

    ctf_features = _get_ctf_feature_names(engine)
    ctf_ranking = _load_ctf_ic_ranking(
        engine,
        ctf_features=ctf_features,
        horizon=args.horizon,
        return_type=args.return_type,
        ic_ir_cutoff=args.ic_ir_cutoff,
    )

    if ctf_ranking.empty:
        logger.warning(
            "CTF IC ranking is empty -- no CTF features found in ic_results. "
            "Run run_ctf_ic_sweep first."
        )
        print("\nNo CTF features in ic_results. Run:")
        print("  python -m ta_lab2.scripts.analysis.run_ctf_ic_sweep --all")
        return 1

    n_total = len(ctf_ranking)
    logger.info(
        "Step 1 complete (%.1fs): %d CTF features found. Top-10 by IC-IR:",
        time.time() - t1,
        n_total,
    )
    for _, row in ctf_ranking.head(10).iterrows():
        logger.info(
            "  %-45s IC-IR=%.4f, IC=%.4f, pass_rate=%.1f%%",
            row["feature"],
            float(row.get("mean_abs_ic_ir") or 0.0),
            float(row.get("mean_abs_ic") or 0.0),
            100.0 * float(row.get("pass_rate") or 0.0),
        )

    # Top-N features for detailed tests
    top_n_features = ctf_ranking.head(args.top_n)["feature"].tolist()
    logger.info(
        "Will run tests on top-%d of %d CTF features", len(top_n_features), n_total
    )

    # Representative asset (BTC=1 for 1D base_tf)
    representative_asset_id = 1
    base_tf = "1D"

    # Date range for CTF tests
    train_start, train_end = _get_ctf_date_range(engine, base_tf=base_tf)
    logger.info("CTF date range: %s to %s", train_start.date(), train_end.date())

    if args.dry_run:
        # Print ranking and exit without DB/file writes
        print("\n--- CTF IC Ranking (dry-run) ---")
        for i, (_, row) in enumerate(ctf_ranking.head(30).iterrows(), 1):
            feat = str(row["feature"])
            ic_ir = float(row.get("mean_abs_ic_ir") or 0.0)
            pr = float(row.get("pass_rate") or 0.0)
            tier = classify_feature_tier(
                ic_ir_mean=ic_ir,
                pass_rate=pr,
                stationarity="INSUFFICIENT_DATA",
                regime_ic=None,
                ic_ir_cutoff=args.ic_ir_cutoff,
            )
            print(
                f"  {i:>3}. {feat:<50} IC-IR={ic_ir:.4f} pass_rate={pr:.1%} -> {tier}"
            )
        print(f"\nTotal CTF features: {n_total}")
        print(f"IC-IR cutoff: {args.ic_ir_cutoff}")
        return 0

    # -----------------------------------------------------------------------
    # Step 2: Stationarity tests (if not skipped)
    # -----------------------------------------------------------------------
    if args.skip_stationarity:
        logger.info("Step 2: Skipping stationarity tests (--skip-stationarity)")
        stationarity_results: dict[str, dict] = {}
    else:
        stationarity_results = _run_ctf_stationarity_tests(
            engine=engine,
            features_list=top_n_features,
            base_tf=base_tf,
            representative_asset_id=representative_asset_id,
            train_start=train_start,
            train_end=train_end,
        )

    # -----------------------------------------------------------------------
    # Step 3: Ljung-Box tests (if not skipped)
    # -----------------------------------------------------------------------
    if args.skip_ljungbox:
        logger.info("Step 3: Skipping Ljung-Box tests (--skip-ljungbox)")
        ljungbox_results: dict[str, dict] = {}
    else:
        ljungbox_results = _run_ctf_ljungbox_tests(
            engine=engine,
            features_list=top_n_features,
            base_tf=base_tf,
            representative_asset_id=representative_asset_id,
            train_start=train_start,
            train_end=train_end,
            horizon=args.horizon,
            return_type=args.return_type,
        )

    # -----------------------------------------------------------------------
    # Step 4: Classify all CTF features into tiers
    # -----------------------------------------------------------------------
    logger.info("Step 4: Classifying %d CTF features into tiers...", n_total)
    t4 = time.time()

    # Classify per unique feature (aggregate across all base_tfs)
    tier_assignments: dict[str, str] = {}
    for _, row in ctf_ranking.iterrows():
        feat = str(row["feature"])
        ic_ir = float(row.get("mean_abs_ic_ir") or 0.0)
        pr = float(row.get("pass_rate") or 0.0)
        stat_result = stationarity_results.get(feat, {})
        stationarity = stat_result.get("result", "INSUFFICIENT_DATA")
        tier = classify_feature_tier(
            ic_ir_mean=ic_ir,
            pass_rate=pr,
            stationarity=stationarity,
            regime_ic=None,
            ic_ir_cutoff=args.ic_ir_cutoff,
        )
        tier_assignments[feat] = tier

    tier_counts: dict[str, int] = {
        "active": 0,
        "conditional": 0,
        "watch": 0,
        "archive": 0,
    }
    for tier in tier_assignments.values():
        if tier in tier_counts:
            tier_counts[tier] += 1

    logger.info(
        "Step 4 complete (%.1fs): active=%d, conditional=%d, watch=%d, archive=%d",
        time.time() - t4,
        tier_counts["active"],
        tier_counts["conditional"],
        tier_counts["watch"],
        tier_counts["archive"],
    )

    # -----------------------------------------------------------------------
    # Step 5: Load AMA IC ranking + build comparison report
    # -----------------------------------------------------------------------
    logger.info("Step 5: Loading AMA IC ranking for comparison...")
    ama_ranking = _load_ama_ic_ranking(
        engine,
        ctf_features=ctf_features,
        horizon=args.horizon,
        return_type=args.return_type,
    )
    md_report, json_report = _build_comparison_report(
        ctf_ranking=ctf_ranking,
        ama_ranking=ama_ranking,
        tier_assignments=tier_assignments,
        ic_ir_cutoff=args.ic_ir_cutoff,
    )
    logger.info("Step 5: Comparison report built (%d chars markdown)", len(md_report))

    # -----------------------------------------------------------------------
    # Step 6: Classify per (feature, base_tf) and persist to dim_ctf_feature_selection
    # -----------------------------------------------------------------------
    logger.info("Step 6: Persisting tier assignments to dim_ctf_feature_selection...")
    t6 = time.time()

    # Load per-(feature, tf) groupings for individual base_tf rows
    ctf_by_tf = _load_ctf_ic_by_tf(
        engine,
        ctf_features=ctf_features,
        horizon=args.horizon,
        return_type=args.return_type,
        ic_ir_cutoff=args.ic_ir_cutoff,
    )

    now_dt = datetime.utcnow()
    db_rows: list[dict] = []
    tier_by_tf: dict[str, dict[str, str]] = {}  # feature -> {tf -> tier}

    if not ctf_by_tf.empty:
        for _, row in ctf_by_tf.iterrows():
            feat = str(row["feature"])
            tf = str(row["tf"])
            ic_ir = float(row.get("mean_abs_ic_ir") or 0.0)
            pr = float(row.get("pass_rate") or 0.0)
            stat_result = stationarity_results.get(feat, {})
            stationarity = stat_result.get("result", "INSUFFICIENT_DATA")
            lb_result = ljungbox_results.get(feat, {})
            lb_flag = bool(lb_result.get("flag", False))
            tier = classify_feature_tier(
                ic_ir_mean=ic_ir,
                pass_rate=pr,
                stationarity=stationarity,
                regime_ic=None,
                ic_ir_cutoff=args.ic_ir_cutoff,
            )
            rationale = (
                f"IC-IR={ic_ir:.4f}, pass_rate={pr:.1%}, stationarity={stationarity}"
                + (", ljung_box=flagged" if lb_flag else "")
            )
            db_rows.append(
                {
                    "feature_name": feat,
                    "base_tf": tf,
                    "tier": tier,
                    "ic_ir_mean": _to_python(ic_ir),
                    "pass_rate": _to_python(pr),
                    "stationarity": stationarity,
                    "ljung_box_flag": lb_flag,
                    "selected_at": now_dt,
                    "yaml_version": args.yaml_version,
                    "rationale": rationale,
                }
            )
            if feat not in tier_by_tf:
                tier_by_tf[feat] = {}
            tier_by_tf[feat][tf] = tier
    else:
        # Fallback: use aggregate ranking (one row per feature with 'all' tf)
        for _, row in ctf_ranking.iterrows():
            feat = str(row["feature"])
            ic_ir = float(row.get("mean_abs_ic_ir") or 0.0)
            pr = float(row.get("pass_rate") or 0.0)
            stat_result = stationarity_results.get(feat, {})
            stationarity = stat_result.get("result", "INSUFFICIENT_DATA")
            lb_result = ljungbox_results.get(feat, {})
            lb_flag = bool(lb_result.get("flag", False))
            tier = tier_assignments[feat]
            rationale = (
                f"IC-IR={ic_ir:.4f}, pass_rate={pr:.1%}, stationarity={stationarity}"
            )
            db_rows.append(
                {
                    "feature_name": feat,
                    "base_tf": "1D",
                    "tier": tier,
                    "ic_ir_mean": _to_python(ic_ir),
                    "pass_rate": _to_python(pr),
                    "stationarity": stationarity,
                    "ljung_box_flag": lb_flag,
                    "selected_at": now_dt,
                    "yaml_version": args.yaml_version,
                    "rationale": rationale,
                }
            )

    db_rows_written = save_ctf_to_db(engine, db_rows)
    logger.info(
        "Step 6 complete (%.1fs): %d rows written to dim_ctf_feature_selection",
        time.time() - t6,
        db_rows_written,
    )

    # -----------------------------------------------------------------------
    # Step 7: Prune CTF config
    # -----------------------------------------------------------------------
    logger.info("Step 7: Pruning CTF config...")
    project_root_path = Path(__file__).resolve().parents[4]
    original_yaml_path = project_root_path / "configs" / "ctf_config.yaml"
    pruned_yaml_path = project_root_path / "configs" / "ctf_config_pruned.yaml"

    # Build archive_ref_tfs_by_indicator: indicator -> set of ref_tfs fully archived
    # A ref_tf is "all-archive" for an indicator if all its composites at all base_tfs are archive
    archive_ref_tfs_by_indicator: dict[str, set[str]] = {}

    if tier_by_tf:
        # Group by (indicator, ref_tf) to check if all composites are archive
        # Feature name pattern: {indicator}_{ref_tf_lower}_{composite}
        from collections import defaultdict

        indicator_ref_tf_tiers: dict[tuple[str, str], list[str]] = defaultdict(list)
        for feat, tf_map in tier_by_tf.items():
            parts = feat.rsplit("_", 2)
            if len(parts) == 3:
                indicator_name, ref_tf_lower, composite = parts
                for base_tf_key, tier_val in tf_map.items():
                    indicator_ref_tf_tiers[(indicator_name, ref_tf_lower)].append(
                        tier_val
                    )

        for (indicator_name, ref_tf_lower), tiers in indicator_ref_tf_tiers.items():
            if all(t == "archive" for t in tiers):
                if indicator_name not in archive_ref_tfs_by_indicator:
                    archive_ref_tfs_by_indicator[indicator_name] = set()
                archive_ref_tfs_by_indicator[indicator_name].add(ref_tf_lower)

    logger.info(
        "Step 7: %d indicators have all-archive ref_tfs: %s",
        len(archive_ref_tfs_by_indicator),
        {k: sorted(v) for k, v in list(archive_ref_tfs_by_indicator.items())[:5]},
    )

    if original_yaml_path.exists():
        _prune_ctf_config(
            original_yaml_path=original_yaml_path,
            archive_ref_tfs_by_indicator=archive_ref_tfs_by_indicator,
            output_path=pruned_yaml_path,
        )
    else:
        logger.warning("Step 7: %s not found -- skipping prune", original_yaml_path)

    # -----------------------------------------------------------------------
    # Step 8: Write comparison reports
    # -----------------------------------------------------------------------
    logger.info("Step 8: Writing comparison reports...")
    reports_dir = project_root_path / "reports" / "ctf"
    reports_dir.mkdir(parents=True, exist_ok=True)

    md_path = reports_dir / "ctf_ic_comparison_report.md"
    json_path = reports_dir / "ctf_ic_comparison_report.json"

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    logger.info("Markdown report written to %s", md_path)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_report, f, indent=2, default=str)
    logger.info("JSON report written to %s", json_path)

    # -----------------------------------------------------------------------
    # Step 9: Print terminal summary
    # -----------------------------------------------------------------------
    _print_ctf_summary(
        ctf_ranking=ctf_ranking,
        tier_assignments=tier_assignments,
        tier_by_tf=tier_by_tf,
        db_rows_written=db_rows_written,
        pruned_yaml_path=pruned_yaml_path if original_yaml_path.exists() else None,
    )

    pipeline_elapsed = time.time() - pipeline_start
    minutes = int(pipeline_elapsed // 60)
    seconds = int(pipeline_elapsed % 60)
    logger.info("CTF feature selection pipeline complete in %dm%ds", minutes, seconds)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
