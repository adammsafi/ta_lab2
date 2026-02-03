# Binance - Detailed API Map

This document maps the universal API functions defined in `unified_interface.md` to the specific implementation for the Binance API.

## 1. Get Market Data

### `get_ticker(pair: string)`
*   **Unified Definition:** Fetches the latest price for a given trading pair.
*   **Endpoint:** `GET /api/v3/ticker/price`
*   **Parameter Mapping:**
    *   The unified `pair` (e.g., "BTC/USD") must be converted to the Binance `symbol` format (e.g., "BTCUSDT").
*   **Response Mapping:**
    *   The `price` field from the Binance JSON response maps directly to our unified `last_price`.

### `get_order_book(pair: string, depth: int)`
*   **Unified Definition:** Fetches the current order book.
*   **Endpoint:** `GET /api/v3/depth`
*   **Parameter Mapping:**
    *   `pair` -> `symbol` (e.g., "BTCUSDT").
    *   `depth` -> `limit`. Note: Binance has specific allowed values for the limit (e.g., 5, 10, 20, 50, 100, 500, 1000, 5000). The translator will need to handle or round the `depth` parameter accordingly.
*   **Response Mapping:**
    *   The `bids` and `asks` arrays in the response map directly to our unified format.

## 2. Trading

### `place_limit_order(pair: string, side: string, price: float, amount: float)`
*   **Unified Definition:** Places a new limit order.
*   **Endpoint:** `POST /api/v3/order` (SIGNED)
*   **Parameter Mapping:**
    *   `pair` -> `symbol` (e.g., "BTCUSDT").
    *   `side` -> `side` (must be uppercase "BUY" or "SELL").
    *   `price` -> `price`.
    *   `amount` -> `quantity`.
    *   **Required static parameters:**
        *   `type`: Must be "LIMIT".
        *   `timeInForce`: A default like "GTC" (Good-Til-Canceled) should be used.
*   **Response Mapping:**
    *   The `orderId` field from the response maps to our unified `order_id`.
