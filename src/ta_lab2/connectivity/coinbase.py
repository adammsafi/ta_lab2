# src/ta_lab2/connectivity/coinbase.py
"""
Coinbase Advanced Trade API adapter.

Authentication uses JWT ES256 signed with an EC private key (CDP format).
Every authenticated request includes a fresh JWT in the Authorization header.

API reference: https://docs.cdp.coinbase.com/advanced-trade/reference
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, List

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.backends import default_backend

from .base import ExchangeInterface
from .exchange_config import ExchangeConfig
from .exceptions import AuthenticationError
from .decorators import handle_api_errors


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

BASE_HOST = "api.coinbase.com"
SANDBOX_HOST = "api-sandbox.coinbase.com"


class CoinbaseExchange(ExchangeInterface):
    """
    Coinbase Advanced Trade API adapter.

    Parameters
    ----------
    api_key : str, optional
        CDP API key name (e.g. 'organizations/xxx/apiKeys/yyy').
        Required for authenticated endpoints.
    api_secret : str, optional
        EC private key in PEM format.
        Required for authenticated endpoints.
    config : ExchangeConfig, optional
        If provided, credentials and sandbox flag are loaded from config
        (api_key / api_secret from config fields, sandbox from config.is_sandbox).
        Direct api_key / api_secret arguments override config values when both
        are supplied.
    """

    def __init__(
        self,
        api_key: str = None,
        api_secret: str = None,
        config: ExchangeConfig = None,
        **kwargs,
    ):
        # Resolve credentials: config first, then direct args override
        resolved_key = api_key
        resolved_secret = api_secret
        sandbox = False

        if config is not None:
            if not resolved_key:
                resolved_key = config.api_key or None
            if not resolved_secret:
                resolved_secret = config.api_secret or None
            sandbox = config.is_sandbox

        super().__init__(resolved_key, resolved_secret, **kwargs)
        self.config = config

        host = SANDBOX_HOST if sandbox else BASE_HOST
        self.base_url = f"https://{host}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_pair(self, pair: str) -> str:
        """Convert 'BTC/USD' → 'BTC-USD' for Coinbase product IDs."""
        return pair.replace("/", "-").upper()

    def _build_jwt(self, method: str, path: str) -> str:
        """
        Build a fresh ES256 JWT for a single request.

        Parameters
        ----------
        method : str  HTTP verb in uppercase, e.g. 'GET', 'POST'.
        path   : str  URL path including query string, e.g. '/api/v3/brokerage/accounts'.

        Returns
        -------
        str  Compact-serialised JWT token.

        Raises
        ------
        AuthenticationError
            When api_key or api_secret are missing / invalid PEM.
        """
        if not self.api_key or not self.api_secret:
            raise AuthenticationError(
                "CoinbaseExchange: api_key and api_secret are required for "
                "authenticated requests. Provide them directly or via ExchangeConfig."
            )

        now = int(time.time())
        uri = f"{method.upper()} {BASE_HOST}{path}"

        payload = {
            "sub": self.api_key,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,  # 2-minute window
            "uri": uri,
        }

        headers = {
            "kid": self.api_key,
            "nonce": uuid.uuid4().hex,
        }

        try:
            pem_bytes = (
                self.api_secret.encode("utf-8")
                if isinstance(self.api_secret, str)
                else self.api_secret
            )
            private_key = load_pem_private_key(
                pem_bytes, password=None, backend=default_backend()
            )
        except Exception as exc:
            raise AuthenticationError(
                f"CoinbaseExchange: failed to load EC private key from api_secret: {exc}"
            ) from exc

        token: str = jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers=headers,
        )
        return token

    def _authenticated_request(self, method: str, path: str, data: dict = None):
        """
        Execute an authenticated HTTP request with a fresh Bearer JWT.

        Parameters
        ----------
        method : str   HTTP verb.
        path   : str   URL path (no host).
        data   : dict  JSON body for POST/DELETE requests (optional).

        Returns
        -------
        dict  Parsed JSON response body.
        """
        token = self._build_jwt(method, path)
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.logger.debug(f"Request: {method} {url}")

        if method.upper() == "GET":
            response = self.session.get(url, headers=headers)
        elif method.upper() == "POST":
            response = self.session.post(url, headers=headers, json=data or {})
        elif method.upper() == "DELETE":
            response = self.session.delete(url, headers=headers, json=data or {})
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # Interval helpers
    # ------------------------------------------------------------------

    def _normalize_interval(self, interval: str) -> str:
        """Convert generic interval string to Coinbase Advanced Trade granularity name."""
        mapping = {
            "1m": "ONE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE",
            "1h": "ONE_HOUR",
            "2h": "TWO_HOUR",
            "6h": "SIX_HOUR",
            "1d": "ONE_DAY",
        }
        if interval not in mapping:
            raise ValueError(
                f"Interval '{interval}' is not supported by the Coinbase Advanced Trade API. "
                f"Supported: {list(mapping.keys())}"
            )
        return mapping[interval]

    # ------------------------------------------------------------------
    # Public market-data endpoints
    # ------------------------------------------------------------------

    @handle_api_errors
    def get_ticker(self, pair: str) -> Dict[str, float]:
        """
        Fetch the latest trade price for a product.

        Endpoint: GET /api/v3/brokerage/products/{product_id}/ticker
        Authentication: not required (public endpoint).
        """
        product_id = self._normalize_pair(pair)
        path = f"/api/v3/brokerage/products/{product_id}/ticker"
        url = f"{self.base_url}{path}"
        self.logger.info(f"Fetching ticker for {pair} from Coinbase Advanced Trade...")
        self.logger.debug(f"Request: GET {url}")

        response = self.session.get(url)
        response.raise_for_status()
        data = response.json()

        # Response contains 'trades' list and 'best_bid' / 'best_ask'
        trades = data.get("trades") or []
        last_price = (
            float(trades[0]["price"]) if trades else float(data.get("best_bid", 0))
        )
        self.logger.info(f"Ticker for {pair}: {last_price}")
        return {"last_price": last_price}

    @handle_api_errors
    def get_order_book(
        self, pair: str, depth: int = 10
    ) -> Dict[str, List[List[float]]]:
        """
        Fetch the current order book for a product.

        Endpoint: GET /api/v3/brokerage/products/{product_id}/book
        Authentication: not required (public endpoint).
        """
        product_id = self._normalize_pair(pair)
        path = f"/api/v3/brokerage/products/{product_id}/book"
        url = f"{self.base_url}{path}"
        params = {"limit": depth}
        self.logger.info(
            f"Fetching order book for {pair} (depth={depth}) from Coinbase..."
        )
        self.logger.debug(f"Request: GET {url} params={params}")

        response = self.session.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        pricebook = data.get("pricebook", {})
        bids_raw = pricebook.get("bids", [])
        asks_raw = pricebook.get("asks", [])

        bids = [[float(entry["price"]), float(entry["size"])] for entry in bids_raw]
        asks = [[float(entry["price"]), float(entry["size"])] for entry in asks_raw]
        return {"bids": bids, "asks": asks}

    @handle_api_errors
    def get_historical_klines(
        self, pair: str, interval: str, start_time: int, end_time: int
    ) -> List[list]:
        """
        Fetch historical OHLCV candles.

        Endpoint: GET /api/v3/brokerage/products/{product_id}/candles
        Authentication: not required (public endpoint).

        Returns list of [timestamp_s, open, high, low, close, volume].
        """
        product_id = self._normalize_pair(pair)
        granularity = self._normalize_interval(interval)
        path = f"/api/v3/brokerage/products/{product_id}/candles"
        url = f"{self.base_url}{path}"

        params = {
            "start": str(start_time),
            "end": str(end_time),
            "granularity": granularity,
        }
        self.logger.info(f"Fetching klines for {pair} ({interval}) from Coinbase...")
        self.logger.debug(f"Request: GET {url} params={params}")

        response = self.session.get(url, params=params)
        response.raise_for_status()
        data = response.json()

        candles_raw = data.get("candles", [])
        klines = []
        for c in candles_raw:
            klines.append(
                [
                    int(c["start"]),
                    float(c["open"]),
                    float(c["high"]),
                    float(c["low"]),
                    float(c["close"]),
                    float(c["volume"]),
                ]
            )
        # Coinbase returns most-recent first; reverse to chronological order
        return klines[::-1]

    # ------------------------------------------------------------------
    # Authenticated account endpoints
    # ------------------------------------------------------------------

    @handle_api_errors
    def get_account_balances(self) -> Dict[str, float]:
        """
        Fetch available balances for all accounts.

        Endpoint: GET /api/v3/brokerage/accounts
        Returns dict of {currency: available_balance}.
        """
        path = "/api/v3/brokerage/accounts"
        self.logger.info("Fetching account balances from Coinbase...")
        data = self._authenticated_request("GET", path)

        accounts = data.get("accounts", [])
        balances: Dict[str, float] = {}
        for account in accounts:
            currency = account.get("currency", "")
            available = account.get("available_balance", {}).get("value", "0")
            if currency:
                balances[currency] = float(available)
        self.logger.info(f"Retrieved balances for {len(balances)} currencies.")
        return balances

    @handle_api_errors
    def get_open_orders(self, pair: str = None) -> List[dict]:
        """
        Fetch open orders, optionally filtered by product.

        Endpoint: GET /api/v3/brokerage/orders/historical/batch
        """
        path = "/api/v3/brokerage/orders/historical/batch"
        self.logger.info(f"Fetching open orders from Coinbase (pair={pair})...")
        data = self._authenticated_request("GET", path)

        orders = data.get("orders", [])
        if pair:
            product_id = self._normalize_pair(pair)
            orders = [o for o in orders if o.get("product_id") == product_id]

        result = []
        for o in orders:
            result.append(
                {
                    "order_id": o.get("order_id", ""),
                    "product_id": o.get("product_id", ""),
                    "side": o.get("side", "").lower(),
                    "status": o.get("status", ""),
                    "order_type": o.get("order_type", ""),
                }
            )
        self.logger.info(f"Found {len(result)} open orders.")
        return result

    @handle_api_errors
    def place_market_order(self, pair: str, side: str, amount: float) -> Dict[str, str]:
        """
        Place an immediate-or-cancel market order (market_market_ioc).

        Endpoint: POST /api/v3/brokerage/orders

        Parameters
        ----------
        pair   : str   Trading pair, e.g. 'BTC/USD'.
        side   : str   'buy' or 'sell'.
        amount : float Quote size for buys (USD amount) or base size for sells.

        Returns
        -------
        dict with order_id and status.
        """
        product_id = self._normalize_pair(pair)
        side_upper = side.strip().upper()
        if side_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side '{side}'. Must be 'buy' or 'sell'.")

        client_order_id = uuid.uuid4().hex

        # market_market_ioc: quote_size for BUY, base_size for SELL
        if side_upper == "BUY":
            order_config = {"market_market_ioc": {"quote_size": str(amount)}}
        else:
            order_config = {"market_market_ioc": {"base_size": str(amount)}}

        body = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side_upper,
            "order_configuration": order_config,
        }

        path = "/api/v3/brokerage/orders"
        self.logger.info(f"Placing market order: {side_upper} {amount} {product_id}")
        data = self._authenticated_request("POST", path, data=body)

        success_response = data.get("success_response", {})
        order_id = success_response.get("order_id", "")
        status = "filled" if data.get("success") else "failed"
        self.logger.info(f"Market order placed: order_id={order_id}, status={status}")
        return {"order_id": order_id, "status": status}

    @handle_api_errors
    def place_limit_order(
        self, pair: str, side: str, price: float, amount: float
    ) -> Dict[str, str]:
        """
        Place a good-till-cancelled limit order (limit_limit_gtc).

        Endpoint: POST /api/v3/brokerage/orders

        Parameters
        ----------
        pair   : str   Trading pair, e.g. 'BTC/USD'.
        side   : str   'buy' or 'sell'.
        price  : float Limit price in quote currency.
        amount : float Base size (amount of base asset to buy/sell).

        Returns
        -------
        dict with order_id and status.
        """
        product_id = self._normalize_pair(pair)
        side_upper = side.strip().upper()
        if side_upper not in ("BUY", "SELL"):
            raise ValueError(f"Invalid side '{side}'. Must be 'buy' or 'sell'.")

        client_order_id = uuid.uuid4().hex

        body = {
            "client_order_id": client_order_id,
            "product_id": product_id,
            "side": side_upper,
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": str(amount),
                    "limit_price": str(price),
                    "post_only": False,
                }
            },
        }

        path = "/api/v3/brokerage/orders"
        self.logger.info(
            f"Placing limit order: {side_upper} {amount} {product_id} @ {price}"
        )
        data = self._authenticated_request("POST", path, data=body)

        success_response = data.get("success_response", {})
        order_id = success_response.get("order_id", "")
        status = "open" if data.get("success") else "failed"
        self.logger.info(f"Limit order placed: order_id={order_id}, status={status}")
        return {"order_id": order_id, "status": status}

    @handle_api_errors
    def cancel_order(self, order_id: str) -> Dict[str, str]:
        """
        Cancel an open order by ID.

        Endpoint: POST /api/v3/brokerage/orders/batch_cancel

        The API requires order_ids to be wrapped in an array.

        Returns
        -------
        dict with order_id and status ('cancelled' or 'failed').
        """
        path = "/api/v3/brokerage/orders/batch_cancel"
        body = {"order_ids": [order_id]}
        self.logger.info(f"Cancelling order: {order_id}")
        data = self._authenticated_request("POST", path, data=body)

        results = data.get("results", [])
        if results:
            first = results[0]
            cancelled = first.get("success", False)
            status = "cancelled" if cancelled else "failed"
        else:
            status = "failed"

        self.logger.info(f"Cancel order result: order_id={order_id}, status={status}")
        return {"order_id": order_id, "status": status}
