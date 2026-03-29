# ta_lab2: AI-Accelerated Quant Platform

## What This Is

A systematic crypto trading platform with integrated AI orchestration and persistent memory infrastructure. The system coordinates multiple AI platforms (Claude, ChatGPT, Gemini) through a unified memory layer to accelerate development of trustworthy backtesting and trading infrastructure. Starting crypto-first with BTC/ETH, building toward multi-asset systematic strategies with capital pools.

## Core Value

Build trustworthy quant trading infrastructure 3x faster by creating AI coordination that remembers context, routes work optimally, and eliminates redundant context-setting across sessions and platforms.

## Current State

**Latest shipped:** v1.2.0 Analysis → Live Signals (2026-03-29)
**Current milestone:** v1.3.0 Operational Activation & Research Expansion

**v1.2.0 delivered:** IC-based feature selection (20 active from 112), GARCH conditional volatility (4 model families), walk-forward bake-off (9 strategies, 2 exchanges), 17 Streamlit dashboard pages, live pipeline wiring (signal gates, IC staleness, BL portfolio construction with real signal scores), CTF infrastructure (73.9M rows). 16 phases, 52 plans, 19/19 requirements. Gap closure: all 4 integration breaks resolved.

**v1.1.0 delivered:** Eliminated 254 GB duplicate data (-59%), consolidated 30 siloed tables into _u tables, generalized 1D bar builder with source registry, pruned 7.18M NULL rows, integrated VWAP pipeline, cleaned MCP dead routes. 6 phases, 21 plans, 26/26 requirements. DB: 431 GB → 177 GB.

**v1.0.1 delivered:** FRED macro data pipeline (39 series, 208K rows) wired into regime/risk infrastructure -- 4-dimensional macro regime classifier, tighten-only L4 resolver, event risk gates (FOMC/CPI/NFP/VIX/carry/credit), cross-asset aggregation, and full observability (dashboard, Telegram alerts, drift attribution). 10 phases, 29 plans, 55/55 requirements.

**v1.0.0 delivered:** Full V1 loop -- strategy bake-off, paper-trade executor, risk controls, drift guard, all research tracks answered, feature evaluation across 109 TFs, advanced ML infrastructure, operational dashboard, and V1 Results Memo. 22 phases, 104 plans, 80/80 requirements.

**Cumulative stats:** 95 phases, 411 plans, 650+ files, ~255K lines

## Requirements

### Validated

**ta_lab2 Foundation (Week 1 complete)**
- ✓ Clean package layout under src/ta_lab2 — existing
- ✓ Modular features/regimes/signals/backtests structure — existing
- ✓ CLI entrypoint with basic commands — existing
- ✓ README, ARCHITECTURE, CONTRIBUTING, SECURITY docs — existing
- ✓ GitHub templates and basic CI workflow — existing
- ✓ Smoke import tests passing — existing

**Memory Generation Tooling (built)**
- ✓ ChatGPT export processing pipeline — existing
- ✓ Code → memories generator (AST-based chunking + OpenAI) — existing
- ✓ Git diff → memories generator — existing
- ✓ Memory staging pipeline (00_inbox → 05_approved) — existing
- ✓ Mem0 integration code (ta_lab2_memory.py) — existing

**Memory Content (generated)**
- ✓ ChatGPT conversation memories extracted — existing
- ✓ Code-based memories from ta_lab2 codebase — existing
- ✓ Combined memories (final_combined_memories.jsonl) — existing

**Orchestrator Design (documented)**
- ✓ Routing matrix (task type → platform strengths) — existing
- ✓ Cost optimization tiers (free CLI → subscriptions → paid API) — existing
- ✓ Adapter architecture (Claude/ChatGPT/Gemini) — existing
- ✓ Quota tracking design — existing

### Complete (v1.2.0 Milestone)

**Analysis → Live Signals** ✓
- ✓ IC-based feature selection: 20 active features from 112 candidates (IC-IR >= 1.0, AMA features dominate 18/20) -- v1.2.0
- ✓ GARCH conditional volatility: 4 model families, carry-forward fallback, VaR/CVaR suite -- v1.2.0
- ✓ Walk-forward strategy bake-off: 9 strategies, 2 exchanges, per-asset IC-IR weighting -- v1.2.0
- ✓ 17 Streamlit dashboard pages: strategy-first, signal monitor, asset hub, HL perps, AMA inspector, portfolio -- v1.2.0
- ✓ Live pipeline wiring: signal anomaly gates, IC staleness monitoring (20/20 features), BL portfolio construction with real signal scores -- v1.2.0
- ✓ CTF infrastructure: cross-timeframe features (73.9M rows), IC analysis, feature selection -- v1.2.0
- ✓ Integration testing: smoke tests, burn-in protocol, operations manual, gap closure (Phases 93-95) -- v1.2.0

