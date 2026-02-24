# Phase 43: Exchange Integration - Research

**Researched:** 2026-02-24
**Domain:** Exchange API authentication, paper order adapter, price feed comparison
**Confidence:** HIGH (API specifications), MEDIUM (patterns), LOW (testnet details for Kraken spot)

---

## Summary

Phase 43 extends the existing `src/ta_lab2/connectivity/` module with full authenticated access for Coinbase Advanced Trade API and Kraken Spot REST API. The primary work is implementing HMAC/JWT signing for private endpoints, an ExchangeConfig dataclass, a canonical paper order format, and a new `exchange_price_feed` table.

**Critical discovery:** The existing `coinbase.py` uses the OLD Coinbase Pro API base URL (`https://api.exchange.coinbase.com`). The current Coinbase Advanced Trade API uses `https://api.coinbase.com/api/v3/brokerage`. These are entirely different authentication mechanisms (Pro used HMAC-SHA256 + passphrase; Advanced Trade uses JWT with ES256/ECDSA). The `passphrase` field in the existing constructor is a Pro-API artifact — it is NOT used by the Advanced Trade API.

**Primary recommendation:** Rewrite the Coinbase adapter to use the Advanced Trade API base URL and JWT authentication. Keep the `passphrase` param in `__init__` as an ignored kwarg for backward compatibility if desired, but do not use it in signing logic.

---

## Standard Stack

### Core — No New External Dependencies Required

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `PyJWT` | 2.10.1 | Sign Coinbase JWT tokens (ES256) | YES |
| `cryptography` | 46.0.3 | Load EC PEM private key for JWT | YES |
| `requests` | existing | HTTP for both exchanges | YES (via existing base.py) |
| `hashlib` / `hmac` / `base64` | stdlib | Kraken HMAC-SHA512 signing | YES (stdlib) |

No new packages need to be installed. Both `PyJWT` and `cryptography` are already present.

### Optional (NOT recommended for Phase 43)
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw requests + PyJWT | `coinbase-advanced-py` SDK (v1.8.2) | SDK wraps the REST client cleanly but adds a dependency and diverges from the project's custom adapter pattern. Avoid — keep signing inline in the adapter. |
| Raw requests + stdlib | `python-kraken-sdk` (v3.2.7, unofficial) | Third-party, unofficial, requires Python >=3.11. Not endorsed by Kraken. Unnecessary for our simple use case. |

**Installation (if ever needed):**
```bash
# Nothing to install — PyJWT and cryptography already present
pip install coinbase-advanced-py  # optional SDK, NOT recommended
pip install python-kraken-sdk     # optional unofficial SDK, NOT recommended
```

---

## Architecture Patterns

### Recommended Project Structure (additions only)

```
src/ta_lab2/connectivity/
├── base.py                  # ExchangeInterface ABC — no change
├── coinbase.py              # REWRITE: Advanced Trade API + JWT auth
├── kraken.py               # UPDATE: add HMAC-SHA512 + private endpoints
├── factory.py              # UPDATE: accept ExchangeConfig
├── exchange_config.py      # NEW: ExchangeConfig dataclass
├── decorators.py           # no change
├── exceptions.py           # no change
├── binance.py              # no auth change
├── bitfinex.py             # no auth change
├── bitstamp.py             # no auth change
└── hyperliquid.py          # no auth change

src/ta_lab2/paper_trading/
├── __init__.py             # NEW package
├── canonical_order.py      # NEW: CanonicalOrder dataclass + to_exchange()
└── paper_order_logger.py   # NEW: writes to paper_orders table

src/ta_lab2/scripts/exchange/
├── __init__.py             # NEW
└── refresh_exchange_price_feed.py  # NEW: price feed polling + comparison

sql/exchange/
├── 080_exchange_price_feed.sql  # NEW: DDL
└── 081_paper_orders.sql         # NEW: DDL
```

### Pattern 1: Coinbase Advanced Trade JWT Authentication

**What:** Every REST request to `api.coinbase.com/api/v3/brokerage/*` requires a fresh JWT signed with your EC private key. JWT expires after 2 minutes. Generate per-request.

