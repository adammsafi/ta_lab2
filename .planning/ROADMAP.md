# Roadmap: ta_lab2 AI-Accelerated Quant Platform

## Milestones

- v0.4.0 Memory Infrastructure & Orchestrator (Phases 1-10) - SHIPPED 2026-02-01
- v0.5.0 Ecosystem Reorganization (Phases 11-19) - SHIPPED 2026-02-04
- v0.6.0 EMA & Bar Architecture Standardization (Phases 20-26) - SHIPPED 2026-02-17
- v0.7.0 Regime Integration & Signal Enhancement (Phases 27-28) - SHIPPED 2026-02-20
- v0.8.0 Polish & Hardening (Phases 29-34) - SHIPPED 2026-02-23
- v0.9.0 Research & Experimentation (Phases 35-41) - SHIPPED 2026-02-24
- v1.0.0 V1 Closure — Paper Trading & Validation (Phases 42-60) - current milestone

## Overview

Build trustworthy quant trading infrastructure 3x faster by creating AI coordination that remembers context across platforms. v0.4.0 established quota management, memory infrastructure (3,763 memories in Qdrant via Mem0), multi-platform orchestration with cost optimization, and ta_lab2 development (time model, features, signals). v0.5.0 consolidated four external project directories into unified ta_lab2 structure. v0.6.0 locks down the bars and EMAs foundation so adding new assets (crypto + equities) is mechanical and reliable. v0.9.0 completes the research cycle: new adaptive indicators, IC-based feature evaluation, statistically sound CV, a feature experimentation framework, interactive visualization, and rolling asset descriptive statistics with cross-asset correlation. v1.0.0 closes the V1 loop from the foundational Project Plan: strategy bake-off, paper-trade executor, risk controls, drift guard, all 6 research tracks answered, 2+ weeks live paper validation, and V1 Results Memo.

## Phases

**Phase Numbering:**
- Phases 1-10: v0.4.0 (complete)
- Phases 11-19: v0.5.0 (complete)
- Phases 20-26: v0.6.0 (complete)
- Phases 27-28: v0.7.0 (complete)
- Phases 29-34: v0.8.0 (complete)
- Phases 35-41: v0.9.0 (SHIPPED 2026-02-24)
- Phases 42-60: v1.0.0 (current -- V1 Closure)
- Decimal phases (27.1, 28.1): Urgent insertions if needed

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

<details>
<summary>v0.5.0 Ecosystem Reorganization (Phases 11-19) - SHIPPED 2026-02-04</summary>

- [x] **Phase 11: Memory Preparation** - Initialize memory state before any file moves (BLOCKER)
- [x] **Phase 12: Archive Foundation** - Establish .archive/ structure and preservation patterns
- [x] **Phase 13: Documentation Consolidation** - Convert and integrate ProjectTT docs with memory tracking
- [x] **Phase 14: Tools Integration** - Migrate Data_Tools scripts with memory updates
- [x] **Phase 15: Economic Data Strategy** - Archive packages, extract utils, create integration skeleton with memory updates
- [x] **Phase 16: Repository Cleanup** - Clean root directory and memory updates
- [x] **Phase 17: Verification & Validation** - Validate imports, dependencies, and structure
- [x] **Phase 18: Structure Documentation** - Document final structure and migration decisions
- [x] **Phase 19: Memory Validation & Release** - Final memory validation and milestone release

</details>

<details>
<summary>v0.6.0 EMA & Bar Architecture Standardization (Phases 20-26) - SHIPPED 2026-02-17</summary>

- [x] **Phase 20: Historical Context** - Review GSD phases 1-10 and existing documentation
- [x] **Phase 21: Comprehensive Review** - Complete read-only analysis of all bar/EMA components
- [x] **Phase 22: Critical Data Quality Fixes** - Fix 4 CRITICAL gaps + derive multi-TF from 1D bars
- [x] **Phase 23: Reliable Incremental Refresh** - Flexible orchestration, state management, visibility
- [x] **Phase 24: Pattern Consistency** - Standardize patterns where analysis justifies
- [x] **Phase 25: Baseline Capture** - Capture current outputs before validation testing
- [x] **Phase 26: Validation** - Verify fixes worked correctly, nothing broke

</details>

<details>
<summary>v0.7.0 Regime Integration & Signal Enhancement (Phases 27-28) - SHIPPED 2026-02-20</summary>

- [x] **Phase 27: Regime Integration** - Connect regime module to DB-backed feature pipeline
- [x] **Phase 28: Backtest Pipeline Fix** - Fix signal generators and backtest runner end-to-end

</details>

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

<details>
<summary>v0.5.0 Phase Details (Phases 11-19) - COMPLETE</summary>

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
**Plans**: 5/5 complete

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
**Plans**: 3/3 complete

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
**Plans**: 7/7 complete

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
**Plans**: 13/13 complete

### Phase 15: Economic Data Strategy
**Goal**: Archive packages, extract valuable utilities, create production-ready integration skeleton
**Depends on**: Phase 14
**Requirements**: ECON-01, ECON-02, ECON-03, MEMO-13, MEMO-14
**Success Criteria** (what must be TRUE):
  1. fredtools2 and fedtools2 archived with comprehensive documentation
  2. Valuable utilities extracted to ta_lab2.utils.economic
  3. Production-ready ta_lab2.integrations.economic with working FredProvider
  4. Rate limiting, caching, circuit breaker, data quality validation implemented
  5. pyproject.toml updated with optional dependency extras
  6. Migration support: README guide, migration tool
  7. Memory updated with archive/extraction/replacement relationships
**Plans**: 6/6 complete

### Phase 16: Repository Cleanup
**Goal**: Clean root directory and consolidate duplicate files
**Depends on**: Phase 15
**Requirements**: CLEAN-01, CLEAN-02, CLEAN-03, CLEAN-04, MEMO-13, MEMO-14
**Success Criteria** (what must be TRUE):
  1. Root directory contains only essential files
  2. Temp files, *_refactored.py, *.original archived with manifest
  3. Loose .md files moved to appropriate docs/ subdirectories
  4. Exact duplicates identified via SHA256 and archived
  5. Similar functions flagged for review
**Plans**: 7/7 complete

### Phase 17: Verification & Validation
**Goal**: Validate all imports work and no data was lost
**Depends on**: Phase 16
**Requirements**: VAL-01, VAL-02, VAL-03, VAL-04
**Success Criteria** (what must be TRUE):
  1. All ta_lab2 modules importable without errors
  2. No circular dependencies detected
  3. CI tests validate organization rules
  4. Pre-commit hooks installed
  5. File count validation: pre + archived = post (zero data loss)
**Plans**: 8/8 complete

### Phase 18: Structure Documentation
**Goal**: Document final structure and migration decisions for future reference
**Depends on**: Phase 17
**Requirements**: STRUCT-01, STRUCT-02, STRUCT-03
**Success Criteria** (what must be TRUE):
  1. docs/REORGANIZATION.md explains what moved where and why
  2. README updated with new ecosystem structure
  3. YAML/JSON manifest tracks rationale for each major decision
  4. Before/after directory tree diagrams included
  5. Migration guide enables finding moved files
**Plans**: 4/4 complete

### Phase 19: Memory Validation & Release
**Goal**: Validate memory completeness and release v0.5.0
**Depends on**: Phase 18
**Requirements**: MEMO-15, MEMO-16, MEMO-17, MEMO-18
**Success Criteria** (what must be TRUE):
  1. Function-level memories exist for significant functions
  2. Memory relationship types complete
  3. Duplicate functions detected and documented
  4. Memory graph validation passes
  5. Memory queries work
**Plans**: 6/6 complete

</details>

<details>
<summary>v0.6.0 Phase Details (Phases 20-26) - COMPLETE</summary>

