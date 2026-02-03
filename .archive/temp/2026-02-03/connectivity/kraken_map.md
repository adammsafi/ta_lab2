# Kraken - Detailed API Map

This document maps the universal API functions defined in `unified_interface.md` to the specific implementation for the Kraken API.

**Note:** The Kraken API documentation was not easily parsable, so this map is based on a high-level summary. Further investigation of the official documentation is required to get the exact endpoint paths and parameter names.

## 1. Get Market Data

### `get_ticker(pair: string)`
*   **Unified Definition:** Fetches the latest price for a given trading pair.
*   **Endpoint:** Likely a public endpoint, possibly `/0/public/Ticker`.
*   **Parameter Mapping:**
    *   The unified `pair` (e.g., "BTC/USD") likely needs to be converted to a Kraken-specific format (e.g., "XBTUSDM").
*   **Response Mapping:**
    *   The response structure needs to be investigated to map to our unified `last_price`.

### `get_order_book(pair: string, depth: int)`
*   **Unified Definition:** Fetches the current order book.
*   **Endpoint:** Likely a public endpoint, possibly `/0/public/Depth`.
*   **Parameter Mapping:**
    *   `pair` -> `pair` (e.g., "XBTUSDM").
    *   `depth` -> `count`.
*   **Response Mapping:**
    *   The response structure needs to be investigated to map to our unified `bids` and `asks`.

## 2. Trading

### `place_limit_order(pair: string, side: string, price: float, amount: float)`
*   **Unified Definition:** Places a new limit order.
*   **Endpoint:** A private endpoint, possibly `/0/private/AddOrder`.
*   **Parameter Mapping:**
    *   `pair` -> `pair`.
    *   `side` -> `type` ("buy" or "sell").
    *   `price` -> `price`.
    *   `amount` -> `volume`.
    *   **Required static parameters:**
        *   `ordertype`: "limit".
*   **Response Mapping:**
    *   The response structure needs to be investigated to map to our unified `order_id`.
