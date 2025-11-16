# Data Pipeline

## Overview

- Source: CoinMarketCap OHLCV (API / CSV export)
- Canonical store: Postgres (schema: public.cmc_price_histories7)
- Consumers: ta_lab2 pipelines, research queries, backtests

## Flow

1. Fetch from CMC → write raw JSON/CSV to `data/raw/`
2. ETL script (`scripts/etl/update_cmc_history.py`) parses + upserts into Postgres.
3. ta_lab2 uses `ta_lab2.io.load_btc_ohlcv(source="db", ...)` to read from DB.
4. Pipelines / research operate on the standardized DataFrame.

## Tables

- `public.cmc_price_histories7`
  - `id` (int) – CMC id
  - `timeopen` (timestamptz)
  - `open, high, low, close, volume` (numeric)
  - `load_ts` (timestamptz)
  - `source_file` (text)
