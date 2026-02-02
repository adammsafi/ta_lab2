# Roadmap: ta_lab2 AI-Accelerated Quant Platform

## Milestones

- v0.4.0 Memory Infrastructure & Orchestrator (Phases 1-10) - SHIPPED 2026-02-01
- v0.5.0 Ecosystem Reorganization (Phases 11-19) - IN PROGRESS

## Overview

Build trustworthy quant trading infrastructure 3x faster by creating AI coordination that remembers context across platforms. v0.4.0 established quota management, memory infrastructure (3,763 memories in Qdrant via Mem0), multi-platform orchestration with cost optimization, and ta_lab2 development (time model, features, signals). v0.5.0 consolidates four external project directories (ProjectTT, Data_Tools, fredtools2, fedtools2) into the unified ta_lab2 structure with memory-first auditability and zero deletion.

## Phases

**Phase Numbering:**
- Phases 1-10: v0.4.0 (complete)
- Phases 11-19: v0.5.0 (current milestone)
- Decimal phases (11.1, 12.1): Urgent insertions if needed

<details>
<summary>v0.4.0 Memory Infrastructure & Orchestrator (Phases 1-10) - SHIPPED 2026-02-01</summary>

- [x] **Phase 1: Foundation & Quota Management** - Infrastructure validation and quota tracking foundation
- [x] **Phase 2: Memory Core (ChromaDB Integration)** - Integrate existing 3,763 memories and enable semantic search
- [x] **Phase 3: Memory Advanced (Mem0 Migration)** - Migrate to Mem0 + Qdrant, add conflict resolution and health monitoring
- [x] **Phase 4: Orchestrator Adapters** - Claude, ChatGPT, Gemini platform integrations
- [x] **Phase 5: Orchestrator Coordination** - Routing, handoffs, parallel execution, cost tracking
- [x] **Phase 6: ta_lab2 Time Model** - Dimension tables and EMA unification
- [x] **Phase 7: ta_lab2 Feature Pipeline** - Returns, volatility, technical indicators
- [x] **Phase 8: ta_lab2 Signals** - Signal generation and backtest integration
- [x] **Phase 9: Integration & Observability** - Cross-system validation and monitoring
- [x] **Phase 10: Release Validation** - Final tests, documentation, v0.4.0 tag

</details>

### v0.5.0 Ecosystem Reorganization (Phases 11-19) - IN PROGRESS

- [ ] **Phase 11: Memory Preparation** - Initialize memory state before any file moves (BLOCKER)
- [ ] **Phase 12: Archive Foundation** - Establish .archive/ structure and preservation patterns
- [ ] **Phase 13: Documentation Consolidation** - Convert and integrate ProjectTT docs with memory tracking
- [ ] **Phase 14: Tools Integration** - Migrate Data_Tools scripts with memory updates
- [ ] **Phase 15: Economic Data Strategy** - Evaluate and integrate fredtools2/fedtools2 with memory updates
- [ ] **Phase 16: Repository Cleanup** - Clean root directory with memory updates
- [ ] **Phase 17: Verification & Validation** - Validate imports, dependencies, and structure
- [ ] **Phase 18: Structure Documentation** - Document final structure and migration decisions
- [ ] **Phase 19: Memory Validation & Release** - Final memory validation and milestone release

## Phase Details

<details>
<summary>v0.4.0 Phase Details (Phases 1-10) - COMPLETE</summary>

### Phase 1: Foundation & Quota Management
**Goal**: Quota tracking system operational and infrastructure validated for parallel development
**Depends on**: Nothing (first phase)
**Requirements**: ORCH-05, ORCH-11
**Success Criteria** (what must be TRUE):
  1. System tracks Gemini quota usage (1500/day limit) with UTC midnight reset
  2. Pre-flight adapter validation prevents routing to unimplemented adapters
  3. Infrastructure dependencies (Mem0, Vertex AI, platform SDKs) installed and verified
  4. Development environment supports parallel work on memory/orchestrator/ta_lab2 tracks
**Plans**: 3/3 complete

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
**Plans**: 5/5 complete

