# Exchange API Map

This document outlines the API details for key cryptocurrency exchanges.

## 1. Binance
*   **API Documentation:** [https://github.com/binance/binance-spot-api-docs](https://github.com/binance/binance-spot-api-docs)
*   **Authentication:** API Keys (HMAC SHA256 signatures required for `SIGNED` endpoints). Public data endpoints do not require authentication.
*   **Key Endpoints:**
    *   **Market Data:**
        *   `GET /api/v3/exchangeInfo`: Exchange trading rules and symbol information.
        *   `GET /api/v3/klines`: Candlestick/kline data.
        *   `GET /api/v3/ticker/24hr`: 24-hour price change statistics.
        *   `GET /api/v3/ticker/price`: Latest price for a symbol.
    *   **Account/Trade (Signed):**
        *   `POST /api/v3/order`: Place a new order.
        *   `DELETE /api/v3/order`: Cancel an order.
        *   `GET /api/v3/account`: Get current account information.
        *   `GET /api/v3/myTrades`: Get trades for a specific account.
*   **Rate Limits:**
    *   **Request Weight:** 1200 per minute.
    *   **Orders:** 50 per 10 seconds and 160,000 per 24 hours.
*   **Data Formats:** JSON for all requests and responses.

## 2. Coinbase Exchange
*   **API Documentation:** [https://docs.cloud.coinbase.com/exchange/docs/welcome](https://docs.cloud.coinbase.com/exchange/docs/welcome)
*   **Authentication:** API Key, Secret, and Passphrase. HMAC signature required for private endpoints. Public market data endpoints do not require authentication.
*   **Key Endpoints:**
    *   **Market Data (Public):**
        *   Get Products: `GET /products`
        *   Product Order Book: `GET /products/{product_id}/book`
        *   Product Ticker: `GET /products/{product_id}/ticker`
        *   Product Trades: `GET /products/{product_id}/trades`
        *   Historic Rates: `GET /products/{product_id}/candles`
    *   **Account/Trade (Private):**
        *   List Accounts: `GET /accounts`
        *   Place a new order: `POST /orders`
        *   Cancel an order: `DELETE /orders/{order_id}`
        *   List Fills: `GET /fills`
*   **Rate Limits:**
    *   **Public Endpoints:** 10 requests per second per IP (bursts up to 15).
    *   **Private Endpoints:** 15 requests per second per profile (bursts up to 30).
*   **Data Formats:** JSON for all REST API requests and responses.

## 3. Kraken
*   **API Documentation:** [https://docs.kraken.com/rest/](https://docs.kraken.com/rest/)
*   **Authentication:** API Key and API Secret. Private endpoints require a signature created using HMAC-SHA512.
*   **Key Endpoints:** The API is divided into public and private endpoints.
    *   **Public:** Used for market data (ticker info, order books, historical data).
    *   **Private:** Used for account and trade management (account balance, trade history, placing orders).
    *   *Note: Specific endpoint paths were not easily extractable and require consulting the official documentation.*
*   **Rate Limits:** The API has rate limits that vary by endpoint. Exceeding them will result in a `429` error.
*   **Data Formats:** JSON is used for requests and responses.

## 4. Bitfinex
*   **API Documentation:** [https://docs.bitfinex.com/v2/reference](https://docs.bitfinex.com/v2/reference)
*   **Authentication:** API Key and Secret. Requests are authenticated via headers: `bfx-nonce`, `bfx-apikey`, `bfx-signature`.
*   **Key Endpoints:**
    *   **Public:**
        *   Platform Status: `/platform/status`
        *   Ticker: `/ticker/{symbol}`
        *   Trades: `/trades/{symbol}/hist`
        *   Candles: `/candles/{candle}/{section}`
    *   **Authenticated:**
        *   Wallets: `/wallets`
        *   Submit Order: `/order/submit`
        *   Cancel Order: `/order/cancel`
        *   Orders History: `/orders/hist`
        *   Positions: `/positions`
        *   User Info: `/info/user`
*   **Rate Limits:** Varies by endpoint. For example, the Platform Status endpoint is limited to 30 requests per minute.
*   **Data Formats:** JSON, often in an array format.

## 5. Bitstamp by Robinhood
*   **API Documentation:** [https://www.bitstamp.net/api/](https://www.bitstamp.net/api/)
*   **Authentication:** API Key and Secret. Private calls are authenticated via `X-Auth` headers and a SHA256 HMAC signature.
*   **Key Endpoints:**
    *   **Public:**
        *   Ticker: `/api/v2/ticker/{market_symbol}/`
        *   Order Book: `/api/v2/order_book/{market_symbol}/`
        *   Transactions: `/api/v2/transactions/{market_symbol}/`
        *   OHLC Data: `/api/v2/ohlc/{market_symbol}/`
    *   **Private:**
        *   Account Balances: `/api/v2/account_balances/`
        *   Open Orders: `/api/v2/open_orders/`
        *   Place Buy/Sell Order: `/api/v2/buy/{market_symbol}/` or `/api/v2/sell/{market_symbol}/`
        *   Cancel Order: `/api/v2/cancel_order/`
*   **Rate Limits:** 400 requests per second, with a default limit of 10,000 requests per 10 minutes.
*   **Data Formats:** JSON for all requests and responses.

## 6. Hyperliquid
*   **API Documentation:** [https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api)
*   **Authentication:** Involves private keys or dedicated API wallets for signing requests.
*   **Key Endpoints:** The API has an "info" endpoint for public data and an "exchange" endpoint for trading actions. The base URL is `https://api.hyperliquid.xyz`.
    *   *Note: Specific endpoint paths were not easily extractable and require consulting the official documentation.*
*   **Rate Limits:** There is a limit of 1000 WebSocket subscriptions per IP address. Other rate limits exist and are detailed in the documentation.
*   **Data Formats:** JSON for POST requests and responses. Also supports WebSocket for subscriptions.
