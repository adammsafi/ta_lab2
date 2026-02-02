# ta_lab2 v0.4.0

Multi-timescale Technical Analysis Lab with AI Orchestration

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## Quick Start

### Installation

```bash
git clone https://github.com/your-username/ta_lab2.git
cd ta_lab2
pip install -e ".[orchestrator]"
```

For development with AI orchestration features, install the optional `orchestrator` dependency group which includes OpenAI, Anthropic, and Google AI SDKs.

### Basic Usage

```bash
# Set database URL
export TARGET_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"

# Windows (PowerShell)
$env:TARGET_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"

# Initialize time model (dim_timeframe and dim_sessions)
python -m ta_lab2.scripts.time.ensure_dim_tables

# Run feature pipeline
python -m ta_lab2.scripts.features.ta_feature refresh --all

# Generate trading signals
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Run backtest
python -m ta_lab2.scripts.signals.run_backtest --signal-type ema_crossover
```

For detailed setup instructions, see [Deployment Guide](deployment.md) and Time Model Documentation.

---

## Overview

**ta_lab2** is a production-ready technical analysis and quantitative trading infrastructure designed for multi-timescale feature engineering, signal generation, and backtesting. The v0.4.0 release introduces AI orchestration capabilities with persistent memory, cost-optimized routing across multiple LLM providers, and comprehensive observability.

**Key Capabilities:**
- Multi-timeframe EMA calculations (daily, calendar, trading-day aligned) across 199 timeframes
- Feature pipeline for returns, volatility estimators, and technical indicators (RSI, MACD, Bollinger Bands, ATR, ADX)
- Trading signal generation (EMA crossovers, RSI mean reversion, ATR breakouts) with database-driven configuration
- Vectorbt-based backtesting with reproducibility validation and performance metrics
- AI memory system with 3,763+ memories for context persistence across sessions
- Multi-platform AI orchestrator with cost-optimized routing (Gemini free tier → subscriptions → paid APIs)
- PostgreSQL-backed observability (metrics, tracing, health checks, alerts)

For architectural details and system design, see [ARCHITECTURE](../ARCHITECTURE.md) and [DESIGN](DESIGN.md).

---

## Components

<details>
<summary><strong>Time Model</strong> (dim_timeframe, dim_sessions)</summary>

The time model provides unified timeframe definitions and trading session calendars for consistent multi-timeframe analysis.

**Features:**
- 199 timeframes in `dim_timeframe` (1D to 365D, including calendar and trading-day variants)
- CRYPTO (24/7) and EQUITY (trading days only) sessions in `dim_sessions`
- Calendar vs trading-day alignment for accurate feature calculations
- Watermarking and state management for incremental refresh

**Tables:**
- `dim_timeframe`: Canonical timeframe definitions with metadata (tf_days, is_canonical, anchor_hour, etc.)
- `dim_sessions`: Trading session schedules per asset class (CRYPTO, EQUITY)

**Usage:**
```bash
# Initialize time model tables
python -m ta_lab2.scripts.time.ensure_dim_tables

# View timeframes
SELECT * FROM dim_timeframe ORDER BY tf_days;

# View sessions
SELECT * FROM dim_sessions;
```

See Time Model Documentation for details.

</details>

<details>
<summary><strong>Feature Pipeline</strong> (EMAs, returns, volatility, technical indicators)</summary>

Multi-stage feature calculation pipeline for technical analysis across multiple timeframes.

**Feature Types:**
- **EMAs**: Multi-timeframe exponential moving averages (daily, calendar, trading-day aligned)
  - Tables: `cmc_ema_daily`, `cmc_ema_multi_tf`, `cmc_ema_multi_tf_cal`, `cmc_ema_multi_tf_v2`, `cmc_ema_multi_tf_cal_anchor`
  - Unified view: `all_emas` (logical union of all EMA tables)
  - Periods: 5, 9, 10, 21, 50, 100, 200
- **Returns**: Bar-to-bar and multi-day percentage/log returns
  - Table: `cmc_returns_daily`
  - Lookbacks: 1D, 2D, 3D, 5D, 7D, 14D, 21D, 30D, 60D, 90D, 180D, 365D
- **Volatility**: Parkinson, Garman-Klass, Rogers-Satchell estimators
  - Table: `cmc_vol_daily`
