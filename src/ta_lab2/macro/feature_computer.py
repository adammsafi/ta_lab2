"""feature_computer.py

Compute FRED-03 through FRED-16 derived macro features from forward-filled
wide FRED DataFrame.

Pipeline:
    load_series_wide() -> forward_fill_with_limits()
    -> compute_derived_features() -> compute_derived_features_66()
    => final DataFrame with DB-ready lowercase column names

The top-level orchestrator is compute_macro_features(engine, start_date, end_date),
which calls all steps and returns a DataFrame ready for upsert into
fred.fred_macro_features.

Usage:
    from ta_lab2.macro.feature_computer import compute_macro_features

    df = compute_macro_features(engine, start_date="2015-01-01", end_date="2026-03-01")
    # df.index = DatetimeIndex (calendar-daily)
    # df.columns = lowercase DB column names matching fred.fred_macro_features schema
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy.engine import Engine

from ta_lab2.macro.forward_fill import forward_fill_with_limits
from ta_lab2.macro.fred_reader import SERIES_TO_LOAD, load_series_wide

logger = logging.getLogger(__name__)

# ── Lowercase rename map: FRED ID -> DB column name ───────────────────────
# All 21 raw series columns in fred.fred_macro_features use lowercase names.
_RENAME_MAP: dict[str, str] = {
    # Phase 65: 11 original series
    "WALCL": "walcl",
    "WTREGEN": "wtregen",
    "RRPONTSYD": "rrpontsyd",
    "DFF": "dff",
    "DGS10": "dgs10",
    "T10Y2Y": "t10y2y",
    "VIXCLS": "vixcls",
    "DTWEXBGS": "dtwexbgs",
    "ECBDFR": "ecbdfr",
    "IRSTCI01JPM156N": "irstci01jpm156n",
    "IRLTLT01JPM156N": "irltlt01jpm156n",
    # Phase 66: 7 new series (FRED-08 through FRED-16)
    "BAMLH0A0HYM2": "bamlh0a0hym2",
    "NFCI": "nfci",
    "M2SL": "m2sl",
    "DEXJPUS": "dexjpus",
    "DFEDTARU": "dfedtaru",
    "DFEDTARL": "dfedtarl",
    "CPIAUCSL": "cpiaucsl",
    # Phase 97: US equity indices
    "SP500": "sp500",
    "NASDAQCOM": "nasdaqcom",
    "DJIA": "djia",
}

# ── VIX regime thresholds (consensus values per research) ──────────────────
_VIX_BINS = [0.0, 15.0, 25.0, float("inf")]
_VIX_LABELS = ["calm", "elevated", "crisis"]


def compute_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all FRED-03 through FRED-07 derived columns from ffilled wide DataFrame.

    Parameters
    ----------
    df:
        Forward-filled wide DataFrame from forward_fill_with_limits().
        Index: DatetimeIndex (calendar-daily, tz-naive).
        Columns: uppercase FRED series IDs (e.g. "WALCL", "VIXCLS").

    Returns
    -------
    pd.DataFrame
        Same DataFrame with derived feature columns added in-place:
        - net_liquidity (FRED-03)
        - us_jp_rate_spread, us_ecb_rate_spread, us_jp_10y_spread (FRED-04)
        - yc_slope_change_5d (FRED-05)
        - vix_regime (FRED-06, Text: calm/elevated/crisis)
        - dtwexbgs_5d_change, dtwexbgs_20d_change (FRED-07)

    Notes
    -----
    - Missing WTREGEN: if "WTREGEN" not in df.columns, net_liquidity is set to NaN
      and a WARNING is logged. The rest of the pipeline continues normally.
    - VIX regime is NaN (None) where VIXCLS is NaN, even after forward-fill.
    - NaN propagation in arithmetic is intentional: a NaN input means the feature
      is not reliably computable for that date.
    """
    result = df.copy()

    # FRED-03: Net liquidity proxy = WALCL - WTREGEN - RRPONTSYD
    walcl = result.get("WALCL")
    rrpontsyd = result.get("RRPONTSYD")

    if "WTREGEN" not in result.columns:
        logger.warning(
            "WTREGEN column missing from DataFrame -- net_liquidity set to NaN. "
            "Add WTREGEN to VM FRED series list and run sync_fred_from_vm.py."
        )
        result["net_liquidity"] = float("nan")
    elif walcl is None or rrpontsyd is None:
        logger.warning("WALCL or RRPONTSYD missing -- net_liquidity set to NaN.")
        result["net_liquidity"] = float("nan")
    else:
        result["net_liquidity"] = (
            result["WALCL"] - result["WTREGEN"] - result["RRPONTSYD"]
        )

    # FRED-04: Rate spreads
    # US-Japan short-term rate differential
    if "DFF" in result.columns and "IRSTCI01JPM156N" in result.columns:
        result["us_jp_rate_spread"] = result["DFF"] - result["IRSTCI01JPM156N"]
    else:
        result["us_jp_rate_spread"] = float("nan")

    # US-ECB rate differential
    if "DFF" in result.columns and "ECBDFR" in result.columns:
        result["us_ecb_rate_spread"] = result["DFF"] - result["ECBDFR"]
    else:
        result["us_ecb_rate_spread"] = float("nan")

    # US-Japan 10-year bond spread
    if "DGS10" in result.columns and "IRLTLT01JPM156N" in result.columns:
        result["us_jp_10y_spread"] = result["DGS10"] - result["IRLTLT01JPM156N"]
    else:
        result["us_jp_10y_spread"] = float("nan")

    # FRED-05: Yield curve slope change (5-day delta of T10Y2Y spread)
    if "T10Y2Y" in result.columns:
        result["yc_slope_change_5d"] = result["T10Y2Y"].diff(5)
    else:
        result["yc_slope_change_5d"] = float("nan")

    # FRED-06: VIX regime categorical
    if "VIXCLS" in result.columns:
        vix_regime: Any = pd.cut(
            result["VIXCLS"],
            bins=_VIX_BINS,
            labels=_VIX_LABELS,
            right=True,
        ).astype(str)
        # Rows where VIXCLS was NaN after ffill -> pd.cut returns NaN -> astype(str) -> "nan"
        # Replace "nan" with None so the DB gets NULL, not the string "nan"
        vix_regime[result["VIXCLS"].isna()] = None
        result["vix_regime"] = vix_regime
    else:
        result["vix_regime"] = None

    # FRED-07: Dollar strength changes (5-day and 20-day)
    if "DTWEXBGS" in result.columns:
        result["dtwexbgs_5d_change"] = result["DTWEXBGS"].diff(5)
        result["dtwexbgs_20d_change"] = result["DTWEXBGS"].diff(20)
    else:
        result["dtwexbgs_5d_change"] = float("nan")
        result["dtwexbgs_20d_change"] = float("nan")

    return result


