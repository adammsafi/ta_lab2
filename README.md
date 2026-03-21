# ta_lab2 v1.0.0

Multi-timescale Technical Analysis Lab with AI Orchestration

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

> **v1.0.0 V1 Closure: Paper Trading & Validation**
> Full V1 loop with paper-trade executor, exchange integration, risk controls, drift guard, IC-based feature evaluation, portfolio construction, advanced labeling, ML infrastructure, and operational dashboard.

---

## Quick Start

### Installation

```bash
git clone https://github.com/adammsafi/ta_lab2.git
cd ta_lab2
pip install -e ".[orchestrator,analytics]"
```

For development with AI orchestration and analytics features, install the optional dependency groups.

### Basic Usage

```bash
# Set database URL
export TARGET_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"

# Windows (PowerShell)
$env:TARGET_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"

# Initialize time model (dim_timeframe and dim_sessions)
python -m ta_lab2.scripts.time.ensure_dim_tables

# Run full daily refresh (bars -> EMAs -> regimes -> features -> signals)
python -m ta_lab2.scripts.run_daily_refresh --all

# Run feature pipeline only
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --all-tfs

# Generate trading signals
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Run backtest
python -m ta_lab2.scripts.signals.run_backtest --signal-type ema_crossover

# Run paper trading (requires exchange API keys)
python -m ta_lab2.scripts.run_daily_refresh --all --paper-start 2026-03-01
```

For detailed setup instructions, see [Deployment Guide](docs/deployment.md) and [Time Model Documentation](docs/time/time_model_overview.md).

---

## Overview

**ta_lab2** is a production-ready technical analysis and quantitative trading infrastructure designed for multi-timescale feature engineering, signal generation, backtesting, paper trading, and risk management. The v1.0.0 release closes the V1 loop with a paper-trade executor, exchange integration, risk controls, drift guard, IC-based feature evaluation, portfolio construction, advanced labeling, ML infrastructure, and an operational dashboard.

**Key Capabilities:**
- Multi-timeframe EMA and AMA calculations (KAMA, DEMA, TEMA, HMA) across 109 timeframes
- Feature pipeline: returns, volatility, technical indicators, and 112-column bar-level feature store (`features`)
- Trading signal generation (EMA crossovers, RSI mean reversion, ATR breakouts) with regime-aware configuration
- Vectorbt-based backtesting with walk-forward validation, PSR, and reproducibility checks
- Paper-trade executor with exchange integration (Coinbase, Kraken) and full order/fill/position pipeline
- Risk controls: kill switch, position caps, daily loss stops, circuit breaker, VaR simulation, tail-risk policy
- Drift guard with parallel backtest vs paper comparison and auto-pause on divergence
- IC-based feature evaluation across 109 TFs with BH-corrected promotion gate and feature lifecycle
- Portfolio construction: Black-Litterman, TopkDropout, bet sizing, stop laddering
- Advanced labeling: triple barrier, meta-labeling, CUSUM filter, trend scanning
- ML infrastructure: expression engine, regime routing, DoubleEnsemble, Optuna hyperparameter optimization
- Operational Streamlit dashboard with live PnL, exposure, drawdown, drift, and risk status
- AI memory system with 3,763+ memories and multi-platform orchestrator (Claude, ChatGPT, Gemini)
- PostgreSQL-backed observability (metrics, tracing, health checks, Telegram alerts)

For architectural details and system design, see [Documentation Index](docs/index.md).

---

## Project Structure

ta_lab2 follows a unified ecosystem structure:

```
ta_lab2/
├── src/ta_lab2/              # Core Python package
│   ├── analysis/             # IC evaluation, factor analytics, quintile analysis
│   ├── dashboard/            # Streamlit operational dashboard (5 pages)
│   ├── drift/                # DriftMonitor, backtest vs paper comparison
│   ├── executor/             # PaperExecutor, order management, position sizing
│   ├── experiments/          # FeaturePromoter, ExperimentRunner
│   ├── features/             # Technical indicators (EMA, AMA, RSI, etc.)
│   ├── labeling/             # Triple barrier, meta-labeling, CUSUM filter
│   ├── ml/                   # Expression engine, regime routing, Optuna
│   ├── notifications/        # Telegram alert integration
│   ├── portfolio/            # Portfolio construction, Black-Litterman, sizing
│   ├── regimes/              # Regime detection (L0-L2 labeling, hysteresis)
│   ├── risk/                 # RiskEngine, kill switch, loss limits
│   ├── scripts/              # Data pipelines and CLI tools
│   ├── signals/              # Signal generation (EMA, RSI, ATR)
│   ├── time/                 # Time model (dim_timeframe, dim_sessions)
│   ├── integrations/         # External integrations (FRED)
│   └── tools/                # AI orchestrator, memory, data tools
├── docs/                     # Documentation
│   ├── architecture/         # System design docs
│   ├── features/             # Feature documentation
│   ├── operations/           # Operational runbooks
│   └── index.md              # Documentation home
├── tests/                    # Test suite
├── alembic/                  # Database migrations
├── .archive/                 # Preserved historical files
└── .planning/                # GSD planning artifacts
```

