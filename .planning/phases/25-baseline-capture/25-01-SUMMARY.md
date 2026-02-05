---
phase: 25-baseline-capture
plan: 01
type: execute
subsystem: baseline-validation
tags: [baseline, comparison, metadata, validation, numpy, epsilon-tolerance]

requires:
  - phases: [24-pattern-consistency]
    reason: "BaseBarBuilder pattern established, all 6 bar builders refactored"

provides:
  - artifact: sql/ddl/create_dim_assets.sql
    purpose: "DDL to create dim_assets table from dim_sessions WHERE asset_class = 'CRYPTO'"
  - artifact: sql/baseline/.gitkeep
    purpose: "Directory structure for baseline snapshot SQL files (Plan 02)"
  - artifact: src/ta_lab2/scripts/baseline/comparison_utils.py
    purpose: "Epsilon-aware comparison with NumPy allclose hybrid tolerance"
    exports: [compare_with_hybrid_tolerance, summarize_comparison, compare_tables, COLUMN_TOLERANCES]
  - artifact: src/ta_lab2/scripts/baseline/metadata_tracker.py
    purpose: "Audit trail capture (git hash, timestamp, config) for reproducibility"
    exports: [BaselineMetadata, BaselineConfig, capture_metadata, save_metadata]

affects:
  - phases: [25-baseline-capture-02]
    reason: "Plan 02 orchestration script will use these utilities"

tech-stack:
  added:
    - library: numpy.allclose
      purpose: "Hybrid tolerance floating-point comparison (rtol + atol)"
      version: "1.26+"
  patterns:
    - name: "Epsilon-aware comparison with hybrid bounds"
      description: "Combine absolute tolerance (small values) + relative tolerance (large values) for correct floating-point comparison"
      formula: "abs(baseline - rebuilt) <= max(rtol * max(abs(baseline), abs(rebuilt)), atol)"
    - name: "Column-specific tolerances"
      description: "Different epsilon values for price (1e-6/1e-5) vs volume (1e-2/1e-4) data types"
    - name: "NaN-aware comparison"
      description: "Treat NaN == NaN as match using equal_nan=True (Pitfall 1 from RESEARCH.md)"
    - name: "Comprehensive mismatch reporting"
      description: "Collect ALL mismatches (don't stop early) with severity levels (CRITICAL/WARNING/INFO)"
    - name: "Metadata capture for reproducibility"
      description: "Git commit hash + timestamp + config for full audit trail"

key-files:
  created:
    - path: sql/ddl/create_dim_assets.sql
      loc: 12
      purpose: "DDL to create dim_assets table (CRYPTO assets only)"
    - path: sql/baseline/.gitkeep
      loc: 0
      purpose: "Directory structure for snapshot SQL files"
    - path: src/ta_lab2/scripts/baseline/__init__.py
      loc: 32
      purpose: "Module exports for comparison and metadata utilities"
    - path: src/ta_lab2/scripts/baseline/comparison_utils.py
      loc: 309
      purpose: "Epsilon-aware comparison with hybrid tolerance"
    - path: src/ta_lab2/scripts/baseline/metadata_tracker.py
      loc: 221
      purpose: "Audit trail capture and serialization"
  modified: []

decisions:
  - id: D25-01-001
    decision: "Use NumPy allclose hybrid tolerance (rtol + atol) instead of simple epsilon"
    rationale: "Handles both small values near zero (atol) and large values (rtol) correctly - single epsilon threshold produces false positives/negatives"
    impact: "Correct comparison across price ranges from $0.0001 (altcoins) to $100,000 (BTC)"
    alternatives: ["Simple absolute epsilon", "Manual tolerance loops"]

  - id: D25-01-002
    decision: "Column-specific tolerances: price (1e-6/1e-5) vs volume (1e-2/1e-4)"
    rationale: "Volume has lower precision requirements than price data - using same tolerance for all columns causes false mismatches"
    impact: "Reduces false positive mismatch rate while maintaining strict price validation"
    alternatives: ["Single global tolerance", "Dynamic tolerance based on value ranges"]

  - id: D25-01-003
    decision: "NaN == NaN is match using equal_nan=True"
    rationale: "SQL NULL semantics (NULL != NULL) differs from pandas/NumPy - need explicit NaN handling to avoid false mismatches (RESEARCH.md Pitfall 1)"
    impact: "Correct handling of missing data (NULL timestamps, NaN prices) in comparison"
    alternatives: ["Treat NaN as mismatch", "Skip NaN rows"]

  - id: D25-01-004
    decision: "Comprehensive mismatch reporting with severity levels (CRITICAL/WARNING/INFO)"
    rationale: "CONTEXT.md specifies 'always run to completion, report only' - collect ALL mismatches for comprehensive analysis"
    impact: "Full visibility into comparison results, no hidden issues"
    alternatives: ["Stop on first mismatch", "Binary pass/fail only"]

  - id: D25-01-005
    decision: "Capture git commit hash + timestamp + config in BaselineMetadata"
    rationale: "Full reproducibility requires exact code version (git hash), execution time (timestamp), and configuration (assets, date range, epsilon)"
    impact: "Can reproduce baseline capture 3 months later for debugging"
    alternatives: ["Timestamp only", "Manual documentation"]

