"""cross_asset.py

Cross-Asset Aggregation compute engine for Phase 70 (XAGG-01 through XAGG-04).

Computes four daily cross-asset signals:
  XAGG-01: BTC/ETH 30d rolling Pearson correlation -> cross_asset_agg
  XAGG-02: Average pairwise correlation with high_corr_flag -> cross_asset_agg
  XAGG-03: Aggregate funding rate with 30d/90d z-scores -> funding_rate_agg
  XAGG-04: Crypto-macro correlation regime with sign-flip detection
           -> crypto_macro_corr_regimes  (per asset/macro_var)
           -> macro_regimes.crypto_macro_corr  (daily aggregate label)

Data sources:
  - returns_bars_multi_tf (tf='1D', roll=FALSE, ret_arith)
  - tvc_price_histories (daily close -> simple returns)
  - funding_rates (tf='1d', daily rollup rows)
  - fred.fred_macro_features (VIX, DXY, HY OAS, net_liquidity)

All numeric thresholds live in configs/cross_asset_config.yaml.
All float values are sanitized via _to_python() before DB binding.
All DB writes use temp table + INSERT...ON CONFLICT upsert pattern.

Phase 70, Plan 02.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    import yaml  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Warmup window: how many days before watermark to include for rolling warmup.
# Must cover the longest rolling window in config (180d corr window) + 30d margin.
# Phase 97: increased from 120 to 210 to accommodate 180d correlation window.
WARMUP_DAYS = 210

# Default full-history start date for --full / no-watermark runs
FULL_HISTORY_START = "2020-01-01"

# Hardcoded asset IDs for BTC and ETH (cmc_price_histories7).
# These are looked up from the DB when possible; hardcoded as fallback.
_BTC_ID_FALLBACK = 1
_ETH_ID_FALLBACK = 52

# Minimum correlation window warmup multiplier
# We need this many rows before a rolling corr is considered valid
_CORR_MIN_PERIODS = 10


# ---------------------------------------------------------------------------
# Project root & YAML loader
# ---------------------------------------------------------------------------


try:
    from ta_lab2.config import project_root  # type: ignore[import]
except Exception:  # pragma: no cover

    def project_root() -> Path:
        p = Path(__file__).resolve()
        for parent in [p, *p.parents]:
            if (parent / "pyproject.toml").exists():
                return parent
        return Path(__file__).resolve().parents[3]


def _default_config_path() -> Path:
    """Return path to configs/cross_asset_config.yaml."""
    return project_root() / "configs" / "cross_asset_config.yaml"


def load_cross_asset_config(
    yaml_path: Optional[str | os.PathLike[str]] = None,
) -> Dict[str, Any]:
    """Load cross-asset aggregation configuration from YAML.

    Parameters
    ----------
    yaml_path:
        Optional explicit path. Defaults to <repo>/configs/cross_asset_config.yaml.

    Returns
    -------
    dict with keys: cross_asset, crypto_macro, funding_agg, portfolio_override, telegram.

    Raises
    ------
    FileNotFoundError if config file does not exist.
    RuntimeError if PyYAML is not installed.
    """
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required for cross-asset config. "
            "Install with: pip install pyyaml"
        )

    path = Path(yaml_path) if yaml_path is not None else _default_config_path()
    if not path.exists():
        raise FileNotFoundError(f"Cross-asset config not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        config: Dict[str, Any] = yaml.safe_load(f) or {}

    # Validate required top-level keys
    for key in ("cross_asset", "crypto_macro", "funding_agg"):
        if key not in config:
            raise ValueError(f"Missing required config key: {key}")

    return config


# ---------------------------------------------------------------------------
# Numpy / pandas type safety
# ---------------------------------------------------------------------------


def _to_python(v: Any) -> Any:
    """Convert numpy scalars and NaN to native Python types for psycopg2 safety."""
    if v is None:
        return None
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and (v != v):  # NaN check without math import
        return None
    return v


def _sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Convert DataFrame values to native Python types safe for psycopg2."""
    df = df.where(df.notna(), other=None)  # type: ignore[arg-type]
    for col in df.columns:
        if df[col].dtype == object:
            continue
        try:
            df[col] = df[col].apply(_to_python)
        except Exception:  # noqa: BLE001
            pass
    return df


# ---------------------------------------------------------------------------
# Rolling z-score helper
# ---------------------------------------------------------------------------


def _rolling_zscore_series(
    series: pd.Series, window: int, min_fill_pct: float = 0.80
) -> pd.Series:
    """Rolling z-score for a Series (same logic as feature_computer._rolling_zscore).

    Parameters
    ----------
    series:
        Input time series.
    window:
        Rolling window size.
    min_fill_pct:
        Minimum fill fraction; rows with fewer observations than this are NaN.

    Returns
    -------
    pd.Series of rolling z-scores (same index as input).
    """
    min_periods = max(1, int(min_fill_pct * window))
    roll_mean = series.rolling(window, min_periods=min_periods).mean()
    roll_std = series.rolling(window, min_periods=min_periods).std()
    return (series - roll_mean) / roll_std


# ---------------------------------------------------------------------------
# Watermark helpers
# ---------------------------------------------------------------------------


def get_watermark(engine: Engine, table_name: str) -> Optional[date]:
    """Get MAX(date) from the given table.

    Returns None if the table is empty or on query error.
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(f"SELECT MAX(date) FROM {table_name}")  # noqa: S608
            ).scalar()
        if result is None:
            return None
        if isinstance(result, date):
            return result
        return pd.Timestamp(result).date()
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not query watermark from %s -- assuming fresh run", table_name
        )
        return None


def _resolve_date_range(
    start_date: Optional[str],
    end_date: Optional[str],
    watermark: Optional[date],
    full: bool = False,
) -> Tuple[str, str]:
    """Resolve compute window using watermark or full-history start."""
    if end_date is None:
        end_date = pd.Timestamp.now("UTC").strftime("%Y-%m-%d")

    if start_date is not None:
        return start_date, end_date

    if full or watermark is None:
        return FULL_HISTORY_START, end_date

    # Incremental: watermark minus warmup
    start = (pd.Timestamp(watermark) - pd.Timedelta(days=WARMUP_DAYS)).strftime(
        "%Y-%m-%d"
    )
    logger.info("Watermark: %s, warmup start: %s", watermark, start)
    return start, end_date


# ---------------------------------------------------------------------------
# BTC/ETH asset ID lookup
# ---------------------------------------------------------------------------


def _lookup_btc_eth_ids(engine: Engine) -> Tuple[int, int]:
    """Look up BTC and ETH asset IDs from cmc_price_histories7.

    Falls back to hardcoded IDs (1, 52) if lookup fails.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT symbol, id FROM cmc_price_histories7 "
                    "WHERE symbol IN ('BTC', 'ETH') "
                    "GROUP BY symbol, id ORDER BY symbol"
                )
            ).fetchall()
        mapping = {r[0]: r[1] for r in row}
        btc_id = mapping.get("BTC", _BTC_ID_FALLBACK)
        eth_id = mapping.get("ETH", _ETH_ID_FALLBACK)
        logger.debug("BTC id=%d, ETH id=%d (from DB)", btc_id, eth_id)
        return btc_id, eth_id
    except Exception:  # noqa: BLE001
        logger.warning(
            "Could not look up BTC/ETH ids -- using fallback (%d, %d)",
            _BTC_ID_FALLBACK,
            _ETH_ID_FALLBACK,
        )
        return _BTC_ID_FALLBACK, _ETH_ID_FALLBACK


