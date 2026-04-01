# -*- coding: utf-8 -*-
"""
Multiple testing correction and bootstrap utilities for indicator research.

Provides Bonferroni / Harvey-Liu haircut adjustments for Sharpe ratios and
IC-IR values, block bootstrap confidence intervals for autocorrelated IC
estimates, and DB-backed trial logging and FDR control.

NOTE (arch 8.0.0): optimal_block_length() returns a DataFrame with columns
  ["stationary", "circular"]. In older arch versions the column was "b_sb".
  This module uses the 8.0.0 column name "stationary" exclusively.

Public API:
    get_trial_count         -- count rows in trial_registry
    haircut_sharpe          -- Bonferroni HL 2015 haircut for Sharpe ratios
    haircut_ic_ir           -- Bonferroni HL 2015 haircut for IC-IR (with DB write)
    block_bootstrap_ic      -- autocorrelation-aware 95% CI for IC via StationaryBootstrap
    permutation_ic_test     -- permutation test for IC significance (added by 102-01)
    fdr_control             -- Benjamini-Hochberg FDR correction (added by 102-01)
    log_trials_to_registry  -- persist trial metadata to trial_registry (added by 102-01)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np
from scipy.stats import norm, spearmanr

from arch.bootstrap import StationaryBootstrap, optimal_block_length

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Frequency scaling constants (Harvey & Liu 2015)
# ---------------------------------------------------------------------------

_FREQ_TO_MONTHLY: dict[str, float] = {
    "daily": 21.0,
    "weekly": 4.33,
    "monthly": 1.0,
    "annual": 1.0 / 12.0,
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def get_trial_count(conn: Any) -> int:
    """Return total number of rows in trial_registry.

    Args:
        conn: SQLAlchemy connection or psycopg2 connection.

    Returns:
        Total trial count (int). Returns 0 if table does not exist or conn is
        None (enables pure-Python usage without a DB connection).
    """
    if conn is None:
        return 0
    try:
        # Support both psycopg2 raw connections and SQLAlchemy connections.
        try:
            from sqlalchemy import text as _text

            result = conn.execute(_text("SELECT COUNT(*) FROM trial_registry"))
            row = result.fetchone()
        except Exception:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM trial_registry")
            row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as exc:
        logger.warning("get_trial_count failed: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Harvey & Liu 2015 Bonferroni haircut helpers
# ---------------------------------------------------------------------------


def haircut_sharpe(
    sr_observed: float,
    n_trials: int,
    n_obs: int,
    freq: str = "monthly",
) -> dict[str, Any]:
    """Apply Harvey & Liu (2015) Bonferroni haircut to an observed Sharpe ratio.

    The haircut accounts for data-snooping bias when many strategies have been
    evaluated: the more trials tested, the lower the adjusted Sharpe.

    Algorithm (Bonferroni method):
    1. Convert observed annual SR to a monthly SR (sr_m = sr_observed / sqrt(12)).
    2. Scale n_obs to monthly observations via FREQ_TO_MONTHLY mapping.
    3. Compute t-stat: t = sr_m * sqrt(n_monthly).
    4. One-sided p-value: p = 1 - norm.cdf(t).
    5. Bonferroni adjustment: p_adj = min(1.0, p * n_trials).
    6. Adjusted t: t_adj = norm.ppf(1 - p_adj) if p_adj < 1 else 0.0.
    7. Convert back to annual SR: sr_haircut = (t_adj / sqrt(n_monthly)) * sqrt(12).
    8. Haircut pct: (sr_observed - sr_haircut) / sr_observed.

    Args:
        sr_observed: Observed (annualised) Sharpe ratio.
        n_trials:    Total number of strategies/indicators tested (trial count).
        n_obs:       Number of observations at the given frequency.
        freq:        Observation frequency. One of 'daily', 'weekly', 'monthly',
                     'annual'. Default 'monthly'.

    Returns:
        dict with keys:
            sr_observed   -- input value
            sr_haircut    -- adjusted Sharpe ratio
            haircut_pct   -- fractional reduction (0-1)
            n_trials      -- input value
            n_obs         -- input value
            freq          -- input value
    """
    # Edge cases
    if sr_observed <= 0.0:
        return {
            "sr_observed": sr_observed,
            "sr_haircut": 0.0,
            "haircut_pct": 0.0,
            "n_trials": n_trials,
            "n_obs": n_obs,
            "freq": freq,
        }
    if n_trials <= 0:
        return {
            "sr_observed": sr_observed,
            "sr_haircut": sr_observed,
            "haircut_pct": 0.0,
            "n_trials": n_trials,
            "n_obs": n_obs,
            "freq": freq,
        }
    if n_obs <= 0:
        return {
            "sr_observed": sr_observed,
            "sr_haircut": 0.0,
            "haircut_pct": 1.0,
            "n_trials": n_trials,
            "n_obs": n_obs,
            "freq": freq,
        }

    scale = _FREQ_TO_MONTHLY.get(freq, 1.0)
    n_monthly = n_obs / scale

    # Monthly SR (annual divided by sqrt(12))
    sr_m = sr_observed / math.sqrt(12.0)

    # t-stat under H0: SR = 0
    t = sr_m * math.sqrt(n_monthly)

    # One-sided p-value (H1: SR > 0)
    p = 1.0 - norm.cdf(t)

    # Bonferroni correction
    p_adj = min(1.0, p * n_trials)

    # Adjusted threshold
    if p_adj < 1.0:
        t_adj = float(norm.ppf(1.0 - p_adj))
    else:
        t_adj = 0.0

    # Convert adjusted t back to annual SR
    sr_haircut = (t_adj / math.sqrt(n_monthly)) * math.sqrt(12.0)

    # Clamp: haircut can't inflate the SR
    sr_haircut = min(sr_haircut, sr_observed)
    sr_haircut = max(sr_haircut, 0.0)

    haircut_pct = (sr_observed - sr_haircut) / sr_observed

    return {
        "sr_observed": sr_observed,
        "sr_haircut": sr_haircut,
        "haircut_pct": haircut_pct,
        "n_trials": n_trials,
        "n_obs": n_obs,
        "freq": freq,
    }


def haircut_ic_ir(
    conn: Any,
    ic_ir_observed: float,
    n_obs: int,
    indicator_name: Optional[str] = None,
    tf: Optional[str] = None,
) -> dict[str, Any]:
    """Apply Harvey & Liu (2015) Bonferroni haircut to an IC-IR value.

    IC-IR (information ratio of the IC time series) has the same mathematical
    structure as a Sharpe ratio, so the Bonferroni method applies directly.
    The number of trials is fetched from trial_registry via get_trial_count().

    When ``indicator_name`` and ``tf`` are both provided and ``conn`` is not None,
    the haircutted IC-IR is written back to trial_registry.haircut_ic_ir.

    Args:
        conn:             DB connection (SQLAlchemy or psycopg2). May be None for
                          pure-computation use without a DB write.
        ic_ir_observed:   Observed IC-IR (mean IC / std IC over N observations).
        n_obs:            Number of IC observations used to compute the IC-IR.
        indicator_name:   Indicator name key in trial_registry. Required for DB write.
        tf:               Timeframe key in trial_registry. Required for DB write.

    Returns:
        dict with keys:
            ic_ir_observed  -- input value
            ic_ir_haircut   -- adjusted IC-IR
            haircut_pct     -- fractional reduction (0-1)
            n_trials        -- fetched from trial_registry
            n_obs           -- input value
    """
    n_trials = get_trial_count(conn)

    # Edge cases
    if ic_ir_observed <= 0.0:
        result = {
            "ic_ir_observed": ic_ir_observed,
            "ic_ir_haircut": 0.0,
            "haircut_pct": 0.0,
            "n_trials": n_trials,
            "n_obs": n_obs,
        }
        return result

    if n_trials <= 0:
        return {
            "ic_ir_observed": ic_ir_observed,
            "ic_ir_haircut": ic_ir_observed,
            "haircut_pct": 0.0,
            "n_trials": n_trials,
            "n_obs": n_obs,
        }

    if n_obs <= 0:
        return {
            "ic_ir_observed": ic_ir_observed,
            "ic_ir_haircut": 0.0,
            "haircut_pct": 1.0,
            "n_trials": n_trials,
            "n_obs": n_obs,
        }

    # Same structure as Sharpe: IC-IR = mean_IC / std_IC ~ t / sqrt(n)
    t = ic_ir_observed * math.sqrt(n_obs)
    p = 1.0 - norm.cdf(t)
    p_adj = min(1.0, p * n_trials)

    if p_adj < 1.0:
        t_adj = float(norm.ppf(1.0 - p_adj))
    else:
        t_adj = 0.0

    ic_ir_haircut = t_adj / math.sqrt(n_obs)

    # Clamp: haircut can't inflate the IC-IR
    ic_ir_haircut = min(ic_ir_haircut, ic_ir_observed)
    ic_ir_haircut = max(ic_ir_haircut, 0.0)

    haircut_pct = (ic_ir_observed - ic_ir_haircut) / ic_ir_observed

    # Persist to DB if conn + keys supplied
    if conn is not None and indicator_name is not None and tf is not None:
        try:
            try:
                from sqlalchemy import text as _text

                conn.execute(
                    _text(
                        "UPDATE trial_registry "
                        "SET haircut_ic_ir = :v "
                        "WHERE indicator_name = :ind AND tf = :tf"
                    ),
                    {"v": ic_ir_haircut, "ind": indicator_name, "tf": tf},
                )
            except Exception:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE trial_registry "
                    "SET haircut_ic_ir = %s "
                    "WHERE indicator_name = %s AND tf = %s",
                    (ic_ir_haircut, indicator_name, tf),
                )
        except Exception as exc:
            logger.warning(
                "haircut_ic_ir DB write failed for %s/%s: %s",
                indicator_name,
                tf,
                exc,
            )

    return {
        "ic_ir_observed": ic_ir_observed,
        "ic_ir_haircut": ic_ir_haircut,
        "haircut_pct": haircut_pct,
        "n_trials": n_trials,
        "n_obs": n_obs,
    }


# ---------------------------------------------------------------------------
# Block bootstrap IC confidence interval
# ---------------------------------------------------------------------------


def block_bootstrap_ic(
    feature: np.ndarray,
    fwd_returns: np.ndarray,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """Compute a 95% CI for the IC using a stationary block bootstrap.

    Unlike naive IID bootstrap, block bootstrap preserves the autocorrelation
    structure of the return series, producing wider and more conservative
    confidence intervals when the series is autocorrelated.

    Uses arch 8.0.0 StationaryBootstrap with an adaptive block length estimated
    via optimal_block_length() (Politis & Romano). Column name: "stationary".

    Args:
        feature:     1-D array of feature values (signals).
        fwd_returns: 1-D array of forward returns aligned with ``feature``.
        n_boot:      Number of bootstrap samples. Default 1000.
        seed:        Random seed for reproducibility. Default 42.

    Returns:
        dict with keys:
            ic_obs     -- observed Spearman IC
            ci_lo      -- 2.5th percentile of bootstrap IC distribution
            ci_hi      -- 97.5th percentile of bootstrap IC distribution
            block_len  -- block length used (0 if < 20 obs)
            n_boot     -- actual number of valid bootstrap samples used
            n_obs      -- number of valid (non-NaN) observation pairs
    """
    feat = np.asarray(feature, dtype=float)
    ret = np.asarray(fwd_returns, dtype=float)

    # Drop NaN pairs
    mask = ~(np.isnan(feat) | np.isnan(ret))
    feat_clean = feat[mask]
    ret_clean = ret[mask]
    n_obs = int(len(feat_clean))

    _nan = float("nan")

    if n_obs < 20:
        ic_obs, _ = spearmanr(feat_clean, ret_clean) if n_obs > 1 else (0.0, 1.0)
        return {
            "ic_obs": float(ic_obs),
            "ci_lo": _nan,
            "ci_hi": _nan,
            "block_len": 0,
            "n_boot": 0,
            "n_obs": n_obs,
        }

    # Observed IC
    ic_obs_val, _ = spearmanr(feat_clean, ret_clean)
    ic_obs = float(ic_obs_val)

    # Adaptive block length (arch 8.0.0 column: "stationary")
    try:
        opt = optimal_block_length(ret_clean)
        raw_bl = float(opt["stationary"].iloc[0])
        if math.isnan(raw_bl) or raw_bl <= 0.0:
            raw_bl = 1.0
        block_len = max(1, int(math.ceil(raw_bl)))
    except Exception as exc:
        logger.warning("optimal_block_length failed (%s); using block_len=1", exc)
        block_len = 1

    # Stationary block bootstrap — resample pair indices jointly so that the
    # feature/return alignment is preserved across bootstrap samples.
    # Using ret_clean as the data arg to drive block structure; then apply the
    # same indices (bs.index) to both feat_clean and ret_clean.
    bs = StationaryBootstrap(block_len, ret_clean, seed=seed)

    boot_ics: list[float] = []
    for _, _ in bs.bootstrap(n_boot):
        # bs.index contains the current bootstrap sample indices
        idx = bs.index
        if len(idx) != n_obs:
            continue
        boot_feat = feat_clean[idx]
        boot_ret = ret_clean[idx]
        ic_b, _ = spearmanr(boot_feat, boot_ret)
        boot_ics.append(float(ic_b))

    if len(boot_ics) == 0:
        return {
            "ic_obs": ic_obs,
            "ci_lo": _nan,
            "ci_hi": _nan,
            "block_len": block_len,
            "n_boot": 0,
            "n_obs": n_obs,
        }

    arr = np.array(boot_ics)
    ci_lo = float(np.percentile(arr, 2.5))
    ci_hi = float(np.percentile(arr, 97.5))

    return {
        "ic_obs": ic_obs,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "block_len": block_len,
        "n_boot": len(boot_ics),
        "n_obs": n_obs,
    }
