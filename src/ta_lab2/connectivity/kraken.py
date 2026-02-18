# src/ta_lab2/connectivity/kraken.py

from .base import ExchangeInterface
from typing import Dict, List
from .decorators import handle_api_errors


class KrakenExchange(ExchangeInterface):
    BASE_URL = "https://api.kraken.com/0/public"

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        super().__init__(api_key, api_secret, **kwargs)

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'XBTUSD' for Kraken."""
        pair = pair.replace("BTC", "XBT")
        return pair.replace("/", "").upper()

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        """
        Fetches the latest price for a given trading pair from Kraken.
        Endpoint: GET /Ticker
        """
        kraken_pair = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/Ticker"
        params = {"pair": kraken_pair}
        self.logger.info(f"Fetching ticker for {pair} from Kraken...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()

        if data["error"]:
            self.logger.error(
                f"Kraken API error while fetching ticker for {pair}: {data['error']}"
            )
            raise ConnectionError(f"Kraken API error: {data['error']}")

        self.logger.info(f"Successfully fetched ticker for {pair} from Kraken.")
        result_pair = list(data["result"].keys())[0]
        last_price = float(data["result"][result_pair]["c"][0])

        return {"last_price": last_price}

    @handle_api_errors
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        """
        Fetches the current order book from Kraken.
        Endpoint: GET /Depth
        """
        kraken_pair = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/Depth"
        params = {"pair": kraken_pair, "count": depth}
        self.logger.info(
            f"Fetching order book for {pair} with depth {depth} from Kraken..."
        )
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()

        if data["error"]:
            self.logger.error(
                f"Kraken API error while fetching order book for {pair}: {data['error']}"
            )
            raise ConnectionError(f"Kraken API error: {data['error']}")

        self.logger.info(f"Successfully fetched order book for {pair} from Kraken.")
        result_pair = list(data["result"].keys())[0]
        bids = [
            [float(price), float(qty)]
            for price, qty, _ in data["result"][result_pair]["bids"]
        ]
        asks = [
            [float(price), float(qty)]
            for price, qty, _ in data["result"][result_pair]["asks"]
        ]

        return {"bids": bids, "asks": asks}

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetches historical kline (candlestick) data from Kraken.
        Endpoint: GET /OHLC
        """
        kraken_pair = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/OHLC"

        interval_map = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        if interval not in interval_map:
            raise ValueError(
                f"Interval '{interval}' is not supported by this Kraken implementation."
            )
        kraken_interval = interval_map[interval]

        params = {"pair": kraken_pair, "interval": kraken_interval, "since": start_time}
        self.logger.info(f"Fetching klines for {pair} from Kraken...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()

        if data["error"]:
            self.logger.error(
                f"Kraken API error while fetching klines for {pair}: {data['error']}"
            )
            raise ConnectionError(f"Kraken API error: {data['error']}")

        self.logger.info(f"Successfully fetched klines for {pair} from Kraken.")
        result_pair = list(data["result"].keys())[0]
        klines = []
        for kline in data["result"][result_pair]:
            ts = int(kline[0])
            if ts <= end_time:
                klines.append(
                    [
                        ts,
                        float(kline[1]),
                        float(kline[2]),
                        float(kline[3]),
                        float(kline[4]),
                        float(kline[6]),
                    ]
                )
        return klines

    def get_account_balances(self) -> Dict[str, float]:
        raise NotImplementedError("Kraken get_account_balances not yet implemented.")

    def get_open_orders(self, pair: str = None) -> List[dict]:
        raise NotImplementedError("Kraken get_open_orders not yet implemented.")

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        raise NotImplementedError("Kraken place_limit_order not yet implemented.")

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        raise NotImplementedError("Kraken place_market_order not yet implemented.")

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        raise NotImplementedError("Kraken cancel_order not yet implemented.")
