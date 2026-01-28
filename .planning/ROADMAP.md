# Roadmap: ta_lab2 AI-Accelerated Quant Platform

## Overview

Build trustworthy quant trading infrastructure 3x faster by creating AI coordination that remembers context across platforms. Start with quota management and memory infrastructure (integrate existing 3,763 memories in ChromaDB), layer in multi-platform orchestration with cost optimization, migrate to hybrid Mem0 + Vertex AI architecture, then accelerate ta_lab2 development (time model, features, signals) through the coordinated AI system. Parallel tracks converge at integration phase where memory + orchestrator + ta_lab2 prove the unified vision.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation & Quota Management** - Infrastructure validation and quota tracking foundation
- [ ] **Phase 2: Memory Core (ChromaDB Integration)** - Integrate existing 3,763 memories and enable semantic search
- [ ] **Phase 3: Memory Advanced (Mem0 Migration)** - Migrate to Mem0 + Vertex AI, add conflict resolution and health monitoring
- [ ] **Phase 4: Orchestrator Adapters** - Claude, ChatGPT, Gemini platform integrations
- [ ] **Phase 5: Orchestrator Coordination** - Routing, handoffs, parallel execution, cost tracking
- [ ] **Phase 6: ta_lab2 Time Model** - Dimension tables and EMA unification
- [ ] **Phase 7: ta_lab2 Feature Pipeline** - Returns, volatility, technical indicators
- [ ] **Phase 8: ta_lab2 Signals** - Signal generation and backtest integration
- [ ] **Phase 9: Integration & Observability** - Cross-system validation and monitoring
- [ ] **Phase 10: Release Validation** - Final tests, documentation, v0.4.0 tag

## Phase Details

### Phase 1: Foundation & Quota Management
**Goal**: Quota tracking system operational and infrastructure validated for parallel development
**Depends on**: Nothing (first phase)
**Requirements**: ORCH-05, ORCH-11
**Success Criteria** (what must be TRUE):
  1. System tracks Gemini quota usage (1500/day limit) with UTC midnight reset
  2. Pre-flight adapter validation prevents routing to unimplemented adapters
  3. Infrastructure dependencies (Mem0, Vertex AI, platform SDKs) installed and verified
  4. Development environment supports parallel work on memory/orchestrator/ta_lab2 tracks
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Infrastructure setup & SDK validation (Wave 1)
- [x] 01-02-PLAN.md — Quota system enhancement with persistence, alerts, reservation (Wave 1)
- [x] 01-03-PLAN.md — Pre-flight validation & smoke tests (Wave 2)

### Phase 2: Memory Core (ChromaDB Integration)
**Goal**: Existing ChromaDB memory store (3,763 memories) integrated with orchestrator
**Depends on**: Phase 1
**Requirements**: MEMO-01, MEMO-02, MEMO-03, MEMO-04, MEMO-07
**Success Criteria** (what must be TRUE):
  1. ChromaDB memory store (3,763 embedded memories) validated and accessible
  2. Semantic search API exposed from ChromaDB with threshold >0.7
  3. Context injection system retrieves top-K memories for AI prompts
  4. Claude, ChatGPT, and Gemini can all read from ChromaDB memory layer (via HTTP API)
  5. Incremental update pipeline adds new memories without breaking existing embeddings
**Required Dependencies**: fastapi, uvicorn (for MEMO-04 cross-platform access)
**Plans**: 5 plans (4 original + 1 gap closure)

Plans:
- [x] 02-01-PLAN.md — ChromaDB client wrapper & integrity validation (Wave 1)
- [x] 02-02-PLAN.md — Semantic search API & context injection (Wave 2)
- [x] 02-03-PLAN.md — Incremental update pipeline (Wave 2)
- [x] 02-04-PLAN.md — Cross-platform REST API for memory access (Wave 3)
- [ ] 02-05-PLAN.md — Fix semantic search embedding dimension mismatch (Gap closure)