### Key Components

| Component | Location | Description |
|-----------|----------|-------------|
| Core Features | `src/ta_lab2/features/` | EMA, AMA, RSI, regime detection, 112-column feature store |
| Paper Trading | `src/ta_lab2/executor/` | PaperExecutor, exchange integration, order/fill pipeline |
| Risk Controls | `src/ta_lab2/risk/` | RiskEngine, kill switch, loss limits, tail-risk |
| Research & ML | `src/ta_lab2/analysis/`, `ml/`, `experiments/` | IC evaluation, expression engine, Optuna |
| Portfolio | `src/ta_lab2/portfolio/` | Black-Litterman, TopkDropout, bet sizing |
| Labeling | `src/ta_lab2/labeling/` | Triple barrier, meta-labeling, CUSUM |
| Dashboard | `src/ta_lab2/dashboard/` | Streamlit with live PnL, exposure, drift |
| Data Pipelines | `src/ta_lab2/scripts/` | Bar builders, EMA/AMA refreshers, daily refresh |
| AI Orchestrator | `src/ta_lab2/tools/ai_orchestrator/` | Multi-platform AI coordination |

---

## Documentation

- **[Documentation Index](docs/index.md)** - Entry point for all documentation
- **[Architecture](docs/architecture/)** - System design and core concepts
- **[Features](docs/features/)** - Feature-specific documentation (EMAs, bars)

### Reorganization Documentation

The v0.5.0 release consolidated external directories into ta_lab2:

- **[REORGANIZATION.md](docs/REORGANIZATION.md)** - Complete guide to what moved where (155 files documented)
- **[Decision Manifest](docs/manifests/)** - Structured tracking of all decisions
- **[Diagrams](docs/diagrams/)** - Before/after structure visualizations

If migrating from v0.4.0 or updating imports, see the [Migration Guide](docs/REORGANIZATION.md#migration-guide).

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
- `dim_timeframe`: Canonical timeframe definitions with metadata (tf_days, is_calendar, anchor_hour, etc.)
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

See [Time Model Documentation](docs/time/time_model_overview.md) for details.

</details>

<details>
<summary><strong>Feature Pipeline</strong> (EMAs, AMAs, returns, volatility, technical indicators)</summary>

Multi-stage feature calculation pipeline across 109 timeframes with 36 tables organized into 6 families.

**Feature Types:**
- **EMAs**: Multi-timeframe exponential moving averages (daily, calendar, trading-day aligned)
  - 6 tables: `ema_multi_tf` + 4 calendar variants + `ema_multi_tf_u` (unified)
  - Periods: 5, 9, 10, 21, 50, 100, 200
- **AMAs**: Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA) with full multi-TF parity
  - 6 tables: `ama_multi_tf` + 4 calendar variants + `ama_multi_tf_u` (unified)
  - ~91M rows across all variants
- **Returns**: Bar-to-bar returns with multi-window z-scores (`_zscore_30/90/365`)
  - 6 tables: `returns_bars_multi_tf` + variants + unified
- **Volatility**: Parkinson, Garman-Klass, Rogers-Satchell estimators
- **Technical Indicators**: RSI, MACD, Stochastic, Bollinger Bands, ATR, ADX
- **Unified Feature Store**: `features` — 112-column bar-level feature store across all 109 TFs (~2.1M rows)

**Pipeline Execution:**
```bash
# Full daily refresh (bars -> EMAs -> AMAs -> regimes -> features -> signals)
python -m ta_lab2.scripts.run_daily_refresh --all

# Feature refresh only (all assets, all timeframes)
python -m ta_lab2.scripts.features.run_all_feature_refreshes --all --all-tfs
```

**Architecture:**
- 36 tables = 6 families (price bars, bar returns, EMA values, EMA returns, AMA values, AMA returns) x 6 variants
- Unified `_u` tables via INSERT...SELECT...ON CONFLICT DO NOTHING with `alignment_source` watermark
- Multi-window z-scores computed via pure SQL window functions
- Incremental refresh with watermark tracking per (id, tf)

</details>

