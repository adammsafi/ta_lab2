# Bitfinex - Detailed API Map

This document maps the universal API functions defined in `unified_interface.md` to the specific implementation for the Bitfinex API.

## 1. Get Market Data

### `get_ticker(pair: string)`
*   **Unified Definition:** Fetches the latest price for a given trading pair.
*   **Endpoint:** `GET /ticker/{symbol}`
*   **Parameter Mapping:**
    *   The unified `pair` (e.g., "BTC/USD") must be converted to the Bitfinex `symbol` format (e.g., "tBTCUSD").
*   **Response Mapping:**
    *   The Bitfinex response is an array of values. The `LAST_PRICE` (index 6) maps to our unified `last_price`.

### `get_order_book(pair: string, depth: int)`
*   **Unified Definition:** Fetches the current order book.
*   **Endpoint:** `GET /book/{symbol}/{precision}`
*   **Parameter Mapping:**
    *   `pair` -> `symbol` (e.g., "tBTCUSD").
    *   `precision` is a required parameter for Bitfinex. A default like "P0" can be used.
    *   `depth` is not a direct parameter. The API returns a configurable number of price points (default 25, max 100). The translator will need to handle this.
*   **Response Mapping:**
    *   The response is an array of arrays. Bids are entries where `AMOUNT` > 0, and asks are entries where `AMOUNT` < 0. Each entry is `[PRICE, COUNT, AMOUNT]`. This needs to be transformed into our unified `[[price, size], ...]` format.

## 2. Trading

### `place_limit_order(pair: string, side: string, price: float, amount: float)`
*   **Unified Definition:** Places a new limit order.
*   **Endpoint:** `POST /order/submit` (Authenticated)
*   **Parameter Mapping:**
    *   `pair` -> `symbol` (e.g., "tBTCUSD").
    *   `side` is determined by the sign of the `amount`. "buy" means positive `amount`, "sell" means negative `amount`.
    *   `price` -> `price`.
    *   `amount` -> `amount` (a string, positive for buy, negative for sell).
    *   **Required static parameters:**
        *   `type`: "LIMIT".
*   **Response Mapping:**
    *   The order ID can be found in the response notification. The structure needs to be investigated further.
