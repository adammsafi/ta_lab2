# src/ta_lab2/connectivity/bitstamp.py

from .base import ExchangeInterface
from typing import Dict, List
from .decorators import handle_api_errors


class BitstampExchange(ExchangeInterface):
    BASE_URL = "https://www.bitstamp.net/api/v2"

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        super().__init__(api_key, api_secret, **kwargs)

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'btcusd' for Bitstamp."""
        return pair.replace("/", "").lower()

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        """
        Fetches the latest price for a given trading pair from Bitstamp.
        Endpoint: GET /ticker/{market_symbol}/
        """
        market_symbol = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/ticker/{market_symbol}/"
        self.logger.info(f"Fetching ticker for {pair} from Bitstamp...")
        self.logger.debug(f"Request: GET {endpoint}")

        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched ticker for {pair} from Bitstamp.")
        return {"last_price": float(data["last"])}

    @handle_api_errors
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        """
        Fetches the current order book from Bitstamp.
        Endpoint: GET /order_book/{market_symbol}/
        """
        market_symbol = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/order_book/{market_symbol}/"
        self.logger.info(
            f"Fetching order book for {pair} with depth {depth} from Bitstamp..."
        )
        self.logger.debug(f"Request: GET {endpoint}")

        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched order book for {pair} from Bitstamp.")

        bids = [[float(price), float(qty)] for price, qty in data["bids"]]
        asks = [[float(price), float(qty)] for price, qty in data["asks"]]

        return {"bids": bids[:depth], "asks": asks[:depth]}

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetches historical kline (candlestick) data from Bitstamp.
        Endpoint: GET /ohlc/{market_symbol}/
        """
        market_symbol = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/ohlc/{market_symbol}/"

        interval_map = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
            "6h": 21600,
            "12h": 43200,
            "1d": 86400,
        }
        if interval not in interval_map:
            raise ValueError(
                f"Interval '{interval}' is not supported by this Bitstamp implementation."
            )
        step = interval_map[interval]

        params = {"step": step, "limit": 1000}
        self.logger.info(f"Fetching klines for {pair} from Bitstamp...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()["data"]["ohlc"]
        self.logger.info(f"Successfully fetched klines for {pair} from Bitstamp.")

        klines = []
        for kline in data:
            ts = int(kline["timestamp"])
            if start_time <= ts <= end_time:
                klines.append(
                    [
                        ts,
                        float(kline["open"]),
                        float(kline["high"]),
                        float(kline["low"]),
                        float(kline["close"]),
                        float(kline["volume"]),
                    ]
                )
        return klines[::-1]

    def get_account_balances(self) -> Dict[str, float]:
        raise NotImplementedError("Bitstamp get_account_balances not yet implemented.")

    def get_open_orders(self, pair: str = None) -> List[dict]:
        raise NotImplementedError("Bitstamp get_open_orders not yet implemented.")

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        raise NotImplementedError("Bitstamp place_limit_order not yet implemented.")

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        raise NotImplementedError("Bitstamp place_market_order not yet implemented.")

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        raise NotImplementedError("Bitstamp cancel_order not yet implemented.")