**Authentication type:** ES256 (ECDSA with P-256) — NOT HMAC, NOT passphrase.

**Key format:** The `api_key` is a string like `organizations/{org_id}/apiKeys/{key_id}`. The `api_secret` is a PEM-encoded EC private key block.

**Required JWT claims:**

```python
# Source: https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication
# and https://github.com/coinbase/coinbase-advanced-py README

import time, secrets, jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

def _build_jwt(self, method: str, path: str) -> str:
    """Generate per-request JWT for Coinbase Advanced Trade API."""
    uri = f"{method} {self.BASE_HOST}{path}"
    private_key = load_pem_private_key(
        self.api_secret.encode("utf-8"),
        password=None
    )
    payload = {
        "sub": self.api_key,
        "iss": "cdp",
        "nbf": int(time.time()),
        "exp": int(time.time()) + 120,  # 2-minute expiry
        "uri": uri,
    }
    headers = {
        "kid": self.api_key,
        "nonce": secrets.token_hex(16),  # random per-request value
    }
    token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    return token
```

**Request header:**
```
Authorization: Bearer {jwt_token}
```

**Base URL (Advanced Trade API):**
```
https://api.coinbase.com
```

**Sandbox base URL:**
```
https://api-sandbox.coinbase.com
```

The sandbox returns the same response format as production but with static/pre-defined data. No real authentication required in sandbox (but format the request identically). Only Accounts and Orders endpoints are available in sandbox.

### Pattern 2: Kraken HMAC-SHA512 Authentication

**What:** Every POST request to `/0/private/*` requires HMAC-SHA512 signing with a nonce.

**Signature algorithm:**
```
API-Sign = HMAC-SHA512 of (URI_path + SHA256(nonce + POST_data)) using base64-decoded API secret
```

**Python implementation:**

```python
# Source: https://docs.kraken.com/api/docs/guides/spot-rest-auth/
import urllib.parse, hashlib, hmac, base64, time

def _sign_request(self, urlpath: str, data: dict) -> str:
    """Generate Kraken HMAC-SHA512 signature."""
    encoded = (str(data["nonce"]) + urllib.parse.urlencode(data)).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()

def _private_request(self, endpoint: str, data: dict = None) -> dict:
    """Make authenticated Kraken private API request."""
    urlpath = f"/0/private/{endpoint}"
    if data is None:
        data = {}
    data["nonce"] = str(int(time.time() * 1000))  # ms-resolution timestamp
    signature = self._sign_request(urlpath, data)
    headers = {
        "API-Key": self.api_key,
        "API-Sign": signature,
    }
    response = self.session.post(
        f"{self.PRIVATE_BASE_URL}/{endpoint}",
        headers=headers,
        data=data,
    )
    response.raise_for_status()
    result = response.json()
    if result.get("error"):
        raise InvalidRequestError(f"Kraken error: {result['error']}")
    return result["result"]
```

**Base URLs:**
```
Public:  https://api.kraken.com/0/public
Private: https://api.kraken.com/0/private
```

**Testnet status:** Kraken does NOT have a public testnet for Spot REST API. Only Futures has a demo environment (`demo-futures.kraken.com`). For Spot development, options are:
1. Use very small amounts on live API
2. Mock the private endpoints in tests (recommended for Phase 43)
3. Contact Kraken support for UAT access (institutional only)

### Pattern 3: ExchangeConfig Dataclass

```python
# Source: project pattern from refresh_utils.py dataclass approach
from dataclasses import dataclass, field
from typing import Literal, Optional

@dataclass
class ExchangeConfig:
    """Encapsulates venue + environment + credentials for one exchange."""
    venue: str                          # "coinbase" | "kraken" | ...
    environment: Literal["sandbox", "production"] = "sandbox"
    api_key: str = ""
    api_secret: str = ""
    passphrase: Optional[str] = None    # Legacy Pro field, not used for Advanced Trade
    env_file: Optional[str] = None      # Path to per-exchange .env file (e.g., "coinbase.env")

    def validate(self) -> None:
        """Raise ValueError if credentials are missing."""
        if not self.api_key:
            raise ValueError(f"api_key required for {self.venue}")
        if not self.api_secret:
            raise ValueError(f"api_secret required for {self.venue}")

    @classmethod
    def from_env_file(cls, venue: str, env_file: str, **kwargs) -> "ExchangeConfig":
        """Load credentials from per-exchange .env file."""
        # dotenv-style parsing — mirrors existing db_config.env pattern
        ...
```

