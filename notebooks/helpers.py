"""Shared helpers for ta_lab2 research notebooks."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

# ---------------------------------------------------------------------------
# sys.path bootstrap — ensures ta_lab2 is importable when helpers.py is
# imported from the notebooks directory (which lives outside src/).
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
_SRC = str(_ROOT / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from ta_lab2.scripts.refresh_utils import resolve_db_url  # noqa: E402


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def get_engine():
    """
    Return a NullPool SQLAlchemy engine using resolve_db_url().

    NullPool is used to avoid connection pooling issues in notebook sessions.
    Notebooks should call this once and pass the engine to data-loading helpers.

    Returns:
        sqlalchemy.engine.Engine backed by NullPool.
    """
    db_url = resolve_db_url()
    return create_engine(db_url, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Data Loaders
# ---------------------------------------------------------------------------


def load_features(
    engine,
    asset_id: int,
    tf: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Load feature rows from features for a single asset / timeframe window.

    Args:
        engine: SQLAlchemy engine (use get_engine()).
        asset_id: Asset primary key (e.g. 1 for BTC).
        tf: Timeframe string (e.g. "1D", "1W").
        start: Inclusive start date string "YYYY-MM-DD".
        end: Inclusive end date string "YYYY-MM-DD".

    Returns:
        DataFrame indexed by ts (tz-aware UTC), ordered ascending.
    """
    sql = text(
        """
        SELECT *
        FROM features
        WHERE id   = :id
          AND tf   = :tf
          AND ts  >= :start
          AND ts  <= :end
        ORDER BY ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"id": asset_id, "tf": tf, "start": start, "end": end}
        )
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df


def load_price_bars(
    engine,
    asset_id: int,
    tf: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Load OHLCV price bars from price_bars_multi_tf.

    Args:
        engine: SQLAlchemy engine (use get_engine()).
        asset_id: Asset primary key.
        tf: Timeframe string (e.g. "1D").
        start: Inclusive start date string "YYYY-MM-DD".
        end: Inclusive end date string "YYYY-MM-DD".

    Returns:
        DataFrame with columns (open, high, low, close, volume), indexed by ts
        (tz-aware UTC), ordered ascending.
    """
    sql = text(
        """
        SELECT ts, open, high, low, close, volume
        FROM price_bars_multi_tf
        WHERE id   = :id
          AND tf   = :tf
          AND ts  >= :start
          AND ts  <= :end
        ORDER BY ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"id": asset_id, "tf": tf, "start": start, "end": end}
        )
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df


def load_regimes(
    engine,
    asset_id: int,
    tf: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Load regime rows from regimes for a single asset / timeframe window.

    Args:
        engine: SQLAlchemy engine (use get_engine()).
        asset_id: Asset primary key.
        tf: Timeframe string (e.g. "1D").
        start: Inclusive start date string "YYYY-MM-DD".
        end: Inclusive end date string "YYYY-MM-DD".

    Returns:
        DataFrame with l2_label (and other regime columns), indexed by ts
        (tz-aware UTC), ordered ascending.
    """
    sql = text(
        """
        SELECT *
        FROM regimes
        WHERE id   = :id
          AND tf   = :tf
          AND ts  >= :start
          AND ts  <= :end
        ORDER BY ts
        """
    )
    with engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"id": asset_id, "tf": tf, "start": start, "end": end}
        )
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_asset_data(
    engine,
    asset_id: int,
    tf: str,
    min_days: int = 365,
) -> dict:
    """
    Validate that sufficient data exists for an asset / timeframe.

    Queries the asset_data_coverage table.

    Args:
        engine: SQLAlchemy engine (use get_engine()).
        asset_id: Asset primary key.
        tf: Timeframe / granularity string (e.g. "1D").
        min_days: Minimum required calendar days of coverage.

    Returns:
        dict with keys:
            valid (bool): True if n_days >= min_days.
            n_days (int): Number of days covered (0 if no data).
            first_ts: First timestamp (or None).
            last_ts: Last timestamp (or None).
            message (str): Human-readable summary.
    """
    sql = text(
        """
        SELECT n_days, first_ts, last_ts
        FROM asset_data_coverage
        WHERE id          = :id
          AND granularity = :tf
        LIMIT 1
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"id": asset_id, "tf": tf}).fetchone()

    if row is None:
        return {
            "valid": False,
            "n_days": 0,
            "first_ts": None,
            "last_ts": None,
            "message": f"No coverage data found for asset {asset_id} / {tf}",
        }

    n_days = int(row[0]) if row[0] is not None else 0
    first_ts = row[1]
    last_ts = row[2]
    valid = n_days >= min_days
    if valid:
        message = f"OK — {n_days} days from {first_ts} to {last_ts}"
    else:
        message = f"Insufficient data: {n_days} days (need {min_days})"

    return {
        "valid": valid,
        "n_days": n_days,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------


def style_ic_table(df: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """
    Apply styling to an IC results DataFrame for notebook display.

    Applies:
        - RdYlGn background gradient on "ic" column (vmin=-0.1, vmax=0.1).
        - Formats ic and ic_p_value columns to 4 decimal places.
        - Formats n_obs with comma thousands separator.

    Args:
        df: DataFrame with columns: ic, ic_p_value, n_obs (at minimum).

    Returns:
        pandas Styler ready for display in Jupyter.
    """
    styler = df.style

    # Background gradient on ic column (if present)
    if "ic" in df.columns:
        styler = styler.background_gradient(
            subset=["ic"], cmap="RdYlGn", vmin=-0.1, vmax=0.1
        )

    # Format numeric columns
    fmt: dict[str, str] = {}
    if "ic" in df.columns:
        fmt["ic"] = "{:.4f}"
    if "ic_p_value" in df.columns:
        fmt["ic_p_value"] = "{:.4f}"
    if "n_obs" in df.columns:
        fmt["n_obs"] = "{:,.0f}"

    if fmt:
        styler = styler.format(fmt)

    return styler
