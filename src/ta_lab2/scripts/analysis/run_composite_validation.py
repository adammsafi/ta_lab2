"""
4-layer validation gauntlet for proprietary composite indicators (Phase 106).

Layers
------
1. Permutation IC test: empirical significance via 1000 shuffles.
2. FDR correction: Benjamini-Hochberg across all 6 composites.
3. CPCV: combinatorial purged cross-validation (6 splits, 2 test splits).
4. Held-out: final 20% touched exactly once as terminal gate.

Survivors are promoted to dim_feature_registry with:
  lifecycle='promoted', source_type='proprietary'

Usage
-----
    python -m ta_lab2.scripts.analysis.run_composite_validation --tf 10D --verbose
    python -m ta_lab2.scripts.analysis.run_composite_validation --tf 10D --venue-id 1
    python -m ta_lab2.scripts.analysis.run_composite_validation --help

Notes
-----
- Composites with < 100 non-null training pairs: marked "insufficient_data".
- If < 2 composites survive the 4-layer gauntlet, Option B fallback is applied:
  same-sign held-out IC (drop |IC| >= 0.01 floor). If still < 2, Option C:
  accept 1 strong survivor (|IC| > 0.03 with p < 0.01). Choice is documented.
- ASCII-only output (Windows cp1252 compatibility).
- Reports saved to reports/composites/composite_validation_results.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import create_engine, pool, text

from ta_lab2.features.composite_indicators import COMPOSITE_NAMES
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_VALID_PAIRS = 100  # minimum non-null (feature, fwd_return) pairs for IC
CPCV_N_SPLITS = 6
CPCV_N_TEST_SPLITS = 2
CPCV_EMBARGO_FRAC = 0.01
N_PERMS = 1000
RNG_SEED = 42


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_composite_data(engine, tf: str, venue_id: int) -> pd.DataFrame:
    """Load composite columns + forward return from features table.

    Forward return is computed from features.close as:
        fwd_ret = close.pct_change().shift(-horizon)

    Returns a DataFrame indexed by (id, ts) with composite columns and fwd_ret.
    """
    cols_sql = ", ".join(COMPOSITE_NAMES)
    query = text(f"""
        SELECT id, ts, close, {cols_sql}
        FROM features
        WHERE tf = :tf
          AND venue_id = :venue_id
          AND close IS NOT NULL
        ORDER BY id, ts
    """)
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"tf": tf, "venue_id": venue_id})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index(["id", "ts"]).sort_index()
    return df


def _compute_fwd_returns(df: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Add fwd_ret column per asset using close.pct_change().shift(-horizon)."""
    fwd_rets = []
    for asset_id, group in df.groupby(level="id"):
        close = group["close"]
        fwd_ret = close.pct_change().shift(-horizon)
        fwd_ret.name = "fwd_ret"
        fwd_rets.append(fwd_ret)
    df["fwd_ret"] = pd.concat(fwd_rets)
    return df