**Factory integration:** Update `get_exchange(name, **credentials)` to also accept `config: ExchangeConfig = None`.

### Pattern 4: Canonical Order Format

The canonical order is the normalized representation. `.to_exchange(name)` serializes it to the exact payload that exchange expects.

```python
from dataclasses import dataclass, field
from typing import Literal, Optional
import uuid

@dataclass
class CanonicalOrder:
    """Normalized order representation — exchange-agnostic."""
    pair: str                               # "BTC/USD" (internal format)
    side: Literal["buy", "sell"]
    order_type: Literal["market", "limit", "stop"]
    quantity: float                         # base asset quantity (e.g., BTC)
    limit_price: Optional[float] = None     # required for limit/stop
    stop_price: Optional[float] = None      # required for stop
    client_order_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal_id: Optional[int] = None         # FK to dim_signals

    def to_exchange(self, exchange: str) -> dict:
        """
        Serialize to the exact JSON payload expected by the named exchange.
        Used for preview/logging — does NOT submit to live API.
        """
        if exchange == "coinbase":
            return self._to_coinbase()
        elif exchange == "kraken":
            return self._to_kraken()
        raise ValueError(f"Unknown exchange: {exchange}")

    def _to_coinbase(self) -> dict:
        """Coinbase Advanced Trade POST /api/v3/brokerage/orders format."""
        product_id = self.pair.replace("/", "-").upper()
        if self.order_type == "market":
            order_config = {
                "market_market_ioc": {
                    "base_size": str(self.quantity)
                }
            }
        elif self.order_type == "limit":
            order_config = {
                "limit_limit_gtc": {
                    "base_size": str(self.quantity),
                    "limit_price": str(self.limit_price),
                    "post_only": False,
                }
            }
        return {
            "client_order_id": self.client_order_id,
            "product_id": product_id,
            "side": self.side.upper(),   # "BUY" or "SELL"
            "order_configuration": order_config,
        }

    def _to_kraken(self) -> dict:
        """Kraken POST /0/private/AddOrder format."""
        pair = self.pair.replace("BTC", "XBT").replace("/", "").upper()
        payload = {
            "pair": pair,
            "type": self.side,           # "buy" or "sell"
            "ordertype": self.order_type,  # "market" or "limit"
            "volume": str(self.quantity),
        }
        if self.limit_price is not None:
            payload["price"] = str(self.limit_price)
        return payload
```

### Anti-Patterns to Avoid

- **Reusing the passphrase for Advanced Trade JWT:** The `passphrase` is a Coinbase Pro artifact. Advanced Trade JWT uses only `api_key` + `api_secret` (EC private key). Ignore passphrase in signing logic.
- **Reusing the old `api.exchange.coinbase.com` base URL:** That is Coinbase Exchange (institutional). The retail Advanced Trade API is `api.coinbase.com/api/v3/brokerage`.
- **Caching JWT tokens across requests:** JWT expires in 2 minutes and must include the `uri` claim (method + path). Generate fresh for every request.
- **Using Kraken nonce as a counter instead of timestamp:** Counter-based nonce fails if shared across processes or if the counter resets. Use `int(time.time() * 1000)`.
- **Calling Kraken private endpoints via GET:** All private endpoints are POST-only.
- **Treating Kraken `Balance` errors silently:** Kraken returns HTTP 200 with `{"error": [...], "result": {}}`. Always check `result["error"]` before accessing `result["result"]`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| EC key loading from PEM | Custom PEM parser | `cryptography.hazmat.primitives.serialization.load_pem_private_key` | PEM format has multiple variants; the library handles all of them |
| UUID generation for client_order_id | Custom random string | `str(uuid.uuid4())` | UUIDs are collision-resistant and exchange-standard |
| Nonce generation for Kraken | Custom counter | `int(time.time() * 1000)` | System time is monotonically increasing; counter breaks across processes |
| JWT token encoding | Custom JWT builder | `jwt.encode(..., algorithm="ES256")` via PyJWT (already installed) | JWT encoding is non-trivial and security-sensitive |
| Per-exchange .env file loading | Custom config file parser | `python-dotenv` or manual line parsing matching existing `_load_db_url_from_config()` pattern | Project already has a clean env file parsing pattern — replicate it |
| Adaptive threshold | Custom volatility calc | Query `cmc_asset_stats.std_ret_30` for `tf = '1D'` — already computed | Phase 41 already provides this |