- **Technical Indicators**: RSI (7, 14, 21), MACD (12/26/9, 8/17/9), Stochastic (14/3), Bollinger Bands (20/2), ATR (14), ADX (14)
  - Table: `cmc_daily_features` (materialized feature store with all indicators)

**Pipeline Execution:**
```bash
# Refresh all features (parallel execution)
python -m ta_lab2.scripts.pipeline.run_go_forward_daily_refresh

# Refresh individual feature types
python -m ta_lab2.scripts.emas.refresh_cmc_emas --ids all
python -m ta_lab2.scripts.features.returns_feature refresh --all
python -m ta_lab2.scripts.features.volatility_feature refresh --all
python -m ta_lab2.scripts.features.ta_feature refresh --all

# Refresh materialized feature store
python -m ta_lab2.scripts.features.daily_features_refresh
```

**State Management:**
- State tables track watermarks per (id, feature_type, feature_name) for incremental refresh
- Null handling strategies: skip (returns), forward_fill (volatility), interpolate (TA indicators)
- Outlier detection: Z-score (4 sigma) and IQR (1.5x) methods with `is_outlier` flag

See [EMA State Standardization](EMA_STATE_STANDARDIZATION.md) for implementation details.

</details>

<details>
<summary><strong>Signal System</strong> (crossovers, reversions, breakouts)</summary>

Database-driven trading signal generation with position lifecycle tracking and feature hashing for reproducibility.

**Signal Types:**
- **EMA Crossover**: Fast/slow EMA crossover signals (9/21, 21/50, 50/200)
  - Table: `cmc_signals_ema_crossover`
  - Direction: LONG (fast > slow), SHORT (fast < slow)
- **RSI Mean Reversion**: Oversold/overbought RSI signals
  - Table: `cmc_signals_rsi_mean_revert`
  - Thresholds: Oversold (<30), Overbought (>70)
- **ATR Breakout**: Donchian channel + ATR expansion breakouts
  - Table: `cmc_signals_atr_breakout`
  - Types: channel_break, atr_expansion, or both

**Configuration:**
- `dim_signals`: Database-driven signal configuration with JSONB params
- No code changes needed to add new signal parameter sets
- Example: Add new RSI period via INSERT into dim_signals

**Position Tracking:**
- `SignalStateManager`: Tracks open positions and dirty windows per (id, signal_type, signal_id)
- Feature snapshot at entry (close, EMAs, RSI, ATR) for backtest self-containment
- FIFO position matching for exit signals

**Reproducibility:**
- SHA256 feature hashing (first 16 chars) for deterministic backtest validation
- Feature version hash computed from explicit column order
- Hash mismatch detection prevents stale backtest comparisons

**Usage:**
```bash
# Generate all signals
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Generate specific signal type
python -m ta_lab2.scripts.signals.ema_crossover_refresh
python -m ta_lab2.scripts.signals.rsi_mean_revert_refresh
python -m ta_lab2.scripts.signals.atr_breakout_refresh
```

</details>

<details>
<summary><strong>Memory System</strong> (Mem0 + Qdrant)</summary>

AI context persistence with semantic search, conflict detection, and health monitoring.

**Architecture:**
- **Mem0**: Logic layer for memory operations (add, search, update, delete)
- **Qdrant**: Vector database backend (localhost:6333 in server mode)
- **OpenAI text-embedding-3-small**: 1536-dimensional embeddings for consistency
- **REST API**: FastAPI endpoints for cross-platform access (`/api/v1/memory/*`)

**Features:**
- 3,763+ memories in vector store with semantic search
- Similarity threshold: 0.7 for relevance filtering
- LLM-powered conflict detection (GPT-4o-mini) with 26% accuracy improvement over rules
- Metadata scoping for context-dependent truths (e.g., asset_class)
- Staleness tracking: 90-day threshold with `last_verified` refresh pattern
- JSONL audit log for conflict resolution history

**Health Monitoring:**
- `/api/v1/memory/health`: Overall health status with nested component checks
- `/api/v1/memory/health/stale`: List memories not verified in 90+ days
- Age distribution buckets: 0-30d, 30-60d, 60-90d, 90+d

