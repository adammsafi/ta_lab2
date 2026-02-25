"""
SignalReader - Watermark-based signal queries with stale guard.

Reads unprocessed signals from signal tables using a watermark timestamp
and executor_processed_at IS NULL filter to prevent duplicate processing.
Provides a stale signal guard that raises StaleSignalError when signals
are older than the configured cadence, with a bypass for the first run.

Exports: SignalReader, StaleSignalError, SIGNAL_TABLE_MAP
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------


class StaleSignalError(Exception):
    """Raised when the most recent signal in a table is older than cadence_hours."""


# ---------------------------------------------------------------------------
# Signal table registry
# ---------------------------------------------------------------------------

SIGNAL_TABLE_MAP: dict[str, str] = {
    "ema_crossover": "cmc_signals_ema_crossover",
    "rsi_mean_revert": "cmc_signals_rsi_mean_revert",
    "atr_breakout": "cmc_signals_atr_breakout",
}

# Set of valid table names (used for validation / injection prevention)
_VALID_SIGNAL_TABLES: frozenset[str] = frozenset(SIGNAL_TABLE_MAP.values())


# ---------------------------------------------------------------------------
# SignalReader
# ---------------------------------------------------------------------------


class SignalReader:
    """
    Reads signals from the signal tables using watermark + unprocessed filters.

    Parameters
    ----------
    engine : sqlalchemy.engine.Engine
        SQLAlchemy engine instance. The caller is responsible for providing
        connections; this class stores the engine for convenience methods
        that open their own connection.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_table(signal_table: str) -> None:
        """
        Validate signal_table against the allowed list.

        Raises
        ------
        ValueError
            If signal_table is not in the known set of signal tables.
        """
        if signal_table not in _VALID_SIGNAL_TABLES:
            raise ValueError(
                f"Unknown signal table '{signal_table}'. "
                f"Allowed tables: {sorted(_VALID_SIGNAL_TABLES)}"
            )

    # ------------------------------------------------------------------
    # Stale guard
    # ------------------------------------------------------------------

    def check_signal_freshness(
        self,
        conn: Any,
        signal_table: str,
        signal_id: int,
        cadence_hours: float,
        last_watermark_ts: datetime | None,
    ) -> None:
        """
        Guard against processing stale signals.

        If last_watermark_ts is None (first run) the check is skipped.
        Otherwise, queries MAX(ts) for the given signal_id and raises
        StaleSignalError if no signals exist or if the latest signal is
        older than cadence_hours.

        Parameters
        ----------
        conn :
            Active SQLAlchemy connection.
        signal_table : str
            Table name — must be in SIGNAL_TABLE_MAP.values().
        signal_id : int
            The signal configuration id to check.
        cadence_hours : float
            Maximum acceptable age of the latest signal, in hours.
        last_watermark_ts : datetime | None
            The previous watermark timestamp. None on first run.

        Raises
        ------
        StaleSignalError
            When no signals exist or latest signal exceeds cadence_hours.
        ValueError
            When signal_table is not a known table name.
        """
        if last_watermark_ts is None:
            # First run — skip stale check
            logger.debug(
                "check_signal_freshness: watermark is None (first run), skipping stale check "
                "for signal_id=%s table=%s",
                signal_id,
                signal_table,
            )
            return

        self._validate_table(signal_table)

        sql = text(
            f"SELECT MAX(ts) AS latest_ts FROM public.{signal_table} WHERE signal_id = :signal_id"
        )
        row = conn.execute(sql, {"signal_id": signal_id}).fetchone()

        latest_ts: datetime | None = row.latest_ts if row else None

        if latest_ts is None:
            raise StaleSignalError(
                f"No signals found in {signal_table} for signal_id={signal_id}."
            )

        # Ensure both datetimes are timezone-aware for comparison
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)

        now_utc = datetime.now(timezone.utc)
        age_hours = (now_utc - latest_ts).total_seconds() / 3600.0

        if age_hours > cadence_hours:
            raise StaleSignalError(
                f"Latest signal in {signal_table} (signal_id={signal_id}) is {age_hours:.1f}h old, "
                f"exceeds cadence limit of {cadence_hours}h."
            )

        logger.debug(
            "check_signal_freshness: OK (age=%.1fh, cadence=%.1fh) table=%s signal_id=%s",
            age_hours,
            cadence_hours,
            signal_table,
            signal_id,
        )

    # ------------------------------------------------------------------
    # Read unprocessed
    # ------------------------------------------------------------------

    def read_unprocessed_signals(
        self,
        conn: Any,
        signal_table: str,
        signal_id: int,
        last_watermark_ts: datetime | None,
    ) -> list[dict]:
        """
        Return signals that have not yet been processed by the executor.

        Queries for rows where executor_processed_at IS NULL.
        When last_watermark_ts is provided the query also filters ts > watermark.

        Parameters
        ----------
        conn :
            Active SQLAlchemy connection.
        signal_table : str
            Target signal table (validated against SIGNAL_TABLE_MAP).
        signal_id : int
            The signal configuration id to read.
        last_watermark_ts : datetime | None
            High-water mark from previous execution. None on first run.

        Returns
        -------
        list[dict]
            Rows ordered by ts ASC, each as a plain dict.
        """
        self._validate_table(signal_table)

        base_sql = (
            f"SELECT id, ts, signal_id, direction, position_state, "
            f"entry_price, entry_ts, exit_price, exit_ts, feature_snapshot, params_hash "
            f"FROM public.{signal_table} "
            f"WHERE signal_id = :signal_id "
            f"AND executor_processed_at IS NULL"
        )

        params: dict[str, Any] = {"signal_id": signal_id}

        if last_watermark_ts is not None:
            base_sql += " AND ts > :watermark_ts"
            params["watermark_ts"] = last_watermark_ts

        base_sql += " ORDER BY ts ASC"

        rows = conn.execute(text(base_sql), params).fetchall()

        result = [dict(row._mapping) for row in rows]
        logger.debug(
            "read_unprocessed_signals: %d rows from %s (signal_id=%s, watermark=%s)",
            len(result),
            signal_table,
            signal_id,
            last_watermark_ts,
        )
        return result

    # ------------------------------------------------------------------
    # Mark processed
    # ------------------------------------------------------------------

    def mark_signals_processed(
        self,
        conn: Any,
        signal_table: str,
        signal_ids_and_timestamps: list[tuple[int, datetime]],
    ) -> None:
        """
        Set executor_processed_at = now() on the given signals.

        Parameters
        ----------
        conn :
            Active SQLAlchemy connection.
        signal_table : str
            Target signal table (validated against SIGNAL_TABLE_MAP).
        signal_ids_and_timestamps : list[tuple[int, datetime]]
            List of (id, ts) pairs identifying the rows to mark.
        """
        self._validate_table(signal_table)

        sql = text(
            f"UPDATE public.{signal_table} "
            f"SET executor_processed_at = now() "
            f"WHERE id = :id AND ts = :ts"
        )

        for asset_id, ts in signal_ids_and_timestamps:
            conn.execute(sql, {"id": asset_id, "ts": ts})
            logger.debug(
                "mark_signals_processed: table=%s id=%s ts=%s",
                signal_table,
                asset_id,
                ts,
            )

    # ------------------------------------------------------------------
    # Group by asset
    # ------------------------------------------------------------------

    @staticmethod
    def get_latest_signal_per_asset(signals: list[dict]) -> dict[int, dict]:
        """
        Pure function. Groups signals by asset id and returns the latest
        signal (highest ts) per asset.

        Parameters
        ----------
        signals : list[dict]
            List of signal dicts each containing 'id' and 'ts' keys.

        Returns
        -------
        dict[int, dict]
            Mapping of asset_id -> latest signal dict.
        """
        latest: dict[int, dict] = {}
        for signal in signals:
            asset_id: int = signal["id"]
            existing = latest.get(asset_id)
            if existing is None or signal["ts"] > existing["ts"]:
                latest[asset_id] = signal
        return latest