# ── Phase 66: FRED-08 through FRED-16 helpers & computation ──────────────


def _rolling_zscore(
    series: pd.Series, window: int, min_fill_pct: float = 0.80
) -> pd.Series:
    """Compute rolling z-score with minimum fill requirement.

    Parameters
    ----------
    series:
        Input series (can contain NaN from ffill limits).
    window:
        Rolling window size in days.
    min_fill_pct:
        Minimum fraction of non-NaN rows required (default: 0.80).

    Returns
    -------
    pd.Series
        Z-score series.  NaN where insufficient data.
    """
    min_periods = max(1, int(min_fill_pct * window))
    roll_mean = series.rolling(window, min_periods=min_periods).mean()
    roll_std = series.rolling(window, min_periods=min_periods).std()
    return (series - roll_mean) / roll_std


def _compute_fed_regime(df: pd.DataFrame) -> None:
    """Compute FRED-13 (fed regime) and FRED-16 (TARGET_MID, TARGET_SPREAD) in-place.

    Modifies *df* by adding four columns:
        target_mid             – (DFEDTARU + DFEDTARL) / 2
        target_spread          – DFEDTARU - DFEDTARL
        fed_regime_structure   – "zero-bound" | "single-target" | "target-range" | None
        fed_regime_trajectory  – "hiking" | "holding" | "cutting" | None
    """
    has_upper = "DFEDTARU" in df.columns
    has_lower = "DFEDTARL" in df.columns
    has_dff = "DFF" in df.columns

    if has_upper and has_lower:
        upper = df["DFEDTARU"]
        lower = df["DFEDTARL"]

        # FRED-16: TARGET_MID and TARGET_SPREAD
        df["target_mid"] = (upper + lower) / 2.0
        df["target_spread"] = upper - lower

        # FRED-13 structure: classify based on data values
        #   zero-bound:    DFEDTARU <= 0.25
        #   single-target: spread < 0.001 (effectively equal) and not zero-bound
        #   target-range:  spread >= 0.001 and not zero-bound
        def _classify_structure(row_upper: float, row_lower: float) -> str | None:
            if row_upper != row_upper:  # NaN check
                return None
            if row_upper <= 0.25:
                return "zero-bound"
            if abs(row_upper - row_lower) < 0.001:
                return "single-target"
            return "target-range"

        df["fed_regime_structure"] = [
            _classify_structure(u, lo) for u, lo in zip(upper, lower)
        ]
    else:
        df["target_mid"] = float("nan")
        df["target_spread"] = float("nan")
        df["fed_regime_structure"] = None

    # FRED-13 trajectory: hiking / holding / cutting from DFF 90-day change
    if has_dff:
        dff = df["DFF"]
        change_90d = dff.diff(90)

        def _classify_trajectory(delta: float) -> str | None:
            if delta != delta:  # NaN
                return None
            if delta > 0.25:
                return "hiking"
            if delta < -0.25:
                return "cutting"
            return "holding"

        df["fed_regime_trajectory"] = change_90d.apply(_classify_trajectory)
    else:
        df["fed_regime_trajectory"] = None


