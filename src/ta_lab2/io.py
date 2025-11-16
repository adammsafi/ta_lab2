from __future__ import annotations

import os
from typing import Mapping, Any, Sequence, Optional

import os
from typing import Mapping, Any, Sequence, Optional

import pathlib
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import load_settings


def write_parquet(df: pd.DataFrame, path: str, partition_cols=None):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if partition_cols:
        df.to_parquet(path, partition_cols=partition_cols, index=False)
    else:
        df.to_parquet(path, index=False)


def read_parquet(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)


# ----------------- Internal helpers ----------------- #


def _as_mapping(obj: Any) -> Mapping[str, Any] | None:
    if isinstance(obj, Mapping):
        return obj
    return None


def _get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """
    Try obj.name, then obj[name] if obj is a Mapping; otherwise default.
    """
    if hasattr(obj, name):
        return getattr(obj, name)
    m = _as_mapping(obj)
    if m is not None and name in m:
        return m[name]
    return default


def _get_marketdata_config() -> Any:
    """
    Return the 'marketdata' section from config via load_settings().

    Expects your config to have something like:

        marketdata:
          db_url_env: MARKETDATA_DB_URL
          schema: public
          tables:
            ohlcv_daily: cmc_price_histories7
            da_ids: cmc_da_ids
            da_info: cmc_da_info
            exchange_info: cmc_exchange_info
            exchange_map: cmc_exchange_map
            ema_daily: cmc_ema_daily            # optional, with default fallback
    """
    settings = load_settings()
    # Support both attribute style and mapping style
    md = _get_attr_or_key(settings, "marketdata", None)
    if md is None:
        raise RuntimeError(
            "No 'marketdata' section found in settings. "
            "Add a 'marketdata' block to configs/default.yaml."
        )
    return md


def _get_marketdata_engine(db_url: str | None = None) -> Engine:
    """
    Build a SQLAlchemy Engine for the marketdata database.

    Precedence:
    1. Explicit db_url argument.
    2. settings.marketdata.db_url
    3. os.environ[settings.marketdata.db_url_env]
    4. os.environ['MARKETDATA_DB_URL']
    """
    if db_url:
        return create_engine(db_url)

    md = _get_marketdata_config()

    # 1) db_url directly in config (if present)
    cfg_url = _get_attr_or_key(md, "db_url", None)
    if cfg_url:
        return create_engine(cfg_url)

    # 2) env var name in config
    env_name = _get_attr_or_key(md, "db_url_env", None)
    if env_name:
        env_val = os.getenv(str(env_name))
        if env_val:
            return create_engine(env_val)

    # 3) generic fallback
    env_val = os.getenv("MARKETDATA_DB_URL")
    if env_val:
        return create_engine(env_val)

    raise RuntimeError(
        "Could not determine DB URL for marketdata. "
        "Set MARKETDATA_DB_URL or add marketdata.db_url/env in config."
    )


def _get_marketdata_tables() -> Mapping[str, str]:
    """
    Return a mapping of logical table names → actual DB table names
    from settings.marketdata.tables, with sensible defaults.
    """
    md = _get_marketdata_config()
    tables = _get_attr_or_key(md, "tables", {}) or {}
    m = _as_mapping(tables) or {}

    return {
        "ohlcv_daily": m.get("ohlcv_daily", "cmc_price_histories7"),
        "da_ids": m.get("da_ids", "cmc_da_ids"),
        "da_info": m.get("da_info", "cmc_da_info"),
        "exchange_info": m.get("exchange_info", "cmc_exchange_info"),
        "exchange_map": m.get("exchange_map", "cmc_exchange_map"),
        # indicator table defaults
        "ema_daily": m.get("ema_daily", "cmc_ema_daily"),
    }


def _get_marketdata_schema_and_tables() -> tuple[str | None, Mapping[str, str]]:
    """
    Return (schema, tables) for marketdata.
    schema may be None or a string like 'public'.
    """
    md = _get_marketdata_config()
    schema = _get_attr_or_key(md, "schema", None)
    tables = _get_marketdata_tables()
    return schema, tables


def _qualify_table(schema: str | None, table_name: str) -> str:
    """
    Return fully-qualified table name if a schema is provided.
    """
    if schema:
        return f"{schema}.{table_name}"
    return table_name


# ----------------- Public loaders ----------------- #


