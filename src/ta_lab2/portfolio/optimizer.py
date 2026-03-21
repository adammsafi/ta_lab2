"""
Portfolio optimizer: Mean-Variance, CVaR, and HRP wrappers with regime routing.

Regime routing selects the active optimizer based on a regime label supplied by
the caller.  Ill-conditioned covariance matrices automatically fall back to HRP
which does not require matrix inversion.

ASCII-only file -- no UTF-8 box-drawing characters.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pypfopt import (
    EfficientCVaR,
    EfficientFrontier,
    HRPOpt,
    expected_returns,
    risk_models,
)
from pypfopt.exceptions import OptimizationError

from ta_lab2.portfolio import load_portfolio_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded fallback TF->days map used when DimTimeframe DB is not available.
# Keys match the canonical tf strings used in the pipeline.
# Values are tf_days_nominal (fractional days allowed for intraday TFs).
# ---------------------------------------------------------------------------
_TF_DAYS_FALLBACK: Dict[str, float] = {
    "1m": 1.0 / 1440,
    "5m": 1.0 / 288,
    "15m": 1.0 / 96,
    "30m": 1.0 / 48,
    "1H": 1.0 / 24,
    "2H": 1.0 / 12,
    "4H": 1.0 / 6,
    "6H": 0.25,
    "8H": 1.0 / 3,
    "12H": 0.5,
    "1D": 1.0,
    "2D": 2.0,
    "3D": 3.0,
    "5D": 5.0,
    "7D": 7.0,
    "1W": 7.0,
    "2W": 14.0,
    "1M": 30.0,
    "3M": 91.0,
    "6M": 182.0,
    "1Y": 365.0,
}


def _resolve_tf_days(tf: str) -> float:
    """
    Return tf_days_nominal for *tf*.

    Tries DimTimeframe.from_db() first (requires DB_URL env var).  Falls back
    to the hardcoded map so that the optimizer can run without a live DB
    connection (unit tests, offline analysis).
    """
    # Try DB-backed lookup first.
    try:
        import os

        db_url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
        if db_url:
            from ta_lab2.time.dim_timeframe import DimTimeframe

            dim = DimTimeframe.from_db(db_url)
            return float(dim.tf_days(tf))
    except Exception as exc:  # noqa: BLE001
        logger.debug("DimTimeframe DB lookup failed (%s); using fallback map.", exc)

    # Fallback to hardcoded map.
    if tf in _TF_DAYS_FALLBACK:
        return _TF_DAYS_FALLBACK[tf]

    raise KeyError(
        f"Unknown timeframe {tf!r}. "
        "Add it to _TF_DAYS_FALLBACK in optimizer.py or ensure DB connectivity."
    )


class PortfolioOptimizer:
    """
    Wraps PyPortfolioOpt's three optimizers with regime-conditional routing.

    Optimizers supported
    --------------------
    mv   -- Mean-Variance (Markowitz) with Ledoit-Wolf shrinkage covariance.
    cvar -- Conditional Value-at-Risk minimization.
    hrp  -- Hierarchical Risk Parity (no matrix inversion required).

    Regime routing
    --------------
    A regime label (e.g. 'bear', 'stable', 'uncertain') is mapped to an
    optimizer via the ``regime_routing`` section of portfolio.yaml.

    Fallback chain
    --------------
    1. If the covariance condition number exceeds ``condition_number_threshold``
       the active optimizer is overridden to 'hrp' (logged as a warning).
    2. If max_sharpe() fails, a fresh EfficientFrontier runs min_volatility().
    3. If the regime-selected optimizer returned None weights, falls back to hrp.
    """

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self, config: Optional[dict] = None) -> None:
        if config is None:
            config = load_portfolio_config()

        opt_cfg = config.get("optimizer", {})
        self.lookback_calendar_days: int = int(
            opt_cfg.get("lookback_calendar_days", 180)
        )
        self.min_lookback_bars: int = int(opt_cfg.get("min_lookback_bars", 60))
        self.max_position_pct: float = float(opt_cfg.get("max_position_pct", 0.15))
        self.max_gross_exposure: float = float(opt_cfg.get("max_gross_exposure", 1.5))
        self.cvar_beta: float = float(opt_cfg.get("cvar_beta", 0.95))
        self.condition_number_threshold: float = float(
            opt_cfg.get("condition_number_threshold", 1000)
        )

        rr = config.get("regime_routing", {})
        self._regime_routing: Dict[str, str] = {k: str(v) for k, v in rr.items()}
        self._default_optimizer: str = self._regime_routing.get("default", "hrp")

        # High-correlation regime covariance override config
        hco = config.get("high_corr_override", {})
        self._high_corr_override_enabled: bool = bool(hco.get("enabled", True))
        self._high_corr_blend_factor: float = float(hco.get("blend_factor", 0.3))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(
        self,
        prices: pd.DataFrame,
        regime_label: Optional[str] = None,
        tf: str = "1D",
    ) -> dict:
        """
        Run all three optimizers and return a unified result dict.

        Parameters
        ----------
        prices : pd.DataFrame
            DatetimeIndex rows x asset columns, values are close prices.
        regime_label : str or None
            Current regime (e.g. 'bear', 'stable', 'uncertain').  If None
            the config default is used.
        tf : str
            Timeframe key (e.g. '1D', '4H').  Used to convert the calendar-day
            lookback window into a number of bars.

        Returns
        -------
        dict with keys:
            mv              -- dict of weights, or None if optimization failed
            cvar            -- dict of weights, or None if optimization failed
            hrp             -- dict of weights (HRP rarely fails)
            active          -- name of the recommended optimizer ('mv'/'cvar'/'hrp')
            condition_number -- float
            ill_conditioned  -- bool
            mu               -- pd.Series of expected returns
            S                -- pd.DataFrame covariance matrix
        """
        # --- Adaptive lookback -----------------------------------------
        tf_days = _resolve_tf_days(tf)
        lookback_bars = round(self.lookback_calendar_days / tf_days)

        if lookback_bars < self.min_lookback_bars:
            raise ValueError(
                f"Computed lookback_bars={lookback_bars} for tf={tf!r} is below "
                f"min_lookback_bars={self.min_lookback_bars}.  "
                f"Provide a higher-frequency timeframe or more history."
            )

        prices_window = prices.tail(lookback_bars)

        logger.debug(
            "run_all: tf=%s tf_days=%.4f lookback_bars=%d prices_window=%d rows",
            tf,
            tf_days,
            lookback_bars,
            len(prices_window),
        )

        # --- Expected returns and covariance ----------------------------
        mu: pd.Series = expected_returns.ema_historical_return(
            prices_window, span=lookback_bars
        )
        S: pd.DataFrame = risk_models.CovarianceShrinkage(prices_window).ledoit_wolf()

        # --- High-correlation regime covariance override ----------------
        S = self._apply_high_corr_override(S)

        # --- Condition number check -------------------------------------
        cond_number = float(np.linalg.cond(S.values))
        ill_conditioned = cond_number > self.condition_number_threshold

        if ill_conditioned:
            logger.warning(
                "Covariance condition number %.1f exceeds threshold %.1f; "
                "HRP auto-fallback will be applied.",
                cond_number,
                self.condition_number_threshold,
            )

        # --- Weight bounds (dynamic floor to guarantee feasibility) -----
        n_assets = len(prices_window.columns)
        effective_max = max(self.max_position_pct, 1.0 / n_assets)

        # --- Run each optimizer -----------------------------------------
        returns_df = expected_returns.returns_from_prices(prices_window)

        weights_mv = self._run_mv(mu, S, effective_max)
        weights_cvar = self._run_cvar(mu, returns_df, effective_max)
        weights_hrp = self._run_hrp(returns_df, S)

        # --- Select active optimizer ------------------------------------
        results = {"mv": weights_mv, "cvar": weights_cvar, "hrp": weights_hrp}
        active = self._select_active(regime_label, ill_conditioned, results)

        return {
            "mv": weights_mv,
            "cvar": weights_cvar,
            "hrp": weights_hrp,
            "active": active,
            "condition_number": cond_number,
            "ill_conditioned": ill_conditioned,
            "mu": mu,
            "S": S,
        }

    def get_active_weights(self, result: dict) -> dict:
        """
        Extract the weights for the active optimizer from a run_all() result.

        Returns an empty dict if the active optimizer's weights are None.
        """
        active = result.get("active", "hrp")
        w = result.get(active)
        return w if w is not None else {}

    # ------------------------------------------------------------------
    # High-correlation regime covariance override
    # ------------------------------------------------------------------

    def _apply_high_corr_override(self, S: pd.DataFrame) -> pd.DataFrame:
        """Inflate off-diagonal covariance when high_corr_flag is True in DB.

        When the cross-asset high-correlation regime is active (as signaled by
        cross_asset_agg.high_corr_flag), blending the covariance matrix
        toward a fully-correlated matrix reduces the illusory diversification
        benefit that optimizers might otherwise exploit.

        Blend formula:
            S_adjusted = (1 - blend_factor) * S + blend_factor * S_full_corr

        where S_full_corr has the same diagonal (variances) as S but
        off-diagonal entries set to sqrt(var_i * var_j) (correlation = 1.0).

        Parameters
        ----------
        S:
            Covariance matrix computed by the Ledoit-Wolf shrinkage estimator.

        Returns
        -------
        Adjusted covariance matrix (same shape and index/columns as input),
        or S unchanged if the override is disabled or not applicable.
        """
        # Check master switch
        if not self._high_corr_override_enabled:
            logger.info("high_corr_override disabled in config; skipping.")
            return S

        # Query latest high_corr_flag from cross_asset_agg
        high_corr_flag: Optional[bool] = None
        avg_pairwise_corr: Optional[float] = None
        try:
            import os

            db_url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
            if db_url:
                from sqlalchemy import create_engine, text

                engine = create_engine(db_url)
                with engine.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT high_corr_flag, avg_pairwise_corr_30d "
                            "FROM cross_asset_agg "
                            "ORDER BY date DESC LIMIT 1"
                        )
                    ).fetchone()
                if row is not None:
                    high_corr_flag = bool(row[0]) if row[0] is not None else None
                    avg_pairwise_corr = float(row[1]) if row[1] is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "high_corr_override: DB query failed (%s); skipping override.", exc
            )
            return S

        if high_corr_flag is not True:
            # Flag is False, NULL, or DB had no data -- no override
            return S

        # Build fully-correlated covariance matrix (correlation = 1 for all pairs)
        variances = np.diag(S.values)  # shape (n,)
        std_devs = np.sqrt(np.maximum(variances, 0.0))  # shape (n,)
        # S_full_corr[i, j] = std_i * std_j  (correlation = 1.0)
        S_full_corr = np.outer(std_devs, std_devs)

        blend = self._high_corr_blend_factor
        S_adj_values = (1.0 - blend) * S.values + blend * S_full_corr

        logger.warning(
            "High-correlation regime detected (avg_pairwise_corr=%.3f); "
            "inflating off-diagonal covariance by blend_factor=%.2f",
            avg_pairwise_corr if avg_pairwise_corr is not None else float("nan"),
            blend,
        )

        return pd.DataFrame(S_adj_values, index=S.index, columns=S.columns)

    # ------------------------------------------------------------------
    # Internal optimizer runners (each uses a FRESH instance)
    # ------------------------------------------------------------------

    def _run_mv(
        self,
        mu: pd.Series,
        S: pd.DataFrame,
        effective_max: float,
    ) -> Optional[dict]:
        """
        Mean-Variance optimizer.

        Tries max_sharpe() first; falls back to min_volatility() on a fresh
        EfficientFrontier instance if the first call raises OptimizationError.
        """
        try:
            ef = EfficientFrontier(mu, S, weight_bounds=(0, effective_max))
            ef.max_sharpe()
            return dict(ef.clean_weights())
        except OptimizationError as exc:
            logger.info(
                "MV max_sharpe failed (%s); trying min_volatility fallback.", exc
            )

        try:
            ef2 = EfficientFrontier(mu, S, weight_bounds=(0, effective_max))
            ef2.min_volatility()
            return dict(ef2.clean_weights())
        except OptimizationError as exc:
            logger.warning("MV min_volatility fallback also failed: %s", exc)
            return None

    def _run_cvar(
        self,
        mu: pd.Series,
        returns_df: pd.DataFrame,
        effective_max: float,
    ) -> Optional[dict]:
        """
        CVaR (Conditional Value-at-Risk) optimizer.
        """
        try:
            ef_cvar = EfficientCVaR(
                mu,
                returns_df,
                beta=self.cvar_beta,
                weight_bounds=(0, effective_max),
            )
            ef_cvar.min_cvar()
            return dict(ef_cvar.clean_weights())
        except Exception as exc:  # noqa: BLE001
            logger.warning("CVaR optimization failed: %s", exc)
            return None

    def _run_hrp(
        self,
        returns_df: pd.DataFrame,
        S: pd.DataFrame,
    ) -> Optional[dict]:
        """
        Hierarchical Risk Parity optimizer.

        Filters both returns_df and S to their common asset columns to avoid
        shape mismatches when assets differ between the two inputs.
        """
        try:
            common = [c for c in returns_df.columns if c in S.columns]
            hrp = HRPOpt(
                returns=returns_df[common],
                cov_matrix=S.loc[common, common],
            )
            hrp.optimize(linkage_method="ward")
            return dict(hrp.clean_weights())
        except Exception as exc:  # noqa: BLE001
            logger.warning("HRP optimization failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Regime routing
    # ------------------------------------------------------------------

    def _select_active(
        self,
        regime_label: Optional[str],
        ill_conditioned: bool,
        results: dict,
    ) -> str:
        """
        Select the active optimizer name from the result dict.

        Priority:
        1. Ill-conditioned matrix -> always 'hrp'.
        2. Regime routing table lookup (or config default if label is unknown).
        3. If the selected optimizer returned None weights, fall back to 'hrp'.
        """
        if ill_conditioned:
            logger.warning(
                "Ill-conditioned covariance: forcing active optimizer to 'hrp'."
            )
            return "hrp"

        if regime_label is not None and regime_label in self._regime_routing:
            selected = self._regime_routing[regime_label]
        else:
            selected = self._default_optimizer
            if regime_label is not None:
                logger.debug(
                    "Regime label %r not in routing table; using default %r.",
                    regime_label,
                    selected,
                )

        if results.get(selected) is None:
            logger.warning(
                "Selected optimizer %r returned None; falling back to 'hrp'.",
                selected,
            )
            return "hrp"

        return selected