### Complete (v1.1.0 Milestone)

**Pipeline Consolidation & Storage Optimization** ✓
- ✓ Generalized 1D bar builder: single `refresh_price_bars_1d.py --source cmc|tvc|hl|all` replaces 3 source-specific scripts -- v1.1.0
- ✓ Direct-to-_u migration: all 6 table families write directly to _u tables with alignment_source discrimination -- v1.1.0
- ✓ 30 siloed tables dropped, 6 sync scripts deleted, 254 GB storage reclaimed (431 GB → 177 GB) -- v1.1.0
- ✓ NULL first-observation rows pruned (7.18M AMA return rows), all return scripts filter going forward -- v1.1.0
- ✓ VWAP pipeline integrated for all multi-venue assets, MCP dead routes removed -- v1.1.0

### Complete (v1.0.1 Milestone)

**Macro Regime Infrastructure** ✓
- ✓ FRED macro feature store: 39 series forward-filled to daily, 50+ derived columns (rate spreads, VIX, carry, credit, fed regime, net liquidity) -- v1.0.1
- ✓ 4-dimensional macro regime classifier (monetary policy, liquidity, risk appetite, carry) with hysteresis and YAML config -- v1.0.1
- ✓ HMM secondary classifier, lead-lag analysis, regime transition probability matrix -- v1.0.1
- ✓ L4 tighten-only resolver: macro regime conditions all position sizing, never loosens -- v1.0.1
- ✓ Event risk gates: FOMC/CPI/NFP calendar, VIX spike, carry unwind, credit stress, composite stress score -- v1.0.1
- ✓ Cross-asset aggregation: BTC/ETH correlation, funding rate z-score, crypto-macro correlation regime -- v1.0.1
- ✓ Macro observability: dashboard, Telegram alerts, FRED freshness, drift attribution, regime timeline chart -- v1.0.1
- ✓ MCP memory server: Qdrant semantic search accessible from Claude Code sessions -- v1.0.1

### Complete (v1.0.0 Milestone)

**Paper Trading & Validation** ✓
- ✓ Strategy bake-off with IC/PSR/CV evaluation, 2 strategies selected -- v1.0.0
- ✓ Paper-trade executor: signal -> order -> fill -> position pipeline with backtest parity -- v1.0.0
- ✓ Risk controls: kill switch, position caps, daily loss stops, circuit breaker, VaR, tail-risk policy -- v1.0.0
- ✓ Drift guard: parallel backtest vs paper comparison, auto-pause on divergence -- v1.0.0
- ✓ Advanced ML: factor analytics, triple barrier, purged CPCV, portfolio construction, expression engine, Optuna -- v1.0.0
- ✓ Operational dashboard: live PnL, exposure, drawdown, drift, risk status; Telegram notifications -- v1.0.0

### Complete (v0.9.0 Milestone)

**Research & Experimentation** ✓
- ✓ Adaptive Moving Averages: KAMA, DEMA, TEMA, HMA with (indicator, params_hash) PK, full multi-TF, _u sync, z-scores, daily refresh integration
- ✓ IC evaluation: Spearman IC, rolling IC, IC-IR, regime breakdown, significance testing, cmc_ic_results DB persistence
- ✓ PSR/DSR/MinTRL: full Lopez de Prado formulas, Pearson kurtosis, Alembic migration (psr->psr_legacy), backtest pipeline integration
- ✓ Cross-validation: PurgedKFoldSplitter + CPCVSplitter from scratch (mlfinlab discontinued), leakage-free fold validation
- ✓ Feature experimentation: YAML registry, ExperimentRunner, BH-corrected promotion gate, dim_feature_registry + cmc_feature_experiments tables
- ✓ Streamlit dashboard: 5 pages (landing, pipeline monitor, research explorer with rolling IC, asset stats, experiments), NullPool + cache
- ✓ Polished notebooks: helpers.py + 3 notebooks (indicators, features, experiments), parameterized, narrative cells
- ✓ Asset descriptive stats: rolling 30/60/90/252-bar mean/std/Sharpe/skew/kurt/drawdown in cmc_asset_stats
- ✓ Cross-asset correlation: pairwise rolling Pearson in cmc_cross_asset_corr + cmc_corr_latest materialized view

### Complete (v0.8.0 Milestone)

**Polish & Hardening** ✓
- ✓ Stats/QA orchestration: stats runners in daily refresh, FAIL gating, weekly Telegram digest
- ✓ Code quality: ruff lint blocking in CI, mypy non-blocking, 7 parallel CI jobs
- ✓ Documentation: version 0.8.0 synced, pipeline diagrams, mkdocs --strict CI gate
- ✓ Runbooks: regime pipeline, backtest pipeline, asset onboarding SOP, disaster recovery
- ✓ Alembic: framework bootstrapped, baseline revision 25f2b3c90f65, 17 legacy SQL cataloged