def _train_held_out_split(
    asset_df: pd.DataFrame, held_out_frac: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by timestamp: first (1-held_out_frac) is training, last held_out_frac is held-out."""
    n = len(asset_df)
    split_idx = int(n * (1.0 - held_out_frac))
    return asset_df.iloc[:split_idx], asset_df.iloc[split_idx:]


# ---------------------------------------------------------------------------
# Layer 1: Permutation IC
# ---------------------------------------------------------------------------


def _run_permutation_ic(
    feature_vals: np.ndarray,
    fwd_ret_vals: np.ndarray,
    n_perms: int = N_PERMS,
    seed: int = RNG_SEED,
) -> dict:
    """Compute permutation IC test inline (no external dependency required)."""
    # pairwise NaN mask
    valid = np.isfinite(feature_vals) & np.isfinite(fwd_ret_vals)
    x = feature_vals[valid]
    y = fwd_ret_vals[valid]
    n_obs = int(valid.sum())

    if n_obs < 20:
        return {
            "ic_obs": float("nan"),
            "p_value": 1.0,
            "n_obs": n_obs,
            "passes": False,
        }

    stat = spearmanr(x, y)
    ic_obs = float(stat.statistic)
    abs_ic = abs(ic_obs)

    rng = np.random.default_rng(seed)
    null_abs_ics = np.empty(n_perms, dtype=float)
    for i in range(n_perms):
        y_shuf = rng.permutation(y)
        null_stat = spearmanr(x, y_shuf)
        null_abs_ics[i] = abs(float(null_stat.statistic))

    p_value = float(np.mean(null_abs_ics >= abs_ic))
    pct95 = float(np.percentile(null_abs_ics, 95))
    passes = abs_ic >= pct95

    return {
        "ic_obs": ic_obs,
        "p_value": p_value,
        "n_obs": n_obs,
        "passes": bool(passes),
    }


# ---------------------------------------------------------------------------
# Layer 2: FDR correction
# ---------------------------------------------------------------------------


def _apply_fdr(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    """Benjamini-Hochberg FDR correction. Returns list of reject booleans."""
    from statsmodels.stats.multitest import fdrcorrection

    rejected, _ = fdrcorrection(p_values, alpha=alpha, method="indep")
    return list(rejected)


# ---------------------------------------------------------------------------
# Layer 3: CPCV
# ---------------------------------------------------------------------------


def _run_cpcv(
    feature_vals: np.ndarray,
    fwd_ret_vals: np.ndarray,
    timestamps: pd.DatetimeIndex,
    horizon: int,
) -> dict:
    """Run CPCV using CPCVSplitter from backtests/cv.py.

    Falls back to simple 6-fold time-series split if CPCVSplitter fails.

    Returns dict with: cpcv_ic_mean, cpcv_ic_std, cpcv_paths_positive_frac, cpcv_passed.
    """
    # pairwise valid mask
    valid = np.isfinite(feature_vals) & np.isfinite(fwd_ret_vals)
    x = feature_vals[valid]
    y = fwd_ret_vals[valid]
    ts_valid = timestamps[valid]
    n = len(x)

    if n < 30:
        return {
            "cpcv_ic_mean": float("nan"),
            "cpcv_ic_std": float("nan"),
            "cpcv_paths_positive_frac": float("nan"),
            "cpcv_passed": False,
            "cpcv_method": "insufficient",
        }

    # Build t1_series (label-end timestamps = ts + horizon bars approximation)
    # We approximate label-end as the next-horizon timestamp
    t1_values = []
    for i in range(n):
        end_idx = min(i + horizon, n - 1)
        t1_values.append(ts_valid[end_idx])
    t1_series = pd.Series(t1_values, index=ts_valid, dtype="datetime64[ns, UTC]")

    path_ics: list[float] = []

    try:
        from ta_lab2.backtests.cv import CPCVSplitter

        # Need monotonic index
        if not t1_series.index.is_monotonic_increasing:
            t1_series = t1_series.sort_index()

        splitter = CPCVSplitter(
            n_splits=CPCV_N_SPLITS,
            n_test_splits=CPCV_N_TEST_SPLITS,
            t1_series=t1_series,
            embargo_frac=CPCV_EMBARGO_FRAC,
        )

        X_dummy = np.zeros((n, 1))
        for train_idx, test_idx in splitter.split(X_dummy):
            if len(test_idx) < 10:
                continue
            x_test = x[test_idx]
            y_test = y[test_idx]
            valid_fold = np.isfinite(x_test) & np.isfinite(y_test)
            if valid_fold.sum() < 10:
                continue
            stat = spearmanr(x_test[valid_fold], y_test[valid_fold])
            path_ics.append(float(stat.statistic))

        method = "cpcv"

    except Exception as e:
        logger.warning("CPCVSplitter failed (%s), using simple 6-fold split", e)
        # Fallback: simple 6 non-overlapping folds, use each as test
        fold_size = n // CPCV_N_SPLITS
        for k in range(CPCV_N_SPLITS):
            start = k * fold_size
            end = start + fold_size if k < CPCV_N_SPLITS - 1 else n
            test_idx = np.arange(start, end)
            if len(test_idx) < 10:
                continue
            x_test = x[test_idx]
            y_test = y[test_idx]
            valid_fold = np.isfinite(x_test) & np.isfinite(y_test)
            if valid_fold.sum() < 10:
                continue
            stat = spearmanr(x_test[valid_fold], y_test[valid_fold])
            path_ics.append(float(stat.statistic))
        method = "simple_kfold"

    if len(path_ics) < 2:
        return {
            "cpcv_ic_mean": float("nan"),
            "cpcv_ic_std": float("nan"),
            "cpcv_paths_positive_frac": float("nan"),
            "cpcv_passed": False,
            "cpcv_method": method,
        }

    arr = np.array(path_ics)
    ic_mean = float(np.mean(arr))
    ic_std = float(np.std(arr))
    pos_frac = float(np.mean(arr > 0))
    cpcv_passed = (ic_mean > 0) and (pos_frac > 0.6)

    return {
        "cpcv_ic_mean": ic_mean,
        "cpcv_ic_std": ic_std,
        "cpcv_paths_positive_frac": pos_frac,
        "cpcv_passed": bool(cpcv_passed),
        "cpcv_method": method,
        "cpcv_n_paths": len(path_ics),
    }


# ---------------------------------------------------------------------------
# Layer 4: Held-out validation
# ---------------------------------------------------------------------------


def _run_held_out(
    feature_vals: np.ndarray,
    fwd_ret_vals: np.ndarray,
    training_ic: float,
    ic_floor: float = 0.01,
) -> dict:
    """Compute Spearman IC on held-out data; gate on sign + magnitude."""
    valid = np.isfinite(feature_vals) & np.isfinite(fwd_ret_vals)
    x = feature_vals[valid]
    y = fwd_ret_vals[valid]
    n_obs = int(valid.sum())

    if n_obs < 20:
        return {
            "held_out_ic": float("nan"),
            "held_out_n_obs": n_obs,
            "held_out_passed": False,
            "held_out_status": "insufficient",
        }

    stat = spearmanr(x, y)
    ic = float(stat.statistic)
    same_sign = (
        np.isfinite(training_ic)
        and np.isfinite(ic)
        and np.sign(ic) == np.sign(training_ic)
    )

    if not same_sign:
        status = "failed_sign_flip"
        passed = False
    elif abs(ic) < ic_floor:
        status = "marginal"
        passed = False  # strict; may be relaxed by fallback logic
    else:
        status = "passed"
        passed = True

    return {
        "held_out_ic": ic,
        "held_out_n_obs": n_obs,
        "held_out_passed": bool(passed),
        "held_out_status": status,
    }


# ---------------------------------------------------------------------------
# Promotion
# ---------------------------------------------------------------------------


def _promote_composite(
    engine,
    composite_name: str,
    best_ic: float,
    best_horizon: int,
    alpha: float,
    verbose: bool = False,
) -> None:
    """Insert or update dim_feature_registry with lifecycle='promoted', source_type='proprietary'."""
    now = datetime.now(timezone.utc)
    sql = text("""
        INSERT INTO public.dim_feature_registry (
            feature_name,
            lifecycle,
            source_type,
            best_ic,
            best_horizon,
            promoted_at,
            promotion_alpha,
            updated_at
        ) VALUES (
            :feature_name,
            'promoted',
            'proprietary',
            :best_ic,
            :best_horizon,
            :promoted_at,
            :promotion_alpha,
            :updated_at
        )
        ON CONFLICT (feature_name) DO UPDATE SET
            lifecycle = 'promoted',
            source_type = 'proprietary',
            best_ic = EXCLUDED.best_ic,
            best_horizon = EXCLUDED.best_horizon,
            promoted_at = EXCLUDED.promoted_at,
            promotion_alpha = EXCLUDED.promotion_alpha,
            updated_at = EXCLUDED.updated_at
    """)
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "feature_name": composite_name,
                "best_ic": float(best_ic),
                "best_horizon": int(best_horizon),
                "promoted_at": now,
                "promotion_alpha": float(alpha),
                "updated_at": now,
            },
        )
    if verbose:
        print(
            f"  [PROMOTED] {composite_name} -> dim_feature_registry (source_type='proprietary')"
        )


# ---------------------------------------------------------------------------
# Main validation loop
# ---------------------------------------------------------------------------


def _check_registry_has_source_type(engine: object) -> bool:
    """Check if dim_feature_registry has source_type column."""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'dim_feature_registry'
              AND column_name = 'source_type'
        """)
        )
        return result.fetchone() is not None


