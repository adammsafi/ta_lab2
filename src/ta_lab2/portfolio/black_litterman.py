"""
Black-Litterman allocation module.

Combines a market-cap-implied equilibrium prior with IC-IR weighted signal views
to produce posterior expected returns (bl_returns) and a posterior covariance
(bl_cov).  The posterior feeds PyPortfolioOpt's EfficientFrontier for max_sharpe
or min_volatility optimization.

ASCII-only file -- no UTF-8 box-drawing characters.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

from pypfopt import EfficientFrontier, black_litterman, risk_models
from pypfopt.black_litterman import BlackLittermanModel
from pypfopt.exceptions import OptimizationError

from ta_lab2.portfolio import load_portfolio_config

logger = logging.getLogger(__name__)


class BLAllocationBuilder:
    """
    Build a Black-Litterman posterior allocation from market cap prior and signal views.

    Workflow
    --------
    1. signals_to_mu()  -- IC-IR weighted composite -> cross-sectional z-score -> return scale
    2. build_views()    -- signal scores + IC-IR -> absolute views + view confidences
    3. run()            -- market cap prior + views -> posterior weights via EfficientFrontier

    Configuration (portfolio.yaml -> black_litterman section)
    ----------------------------------------------------------
    tau                 : float, default 0.05.  Uncertainty of the prior.
    use_idzorek         : bool, default True.   Idzorek omega = confidence-to-uncertainty map.
    min_view_confidence : float, default 0.2.   Lower bound for normalized view confidence.
    max_view_confidence : float, default 0.8.   Upper bound for normalized view confidence.
    views_source        : str, default 'all_active'. Which signals to include as views.
    """

    # Minimum IC-IR threshold to include a signal as a BL view.
    _MIN_IC_IR_FOR_VIEW: float = 0.1

    def __init__(self, config: Optional[dict] = None) -> None:
        if config is None:
            config = load_portfolio_config()

        bl_cfg = config.get("black_litterman", {})
        self.tau: float = float(bl_cfg.get("tau", 0.05))
        self.use_idzorek: bool = bool(bl_cfg.get("use_idzorek", True))
        self.min_view_confidence: float = float(bl_cfg.get("min_view_confidence", 0.2))
        self.max_view_confidence: float = float(bl_cfg.get("max_view_confidence", 0.8))
        self.views_source: str = str(bl_cfg.get("views_source", "all_active"))

        # Extract max_position_pct from optimizer section for weight bounds.
        opt_cfg = config.get("optimizer", {})
        self.max_position_pct: float = float(opt_cfg.get("max_position_pct", 0.15))

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def signals_to_mu(
        self,
        signal_scores: pd.DataFrame,
        ic_ir: pd.Series,
        base_vol: pd.Series,
    ) -> pd.Series:
        """
        Convert IC-IR weighted signal scores to expected return estimates.

        Parameters
        ----------
        signal_scores : pd.DataFrame
            Index = asset_id, columns = signal types (e.g. 'rsi', 'ema_cross').
            Values are raw signal scores (e.g. in [-1, 1] or [0, 1]).
        ic_ir : pd.Series
            Index = signal_type, values = rolling IC-IR for each signal.
        base_vol : pd.Series
            Index = asset_id, values = annualized volatility per asset.

        Returns
        -------
        pd.Series
            Index = asset_id.  Expected return estimates at return scale.
        """
        # Step 1: clip IC-IR to >= 0 (negative IC-IR = noisy signal, ignore).
        ic_ir_clipped = ic_ir.clip(lower=0)
        total = ic_ir_clipped.sum()

        if total == 0:
            # No signal has positive IC-IR: return zero expected alpha for all assets.
            logger.warning(
                "signals_to_mu: all IC-IR values are <= 0; returning zero expected returns."
            )
            return pd.Series(0.0, index=signal_scores.index)

        # Step 2: normalize IC-IR weights to sum to 1.0.
        weights = ic_ir_clipped / total

        # Align weights to columns of signal_scores (missing signal types -> 0 weight).
        weights = weights.reindex(signal_scores.columns).fillna(0.0)

        # Step 3: IC-IR weighted composite score per asset.
        composite = signal_scores.mul(weights, axis="columns").sum(axis=1)

        # Step 4: cross-sectional z-score.
        std = composite.std()
        if std < 1e-8:
            logger.warning(
                "signals_to_mu: composite scores are constant; returning zero expected returns."
            )
            return pd.Series(0.0, index=signal_scores.index)

        z = (composite - composite.mean()) / std

        # Step 5: scale to return space via annualized vol (10% of vol = max alpha).
        vol_aligned = base_vol.reindex(signal_scores.index).fillna(base_vol.mean())
        return z * vol_aligned * 0.1

    def build_views(
        self,
        signal_scores: pd.DataFrame,
        ic_ir: pd.Series,
    ) -> tuple[dict, list]:
        """
        Build absolute views dict and view confidence list for BlackLittermanModel.

        Views that have IC-IR <= _MIN_IC_IR_FOR_VIEW are excluded.
        View confidences are normalized to [min_view_confidence, max_view_confidence].

        Parameters
        ----------
        signal_scores : pd.DataFrame
            Index = asset_id, columns = signal types.
        ic_ir : pd.Series
            Index = signal_type, rolling IC-IR per signal.

        Returns
        -------
        tuple[dict, list]
            (absolute_views, view_confidences)
            absolute_views  : dict[asset_id -> expected_return_float]
            view_confidences: list[float] ordered the same as absolute_views.keys()
        """
        # Filter to signals with IC-IR above threshold.
        qualified = ic_ir[ic_ir > self._MIN_IC_IR_FOR_VIEW]

        if qualified.empty:
            logger.warning(
                "build_views: no signal types with IC-IR > %.2f; returning empty views.",
                self._MIN_IC_IR_FOR_VIEW,
            )
            return {}, []

        # Restrict signal_scores to qualified signal columns only.
        cols_available = [c for c in qualified.index if c in signal_scores.columns]
        if not cols_available:
            logger.warning(
                "build_views: qualified IC-IR signal types not found in signal_scores columns; "
                "returning empty views."
            )
            return {}, []

        ic_ir_q = qualified[cols_available]
        scores_q = signal_scores[cols_available]

        # Compute IC-IR weighted composite per asset (same as signals_to_mu but no vol scaling).
        total = ic_ir_q.clip(lower=0).sum()
        weights = ic_ir_q.clip(lower=0) / total
        composite = scores_q.mul(weights, axis="columns").sum(axis=1)

        # Cross-sectional z-score, then return as absolute view dict.
        std = composite.std()
        if std < 1e-8:
            composite_norm = composite * 0.0
        else:
            composite_norm = (composite - composite.mean()) / std

        absolute_views = composite_norm.to_dict()

        # Normalize IC-IR to [min_conf, max_conf] range via min-max scaling.
        ir_vals = ic_ir_q.clip(lower=0)
        ir_min, ir_max = ir_vals.min(), ir_vals.max()

        conf_range = self.max_view_confidence - self.min_view_confidence

        if ir_max - ir_min < 1e-8:
            # All IC-IR values are identical: assign midpoint confidence uniformly.
            asset_confidences = {
                asset: (self.min_view_confidence + self.max_view_confidence) / 2.0
                for asset in absolute_views
            }
        else:
            # Per-asset confidence derived from the signal-type IC-IR values.
            # Use a single scalar confidence per asset = weighted mean IR -> normalized.
            per_signal_conf = (
                self.min_view_confidence
                + (ir_vals - ir_min) / (ir_max - ir_min) * conf_range
            )
            # Each asset shares the same view confidence (weighted average of per-signal).
            mean_conf = float(per_signal_conf.mul(weights).sum())
            asset_confidences = {asset: mean_conf for asset in absolute_views}

        view_confidences = [asset_confidences[asset] for asset in absolute_views]

        return absolute_views, view_confidences

    def run(
        self,
        prices: pd.DataFrame,
        market_caps: pd.Series,
        signal_scores: pd.DataFrame,
        ic_ir: pd.Series,
        base_vol: pd.Series,
        S: Optional[pd.DataFrame] = None,
        tf: str = "1D",
    ) -> dict:
        """
        Build a Black-Litterman posterior allocation.

        Parameters
        ----------
        prices : pd.DataFrame
            DatetimeIndex x asset columns, close prices.
        market_caps : pd.Series
            asset -> latest market cap at the same timestamp for all assets.
        signal_scores : pd.DataFrame
            asset x signal_type score matrix.
        ic_ir : pd.Series
            signal_type -> rolling IC-IR.
        base_vol : pd.Series
            asset -> annualized volatility.
        S : pd.DataFrame or None
            Pre-computed shrinkage covariance from PortfolioOptimizer.run_all().
            If None, computed here via Ledoit-Wolf on the provided prices.
        tf : str
            Timeframe key (only used when S is None for adaptive lookback).

        Returns
        -------
        dict with keys:
            bl              -- dict of posterior weights (clean_weights)
            bl_returns      -- pd.Series of posterior expected returns
            bl_cov          -- pd.DataFrame of posterior covariance
            prior           -- pd.Series of market-implied prior returns
            views           -- dict of absolute views used
            view_confidences -- list of confidence scalars per view
        """
        # Step 1: Resolve covariance matrix.
        if S is None:
            tf_days = _resolve_tf_days(tf)
            lookback_bars = round(180 / tf_days)  # default 180-day lookback
            prices_window = prices.tail(lookback_bars)
            S = risk_models.CovarianceShrinkage(prices_window).ledoit_wolf()
            logger.debug(
                "run: computed S via Ledoit-Wolf (tf=%s, lookback_bars=%d).",
                tf,
                lookback_bars,
            )
        else:
            prices_window = prices

        # Align assets: keep only assets present in both S and market_caps.
        common_assets = [a for a in S.columns if a in market_caps.index]
        if not common_assets:
            raise ValueError(
                "run: no common assets between covariance matrix and market_caps. "
                "Check that prices and market_caps use the same asset identifiers."
            )
        S_aligned = S.loc[common_assets, common_assets]
        mcaps_aligned = market_caps.reindex(common_assets).fillna(market_caps.min())

        # Step 2: Market-implied prior returns.
        delta = black_litterman.market_implied_risk_aversion(
            prices_window[common_assets]
        )
        prior = black_litterman.market_implied_prior_returns(
            mcaps_aligned, delta, S_aligned
        )

        # Step 3: Build views from signal scores.
        scores_aligned = signal_scores.reindex(common_assets)
        ic_ir_clean = ic_ir.dropna()
        absolute_views, view_confidences = self.build_views(scores_aligned, ic_ir_clean)

        # Step 4: If no views pass the threshold, optimize on prior returns directly.
        if not absolute_views:
            logger.warning(
                "run: no views passed the IC-IR threshold; "
                "returning prior-only EfficientFrontier weights."
            )
            n_assets = len(common_assets)
            effective_max = max(self.max_position_pct, 1.0 / n_assets)
            try:
                ef = EfficientFrontier(
                    prior, S_aligned, weight_bounds=(0, effective_max)
                )
                ef.max_sharpe()
                bl_weights = dict(ef.clean_weights())
            except OptimizationError:
                ef2 = EfficientFrontier(
                    prior, S_aligned, weight_bounds=(0, effective_max)
                )
                ef2.min_volatility()
                bl_weights = dict(ef2.clean_weights())

            return {
                "bl": bl_weights,
                "bl_returns": prior,
                "bl_cov": S_aligned,
                "prior": prior,
                "views": {},
                "view_confidences": [],
            }

        # Step 5: Construct BlackLittermanModel.
        omega_param = "idzorek" if self.use_idzorek else None
        bl_model = BlackLittermanModel(
            S_aligned,
            pi=prior,
            absolute_views=absolute_views,
            omega=omega_param,
            view_confidences=view_confidences,
            tau=self.tau,
        )
        bl_returns = bl_model.bl_returns()
        bl_cov = bl_model.bl_cov()

        # Step 6: Optimize posterior via EfficientFrontier.
        n_assets = len(common_assets)
        effective_max = max(self.max_position_pct, 1.0 / n_assets)

        try:
            ef = EfficientFrontier(bl_returns, bl_cov, weight_bounds=(0, effective_max))
            ef.max_sharpe()
            bl_weights = dict(ef.clean_weights())
            logger.debug("run: max_sharpe succeeded.")
        except OptimizationError as exc:
            logger.info(
                "run: BL max_sharpe failed (%s); falling back to min_volatility.", exc
            )
            try:
                ef2 = EfficientFrontier(
                    bl_returns, bl_cov, weight_bounds=(0, effective_max)
                )
                ef2.min_volatility()
                bl_weights = dict(ef2.clean_weights())
                logger.debug("run: min_volatility fallback succeeded.")
            except OptimizationError as exc2:
                logger.warning(
                    "run: both max_sharpe and min_volatility failed (%s); "
                    "returning prior-only weights.",
                    exc2,
                )
                n_assets = len(common_assets)
                effective_max = max(self.max_position_pct, 1.0 / n_assets)
                ef3 = EfficientFrontier(
                    prior, S_aligned, weight_bounds=(0, effective_max)
                )
                ef3.min_volatility()
                bl_weights = dict(ef3.clean_weights())

        return {
            "bl": bl_weights,
            "bl_returns": bl_returns,
            "bl_cov": bl_cov,
            "prior": prior,
            "views": absolute_views,
            "view_confidences": view_confidences,
        }


# ---------------------------------------------------------------------------
# TF-days fallback (mirrors optimizer.py pattern for offline operation)
# ---------------------------------------------------------------------------

_TF_DAYS_FALLBACK: dict[str, float] = {
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

    Tries DimTimeframe.from_db() first; falls back to hardcoded map.
    """
    try:
        import os

        db_url = os.environ.get("TARGET_DB_URL") or os.environ.get("DATABASE_URL")
        if db_url:
            from ta_lab2.time.dim_timeframe import DimTimeframe

            dim = DimTimeframe.from_db(db_url)
            return float(dim.tf_days(tf))
    except Exception as exc:  # noqa: BLE001
        logger.debug("DimTimeframe DB lookup failed (%s); using fallback map.", exc)

    if tf in _TF_DAYS_FALLBACK:
        return _TF_DAYS_FALLBACK[tf]

    raise KeyError(
        f"Unknown timeframe {tf!r}. "
        "Add it to _TF_DAYS_FALLBACK in black_litterman.py or ensure DB connectivity."
    )
