# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v1.0.0 V1 Closure — Paper Trading & Validation

## Current Position

Phase: Phase 43 (Exchange Integration) — In progress
Plan: 1/5 complete
Status: v1.0.0 in progress. Phase 42 complete. Phase 43 started: Plan 01 (ExchangeConfig + DDL) complete.
Last activity: 2026-02-25 — Completed 43-01-PLAN.md (ExchangeConfig dataclass; Alembic migration b180d8d07a85 for exchange_price_feed + paper_orders; reference DDL)

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 | [##########] 100% v0.7.0 | [##########] 100% v0.8.0 | [############] 100% v0.9.0 | [█████] Phase 42 COMPLETE | [█] Phase 43 1/5

## Performance Metrics

**Velocity:**
- Total plans completed: 215 (56 in v0.4.0, 56 in v0.5.0, 30 in v0.6.0, 10 in v0.7.0, 13 in v0.8.0, 1 in Phase 34 audit cleanup, 8 in Phase 35, 5 in Phase 36, 4 in Phase 37, 5 in Phase 38, 4 in Phase 39, 3 in Phase 40, 6 in Phase 41, 3 in Phase 41.1, 5 in Phase 42, 1 in Phase 43)
- Average duration: 7 min
- Total execution time: ~28 hours

**By Phase (v0.4.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 01-foundation-quota-management | 3 | 23 min | 8 min | Complete |
| 02-memory-core-chromadb-integration | 5 | 29 min | 6 min | Complete |
| 03-memory-advanced-mem0-migration | 6 | 193 min | 32 min | Complete |
| 04-orchestrator-adapters | 4 | 61 min | 15 min | Complete |
| 05-orchestrator-coordination | 6 | 34 min | 6 min | Complete |
| 06-ta-lab2-time-model | 6 | 37 min | 6 min | Complete |
| 07-ta_lab2-feature-pipeline | 7 | 45 min | 6 min | Complete |
| 08-ta_lab2-signals | 6 | 49 min | 8 min | Complete |
| 09-integration-observability | 7 | 260 min | 37 min | Complete |
| 10-release-validation | 8 | 34 min | 4 min | Complete |

**By Phase (v0.5.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 11-memory-preparation | 5 | 46 min | 9 min | Complete |
| 12-archive-foundation | 3 | 11 min | 4 min | Complete |
| 13-documentation-consolidation | 7 | 30 min | 4 min | Complete |
| 14-tools-integration | 13 | 128 min | 10 min | Complete |
| 15-economic-data-strategy | 6 | 36 min | 6 min | Complete |
| 16-repository-cleanup | 7 | 226 min | 32 min | Complete |
| 17-verification-validation | 8 | 38 min | 5 min | Complete |
| 18-structure-documentation | 4 | 21 min | 5 min | Complete |
| 19-memory-validation-release | 6 | 90 min | 15 min | Complete |

**Recent Trend:**
- v0.4.0 complete: 10 phases, 56 plans, 12.55 hours total
- v0.5.0 complete: 9 phases, 56 plans, 9.85 hours total
- v0.6.0 complete: 7 phases, 30 plans, ~3.80 hours total
- v0.7.0 complete: 2 phases, 10 plans, ~0.50 hours total
- v0.8.0 complete: 6 phases, 16 plans (13 execution + 2 gap closure + 1 audit cleanup), ~1.2 hours total

**By Phase (v0.6.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 20-historical-context | 3/3 | 17 min | 6 min | Complete |
| 21-comprehensive-review | 4/4 | 29 min | 7 min | Complete |
| 22-critical-data-quality-fixes | 6/6 | 82 min | 14 min | Complete |
| 23-reliable-incremental-refresh | 4/4 | 17 min | 4 min | Complete |
| 24-pattern-consistency | 4/4 | 40 min | 10 min | Complete |
| 25-baseline-capture | 2/2 | 11 min | 6 min | Complete |
| 26-validation | 3/3 | ~120 min | ~40 min | Complete |

**By Phase (v0.7.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 27-regime-integration | 7/7 | ~20 min | ~3 min | Complete |
| 28-backtest-pipeline-fix | 3/3 | ~17 min | ~6 min | Complete |

**By Phase (v0.8.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 29-stats-qa-orchestration | 3/3 | 13 min | 4 min | Complete |
| 30-code-quality-tooling | 2/2 | 12 min | 6 min | Complete |
| 31-documentation-freshness | 3/3 | ~25 min | ~8 min | Complete |
| 32-runbooks | 2/2 | ~9 min | ~5 min | Complete |
| 33-alembic-migrations | 2/2 | ~5 min | ~3 min | Complete |
| 34-audit-cleanup | 1/1 | ~2 min | ~2 min | Complete |

**By Phase (v0.9.0):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 35-ama-engine | 8/8 | ~56 min | ~7 min | Complete |
| 36-psr-purged-k-fold | 5/5 | ~24 min | ~5 min | Complete |
| 37-ic-evaluation | 4/4 | ~23 min | ~6 min | Complete |
| 38-feature-experimentation | 5/5 | ~19 min | ~4 min | Complete |

**By Phase (v0.9.1 Milestone Cleanup):**

| Phase | Plans | Total | Avg/Plan | Status |
|-------|-------|-------|----------|--------|
| 41.1-milestone-cleanup | 3/3 | ~8 min | ~3 min | Complete |

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- **Review first, then fix** (v0.6.0): Complete ALL analysis before code changes
- **Keep all 6 EMA variants** (v0.6.0): They exist for legitimate reasons (calendar alignment, ISO vs US, anchoring)
- **Bars and EMAs separate** (v0.6.0): Modular design, not tightly coupled
- **Move quickly on data sources** (v0.6.0): Bar tables have better validation, switch over decisively
- **Whatever it takes timeline** (v0.6.0): Do it right, even if it takes 6-8 weeks
- **Leverage proven Phase 6-7 patterns** (Phase 20): dim_timeframe, unified EMA table, state management are working - extend to bars, don't rebuild
- **EMAs already use bar tables** (Phase 20): CRITICAL - All 6 EMA variants already migrated to validated bars. Phase 22 assumption invalid, requires re-scoping.
- **All 6 EMA variants exist for legitimate reasons** (Phase 21): 80%+ infrastructure shared (BaseEMARefresher, EMAStateManager, compute_ema) with 20% intentional differences (data source, calendar alignment, anchoring) - NOT code duplication
- **Gap severity framework established** (Phase 21-04): CRITICAL (data corruption), HIGH (error-prone), MEDIUM (workarounds), LOW (nice-to-have) - 15 gaps identified (4 CRITICAL, 5 HIGH, 4 MEDIUM, 2 LOW), prioritized for Phase 22-24
- **Asset onboarding documented** (Phase 21-04): 6-step checklist (dim_assets -> 1D bars -> multi-TF bars -> EMAs -> validate -> verify incremental), 15-40 minutes per asset
- **Hybrid EMA validation** (Phase 22-02): Wide price bounds (0.5x-2x) catch corruption, narrow statistical bounds (3-sigma) catch drift - batched queries achieve <2% overhead
- **Warn and continue for EMA violations** (Phase 22-02): Write all EMAs even if invalid, log to both ema_rejects table and WARNING logs for maximum visibility
- **Derive multi-TF from 1D bars** (Phase 22-04/22-05): All 5 multi-TF builders support optional --from-1d derivation with calendar alignment - creates single source of truth for bar data quality
- **Reject tables dual purpose** (Phase 22-01): Multi-TF reject tables log OHLC repairs pre-derivation AND validate aggregation post-derivation - complete audit trail with violation_type + repair_action columns
- **Subprocess isolation for orchestrators** (Phase 23-01): EMA orchestrator refactored to use subprocess.run instead of runpy for process isolation, matching bar orchestrator pattern with dry-run and summary reporting
- **Unified daily refresh with state checking** (Phase 23-02): Single command for daily refresh (run_daily_refresh.py --all) with state-based bar freshness checking before EMAs - stale IDs are logged and skipped to prevent EMA computations on incomplete data
- **Makefile convenience layer** (Phase 23-03): make bars/emas/daily-refresh for common operations, Python-based date formatting for cross-platform compatibility
- **Daily log files with rotation** (Phase 23-03): .logs/refresh-YYYY-MM-DD.log for audit trail, automatic rotation (30 days default)
- **Severity-based Telegram alerting** (Phase 23-03): AlertSeverity enum filters alerts (default: ERROR+), send_critical_alert() for database/corruption errors
- **Preserve psycopg for SQL performance in 1D builder** (Phase 24-02): 1D bar builder uses large CTEs with complex aggregations - raw psycopg execution 2-3x faster than SQLAlchemy for this workload
- **Modernize CLI for BaseBarBuilder consistency** (Phase 24-02): Space-separated IDs, --full-rebuild flag for consistency across all bar builders using BaseBarBuilder
- **26.7% LOC reduction acceptable for SQL-based builders** (Phase 24-02): 1D builder achieved 260 lines saved (971->711) despite SQL-heavy implementation limiting code reuse with DataFrame-based base class
- **46% LOC reduction for calendar builders** (Phase 24-04): All 4 calendar builders refactored (5991->3230 lines), preserving calendar alignment (US Sunday vs ISO Monday) and anchor window logic despite complex semantics
- **tz column design documented (GAP-M03 closed)** (Phase 24-04): Calendar state tables use tz as metadata only, NOT in PRIMARY KEY - single timezone per run design is intentional, not a bug
- **NumPy allclose hybrid tolerance for baseline comparison** (Phase 25-01): Combine absolute (atol) + relative (rtol) tolerance to handle both small values near zero and large values correctly - avoids false positives/negatives from single epsilon threshold
- **Column-specific tolerances** (Phase 25-01): Price (1e-6/1e-5) vs volume (1e-2/1e-4) - different data types need different precision requirements
- **NaN == NaN is match** (Phase 25-01): Treat NaN == NaN as match using equal_nan=True to avoid SQL NULL semantics issues (NULL != NULL)
- **Git-based audit trail for baseline capture** (Phase 25-01): Capture git commit hash + timestamp + config in BaselineMetadata for full reproducibility 3 months later
- **Snapshot -> Truncate -> Rebuild -> Compare workflow** (Phase 25-02): Atomic validation pattern proves refactoring correctness by comparing identical input -> output transformations
- **Intelligent sampling (beginning/end/random)** (Phase 25-02): 30 days beginning + 30 days end + 5% random interior balances speed and confidence - detects temporal drift while avoiding full table scans
- **Never fail early in baseline capture** (Phase 25-02): Always run to completion, report ALL issues - partial results hide systemic problems
- **Subprocess isolation for baseline workflow** (Phase 25-02): Run bar builders and EMA refreshers via subprocess.run matching Phase 23 patterns (run_daily_refresh.py)
- **cmc_regime_comovement PK includes computed_at** (Phase 27-01): Retains historical snapshots across refreshes - each refresh snapshot preserved for temporal analytics
- **regime_key nullable on signal tables** (Phase 27-01): Existing signals have NULL regime_key, backward-compatible, signal generators populate going forward
- **regime_enabled defaults TRUE on dim_signals** (Phase 27-01): All existing signals automatically participate in regime-aware execution, opt-out is explicit
- **int cast before period sort in pivot_emas_to_wide** (Phase 27-02): Cast period to int before sorting column names -- prevents alphabetic trap where '200' < '50'; ensures close_ema_20 < close_ema_50 < close_ema_200
- **aggfunc='first' in pivot_table for EMA deduplication** (Phase 27-02): Defensive choice; plain pivot() raises ValueError on duplicates, pivot_table silently takes first value -- safer for production pipeline
- **HysteresisTracker tightening via size_mult/stop_mult** (Phase 27-04): Tightening = new size < old OR new stop > old; uses public resolve_policy_from_table not private _match_policy to stay decoupled from resolver internals
- **Flip detection includes initial assignment (old=None)** (Phase 27-04): First regime seen per (id,tf,layer) is recorded as flip with old_regime=None for full audit trail
- **Comovement scoped DELETE removes all prior snapshots** (Phase 27-04): write_comovement_to_db deletes all rows for (ids,tf) before insert, so each refresh leaves exactly one snapshot -- prevents unbounded table growth
- **BTC (id=1) as market proxy, skipped for self** (Phase 27-03): When computing regimes for id=1, skip proxy loading to avoid circular self-reference; proxy only applies for other assets lacking L0/L1 history
- **regime_key fallback chain L2->L1->L0->Unknown** (Phase 27-03): "Unknown" sentinel avoids None in NOT NULL column; L2 (daily) is primary as it has most bars
- **Row-by-row policy resolution acceptable** (Phase 27-03): 5614 rows resolves in ~2.4s total (DB I/O dominates); vectorization not needed for daily refresh cadence
- **regime_enabled defaults True on signal generators** (Phase 27-06): Opt-out pattern means all existing refresh workflows become regime-aware automatically; --no-regime flag for explicit A/B comparison
- **Graceful fallback on empty cmc_regimes** (Phase 27-06): load_regime_context_batch wraps SQL in try/except; merge_regime_context with empty df adds NULL columns - signals generate as before when regime table is empty
- **RSI regime_key via post-transform merge** (Phase 27-06): RSI transform_signals_to_records uses mutable dict update-in-place pattern; regime_key attached after via (id, entry_ts) join rather than inline to avoid structural changes to the transform method
- **Per-asset hysteresis tracker reset** (Phase 27-05): tracker.reset() before each asset prevents prior asset state leaking into next; critical for correctness when processing --all
- **Returns fallback to NULL stats** (Phase 27-05): _load_returns_for_id wraps in try/except; DEBUG-level log avoids noise; avg_ret_1d/std_ret_1d are NULL until cmc_returns.ret_1d column populated
- **Reload daily_df for comovement** (Phase 27-05): Reload via load_regime_input_data rather than threading through compute_regimes_for_id return; cleaner separation of concerns
- **--regimes standalone flag plus --all inclusion** (Phase 27-07): Consistent with --bars/--emas pattern; --all becomes single command for bars->EMAs->regimes pipeline
- **EMA early-stop before regimes** (Phase 27-07): Added failure check before running regimes - regimes depend on fresh EMAs; propagates --dry-run to regime subprocess
- **regime_inspect default reads from DB** (Phase 27-07): Operational check should be fast; --live flag triggers compute_regimes_for_id for testing changes before write
- **JSONB serialization pattern** (Phase 28-01): Use `json.dumps(x) if isinstance(x, dict) else x` before to_sql() for JSONB columns -- isinstance guard is defensive, handles pre-serialized strings; all 3 signal generators now consistent
- **_ensure_utc pattern** (Phase 28-02): Helper checks ts.dt.tz: None -> tz_localize("UTC"), aware -> tz_convert("UTC") -- safe for both vbt naive output and pandas tz-aware series
- **Tz boundary pattern for vectorbt** (Phase 28-02): Strip tz at vectorbt ingestion (run_backtest), re-add at trade extraction (_ensure_utc in _extract_trades) -- single strip covers all downstream vectorbt calls
- **str.lower() for vbt direction** (Phase 28-02): vbt 0.28.1 returns 'Long'/'Short' strings, not integers -- .astype(str).str.lower() handles both string and integer cases without NaN
- **Backward-compat fee extraction** (Phase 28-02): Entry Fees + Exit Fees (vbt 0.28.1) -> Fees (older vbt) -> 0.0 -- chained fallback maximizes cross-version compatibility
- **ts coercion at merge point** (Phase 28-03): When pd.read_sql legacy path returns ts as object dtype, coerce both sides of merge via pd.to_datetime(utc=True) in merge_regime_context -- single central fix covers all 3 signal generator callers
- **load_prices without index_col** (Phase 28-03): pd.read_sql with index_col='ts'+parse_dates infers local-offset tz (UTC-04:00) producing 1903 duplicate index entries; post-hoc coerce via pd.to_datetime(utc=True).tz_convert("UTC").tz_localize(None) is reliable
- **date-string split bounds for vbt** (Phase 28-03): strftime('%Y-%m-%d') triggers pandas partial-date matching (inclusive range) for tz-naive DatetimeIndex with 23:59:59.999 entries -- exact Timestamp key lookup fails
- **numpy scalar normalization at SQL boundary** (Phase 28-03): _to_python() with hasattr(v, 'item') normalizes np.float64/np.int64/np.bool_ to Python native before psycopg2 binding -- avoids 'schema "np" does not exist' error
- **vbt 0.28.1 price columns renamed** (Phase 28-03): 'Entry Price'/'Exit Price' -> 'Avg Entry Price'/'Avg Exit Price' in records_readable; use 'Avg Entry Price' in columns check with fallback
- **v0.8.0 sequencing constraint** (Roadmap): Phase 29 (Stats) before Phase 30 (Quality) so new orchestrator code is included in ruff sweep; Phase 33 (Alembic) can run in parallel with Phase 29; Phase 31 (Docs) after Phase 30; Phase 32 (Runbooks) last
- **Subprocess timeouts before new steps** (v0.8.0 research): Add timeout= to all existing subprocess.run() calls BEFORE wiring new stats runner subprocess steps -- prevents silent hangs on Windows (CPython issue #88693)
- **Ruff zero-violations before removing || true** (v0.8.0 research): Run ruff check src --statistics, fix all violations, verify zero-exit locally, THEN remove || true in a separate PR -- never remove escape hatch while violations exist
- **No alembic autogenerate in v0.8.0** (v0.8.0 research): Write baseline migration by hand as a no-op; autogenerate without ORM models recreates all 50 tables as op.create_table() calls -- stamp-then-forward only
- **mypy scoped to features/ and regimes/ only** (v0.8.0 research): Initial CI check non-blocking (continue-on-error: true); 35% unannotated functions + vectorbt/psycopg2 noise make global strict enforcement impossible in v0.8.0
- **encoding='utf-8' in alembic env.py** (v0.8.0 research): Per MEMORY.md Windows pitfall -- UTF-8 box-drawing chars in SQL comments cause UnicodeDecodeError with default cp1252 encoding
- **pyproject.toml is version source of truth** (v0.8.0 research): importlib.metadata.version("ta_lab2") reads pyproject.toml; update all three files (pyproject.toml, mkdocs.yml, README.md) to 0.8.0 in a single commit
- **Tiered subprocess timeouts by operation weight** (Phase 29-01): bars=7200s, EMAs=3600s, regimes=1800s, stats=3600s, audit=1800s, sync=600s, git=30s, tools=300s -- module-level TIMEOUT_X constants with 'initial estimate' annotation
- **TimeoutExpired as separate except clause** (Phase 29-01): Catch subprocess.TimeoutExpired BEFORE generic Exception -- keeps timeout error messages clear and distinct; tools use RuntimeError raise, orchestrators use ComponentResult(error_message=...)
- **report_dev_timeline.py module-level fallback** (Phase 29-01): git log runs at import/module level -- try/except at module scope with git_log=[] fallback (can't return ComponentResult at module scope)
- **Stats exit code as pipeline signal** (Phase 29-02): run_all_stats_runners.py exits 1 for FAIL (DB rows or crashed runners), 0 for PASS/WARN -- run_daily_refresh.py checks exit code for pipeline gate
- **DB query is authoritative for FAIL/WARN** (Phase 29-02): Stats runners exit 0 even when they write FAIL rows; orchestrator queries DB after all runners complete -- do NOT rely solely on subprocess return codes
- **Pipeline gate is unconditional for stats** (Phase 29-02): Stats FAIL always halts even with --continue-on-error; continuing past bad data is worse than stopping; bars/EMAs respect --continue-on-error but stats does not
- **Telegram alerting internal to stats orchestrator** (Phase 29-02): run_daily_refresh.py only checks exit code; Telegram logic in run_all_stats_runners.py for cohesion
- **Aggregate comparison for weekly delta** (Phase 29-03): Delete-before-insert means last-week rows for un-impacted keys may not be present; compare aggregate FAIL/WARN totals (NOT row-level) for reliable week-over-week delta
- **Weekly digest NOT in --all** (Phase 29-03): Digest is a reporting operation invoked on demand (--weekly-digest); --all runs the data refresh pipeline (bars+EMAs+regimes+stats); separate concerns
- **Dry-run exits before DB engine creation in weekly_digest** (Phase 29-03): --dry-run prints table list and exits 0 immediately, no SQLAlchemy engine created -- safe for CI/verification without DB
- **Telegram split strategy for digest** (Phase 29-03): Try combined message (<4000 chars) first, truncate to top-5-FAIL if needed, split into two messages as final fallback -- covers all realistic 7-table digest sizes
- **E741 l->lq for liquidity loop vars** (Phase 30-01): In labels.py the `l` var iterates over liq (liquidity) series -- rename to `lq` not `lo`; `lo` reserved for OHLC low price in vol.py/resample.py/breakout_atr.py
- **Pre-commit ruff version mismatch** (Phase 30-01): .pre-commit-config.yaml pins ruff to v0.1.14 while local is 0.14.3; causes hook to reformat Protocol stub ellipsis differently; use --no-verify for formatting fixup commits; update pin in Plan 30-02
- **target-version=py312 eliminates invalid-syntax** (Phase 30-01): Adding [tool.ruff] global section with target-version=py312 fixes f-string backslash and except* syntax violations without touching code
- **pandas-stubs dev-only not all** (Phase 30-02): Adding to all group risks numpy version conflict with vectorbt 0.28.1; dev group is safe since vectorbt is not a dev dependency
- **mypy continue-on-error: true** (Phase 30-02): 15 documented baseline errors in features/regimes (35% unannotated + missing stubs for vectorbt/psycopg2) -- non-blocking enables visibility without blocking PRs
- **5-job parallel CI** (Phase 30-02): test/lint/format/mypy/version-check all independent, no depends-on chains; lint/format/version-check fast (<30s), mypy non-blocking, test is the slow matrix job
- **Hard gate removal protocol** (Phase 30-02): Fix all violations FIRST (Plan 30-01) THEN remove || true (Plan 30-02) -- never remove escape hatch while violations exist
- **Split pipeline diagrams into two .mmd files** (Phase 31-02): data_flow.mmd (main pipeline TD) + table_variants.mmd (variant structure LR) -- cleaner rendering than single combined file; Mermaid renderer support for multi-diagram varies
- **Alembic section deleted not replaced** (Phase 31-01): Aspirational alembic commands removed with no placeholder -- Phase 33 will add real migration docs when Alembic is implemented; empty sections mislead users
- **Historical changelog entries preserved** (Phase 31-01): v0.4.0/v0.5.0 release entries in README.md and docs/index.md are historical facts, not stale content -- only version-position fields (headers, footers, site_name) are bumped
- **Nav anchors removed from mkdocs.yml** (Phase 31-03): mkdocs --strict treats page.md#anchor as a missing file reference; clean page.md paths only
- **docs/CHANGELOG.md as content copy** (Phase 31-03): mkdocs on Windows does not follow symlinks; a real file copy is required; updated with v0.8.0 entry
- **mkdocs-material pinned <9.7** (Phase 31-03): v9.7.x introduced a colorama dependency that crashes on Windows; pin in pyproject.toml docs + all groups
- **CI docs job independent** (Phase 31-03): docs job runs mkdocs build --strict as blocking gate; version-check now validates pyproject.toml == README.md == mkdocs.yml
- **Standard alembic template over pyproject template** (Phase 33-01): `alembic init alembic` (standard) used; pyproject template appends [tool.alembic] to pyproject.toml but still generates alembic.ini anyway -- redundant; standard template cleaner
- **target_metadata=None in alembic env.py** (Phase 33-01): Permanently disables autogenerate -- without ORM models it would emit op.create_table() for all 50+ existing tables; all revisions written by hand
- **Placeholder URL in alembic.ini, real URL via resolve_db_url()** (Phase 33-01): alembic.ini committed with driver://user:pass@localhost/dbname; env.py calls resolve_db_url() which reads db_config.env, TARGET_DB_URL, or MARKETDATA_DB_URL
- **Baseline revision 25f2b3c90f65 as Alembic epoch** (Phase 33-02): No-op baseline with down_revision=None; alembic stamp head applied to production DB; represents cumulative state after all 17 legacy SQL migrations applied
- **alembic history in CI not alembic current** (Phase 33-02): history reads filesystem only (no DB), current requires live DB -- history is appropriate for CI structural validation
- **stamp not upgrade on existing production DB** (Phase 33-02): stamp records current state without DDL; upgrade runs migration code -- use stamp only during initial setup and disaster recovery
- **Unconditional DROP IF EXISTS for PSR downgrade** (Phase 36-01): Pre-migration DB had no psr column; renaming psr_legacy back to psr in downgrade creates a phantom column -- use DROP COLUMN IF EXISTS on both columns to return to exact pre-migration state
- **Two separate PSR revisions** (Phase 36-01): Column rename (adf582a23467) and table creation (5f8223cfbf06) are independent; separate revisions allow bisecting failures and rolling back table only
- **psr_results unique on (run_id, formula_version)** (Phase 36-01): Prevents duplicate computations; enables multiple formula variants per run for A/B comparison between implementations
- **return_source TEXT for PSR inputs** (Phase 36-01): Distinguishes portfolio-level vs trade-reconstruction returns -- affects skewness/kurtosis estimates which feed directly into PSR formula
- **AMA orchestrator uses -m module invocation** (Phase 35-08): All AMA subprocesses invoked via python -m module (not script file paths) -- consistent with refresh_returns_zscore and run_all_stats_runners invocation pattern
- **PostStep gate: any_value_succeeded** (Phase 35-08): Post-steps run if at least one value refresher succeeds (not all) -- with --continue-on-error, partial value refresher success still produces data; post-steps process whatever was produced
- **AMAs inherit fresh-bar IDs from EMA filtering** (Phase 35-08): ids_for_amas = ids_for_emas when run_emas is True -- AMAs process same stale-bar-filtered set as EMAs; stale assets skipped in both EMA and AMA stages
- **v0.9.0 AMA table family** (v0.9.0 research): cmc_ama_multi_tf uses (id, ts, tf, indicator, params_hash) PK -- separate namespace from EMA tables; indicator column distinguishes KAMA/DEMA/TEMA/HMA in a single table
- **v0.9.0 IC requires train_start/train_end** (v0.9.0 research): All IC functions enforce time-bounded evaluation; no full-history IC for feature selection -- prevents future-information leakage
- **v0.9.0 PurgedKFold from scratch** (v0.9.0 research): Implement PurgedKFoldSplitter without mlfinlab (discontinued, known bug); t1_series required argument, not optional
- **v0.9.0 BH correction as promotion gate** (v0.9.0 research): scipy.stats.false_discovery_control() for BH correction; promotion rejected if no horizon passes at alpha=0.05
- **v0.9.0 PSR migration first** (v0.9.0 research): Alembic migration psr->psr_legacy MUST precede any PSR formula code -- column name collision risk
- **v0.9.0 Streamlit NullPool** (v0.9.0 research): All dashboard DB queries use NullPool + @st.cache_data(ttl=300); fileWatcherType=poll for Windows compatibility
- **v0.9.0 zero new core deps** (v0.9.0 research): scipy, sklearn, plotly, streamlit already installed; only new package is jupyterlab >= 4.5
- **v0.9.0 fix fillna deprecation before IC** (v0.9.0 research): Replace fillna(method='ffill') with ffill() in feature_eval.py before adding IC code -- avoids FutureWarning becoming error
- **AMA uses indicator+params_hash PK** (Phase 35-01): (id, ts, tf, indicator, params_hash) replaces (id, ts, tf, period) -- single table for all AMA types (KAMA/DEMA/TEMA/HMA) distinguished by indicator column
- **dim_ama_params lookup table** (Phase 35-01): Maps (indicator, params_hash) -> params_json JSONB + label TEXT -- human-readable parameter resolution without decoding hashes
- **AMA returns have no bar-space variant** (Phase 35-01): _ama columns only (no _ama_bar family) -- AMAs computed on canonical bar closes only, simplifies DDL vs EMA pattern
- **params_hash covers params dict only, not indicator** (Phase 35-02): DEMA(21)/TEMA(21)/HMA(21) share hash d47fe5cc -- correct design; indicator column provides DB-level differentiation; compute_params_hash receives only the params dict
- **AMAParamSet.params hash=False** (Phase 35-02): Frozen dataclass with mutable dict field requires hash=False, compare=False on that field -- prevents TypeError at instantiation while keeping the dataclass immutable in practice
- **KAMA warmup guard via np.full(n, nan) init** (Phase 35-02): All warmup rows are NaN by default from initialization -- only valid positions get computed values; DEMA/TEMA use explicit iloc[:warmup]=nan because ewm() produces values from row 0
- **HMA uses rolling().apply(raw=True) for WMA** (Phase 35-02): raw=True passes numpy array per window avoiding Series overhead; mathematically correct (linear weights, not exponential); _wma_numpy convolution alternative held in reserve if profiling shows bottleneck on 109 TFs
- **er column inline on AMA value tables** (Phase 35-01): KAMA Efficiency Ratio stored as er column, NULL for DEMA/TEMA/HMA -- queryable as standalone IC signal without separate join
- **BaseAMAFeature sibling not subclass of BaseEMAFeature** (Phase 35-03): (indicator, params_hash) PK vs (period) requires independent _get_pk_columns() and _pg_upsert() -- sharing code would require awkward overrides of every DB method
- **AMAStateManager standalone class** (Phase 35-03): Does NOT reuse EMAStateManager -- EMAStateManager DDL hardcodes period INTEGER PK which is wrong for AMA state
- **d1_roll == d1 for multi_tf AMA** (Phase 35-03): No intra-period roll variant exists (all rows roll=FALSE); _roll columns kept for schema compatibility with EMA table family
- **CAST(:params_json AS jsonb) not ::jsonb** (Phase 35-04): SQLAlchemy text() bind param syntax conflicts with Postgres ::jsonb cast suffix; CAST(... AS jsonb) is standard SQL and driver-agnostic
- **Minimum watermark strategy for incremental AMA** (Phase 35-04): start_ts = min(last_canonical_ts across all param_sets for a TF); if ANY param_set has no state, start_ts=None triggers full history for all -- ensures consistency across param_sets in a TF batch
- **BaseAMARefresher not subclass of BaseEMARefresher** (Phase 35-04): AMA needs AMAWorkerTask (not WorkerTask), AMAStateManager (not EMAStateManager), param_sets (not periods) -- inheriting would require overriding virtually every method
- **AMAReturnsFeature standalone not subclass** (Phase 35-05): Different responsibility than BaseAMAFeature — reads indicator values and computes returns vs. reads bars and computes values; sharing would require awkward multi-level inheritance
- **State inline DDL creation for returns** (Phase 35-05): _ensure_state_table() creates returns state table at runtime with (id, tf, indicator, params_hash) PK + last_ts watermark — no pre-existing migration needed
- **c_delta1.values for canonical assignment** (Phase 35-05): When assigning canonical column results back via .loc[canon_idx], use .values to avoid pandas index alignment issues where canonical subset index doesn't match parent index
- **sync_sources_to_unified() unmodified for AMA** (Phase 35-07): Dynamic column discovery via information_schema handles indicator+params_hash+alignment_source automatically; AMA_SOURCE_PREFIX='cmc_ama_' strips to multi_tf, multi_tf_cal_us, etc.
- **Z-score key_cols must include indicator+params_hash** (Phase 35-07): Omitting them aggregates across KAMA/DEMA/TEMA/HMA rows for same (id, tf) — produces garbage; each AMA type+param set gets independent rolling z-score series
- **_process_key temp table DDL handles AMA cols via else->text** (Phase 35-07): indicator, params_hash, alignment_source all map to text type via existing else-branch — no changes to _process_key needed for AMA support
- **Custom worker per calendar AMA refresher** (Phase 35-06): _cal_ama_worker / _cal_anchor_ama_worker defined at module level (required for pickling); base _ama_worker hardcodes MultiTFAMAFeature — calendar variants need scheme-aware feature class selection via task.extra_config["scheme"]
- **SCHEME_MAP for cal AMA routing** (Phase 35-06): Single dict maps scheme key -> feature_class/bars_table/output_table/state_table; mirrors EMA calendar pattern; avoids scattered if/else in worker and _run_for_scheme
- **No-arg constructor on CalAMARefresher** (Phase 35-06): BaseAMARefresher.create_argument_parser() calls cls() to get get_description() before scheme is known — constructor accepts scheme="us" as default
- **Pearson kurtosis mandatory for PSR** (Phase 36-02): scipy kurtosis(fisher=False) gives gamma_4≈3 for normal data; Fisher/excess (default) gives gamma_4≈0 — wrong variance formula producing SR > sqrt(2) numerical issues
- **PSR zero-std guard before SR calculation** (Phase 36-02): std==0 returns 0.5/0.0/1.0 based on sr_star sign; must come BEFORE sr_hat = mean/std to avoid division by zero
- **DSR approximate mode uses fixed seed** (Phase 36-02): rng(42) generates synthetic N(0,1) SR estimates for expected_max_sr — reproducible approximation when full SR list unavailable
- **Kurtosis test uses relative error + directional comparison** (Phase 36-02): abs tolerance 1e-8 too tight at T=100k due to sample moments — use rel_err for Pearson-vs-approx, directional Pearson>Fisher for the kurtosis trap test
- **tz-aware pandas comparison fix** (Phase 36-03): Use (series <= ts).to_numpy() not series.values <= ts for tz-aware timestamps — .values strips tz on Windows (MEMORY.md pitfall), causing TypeError in purge comparison
- **PurgedKFoldSplitter t1_series required** (Phase 36-03): ValueError when None — implement from scratch, no mlfinlab (discontinued, known bug #295)
- **CPCVSplitter combos pre-computed at init** (Phase 36-03): itertools.combinations stored as self._combos — O(1) get_n_splits() and consistent iteration order for PBO path matrix
- **Purge in CPCV uses min test_start_ts** (Phase 36-03): Earliest start across all combo groups is the purge boundary — prevents any label from any training obs bleeding into any test group
- **Warn-only migration check (never auto-upgrade)** (Phase 36-05): run_daily_refresh.py checks alembic current vs head at startup; warns with `alembic upgrade head` instructions; try/except wrapper prevents check failure from crashing pipeline
- **NullPool for migration check** (Phase 36-05): Matches project pattern for one-shot DB connections; check skipped in --dry-run mode
- **_psr_* prefix pattern for detail stats** (Phase 36-04): PSR distributional stats (skewness, kurtosis, n_obs, min_trl) stored in metrics dict with _psr_ prefix; stripped before cmc_backtest_metrics INSERT; passed to psr_results INSERT in same transaction
- **return_source distinguishes PSR compute paths** (Phase 36-04): 'portfolio' = pf.returns() during backtest (exact, fees-aware); 'trade_reconstruction' = pnl_pct/n_bars approximation from CLI; column makes distinction queryable
- **DSR CLI deferred to Phase 37+** (Phase 36-04): compute_dsr() library function satisfies formula requirement; CLI extension needs multiple runs' returns simultaneously — not a single-run operation
- **fwd_ret.reindex() for IC boundary alignment** (Phase 37-02): Use reindex(feat_train.index) not boolean mask when feature and forward return series have different index lengths — aligns by label, avoids IndexError
- **DatetimeIndex arithmetic returns numpy bool array directly** (Phase 37-02): (feat_train.index + pd.Timedelta(...)) > train_end returns numpy.ndarray, not pandas BooleanArray — no .to_numpy() needed for iloc indexing
- **IC boundary masking via full-series fwd_ret then reindex+null** (Phase 37-02): Compute forward returns on full series, reindex to train window, null boundary bars where bar_ts + horizon_days > train_end — explicit look-ahead prevention vs. implicit NaN-at-slice-tail
- **Rolling IC vectorized rank-then-correlate** (Phase 37-02): rolling().rank() then rolling().corr() is 30x faster than per-window spearmanr() loop; IC-IR = mean/std; IC-IR t-stat = mean*sqrt(n)/std (ttest_1samp equivalent)
- **compute_ic_by_regime accepts pre-built regimes_df** (Phase 37-03): Library layer does NOT load from DB; l2_label parsing (split('-') -> trend_state/vol_state) happens in CLI/DB helper layer (Plan 04); keeps library pure and testable without DB
- **Sparse-regime guard at min_obs_per_regime=30** (Phase 37-03): Regimes with fewer bars silently skipped; if ALL regimes sparse, falls back to full-sample IC with regime_label='all' — never returns empty DataFrame
- **Regime-window train bounds from common_ts intersection** (Phase 37-03): Use min/max of feature-close intersection within regime label as synthetic train_start/train_end — prevents boundary masking from nulling all regime bars
- **batch_compute_ic excludes 'close' by name convention** (Phase 37-03): Auto-detected feature_cols = all numeric columns except 'close'; consistent with close being a separate argument
- **Significance coloring threshold 0.05** (Phase 37-03): plot_ic_decay uses sig_threshold=0.05 default; royalblue for significant bars, lightgray for non-significant
- **Column validation before SQL injection in load_feature_series** (Phase 37-04): get_columns() validates feature_col exists before f-string SQL injection — prevents both runtime errors and column-name SQL injection
- **split_part SQL for cmc_regimes l2_label parsing** (Phase 37-04): cmc_regimes has NO trend_state/vol_state columns — must derive via split_part(l2_label, '-', 1/2) SQL; never reference them as WHERE filter columns
- **save_ic_results individual INSERT per row** (Phase 37-04): Loops over rows for accurate rowcount; ON CONFLICT DO NOTHING (append) vs DO UPDATE (overwrite) controlled by overwrite= flag
- **_to_python() numpy scalar normalization at SQL boundary** (Phase 37-04): hasattr(v, 'item') check normalizes numpy scalars; NaN -> None for SQL NULL; pd.Timestamp -> pydatetime for TIMESTAMPTZ binding
- **Feature registry lifecycle CHECK constraint** (Phase 38-01): dim_feature_registry enforces lifecycle IN ('experimental','promoted','deprecated') at DB level via CHECK constraint — state machine is DB-enforced, not just application-level
- **cmc_feature_experiments 9-col unique key** (Phase 38-01): (feature_name, asset_id, tf, horizon, return_type, regime_col, regime_label, train_start, train_end) enables upsert semantics; parallel to cmc_ic_results structure but with feature_name (registry FK) replacing feature (raw column name)
- **BH-corrected p-value stored at row level** (Phase 38-01): ic_p_value_bh in cmc_feature_experiments stored per experiment row — enables post-hoc significance analysis and promotion gate without rerunning BH correction
- **Compute cost columns in experiments table** (Phase 38-01): wall_clock_seconds, peak_memory_mb, n_rows_computed — ExperimentRunner can use these to route cheap vs expensive features and monitor resource usage
- **YAML feature registry lifecycle validation at load time** (Phase 38-02): FeatureRegistry raises ValueError on invalid lifecycle at load() not at compute time — fail fast before any ExperimentRunner computation
- **Sweep naming convention {base}_{key}{val}** (Phase 38-02): Predictable, inspectable variant names from itertools.product expansion; duplicate detection via _features dict keyed by expanded name
- **eval globals inject np+pd restrict __builtins__** (Phase 38-02): np.log(close) works in inline expressions; os.system() blocked; documents trust assumption for trusted YAML files
- **External depends_on silently filtered in DAG** (Phase 38-02): Features referencing promoted/external dependencies are not in the registry dict; DAG silently drops them from edges — allows gradual promotion without breaking YAML
- **Single connection for all assets in ExperimentRunner** (Phase 38-03): PostgreSQL temp tables are session-scoped; opening new connection per asset drops the table; one `with engine.connect() as conn:` block covers all assets in a run
- **BH correction across all rows not per-asset** (Phase 38-03): scipy.stats.false_discovery_control() applied ONCE across all (asset x horizon x return_type) — more conservative; matches plan intent for 'single run hypothesis testing'
- **_ALLOWED_TABLES frozenset at query time** (Phase 38-03): Allowlist validated in _load_inputs() not registry.load() — catches YAML edits after initial validation; prevents SQL injection from crafted table names
- **save_experiment_results DO UPDATE semantics** (Phase 38-03): ON CONFLICT uq_feature_experiments_key DO UPDATE — re-running experiment updates results rather than silently skipping; correct for analysis workflows
- **BH gate default min_pass_rate=0.0** (Phase 38-04): At least one combo must pass BH at alpha=0.05 (not all); stricter enforcement via --min-pass-rate CLI flag; practical for horizon-specific significance
- **Live Alembic head for migration stub down_revision** (Phase 38-04): SELECT version_num FROM alembic_version at runtime — never hardcode; avoids chain breaks when new migrations added between promotion runs
- **Non-destructive feature deprecation** (Phase 38-04): deprecate_feature() sets lifecycle='deprecated', does NOT drop cmc_features column (requires downtime) or delete experiment rows (audit trail); purge_experiment.py defaults to deprecate, not delete
- **NaN filter before false_discovery_control()** (Phase 38-04): scipy raises ValueError on NaN inputs; filter valid_mask before passing array; return (False, df, reason) when zero valid p-values exist
- **Duplicate detection requires expanded-name collision, not base-name collision** (Phase 38-05): YAML keys must be unique so two features with same base name is impossible; collision arises when sweep expansion produces a variant name that matches an explicitly defined feature (e.g., rsi_sweep[period=5] -> rsi_sweep_period5 collides with explicit rsi_sweep_period5)
- **dotpath tests patch at import site not target module** (Phase 38-05): Use patch('ta_lab2.experiments.runner.importlib.import_module') not 'importlib.import_module' — ensures mock intercepts ExperimentRunner's importlib calls
- **plot_rolling_ic horizon not window parameter** (Phase 39-02): plan assumed window= kwarg but plot_rolling_ic uses horizon= (optional int shown in subtitle); build_rolling_ic_chart maps window->horizon; window is consumed by compute_rolling_ic() which produces the series
- **chart_download_button lazy streamlit import** (Phase 39-02): import streamlit inside function body — charts.py is imported by notebooks/tests outside Streamlit context; lazy import prevents ImportError at module load time
- **vrect opacity=1 with rgba alpha for bands** (Phase 39-02): Plotly vrect opacity multiplies the rgba channel; set opacity=1 and use low rgba alpha (0.12-0.15) for correct transparency behavior
- **Traffic light uses worst-case staleness per family** (Phase 39-03): max(staleness_hours) per family group surfaces any stale table even when others are fresh; avoids false green if one variant is stale
- **Landing page IC preview: first asset alphabetically** (Phase 39-03): dim_assets ordered by symbol; BTC (id=1) fallback when list empty; preview uses tf='1D' always
- **TABLE_FAMILIES constant for family grouping** (Phase 39-03): dict[display_name->prefix] used in both Data Freshness expanders and Asset Coverage pivot; unknown source_tables fall back to raw name
- **NullPool per notebook session** (Phase 40-01): helpers.get_engine() uses NullPool — avoids connection leak across long-running notebook cells; matches Streamlit dashboard pattern
- **AMAs on-the-fly in notebooks** (Phase 40-01): compute_ama() called directly rather than querying cmc_ama_multi_tf — exploratory notebooks demonstrate the library API; no pre-computed table needed
- **vrect block grouping** (Phase 40-01): build_regime_vrects() collapses consecutive same-label bars into blocks before fig.add_vrect() — prevents Plotly performance issue with 1000+ individual shapes
- **window reserved word in raw SQL** (Phase 41-01): PostgreSQL reserved word `window` must be double-quoted in raw op.execute() SQL strings; SQLAlchemy op.create_table/op.create_index handle quoting automatically; always test upgrade immediately after writing migrations with raw SQL
- **Materialized view via op.execute()** (Phase 41-01): Alembic has no native materialized view op; use op.execute() with raw SQL for CREATE MATERIALIZED VIEW and CREATE UNIQUE INDEX; unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY
- **Programmatic DDL column generation** (Phase 41-01): For repetitive column patterns (32 stat cols = 8 stats x 4 windows), generate via helper function with tuple constants to avoid copy-paste errors in migration files
- **str(engine.url) strips password in SQLAlchemy** (Phase 41-02): str(engine.url) returns masked URL (postgres:***); use explicit db_url string pass-through in worker callchain to avoid authentication failures in subprocess workers
- **Tz-safe watermark read pattern** (Phase 41-02): pd.Timestamp(row[0]).tz_convert("UTC") if tzinfo else .tz_localize("UTC") — DB may return offset-aware timestamps (e.g. -05:00); constructing pd.Timestamp(row, tz="UTC") raises TypeError when tzinfo already present
- **kurt_pearson = kurt_fisher + 3.0** (Phase 41-02): pandas .kurt() returns Fisher/excess kurtosis (normal=0); Pearson kurtosis = Fisher + 3.0 (normal=3); both stored for flexibility in downstream analysis (PSR uses Pearson)
- **cmc_returns_bars_multi_tf uses "timestamp" not "ts"** (Phase 41-03): Source table for correlation uses `"timestamp"` column (PostgreSQL reserved word, must double-quote in raw SQL); contrast with cmc_cross_asset_corr which uses `ts`
- **SpearmanrResult named tuple access** (Phase 41-03): scipy.stats.spearmanr() returns SpearmanrResult with .statistic and .pvalue attributes (not positional [0]/[1] indexing); same pattern applies to pearsonr()
- **Wide-load strategy for pairwise correlation** (Phase 41-03): Load all assets' ret_arith for a TF in one query, pivot to wide DataFrame, loop over pairs in Python — avoids N*(N-1)/2 separate DB queries per TF
- **tz_localize/tz_convert on DatetimeIndex** (Phase 41-03): After pd.DataFrame.pivot(), use `if wide.index.tz is None: .tz_localize("UTC") else: .tz_convert("UTC")` — raw `pd.DatetimeIndex(idx, tz="UTC")` raises TypeError when index already has tzinfo
- **Desc stats pipeline position: AMAs -> desc_stats -> regimes** (Phase 41-04): desc_stats runs after AMAs (depends on fresh bars/EMAs), before regimes (independent of desc_stats); pipeline order: bars -> EMAs -> AMAs -> desc_stats -> regimes -> stats
- **Used -m module invocation for desc_stats orchestrator** (Phase 41-04): run_all_desc_stats_refreshes uses python -m module (not script path), matching stats runners and AMA orchestrator patterns
- **--workers not --num-processes for desc stats subprocess** (Phase 41-04): run_all_desc_stats_refreshes uses --workers param name; daily refresh maps num_processes -> workers when forwarding
- **load_rolling_stats returns None not empty DataFrame** (Phase 41-06): Allows callers to distinguish "unavailable" from "empty table" — cleaner conditional logic
- **Regime stats augmentation in main loop not compute_regimes_for_id** (Phase 41-06): Preserves labeling function purity; augmentation left-joined after load_regime_input_data in per-asset loop
- **check_desc_stats_quality inline not in STATS_TABLES/ALL_STATS_SCRIPTS** (Phase 41-06): No subprocess runner script exists for desc stats tables; inline function avoids creating one
- **filter_ prefix on ExperimentRunner filter params** (Phase 41.1-01): Prevents collision with existing id/tf/start/end params; filter keys double-quoted in SQL for reserved-word safety
- **AMA tables NOT in _TABLES_WITHOUT_TF** (Phase 41.1-01): AMA tables have tf column; standard WHERE id/tf/ts clause applies; only cmc_vol/cmc_ta_daily lack tf
- **fold_boundaries public API** (Phase 41.1-03): Renamed from _fold_boundaries — external callers (notebooks, CLIs) should reference public name; _fold_sizes kept private
- **Column name sanitization before SQL interpolation** (Phase 41.1-03): all(c.isalnum() or c == '_' for c in col) guards before SQL f-string in load_feature_close_series — prevents injection from user-facing selectbox input
- **close_series_for_ic alias in rolling IC section** (Phase 41.1-03): Avoids shadowing close_series used in Regime Analysis section on same page; Streamlit pages execute top-to-bottom, shadowing breaks later sections
- **IC sweep two-phase strategy** (Phase 42-01): Full 914-pair sweep takes 3-4+ hours; run key TFs (1D, 7D, 14D, 30D, 90D) covering all assets -- delivers 47,614 IC rows in 7-8 minutes for the highest-signal TFs
- **Per-pair transaction isolation for IC sweep** (Phase 42-01): Each (asset_id, tf) uses its own engine.begin() context; AMA table absence doesn't abort cmc_features sweep; prevents cascade failures
- **AMA IC sweep graceful degradation** (Phase 42-01): table_exists() pre-check in _discover_ama_combos(); returns empty list if table absent; sweep re-runnable once AMA pipeline populates the table
- **Regime breakdown scoped to BTC/ETH 1D** (Phase 42-01): _REGIME_ASSET_IDS frozenset pattern; extending to all assets/TFs multiplies compute 4-7x with diminishing analytical value
- **CAST(:param AS jsonb) for JSONB in SQLAlchemy text()** (Phase 42-02): :param::jsonb triggers psycopg2 syntax error (colon clash with named param syntax); use CAST(:param AS jsonb) instead
- **DSR sr_estimates must be per-bar not annualized** (Phase 42-02): compute_psr/dsr uses per-bar sr_hat = mean/std; divide annualized Sharpe by sqrt(365) before passing as sr_estimates benchmark
- **V1 gate outcome: no single strategy passes Sharpe>=1.0 + MaxDD<=15%** (Phase 42-02): Best is ema_trend BTC 1D Sharpe=1.42 but MaxDD worst=-70.1%; RSI low drawdown but Sharpe<1.0; ensemble/blending step needed per CONTEXT.md
- **Fixed-parameter walk-forward as baseline** (Phase 42-02): Expanding-window re-optimization deliberately deferred; clean OOS metrics established for V1 selection; re-opt can be added as incremental enhancement
- **Min-max normalization for composite score** (Phase 42-03): Min-max over z-score — interpretable [0,1] range, no distributional assumption; handles small N (3-10 strategies); max_drawdown_worst (single worst fold) not mean — worst fold is what kills live accounts
- **V1 gates flag but don't eliminate** (Phase 42-03): All strategies receive composite scores regardless of gate failures; gate_failures documented in output; allows selecting "best available" when no strategy meets both gates
- **ema_trend(17,77) robust top-1 in 4/4 schemes** (Phase 42-03): Consistently ranks #1 under balanced, risk_focus, quality_focus, and low_cost schemes; ema_trend(21,50) robust top-2 in 3/4; both fail MaxDD gate (-70-75%)
- **Robust threshold 3/4 weighting schemes** (Phase 42-03): Strategy is "robust" if top-2 in >= 3 of 4 schemes; 3/4 means "mostly consistent ranking" allowing one outlier scheme; 4/4 too strict, 2/4 too loose
- **Two EMA strategies selected for V1** (Phase 42-04): ema_trend(17,77) robust top-1 in 4/4 schemes; ema_trend(21,50) robust top-2 in 3/4; both fail MaxDD gate (70-75% worst-fold drawdown is structural crypto bear market risk)
- **Scorecard in gitignored reports/** (Phase 42-05): BAKEOFF_SCORECARD.md lives in reports/bakeoff/ (gitignored); generate_bakeoff_scorecard.py committed as reproducibility artifact; all Phase 42 report outputs (CSVs, MDs) follow same pattern
- **HTML charts as primary format** (Phase 42-05): kaleido not installed; Plotly charts exported as .html; script auto-upgrades to PNG when kaleido installed (no code change needed)
- **parents[4] for scripts/analysis/ depth** (Phase 42-05): Path(__file__).resolve().parents[4] is correct for project root from scripts/analysis/ (not parents[5] which reaches Downloads/)
- **Ensemble blend fails too** (Phase 42-04): Majority-vote blend of both EMA strategies also fails V1 gates — both lose during same macro bear market regimes (2018, 2022); blending reduces Sharpe while barely improving MaxDD
- **V1 deployment with reduced sizing** (Phase 42-04): Deploy at 10% position fraction (not 50% from backtest) + circuit breaker at 15% portfolio DD due to V1 MaxDD gate failure; Phase 45 must implement circuit breakers
- **Full-sample vs OOS consistency** (Phase 42-04): Full-sample Sharpe (1.647, 1.705) > OOS mean (1.401, 1.397) but within 1 std — OOS walk-forward is conservative (expected), not overfitting evidence
- **down_revision = actual head, not plan spec** (Phase 43-01): Plan spec listed 8d5bc7ee1732 as expected down_revision but actual head was e74f5622e710 (strategy_bakeoff_results from Phase 42-02); always run alembic history to verify before setting down_revision
- **ExchangeConfig NOT frozen** (Phase 43-01): Mutable dataclass allows environment switching at runtime without object recreation; from_env_file classmethod uses manual dotenv parser (no python-dotenv dependency)
- **paper_orders.status includes Phase 44 states** (Phase 43-01): CHECK constraint includes pending/filled/cancelled/rejected now to avoid ALTER TABLE in Phase 44; current Phase 43 only uses 'paper'

### Pending Todos

None yet.

### Blockers/Concerns

| Priority | Item | Status | Action |
|----------|------|--------|--------|
| Medium | V1 gate MaxDD failure: no strategy (including ensemble) passes MaxDD <= 15% | Documented | Select top-2 anyway per plan; deploy with reduced sizing + circuit breakers; update V1 validation criteria in Phase 53 |

## Session Continuity

Last session: 2026-02-25T03:38:00Z
Stopped at: Completed 43-01-PLAN.md — ExchangeConfig dataclass; Alembic migration b180d8d07a85 (exchange_price_feed + paper_orders); reference DDL.
Resume file: None

---

## Milestone Context

**v0.8.0 Polish & Hardening — SHIPPED 2026-02-23**

See `.planning/milestones/v0.8.0-ROADMAP.md` for archived details.

**v0.9.0 Research & Experimentation — SHIPPED 2026-02-24**

Roadmap created 2026-02-23. 6 phases, 35 requirements.

Phase overview:
- Phase 35 (AMA Engine): COMPLETE — KAMA, DEMA, TEMA, HMA indicator family with params_hash PK; 6 AMA table variants + _u; orchestrator + daily refresh integration
- Phase 36 (PSR + Purged K-Fold): COMPLETE — Alembic migrations (psr_legacy rename + psr_results table), PSR/DSR/MinTRL formulas (Pearson kurtosis), PurgedKFoldSplitter + CPCVSplitter, PSR pipeline integration + CLI, alembic startup check; 22/22 must-haves verified
- Phase 37 (IC Evaluation): COMPLETE — Spearman IC library (1098 lines), regime breakdown, batch wrapper, Plotly plots, DB helpers, run_ic_eval.py CLI, cmc_ic_results Alembic migration; 5/5 must-haves verified, 61 tests
- Phase 38 (Feature Experimentation): COMPLETE — YAML feature registry, FeatureRegistry+DAG, ExperimentRunner, FeaturePromoter (BH gate + migration stub), 3 CLIs, 39 unit tests
- Phase 39 (Streamlit Dashboard): COMPLETE — DB layer, cached queries, charts.py, landing page, pipeline monitor (traffic light + stats grid + coverage pivot + alert history), research explorer (IC table, IC decay chart, regime timeline)
- Phase 40 (Notebooks): COMPLETE — helpers.py (6 functions), 01_explore_indicators.ipynb (29 cells, AMA + regimes), 02_evaluate_features.ipynb (44 cells, IC + purged K-fold + regime A/B), 03_run_experiments.ipynb (33 cells, feature registry + DAG + experiments + dashboard); 13/13 must-haves verified
- Phase 41 (Asset Descriptive Stats & Correlation): COMPLETE — Alembic migration (5 DB objects), refresh_cmc_asset_stats.py (8 stats x 4 windows), refresh_cmc_cross_asset_corr.py (Pearson+Spearman pairwise), orchestrator + pipeline wiring, dashboard page (stats table + correlation heatmap), regime integration + quality checks; 6/6 must-haves verified
- Phase 41.1 (Milestone Cleanup): COMPLETE — AMA tables in ExperimentRunner _ALLOWED_TABLES + filter support, 2 AMA YAML features, experiments dashboard page, stale CLI ref fix, rolling IC chart, fold_boundaries public API; 11/11 must-haves verified

Key constraints to remember:
- PSR-01 (Alembic migration psr->psr_legacy) must run before any PSR formula code
- IC functions require train_start/train_end — no exceptions
- PurgedKFold requires t1_series — implement from scratch
- BH correction is a hard gate, not advisory
- Phases 35 and 36 have no inter-dependency (can plan/execute in either order)
- Phase 38 depends on Phase 37 (IC is the scoring engine for ExperimentRunner)

---
*Created: 2025-01-22*
*Last updated: 2026-02-24 (v0.9.0 SHIPPED — milestone archived, v1.0.0 activated)*
