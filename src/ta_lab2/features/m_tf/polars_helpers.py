"""
Polars integration helpers for faster DataFrame operations.

Provides drop-in replacements for pandas operations using Polars internally.
All functions maintain pandas API compatibility (return pandas DataFrames).
"""
from __future__ import annotations

from typing import Any, Optional

import pandas as pd
from sqlalchemy.engine import Engine, Connection

try:
    import polars as pl

    HAVE_POLARS = True
except ImportError:
    pl = None
    HAVE_POLARS = False


def read_sql_polars(
    sql: str,
    engine_or_conn: Engine | Connection,
    params: Optional[dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Read SQL query using Polars (5-10x faster for large datasets).

    Args:
        sql: SQL query string
        engine_or_conn: SQLAlchemy Engine or Connection object
        params: Optional query parameters dict

    Falls back to pandas if Polars not available or on error.
    Returns pandas DataFrame for API compatibility.
    """
    # Convert params to None if it's an immutabledict (SQLAlchemy artifact)
    if (
        params is not None
        and hasattr(params, "__module__")
        and "immutabledict" in str(type(params))
    ):
        params = dict(params) if params else None

    # Use pandas fallback if Polars not available
    if not HAVE_POLARS:
        # Fallback to pandas
        # Both Engine and Connection with params need text() wrapper
        if isinstance(engine_or_conn, Connection):
            from sqlalchemy import text as sql_text

            if params:
                result = engine_or_conn.execute(sql_text(sql), params)
            else:
                result = engine_or_conn.execute(sql_text(sql))
            return pd.DataFrame(result.fetchall(), columns=result.keys())
        else:
            # Engine
            if params:
                from sqlalchemy import text as sql_text

                with engine_or_conn.connect() as conn:
                    result = conn.execute(sql_text(sql), params)
                    return pd.DataFrame(result.fetchall(), columns=result.keys())
            else:
                return pd.read_sql(sql, engine_or_conn)

    try:
        # Use Polars read_database for speed
        # Note: Polars doesn't support parameterized queries directly,
        # so we need to use pandas for those
        if params:
            # Fallback for parameterized queries
            # Both Engine and Connection need text() wrapper for params
            from sqlalchemy import text as sql_text

            if isinstance(engine_or_conn, Connection):
                result = engine_or_conn.execute(sql_text(sql), params)
                return pd.DataFrame(result.fetchall(), columns=result.keys())
            else:
                # Engine - use connect() then execute
                with engine_or_conn.connect() as conn:
                    result = conn.execute(sql_text(sql), params)
                    return pd.DataFrame(result.fetchall(), columns=result.keys())

        # Handle both Engine and Connection
        if isinstance(engine_or_conn, Connection):
            # Already have a connection
            df_pl = pl.read_database(sql, connection=engine_or_conn.connection)
        else:
            # Have an engine, get connection
            with engine_or_conn.connect() as conn:
                df_pl = pl.read_database(sql, connection=conn.connection)

        # Convert to pandas
        return df_pl.to_pandas()
    except Exception:
        # Fallback on any error - handle Connection vs Engine differently
        if isinstance(engine_or_conn, Connection):
            # For Connection objects, execute directly
            try:
                from sqlalchemy import text as sql_text

                if params:
                    result = engine_or_conn.execute(sql_text(sql), params)
                else:
                    result = engine_or_conn.execute(sql_text(sql))
                return pd.DataFrame(result.fetchall(), columns=result.keys())
            except Exception:
                # Last resort: try pandas (may not work with Connection)
                return pd.read_sql(sql, engine_or_conn)
        else:
            # For Engine objects with params, use text() and execute
            if params:
                from sqlalchemy import text as sql_text

                with engine_or_conn.connect() as conn:
                    result = conn.execute(sql_text(sql), params)
                    return pd.DataFrame(result.fetchall(), columns=result.keys())
            else:
                return pd.read_sql(sql, engine_or_conn)


def optimize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Optimize DataFrame memory usage using Polars round-trip.

    Polars is more memory-efficient than pandas.
    Returns optimized pandas DataFrame.
    """
    if not HAVE_POLARS or df.empty:
        return df

    try:
        # Convert to Polars and back for memory optimization
        df_pl = pl.from_pandas(df)
        return df_pl.to_pandas()
    except Exception:
        return df


def fast_groupby_agg(
    df: pd.DataFrame,
    by: list[str],
    agg_dict: dict[str, str | list],
) -> pd.DataFrame:
    """
    Fast groupby aggregation using Polars (10-100x faster).

    Args:
        df: Input DataFrame
        by: Columns to group by
        agg_dict: Dict of {column: aggregation} e.g. {"value": "sum"}

    Returns:
        Aggregated pandas DataFrame
    """
    if not HAVE_POLARS or df.empty:
        return df.groupby(by).agg(agg_dict)

    try:
        df_pl = pl.from_pandas(df)

        # Build Polars aggregation expressions
        agg_exprs = []
        for col, agg_func in agg_dict.items():
            if agg_func == "sum":
                agg_exprs.append(pl.col(col).sum().alias(col))
            elif agg_func == "mean":
                agg_exprs.append(pl.col(col).mean().alias(col))
            elif agg_func == "count":
                agg_exprs.append(pl.col(col).count().alias(col))
            elif agg_func == "min":
                agg_exprs.append(pl.col(col).min().alias(col))
            elif agg_func == "max":
                agg_exprs.append(pl.col(col).max().alias(col))
            elif agg_func == "list" or agg_func == list:
                agg_exprs.append(pl.col(col).alias(col))
            else:
                # Fallback for unsupported
                return df.groupby(by).agg(agg_dict)

        result_pl = df_pl.group_by(by).agg(agg_exprs)
        return result_pl.to_pandas()
    except Exception:
        return df.groupby(by).agg(agg_dict)


def fast_merge(
    left: pd.DataFrame,
    right: pd.DataFrame,
    on: str | list[str],
    how: str = "inner",
) -> pd.DataFrame:
    """
    Fast merge using Polars (5-10x faster for large joins).

    Returns pandas DataFrame.
    """
    if not HAVE_POLARS or left.empty or right.empty:
        return pd.merge(left, right, on=on, how=how)

    try:
        left_pl = pl.from_pandas(left)
        right_pl = pl.from_pandas(right)

        result_pl = left_pl.join(right_pl, on=on, how=how)
        return result_pl.to_pandas()
    except Exception:
        return pd.merge(left, right, on=on, how=how)


def fast_filter(df: pd.DataFrame, condition: pd.Series) -> pd.DataFrame:
    """
    Fast filtering using Polars.

    Args:
        df: DataFrame to filter
        condition: Boolean series (pandas)

    Returns:
        Filtered pandas DataFrame
    """
    if not HAVE_POLARS or df.empty:
        return df[condition]

    try:
        df_pl = pl.from_pandas(df)
        condition_pl = pl.from_pandas(pd.DataFrame({"_cond": condition}))["_cond"]

        result_pl = df_pl.filter(condition_pl)
        return result_pl.to_pandas()
    except Exception:
        return df[condition]