def run_validation(
    tf: str,
    venue_id: int,
    horizon: int,
    alpha: float,
    held_out_frac: float,
    verbose: bool,
    db_url: str,
) -> list[dict]:
    """Run the full 4-layer validation gauntlet. Returns list of result dicts."""
    engine = create_engine(db_url, poolclass=pool.NullPool)

    # Check if source_type column exists
    has_source_type = _check_registry_has_source_type(engine)
    if not has_source_type:
        logger.warning(
            "dim_feature_registry missing source_type column. "
            "Promotion will proceed without source_type."
        )

    print("\n=== Phase 106 Composite Validation ===")
    print(f"  tf={tf}, venue_id={venue_id}, horizon={horizon}, alpha={alpha}")
    print(f"  held_out_frac={held_out_frac}, n_perms={N_PERMS}\n")

    # Load data
    print("Loading composite data from features table...")
    df_full = _load_composite_data(engine, tf, venue_id)

    if df_full.empty:
        print(f"  ERROR: No data found for tf={tf}, venue_id={venue_id}. Exiting.")
        return []

    df_full = _compute_fwd_returns(df_full, horizon)
    print(
        f"  Loaded {len(df_full)} rows across {df_full.index.get_level_values('id').nunique()} assets."
    )

    # Collect training pools and held-out pools per composite
    train_pools: dict[str, tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]] = {}
    held_out_pools: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for composite in COMPOSITE_NAMES:
        train_x_list, train_y_list, train_ts_list = [], [], []
        held_out_x_list, held_out_y_list = [], []
        qualifying_assets = 0

        for asset_id, group in df_full.groupby(level="id"):
            asset_df = group.droplevel("id")
            train_df, hout_df = _train_held_out_split(asset_df, held_out_frac)

            # Check >= 50% non-null in training
            n_train = len(train_df)
            n_nonnull = train_df[composite].notna().sum()
            if n_nonnull < 0.5 * n_train or n_nonnull == 0:
                continue

            qualifying_assets += 1

            # Training pool
            feat_train = train_df[composite].values
            fwd_train = train_df["fwd_ret"].values
            ts_train = train_df.index

            train_x_list.append(feat_train)
            train_y_list.append(fwd_train)
            train_ts_list.append(ts_train)

            # Held-out pool
            held_out_x_list.append(hout_df[composite].values)
            held_out_y_list.append(hout_df["fwd_ret"].values)

        if verbose:
            print(f"  {composite}: {qualifying_assets} qualifying assets")

        if qualifying_assets == 0:
            train_pools[composite] = (np.array([]), np.array([]), pd.DatetimeIndex([]))
            held_out_pools[composite] = (np.array([]), np.array([]))
        else:
            train_x = np.concatenate(train_x_list)
            train_y = np.concatenate(train_y_list)
            train_ts = (
                pd.DatetimeIndex(train_ts_list[0])
                if len(train_ts_list) == 1
                else pd.DatetimeIndex(
                    np.concatenate([ts.values for ts in train_ts_list])
                )
            )
            train_pools[composite] = (train_x, train_y, train_ts)

            hx = np.concatenate(held_out_x_list)
            hy = np.concatenate(held_out_y_list)
            held_out_pools[composite] = (hx, hy)

    # ---------------------------------------------------------------------------
    # Layer 1: Permutation IC for all composites
    # ---------------------------------------------------------------------------
    print("\n--- Layer 1: Permutation IC (1000 shuffles) ---")
    perm_results: dict[str, dict] = {}
    p_values_for_fdr: list[float] = []
    composite_status: dict[str, str] = {}

    for composite in COMPOSITE_NAMES:
        x, y, _ = train_pools[composite]
        valid = np.isfinite(x) & np.isfinite(y)
        n_valid = int(valid.sum())

        if n_valid < MIN_VALID_PAIRS:
            perm_results[composite] = {
                "ic_obs": float("nan"),
                "p_value": 1.0,
                "n_obs": n_valid,
                "passes": False,
            }
            composite_status[composite] = "insufficient_data"
            p_values_for_fdr.append(1.0)  # sentinel for FDR
            print(f"  {composite}: INSUFFICIENT DATA (n={n_valid} < {MIN_VALID_PAIRS})")
        else:
            r = _run_permutation_ic(x, y, n_perms=N_PERMS, seed=RNG_SEED)
            perm_results[composite] = r
            composite_status[composite] = "ok"
            p_values_for_fdr.append(r["p_value"])
            ic_str = f"{r['ic_obs']:+.4f}" if not np.isnan(r["ic_obs"]) else "nan"
            print(
                f"  {composite}: IC={ic_str}, p={r['p_value']:.4f}, "
                f"n_obs={r['n_obs']}, passes_perm={r['passes']}"
            )

    # ---------------------------------------------------------------------------
    # Layer 2: FDR correction
    # ---------------------------------------------------------------------------
    print("\n--- Layer 2: FDR Correction (Benjamini-Hochberg, alpha=0.05) ---")
    fdr_rejected = _apply_fdr(p_values_for_fdr, alpha=alpha)

    fdr_survivors: list[str] = []
    for i, composite in enumerate(COMPOSITE_NAMES):
        status = "PASS" if fdr_rejected[i] else "FAIL"
        insuf = (
            "(insufficient_data)"
            if composite_status[composite] == "insufficient_data"
            else ""
        )
        print(f"  {composite}: FDR={status} (p={p_values_for_fdr[i]:.4f}) {insuf}")
        if fdr_rejected[i] and composite_status[composite] == "ok":
            fdr_survivors.append(composite)

    print(f"  FDR survivors: {fdr_survivors}")

    # ---------------------------------------------------------------------------
    # Layer 3: CPCV
    # ---------------------------------------------------------------------------
    print(
        f"\n--- Layer 3: CPCV ({CPCV_N_SPLITS} splits, {CPCV_N_TEST_SPLITS} test splits) ---"
    )
    cpcv_results: dict[str, dict] = {}
    cpcv_survivors: list[str] = []

    for composite in COMPOSITE_NAMES:
        if composite not in fdr_survivors:
            cpcv_results[composite] = {
                "cpcv_ic_mean": float("nan"),
                "cpcv_ic_std": float("nan"),
                "cpcv_paths_positive_frac": float("nan"),
                "cpcv_passed": False,
                "cpcv_method": "skipped",
            }
            continue

        x, y, ts = train_pools[composite]
        # Build a sorted DatetimeIndex for CPCV from pooled training data
        valid = np.isfinite(x) & np.isfinite(y)
        x_v = x[valid]
        y_v = y[valid]

        # Build timestamps for valid pairs (approximate pooled timeline)
        # For single-composite pooled data across assets, we need a monotonic ts
        # Use a synthetic range if pooled across multiple assets
        n_v = len(x_v)
        synth_ts = pd.date_range("2010-01-01", periods=n_v, freq="1D", tz="UTC")

        r = _run_cpcv(x_v, y_v, synth_ts, horizon)
        cpcv_results[composite] = r

        status = "PASS" if r["cpcv_passed"] else "FAIL"
        print(
            f"  {composite}: mean_IC={r['cpcv_ic_mean']:.4f}, "
            f"pos_frac={r['cpcv_paths_positive_frac']:.2f}, "
            f"method={r.get('cpcv_method', '?')}, "
            f"n_paths={r.get('cpcv_n_paths', '?')}, "
            f"CPCV={status}"
        )

        if r["cpcv_passed"]:
            cpcv_survivors.append(composite)

    print(f"  CPCV survivors: {cpcv_survivors}")

    # ---------------------------------------------------------------------------
    # Layer 4: Held-out (strict: same sign AND |IC| >= 0.01)
    # ---------------------------------------------------------------------------
    print("\n--- Layer 4: Held-out Validation (final gate, 20%) ---")
    held_out_results: dict[str, dict] = {}
    full_survivors: list[str] = []

    for composite in COMPOSITE_NAMES:
        if composite not in cpcv_survivors:
            held_out_results[composite] = {
                "held_out_ic": float("nan"),
                "held_out_n_obs": 0,
                "held_out_passed": False,
                "held_out_status": "skipped",
            }
            continue

        hx, hy = held_out_pools[composite]
        training_ic = perm_results[composite]["ic_obs"]
        r = _run_held_out(hx, hy, training_ic, ic_floor=0.01)
        held_out_results[composite] = r

        status_str = r["held_out_status"].upper()
        ic_str = f"{r['held_out_ic']:+.4f}" if not np.isnan(r["held_out_ic"]) else "nan"
        print(
            f"  {composite}: held_out_IC={ic_str}, n={r['held_out_n_obs']}, "
            f"status={status_str}"
        )

        if r["held_out_passed"]:
            full_survivors.append(composite)

    print(f"  Strict survivors (all 4 layers): {full_survivors}")

    # ---------------------------------------------------------------------------
    # Fallback strategy if < 2 survivors
    # ---------------------------------------------------------------------------
    fallback_applied: str | None = None
    promoted_composites: list[str] = list(full_survivors)

    if len(full_survivors) < 2:
        print(
            "\n  [FALLBACK] < 2 strict survivors. Applying Option B: relax held-out to same-sign only."
        )
        fallback_applied = "Option B: same-sign held-out (dropped |IC| >= 0.01 floor)"
        marginal_survivors: list[str] = []

        for composite in cpcv_survivors:
            if composite in full_survivors:
                continue
            r = held_out_results.get(composite, {})
            status = r.get("held_out_status", "")
            ic = r.get("held_out_ic", float("nan"))
            if status == "marginal" and not np.isnan(ic):
                marginal_survivors.append(composite)
                print(
                    f"    [MARGINAL] {composite}: held_out_IC={ic:+.4f} (same sign, |IC| < 0.01)"
                )

        promoted_composites = list(full_survivors) + marginal_survivors

        if len(promoted_composites) < 2:
            print(
                "  [FALLBACK] Option B insufficient. Applying Option C: accept 1 strong survivor."
            )
            fallback_applied = "Option C: 1 strong survivor (|IC|>0.03, p<0.01)"
            strong_survivors: list[str] = []
            for composite in fdr_survivors:
                perm_r = perm_results[composite]
                ic = perm_r.get("ic_obs", float("nan"))
                p = perm_r.get("p_value", 1.0)
                if not np.isnan(ic) and abs(ic) > 0.03 and p < 0.01:
                    strong_survivors.append(composite)
                    print(f"    [STRONG] {composite}: IC={ic:+.4f}, p={p:.4f}")
            promoted_composites = list(set(full_survivors) | set(strong_survivors))

        print(f"  Fallback promoted: {promoted_composites}")

    # ---------------------------------------------------------------------------
    # Build final result dicts
    # ---------------------------------------------------------------------------
    all_results: list[dict] = []
    for composite in COMPOSITE_NAMES:
        perm_r = perm_results[composite]
        cpcv_r = cpcv_results.get(composite, {})
        hout_r = held_out_results.get(composite, {})

        status = composite_status.get(composite, "ok")
        if status == "insufficient_data":
            layer1_status = "insufficient_data"
        elif perm_r.get("passes"):
            layer1_status = "passed"
        else:
            layer1_status = "failed"

        overall_passed = composite in promoted_composites

        entry = {
            "composite_name": composite,
            "status": status,
            # Layer 1
            "permutation_ic": perm_r.get("ic_obs"),
            "permutation_p": perm_r.get("p_value"),
            "permutation_n_obs": perm_r.get("n_obs"),
            "permutation_passed": perm_r.get("passes"),
            "layer1_status": layer1_status,
            # Layer 2
            "fdr_rejected": bool(fdr_rejected[COMPOSITE_NAMES.index(composite)]),
            # Layer 3
            "cpcv_ic_mean": cpcv_r.get("cpcv_ic_mean"),
            "cpcv_ic_std": cpcv_r.get("cpcv_ic_std"),
            "cpcv_paths_positive_frac": cpcv_r.get("cpcv_paths_positive_frac"),
            "cpcv_passed": cpcv_r.get("cpcv_passed"),
            "cpcv_method": cpcv_r.get("cpcv_method"),
            "cpcv_n_paths": cpcv_r.get("cpcv_n_paths"),
            # Layer 4
            "held_out_ic": hout_r.get("held_out_ic"),
            "held_out_n_obs": hout_r.get("held_out_n_obs"),
            "held_out_passed": hout_r.get("held_out_passed"),
            "held_out_status": hout_r.get("held_out_status"),
            # Overall
            "overall_passed": overall_passed,
        }
        all_results.append(entry)

    # ---------------------------------------------------------------------------
    # Print summary table
    # ---------------------------------------------------------------------------
    print("\n=== Validation Results Summary ===")
    header = f"{'Composite':<40} {'Perm IC':>8} {'FDR':>5} {'CPCV':>5} {'HOut IC':>8} {'Overall':>8}"
    print(header)
    print("-" * len(header))
    for r in all_results:
        perm_ic = (
            f"{r['permutation_ic']:+.4f}"
            if r["permutation_ic"] is not None
            and not (
                isinstance(r["permutation_ic"], float) and np.isnan(r["permutation_ic"])
            )
            else "  N/A "
        )
        fdr = "PASS" if r["fdr_rejected"] else "FAIL"
        cpcv = (
            "PASS"
            if r["cpcv_passed"]
            else ("SKIP" if r["cpcv_method"] in (None, "skipped") else "FAIL")
        )
        hout = (
            f"{r['held_out_ic']:+.4f}"
            if r["held_out_ic"] is not None
            and not (isinstance(r["held_out_ic"], float) and np.isnan(r["held_out_ic"]))
            else "  N/A "
        )
        overall = (
            "*** PROMOTED ***"
            if r["overall_passed"]
            else ("INSUFFICIENT" if r["status"] == "insufficient_data" else "failed")
        )
        print(
            f"  {r['composite_name']:<38} {perm_ic:>8} {fdr:>5} {cpcv:>5} {hout:>8} {overall:>16}"
        )

    print(f"\nFallback: {fallback_applied or 'None (>= 2 strict survivors)'}")
    print(f"Promoted ({len(promoted_composites)}): {promoted_composites}")

    # ---------------------------------------------------------------------------
    # Promote survivors to dim_feature_registry
    # ---------------------------------------------------------------------------
    if promoted_composites:
        print("\n--- Promoting to dim_feature_registry ---")
        for composite in promoted_composites:
            perm_r = perm_results[composite]
            best_ic = perm_r.get("ic_obs") or 0.0
            if np.isnan(best_ic):
                best_ic = 0.0
            try:
                if has_source_type:
                    _promote_composite(
                        engine, composite, best_ic, horizon, alpha, verbose
                    )
                else:
                    # Fallback: promote without source_type column
                    _promote_composite_no_source_type(
                        engine, composite, best_ic, horizon, alpha, verbose
                    )
            except Exception as e:
                logger.error("Failed to promote %s: %s", composite, e)

    return all_results, fallback_applied, promoted_composites