def load_cmc_ohlcv_daily(
    ids: Sequence[int],
    *,
    start: Optional[pd.Timestamp | str] = None,
    end: Optional[pd.Timestamp | str] = None,
    db_url: str | None = None,
    tz: str = "UTC",
) -> pd.DataFrame:
    """
    Load daily OHLCV time series from the cmc_price_histories7 table
    (or whatever is configured as marketdata.tables.ohlcv_daily).

    NOTE: ts is derived from timeclose to align with bar close dates.

    Parameters
    ----------
    ids :
        Sequence of CoinMarketCap IDs to load (e.g. [1, 1027, 5426, ...]).
    start :
        Optional lower bound (inclusive) on timeclose.
    end :
        Optional upper bound (exclusive) on timeclose.
    db_url :
        Optional DB URL override. If omitted, uses settings/env resolution.
    tz :
        Timezone to localize timestamps to (default 'UTC').

    Returns
    -------
    DataFrame
        MultiIndex (id, ts) with columns:
        ['open', 'high', 'low', 'close', 'volume'].

        'ts' is a tz-aware pandas.Timestamp derived from timeclose.
    """
    if not ids:
        raise ValueError("ids must be a non-empty sequence of CMC IDs")

    engine = _get_marketdata_engine(db_url=db_url)
    schema, tables = _get_marketdata_schema_and_tables()
    table = _qualify_table(schema, tables["ohlcv_daily"])

    where_clauses = ["id = ANY(:ids)"]
    params: dict[str, object] = {"ids": list(ids)}

    if start is not None:
        where_clauses.append("timeclose >= :start")
        params["start"] = pd.to_datetime(start).to_pydatetime()

    if end is not None:
        where_clauses.append("timeclose < :end")
        params["end"] = pd.to_datetime(end).to_pydatetime()

    where_sql = " AND ".join(where_clauses)

    stmt = text(
        f"""
        SELECT
            id,
            timeclose AS ts,
            open,
            high,
            low,
            close,
            volume
        FROM {table}
        WHERE {where_sql}
        ORDER BY id, ts
        """
    )

    df = pd.read_sql(stmt, engine, params=params)

    if df.empty:
        # Return an empty, correctly-shaped frame
        idx = pd.MultiIndex.from_arrays(
            [pd.Index([], name="id"), pd.DatetimeIndex([], name="ts")]
        )
        return pd.DataFrame(
            [], index=idx, columns=["open", "high", "low", "close", "volume"]
        )

    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert(tz)
    df = df.set_index(["id", "ts"]).sort_index()

    cols = ["open", "high", "low", "close", "volume"]
    df = df[cols]

    return df


def load_close_panel(
    ids: Sequence[int],
    *,
    start: Optional[pd.Timestamp | str] = None,
    end: Optional[pd.Timestamp | str] = None,
    db_url: str | None = None,
    tz: str = "UTC",
) -> pd.DataFrame:
    """
    Convenience loader: return a wide panel of close prices.

    Parameters
    ----------
    ids :
        Sequence of CoinMarketCap IDs to load.
    start, end :
        Optional date bounds passed through to load_cmc_ohlcv_daily.
    db_url :
        Optional DB URL override.
    tz :
        Timezone to localize timestamps to (default 'UTC').

    Returns
    -------
    DataFrame
        Index: ts (tz-aware, from timeclose)
        Columns: one column per asset id
        Values: close prices.
    """
    ohlcv = load_cmc_ohlcv_daily(
        ids=ids,
        start=start,
        end=end,
        db_url=db_url,
        tz=tz,
    )
    if ohlcv.empty:
        return pd.DataFrame(columns=pd.Index([], name="id"))

    close_wide = ohlcv["close"].unstack("id")
    close_wide.index.name = "ts"
    return close_wide


