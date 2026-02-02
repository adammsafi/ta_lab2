# ta_lab2: AI-Accelerated Quant Platform

## What This Is

A systematic crypto trading platform with integrated AI orchestration and persistent memory infrastructure. The system coordinates multiple AI platforms (Claude, ChatGPT, Gemini) through a unified memory layer to accelerate development of trustworthy backtesting and trading infrastructure. Starting crypto-first with BTC/ETH, building toward multi-asset systematic strategies with capital pools.

## Core Value

Build trustworthy quant trading infrastructure 3x faster by creating AI coordination that remembers context, routes work optimally, and eliminates redundant context-setting across sessions and platforms.

## Current Milestone: v0.5.0 Ecosystem Reorganization

**Goal:** Consolidate scattered project directories (ta_lab2, ProjectTT, Data_Tools, fredtools2, fedtools2) into unified structure without deleting anything.

**Target features:**
- Archive Management: Move backup artifacts to .archive/ structure
- Documentation Consolidation: Integrate ProjectTT docs into ta_lab2
- Tools Integration: Migrate Data_Tools scripts to ta_lab2/tools/
- Economic Data Strategy: Evaluate and integrate fredtools2/fedtools2
- Root Directory Cleanup: Organize clutter while preserving in git
- Structure Documentation: Create reorganization guide
- Verification: Validate imports work, nothing lost

**Critical Constraint:** NO DELETION - everything preserved in git history + .archive/

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

### Active (v0.5.0 Milestone)

**Ecosystem Reorganization**
- [ ] Archive backup artifacts (.original files, *_refactored.py)
- [ ] Consolidate ProjectTT documentation into ta_lab2
- [ ] Migrate Data_Tools scripts into ta_lab2/tools/
- [ ] Integrate or reference fredtools2/fedtools2 economic data projects
- [ ] Clean up root directory clutter (preserve in .archive/)
- [ ] Document new structure and migration decisions
- [ ] Verify all imports work after reorganization
- [ ] Update README with ecosystem structure

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

### Out of Scope

- Live trading execution — no order routing, position management, or real capital deployment
- Derivatives (perps/options) — spot only until risk controls proven
- ML/AI features — classical technical analysis only (ML in Year 2-3)
- Cloud deployment — local/VM only for v1
- Multi-venue expansion — CoinMarketCap data only for now
- External capital — proprietary trading only (fund/MA in Year 5+)

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
| Backtest/live parity as success criterion | System is only trustworthy if backtests use identical logic to live trading - reproducibility is mandatory | — Pending |

---
*Last updated: 2026-02-02 after v0.5.0 milestone initialization*