# ---------------------------------------------------------------------------
# XAGG-01 + XAGG-02: Cross-asset correlation
# ---------------------------------------------------------------------------


def compute_cross_asset_corr(
    engine: Engine,
    config: Dict[str, Any],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Compute BTC/ETH and average pairwise cross-asset correlations.

    XAGG-01: BTC/ETH 30d rolling Pearson correlation.
    XAGG-02: Average pairwise 30d rolling correlation across ALL tracked assets,
             with a high_corr_flag signaling macro-driven market conditions.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    config:
        Cross-asset config dict (from load_cross_asset_config()).
    start_date:
        Optional override start date (ISO format). If None, uses watermark.
    end_date:
        Optional override end date (ISO format). If None, uses today.

    Returns
    -------
    pd.DataFrame with columns:
        date, btc_eth_corr_30d, avg_pairwise_corr_30d, high_corr_flag, n_assets
    """
    ca_cfg = config["cross_asset"]
    window = int(ca_cfg.get("btc_eth_corr_window", 30))
    avg_window = int(ca_cfg.get("avg_pairwise_corr_window", 30))
    high_corr_threshold = float(ca_cfg.get("high_corr_threshold", 0.7))
    min_assets = int(ca_cfg.get("min_assets_for_avg", 3))

    # Resolve date range using cross_asset_agg watermark
    wm = get_watermark(engine, "cross_asset_agg")
    start, end = _resolve_date_range(start_date, end_date, wm)
    logger.info("XAGG-01/02 compute window: %s to %s", start, end)

    # --- Load CMC daily returns (tf='1D', roll=FALSE) ---
    cmc_sql = text(
        'SELECT id, "timestamp"::date AS date, ret_arith '
        "FROM returns_bars_multi_tf_u "
        "WHERE tf = '1D' AND roll = FALSE AND alignment_source = 'multi_tf' "
        'AND "timestamp"::date >= :start AND "timestamp"::date <= :end '
        "ORDER BY id, date"
    )
    try:
        with engine.connect() as conn:
            cmc_df = pd.read_sql(cmc_sql, conn, params={"start": start, "end": end})
    except Exception as exc:
        logger.error("Failed to load CMC returns: %s", exc)
        raise

    # --- Load TVC daily prices and compute simple returns ---
    tvc_sql = text(
        "SELECT h.id, p.ts::date AS date, p.close "
        "FROM tvc_price_histories_meta h "
        "JOIN tvc_price_histories p ON p.id = h.id "
        "WHERE p.tf = '1D' "
        "AND p.ts::date >= :start AND p.ts::date <= :end "
        "ORDER BY h.id, date"
    )
    try:
        with engine.connect() as conn:
            tvc_raw = pd.read_sql(tvc_sql, conn, params={"start": start, "end": end})
        if not tvc_raw.empty:
            tvc_raw["date"] = pd.to_datetime(tvc_raw["date"], utc=True).dt.date
            tvc_raw = tvc_raw.sort_values(["id", "date"])
            tvc_raw["ret_arith"] = tvc_raw.groupby("id")["close"].pct_change()
            tvc_raw = tvc_raw[["id", "date", "ret_arith"]].dropna(subset=["ret_arith"])
            tvc_raw["id"] = tvc_raw["id"].astype(str).apply(lambda x: f"tvc_{x}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("TVC price load failed (continuing with CMC only): %s", exc)
        tvc_raw = pd.DataFrame(columns=["id", "date", "ret_arith"])

    # --- Merge return sets ---
    if not cmc_df.empty:
        cmc_df["date"] = pd.to_datetime(cmc_df["date"], utc=True).dt.date
        cmc_df["id"] = cmc_df["id"].astype(str)

    all_returns = pd.concat(
        [
            df
            for df in [
                cmc_df[["id", "date", "ret_arith"]]
                if not cmc_df.empty
                else pd.DataFrame(),
                tvc_raw,
            ]
            if not df.empty
        ],
        ignore_index=True,
    )

    if all_returns.empty:
        logger.warning("No return data found for XAGG-01/02; returning empty DataFrame")
        return pd.DataFrame(
            columns=[
                "date",
                "btc_eth_corr_30d",
                "avg_pairwise_corr_30d",
                "high_corr_flag",
                "n_assets",
            ]
        )

    # Pivot to wide: rows=dates, columns=asset ids
    returns_wide = all_returns.pivot_table(
        index="date", columns="id", values="ret_arith", aggfunc="first"
    )
    returns_wide.index = pd.to_datetime(returns_wide.index)
    returns_wide = returns_wide.sort_index()

    # --- XAGG-01: BTC/ETH 30d rolling correlation ---
    btc_id, eth_id = _lookup_btc_eth_ids(engine)
    btc_col = str(btc_id)
    eth_col = str(eth_id)

    btc_eth_corr: pd.Series = pd.Series(dtype=float, name="btc_eth_corr_30d")
    if btc_col in returns_wide.columns and eth_col in returns_wide.columns:
        btc_eth_corr = (
            returns_wide[btc_col]
            .rolling(window=window, min_periods=_CORR_MIN_PERIODS)
            .corr(returns_wide[eth_col])
            .rename("btc_eth_corr_30d")
        )
    else:
        logger.warning(
            "BTC (id=%s) or ETH (id=%s) not found in returns -- XAGG-01 will be NULL",
            btc_col,
            eth_col,
        )
        btc_eth_corr = pd.Series(
            [None] * len(returns_wide),
            index=returns_wide.index,
            name="btc_eth_corr_30d",
        )

    # --- XAGG-02: Average pairwise 30d rolling correlation ---
    # Compute rolling correlation matrix, extract upper triangle mean per date.
    n_assets_series = returns_wide.notna().sum(axis=1).rename("n_assets")

    avg_pairwise: List[Optional[float]] = []
    all_dates = returns_wide.index

    for i, dt in enumerate(all_dates):
        # Slice the window of rows ending at this date
        window_slice = returns_wide.iloc[max(0, i - avg_window + 1) : i + 1]

        # Minimum: need at least min_assets and _CORR_MIN_PERIODS rows
        n_valid = window_slice.shape[0]
        if n_valid < _CORR_MIN_PERIODS:
            avg_pairwise.append(None)
            continue

        # Drop columns with any NaN in this window to get stable pairwise corr
        valid_cols = window_slice.dropna(axis=1, how="any").columns
        if len(valid_cols) < min_assets:
            avg_pairwise.append(None)
            continue

        corr_mat = window_slice[valid_cols].corr()
        # Extract upper triangle (k=1 excludes diagonal)
        import numpy as np

        upper_tri = corr_mat.values[np.triu_indices_from(corr_mat.values, k=1)]
        if len(upper_tri) == 0:
            avg_pairwise.append(None)
        else:
            avg_pairwise.append(float(np.nanmean(upper_tri)))

    avg_pairwise_series = pd.Series(
        avg_pairwise, index=all_dates, name="avg_pairwise_corr_30d"
    )

    # --- Assemble result DataFrame ---
    result = pd.DataFrame(
        {
            "date": all_dates,
            "btc_eth_corr_30d": btc_eth_corr.values
            if len(btc_eth_corr) == len(all_dates)
            else [None] * len(all_dates),
            "avg_pairwise_corr_30d": avg_pairwise_series.values,
            "n_assets": n_assets_series.values,
        }
    )

    # high_corr_flag
    result["high_corr_flag"] = result["avg_pairwise_corr_30d"].apply(
        lambda x: bool(x > high_corr_threshold) if x is not None and x == x else None
    )

    # Convert date to date objects (not datetime)
    result["date"] = pd.to_datetime(result["date"]).dt.date

    # Filter to requested end window (remove warmup-only rows if desired)
    # Keep all rows so watermark can advance correctly
    result = result.dropna(
        subset=["btc_eth_corr_30d", "avg_pairwise_corr_30d"], how="all"
    )

    logger.info("XAGG-01/02: computed %d rows", len(result))
    return result


# ---------------------------------------------------------------------------
# XAGG-01/02 upsert
# ---------------------------------------------------------------------------


def upsert_cross_asset_agg(engine: Engine, df: pd.DataFrame) -> int:
    """Upsert cross-asset correlation DataFrame into cross_asset_agg.

    Uses temp table + INSERT...ON CONFLICT(date) DO UPDATE pattern.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with columns: date, btc_eth_corr_30d, avg_pairwise_corr_30d,
        high_corr_flag, n_assets.

    Returns
    -------
    Number of rows upserted.
    """
    if df.empty:
        return 0

    df = df.copy()
    df = _sanitize_dataframe(df)

    col_list = [
        "date",
        "btc_eth_corr_30d",
        "avg_pairwise_corr_30d",
        "high_corr_flag",
        "n_assets",
    ]
    # Ensure only known columns are used
    col_list = [c for c in col_list if c in df.columns]
    cols_str = ", ".join(col_list)
    update_cols = [c for c in col_list if c != "date"]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    set_clause += ", ingested_at = now()"

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE _xagg_corr_staging "
                "(LIKE cross_asset_agg INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
        )
        df[col_list].to_sql(
            "_xagg_corr_staging",
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )
        result = conn.execute(
            text(
                f"INSERT INTO cross_asset_agg ({cols_str}) "
                f"SELECT {cols_str} FROM _xagg_corr_staging "
                f"ON CONFLICT (date) DO UPDATE SET {set_clause}"
            )
        )
        row_count = result.rowcount

    logger.info("Upserted %d rows into cross_asset_agg", row_count)
    return row_count


# ---------------------------------------------------------------------------
# XAGG-03: Funding rate aggregation
# ---------------------------------------------------------------------------


def compute_funding_rate_agg(
    engine: Engine,
    config: Dict[str, Any],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Compute aggregate funding rate signal with 30d and 90d z-scores.

    XAGG-03: Loads daily rollup funding rates from funding_rates (tf='1d'),
    groups by (date, symbol), computes simple average across venues, and
    computes 30d and 90d rolling z-scores per symbol.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    config:
        Cross-asset config dict (from load_cross_asset_config()).
    start_date:
        Optional override start date. If None, uses watermark.
    end_date:
        Optional override end date. If None, uses today.

    Returns
    -------
    pd.DataFrame with columns:
        date, symbol, avg_funding_rate, vwap_funding_rate, n_venues,
        zscore_30d, zscore_90d, venues_included
    """
    fa_cfg = config.get("funding_agg", {})
    zscore_windows = fa_cfg.get("zscore_windows", [30, 90])
    window_30 = int(zscore_windows[0]) if len(zscore_windows) > 0 else 30
    window_90 = int(zscore_windows[1]) if len(zscore_windows) > 1 else 90

    # Resolve date range using funding_rate_agg watermark
    wm = get_watermark(engine, "funding_rate_agg")
    start, end = _resolve_date_range(start_date, end_date, wm)
    logger.info("XAGG-03 compute window: %s to %s", start, end)

    # Load daily rollup funding rates (tf='1d')
    sql = text(
        "SELECT ts::date AS date, symbol, venue_id, funding_rate "
        "FROM funding_rates "
        "WHERE tf = '1d' "
        "AND ts::date >= :start AND ts::date <= :end "
        "ORDER BY symbol, date, venue_id"
    )
    try:
        with engine.connect() as conn:
            raw = pd.read_sql(sql, conn, params={"start": start, "end": end})
    except Exception as exc:
        logger.error("Failed to load funding rates: %s", exc)
        raise

    if raw.empty:
        logger.warning(
            "No funding rate data found for XAGG-03; returning empty DataFrame"
        )
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "avg_funding_rate",
                "vwap_funding_rate",
                "n_venues",
                "zscore_30d",
                "zscore_90d",
                "venues_included",
            ]
        )

    raw["date"] = pd.to_datetime(raw["date"], utc=True).dt.date

    # Group by (date, symbol) -- simple average across venues, NaN venues excluded
    def _agg_venues(grp: pd.DataFrame) -> pd.Series:
        valid = grp.dropna(subset=["funding_rate"])
        n_venues = len(valid)
        venues_list = sorted(valid["venue_id"].dropna().unique().tolist())
        avg_rate = float(valid["funding_rate"].mean()) if n_venues > 0 else None
        # vwap_funding_rate: NULL for now (requires volume data not consistently available)
        return pd.Series(
            {
                "avg_funding_rate": avg_rate,
                "vwap_funding_rate": None,
                "n_venues": n_venues,
                "venues_included": ",".join(str(v) for v in venues_list),
            }
        )

    grouped = raw.groupby(["date", "symbol"]).apply(_agg_venues).reset_index()

    # Compute 30d and 90d rolling z-scores per symbol
    all_parts: List[pd.DataFrame] = []
    for symbol, sym_df in grouped.groupby("symbol"):
        sym_df = sym_df.sort_values("date").copy()
        sym_df["date"] = pd.to_datetime(sym_df["date"])

        rates = sym_df["avg_funding_rate"].astype(float)

        # 30d z-score
        roll_30_mean = rates.rolling(
            window=window_30, min_periods=_CORR_MIN_PERIODS
        ).mean()
        roll_30_std = rates.rolling(
            window=window_30, min_periods=_CORR_MIN_PERIODS
        ).std(ddof=1)
        zscore_30 = (rates - roll_30_mean) / roll_30_std.replace(0, float("nan"))

        # 90d z-score
        roll_90_mean = rates.rolling(
            window=window_90, min_periods=_CORR_MIN_PERIODS
        ).mean()
        roll_90_std = rates.rolling(
            window=window_90, min_periods=_CORR_MIN_PERIODS
        ).std(ddof=1)
        zscore_90 = (rates - roll_90_mean) / roll_90_std.replace(0, float("nan"))

        sym_df["zscore_30d"] = zscore_30.values
        sym_df["zscore_90d"] = zscore_90.values
        sym_df["date"] = sym_df["date"].dt.date
        all_parts.append(sym_df)

    if not all_parts:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "avg_funding_rate",
                "vwap_funding_rate",
                "n_venues",
                "zscore_30d",
                "zscore_90d",
                "venues_included",
            ]
        )

    result = pd.concat(all_parts, ignore_index=True)
    result = result[
        [
            "date",
            "symbol",
            "avg_funding_rate",
            "vwap_funding_rate",
            "n_venues",
            "zscore_30d",
            "zscore_90d",
            "venues_included",
        ]
    ]

    logger.info(
        "XAGG-03: computed %d rows for %d symbols",
        len(result),
        result["symbol"].nunique(),
    )
    return result