### Phase 3: Memory Advanced (Mem0 Migration)
**Goal**: Memory system migrated to Mem0 with self-maintenance and conflict detection
**Depends on**: Phase 2
**Requirements**: MEMO-09, MEMO-05, MEMO-06, MEMO-08
**Success Criteria** (what must be TRUE):
  1. All 3,763 memories successfully migrated from ChromaDB -> Mem0 (using Qdrant as backend)
  2. Conflicting memories detected and resolved (no contradictory context)
  3. Stale memories flagged with deprecated_since timestamp
  4. Memory health monitoring detects outdated context before it poisons decisions
  5. All memories have enhanced metadata (created_at, last_verified, deprecated_since)
**Plans**: 6/6 complete

### Phase 4: Orchestrator Adapters
**Goal**: All three AI platforms (Claude, ChatGPT, Gemini) accessible via unified adapter interface
**Depends on**: Phase 1 (quota tracking for Gemini)
**Requirements**: ORCH-01, ORCH-02, ORCH-03
**Success Criteria** (what must be TRUE):
  1. Claude Code adapter executes tasks via subprocess and parses file results
  2. ChatGPT adapter executes tasks via OpenAI API integration
  3. Gemini adapter executes tasks via gcloud CLI + API with quota tracking
  4. All adapters implement common interface for task submission and result retrieval
**Plans**: 4/4 complete

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
**Plans**: 6/6 complete

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
**Plans**: 6/6 complete

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
**Plans**: 7/7 complete

### Phase 8: ta_lab2 Signals
**Goal**: Trading signals generated and backtestable with reproducible results
**Depends on**: Phase 7 (feature pipeline)
**Requirements**: SIG-01, SIG-02
**Success Criteria** (what must be TRUE):
  1. cmc_signals_daily generates EMA crossovers, RSI mean reversion, ATR breakout signals
  2. Backtest integration v1 references cmc_daily_features and produces PnL
  3. Backtest reruns produce identical signals and PnL (reproducibility validated)
**Plans**: 6/6 complete

### Phase 9: Integration & Observability
**Goal**: Cross-system validation proves memory + orchestrator + ta_lab2 work together
**Depends on**: Phase 5 (orchestrator), Phase 8 (signals)
**Requirements**: SIG-03
**Success Criteria** (what must be TRUE):
  1. Observability infrastructure tests pass (tracing, metrics, health checks, workflow state)
  2. TF alignment tests confirm calculations use correct timeframes
  3. Roll alignment tests validate calendar boundary handling
  4. Orchestrator successfully coordinates ta_lab2 feature refresh tasks via memory context
  5. End-to-end workflow: user submits task -> orchestrator routes -> memory provides context -> ta_lab2 executes -> results stored
**Plans**: 7/7 complete

### Phase 10: Release Validation
**Goal**: v0.4.0 release ready with full documentation and validation
**Depends on**: Phase 9 (integration)
**Requirements**: SIG-04, SIG-05, SIG-06, SIG-07
**Success Criteria** (what must be TRUE):
  1. Time alignment validation passes (all calculations use correct TF from dim_timeframe)
  2. Data consistency validation passes (no gaps, rowcounts match, EMAs calculate correctly)
  3. Backtest reproducibility validation passes (identical results on reruns)
  4. Release v0.4.0 tagged with full documentation (README, ARCHITECTURE, API docs)
  5. All 42 v1 requirements validated and marked complete
**Plans**: 8/8 complete

</details>

### Phase 11: Memory Preparation
**Goal**: Capture current state of all codebases in memory before any file moves
**Depends on**: Phase 10 (v0.4.0 complete)
**Requirements**: MEMO-10, MEMO-11, MEMO-12
**Success Criteria** (what must be TRUE):
  1. Memory contains v0.4.0 completion context and current project state
  2. ta_lab2 codebase has baseline memory snapshot with pre_reorg_v0.5.0 tag
  3. All external directories (Data_Tools, ProjectTT, fredtools2, fedtools2) indexed in memory
  4. Pre-integration memories tagged with pre_integration_v0.5.0 metadata
  5. Memory queries can answer "What files exist in directory X?" for all 5 directories