def _promote_composite_no_source_type(
    engine,
    composite_name: str,
    best_ic: float,
    best_horizon: int,
    alpha: float,
    verbose: bool,
) -> None:
    """Promote without source_type column (schema compatibility fallback)."""
    now = datetime.now(timezone.utc)
    sql = text("""
        INSERT INTO public.dim_feature_registry (
            feature_name, lifecycle, best_ic, best_horizon,
            promoted_at, promotion_alpha, updated_at
        ) VALUES (
            :feature_name, 'promoted', :best_ic, :best_horizon,
            :promoted_at, :promotion_alpha, :updated_at
        )
        ON CONFLICT (feature_name) DO UPDATE SET
            lifecycle = 'promoted',
            best_ic = EXCLUDED.best_ic,
            best_horizon = EXCLUDED.best_horizon,
            promoted_at = EXCLUDED.promoted_at,
            promotion_alpha = EXCLUDED.promotion_alpha,
            updated_at = EXCLUDED.updated_at
    """)
    with engine.begin() as conn:
        conn.execute(
            sql,
            {
                "feature_name": composite_name,
                "best_ic": float(best_ic),
                "best_horizon": int(best_horizon),
                "promoted_at": now,
                "promotion_alpha": float(alpha),
                "updated_at": now,
            },
        )
    if verbose:
        print(f"  [PROMOTED] {composite_name} (no source_type column)")


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------


