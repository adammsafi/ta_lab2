"""
ws_feeds - WebSocket feed managers for Hyperliquid, Kraken, and Coinbase.

Each feed runs in a dedicated daemon thread and writes live tick prices into a
shared PriceCache instance.  The main executor thread is never blocked.

Feed overview
-------------
* **Hyperliquid** — Uses the official ``hyperliquid-python-sdk``
  ``WebsocketManager`` (threading-based, NOT asyncio).  Subscribes to the
  ``allMids`` channel which delivers all mid prices in a single push.  The SDK
  pings the server every 50 s; there is no application-level reconnection —
  monitor ``PriceCache.is_stale()`` externally.

* **Kraken** — Uses ``websockets 16.0`` with the ``async for websocket in
  connect(...)`` infinite-iterator pattern which provides automatic exponential
  backoff reconnection.  Subscribes to the ``ticker`` channel on the v2 public
  endpoint ``wss://ws.kraken.com/v2``.

* **Coinbase** — Uses the same ``websockets`` pattern against
  ``wss://advanced-trade-ws.coinbase.com``.  CRITICAL: subscribe message must
  be sent within 5 s of connect or the server closes the connection.

Both async feeds run inside a freshly created ``asyncio`` event loop that lives
in its own daemon thread — no interference with any outer event loop.

Dependencies
------------
* ``hyperliquid-python-sdk`` (pip install hyperliquid-python-sdk)
* ``websockets >= 16.0`` (pip install "websockets>=16.0")

If either package is absent the corresponding feed is skipped and a warning is
logged; the others continue unaffected.

Exports: start_hl_feed, start_kraken_feed, start_coinbase_feed, start_all_feeds
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import TYPE_CHECKING

from ta_lab2.executor.price_cache import PriceCache

if TYPE_CHECKING:
    pass

__all__ = [
    "start_hl_feed",
    "start_kraken_feed",
    "start_coinbase_feed",
    "start_all_feeds",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_KRAKEN_WS_URL = "wss://ws.kraken.com/v2"
_COINBASE_WS_URL = "wss://advanced-trade-ws.coinbase.com"

# ---------------------------------------------------------------------------
# Hyperliquid feed (SDK WebsocketManager — threading-based)
# ---------------------------------------------------------------------------


def start_hl_feed(
    price_cache: PriceCache,
    logger: logging.Logger | None = None,
) -> threading.Thread:
    """Start the Hyperliquid ``allMids`` subscription in a daemon thread.

    Uses the ``hyperliquid-python-sdk`` ``WebsocketManager`` which is
    threading-based (not asyncio) and sends a keep-alive ping every 50 s.

    .. warning::
        The SDK has **no** application-level reconnection logic.  If the
        connection silently drops, ``PriceCache.is_stale()`` will detect
        the staleness.  The calling service should alert and restart.

    Parameters
    ----------
    price_cache:
        Shared cache written on every ``allMids`` message.
    logger:
        Logger to use.  Defaults to the module logger.

    Returns
    -------
    threading.Thread
        The daemon thread running the subscription loop.
    """
    log = logger or logging.getLogger(__name__)

    try:
        from hyperliquid.info import Info  # type: ignore[import-untyped]
        from hyperliquid.utils import constants  # type: ignore[import-untyped]
    except ImportError:
        log.warning(
            "hyperliquid-python-sdk not installed; HL feed disabled. "
            "Install with: pip install hyperliquid-python-sdk"
        )

        # Return a no-op thread so callers can always join the returned list.
        t = threading.Thread(target=lambda: None, daemon=True, name="hl-feed-disabled")
        t.start()
        return t

    def _on_all_mids(msg: dict) -> None:  # type: ignore[type-arg]
        """Callback fired by SDK on each allMids push."""
        try:
            mids: dict[str, str] = msg["data"]["mids"]
            for symbol, price_str in mids.items():
                price_cache.update(symbol, float(price_str))
        except Exception:
            log.exception("HL allMids callback error (non-fatal)")

    def _run() -> None:
        try:
            log.info("Starting Hyperliquid allMids WebSocket feed")
            info = Info(constants.MAINNET_API_URL, skip_ws=False)
            info.subscribe({"type": "allMids"}, _on_all_mids)
            # SDK WebsocketManager runs in its own thread; the subscription
            # call returns immediately.  Block this thread forever so the
            # daemon thread stays alive as long as the process is alive.
            threading.Event().wait()
        except Exception:
            log.exception("HL feed thread error")

    t = threading.Thread(target=_run, daemon=True, name="hl-feed")
    t.start()
    log.info("HL feed daemon thread started")
    return t


# ---------------------------------------------------------------------------
# Kraken feed (websockets 16.0 — asyncio in dedicated thread)
# ---------------------------------------------------------------------------


async def _kraken_feed_loop(
    price_cache: PriceCache,
    symbols: list[str],
    logger: logging.Logger,
) -> None:
    """Kraken WS v2 ticker subscription with auto-reconnect.

    Uses the ``websockets 16.0`` ``async for websocket in connect(...)``
    infinite-iterator pattern which handles exponential-backoff reconnection
    transparently.

    Parameters
    ----------
    price_cache:
        Shared price cache; updated on every ticker message.
    symbols:
        Kraken v2 symbol strings, e.g. ``["BTC/USD", "ETH/USD"]``.
    logger:
        Logger for status and error messages.
    """
    try:
        import websockets  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "websockets not installed; Kraken feed disabled. "
            "Install with: pip install 'websockets>=16.0'"
        )
        return

    subscribe_msg = json.dumps(
        {
            "method": "subscribe",
            "params": {
                "channel": "ticker",
                "symbol": symbols,
            },
        }
    )

    logger.info("Starting Kraken ticker feed for %d symbols", len(symbols))

    async for websocket in websockets.connect(_KRAKEN_WS_URL):
        try:
            await websocket.send(subscribe_msg)
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    if data.get("channel") == "ticker":
                        for item in data.get("data", []):
                            price_cache.update(item["symbol"], float(item["last"]))
                except Exception:
                    logger.exception("Kraken message parse error (non-fatal)")
        except websockets.ConnectionClosed:
            logger.warning("Kraken WS connection closed; reconnecting...")
            continue
        except Exception:
            logger.exception("Kraken feed error; reconnecting...")
            continue


def start_kraken_feed(
    price_cache: PriceCache,
    symbols: list[str],
    logger: logging.Logger | None = None,
) -> threading.Thread:
    """Start the Kraken ticker feed in a daemon thread.

    The thread creates its own ``asyncio`` event loop so it is completely
    isolated from any caller event loop.

    Parameters
    ----------
    price_cache:
        Shared price cache.
    symbols:
        Kraken v2 symbol strings, e.g. ``["BTC/USD", "ETH/USD"]``.
    logger:
        Logger to use.  Defaults to the module logger.

    Returns
    -------
    threading.Thread
        The daemon thread running the asyncio event loop.
    """
    log = logger or logging.getLogger(__name__)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_kraken_feed_loop(price_cache, symbols, log))
        except Exception:
            log.exception("Kraken feed thread error")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="kraken-feed")
    t.start()
    log.info("Kraken feed daemon thread started (%d symbols)", len(symbols))
    return t


# ---------------------------------------------------------------------------
# Coinbase feed (websockets 16.0 — asyncio in dedicated thread)
# ---------------------------------------------------------------------------


async def _coinbase_feed_loop(
    price_cache: PriceCache,
    product_ids: list[str],
    logger: logging.Logger,
) -> None:
    """Coinbase Advanced Trade ticker subscription with auto-reconnect.

    .. important::
        The subscribe message **must** be sent within 5 seconds of ``connect``
        or the Coinbase server closes the connection.  No DB lookups or heavy
        work should occur between ``connect`` and ``send``.

    Parameters
    ----------
    price_cache:
        Shared price cache; updated on every ticker event.
    product_ids:
        Coinbase product IDs, e.g. ``["BTC-USD", "ETH-USD"]``.
    logger:
        Logger for status and error messages.
    """
    try:
        import websockets  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "websockets not installed; Coinbase feed disabled. "
            "Install with: pip install 'websockets>=16.0'"
        )
        return

    subscribe_msg = json.dumps(
        {
            "type": "subscribe",
            "product_ids": product_ids,
            "channel": "ticker",
        }
    )

    logger.info("Starting Coinbase ticker feed for %d product IDs", len(product_ids))

    async for websocket in websockets.connect(_COINBASE_WS_URL):
        try:
            # CRITICAL: subscribe IMMEDIATELY — Coinbase closes connection
            # after 5 s with no subscription.
            await websocket.send(subscribe_msg)
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                    if data.get("channel") == "ticker":
                        for event in data.get("events", []):
                            for ticker in event.get("tickers", []):
                                price_cache.update(
                                    ticker["product_id"],
                                    float(ticker["price"]),
                                )
                except Exception:
                    logger.exception("Coinbase message parse error (non-fatal)")
        except websockets.ConnectionClosed:
            logger.warning("Coinbase WS connection closed; reconnecting...")
            continue
        except Exception:
            logger.exception("Coinbase feed error; reconnecting...")
            continue


def start_coinbase_feed(
    price_cache: PriceCache,
    product_ids: list[str],
    logger: logging.Logger | None = None,
) -> threading.Thread:
    """Start the Coinbase Advanced Trade ticker feed in a daemon thread.

    The thread creates its own ``asyncio`` event loop so it is completely
    isolated from any caller event loop.

    Parameters
    ----------
    price_cache:
        Shared price cache.
    product_ids:
        Coinbase product IDs, e.g. ``["BTC-USD", "ETH-USD"]``.
    logger:
        Logger to use.  Defaults to the module logger.

    Returns
    -------
    threading.Thread
        The daemon thread running the asyncio event loop.
    """
    log = logger or logging.getLogger(__name__)

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_coinbase_feed_loop(price_cache, product_ids, log))
        except Exception:
            log.exception("Coinbase feed thread error")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="coinbase-feed")
    t.start()
    log.info("Coinbase feed daemon thread started (%d product IDs)", len(product_ids))
    return t


# ---------------------------------------------------------------------------
# Convenience: start all configured feeds
# ---------------------------------------------------------------------------


def start_all_feeds(
    price_cache: PriceCache,
    kraken_symbols: list[str] | None = None,
    coinbase_product_ids: list[str] | None = None,
    logger: logging.Logger | None = None,
) -> list[threading.Thread]:
    """Start all configured WebSocket feeds.

    Hyperliquid is always started (primary exchange for VM execution).
    Kraken and Coinbase are started only when their symbol lists are
    provided and non-empty.

    All threads are daemon threads: they die automatically when the main
    process exits, so no explicit cleanup is needed for normal shutdown.

    Parameters
    ----------
    price_cache:
        The shared ``PriceCache`` instance written by all feeds.
    kraken_symbols:
        Optional list of Kraken v2 symbols, e.g. ``["BTC/USD", "ETH/USD"]``.
        Pass ``None`` or ``[]`` to skip the Kraken feed.
    coinbase_product_ids:
        Optional list of Coinbase product IDs, e.g. ``["BTC-USD", "ETH-USD"]``.
        Pass ``None`` or ``[]`` to skip the Coinbase feed.
    logger:
        Logger to use.  Defaults to the module logger.

    Returns
    -------
    list[threading.Thread]
        All daemon threads that were started (1–3 threads).
    """
    log = logger or logging.getLogger(__name__)
    threads: list[threading.Thread] = []

    # Hyperliquid — always started
    threads.append(start_hl_feed(price_cache, log))

    # Kraken — only when symbols provided
    if kraken_symbols:
        threads.append(start_kraken_feed(price_cache, kraken_symbols, log))
    else:
        log.debug("Kraken feed skipped (no symbols provided)")

    # Coinbase — only when product IDs provided
    if coinbase_product_ids:
        threads.append(start_coinbase_feed(price_cache, coinbase_product_ids, log))
    else:
        log.debug("Coinbase feed skipped (no product IDs provided)")

    log.info(
        "start_all_feeds: %d feed thread(s) started "
        "(HL=always, Kraken=%s, Coinbase=%s)",
        len(threads),
        bool(kraken_symbols),
        bool(coinbase_product_ids),
    )
    return threads
