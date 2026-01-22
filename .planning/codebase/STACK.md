# Technology Stack

**Analysis Date:** 2026-01-21

## Languages

**Primary:**
- Python 3.10+ - Core language for all data processing, backtests, feature engineering
- SQL (PostgreSQL) - Market data queries and time-series analytics

**Secondary:**
- YAML - Configuration files (`configs/default.yaml`)
- JSON - Configuration and serialization

## Runtime

**Environment:**
- CPython 3.10+
- psycopg2-binary 2.9+ or psycopg 3.x (PostgreSQL adapter)

**Package Manager:**
- pip (standard Python packaging)
- Lockfile: `requirements-311.txt` (pip freeze format)

## Frameworks

**Core Data Processing:**
- pandas 2.2.3 - DataFrames, time-series resampling, pivoting
- numpy 1.26.4 - Numerical operations, array computations
- SQLAlchemy 2.0.44 - ORM and database abstraction layer

**Financial Analysis:**
- yfinance 0.2.53 - (in requirements but not actively used in codebase)
- fredapi 0.5.2 - Federal Reserve Economic Data (FRED) API client (in requirements)
- vectorbt 0.28.1 - Vectorized backtesting and analysis
- arch 7.2.0 - ARCH/GARCH volatility modeling

**Testing:**
- pytest 8.4.2 - Test runner
- pytest-benchmark 5.2.0 - Performance benchmarking
- hypothesis 6.142.5 - Property-based testing

**Build/Dev:**
- setuptools 68+ - Package building and installation
- ruff 0.14.3 - Fast Python linter
- mypy 1.18.2 - Static type checking

**Visualization:**
- matplotlib 3.10.0 - Static plotting
- plotly 6.4.0 - Interactive web-based visualizations
- altair 5.5.0 - Declarative visualization

**Utilities:**
- PyYAML 6.0.3 - YAML parsing and generation
- python-dotenv 1.2.1 - Environment variable loading from .env files
- GitPython 3.1.44 - Git operations
- click 8.1.8 - CLI framework
- streamlit 1.44.0 - Interactive web app framework (installed but not actively used)

**AI/ML Integration:**
- openai - OpenAI API client for ChatGPT/GPT-4 integration
- google-api-python-client 2.160.0 - Google APIs (Sheets, Drive, etc.)

**Date/Time:**
- dateutil 2.9.0 - Date parsing and arithmetic
- pytz 2025.2 - Timezone support
- astronomy-engine 2.1.19 - Astronomical calculations (seasons, moon phases)

**External Services:**
- requests 2.32.3 - HTTP client library
- aiohttp 3.13.2 - Async HTTP client
- twilio 9.8.5 - SMS/communication API (installed but not actively used)

**Time Series & Markets:**
- schedule 1.2.2 - Job scheduling for periodic tasks

## Configuration

**Environment:**
- Primary DB: `MARKETDATA_DB_URL` or `TARGET_DB_URL` environment variables (PostgreSQL connection string)
- OpenAI: `OPENAI_API_KEY` environment variable
- Loaded from: `db_config.env` and `openai_config.env` (local, not committed)

**Build:**
- `pyproject.toml` - Modern Python packaging (setuptools backend)
  - Location: `C:\Users\asafi\Downloads\ta_lab2\pyproject.toml`
  - Entry point: `ta-lab2` CLI command routes to `ta_lab2.cli:main`

**Configuration Files:**
- `configs/default.yaml` - Primary application configuration
  - Feature definitions (EMA windows, RSI/MACD/Bollinger parameters)
  - Indicator toggles and periods
  - Bar-to-bar returns modes and windows
  - Rolling volatility settings
  - Calendar and regime detection parameters
  - Pipeline toggles (indicators, segments, regimes, etc.)

## Database

**Primary Database:**
- PostgreSQL 12+ (via connection string `postgresql+psycopg2://postgres:3400@localhost:5432/marketdata`)
- Tables: `cmc_price_histories7`, `cmc_da_ids`, `cmc_da_info`, `cmc_exchange_info`, `cmc_exchange_map`, `cmc_ema_daily`, `cmc_ema_multi_tf`, `cmc_ema_multi_tf_cal`, `cmc_ema_multi_tf_cal_anchor`, `cmc_ema_multi_tf_v2`, `cmc_ema_multi_tf_u`

**Data Format:**
- Parquet files via `pyarrow 19.0.1` for efficient storage
- CSV for data exchange and manual inspection

## Platform Requirements

**Development:**
- Windows/Linux/macOS with Python 3.10+
- PostgreSQL 12+ running locally or remotely accessible
- Git for version control

**Production:**
- Python 3.10+ runtime
- PostgreSQL 12+ for data storage
- Environment variables: `TARGET_DB_URL`, `OPENAI_API_KEY`, `MARKETDATA_DB_URL`

## Optional Dependencies

**Installed but Not Core:**
- `streamlit` - Web UI framework (ready for dashboard development)
- `yfinance` - Market data fetching (alternative to current data source)
- `fredapi` - FRED data (available for economic indicators)
- `twilio` - Messaging service (available for notifications)
- `plotly` - Interactive plotting (alternative to matplotlib)

---

*Stack analysis: 2026-01-21*