### Phase 20: Historical Context
**Goal**: Understand how we got here before making changes
**Depends on**: Phase 19 (v0.5.0 complete)
**Requirements**: HIST-01, HIST-02, HIST-03
**Success Criteria** (what must be TRUE):
  1. GSD phases 1-10 reviewed with key decisions documented
  2. Existing documentation inventory complete (what to leverage, what's missing)
  3. Current state assessment documented (what works, what's unclear, what's broken)
**Plans**: 3 plans

Plans:
- [x] 20-01-PLAN.md - Historical review: mine Git history and SUMMARYs for bar/EMA evolution narrative
- [x] 20-02-PLAN.md - Documentation inventory: catalog all bar/EMA docs with multi-dimensional categorization
- [x] 20-03-PLAN.md - Current state assessment: feature-level health matrix for bars and EMAs

---

### Phase 21: Comprehensive Review
**Goal**: Complete ALL analysis before any code changes
**Depends on**: Phase 20
**Requirements**: RVWQ-01, RVWQ-02, RVWQ-03, RVWQ-04, RVWD-01, RVWD-02, RVWD-03, RVWD-04
**Success Criteria** (what must be TRUE):
  1. All 4 understanding questions answered (EMA variants, incremental refresh, validation points, new asset process)
  2. Script inventory table complete (every bar/EMA script cataloged with purpose, tables, state, dependencies)
  3. Data flow diagram exists showing price_histories7 -> bars -> EMAs with validation points marked
  4. Variant comparison matrix complete (6 EMA variants side-by-side)
  5. Gap analysis document produced with severity tiers (CRITICAL/HIGH/MEDIUM/LOW)
**Plans**: 4 plans

Plans:
- [x] 21-01-PLAN.md - Script inventory and data flow diagram (RVWD-01, RVWD-02)
- [x] 21-02-PLAN.md - EMA variants analysis and comparison matrix (RVWQ-01, RVWD-03)
- [x] 21-03-PLAN.md - Incremental refresh and validation points (RVWQ-02, RVWQ-03)
- [x] 21-04-PLAN.md - New asset guide and gap analysis (RVWQ-04, RVWD-04)

---

### Phase 22: Critical Data Quality Fixes
**Goal**: Fix 4 CRITICAL data quality gaps + architectural refactor to derive multi-TF from 1D bars
**Depends on**: Phase 21
**Requirements**: GAP-C01, GAP-C02, GAP-C03, GAP-C04
**Success Criteria** (what must be TRUE):
  1. Multi-TF builders log OHLC repairs to reject tables (GAP-C01 closed)
  2. EMA output validation catches NaN/infinity/out-of-range values (GAP-C02 closed)
  3. 1D builder detects backfills and triggers rebuilds (GAP-C03 simple fix)
  4. Multi-TF bars can be derived from 1D bars (GAP-C03 architectural refactor)
  5. Automated validation test suite runs in CI (GAP-C04 closed)
**Plans**: 6 plans in 3 waves

Plans:
- [x] 22-01-PLAN.md - Multi-TF reject tables (GAP-C01: shared schema + 5 builders)
- [x] 22-02-PLAN.md - EMA output validation (GAP-C02: hybrid bounds in BaseEMARefresher)
- [x] 22-03-PLAN.md - 1D backfill detection (GAP-C03 Part 1: daily_min_seen column)
- [x] 22-04-PLAN.md - Derive multi-TF foundation (GAP-C03 Part 2: derivation module + main builder)
- [x] 22-05-PLAN.md - Derive multi-TF calendar builders (GAP-C03 Part 3: all 4 calendar variants)
- [x] 22-06-PLAN.md - Automated validation test suite (GAP-C04: tests + CI integration)

---

### Phase 23: Reliable Incremental Refresh
**Goal**: One command for daily refresh with clear visibility into what happened
**Depends on**: Phase 22
**Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-04, STAT-01, STAT-02, STAT-03, STAT-04, VISI-01, VISI-02, VISI-03
**Success Criteria** (what must be TRUE):
  1. Orchestration script can run: all tasks, bars only, EMAs only, or specific variant
  2. Bars and EMAs execute as separate modular pieces with clear interfaces
  3. One command handles daily refresh with meaningful log output
  4. State management patterns documented and consistent across scripts
  5. Logs show what was processed (X days, Y bars, Z EMAs, N gaps flagged)
**Plans**: 4 plans in 3 waves

Plans:
- [x] 23-01-PLAN.md - Enhance EMA orchestrator (subprocess, dry-run, summary reporting)
- [x] 23-02-PLAN.md - Unified daily refresh script (run_daily_refresh.py with state coordination)
- [x] 23-03-PLAN.md - Makefile and log infrastructure (convenience targets, daily logs, alerting)
- [x] 23-04-PLAN.md - Documentation (state management patterns, operational guide)

---

### Phase 24: Pattern Consistency
**Goal**: Standardize bar builder patterns by extracting BaseBarBuilder following proven BaseEMARefresher template
**Depends on**: Phase 23
**Requirements**: PATT-01, PATT-02, PATT-03, PATT-04, PATT-05, PATT-06
**Success Criteria** (what must be TRUE):
  1. All 6 EMA variants retained (no consolidation)
  2. BaseBarBuilder template class created mirroring BaseEMARefresher pattern
  3. All 6 bar builders refactored to use BaseBarBuilder (70% LOC reduction target)
  4. Calendar tz column design rationale documented (GAP-M03 closed)
  5. Standardization applied only where gap analysis justified (no premature abstraction)
**Plans**: 4 plans in 3 waves

Plans:
- [x] 24-01-PLAN.md - Design and create BaseBarBuilder template class (GAP-M01 foundation)
- [x] 24-02-PLAN.md - Refactor 1D bar builder to use BaseBarBuilder (proof of concept)
- [x] 24-03-PLAN.md - Refactor main multi-TF builder to use BaseBarBuilder
- [x] 24-04-PLAN.md - Refactor 4 calendar builders + document tz column (GAP-M03)

---

### Phase 25: Baseline Capture
**Goal**: Capture current bar and EMA outputs before validation testing using Snapshot -> Truncate -> Rebuild -> Compare workflow
**Depends on**: Phase 24
**Requirements**: TEST-01
**Success Criteria** (what must be TRUE):
  1. Baseline outputs captured for all 6 bar tables and 4 EMA tables
  2. Baselines stored in timestamped snapshot tables suitable for comparison
  3. Comparison uses epsilon tolerance with hybrid bounds (rtol + atol)
  4. Baseline capture documented and reproducible with full metadata audit trail
**Plans**: 2 plans in 2 waves

Plans:
- [x] 25-01-PLAN.md - Infrastructure (dim_assets DDL, comparison utilities, metadata tracker)
- [x] 25-02-PLAN.md - Orchestration script (Snapshot -> Truncate -> Rebuild -> Compare workflow)

---

### Phase 26: Validation & Architectural Standardization
**Goal**: Validate architecture through unified schemas, lean tables, enriched returns, and comprehensive test infrastructure
**Depends on**: Phase 25
**Requirements**: TEST-02, TEST-03, TEST-04, TEST-05
**Success Criteria** (what must be TRUE):
  1. Unified bar schema deployed across all 6 bar tables with consistent PK structure
  2. Lean EMA tables (derivatives dropped), dual-EMA schema (ema + ema_bar) operational
  3. Enriched returns schema with delta1, delta2, ret_arith, ret_log, series discriminator
  4. Incremental stats scripts validate all table families with watermark-based monitoring
  5. Pytest schema tests pass for all existing tables; missing tables gracefully skipped
  6. All 18 audit scripts runnable; returns stats produce PASS across 1,215+ key groups

Plans:
- [x] 26-01: Unified bar schema, lean EMAs, enriched returns (SQL migrations + code)
- [x] 26-02: Returns EMA stats scripts + schema tests + audit updates
- [x] 26-03: Fix false positives, graceful missing-table handling, documentation

</details>

<details>
<summary>v0.7.0 Phase Details (Phases 27-28) - COMPLETE</summary>

### Phase 27: Regime Integration
**Goal:** Connect existing regime module (labels, policy resolver, hysteresis, data budget) to DB-backed feature pipeline. Write refresh_cmc_regimes.py that reads from cmc_features and calendar bar tables, runs L0-L2 labeling, resolves policy, writes to cmc_regimes table. Wire regime context into signal generators.
**Depends on:** Phase 26
**Success Criteria** (what must be TRUE):
  1. refresh_cmc_regimes.py reads from cmc_features and calendar bar tables (weekly/monthly)
  2. L0-L2 regime labeling runs against DB data with correct EMA column mapping
  3. Policy resolver produces regime labels written to cmc_regimes table
  4. Data budget gating correctly enables/disables layers based on bar history
  5. Signal generators accept regime context for position sizing/filtering
**Plans**: 7 plans in 4 waves

Plans:
- [x] 27-01-PLAN.md -- DDL for regime tables (cmc_regimes, cmc_regime_flips, cmc_regime_stats) + signal table extensions
- [x] 27-02-PLAN.md -- EMA pivot utility and DB data loaders (regime_data_loader.py)
- [x] 27-03-PLAN.md -- Core refresh_cmc_regimes.py (labeling + policy resolution + DB write)
- [x] 27-04-PLAN.md -- HysteresisTracker + flip detection + stats computation
- [x] 27-05-PLAN.md -- Wire hysteresis/flips/stats into refresh script + CLI flags
- [x] 27-06-PLAN.md -- Signal generator regime integration (all 3 generators + --no-regime flag)
- [x] 27-07-PLAN.md -- Orchestrator integration (run_daily_refresh.py) + regime_inspect.py + end-to-end verification

---

### Phase 28: Backtest Pipeline Fix
**Goal:** Fix the signal generators (dict serialization bug in feature_snapshot) and backtest runner (vectorbt timestamp errors) so the full signal-to-backtest pipeline works end-to-end. Without this, no strategy validation is possible.
**Depends on:** Phase 26 (can run in parallel with Phase 27)
**Success Criteria** (what must be TRUE):
  1. Signal generators write to DB without errors (feature_snapshot serialized correctly)
  2. All 3 signal refreshers (RSI, EMA crossover, ATR breakout) complete without crashes
  3. Backtest runner reads signals and produces PnL results without vectorbt timestamp errors
  4. End-to-end pipeline works: cmc_features -> signals -> backtest -> PnL summary
  5. At least one signal type produces a complete backtest report
**Plans**: 3 plans in 2 waves

Plans:
- [x] 28-01-PLAN.md -- Fix EMA and ATR signal generator feature_snapshot serialization (json.dumps)
- [x] 28-02-PLAN.md -- Fix vectorbt boundary bugs in backtest_from_signals.py (tz, direction, fees, cost_model)
- [x] 28-03-PLAN.md -- End-to-end pipeline verification (signal generation + backtest + DB storage)

</details>

<details>
<summary>v0.8.0 Polish & Hardening (Phases 29-34) - SHIPPED 2026-02-23</summary>

- [x] **Phase 29: Stats/QA Orchestration** - Wire 5 existing stats runners into daily refresh pipeline + weekly QC digest
- [x] **Phase 30: Code Quality Tooling** - Make ruff lint blocking in CI, add mypy config, fix stale tooling references
- [x] **Phase 31: Documentation Freshness** - Version sync, pipeline mermaid diagram, fix stale refs, mkdocs build clean
- [x] **Phase 32: Runbooks** - Regime runbook, backtest runbook, new-asset SOP, disaster recovery guide
- [x] **Phase 33: Alembic Migrations** - Bootstrap framework, stamp existing schema, catalog legacy SQL migrations
- [x] **Phase 34: Audit Cleanup** - Close 4 tech debt items from milestone audit

</details>

<details>
<summary>v0.9.0 Research & Experimentation (Phases 35-41) - SHIPPED 2026-02-24</summary>

- [x] **Phase 35: AMA Engine** - Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA) with full calendar parity
- [x] **Phase 36: PSR + Purged K-Fold** - Probabilistic Sharpe Ratio, DSR, MinTRL + leakage-free CV splitters
- [x] **Phase 37: IC Evaluation** - Information Coefficient scoring engine with regime breakdown and significance testing
- [x] **Phase 38: Feature Experimentation** - YAML registry, ExperimentRunner, BH-corrected promotion gate
- [x] **Phase 39: Streamlit Dashboard** - Pipeline monitor + research explorer with cached DB queries
- [x] **Phase 40: Notebooks** - 3-5 polished Jupyter notebooks demonstrating the full research cycle
- [x] **Phase 41: Asset Descriptive Stats & Correlation** - Rolling per-asset summary stats + cross-asset return correlation time series
- [x] **Phase 41.1: Milestone Cleanup** - Close tech debt from v0.9.0 audit (AMA allowlist, features.yaml, dashboard enhancements)

