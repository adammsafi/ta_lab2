"""
Proprietary composite indicator formulas for Phase 106.

Each composite combines multiple data sources (AMA/KAMA, CTF agreement,
Hyperliquid OI/funding, cross-asset lead-lag IC, multi-TF alignment, volume)
into a single feature column that captures interactions invisible to any
single-source indicator.

Module structure
----------------
Private input loaders (_load_*)
    Low-level SQL helpers that return DataFrames/Series with UTC DatetimeIndex.
    All use sqlalchemy.text() and pd.to_datetime(utc=True) per project convention.

Composite compute functions (compute_*)
    One function per proprietary indicator.  Each accepts a SQLAlchemy connection
    (Engine.connect() context) plus asset parameters, and returns a pd.Series
    with a UTC DatetimeIndex and the output column name as .name.
    All are NaN-safe: missing data causes NaN output, never a raised exception.

Module-level registry
    COMPOSITE_NAMES   list[str]                      -- ordered column names
    ALL_COMPOSITES    dict[str, Callable]             -- name -> compute function

Notes
-----
- ASCII-only comments (Windows cp1252 compatibility).
- No cmc_ prefix on table names except genuine CMC-only tables.
- venue_id=1 (CMC_AGG) is the default for analytics tables.
- HL tables live in the hyperliquid schema.
- Rolling windows are applied with min_periods to avoid silent all-NaN Series.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output column names (authoritative list)
# ---------------------------------------------------------------------------
COMPOSITE_NAMES: list[str] = [
    "ama_er_regime_signal",
    "oi_divergence_ctf_agreement",
    "funding_adjusted_momentum",
    "cross_asset_lead_lag_composite",
    "tf_alignment_score",
    "volume_regime_gated_trend",
]

# ---------------------------------------------------------------------------
# Internal rolling z-score helper
# ---------------------------------------------------------------------------


def _rolling_zscore(series: pd.Series, window: int, min_periods: int = 20) -> pd.Series:
    """Compute rolling z-score: (x - mean) / std over a trailing window.

    Returns NaN where std == 0 or insufficient observations.

    Parameters
    ----------
    series:
        Input series with DatetimeIndex.
    window:
        Rolling window size in bars.
    min_periods:
        Minimum observations required to compute a value.

    Returns
    -------
    pd.Series of the same index, dtype float.
    """
    rm = series.rolling(window, min_periods=min_periods).mean()
    rs = series.rolling(window, min_periods=min_periods).std()
    return (series - rm) / rs.replace(0.0, np.nan)


# ---------------------------------------------------------------------------
# Private input loaders
# ---------------------------------------------------------------------------


def _load_ama_er(conn, asset_id: int, venue_id: int, tf: str) -> pd.DataFrame:
    """Load KAMA (er + ama values) from ama_multi_tf for a single asset/tf.

    Filters to indicator='KAMA' and non-null er.  Returns a DataFrame indexed
    by UTC ts with columns ['er', 'ama'].  Empty DataFrame on no data.

    Parameters
    ----------
    conn:
        SQLAlchemy connection (Engine.connect() context).
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Timeframe string (e.g. '1D').
    """
    try:
        df = pd.read_sql(
            text("""
                SELECT ts, er, ama
                FROM public.ama_multi_tf
                WHERE id = :asset_id
                  AND venue_id = :venue_id
                  AND tf = :tf
                  AND indicator = 'KAMA'
                  AND er IS NOT NULL
                ORDER BY ts
            """),
            conn,
            params={"asset_id": asset_id, "venue_id": venue_id, "tf": tf},
        )
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        return df
    except Exception:
        logger.exception(
            "_load_ama_er failed for asset_id=%d venue_id=%d tf=%s",
            asset_id,
            venue_id,
            tf,
        )
        return pd.DataFrame(columns=["er", "ama"])


def _load_price_bars(
    conn, asset_id: int, venue_id: int, tf: str, columns: list[str]
) -> pd.DataFrame:
    """Load selected OHLCV columns from price_bars_multi_tf.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Timeframe string (e.g. '1D').
    columns:
        List of column names to select, subset of [close, open, high, low, volume].

    Returns
    -------
    DataFrame indexed by UTC ts. Empty if no rows.
    """
    safe_cols = [c for c in columns if c in {"close", "open", "high", "low", "volume"}]
    if not safe_cols:
        return pd.DataFrame()

    col_sql = ", ".join(safe_cols)
    try:
        df = pd.read_sql(
            text(f"""
                SELECT ts, {col_sql}
                FROM public.price_bars_multi_tf
                WHERE id = :asset_id
                  AND venue_id = :venue_id
                  AND tf = :tf
                ORDER BY ts
            """),
            conn,
            params={"asset_id": asset_id, "venue_id": venue_id, "tf": tf},
        )
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        return df
    except Exception:
        logger.exception(
            "_load_price_bars failed for asset_id=%d venue_id=%d tf=%s",
            asset_id,
            venue_id,
            tf,
        )
        return pd.DataFrame(columns=safe_cols)


def _resolve_hl_asset_id(conn, cmc_symbol: str) -> Optional[int]:
    """Resolve a CMC ticker symbol to a Hyperliquid perp asset_id.

    Joins hyperliquid.hl_assets (asset_type='perp', asset_id < 20000 to
    exclude km assets) on symbol match.  Returns None if not found.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    cmc_symbol:
        Ticker symbol as it appears on Hyperliquid (e.g. 'BTC', 'ETH').

    Returns
    -------
    int asset_id or None.
    """
    try:
        row = conn.execute(
            text("""
                SELECT asset_id
                FROM hyperliquid.hl_assets
                WHERE symbol = :symbol
                  AND asset_type = 'perp'
                  AND asset_id < 20000
                LIMIT 1
            """),
            {"symbol": cmc_symbol},
        ).fetchone()
        return int(row[0]) if row else None
    except Exception:
        logger.exception("_resolve_hl_asset_id failed for symbol=%s", cmc_symbol)
        return None


def _load_hl_oi(conn, hl_asset_id: int) -> pd.Series:
    """Load Hyperliquid open interest (close OI) as a daily Series.

    Queries hyperliquid.hl_open_interest for the given asset.  Returns a
    pd.Series indexed by UTC ts with the OI values, named 'oi'.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    hl_asset_id:
        Hyperliquid asset_id (from hl_assets).

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex.  Empty on no data.
    """
    try:
        df = pd.read_sql(
            text("""
                SELECT ts, "close" AS oi
                FROM hyperliquid.hl_open_interest
                WHERE asset_id = :asset_id
                ORDER BY ts
            """),
            conn,
            params={"asset_id": hl_asset_id},
        )
        if df.empty:
            return pd.Series(dtype=float, name="oi")
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        s = df["oi"].astype(float)
        s.name = "oi"
        return s
    except Exception:
        logger.exception("_load_hl_oi failed for hl_asset_id=%d", hl_asset_id)
        return pd.Series(dtype=float, name="oi")


def _load_hl_funding(conn, hl_asset_id: int) -> pd.Series:
    """Load Hyperliquid hourly funding rates as a Series.

    Queries hyperliquid.hl_funding_rates for the given asset.  Returns a
    pd.Series indexed by UTC ts with the funding_rate values, named
    'funding_rate'.  Caller handles aggregation to daily.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    hl_asset_id:
        Hyperliquid asset_id (from hl_assets).

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex.  Empty on no data.
    """
    try:
        df = pd.read_sql(
            text("""
                SELECT ts, funding_rate
                FROM hyperliquid.hl_funding_rates
                WHERE asset_id = :asset_id
                ORDER BY ts
            """),
            conn,
            params={"asset_id": hl_asset_id},
        )
        if df.empty:
            return pd.Series(dtype=float, name="funding_rate")
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        s = df["funding_rate"].astype(float)
        s.name = "funding_rate"
        return s
    except Exception:
        logger.exception("_load_hl_funding failed for hl_asset_id=%d", hl_asset_id)
        return pd.Series(dtype=float, name="funding_rate")


def _load_lead_lag_metadata(
    conn,
    target_asset_id: int,
    tf: str,
    horizon: int,
    venue_id: int = 1,
) -> pd.DataFrame:
    """Load significant lead-lag IC rows for a given target (follower) asset.

    Queries lead_lag_ic where asset_b_id=target and is_significant=TRUE.
    asset_a is the predictor; ic is the predictive power at the given horizon.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    target_asset_id:
        CMC asset ID of the follower asset (asset_b in lead_lag_ic).
    tf:
        Timeframe string (e.g. '1D').
    horizon:
        Forward return horizon in bars.
    venue_id:
        Venue ID filter (default 1 = CMC_AGG).

    Returns
    -------
    DataFrame with columns [asset_a_id, feature, ic].  Empty if no significant rows.
    """
    try:
        df = pd.read_sql(
            text("""
                SELECT asset_a_id, feature, ic
                FROM public.lead_lag_ic
                WHERE asset_b_id = :target_asset_id
                  AND tf = :tf
                  AND horizon = :horizon
                  AND venue_id = :venue_id
                  AND is_significant = TRUE
                ORDER BY ABS(ic) DESC
            """),
            conn,
            params={
                "target_asset_id": target_asset_id,
                "tf": tf,
                "horizon": horizon,
                "venue_id": venue_id,
            },
        )
        return df
    except Exception:
        logger.exception(
            "_load_lead_lag_metadata failed for target_asset_id=%d tf=%s horizon=%d",
            target_asset_id,
            tf,
            horizon,
        )
        return pd.DataFrame(columns=["asset_a_id", "feature", "ic"])


def _load_ctf_agreement_col(
    conn,
    asset_id: int,
    base_tf: str,
    ref_tf: str,
    indicator_name: str,
    venue_id: int = 1,
) -> pd.Series:
    """Load a single CTF agreement column from public.ctf.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID.
    base_tf:
        Base timeframe string (e.g. '1D').
    ref_tf:
        Reference timeframe string (e.g. '7D').
    indicator_name:
        Indicator name as stored in dim_ctf_indicators (e.g. 'ret_arith').
    venue_id:
        Venue ID (default 1 = CMC_AGG).

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex named 'agreement'.  Empty on no data.
    """
    try:
        df = pd.read_sql(
            text("""
                SELECT c.ts, c.agreement
                FROM public.ctf c
                JOIN public.dim_ctf_indicators d ON d.indicator_id = c.indicator_id
                WHERE c.id = :asset_id
                  AND c.base_tf = :base_tf
                  AND c.ref_tf = :ref_tf
                  AND c.venue_id = :venue_id
                  AND d.indicator_name = :indicator_name
                  AND c.alignment_source = 'multi_tf'
                ORDER BY c.ts
            """),
            conn,
            params={
                "asset_id": asset_id,
                "base_tf": base_tf,
                "ref_tf": ref_tf,
                "venue_id": venue_id,
                "indicator_name": indicator_name,
            },
        )
        if df.empty:
            return pd.Series(dtype=float, name="agreement")
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        s = df["agreement"].astype(float)
        s.name = f"agreement_{base_tf}_{ref_tf}"
        return s
    except Exception:
        logger.exception(
            "_load_ctf_agreement_col failed for asset_id=%d base_tf=%s ref_tf=%s indicator=%s",
            asset_id,
            base_tf,
            ref_tf,
            indicator_name,
        )
        return pd.Series(dtype=float, name="agreement")


# ---------------------------------------------------------------------------
# Composite 1: AMA ER Regime Signal
# ---------------------------------------------------------------------------


def compute_ama_er_regime_signal(
    conn,
    asset_id: int,
    venue_id: int,
    tf: str,
) -> pd.Series:
    """Kaufman Adaptive Moving Average Efficiency Ratio Regime Signal.

    Financial intuition
    -------------------
    The KAMA Efficiency Ratio (ER) measures how directionally a price series
    moves relative to its volatility.  ER near 1.0 signals a strong trend;
    ER near 0.0 signals choppy sideways price action.  By ranking the ER
    over a rolling 60-bar window we get a percentile score that is robust to
    structural breaks.  Multiplying by the sign of (close - KAMA) gives a
    directionally signed signal: +1 = trending up with high ER, -1 = trending
    down with high ER, values near 0 = low-ER (choppy) environment.

    Formula
    -------
    er_rank  = er.rolling(60, min_periods=20).rank(pct=True)
    direction = sign(close - kama)
    result   = er_rank * direction

    Range
    -----
    [-1.0, +1.0]

    Warmup
    ------
    Requires 20 bars for the first non-NaN output (min_periods=20).
    Stable from bar 60 onward.

    Data coverage
    -------------
    Requires ama_multi_tf with indicator='KAMA' populated for the asset/tf.
    Returns all-NaN Series if KAMA data absent.

    Parameters
    ----------
    conn:
        SQLAlchemy connection (Engine.connect() context).
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Timeframe string (e.g. '1D').

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex, .name='ama_er_regime_signal'.
    """
    out_name = "ama_er_regime_signal"
    _empty = pd.Series(dtype=float, name=out_name)

    try:
        ama_df = _load_ama_er(conn, asset_id, venue_id, tf)
        if ama_df.empty:
            logger.debug(
                "compute_ama_er_regime_signal: no KAMA data for asset_id=%d tf=%s",
                asset_id,
                tf,
            )
            return _empty

        price_df = _load_price_bars(conn, asset_id, venue_id, tf, ["close"])
        if price_df.empty:
            logger.debug(
                "compute_ama_er_regime_signal: no price data for asset_id=%d tf=%s",
                asset_id,
                tf,
            )
            return _empty

        # Align on shared timestamps.
        aligned = pd.concat(
            [ama_df[["er", "ama"]], price_df[["close"]]], axis=1
        ).dropna(subset=["er", "ama", "close"])
        if aligned.empty:
            return _empty

        er = aligned["er"].astype(float)
        kama = aligned["ama"].astype(float)
        close = aligned["close"].astype(float)

        # ER quantile rank over 60-bar rolling window.
        er_rank = er.rolling(60, min_periods=20).rank(pct=True)

        # Direction: +1 above KAMA, -1 below.
        direction = np.sign(close - kama)

        result = (er_rank * direction).rename(out_name)
        return result

    except Exception:
        logger.exception(
            "compute_ama_er_regime_signal failed for asset_id=%d venue_id=%d tf=%s",
            asset_id,
            venue_id,
            tf,
        )
        return _empty


# ---------------------------------------------------------------------------
# Composite 2: OI Divergence x CTF Agreement
# ---------------------------------------------------------------------------


def compute_oi_divergence_ctf_agreement(
    conn,
    asset_id: int,
    venue_id: int,
    tf: str,
    cmc_symbol: str,
) -> pd.Series:
    """Open-Interest Divergence gated by Cross-Timeframe Agreement.

    Financial intuition
    -------------------
    When OI grows faster than price (positive OI divergence) it suggests new
    money is entering the market and the move may continue.  When OI lags
    price, it may be short-covering with no conviction.  Cross-timeframe
    agreement measures whether the trend direction is consistent across time
    horizons; multiplying by CTF agreement gates the divergence signal by
    whether the broader trend is aligned.

    Formula
    -------
    oi_mom   = (oi - oi.shift(5)) / oi.shift(5)              [5-bar OI ROC]
    px_mom   = (close - close.shift(5)) / close.shift(5)     [5-bar price ROC]
    div      = zscore(oi_mom, 60) - zscore(px_mom, 60)       [rolling 60-bar]
    ctf_agr  = ret_arith CTF agreement for base_tf=tf, ref_tf='7D'
    result   = div * ctf_agr

    Range
    -----
    Unbounded (z-score difference * [0,1] fraction).  Typical range [-3, +3].

    Warmup
    ------
    65 bars (60 for rolling z-score + 5 for momentum shift).

    Data coverage
    -------------
    Returns all-NaN Series for assets not listed on Hyperliquid as a perp.
    CTF agreement defaults to 1.0 (no gating) if absent to preserve signal
    when CTF data is missing.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Base timeframe string.
    cmc_symbol:
        CMC ticker (used to resolve HL perp, e.g. 'BTC').

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex, .name='oi_divergence_ctf_agreement'.
    NaN for assets without HL coverage.
    """
    out_name = "oi_divergence_ctf_agreement"
    _empty = pd.Series(dtype=float, name=out_name)

    try:
        hl_asset_id = _resolve_hl_asset_id(conn, cmc_symbol)
        if hl_asset_id is None:
            logger.debug(
                "compute_oi_divergence_ctf_agreement: %s not on HL perp", cmc_symbol
            )
            return _empty

        oi = _load_hl_oi(conn, hl_asset_id)
        if oi.empty:
            return _empty

        price_df = _load_price_bars(conn, asset_id, venue_id, tf, ["close"])
        if price_df.empty:
            return _empty

        # Resample OI to match price tf (daily by default) -- simple forward-fill.
        # Align on common UTC date, keeping daily granularity.
        oi_daily = oi.resample("1D").last().ffill()
        price_daily = price_df["close"].astype(float).resample("1D").last().ffill()

        # Align on shared index.
        aligned = pd.concat(
            [oi_daily.rename("oi"), price_daily.rename("close")], axis=1
        ).dropna()
        if aligned.empty:
            return _empty

        oi_mom = (aligned["oi"] - aligned["oi"].shift(5)) / aligned["oi"].shift(
            5
        ).replace(0.0, np.nan)
        px_mom = (aligned["close"] - aligned["close"].shift(5)) / aligned[
            "close"
        ].shift(5).replace(0.0, np.nan)

        div = _rolling_zscore(oi_mom, 60) - _rolling_zscore(px_mom, 60)

        # Load CTF agreement for ret_arith at ref_tf=7D.
        ctf_agr = _load_ctf_agreement_col(
            conn, asset_id, tf, "7D", "ret_arith", venue_id
        )
        if ctf_agr.empty:
            # No gating if CTF absent -- multiply by 1.0 (neutral).
            ctf_agr_aligned = pd.Series(1.0, index=div.index, name="agreement")
        else:
            # Resample CTF to daily and align.
            ctf_agr_daily = ctf_agr.astype(float).resample("1D").last().ffill()
            ctf_agr_aligned = ctf_agr_daily.reindex(div.index, method="ffill")

        result = (div * ctf_agr_aligned).rename(out_name)
        return result

    except Exception:
        logger.exception(
            "compute_oi_divergence_ctf_agreement failed for asset_id=%d symbol=%s tf=%s",
            asset_id,
            cmc_symbol,
            tf,
        )
        return _empty


# ---------------------------------------------------------------------------
# Composite 3: Funding-Adjusted Momentum
# ---------------------------------------------------------------------------


def compute_funding_adjusted_momentum(
    conn,
    asset_id: int,
    venue_id: int,
    tf: str,
    cmc_symbol: str,
) -> pd.Series:
    """Price Momentum Adjusted for Cumulative Funding Rate Drag.

    Financial intuition
    -------------------
    Perpetual futures funding rates represent the cost of maintaining a
    directional position.  When cumulative funding is high and positive
    (longs paying shorts), longs are being squeezed -- the price momentum
    signal may be overcrowded.  Subtracting the funding z-score from the
    raw momentum z-score yields a signal that is strong only when price is
    moving in a direction not yet reflected in funding costs.

    Formula
    -------
    raw_mom  = (close - close.shift(20)) / close.shift(20)   [20-bar ROC]
    daily_fr = hl_funding_rates aggregated to daily SUM
    cum_fr   = daily_fr.rolling(20).sum()                     [cumulative]
    result   = zscore(raw_mom, 60) - zscore(cum_fr, 60)

    Range
    -----
    Unbounded; typical range [-4, +4].

    Warmup
    ------
    80 bars (60 for rolling z-score + 20 for momentum window).

    Data coverage
    -------------
    Returns all-NaN Series for assets not on Hyperliquid as a perp.
    Funding is aggregated from hourly to daily by DATE_TRUNC-equivalent
    groupby on the Python side (resample('1D').sum()).

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Timeframe string (e.g. '1D').
    cmc_symbol:
        CMC ticker (used to resolve HL perp).

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex, .name='funding_adjusted_momentum'.
    NaN for assets without HL coverage.
    """
    out_name = "funding_adjusted_momentum"
    _empty = pd.Series(dtype=float, name=out_name)

    try:
        hl_asset_id = _resolve_hl_asset_id(conn, cmc_symbol)
        if hl_asset_id is None:
            logger.debug(
                "compute_funding_adjusted_momentum: %s not on HL perp", cmc_symbol
            )
            return _empty

        funding_raw = _load_hl_funding(conn, hl_asset_id)
        if funding_raw.empty:
            return _empty

        price_df = _load_price_bars(conn, asset_id, venue_id, tf, ["close"])
        if price_df.empty:
            return _empty

        # Aggregate funding to daily by summing all intraday periods.
        daily_fr = funding_raw.resample("1D").sum()

        # 20-bar cumulative funding.
        cum_fr = daily_fr.rolling(20, min_periods=10).sum()

        # Price close at daily granularity.
        close = price_df["close"].astype(float).resample("1D").last().ffill()

        # 20-bar raw momentum.
        raw_mom = (close - close.shift(20)) / close.shift(20).replace(0.0, np.nan)

        # Align both series on shared daily index.
        aligned = pd.concat(
            [raw_mom.rename("raw_mom"), cum_fr.rename("cum_fr")], axis=1
        ).dropna()
        if aligned.empty:
            return _empty

        result = (
            _rolling_zscore(aligned["raw_mom"], 60)
            - _rolling_zscore(aligned["cum_fr"], 60)
        ).rename(out_name)
        return result

    except Exception:
        logger.exception(
            "compute_funding_adjusted_momentum failed for asset_id=%d symbol=%s tf=%s",
            asset_id,
            cmc_symbol,
            tf,
        )
        return _empty


# ---------------------------------------------------------------------------
# Composite 4: Cross-Asset Lead-Lag Composite
# ---------------------------------------------------------------------------


def compute_cross_asset_lead_lag_composite(
    conn,
    asset_id: int,
    venue_id: int,
    tf: str,
    horizon: int = 1,
) -> pd.Series:
    """IC-Weighted Composite of Cross-Asset Lead-Lag Signals.

    Financial intuition
    -------------------
    Certain assets systematically lead others by 1-5 bars.  For example,
    BTC often leads alt-coins; large-caps lead small-caps.  The lead_lag_ic
    table captures statistically significant IC values for each (predictor,
    follower, feature, horizon) combination.  This composite takes all
    significant predictors for the target asset and forms an IC-weighted
    combination of their lagged CTF features.  The result is a single
    signal that concentrates the information from all available leaders.

    Formula
    -------
    For each significant predictor (asset_a) with IC weight w_a and
    feature f_a:
        signal_a = ctf_feature f_a for asset_a, shifted by horizon bars
    result = sum(w_a * signal_a) / sum(|w_a|)

    Range
    -----
    Depends on the input CTF features (typically normalized).  Expected
    range similar to the constituent CTF features.

    Warmup
    ------
    Depends on the base CTF feature warmup plus 1 bar for lagging.

    Data coverage
    -------------
    Returns all-NaN Series if lead_lag_ic has no significant rows for this
    asset.  Logs a warning in that case.  Returns NaN for any timestamp
    where all predictor features are NaN.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID of the target (follower) asset.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Timeframe string (e.g. '1D').
    horizon:
        Lead horizon in bars (default 1).

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex, .name='cross_asset_lead_lag_composite'.
    """
    out_name = "cross_asset_lead_lag_composite"
    _empty = pd.Series(dtype=float, name=out_name)

    try:
        meta = _load_lead_lag_metadata(conn, asset_id, tf, horizon, venue_id)
        if meta.empty:
            logger.warning(
                "compute_cross_asset_lead_lag_composite: no significant lead-lag rows "
                "for asset_id=%d tf=%s horizon=%d -- returning NaN",
                asset_id,
                tf,
                horizon,
            )
            return _empty

        # Load CTF features for each unique predictor asset.
        all_weighted: list[pd.Series] = []
        all_weights: list[float] = []

        for _, row in meta.iterrows():
            predictor_id = int(
                row["asset_id_a"] if "asset_id_a" in row else row["asset_a_id"]
            )
            feature_name = str(row["feature"])
            ic_weight = float(row["ic"])

            # Load the specific CTF feature for the predictor asset.
            # feature_name follows convention {indicator}_{ref_tf}_{composite}
            # e.g. 'ret_arith_7d_agreement'.  We use it as a column filter.
            try:
                # Build wide CTF frame for predictor; filter to this feature column.
                df = pd.read_sql(
                    text("""
                        SELECT c.ts, c.agreement, c.slope, c.divergence
                        FROM public.ctf c
                        JOIN public.dim_ctf_indicators di ON di.indicator_id = c.indicator_id
                        WHERE c.id = :asset_id
                          AND c.base_tf = :tf
                          AND c.venue_id = :venue_id
                          AND c.alignment_source = 'multi_tf'
                        ORDER BY c.ts
                    """),
                    conn,
                    params={"asset_id": predictor_id, "tf": tf, "venue_id": venue_id},
                )
                if df.empty:
                    continue
                df["ts"] = pd.to_datetime(df["ts"], utc=True)
                df = df.set_index("ts").sort_index()

                # Choose the most relevant column from the feature name.
                for composite_key in ("agreement", "slope", "divergence"):
                    if composite_key in feature_name and composite_key in df.columns:
                        feat_series = df[composite_key].astype(float)
                        break
                else:
                    feat_series = df.iloc[:, 0].astype(float)

                # Lag by horizon bars (predictor leads by horizon).
                lagged = feat_series.shift(horizon)
                all_weighted.append(lagged * ic_weight)
                all_weights.append(abs(ic_weight))

            except Exception:
                logger.debug(
                    "compute_cross_asset_lead_lag_composite: failed to load feature "
                    "for predictor_id=%d feature=%s -- skipping",
                    predictor_id,
                    feature_name,
                )
                continue

        if not all_weighted:
            return _empty

        total_weight = sum(all_weights)
        if total_weight == 0.0:
            return _empty

        # IC-weighted combination on a common time index.
        combined = pd.concat(all_weighted, axis=1)
        numerator = combined.sum(axis=1, min_count=1)
        result = (numerator / total_weight).rename(out_name)
        return result

    except Exception:
        logger.exception(
            "compute_cross_asset_lead_lag_composite failed for asset_id=%d tf=%s",
            asset_id,
            tf,
        )
        return _empty


# ---------------------------------------------------------------------------
# Composite 5: TF Alignment Score
# ---------------------------------------------------------------------------

# TF pair definitions: (base_tf, ref_tf).  All valid CTF combinations.
_TF_ALIGNMENT_PAIRS: list[tuple[str, str]] = [
    ("1D", "7D"),
    ("1D", "14D"),
    ("1D", "30D"),
    ("7D", "30D"),
]


def compute_tf_alignment_score(
    conn,
    asset_id: int,
    venue_id: int,
) -> pd.Series:
    """Average Cross-Timeframe Agreement Score Centered at Zero.

    Financial intuition
    -------------------
    When price momentum is consistent across multiple timeframes (daily,
    weekly, monthly), the trend is more reliable and likely to persist.
    This composite averages the CTF agreement scores across four TF pairs.
    Subtracting 0.5 centers the signal at zero: positive values indicate
    multi-TF alignment, negative values indicate divergence.

    Formula
    -------
    For each TF pair (base_tf, ref_tf):
        agr_i = CTF agreement for ret_arith indicator
    result = mean(agr_i across available pairs) - 0.5

    Range
    -----
    [-0.5, +0.5]  (before centering: [0, 1]).

    Warmup
    ------
    Depends on CTF computation warmup (typically 20 bars).

    Data coverage
    -------------
    Uses only pairs with available data.  Warns if fewer than 3 pairs are
    available (insufficient for a robust alignment estimate).  Returns
    all-NaN Series if no pairs have data.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex, .name='tf_alignment_score'.
    """
    out_name = "tf_alignment_score"
    _empty = pd.Series(dtype=float, name=out_name)

    try:
        available: list[pd.Series] = []

        for base_tf, ref_tf in _TF_ALIGNMENT_PAIRS:
            s = _load_ctf_agreement_col(
                conn, asset_id, base_tf, ref_tf, "ret_arith", venue_id
            )
            if not s.empty:
                available.append(s.astype(float))

        n_pairs = len(available)
        if n_pairs == 0:
            return _empty

        if n_pairs < 3:
            logger.warning(
                "compute_tf_alignment_score: only %d/%d TF pairs available for "
                "asset_id=%d venue_id=%d -- alignment estimate may be unreliable",
                n_pairs,
                len(_TF_ALIGNMENT_PAIRS),
                asset_id,
                venue_id,
            )

        # Resample all to daily for consistent alignment, then average.
        daily_frames = []
        for s in available:
            d = s.resample("1D").last().ffill()
            daily_frames.append(d)

        combined = pd.concat(daily_frames, axis=1)
        mean_agr = combined.mean(axis=1, skipna=True)
        result = (mean_agr - 0.5).rename(out_name)
        return result

    except Exception:
        logger.exception(
            "compute_tf_alignment_score failed for asset_id=%d venue_id=%d",
            asset_id,
            venue_id,
        )
        return _empty


# ---------------------------------------------------------------------------
# Composite 6: Volume-Regime-Gated Trend
# ---------------------------------------------------------------------------


def compute_volume_regime_gated_trend(
    conn,
    asset_id: int,
    venue_id: int,
    tf: str,
) -> pd.Series:
    """KAMA-Relative Trend Signal Gated by Continuous Volume Regime.

    Financial intuition
    -------------------
    Trend signals derived from moving averages are unreliable in low-volume
    environments where prices are easy to move without genuine participation.
    This composite computes a trend signal normalized by ATR (so the signal is
    comparable across volatility regimes) and then applies a soft volume gate
    via tanh.  The tanh gate is continuous: low volume dampens the trend signal
    toward zero but never flips its sign, unlike a hard binary gate.

    Formula
    -------
    true_range = max(high-low, |high-prev_close|, |low-prev_close|)
    atr_14     = true_range.rolling(14, min_periods=7).mean()
    trend      = (close - kama) / atr_14
    vol_ratio  = volume / volume.rolling(20, min_periods=10).mean() - 1
    vol_gate   = tanh(vol_ratio)                             [range: -1, +1]
    result     = trend * (0.5 + 0.5 * vol_gate)             [gate in [0, 1]]

    Range
    -----
    Unbounded (trend_signal in ATR units; typical range [-3, +3]).

    Warmup
    ------
    Requires 20 bars for volume gate stability; 14 bars for ATR; KAMA warmup
    from ama_multi_tf.  Effective warmup: ~25 bars.

    Data coverage
    -------------
    Returns all-NaN Series if KAMA data or price/volume bars are absent.

    Parameters
    ----------
    conn:
        SQLAlchemy connection.
    asset_id:
        CMC asset ID.
    venue_id:
        Venue ID (1 = CMC_AGG).
    tf:
        Timeframe string (e.g. '1D').

    Returns
    -------
    pd.Series[float] with UTC DatetimeIndex, .name='volume_regime_gated_trend'.
    """
    out_name = "volume_regime_gated_trend"
    _empty = pd.Series(dtype=float, name=out_name)

    try:
        ama_df = _load_ama_er(conn, asset_id, venue_id, tf)
        if ama_df.empty:
            return _empty

        price_df = _load_price_bars(
            conn, asset_id, venue_id, tf, ["close", "high", "low", "volume"]
        )
        if price_df.empty:
            return _empty

        # Align on shared timestamps.
        aligned = pd.concat(
            [ama_df[["ama"]], price_df[["close", "high", "low", "volume"]]], axis=1
        ).dropna(subset=["ama", "close", "volume"])
        if aligned.empty:
            return _empty

        close = aligned["close"].astype(float)
        high = aligned["high"].astype(float)
        low = aligned["low"].astype(float)
        volume = aligned["volume"].astype(float)
        kama = aligned["ama"].astype(float)

        # True Range computation (requires previous close via shift).
        prev_close = close.shift(1)
        tr = pd.concat(
            [
                (high - low),
                (high - prev_close).abs(),
                (low - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr_14 = tr.rolling(14, min_periods=7).mean()

        # Trend signal normalized by ATR; avoid division by zero.
        trend = (close - kama) / atr_14.replace(0.0, np.nan)

        # Continuous volume gate via tanh: 0 = average vol, saturates at +/-1.
        vol_mean = volume.rolling(20, min_periods=10).mean().replace(0.0, np.nan)
        vol_ratio = volume / vol_mean - 1.0
        vol_gate = np.tanh(vol_ratio)

        # Rescale gate from [-1, +1] to [0, 1] so trend is only dampened, not flipped.
        gate_scaled = 0.5 + 0.5 * vol_gate

        result = (trend * gate_scaled).rename(out_name)
        return result

    except Exception:
        logger.exception(
            "compute_volume_regime_gated_trend failed for asset_id=%d venue_id=%d tf=%s",
            asset_id,
            venue_id,
            tf,
        )
        return _empty


# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

ALL_COMPOSITES: dict = {
    "ama_er_regime_signal": compute_ama_er_regime_signal,
    "oi_divergence_ctf_agreement": compute_oi_divergence_ctf_agreement,
    "funding_adjusted_momentum": compute_funding_adjusted_momentum,
    "cross_asset_lead_lag_composite": compute_cross_asset_lead_lag_composite,
    "tf_alignment_score": compute_tf_alignment_score,
    "volume_regime_gated_trend": compute_volume_regime_gated_trend,
}

# Sanity check: registry matches COMPOSITE_NAMES.
assert set(ALL_COMPOSITES.keys()) == set(COMPOSITE_NAMES), (
    f"ALL_COMPOSITES keys mismatch COMPOSITE_NAMES: "
    f"{set(ALL_COMPOSITES.keys()) ^ set(COMPOSITE_NAMES)}"
)
