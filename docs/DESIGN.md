# ta_lab2 System Design

Version: 0.4.0

This document describes the high-level design of ta_lab2, including system goals, architecture overview, data flow, and key design decisions. For implementation details, see [ARCHITECTURE.md](../ARCHITECTURE.md).

---

## System Goals

ta_lab2 is a systematic crypto trading platform with integrated AI orchestration. The system has three primary goals:

1. **Technical Analysis & Regime Detection for Trading**
   - Multi-timeframe EMA calculations with unified time model
   - Comprehensive feature pipeline (returns, volatility, technical indicators)
   - Signal generation across multiple strategies (EMA crossover, RSI mean reversion, ATR breakout)
   - Reproducible backtesting with triple-layer verification

2. **AI Orchestration for Multi-Platform Task Coordination**
   - Coordinate Claude, ChatGPT, and Gemini through unified memory layer
   - Cost-optimized routing (free tiers first, then subscriptions, then paid APIs)
   - Quota tracking and adaptive concurrency control
   - Persistent memory for context across sessions and platforms

3. **Trustworthy Infrastructure with Quality Gates**
   - PostgreSQL-backed observability (metrics, traces, workflow state)
   - Three-tier test pattern (real_deps, mixed_deps, mocked_deps)
   - Validation gates for time alignment, data consistency, backtest reproducibility
   - Database-driven configuration for extensibility without code changes

---

## Architecture Overview

The system follows a vertical slice architecture with three parallel tracks:

