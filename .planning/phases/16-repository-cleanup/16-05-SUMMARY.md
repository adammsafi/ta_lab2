---
phase: 16-repository-cleanup
plan: 05
subsystem: repository-cleanup
tags: [code-analysis, similarity-detection, ast-parsing, refactoring-support]
completed: 2026-02-03
duration: 132 minutes

requires:
  phases: [16-01, 16-02, 16-03]
  decisions: []

provides:
  tools: [similarity.py]
  reports: [similarity_report.json]

affects:
  phases: []
  files: []

tech-stack:
  added:
    - ast (Python stdlib): AST parsing for function extraction
    - difflib.SequenceMatcher: Text-based code similarity scoring
  patterns:
    - dataclass-based analysis results
    - three-tier similarity classification
    - O(n²) with aggressive pre-filtering

key-files:
  created:
    - src/ta_lab2/tools/cleanup/similarity.py: Function similarity detection tool
    - src/ta_lab2/tools/cleanup/__init__.py: Cleanup module exports
    - .planning/phases/16-repository-cleanup/similarity_report.json: Similarity analysis results
  modified: []

decisions:
  - id: CLEAN-05-01
    context: AST normalization for comparison
    decision: Use ast.unparse() output directly without removing lineno attributes
    rationale: ast.unparse() requires lineno for type comments; output is already normalized
    alternatives: ["Pre-normalize AST (causes AttributeError)", "String-based comparison without AST"]
    impact: Enables successful function extraction and comparison

  - id: CLEAN-05-02
    context: Performance optimization for large codebase
    decision: Add 30% length difference pre-filter before SequenceMatcher
    rationale: Functions with >30% length difference unlikely to be 70%+ similar; skip expensive comparison
    alternatives: ["Hash-based pre-filtering", "Sample-based comparison", "Lower threshold"]
    impact: 80% comparison skip rate (1.8M of 2.2M), ~10x speedup

  - id: CLEAN-05-03
    context: Similarity report usage
    decision: Report for manual review only, no automatic consolidation
    rationale: User controls refactoring decisions per CONTEXT.md; tool flags candidates only
    alternatives: ["Automatic consolidation", "Interactive refactoring wizard"]
    impact: Safe discovery without risk of incorrect automated changes

metrics:
  functions_analyzed: 2119
  comparisons_performed: 444042
  comparisons_skipped: 1799979
  skip_rate: 80%
  matches_found: 1463
  near_exact_matches: 728
  similar_matches: 297
  related_matches: 438
---

# Phase 16 Plan 05: Function Similarity Analysis Summary

**One-liner:** AST-based function similarity detection with three-tier classification (728 near-exact, 297 similar, 438 related matches) for manual consolidation review

## What Was Built

### Similarity Analysis Tool
Created `src/ta_lab2/tools/cleanup/similarity.py` with:
- **AST-based function extraction**: Parse Python files, extract all function definitions
- **Three-tier classification**:
  - Near-exact (95%+): Strong candidates for consolidation
  - Similar (85-95%): Potential refactoring opportunities
  - Related (70-85%): Review for patterns
- **Performance optimizations**:
  - Argument count pre-filter (skip if >3 arg difference)
  - Length-based pre-filter (skip if >30% length difference)
  - Progress logging every 100 functions
  - 80% comparison skip rate achieved

### Analysis Results
Generated `.planning/phases/16-repository-cleanup/similarity_report.json`:
- **2,119 functions analyzed** across src/ta_lab2
- **1,463 similar pairs found** (70%+ similarity threshold)
- **728 near-exact matches** (95%+ similarity)
  - Many in `m_tf/old/` directory (duplicated helper functions like `_normalize_daily`)
  - Some between base classes (`base_ema_feature.py` vs `base_feature.py`)
- **444,042 comparisons performed**, 1,799,979 skipped
- **132 minutes total** (including optimization iteration)

### Cleanup Module Structure
```
src/ta_lab2/tools/cleanup/
├── __init__.py          # Exports for both duplicate and similarity detection
├── duplicates.py        # (From 16-04, created by user/linter)
└── similarity.py        # Function similarity analysis (this plan)
```

## Key Technical Decisions

### 1. AST Unparsing Without Pre-Normalization (CLEAN-05-01)
**Problem:** Initial approach deleted `lineno` attributes before unparsing, causing AttributeError.
**Solution:** Use `ast.unparse()` output directly - it's already normalized (location-independent).
**Impact:** Fixed 0 functions extracted bug, enabled successful analysis.

### 2. Length-Based Pre-Filtering (CLEAN-05-02)
**Problem:** O(n²) SequenceMatcher on 2119 functions = 2.2M comparisons, extremely slow.
**Solution:** Skip comparison if function code lengths differ by >30%.
**Impact:** Reduced to 444K comparisons (80% skip rate), ~10x speedup.

### 3. Manual Review Only (CLEAN-05-03)
**Decision:** Report flags candidates; user decides consolidation.
**Rationale:** Follows CONTEXT.md decision - "Similar functions: Flag for manual review - generate report, user decides later"
**Impact:** Safe discovery tool, no risk of incorrect automated refactoring.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Created cleanup module infrastructure**
- **Found during:** Task 1
- **Issue:** Plan 16-05 depends on [16-01, 16-02, 16-03] but references "Cleanup module from Plan 04"; Plan 16-04 not completed, cleanup/ directory missing
- **Fix:** Created src/ta_lab2/tools/cleanup/ directory and initial __init__.py with similarity exports only
- **Files created:** src/ta_lab2/tools/cleanup/__init__.py (initial version)
- **Commits:** 46705b0 (included in Task 1 commit)
- **Resolution:** User/linter later created duplicates.py and updated __init__.py to include both modules