**Plans**: 5 plans
Plans:
- [ ] 11-01-PLAN.md - Create extraction and indexing infrastructure
- [ ] 11-02-PLAN.md - Index ta_lab2 codebase snapshot
- [ ] 11-03-PLAN.md - Index external directories snapshot
- [ ] 11-04-PLAN.md - Extract v0.4.0 conversation history
- [ ] 11-05-PLAN.md - Validate 100% coverage and document state

### Phase 12: Archive Foundation
**Goal**: Establish archive structure and preservation patterns before any file moves
**Depends on**: Phase 11
**Requirements**: ARCH-01, ARCH-02, ARCH-03, ARCH-04
**Success Criteria** (what must be TRUE):
  1. .archive/ directory exists with timestamped subdirectories and category structure
  2. 00-README.md documents archive contents and retrieval instructions
  3. manifest.json template created for tracking archived files
  4. git mv verified to preserve history (git log --follow works for test file)
  5. Pre-reorganization file counts recorded for validation
**Plans**: TBD

### Phase 13: Documentation Consolidation
**Goal**: Convert ProjectTT documentation and integrate into docs/ structure
**Depends on**: Phase 12
**Requirements**: DOC-01, DOC-02, DOC-03, MEMO-13, MEMO-14
**Success Criteria** (what must be TRUE):
  1. ProjectTT .docx files converted to Markdown in docs/
  2. docs/index.md serves as documentation home page
  3. Original Excel/Word files preserved in .archive/documentation/
  4. Memory updated with moved_to relationships for each file
  5. Phase-level memory snapshot created with phase 13 tag
**Plans**: TBD

### Phase 14: Tools Integration
**Goal**: Migrate Data_Tools scripts into ta_lab2/tools/ with working imports
**Depends on**: Phase 13
**Requirements**: TOOL-01, TOOL-02, TOOL-03, MEMO-13, MEMO-14
**Success Criteria** (what must be TRUE):
  1. Data_Tools scripts moved to src/ta_lab2/tools/data_tools/
  2. All import paths updated (no hardcoded paths remain)
  3. pytest smoke tests pass for migrated scripts
  4. Memory updated with moved_to relationships for each file
  5. Phase-level memory snapshot created with phase 14 tag
**Plans**: TBD

### Phase 15: Economic Data Strategy
**Goal**: Evaluate fredtools2/fedtools2 and implement integration decision
**Depends on**: Phase 14
**Requirements**: ECON-01, ECON-02, ECON-03, MEMO-13, MEMO-14
**Success Criteria** (what must be TRUE):
  1. Function inventory complete for both packages
  2. Decision documented: merge into ta_lab2, keep as optional deps, or archive
  3. If integrating: packages accessible via pip install ta_lab2[economic-data]
  4. If archiving: packages in .archive/economic_data/ with documentation
  5. Memory updated with integration decision and file locations
**Plans**: TBD

### Phase 16: Repository Cleanup
**Goal**: Clean root directory and consolidate duplicate files
**Depends on**: Phase 15
**Requirements**: CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04, MEMO-13, MEMO-14
**Success Criteria** (what must be TRUE):
  1. Root directory contains only essential files (README, pyproject.toml, core configs)
  2. Temp files, *_refactored.py, *.original archived with manifest
  3. Loose .md files moved to appropriate docs/ subdirectories
  4. Exact duplicates identified via SHA256 and archived
  5. Similar functions (85%+ threshold) flagged for review
**Plans**: TBD

### Phase 17: Verification & Validation
**Goal**: Validate all imports work and no data was lost
**Depends on**: Phase 16
**Requirements**: VAL-01, VAL-02, VAL-03, VAL-04
**Success Criteria** (what must be TRUE):
  1. All ta_lab2 modules importable without errors
  2. No circular dependencies detected (pycycle/import-linter clean)
  3. CI tests validate organization rules (no .py in root, manifest integrity)
  4. Pre-commit hooks installed preventing future disorganization
  5. File count validation: pre + archived = post (zero data loss)
**Plans**: TBD

