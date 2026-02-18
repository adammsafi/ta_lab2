# src/ta_lab2/connectivity/coinbase.py

from .base import ExchangeInterface
from typing import Dict, List
from .decorators import handle_api_errors


class CoinbaseExchange(ExchangeInterface):
    BASE_URL = "https://api.exchange.coinbase.com"

    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        passphrase: str = None,
        **kwargs,
    ):
        super().__init__(api_key, api_secret, passphrase=passphrase, **kwargs)

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'BTC-USD' for Coinbase."""
        return pair.replace("/", "-").upper()

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        """
        Fetches the latest price for a given trading pair from Coinbase Exchange.
        Endpoint: GET /products/{product_id}/ticker
        """
        product_id = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/products/{product_id}/ticker"
        self.logger.info(f"Fetching ticker for {pair} from Coinbase...")
        self.logger.debug(f"Request: GET {endpoint}")

        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched ticker for {pair} from Coinbase.")
        return {"last_price": float(data["price"])}

    @handle_api_errors
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        """
        Fetches the current order book from Coinbase Exchange.
        Endpoint: GET /products/{product_id}/book
        """
        product_id = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/products/{product_id}/book"

        level = 2 if depth > 1 else 1
        params = {"level": level}
        self.logger.info(
            f"Fetching order book for {pair} with depth {depth} (level {level}) from Coinbase..."
        )
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched order book for {pair} from Coinbase.")

        bids = [[float(price), float(qty)] for price, qty, _ in data["bids"]]
        asks = [[float(price), float(qty)] for price, qty, _ in data["asks"]]

        if level == 1:
            bids = [bids[0]] if bids else []
            asks = [asks[0]] if asks else []

        return {"bids": bids, "asks": asks}

    def _normalize_interval(self, interval: str) -> int:
        """Converts a standard interval string to Coinbase's granularity in seconds."""
        mapping = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "6h": 21600,
            "1d": 86400,
        }
        if interval not in mapping:
            raise ValueError(
                f"Interval '{interval}' is not supported by this Coinbase implementation."
            )
        return mapping[interval]

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetches historical kline (candlestick) data from Coinbase Exchange.
        Endpoint: GET /products/{product_id}/candles
        """
        import datetime

        product_id = self._normalize_pair(pair)
        granularity = self._normalize_interval(interval)
        endpoint = f"{self.BASE_URL}/products/{product_id}/candles"

        params = {
            "granularity": granularity,
            "start": datetime.datetime.fromtimestamp(
                start_time, tz=datetime.timezone.utc
            ).isoformat(),
            "end": datetime.datetime.fromtimestamp(
                end_time, tz=datetime.timezone.utc
            ).isoformat(),
        }
        self.logger.info(f"Fetching klines for {pair} from Coinbase...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched klines for {pair} from Coinbase.")

        klines = []
        for kline in data:
            klines.append(
                [
                    int(kline[0]),
                    float(kline[3]),
                    float(kline[2]),
                    float(kline[1]),
                    float(kline[4]),
                    float(kline[5]),
                ]
            )
        return klines[::-1]

    def get_account_balances(self) -> Dict[str, float]:
        raise NotImplementedError(
            "Coinbase get_account_balances not yet implemented (requires authentication/signing)."
        )

    def get_open_orders(self, pair: str = None) -> List[dict]:
        raise NotImplementedError(
            "Coinbase get_open_orders not yet implemented (requires authentication/signing)."
        )

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        raise NotImplementedError(
            "Coinbase place_limit_order not yet implemented (requires authentication/signing)."
        )

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        raise NotImplementedError(
            "Coinbase place_market_order not yet implemented (requires authentication/signing)."
        )

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        raise NotImplementedError(
            "Coinbase cancel_order not yet implemented (requires authentication/signing)."
        )