# ---------------------------------------------------------------------------
# XAGG-03 upsert
# ---------------------------------------------------------------------------


def upsert_funding_rate_agg(engine: Engine, df: pd.DataFrame) -> int:
    """Upsert funding rate aggregate DataFrame into funding_rate_agg.

    Uses temp table + INSERT...ON CONFLICT(date, symbol) DO UPDATE pattern.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with columns: date, symbol, avg_funding_rate, vwap_funding_rate,
        n_venues, zscore_30d, zscore_90d, venues_included.

    Returns
    -------
    Number of rows upserted.
    """
    if df.empty:
        return 0

    df = df.copy()
    df = _sanitize_dataframe(df)

    col_list = [
        "date",
        "symbol",
        "avg_funding_rate",
        "vwap_funding_rate",
        "n_venues",
        "zscore_30d",
        "zscore_90d",
        "venues_included",
    ]
    col_list = [c for c in col_list if c in df.columns]
    cols_str = ", ".join(col_list)
    update_cols = [c for c in col_list if c not in ("date", "symbol")]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    set_clause += ", ingested_at = now()"

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE _funding_agg_staging "
                "(LIKE funding_rate_agg INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
        )
        df[col_list].to_sql(
            "_funding_agg_staging",
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )
        result = conn.execute(
            text(
                f"INSERT INTO funding_rate_agg ({cols_str}) "
                f"SELECT {cols_str} FROM _funding_agg_staging "
                f"ON CONFLICT (date, symbol) DO UPDATE SET {set_clause}"
            )
        )
        row_count = result.rowcount

    logger.info("Upserted %d rows into funding_rate_agg", row_count)
    return row_count


