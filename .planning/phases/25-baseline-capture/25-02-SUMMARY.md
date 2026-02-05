---
phase: 25-baseline-capture
plan: 02
type: execute
subsystem: baseline-validation
tags: [baseline, orchestration, snapshot, truncate, rebuild, compare, subprocess, phase23-patterns]

requires:
  - phases: [25-baseline-capture-01]
    reason: "Uses comparison_utils (hybrid tolerance) and metadata_tracker (audit trail) from Plan 01"
  - phases: [23-reliable-incremental-refresh]
    reason: "Follows Phase 23 orchestration patterns (subprocess isolation, dry-run, verbose, summary reporting)"

provides:
  - artifact: sql/baseline/snapshot_template.sql
    purpose: "Template documenting snapshot naming convention for all 12 tables (6 bar + 6 EMA)"
  - artifact: src/ta_lab2/scripts/baseline/capture_baseline.py
    purpose: "Main orchestration script implementing Snapshot -> Truncate -> Rebuild -> Compare workflow"
    exports: [main, create_snapshots, truncate_tables, run_bar_builders, run_ema_refreshers, compare_all_tables, generate_report]

affects:
  - phases: [26-validation]
    reason: "Phase 26 will use this script to validate refactoring correctness"

tech-stack:
  added: []
  patterns:
    - name: "Snapshot -> Truncate -> Rebuild -> Compare workflow"
      description: "Atomic validation pattern: capture current state, wipe clean, rebuild from scratch, compare outputs"
    - name: "Intelligent sampling (beginning/end/random)"
      description: "Sample first N days (drift detection), last N days (recent data), random interior (coverage) - reduces comparison time while maintaining confidence"
    - name: "Never fail early pattern"
      description: "Always run to completion, report ALL issues - partial results hide problems"
    - name: "Phase 23 subprocess isolation"
      description: "Run bar builders and EMA refreshers via subprocess.run for process isolation, matching run_daily_refresh.py pattern"

key-files:
  created:
    - path: sql/baseline/snapshot_template.sql
      loc: 40
      purpose: "Template documenting snapshot naming convention"
    - path: src/ta_lab2/scripts/baseline/capture_baseline.py
      loc: 1067
      purpose: "Main orchestration script for baseline capture"
  modified: []

decisions:
  - id: D25-02-001
    decision: "Integrated sampling utilities into main script (not separate module)"
    rationale: "Sampling is tightly coupled to comparison workflow - no reuse anticipated outside capture_baseline.py, simpler to maintain in single file"
    impact: "Cleaner architecture, easier to understand workflow, no artificial module boundary"
    alternatives: ["Create separate sampling_utils.py module"]

  - id: D25-02-002
    decision: "Subprocess isolation for bar and EMA builders (Phase 23 pattern)"
    rationale: "Follows established pattern from run_daily_refresh.py - subprocess.run provides process isolation, error handling, and clean separation of concerns"
    impact: "Consistent with existing orchestration scripts, predictable behavior, clear error boundaries"
    alternatives: ["Import and call directly (runpy pattern from older code)"]

  - id: D25-02-003
    decision: "All 12 tables in scope (6 bar + 6 EMA) - no filtering"
    rationale: "Phase 21 documented all 6 EMA variants as legitimate (80%+ shared infrastructure, 20% intentional differences) - must validate all variants to detect drift"
    impact: "Complete validation coverage, proves refactoring correctness for entire system"
    alternatives: ["Validate only primary tables (multi_tf, v2)", "Let user choose tables via CLI"]

  - id: D25-02-004
    decision: "Primary keys on snapshot tables for efficient comparison"
    rationale: "Merge operations require indexed keys - without PKs, comparison queries become full table scans (O(n²) complexity)"
    impact: "Comparison performance scales linearly instead of quadratically, enables larger sample sizes"
    alternatives: ["No indexes (slower)", "Create indexes instead of constraints"]

  - id: D25-02-005
    decision: "Default sampling: 30 days beginning + 30 days end + 5% random interior"
    rationale: "Beginning/end capture drift over time (most common failure mode), random interior provides coverage - 25-RESEARCH.md Pattern 3"
    impact: "Fast comparison (~5-10% of total data) while maintaining high confidence in correctness"
    alternatives: ["Full table comparison (too slow)", "Random sample only (misses temporal drift)"]

metrics:
  duration: "5 min"
  completed: 2026-02-05
  tasks_completed: 3
  tasks_total: 3
  files_created: 2
  files_modified: 0
  loc_added: 1107
  commits: 2