**Usage:**
```bash
# Start Qdrant server (required)
docker run -d -p 6333:6333 -v qdrant_data:/qdrant/storage qdrant/qdrant

# Set environment variables
export QDRANT_SERVER_MODE=true
export OPENAI_API_KEY="sk-..."

# Query memory API
curl http://localhost:8000/api/v1/memory/health
curl http://localhost:8000/api/v1/memory/search?query="EMA calculation"
```

**Python API:**
```python
from ta_lab2.tools.ai_orchestrator.memory import MemoryService

memory = MemoryService()
memory.add("Multi-timeframe EMAs use dim_timeframe for alignment", metadata={"component": "features"})
results = memory.search("How are EMAs calculated?", limit=5)
```

See [Memory API Reference](api/memory.md) for full REST endpoint documentation.

</details>

<details>
<summary><strong>Orchestrator</strong> (Claude, ChatGPT, Gemini)</summary>

Multi-platform AI coordination with cost-optimized routing, parallel execution, and AI-to-AI handoffs.

**Platform Adapters:**
- **ClaudeAdapter**: Anthropic Claude (gpt-4-class reasoning)
- **ChatGPTAdapter**: OpenAI GPT-4o-mini (default for cost efficiency: $0.15/$0.60 per 1M tokens)
- **GeminiAdapter**: Google Gemini (free tier: 1500 requests/day)

**Cost-Optimized Routing:**
1. Gemini free tier (priority=1, lowest cost)
2. Subscriptions (priority=2, ChatGPT Plus, Claude Pro)
3. Paid APIs (priority=3, OpenAI/Anthropic pay-as-you-go)
4. RuntimeError on exhaustion with clear error message

**Features:**
- **Parallel Execution**: TaskGroup (Python 3.11+) with semaphore-based concurrency control (default: 10 concurrent tasks)
- **Quota Management**: Request-based tracking with 50%/80%/90% alert thresholds
- **AI-to-AI Handoffs**: Hybrid (pointer + summary) pattern for context sharing via memory
- **Retry Logic**: Exponential backoff (1s → 32s) with 3s jitter, 5 attempts for rate limits/timeouts
- **Platform Fallback**: Automatic fallback to next platform on failure with full retry cycle

**Handoff Pattern:**
- Full context stored in memory with unique ID
- Brief summary (max 500 chars) passed inline for quick reference
- Fail-fast memory lookup: RuntimeError if context not found

**Usage:**
```bash
# Run single task
ta-lab2 orchestrator submit --prompt "Explain EMA calculation" --platform gemini

# Run batch with parallel execution
ta-lab2 orchestrator batch tasks.json --parallel 5

# Check quota status
ta-lab2 orchestrator quota

# View cost tracker
ta-lab2 orchestrator costs
```

**Python API:**
```python
from ta_lab2.tools.ai_orchestrator import Orchestrator, Platform, Task

orchestrator = Orchestrator()
task = Task(prompt="Summarize backtest results", platform_hint=Platform.GEMINI)
result = await orchestrator.execute_task(task)
```

See [Orchestrator CLI Reference](api/orchestrator.md) for full command documentation.

</details>

<details>
<summary><strong>Observability</strong> (metrics, tracing, health checks, alerts)</summary>

PostgreSQL-backed production monitoring with correlation ID tracing and alert delivery.

**Metrics Storage:**
- Table: `observability.metrics` (month-partitioned by `recorded_at`)
- Dimensions: component, metric_name, value, tags (JSONB)
- Queryable via SQL for custom dashboards and analysis

**Tracing:**
- 32-char hex correlation IDs for cross-system request tracing
- OpenTelemetry trace context when available, UUID fallback
- Propagated through headers and logs for end-to-end visibility

**Health Checks:**
- **Kubernetes probe pattern**: Separate liveness, readiness, startup endpoints
- **Liveness**: Process alive (always returns 200 after startup)
- **Readiness**: Dependencies healthy (database, memory service, external APIs)
- **Startup**: Initialization complete (dim_timeframe/dim_sessions exist)
- **Nested details**: `details['checks']['database']` for organized component status

**Alert Thresholds:**
- **Baseline + percentage approach**: p50 from last 7 days, trigger when current >2x baseline
- **Strict data quality**: 0% tolerance for gaps/alignment/rowcount issues (crypto 24/7 data)
- **Severity escalation**: Integration failures CRITICAL after >3 errors, resource exhaustion CRITICAL at ≥95%
- **Dual delivery**: Telegram for immediate notification + database for historical tracking