### Phase 3: Memory Advanced (Mem0 Migration)
**Goal**: Memory system migrated to Mem0 + Vertex AI with self-maintenance and conflict detection
**Depends on**: Phase 2
**Requirements**: MEMO-09, MEMO-05, MEMO-06, MEMO-08
**Success Criteria** (what must be TRUE):
  1. All 3,763 memories successfully migrated from ChromaDB → Mem0 + Vertex AI Memory Bank
  2. Conflicting memories detected and resolved (no contradictory context)
  3. Stale memories flagged with deprecated_since timestamp
  4. Memory health monitoring detects outdated context before it poisons decisions
  5. All memories have enhanced metadata (created_at, last_verified, deprecated_since)
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 4: Orchestrator Adapters
**Goal**: All three AI platforms (Claude, ChatGPT, Gemini) accessible via unified adapter interface
**Depends on**: Phase 1 (quota tracking for Gemini)
**Requirements**: ORCH-01, ORCH-02, ORCH-03
**Success Criteria** (what must be TRUE):
  1. Claude Code adapter executes tasks via subprocess and parses file results
  2. ChatGPT adapter executes tasks via OpenAI API integration
  3. Gemini adapter executes tasks via gcloud CLI + API with quota tracking
  4. All adapters implement common interface for task submission and result retrieval
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 5: Orchestrator Coordination
**Goal**: Tasks route intelligently across platforms with cost optimization and parallel execution
**Depends on**: Phase 4 (adapters), Phase 2 (memory for handoffs)
**Requirements**: ORCH-04, ORCH-06, ORCH-07, ORCH-08, ORCH-09, ORCH-10, ORCH-12
**Success Criteria** (what must be TRUE):
  1. Cost-optimized routing sends tasks to Gemini CLI free tier first, then subscriptions, then paid APIs
  2. Parallel execution engine runs independent tasks concurrently via asyncio
  3. AI-to-AI handoffs work: Task A writes to memory, spawns Task B with context pointer
  4. Error handling retries failed tasks and routes to fallback platforms
  5. Per-task cost tracking records token usage and API pricing
  6. Orchestrator CLI accepts task submissions and returns results
  7. Result aggregation combines outputs from parallel tasks
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 6: ta_lab2 Time Model
**Goal**: Time handling unified across ta_lab2 with formal dimension tables
**Depends on**: Phase 1 (can develop in parallel with memory/orchestrator)
**Requirements**: TIME-01, TIME-02, TIME-03, TIME-04, TIME-05, TIME-06, TIME-07
**Success Criteria** (what must be TRUE):
  1. dim_timeframe table contains all TF definitions (1D, 3D, 5D, 1W, 1M, 3M, etc.)
  2. dim_sessions table handles trading hours, DST, session boundaries
  3. Single unified EMA table (cmc_ema_multi_tf + cmc_ema_multi_tf_cal merged)
  4. All EMA refresh scripts reference dim_timeframe instead of hardcoded values
  5. Time alignment validation tests pass (TF windows, calendar rolls, session boundaries)
  6. Incremental EMA refresh computes only new rows
  7. Rowcount validation confirms actual counts match tf-defined expectations
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 7: ta_lab2 Feature Pipeline
**Goal**: Returns, volatility, and technical indicators calculated correctly from unified time model
**Depends on**: Phase 6 (time model)
**Requirements**: FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05, FEAT-06, FEAT-07
**Success Criteria** (what must be TRUE):
  1. cmc_returns_daily calculates returns using lookbacks from dim_timeframe
  2. cmc_vol_daily computes Parkinson and GK volatility measures
  3. cmc_ta_daily calculates RSI, MACD, and other indicators respecting sessions
  4. cmc_daily_features view unifies prices, EMAs, returns, vol, and TA
  5. Null handling strategy implemented and validated
  6. Incremental refresh works for all feature tables
  7. Data consistency checks detect gaps, anomalies, and outliers
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 8: ta_lab2 Signals
**Goal**: Trading signals generated and backtestable with reproducible results
**Depends on**: Phase 7 (feature pipeline)
**Requirements**: SIG-01, SIG-02
**Success Criteria** (what must be TRUE):
  1. cmc_signals_daily generates EMA crossovers, RSI mean reversion, ATR breakout signals
  2. Backtest integration v1 references cmc_daily_features and produces PnL
  3. Backtest reruns produce identical signals and PnL (reproducibility validated)
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 9: Integration & Observability
**Goal**: Cross-system validation proves memory + orchestrator + ta_lab2 work together
**Depends on**: Phase 5 (orchestrator), Phase 8 (signals)
**Requirements**: SIG-03
**Success Criteria** (what must be TRUE):
  1. Observability suite passes all gap tests
  2. TF alignment tests confirm calculations use correct timeframes
  3. Roll alignment tests validate calendar boundary handling
  4. Orchestrator successfully coordinates ta_lab2 feature refresh tasks via memory context
  5. End-to-end workflow: user submits task -> orchestrator routes -> memory provides context -> ta_lab2 executes -> results stored
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

### Phase 10: Release Validation
**Goal**: v0.4.0 release ready with full documentation and validation
**Depends on**: Phase 9 (integration)
**Requirements**: SIG-04, SIG-05, SIG-06, SIG-07
**Success Criteria** (what must be TRUE):
  1. Time alignment validation passes (all calculations use correct TF from dim_timeframe)
  2. Data consistency validation passes (no gaps, rowcounts match, EMAs calculate correctly)
  3. Backtest reproducibility validation passes (identical results on reruns)
  4. Release v0.4.0 tagged with full documentation (README, ARCHITECTURE, API docs)
  5. All 41 v1 requirements validated and marked complete
**Plans**: TBD

Plans:
- [ ] TBD (to be planned)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Quota Management | 3/3 | Complete | 2026-01-27 |
| 2. Memory Core | 4/5 | Gap closure | - |
| 3. Memory Advanced | 0/TBD | Not started | - |
| 4. Orchestrator Adapters | 0/TBD | Not started | - |
| 5. Orchestrator Coordination | 0/TBD | Not started | - |
| 6. ta_lab2 Time Model | 0/TBD | Not started | - |
| 7. ta_lab2 Feature Pipeline | 0/TBD | Not started | - |
| 8. ta_lab2 Signals | 0/TBD | Not started | - |
| 9. Integration & Observability | 0/TBD | Not started | - |
| 10. Release Validation | 0/TBD | Not started | - |

---
*Created: 2025-01-22*
*Last updated: 2026-01-28 (Phase 2 gap closure: added 02-05-PLAN.md to fix embedding dimension mismatch)*
