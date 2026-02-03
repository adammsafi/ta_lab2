# Coinbase - Detailed API Map

This document maps the universal API functions defined in `unified_interface.md` to the specific implementation for the Coinbase Exchange API.

## 1. Get Market Data

### `get_ticker(pair: string)`
*   **Unified Definition:** Fetches the latest price for a given trading pair.
*   **Endpoint:** `GET /products/{product_id}/ticker`
*   **Parameter Mapping:**
    *   The unified `pair` (e.g., "BTC/USD") must be converted to the Coinbase `product_id` format (e.g., "BTC-USD").
*   **Response Mapping:**
    *   The `price` field from the Coinbase JSON response maps directly to our unified `last_price`.

### `get_order_book(pair: string, depth: int)`
*   **Unified Definition:** Fetches the current order book.
*   **Endpoint:** `GET /products/{product_id}/book`
*   **Parameter Mapping:**
    *   `pair` -> `product_id` (e.g., "BTC-USD").
    *   `depth` -> `level`. Note: Coinbase has specific allowed values for the level (1, 2, or 3). Level 1 is the best bid and ask, Level 2 is the full order book (aggregated), and Level 3 is the full order book (non-aggregated). The translator will need to map the `depth` parameter to one of these levels.
*   **Response Mapping:**
    *   The `bids` and `asks` arrays in the response map directly to our unified format.

## 2. Trading

### `place_limit_order(pair: string, side: string, price: float, amount: float)`
*   **Unified Definition:** Places a new limit order.
*   **Endpoint:** `POST /orders` (Private)
*   **Parameter Mapping:**
    *   `pair` -> `product_id` (e.g., "BTC-USD").
    *   `side` -> `side` ("buy" or "sell").
    *   `price` -> `price`.
    *   `amount` -> `size`.
    *   **Required static parameters:**
        *   `type`: Must be "limit".
*   **Response Mapping:**
    *   The `id` field from the response maps to our unified `order_id`.
