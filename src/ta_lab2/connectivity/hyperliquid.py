# src/ta_lab2/connectivity/hyperliquid.py

from .base import ExchangeInterface
from typing import Dict, List
from .decorators import handle_api_errors


class HyperliquidExchange(ExchangeInterface):
    BASE_URL = "https://api.hyperliquid.xyz"

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        super().__init__(api_key, api_secret, **kwargs)

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'BTC' for Hyperliquid (assuming USD based)."""
        return pair.split("/")[0].upper()

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        self.logger.warning(
            "Hyperliquid get_ticker is not implemented, likely requires WebSocket."
        )
        raise NotImplementedError(
            "Hyperliquid get_ticker is not implemented, likely requires WebSocket."
        )

    @handle_api_errors
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        self.logger.warning(
            "Hyperliquid get_order_book is not implemented, likely requires WebSocket."
        )
        raise NotImplementedError(
            "Hyperliquid get_order_book is not implemented, likely requires WebSocket."
        )

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetches historical kline (candlestick) data from Hyperliquid.
        This is based on the `candles_snapshot` method in the SDK's info.py.
        """
        coin = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/info"

        req = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": start_time * 1000,
                "endTime": end_time * 1000,
            },
        }
        self.logger.info(f"Fetching klines for {pair} from Hyperliquid...")
        self.logger.debug(f"Request: POST {endpoint} with payload {req}")

        response = self.session.post(endpoint, json=req)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched klines for {pair} from Hyperliquid.")

        klines = []
        if data:
            for kline in data:
                klines.append(
                    [
                        int(kline["t"] / 1000),
                        float(kline["o"]),
                        float(kline["h"]),
                        float(kline["l"]),
                        float(kline["c"]),
                        float(kline["v"]),
                    ]
                )
        return klines

    def get_account_balances(self) -> Dict[str, float]:
        raise NotImplementedError(
            "Hyperliquid get_account_balances not yet implemented."
        )

    def get_open_orders(self, pair: str = None) -> List[dict]:
        raise NotImplementedError("Hyperliquid get_open_orders not yet implemented.")

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        raise NotImplementedError("Hyperliquid place_limit_order not yet implemented.")

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        raise NotImplementedError("Hyperliquid place_market_order not yet implemented.")

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        raise NotImplementedError("Hyperliquid cancel_order not yet implemented.")