def compute_derived_features_66(df: pd.DataFrame) -> pd.DataFrame:
    """Compute FRED-08 through FRED-16 derived columns.

    Called AFTER compute_derived_features() which has already added lowercase
    derived columns (net_liquidity, us_jp_rate_spread, etc.) to the DataFrame.
    Raw FRED series are still uppercase (BAMLH0A0HYM2, NFCI, etc.) because the
    rename step happens later in compute_macro_features().

    Parameters
    ----------
    df:
        DataFrame from compute_derived_features().  Contains uppercase FRED IDs
        plus lowercase derived columns from Phase 65.

    Returns
    -------
    pd.DataFrame
        Same DataFrame with 18 new derived columns added:
        hy_oas_level, hy_oas_5d_change, hy_oas_30d_zscore,
        nfci_level, nfci_4wk_direction, m2_yoy_pct,
        dexjpus_level, dexjpus_5d_pct_change, dexjpus_20d_vol, dexjpus_daily_zscore,
        net_liquidity_365d_zscore, net_liquidity_trend,
        fed_regime_structure, fed_regime_trajectory, target_mid, target_spread,
        carry_momentum, cpi_surprise_proxy
    """
    result = df.copy()

    # ── FRED-08: Credit stress (BAMLH0A0HYM2 = HY OAS spread) ─────────
    if "BAMLH0A0HYM2" in result.columns:
        hy = result["BAMLH0A0HYM2"]
        result["hy_oas_level"] = hy
        result["hy_oas_5d_change"] = hy.diff(5)
        result["hy_oas_30d_zscore"] = _rolling_zscore(hy, 30)
    else:
        result["hy_oas_level"] = float("nan")
        result["hy_oas_5d_change"] = float("nan")
        result["hy_oas_30d_zscore"] = float("nan")

    # ── FRED-09: Financial conditions (NFCI -- weekly) ─────────────────
    if "NFCI" in result.columns:
        nfci = result["NFCI"]
        result["nfci_level"] = nfci
        # 4-week direction: sign of 28-day diff
        nfci_diff = nfci.diff(28)
        result["nfci_4wk_direction"] = nfci_diff.apply(
            lambda x: ("rising" if x > 0 else ("falling" if x < 0 else None))
            if x == x
            else None  # NaN check
        )
    else:
        result["nfci_level"] = float("nan")
        result["nfci_4wk_direction"] = None

    # ── FRED-10: M2 money supply YoY (M2SL -- monthly, ffilled) ───────
    # CRITICAL: pct_change(365) NOT pct_change(1).  M2SL is monthly
    # forward-filled to daily; pct_change(1) gives 0 on non-release days.
    if "M2SL" in result.columns:
        result["m2_yoy_pct"] = result["M2SL"].pct_change(365) * 100.0
    else:
        result["m2_yoy_pct"] = float("nan")

    # ── FRED-11: Carry trade (DEXJPUS -- daily) ───────────────────────
    if "DEXJPUS" in result.columns:
        jpy = result["DEXJPUS"]
        result["dexjpus_level"] = jpy
        result["dexjpus_5d_pct_change"] = jpy.pct_change(5) * 100.0
        # 20-day rolling vol of daily returns
        daily_ret = jpy.pct_change(1) * 100.0
        result["dexjpus_20d_vol"] = daily_ret.rolling(20, min_periods=16).std()
        # Daily z-score: z-score of 1-day return using 20d rolling window
        roll_mean_dm = daily_ret.rolling(20, min_periods=16).mean()
        roll_std_dm = daily_ret.rolling(20, min_periods=16).std()
        result["dexjpus_daily_zscore"] = (daily_ret - roll_mean_dm) / roll_std_dm
    else:
        result["dexjpus_level"] = float("nan")
        result["dexjpus_5d_pct_change"] = float("nan")
        result["dexjpus_20d_vol"] = float("nan")
        result["dexjpus_daily_zscore"] = float("nan")

    # ── FRED-12: Net liquidity z-score + dual-window trend ────────────
    # net_liquidity was added by Phase 65 compute_derived_features()
    if "net_liquidity" in result.columns:
        nl = result["net_liquidity"]
        result["net_liquidity_365d_zscore"] = _rolling_zscore(nl, 365)
        # Dual-window trend: 30d MA vs 150d MA
        ma30 = nl.rolling(30, min_periods=24).mean()
        ma150 = nl.rolling(150, min_periods=120).mean()
        trend_diff = ma30 - ma150
        result["net_liquidity_trend"] = trend_diff.apply(
            lambda x: ("expanding" if x > 0 else ("contracting" if x < 0 else None))
            if x == x
            else None
        )
    else:
        result["net_liquidity_365d_zscore"] = float("nan")
        result["net_liquidity_trend"] = None

    # ── FRED-13 + FRED-16: Fed regime + target rate metrics ───────────
    _compute_fed_regime(result)  # adds target_mid, target_spread,
    #                              fed_regime_structure, fed_regime_trajectory

    # ── FRED-14: Carry momentum indicator ─────────────────────────────
    # Uses dexjpus_daily_zscore (FRED-11) and us_jp_rate_spread (Phase 65)
    if "dexjpus_daily_zscore" in result.columns:
        base_z = result["dexjpus_daily_zscore"]
        carry_spread = result.get("us_jp_rate_spread")

        if carry_spread is not None and not (
            isinstance(carry_spread, float) and carry_spread != carry_spread
        ):
            # Elevated threshold (2.0) when carry spread is positive
            threshold = carry_spread.apply(lambda x: 2.0 if (x == x and x > 0) else 1.5)
        else:
            threshold = 1.5

        result["carry_momentum"] = (base_z.abs() > threshold).astype(float)
        result["carry_momentum"] = result["carry_momentum"].where(
            base_z.notna(), other=None
        )
    else:
        result["carry_momentum"] = float("nan")

    # ── FRED-15: CPI surprise proxy (CPIAUCSL -- monthly) ────────────
    if "CPIAUCSL" in result.columns:
        cpi = result["CPIAUCSL"]
        cpi_mom = cpi.pct_change(30) * 100.0  # approx MoM from ffilled data
        baseline = cpi_mom.rolling(90, min_periods=72).mean()  # 3-month trend
        result["cpi_surprise_proxy"] = cpi_mom - baseline
    else:
        result["cpi_surprise_proxy"] = float("nan")

    return result


