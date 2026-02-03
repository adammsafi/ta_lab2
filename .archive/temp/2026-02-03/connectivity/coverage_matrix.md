# API Coverage Matrix

This table tracks the implementation status of the universal API functions for each exchange.

| Universal Function              | Binance          | Coinbase         | Bitfinex         | Bitstamp         | Kraken           | Hyperliquid  | Notes                               |
|---------------------------------|------------------|------------------|------------------|------------------|------------------|--------------|-------------------------------------|
| `get_ticker`                    | Implemented      | Implemented      | Implemented      | Implemented      | Implemented      | To Do        | Binance fails due to region block   |
| `get_order_book`                | Implemented      | Implemented      | Implemented      | Implemented      | Implemented      | To Do        | Binance fails due to region block   |
| `get_historical_klines`         | Implemented      | Implemented      | Implemented      | Implemented      | Implemented      | To Do        | Binance fails due to region block   |
| `get_account_balances`          | To Do            | To Do            | To Do            | To Do            | To Do            | To Do        | Requires Authentication             |
| `get_open_orders`               | To Do            | To Do            | To Do            | To Do            | To Do            | To Do        | Requires Authentication             |
| `place_limit_order`             | To Do            | To Do            | To Do            | To Do            | To Do            | To Do        | Requires Authentication             |
| `place_market_order`            | To Do            | To Do            | To Do            | To Do            | To Do            | To Do        | Requires Authentication             |
| `cancel_order`                  | To Do            | To Do            | To Do            | To Do            | To Do            | To Do        | Requires Authentication             |
