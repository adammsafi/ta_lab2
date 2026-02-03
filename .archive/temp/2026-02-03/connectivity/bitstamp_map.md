# Bitstamp - Detailed API Map

This document maps the universal API functions defined in `unified_interface.md` to the specific implementation for the Bitstamp API.

## 1. Get Market Data

### `get_ticker(pair: string)`
*   **Unified Definition:** Fetches the latest price for a given trading pair.
*   **Endpoint:** `GET /api/v2/ticker/{market_symbol}/`
*   **Parameter Mapping:**
    *   The unified `pair` (e.g., "BTC/USD") must be converted to the Bitstamp `market_symbol` format (e.g., "btcusd").
*   **Response Mapping:**
    *   The `last` field from the Bitstamp JSON response maps to our unified `last_price`.

### `get_order_book(pair: string, depth: int)`
*   **Unified Definition:** Fetches the current order book.
*   **Endpoint:** `GET /api/v2/order_book/{market_symbol}/`
*   **Parameter Mapping:**
    *   `pair` -> `market_symbol` (e.g., "btcusd").
    *   `depth` is not a direct parameter. The API returns the full order book. The translator can truncate this to the desired depth.
*   **Response Mapping:**
    *   The `bids` and `asks` arrays in the response map directly to our unified format.

## 2. Trading

### `place_limit_order(pair: string, side: string, price: float, amount: float)`
*   **Unified Definition:** Places a new limit order.
*   **Endpoint:** `POST /api/v2/buy/{market_symbol}/` or `POST /api/v2/sell/{market_symbol}/` (Private)
*   **Parameter Mapping:**
    *   The endpoint used depends on the `side`.
    *   `pair` -> `market_symbol` (e.g., "btcusd").
    *   `price` -> `price`.
    *   `amount` -> `amount`.
*   **Response Mapping:**
    *   The `id` field from the response maps to our unified `order_id`.