### Phase 18: Structure Documentation
**Goal**: Document final structure and migration decisions for future reference
**Depends on**: Phase 17
**Requirements**: STRUCT-01, STRUCT-02, STRUCT-03
**Success Criteria** (what must be TRUE):
  1. docs/REORGANIZATION.md explains what moved where and why
  2. README updated with new ecosystem structure and component links
  3. YAML/JSON manifest tracks rationale for each major decision
  4. Before/after directory tree diagrams included
  5. Migration guide enables finding moved files
**Plans**: TBD

### Phase 19: Memory Validation & Release
**Goal**: Validate memory completeness and release v0.5.0
**Depends on**: Phase 18
**Requirements**: MEMO-15, MEMO-16, MEMO-17, MEMO-18
**Success Criteria** (what must be TRUE):
  1. Function-level memories exist for significant functions
  2. Memory relationship types complete (contains, calls, imports, moved_to, similar_to)
  3. Duplicate functions detected and documented (95%+, 85-95%, 70-85% thresholds)
  4. Memory graph validation passes (no orphans, all relationships linked)
  5. Memory queries work: function lookup, cross-reference, edit impact analysis
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> ... -> 10 (v0.4.0) -> 11 -> 12 -> ... -> 19 (v0.5.0)

### v0.4.0 Progress (Complete)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation & Quota Management | 3/3 | Complete | 2026-01-27 |
| 2. Memory Core | 5/5 | Complete | 2026-01-28 |
| 3. Memory Advanced | 6/6 | Complete | 2026-01-28 |
| 4. Orchestrator Adapters | 4/4 | Complete | 2026-01-29 |
| 5. Orchestrator Coordination | 6/6 | Complete | 2026-01-29 |
| 6. ta_lab2 Time Model | 6/6 | Complete | 2026-01-30 |
| 7. ta_lab2 Feature Pipeline | 7/7 | Complete | 2026-01-30 |
| 8. ta_lab2 Signals | 6/6 | Complete | 2026-01-30 |
| 9. Integration & Observability | 7/7 | Complete | 2026-01-30 |
| 10. Release Validation | 8/8 | Complete | 2026-02-01 |

### v0.5.0 Progress (Current)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 11. Memory Preparation | 0/5 | Planned | - |
| 12. Archive Foundation | 0/TBD | Not started | - |
| 13. Documentation Consolidation | 0/TBD | Not started | - |
| 14. Tools Integration | 0/TBD | Not started | - |
| 15. Economic Data Strategy | 0/TBD | Not started | - |
| 16. Repository Cleanup | 0/TBD | Not started | - |
| 17. Verification & Validation | 0/TBD | Not started | - |
| 18. Structure Documentation | 0/TBD | Not started | - |
| 19. Memory Validation & Release | 0/TBD | Not started | - |

## Requirement Coverage

### v0.5.0 Requirements (32 total)

| Category | Requirements | Phase(s) | Count |
|----------|--------------|----------|-------|
| Memory Integration | MEMO-10, MEMO-11, MEMO-12 | Phase 11 | 3 |
| Memory Integration | MEMO-13, MEMO-14 | Phases 13-16 | 2 (used in 4 phases) |
| Memory Integration | MEMO-15, MEMO-16, MEMO-17, MEMO-18 | Phase 19 | 4 |
| Archive Management | ARCH-01, ARCH-02, ARCH-03, ARCH-04 | Phase 12 | 4 |
| Documentation | DOC-01, DOC-02, DOC-03 | Phase 13 | 3 |
| Tools Integration | TOOL-01, TOOL-02, TOOL-03 | Phase 14 | 3 |
| Economic Data | ECON-01, ECON-02, ECON-03 | Phase 15 | 3 |
| Repository Cleanup | CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04 | Phase 16 | 4 |
| Verification | VAL-01, VAL-02, VAL-03, VAL-04 | Phase 17 | 4 |
| Structure Docs | STRUCT-01, STRUCT-02, STRUCT-03 | Phase 18 | 3 |

**Coverage:** 32/32 requirements mapped (100%)

---
*Created: 2025-01-22*
*Last updated: 2026-02-02 (Phase 11 planned: 5 plans in 3 waves)*