commits:
  - hash: 75cf9ef1
    message: "feat(25-02): create SQL snapshot template"
  - hash: 9e603d68
    message: "feat(25-02): create baseline capture orchestration script"
---

# Phase 25 Plan 02: Orchestration Script Summary

**One-liner:** Created capture_baseline.py orchestrator implementing Snapshot -> Truncate -> Rebuild -> Compare workflow with intelligent sampling and Phase 23 subprocess patterns.

## What Was Built

### 1. SQL Snapshot Template (`snapshot_template.sql`)
- Documents snapshot naming convention: `{table}_snapshot_{YYYYMMDD_HHMMSS}`
- Lists all 12 tables to snapshot (6 bar + 6 EMA)
- Shows CREATE TABLE AS SELECT pattern
- Documents primary key pattern for efficient comparison

### 2. Main Orchestration Script (`capture_baseline.py`)

**Five-phase workflow:**

1. **Phase 1: Snapshot** - Create timestamped snapshots of all 12 tables with primary keys
2. **Phase 2: Truncate** - Clear all tables to prepare for rebuild (with verification)
3. **Phase 3: Rebuild** - Run bar builders then EMA refreshers via subprocess
4. **Phase 4: Compare** - Intelligent sampling comparison (beginning/end/random)
5. **Phase 5: Report** - Comprehensive report with pass/fail, severity, statistics

**Key features:**

- **CLI interface**: `--ids`, `--dry-run`, `--verbose`, `--skip-rebuild`, `--sample-*` options
- **Subprocess isolation**: Follows Phase 23 pattern (run_daily_refresh.py style)
- **Never fails early**: Always runs to completion, reports ALL issues
- **Intelligent sampling**: 30 days beginning + 30 days end + 5% random interior (configurable)
- **Hybrid tolerance comparison**: Uses comparison_utils from Plan 01 (NumPy allclose)
- **Git-based audit trail**: Uses metadata_tracker from Plan 01

## Design Patterns Applied

### Pattern 1: Snapshot -> Truncate -> Rebuild -> Compare
```
Baseline (before refactoring) → Snapshot → Truncate → Rebuild → Compare
                                   ↓          ↓          ↓         ↓
                              Timestamped  Empty      Fresh    Epsilon
                              snapshot     tables     data     tolerance
```

**Why:** Atomic validation - proves refactoring correctness by comparing identical input → output transformations.

### Pattern 2: Intelligent Sampling (RESEARCH.md Pattern 3)
```python
# Beginning sample (first 30 days) - detects drift
SELECT * FROM table WHERE ts <= MIN(ts) + INTERVAL '30 days'

# End sample (last 30 days) - verifies recent data
SELECT * FROM table WHERE ts >= MAX(ts) - INTERVAL '30 days'

# Random interior (5%) - provides coverage
SELECT * FROM table WHERE random() < 0.05
  AND ts > MIN(ts) + 30 days
  AND ts < MAX(ts) - 30 days
```

**Why:** Full table comparison too slow (millions of rows), random-only sampling misses temporal drift. Combined approach balances speed and confidence.

### Pattern 3: Phase 23 Subprocess Isolation
```python
# Bar builders
cmd = [sys.executable, "run_all_bar_builders.py", "--ids", ids, "--full-rebuild"]
result = subprocess.run(cmd, check=False, capture_output=True, text=True)

# EMA refreshers
cmd = [sys.executable, "run_all_ema_refreshes.py", "--ids", ids]
result = subprocess.run(cmd, check=False, capture_output=True, text=True)
```

**Why:** Process isolation prevents state leakage, clear error boundaries, matches existing orchestration patterns (run_daily_refresh.py).

### Pattern 4: Never Fail Early
```python
# Snapshot phase - track failures, continue
for table in all_tables:
    try:
        create_snapshot(table)
    except Exception as e:
        print(f"[ERROR] {e}")
        # Continue to next table

# Compare phase - collect ALL mismatches
for table in all_tables:
    result = compare_tables(...)
    summaries.append(result)  # Never break early

# Report phase - show ALL issues
print_report(summaries)  # Complete picture
```

**Why:** CONTEXT.md requirement "always run to completion, report only" - partial results hide systemic issues.

## Key Decisions

