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
# Must cover the longest rolling window in config (90d z-score) + margin.
WARMUP_DAYS = 120

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
        "FROM returns_bars_multi_tf "
        "WHERE tf = '1D' AND roll = FALSE "
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
        "SELECT ts::date AS date, symbol, venue, funding_rate "
        "FROM funding_rates "
        "WHERE tf = '1d' "
        "AND ts::date >= :start AND ts::date <= :end "
        "ORDER BY symbol, date, venue"
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
        venues_list = sorted(valid["venue"].dropna().unique().tolist())
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
        "FROM returns_bars_multi_tf "
        "WHERE tf = '1D' AND roll = FALSE "
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
# XAGG-04 upserts
# ---------------------------------------------------------------------------


def upsert_crypto_macro_corr(engine: Engine, df: pd.DataFrame) -> int:
    """Upsert crypto-macro correlation DataFrame into crypto_macro_corr_regimes.

    Uses temp table + INSERT...ON CONFLICT(date, asset_id, macro_var) DO UPDATE.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    df:
        DataFrame with columns: date, asset_id, macro_var, corr_60d,
        prev_corr_60d, sign_flip_flag, corr_regime.

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
        "asset_id",
        "macro_var",
        "corr_60d",
        "prev_corr_60d",
        "sign_flip_flag",
        "corr_regime",
    ]
    col_list = [c for c in col_list if c in df.columns]
    cols_str = ", ".join(col_list)
    update_cols = [c for c in col_list if c not in ("date", "asset_id", "macro_var")]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
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
                f"ON CONFLICT (date, asset_id, macro_var) DO UPDATE SET {set_clause}"
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