</details>

<details>
<summary>v0.9.0 Phase Details (Phases 35-41) - COMPLETE</summary>

### Phase 35: AMA Engine
**Goal:** Users can compute and refresh Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA) across all timeframes, with derivatives, z-scores, and unified table sync wired into the daily refresh pipeline.
**Depends on:** Phase 34 (v0.8.0 complete)
**Requirements:** AMA-01, AMA-02, AMA-03, AMA-04, AMA-05, AMA-06, AMA-07
**Success Criteria** (what must be TRUE):
  1. `python -m ta_lab2.scripts.amas.run_all_ama_refreshes --ids all --all-tfs` completes without errors and populates `cmc_ama_multi_tf` with KAMA, DEMA, TEMA, and HMA rows
  2. `cmc_ama_multi_tf` has PK `(id, ts, tf, indicator, params_hash)` and includes derivative columns (d1, d2, d1_roll, d2_roll); rows with insufficient warmup data are NULL rather than computed from stale state
  3. KAMA Efficiency Ratio is stored as a standalone column in `cmc_ama_multi_tf`, queryable independently from the AMA value itself
  4. Z-scores (_zscore_30, _zscore_90, _zscore_365) appear on AMA returns rows after running the existing `refresh_returns_zscore.py` against the AMA returns table
  5. `run_daily_refresh.py --all` executes the AMA stage (after EMAs) and the `cmc_ama_multi_tf_u` unified table is populated via sync
**Plans**: 8/8 complete

Plans:
- [x] 35-01-PLAN.md -- DDL for all 12 AMA tables + state tables + dim_ama_params
- [x] 35-02-PLAN.md -- AMA computation functions (KAMA, DEMA, TEMA, HMA) + ama_params.py
- [x] 35-03-PLAN.md -- BaseAMAFeature class + AMAStateManager
- [x] 35-04-PLAN.md -- BaseAMARefresher + refresh_cmc_ama_multi_tf.py (main refresher)
- [x] 35-05-PLAN.md -- AMA returns feature class + returns refresher script
- [x] 35-06-PLAN.md -- Calendar variant refreshers (cal + cal_anchor)
- [x] 35-07-PLAN.md -- Sync scripts (_u tables) + z-score extension
- [x] 35-08-PLAN.md -- run_all_ama_refreshes.py orchestrator + daily refresh wiring

---

### Phase 36: PSR + Purged K-Fold
**Goal:** Users can compute statistically sound Sharpe ratio estimates (PSR, DSR, MinTRL) and perform leakage-free cross-validation (PurgedKFold, CPCV) on any backtest result or feature set.
**Depends on:** Phase 34 (v0.8.0 complete; can run in parallel with Phase 35)
**Requirements:** PSR-01, PSR-02, PSR-03, PSR-04, PSR-05, CV-01, CV-02, CV-03
**Success Criteria** (what must be TRUE):
  1. Alembic migration `psr_rename` completes cleanly: existing `psr` column renamed to `psr_legacy` in `cmc_backtest_metrics` with no data loss; `alembic history` shows the migration
  2. `compute_psr(returns, sr_star)` returns a value in [0, 1] matching Lopez de Prado formula using scipy skew/kurtosis; returns NaN when n < 30 and logs a warning when n < 100
  3. `compute_dsr(returns_list, sr_star)` deflates the best-of-N Sharpe correctly -- the deflated value is always <= the raw best Sharpe
  4. `PurgedKFoldSplitter(n_splits, t1_series, embargo_bars)` raises `ValueError` when `t1_series` is not provided; fold train/test indices contain no overlap after purging and embargoing
  5. `CombPurgedKFoldCV` generates the combinatorial path matrix required for PBO analysis; all generated paths cover the full sample without train-test contamination
**Plans**: 5/5 complete

Plans:
- [x] 36-01-PLAN.md -- Alembic migrations: psr column rename + psr_results table (PSR-01)
- [x] 36-02-PLAN.md -- PSR/DSR/MinTRL formulas via TDD (PSR-02, PSR-03, PSR-04, PSR-05)
- [x] 36-03-PLAN.md -- PurgedKFoldSplitter + CPCVSplitter via TDD (CV-01, CV-02, CV-03)
- [x] 36-04-PLAN.md -- Wire PSR into backtest pipeline + standalone CLI
- [x] 36-05-PLAN.md -- Alembic migration check in run_daily_refresh.py

---

### Phase 37: IC Evaluation
**Goal:** Users can score any feature column for predictive power across forward-return horizons, broken down by regime, with significance testing and results persisted to the database.
**Depends on:** Phase 34 (v0.8.0 complete; enhanced by Phase 35 AMAs but not blocked by them)
**Requirements:** IC-01, IC-02, IC-03, IC-04, IC-05, IC-06, IC-07, IC-08
**Success Criteria** (what must be TRUE):
  1. `compute_ic(feature_series, returns_df, train_start, train_end)` raises `TypeError` when `train_start`/`train_end` are omitted; passing future data beyond `train_end` does not affect the returned IC values
  2. Calling `compute_ic` with horizons `[1, 2, 3, 5, 10, 20, 60]` returns a DataFrame with one IC value per horizon; the IC decay table shows monotonically decreasing absolute IC as horizon increases for a known predictive feature
  3. Rolling IC time series (63-bar window) and IC-IR summary statistic are computed and match manual calculation on a test fixture
  4. `compute_ic_by_regime(feature_series, returns_df, regimes_df, train_start, train_end)` returns separate IC values per regime label; assets with no regime data return IC computed on the full sample
  5. IC significance t-stat and p-value are attached to each IC result row; feature turnover (rank autocorrelation) is computed and stored alongside IC in `cmc_ic_results`
**Plans**: 4 plans in 2 waves

Plans:
- [x] 37-01-PLAN.md -- Fix fillna deprecation + Alembic migration for cmc_ic_results table
- [x] 37-02-PLAN.md -- IC core library via TDD: compute_ic, rolling IC, IC-IR, significance, turnover
- [x] 37-03-PLAN.md -- Regime IC breakdown + batch wrapper + Plotly visualization helpers
- [x] 37-04-PLAN.md -- CLI script (run_ic_eval.py) + DB helpers (save/load)

---

### Phase 38: Feature Experimentation Framework
**Goal:** Users can register experimental features in YAML, score them with IC on demand without writing to production tables, and promote statistically significant features through a BH-corrected gate into `dim_feature_registry`.
**Depends on:** Phase 37 (IC evaluation is the scoring engine)
**Requirements:** FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05
**Success Criteria** (what must be TRUE):
  1. A YAML feature definition with `lifecycle: experimental` is picked up by `ExperimentRunner` without any DB schema changes; removing the YAML entry stops the feature from being scored
  2. `ExperimentRunner.run(feature_name, asset_ids, tf, train_start, train_end)` computes the feature from existing base data in memory, scores it with IC across all configured horizons, and writes results to `cmc_feature_experiments` -- no rows written to production feature tables
  3. `promote_feature(feature_name)` passes only when Benjamini-Hochberg corrected p-values are significant at alpha=0.05 for at least one horizon; calling it on a noise feature (IC ~ 0) raises `PromotionRejectedError`
  4. After promotion, the feature appears in `dim_feature_registry` with `lifecycle: promoted` and a migration stub is generated pointing to the Alembic migrations directory
  5. `alembic upgrade head` applies the `dim_feature_registry` and `cmc_feature_experiments` DDL migration cleanly on a fresh schema; `alembic downgrade -1` reverses it without errors
**Plans**: 5/5 complete

Plans:
- [x] 38-01-PLAN.md -- Alembic migration for dim_feature_registry and cmc_feature_experiments tables (FEAT-05)
- [x] 38-02-PLAN.md -- YAML feature registry + DAG dependency resolver (FEAT-01)
- [x] 38-03-PLAN.md -- ExperimentRunner + run_experiment.py CLI (FEAT-02, FEAT-03)
- [x] 38-04-PLAN.md -- FeaturePromoter + BH gate + promote/purge CLIs (FEAT-04)
- [x] 38-05-PLAN.md -- Unit tests + end-to-end verification

---

### Phase 39: Streamlit Dashboard
**Goal:** Users can launch a single Streamlit app that shows live pipeline health (Mode B) and interactive research results -- IC scores, regime timelines (Mode A) -- without hammering the database.
**Depends on:** Phases 35-38 (needs meaningful data to display; DASH-04 config is standalone)
**Requirements:** DASH-01, DASH-02, DASH-03, DASH-04
**Success Criteria** (what must be TRUE):
  1. `streamlit run src/ta_lab2/dashboard/app.py` starts without errors on Windows using `fileWatcherType = "poll"` config; the app loads within 10 seconds on a cold start
  2. Pipeline Monitor (Mode B) displays run status, data freshness per table, and the most recent stats runner PASS/FAIL result sourced from existing DB tables -- all without a manual page refresh
  3. Research Explorer (Mode A) renders an IC score table for a user-selected asset and timeframe, with regime timeline overlay, within the `@st.cache_data(ttl=300)` window
  4. All DB queries use a NullPool SQLAlchemy engine; running the dashboard for 30 minutes while repeatedly switching modes does not exhaust the database connection pool
**Plans**: 4/4 complete

