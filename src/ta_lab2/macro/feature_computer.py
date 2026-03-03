"""feature_computer.py

Compute FRED-03 through FRED-07 derived macro features from forward-filled
wide FRED DataFrame.

Pipeline:
    load_series_wide() -> forward_fill_with_limits() -> compute_derived_features()
    => final DataFrame with DB-ready lowercase column names

The top-level orchestrator is compute_macro_features(engine, start_date, end_date),
which calls all three steps and returns a DataFrame ready for upsert into
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
# All 11 raw series columns in fred.fred_macro_features use lowercase names.
_RENAME_MAP: dict[str, str] = {
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
            walcl, wtregen, rrpontsyd, dff, dgs10, t10y2y, vixcls, dtwexbgs,
            ecbdfr, irstci01jpm156n, irltlt01jpm156n,
            net_liquidity, us_jp_rate_spread, us_ecb_rate_spread, us_jp_10y_spread,
            yc_slope_change_5d, vix_regime,
            dtwexbgs_5d_change, dtwexbgs_20d_change,
            source_freq_walcl, source_freq_wtregen,
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

    # ── Step 3: Compute derived features ──────────────────────────────────
    df_derived = compute_derived_features(df_filled)

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
            days = (df_derived.index - src).days
            df_derived[db_col] = days.where(src.notna(), other=None)
        else:
            df_derived[db_col] = None

    # Drop uppercase columns that didn't get renamed (e.g., derived feature
    # intermediaries or any unexpected extra columns from the wide DataFrame)
    # Keep only columns that belong in the DB schema
    db_columns = list(_RENAME_MAP.values()) + [
        "net_liquidity",
        "us_jp_rate_spread",
        "us_ecb_rate_spread",
        "us_jp_10y_spread",
        "yc_slope_change_5d",
        "vix_regime",
        "dtwexbgs_5d_change",
        "dtwexbgs_20d_change",
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
