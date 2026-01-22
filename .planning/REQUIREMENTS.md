# Requirements: ta_lab2 AI-Accelerated Quant Platform

**Defined:** 2025-01-22
**Core Value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory

## v1 Requirements

Target: 6 weeks (12-week plan accelerated through AI orchestration)

### Memory Infrastructure

- [ ] **MEMO-01**: Ingest 2847 existing memories into Mem0 + Vertex AI Memory Bank
- [ ] **MEMO-02**: Implement semantic search across all memories (relevance threshold >0.7)
- [ ] **MEMO-03**: Build context injection system (retrieve top-K relevant memories for AI prompts)
- [ ] **MEMO-04**: Enable cross-platform memory sharing (Claude/ChatGPT/Gemini read unified memory)
- [ ] **MEMO-05**: Implement conflict detection and resolution for contradictory memories
- [ ] **MEMO-06**: Build memory health monitoring (detect stale/deprecated memories)
- [ ] **MEMO-07**: Implement batch ingestion pipeline with checkpoints (resume on failure)
- [ ] **MEMO-08**: Add memory metadata (created_at, last_verified, deprecated_since)

### Orchestrator

- [ ] **ORCH-01**: Implement Claude Code adapter (subprocess execution + file parsing)
- [ ] **ORCH-02**: Implement ChatGPT adapter (OpenAI API integration)
- [ ] **ORCH-03**: Implement Gemini adapter (gcloud CLI + API with quota tracking)
- [ ] **ORCH-04**: Build cost-optimized routing (Gemini CLI free → subscriptions → paid APIs)
- [ ] **ORCH-05**: Implement quota tracking system (Gemini 1500/day, reset at UTC midnight)
- [ ] **ORCH-06**: Build parallel execution engine (asyncio for independent tasks)
- [ ] **ORCH-07**: Implement AI-to-AI handoffs (Task A writes to memory → spawns Task B with context pointer)
- [ ] **ORCH-08**: Add error handling with retries and fallback routing
- [ ] **ORCH-09**: Implement per-task cost tracking (token counting + API pricing)
- [ ] **ORCH-10**: Create orchestrator CLI interface for task submission
- [ ] **ORCH-11**: Add pre-flight adapter validation (check implementation before routing)
- [ ] **ORCH-12**: Implement result aggregation for parallel tasks

### ta_lab2 Time Model (Weeks 1-4)

- [ ] **TIME-01**: Create dim_timeframe table with all TF definitions (1D, 3D, 5D, 1W, 1M, 3M, etc.)
- [ ] **TIME-02**: Create dim_sessions table (trading hours, DST handling, session boundaries)
- [ ] **TIME-03**: Unify cmc_ema_multi_tf + cmc_ema_multi_tf_cal into single table
- [ ] **TIME-04**: Update all EMA refresh scripts to reference dim_timeframe
- [ ] **TIME-05**: Build time alignment validation tests (TF windows, calendar rolls, session boundaries)
- [ ] **TIME-06**: Implement incremental EMA refresh (only compute new rows)
- [ ] **TIME-07**: Add rowcount validation (actual vs tf-defined expected counts)

### ta_lab2 Feature Pipeline (Weeks 5-8)

- [ ] **FEAT-01**: Implement cmc_returns_daily (lookbacks from dim_timeframe)
- [ ] **FEAT-02**: Implement cmc_vol_daily (Parkinson, GK volatility measures)
- [ ] **FEAT-03**: Implement cmc_ta_daily (RSI, MACD, indicators respecting sessions)
- [ ] **FEAT-04**: Create unified cmc_daily_features view (join prices, EMAs, returns, vol, TA)
- [ ] **FEAT-05**: Implement null handling strategy and validation
- [ ] **FEAT-06**: Add incremental refresh for all feature tables
- [ ] **FEAT-07**: Build data consistency checks (gaps, anomalies, outliers)

### ta_lab2 Signals & Validation (Weeks 9-12)

- [ ] **SIG-01**: Implement cmc_signals_daily (EMA crossovers, RSI mean reversion, ATR breakout)
- [ ] **SIG-02**: Build backtest integration v1 (reference cmc_daily_features)
- [ ] **SIG-03**: Create observability suite (gap tests, TF alignment tests, roll alignment tests)
- [ ] **SIG-04**: Pass time alignment validation (all calculations use correct TF from dim_timeframe)
- [ ] **SIG-05**: Pass data consistency validation (no gaps, rowcounts match, EMAs calculate correctly)
- [ ] **SIG-06**: Pass backtest reproducibility validation (identical signals/PnL on re-runs)
- [ ] **SIG-07**: Tag release v0.4.0 with full documentation

## v2 Requirements

Deferred to future release. Tracked but not in current scope.

### Live Trading

- **LIVE-01**: Order routing and execution engine
- **LIVE-02**: Position tracking and PnL calculation
- **LIVE-03**: Real capital deployment with risk controls

### Derivatives

- **DERIV-01**: Perpetual swaps support (funding capture in backtests)
- **DERIV-02**: Options on crypto, equities, ETFs
- **DERIV-03**: Margin models and liquidation buffers

### ML/AI Models

- **ML-01**: Feature ranking and selection
- **ML-02**: Regime tagging with ML
- **ML-03**: Strategy parameter optimization

### Advanced Orchestration

- **ADV-01**: Workflow templates for common patterns
- **ADV-02**: Autonomous task decomposition (break complex goals into subtasks)
- **ADV-03**: Platform-specific prompt optimization

## Out of Scope

Explicitly excluded from v1. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Live trading execution | Infrastructure validation first - no real capital until system proven trustworthy |
| Derivatives (perps/options) | Spot only until risk controls proven and validated |
| ML/AI model training | Classical technical analysis sufficient for v1 - defer ML to Year 2-3 |
| Cloud deployment | Local/VM only for v1 - avoid cloud migration costs and complexity |
| External data vendors beyond CMC | Cost optimization - CMC data sufficient for crypto validation |
| Real-time/streaming data | Batch processing sufficient for v1 - real-time in Year 2 |
| Web UI/dashboard | CLI-first for v1 - UI adds complexity without immediate value |
| Outside capital management | Proprietary trading only - fund/MA structure requires proven track record (Year 5+) |

## Traceability

Which requirements map to which phases. Will be updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| MEMO-01 | TBD | Pending |
| MEMO-02 | TBD | Pending |
| ... | ... | ... |

**Coverage:**
- v1 requirements: 41 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 41 ⚠️

---
*Requirements defined: 2025-01-22*
*Last updated: 2025-01-22 after initial definition*