# ---------------------------------------------------------------------------
# XAGG-04: Crypto-macro correlation regime
# ---------------------------------------------------------------------------


def send_sign_flip_alerts(sign_flip_df: pd.DataFrame, config: Dict[str, Any]) -> int:
    """Send Telegram alerts for crypto-macro sign-flip events.

    Reads config.telegram.sign_flip_alerts to determine if alerts are enabled.
    Groups sign flips by date to avoid spamming: if more than 3 flips on the
    same date, sends a single summary message instead of individual ones.

    Parameters
    ----------
    sign_flip_df:
        DataFrame with XAGG-04 correlation rows (must contain sign_flip_flag,
        date, asset_id, macro_var, prev_corr_60d, corr_60d columns).
    config:
        Cross-asset config dict (from load_cross_asset_config()).

    Returns
    -------
    Number of Telegram alert messages sent (0 if disabled or no flips).
    """
    tg_cfg = config.get("telegram", {})
    if not tg_cfg.get("sign_flip_alerts", False):
        return 0

    if sign_flip_df.empty:
        return 0

    # Filter to sign flip rows only
    flip_df = sign_flip_df[sign_flip_df["sign_flip_flag"] == True].copy()  # noqa: E712
    if flip_df.empty:
        return 0

    # Filter to window=60 only to avoid alert spam from multi-window rows (Phase 97)
    if "window" in flip_df.columns:
        flip_df = flip_df[flip_df["window"] == 60]
        if flip_df.empty:
            return 0

    # Import Telegram module with graceful fallback
    try:
        from ta_lab2.notifications.telegram import is_configured, send_alert
    except ImportError:
        logger.warning(
            "ta_lab2.notifications.telegram not importable; skipping sign-flip alerts"
        )
        return 0

    if not is_configured():
        logger.warning("Telegram not configured; skipping sign-flip alerts")
        return 0

    alerts_sent = 0
    spam_threshold = 3

    # Group by date
    for flip_date, date_group in flip_df.groupby("date"):
        n_flips = len(date_group)
        try:
            if n_flips > spam_threshold:
                # Send a summary instead of individual alerts
                message = (
                    f"{n_flips} crypto-macro sign flips detected on {flip_date}\n\n"
                    "Top flips:\n"
                )
                for _, row in date_group.head(spam_threshold).iterrows():
                    prev = row.get("prev_corr_60d")
                    curr = row.get("corr_60d")
                    prev_str = f"{prev:.3f}" if prev is not None else "N/A"
                    curr_str = f"{curr:.3f}" if curr is not None else "N/A"
                    message += (
                        f"  Asset: id={row['asset_id']}  "
                        f"Macro: {row['macro_var']}  "
                        f"Corr: {prev_str} -> {curr_str}\n"
                    )
                remaining = n_flips - spam_threshold
                if remaining > 0:
                    message += f"  ... and {remaining} more"
                send_alert("CRYPTO-MACRO SIGN FLIP", message, severity="warning")
                alerts_sent += 1
            else:
                # Send individual alerts
                for _, row in date_group.iterrows():
                    prev = row.get("prev_corr_60d")
                    curr = row.get("corr_60d")
                    prev_str = f"{prev:.3f}" if prev is not None else "N/A"
                    curr_str = f"{curr:.3f}" if curr is not None else "N/A"
                    asset_id = row.get("asset_id", "?")
                    macro_var = row.get("macro_var", "?")
                    message = (
                        f"Asset: id={asset_id}\n"
                        f"Macro Var: {macro_var}\n"
                        f"Correlation: {prev_str} -> {curr_str}\n"
                        f"Date: {flip_date}"
                    )
                    send_alert("CRYPTO-MACRO SIGN FLIP", message, severity="warning")
                    alerts_sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sign-flip alert failed for date %s: %s", flip_date, exc)

    logger.info("Sent %d sign-flip Telegram alert(s)", alerts_sent)
    return alerts_sent


