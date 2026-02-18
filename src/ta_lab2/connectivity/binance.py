# src/ta_lab2/connectivity/binance.py

from .base import ExchangeInterface
from typing import Dict, List
from .decorators import handle_api_errors


class BinanceExchange(ExchangeInterface):
    BASE_URL = "https://api.binance.com"

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        super().__init__(api_key, api_secret, **kwargs)

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'BTCUSDT'."""
        return pair.replace("/", "").upper()

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        """
        Fetches the latest price for a given trading pair from Binance.
        Endpoint: GET /api/v3/ticker/price
        """
        symbol = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/api/v3/ticker/price"
        params = {"symbol": symbol}
        self.logger.info(f"Fetching ticker for {pair} from Binance...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched ticker for {pair} from Binance.")
        return {"last_price": float(data["price"])}

    @handle_api_errors
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        """
        Fetches the current order book from Binance.
        Endpoint: GET /api/v3/depth
        """
        symbol = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/api/v3/depth"

        allowed_limits = [5, 10, 20, 50, 100, 500, 1000, 5000]
        limit = min(allowed_limits, key=lambda x: abs(x - depth))

        params = {"symbol": symbol, "limit": limit}
        self.logger.info(
            f"Fetching order book for {pair} with depth {depth} from Binance..."
        )
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched order book for {pair} from Binance.")

        bids = [[float(price), float(qty)] for price, qty in data["bids"]]
        asks = [[float(price), float(qty)] for price, qty in data["asks"]]

        return {"bids": bids, "asks": asks}

    def _normalize_interval(self, interval: str) -> str:
        """Converts a standard interval string to Binance's format."""
        mapping = {
            "1m": "1m",
            "5m": "5m",
            "1h": "1h",
            "1d": "1d",
        }
        if interval not in mapping:
            raise ValueError(
                f"Interval '{interval}' is not supported by this Binance implementation."
            )
        return mapping[interval]

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetches historical kline (candlestick) data from Binance.
        Endpoint: GET /api/v3/klines
        """
        symbol = self._normalize_pair(pair)
        normalized_interval = self._normalize_interval(interval)
        endpoint = f"{self.BASE_URL}/api/v3/klines"

        params = {
            "symbol": symbol,
            "interval": normalized_interval,
            "startTime": start_time * 1000,
            "endTime": end_time * 1000,
            "limit": 1000,
        }
        self.logger.info(f"Fetching klines for {pair} from Binance...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched klines for {pair} from Binance.")

        klines = []
        for kline in data:
            klines.append(
                [
                    int(kline[0] / 1000),
                    float(kline[1]),
                    float(kline[2]),
                    float(kline[3]),
                    float(kline[4]),
                    float(kline[5]),
                ]
            )
        return klines

    def get_account_balances(self) -> Dict[str, float]:
        raise NotImplementedError(
            "Binance get_account_balances not yet implemented (requires authentication/signing)."
        )

    def get_open_orders(self, pair: str = None) -> List[dict]:
        raise NotImplementedError(
            "Binance get_open_orders not yet implemented (requires authentication/signing)."
        )

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        raise NotImplementedError(
            "Binance place_limit_order not yet implemented (requires authentication/signing)."
        )

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        raise NotImplementedError(
            "Binance place_market_order not yet implemented (requires authentication/signing)."
        )

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        raise NotImplementedError(
            "Binance cancel_order not yet implemented (requires authentication/signing)."
        )