**Key insight:** Both signing implementations are self-contained using stdlib + already-installed PyJWT/cryptography. Adding no new packages keeps the dependency surface minimal.

---

## Endpoint Map

### Coinbase Advanced Trade API (base: `https://api.coinbase.com`)

| Method | HTTP | Path | Notes |
|--------|------|------|-------|
| `get_account_balances` | GET | `/api/v3/brokerage/accounts` | Returns paginated accounts array; filter `available_balance` |
| `get_open_orders` | GET | `/api/v3/brokerage/orders/historical/batch` | Filter: `order_status=OPEN`, optionally `product_ids` |
| `place_market_order` | POST | `/api/v3/brokerage/orders` | Body: `market_market_ioc` config with `base_size` |
| `place_limit_order` | POST | `/api/v3/brokerage/orders` | Body: `limit_limit_gtc` config with `base_size` + `limit_price` |
| `cancel_order` | POST | `/api/v3/brokerage/orders/batch_cancel` | Body: `{"order_ids": [...]}`; returns per-order success/failure |
| `get_ticker` (existing) | GET | `/products/{product_id}/ticker` | WRONG URL — this is the Pro API. Must update to `/api/v3/brokerage/best_bid_ask?product_ids=BTC-USD` |

**Order response format (create):**
```json
{
  "success": true,
  "success_response": {
    "order_id": "string",
    "product_id": "BTC-USD",
    "side": "BUY",
    "client_order_id": "string"
  }
}
```

**Sandbox URL:** `https://api-sandbox.coinbase.com` — same paths, static responses, no auth required.

### Kraken Spot REST API (base: `https://api.kraken.com`)

| Method | HTTP | Path | Notes |
|--------|------|------|-------|
| `get_account_balances` | POST | `/0/private/Balance` | Returns `{"XXBT": "0.5", "ZUSD": "1000.0", ...}` |
| `get_open_orders` | POST | `/0/private/OpenOrders` | Optional `pair` filter; returns dict keyed by txid |
| `place_market_order` | POST | `/0/private/AddOrder` | `ordertype=market`, no `price` field |
| `place_limit_order` | POST | `/0/private/AddOrder` | `ordertype=limit`, `price=str(limit_price)` |
| `cancel_order` | POST | `/0/private/CancelOrder` | Body: `txid=order_id_string` |

**AddOrder request parameters:**
```python
{
    "pair": "XBTUSD",         # BTC renamed to XBT; BTC/USD -> XBTUSD
    "type": "buy",            # or "sell"
    "ordertype": "market",    # or "limit"
    "volume": "0.001",        # base asset quantity
    "price": "30000",         # limit only
    "nonce": "1234567890123"  # millisecond timestamp
}
```

**AddOrder response:**
```json
{
  "result": {
    "descr": {"order": "buy 0.001 XBTUSD @ limit 30000"},
    "txid": ["OXXXXXX-YYYYYY-ZZZZZZ"]
  },
  "error": []
}
```

---

## Common Pitfalls

### Pitfall 1: Coinbase Pro vs Advanced Trade URL Confusion

**What goes wrong:** Existing `coinbase.py` uses `https://api.exchange.coinbase.com` (Coinbase Pro/Exchange API), which was deprecated for retail users as of June 2024. The public endpoints still respond but authenticated endpoints will fail or require a different key type.

**Why it happens:** The adapter was written before the Pro API was sunset.

