# ta_lab2 Architecture

**Version:** 0.4.0
**Last Updated:** 2026-02-01

This document explains how the `ta_lab2` package is organized, how data flows through it, and the architectural decisions behind the v0.4.0 release.

---

## Table of Contents

1. [High-Level Overview](#high-level-overview)
2. [Package Structure](#package-structure)
3. [Database Schema](#database-schema)
4. [Core Systems](#core-systems)
   - [Time Model](#time-model)
   - [Feature Pipeline](#feature-pipeline)
   - [Signal System](#signal-system)
   - [Memory System](#memory-system)
   - [Orchestrator](#orchestrator)
   - [Observability](#observability)
5. [Data Flow](#data-flow)
6. [API Reference](#api-reference)
7. [Design Principles](#design-principles)

---

## High-Level Overview

**ta_lab2** is a multi-timescale technical analysis lab for building features, regimes, signals, and backtests on crypto assets (primarily BTC). The v0.4.0 release transforms it from a research tool into a production-ready quantitative trading infrastructure with AI orchestration capabilities.

**Core Flow:**

```
Data source (CoinMarketCap)
  → Time Model (dim_timeframe, dim_sessions)
  → Feature Pipeline (EMAs, returns, vol, TA indicators)
  → Signal System (crossovers, reversions, breakouts)
  → Backtesting (vectorbt)
  → Observability (metrics, tracing, health)

AI Orchestration (parallel track):
  Memory System (Mem0 + Qdrant) ←→ Orchestrator (Claude, ChatGPT, Gemini)
```

**v0.4.0 Highlights:**
- **Time Model**: 199 timeframes with calendar/trading-day alignment
- **Feature Pipeline**: Multi-stage calculation (EMAs → returns → volatility → TA indicators → daily features)
- **Signal System**: Database-driven configuration with reproducibility validation
- **Memory System**: 3,763+ memories with semantic search and conflict detection
- **Orchestrator**: Cost-optimized routing across 3 LLM platforms with parallel execution
- **Observability**: PostgreSQL-backed metrics, tracing, and health monitoring

---

## Package Structure

Root package: `ta_lab2`

### Top-Level Modules

- **`ta_lab2.cli`**: Command-line entry point (deprecated in favor of component-specific CLIs)
- **`ta_lab2.io`**: Load/save helpers for parquet and database access
- **`ta_lab2.resample`**: Calendar and seasonal binning utilities
- **`ta_lab2.compare`**: Multi-timeframe comparison helpers
- **`ta_lab2.logging_setup`**: Central logging configuration

### Core Subsystems

- **`ta_lab2.features.*`**: Feature engineering (EMAs, returns, volatility, indicators)
- **`ta_lab2.regimes.*`**: Regime classification and policy resolution
- **`ta_lab2.signals.*`**: Trading signal generation and position sizing
- **`ta_lab2.backtests.*`**: Backtest runners (bt.py, vectorbt) and metrics
- **`ta_lab2.analysis.*`**: Performance evaluation and feature importance
- **`ta_lab2.pipelines.*`**: End-to-end workflows (BTC pipeline)
- **`ta_lab2.viz.*`**: Charting and visualization
- **`ta_lab2.tools.ai_orchestrator.*`**: AI orchestration infrastructure (v0.4.0)
- **`ta_lab2.observability.*`**: Production monitoring (v0.4.0)

### Scripts (Operational Entry Points)

- **`ta_lab2.scripts.time.*`**: Time model initialization
- **`ta_lab2.scripts.emas.*`**: EMA calculation and validation
- **`ta_lab2.scripts.features.*`**: Returns, volatility, TA indicator refresh
- **`ta_lab2.scripts.signals.*`**: Signal generation and backtesting
- **`ta_lab2.scripts.pipeline.*`**: Go-forward daily refresh orchestration

---

## Database Schema

### Time Model Tables

**`dim_timeframe`**: Canonical timeframe definitions
- Primary Key: `id` (SERIAL)
- Unique Key: `tf_label` (VARCHAR, e.g., "1D", "7D", "30D")
- Attributes: `tf_days` (NUMERIC), `is_calendar` (BOOLEAN), `is_canonical` (BOOLEAN), `calendar_scheme` (VARCHAR)

**`dim_sessions`**: Trading session schedules per asset class
- Primary Key: `session_id` (SERIAL)
- Unique Key: `session_type` (VARCHAR, e.g., "CRYPTO", "EQUITY")
- Attributes: `asset_class` (VARCHAR), `trading_days_per_week` (INTEGER), `trading_hours_per_day` (NUMERIC)

### Feature Tables

**EMA Tables:**
- `cmc_ema_daily`: Daily EMAs (1D timeframe only)
- `cmc_ema_multi_tf`: Multi-timeframe EMAs (trading-day aligned)
- `cmc_ema_multi_tf_cal`: Multi-timeframe EMAs (calendar-aligned)
- `cmc_ema_multi_tf_v2`: Multi-timeframe EMAs with advanced alignment
- `cmc_ema_multi_tf_cal_anchor`: Calendar-aligned EMAs with anchor points

**Primary Key Pattern:** `(id, ts, tf, period)`
- `id`: Asset ID (foreign key to `cmc_price_histories7.id`)
- `ts`: Bar timestamp (DATE or TIMESTAMP)
- `tf`: Timeframe label (VARCHAR, references `dim_timeframe.tf_label`)
- `period`: EMA span in bars (INTEGER)

**Columns:** `ema`, `d1`, `d2`, `d1_close`, `d2_close`, `roll`

**Returns and Volatility:**
- `cmc_returns_daily`: Bar-to-bar and multi-day returns
  - Primary Key: `(id, ts)`
  - Columns: `ret_1d_pct`, `ret_1d_log`, `ret_2d_pct`, ..., `ret_365d_pct`, `is_outlier`
- `cmc_vol_daily`: Volatility estimators
  - Primary Key: `(id, ts)`
  - Columns: `vol_parkinson`, `vol_garman_klass`, `vol_rogers_satchell`, `vol_atr`, `is_outlier`

**Materialized Feature Store:**
- `cmc_daily_features`: Unified view with all features
  - Primary Key: `(id, ts)`
  - Includes: price OHLCV, EMAs (pivoted), returns, volatility, TA indicators, asset_class

### Signal Tables

**`dim_signals`**: Signal configuration registry
- Primary Key: `signal_id` (SERIAL)
- Attributes: `signal_type` (VARCHAR), `signal_name` (VARCHAR), `params` (JSONB), `is_active` (BOOLEAN)

**Signal Output Tables:**
- `cmc_signals_ema_crossover`: EMA crossover signals
  - Primary Key: `(id, ts, signal_id)`
  - Columns: `signal_type`, `direction`, `signal_state`, `entry_price`, `exit_price`, `feature_version_hash`, `feature_snapshot` (JSONB)
- `cmc_signals_rsi_mean_revert`: RSI mean reversion signals (same schema)
- `cmc_signals_atr_breakout`: ATR breakout signals (same schema + `breakout_type`, `channel_high`, `channel_low`)

**Backtest Tables:**
- `cmc_backtest_runs`: Backtest metadata
  - Primary Key: `run_id` (SERIAL)
  - Columns: `signal_type`, `signal_id`, `feature_version_hash`, `params_hash`, `run_date`, `total_pnl`, `sharpe_ratio`, `win_rate`
- `cmc_backtest_trades`: Trade-level detail
  - Primary Key: `(run_id, trade_id)`
- `cmc_backtest_metrics`: Performance metrics
  - Primary Key: `(run_id, metric_name)`

### State Management Tables

**Pattern:** `{feature_type}_state` tables track watermarks per (id, feature_type, feature_name)
- `cmc_ema_daily_state`, `cmc_ema_multi_tf_state`, `cmc_ema_multi_tf_cal_state`, etc.
- Columns: `id`, `feature_type`, `feature_name`, `watermark_ts`, `last_refresh_ts`, `refresh_status`

### Observability Tables

**`observability.metrics`**: Time-series metrics (month-partitioned)
- Primary Key: `(metric_id, recorded_at)` (partitioned by month)
- Columns: `component`, `metric_name`, `value`, `tags` (JSONB), `recorded_at`

**`observability.traces`**: Request tracing
- Primary Key: `trace_id`
- Columns: `correlation_id`, `span_name`, `start_time`, `end_time`, `status`, `attributes` (JSONB)

**`observability.workflow_state`**: Workflow execution tracking
- Primary Key: `workflow_id`
- Columns: `correlation_id`, `workflow_type`, `phase`, `status`, `created_at`, `updated_at`, `metadata` (JSONB)

**`observability.alerts`**: Alert history
- Primary Key: `alert_id`
- Columns: `alert_type`, `severity`, `component`, `message`, `threshold_value`, `current_value`, `triggered_at`, `resolved_at`

### Views

**`all_emas`**: Logical union of all EMA tables
- Standardizes schema across `cmc_ema_daily`, `cmc_ema_multi_tf`, `cmc_ema_multi_tf_cal`
- Columns: `id`, `ts`, `tf`, `tf_days`, `period`, `ema`, `d1`, `d2`, `d1_close`, `d2_close`, `roll`

**`cmc_price_with_emas`**: Daily OHLCV joined to single EMA layer
- One row per (id, ts) from `cmc_price_histories7`
- Includes: price columns + selected EMA configuration

**`cmc_price_with_emas_d1d2`**: Same as above + EMA derivatives
- Adds: `d1`, `d2`, `d1_close`, `d2_close`, `roll`

---

## Core Systems

### Time Model

**Purpose:** Unified timeframe definitions and trading session calendars for consistent multi-timeframe analysis.

**Components:**
- **dim_timeframe**: 199 timeframes (1D to 365D) with metadata
  - `tf_label`: Human-readable label (e.g., "7D", "30D")
  - `tf_days`: Timeframe length in days (NUMERIC for precision)
  - `is_calendar`: TRUE for calendar-aligned, FALSE for trading-day aligned
  - `is_canonical`: TRUE for canonical bars (official close), FALSE for preview bars
  - `calendar_scheme`: "daily", "weekly", "monthly", etc.
  - `anchor_hour`: Optional hour for intraday anchoring
  - `tf_days_min`, `tf_days_max`: Range for variable-length timeframes
- **dim_sessions**: Trading session schedules
  - CRYPTO: 24/7, 365 days/year
  - EQUITY: Trading days only (exclude weekends/holidays), ~252 days/year

**Alignment Logic:**
- **Calendar-aligned**: Fixed intervals (7D = exactly 7 calendar days)
- **Trading-day aligned**: Counts only trading days per session type
- **Canonical bars**: Official close at end of timeframe
- **Preview bars**: In-between bars for real-time monitoring

**Usage in Features:**
- EMAs query `dim_timeframe` to determine alignment strategy
- Returns and volatility respect session calendars for accurate calculations
- Watermarking uses `tf_days` for incremental refresh windows

**Scripts:**
- `ensure_dim_tables.py`: Idempotent creation of time model tables
- SQL seed files: `010-014` for comprehensive timeframe population

---

### Feature Pipeline

**Purpose:** Multi-stage feature calculation for technical analysis across timeframes.

**Architecture:**

```
Stage 1: EMAs (baseline features)
  ├─ cmc_ema_daily (1D only, fast refresh)
  ├─ cmc_ema_multi_tf (2D-365D, trading-day aligned)
  ├─ cmc_ema_multi_tf_cal (2D-365D, calendar-aligned)
  └─ Views: all_emas (union), cmc_price_with_emas (joined)

Stage 2: Returns (depends on price)
  └─ cmc_returns_daily (1D to 365D lookbacks)

Stage 3: Volatility (depends on price)
  └─ cmc_vol_daily (Parkinson, Garman-Klass, Rogers-Satchell, ATR)

Stage 4: TA Indicators (depends on price, EMAs)
  └─ TAFeature (RSI, MACD, Stochastic, Bollinger, ATR, ADX)

Stage 5: Daily Features (depends on all above)
  └─ cmc_daily_features (materialized table, LEFT JOINs for graceful degradation)
```

**Base Classes:**
- **BaseEMAFeature**: Template method pattern for EMA calculation
  - `compute_for_ids()`: Load → compute → normalize → flag outliers → write
  - State management: Tracks watermarks per (id, tf, period)
- **BaseFeature**: Template for returns, volatility, TA indicators
  - `compute_for_ids()`: Load → null handling → compute → normalize → flag outliers → write
  - Null strategies: skip (returns), forward_fill (vol), interpolate (TA)

**State Management:**
- State tables: `{feature_type}_state` with columns (id, feature_type, feature_name, watermark_ts)
- Incremental refresh: Only recompute from watermark + lookback window
- Atomic writes: Transaction-based to prevent partial updates

**Outlier Detection:**
- Z-score method: Default 4 sigma (normal distributions)
- IQR method: Default 1.5x IQR (robust for skewed data)
- `is_outlier` flag: Marks outliers but preserves original values for analysis

**Normalization:**
- Rolling window z-scores: Default 252 days (1 trading year)
- Handles std=0 with NaN for constant values
- Selective normalization: Only key windows get z-scores to reduce storage

**Parallel Execution:**
- Phase 1 (EMAs) runs first (baseline features)
- Phase 2 (returns, vol, TA) runs concurrently (same dependency on price)
- ThreadPoolExecutor with max_workers=3 for 3x speedup
- Graceful degradation: One table failure doesn't stop pipeline

**Scripts:**
- `run_go_forward_daily_refresh.py`: Orchestrates full pipeline
- `refresh_cmc_emas.py`: Stage 1 (EMAs)
- `returns_feature.py`, `volatility_feature.py`, `ta_feature.py`: Stages 2-4
- `daily_features_refresh.py`: Stage 5 (materialized store)

---

### Signal System

**Purpose:** Database-driven trading signal generation with position lifecycle tracking and reproducibility validation.

**Architecture:**

```
Configuration Layer
  └─ dim_signals (JSONB params for strategies)

Generation Layer
  ├─ EMASignalGenerator (crossovers)
  ├─ RSISignalGenerator (mean reversion)
  └─ ATRSignalGenerator (breakouts)

State Management Layer
  └─ SignalStateManager (position tracking, dirty windows)

Output Layer
  ├─ cmc_signals_ema_crossover
  ├─ cmc_signals_rsi_mean_revert
  └─ cmc_signals_atr_breakout

Validation Layer
  └─ Feature hashing for reproducibility
```

**Configuration (dim_signals):**
- JSONB params enable adding strategies without code changes
- Example: `{"fast_period": 9, "slow_period": 21, "rsi_period": 14}`
- `is_active` flag for toggling strategies without deletion

**Signal Generation:**
- **EMASignalGenerator**:
  - Load EMA pairs from `dim_signals`
  - Detect crossovers (fast > slow → LONG, fast < slow → SHORT)
  - Capture feature snapshot at entry (close, fast_ema, slow_ema, rsi_14, atr_14)
  - FIFO position matching for exits
- **RSISignalGenerator**:
  - Oversold (<30) → LONG, Overbought (>70) → SHORT
  - Mean reversion logic with configurable thresholds
- **ATRSignalGenerator**:
  - Donchian channel breakouts + ATR expansion
  - Breakout type classification: channel_break, atr_expansion, or both
  - Channel levels in feature snapshot for audit trail

**Position Tracking (SignalStateManager):**
- Extends `FeatureStateManager` pattern
- Tracks open positions per (id, signal_type, signal_id)
- `load_open_positions()`: Queries signal table (not state table) for full context
- Dirty window management: Only recompute from watermark
- State columns: `signal_state` (OPEN, CLOSED), `entry_ts`, `exit_ts`, `entry_price`, `exit_price`

**Feature Hashing for Reproducibility:**
- SHA256 hash (first 16 chars) of feature columns
- Explicit column order for stability across runs
- Batch-level computation: Once per asset (10-100x efficiency vs per-row)
- Hash mismatch detection: Prevents stale backtest comparisons
- Example: `feature_version_hash = "a3f2e9b1c4d6..."`

**Feature Snapshot:**
- JSONB column captures features at signal entry
- Self-contained for backtest validation
- Example: `{"close": 45000, "ema_fast": 44800, "ema_slow": 44200, "rsi_14": 65, "atr_14": 1200}`

**Scripts:**
- `run_all_signal_refreshes.py`: Orchestrates all signal types
- `ema_crossover_refresh.py`, `rsi_mean_revert_refresh.py`, `atr_breakout_refresh.py`: Individual generators

---

### Memory System

**Purpose:** AI context persistence with semantic search, conflict detection, and health monitoring.

**Architecture:**

```
Logic Layer
  └─ MemoryService (Mem0 wrapper)
       ├─ add_memory()
       ├─ search_memory()
       ├─ update_memory()
       └─ delete_memory()

Vector Storage Layer
  └─ Qdrant (localhost:6333 in server mode)
       └─ Docker container with volume mount

Embedding Layer
  └─ OpenAI text-embedding-3-small (1536-dim)

API Layer
  └─ FastAPI endpoints (/api/v1/memory/*)
       ├─ POST /add
       ├─ GET /search
       ├─ GET /health
       └─ GET /health/stale

Conflict Detection Layer
  └─ Mem0 infer=True (GPT-4o-mini)
       └─ JSONL audit log (conflict_log.jsonl)
```

**Mem0 Integration:**
- `mem0ai==1.0.2`: Logic layer for memory operations
- `infer=True`: LLM-powered conflict detection (26% accuracy improvement over rules)
- Similarity threshold: 0.85 for high-precision conflict detection
- Metadata scoping: Same fact with different metadata (e.g., asset_class) not flagged

**Qdrant Backend:**
- Server mode: Docker container (qdrant/qdrant) with volume mount
- Persistent storage: `/qdrant/storage` volume for durability
- Auto-restart: `--restart always` for production reliability
- Port: 6333 (localhost only, not exposed externally)
- Environment variable: `QDRANT_SERVER_MODE=true` (default)

**Embeddings:**
- OpenAI `text-embedding-3-small`: 1536-dimensional embeddings
- Chosen for consistency with existing 3,763 memories
- Batch size: 50 for efficiency (balances API calls vs memory usage)
- Dimension validation: Enforced before insertion to prevent corruption

**Memory Operations:**
- **add_memory(text, metadata)**: Add new memory with optional metadata
  - Returns: memory_id (UUID)
  - Conflict detection: Automatic via infer=True
- **search_memory(query, limit, threshold)**: Semantic search
  - Returns: `{'results': [{'id', 'text', 'metadata', 'score'}]}`
  - Default threshold: 0.7 for relevance filtering
  - Distance to similarity conversion: `similarity = 1 - distance`
- **update_memory(memory_id, text)**: Update existing memory
  - Preserves metadata, updates text and embedding
- **delete_memory(memory_id)**: Delete memory (soft deletion via deprecated_since)

**Metadata Scoping:**
- Context-dependent truths: Different values for different contexts
- Example: "Default EMA period is 21" with metadata `{"asset_class": "crypto"}` vs `{"asset_class": "equity"}`
- Prevents false conflict detection across contexts

**Staleness Tracking:**
- `last_verified` timestamp (ISO 8601 format)
- 90-day staleness threshold per MEMO-06
- Age distribution buckets: 0-30d, 30-60d, 60-90d, 90+d
- Verification refresh pattern: Human confirms accuracy, system updates timestamp

**Health Monitoring:**
- `/health`: Overall status with nested component checks
  - `details['checks']['qdrant']`: Vector store connectivity
  - `details['checks']['embeddings']`: OpenAI API availability
- `/health/stale`: List memories not verified in 90+ days with age breakdown

**REST API (FastAPI):**
- Factory pattern: `create_memory_api()` returns configured FastAPI app
- Lazy imports: Endpoints import functions inside to avoid circular dependencies
- Pydantic validation: Field constraints with clear error messages
- CORS enabled: For cross-platform access (Claude, ChatGPT, Gemini)

**Conflict Resolution:**
- JSONL audit log: Append-only `conflict_log.jsonl` for grep-friendly tracking
- Log format: `{"timestamp": "...", "memory_id": "...", "conflict_type": "...", "resolution": "..."}`
- Non-destructive by default: Conflicts logged but not auto-resolved

**Migration from ChromaDB:**
- Phase 2: ChromaDB (3,763 memories)
- Phase 3: Qdrant (Mem0 requirement, ChromaDB support not yet in mem0ai 1.0.2)
- Metadata migration: `created_at`, `last_verified` to ISO 8601 format
- 95% success rate threshold for migration validation

---

### Orchestrator

**Purpose:** Multi-platform AI coordination with cost-optimized routing, parallel execution, and AI-to-AI handoffs.

**Architecture:**

```
Orchestrator Core
  ├─ Platform Adapters
  │    ├─ ClaudeAdapter (AsyncBasePlatformAdapter)
  │    ├─ ChatGPTAdapter (AsyncBasePlatformAdapter)
  │    └─ GeminiAdapter (AsyncBasePlatformAdapter)
  ├─ Cost Optimizer
  │    └─ route_cost_optimized() (Platform enum priority tiers)
  ├─ Quota Manager
  │    ├─ QuotaTracker (request-based tracking)
  │    └─ check_and_reserve() / release_and_record()
  ├─ Parallel Executor
  │    ├─ TaskGroup (Python 3.11+, fail-independent)
  │    └─ Semaphore (concurrency control, default 10)
  └─ Handoff Manager
       ├─ create_handoff_context() (store in memory)
       └─ load_handoff_context() (retrieve from memory)

Supporting Infrastructure
  ├─ CostTracker (cost per platform, total spend)
  ├─ ChainTracker (task genealogy, in-memory)
  └─ Retry Logic (exponential backoff, platform fallback)
```

**Platform Adapters (AsyncBasePlatformAdapter):**
- Abstract base class pattern (not protocol) for code reuse
- Task ID format: `{platform}_{yyyymmdd}_{uuid8}` for traceability
- Default timeout: 300 seconds (configurable via TaskConstraints)
- Streaming support: `StreamingResult` saves partial results on cancellation
- Status tracking: Pending tasks as `asyncio.Task` for RUNNING/COMPLETED/CANCELLED
- **ClaudeAdapter**:
  - Model: `claude-sonnet-3-5` (gpt-4-class reasoning)
  - Retry: Tenacity with exponential backoff (1s → 32s, 3s jitter, 5 attempts)
  - Error classification: Retryable (rate limits, timeouts, 5xx) vs non-retryable (auth, quota)
- **ChatGPTAdapter**:
  - Model: `gpt-4o-mini` (default for cost efficiency: $0.15/$0.60 per 1M tokens)
  - Same retry logic as Claude
- **GeminiAdapter**:
  - Model: `gemini-pro`
  - Free tier: 1500 requests/day (request-based quota, not tokens)

**Cost-Optimized Routing:**
- Priority tiers (Platform enum):
  1. Gemini free tier (priority=1, lowest cost)
  2. Subscriptions (priority=2, ChatGPT Plus, Claude Pro)
  3. Paid APIs (priority=3, OpenAI/Anthropic pay-as-you-go)
- `route_cost_optimized()`: Try platforms in order, RuntimeError on exhaustion
- Advisory platform hints: Honored if quota available, automatic fallback otherwise
- Platform fallback: Each platform gets full retry cycle before moving to next

**Quota Management (QuotaTracker):**
- Request-based tracking for Gemini (1500/day), token-based for others
- Check BEFORE API call (fail-fast pattern)
- Reservation pattern: `check_and_reserve()` → execute → `release_and_record()`
- Auto-release on failure/cancellation (prevents quota leakage)
- Alert thresholds: 50%, 80%, 90% with `warn_quota_threshold()`
- Reservation auto-release on usage: No manual release needed

**Parallel Execution:**
- **TaskGroup** (Python 3.11+): Native fail-independent semantics via ExceptionGroup
- **Semaphore**: Default 10 concurrent tasks (configurable)
- Adaptive concurrency scaling: `min(max_concurrent, available_quota // 2)` with minimum of 1
- Result ordering preservation: `Results[i]` corresponds to `Tasks[i]` regardless of completion order

**Handoff Pattern (Pointer + Summary):**
- Full context stored in memory with unique ID
- Brief summary (max 500 chars) passed inline for quick reference
- `create_handoff_context(full_context, brief_summary)`: Returns memory_id
- `load_handoff_context(memory_id)`: Fail-fast if not found (RuntimeError)
- Lazy imports for memory functions to avoid circular dependencies
- Task genealogy: `ChainTracker` maintains parent-child relationships (chain_id inheritance)

**Retry Logic:**
- MAX_RETRIES=3 with exponential backoff (1s, 2s, 4s)
- Retryable errors: Rate limits, timeouts, 5xx server errors
- Non-retryable errors: Auth failures, quota exhausted (fail-fast)
- Before sleep logging: Records retry attempt for debugging

**CLI:**
- Delegation pattern: Main CLI delegates to orchestrator CLI via argv passthrough
- Commands: `task`, `batch`, `quota`, `cost`
- Lazy imports: QuotaTracker, CostTracker imported inside cmd_* functions
- JSON output truncation: Batch results truncate to 500 chars for readability

---

### Observability

**Purpose:** PostgreSQL-backed production monitoring with correlation ID tracing and alert delivery.

**Architecture:**

```
Metrics Layer
  └─ observability.metrics (month-partitioned)
       └─ MetricsCollector.record()

Tracing Layer
  ├─ observability.traces
  └─ Correlation IDs (32-char hex)
       ├─ OpenTelemetry trace context (when available)
       └─ UUID fallback

Health Check Layer
  ├─ Kubernetes probe pattern
  │    ├─ Liveness (process alive)
  │    ├─ Readiness (dependencies healthy)
  │    └─ Startup (initialized)
  └─ HealthChecker with nested details

Workflow Tracking Layer
  └─ observability.workflow_state
       └─ 8-tuple: (workflow_id, correlation_id, type, phase, status, created_at, updated_at, metadata)

Alert Layer
  ├─ observability.alerts
  └─ Dual delivery: Telegram + database
```

**Metrics Storage:**
- Table: `observability.metrics` (month-partitioned by `recorded_at`)
- Schema: `(metric_id SERIAL, component VARCHAR, metric_name VARCHAR, value NUMERIC, tags JSONB, recorded_at TIMESTAMP)`
- Partitioning: Monthly partitions for scalability with high-frequency recording
- Example: `{"component": "feature_pipeline", "metric_name": "ema_refresh_duration", "value": 45.2, "tags": {"feature": "ema", "tf": "7D"}}`

**Tracing:**
- Correlation IDs: 32-char hex for cross-system request tracing
- OpenTelemetry integration: Uses trace context when available (graceful degradation without `opentelemetry-api`)
- Propagation: Through headers (`X-Correlation-ID`) and logs
- Trace storage: `observability.traces` with span_name, start_time, end_time, status, attributes (JSONB)

**Health Checks (Kubernetes Pattern):**
- **Liveness** (`/health/liveness`): Process alive (always 200 after startup)
- **Readiness** (`/health/readiness`): Dependencies healthy (database, memory service, external APIs)
- **Startup** (`/health/startup`): Initialization complete (dim_timeframe/dim_sessions exist)
- Nested details structure: `details['checks']['database']` for organized component status
- Manual startup flag: `HealthChecker.startup()` returns status but doesn't set property (caller must set explicitly)

**Workflow Tracking:**
- Table: `observability.workflow_state`
- 8-column results: `(workflow_id, correlation_id, type, phase, status, created_at, updated_at, metadata)`
- Query pattern: `SELECT * FROM observability.workflow_state WHERE correlation_id = ? ORDER BY created_at`

**Alert Thresholds:**
- **Baseline + percentage approach**: p50 from last 7 days, trigger when current >2x baseline
- **Strict data quality**: 0% tolerance for gaps/alignment/rowcount issues (crypto 24/7 data)
- **Severity escalation**: Integration failures CRITICAL after >3 errors, resource exhaustion CRITICAL at ≥95%
- Example thresholds:
  - Gap detection: >0 missing bars → CRITICAL
  - Alignment: >0 misaligned bars → CRITICAL
  - Rowcount: >5% deviation → WARNING
  - EMA NULL values: >0 NULL EMAs → CRITICAL

**Alert Delivery:**
- **Telegram**: Immediate notification via Telegram Bot API
  - Environment variable: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
  - Graceful degradation: Log warning if not configured, don't block validation
- **Database**: Historical tracking via `observability.alerts` table
- Dual delivery pattern: Both attempted on every alert, both must succeed for acknowledgment

**Graceful Degradation:**
- OpenTelemetry: Works without `opentelemetry-api` via no-op classes
- Telegram: Validation works without alerts (just logs warnings)
- Observability doesn't block development or core operations

---

## Data Flow

### A. Daily Feature Refresh Pipeline

```
1. Initialize
   └─ ensure_dim_tables.py (dim_timeframe, dim_sessions)

2. Stage 1: EMAs (baseline features)
   └─ refresh_cmc_emas.py
        ├─ Query state: cmc_ema_daily_state, cmc_ema_multi_tf_state
        ├─ Load price: cmc_price_histories7 (from watermark - lookback)
        ├─ Compute: EMAs for periods 5, 9, 10, 21, 50, 100, 200
        ├─ Write: cmc_ema_daily, cmc_ema_multi_tf, cmc_ema_multi_tf_cal
        └─ Update state: watermark_ts, last_refresh_ts

3. Stage 2-4: Returns, Volatility, TA (parallel)
   ├─ returns_feature.py → cmc_returns_daily
   ├─ volatility_feature.py → cmc_vol_daily
   └─ ta_feature.py → TAFeature (inline computation, not stored separately)

4. Stage 5: Materialized feature store
   └─ daily_features_refresh.py → cmc_daily_features
        ├─ Query watermarks: MIN of all source tables
        ├─ LEFT JOIN: EMAs (pivoted), returns, volatility, TA
        ├─ Write: Unified row per (id, ts)
        └─ Graceful degradation: NULL columns for missing sources

5. Validation (optional, --validate flag)
   └─ validate_feature_pipeline.py
        ├─ Gap detection (via dim_sessions)
        ├─ Rowcount tolerance (5%)
        ├─ NULL ratio threshold (10%)
        └─ Cross-table consistency (returns vs price delta)
```

### B. Signal Generation and Backtesting

```
1. Generate Signals
   └─ run_all_signal_refreshes.py
        ├─ Load config: dim_signals (WHERE is_active = TRUE)
        ├─ Generate:
        │    ├─ ema_crossover_refresh.py → cmc_signals_ema_crossover
        │    ├─ rsi_mean_revert_refresh.py → cmc_signals_rsi_mean_revert
        │    └─ atr_breakout_refresh.py → cmc_signals_atr_breakout
        └─ Feature hashing: SHA256 for reproducibility

2. Run Backtest
   └─ run_backtest.py
        ├─ Load signals: FROM cmc_signals_{type} WHERE signal_id = ?
        ├─ Load features: cmc_daily_features (for price data)
        ├─ Vectorbt: Portfolio.from_signals()
        ├─ Metrics: Sharpe, Sortino, Calmar, VaR, CVaR, profit factor, win rate
        ├─ Write:
        │    ├─ cmc_backtest_runs (run metadata)
        │    ├─ cmc_backtest_trades (trade-level detail)
        │    └─ cmc_backtest_metrics (performance metrics)
        └─ Validation: compare_backtest_runs() for reproducibility

3. Validate Reproducibility
   └─ validate_backtest_reproducibility.py
        ├─ Run identical backtest twice
        ├─ Compare: PnL, metrics, trade counts
        ├─ Tolerance: 1e-10 (strict)
        └─ Report: Pass/fail with detailed diff
```

### C. AI Orchestration Workflow

```
1. Memory Query
   └─ MemoryService.search("How are EMAs calculated?")
        ├─ Embed query: OpenAI text-embedding-3-small
        ├─ Vector search: Qdrant (similarity threshold 0.7)
        └─ Return: Top 5 memories with scores

2. Task Execution
   └─ Orchestrator.execute_task(task)
        ├─ Quota check: QuotaTracker.check_and_reserve()
        ├─ Route: route_cost_optimized() (Gemini → ChatGPT → Claude)
        ├─ Execute: platform_adapter.execute(task)
        │    ├─ Retry: Exponential backoff (1s → 32s, 5 attempts)
        │    └─ Fallback: Try next platform on failure
        ├─ Release: QuotaTracker.release_and_record()
        └─ Record: CostTracker, MetricsCollector

3. Parallel Execution
   └─ Orchestrator.execute_batch(tasks, max_concurrent=10)
        ├─ Semaphore: Control concurrency
        ├─ TaskGroup: Fail-independent execution
        ├─ Adaptive scaling: min(max_concurrent, available_quota // 2)
        └─ Preserve order: Results[i] ↔ Tasks[i]

4. AI-to-AI Handoff
   └─ Task A → Task B
        ├─ Task A: create_handoff_context(full_context, brief_summary)
        │    └─ MemoryService.add(full_context) → memory_id
        ├─ Orchestrator: Spawn Task B with memory_id
        └─ Task B: load_handoff_context(memory_id)
             └─ MemoryService.get_by_id(memory_id) → full_context
```

### D. Observability and Health Monitoring

```
1. Metrics Collection
   └─ MetricsCollector.record("ema_refresh_duration", 45.2, tags={"feature": "ema"})
        └─ INSERT INTO observability.metrics (component, metric_name, value, tags, recorded_at)

2. Tracing
   └─ @record_trace("ema_calculation")
        ├─ Generate correlation_id (OpenTelemetry trace context or UUID)
        ├─ Start span: Record start_time
        ├─ Execute function
        ├─ End span: Record end_time, status
        └─ INSERT INTO observability.traces

3. Health Checks
   └─ HealthChecker.readiness()
        ├─ Check database: SELECT 1 FROM dim_timeframe LIMIT 1
        ├─ Check memory: MemoryService.health_check()
        ├─ Check Qdrant: Qdrant client ping
        └─ Return: HealthStatus(is_healthy, details)

4. Alert Delivery
   └─ AlertManager.send_alert(alert)
        ├─ INSERT INTO observability.alerts
        ├─ Telegram: POST to https://api.telegram.org/bot{token}/sendMessage
        └─ Log: alert_sent.log
```

---

## API Reference

### Memory API (FastAPI)

**Base URL:** `http://localhost:8000/api/v1/memory`

**Endpoints:**

- `POST /add`: Add new memory
  - Request: `{"text": "...", "metadata": {...}}`
  - Response: `{"memory_id": "uuid"}`
- `GET /search`: Semantic search
  - Query params: `query`, `limit` (default 5), `threshold` (default 0.7)
  - Response: `{"results": [{"id": "...", "text": "...", "metadata": {...}, "score": 0.85}]}`
- `PUT /update/{memory_id}`: Update existing memory
  - Request: `{"text": "..."}`
  - Response: `{"memory_id": "uuid"}`
- `DELETE /delete/{memory_id}`: Delete memory
  - Response: `{"memory_id": "uuid"}`
- `GET /health`: Overall health status
  - Response: `{"status": "healthy", "details": {"checks": {"qdrant": "ok", "embeddings": "ok"}}}`
- `GET /health/stale`: List stale memories
  - Query params: `threshold_days` (default 90)
  - Response: `{"stale_memories": [{"id": "...", "age_days": 120}]}`

### Orchestrator CLI

**Entry point:** `python -m ta_lab2.tools.ai_orchestrator.cli`

**Commands:**

- `task <prompt> [--platform gemini|chatgpt|claude]`: Execute single task
- `batch <tasks_json> [--parallel N]`: Execute batch with parallel execution
- `quota status`: Check quota status across platforms
- `quota reset <platform>`: Reset quota for platform (admin only)
- `cost report [--platform P] [--start-date D] [--end-date D]`: Generate cost report

### Health Check Endpoints

**Base URL:** `http://localhost:8000/health`

**Endpoints:**

- `GET /liveness`: Process alive (200 after startup)
- `GET /readiness`: Dependencies healthy (database, memory, APIs)
- `GET /startup`: Initialization complete (dim tables exist)

### Feature Refresh Scripts

**Pattern:** `python -m ta_lab2.scripts.{category}.{script_name} [--ids all|<comma-separated>] [--force]`

**Examples:**

- `python -m ta_lab2.scripts.emas.refresh_cmc_emas --ids all`
- `python -m ta_lab2.scripts.features.returns_feature refresh --all`
- `python -m ta_lab2.scripts.signals.run_all_signal_refreshes`
- `python -m ta_lab2.scripts.pipeline.run_go_forward_daily_refresh --validate`

---

## Design Principles

### 1. Database-Driven Configuration

**Principle:** Configuration belongs in the database, not code.

**Examples:**
- `dim_timeframe`: Timeframe definitions (no hardcoded timeframe lists)
- `dim_signals`: Signal parameters (add new strategies via INSERT, not code changes)
- `dim_indicators`: TA indicator params (enable/disable indicators via is_active flag)

**Benefits:**
- Add new configurations without redeploying code
- Query configuration history via SQL
- Audit trail for configuration changes

### 2. State Management for Incremental Refresh

**Principle:** Track watermarks per entity to enable efficient incremental updates.

**Pattern:** `{feature_type}_state` tables with columns (id, feature_type, feature_name, watermark_ts)

**Examples:**
- `cmc_ema_daily_state`: Track last refresh per (id, period)
- `cmc_returns_daily_state`: Track last refresh per (id, lookback)
- Signal state: Track open positions per (id, signal_type, signal_id)

**Benefits:**
- Only recompute from watermark + lookback window (10-100x speedup)
- Graceful recovery from failures (resume from watermark)
- Clear visibility into refresh status per entity

### 3. Graceful Degradation

**Principle:** Optional components shouldn't block core operations.

**Examples:**
- LEFT JOINs in `cmc_daily_features`: NULL columns for missing sources
- Telegram alerts: Log warning if not configured, don't fail validation
- OpenTelemetry: No-op classes when `opentelemetry-api` not installed
- Test skip pattern: `pytest.mark.skipif(not TARGET_DB_URL)` for infrastructure tests

**Benefits:**
- Core features work in minimal environments
- Development doesn't require full production stack
- Partial failures don't cascade

### 4. Atomic Transactions

**Principle:** Multi-table operations must succeed or fail together.

**Examples:**
- Backtest storage: `engine.begin()` ensures runs/trades/metrics all succeed or all fail
- Signal generation: Feature computation + state update in single transaction
- Migration: 95% success threshold for validation (all-or-nothing)

**Benefits:**
- No partial updates causing inconsistent state
- Clear success/failure semantics
- Easy rollback on errors

### 5. Test Tier Separation

**Principle:** Tests should clearly declare infrastructure dependencies.

**Tiers:**
- `mocked_deps`: Unit tests, all mocked (fast, CI-friendly)
- `mixed_deps`: Real database + mocked AI (for database logic)
- `real_deps`: Full infrastructure (for E2E validation)

**Benefits:**
- CI runs fast tier by default (mocked_deps)
- Local development chooses tier based on available infrastructure
- Clear dependency expectations prevent flaky tests

### 6. Feature Hashing for Reproducibility

**Principle:** Detect data changes that invalidate backtest comparisons.

**Pattern:** SHA256 hash (first 16 chars) of feature columns in explicit order

**Examples:**
- Signal generation: `feature_version_hash = hash(close, ema_fast, ema_slow, rsi_14, atr_14)`
- Backtest validation: Compare hash before running to detect stale data
- Cache invalidation: Different hash → recompute

**Benefits:**
- Deterministic backtest results (same data → same results)
- Early detection of data changes (fail-fast)
- Cache invalidation based on data freshness

### 7. Cost-Optimized Routing

**Principle:** Use cheapest LLM that meets quality bar.

**Routing Logic:**
1. Gemini free tier (1500 requests/day, $0)
2. Subscriptions (ChatGPT Plus, Claude Pro, flat monthly fee)
3. Paid APIs (OpenAI/Anthropic, pay-as-you-go)

**Benefits:**
- Minimize cost (Gemini free tier covers most tasks)
- Automatic fallback when quota exhausted
- Advisory hints honored when available

### 8. Observability as SQL Queries

**Principle:** Store observability data in PostgreSQL for SQL queryability.

**Examples:**
- Metrics: `SELECT * FROM observability.metrics WHERE component = 'feature_pipeline' AND recorded_at > NOW() - INTERVAL '1 day'`
- Traces: `SELECT * FROM observability.traces WHERE correlation_id = ? ORDER BY start_time`
- Alerts: `SELECT * FROM observability.alerts WHERE severity = 'CRITICAL' AND resolved_at IS NULL`

**Benefits:**
- No external tools required (Prometheus, Grafana)
- Custom dashboards via SQL
- Join with business data for deeper insights

---

## What Goes Where (Rules of Thumb)

- **New indicator / feature** → `ta_lab2.features.*`
- **Regime logic / policy** → `ta_lab2.regimes.*`
- **Trading rules / signal logic** → `ta_lab2.signals.*`
- **Full workflow for a specific asset** → `ta_lab2.pipelines.*`
- **Backtest or metrics** → `ta_lab2.backtests.*` or `ta_lab2.analysis.*`
- **Memory / AI orchestration** → `ta_lab2.tools.ai_orchestrator.*`
- **Observability (metrics, tracing, health)** → `ta_lab2.observability.*`
- **Operational scripts** → `ta_lab2.scripts.*`
- **One-off research experiments** → `ta_lab2.research.queries.*`
- **Visualization** → `ta_lab2.viz.*`
- **CLI wiring** → `ta_lab2.cli` (legacy) or component-specific CLIs
- **Cross-cutting utilities** → `ta_lab2.utils.*` (sparingly)

---

**This architecture keeps the package understandable as it grows and makes it clear where to put new code.**
