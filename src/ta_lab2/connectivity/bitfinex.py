# src/ta_lab2/connectivity/bitfinex.py

from .base import ExchangeInterface
from typing import Dict, List
from .decorators import handle_api_errors


class BitfinexExchange(ExchangeInterface):
    BASE_URL = "https://api-pub.bitfinex.com/v2"

    def __init__(self, api_key: str = None, api_secret: str = None, **kwargs):
        super().__init__(api_key, api_secret, **kwargs)

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'tBTCUSD' for Bitfinex."""
        return f"t{pair.replace('/', '').upper()}"

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        """
        Fetches the latest price for a given trading pair from Bitfinex.
        Endpoint: GET /ticker/{symbol}
        """
        symbol = self._normalize_pair(pair)
        endpoint = f"{self.BASE_URL}/ticker/{symbol}"
        self.logger.info(f"Fetching ticker for {pair} from Bitfinex...")
        self.logger.debug(f"Request: GET {endpoint}")

        response = self.session.get(endpoint)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched ticker for {pair} from Bitfinex.")
        return {"last_price": float(data[6])}

    @handle_api_errors
    def get_order_book(self, pair: str, depth: int) -> Dict[str, List[List[float]]]:
        """
        Fetches the current order book from Bitfinex.
        Endpoint: GET /book/{symbol}/{precision}
        """
        symbol = self._normalize_pair(pair)
        precision = "P0"
        endpoint = f"{self.BASE_URL}/book/{symbol}/{precision}"

        if depth <= 1:
            length = "1"
        elif depth <= 25:
            length = "25"
        else:
            length = "100"
        params = {"len": length}
        self.logger.info(
            f"Fetching order book for {pair} with depth {depth} from Bitfinex..."
        )
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched order book for {pair} from Bitfinex.")

        bids = []
        asks = []
        for item in data:
            price, _, amount = item
            if amount > 0:
                bids.append([float(price), float(amount)])
            else:
                asks.append([float(price), abs(float(amount))])

        return {"bids": bids, "asks": asks}

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetches historical kline (candlestick) data from Bitfinex.
        Endpoint: GET /candles/trade:{timeframe}:{symbol}/{section}
        """
        symbol = self._normalize_pair(pair)
        timeframe = interval
        section = "hist"
        endpoint = f"{self.BASE_URL}/candles/trade:{timeframe}:{symbol}/{section}"

        params = {
            "start": start_time * 1000,
            "end": end_time * 1000,
            "sort": -1,
            "limit": 10000,
        }
        self.logger.info(f"Fetching klines for {pair} from Bitfinex...")
        self.logger.debug(f"Request: GET {endpoint} with params {params}")

        response = self.session.get(endpoint, params=params)
        response.raise_for_status()
        data = response.json()
        self.logger.info(f"Successfully fetched klines for {pair} from Bitfinex.")

        klines = []
        for kline in data:
            klines.append(
                [
                    int(kline[0] / 1000),
                    float(kline[1]),
                    float(kline[3]),
                    float(kline[4]),
                    float(kline[2]),
                    float(kline[5]),
                ]
            )
        return klines

    def get_account_balances(self) -> Dict[str, float]:
        raise NotImplementedError("Bitfinex get_account_balances not yet implemented.")

    def get_open_orders(self, pair: str = None) -> List[dict]:
        raise NotImplementedError("Bitfinex get_open_orders not yet implemented.")

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        raise NotImplementedError("Bitfinex place_limit_order not yet implemented.")

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        raise NotImplementedError("Bitfinex place_market_order not yet implemented.")

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        raise NotImplementedError("Bitfinex cancel_order not yet implemented.")