**How to avoid:** Replace `BASE_URL` with `https://api.coinbase.com` and update all authenticated endpoint paths to `/api/v3/brokerage/*`. Update existing `get_ticker` endpoint from `/products/{id}/ticker` (Pro) to `/api/v3/brokerage/best_bid_ask?product_ids={id}` (Advanced Trade).

**Warning signs:** HTTP 404 or 401 responses when calling authenticated endpoints with new CDP keys.

### Pitfall 2: Coinbase JWT Must Include the `uri` Claim

**What goes wrong:** Generating a generic JWT without the `uri` claim (method + host + path). Coinbase rejects it.

**Why it happens:** Standard JWT implementations don't include exchange-specific claims.

**How to avoid:** Always include `"uri": "{METHOD} api.coinbase.com{path}"` in the JWT payload and generate a new JWT for each unique request. The `nonce` header must also be unique per request.

### Pitfall 3: Kraken Nonce Ordering Violations

**What goes wrong:** Multiple concurrent requests with out-of-order nonces cause `EAPI:Invalid nonce` errors. Too many of these trigger temporary IP bans.

**Why it happens:** Parallel requests or nonce reuse.

**How to avoid:** For Phase 43 (sequential REST polling), use `int(time.time() * 1000)`. Do not share a single `KrakenExchange` instance across threads without locking. Kraken supports a "nonce window" configuration to tolerate minor reordering.

### Pitfall 4: Kraken Returns HTTP 200 on API Errors

**What goes wrong:** Code assumes HTTP 200 = success, skips checking `result["error"]`, silently proceeds with empty `result["result"]`.

**Why it happens:** Kraken wraps errors in the JSON body, not HTTP status codes.

**How to avoid:** After every Kraken private request, check `if response_json.get("error")` before accessing `result`. The existing error decorator catches HTTP-level errors but NOT Kraken application-level errors. The `_private_request` helper should handle this.

### Pitfall 5: Adaptive Threshold Graceful Degradation

**What goes wrong:** `cmc_asset_stats` may not have `std_ret_30` for a given asset if the asset is new or returns haven't been computed.

**Why it happens:** The stats table is populated by a separate refresh script.

**How to avoid:** Fall back to a hardcoded default threshold (e.g., 5% for BTC, 7% for ETH) when `std_ret_30` is NULL. Log which fallback path was taken.

### Pitfall 6: Kraken BTC Pair Naming

**What goes wrong:** Kraken uses `XBT` instead of `BTC`. `BTC-USD` (Coinbase) becomes `XBTUSD` (Kraken). ETH/USD becomes `ETHUSD`.

**Why it happens:** Kraken uses ISO 4217 currency code for Bitcoin (XBT).

**How to avoid:** The existing `_normalize_pair` in `kraken.py` already handles `BTC -> XBT`. Verify it also handles `ETH/USD -> ETHUSD` correctly (it does: replace `/` with `""`).

### Pitfall 7: Coinbase `order_ids` is an Array (batch cancel)

**What goes wrong:** Coinbase `cancel_order(order_id)` signature takes a single string, but the API endpoint `POST /batch_cancel` takes `{"order_ids": [...]}` (array). The per-order result is also a list, not a single boolean.

**How to avoid:** The adapter's `cancel_order(order_id)` method wraps the ID in a list: `{"order_ids": [order_id]}`. Parse the response `results[0].success`.

---

## Code Examples

### Coinbase: Full Authenticated Request Flow

```python
# Source: https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication
# and https://coinbase.github.io/coinbase-advanced-py/jwt_generator.html

import time, secrets, jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

class CoinbaseExchange(ExchangeInterface):
    BASE_HOST = "api.coinbase.com"
    BASE_URL = f"https://{BASE_HOST}"
    SANDBOX_URL = "https://api-sandbox.coinbase.com"

    def _build_jwt(self, method: str, path: str) -> str:
        private_key = load_pem_private_key(
            self.api_secret.encode("utf-8"),
            password=None,
        )
        uri = f"{method} {self.BASE_HOST}{path}"
        now = int(time.time())
        payload = {
            "sub": self.api_key,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": uri,
        }
        token = jwt.encode(
            payload,
            private_key,
            algorithm="ES256",
            headers={"kid": self.api_key, "nonce": secrets.token_hex(16)},
        )
        return token

    def _auth_headers(self, method: str, path: str) -> dict:
        return {"Authorization": f"Bearer {self._build_jwt(method, path)}"}

    def get_account_balances(self) -> dict[str, float]:
        path = "/api/v3/brokerage/accounts"
        headers = self._auth_headers("GET", path)
        resp = self.session.get(f"{self.BASE_URL}{path}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return {
            acc["currency"]: float(acc["available_balance"]["value"])
            for acc in data.get("accounts", [])
        }
```

