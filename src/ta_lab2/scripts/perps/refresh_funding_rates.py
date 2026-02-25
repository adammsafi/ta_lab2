"""
refresh_funding_rates.py
========================

CLI script to ingest perpetual funding rate history from 6 active venues
into the cmc_funding_rates table with watermark-based incremental refresh.

Venues supported:
    - binance   (8h settlement, limit 1000/batch)
    - hyperliquid (1h settlement, startTime pagination)
    - bybit     (8h settlement, sliding endTime window -- MUST pass both startTime+endTime)
    - dydx      (1h settlement, cursor-based effectiveBeforeOrAt)
    - aevo      (1h settlement, offset pagination, nanosecond timestamps)
    - aster     (8h settlement, mirrors Binance API)
    - lighter   (STUB -- logs WARNING and returns empty; SDK integration deferred)

Usage:
    # Full refresh -- all venues, BTC and ETH
    python -m ta_lab2.scripts.perps.refresh_funding_rates --all

    # Single venue
    python -m ta_lab2.scripts.perps.refresh_funding_rates --venue binance

    # Single symbol
    python -m ta_lab2.scripts.perps.refresh_funding_rates --symbol BTC

    # Dry run -- show what would be fetched (no DB connection required)
    python -m ta_lab2.scripts.perps.refresh_funding_rates --dry-run --venue binance --symbol BTC

    # With daily rollup
    python -m ta_lab2.scripts.perps.refresh_funding_rates --all --rollup

    # Skip daily rollup (default is to compute)
    python -m ta_lab2.scripts.perps.refresh_funding_rates --all --no-rollup

Design decisions:
    - Standalone only: NOT wired into run_daily_refresh.py. Funding ingest comes
      from exchange APIs (not CMC) and should run independently to avoid blocking
      the main CMC pipeline on exchange API failures.
    - NullPool: Matches project pattern for one-shot script DB connections.
    - Watermark: SELECT MAX(ts) per (venue, symbol, tf) -- None triggers full backfill.
    - Daily rollup: Resamples sub-day rates to UTC day; upserted as tf='1d'.
    - Cross-venue fallback: Returns cross-venue average within +/- 30 min window.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from ta_lab2.scripts.perps.funding_fetchers import (
    FundingRateRow,
    fetch_aevo_funding,
    fetch_aster_funding,
    fetch_binance_funding,
    fetch_bybit_funding,
    fetch_dydx_funding,
    fetch_hyperliquid_funding,
    fetch_lighter_funding,
)
from ta_lab2.scripts.refresh_utils import resolve_db_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Interval constants for batch pagination (milliseconds)
_MS_PER_HOUR = 60 * 60 * 1000
_MS_PER_8H = 8 * _MS_PER_HOUR
_MS_PER_4H = 4 * _MS_PER_HOUR
_MS_PER_1H = _MS_PER_HOUR

# Binance/Aster/Bybit batch window (1000 x 8h settlements = ~333 days)
_BINANCE_BATCH_MS = 1000 * _MS_PER_8H
# Bybit sliding window (200 x 8h = ~67 days)
_BYBIT_BATCH_MS = 200 * _MS_PER_8H
# dYdX cursor limit
_DYDX_LIMIT = 100
# Aevo page limit (max 50)
_AEVO_LIMIT = 50

# Binance BTC perpetual approximate launch date (Sep 2019)
_BINANCE_BTC_EPOCH_MS = 1_569_888_000_000  # 2019-10-01 00:00:00 UTC
# Hyperliquid mainnet approximate launch (Jun 2023)
_HYPERLIQUID_EPOCH_MS = 1_685_577_600_000  # 2023-06-01 00:00:00 UTC
# dYdX v4 mainnet launch (Oct 2023)
_DYDX_EPOCH_ISO = "2023-10-28T00:00:00Z"
# Aevo launch (Sep 2023) in nanoseconds
_AEVO_EPOCH_NS = 1_693_526_400 * 1_000_000_000  # 2023-09-01 00:00:00 UTC
# Aster approximate launch (2023)
_ASTER_EPOCH_MS = 1_672_531_200_000  # 2023-01-01 00:00:00 UTC

# Supported venues for --all
ALL_VENUES = ["binance", "hyperliquid", "bybit", "dydx", "aevo", "aster", "lighter"]

# Default symbols
DEFAULT_SYMBOLS = ["BTC", "ETH"]

# Venue-to-exchange-symbol mapping for BTC/ETH
VENUE_SYMBOLS: dict[str, dict[str, str]] = {
    "binance": {"BTC": "BTCUSDT", "ETH": "ETHUSDT"},
    "hyperliquid": {"BTC": "BTC", "ETH": "ETH"},
    "bybit": {"BTC": "BTCUSDT", "ETH": "ETHUSDT"},
    "dydx": {"BTC": "BTC-USD", "ETH": "ETH-USD"},
    "aevo": {"BTC": "BTC-PERP", "ETH": "ETH-PERP"},
    "aster": {"BTC": "BTCUSDT", "ETH": "ETHUSDT"},
    "lighter": {"BTC": "BTC", "ETH": "ETH"},
}

# Native tf per venue (for watermark query)
VENUE_TF: dict[str, str] = {
    "binance": "8h",
    "hyperliquid": "1h",
    "bybit": "8h",
    "dydx": "1h",
    "aevo": "1h",
    "aster": "8h",
    "lighter": "1h",
}


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def upsert_funding_rates(engine, rows: List[FundingRateRow]) -> int:
    """
    Upsert funding rate rows into cmc_funding_rates.

    Uses temp table + INSERT...SELECT...ON CONFLICT DO NOTHING pattern
    (same as sync_utils.py pattern for unified tables).

    Args:
        engine: SQLAlchemy engine (NullPool recommended)
        rows: List of FundingRateRow objects

    Returns:
        Number of rows actually inserted (duplicates silently skipped)
    """
    if not rows:
        return 0

    df = pd.DataFrame(
        [
            {
                "venue": r.venue,
                "symbol": r.symbol,
                "ts": r.ts,
                "tf": r.tf,
                "funding_rate": r.funding_rate,
                "mark_price": r.mark_price,
                "raw_tf": r.raw_tf if r.raw_tf else None,
                "ingested_at": datetime.now(timezone.utc),
            }
            for r in rows
        ]
    )

    with engine.begin() as conn:
        # Write to temp staging table
        df.to_sql(
            "_tmp_funding_rates",
            conn,
            if_exists="replace",
            index=False,
            method="multi",
        )

        # INSERT...SELECT...ON CONFLICT DO NOTHING from temp -> target
        result = conn.execute(
            text(
                """
                WITH ins AS (
                    INSERT INTO public.cmc_funding_rates
                        (venue, symbol, ts, tf, funding_rate, mark_price, raw_tf, ingested_at)
                    SELECT
                        venue, symbol, ts::timestamptz, tf,
                        funding_rate::numeric, mark_price::numeric,
                        raw_tf, ingested_at::timestamptz
                    FROM _tmp_funding_rates
                    ON CONFLICT (venue, symbol, ts, tf) DO NOTHING
                    RETURNING 1
                )
                SELECT COUNT(*)::bigint AS n_inserted FROM ins
                """
            )
        )
        row = result.fetchone()
        n_inserted = int(row[0]) if row else 0

        # Drop temp table
        conn.execute(text("DROP TABLE IF EXISTS _tmp_funding_rates"))

    return n_inserted


def get_watermark(engine, venue: str, symbol: str, tf: str) -> Optional[datetime]:
    """
    Get the latest stored timestamp for a venue/symbol/tf combination.

    Args:
        engine: SQLAlchemy engine
        venue: Exchange venue name
        symbol: Base asset symbol ('BTC', 'ETH')
        tf: Settlement timeframe ('1h', '4h', '8h')

    Returns:
        datetime (UTC-aware) of last stored row, or None if no rows exist
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT MAX(ts) FROM public.cmc_funding_rates
                WHERE venue = :venue AND symbol = :sym AND tf = :tf
                """
            ),
            {"venue": venue, "sym": symbol, "tf": tf},
        ).fetchone()

    if row is None or row[0] is None:
        return None

    wm = row[0]
    # Ensure UTC-aware
    if hasattr(wm, "tzinfo") and wm.tzinfo is None:
        wm = wm.replace(tzinfo=timezone.utc)
    return wm


# ---------------------------------------------------------------------------
# Per-venue pagination logic
# ---------------------------------------------------------------------------


def _ingest_binance(
    engine,
    symbol_base: str,
    exchange_symbol: str,
    dry_run: bool,
    watermark_ms: Optional[int],
) -> int:
    """Paginate Binance forward from watermark using startTime/endTime windows."""
    if dry_run:
        start_ms = watermark_ms if watermark_ms else _BINANCE_BTC_EPOCH_MS
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        logger.info(
            "[dry-run] binance %s: would fetch from %s",
            symbol_base,
            start_dt.isoformat(),
        )
        return 0

    start_ms = (watermark_ms + _MS_PER_8H) if watermark_ms else _BINANCE_BTC_EPOCH_MS
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    total = 0

    while start_ms < now_ms:
        end_ms = min(start_ms + _BINANCE_BATCH_MS, now_ms)
        rows = fetch_binance_funding(
            symbol=exchange_symbol, start_ms=start_ms, end_ms=end_ms, limit=1000
        )
        if rows:
            inserted = upsert_funding_rates(engine, rows)
            total += inserted
            logger.info(
                "binance %s: fetched=%d inserted=%d (window %s to %s)",
                symbol_base,
                len(rows),
                inserted,
                datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
                datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
            )
        start_ms = end_ms + _MS_PER_8H
        time.sleep(0.1)

    return total


def _ingest_hyperliquid(
    engine,
    symbol_base: str,
    exchange_symbol: str,
    dry_run: bool,
    watermark_ms: Optional[int],
) -> int:
    """Paginate Hyperliquid forward from watermark using startTime."""
    if dry_run:
        start_ms = watermark_ms if watermark_ms else _HYPERLIQUID_EPOCH_MS
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        logger.info(
            "[dry-run] hyperliquid %s: would fetch from %s",
            symbol_base,
            start_dt.isoformat(),
        )
        return 0

    start_ms = (watermark_ms + _MS_PER_1H) if watermark_ms else _HYPERLIQUID_EPOCH_MS
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    total = 0

    while start_ms < now_ms:
        rows = fetch_hyperliquid_funding(coin=exchange_symbol, start_ms=start_ms)
        if not rows:
            break

        inserted = upsert_funding_rates(engine, rows)
        total += inserted
        logger.info(
            "hyperliquid %s: fetched=%d inserted=%d",
            symbol_base,
            len(rows),
            inserted,
        )

        # Advance to next batch: last ts + 1 interval
        last_ts = max(r.ts for r in rows)
        start_ms = int(last_ts.timestamp() * 1000) + _MS_PER_1H
        time.sleep(0.1)

    return total


def _ingest_bybit(
    engine,
    symbol_base: str,
    exchange_symbol: str,
    dry_run: bool,
    watermark_ms: Optional[int],
) -> int:
    """
    Paginate Bybit backward from now using sliding endTime windows.
    ALWAYS provides both startTime and endTime (Bybit constraint).
    Stops at watermark.
    """
    if dry_run:
        start_ms = watermark_ms if watermark_ms else 0
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        logger.info(
            "[dry-run] bybit %s: would fetch backward from now to %s",
            symbol_base,
            start_dt.isoformat(),
        )
        return 0

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    end_ms = now_ms
    stop_ms = watermark_ms if watermark_ms else 0
    total = 0

    while end_ms > stop_ms:
        start_ms = max(end_ms - _BYBIT_BATCH_MS, stop_ms)
        # CRITICAL: Always pass both startTime and endTime to Bybit
        rows = fetch_bybit_funding(
            symbol=exchange_symbol, start_ms=start_ms, end_ms=end_ms
        )
        if rows:
            inserted = upsert_funding_rates(engine, rows)
            total += inserted
            logger.info(
                "bybit %s: fetched=%d inserted=%d (window %s to %s)",
                symbol_base,
                len(rows),
                inserted,
                datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
                datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
            )

        end_ms = start_ms - _MS_PER_8H
        time.sleep(0.1)

    return total


def _ingest_dydx(
    engine,
    symbol_base: str,
    exchange_symbol: str,
    dry_run: bool,
    watermark_ms: Optional[int],
) -> int:
    """
    Paginate dYdX backward using effectiveBeforeOrAt cursor.
    Stops at watermark.
    """
    if dry_run:
        logger.info(
            "[dry-run] dydx %s: would fetch backward from now using cursor pagination (v4 only, Oct 2023+)",
            symbol_base,
        )
        return 0

    stop_ts: Optional[datetime] = None
    if watermark_ms:
        stop_ts = datetime.fromtimestamp(watermark_ms / 1000, tz=timezone.utc)

    # Start from now, paginate backward
    cursor: Optional[str] = None
    total = 0

    while True:
        rows = fetch_dydx_funding(
            market=exchange_symbol, before_or_at=cursor, limit=_DYDX_LIMIT
        )
        if not rows:
            break

        # Filter rows after watermark
        if stop_ts:
            rows = [r for r in rows if r.ts > stop_ts]

        if rows:
            inserted = upsert_funding_rates(engine, rows)
            total += inserted
            logger.info(
                "dydx %s: fetched=%d inserted=%d (oldest=%s)",
                symbol_base,
                len(rows),
                inserted,
                min(r.ts for r in rows).isoformat(),
            )

        # Advance cursor to oldest row in batch
        if rows:
            oldest_ts = min(r.ts for r in rows)
            cursor = oldest_ts.strftime("%Y-%m-%dT%H:%M:%SZ")

            # Stop if we've reached watermark or dYdX v4 epoch
            if stop_ts and oldest_ts <= stop_ts:
                break
            if cursor <= _DYDX_EPOCH_ISO:
                break
        else:
            break

        time.sleep(0.1)

    return total


def _ingest_aevo(
    engine,
    symbol_base: str,
    exchange_symbol: str,
    dry_run: bool,
    watermark_ms: Optional[int],
) -> int:
    """
    Paginate Aevo using start_ns from watermark with limit 50.
    """
    if dry_run:
        start_ns = (
            (watermark_ms * 1_000_000 + _MS_PER_1H * 1_000_000)
            if watermark_ms
            else _AEVO_EPOCH_NS
        )
        start_dt = datetime.fromtimestamp(start_ns / 1e9, tz=timezone.utc)
        logger.info(
            "[dry-run] aevo %s: would fetch from %s (ns timestamps)",
            symbol_base,
            start_dt.isoformat(),
        )
        return 0

    # Convert watermark ms to ns
    start_ns = (
        int(watermark_ms * 1_000_000 + _MS_PER_1H * 1_000_000)
        if watermark_ms
        else _AEVO_EPOCH_NS
    )
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
    total = 0

    while start_ns < now_ns:
        rows = fetch_aevo_funding(
            instrument=exchange_symbol, start_ns=start_ns, limit=_AEVO_LIMIT
        )
        if not rows:
            break

        inserted = upsert_funding_rates(engine, rows)
        total += inserted
        logger.info(
            "aevo %s: fetched=%d inserted=%d",
            symbol_base,
            len(rows),
            inserted,
        )

        # Advance to next page
        last_ts = max(r.ts for r in rows)
        start_ns = int(last_ts.timestamp() * 1e9) + int(_MS_PER_1H * 1_000_000)
        time.sleep(0.1)

    return total


def _ingest_aster(
    engine,
    symbol_base: str,
    exchange_symbol: str,
    dry_run: bool,
    watermark_ms: Optional[int],
) -> int:
    """Paginate Aster forward from watermark (identical to Binance pattern)."""
    if dry_run:
        start_ms = watermark_ms if watermark_ms else _ASTER_EPOCH_MS
        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        logger.info(
            "[dry-run] aster %s: would fetch from %s",
            symbol_base,
            start_dt.isoformat(),
        )
        return 0

    start_ms = (watermark_ms + _MS_PER_8H) if watermark_ms else _ASTER_EPOCH_MS
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    total = 0

    while start_ms < now_ms:
        end_ms = min(start_ms + _BINANCE_BATCH_MS, now_ms)
        rows = fetch_aster_funding(
            symbol=exchange_symbol, start_ms=start_ms, end_ms=end_ms, limit=1000
        )
        if rows:
            inserted = upsert_funding_rates(engine, rows)
            total += inserted
            logger.info(
                "aster %s: fetched=%d inserted=%d (window %s to %s)",
                symbol_base,
                len(rows),
                inserted,
                datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
                datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
            )
        start_ms = end_ms + _MS_PER_8H
        time.sleep(0.1)

    return total


# ---------------------------------------------------------------------------
# Rollup and fallback
# ---------------------------------------------------------------------------


def compute_daily_rollup(engine, venue: str, symbol: str) -> int:
    """
    Compute daily funding rate rollup from sub-day settlement rates.

    Reads all non-'1d' rows for venue/symbol, resamples to daily sum
    at UTC day boundaries, and upserts as tf='1d', raw_tf='rollup'.

    For 8h venues: sum of 3 settlements per day = daily rate.
    For 1h venues: sum of 24 settlements per day = daily rate.

    Args:
        engine: SQLAlchemy engine
        venue: Exchange venue
        symbol: Base asset symbol ('BTC', 'ETH')

    Returns:
        Number of daily rollup rows upserted
    """
    with engine.connect() as conn:
        df = pd.read_sql(
            text(
                """
                SELECT ts, funding_rate
                FROM public.cmc_funding_rates
                WHERE venue = :venue AND symbol = :sym AND tf != '1d'
                ORDER BY ts
                """
            ),
            conn,
            params={"venue": venue, "sym": symbol},
        )

    if df.empty:
        logger.info(
            "compute_daily_rollup: no sub-day rows for venue=%s symbol=%s",
            venue,
            symbol,
        )
        return 0

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    # Resample to daily sum (UTC day boundaries)
    daily = df["funding_rate"].resample("1D").sum().reset_index()
    daily.columns = ["ts", "funding_rate"]
    daily = daily.dropna(subset=["funding_rate"])

    if daily.empty:
        return 0

    rows = [
        FundingRateRow(
            venue=venue,
            symbol=symbol,
            ts=row["ts"].to_pydatetime(),
            tf="1d",
            funding_rate=float(row["funding_rate"]),
            raw_tf="rollup",
        )
        for _, row in daily.iterrows()
    ]

    inserted = upsert_funding_rates(engine, rows)
    logger.info(
        "compute_daily_rollup: venue=%s symbol=%s rolled up %d rows -> %d inserted",
        venue,
        symbol,
        len(rows),
        inserted,
    )
    return inserted


def get_funding_rate_with_fallback(
    engine,
    venue: str,
    symbol: str,
    ts: datetime,
    tf: str = "8h",
) -> Optional[float]:
    """
    Fetch funding rate for a specific venue/symbol/ts.

    Falls back to cross-venue average within +/- 30 minutes when the
    specific venue has no data for the requested timestamp.

    Args:
        engine: SQLAlchemy engine
        venue: Exchange venue to try first
        symbol: Base asset symbol ('BTC', 'ETH')
        ts: Settlement timestamp to look up
        tf: Timeframe granularity ('1h', '4h', '8h')

    Returns:
        float funding rate if found, None if no data available
    """
    # Try exact match first
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT funding_rate FROM public.cmc_funding_rates
                WHERE venue = :venue AND symbol = :sym AND ts = :ts AND tf = :tf
                """
            ),
            {"venue": venue, "sym": symbol, "ts": ts, "tf": tf},
        ).fetchone()

    if row is not None:
        return float(row[0])

    # Fallback: cross-venue average within +/- 30 minutes
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT AVG(funding_rate) FROM public.cmc_funding_rates
                WHERE symbol = :sym
                  AND ts BETWEEN :ts_lo AND :ts_hi
                  AND tf = :tf
                """
            ),
            {
                "sym": symbol,
                "ts_lo": ts - pd.Timedelta(minutes=30),
                "ts_hi": ts + pd.Timedelta(minutes=30),
                "tf": tf,
            },
        ).fetchone()

    if row is not None and row[0] is not None:
        logger.debug(
            "get_funding_rate_with_fallback: using cross-venue avg for venue=%s symbol=%s ts=%s",
            venue,
            symbol,
            ts.isoformat(),
        )
        return float(row[0])

    return None


# ---------------------------------------------------------------------------
# Top-level ingest orchestrator
# ---------------------------------------------------------------------------


def ingest_venue_full(
    engine,
    venue: str,
    symbols: List[str],
    dry_run: bool,
) -> int:
    """
    Ingest all available history for a venue+symbols, using DB watermark
    to perform incremental refresh.

    For dry_run=True: skips DB watermark query entirely (uses epoch 0 / None
    as start, equivalent to full backfill start). Logs what would be fetched
    but does NOT call any fetcher functions or write to DB.

    Args:
        engine: SQLAlchemy engine (None acceptable in dry-run mode)
        venue: Exchange venue name
        symbols: List of base asset symbols to ingest
        dry_run: If True, log only -- no DB access for watermark, no fetches

    Returns:
        Total rows inserted across all symbols
    """
    total = 0

    for symbol_base in symbols:
        exchange_symbol = VENUE_SYMBOLS.get(venue, {}).get(symbol_base, symbol_base)
        native_tf = VENUE_TF.get(venue, "8h")

        # Get watermark (skip in dry-run -- use epoch 0 as start)
        watermark_ms: Optional[int] = None
        if not dry_run:
            try:
                wm = get_watermark(engine, venue, symbol_base, native_tf)
                if wm is not None:
                    watermark_ms = int(wm.timestamp() * 1000)
                    logger.info(
                        "venue=%s symbol=%s watermark=%s",
                        venue,
                        symbol_base,
                        wm.isoformat(),
                    )
                else:
                    logger.info(
                        "venue=%s symbol=%s no watermark -- full backfill",
                        venue,
                        symbol_base,
                    )
            except Exception as exc:
                logger.warning(
                    "venue=%s symbol=%s watermark query failed: %s -- assuming full backfill",
                    venue,
                    symbol_base,
                    exc,
                )

        # Dispatch to venue-specific ingest function
        if venue == "binance":
            n = _ingest_binance(
                engine, symbol_base, exchange_symbol, dry_run, watermark_ms
            )
        elif venue == "hyperliquid":
            n = _ingest_hyperliquid(
                engine, symbol_base, exchange_symbol, dry_run, watermark_ms
            )
        elif venue == "bybit":
            n = _ingest_bybit(
                engine, symbol_base, exchange_symbol, dry_run, watermark_ms
            )
        elif venue == "dydx":
            n = _ingest_dydx(
                engine, symbol_base, exchange_symbol, dry_run, watermark_ms
            )
        elif venue == "aevo":
            n = _ingest_aevo(
                engine, symbol_base, exchange_symbol, dry_run, watermark_ms
            )
        elif venue == "aster":
            n = _ingest_aster(
                engine, symbol_base, exchange_symbol, dry_run, watermark_ms
            )
        elif venue == "lighter":
            # Stub: log WARNING and return 0 (lighter-python SDK required)
            _ = fetch_lighter_funding()
            logger.info("venue=lighter symbol=%s: skipped (stub)", symbol_base)
            n = 0
        else:
            logger.warning("Unknown venue: %s -- skipping", venue)
            n = 0

        logger.info("venue=%s symbol=%s total_inserted=%d", venue, symbol_base, n)
        total += n

    return total


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest perpetual funding rate history from 6 active venues "
            "(Binance, Hyperliquid, Bybit, dYdX, Aevo, Aster) into cmc_funding_rates."
        )
    )

    # Target selection
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_venues",
        help="Refresh all venues (binance, hyperliquid, bybit, dydx, aevo, aster, lighter).",
    )
    parser.add_argument(
        "--venue",
        choices=ALL_VENUES,
        help="Single venue to refresh.",
    )
    parser.add_argument(
        "--symbol",
        choices=DEFAULT_SYMBOLS,
        help="Single symbol to refresh (default: both BTC and ETH).",
    )

    # Mode flags
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show what would be fetched without writing to DB. "
            "Skips DB watermark query entirely (uses epoch 0 as start). "
            "Safe to run without a DB connection."
        ),
    )
    parser.add_argument(
        "--rollup",
        action="store_true",
        default=False,
        help="Compute daily rollup (tf='1d') after ingest.",
    )
    parser.add_argument(
        "--no-rollup",
        action="store_true",
        default=False,
        help="Skip daily rollup computation (overrides --rollup).",
    )

    # DB connection
    parser.add_argument(
        "--db-url",
        help="Database URL (default: resolved from db_config.env or TARGET_DB_URL).",
    )

    # Logging
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Determine venues and symbols
    if args.all_venues:
        venues = ALL_VENUES
    elif args.venue:
        venues = [args.venue]
    else:
        parser.error("Specify --all or --venue <name>")

    symbols = [args.symbol] if args.symbol else DEFAULT_SYMBOLS

    # Determine rollup behavior
    # Default: do NOT compute rollup (must opt-in with --rollup)
    # --no-rollup overrides --rollup
    do_rollup = args.rollup and not args.no_rollup

    # Create engine (skip in dry-run -- no DB connection needed)
    engine = None
    if not args.dry_run:
        db_url = resolve_db_url(args.db_url)
        engine = create_engine(db_url, poolclass=NullPool)
        logger.info("Connected to DB (NullPool)")

    logger.info(
        "Starting funding rate refresh: venues=%s symbols=%s dry_run=%s rollup=%s",
        venues,
        symbols,
        args.dry_run,
        do_rollup,
    )

    grand_total = 0
    for venue in venues:
        try:
            n = ingest_venue_full(engine, venue, symbols, dry_run=args.dry_run)
            grand_total += n
        except Exception as exc:
            logger.warning("venue=%s ingest failed: %s -- continuing", venue, exc)

    logger.info("Ingest complete. Total inserted: %d", grand_total)

    # Daily rollup (only when not dry-run and rollup enabled)
    if do_rollup and not args.dry_run:
        logger.info("Computing daily rollups...")
        rollup_total = 0
        for venue in venues:
            if venue == "lighter":
                continue  # lighter has no data; skip rollup
            for symbol in symbols:
                try:
                    n = compute_daily_rollup(engine, venue, symbol)
                    rollup_total += n
                except Exception as exc:
                    logger.warning(
                        "compute_daily_rollup venue=%s symbol=%s failed: %s",
                        venue,
                        symbol,
                        exc,
                    )
        logger.info("Rollup complete. Total rollup rows inserted: %d", rollup_total)
    elif do_rollup and args.dry_run:
        logger.info(
            "[dry-run] Would compute daily rollups for venues=%s symbols=%s",
            venues,
            symbols,
        )


if __name__ == "__main__":
    main()