**Usage:**
```bash
# Check health
curl http://localhost:8000/health/liveness
curl http://localhost:8000/health/readiness
curl http://localhost:8000/health/startup

# Query metrics
SELECT * FROM observability.metrics
WHERE component = 'feature_pipeline'
  AND recorded_at > NOW() - INTERVAL '1 day'
ORDER BY recorded_at DESC;

# View workflow traces
SELECT * FROM observability.workflow_state
WHERE correlation_id = 'abc123...'
ORDER BY created_at;
```

**Python API:**
```python
from ta_lab2.observability import MetricsCollector, HealthChecker, record_trace

# Record metrics
metrics = MetricsCollector()
metrics.record("feature_refresh_duration", 45.2, tags={"feature": "ema"})

# Health checks
health = HealthChecker()
status = health.readiness()  # Returns HealthStatus with nested details

# Tracing
@record_trace("ema_calculation")
async def calculate_emas(ids):
    # Automatically records correlation_id, duration, errors
    pass
```

</details>

---

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ta_lab2 --cov-report=html

# Run specific test tiers
pytest -m mocked_deps       # Unit tests (no infrastructure)
pytest -m mixed_deps        # Integration tests (real DB, mocked AI)
pytest -m real_deps         # E2E tests (full infrastructure)

# Run validation tests (requires database)
pytest -m validation
```

**Test Tiers:**
- `mocked_deps`: Unit tests with all dependencies mocked (fast, CI-friendly)
- `mixed_deps`: Real database + mocked AI adapters (for database logic testing)
- `real_deps`: Full infrastructure including Qdrant, LLM APIs (for E2E validation)

**Coverage Threshold:** 70% minimum (enforced in CI)

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type checking
mypy src/
```

### Database Migrations

```bash
# Create new migration
alembic revision -m "Add new feature table"

# Apply migrations
alembic upgrade head

# View migration history
alembic history
```

---

## Documentation

- **[Design Overview](DESIGN.md)** - High-level system concepts and data flow
- **[Architecture](../ARCHITECTURE.md)** - Implementation details and schemas
- **[Deployment Guide](deployment.md)** - Setup and configuration
- **[API Reference](api/memory.md)** - Memory REST API documentation
- **[CLI Reference](api/orchestrator.md)** - Orchestrator CLI commands
- **[Changelog](../CHANGELOG.md)** - Version history

---

## Project Documentation

Documentation converted from ProjectTT (original files preserved in `.archive/documentation/`).

### Architecture

Core system design, components, and terminology.

- [Workspace Overview](architecture/ta-lab2-workspace-v.1.1.md) - Main project architecture and design (v1.1)
- [Core Components](architecture/corecomponents.md) - Foundational system components
- [Key Terms](architecture/keyterms.md) - Terminology and definitions
- [Database Schemas](architecture/schemas.md) - Database table definitions
- [Database Keys](architecture/db-keys.md) - Primary and foreign key relationships
- [Genesis Files Summary](architecture/ta-lab2-genesisfiles-summary.md) - Project origins and evolution
- [Vision Draft](architecture/ta-lab2-vision-draft-20251111.md) - Strategic vision and goals
- [Project Plan](architecture/project-plan.md) - Original project plan
- [V1 Project Plan](architecture/v1-project-plan.md) - Version 1 planning
- [ChatGPT Vision Questions](architecture/chatgpt-visionquestions.md) - Strategic questions
- [Timeframes](architecture/timeframes.md) - Timeframe concepts and design
- [Regimes In Depth](architecture/regimesindepth.md) - Market regime detection
- [Hysteresis](architecture/hysteresis.md) - Hysteresis in technical indicators
- [Fed Data Summary](architecture/feddata-indepthsummary-20251110.md) - Federal Reserve data integration

### Features

Feature implementations and technical analysis components.