### Kraken: Full Authenticated Request Flow

```python
# Source: https://docs.kraken.com/api/docs/guides/spot-rest-auth/

import urllib.parse, hashlib, hmac, base64, time

class KrakenExchange(ExchangeInterface):
    PUBLIC_BASE_URL = "https://api.kraken.com/0/public"
    PRIVATE_BASE_URL = "https://api.kraken.com/0/private"

    def _sign(self, urlpath: str, data: dict) -> str:
        encoded = (str(data["nonce"]) + urllib.parse.urlencode(data)).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()
        mac = hmac.new(base64.b64decode(self.api_secret), message, hashlib.sha512)
        return base64.b64encode(mac.digest()).decode()

    def _private_post(self, endpoint: str, data: dict = None) -> dict:
        if data is None:
            data = {}
        data["nonce"] = str(int(time.time() * 1000))
        urlpath = f"/0/private/{endpoint}"
        data["API-Sign"] = self._sign(urlpath, data)
        headers = {"API-Key": self.api_key, "API-Sign": data.pop("API-Sign")}
        resp = self.session.post(
            f"{self.PRIVATE_BASE_URL}/{endpoint}",
            headers=headers,
            data=data,
        )
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise InvalidRequestError(f"Kraken API error: {result['error']}")
        return result["result"]

    def get_account_balances(self) -> dict[str, float]:
        result = self._private_post("Balance")
        return {asset: float(bal) for asset, bal in result.items()}

    def place_limit_order(self, pair, side, price, amount) -> dict:
        kraken_pair = self._normalize_pair(pair)
        result = self._private_post("AddOrder", {
            "pair": kraken_pair,
            "type": side.lower(),
            "ordertype": "limit",
            "price": str(price),
            "volume": str(amount),
        })
        return {"order_id": result["txid"][0], "status": "submitted"}
```

### Paper Order Logger DDL

```sql
-- sql/exchange/081_paper_orders.sql
CREATE TABLE IF NOT EXISTS public.paper_orders (
    order_uuid      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Source
    signal_id       INTEGER NULL,           -- FK to dim_signals (nullable for manual orders)
    asset_id        INTEGER NULL,           -- FK to dim_assets

    -- Order details (canonical)
    exchange        TEXT NOT NULL,          -- 'coinbase' | 'kraken'
    pair            TEXT NOT NULL,          -- 'BTC/USD' | 'ETH/USD'
    side            TEXT NOT NULL,          -- 'buy' | 'sell'
    order_type      TEXT NOT NULL,          -- 'market' | 'limit' | 'stop'
    quantity        NUMERIC NOT NULL,       -- base asset quantity
    limit_price     NUMERIC NULL,           -- null for market orders
    stop_price      NUMERIC NULL,           -- null for non-stop orders

    -- Exchange-specific preview
    exchange_payload JSONB NULL,            -- result of .to_exchange(name) for audit

    -- Status
    status          TEXT NOT NULL DEFAULT 'paper',  -- always 'paper' in Phase 43
    environment     TEXT NOT NULL DEFAULT 'sandbox', -- 'sandbox' | 'production'
    client_order_id TEXT NULL,              -- UUID assigned at creation

    CONSTRAINT chk_side CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_order_type CHECK (order_type IN ('market', 'limit', 'stop')),
    CONSTRAINT chk_status CHECK (status IN ('paper', 'submitted', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_paper_orders_exchange
    ON public.paper_orders (exchange, pair, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_paper_orders_signal
    ON public.paper_orders (signal_id)
    WHERE signal_id IS NOT NULL;
```

