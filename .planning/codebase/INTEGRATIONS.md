# External Integrations

**Analysis Date:** 2026-01-21

## APIs & External Services

**OpenAI (ChatGPT/GPT-4):**
- Uses gpt-4-mini model for data QA analysis
- SDK/Client: `openai` Python package (v1.0+)
- Auth: `OPENAI_API_KEY` environment variable (loaded from `openai_config.env`)
- Usage: `src/ta_lab2/scripts/open_ai_script.py` - analyzes CSV stats from EMA/price bar tests
- Use Case: Summarize test results, identify patterns, suggest QA actions

**Google APIs:**
- Packages: `google-api-python-client 2.160.0`, `google-auth 2.38.0`, `google-auth-oauthlib 1.2.1`
- Capabilities: Sheets, Drive, Gmail access (installed, not actively used in current codebase)
- OAuth support included

**FRED (Federal Reserve Economic Data):**
- Package: `fredapi 0.5.2` (installed, not actively used in codebase)
- Purpose: Available for fetching economic indicators if needed

**Yahoo Finance:**
- Package: `yfinance 0.2.53` (installed, not actively used in codebase)
- Purpose: Alternative market data source (currently using CoinMarketCap via direct SQL tables)

**Twilio:**
- Package: `twilio 9.8.5` (installed, not actively used)
- Capabilities: SMS and communication services
- Purpose: Available for alerts/notifications

## Data Storage

**Databases:**
- PostgreSQL 12+ (primary production database)
  - Connection: Environment variable `TARGET_DB_URL` or `MARKETDATA_DB_URL`
  - Pattern: `postgresql+psycopg2://postgres:3400@localhost:5432/marketdata`
  - Client: SQLAlchemy 2.0.44 + psycopg2-binary 2.9.11 (or psycopg 3.x v3 preferred)
  - Tables structure:
    - `cmc_price_histories7` - OHLCV daily bars for 7 assets (BTC, ETH, SOL, BNB, XRP, HYPE, LINK)
    - `cmc_da_ids` - Asset ID mappings (symbol ↔ name ↔ slug)
    - `cmc_da_info` - Asset metadata (URLs, categories, etc.)
    - `cmc_exchange_info` - Exchange descriptive data
    - `cmc_exchange_map` - Exchange ID mappings
    - `cmc_ema_daily` - Daily multi-period EMA for 7 assets
    - `cmc_ema_multi_tf` - Multi-timeframe EMA data
    - `cmc_ema_multi_tf_cal` - Calendar-adjusted multi-timeframe EMA
    - `cmc_ema_multi_tf_cal_anchor` - Anchor-based calendar-adjusted multi-timeframe EMA
    - `cmc_ema_multi_tf_v2` - Alternative multi-timeframe EMA implementation
    - `cmc_ema_multi_tf_u` - Unsigned/unsigned multi-timeframe EMA

**File Storage:**
- Local filesystem (Parquet format via `pyarrow`)
  - Default output: `artifacts/` directory
  - Location in code: `src/ta_lab2/io.py` functions `write_parquet()`, `read_parquet()`

**Caching:**
- Not detected - no explicit cache layer configured

## Authentication & Identity

**Auth Provider:**
- Custom: Environment-based configuration (API keys in env vars)
- OpenAI API key in environment
- Google OAuth optional (libraries present, not actively used)
- Database: PostgreSQL connection string in environment (username:password embedded)

**Implementation Approach:**
- `.env` file loading via `python-dotenv` (files: `db_config.env`, `openai_config.env`)
- Dynamic environment variable resolution in `src/ta_lab2/config.py`
- Fallback mechanism: tries `TARGET_DB_URL` → `DB_URL` → `MARKETDATA_DB_URL`

## Monitoring & Observability

**Error Tracking:**
- Not detected - no Sentry, Rollbar, or similar service integrated

**Logs:**
- Console/stdout only (no structured logging configured)
- Pattern: Python's built-in `print()` statements and potential `logging` module (not configured at global level)

**Metrics & Analytics:**
- Custom statistics collected via SQL queries and CSV exports
- Stats auditing: `src/ta_lab2/scripts/emas/audit_ema_samples.py`, `audit_ema_integrity.py`, etc.

## CI/CD & Deployment

**Hosting:**
- Local/self-hosted: Designed for on-premise deployment with manual PostgreSQL setup
- Data: CoinMarketCap price data (imported into local PostgreSQL)

**CI Pipeline:**
- GitHub Actions workflow config detected but not examined: `.github/release-please-config.json`
- Release management: `release-please` (automated release notes generation)

**Version Control:**
- Git repo with GitHub remote (GitHub Actions config present)

## Environment Configuration

**Required env vars (for full functionality):**
- `TARGET_DB_URL` or `MARKETDATA_DB_URL` - PostgreSQL connection string for market data
- `OPENAI_API_KEY` - OpenAI API key for GPT-4 analysis (optional, only for `open_ai_script.py`)

**Secrets location:**
- Local files (NOT committed to git):
  - `db_config.env` - Database credentials
  - `openai_config.env` - OpenAI API key

**Configuration files (committed):**
- `configs/default.yaml` - Application settings and feature parameters
- `pyproject.toml` - Package metadata and dependencies

## Data Sources (Incoming)

**CoinMarketCap:**
- Data: Daily OHLCV bars for major cryptocurrencies
- Mechanism: Imported via Python scripts into PostgreSQL tables
- Tables populated: `cmc_price_histories7`, `cmc_da_ids`, `cmc_da_info`, `cmc_exchange_info`, `cmc_exchange_map`
- Scripts: `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py` (daily refresh)
- Refresh modes:
  - Single-timeframe (1d)
  - Multi-timeframe standard (`cmc_ema_multi_tf`)
  - Multi-timeframe with calendar adjustments (`cmc_ema_multi_tf_cal`)
  - Calendar-anchored multi-timeframe (`cmc_ema_multi_tf_cal_anchor`)

## Webhooks & Callbacks

**Incoming:**
- Not detected - no webhook endpoints configured

**Outgoing:**
- Not detected - no external webhook calls observed

**Scheduled Tasks:**
- Daily refresh pipeline: `src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py`
- Uses `schedule` package (1.2.2) for job scheduling
- Execution: Manual CLI invocation or cron-based scheduling (external to app)

## External Libraries with Network Access

**Async HTTP:**
- `aiohttp 3.13.2` - Async HTTP client (installed, not actively used)
- `requests 2.32.3` - Synchronous HTTP client (installed, not actively used for external APIs currently)

**GIT Operations:**
- `GitPython 3.1.44` - Git repository operations (available for versioning data snapshots)

---

*Integration audit: 2026-01-21*