Plans:
- [x] 39-01-PLAN.md -- Config + DB layer + app shell + query modules (DASH-03, DASH-04)
- [x] 39-02-PLAN.md -- Plotly chart builders (IC decay, rolling IC, regime timeline, regime price overlay)
- [x] 39-03-PLAN.md -- Landing page + Pipeline Monitor page (DASH-01)
- [x] 39-04-PLAN.md -- Research Explorer page (DASH-02)

---

### Phase 40: Notebooks
**Goal:** Users can hand off 3-5 polished Jupyter notebooks that demonstrate the full v0.9.0 research cycle -- from AMA exploration through IC evaluation, purged CV demo, and feature experimentation -- each runnable from scratch with a single "Restart and Run All".
**Depends on:** Phases 35-39 (built last; requires all prior phases to have meaningful outputs)
**Requirements:** NOTE-01, NOTE-02, NOTE-03
**Success Criteria** (what must be TRUE):
  1. Each notebook completes "Restart and Run All" in under 5 minutes on a machine with DB access, producing no errors and no empty output cells
  2. Parameterized variables (`ASSET_ID`, `TF`, `START_DATE`, `END_DATE`) are defined in the first code cell; changing only those cells and re-running produces valid results for a different asset or timeframe
  3. Notebooks cover at minimum: AMA value inspection, IC evaluation with decay table, purged K-fold split visualization, and feature experimentation workflow -- each with a prose narrative cell before each major computation block
**Plans**: 3/3 complete

Plans:
- [x] 40-01-PLAN.md -- Shared helpers module + Notebook 01: Explore Indicators (AMA + regimes)
- [x] 40-02-PLAN.md -- Notebook 02: Evaluate Features (IC + purged K-fold + regime A/B backtest)
- [x] 40-03-PLAN.md -- Notebook 03: Run Experiments (feature experimentation + dashboard launch)

---

### Phase 41: Asset Descriptive Statistics & Cross-Asset Correlation
**Goal:** Users can query rolling per-asset descriptive statistics (mean return, std dev, Sharpe, skewness, kurtosis, max drawdown) and cross-asset return correlation as persisted time-series tables -- tracked over time at every bar, not just latest snapshots -- refreshed daily and usable as future regime detection inputs.
**Depends on:** Phase 34 (v0.8.0 complete; reads from existing `cmc_returns_bars_multi_tf` and `cmc_vol` tables)
**Requirements:** DESC-01, DESC-02, DESC-03, DESC-04, DESC-05, CORR-01, CORR-02, CORR-03
**Success Criteria** (what must be TRUE):
  1. `cmc_asset_stats` contains rolling mean return and std dev for each asset/TF across trailing windows (30, 60, 90, 252 bars), with one row per (id, ts, tf) -- a full time series, not just the latest value
  2. Rolling Sharpe ratio, skewness (scipy), and kurtosis (scipy) are computed per asset/TF/window and stored alongside mean and std dev in `cmc_asset_stats`
  3. Rolling max drawdown per window is tracked in `cmc_asset_stats`; the value at any row reflects the worst peak-to-trough decline within the trailing window ending at that bar
  4. `cmc_cross_asset_corr` contains pairwise rolling return correlation (Pearson) between all asset pairs per TF, across trailing windows (30, 60, 90, 252 bars), tracked as a time series with one row per (id_a, id_b, ts, tf, window)
  5. Both tables are created via Alembic migration and wired into `run_daily_refresh.py --all` as a stage (after features); `--desc-stats` flag available for standalone execution
**Plans**: 6/6 complete

Plans:
- [x] 41-01-PLAN.md -- Alembic migration for cmc_asset_stats, cmc_cross_asset_corr, state tables, cmc_corr_latest materialized view
- [x] 41-02-PLAN.md -- refresh_cmc_asset_stats.py: per-asset rolling stats with watermark incremental refresh
- [x] 41-03-PLAN.md -- refresh_cmc_cross_asset_corr.py: pairwise rolling correlation with materialized view refresh
- [x] 41-04-PLAN.md -- run_all_desc_stats_refreshes.py orchestrator + run_daily_refresh.py pipeline wiring
- [x] 41-05-PLAN.md -- Dashboard page: asset stats table + correlation heatmap + time-series explorer
- [x] 41-06-PLAN.md -- Regime wiring (optional stats augmentation) + quality check registration

---

### Phase 41.1: Milestone Cleanup
**Goal:** Close tech debt items from v0.9.0 milestone audit -- wire AMA tables into experimentation framework, fix stale references, add dashboard experiment visualization and rolling IC chart.
**Depends on:** Phase 41 (all v0.9.0 phases complete)
**Gap Closure:** Closes 6 tech debt items from v0.9.0 audit (2 missing integrations, 4 minor fixes)
**Success Criteria** (what must be TRUE):
  1. ExperimentRunner `_ALLOWED_TABLES` includes AMA tables; a YAML feature referencing `cmc_ama_multi_tf_u` does not raise ValueError
  2. At least 2 AMA-based experimental features defined in `configs/experiments/features.yaml`
  3. Stale CLI reference in Research Explorer help text corrected
  4. `_fold_boundaries` public API or notebook uses public equivalent
  5. Dashboard has an Experiments page showing `cmc_feature_experiments` results
  6. Research Explorer page includes rolling IC chart for selected feature
**Plans**: 3 plans in 1 wave

Plans:
- [x] 41.1-01-PLAN.md -- AMA tables in ExperimentRunner _ALLOWED_TABLES + filter support + YAML features
- [x] 41.1-02-PLAN.md -- Dashboard experiments page (queries + page + nav registration)
- [x] 41.1-03-PLAN.md -- Fix stale CLI ref, add rolling IC chart, make fold_boundaries public

</details>

<details>
<summary>v1.0.0 V1 Closure -- Paper Trading & Validation (Phases 42-60) - CURRENT</summary>

- [x] **Phase 42: Strategy Bake-Off** - IC/PSR/CV evaluation of existing signals, select 2 strategies for V1
- [x] **Phase 43: Exchange Integration** - Connect to two exchange APIs (Coinbase + Kraken), price feed comparison, paper order adapter
- [x] **Phase 44: Order & Fill Store** - DB tables for orders, fills, positions with full audit trail
- [x] **Phase 45: Paper-Trade Executor** - Engine reads signals, generates orders, tracks positions, verifies backtest parity
- [x] **Phase 46: Risk Controls** - Kill switch, position caps, daily loss stops, circuit breaker, discretionary overrides
- [x] **Phase 47: Drift Guard** - Parallel backtest vs paper comparison, auto-pause on divergence
- [x] **Phase 48: Loss Limits Policy** - VaR simulation, intraday stop analysis, pool-level cap definition
- [x] **Phase 49: Tail-Risk Policy** - Hard stops vs vol-sizing, flatten triggers, policy document
- [x] **Phase 50: Data Economics** - Cost audit, build-vs-buy analysis, trigger definition
- [x] **Phase 51: Perps Readiness** - Funding rate ingestion, margin model, liquidation buffer, venue downtime playbook
- [x] **Phase 52: Operational Dashboard** - Live PnL, exposure, drawdown, drift, risk status views
- [x] **Phase 53: V1 Validation** - 2+ weeks paper trading, success criteria measurement
- [x] **Phase 54: V1 Results Memo** - Formal report: methodology, results, failure modes, research answers, next steps
- [x] **Phase 55: Feature & Signal Evaluation** - Run IC evals on all features/AMAs, score with BH gate, adaptive RSI A/B, populate dashboards
- [x] **Phase 56: Factor Analytics & Reporting Upgrade** - QuantStats tear sheets, IC decay/Rank IC, quintile returns, cross-sectional normalization, MAE/MFE, Monte Carlo CI
- [x] **Phase 57: Advanced Labeling & Cross-Validation** - Triple barrier labeling, meta-labeling, purged CPCV, CUSUM event filter, trend scanning
- [x] **Phase 58: Portfolio Construction & Position Sizing** - PyPortfolioOpt integration, Black-Litterman, TopkDropout, bet sizing, stop laddering
- [x] **Phase 59: Microstructural & Advanced Features** - Fractional differentiation, Kyle/Amihud lambda, SADF bubble detection, entropy, codependence
- [x] **Phase 60: ML Infrastructure & Experimentation** - Expression engine, feature importance, regime-routed models, concept drift, experiment tracking, Optuna

</details>

<details>
<summary>v1.0.0 Phase Details (Phases 42-60) - IN PROGRESS</summary>

### Phase 42: Strategy Bake-Off
**Goal:** Use v0.9.0 research tooling to evaluate existing signals and select the 2 best strategies for V1 paper trading, with documented rationale and expected performance.
**Depends on:** v0.9.0 complete (IC evaluation, PSR, purged K-fold, feature experimentation all available)
**Requirements:** STRAT-01, STRAT-02, STRAT-03, STRAT-04
**Success Criteria** (what must be TRUE):
  1. IC scores computed for all features across BTC/ETH 1D; features ranked by IC-IR
  2. Walk-forward backtest results for >= 3 signal types with purged K-fold; no data leakage
  3. 2 strategies selected with documented rationale; parameters chosen via walk-forward, not in-sample optimization
  4. Final backtest meets Sharpe >= 1.0, Max DD <= 15% with realistic fees/slippage
**Plans**: 5 plans in 5 waves

Plans:
- [x] 42-01-PLAN.md -- IC feature sweep: batch IC across all assets x all TFs x all features
- [x] 42-02-PLAN.md -- Walk-forward backtest orchestration with PurgedKFold + CPCV + cost matrix
- [x] 42-03-PLAN.md -- Composite scoring + sensitivity analysis under 4 weighting schemes
- [x] 42-04-PLAN.md -- Strategy selection + ensemble contingency + final validation backtest
- [x] 42-05-PLAN.md -- Scorecard generation: formal bake-off report with charts and tables

---

