"""
PriceCache - Thread-safe real-time price store for WebSocket feed consumers.

Used by the VM executor (Phase 113) to share live tick prices from all three
WebSocket feeds (Hyperliquid, Kraken, Coinbase) with the stop monitor and
position sizer.

All arithmetic uses Decimal for financial precision. Per-symbol timestamps
enable staleness detection: if a symbol's last-update age exceeds
max_age_seconds (default 120 s), the price is considered stale and should
not be trusted for stop/TP decisions.

Exports: PriceCache
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from decimal import Decimal

__all__ = ["PriceCache"]


class PriceCache:
    """Thread-safe last-price cache keyed by symbol string.

    All write and read operations acquire an RLock so that WebSocket callback
    threads and the synchronous executor/stop-monitor thread can coexist
    safely.

    Symbols are stored exactly as received from the exchange (e.g. "BTC" from
    Hyperliquid, "BTC/USD" from Kraken, "BTC-USD" from Coinbase).  Callers
    are responsible for normalising symbols before lookup.

    Example::

        cache = PriceCache()
        cache.update("BTC", 95_000.5)
        price = cache.get("BTC")                    # Decimal('95000.5')
        price, age = cache.get_with_age("BTC")      # (Decimal('95000.5'), 0.02)
        cache.is_stale("BTC", max_age_seconds=120)  # False
    """

    def __init__(self) -> None:
        self._prices: dict[str, Decimal] = {}
        self._timestamps: dict[str, datetime] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def update(self, symbol: str, price: float) -> None:
        """Update the latest price for *symbol*.

        Converts *price* via ``Decimal(str(price))`` to avoid float
        representation artefacts (e.g. 95000.5 → Decimal('95000.5') not
        Decimal('95000.4999999...')).

        Thread-safe; may be called from any WebSocket callback thread.
        """
        with self._lock:
            self._prices[symbol] = Decimal(str(price))
            self._timestamps[symbol] = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Read — single price
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> Decimal | None:
        """Return the latest price for *symbol*, or ``None`` if not available."""
        with self._lock:
            return self._prices.get(symbol)

    def get_with_age(self, symbol: str) -> tuple[Decimal | None, float]:
        """Return ``(price, age_seconds)`` for *symbol*.

        Returns ``(None, inf)`` if the symbol has no price record.

        ``age_seconds`` is how many seconds have elapsed since the last
        ``update()`` call for this symbol.
        """
        with self._lock:
            price = self._prices.get(symbol)
            ts = self._timestamps.get(symbol)
            if price is None or ts is None:
                return None, float("inf")
            age = (datetime.now(timezone.utc) - ts).total_seconds()
            return price, age

    # ------------------------------------------------------------------
    # Staleness helpers
    # ------------------------------------------------------------------

    def is_stale(self, symbol: str, max_age_seconds: float = 120.0) -> bool:
        """Return ``True`` if the price for *symbol* is older than *max_age_seconds*.

        Also returns ``True`` when the symbol has no price record at all
        (age is treated as ``inf``).
        """
        _, age = self.get_with_age(symbol)
        return age > max_age_seconds

    def stale_symbols(self, max_age_seconds: float = 120.0) -> list[str]:
        """Return a list of symbols whose prices are older than *max_age_seconds*.

        Symbols with no price record are NOT included (they have never been
        seen); only symbols that were once updated but have gone stale are
        returned.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            stale: list[str] = []
            for sym, ts in self._timestamps.items():
                if (now - ts).total_seconds() > max_age_seconds:
                    stale.append(sym)
            return stale

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def all_symbols(self) -> list[str]:
        """Return a snapshot list of all symbols that have a price record."""
        with self._lock:
            return list(self._prices.keys())

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __repr__(self) -> str:  # pragma: no cover
        with self._lock:
            n = len(self._prices)
        return f"PriceCache({n} symbols)"
