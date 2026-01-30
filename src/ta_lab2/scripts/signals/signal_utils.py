"""
Signal utilities - Feature hashing and signal configuration loading.

This module provides utilities for signal generation:
- Feature hashing for reproducibility validation
- Parameter hashing for configuration change detection
- Active signal loading from dim_signals

These utilities enable reproducible backtesting and signal versioning.
"""

import hashlib
import json
from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


def compute_feature_hash(df: pd.DataFrame, columns: list[str]) -> str:
    """
    Compute SHA256 hash of feature data for reproducibility.

    Sorts DataFrame by 'ts' column before hashing to ensure deterministic
    output regardless of row order.

    Args:
        df: DataFrame containing feature data
        columns: List of column names to include in hash

    Returns:
        First 16 characters of SHA256 hash (hexadecimal string)

    Raises:
        KeyError: If required columns not in DataFrame
        ValueError: If DataFrame is empty

    Examples:
        >>> df = pd.DataFrame({
        ...     'ts': ['2024-01-01', '2024-01-02'],
        ...     'close': [100.0, 101.0],
        ...     'ema_21': [99.5, 100.5]
        ... })
        >>> hash1 = compute_feature_hash(df, ['close', 'ema_21'])
        >>> hash2 = compute_feature_hash(df, ['close', 'ema_21'])
        >>> hash1 == hash2  # Deterministic
        True
    """
    if df.empty:
        raise ValueError("Cannot compute hash of empty DataFrame")

    # Verify columns exist
    missing = set(columns) - set(df.columns)
    if missing:
        raise KeyError(f"Columns not found in DataFrame: {missing}")

    # Sort by timestamp for deterministic ordering
    df_sorted = df.sort_values('ts')

    # Generate CSV bytes (exclude index)
    csv_bytes = df_sorted[columns].to_csv(index=False).encode('utf-8')

    # Compute SHA256 hash and return first 16 chars
    hash_full = hashlib.sha256(csv_bytes).hexdigest()
    return hash_full[:16]


def compute_params_hash(params: dict) -> str:
    """
    Compute SHA256 hash of signal parameters for change detection.

    Sorts keys before hashing to ensure deterministic output regardless
    of dictionary insertion order.

    Args:
        params: Dictionary of signal parameters (from dim_signals.params JSONB)

    Returns:
        First 16 characters of SHA256 hash (hexadecimal string)

    Examples:
        >>> params1 = {"fast_period": 9, "slow_period": 21}
        >>> params2 = {"slow_period": 21, "fast_period": 9}
        >>> compute_params_hash(params1) == compute_params_hash(params2)
        True
    """
    # Convert to JSON with sorted keys
    json_str = json.dumps(params, sort_keys=True)
    json_bytes = json_str.encode('utf-8')

    # Compute SHA256 hash and return first 16 chars
    hash_full = hashlib.sha256(json_bytes).hexdigest()
    return hash_full[:16]


def load_active_signals(
    engine: Engine,
    signal_type: str,
    signal_id: Optional[int] = None,
) -> list[dict]:
    """
    Query active signals from dim_signals configuration table.

    Args:
        engine: SQLAlchemy engine for database operations
        signal_type: Signal type to filter ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')
        signal_id: Optional specific signal ID to load (if None, loads all active)

    Returns:
        List of dictionaries with keys: signal_id, signal_name, params
        params is already parsed from JSONB into Python dict

    Raises:
        sqlalchemy.exc.SQLAlchemyError: On database errors

    Examples:
        >>> signals = load_active_signals(engine, 'ema_crossover')
        >>> signals[0]
        {
            'signal_id': 1,
            'signal_name': 'ema_9_21_long',
            'params': {'fast_period': 9, 'slow_period': 21, 'direction': 'long'}
        }
    """
    # Build query with optional signal_id filter
    where_clauses = [
        "signal_type = :signal_type",
        "is_active = TRUE"
    ]
    params = {"signal_type": signal_type}

    if signal_id is not None:
        where_clauses.append("signal_id = :signal_id")
        params["signal_id"] = signal_id

    where_sql = " AND ".join(where_clauses)

    sql_text = f"""
        SELECT
            signal_id,
            signal_name,
            params
        FROM public.dim_signals
        WHERE {where_sql}
        ORDER BY signal_id
    """

    sql = text(sql_text)

    with engine.connect() as conn:
        result = conn.execute(sql, params)
        rows = result.fetchall()

        # Convert to list of dicts (params already parsed from JSONB)
        return [
            {
                "signal_id": row[0],
                "signal_name": row[1],
                "params": row[2]  # JSONB auto-parsed to dict by psycopg2
            }
            for row in rows
        ]