### Complete (v0.7.0 Milestone)

**Regime Integration & Signal Enhancement** ✓
- ✓ Regime pipeline: refresh_cmc_regimes.py with L0-L2 labeling, policy resolution, hysteresis
- ✓ 4 regime tables: cmc_regimes, cmc_regime_flips, cmc_regime_stats, cmc_regime_comovement
- ✓ Signal generators wired with regime_enabled param and --no-regime flag
- ✓ Orchestrator: run_daily_refresh.py --all runs bars→EMAs→regimes→stats
- ✓ Backtest pipeline fix: feature_snapshot serialization, vectorbt compat, end-to-end verified

### Complete (v0.6.0 Milestone)

**EMA & Bar Architecture Standardization** ✓
- ✓ Comprehensive review of all bar builders, EMA calculators, schemas, data flows
- ✓ All EMAs use validated bar tables (not raw price_histories7)
- ✓ BaseBarBuilder + BaseEMARefresher pattern consistency across all builders
- ✓ Unified bar/EMA/returns schemas with consistent PKs
- ✓ Baseline capture + validation (38 pytest tests, 17 audit scripts, stats runners)

### Complete (v0.5.0 Milestone)

**Ecosystem Reorganization** ✓
- ✓ Archived backup artifacts (.original files, *_refactored.py)
- ✓ Consolidated ProjectTT documentation into ta_lab2
- ✓ Migrated Data_Tools scripts into ta_lab2/tools/
- ✓ Integrated fredtools2/fedtools2 economic data projects
- ✓ Cleaned up root directory clutter (preserved in .archive/)
- ✓ Documented new structure and migration decisions
- ✓ Verified all imports work after reorganization
- ✓ Updated README with ecosystem structure

### Complete (v0.4.0 Milestone)

**Memory Infrastructure Integration** ✓
- ✓ Ingest generated memories into Mem0
- ✓ Set up Qdrant backend for Mem0
- ✓ Connect Mem0 (logic layer) to Qdrant (storage layer)
- ✓ Implement memory retrieval for AI context injection
- ✓ Test memory search and relevance scoring
- ✓ Build memory update and conflict resolution

**Orchestrator Implementation** ✓
- ✓ Implement Claude Code adapter (subprocess + file parsing)
- ✓ Implement Gemini adapter (gcloud CLI + API)
- ✓ Implement ChatGPT adapter (API integration)
- ✓ Build task routing engine with cost optimization
- ✓ Implement quota tracking for free tiers
- ✓ Build parallel task execution (asyncio)
- ✓ Create orchestrator CLI interface
- ✓ Test direct handoffs (Task A → write to Memory → spawn Task B with context)

**ta_lab2 Time Model** ✓
- ✓ Create dim_timeframe table (TF definitions: 1D, 3D, 5D, 1W, 1M, etc.)
- ✓ Create dim_sessions table (trading hours, DST handling)
- ✓ Unify cmc_ema_multi_tf + cmc_ema_multi_tf_cal into single table
- ✓ Update all refresh scripts to reference dimension tables
- ✓ Build time alignment validation tests

**ta_lab2 Feature Pipeline** ✓
- ✓ Implement cmc_returns_daily (using dim_timeframe lookbacks)
- ✓ Implement cmc_vol_daily (Parkinson, GK volatility measures)
- ✓ Implement cmc_ta_daily (RSI, MACD, indicators)
- ✓ Create unified cmc_daily_features view
- ✓ Validate null handling and data consistency

**ta_lab2 Signals & Validation** ✓
- ✓ Implement cmc_signals_daily (EMA crossovers, RSI MR, ATR breakout)
- ✓ Build backtest integration v1 (reference daily features)
- ✓ Create observability suite (gap tests, TF alignment, roll alignment)
- ✓ Pass all three validation layers (time alignment, data consistency, backtest reproducibility)
- ✓ Tag release v0.4.0

### Active (v1.3.0)

**Operational Activation** — make built infrastructure actually run
- [ ] Seed dim_executor_config with active strategies from bakeoff winners
- [ ] Wire signal generators into daily refresh pipeline
- [ ] Schedule/auto-run paper executor
- [ ] Portfolio construction operational end-to-end (BL → position sizing → orders)
- [ ] Backtest-to-live parity tracking (measure live vs backtest Sharpe gap)
- [ ] PnL attribution (alpha vs long-crypto bias)

**Backtest Expansion** — scale from 2 runs to hundreds of thousands
- [ ] Multiprocessing backtest orchestrator (resume-safe, batched)
- [ ] Trade-level backfill for existing bakeoff strategies (~113K runs)
- [ ] Monte Carlo confidence intervals on every run
- [ ] CTF feature-based signal generation + backtest
- [ ] Expanded parameter grids for existing signals
- [ ] Backtest results reporting dashboards

