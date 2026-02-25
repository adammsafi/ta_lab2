"""
CanonicalOrder: Normalized order representation with exchange format translation.

Provides a single canonical order format that translates to exchange-specific
wire formats via to_exchange(). Supports Coinbase Advanced Trade and Kraken
AddOrder APIs.

Usage:
    order = CanonicalOrder("BTC/USD", "buy", "market", 0.01)
    coinbase_payload = order.to_exchange("coinbase")
    kraken_payload = order.to_exchange("kraken")

    order = CanonicalOrder.from_signal(signal_dict)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class CanonicalOrder:
    """
    Normalized order representation.

    Pair uses slash notation (e.g., "BTC/USD"). Side is lowercase "buy" or "sell".
    Order type is one of "market", "limit", "stop". Use to_exchange() to translate
    to the wire format for a specific exchange.
    """

    pair: str
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop"]
    quantity: float
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    client_order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: Optional[int] = None
    asset_id: Optional[int] = None

    def validate(self) -> None:
        """
        Validate order consistency.

        Raises:
            ValueError: if order is inconsistent (e.g., limit order missing limit_price).
        """
        if self.side not in ("buy", "sell"):
            raise ValueError(f"Invalid side '{self.side}'. Must be 'buy' or 'sell'.")

        if self.order_type not in ("market", "limit", "stop"):
            raise ValueError(
                f"Invalid order_type '{self.order_type}'. Must be 'market', 'limit', or 'stop'."
            )

        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}.")

        if self.order_type == "limit" and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders.")

        if self.order_type == "stop" and self.stop_price is None:
            raise ValueError("stop_price is required for stop orders.")

    def to_exchange(self, exchange: str) -> dict:
        """
        Translate this order to the wire format for the given exchange.

        Args:
            exchange: Exchange name, case-insensitive ("coinbase" or "kraken").

        Returns:
            Exchange-specific order payload dict.

        Raises:
            ValueError: if exchange is unknown.
        """
        name = exchange.lower()
        if name == "coinbase":
            return self._to_coinbase()
        elif name == "kraken":
            return self._to_kraken()
        else:
            raise ValueError(
                f"Unknown exchange '{exchange}'. Supported exchanges: coinbase, kraken."
            )

    def _to_coinbase(self) -> dict:
        """
        Build Coinbase Advanced Trade order payload.

        Uses product_id format (BTC-USD) and order_configuration nesting.
        market -> market_market_ioc (immediate-or-cancel with base_size)
        limit  -> limit_limit_gtc (good-til-cancelled)
        stop   -> stop_limit_stop_limit_gtc
        """
        product_id = self.pair.replace("/", "-").upper()

        if self.order_type == "market":
            order_configuration = {
                "market_market_ioc": {"base_size": str(self.quantity)}
            }
        elif self.order_type == "limit":
            order_configuration = {
                "limit_limit_gtc": {
                    "base_size": str(self.quantity),
                    "limit_price": str(self.limit_price),
                }
            }
        else:  # stop
            order_configuration = {
                "stop_limit_stop_limit_gtc": {
                    "base_size": str(self.quantity),
                    "stop_price": str(self.stop_price),
                    "limit_price": str(self.limit_price or self.stop_price),
                }
            }

        return {
            "client_order_id": self.client_order_id,
            "product_id": product_id,
            "side": self.side.upper(),
            "order_configuration": order_configuration,
        }

    def _to_kraken(self) -> dict:
        """
        Build Kraken AddOrder payload.

        Pair format: BTC->XBT, slash removed (e.g., "BTC/USD" -> "XBTUSD").
        ordertype: market / limit / stop-loss-limit
        """
        # Kraken uses XBT for Bitcoin
        raw_pair = self.pair.replace("/", "").upper()
        pair = raw_pair.replace("BTC", "XBT")

        base = {
            "pair": pair,
            "type": self.side,
            "volume": str(self.quantity),
        }

        if self.order_type == "market":
            return {**base, "ordertype": "market"}
        elif self.order_type == "limit":
            return {**base, "ordertype": "limit", "price": str(self.limit_price)}
        else:  # stop
            return {
                **base,
                "ordertype": "stop-loss-limit",
                "price": str(self.stop_price),
                "price2": str(self.limit_price or self.stop_price),
            }

    @classmethod
    def from_signal(cls, signal: dict) -> "CanonicalOrder":
        """
        Construct a CanonicalOrder from a signal dict.

        Accepts output from the cmc_signals table row or in-memory signal dicts.

        Required keys (at least one of each group):
            - pair (the trading pair in "BTC/USD" format)
            - side or direction (buy/sell or Long/Short/BUY/SELL)
            - quantity or size (base asset quantity as float)

        Optional keys:
            - order_type (default: "market")
            - limit_price
            - stop_price
            - signal_id (int FK to cmc_signals)
            - asset_id (int FK to dim_assets)

        Args:
            signal: dict with signal data.

        Returns:
            CanonicalOrder instance.

        Raises:
            ValueError: if required keys are missing.
        """
        # --- pair ---
        if "pair" not in signal:
            raise ValueError("Signal dict must contain 'pair' key.")
        pair = signal["pair"]

        # --- side / direction ---
        if "side" in signal:
            raw_side = str(signal["side"])
        elif "direction" in signal:
            raw_side = str(signal["direction"])
        else:
            raise ValueError("Signal dict must contain 'side' or 'direction' key.")

        side_lower = raw_side.lower()
        if side_lower in ("buy", "long"):
            side: Literal["buy", "sell"] = "buy"
        elif side_lower in ("sell", "short"):
            side = "sell"
        else:
            raise ValueError(
                f"Cannot normalize side/direction value '{raw_side}'. "
                "Expected: buy/sell/long/short (case-insensitive)."
            )

        # --- quantity ---
        if "quantity" in signal:
            quantity = float(signal["quantity"])
        elif "size" in signal:
            quantity = float(signal["size"])
        else:
            raise ValueError("Signal dict must contain 'quantity' or 'size' key.")

        # --- optional fields ---
        order_type = signal.get("order_type", "market")
        limit_price_raw = signal.get("limit_price")
        stop_price_raw = signal.get("stop_price")
        limit_price = float(limit_price_raw) if limit_price_raw is not None else None
        stop_price = float(stop_price_raw) if stop_price_raw is not None else None
        signal_id = signal.get("signal_id")
        asset_id = signal.get("asset_id")

        return cls(
            pair=pair,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            signal_id=signal_id,
            asset_id=asset_id,
        )

    def __repr__(self) -> str:
        return (
            f"CanonicalOrder({self.pair} {self.side} {self.order_type} {self.quantity})"
        )
