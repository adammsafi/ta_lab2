# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-23)

**Core value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Current focus:** v0.9.0 Research & Experimentation — Phase 36 in progress (PSR + Purged K-Fold)

## Current Position

Phase: 36 (PSR + Purged K-Fold) — In Progress
Plan: 03 of 6
Status: In progress — Plan 36-03 executed (PurgedKFoldSplitter + CPCVSplitter via TDD, 33 tests)
Last activity: 2026-02-24 — Completed 36-03-PLAN.md (leakage-free CV splitters)

Progress: [##########] 100% v0.4.0 | [##########] 100% v0.5.0 | [##########] 100% v0.6.0 | [##########] 100% v0.7.0 | [##########] 100% v0.8.0 | [████████░░] ~57% v0.9.0

## Performance Metrics

**Velocity:**
- Total plans completed: 176 (56 in v0.4.0, 56 in v0.5.0, 30 in v0.6.0, 10 in v0.7.0, 13 in v0.8.0, 1 in Phase 34 audit cleanup, 8 in Phase 35, 2 in Phase 36)
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
| 36-psr-purged-k-fold | 2/6 | ~8 min | ~4 min | In Progress |

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

### Pending Todos

None yet.

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-02-24T00:07Z
Stopped at: Phase 36 Plan 03 complete — PurgedKFoldSplitter + CPCVSplitter, 33 tests all passing
Resume file: None

---

## Milestone Context

**v0.8.0 Polish & Hardening — SHIPPED 2026-02-23**

See `.planning/milestones/v0.8.0-ROADMAP.md` for archived details.

**v0.9.0 Research & Experimentation — In Progress**

Roadmap created 2026-02-23. 6 phases, 35 requirements.

Phase overview:
- Phase 35 (AMA Engine): COMPLETE — KAMA, DEMA, TEMA, HMA indicator family with params_hash PK; 6 AMA table variants + _u; orchestrator + daily refresh integration
- Phase 36 (PSR + Purged K-Fold): IN PROGRESS (1/6) — PSR schema migrations done (psr_column_rename + psr_results_table); PSR formula code next
- Phase 37 (IC Evaluation): Feature scoring — Spearman IC, rolling IC, IC decay, regime breakdown, significance
- Phase 38 (Feature Experimentation): Registry + ExperimentRunner + BH-corrected promotion gate
- Phase 39 (Streamlit Dashboard): Pipeline Monitor + Research Explorer, NullPool, Windows-compatible
- Phase 40 (Notebooks): 3-5 polished, Restart-and-Run-All clean, shareable

Key constraints to remember:
- PSR-01 (Alembic migration psr->psr_legacy) must run before any PSR formula code
- IC functions require train_start/train_end — no exceptions
- PurgedKFold requires t1_series — implement from scratch
- BH correction is a hard gate, not advisory
- Phases 35 and 36 have no inter-dependency (can plan/execute in either order)
- Phase 38 depends on Phase 37 (IC is the scoring engine for ExperimentRunner)

---
*Created: 2025-01-22*
*Last updated: 2026-02-23 (Phase 36 Plan 01 complete — PSR schema migrations; continuing with PSR formula code)*