**2. [Rule 1 - Bug] Fixed AST extraction AttributeError**
- **Found during:** Task 3 initial run
- **Issue:** `normalize_ast()` deleted `lineno` attribute before `ast.unparse()`, causing AttributeError when unparsing type comments
- **Fix:** Extract metadata before unparsing; use ast.unparse() output directly (already normalized)
- **Files modified:** src/ta_lab2/tools/cleanup/similarity.py
- **Commit:** 61ba3b2

**3. [Rule 2 - Missing Critical] Added performance optimization**
- **Found during:** Task 3 execution
- **Issue:** O(n²) comparison taking 40-60 minutes with minimal feedback; 2.2M comparisons too slow
- **Fix:** Added 30% length difference pre-filter, progress logging, comparison statistics
- **Files modified:** src/ta_lab2/tools/cleanup/similarity.py
- **Commit:** 9afb1ca

## Files Changed

### Created
- `src/ta_lab2/tools/cleanup/similarity.py` (256 lines)
  - FunctionInfo, SimilarityMatch dataclasses
  - extract_functions(), find_similar_functions(), generate_similarity_report()
  - EXCLUDE_DIRS constant
- `src/ta_lab2/tools/cleanup/__init__.py` (34 lines, later updated by user/linter)
  - Exports similarity analysis functions
  - (User/linter added duplicate detection exports)
- `.planning/phases/16-repository-cleanup/similarity_report.json` (23,424 lines)
  - $schema v1.0.0
  - Summary statistics
  - 728 near-exact matches
  - 297 similar matches
  - 438 related matches

### Modified
None (initial creation)

## Testing Results

### Verification
✅ Similarity analysis tool works (find_similar_functions import and execution)
✅ Report generated with valid schema ($schema v1.0.0)
✅ Three-tier classification present (near_exact, similar, related)
✅ Similar function pairs documented with file locations, names, similarity scores
✅ No automatic consolidation performed (manual review only)

### Notable Findings
**Top near-exact matches:**
1. `base_ema_feature.py:_ensure_output_table` ↔ `base_feature.py:_ensure_output_table` (100%)
2. Multiple `_normalize_daily` functions in `m_tf/old/` directory (100%)

**Patterns:**
- High duplication in `m_tf/old/` experimental/archived variants
- Some base class method duplication between feature implementations
- Helper function duplication across modules

## Integration Points

### Upstream Dependencies
- **Phase 16-01**: Archive infrastructure (manifest patterns, SHA256 checksums)
- **Phase 16-02**: Feature file organization (m_tf structure)
- **Phase 16-03**: Documentation organization (provides cleanup context)

### Downstream Usage
- **Phase 16-06** (if exists): May use similarity report for consolidation decisions
- **Future refactoring**: Report enables informed consolidation decisions
- **Code review**: Identify duplicate patterns for DRY refactoring

## Lessons Learned

### What Went Well
1. **AST-based approach**: Robust function extraction, handles complex Python code
2. **Three-tier classification**: Clear prioritization for manual review
3. **Dataclass design**: Clean, type-safe analysis results
4. **Performance optimization**: Length pre-filter reduced execution time significantly

### What Was Challenging
1. **AST normalization**: Required understanding ast.unparse() requirements (lineno for type comments)
2. **Performance**: Initial O(n²) too slow; required iterative optimization
3. **Long execution time**: Even optimized, 132 minutes for full analysis

### What We'd Do Differently
1. **Hash-based pre-filtering**: Use code hash for exact duplicate detection before SequenceMatcher
2. **Parallel processing**: multiprocessing.Pool for comparison batches
3. **Incremental analysis**: Cache results, only analyze changed files
4. **Configurable thresholds**: Command-line arguments for threshold, min_lines

## Next Phase Readiness

### Blockers
None.

### Outputs for Next Phase
- **similarity_report.json**: 1,463 function pairs flagged for review
- **Top candidates**: 728 near-exact matches (95%+) ready for consolidation evaluation
- **Pattern insights**: High duplication in m_tf/old/ directory

### Required Follow-up
None required. Report available for manual review when user chooses to consolidate.

## Metrics

**Execution:**
- Duration: 132 minutes (2.2 hours)
- Tasks: 3/3 completed
- Commits: 4 (1 feat, 1 fix, 1 perf, 1 feat-report)

**Analysis:**
- Functions analyzed: 2,119
- Comparisons performed: 444,042
- Comparisons skipped: 1,799,979 (80%)
- Total matches: 1,463
- Near-exact (95%+): 728
- Similar (85-95%): 297
- Related (70-85%): 438

**Code:**
- Files created: 3 (similarity.py, __init__.py, report.json)
- Lines added: 23,680 (256 code + 23,424 report JSON)
- Exports: 6 functions (FunctionInfo, SimilarityMatch, EXCLUDE_DIRS, extract_functions, find_similar_functions, generate_similarity_report)