### Phase 43: Exchange Integration
**Goal:** Connect to two exchange APIs (Coinbase Advanced Trade + Kraken) with authenticated access for BTC/ETH spot, price feed comparison against DB bar data, and paper order format translation.
**Depends on:** Phase 42 (strategies selected; can begin in parallel once bake-off reaches plan 03)
**Requirements:** EXCH-01, EXCH-02, EXCH-03
**Success Criteria** (what must be TRUE):
  1. Coinbase adapter uses Advanced Trade API with JWT ES256 signing; sandbox + production environments switchable via ExchangeConfig
  2. Kraken adapter uses HMAC-SHA512 signing for private endpoints; all 8 ExchangeInterface methods implemented on both adapters
  3. refresh_exchange_price_feed.py fetches live prices from both venues, compares against DB bar closes, computes discrepancy with adaptive threshold (3-sigma from cmc_asset_stats), writes to exchange_price_feed table
  4. CanonicalOrder.to_exchange('coinbase') and .to_exchange('kraken') produce correct exchange-specific order payloads; PaperOrderLogger persists to paper_orders table
  5. All components unit-tested without live API credentials or database connections
**Plans**: 6 plans in 3 waves

Plans:
- [x] 43-01-PLAN.md -- ExchangeConfig dataclass + Alembic migration (exchange_price_feed, paper_orders tables)
- [x] 43-02-PLAN.md -- Coinbase Advanced Trade API rewrite with JWT ES256 auth
- [x] 43-03-PLAN.md -- Kraken HMAC-SHA512 auth for private endpoints
- [x] 43-04-PLAN.md -- CanonicalOrder dataclass + PaperOrderLogger
- [x] 43-05-PLAN.md -- Price feed comparison script + factory update + daily refresh wiring
- [x] 43-06-PLAN.md -- Unit tests for all Phase 43 components

---

### Phase 44: Order & Fill Store
**Goal:** Persist every order, fill, and position change in the database with full audit trail and atomic updates.
**Depends on:** Phase 43 (needs exchange order format for schema design)
**Requirements:** ORD-01, ORD-02, ORD-03, ORD-04
**Success Criteria** (what must be TRUE):
  1. `cmc_orders`, `cmc_fills`, `cmc_positions` tables created via Alembic
  2. Order lifecycle tracked: created -> submitted -> filled/cancelled/rejected
  3. Partial fills update position correctly with weighted cost basis
  4. All writes are atomic -- no orphaned fills or inconsistent positions
**Plans**: 3 plans in 2 waves

Plans:
- [x] 44-01-PLAN.md -- Alembic migration for all Phase 44 tables (cmc_orders, cmc_fills, cmc_positions, cmc_order_events, cmc_order_dead_letter) + v_cmc_positions_agg view + reference DDL
- [x] 44-02-PLAN.md -- Position math TDD: compute_position_update() pure function with all edge cases (new, add, close, flip)
- [x] 44-03-PLAN.md -- OrderManager class (process_fill, promote_paper_order, update_order_status, dead letter) + unit tests

---

### Phase 45: Paper-Trade Executor
**Goal:** Engine that reads signals, places paper orders, tracks positions and P&L, and can be verified against the backtester for parity.
**Depends on:** Phase 44 (needs order/fill store)
**Requirements:** EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05
**Success Criteria** (what must be TRUE):
  1. Executor reads signals and generates orders for selected strategies
  2. Paper fills simulated with configurable slippage model (zero, fixed, lognormal)
  3. Position tracker maintains holdings, cost basis, unrealized P&L per strategy
  4. Execution loop runs daily with full logging (wired into run_daily_refresh.py)
  5. Historical replay produces results matching backtester within tolerance
**Plans**: 7 plans in 4 waves

Plans:
- [x] 45-01-PLAN.md -- Alembic migration (dim_executor_config, cmc_executor_run_log, cmc_positions PK extension, signal table columns) + YAML seed
- [x] 45-02-PLAN.md -- FillSimulator TDD: slippage model (zero, fixed, lognormal) with seeded RNG
- [x] 45-03-PLAN.md -- SignalReader (watermark + stale guard) + PositionSizer (3 sizing modes) + unit tests
- [x] 45-04-PLAN.md -- PaperExecutor class: orchestrate signal-to-fill pipeline + unit tests
- [x] 45-05-PLAN.md -- CLI entry points + pipeline wiring (signals + executor stages in run_daily_refresh.py)
- [x] 45-06-PLAN.md -- ParityChecker: backtest parity verification + dedicated CLI
- [x] 45-07-PLAN.md -- Integration verification: package exports, full test suite, pipeline smoke test
---

### Phase 46: Risk Controls
**Goal:** Implement kill switch, position caps, daily loss stops, circuit breaker, and discretionary override logging -- the safety net required before running any paper trades.
**Depends on:** Phase 44 (needs position tracking), Phase 45 (needs executor to enforce controls)
**Requirements:** RISK-01, RISK-02, RISK-03, RISK-04, RISK-05
**Success Criteria** (what must be TRUE):
  1. Kill switch flattens all positions and halts processing in < 5 seconds
  2. Position caps enforced -- oversized orders scaled down with log
  3. Daily loss stop triggers kill switch when threshold exceeded
  4. Discretionary overrides logged with full audit trail
  5. Circuit breaker pauses on N consecutive losing signals
**Plans**: 4 plans in 3 waves

Plans:
- [x] 46-01-PLAN.md -- Alembic migration for 4 risk tables (dim_risk_limits, dim_risk_state, cmc_risk_events, cmc_risk_overrides) + reference DDL
- [x] 46-02-PLAN.md -- RiskEngine library + KillSwitch operations + kill_switch_cli + unit tests
- [x] 46-03-PLAN.md -- OverrideManager + override_cli + unit tests
- [x] 46-04-PLAN.md -- Package integration tests + executor wiring documentation

---

### Phase 47: Drift Guard
**Goal:** Continuous drift monitoring between paper executor and backtest replay -- daily metrics computation, tiered graduated response (WARNING/PAUSE/ESCALATE), 6-source attribution decomposition, and weekly Markdown + Plotly reports.
**Depends on:** Phase 45 (paper executor fills), Phase 46 (kill switch for escalation), Phase 44 (order/fill tables), Phase 28 (SignalBacktester for replay)
**Requirements:** DRIFT-01, DRIFT-02, DRIFT-03, DRIFT-04
**Success Criteria** (what must be TRUE):
  1. DriftMonitor runs PIT and current-data replays for all active strategies, computes drift metrics, writes to cmc_drift_metrics
  2. Tiered graduated response: WARNING at 75% threshold, PAUSE at 100%, ESCALATE to kill switch after N days
  3. DriftAttributor decomposes drift into 6 sources (fees, slippage, timing, data revision, sizing, regime) via sequential OAT
  4. ReportGenerator produces weekly Markdown report with 3 Plotly HTML charts (equity overlay, tracking error, attribution waterfall)
  5. Drift monitor wired into run_daily_refresh.py as pipeline stage after executor; weekly report invoked separately
**Plans**: 5 plans in 4 waves

Plans:
- [x] 47-01-PLAN.md -- Alembic migration + reference DDL (cmc_drift_metrics, v_drift_summary, dim_risk_state/limits extensions)
- [x] 47-02-PLAN.md -- DriftMetrics dataclass + computation functions + data snapshot collection + unit tests
- [x] 47-03-PLAN.md -- DriftMonitor orchestrator + drift pause (tiered graduated response) + unit tests
- [x] 47-04-PLAN.md -- DriftAttributor (6-source sequential OAT) + ReportGenerator (Markdown + Plotly) + unit tests
- [x] 47-05-PLAN.md -- CLI scripts + pipeline wiring (run_daily_refresh.py) + package exports + full test suite
---

### Phase 51: Perps Readiness
**Goal:** Build the technical foundation for perpetual futures paper trading: funding rate ingestion from 6 venues, margin model (isolated + cross), liquidation buffer with alerts, backtester extension for funding payments, and venue downtime playbook.
**Depends on:** Phase 46 (risk controls for Gate 1.6 extension)
**Requirements:** PERP-01, PERP-02, PERP-03, PERP-04, PERP-05
**Success Criteria** (what must be TRUE):
  1. `python -m ta_lab2.scripts.perps.refresh_funding_rates --all` ingests funding rate history from 6 venues (Binance, Hyperliquid, Bybit, dYdX, Aevo, Aster) for BTC/ETH with watermark-based incremental refresh
  2. FundingAdjuster computes per-bar funding payments and adjusts backtest equity curve; both daily and per-settlement modes supported; sign convention correct (positive rate = longs pay)
  3. MarginState tracks isolated and cross margin with venue-specific tiered rates from cmc_margin_config; compute_margin_utilization flags warning at 1.5x and critical at 1.1x maintenance margin
  4. RiskEngine Gate 1.6 blocks buy orders when margin utilization is at or below 1.1x maintenance margin; sell orders always pass (reducing exposure is safe)
  5. Venue downtime playbook documents procedure for all downtime types with machine-readable YAML health config and hedge-on-alternate-venue procedure
**Plans**: 5 plans in 4 waves

Plans:
- [x] 51-01-PLAN.md -- Alembic migration + reference DDL (cmc_funding_rates, cmc_margin_config, cmc_perp_positions, risk event extensions)
- [x] 51-02-PLAN.md -- Funding rate fetchers (6 venues) + refresh_funding_rates.py CLI with watermark pagination and daily rollup
- [x] 51-03-PLAN.md -- Venue downtime playbook (Markdown procedure + YAML health config)
- [x] 51-04-PLAN.md -- FundingAdjuster (backtester extension) + margin model (MarginState + tiered rates) + unit tests
- [x] 51-05-PLAN.md -- Liquidation buffer (RiskEngine Gate 1.6) + package exports + integration tests


---

