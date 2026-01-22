# Codebase Concerns

**Analysis Date:** 2026-01-21

## Tech Debt

**Massive "old" directories with duplicate legacy code:**
- Issue: Multiple `old/` and `older-asof_/` directories containing hundreds of lines of deprecated scripts that duplicate active code, making maintenance burden unclear
- Files affected:
  - `src/ta_lab2/features/m_tf/old/` (10+ old EMA variant files)
  - `src/ta_lab2/scripts/bars/old/` (15+ old bar refresh scripts)
  - `src/ta_lab2/scripts/emas/old/` (10+ old EMA refresh scripts)
  - `src/ta_lab2/scripts/emas/stats/multi_tf/old/` (3+ old stats scripts)
  - `src/ta_lab2/scripts/emas/stats/multi_tf_cal/old/` (3+ old stats scripts)
  - `src/ta_lab2/scripts/emas/stats/multi_tf_cal_anchor/old/` (3+ old stats scripts)
  - `src/ta_lab2/scripts/emas/stats/multi_tf_v2/old/` (3+ old stats scripts)
- Impact: Codebase is bloated (77k+ lines in src alone), new developers confused about which is current version, search and refactoring tools need to filter noise
- Fix approach: Archive all old files to git history, delete directories entirely, or move to separate `archive/` folder outside src path