### Price Feed Table DDL

```sql
-- sql/exchange/080_exchange_price_feed.sql
CREATE TABLE IF NOT EXISTS public.exchange_price_feed (
    feed_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Source
    exchange        TEXT NOT NULL,          -- 'coinbase' | 'kraken'
    pair            TEXT NOT NULL,          -- 'BTC/USD' | 'ETH/USD' (internal format)
    environment     TEXT NOT NULL DEFAULT 'production',

    -- Price snapshot
    bid             NUMERIC NULL,
    ask             NUMERIC NULL,
    mid             NUMERIC NULL,           -- (bid + ask) / 2
    last_price      NUMERIC NOT NULL,

    -- Comparison to DB bar data
    bar_close       NUMERIC NULL,           -- last known close from cmc_price_bars_multi_tf
    bar_ts          TIMESTAMPTZ NULL,       -- timestamp of that bar
    discrepancy_pct NUMERIC NULL,           -- abs((last_price - bar_close) / bar_close) * 100
    threshold_pct   NUMERIC NULL,           -- adaptive threshold used
    exceeds_threshold BOOLEAN NULL,         -- TRUE if discrepancy_pct > threshold_pct

    CONSTRAINT chk_exchange CHECK (exchange IN ('coinbase', 'kraken', 'binance', 'bitfinex', 'bitstamp'))
);

CREATE INDEX IF NOT EXISTS idx_exchange_price_feed_pair_ts
    ON public.exchange_price_feed (exchange, pair, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_exchange_price_feed_exceeds
    ON public.exchange_price_feed (exceeds_threshold, fetched_at DESC)
    WHERE exceeds_threshold = TRUE;
```

### Adaptive Threshold Query

```python
def get_adaptive_threshold(engine, asset_id: int, tf: str = "1D") -> float:
    """
    Return discrepancy threshold based on 30-bar return std dev.
    Falls back to 5.0% if cmc_asset_stats has no data.
    Source: cmc_asset_stats.std_ret_30 (Phase 41 output)
    """
    DEFAULTS = {"BTC": 5.0, "ETH": 7.0}
    DEFAULT_FALLBACK = 5.0

    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT std_ret_30
                FROM public.cmc_asset_stats
                WHERE id = :id AND tf = :tf
                ORDER BY ts DESC LIMIT 1
            """),
            {"id": asset_id, "tf": tf}
        ).fetchone()

    if row and row[0] is not None:
        # Convert daily std_ret (decimal) to pct threshold: 2x std dev as threshold
        return float(row[0]) * 100 * 2.0
    return DEFAULT_FALLBACK
```

### ExchangeConfig with .env file loading

```python
# Mirrors existing _load_db_url_from_config() pattern in refresh_utils.py
@classmethod
def from_env_file(cls, venue: str, env_file: str, **kwargs) -> "ExchangeConfig":
    creds = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                creds[k.strip()] = v.strip()
    prefix = venue.upper()
    return cls(
        venue=venue,
        api_key=creds.get(f"{prefix}_API_KEY", ""),
        api_secret=creds.get(f"{prefix}_API_SECRET", ""),
        passphrase=creds.get(f"{prefix}_API_PASSPHRASE"),
        **kwargs,
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Coinbase Pro API (`api.exchange.coinbase.com`) + HMAC-SHA256 + passphrase | Coinbase Advanced Trade API (`api.coinbase.com/api/v3/brokerage`) + JWT ES256 | Deprecated June 2024 | Must rewrite Coinbase auth from scratch |
| Coinbase Pro passphrase in constructor | No passphrase in Advanced Trade | 2024 | Existing `passphrase` kwarg in adapter is vestigial |
| Kraken: no change | HMAC-SHA512 with nonce — same as always | — | Kraken auth is stable and well-documented |

**Deprecated/outdated in codebase:**
- `CoinbaseExchange.BASE_URL = "https://api.exchange.coinbase.com"` — must change to `https://api.coinbase.com`
- Coinbase `get_ticker` path `/products/{product_id}/ticker` — Pro API path; Advanced Trade uses `/api/v3/brokerage/best_bid_ask`
- `passphrase` in Coinbase `__init__` — not used by Advanced Trade auth