### Phase 50: Data Economics
**Goal:** Make the build-vs-buy decision for data infrastructure with documented rationale and quantitative triggers for re-evaluation.
**Depends on:** No hard code dependencies (research/analysis phase producing documents, not code)
**Requirements:** DATA-01, DATA-02, DATA-03
**Success Criteria** (what must be TRUE):
  1. Current data costs audited with real DB measurements (pg_database_size), per-asset granularity, and developer time estimates
  2. Three architecture alternatives (local PostgreSQL, DIY data lake, managed platform) compared at current, 2x, and 5x scale with monthly TCO ranges
  3. Multi-factor decision trigger matrix defines quantitative thresholds for when data lake migration becomes justified
  4. ADR in MADR 4.0 format captures the decision with dissenting view and review schedule
  5. Crypto + equities vendor comparison covers pricing, history depth, and API access
**Plans**: 2 plans in 2 waves

Plans:
- [x] 50-01-PLAN.md -- DB measurements + cost audit + vendor comparison documents
- [x] 50-02-PLAN.md -- TCO model + decision triggers + ADR + executive summary

---

### Phase 52: Operational Dashboard
**Goal:** Extend the existing Phase 39 Streamlit dashboard with 4 operational pages showing live PnL, exposure, drawdown, drift status, and risk controls -- the cockpit for daily paper trading monitoring.
**Depends on:** Phase 45 (paper executor), Phase 46 (risk controls), Phase 47 (drift guard)
**Requirements:** DASH-L01, DASH-L02, DASH-L03, DASH-L04, DASH-L05
**Success Criteria** (what must be TRUE):
  1. Live PnL view: cumulative PnL equity curve, daily P&L, drawdown chart (stacked two-panel), since inception
  2. Exposure view: current positions per asset with notional value, pct of portfolio, cost basis, regime label, and last 20 fills trade log
  3. Drawdown view: peak equity, current drawdown pct, max historical drawdown pct, time since peak
  4. Drift view: paper vs backtest tracking error displayed as rolling time series with alert threshold line, equity overlay chart
  5. Risk status: kill switch state, daily loss consumed vs cap (progress bar), position utilization vs caps, circuit breaker status, filterable risk event history
**Plans**: 4 plans in 3 waves

Plans:
- [x] 52-01-PLAN.md -- Query modules (trading, risk, drift, executor) + operational chart builders in charts.py
- [x] 52-02-PLAN.md -- Trading page (PnL, positions, trade log) + Risk & Controls page (kill switch, limits, events)
- [x] 52-03-PLAN.md -- Drift Monitor page (TE chart, equity overlay) + Executor Status page (run log, config)
- [x] 52-04-PLAN.md -- App.py navigation registration + landing page operational health indicators + human verification

---

### Phase 53: V1 Validation
**Goal:** Build the validation tooling to run, monitor, and report on 2+ weeks of paper trading -- gate assessment framework, daily logs, audit/gap detection, kill switch exercise protocol, and comprehensive end-of-period report.
**Depends on:** Phase 45 (paper executor), Phase 46 (risk controls), Phase 47 (drift guard), Phase 52 (operational dashboard)
**Requirements:** VAL-01, VAL-02, VAL-03, VAL-04, VAL-05
**Success Criteria** (what must be TRUE):
  1. Paper trading runs for minimum 2 consecutive weeks with both selected strategies active
  2. Tracking error vs backtest measured: target < 1%
  3. Slippage measured and documented: target < 50 bps
  4. Kill switch tested: triggered manually and automatically (via daily loss stop) during validation period
  5. All operational logs reviewed: no unexplained gaps, no silent failures, full order/fill audit trail
**Plans**: 4 plans in 3 waves

Plans:
- [x] 53-01-PLAN.md -- Gate framework (GateStatus/GateResult/score_gate/build_gate_scorecard) + pre-flight checklist CLI
- [x] 53-02-PLAN.md -- Daily validation log generator + audit/gap detection checker + CLIs
- [x] 53-03-PLAN.md -- Kill switch exercise protocol script (8-step manual + auto trigger test)
- [x] 53-04-PLAN.md -- End-of-period report builder (Markdown + Plotly + Jupyter notebook) + package exports + nbformat dep

---

### Phase 54: V1 Results Memo
**Goal:** Produce the formal V1 capstone report documenting methodology, quantitative results (backtest + paper), failure modes, all 6 research track answers, and V2 recommendations. Single Python generator script produces reports/v1_memo/V1_MEMO.md with companion Plotly HTML charts and CSV data tables.
**Depends on:** Phases 42-49 (backtest and policy data); Phase 53 (paper trading data, graceful degradation if incomplete)
**Requirements:** MEMO-01, MEMO-02, MEMO-03, MEMO-04, MEMO-05
**Success Criteria** (what must be TRUE):
  1. `python -m ta_lab2.scripts.analysis.generate_v1_memo --backtest-only` produces reports/v1_memo/V1_MEMO.md with all 7 sections rendered from backtest and policy artifacts
  2. Methodology section documents data sources, strategy descriptions, parameter selection (IC/PSR/CV bake-off), and fee/slippage assumptions
  3. Results section includes Sharpe, MaxDD, MAR, win rate, turnover for both strategies against 4 benchmarks; paper trading sections gracefully degrade when Phase 53 data unavailable
  4. Each of the 6 research tracks has a dedicated subsection with methodology, findings, and remaining questions
  5. V2 roadmap proposes concrete phases (56+) with go/no-go triggers and effort estimates grounded in V1 velocity data
**Plans**: 3 plans in 3 waves

Plans:
- [x] 54-01-PLAN.md -- Generator skeleton + CLI + Executive Summary + Build Narrative + Methodology (MEMO-01)
- [x] 54-02-PLAN.md -- Results (MEMO-02) + Failure Modes (MEMO-03) with DB queries, charts, benchmarks
- [x] 54-03-PLAN.md -- Research Tracks (MEMO-04) + Key Takeaways + V2 Roadmap (MEMO-05) + Appendix + CSV exports

---

### Phase 55: Feature & Signal Evaluation
**Goal:** Close the evaluation gap -- run the v0.9.0 IC and experimentation infrastructure on real data, score all existing features and AMA variants, validate signal quality, and populate dashboards with empirical results.
**Depends on:** v0.9.0 complete (Phases 37-38 IC evaluation + feature experimentation framework already built)
**Requirements:** EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05
**Success Criteria** (what must be TRUE):
  1. IC scores computed for all canonical features (rsi_14, EMA crossovers, vol ratios, return z-scores) across all assets x all TFs; features ranked by IC-IR
  2. AMA variants (KAMA ER, DEMA momentum, TEMA/HMA slopes) defined in features.yaml and scored via ExperimentRunner; BH gate applied
  3. Adaptive RSI vs static RSI A/B comparison: IC scores + backtest Sharpe documented; default updated if adaptive wins, code removed if it doesn't
  4. cmc_ic_results and cmc_feature_experiments tables populated with real data; dashboards (Research Explorer, Experiments page) show non-empty results
  5. Evaluation findings documented: top features by IC-IR, regime-conditional IC breakdown, promoted/deprecated feature decisions
**Plans**: 5 plans in 3 waves

Plans:
- [ ] 55-01-PLAN.md -- Methodology verification + full IC sweep across all assets x all 109 TFs
- [ ] 55-02-PLAN.md -- YAML feature registry expansion from 5 to ~130+ entries (canonical + AMA + EMA crossovers + adaptive RSI)
- [ ] 55-03-PLAN.md -- ExperimentRunner sweep for all YAML features + BH gate summary
- [ ] 55-04-PLAN.md -- Adaptive vs static RSI A/B comparison (IC + walk-forward Sharpe)
- [ ] 55-05-PLAN.md -- Lifecycle decisions + EVALUATION_FINDINGS.md + Jupyter notebook
---

### Phase 56: Factor Analytics & Reporting Upgrade
**Goal:** Upgrade strategy and feature evaluation with industry-standard analytics: QuantStats HTML tear sheets (60+ metrics), Rank IC labeling, quintile group returns with monotonicity charts, cross-sectional normalization (CS z-scores and ranks), MAE/MFE per trade, and Monte Carlo Sharpe CI.
**Depends on:** Phase 55 (needs IC infrastructure and backtest tables populated)
**Requirements:** ANALYTICS-01, ANALYTICS-02, ANALYTICS-03, ANALYTICS-04, ANALYTICS-05
**Success Criteria** (what must be TRUE):
  1. Every backtest run produces an HTML tear sheet with 60+ metrics and benchmark comparison
  2. IC results include Rank IC, ICIR, and IC decay at 5 horizons for all canonical features
  3. Cross-sectional z-scores and ranks computed and persisted alongside existing time-series z-scores
  4. MAE/MFE columns populated in cmc_backtest_trades; Monte Carlo CI reported per backtest run
  5. Quintile return charts available for any factor -- monotonicity visually confirmed or rejected
**Plans**: 7 plans in 3 waves

Plans:
- [x] 56-01-PLAN.md -- Alembic migrations for all Phase 56 schema changes (rank_ic, mae/mfe, mc_ci, cs_norms, tearsheet_path)
- [x] 56-02-PLAN.md -- QuantStats install + HTML tear sheet reporter module
- [x] 56-03-PLAN.md -- Quintile group returns engine + Plotly chart + CLI
- [x] 56-04-PLAN.md -- Rank IC column update in ic.py + backfill existing data
- [x] 56-05-PLAN.md -- MAE/MFE computation module + Monte Carlo resampling module
- [x] 56-06-PLAN.md -- Cross-sectional normalization refresh script
- [x] 56-07-PLAN.md -- Backtest pipeline integration (wire QuantStats + MAE/MFE + MC into save_backtest_results)

---