<details>
<summary><strong>Signal System</strong> (crossovers, reversions, breakouts)</summary>

Database-driven trading signal generation with position lifecycle tracking and feature hashing for reproducibility.

**Signal Types:**
- **EMA Crossover**: Fast/slow EMA crossover signals (9/21, 21/50, 50/200)
  - Table: `signals_ema_crossover`
  - Direction: LONG (fast > slow), SHORT (fast < slow)
- **RSI Mean Reversion**: Oversold/overbought RSI signals
  - Table: `signals_rsi_mean_revert`
  - Thresholds: Oversold (<30), Overbought (>70)
- **ATR Breakout**: Donchian channel + ATR expansion breakouts
  - Table: `signals_atr_breakout`
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
python -m ta_lab2.tools.ai_orchestrator.cli task "Explain EMA calculation" --platform gemini

# Run batch with parallel execution
python -m ta_lab2.tools.ai_orchestrator.cli batch tasks.json --parallel 5

# Check quota status
python -m ta_lab2.tools.ai_orchestrator.cli quota status

# View cost tracker
python -m ta_lab2.tools.ai_orchestrator.cli cost report
```

**Python API:**
```python
from ta_lab2.tools.ai_orchestrator import Orchestrator, Platform, Task

orchestrator = Orchestrator()
task = Task(prompt="Summarize backtest results", platform_hint=Platform.GEMINI)
result = await orchestrator.execute_task(task)
```

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

<details>
<summary><strong>Paper Trading & Risk Controls</strong> (executor, exchanges, risk engine, drift guard)</summary>

End-to-end paper trading pipeline from signal generation through order execution, with comprehensive risk management.

**Paper-Trade Executor:**
- Signal -> order -> fill -> position pipeline with full audit trail
- Exchange integration: Coinbase + Kraken APIs with paper order adapter
- Order & fill store: `orders`, `fills`, `positions` with FIFO matching
- Backtest parity verification ensures paper trades match historical backtests
- Database-driven configuration via `dim_executor_config` (strategies, sizing, initial capital)

**Risk Controls:**
- **RiskEngine**: 3 gate points (`_is_halted`, `check_daily_loss`, `check_order`) enforce all risk limits
- **Kill switch**: `dim_risk_state` table; immediate halt with Telegram notification and dashboard banner
- **Daily loss stops**: Configurable per-strategy loss caps with automatic halt
- **Position caps**: Maximum position sizes enforced at order creation
- **Circuit breaker**: Auto-halt on consecutive losses or drawdown thresholds

**Loss Limits & Tail-Risk:**
- VaR simulation for pool-level capital allocation
- Hard stops vs volatility-based sizing analysis
- Flatten triggers for extreme market conditions
- Intraday stop analysis with documented policy

**Drift Guard:**
- `DriftMonitor` compares paper trading fills against parallel backtest results
- Tracking error (TE) and slippage metrics computed daily
- Auto-pause on divergence exceeding configured thresholds
- Escalation to kill switch with Telegram alert

**Usage:**
```bash
# Run daily pipeline with paper trading and drift monitoring
python -m ta_lab2.scripts.run_daily_refresh --all --paper-start 2026-03-01
```

</details>

<details>
<summary><strong>Research & ML</strong> (IC evaluation, labeling, portfolio, ML infrastructure)</summary>

Comprehensive quantitative research toolkit spanning feature evaluation, advanced labeling, portfolio construction, and ML experimentation.

**IC-Based Feature Evaluation:**
- Spearman IC, rolling IC, IC-IR, and regime breakdown across all features x 109 TFs
- `ic_results` table with 82K+ rows of evaluation data
- BH-corrected promotion gate with `FeaturePromoter` and `dim_feature_registry`
- Dual-source loading: `ic_results` (bar-level) and `feature_experiments` (experiment-level)
- Batch promotion CLI: `python -m ta_lab2.scripts.experiments.batch_promote_features`

**Factor Analytics:**
- QuantStats tear sheets with BTC benchmark
- IC decay analysis and rank IC
- Quintile returns engine for cross-sectional analysis
- MAE/MFE (Maximum Adverse/Favorable Excursion) per trade
- Monte Carlo confidence intervals with bootstrap resampling
- Cross-sectional normalization refresh

**Advanced Labeling:**
- Triple barrier labeling with configurable profit-take/stop-loss/time barriers
- Meta-labeling (RF classifier) for signal filtering with bet sizing
- CUSUM event filter with threshold calibration for pre-filtering signals
- Trend scanning labels with OLS t-value windows

**Portfolio Construction:**
- `PortfolioOptimizer`: Mean-variance, CVaR, and HRP with regime routing
- `BLAllocationBuilder`: Black-Litterman with market cap prior and IC-IR signal views
- `TopkDropoutSelector`: Dropout-based turnover control
- `BetSizer`: Probability-based position scaling from meta-labeling confidence
- `StopLadder`: Multi-tier stop-loss/take-profit exit scaling
- `TurnoverTracker`: Decomposed cost reporting in backtest loop

**ML Infrastructure:**
- Expression engine for config-driven feature computation
- `RegimeRouter`: Per-regime sub-models with global fallback
- `DoubleEnsemble`: Concept drift detection with sample/feature reweighting
- Optuna TPE hyperparameter sweep with experiment tracking
- MDA/SFI/clustered feature importance
- `ml_experiments` table for experiment tracking

**Microstructural Features:**
- Fractional differentiation (fixed-width window FFD)
- Kyle/Amihud lambda (price impact measures)
- SADF bubble detection (integrated into regime pipeline)
- Shannon/Lempel-Ziv entropy
- Pairwise codependence metrics

</details>

<details>
<summary><strong>Dashboard</strong> (Streamlit operational dashboard)</summary>

Interactive Streamlit dashboard for monitoring research, pipelines, and trading operations.

**Pages:**
- **Landing**: Project overview and key metrics
- **Pipeline Monitor**: Data pipeline health, refresh status, row counts
- **Research Explorer**: Rolling IC charts, feature rankings, experiment results
- **Asset Stats**: Rolling descriptive statistics and cross-asset correlation
- **Experiments**: Feature experimentation results with promotion status

**Usage:**
```bash
streamlit run src/ta_lab2/dashboard/app.py
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
# Lint (auto-fix)
ruff check src/ --fix