1. **Integrated sampling into main script**: No separate module - sampling tightly coupled to comparison workflow
2. **Subprocess isolation (Phase 23 pattern)**: Matches run_daily_refresh.py for consistency
3. **All 12 tables in scope**: Validates all 6 EMA variants (Phase 21 finding: all legitimate)
4. **Primary keys on snapshots**: Enables efficient merge operations (O(n) vs O(n²))
5. **Default 30/30/5% sampling**: Balances speed and confidence (RESEARCH.md Pattern 3)

## CLI Usage Examples

```bash
# Full workflow for specific IDs
python capture_baseline.py --ids 1,52,825

# Full workflow for all IDs
python capture_baseline.py --ids all

# Dry run to see commands
python capture_baseline.py --ids 1 --dry-run

# Skip rebuild, only snapshot + compare
python capture_baseline.py --ids all --skip-rebuild

# Verbose output from subprocesses
python capture_baseline.py --ids all --verbose

# Custom sampling parameters
python capture_baseline.py --ids all --sample-beginning 60 --sample-end 60 --sample-random-pct 0.10
```

## Verification Results

All verification checks passed:

1. ✅ `python capture_baseline.py --help` shows CLI options
2. ✅ `--dry-run --ids 1` shows complete workflow (snapshot/truncate/rebuild/compare)
3. ✅ All imports work: `from ta_lab2.scripts.baseline.capture_baseline import main`
4. ✅ SQL template exists: `sql/baseline/snapshot_template.sql`
5. ✅ Template lists all 12 tables: 19 references to "cmc_" tables

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `sql/baseline/snapshot_template.sql` | 40 | Template documenting snapshot naming convention |
| `src/ta_lab2/scripts/baseline/capture_baseline.py` | 1067 | Main orchestration script for baseline capture |
| **Total** | **1107** | **2 files created** |

## Deviations from Plan

None - plan executed exactly as written.

Task 3 (sampling utilities) was integrated into Task 2 (main script) as planned - the plan specified "Add functions" to capture_baseline.py, which was accomplished.

## Next Phase Readiness

**Ready for Phase 26 (Validation):**

✅ `capture_baseline.py` script ready to use for validation testing
✅ Follows Phase 23 patterns (subprocess isolation, dry-run, verbose, summary reporting)
✅ Uses Plan 01 utilities (comparison_utils, metadata_tracker)
✅ All 12 tables handled (6 bar + 6 EMA)
✅ Intelligent sampling reduces comparison time
✅ Never fails early - comprehensive reporting

**No blockers or concerns.**

## Technical Highlights

### Intelligent Sampling Strategy

Default configuration samples ~5-10% of data while maintaining high confidence:

- **Beginning 30 days**: Detects drift over time (first calculation vs later calculations)
- **End 30 days**: Verifies recent data (most likely to be affected by recent changes)
- **Random 5% interior**: Provides general coverage without overwhelming comparison

Example for 5-year dataset (1825 days):
- Beginning sample: 30 days = ~500 rows per ID
- End sample: 30 days = ~500 rows per ID
- Random sample: 1765 * 0.05 = ~88 rows per ID
- Total: ~1088 rows per ID (~6% of total)

### Subprocess Isolation Benefits

Following Phase 23 pattern provides:

1. **Process isolation**: Bar builder errors don't affect EMA refreshers
2. **Clean error boundaries**: Returncode 0 = success, non-zero = failure
3. **Output control**: `--verbose` streams output, default captures for error reporting
4. **Consistency**: Matches run_daily_refresh.py, run_all_bar_builders.py patterns

### Primary Key Performance

Without PKs, merge operations are O(n²):
```sql
-- No index: full table scan for each row
SELECT * FROM snapshot s
JOIN rebuilt r ON s.id = r.id AND s.tf = r.tf ...
-- Execution time: minutes to hours for large tables
```

With PKs, merge operations are O(n):
```sql
-- Index lookup: constant time per row
SELECT * FROM snapshot s
JOIN rebuilt r ON s.id = r.id AND s.tf = r.tf ...
-- Execution time: seconds for large tables
```

## References

- **Phase 25 CONTEXT.md**: User decisions on workflow, sampling, failure handling
- **Phase 25 RESEARCH.md**: Intelligent sampling Pattern 3, pitfalls
- **Phase 23 patterns**: Subprocess isolation, dry-run, verbose, summary reporting
- **Phase 21 documentation**: All 6 EMA variants are legitimate (not code duplication)
- **Plan 01 modules**: comparison_utils (hybrid tolerance), metadata_tracker (audit trail)

---

*Completed: 2026-02-05*
*Duration: 5 minutes*
*Commits: 75cf9ef1, 9e603d68*
