# src/ta_lab2/connectivity/kraken.py

import base64
import hashlib
import hmac
import time
import urllib.parse
from typing import Dict, List

from .base import ExchangeInterface
from .decorators import handle_api_errors
from .exceptions import AuthenticationError, InvalidRequestError
from .exchange_config import ExchangeConfig


class KrakenExchange(ExchangeInterface):
    PUBLIC_URL = "https://api.kraken.com/0/public"
    PRIVATE_URL = "https://api.kraken.com/0/private"
    # Keep BASE_URL for backward compatibility with existing public methods
    BASE_URL = "https://api.kraken.com/0/public"

    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        config: ExchangeConfig = None,
        **kwargs,
    ):
        # If an ExchangeConfig is provided, prefer its credentials
        if config is not None:
            api_key = config.api_key or api_key
            api_secret = config.api_secret or api_secret
        super().__init__(api_key, api_secret, **kwargs)

    # ------------------------------------------------------------------ #
    # Private auth helpers                                                 #
    # ------------------------------------------------------------------ #

    def _requires_auth(self) -> None:
        """Raise AuthenticationError when credentials are absent."""
        if not self.api_key or not self.api_secret:
            raise AuthenticationError(
                "Kraken authenticated endpoint requires api_key and api_secret. "
                "Provide them directly or via ExchangeConfig."
            )

    def _sign(self, urlpath: str, data: dict) -> str:
        """
        Compute the Kraken HMAC-SHA512 signature for a private request.

        Algorithm (per Kraken REST API docs):
          1. Concatenate: nonce (as string) + urlencode(data)
          2. Hash that string with SHA-256
          3. Prepend the raw urlpath bytes
          4. HMAC the result with the base64-decoded API secret using SHA-512
          5. Return the result base64-encoded
        """
        encoded = (str(data["nonce"]) + urllib.parse.urlencode(data)).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        mac = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    def _private_post(self, endpoint: str, data: dict = None) -> dict:
        """
        POST to a Kraken private endpoint with HMAC-SHA512 authentication.

        Parameters
        ----------
        endpoint : str
            The endpoint name without path prefix, e.g. 'Balance', 'AddOrder'.
        data : dict, optional
            Additional POST parameters. A nonce will be injected automatically.

        Returns
        -------
        dict
            The ``result`` field from the Kraken JSON response.

        Raises
        ------
        AuthenticationError
            When no credentials are present.
        InvalidRequestError
            When the Kraken response contains a non-empty ``error`` list.
        """
        self._requires_auth()
        if data is None:
            data = {}

        # Millisecond-resolution nonce (monotonically increasing within a session)
        data["nonce"] = str(int(time.time() * 1000))

        urlpath = f"/0/private/{endpoint}"
        signature = self._sign(urlpath, data)

        headers = {
            "API-Key": self.api_key,
            "API-Sign": signature,
        }

        url = f"https://api.kraken.com{urlpath}"
        self.logger.debug(f"POST {url} data={list(data.keys())}")

        response = self.session.post(url, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()

        if result.get("error"):
            raise InvalidRequestError(f"Kraken error: {result['error']}")

        return result["result"]

    # ------------------------------------------------------------------ #
    # Pair normalization helper (existing — unchanged)                     #
    # ------------------------------------------------------------------ #

    def _normalize_pair(self, pair: str) -> str:
        """Converts 'BTC/USD' to 'XBTUSD' for Kraken."""
        pair = pair.replace("BTC", "XBT")
        return pair.replace("/", "").upper()

    # ------------------------------------------------------------------ #
    # Public endpoints (existing — unchanged)                             #
    # ------------------------------------------------------------------ #

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

    # ------------------------------------------------------------------ #
    # Private endpoints (authenticated)                                   #
    # ------------------------------------------------------------------ #

    def get_account_balances(self) -> Dict[str, float]:
        """
        Return non-zero balances for the authenticated account.

        Returns
        -------
        dict
            ``{asset: balance}`` mapping, e.g. ``{"XXBT": 0.5, "ZUSD": 1000.0}``.
            Assets with a zero balance are excluded.

        Raises
        ------
        AuthenticationError
            When no credentials are configured.
        """
        result = self._private_post("Balance")
        return {
            asset: float(balance)
            for asset, balance in result.items()
            if float(balance) > 0
        }

    def get_open_orders(self, pair: str = None) -> List[dict]:
        """
        Return a list of open orders for the authenticated account.

        Parameters
        ----------
        pair : str, optional
            If provided, only orders for this pair are returned (normalised
            via ``_normalize_pair``).

        Returns
        -------
        list of dict
            Each dict contains: order_id, pair, side, ordertype, volume,
            price, status.

        Raises
        ------
        AuthenticationError
            When no credentials are configured.
        """
        result = self._private_post("OpenOrders")
        open_orders = result.get("open", {})

        normalized_filter = self._normalize_pair(pair) if pair else None
        orders = []
        for txid, order_data in open_orders.items():
            descr = order_data.get("descr", {})
            order = {
                "order_id": txid,
                "pair": descr.get("pair", ""),
                "side": descr.get("type", ""),
                "ordertype": descr.get("ordertype", ""),
                "volume": order_data.get("vol", ""),
                "price": descr.get("price", ""),
                "status": order_data.get("status", ""),
            }
            if normalized_filter is None or order["pair"] == normalized_filter:
                orders.append(order)
        return orders

    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        """
        Submit a market order.

        Parameters
        ----------
        pair : str
            Trading pair, e.g. ``'BTC/USD'``.
        side : str
            ``'buy'`` or ``'sell'``.
        amount : float
            Order volume in base currency.

        Returns
        -------
        dict
            ``{"order_id": "<txid>", "status": "submitted"}``

        Raises
        ------
        AuthenticationError
            When no credentials are configured.
        InvalidRequestError
            When Kraken rejects the order.
        """
        data = {
            "pair": self._normalize_pair(pair),
            "type": side.lower(),
            "ordertype": "market",
            "volume": str(amount),
        }
        result = self._private_post("AddOrder", data)
        return {"order_id": result["txid"][0], "status": "submitted"}

    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        """
        Submit a limit order.

        Parameters
        ----------
        pair : str
            Trading pair, e.g. ``'BTC/USD'``.
        side : str
            ``'buy'`` or ``'sell'``.
        price : float
            Limit price in quote currency.
        amount : float
            Order volume in base currency.

        Returns
        -------
        dict
            ``{"order_id": "<txid>", "status": "submitted"}``

        Raises
        ------
        AuthenticationError
            When no credentials are configured.
        InvalidRequestError
            When Kraken rejects the order.
        """
        data = {
            "pair": self._normalize_pair(pair),
            "type": side.lower(),
            "ordertype": "limit",
            "price": str(price),
            "volume": str(amount),
        }
        result = self._private_post("AddOrder", data)
        return {"order_id": result["txid"][0], "status": "submitted"}

    def cancel_order(self, order_id: str) -> Dict[str, str]:
        """
        Cancel an open order by transaction ID.

        Parameters
        ----------
        order_id : str
            Kraken transaction ID (txid) of the order to cancel.

        Returns
        -------
        dict
            ``{"order_id": "<txid>", "status": "cancelled"}``

        Raises
        ------
        AuthenticationError
            When no credentials are configured.
        InvalidRequestError
            When Kraken cannot find or cancel the order.
        """
        data = {"txid": order_id}
        self._private_post("CancelOrder", data)
        return {"order_id": order_id, "status": "cancelled"}