def compute_crypto_macro_corr(
    engine: Engine,
    config: Dict[str, Any],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    alert_new_only: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Compute crypto-macro correlation regime with sign-flip detection.

    XAGG-04: Computes 60d rolling Pearson correlation between each tradeable
    asset's daily returns and macro variable daily changes (VIX, DXY, HY OAS,
    net_liquidity). Detects sign flips (correlation crossing the threshold
    magnitude in opposite direction) and assigns a regime label.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    config:
        Cross-asset config dict (from load_cross_asset_config()).
    start_date:
        Optional override start date. If None, uses watermark.
    end_date:
        Optional override end date. If None, uses today.
    alert_new_only:
        When True (default), Telegram alerts are only sent for dates after the
        watermark (i.e. newly computed rows). Set to False to suppress all alerts
        (useful during --full historical recompute to avoid spamming old flips).

    Returns
    -------
    Tuple of two DataFrames:
        crypto_macro_corr_df: columns: date, asset_id, macro_var, corr_60d,
            prev_corr_60d, sign_flip_flag, corr_regime
        macro_regime_update_df: columns: date, crypto_macro_corr (TEXT label)
    """
    cm_cfg = config.get("crypto_macro", {})
    corr_window = int(cm_cfg.get("corr_window", 60))
    sign_flip_threshold = float(cm_cfg.get("sign_flip_threshold", 0.3))
    macro_var_columns: Dict[str, str] = cm_cfg.get(
        "macro_var_columns",
        {
            "vix": "vixcls",
            "dxy": "dtwexbgs",
            "hy_oas": "bamlh0a0hym2",
            "net_liquidity": "net_liquidity",
        },
    )

    empty_corr = pd.DataFrame(
        columns=[
            "date",
            "asset_id",
            "macro_var",
            "corr_60d",
            "prev_corr_60d",
            "sign_flip_flag",
            "corr_regime",
        ]
    )
    empty_regime = pd.DataFrame(columns=["date", "crypto_macro_corr"])

    # Resolve date range using crypto_macro_corr_regimes watermark
    wm = get_watermark(engine, "crypto_macro_corr_regimes")
    start, end = _resolve_date_range(start_date, end_date, wm)
    logger.info("XAGG-04 compute window: %s to %s", start, end)

    # --- Load crypto daily returns (tf='1D', roll=FALSE) ---
    ret_sql = text(
        'SELECT id, "timestamp"::date AS date, ret_arith '
        "FROM returns_bars_multi_tf_u "
        "WHERE tf = '1D' AND roll = FALSE AND alignment_source = 'multi_tf' "
        'AND "timestamp"::date >= :start AND "timestamp"::date <= :end '
        "ORDER BY id, date"
    )
    try:
        with engine.connect() as conn:
            ret_df = pd.read_sql(ret_sql, conn, params={"start": start, "end": end})
    except Exception as exc:
        logger.error("Failed to load crypto returns for XAGG-04: %s", exc)
        raise

    if ret_df.empty:
        logger.warning("No crypto return data for XAGG-04; returning empty DataFrames")
        return empty_corr, empty_regime

    ret_df["date"] = pd.to_datetime(ret_df["date"], utc=True).dt.date

    # Filter to tier-1 assets only (Phase 97 requirement)
    try:
        with engine.connect() as conn:
            tier1_ids = [
                row[0]
                for row in conn.execute(
                    text("SELECT DISTINCT id FROM dim_assets WHERE pipeline_tier = 1")
                ).fetchall()
            ]
        if tier1_ids:
            before_count = ret_df["id"].nunique()
            ret_df = ret_df[ret_df["id"].isin(tier1_ids)]
            logger.info(
                "XAGG-04: filtered to %d tier-1 assets (was %d)",
                ret_df["id"].nunique(),
                before_count,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Could not load tier-1 asset filter (continuing with all assets): %s", exc
        )

    # --- Load macro features ---
    macro_cols_needed = list(macro_var_columns.values())
    macro_cols_str = ", ".join(macro_cols_needed)
    macro_sql = text(
        f"SELECT date, {macro_cols_str} "  # noqa: S608
        "FROM fred.fred_macro_features "
        "WHERE date >= :start AND date <= :end "
        "ORDER BY date"
    )
    try:
        with engine.connect() as conn:
            macro_df = pd.read_sql(macro_sql, conn, params={"start": start, "end": end})
    except Exception as exc:
        logger.error("Failed to load macro features for XAGG-04: %s", exc)
        raise

    if macro_df.empty:
        logger.warning(
            "No macro features found for XAGG-04; returning empty DataFrames"
        )
        return empty_corr, empty_regime

    macro_df["date"] = pd.to_datetime(macro_df["date"]).dt.date
    macro_df = macro_df.set_index("date").sort_index()

    # Compute macro variable changes
    # VIX, DXY, HY_OAS: use daily diff (change in level)
    # net_liquidity: use level directly (it already represents a flow proxy)
    macro_changes: Dict[str, pd.Series] = {}
    for var_label, col_name in macro_var_columns.items():
        if col_name not in macro_df.columns:
            logger.warning(
                "Macro column %s not found; skipping %s", col_name, var_label
            )
            continue
        series = macro_df[col_name].astype(float)
        if var_label == "net_liquidity":
            macro_changes[var_label] = series  # level
        else:
            macro_changes[var_label] = series.diff()  # daily change

    if not macro_changes:
        logger.warning("No macro variables available for XAGG-04")
        return empty_corr, empty_regime

    # Pivot crypto returns to wide: rows=dates, cols=asset_ids
    crypto_wide = ret_df.pivot_table(
        index="date", columns="id", values="ret_arith", aggfunc="first"
    )
    crypto_wide.index = pd.to_datetime(crypto_wide.index)
    crypto_wide = crypto_wide.sort_index()

    # Build combined index spanning both crypto and macro date ranges
    macro_index = pd.DatetimeIndex([pd.Timestamp(d) for d in macro_df.index])
    all_index = crypto_wide.index.union(macro_index)

    # Align macro changes to the shared index
    macro_aligned: Dict[str, pd.Series] = {}
    for var_label, series in macro_changes.items():
        aligned = series.reindex(
            pd.DatetimeIndex([pd.Timestamp(d) for d in series.index])
        )
        aligned = aligned.reindex(all_index)
        macro_aligned[var_label] = aligned

    # Align crypto returns to the shared index
    crypto_aligned = crypto_wide.reindex(all_index)

    # --- Compute 60d rolling correlations per (asset, macro_var) ---
    all_corr_rows: List[Dict[str, Any]] = []

    asset_ids = crypto_wide.columns.tolist()

    for asset_id in asset_ids:
        asset_returns = crypto_aligned[asset_id]

        for var_label, macro_series in macro_aligned.items():
            # 60d rolling Pearson correlation
            roll_corr = asset_returns.rolling(
                window=corr_window, min_periods=_CORR_MIN_PERIODS
            ).corr(macro_series)

            # Shift by 1 day for prev_corr_60d
            prev_corr = roll_corr.shift(1)

            # Process each date
            for dt in all_index:
                corr_val = _to_python(roll_corr.get(dt))
                prev_val = _to_python(prev_corr.get(dt))

                if corr_val is None:
                    continue

                # Sign-flip detection
                flip = False
                if prev_val is not None:
                    went_positive = (
                        prev_val < -sign_flip_threshold
                        and corr_val > sign_flip_threshold
                    )
                    went_negative = (
                        prev_val > sign_flip_threshold
                        and corr_val < -sign_flip_threshold
                    )
                    flip = went_positive or went_negative

                # Regime label
                if flip:
                    regime = "flipping"
                elif abs(corr_val) > sign_flip_threshold:
                    regime = "correlated"
                else:
                    regime = "decorrelated"

                all_corr_rows.append(
                    {
                        "date": dt.date() if hasattr(dt, "date") else dt,
                        "asset_id": int(asset_id),
                        "macro_var": var_label,
                        "window": corr_window,
                        "corr_60d": corr_val,
                        "prev_corr_60d": prev_val,
                        "sign_flip_flag": flip,
                        "corr_regime": regime,
                    }
                )

    if not all_corr_rows:
        logger.warning("No correlation rows computed for XAGG-04")
        return empty_corr, empty_regime

    corr_df = pd.DataFrame(all_corr_rows)
    logger.info(
        "XAGG-04: computed %d correlation rows for %d assets x %d macro vars",
        len(corr_df),
        corr_df["asset_id"].nunique(),
        corr_df["macro_var"].nunique(),
    )

    # --- Compute daily aggregate macro regime label ---
    # Per date: if ANY sign_flip_flag -> 'flipping'
    # elif majority 'correlated' -> 'correlated'
    # else -> 'decorrelated'
    regime_rows: List[Dict[str, Any]] = []
    for dt, day_df in corr_df.groupby("date"):
        if day_df["sign_flip_flag"].any():
            label = "flipping"
        else:
            n_total = len(day_df)
            n_corr = (day_df["corr_regime"] == "correlated").sum()
            label = "correlated" if n_corr > (n_total / 2) else "decorrelated"
        regime_rows.append({"date": dt, "crypto_macro_corr": label})

    regime_df = pd.DataFrame(regime_rows)
    logger.info("XAGG-04: computed %d macro_regime label rows", len(regime_df))

    # --- Send Telegram sign-flip alerts ---------------------------------
    # Only alert on new rows (dates after watermark) to avoid spamming
    # historical sign flips during --full recompute runs.
    try:
        alert_df = corr_df
        if alert_new_only and wm is not None:
            alert_df = corr_df[
                corr_df["date"].apply(
                    lambda d: (d if not hasattr(d, "date") else d) > wm
                )
            ]
        elif not alert_new_only:
            # Caller opted out of alerts (e.g. --full historical mode)
            alert_df = pd.DataFrame(columns=corr_df.columns)
        send_sign_flip_alerts(alert_df, config)
    except Exception as exc:  # noqa: BLE001
        logger.warning("sign-flip alert error (non-fatal): %s", exc)

    return corr_df, regime_df


# ---------------------------------------------------------------------------
# XAGG-05: BTC-equity multi-window rolling correlation
# ---------------------------------------------------------------------------


def compute_btc_equity_corr(
    engine: Engine,
    config: Dict[str, Any],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    """Compute multi-window rolling BTC-equity correlation with vol regime and divergence.

    Phase 97 MACRO-02: For each equity index (SP500, NASDAQCOM, DJIA) and each
    correlation window (30d, 60d, 90d, 180d):
      1. Compute rolling Pearson correlation between BTC daily returns and equity daily returns
      2. Classify equity vol regime (calm/elevated/crisis) from realized vol
      3. Cross-validate vs VIX regime (vix_agreement_flag)
      4. Compute divergence signal (dual-method: vol z-score spread + corr regime shift)

    IMPORTANT: Equity returns are computed as .diff() on raw SP500/NASDAQCOM/DJIA level
    from fred_macro_features (matching the existing vix/dxy pattern in XAGG-04).
    Realized vol uses .pct_change() on equity levels for correct annualization.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the marketdata database.
    config:
        Cross-asset config dict (must have 'btc_equity' key).
    start_date:
        Optional override start date (ISO format). If None, uses watermark.
    end_date:
        Optional override end date (ISO format). If None, uses today.

    Returns
    -------
    pd.DataFrame with columns: date, asset_id, macro_var, window, corr_60d,
        prev_corr_60d, sign_flip_flag, corr_regime, equity_vol_regime,
        vix_agreement_flag, realized_vol_z, vix_z, vol_spread, divergence_zscore,
        divergence_flag
    """
    be_cfg = config.get("btc_equity", {})
    corr_windows: List[int] = be_cfg.get("corr_windows", [30, 60, 90, 180])
    equity_vars: Dict[str, str] = be_cfg.get(
        "equity_macro_vars",
        {"SP500": "sp500", "NASDAQCOM": "nasdaqcom"},
    )
    vol_thresholds: Dict[str, Any] = be_cfg.get(
        "vol_regime_thresholds",
        {"calm_upper": 15.0, "elevated_upper": 25.0},
    )
    div_zscore_threshold = float(be_cfg.get("divergence_zscore_threshold", 2.0))
    sign_flip_threshold = float(
        config.get("crypto_macro", {}).get("sign_flip_threshold", 0.3)
    )

    calm_upper = float(vol_thresholds.get("calm_upper", 15.0))
    elevated_upper = float(vol_thresholds.get("elevated_upper", 25.0))

    # Resolve date range using crypto_macro_corr_regimes watermark
    wm = get_watermark(engine, "crypto_macro_corr_regimes")
    start, end = _resolve_date_range(start_date, end_date, wm)
    logger.info("BTC-equity corr compute window: %s to %s", start, end)

    # --- Load BTC daily returns ---
    # Filter to venue_id=1 (CMC_AGG) to avoid duplicate rows from multi-venue tables.
    btc_id, _ = _lookup_btc_eth_ids(engine)
    ret_sql = text(
        'SELECT "timestamp"::date AS date, ret_arith '
        "FROM returns_bars_multi_tf_u "
        "WHERE tf = '1D' AND roll = FALSE AND alignment_source = 'multi_tf' "
        "AND id = :btc_id AND venue_id = 1 "
        'AND "timestamp"::date >= :start AND "timestamp"::date <= :end '
        "ORDER BY date"
    )
    with engine.connect() as conn:
        btc_df = pd.read_sql(
            ret_sql, conn, params={"btc_id": btc_id, "start": start, "end": end}
        )

    if btc_df.empty:
        logger.warning("No BTC return data for BTC-equity corr")
        return pd.DataFrame()

    btc_df["date"] = pd.to_datetime(btc_df["date"], utc=True).dt.date
    btc_returns = btc_df.set_index("date")["ret_arith"].sort_index()
    btc_returns.index = pd.DatetimeIndex(btc_returns.index)

    # --- Load equity index raw levels + VIX from fred_macro_features ---
    equity_cols = list(equity_vars.values())
    cols_needed = equity_cols + ["vixcls"]
    cols_str = ", ".join(cols_needed)
    macro_sql = text(
        f"SELECT date, {cols_str} "  # noqa: S608
        "FROM fred.fred_macro_features "
        "WHERE date >= :start AND date <= :end "
        "ORDER BY date"
    )
    with engine.connect() as conn:
        macro_df = pd.read_sql(macro_sql, conn, params={"start": start, "end": end})

    if macro_df.empty:
        logger.warning("No macro features for BTC-equity corr")
        return pd.DataFrame()

    macro_df["date"] = pd.to_datetime(macro_df["date"]).dt.date
    macro_df = macro_df.set_index("date").sort_index()
    macro_df.index = pd.DatetimeIndex(macro_df.index)

    # --- Compute equity daily changes (use .diff() on raw level, matching vix/dxy pattern) ---
    equity_changes: Dict[str, pd.Series] = {}
    for var_label, col_name in equity_vars.items():
        if col_name in macro_df.columns:
            equity_changes[var_label] = macro_df[col_name].astype(float).diff()
        else:
            logger.warning(
                "Equity column %s not found in fred_macro_features; skipping %s",
                col_name,
                var_label,
            )

    if not equity_changes:
        logger.warning("No equity columns found for BTC-equity corr")
        return pd.DataFrame()

    vix_series: Optional[pd.Series] = (
        macro_df["vixcls"].astype(float) if "vixcls" in macro_df.columns else None
    )

    # --- Align BTC returns to combined date range ---
    all_index = btc_returns.index.union(macro_df.index)
    btc_aligned = btc_returns.reindex(all_index)

    # --- Compute multi-window correlations ---
    all_rows: List[Dict[str, Any]] = []

    for var_label, equity_change in equity_changes.items():
        col_name = equity_vars[var_label]
        equity_aligned = equity_change.reindex(all_index)

        # Realized vol of equity for vol regime classification (21d rolling, annualized)
        # Use pct_change() on raw levels (not .diff()) for proper vol scaling
        if col_name in macro_df.columns:
            equity_daily_ret = (
                macro_df[col_name].astype(float).pct_change(fill_method=None)
            )
            equity_daily_ret_aligned = equity_daily_ret.reindex(all_index)
            realized_vol_21d = (
                equity_daily_ret_aligned.rolling(21, min_periods=17).std()
                * (252**0.5)
                * 100.0
            )
        else:
            realized_vol_21d = pd.Series(float("nan"), index=all_index)

        # VIX aligned for cross-validation
        vix_aligned = (
            vix_series.reindex(all_index)
            if vix_series is not None
            else pd.Series(float("nan"), index=all_index)
        )

        for window in corr_windows:
            # Rolling Pearson correlation
            roll_corr = btc_aligned.rolling(
                window=window, min_periods=max(10, int(window * 0.5))
            ).corr(equity_aligned)

            prev_corr = roll_corr.shift(1)

            # Convert to plain numpy arrays indexed by position for scalar access
            roll_corr_vals = roll_corr.values
            prev_corr_vals = prev_corr.values
            rv_vals = realized_vol_21d.reindex(all_index).values
            vix_vals = vix_aligned.reindex(all_index).values

            for i, dt in enumerate(all_index):
                corr_val = _to_python(roll_corr_vals[i])
                if corr_val is None:
                    continue

                prev_val = _to_python(prev_corr_vals[i])
                rv = _to_python(rv_vals[i])
                vix_val = _to_python(vix_vals[i])

                # Sign-flip detection
                flip = False
                if prev_val is not None:
                    went_pos = (
                        prev_val < -sign_flip_threshold
                        and corr_val > sign_flip_threshold
                    )
                    went_neg = (
                        prev_val > sign_flip_threshold
                        and corr_val < -sign_flip_threshold
                    )
                    flip = went_pos or went_neg

                # Correlation regime
                if flip:
                    regime = "flipping"
                elif abs(corr_val) > sign_flip_threshold:
                    regime = "correlated"
                else:
                    regime = "decorrelated"

                # Equity vol regime (from 21d realized vol)
                if rv is not None:
                    if rv <= calm_upper:
                        eq_vol_regime: Optional[str] = "calm"
                    elif rv <= elevated_upper:
                        eq_vol_regime = "elevated"
                    else:
                        eq_vol_regime = "crisis"
                else:
                    eq_vol_regime = None

                # VIX-derived regime for cross-validation
                vix_regime_val: Optional[str] = None
                if vix_val is not None:
                    if vix_val <= calm_upper:
                        vix_regime_val = "calm"
                    elif vix_val <= elevated_upper:
                        vix_regime_val = "elevated"
                    else:
                        vix_regime_val = "crisis"

                # VIX agreement flag: equity vol regime matches VIX-derived regime
                vix_agreement: Optional[bool] = None
                if eq_vol_regime is not None and vix_regime_val is not None:
                    vix_agreement = eq_vol_regime == vix_regime_val

                # Z-scores and divergence computed post-hoc (vectorized below)
                all_rows.append(
                    {
                        "date": dt.date() if hasattr(dt, "date") else dt,
                        "asset_id": btc_id,
                        "macro_var": var_label,
                        "window": window,
                        "corr_60d": corr_val,  # Keep column name as-is (research finding #8)
                        "prev_corr_60d": prev_val,
                        "sign_flip_flag": flip,
                        "corr_regime": regime,
                        "equity_vol_regime": eq_vol_regime,
                        "vix_agreement_flag": vix_agreement,
                        "realized_vol_z": None,  # Filled below
                        "vix_z": None,  # Filled below
                        "vol_spread": None,  # Filled below
                        "divergence_zscore": None,  # Filled below
                        "divergence_flag": None,  # Filled below
                    }
                )

    if not all_rows:
        logger.warning("No BTC-equity correlation rows computed")
        return pd.DataFrame()

    result_df = pd.DataFrame(all_rows)

    # --- Post-hoc vectorized computation of z-scores and divergence ---
    # More efficient than per-row computation in the inner loop above.
    for var_label in equity_changes:
        col_name = equity_vars[var_label]
        for window in corr_windows:
            mask = (result_df["macro_var"] == var_label) & (
                result_df["window"] == window
            )
            subset = result_df.loc[mask].copy().sort_values("date")

            if subset.empty:
                continue

            dates = pd.DatetimeIndex(pd.to_datetime(subset["date"]))

            # Realized vol z-score (63d rolling)
            if col_name in macro_df.columns:
                eq_ret = macro_df[col_name].astype(float).pct_change(fill_method=None)
                rv_series = (
                    eq_ret.rolling(21, min_periods=17).std() * (252**0.5) * 100.0
                )
                rv_aligned = rv_series.reindex(dates)
                rv_z_series = _rolling_zscore_series(rv_aligned, 63)
                result_df.loc[mask, "realized_vol_z"] = rv_z_series.values

            # VIX z-score (63d rolling)
            if vix_series is not None:
                vix_aligned_sub = vix_series.reindex(dates)
                vix_z_series = _rolling_zscore_series(vix_aligned_sub, 63)
                result_df.loc[mask, "vix_z"] = vix_z_series.values

                # Vol spread = realized_vol_z - vix_z
                rv_z_vals = result_df.loc[mask, "realized_vol_z"].astype(float)
                vix_z_vals = result_df.loc[mask, "vix_z"].astype(float)
                vol_spread = rv_z_vals.values - vix_z_vals.values
                result_df.loc[mask, "vol_spread"] = vol_spread

                # Divergence z-score: rolling z-score of the vol_spread itself (63d)
                vol_spread_series = pd.Series(vol_spread, index=range(len(vol_spread)))
                div_z = _rolling_zscore_series(vol_spread_series, 63)
                result_df.loc[mask, "divergence_zscore"] = div_z.values

                # Divergence flag: |divergence_zscore| > threshold
                result_df.loc[mask, "divergence_flag"] = (
                    div_z.abs() > div_zscore_threshold
                ).values

    logger.info(
        "BTC-equity corr: %d rows for %d equity vars x %d windows",
        len(result_df),
        len(equity_changes),
        len(corr_windows),
    )
    return result_df


# ---------------------------------------------------------------------------
# XAGG-04 upserts
# ---------------------------------------------------------------------------


def upsert_crypto_macro_corr(engine: Engine, df: pd.DataFrame) -> int:
    """Upsert crypto-macro correlation DataFrame into crypto_macro_corr_regimes.

    Uses temp table + INSERT...ON CONFLICT(date, asset_id, macro_var, window) DO UPDATE.

    Phase 97 update: window is now part of the PK. All 8 new columns (window,
    equity_vol_regime, vix_agreement_flag, realized_vol_z, vix_z, vol_spread,
    divergence_zscore, divergence_flag) are included when present in df.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with columns: date, asset_id, macro_var, window, corr_60d,
        prev_corr_60d, sign_flip_flag, corr_regime, and optionally:
        equity_vol_regime, vix_agreement_flag, realized_vol_z, vix_z, vol_spread,
        divergence_zscore, divergence_flag.

    Returns
    -------
    Number of rows upserted.
    """
    if df.empty:
        return 0

    df = df.copy()

    # Backward compatibility: if no window column (old XAGG-04 call path), default to 60.
    if "window" not in df.columns:
        df["window"] = 60

    df = _sanitize_dataframe(df)

    col_list = [
        "date",
        "asset_id",
        "macro_var",
        "window",
        "corr_60d",
        "prev_corr_60d",
        "sign_flip_flag",
        "corr_regime",
        "equity_vol_regime",
        "vix_agreement_flag",
        "realized_vol_z",
        "vix_z",
        "vol_spread",
        "divergence_zscore",
        "divergence_flag",
    ]
    col_list = [c for c in col_list if c in df.columns]
    # 'window' is a PostgreSQL reserved word -- must be double-quoted in SQL.
    # Build quoted column string for SQL but keep unquoted names for DataFrame access.
    _reserved = {"window"}

    def _q(name: str) -> str:
        return f'"{name}"' if name in _reserved else name

    cols_str = ", ".join(_q(c) for c in col_list)
    update_cols = [
        c for c in col_list if c not in ("date", "asset_id", "macro_var", "window")
    ]
    set_clause = ", ".join(f"{_q(c)} = EXCLUDED.{_q(c)}" for c in update_cols)
    set_clause += ", ingested_at = now()"

    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TEMP TABLE _crypto_macro_corr_staging "
                "(LIKE crypto_macro_corr_regimes INCLUDING DEFAULTS) "
                "ON COMMIT DROP"
            )
        )
        df[col_list].to_sql(
            "_crypto_macro_corr_staging",
            conn,
            if_exists="append",
            index=False,
            method="multi",
        )
        result = conn.execute(
            text(
                f"INSERT INTO crypto_macro_corr_regimes ({cols_str}) "
                f"SELECT {cols_str} FROM _crypto_macro_corr_staging "
                f'ON CONFLICT (date, asset_id, macro_var, "window") DO UPDATE SET {set_clause}'
            )
        )
        row_count = result.rowcount

    logger.info("Upserted %d rows into crypto_macro_corr_regimes", row_count)
    return row_count


def update_macro_regime_corr(engine: Engine, df: pd.DataFrame) -> int:
    """Update macro_regimes.crypto_macro_corr for each date in df.

    Performs a batch parameterized UPDATE for each (date, label) row.
    Only updates rows where the date already exists in macro_regimes
    (we do not insert -- regime classifier owns that table's rows).

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with columns: date, crypto_macro_corr.

    Returns
    -------
    Total number of rows updated.
    """
    if df.empty:
        return 0

    update_sql = text(
        "UPDATE macro_regimes "
        "SET crypto_macro_corr = :label, ingested_at = now() "
        "WHERE date = :date"
    )

    total_updated = 0
    with engine.begin() as conn:
        for _, row in df.iterrows():
            dt = row["date"]
            label = _to_python(row["crypto_macro_corr"])
            if label is None:
                continue
            result = conn.execute(update_sql, {"label": label, "date": dt})
            total_updated += result.rowcount

    logger.info("Updated %d rows in macro_regimes.crypto_macro_corr", total_updated)
    return total_updated
