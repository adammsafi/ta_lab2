"""
funding_fetchers.py
===================

Per-venue fetch functions for perpetual funding rate history.

Supported venues:
    - Binance (8h settlement, public REST, ~Sep 2019 history for BTC)
    - Hyperliquid (1h settlement, public POST /info, ~2023 history)
    - Bybit (8h BTC/ETH, public REST, ~2019 history)
    - dYdX v4 (1h settlement, v4 indexer only, Oct 2023+)
    - Aevo (1h settlement, nanosecond timestamps, Sep 2023+)
    - Aster (8h, mirrors Binance Futures API exactly)
    - Lighter (STUB -- lighter-python SDK required; returns empty list)

All fetchers:
    - Use requests.get/post with timeout=30
    - Call resp.raise_for_status()
    - Return List[FundingRateRow]
    - Handle empty responses gracefully (return [])
    - Log errors at WARNING level, do not crash on individual venue failure

CRITICAL pitfalls (from research):
    - Bybit: MUST provide both startTime and endTime, or neither
    - Aevo: timestamps are NANOSECONDS (divide by 1e9, NOT 1e3)
    - dYdX: use v4 indexer only (indexer.dydx.trade/v4), NOT v3
    - Lighter: no confirmed public REST endpoint; SDK required
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FundingRateRow:
    """Normalized funding rate record for cmc_funding_rates table."""

    venue: str
    """Exchange venue: 'binance', 'hyperliquid', 'bybit', 'dydx', 'aevo', 'aster', 'lighter'"""

    symbol: str
    """Base asset symbol without quote: 'BTC', 'ETH'"""

    ts: datetime
    """Settlement timestamp in UTC"""

    tf: str
    """Timeframe / settlement granularity: '1h', '4h', '8h'"""

    funding_rate: float
    """Raw per-settlement funding rate (e.g. 0.0001 = 0.01%)"""

    mark_price: Optional[float] = field(default=None)
    """Mark price at settlement time, if available"""

    raw_tf: str = field(default="")
    """Original venue settlement period string (e.g. '8h', '1h', 'rollup')"""


# ---------------------------------------------------------------------------
# Venue fetchers
# ---------------------------------------------------------------------------


def fetch_binance_funding(
    symbol: str = "BTCUSDT",
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    limit: int = 1000,
) -> List[FundingRateRow]:
    """
    Fetch Binance perpetual funding rate history.

    Endpoint: GET https://fapi.binance.com/fapi/v1/fundingRate
    Settlement: 8h (00:00, 08:00, 16:00 UTC)
    History: ~Sep 2019 for BTCUSDT
    Rate limit: 500 req/5min/IP; max 1000 rows per call
    Auth: None required for market data

    Args:
        symbol: Trading pair symbol (e.g. 'BTCUSDT')
        start_ms: Start time in milliseconds UTC (None = earliest available)
        end_ms: End time in milliseconds UTC (None = now)
        limit: Max rows per request (max 1000)

    Returns:
        List of FundingRateRow with venue='binance', tf='8h'
    """
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    params: dict = {"symbol": symbol, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_binance_funding error for %s: %s", symbol, exc)
        return []

    data = resp.json()
    if not data:
        return []

    base = symbol.replace("USDT", "").replace("BUSD", "")
    rows: List[FundingRateRow] = []
    for item in data:
        try:
            rows.append(
                FundingRateRow(
                    venue="binance",
                    symbol=base,
                    ts=datetime.fromtimestamp(
                        int(item["fundingTime"]) / 1000, tz=timezone.utc
                    ),
                    tf="8h",
                    funding_rate=float(item["fundingRate"]),
                    mark_price=(
                        float(item["markPrice"])
                        if item.get("markPrice") not in (None, "")
                        else None
                    ),
                    raw_tf="8h",
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "fetch_binance_funding parse error for item %s: %s", item, exc
            )

    return rows


def fetch_hyperliquid_funding(
    coin: str = "BTC",
    start_ms: int = 0,
    end_ms: Optional[int] = None,
) -> List[FundingRateRow]:
    """
    Fetch Hyperliquid perpetual funding rate history.

    Endpoint: POST https://api.hyperliquid.xyz/info
    Payload: {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
    Settlement: 1h (hourly, funded at rate/8 per hour)
    Auth: None required
    History: ~2023 (Hyperliquid mainnet launch)

    Args:
        coin: Base asset symbol (e.g. 'BTC', 'ETH')
        start_ms: Start time in milliseconds UTC
        end_ms: End time in milliseconds UTC (optional)

    Returns:
        List of FundingRateRow with venue='hyperliquid', tf='1h'
    """
    url = "https://api.hyperliquid.xyz/info"
    payload: dict = {"type": "fundingHistory", "coin": coin, "startTime": start_ms}
    if end_ms is not None:
        payload["endTime"] = end_ms

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_hyperliquid_funding error for %s: %s", coin, exc)
        return []

    data = resp.json()
    if not data:
        return []

    rows: List[FundingRateRow] = []
    for item in data:
        try:
            rows.append(
                FundingRateRow(
                    venue="hyperliquid",
                    symbol=coin,
                    ts=datetime.fromtimestamp(
                        int(item["time"]) / 1000, tz=timezone.utc
                    ),
                    tf="1h",
                    funding_rate=float(item["fundingRate"]),
                    raw_tf="1h",
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning(
                "fetch_hyperliquid_funding parse error for item %s: %s", item, exc
            )

    return rows


def fetch_bybit_funding(
    symbol: str = "BTCUSDT",
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
) -> List[FundingRateRow]:
    """
    Fetch Bybit perpetual funding rate history.

    Endpoint: GET https://api.bybit.com/v5/market/funding/history
    Settlement: 8h for BTC/ETH (Bybit dynamic system does NOT apply to BTC/ETH)
    Rate limit: None documented; max 200 rows per request
    Auth: None required for market data

    CRITICAL: Bybit requires endTime when startTime is provided.
    NEVER pass startTime without endTime -- returns HTTP 400.
    Always pass both or neither.

    Args:
        symbol: Trading pair symbol (e.g. 'BTCUSDT')
        start_ms: Start time in milliseconds UTC (only used when end_ms also provided)
        end_ms: End time in milliseconds UTC

    Returns:
        List of FundingRateRow with venue='bybit', tf='8h'
    """
    url = "https://api.bybit.com/v5/market/funding/history"
    params: dict = {"category": "linear", "symbol": symbol, "limit": 200}

    # CRITICAL: Must not pass startTime alone -- Bybit returns error
    # Pass both or neither
    if end_ms is not None:
        params["endTime"] = end_ms
        if start_ms is not None:
            params["startTime"] = start_ms
    # If only start_ms provided (no end_ms), do NOT include startTime

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_bybit_funding error for %s: %s", symbol, exc)
        return []

    data = resp.json()
    result_list = data.get("result", {}).get("list", [])
    if not result_list:
        return []

    base = symbol.replace("USDT", "").replace("USDC", "")
    rows: List[FundingRateRow] = []
    for item in result_list:
        try:
            rows.append(
                FundingRateRow(
                    venue="bybit",
                    symbol=base,
                    ts=datetime.fromtimestamp(
                        int(item["fundingRateTimestamp"]) / 1000, tz=timezone.utc
                    ),
                    tf="8h",
                    funding_rate=float(item["fundingRate"]),
                    raw_tf="8h",
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("fetch_bybit_funding parse error for item %s: %s", item, exc)

    return rows


def fetch_dydx_funding(
    market: str = "BTC-USD",
    before_or_at: Optional[str] = None,
    limit: int = 100,
) -> List[FundingRateRow]:
    """
    Fetch dYdX v4 perpetual funding rate history.

    Endpoint: GET https://indexer.dydx.trade/v4/historicalFunding/{market}
    Settlement: 1h (hourly tick epoch)
    Cursor: effectiveBeforeOrAt (ISO datetime string)
    Auth: None required
    History: dYdX v4 mainnet launched Oct 2023 only (v3 data not available via v4 API)

    NOTE: Use v4 ONLY. Do NOT use v3 endpoint (api.dydx.exchange/v1/ -- deprecated).

    Args:
        market: Market identifier (e.g. 'BTC-USD', 'ETH-USD')
        before_or_at: ISO datetime string cursor for pagination (e.g. '2024-01-01T00:00:00Z')
        limit: Max rows per request (max 100)

    Returns:
        List of FundingRateRow with venue='dydx', tf='1h'
    """
    url = f"https://indexer.dydx.trade/v4/historicalFunding/{market}"
    params: dict = {"limit": limit}
    if before_or_at is not None:
        params["effectiveBeforeOrAt"] = before_or_at

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_dydx_funding error for %s: %s", market, exc)
        return []

    data = resp.json()
    funding_list = data.get("historicalFunding", [])
    if not funding_list:
        return []

    base = market.split("-")[0]
    rows: List[FundingRateRow] = []
    for item in funding_list:
        try:
            rows.append(
                FundingRateRow(
                    venue="dydx",
                    symbol=base,
                    ts=datetime.fromisoformat(
                        item["effectiveAt"].replace("Z", "+00:00")
                    ),
                    tf="1h",
                    funding_rate=float(item["rate"]),
                    raw_tf="1h",
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("fetch_dydx_funding parse error for item %s: %s", item, exc)

    return rows


def fetch_aevo_funding(
    instrument: str = "BTC-PERP",
    start_ns: int = 0,
    end_ns: Optional[int] = None,
    limit: int = 50,
) -> List[FundingRateRow]:
    """
    Fetch Aevo perpetual funding rate history.

    Endpoint: GET https://api.aevo.xyz/funding-history
    Settlement: 1h (Aevo pays hourly; rate = 8h rate / 8)
    Auth: None required for public market data
    History: Available from ~Sep 2023 (Aevo launch)

    CRITICAL: Timestamps from Aevo are UNIX NANOSECONDS, not milliseconds.
    Always divide by 1e9 (NOT 1e3) to convert to seconds.
    Forgetting this produces dates in ~2059.

    Response items are arrays: [instrument_name, timestamp_ns, rate, mark_price]

    Args:
        instrument: Instrument name (e.g. 'BTC-PERP', 'ETH-PERP')
        start_ns: Start time in nanoseconds UTC
        end_ns: End time in nanoseconds UTC (optional)
        limit: Max rows per request (max 50)

    Returns:
        List of FundingRateRow with venue='aevo', tf='1h'
    """
    url = "https://api.aevo.xyz/funding-history"
    params: dict = {
        "instrument_name": instrument,
        "start_time": start_ns,
        "limit": limit,
    }
    if end_ns is not None:
        params["end_time"] = end_ns

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_aevo_funding error for %s: %s", instrument, exc)
        return []

    data = resp.json()
    funding_history = data.get("funding_history", [])
    if not funding_history:
        return []

    base = instrument.split("-")[0]
    rows: List[FundingRateRow] = []
    for item in funding_history:
        try:
            # CRITICAL: Aevo timestamps are nanoseconds, NOT milliseconds
            ts_ns = int(item[1])
            ts = datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc)
            rows.append(
                FundingRateRow(
                    venue="aevo",
                    symbol=base,
                    ts=ts,
                    tf="1h",
                    funding_rate=float(item[2]),
                    mark_price=float(item[3]) if len(item) > 3 and item[3] else None,
                    raw_tf="1h",
                )
            )
        except (IndexError, ValueError, TypeError) as exc:
            logger.warning("fetch_aevo_funding parse error for item %s: %s", item, exc)

    return rows


def fetch_aster_funding(
    symbol: str = "BTCUSDT",
    start_ms: Optional[int] = None,
    end_ms: Optional[int] = None,
    limit: int = 1000,
) -> List[FundingRateRow]:
    """
    Fetch Aster perpetual funding rate history.

    Endpoint: GET https://fapi.asterdex.com/fapi/v1/fundingRate
    Aster mirrors the Binance Futures API exactly.
    Settlement: 8h for most pairs (ASTERUSDT is 4h)
    Auth: None required for market data
    History: ~2023 (Aster launch date; exact depth unknown)

    Args:
        symbol: Trading pair symbol (e.g. 'BTCUSDT')
        start_ms: Start time in milliseconds UTC
        end_ms: End time in milliseconds UTC
        limit: Max rows per request (max 1000)

    Returns:
        List of FundingRateRow with venue='aster', tf='8h'
    """
    url = "https://fapi.asterdex.com/fapi/v1/fundingRate"
    params: dict = {"symbol": symbol, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch_aster_funding error for %s: %s", symbol, exc)
        return []

    data = resp.json()
    if not data:
        return []

    base = symbol.replace("USDT", "").replace("BUSD", "")
    rows: List[FundingRateRow] = []
    for item in data:
        try:
            rows.append(
                FundingRateRow(
                    venue="aster",
                    symbol=base,
                    ts=datetime.fromtimestamp(
                        int(item["fundingTime"]) / 1000, tz=timezone.utc
                    ),
                    tf="8h",
                    funding_rate=float(item["fundingRate"]),
                    raw_tf="8h",
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("fetch_aster_funding parse error for item %s: %s", item, exc)

    return rows


def fetch_lighter_funding(
    *args,
    **kwargs,
) -> List[FundingRateRow]:
    """
    STUB: Lighter funding rate fetcher -- lighter-python SDK integration deferred.

    TODO: Implement once the Lighter REST funding history endpoint is confirmed
    or lighter-python SDK is validated for historical data access.

    Open question from research (51-RESEARCH.md):
    - Lighter docs page (docs.lighter.xyz/perpetual-futures/api) returned 404
    - Lighter mainnet launched 2024; their API uses lighter-python SDK
    - REST endpoint for historical funding rates is unconfirmed as of 2026-02-25
    - When implementing: use lighter-python OrderApi or dedicated market data method
    - Fallback: Coinglass aggregator as data source for historical Lighter funding data

    Returns:
        Empty list (no data fetched)
    """
    logger.warning(
        "Lighter funding rate API not confirmed; requires lighter-python SDK. "
        "Lighter stub returning empty list. "
        "See TODO in fetch_lighter_funding and 51-RESEARCH.md open questions."
    )
    return []