### Phase 57: Advanced Labeling & Cross-Validation
**Goal:** Replace fixed-horizon return labels with adaptive triple barrier labeling, add meta-labeling for false positive reduction, and implement purged cross-validation (CPCV) to prevent data leakage in backtests. Based on MLFinLab's AFML implementation.
**Depends on:** Phase 55 (Feature & Signal Evaluation), Phase 56 (Factor Analytics)
**Requirements:** LABEL-01, LABEL-02, LABEL-03, LABEL-04
**Success Criteria** (what must be TRUE):
  1. Triple barrier labeler produces {+1, -1, 0} labels for any (asset, tf) pair with configurable pt/sl multipliers and vertical barrier
  2. Meta-labeling pipeline: existing signals -> direction, RF classifier -> trade/no-trade with probability-based sizing
  3. CPCV produces distribution of OOS Sharpe ratios (not single point estimate) for each signal strategy
  4. CUSUM filter integrated as optional pre-filter for all 3 signal generators; reduces trade count by 20-40% while maintaining or improving Sharpe
**Plans**: 6 plans

Plans:
- [x] 57-01-PLAN.md -- Triple barrier labeling core
- [x] 57-02-PLAN.md -- CUSUM event filter + trend scanning
- [x] 57-03-PLAN.md -- Triple barrier batch refresh ETL
- [x] 57-04-PLAN.md -- CUSUM signal integration
- [x] 57-05-PLAN.md -- Meta-labeling pipeline
- [x] 57-06-PLAN.md -- CPCV Sharpe distribution

---

### Phase 58: Portfolio Construction & Position Sizing
**Goal:** Graduate from per-asset backtesting to portfolio-level optimization. Integrate PyPortfolioOpt for multi-asset allocation, add intelligent position sizing from MLFinLab, and implement cross-asset strategies from Qlib.
**Depends on:** Phase 56 (Factor Analytics), Phase 42 (Strategy Selection)
**Requirements:** PORT-01, PORT-02, PORT-03, PORT-04, PORT-05
**Success Criteria** (what must be TRUE):
  1. Portfolio optimizer produces allocation weights for the crypto universe given signal scores and covariance matrix
  2. CVaR and HRP optimizers available as regime-conditional alternatives (bear -> CVaR, stable -> mean-variance)
  3. Black-Litterman integration: CMC market caps -> prior, signals -> views -> posterior -> weights
  4. TopkDropout backtested across universe with turnover tracking; compared to equal-weight and per-asset baselines
  5. Bet sizing function maps signal probability to position size; demonstrated improvement in Sharpe vs fixed sizing
**Plans**: 7 plans in 4 waves (+ 2 gap closure)

Plans:
- [x] 58-01-PLAN.md -- Foundation: Alembic migration, portfolio.yaml config, PyPortfolioOpt install, package skeleton
- [x] 58-02-PLAN.md -- PortfolioOptimizer: MV/CVaR/HRP wrappers with regime routing and fallback logic
- [x] 58-03-PLAN.md -- Black-Litterman allocation + probability-based bet sizing
- [x] 58-04-PLAN.md -- TopkDropout selector, turnover cost tracker, rebalance scheduler
- [x] 58-05-PLAN.md -- Integration scripts: refresh_portfolio_allocations, portfolio backtest, daily refresh wiring
- [x] 58-06-PLAN.md -- Gap closure: TurnoverTracker wiring + real signal probabilities (PORT-03/04)
- [x] 58-07-PLAN.md -- Gap closure: StopLadder ATR breakout integration (PORT-05)

---

### Phase 59: Microstructural & Advanced Features
**Goal:** Expand cmc_features with microstructural signals, stationarity-preserving transforms, bubble detection, and non-linear dependency measures drawn from MLFinLab's AFML implementation.
**Depends on:** Phase 55 (Feature & Signal Evaluation), Phase 56 (Factor Analytics)
**Requirements:** MICRO-01, MICRO-02, MICRO-03, MICRO-04, MICRO-05
**Success Criteria** (what must be TRUE):
  1. Fractionally differentiated prices computed for all assets with auto-tuned d via ADF test; stored as feature columns
  2. Kyle/Amihud/Hasbrouck lambdas computed from OHLCV bars; added to cmc_features with IC scores showing predictive value
  3. SADF series computed for all assets; integrated into regime pipeline as bubble/explosive flag
  4. Entropy features (at least Shannon + Lempel-Ziv) computed and persisted; IC evaluated
  5. Distance correlation and mutual information matrices computed; compared to Pearson for regime comovement
**Plans**: 5 plans in 3 waves

Plans:
- [x] 59-01-PLAN.md -- DDL migration: 9 microstructure columns + cmc_codependence table
- [x] 59-02-PLAN.md -- Core math library: 14 pure numpy/scipy functions with 32 unit tests
- [x] 59-03-PLAN.md -- MicrostructureFeature BaseFeature subclass + CLI
- [x] 59-04-PLAN.md -- Codependence pairwise computation script
- [x] 59-05-PLAN.md -- Orchestrator wiring, SADF regime integration, IC eval, codependence comparison

---

### Phase 60: ML Infrastructure & Experimentation
**Goal:** Build the ML experimentation layer -- config-driven factor definitions, feature importance ranking, adaptive models that route by regime, concept drift handling, and experiment tracking. Capstone phase tying together evaluation (55-56), validation (57), and expanded features (59).
**Depends on:** Phase 57 (Purged CV), Phase 59 (Expanded feature set), Phase 55 (Feature experimentation framework)
**Requirements:** MLINFRA-01, MLINFRA-02, MLINFRA-03, MLINFRA-04, MLINFRA-05, MLINFRA-06
**Success Criteria** (what must be TRUE):
  1. Expression engine parses factor strings from YAML, evaluates against OHLCV data, and produces feature columns without Python code changes
  2. MDA feature importance report ranks all cmc_features columns by OOS predictive contribution; top/bottom features documented
  3. Regime-routed strategy backtested: per-regime sub-model vs single model; improvement in Sharpe or drawdown documented
  4. At least one concept drift model trained and evaluated with purged CV; compared to static model baseline
  5. Experiment tracker persists full config + metrics for every run; queryable comparison dashboard
  6. Optuna optimization produces better parameters than grid search on at least 1 strategy with documented efficiency gain
**Plans**: 8 plans in 3 waves

Plans:
- [x] 60-01-PLAN.md -- Expression engine module + YAML expression-mode factors
- [x] 60-02-PLAN.md -- Experiment tracking table (DDL) + ExperimentTracker module
- [x] 60-03-PLAN.md -- Wire expression engine into FeatureRegistry + ExperimentRunner
- [x] 60-04-PLAN.md -- Feature importance module (MDA, SFI, clustered FI)
- [x] 60-05-PLAN.md -- Regime router module + feature importance CLI script
- [x] 60-06-PLAN.md -- DoubleEnsemble concept drift model
- [x] 60-07-PLAN.md -- CLI scripts: regime routing, DoubleEnsemble eval, Optuna sweep
- [x] 60-08-PLAN.md -- Dependencies install + Alembic migration + E2E expression verification

</details>

---

### Phase 61: Integration Wiring & Bug Fixes
**Goal:** Wire the 3 missing cross-phase connections identified by the v1.0.0 milestone audit and fix the Phase 47 drift attribution column-name bugs. After this phase, RiskEngine enforces all risk gates during paper trading, daily refresh includes feature refresh, Telegram alerts fire correctly, and drift attribution reports render without errors.
**Depends on:** Phase 45 (PaperExecutor), Phase 46 (RiskEngine), Phase 47 (drift guard), Phase 50 (daily refresh orchestrator)
**Gap Closure:** Closes 3 integration gaps + 1 phase tech debt item from v1.0.0 audit
**Success Criteria** (what must be TRUE):
  1. PaperExecutor calls RiskEngine.check_order() before every CanonicalOrder creation, check_daily_loss() at start of each run() iteration, and checks dim_risk_state.trading_state before processing signals
  2. `run_daily_refresh.py --all` includes a cmc_features refresh stage between regimes and signals
  3. `send_critical_alert` in paper_executor.py imports from `ta_lab2.notifications.telegram` (not from run_daily_refresh)
  4. `run_drift_report.py --with-attribution` renders without column-name errors (4 bugs on lines 168-204 fixed) and breach count section populates correctly

---

### Phase 62: Operational Completeness
**Goal:** Run deferred operational tasks that require live DB execution — complete the IC sweep across all 109 TFs, execute feature promotions to dim_feature_registry, run the 4 ML CLI scripts to generate documented results, and resolve the orphaned RebalanceScheduler.
**Depends on:** Phase 55 (IC sweep infrastructure), Phase 58 (RebalanceScheduler), Phase 60 (ML CLI scripts)
**Gap Closure:** Closes remaining tech debt from Phases 55, 58, 60
**Success Criteria** (what must be TRUE):
  1. `SELECT COUNT(DISTINCT tf) FROM cmc_ic_results` returns 109 (full IC sweep complete)
  2. dim_feature_registry populated with promoted features from IC ranking
  3. All 4 ML CLI scripts (run_feature_importance, run_regime_routing, run_double_ensemble, run_optuna_sweep) executed with --log-experiment; results in cmc_ml_experiments
  4. RebalanceScheduler either wired into a calling script or removed (no orphaned code)

---

See `.planning/milestones/v1.0.0-REQUIREMENTS.md` and `.planning/milestones/v1.0.0-ROADMAP.md` for full details.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> ... -> 10 (v0.4.0) -> 11 -> ... -> 19 (v0.5.0) -> 20 -> ... -> 26 (v0.6.0) -> 27 -> 28 (v0.7.0) -> 29 -> ... -> 34 (v0.8.0) -> 35 -> ... -> 41 (v0.9.0) -> 42 -> ... -> 62 (v1.0.0)

Note: Within v0.9.0, Phases 35 and 36 have no inter-dependency and may execute in parallel. Phase 37 is enhanced by Phase 35 but not blocked. Phase 38 requires Phase 37. Phase 39 requires Phases 35-38. Phase 40 requires all prior v0.9.0 phases. Phase 41 has no hard dependency on Phases 35-40 (reads from existing returns tables) but is sequenced last. Phase 55 depends only on v0.9.0 (not on other v1.0.0 phases).

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