```
┌──────────────────────────────────────────────────────────────────┐
│                     AI ORCHESTRATOR LAYER                         │
│  ┌────────────┐   ┌────────────┐   ┌────────────┐   ┌─────────┐ │
│  │   Claude   │   │  ChatGPT   │   │   Gemini   │   │ Memory  │ │
│  │  Adapter   │   │  Adapter   │   │  Adapter   │   │ System  │ │
│  └────────────┘   └────────────┘   └────────────┘   └─────────┘ │
│         │                │                │               │       │
│         └────────────────┴────────────────┴───────────────┘       │
│                          Routing & Execution                      │
│                    (Cost-optimized, Quota-aware)                  │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 v
┌──────────────────────────────────────────────────────────────────┐
│                      TA_LAB2 FEATURE PIPELINE                     │
│                                                                   │
│  ┌───────────────┐      ┌───────────────┐      ┌──────────────┐ │
│  │  Data Layer   │  →   │ Feature Layer │  →   │ Signal Layer │ │
│  │ (price bars)  │      │ (EMAs, vol,   │      │ (crossovers, │ │
│  │               │      │  returns, TA) │      │  reversions) │ │
│  └───────────────┘      └───────────────┘      └──────────────┘ │
│          │                      │                      │          │
│          v                      v                      v          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Time Model Layer                       │   │
│  │  (dim_timeframe, dim_sessions, calendar alignment)        │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
                                 │
                                 v
┌──────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY LAYER                            │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐   │
│  │   Metrics    │   │    Traces    │   │  Workflow State    │   │
│  │  (PostgreSQL)│   │ (PostgreSQL) │   │    (PostgreSQL)    │   │
│  └──────────────┘   └──────────────┘   └────────────────────┘   │
│                Health Checks + Alerts (Telegram)                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 1. Time Model

The foundation of all temporal calculations:

- **dim_timeframe**: 199 timeframe definitions (1D-365D with trading/calendar alignment)
  - Columns: `tf_id`, `tf`, `tf_days`, `is_canonical`, `calendar_scheme`, `allow_partial_*`, `tf_days_min/max`
  - Supports both trading-day aligned (5D skip weekends) and calendar-aligned (5D include weekends)
  - Enables validation of temporal alignment across all feature tables

- **dim_sessions**: Trading session definitions (CRYPTO/EQUITY)
  - Columns: `session_id`, `session_name`, `is_24_7`, `trading_days_per_week`, `market_open/close_utc`
  - CRYPTO: 24/7 operation (7 trading days/week)
  - EQUITY: 9:30-16:00 ET with DST handling (5 trading days/week)

- **Calendar alignment**: Timeframes can be trading-aligned or calendar-aligned
  - Trading-aligned 1W = 5 trading days (skip Sat/Sun for equity)
  - Calendar-aligned 1W = 7 calendar days (include weekends)
  - Multi-TF EMAs support both via `calendar_scheme` column

**Design decision**: Time model before features. All downstream tables reference dim_timeframe to ensure consistency.

### 2. Feature Pipeline

Transforms price data into analysis-ready features:

- **Returns** (`cmc_returns_daily`):
  - Bar-to-bar percent and log returns
  - Multi-day returns (1D, 7D, 30D) using `pct_change(periods=n)`
  - Z-score normalization with rolling 252-day window
  - Null handling: skip (preserve gaps for accurate return calculations)

- **Volatility** (`cmc_vol_daily`):
  - Parkinson estimator (high-low range based)
  - Garman-Klass estimator (OHLC based, more efficient)
  - ATR (Average True Range for intraday volatility)
  - Null handling: forward_fill (smooth volatility estimates across gaps)

- **Technical Indicators** (`cmc_ta_daily`):
  - RSI (7, 14, 21 periods), MACD (12/26/9, 8/17/9), Stochastic (14/3)
  - Bollinger Bands (20/2), ATR (14), ADX (14)
  - Database-driven configuration via `dim_indicators` (JSONB params)
  - Null handling: interpolate (smooth signals across gaps)

- **Unified Feature Store** (`cmc_daily_features`):
  - Materialized table (not view) for ML query performance
  - LEFT JOINs for graceful degradation (optional sources return NULL when missing)
  - Incremental refresh via watermark tracking (MIN of all source table watermarks)
  - Includes EMA pivot (9, 10, 21, 50, 200 periods) from `cmc_ema_multi_tf_u` for 1D timeframe

**Design decision**: Three null handling strategies configured per feature type in `dim_features`. Outlier detection via z-score (default 4 sigma) and IQR (default 1.5x) methods, flag but keep approach for transparency.

### 3. Signal System

Database-driven signal generation with reproducibility guarantees:

- **Signal Configuration** (`dim_signals`):
  - JSONB params enable adding strategies without code changes
  - Example: `{"fast_period": 9, "slow_period": 21, "rsi_threshold": 30}`
  - Three signal types: ema_crossover, rsi_mean_revert, atr_breakout

- **Signal Tables** (separate by type):
  - `cmc_signals_ema_crossover`: Fast/slow EMA crossover signals
  - `cmc_signals_rsi_mean_revert`: RSI oversold/overbought reversals
  - `cmc_signals_atr_breakout`: Donchian channel + ATR expansion breakouts

- **SignalStateManager**:
  - Tracks open positions and dirty windows per `(id, signal_type, signal_id)`
  - Extends FeatureStateManager pattern for consistent state tracking
  - FIFO position matching: exit signals match oldest open position first

- **Feature Hashing for Reproducibility**:
  - SHA256 hash (first 16 chars) of feature values at signal generation
  - Explicit column list for hash stability: `['ts', 'close', 'fast_ema', 'slow_ema', 'rsi_14', 'atr_14']`
  - Triple-layer reproducibility: deterministic timestamp queries + feature hashing + version tracking
  - Batch-level hash computation (once per asset batch, not per record) for 10-100x efficiency

**Design decision**: Feature snapshot at entry captured in JSONB for backtest self-containment. Backtest from stored signals (not on-the-fly generation) for reproducibility and auditability.

### 4. Memory System

Persistent context for AI orchestration:

- **Mem0 + Qdrant Architecture**:
  - Mem0 provides logic layer (fact refinement, conflict detection, updates)
  - Qdrant provides vector storage (server mode with Docker for persistence)
  - OpenAI text-embedding-3-small (1536-dim) for consistency with existing 3,763 memories

- **Memory Operations**:
  - `add()`: Insert with LLM-powered conflict detection (`infer=True` by default)
  - `search()`: Semantic search with 0.7 similarity threshold (returns `{'results': [...]}` dict)
  - `update()`: Metadata updates (last_verified, deprecated_since) with ISO 8601 timestamps
  - `get_all()`: Bulk retrieval for migration and health checks

- **Conflict Resolution**:
  - GPT-4o-mini for context-aware conflict detection (26% accuracy improvement over rules)
  - Similarity threshold 0.85 for high-confidence conflicts (reduces false positives)
  - Metadata scoping: same fact with different metadata (e.g., asset_class) not flagged
  - JSONL audit log (`conflict_log.jsonl`) for append-only conflict history

- **Health & Maintenance**:
  - 90-day staleness threshold: memories not verified in 90+ days flagged for review
  - Age distribution buckets: 0-30d, 30-60d, 60-90d, 90+d for health visibility
  - Non-destructive by default: `flag_stale_memories(dry_run=True)` prevents accidental deprecation
  - REST API endpoints: `/api/v1/memory/search`, `/api/v1/memory/health`, `/api/v1/memory/health/stale`

**Design decision**: Qdrant server mode (localhost:6333) for production with Docker volume mount. All 3,763 memories verified persisting across restarts. `QDRANT_SERVER_MODE=true` environment variable controls server vs embedded mode.

### 5. Orchestrator

Multi-platform AI coordination with cost optimization:

- **Platform Adapters**:
  - `AsyncBasePlatformAdapter`: ABC pattern for code reuse (utility methods shared)
  - Claude, ChatGPT, Gemini adapters extend base with platform-specific execution
  - Task ID format: `platform_yyyymmdd_uuid8` for uniqueness and traceability

- **Routing & Cost Optimization**:
  - **COST_TIERS**: Gemini free (tier 1) → subscriptions (tier 2) → paid APIs (tier 3)
  - `route_cost_optimized()`: Cost-first routing with automatic fallback on quota exhaustion
  - Advisory platform hints honored if quota available, fallback to cost tiers otherwise
  - Quota checked BEFORE API call (fail-fast pattern prevents wasted calls)

- **Quota Management**:
  - Request-based tracking for Gemini (1500 requests/day free tier)
  - Token-based tracking for OpenAI/Anthropic
  - Reservation system: `check_and_reserve()` → execute → `release_and_record()`
  - Alert thresholds: 50% (daily checkpoint), 80% (warning), 90% (urgent)
  - Quota released on failure/cancellation to prevent leakage

- **Parallel Execution**:
  - Python 3.11+ TaskGroup for fail-independent execution via ExceptionGroup
  - Semaphore for concurrency control (default 10 concurrent tasks, configurable)
  - Adaptive concurrency scaling: `min(max_concurrent, available_quota // 2)` with minimum of 1
  - Result ordering preservation: Results[i] corresponds to Tasks[i] regardless of completion order

- **Error Handling & Retry**:
  - Tenacity for exponential backoff (1s → 32s with 3s jitter)
  - Retry on RateLimitError, APIError, timeout (max 3 retries)
  - Platform fallback routing: try all platforms in COST_TIERS order on failure
  - Error classification: retryable vs non-retryable (fail-fast on auth/quota exhausted)

- **Task Handoffs**:
  - Hybrid pattern: full context in memory with unique ID, brief summary (max 500 chars) inline
  - Task A → `create_handoff()` → Memory storage → Task B → `load_handoff_context()`
  - Fail-fast memory lookup: raises RuntimeError if context not found
  - ChainTracker for genealogy: child inherits parent's chain_id or creates new one

**Design decision**: Default model gpt-4o-mini for cost efficiency ($0.15/$0.60 per 1M tokens vs gpt-4 $30/$60 - 20x cost savings). Pending tasks as asyncio.Task enables status tracking and cancellation.

### 6. Observability

PostgreSQL-backed observability for SQL queryability:

- **Metrics** (`observability.metrics`):
  - Month-partitioned by `recorded_at` for scalability with high-frequency recording
  - Columns: `metric_id`, `correlation_id`, `metric_name`, `value`, `tags` (JSONB), `recorded_at`
  - Example metrics: pipeline execution time, quota usage, signal counts

- **Traces** (`observability.traces`):
  - 32-char hex correlation IDs (OpenTelemetry trace context when available, UUID fallback)
  - Columns: `trace_id`, `correlation_id`, `operation`, `start_time`, `end_time`, `status`, `metadata` (JSONB)
  - Cross-system request tracing via correlation IDs

- **Workflow State** (`observability.workflow_state`):
  - Columns: `workflow_id`, `correlation_id`, `type`, `phase`, `status`, `created_at`, `updated_at`, `metadata` (JSONB)
  - 8-column results for workflow state queries (8-tuple return format)

- **Health Checks**:
  - Kubernetes probe pattern: liveness (process alive), readiness (dependencies healthy), startup (initialized)
  - Nested health check details: `details['checks']['database']` for organized component status
  - Manual `startup_complete` flag: `HealthChecker.startup()` returns status but caller must set property

- **Alerts**:
  - Telegram for immediate notification + database for historical tracking
  - Dual delivery pattern: both attempted on every alert with graceful degradation
  - Severity escalation: integration failures CRITICAL after >3 errors, resource exhaustion CRITICAL at >=95%
  - Baseline + percentage threshold: p50 baseline from last 7 days, trigger when current >2x baseline

**Design decision**: PostgreSQL instead of external observability tools for SQL queryability and simpler deployment. Graceful OpenTelemetry degradation: tracing works without `opentelemetry-api` via no-op classes.

---

## Data Flow

### End-to-End Pipeline

```
1. Price Data (cmc_price_histories7)
        │
        v
2. EMA Calculation (cmc_ema_multi_tf_u)
   - Query dim_timeframe for timeframe definitions
   - Compute EMAs for 1D-365D timeframes
   - Align to trading or calendar schedule per dim_sessions
        │
        v
3. Feature Computation (parallel execution)
   ├─> Returns (cmc_returns_daily)
   ├─> Volatility (cmc_vol_daily)
   └─> Technical Indicators (cmc_ta_daily)
        │
        v
4. Feature Store (cmc_daily_features)
   - Materialized table with LEFT JOINs
   - EMA pivot (9, 10, 21, 50, 200 periods)
   - Asset class from dim_sessions
        │
        v
5. Signal Generation (cmc_signals_*)
   - Load active signals from dim_signals
   - Compute entry/exit signals
   - Feature snapshot at entry (JSONB)
   - Feature hashing for reproducibility
        │
        v
6. Backtest Execution
   - Read signals from database (not on-the-fly)
   - Clean vs realistic PnL modes (configurable fees/slippage)
   - Atomic transaction for runs/trades/metrics
   - Triple-layer reproducibility verification
        │
        v
7. Observability & Validation
   - Log metrics (execution time, signal counts)
   - Record traces (correlation IDs)
   - Update workflow state
   - Trigger alerts if thresholds exceeded
```

### Incremental Refresh Pattern

All feature tables support incremental refresh via watermark tracking:

1. **Load Watermark**: Query state table for `last_processed_ts` per `(id, feature_type, feature_name)`
2. **Determine Dirty Window**: `WHERE ts > last_processed_ts` for candidate rows
3. **Compute Features**: Apply feature logic to dirty window only
4. **Write Results**: UPSERT to feature table (idempotent)
5. **Update Watermark**: Record new `last_processed_ts` in state table

For composite features (daily_features), use MIN of all source watermarks:

```python
min_watermark = min(
    returns_watermark,
    vol_watermark,
    ta_watermark,
    ema_watermark
)
# Refresh from min_watermark to ensure all sources aligned
```

**Design decision**: Watermarking per alignment_source enables different cadences for trading-aligned vs calendar-aligned timeframes. Idempotency verified via dry-run: running sync twice with same watermark produces identical candidate counts.

---

## Design Decisions

### Vertical Slices Over Horizontal Layers

Traditional N-tier architecture (data → business → presentation) creates coupling and fragility. ta_lab2 uses vertical slices:

- **Feature slice**: dim_features → FeatureStateManager → feature computation → feature table → validation
- **Signal slice**: dim_signals → SignalStateManager → signal generation → signal table → backtest
- **Memory slice**: Mem0 client → Qdrant storage → REST API → health checks

Each slice is independently testable and deployable. Changes within a slice don't ripple across the system.

### Database-Driven Configuration

Avoid code changes for new indicators, signals, or timeframes:

- **dim_indicators**: JSONB params for RSI (7,14,21), MACD (12/26/9, 8/17/9), etc.
- **dim_signals**: JSONB params for signal strategies (fast/slow periods, thresholds)
- **dim_timeframe**: Add new timeframes without code changes (just INSERT to table)

**Rationale**: Faster iteration, fewer deployments, configuration versioned in database with timestamp tracking.

### Feature Hashing for Reproducibility

Backtests must be reproducible. Three-layer approach:

1. **Deterministic timestamp queries**: `WHERE ts BETWEEN start AND end` with explicit ORDER BY
2. **Feature hashing**: SHA256 of feature values at signal generation (first 16 chars)
3. **Version tracking**: Signal params hash in backtest metadata

If feature hash differs between backtest runs, data changed. Alert and investigate before comparing PnL.

**Rationale**: Scientific rigor. Can't trust backtest results if underlying data silently changes.

### Three-Tier Test Pattern

Different tests need different infrastructure:

- **real_deps**: Full infrastructure (PostgreSQL, Qdrant, OpenAI) for integration tests
- **mixed_deps**: Real database/Qdrant, mocked AI APIs for faster feedback
- **mocked_deps**: All external dependencies mocked for CI/CD

Session-scoped `db_engine`, function-scoped `db_session` with transaction rollback for isolation.

**Rationale**: CI runs fast (mocked_deps), developers can test locally (mixed_deps), production validation uses real_deps.

### PostgreSQL-Backed Observability

External observability tools (Datadog, New Relic) add cost and complexity. PostgreSQL provides:

- SQL queryability: `SELECT * FROM observability.metrics WHERE metric_name = 'pipeline_duration' AND recorded_at > NOW() - INTERVAL '7 days'`
- Historical analysis: month-partitioned metrics enable long-term trend analysis
- No additional infrastructure: already running PostgreSQL for data

**Rationale**: Simpler deployment, lower cost, leverage existing SQL skills.

### Cost-Optimized AI Routing

Free tiers first, paid APIs last:

1. **Gemini free tier** (1500 requests/day): Tier 1 priority
2. **Subscriptions** (Claude Pro, ChatGPT Plus): Tier 2 priority
3. **Paid APIs** (pay-per-token): Tier 3 fallback

Quota checked before every API call. Adaptive concurrency scales down as quota depletes.

**Rationale**: Maximize usage of free/subscription tiers before incurring variable costs. 20x cost savings (gpt-4o-mini vs gpt-4).

---

## Quality Attributes

### Reproducibility

Triple-layer verification ensures backtest reproducibility:

1. **Deterministic queries**: Explicit timestamp ranges and ORDER BY clauses
2. **Feature hashing**: SHA256 of feature values detects data changes
3. **Version tracking**: Signal params hash in backtest metadata

Validation: `validate_backtest_reproducibility()` runs identical backtest twice, compares PnL/metrics/trade counts with tolerance (default 1e-10).

Three validation modes: strict (fail on hash mismatch), warn (log warning, proceed), trust (skip validation).

### Extensibility

Database-driven configuration enables new strategies without code changes:

- Add new indicator: INSERT to `dim_indicators` with JSONB params
- Add new signal: INSERT to `dim_signals` with JSONB params
- Add new timeframe: INSERT to `dim_timeframe` with timeframe definition

CLI flags enable selective computation: `--indicators RSI,MACD` filters which indicators to compute for debugging.

### Testability

Three-tier test infrastructure supports different test contexts:

- **49 validation tests** use `mocked_deps` (no infrastructure required)
- **Integration tests** use `mixed_deps` (real DB, mocked AI APIs)
- **E2E tests** use `real_deps` (full infrastructure)

Graceful test skip pattern: tests skip with informative messages when infrastructure unavailable instead of hard failures.

pytest markers: `real_deps`, `mixed_deps`, `mocked_deps`, `integration`, `observability`, `validation`, `validation_gate`, `slow`.

### Performance

Optimizations for production workloads:

- **Batch-level feature hashing**: Compute hash once per asset batch (not per record) for 10-100x efficiency
- **Materialized feature store**: `cmc_daily_features` table (not view) for ML query performance
- **Incremental refresh**: Watermark-based dirty window detection processes only new data
- **Parallel execution**: Returns/vol/ta run concurrently (ThreadPoolExecutor max_workers=3) for 3x speedup
- **Month-partitioned metrics**: observability.metrics partitioned by `recorded_at` for high-frequency recording scalability

### Observability

PostgreSQL-backed observability for operational visibility:

- **Metrics**: Pipeline execution time, quota usage, signal counts
- **Traces**: Correlation IDs for cross-system request tracing
- **Workflow State**: 8-column results for workflow queries
- **Health Checks**: Kubernetes probe pattern (liveness, readiness, startup)
- **Alerts**: Telegram + database dual delivery with severity escalation

Graceful degradation: observability works without `opentelemetry-api` via no-op classes.

---

## References

- **Implementation Details**: [ARCHITECTURE.md](../ARCHITECTURE.md) - Package structure, module organization, data flows
- **Deployment Guide**: [deployment.md](deployment.md) - Infrastructure setup, environment variables, monitoring
- **Contributing Guide**: [CONTRIBUTING.md](../CONTRIBUTING.md) - Development workflows, branch strategy, PR process
- **Security Policy**: [SECURITY.md](../SECURITY.md) - Vulnerability reporting, credential handling

---

## Appendix: Technology Stack

### Core Runtime

- **Python**: 3.10+ (3.11 recommended for TaskGroup)
- **Data Processing**: pandas, polars, numpy, pyarrow
- **Database**: PostgreSQL 14+ (16 recommended), SQLAlchemy 2.0+, psycopg2-binary
- **Visualization**: matplotlib 3.8+

### AI Orchestrator

- **LLM APIs**: anthropic, openai, google-generativeai
- **Memory**: mem0ai, chromadb, qdrant-client
- **API Framework**: FastAPI, pydantic 2.0+
- **Configuration**: python-dotenv

### Testing & Quality

- **Testing**: pytest 8.0+, pytest-asyncio, pytest-mock, pytest-cov
- **Coverage**: pytest-cov 4.0+ (70% threshold)
- **Linting**: ruff 0.1.5+, mypy 1.8+
- **Benchmarking**: pytest-benchmark, hypothesis

### Observability

- **Tracing**: OpenTelemetry (optional, graceful degradation)
- **Alerts**: Telegram Bot API
- **Metrics**: PostgreSQL observability schema (month-partitioned)
- **Health Checks**: Kubernetes probe pattern

---

*Last updated: 2026-02-01*
*Version: 0.4.0 release candidate*