# Format code
ruff format src/

# Type checking (features + regimes only)
mypy src/ta_lab2/features/ src/ta_lab2/regimes/
```

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

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed contribution guidelines.

---

## Security

If you discover a security issue (credential handling, database access, API key exposure), do not open a public GitHub issue.

Follow the process in [SECURITY.md](SECURITY.md) to report it privately.

**Security Best Practices:**
- Never commit secrets, API keys, or database credentials
- Use `.env` files for sensitive configuration (ensure `.gitignore` excludes them)
- Rotate API keys regularly
- Use read-only database users where possible
- Enable SSL/TLS for database connections in production

---

## Links

### Core Documentation
- **[Documentation Index](docs/index.md)** - Main documentation entry point
- **[Architecture](docs/architecture/)** - System design, core concepts, API references
- **[Features Documentation](docs/features/)** - EMAs, bars, signals, backtesting
- **[Migration Guides](docs/migration/)** - Import path updates and reorganization reference

### Technical References
- **[REORGANIZATION.md](docs/REORGANIZATION.md)** - v0.5.0 ecosystem consolidation guide
- **[EMA State Standardization](docs/EMA_STATE_STANDARDIZATION.md)** - EMA calculation and state management
- **[Deployment Guide](docs/deployment.md)** - Infrastructure setup and operations

---

## License

TBD. Until an explicit license is added, treat this as **source-available for personal research use only**.

If you want to use this in a commercial setting, reach out first so terms can be clarified once the project is more mature.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release history and upgrade notes.

**Latest Release:** v1.0.0 (2026-03-01)
- Paper-trade executor with exchange integration (Coinbase + Kraken) and order/fill/position pipeline
- Risk controls: kill switch, daily loss stops, circuit breaker, VaR, tail-risk policy, drift guard
- IC-based feature evaluation across 109 TFs with BH-corrected promotion (107 features promoted)
- Portfolio construction: Black-Litterman, TopkDropout, bet sizing, stop laddering
- Advanced labeling: triple barrier, meta-labeling, CUSUM filter, trend scanning
- ML infrastructure: expression engine, regime routing, DoubleEnsemble, Optuna
- Operational Streamlit dashboard with live PnL, exposure, drift, and risk status
- Factor analytics: QuantStats, IC decay, quintile returns, MAE/MFE, Monte Carlo CI

**Previous Release:** v0.9.0 (2026-02-24)
- Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA) with full multi-TF parity and z-scores
- IC evaluation engine with Spearman IC, rolling IC, IC-IR, regime breakdown, DB persistence
- PSR/DSR/MinTRL (Lopez de Prado), PurgedKFoldSplitter, CPCVSplitter for leakage-free CV
- Feature experimentation: YAML registry, ExperimentRunner, BH-corrected promotion gate
- Streamlit dashboard (5 pages), polished Jupyter notebooks, rolling asset stats