# -- Phase 97: Per-series equity index derived features ----------------

# Series that get the generic per-series derived feature set (Phase 97)
_EQUITY_INDEX_SERIES = ["SP500", "NASDAQCOM", "DJIA"]


def compute_per_series_features_97(df: pd.DataFrame) -> pd.DataFrame:
    """Compute generic derived features for each equity index series.

    For each series in _EQUITY_INDEX_SERIES, computes 8 derived columns:
      {prefix}_ret_1d     - 1-day return (pct_change(1) * 100.0)
      {prefix}_ret_5d     - 5-day return (pct_change(5) * 100.0)
      {prefix}_ret_21d    - 21-day return (pct_change(21) * 100.0)
      {prefix}_ret_63d    - 63-day return (pct_change(63) * 100.0)
      {prefix}_vol_21d    - 21-day rolling volatility of daily returns
      {prefix}_drawdown_pct  - Drawdown from rolling max (negative values)
      {prefix}_ma_ratio_50_200d - 50d MA / 200d MA ratio
      {prefix}_zscore_252d - 252-day rolling z-score (using existing _rolling_zscore)

    Called AFTER compute_derived_features_66(). Raw FRED series are still
    uppercase at this point (rename happens later).

    PATTERN: Uses .pct_change(N) * 100.0 and min_periods = 0.8 * window,
    matching DEXJPUS precedent from compute_derived_features_66().
    """
    result = df.copy()

    for series_id in _EQUITY_INDEX_SERIES:
        if series_id not in result.columns:
            logger.warning(
                "Equity index %s not in DataFrame columns -- skipping derived features. "
                "Ensure %s is in SERIES_TO_LOAD and fred.series_values has data.",
                series_id,
                series_id,
            )
            # Write NaN placeholders for all 8 derived columns
            prefix = series_id.lower()
            for suffix in [
                "ret_1d",
                "ret_5d",
                "ret_21d",
                "ret_63d",
                "vol_21d",
                "drawdown_pct",
                "ma_ratio_50_200d",
                "zscore_252d",
            ]:
                result[f"{prefix}_{suffix}"] = float("nan")
            continue

        raw = result[series_id]
        prefix = series_id.lower()

        # Returns: pct_change(N) * 100.0, matching DEXJPUS pattern
        for window in [1, 5, 21, 63]:
            result[f"{prefix}_ret_{window}d"] = raw.pct_change(window) * 100.0

        # Volatility: 21-day rolling std of daily returns
        daily_ret = raw.pct_change(1) * 100.0
        result[f"{prefix}_vol_21d"] = daily_ret.rolling(21, min_periods=17).std()

        # Drawdown: current level / rolling max - 1 (negative values)
        rolling_max = raw.rolling(252, min_periods=1).max()
        result[f"{prefix}_drawdown_pct"] = ((raw / rolling_max) - 1.0) * 100.0

        # MA ratio: 50d MA / 200d MA
        ma50 = raw.rolling(50, min_periods=40).mean()
        ma200 = raw.rolling(200, min_periods=160).mean()
        result[f"{prefix}_ma_ratio_50_200d"] = ma50 / ma200

        # Z-score: 252-day rolling z-score (reuse existing _rolling_zscore helper)
        result[f"{prefix}_zscore_252d"] = _rolling_zscore(raw, 252)

    return result