metrics:
  duration: "6 min"
  completed: 2026-02-05
  tasks_completed: 3
  tasks_total: 3
  files_created: 5
  files_modified: 0
  loc_added: 574
  commits: 2

commits:
  - hash: 2e63dfeb
    message: "feat(25-01): create dim_assets DDL and baseline directory"
  - hash: fdc9fbf2
    message: "feat(25-01): create baseline comparison and metadata modules"
---

# Phase 25 Plan 01: Baseline Capture Infrastructure Summary

**One-liner:** Created dim_assets DDL, epsilon-aware comparison with NumPy allclose hybrid tolerance, and metadata tracker for git-based audit trail.

## What Was Built

### 1. SQL Infrastructure
- **dim_assets DDL** (`sql/ddl/create_dim_assets.sql`): Creates table from `dim_sessions WHERE asset_class = 'CRYPTO'` for baseline capture scope
- **Baseline directory** (`sql/baseline/`): Directory structure for Plan 02's snapshot SQL files

### 2. Comparison Utilities (`comparison_utils.py`)
- **Hybrid tolerance comparison**: Combines absolute (atol) + relative (rtol) tolerance using NumPy allclose formula
- **Column-specific tolerances**: Different epsilon values for price (1e-6/1e-5) vs volume (1e-2/1e-4) data types
- **NaN-aware comparison**: Treats `NaN == NaN` as match using `equal_nan=True` (avoids SQL NULL semantics issues)
- **Comprehensive mismatch reporting**: Collects ALL mismatches with severity levels (CRITICAL >1%, WARNING >epsilon, INFO expected)
- **Functions**: `compare_with_hybrid_tolerance()`, `summarize_comparison()`, `compare_tables()`

### 3. Metadata Tracker (`metadata_tracker.py`)
- **Git audit trail**: Captures commit hash, branch, dirty status for exact code version tracking
- **Execution metadata**: ISO-8601 timestamp, asset count, date range, script versions
- **Database context**: Connection URL (password redacted), snapshot table suffix
- **Configuration**: Epsilon tolerances, sampling strategy
- **Functions**: `capture_metadata()`, `save_metadata()`

## Design Patterns Applied

### Pattern 1: Hybrid Tolerance (NumPy allclose)
```python
# Formula: abs(baseline - rebuilt) <= max(rtol * max(abs(baseline), abs(rebuilt)), atol)
COLUMN_TOLERANCES = {
    "open": {"atol": 1e-6, "rtol": 1e-5},   # Price: tight tolerance
    "volume": {"atol": 1e-2, "rtol": 1e-4},  # Volume: looser tolerance
}
```

**Why:** Single absolute epsilon fails for values near zero (false negatives) and large values (false positives). Hybrid tolerance handles both correctly.

### Pattern 2: NaN-Aware Comparison
```python
both_nan = np.isnan(baseline_vals) & np.isnan(rebuilt_vals)
within_tolerance = (abs_diff <= threshold) | both_nan
```

**Why:** SQL `NULL != NULL` semantics differs from pandas/NumPy. Explicit NaN handling prevents false mismatches on missing data.

### Pattern 3: Comprehensive Mismatch Reporting
```python
# Collect ALL mismatches (don't stop on first)
for col in float_columns:
    col_mismatches = compare_with_hybrid_tolerance(...)
    all_mismatches.append(col_mismatches)

# Severity classification
if max_rel_diff > 0.01: severity = "CRITICAL"
elif max_rel_diff > 1e-5: severity = "WARNING"
else: severity = "INFO"
```