**Hardcoded user paths in active source files:**
- Issue: Several production scripts embed Windows user paths (`C:/Users/asafi/`, `C:/Users/Adam/`)
- Files affected:
  - `src/ta_lab2/regimes/old_run_btc_pipeline.py:13` (sys.path.append with hardcoded path)
  - `src/ta_lab2/regimes/old_run_btc_pipeline.py:59` (CSV path hardcoded)
  - `src/ta_lab2/scripts/etl/update_cmc_history.py:7` (source_file hardcoded to Adam's Downloads)
  - `src/ta_lab2/scripts/prices/run_refresh_price_histories7_stats.py:18` (REPO_ROOT hardcoded)
  - Multiple docstring examples with hardcoded paths
- Impact: Scripts will fail on other machines or environments; makes Docker/CI deployment impossible; security risk (reveals usernames)
- Fix approach: Use `_find_repo_root()` pattern from `dbtool.py` throughout, or environment variable override, never embed absolute paths in source

**Duplicate import statements:**
- Issue: `src/ta_lab2/tools/dbtool.py` imports `json` twice (lines 5 and 13)
- Files affected: `src/ta_lab2/tools/dbtool.py`
- Impact: Code smell, wasted parsing, subtle sign of manual editing/merges
- Fix approach: Remove duplicate import on line 13

**Large monolithic scripts (1400+ lines):**
- Issue: Multiple scripts exceed 1400 lines with complex nested logic, making them hard to test and maintain
- Files affected:
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py` (1469 lines)
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_us.py` (1447 lines)
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py` (1336 lines)
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_anchor_us.py` (1287 lines)
  - `src/ta_lab2/tools/dbtool.py` (1724 lines)
  - `src/ta_lab2/features/ema.py` (901 lines)
- Impact: Cognitive load, harder to unit test, increased risk of bugs in refactoring
- Fix approach: Extract concerns into smaller modules (`builders.py`, `validators.py`, `diagnostics.py`); consolidate dbtool into purpose-specific modules

**Missing subprocess stdin pipe implementation:**
- Issue: `src/ta_lab2/tools/ai_orchestrator/adapters.py:86` has TODO comment "Implement subprocess execution with stdin pipe"
- Files affected: `src/ta_lab2/tools/ai_orchestrator/adapters.py`
- Impact: Orchestrator adapter cannot pipe input to subprocess tasks; blocks full orchestration workflow
- Fix approach: Implement stdin pipe handling in subprocess execution wrapper

## Known Bugs

**Deprecated builder function still in codebase:**
- Issue: `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_us.py:795` marks `_build_snapshots_incremental_slow()` as DEPRECATED but function remains in code
- Files affected: `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_us.py`
- Trigger: Commented as "kept for reference/backward compatibility" but no evidence it's called
- Workaround: None needed (unused), but documents uncertainty about removal
- Fix approach: Remove deprecated function and any references, or rename to `_legacy_*` and isolate to compatibility layer

**Test file with hash prefix (will be skipped by pytest):**
- Issue: `tests/# test_bar_ohlc_correctness_fast.py` has `#` prefix in filename, making it invisible to test runners
- Files affected: `tests/# test_bar_ohlc_correctness_fast.py`
- Trigger: Pytest discovery ignores files starting with `#`
- Workaround: Run tests explicitly by full path
- Fix approach: Rename to `tests/test_bar_ohlc_correctness_fast.py` (remove leading `#`)

## Security Considerations

**Weak database URL handling in edge cases:**
- Risk: `dbtool.py` and scripts normalize psycopg URLs but fallback pattern may accept malformed URLs without strict validation
- Files affected: `src/ta_lab2/tools/dbtool.py:59-67` (`_normalize_db_url`), `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (similar patterns)
- Current mitigation: SQLAlchemy provides some validation, but manual URL parsing is fragile
- Recommendations:
  - Use `urllib.parse` for URL validation instead of string replacement
  - Add unit tests for malformed URL rejection
  - Consider using connection string validator library

**Insufficient input validation on snapshot data:**
- Risk: `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py` and related audits load CSV/JSON snapshots without size limits
- Files affected: `src/ta_lab2/tools/dbtool.py:1528` (reads entire file into memory), `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py` (loads all snapshots)
- Current mitigation: None observed
- Recommendations:
  - Add file size checks before loading snapshots
  - Stream large files instead of loading entirely into memory
  - Add timeout on snapshot JSON parsing

**Hard-coded values in database operations:**
- Risk: Some SQL building code uses parametrized queries correctly but audit scripts concatenate table/schema names without validation
- Files affected: `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py` (dynamic table selection), `src/ta_lab2/tools/dbtool.py` (schema introspection)
- Current mitigation: Whitelist `BAR_TABLES` and controlled schema names
- Recommendations:
  - Formalize whitelist validation for table/schema names
  - Add unit tests validating SQL injection attempts are rejected

## Performance Bottlenecks

**Multiprocessing Pool without timeout protection:**
- Problem: `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py:1318` and similar scripts use `Pool` without `timeout` parameter, risking hung worker processes
- Files affected:
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py:1318`
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_us.py:1315`
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_iso.py:1156`
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_anchor_us.py:1161`
  - `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py:1208`
  - `src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py:156`
- Cause: Long-running I/O operations (database queries) in worker processes can block indefinitely if connection fails
- Improvement path:
  - Add `timeout` parameter to `pool.map()` calls (suggest 300 seconds)
  - Implement watchdog timer in worker functions to detect hung processes
  - Add per-worker logging to track progress and timeouts

**No connection pooling in database operations:**
- Problem: Scripts create new engine/connection per call, repeatedly establishing PostgreSQL TCP connections
- Files affected: Throughout `refresh_*.py` scripts and audit scripts (every function calls `get_engine(db_url)`)
- Cause: `create_engine()` called multiple times in single script run; each Pool worker creates fresh connections
- Improvement path:
  - Create single global engine at script start, reuse across calls
  - Use connection pooling with `poolclass=QueuePool` in SQLAlchemy
  - Set appropriate pool size for expected worker count

**Memory inefficiency in full dataset loads:**
- Problem: `src/ta_lab2/tools/dbtool.py:1528` and audit scripts load entire snapshots into memory before processing
- Files affected:
  - `src/ta_lab2/tools/dbtool.py` (snapshot check/diff commands)
  - `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py` (loads all bar snapshots into dataframe)
  - `src/ta_lab2/scripts/emas/audit_ema_integrity.py` (similar pattern)
- Cause: No streaming/chunking; JSON/CSV files loaded entirely with `.read_text()` or pandas `read_sql`
- Improvement path:
  - Implement chunked/streaming reads for large snapshots (>100MB)
  - Use `chunksize` parameter in `pd.read_sql()` for table reads
  - Stream JSON parsing instead of full load-then-parse

**No row limit enforcement in diagnostic queries:**
- Problem: Audit scripts (e.g., `audit_price_bars_integrity.py`) query tables without LIMIT, risking full table scan on billions of rows
- Files affected: `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py`, `src/ta_lab2/scripts/emas/audit_ema_integrity.py`
- Cause: Diagnostic queries designed to count/check all data, but no progress indication or sampling fallback
- Improvement path:
  - Add `--max-rows` parameter to audit scripts with sensible default (100k)
  - Implement progress bar with `tqdm` for long-running queries
  - Add sampling mode: audit random N rows instead of all rows

## Fragile Areas

**Bar snapshot calculation with complex tie-breaking logic:**
- Files affected: `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (lines 75-150 for `compute_time_high_low`)
- Why fragile: Tie-breaking for earliest timestamp among high/low extrema uses conditional logic across multiple columns (`timehigh`, `timelow`, `ts`), with fallback rules. Any change to data schema (e.g., new timestamp column) breaks logic.
- Safe modification:
  - Add comprehensive docstring examples showing all edge cases (tied extrema, missing timehigh/timelow, NaT values)
  - Add unit tests for: all tied rows, partial ties, mixed null/non-null timestamps
  - Extract tie-breaking into separate, well-tested function
  - Add data validation before calling (assert all ts are not NaT)
- Test coverage gaps: No unit tests found for `compute_time_high_low()` with edge cases

**OHLC sanity enforcement with multiple correction rules:**
- Files affected: `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (lines 280-330 for `enforce_ohlc_sanity`)
- Why fragile: Applies cascading corrections (high -> high>=max(o,c), low -> low<=min(o,c), then time_low/time_open conditional logic). If applied out of order or incompletely, can produce invalid bars.
- Safe modification:
  - Add detailed comments explaining correction order (must enforce high first, then low, then time fields)
  - Add assertions after each step verifying invariant holds (e.g., assert high >= max(open, close))
  - Extract each correction step into separate function with its own tests
  - Add before/after logging for debugging
- Test coverage gaps: Tests exist but no coverage for cascading correction order or multi-step edge cases

**State table upsert logic with timezone sensitivity:**
- Files affected: `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (lines 496-575 for `upsert_state`)
- Why fragile: Upsert logic conditionally includes `tz` column based on `with_tz` parameter, which changes PRIMARY KEY semantics if mismatched
- Safe modification:
  - Add explicit type hints for payload structure
  - Add validation that PRIMARY KEY (`id`, `tf`) matches conflict target in SQL
  - Add test matrices covering both `with_tz=True/False` paths
  - Document when to use `with_tz=True` (answer: only for cal_anchor variant)
- Test coverage gaps: Tests exist but may not cover both tz paths fully

**Carry-forward optimization with strict gate conditions:**
- Files affected: `src/ta_lab2/scripts/bars/common_snapshot_contract.py` (lines 320-380)
- Why fragile: `can_carry_forward()` uses strict conditions (bar alignment, daily boundaries) to allow O(1) updates instead of full rebuild. If any condition is miscalculated, produces silently incorrect data.
- Safe modification:
  - Add exhaustive comments explaining each gate condition and its safety reasoning
  - Add detailed error messages when carry-forward is rejected
  - Add optional `--force-carry-forward` flag for testing with logging
  - Add field-by-field validation after carry-forward applied
- Test coverage gaps: No unit tests found for carry-forward edge cases or gate condition failures

## Scaling Limits

**Database connection exhaustion with multiprocessing:**
- Current capacity: Typical PostgreSQL allows ~100 connections by default; scripts use `maxtasksperchild=50` per worker
- Limit: With 8 workers × 50 tasks = 400 potential connections, will exceed default pool
- Scaling path:
  - Implement connection pooling at script entry, reuse across workers
  - Reduce `maxtasksperchild` proportionally with worker count
  - Add `--num-processes` auto-tuning based on available connections

**In-memory dataframe limits on large datasets:**
- Current capacity: Can load ~10GB dataframes on systems with 64GB RAM; daily price data grows continuously
- Limit: `refresh_*.py` scripts load entire ID's price history into memory before building bars
- Scaling path:
  - Implement chunked processing by date range, not by ID
  - Use Polars lazy execution to avoid materializing intermediate dataframes
  - Stream bar snapshots directly to database instead of buffering

**Snapshot table growth without partitioning:**
- Current capacity: Tables like `cmc_price_bars_multi_tf` grow ~1-2M rows per month
- Limit: After ~3-5 years, queries and upserts become slow without time-based partitioning
- Scaling path:
  - Add monthly/quarterly partitions on `time_close` column
  - Implement partition pruning in upsert queries
  - Add partition management (auto-create future, drop old)

**Single-database design with no read replicas:**
- Current capacity: All reads/writes go to single PostgreSQL instance
- Limit: Audit scripts doing full table scans block incremental refresh operations
- Scaling path:
  - Add read-only replica for audit/diagnostic queries
  - Implement query routing (reads -> replica, writes -> primary)
  - Set audit scripts to use replica URL with higher timeouts

## Dependencies at Risk

**Psycopg version uncertainty:**
- Risk: Code maintains compatibility with both psycopg v2 and v3, adding conditional logic throughout
- Files affected:
  - `src/ta_lab2/tools/dbtool.py:17-29` (version detection)
  - `tests/test_bar_contract.py:10-22` (similar version detection)
- Impact: Maintenance burden; both versions will eventually EOL; version mismatch causes subtle bugs
- Migration plan:
  - Set minimum requirement to psycopg>=3.1
  - Remove all psycopg2 compatibility code
  - Update any psycopg2-only SQL syntax to psycopg3 style

**Polars vs Pandas inconsistency:**
- Risk: Some scripts use Polars for performance (`refresh_*.py`), others use pandas, no consistent choice
- Files affected: Mixed usage across bar/EMA refresh scripts
- Impact: Code duplication; developers confused which library to use; different error handling patterns
- Migration plan:
  - Standardize on Polars for new code (faster, more efficient)
  - Mark pandas usage as legacy with deprecation notices
  - Create helper module with unified API for both (pandas wrapping Polars internally)

## Missing Critical Features

**No retry logic for transient database failures:**
- Problem: Scripts fail completely if single database query times out or connection drops mid-operation
- Blocks: High-reliability batch operations; production deployments; long-running audits
- Fix approach:
  - Add `tenacity` or similar retry decorator to database calls
  - Implement exponential backoff (1s, 2s, 4s, 8s max)
  - Make retries configurable via CLI flags

**No incremental state recovery from partial failures:**
- Problem: If multiprocessing job fails halfway through (e.g., worker crash), entire job must restart; no resumption point
- Blocks: Running long batch jobs on unstable infrastructure
- Fix approach:
  - Save processed ID list to temporary state file
  - Check for resume file at startup
  - Allow `--resume` flag to skip already-processed IDs

**No dry-run mode for destructive operations:**
- Problem: Scripts delete entire tables (e.g., `delete_bars_for_id_tf()`) without preview or undo
- Blocks: Safe testing; prevents accidental data loss
- Fix approach:
  - Add `--dry-run` flag to all refresh scripts
  - In dry-run, log what would be deleted without actually deleting
  - Print row counts of affected data before deletion

## Test Coverage Gaps

**No tests for multiprocessing failure scenarios:**
- What's not tested: Worker crash, database connection loss during pool execution, out-of-memory in worker
- Files affected: All `refresh_*.py` scripts that use `Pool()`
- Risk: Failure modes not discovered until production; users don't know if partial data was written
- Priority: High
- Suggested approach:
  - Add integration tests with intentional worker failures
  - Mock database to return errors in middle of job
  - Verify state table is consistent after partial failure

**No tests for snapshot data edge cases:**
- What's not tested: Missing columns, NaN/NaT values in unexpected places, duplicate timestamps, gap in bar_seq
- Files affected: `src/ta_lab2/scripts/bars/common_snapshot_contract.py`
- Risk: Data corruption not caught; users get invalid bars silently
- Priority: High
- Suggested approach:
  - Create fixture factory for malformed snapshot data
  - Add parametrized tests for each edge case
  - Test all code paths in `assert_one_row_per_local_day()`, `compute_time_high_low()`, `enforce_ohlc_sanity()`

**No end-to-end tests for full refresh pipeline:**
- What's not tested: Full flow from daily prices -> bars -> EMAs with multiple IDs, multiple timeframes
- Files affected: `src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py`
- Risk: Integration issues not discovered (e.g., EMA expecting bar schema that changed)
- Priority: Medium
- Suggested approach:
  - Create test database with known daily prices
  - Run full pipeline, verify final EMAs are correct
  - Add performance regression test (should complete in < X minutes)

**Incomplete audit script test coverage:**
- What's not tested: Audit integrity, duplicate detection, spacing validation
- Files affected: `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py`, `src/ta_lab2/scripts/emas/audit_ema_integrity.py`
- Risk: Audits miss real problems; users don't know data is corrupt
- Priority: Medium
- Suggested approach:
  - Create test snapshots with known issues (duplicates, gaps)
  - Run audits, verify issues detected and reported
  - Test all audit output CSV columns

---

*Concerns audit: 2026-01-21*