### v0.5.0 Progress (Complete)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 11. Memory Preparation | 5/5 | Complete | 2026-02-02 |
| 12. Archive Foundation | 3/3 | Complete | 2026-02-02 |
| 13. Documentation Consolidation | 7/7 | Complete | 2026-02-02 |
| 14. Tools Integration | 13/13 | Complete | 2026-02-03 |
| 15. Economic Data Strategy | 6/6 | Complete | 2026-02-03 |
| 16. Repository Cleanup | 7/7 | Complete | 2026-02-03 |
| 17. Verification & Validation | 8/8 | Complete | 2026-02-03 |
| 18. Structure Documentation | 4/4 | Complete | 2026-02-04 |
| 19. Memory Validation & Release | 6/6 | Complete | 2026-02-04 |

### v0.6.0 Progress (Complete)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 20. Historical Context | 3/3 | Complete | 2026-02-05 |
| 21. Comprehensive Review | 4/4 | Complete | 2026-02-05 |
| 22. Critical Data Quality Fixes | 6/6 | Complete | 2026-02-05 |
| 23. Reliable Incremental Refresh | 4/4 | Complete | 2026-02-05 |
| 24. Pattern Consistency | 4/4 | Complete | 2026-02-05 |
| 25. Baseline Capture | 2/2 | Complete | 2026-02-05 |
| 26. Validation & Architectural Standardization | 3/3 | Complete | 2026-02-17 |

### v0.7.0 Progress (Complete)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 27. Regime Integration | 7/7 | Complete | 2026-02-20 |
| 28. Backtest Pipeline Fix | 3/3 | Complete | 2026-02-20 |

### v0.8.0 Progress (Complete)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 29. Stats/QA Orchestration | 3/3 | Complete | 2026-02-22 |
| 30. Code Quality Tooling | 2/2 | Complete | 2026-02-22 |
| 31. Documentation Freshness | 3/3 | Complete | 2026-02-23 |
| 32. Runbooks | 2/2 | Complete | 2026-02-23 |
| 33. Alembic Migrations | 2/2 | Complete | 2026-02-23 |
| 34. Audit Cleanup | 1/1 | Complete | 2026-02-23 |

### v0.9.0 Progress (Complete)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 35. AMA Engine | 8/8 | Complete | 2026-02-23 |
| 36. PSR + Purged K-Fold | 5/5 | Complete | 2026-02-24 |
| 37. IC Evaluation | 4/4 | Complete | 2026-02-23 |
| 38. Feature Experimentation | 5/5 | Complete | 2026-02-24 |
| 39. Streamlit Dashboard | 4/4 | Complete | 2026-02-24 |
| 40. Notebooks | 3/3 | Complete | 2026-02-24 |
| 41. Asset Descriptive Stats & Correlation | 6/6 | Complete | 2026-02-24 |
| 41.1. Milestone Cleanup | 3/3 | Complete | 2026-02-24 |

### v1.0.0 Progress (Current)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 42. Strategy Bake-Off | 0/5 | Planned | -- |
| 43. Exchange Integration | 0/6 | Planned | -- |
| 44. Order & Fill Store | 0/3 | Planned | -- |
| 45. Paper-Trade Executor | 0/7 | Planned | -- |
| 46. Risk Controls | 0/4 | Planned | -- |
| 47. Drift Guard | 5/5 | Complete | 2026-02-25 |
| 48. Loss Limits Policy | 4/4 | Complete | 2026-02-25 |
| 49. Tail-Risk Policy | 4/4 | Complete | 2026-02-25 |
| 50. Data Economics | 2/2 | Complete | 2026-02-25 |
| 51. Perps Readiness | 5/5 | Complete | 2026-02-25 |
| 52. Operational Dashboard | 4/4 | Complete | 2026-02-26 |
| 53. V1 Validation | 4/4 | Complete | 2026-02-26 |
| 54. V1 Results Memo | 3/3 | Complete | 2026-02-26 |
| 55. Feature & Signal Evaluation | 0/5 | Planned | -- |
| 56. Factor Analytics & Reporting Upgrade | 0/7 | Planned | -- |
| 57. Advanced Labeling & Cross-Validation | 6/6 | Planned | -- |
| 58. Portfolio Construction & Position Sizing | 0/? | Planned | -- |
| 59. Microstructural & Advanced Features | 0/? | Planned | -- |
| 60. ML Infrastructure & Experimentation | 0/8 | Planned | -- |

## Requirement Coverage

### v0.6.0 Requirements (40 total)

| Category | Requirements | Phase(s) | Count |
|----------|--------------|----------|-------|
| Historical Context | HIST-01, HIST-02, HIST-03 | Phase 20 | 3 |
| Understanding Questions | RVWQ-01, RVWQ-02, RVWQ-03, RVWQ-04 | Phase 21 | 4 |
| Review Deliverables | RVWD-01, RVWD-02, RVWD-03, RVWD-04 | Phase 21 | 4 |
| Critical Gaps | GAP-C01, GAP-C02, GAP-C03, GAP-C04 | Phase 22 | 4 |
| Orchestration | ORCH-01, ORCH-02, ORCH-03, ORCH-04 | Phase 23 | 4 |
| State Management | STAT-01, STAT-02, STAT-03, STAT-04 | Phase 23 | 4 |
| Visibility | VISI-01, VISI-02, VISI-03 | Phase 23 | 3 |
| Pattern Standardization | PATT-01, PATT-02, PATT-03, PATT-04, PATT-05, PATT-06 | Phase 24 | 6 |
| Baseline | TEST-01 | Phase 25 | 1 |
| Validation Testing | TEST-02, TEST-03, TEST-04, TEST-05 | Phase 26 | 4 |

**Coverage:** 37/40 requirements mapped (remaining 3 DATA/DVAL replaced by GAP-C01-04)

### v0.9.0 Requirements (43 total)

| Category | Requirements | Phase | Count |
|----------|--------------|-------|-------|
| Adaptive Moving Averages | AMA-01, AMA-02, AMA-03, AMA-04, AMA-05, AMA-06, AMA-07 | Phase 35 | 7 |
| Information Coefficient | IC-01, IC-02, IC-03, IC-04, IC-05, IC-06, IC-07, IC-08 | Phase 37 | 8 |
| Probabilistic Sharpe Ratio | PSR-01, PSR-02, PSR-03, PSR-04, PSR-05 | Phase 36 | 5 |
| Cross-Validation | CV-01, CV-02, CV-03 | Phase 36 | 3 |
| Feature Experimentation | FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05 | Phase 38 | 5 |
| Streamlit Dashboard | DASH-01, DASH-02, DASH-03, DASH-04 | Phase 39 | 4 |
| Jupyter Notebooks | NOTE-01, NOTE-02, NOTE-03 | Phase 40 | 3 |
| Asset Descriptive Statistics | DESC-01, DESC-02, DESC-03, DESC-04, DESC-05 | Phase 41 | 5 |
| Cross-Asset Correlation | CORR-01, CORR-02, CORR-03 | Phase 41 | 3 |

**Coverage:** 43/43 requirements mapped

### v1.0.0 Requirements (85 total)

| Category | Requirements | Phase | Count |
|----------|--------------|-------|-------|
| Strategy Selection | STRAT-01, STRAT-02, STRAT-03, STRAT-04 | Phase 42 | 4 |
| Exchange Integration | EXCH-01, EXCH-02, EXCH-03 | Phase 43 | 3 |
| Order & Fill Store | ORD-01, ORD-02, ORD-03, ORD-04 | Phase 44 | 4 |
| Paper-Trade Executor | EXEC-01, EXEC-02, EXEC-03, EXEC-04, EXEC-05 | Phase 45 | 5 |
| Risk Controls | RISK-01, RISK-02, RISK-03, RISK-04, RISK-05 | Phase 46 | 5 |
| Drift Guard | DRIFT-01, DRIFT-02, DRIFT-03, DRIFT-04 | Phase 47 | 4 |
| Loss Limits Policy | LOSS-01, LOSS-02, LOSS-03, LOSS-04 | Phase 48 | 4 |
| Tail-Risk Policy | TAIL-01, TAIL-02, TAIL-03 | Phase 49 | 3 |
| Data Economics | DATA-01, DATA-02, DATA-03 | Phase 50 | 3 |
| Perps Readiness | PERP-01, PERP-02, PERP-03, PERP-04, PERP-05 | Phase 51 | 5 |
| Operational Dashboard | DASH-L01, DASH-L02, DASH-L03, DASH-L04, DASH-L05 | Phase 52 | 5 |
| V1 Validation | VAL-01, VAL-02, VAL-03, VAL-04, VAL-05 | Phase 53 | 5 |
| V1 Results Memo | MEMO-01, MEMO-02, MEMO-03, MEMO-04, MEMO-05 | Phase 54 | 5 |
| Feature & Signal Evaluation | EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05 | Phase 55 | 5 |
| Factor Analytics & Reporting | ANALYTICS-01, ANALYTICS-02, ANALYTICS-03, ANALYTICS-04, ANALYTICS-05 | Phase 56 | 5 |
| Advanced Labeling & CV | LABEL-01, LABEL-02, LABEL-03, LABEL-04 | Phase 57 | 4 |
| Portfolio Construction | PORT-01, PORT-02, PORT-03, PORT-04, PORT-05 | Phase 58 | 5 |
| Microstructural Features | MICRO-01, MICRO-02, MICRO-03, MICRO-04, MICRO-05 | Phase 59 | 5 |
| ML Infrastructure | MLINFRA-01, MLINFRA-02, MLINFRA-03, MLINFRA-04, MLINFRA-05, MLINFRA-06 | Phase 60 | 6 |

**Coverage:** 85/85 requirements mapped

---
*Created: 2025-01-22*
*Last updated: 2026-02-27 (Phase 58 planned -- Portfolio Construction & Position Sizing; 5 plans in 4 waves)*