**Why:** CONTEXT.md specifies "always run to completion, report only" - partial analysis hides issues. Full reporting enables comprehensive debugging.

### Pattern 4: Git-Based Audit Trail
```python
git_hash = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip()
git_dirty = subprocess.run(["git", "diff", "--quiet"]).returncode != 0
timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
```

**Why:** Reproducibility requires exact code version (git hash) + execution time (timestamp) + configuration. Without this, debugging 3 months later is impossible.

## Key Decisions

1. **Hybrid tolerance instead of simple epsilon**: Handles both small and large values correctly (avoids false positives/negatives)
2. **Column-specific tolerances**: Price (1e-6/1e-5) vs volume (1e-2/1e-4) - different data types need different precision
3. **NaN == NaN is match**: Avoid SQL NULL semantics issues (RESEARCH.md Pitfall 1)
4. **Comprehensive mismatch reporting**: Collect ALL mismatches with severity levels (CONTEXT.md requirement)
5. **Git commit hash in metadata**: Full reproducibility for debugging 3 months later

## Verification Results

All verification checks passed:

1. ✅ SQL DDL file exists: `sql/ddl/create_dim_assets.sql`
2. ✅ sql/baseline directory exists for Plan 02
3. ✅ Python module structure exists: `src/ta_lab2/scripts/baseline/`
4. ✅ All imports work: `comparison_utils`, `metadata_tracker`
5. ✅ NaN handling test: Correctly treats `NaN == NaN` as match

## Files Created

| File | LOC | Purpose |
|------|-----|---------|
| `sql/ddl/create_dim_assets.sql` | 12 | DDL to create dim_assets table (CRYPTO assets only) |
| `sql/baseline/.gitkeep` | 0 | Directory structure for snapshot SQL files |
| `src/ta_lab2/scripts/baseline/__init__.py` | 32 | Module exports |
| `src/ta_lab2/scripts/baseline/comparison_utils.py` | 309 | Epsilon-aware comparison with hybrid tolerance |
| `src/ta_lab2/scripts/baseline/metadata_tracker.py` | 221 | Audit trail capture and serialization |
| **Total** | **574** | **5 files created** |

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

**Ready for Plan 02 (Orchestration Script):**

✅ `sql/baseline/` directory exists for snapshot SQL generation
✅ `comparison_utils.compare_tables()` ready for snapshot vs rebuilt comparison
✅ `metadata_tracker.capture_metadata()` ready for audit trail generation
✅ All utilities follow existing code style (type hints, docstrings per `logging_config.py` and `common_snapshot_contract.py`)

**No blockers or concerns.**

## Technical Highlights

### NumPy allclose Hybrid Tolerance Formula
```
abs(baseline - rebuilt) <= max(rtol * max(abs(baseline), abs(rebuilt)), atol)
```

This formula solves two problems:
- **Small values near zero**: atol (1e-6) catches exact equality regardless of magnitude
- **Large values**: rtol (1e-5 = 0.001%) catches floating-point rounding errors

Example:
- Price $0.000001 vs $0.000002: abs_diff = 1e-6, atol = 1e-6 → **MATCH** (within absolute tolerance)
- Price $50,000 vs $50,000.5: abs_diff = 0.5, rtol * 50000 = 0.5 → **MATCH** (within relative tolerance)

### Severity Classification
- **CRITICAL**: >1% relative difference (data corruption, calculation error)
- **WARNING**: >epsilon but <1% (unexpected drift, investigate)
- **INFO**: Within epsilon (expected floating-point precision)

This aligns with CONTEXT.md mismatch reporting requirements.

## References

- **Phase 25 CONTEXT.md**: User decisions on epsilon tolerance, mismatch reporting, metadata capture
- **Phase 25 RESEARCH.md**: NumPy allclose pattern, pitfalls (NaN handling, temporal ordering, tolerances)
- **NumPy allclose docs**: Official API for hybrid tolerance comparison
- **Existing patterns**: `logging_config.py` (imports, type hints), `common_snapshot_contract.py` (docstrings, validation)

---

*Completed: 2026-02-05*
*Duration: 6 minutes*
*Commits: 2e63dfeb, fdc9fbf2*