def compute_macro_features(
    engine: Engine,
    start_date: str | None = None,
    end_date: str | None = None,
    series_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Orchestrate the full FRED macro feature computation pipeline.

    Steps:
        1. Load raw series from fred.series_values (load_series_wide)
        2. Forward-fill with per-frequency limits (forward_fill_with_limits)
        3. Compute derived features (compute_derived_features)
        4. Rename columns to lowercase (DB schema convention)
        5. Add source_freq provenance columns
        6. Compute days_since_walcl and days_since_wtregen from source_dates
        7. Return DataFrame ready for upsert into fred.fred_macro_features

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    start_date:
        Optional start date (inclusive), e.g. "2015-01-01".
        If None, loads from earliest available FRED data.
    end_date:
        Optional end date (inclusive), e.g. "2026-03-01".
        If None, loads up to latest available FRED data.
    series_ids:
        Optional override for which series to load. Defaults to SERIES_TO_LOAD.

    Returns
    -------
    pd.DataFrame
        Index: DatetimeIndex (calendar-daily, tz-naive), name="date"
        Columns: lowercase names matching fred.fred_macro_features schema:
            -- Phase 65 raw: walcl, wtregen, rrpontsyd, dff, dgs10, t10y2y,
               vixcls, dtwexbgs, ecbdfr, irstci01jpm156n, irltlt01jpm156n
            -- Phase 66 raw: bamlh0a0hym2, nfci, m2sl, dexjpus, dfedtaru,
               dfedtarl, cpiaucsl
            -- Phase 65 derived: net_liquidity, us_jp_rate_spread,
               us_ecb_rate_spread, us_jp_10y_spread, yc_slope_change_5d,
               vix_regime, dtwexbgs_5d_change, dtwexbgs_20d_change
            -- Phase 66 derived: hy_oas_level, hy_oas_5d_change,
               hy_oas_30d_zscore, nfci_level, nfci_4wk_direction, m2_yoy_pct,
               dexjpus_level, dexjpus_5d_pct_change, dexjpus_20d_vol,
               dexjpus_daily_zscore, net_liquidity_365d_zscore,
               net_liquidity_trend, fed_regime_structure, fed_regime_trajectory,
               carry_momentum, cpi_surprise_proxy, target_mid, target_spread
            -- Provenance: source_freq_walcl, source_freq_wtregen,
               source_freq_irstci01jpm156n, source_freq_irltlt01jpm156n,
               days_since_walcl, days_since_wtregen

    Notes
    -----
    - ingested_at is NOT included (server_default=now() in DB handles it).
    - If no FRED data is available, returns an empty DataFrame.
    - Missing WTREGEN is handled gracefully: net_liquidity set to NaN, WARNING logged.
    """
    ids = series_ids if series_ids is not None else SERIES_TO_LOAD

    # ── Step 1: Load raw series ────────────────────────────────────────────
    df_wide = load_series_wide(
        engine, series_ids=ids, start_date=start_date, end_date=end_date
    )

    if df_wide.empty:
        logger.warning("No FRED data loaded -- returning empty DataFrame")
        return pd.DataFrame()

    # ── Step 2: Forward-fill with per-frequency limits ────────────────────
    df_filled, source_dates = forward_fill_with_limits(
        df_wide, tracked_series=["WALCL", "WTREGEN"]
    )

    # ── Step 3: Compute derived features (Phase 65: FRED-03 to FRED-07) ──
    df_derived = compute_derived_features(df_filled)

    # ── Step 3b: Compute Phase 66 derived features (FRED-08 to FRED-16) ──
    # Must run AFTER compute_derived_features() because it needs
    # net_liquidity and us_jp_rate_spread from Phase 65.
    df_derived = compute_derived_features_66(df_derived)

    # ── Step 3c: Compute Phase 97 equity index derived features ──────────
    df_derived = compute_per_series_features_97(df_derived)

    # ── Step 4: Rename uppercase FRED IDs to lowercase DB column names ────
    df_derived = df_derived.rename(columns=_RENAME_MAP)

    # ── Step 5: Add source_freq provenance (constant strings) ─────────────
    # These reflect the publication frequency of the underlying FRED series.
    for col in ("walcl", "wtregen"):
        if col in df_derived.columns:
            df_derived[f"source_freq_{col}"] = "weekly"

    for col in ("irstci01jpm156n", "irltlt01jpm156n"):
        if col in df_derived.columns:
            df_derived[f"source_freq_{col}"] = "monthly"

    # ── Step 6: Compute days_since_* from source_date provenance ──────────
    # source_dates maps uppercase FRED ID -> Series of source observation dates
    # days_since = (row_date - source_observation_date).days
    for fred_id, db_col in [
        ("WALCL", "days_since_walcl"),
        ("WTREGEN", "days_since_wtregen"),
    ]:
        if fred_id in source_dates:
            src = source_dates[fred_id]
            # df_derived.index is DatetimeIndex; src is aligned to same index
            delta = df_derived.index.to_series() - src
            days = delta.dt.days
            df_derived[db_col] = days.where(src.notna(), other=None)
        else:
            df_derived[db_col] = None

    # Drop uppercase columns that didn't get renamed (e.g., derived feature
    # intermediaries or any unexpected extra columns from the wide DataFrame)
    # Keep only columns that belong in the DB schema
    db_columns = list(_RENAME_MAP.values()) + [
        # Phase 65 derived features
        "net_liquidity",
        "us_jp_rate_spread",
        "us_ecb_rate_spread",
        "us_jp_10y_spread",
        "yc_slope_change_5d",
        "vix_regime",
        "dtwexbgs_5d_change",
        "dtwexbgs_20d_change",
        # Phase 66 derived features (FRED-08 through FRED-16)
        "hy_oas_level",
        "hy_oas_5d_change",
        "hy_oas_30d_zscore",
        "nfci_level",
        "nfci_4wk_direction",
        "m2_yoy_pct",
        "dexjpus_level",
        "dexjpus_5d_pct_change",
        "dexjpus_20d_vol",
        "dexjpus_daily_zscore",
        "net_liquidity_365d_zscore",
        "net_liquidity_trend",
        "fed_regime_structure",
        "fed_regime_trajectory",
        "carry_momentum",
        "cpi_surprise_proxy",
        "target_mid",
        "target_spread",
        # Phase 97: Equity index derived features (24 columns)
        # Note: raw sp500/nasdaqcom/djia are already in list(_RENAME_MAP.values()) above
        "sp500_ret_1d",
        "sp500_ret_5d",
        "sp500_ret_21d",
        "sp500_ret_63d",
        "sp500_vol_21d",
        "sp500_drawdown_pct",
        "sp500_ma_ratio_50_200d",
        "sp500_zscore_252d",
        "nasdaqcom_ret_1d",
        "nasdaqcom_ret_5d",
        "nasdaqcom_ret_21d",
        "nasdaqcom_ret_63d",
        "nasdaqcom_vol_21d",
        "nasdaqcom_drawdown_pct",
        "nasdaqcom_ma_ratio_50_200d",
        "nasdaqcom_zscore_252d",
        "djia_ret_1d",
        "djia_ret_5d",
        "djia_ret_21d",
        "djia_ret_63d",
        "djia_vol_21d",
        "djia_drawdown_pct",
        "djia_ma_ratio_50_200d",
        "djia_zscore_252d",
        # Provenance columns
        "source_freq_walcl",
        "source_freq_wtregen",
        "source_freq_irstci01jpm156n",
        "source_freq_irltlt01jpm156n",
        "days_since_walcl",
        "days_since_wtregen",
    ]
    # Only keep columns that exist in the DataFrame (graceful partial results)
    keep_cols = [c for c in db_columns if c in df_derived.columns]
    df_out = df_derived[keep_cols].copy()
    df_out.index.name = "date"

    logger.info(
        "compute_macro_features: %d rows, %d columns (%s to %s)",
        len(df_out),
        len(df_out.columns),
        df_out.index.min().date() if not df_out.empty else "N/A",
        df_out.index.max().date() if not df_out.empty else "N/A",
    )

    return df_out