**CTF Research Expansion** — turn CTF infrastructure into tradeable signals
- [ ] Graduate top CTF features to production pipeline (feature_selection.yaml)
- [ ] Asset-specific feature selection (per-asset tier in dim_feature_selection)
- [ ] Cross-asset CTF composites (market-wide sentiment, relative-value)
- [ ] Lead-lag IC matrix (does Asset A's CTF predict Asset B's returns?)

**Macro Expansion** — FRED equity indices
- [ ] SP500/NASDAQ/DJIA/Russell 2000 in macro feature layer
- [ ] Derived features (returns, vol, drawdown, MA ratios)
- [ ] Crypto-equity correlation and risk-on/risk-off signals

**ML Research** — nonlinear signal combination
- [ ] LightGBM cross-sectional rank predictor (extend double_ensemble.py)
- [ ] SHAP interaction analysis for feature pair discovery
- [ ] Meta-label confidence filter (XGBoost on triple_barrier_labels)

**Tech Debt Cleanup**
- [ ] Phase 81: orphaned blend_vol_simple() in garch_blend.py
- [ ] Phase 82: missing VERIFICATION.md
- [ ] Phase 92: stale VERIFICATION.md
- [ ] Phase 92: dim_ctf_feature_selection no downstream consumers (by design, deferred)

### Out of Scope

- Live trading with real capital — paper trading only until live Sharpe within 70% of backtest Sharpe
- Derivatives (perps/options) — spot only until risk controls proven
- Cloud deployment — local/VM only for v1
- Multi-venue expansion beyond existing (CMC + HL + TVC already integrated)
- External capital — proprietary trading only (fund/MA in Year 5+)
- Transformer/deep learning models — deferred until P1-P3 ML proven profitable + GPU budget
- Order flow / L2 book data — premature per strategic review
- Funding rate arbitrage — different strategy class (delta-neutral)

## Context

**Existing Codebase**: ta_lab2 is a working quant research library with features/regimes/signals/backtests. Week 1 of 12-week plan is complete (repo structure, docs, tests). The core issue is fragmented time handling across multiple EMA systems and lack of formal time dimension tables.

**Parallel Development**: Work is happening across multiple AI platforms simultaneously. ChatGPT conversations contain valuable context, code is being written in Claude Code sessions, and Gemini is being used for analysis. Currently requires manual context transfer between platforms.

**Memory Artifacts**: Thousands of memories already generated from ChatGPT exports and codebase analysis, stored as JSONL files. Ready for ingestion into unified memory system.

**Vision**: 3-5 year systematic trading platform with capital pools (Conservative/Core/Opportunistic), starting crypto and expanding to equities/ETFs/derivatives. This 12-week plan builds the foundation for Year 0-1.

## Constraints

- **Timeline**: 6 weeks target (aggressive but achievable with AI coordination efficiency) — quality over speed, but working full-time on this
- **Budget**: Cost optimization is critical — orchestrator must route to free tiers first, track quota usage, minimize token waste
- **Tech Stack**: Mostly locked — Python 3.12, Polars, SQLAlchemy, PostgreSQL, existing ta_lab2 infrastructure; open to additions if justified
- **Data Sources**: CoinMarketCap only for v1 — avoid additional vendor costs until proven necessary
- **Infrastructure**: Local/VM deployment — no cloud migration costs for v1

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Hybrid memory architecture (Mem0 + Memory Bank) | Mem0 provides logic layer (fact refinement, updates), Memory Bank provides enterprise storage/retrieval at scale | — Pending |
| Parallel track development (memory + orchestrator + ta_lab2) | All three enable each other - orchestrator needs memory to work, both accelerate ta_lab2, ta_lab2 validates the stack | — Pending |
| Direct handoff model for AI coordination | Task A completes → writes to Memory Bank → spawns Task B with context pointer (not full context dump) | — Pending |
| Time model before features | dim_timeframe and dim_sessions must exist before EMAs, returns, vol, indicators can reference them correctly | — Pending |
| Unified EMA table | Two separate multi-TF EMA systems (tf_day vs calendar) creates permanent inconsistency - must merge before building on top | — Pending |
| Backtest/live parity as success criterion | System is only trustworthy if backtests use identical logic to live trading - reproducibility is mandatory | Validated — PaperExecutor verifies backtest parity |

| Direct-to-_u writes, drop siloed tables | 30 siloed tables duplicate 100GB+ of data; all consumers already read from _u | Validated — 254 GB reclaimed, all 6 families migrated |
| Generalized 1D bar builder with source registry | 3 source-specific scripts are 80% identical; adding a new source requires copying an entire file | Validated — SourceSpec pattern, BAR-03 enables config-only onboarding |

---
*Last updated: 2026-03-29 after v1.3.0 milestone started*