def load_da_ids(
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Load the full CoinMarketCap ID mapping table.

    Uses marketdata.tables.da_ids and optional schema from config.

    Returns
    -------
    DataFrame
        All columns from the configured da_ids table. Typical columns might be:
        ['id', 'name', 'symbol', 'slug', ...]
    """
    engine = _get_marketdata_engine(db_url=db_url)
    schema, tables = _get_marketdata_schema_and_tables()
    table = _qualify_table(schema, tables["da_ids"])

    stmt = text(f"SELECT * FROM {table}")
    return pd.read_sql(stmt, engine)


def load_exchange_info(
    *,
    db_url: str | None = None,
) -> pd.DataFrame:
    """
    Load descriptive information for exchanges.

    Uses marketdata.tables.exchange_info and optional schema from config.

    Returns
    -------
    DataFrame
        All columns from the configured exchange_info table. Typical columns might be:
        ['id', 'name', 'slug', 'url', 'country', ...]
    """
    engine = _get_marketdata_engine(db_url=db_url)
    schema, tables = _get_marketdata_schema_and_tables()
    table = _qualify_table(schema, tables["exchange_info"])

    stmt = text(f"SELECT * FROM {table}")
    return pd.read_sql(stmt, engine)


# ----------------- Indicator persistence (EMA) ----------------- #


def _compute_ema_long_from_close_panel(
    close_panel: pd.DataFrame,
    periods: Sequence[int],
) -> pd.DataFrame:
    """
    Compute EMAs over a wide close panel and return a long-format DataFrame.

    Important behavior:
    - EMAs are only defined where there is an actual close price.
      If an asset stops trading on 2025-10-26 but other assets
      continue to 2025-11-10, its EMA will stop at 2025-10-26.
      No rows are emitted for that asset after its last close.

    Parameters
    ----------
    close_panel :
        DataFrame with index=ts and columns=id, values=close prices.
    periods :
        Iterable of EMA window lengths (ints).

    Returns
    -------
    DataFrame
        Columns: ['id', 'ts', 'period', 'ema']
    """
    if close_panel.empty:
        return pd.DataFrame(columns=["id", "ts", "period", "ema"])

    frames: list[pd.DataFrame] = []
    for p in periods:
        # Raw EMA (extends through trailing NaNs)
        ema_wide = close_panel.ewm(
            span=p, 
            adjust=False,
            min_periods=p,
        ).mean()
        # Only keep EMA where we actually have a close price;
        # this makes EMA NaN wherever close is NaN.
        ema_wide = ema_wide.where(close_panel.notna())
        # stack() drops NaNs → no rows at all where close was NaN.
        ema_long = ema_wide.stack().rename("ema").reset_index()
        # ema_long columns: ['ts', 'id', 'ema']
        ema_long["period"] = int(p)
        frames.append(ema_long[["id", "ts", "period", "ema"]])

    result = pd.concat(frames, ignore_index=True)
    result.sort_values(["id", "ts", "period"], inplace=True)
    return result


def write_ema_daily_to_db(
    ids: Sequence[int],
    periods: Sequence[int],
    *,
    start: Optional[pd.Timestamp | str] = None,
    end: Optional[pd.Timestamp | str] = None,
    db_url: str | None = None,
    chunksize: int = 10_000,
) -> int:
    """
    Compute daily EMAs for the given asset ids from OHLCV in cmc_price_histories7
    and upsert them into the EMA indicator table (marketdata.tables.ema_daily).

    Table schema (recommended) for ema_daily / cmc_ema_daily:

        id      INT          -- CoinMarketCap asset id
        ts      TIMESTAMPTZ  -- timestamp (daily bar close)
        period  INT          -- EMA window length
        ema     DOUBLE PRECISION
        ingested_at TIMESTAMPTZ DEFAULT now()

    This function performs an UPSERT:
        ON CONFLICT (id, ts, period) DO UPDATE SET ema = EXCLUDED.ema

    So rerunning over the same date range will update existing rows instead of
    creating duplicates.

    Parameters
    ----------
    ids :
        Sequence of CoinMarketCap ids to process.
    periods :
        Sequence of EMA window lengths (ints).
    start, end :
        Optional date bounds passed through to load_cmc_ohlcv_daily().
    db_url :
        Optional DB URL override for marketdata database.
    chunksize :
        Batch size for the batched insert.

    Returns
    -------
    int
        Number of EMA rows written (inserted or updated).
    """
    if not ids:
        raise ValueError("ids must be a non-empty sequence of CMC IDs")
    if not periods:
        raise ValueError("periods must be a non-empty sequence of EMA lookbacks")

    # Load close prices panel from DB
    close_panel = load_close_panel(
        ids=ids,
        start=start,
        end=end,
        db_url=db_url,
    )
    if close_panel.empty:
        return 0

    # Compute EMAs (long format: id, ts, period, ema)
    ema_long = _compute_ema_long_from_close_panel(close_panel, periods)
    if ema_long.empty:
        return 0

    engine = _get_marketdata_engine(db_url=db_url)
    schema, tables = _get_marketdata_schema_and_tables()
    ema_table_name = tables["ema_daily"]
    full_table = _qualify_table(schema, ema_table_name)

    # Convert to list-of-dicts for executemany
    records = ema_long.to_dict(orient="records")
    total = len(records)
    if total == 0:
        return 0

    # Prepare UPSERT statement
    stmt = text(
        f"""
        INSERT INTO {full_table} (id, ts, period, ema)
        VALUES (:id, :ts, :period, :ema)
        ON CONFLICT (id, ts, period) DO UPDATE
        SET ema = EXCLUDED.ema
        """
    )

    # Execute in batches
    with engine.begin() as conn:
        for i in range(0, total, chunksize):
            batch = records[i : i + chunksize]
            conn.execute(stmt, batch)

    return total
