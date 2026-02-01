# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2025-01-22)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** Phase 3 complete - Ready for Phase 4 (Orchestrator Adapters)

## Current Position

Phase: 10 of 10 (Release Validation)
Plan: 7 of 7 (API Reference Documentation)
Status: Phase complete
Last activity: 2026-02-01 - Completed 10-07-PLAN.md (API Reference Documentation)

Progress: [██████████] 100% (55/55 plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 55 (across 10 complete phases)
- Average duration: 12 min
- Total execution time: 12.52 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 01-foundation-quota-management | 3 | 23 min | 8 min | ✓ Complete |
| 02-memory-core-chromadb-integration | 5 | 29 min | 6 min | ✓ Complete |
| 03-memory-advanced-mem0-migration | 6 | 193 min | 32 min | ✓ Complete |
| 04-orchestrator-adapters | 4 | 61 min | 15 min | ✓ Complete |
| 05-orchestrator-coordination | 6 | 34 min | 6 min | ✓ Complete |
| 06-ta-lab2-time-model | 6 | 37 min | 6 min | ✓ Complete |
| 07-ta_lab2-feature-pipeline | 7 | 45 min | 6 min | ✓ Complete |
| 08-ta_lab2-signals | 6 | 49 min | 8 min | ✓ Complete |
| 09-integration-observability | 7 | 260 min | 37 min | ✓ Complete |
| 10-release-validation | 7 | 32 min | 5 min | ✓ Complete |

**Recent Trend:**
- Last 5 phases: 49min (08), 260min (09), 32min (10), ?min (11), ?min (12)
- Trend: Phase 10 completed rapidly (4.6 min/plan average) - project complete at 100%

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- **Hybrid memory architecture (Mem0 + Memory Bank)**: Mem0 provides logic layer, Memory Bank provides enterprise storage - Phase 2-3 implementation
- **Parallel track development**: Memory + orchestrator + ta_lab2 can develop simultaneously - Phases 1-6 enable parallel execution
- **Direct handoff model**: Task A writes to memory, spawns Task B with context pointer - Phase 5 implementation
- **Time model before features**: dim_timeframe and dim_sessions must exist before features reference them - Phase 6 before Phase 7
- **Quota management early**: Gemini 1500/day limit requires tracking in Phase 1 before heavy usage
- **Optional dependency group 'orchestrator'** (01-01): AI SDKs isolated in separate dependency group for cleaner installation
- **Config.py from plan 01-02** (01-01): Task 3 requirement satisfied by config.py created in plan 01-02, demonstrating good dependency coordination
- **.env protection** (01-01): Added .env to .gitignore explicitly to prevent secret leakage
- **Storage location: .memory/quota_state.json** (01-02): .memory/ directory used for quota state persistence as it already exists in project
- **Atomic writes via temp file + rename** (01-02): Prevents corruption on crash/power loss, standard pattern for safe writes
- **Alert thresholds: 50%, 80%, 90%** (01-02): Gemini 1500/day limit requires early warnings; 50% is daily checkpoint, 90% is urgent
- **Reservation auto-release on usage** (01-02): Simplifies parallel task coordination - reserve, then use without manual release
- **Double validation pattern** (01-03): Two checkpoints (routing + execution) prevent routing to stub adapters - defense-in-depth
- **Runtime implementation status** (01-03): Adapters report is_implemented property for dynamic validation, not config-based
- **Helpful validation errors** (01-03): Errors list available platforms and requirements for debugging
- **Parallel track stubs** (01-03): Memory, orchestrator, ta_lab2 have stub implementations for independent development
- **ChromaDB singleton pattern** (02-01): MemoryClient uses factory function with reset capability for testing
- **Lazy collection loading** (02-01): Collections loaded on first access for better performance
- **L2 distance acceptable with warning** (02-01): Validation recommends cosine but doesn't fail on L2 (existing data compatibility)
- **Validation dataclass pattern** (02-01): Structured results with is_valid flag, issues list, and readable __str__
- **Distance to similarity conversion** (02-02): similarity = 1 - distance for intuitive scoring (assumes cosine distance)
- **Default 0.7 similarity threshold** (02-02): Per MEMO-02 requirement for relevance filtering
- **Token estimation heuristic** (02-02): ~4 characters per token approximation for context budgeting
- **Max context length 4000 chars** (02-02): Default balances comprehensive context with token limits
- **OpenAI text-embedding-3-small for consistency** (02-03): Uses same model as existing 3,763 memories for embedding consistency
- **Batch size 50 for efficiency** (02-03): Balances API efficiency with memory usage and error isolation
- **ChromaDB upsert for duplicates** (02-03): Handles duplicate memory IDs gracefully by updating instead of failing
- **Embedding dimension validation** (02-03): Validates 1536 dimensions before insertion to prevent corruption
- **Batch error isolation** (02-03): Individual batch failures don't stop entire operation
- **FastAPI for cross-platform access** (02-04): REST API required for Claude/ChatGPT/Gemini to query ChromaDB (cloud services need HTTP)
- **Factory pattern for API** (02-04): create_memory_api() returns configured FastAPI app for testing and customization
- **Lazy imports in endpoints** (02-04): Imports inside endpoint functions reduce startup overhead and avoid circular dependencies
- **Pydantic validation** (02-04): Field constraints provide automatic bounds checking with clear error messages
- **Mock patch paths target definitions** (02-04): Test patches target where functions are defined, not where imported
- **Use Qdrant instead of ChromaDB for Mem0** (03-01): mem0ai 1.0.2 only supports Qdrant provider, ChromaDB support not yet implemented
- **Qdrant path: {chromadb_path_parent}/qdrant_mem0** (03-01): Persistent local storage for Mem0 vector backend
- **infer=True by default** (03-01): Enable LLM conflict detection on all add() operations by default
- **Mock _memory attribute in tests** (03-01): Property decorator prevents patch.object, mock private attribute directly
- **text-embedding-3-small for Mem0** (03-01): Match Phase 2 embeddings (1536-dim) for compatibility
- **ISO 8601 timestamps for metadata** (03-02): created_at, last_verified use ISO 8601 format for parsing and comparison
- **Mark deprecated, don't delete** (03-02): Soft deletion via deprecated_since timestamp preserves audit trail
- **Migration validation threshold 95%** (03-02): Require 95% success rate for metadata migration to pass validation
- **LLM-powered resolution over rules** (03-03): Mem0 infer=True uses GPT-4o-mini for context-aware conflict detection (26% accuracy improvement)
- **Similarity threshold 0.85 for conflicts** (03-03): High threshold reduces false positives while catching semantic conflicts
- **Metadata scoping for context-dependent truths** (03-03): Same fact with different metadata (e.g., asset_class) not flagged as conflict
- **JSONL audit log format** (03-03): Append-only conflict_log.jsonl provides grep-friendly audit trail
- **Non-destructive by default** (03-04): flag_stale_memories uses dry_run=True to prevent accidental deprecation
- **90-day staleness threshold** (03-04): Memories not verified in 90+ days flagged as stale per MEMO-06
- **Age distribution buckets** (03-04): 0-30d, 30-60d, 60-90d, 90+d for health visibility
- **Verification refresh pattern** (03-04): Human confirms memory accuracy, system updates last_verified
- **Lazy imports in endpoints** (03-05): Import health.py and conflict.py inside endpoint functions to avoid circular dependencies
- **Separate stale endpoint** (03-05): /api/v1/memory/health/stale separate from /health for detailed list without full report overhead
- **Pydantic min_length/max_length** (03-05): Use min_length/max_length instead of deprecated min_items/max_items for V2 compatibility
- **Mem0 search returns dict with 'results' key** (03-06): search() returns {'results': [...]} not list directly, requires .get('results', [])
- **Qdrant server mode for production** (03-06): Docker container with volume mount provides reliable persistence; auto-restart enabled; all 3,763 memories verified persisting across restarts
- **QDRANT_SERVER_MODE environment variable** (03-06): Defaults to true for server mode (localhost:6333); set to false for local embedded mode (testing only)
- **AsyncBasePlatformAdapter uses ABC pattern** (04-01): Chose abstract base class over protocol for code reuse (utility methods shared across adapters)
- **Task ID format: platform_yyyymmdd_uuid8** (04-01): Provides uniqueness, traceability, and human-readable structure for debugging
- **TaskConstraints default timeout: 300 seconds** (04-01): Balances reasonable wait time for most tasks (5 minutes) with preventing indefinite hangs
- **StreamingResult saves partial results on cancellation** (04-01): Critical for debugging and resumption - cancellation shouldn't lose all progress
- **Backward compatibility with default values** (04-01): New Task/Result fields all optional with defaults so existing sync code continues working unchanged
- **Tenacity for retry logic** (04-02): Mature library with exponential backoff, jitter, and before_sleep logging for API retries
- **Default model: gpt-4o-mini** (04-02): Cost efficiency - $0.15/$0.60 per 1M tokens vs gpt-4 $30/$60 per 1M (20x cost savings)
- **Retry on RateLimitError and APIError** (04-02): 5 attempts, 1s->32s exponential backoff with 3s jitter per OpenAI best practices
- **Pending tasks as asyncio.Task** (04-02): Enables status tracking (RUNNING/COMPLETED/CANCELLED) and cancellation support
- **check_and_reserve convenience method** (04-04): Single call for quota check + reservation simplifies adapter integration
- **release_and_record method** (04-04): Handles reservation-to-usage conversion after execution, auto-releases excess reservation
- **Request-based quota tracking for Gemini** (04-04): Free tier tracks 1500 requests/day, not tokens (API limitation)
- **Quota checked BEFORE API call** (04-04): Fail-fast pattern prevents wasted API calls when quota exhausted
- **Quota released on failure/cancellation** (04-04): Prevents quota leakage from failed tasks
- **COST_TIERS with Platform enum** (05-01): Type-safe routing with priority structure (Gemini free=1, subscriptions=2, paid=3)
- **route_cost_optimized method** (05-01): Cost-first routing: Gemini free tier → subscriptions → paid APIs with RuntimeError on exhaustion
- **Advisory platform hints** (05-01): Platform hints honored if quota available, automatic fallback to cost tiers when exhausted
- **warn_quota_threshold method** (05-01): Flexible threshold warnings (default 90%) with platform, percentage, used/limit details
- **TaskGroup for fail-independent execution** (05-02): Python 3.11+ TaskGroup provides native fail-independent semantics via ExceptionGroup
- **Semaphore for concurrency control** (05-02): Default 10 concurrent tasks (configurable) prevents quota exhaustion during parallel execution
- **Result ordering preservation** (05-02): Results[i] corresponds to Tasks[i] regardless of completion order for predictable mapping
- **Adaptive concurrency scaling** (05-02): min(max_concurrent, available_quota // 2) with minimum of 1 prevents mid-batch quota exhaustion
- **Hybrid (pointer + summary) handoff pattern** (05-03): Full context in memory with unique ID, brief summary (max 500 chars) passed inline for quick reference
- **Fail-fast memory lookup** (05-03): load_handoff_context raises RuntimeError if context not found - Task B cannot proceed without context from Task A
- **Lazy imports for memory functions** (05-03): add_memory and get_memory_by_id imported inside functions to avoid circular dependency
- **ChainTracker in-memory only** (05-03): Task genealogy tracked in-memory, persistence deferred to CostTracker (Plan 05-04)
- **Chain ID inheritance** (05-03): Child inherits parent's chain_id or creates new one, maintaining workflow-level tracking
- **MAX_RETRIES=3 with exponential backoff** (05-05): Base delay 1s, retries at 1s, 2s, 4s for transient errors (rate limits, timeouts, server errors)
- **Error classification for retry** (05-05): Retryable (rate limits, timeouts, 5xx) vs non-retryable (auth, quota exhausted) - fail-fast on non-retryable
- **Platform fallback routing** (05-05): Try all platforms in COST_TIERS order on failure, each platform gets full retry cycle before moving to next
- **Comprehensive error messages** (05-05): "All platforms failed. Last error: {error}. Tried: {platforms}" format provides debugging context
- **CLI delegation pattern** (05-06): Main CLI delegates to orchestrator CLI via argv passthrough, single source of truth for orchestrator structure
- **Lazy imports in CLI commands** (05-06): QuotaTracker, CostTracker imported inside cmd_* functions to avoid circular dependencies
- **Default 5 parallel tasks for batch** (05-06): Balance concurrency vs stability, configurable via --parallel flag
- **JSON output truncation** (05-06): Batch results truncate task outputs to 500 chars to prevent unwieldy JSON files
- **Conditional table creation (idempotent)** (06-01): ensure_dim_tables.py checks table existence before creating, safe to run multiple times
- **SQL seed files for dim_timeframe** (06-01): Uses existing 010-014 SQL files for comprehensive timeframe population (199 TFs)
- **Inline dim_sessions creation** (06-01): CREATE TABLE + INSERT in Python for simpler session management (default CRYPTO/EQUITY sessions)
- **Optional columns for Python compatibility** (06-01): ALTER TABLE adds is_canonical, calendar_scheme, allow_partial_*, tf_days_min/max after SQL creation
- **Tests skip gracefully without database** (06-01): pytest.mark.skipif(not TARGET_DB_URL) prevents test failures in environments without database
- **Calendar scripts use dim_timeframe indirectly** (06-03): Calendar EMAs query dim_timeframe via SQL in feature modules, not directly in refresh scripts - architecturally sound separation
- **Test for evidence of state usage, not just imports** (06-03): Check for method calls, config usage, state table references to ensure state management is wired and functional
- **Static analysis for code validation** (06-03): File content inspection validates architectural patterns without database connection (<2s execution)
- **ASCII markers instead of Unicode checkmarks** (06-02): Windows console doesn't support ✓/✗, use [OK]/[ERROR] for compatibility (prevents charmap encoding errors)
- **Unit tests use unittest.mock for database-free testing** (06-05): MagicMock enables testing database-dependent code without actual database connection
- **Integration tests skip gracefully without database** (06-05): pytest.mark.skipif(not TARGET_DB_URL) allows test suite to run in environments without full infrastructure
- **Watermarking per alignment_source** (06-05): get_watermark() validates incremental sync correctly handles different alignment sources independently
- **Idempotency verification via dry-run** (06-05): Running sync twice with same watermark state produces identical candidate counts, proving incremental logic works
- **Telegram for alerts instead of email/Slack** (06-06): Per CONTEXT.md requirement - Telegram API simpler than SMTP/Slack webhooks
- **Graceful degradation when Telegram not configured** (06-06): Validation should work without alerts - just log warnings
- **Conservative expected count calculation** (06-06): tf_days-based division for expected counts - simple and works for most TFs
- **Validation warns but doesn't fail pipeline** (06-06): Data quality issues should be investigated but not block refreshes
- **Feature state schema: (id, feature_type, feature_name) PRIMARY KEY** (07-01): Extends EMA pattern with feature dimensions for unified tracking across returns, volatility, and TA features
- **Three null handling strategies** (07-01): skip (returns - preserves gaps), forward_fill (vol - smooth estimates), interpolate (TA - smooth signals) configured per feature in dim_features
- **get_null_strategy() defaults to 'skip'** (07-01): Most conservative strategy when feature not found in dim_features, preserves data integrity
- **BaseFeature template method pattern** (07-02): Following BaseEMAFeature structure, compute_for_ids defines flow: load -> null handling -> compute -> normalize -> flag outliers -> write
- **Z-score rolling window normalization** (07-02): Default 252 days (1 trading year), handles std=0 with NaN for constant values
- **Flag but keep outlier approach** (07-02): Per CONTEXT.md, outliers marked via is_outlier column but original values preserved for analysis transparency
- **Dual outlier detection methods** (07-02): zscore (default 4 sigma) for normal distributions, IQR (default 1.5x IQR) for robust detection with skewed data
- **Reuse existing returns.py functions** (07-03): b2t_pct_delta and b2t_log_delta from ta_lab2.features.returns for bar-to-bar calculations, avoids duplication
- **Multi-day returns via pct_change(periods=n)** (07-03): Simple pandas built-in for multi-day percent returns, mathematically correct
- **Selective z-score normalization** (07-03): Only key windows (1D, 7D, 30D) get z-scores to reduce storage overhead
- **Single is_outlier flag** (07-03): OR across key windows instead of per-window flags, simplifies queries
- **Per-asset chronological processing** (07-03): Returns require groupby('id') then sort for correct shift-based calculations
- **Database-driven indicator configuration** (07-05): dim_indicators with JSONB params enables adding new indicators without code changes
- **Multiple indicator parameter sets** (07-05): RSI (7,14,21), MACD (12/26/9, 8/17/9), Stoch (14/3), BB (20/2), ATR (14), ADX (14)
- **Reuse indicators.py with inplace=True** (07-05): Avoid DataFrame copies for efficiency in TAFeature computation
- **Dynamic schema based on active indicators** (07-05): get_feature_columns() queries dim_indicators for runtime flexibility
- **CLI --indicators flag** (07-05): Filter which indicators to compute without code changes, enables selective computation for debugging
- **Materialized table for feature store** (07-06): cmc_daily_features implemented as table (not view) for ML query performance
- **Source watermark tracking** (07-06): MIN of all source table watermarks determines dirty window start for conservative incremental refresh
- **LEFT JOINs for graceful degradation** (07-06): Optional sources use LEFT JOIN resulting in NULL columns when missing, never fail entire refresh
- **EMA pivot from long to wide** (07-06): Select specific periods (9,10,21,50,200) from cmc_ema_multi_tf_u for 1D timeframe
- **Asset class from dim_sessions** (07-06): Includes asset_class column for market-type filtering in ML queries
- **Gap detection uses dim_timeframe** (07-07): Query dim_sessions for asset's session type (crypto=daily, equity=trading days), generate expected date schedule
- **Feature-specific outlier thresholds** (07-07): Returns >50%, vol >500%, RSI outside 0-100 prevents false positives from generic thresholds
- **Cross-table consistency as critical** (07-07): Returns vs price delta mismatches flagged severity='critical' requiring investigation
- **NULL ratio threshold 10%** (07-07): >10% NULL values triggers warning, configurable per-column for flexibility
- **Rowcount tolerance 5%** (07-07): Accounts for delisted assets and data gaps, prevents false alarms
- **Parallel phase 1 execution** (07-07): returns/vol/ta run concurrently (same dependency on bars), ThreadPoolExecutor max_workers=3 for 3x speedup
- **Graceful degradation on partial failure** (07-07): One table failure doesn't stop pipeline, daily_features continues with LEFT JOINs
- **Validation after refresh by default** (07-07): --validate flag default True, ensures data quality without manual step
- **Database-driven signal configuration** (08-01): dim_signals table with JSONB params for signal strategies, follows dim_indicators pattern
- **Signal tables separate by type** (08-01): Three separate tables (ema_crossover, rsi_mean_revert, atr_breakout) for type-specific columns without schema bloat
- **SignalStateManager for position lifecycle** (08-01): Tracks open positions and dirty windows per (id, signal_type, signal_id) extending FeatureStateManager pattern
- **SHA256 feature hashing for reproducibility** (08-01): First 16 chars of hash balances uniqueness and readability for backtest validation
- **State manager queries signal table** (08-01): load_open_positions queries signal table (not state table) for full context including entry_price, feature_snapshot
- **Load EMA pairs from dim_signals** (08-02): Database-driven configuration via load_active_signals, not hardcoded, enables adding strategies without code changes
- **Explicit column list for feature hashing** (08-02): _load_features uses explicit column order for hash stability across runs
- **FIFO position matching** (08-02): Exit signals match oldest open position first via open_list.pop(0)
- **Feature snapshot at entry** (08-02): Captured close, fast_ema, slow_ema, rsi_14, atr_14 in JSONB for backtest self-containment
- **Batch-level hash computation** (08-02): Compute feature_version_hash once per asset batch (not per record) for 10-100x efficiency
- **Iterative channel computation** (08-04): Loop over asset IDs for Donchian channels instead of groupby().apply() to avoid pandas FutureWarning and preserve 'id' column
- **Feature hash requires 'ts' column** (08-04): compute_feature_hash sorts by 'ts', pattern: hash_df = df_asset.loc[[idx], ['ts'] + feature_cols]
- **Breakout type classification** (08-04): channel_break (Donchian), atr_expansion (volatility spike), or both - enables performance analysis per trigger
- **Channel levels in feature snapshot** (08-04): channel_high, channel_low captured in JSONB for audit trail and backtest validation
- **Backtest from stored signals** (08-05): Reads signals from database (not on-the-fly generation) for reproducibility and auditability
- **Clean vs realistic PnL modes** (08-05): Clean mode (no costs) for theoretical analysis, realistic mode with configurable fees/slippage for practical evaluation
- **Atomic transaction for multi-table storage** (08-05): engine.begin() ensures runs/trades/metrics all succeed or all fail for consistency
- **Comprehensive metrics extraction** (08-05): 15 metrics from vectorbt Portfolio (Sharpe, Sortino, Calmar, VaR, CVaR, profit factor, win rate, etc.) for multi-dimensional strategy evaluation
- **Feature/params hashing for reproducibility** (08-05): SHA256 hash (first 16 chars) of signal params detects configuration changes that invalidate backtest comparisons
- **Triple-layer reproducibility** (08-06): Deterministic timestamp queries + feature hashing + version tracking ensures backtest determinism
- **validate_backtest_reproducibility runs twice** (08-06): Gold standard test - run identical backtest twice, compare PnL/metrics/trade counts with tolerance (default 1e-10)
- **Three validation modes: strict/warn/trust** (08-06): strict (fail on hash mismatch), warn (log warning, proceed), trust (skip validation) for different use cases
- **Partial failure handling as default** (08-06): Pipeline continues when one signal type fails (logs error, continues with partial results), --fail-fast to exit immediately
- **compare_backtest_runs for historical analysis** (08-06): Compare runs from database via feature hash to detect data changes and enable cache invalidation
- **PostgreSQL-backed observability** (09-01): Store metrics, traces, workflow state in database for SQL queryability instead of external tools
- **Graceful OpenTelemetry degradation** (09-01): Tracing works without opentelemetry-api via no-op classes, observability doesn't block development
- **Kubernetes probe pattern** (09-01): Separate liveness (process alive), readiness (dependencies healthy), startup (initialized) following K8s best practices
- **Month-partitioned metrics table** (09-01): observability.metrics partitioned by recorded_at for scalability with high-frequency recording
- **32-char hex correlation IDs** (09-01): Uses OpenTelemetry trace context when available, UUID fallback for cross-system request tracing
- **Three-tier test pattern** (09-02): real_deps (full infrastructure), mixed_deps (real DB/mocked AI), mocked_deps (CI/CD) via pytest markers
- **Session-scoped database fixtures** (09-02): database_engine session-scoped for efficiency, clean_database function-scoped with transaction rollback for isolation
- **Graceful test skip pattern** (09-02): Tests skip with informative messages when infrastructure unavailable instead of hard failures
- **pytest-mock for infrastructure mocking** (09-02): Standard pytest plugin provides mocker fixture for test doubles across all tiers
- **Nested health check details** (09-03): Health check results use nested structure `details['checks']['database']` for organized component status
- **8-column workflow results** (09-03): Workflow state queries return 8-tuple (workflow_id, correlation_id, type, phase, status, created_at, updated_at, metadata)
- **Boolean memory health check** (09-03): Memory service health_check() returns boolean, not dict, for consistent health probe interface
- **Manual startup_complete flag** (09-03): HealthChecker.startup() returns status but doesn't set startup_complete property - caller must set explicitly
- **Patch _get_dim for timeframe tests** (09-04): Mock _get_dim instead of database for cleaner timeframe testing without SQLAlchemy URL parsing
- **pytest parametrize for timeframe coverage** (09-04): Single test function covers multiple timeframes (1D-365D) reducing duplication
- **Separate validation test classes** (09-04): TestStandardTimeframes, TestCalendarTimeframes, TestTradingSessionAlignment improve test organization by validation dimension
- **All validation tests use mocked_deps** (09-04): 49 validation tests run in CI/CD without infrastructure dependencies
- **Baseline + percentage threshold approach** (09-06): Alert thresholds calculate p50 baseline from last 7 days, trigger when current value >2x baseline for dynamic adaptation to variance
- **Strict data quality thresholds (0% tolerance)** (09-06): Gap/alignment/rowcount thresholds set to 0 for strict validation - any missing row is a real issue for crypto 24/7 data
- **Dual delivery pattern for alerts** (09-06): Telegram for immediate notification + database for historical tracking, both attempted on every alert with graceful degradation
- **Severity escalation rules** (09-06): Integration failures CRITICAL after >3 errors, resource exhaustion CRITICAL at ≥95%, data quality CRITICAL with >10 issues
- **E2E tests organized by tier** (09-07): TestE2EWorkflowMocked, TestE2EWorkflowVariants, TestE2EObservability for flexible infrastructure requirements
- **Observability module exports** (09-07): All observability components (tracing, metrics, health, storage, alerts) exportable from single ta_lab2.observability import
- **PostgreSQL 16 service container for CI validation** (10-01): No mock mode for validation gates - all three validation types require real database per CONTEXT.md
- **Coverage threshold 70%** (10-01): Fail build if coverage drops below 70%, balances quality bar with pragmatic testing for v0.4.0 release
- **Session-scoped db_engine, function-scoped db_session** (10-01): db_engine created once per test session for efficiency, db_session with transaction rollback for test isolation
- **ensure_schema fixture for automatic setup** (10-01): Checks for dim_timeframe/dim_sessions tables, calls ensure_dim_tables if missing for reduced test setup friction
- **Zero tolerance for orphan timeframes** (10-02): All EMA tables must reference valid dim_timeframe entries, no orphans allowed (critical data integrity)
- **Zero tolerance for duplicates and NULL EMAs** (10-02): Each (id, ts, tf, period) unique, all EMAs non-NULL (data corruption indicators)
- **Tolerance-based for operational variations** (10-02): 5% rowcount (delisted assets/gaps), 10% tf_days cadence (holidays), 1% price-EMA alignment (weekends)
- **Graceful table existence checks** (10-02): Query information_schema before validation, pytest.skip for optional tables (cmc_ema_multi_tf_cal, cmc_returns_daily, cmc_vol_daily)
- **Keep a Changelog format for release notes** (10-06): Industry-standard format with Added/Changed/Fixed sections, more user-friendly than generated commit logs
- **MkDocs Material for documentation site** (10-06): Modern theme with navigation tabs, dark/light mode, mkdocstrings for API docs, mike for versioning
- **Automated release on version tag push** (10-06): GitHub Actions workflow triggers on v*.*.*, extracts CHANGELOG notes, builds docs bundle, creates release

### Pending Todos

None yet.

### Blockers/Concerns

None currently.

## Session Continuity

Last session: 2026-02-01
Stopped at: Completed 10-07-PLAN.md (API Reference Documentation) - Phase 10 plan 7/7 - PROJECT COMPLETE
Resume file: None

---
*Created: 2025-01-22*
*Last updated: 2026-02-01 (Phase 10 COMPLETE: 7/7 plans complete - PROJECT COMPLETE AT 100% - All 10 phases executed, v0.4.0 ready for release with comprehensive validation tests (70 tests), complete documentation suite (DESIGN.md, deployment.md, Memory API reference, Orchestrator CLI reference), MkDocs site configured, GitHub Actions release automation, and CHANGELOG.md - Ready for v0.4.0 release tag)*
