# Unified Exchange API Interface

This document defines the universal functions for interacting with any exchange.

## 1. Market Data

### `get_ticker(pair: str) -> dict`
*   **Description:** Fetches the latest price for a given trading pair.
*   **Input:** `pair` - A standardized pair string, e.g., "BTC/USD".
*   **Output:** A dictionary containing the last price, e.g., `{"last_price": 67500.50}`.

### `get_order_book(pair: str, depth: int) -> dict`
*   **Description:** Fetches the current order book.
*   **Input:** `pair` - e.g., "BTC/USD", `depth` - Number of levels to retrieve.
*   **Output:** A dictionary with "bids" and "asks", e.g., `{"bids": [[price, size], ...], "asks": [[price, size], ...]}`.

### `get_historical_klines(pair: str, interval: str, start_time: int, end_time: int) -> list`
*   **Description:** Fetches historical kline (candlestick) data.
*   **Input:** `pair`, `interval` (e.g., "1m", "1h", "1d"), `start_time` (Unix timestamp), `end_time` (Unix timestamp).
*   **Output:** A list of lists, e.g., `[[timestamp, open, high, low, close, volume], ...]`. 

## 2. Account Management (Authenticated)

### `get_account_balances() -> dict`
*   **Description:** Fetches all asset balances in the account.
*   **Output:** A dictionary of available balances, e.g., `{"BTC": 1.25, "USD": 10000.50}`.

### `get_open_orders(pair: str = None) -> list`
*   **Description:** Fetches all open orders, optionally for a specific pair.
*   **Output:** A list of order dictionaries.

## 3. Trading (Authenticated)

### `place_limit_order(pair: str, side: str, price: float, amount: float) -> dict`
*   **Description:** Places a new limit order.
*   **Input:** `pair`, `side` ("buy" or "sell"), `price`, `amount`.
*   **Output:** A dictionary with the order ID, e.g., `{"order_id": "12345"}`.

### `place_market_order(pair: str, side: str, amount: float) -> dict`
*   **Description:** Places a new market order.
*   **Input:** `pair`, `side` ("buy" or "sell"), `amount`.
*   **Output:** A dictionary with the order ID.

### `cancel_order(order_id: str) -> dict`
*   **Description:** Cancels an existing order.
*   **Input:** `order_id` - The ID of the order to cancel.
*   **Output:** A dictionary with the order ID of the cancelled order.