**EMAs (Exponential Moving Averages):**
- [EMA Overview](features/ema-overview.md) - Overview of EMA calculations
- [EMA Daily](features/ema-daily.md) - Daily EMA calculations
- [EMA Multi-Timeframe](features/ema-multi-tf.md) - Multi-timeframe EMA system
- [EMA Multi-Timeframe Calendar](features/ema-multi-tf-cal.md) - Calendar-aligned EMAs
- [EMA Multi-Timeframe Calendar Anchor](features/ema-multi-tf-cal-anchor.md) - Anchor-based calendar EMAs
- [EMA Study](features/emas/ema-study.md) - EMA research and analysis
- [EMA Alpha Comparison](features/emas/ema-alpha-comparison.md) - Alpha calculation comparison
- [EMA Thoughts](features/ema-thoughts.md) - Design considerations
- [EMA Possible Next Steps](features/ema-possible-next-steps.md) - Future enhancements
- [EMA Loo](features/ema-loo.md) - EMA implementation details

**Bars (Price Bars):**
- [Bar Creation](features/bar-creation.md) - Price bar construction
- [Bar Implementation](features/bar-implementation.md) - Bar processing implementation

**Memory System:**
- [Memory Model](features/memory-model.md) - AI memory architecture

### Planning

Project planning, status reports, and roadmaps.

- [12-Week Plan (v1)](planning/new-12wk-plan-doc.md) - Original 12-week plan
- [12-Week Plan (v2)](planning/new-12wk-plan-doc-v2.md) - Updated 12-week plan
- [12-Week Plan Table](planning/12-week-plan-table.md) - Plan summary table
- [Status 20251113](planning/status-20251113.md) - Status report November 13
- [So Far 20251108](planning/sofar-20251108.md) - Progress summary November 8
- [So Far In My Own Words](planning/sofarinmyownwords.md) - Narrative progress summary
- [Updates So Far 20251108](planning/updates-sofar-20251108.md) - Update summary November 8
- [Next Steps](planning/ta-lab2-nextsteps-needreview-20251111.md) - Planned next steps
- [Some Next Steps](planning/ta-lab2-somenextstepstoreview-20251111.md) - Additional next steps
- [Status & ToDos](planning/ta-lab2-status-todos-review-20251111.md) - Status and todo list

### Reference

Reference materials, processes, and supporting documentation.

- [Timeframes Chart](reference/timeframes-chart.md) - Timeframe definitions and relationships
- [Exchange Info](reference/exchanges-info.md) - Supported exchanges and assets
- [ChatGPT Export Processing](reference/chat-gpt-export-processing-end-to-end-process.md) - ChatGPT conversation export process
- [Memories](reference/memories.md) - Memory system documentation
- [Update DB](reference/update-db.md) - Database update procedures
- [Updating Price Data](reference/updating-price-data-rough.md) - Price data refresh process
- [Refresh Methods Review](reference/review-refreshmethods-20251201.md) - Review of refresh methods

> **Note:** Original Word and Excel files are preserved in `.archive/documentation/` with full git history and SHA256 checksums for integrity verification.

---

## Contributing

This project welcomes contributions for bug fixes, feature enhancements, and documentation improvements.

**Guidelines:**
- Follow existing code patterns and naming conventions
- Add tests for new features (aim for 70%+ coverage)
- Update documentation (docstrings, README, ARCHITECTURE) for significant changes
- Use conventional commit format: `type(scope): description`
  - Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `style`, `chore`
  - Scopes: component names (e.g., `ema`, `signals`, `orchestrator`, `memory`)

**Branch Strategy:**
- `main`: Stable releases (protected, requires PR + CI green)
- `feature/*`: New features
- `fix/*`: Bug fixes
- `docs/*`: Documentation updates

---

## Security

If you discover a security issue (credential handling, database access, API key exposure), do not open a public GitHub issue.

**Security Best Practices:**
- Never commit secrets, API keys, or database credentials
- Use `.env` files for sensitive configuration (ensure `.gitignore` excludes them)
- Rotate API keys regularly
- Use read-only database users where possible
- Enable SSL/TLS for database connections in production

---

## License

TBD. Until an explicit license is added, treat this as **source-available for personal research use only**.

If you want to use this in a commercial setting, reach out first so terms can be clarified once the project is more mature.

---

## Changelog

See [CHANGELOG](../CHANGELOG.md) for release history and upgrade notes.

**Latest Release:** v0.4.0 (2026-02-01)
- AI orchestration with Mem0 + Qdrant memory system
- Multi-platform LLM coordination (Claude, ChatGPT, Gemini)
- Trading signal system with reproducibility validation
- PostgreSQL-backed observability and health monitoring
- Comprehensive validation tests (70+ tests for time alignment, data consistency, backtest reproducibility)