---

## Open Questions

1. **Coinbase `get_ticker` endpoint migration**
   - What we know: Pro API endpoint was `/products/{id}/ticker`; Advanced Trade has `/api/v3/brokerage/best_bid_ask?product_ids={id}`
   - What's unclear: The existing Coinbase public `get_ticker` tests pass against Pro API. After base URL change, this path will break. Existing tests will need updating.
   - Recommendation: Update `get_ticker` in Coinbase adapter as part of Phase 43, even though auth isn't the primary goal for public endpoints.

2. **Credential validation endpoint for Coinbase**
   - What we know: `GET /api/v3/brokerage/accounts` is the recommended lightweight validation call
   - What's unclear: Rate limits on initialization-time validation calls
   - Recommendation: Call `GET /api/v3/brokerage/accounts?limit=1` on init; catch `AuthenticationError` and re-raise with helpful message.

3. **Kraken `validate_credentials` lightweight call**
   - What we know: `POST /0/private/Balance` is the standard validation call
   - What's unclear: Rate limits per endpoint
   - Recommendation: Use `Balance` for validation; it returns quickly and confirms both key validity and permissions.

4. **Adaptive threshold when `cmc_asset_stats` is empty (early run)**
   - Recommendation documented in pitfall section: fall back to hardcoded defaults per asset, log which path was taken.

---

## Sources

### Primary (HIGH confidence)
- Official Coinbase Advanced Trade API documentation (llms.txt index) — endpoint paths confirmed
- `https://docs.cdp.coinbase.com/coinbase-app/authentication-authorization/api-key-authentication` — JWT auth mechanism confirmed
- `https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/accounts/list-accounts.md` — `GET /api/v3/brokerage/accounts` confirmed
- `https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/create-order.md` — POST body format confirmed
- `https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/cancel-order.md` — `POST /api/v3/brokerage/orders/batch_cancel` confirmed
- `https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-orders.md` — open orders filter confirmed
- `https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox` — sandbox URL confirmed
- `https://docs.kraken.com/api/docs/guides/spot-rest-auth/` — HMAC-SHA512 algorithm confirmed
- `https://pypi.org/project/coinbase-advanced-py/` — SDK version 1.8.2, no new install needed
- Existing project code: `src/ta_lab2/connectivity/` — current adapter structure read directly

### Secondary (MEDIUM confidence)
- `https://github.com/coinbase/coinbase-advanced-py/blob/master/README.md` — SDK usage patterns (verify via official docs)
- WebSearch: "Coinbase Pro API deprecated June 2024" — confirmed via multiple sources

### Tertiary (LOW confidence)
- "Kraken spot API has no sandbox" — inferred from absence of evidence + WebSearch showing only futures demo. Not officially stated in Kraken spot docs. Treat as likely true but worth confirming.
- Adaptive threshold formula (2x std_ret_30) — heuristic, no official source. Planner should treat as Claude's discretion.

---

## Metadata

**Confidence breakdown:**
- Standard stack (libraries): HIGH — both PyJWT and cryptography already installed, confirmed on machine
- Coinbase auth mechanism (JWT ES256): HIGH — confirmed from official CDP auth docs
- Coinbase endpoint paths: HIGH — confirmed from official API reference
- Kraken auth mechanism (HMAC-SHA512): HIGH — confirmed from official Kraken auth guide
- Kraken endpoint paths: HIGH — confirmed from Kraken API docs
- Coinbase sandbox: HIGH — confirmed sandbox URL and limitations from official docs
- Kraken spot testnet: LOW — no public sandbox found; based on absence of documentation
- Canonical order format: MEDIUM — field names are Claude's design based on exchange requirements
- Paper order table DDL: MEDIUM — designed to match project patterns and CONTEXT.md spec
- Price feed table DDL: MEDIUM — designed to match project patterns and CONTEXT.md spec

**Research date:** 2026-02-24
**Valid until:** 2026-05-24 (90 days — APIs are stable; check if Coinbase changes auth docs)