def _save_results(
    results: list[dict],
    fallback_applied: str | None,
    promoted: list[str],
    tf: str,
    venue_id: int,
    horizon: int,
    alpha: float,
) -> Path:
    """Save validation results JSON to reports/composites/."""

    # Sanitize NaN for JSON serialization
    def _sanitize(obj):
        if isinstance(obj, dict):
            return {k: _sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_sanitize(v) for v in obj]
        if isinstance(obj, float) and np.isnan(obj):
            return None
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj

    output = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "params": {
            "tf": tf,
            "venue_id": venue_id,
            "horizon": horizon,
            "alpha": alpha,
            "n_perms": N_PERMS,
        },
        "fallback_applied": fallback_applied,
        "promoted_composites": promoted,
        "n_promoted": len(promoted),
        "results": _sanitize(results),
    }

    # Resolve project root: src/ta_lab2/scripts/analysis/run_composite_validation.py
    # -> parents[4] = project root
    out_dir = Path(__file__).parents[4] / "reports" / "composites"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "composite_validation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="4-layer composite indicator validation gauntlet (Phase 106).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--tf", default="10D", help="Timeframe to validate on.")
    parser.add_argument("--venue-id", type=int, default=1, help="Venue ID.")
    parser.add_argument(
        "--horizon", type=int, default=1, help="Forward return horizon in bars."
    )
    parser.add_argument(
        "--alpha", type=float, default=0.05, help="FDR significance threshold."
    )
    parser.add_argument(
        "--held-out-frac",
        type=float,
        default=0.20,
        help="Fraction of data held out as terminal gate.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed per-composite per-asset output.",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override DB URL (else resolved from db_config.env).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    db_url = resolve_db_url(args.db_url)

    result_data = run_validation(
        tf=args.tf,
        venue_id=args.venue_id,
        horizon=args.horizon,
        alpha=args.alpha,
        held_out_frac=args.held_out_frac,
        verbose=args.verbose,
        db_url=db_url,
    )

    if not result_data:
        print("No results produced. Exiting.")
        sys.exit(1)

    results, fallback_applied, promoted = result_data

    out_path = _save_results(
        results,
        fallback_applied,
        promoted,
        tf=args.tf,
        venue_id=args.venue_id,
        horizon=args.horizon,
        alpha=args.alpha,
    )
    print(f"\nResults saved to: {out_path}")

    if len(promoted) == 0:
        print("\nWARNING: 0 composites promoted. Check data coverage.")
        sys.exit(0)

    print(f"\nDone. {len(promoted)} composite(s) promoted to dim_feature_registry.")


if __name__ == "__main__":
    main()
