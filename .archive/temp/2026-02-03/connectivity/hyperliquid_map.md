# Hyperliquid - Detailed API Map

This document maps the universal API functions defined in `unified_interface.md` to the specific implementation for the Hyperliquid API.

**Note:** The Hyperliquid API documentation was not easily parsable, so this map is based on a high-level summary. Further investigation of the official documentation is required to get the exact endpoint paths and parameter names.

## 1. Get Market Data

### `get_ticker(pair: string)`
*   **Unified Definition:** Fetches the latest price for a given trading pair.
*   **Endpoint:** Likely part of the "info" endpoint.
*   **Parameter Mapping:**
    *   The unified `pair` (e.g., "BTC/USD") likely needs to be converted to a Hyperliquid-specific format.
*   **Response Mapping:**
    *   The response structure needs to be investigated to map to our unified `last_price`.

### `get_order_book(pair: string, depth: int)`
*   **Unified Definition:** Fetches the current order book.
*   **Endpoint:** Likely part of the "info" endpoint.
*   **Parameter Mapping:**
    *   `pair` -> Needs to be mapped to Hyperliquid's format.
*   **Response Mapping:**
    *   The response structure needs to be investigated to map to our unified `bids` and `asks`.

## 2. Trading

### `place_limit_order(pair: string, side: string, price: float, amount: float)`
*   **Unified Definition:** Places a new limit order.
*   **Endpoint:** Likely part of the "exchange" endpoint.
*   **Parameter Mapping:**
    *   Parameters will need to be mapped to Hyperliquid's format. This is a signed action.
*   **Response Mapping:**
    *   The response structure needs to be investigated to map to our unified `order_id`.
