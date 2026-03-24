---
phase: 92-ctf-ic-analysis-feature-selection
plan: "03"
subsystem: analysis
tags: [ic-analysis, feature-selection, cross-timeframe, dim_ctf_feature_selection, yaml-pruning, comparison-report]

# Dependency graph
requires:
  - phase: 92-02
    provides: "CTF IC sweep completed, 1808 CTF IC rows in ic_results for BTC+XRP 1D"
  - phase: 92-01
    provides: "dim_ctf_feature_selection table, load_ctf_features function"
  - phase: 80
    provides: "classify_feature_tier(), IC-IR tier classification framework"

provides:
  - "run_ctf_feature_selection.py CLI: 9-step CTF tier classification + comparison pipeline"
  - "dim_ctf_feature_selection: 96 rows upserted (7 active, 3 cond, 56 watch, 30 archive)"
  - "configs/ctf_config_pruned.yaml: pruned CTF config retaining all 6 base TFs"
  - "reports/ctf/ctf_ic_comparison_report.md: CTF vs AMA IC-IR comparison with redundancy analysis"
  - "reports/ctf/ctf_ic_comparison_report.json: machine-readable comparison data"

affects:
  - "Phase 93+ model training: active CTF features (macd_*_agreement, close_fracdiff) available for inclusion"
  - "run_ctf_refresh: ctf_config_pruned.yaml can be used to target non-archive ref_tf combos"
  - "Dashboard/research pages: dim_ctf_feature_selection queryable for CTF tier context"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "save_ctf_to_db() uses ON CONFLICT DO UPDATE (not TRUNCATE like Phase 80 save_to_db)"
    - "_get_ctf_feature_names() uses dual strategy: config-based generation + DB pattern match"
    - "_prune_ctf_config() uses 'all-archive across all indicators' pruning criterion"
    - "reports/ dir is gitignored; git add -f forces inclusion for comparison reports"

key-files:
  created:
    - "src/ta_lab2/scripts/analysis/run_ctf_feature_selection.py"
    - "configs/ctf_config_pruned.yaml"
    - "reports/ctf/ctf_ic_comparison_report.md"
    - "reports/ctf/ctf_ic_comparison_report.json"
  modified: []

key-decisions:
  - "ic_ir_cutoff=0.5 for CTF active tier (vs 1.0 for Phase 80 AMA) -- CTF has limited coverage, lower bar appropriate"
  - "save_ctf_to_db() upserts to dim_ctf_feature_selection -- does NOT truncate dim_feature_selection (Phase 80 table)"
  - "pruned config retains all 6 base_tfs regardless of archive status -- per Phase 92 context decision"
  - "0 ref_tfs pruned from config because only 7D ref_tf data exists -- other ref_tfs absent from ic_results"
  - "stationarity/ljung-box run with --skip flags for initial pipeline (data limited to 2 assets at 1D only)"
  - "reports/ dir gitignored -- used git add -f for comparison reports as project artifacts"
  - "redundancy_verdict uses dir() check in json_data to handle case where corr_value is None"

patterns-established:
  - "CTF feature name pattern: {indicator_name}_{ref_tf_lower}_{composite} (e.g. rsi_14_7d_slope)"
  - "CTF IC-IR cutoff 0.5 (not AMA's 1.0): different scale appropriate for CTF limited-coverage runs"
  - "Comparison report sections: tier counts, top features table, redundancy (Spearman rho), head-to-head, pruning"

# Metrics
duration: 10min
completed: 2026-03-24
---

# Phase 92 Plan 03: CTF Feature Selection Summary

**CTF tier CLI (run_ctf_feature_selection.py) classifies 96 features into active/conditional/watch/archive using IC-IR cutoff 0.5, persists to dim_ctf_feature_selection, and generates CTF vs AMA comparison report showing LOW redundancy (rho=0.19)**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-24T02:41:08Z
- **Completed:** 2026-03-24T02:51:30Z
- **Tasks:** 2
- **Files modified:** 4 created

## Accomplishments
- Created run_ctf_feature_selection.py with full 9-step CTF feature selection pipeline
- dim_ctf_feature_selection populated with 96 rows: 7 active, 3 conditional, 56 watch, 30 archive
- CTF vs AMA comparison report shows LOW redundancy (Spearman rho=0.19, < 0.4 threshold)
- configs/ctf_config_pruned.yaml written retaining all 6 base TFs (no pruning with limited 7D-only data)
- Top active CTF features: macd_*_7d_agreement (IC-IR=1.29) and close_fracdiff_7d (IC-IR=0.73)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_ctf_feature_selection.py** - `23613b8c` (feat)
2. **Task 2: Execute full pipeline + generate outputs** - `8ead13f9` (feat)

**Plan metadata:** (to be added in final commit)

## Files Created/Modified
- `src/ta_lab2/scripts/analysis/run_ctf_feature_selection.py` - CTF feature selection + comparison + pruning CLI (9-step pipeline)
- `configs/ctf_config_pruned.yaml` - Pruned CTF config retaining all 6 base TFs
- `reports/ctf/ctf_ic_comparison_report.md` - CTF vs AMA IC-IR comparison report with redundancy analysis
- `reports/ctf/ctf_ic_comparison_report.json` - Machine-readable comparison data

## Decisions Made
- ic_ir_cutoff=0.5 for CTF active tier (vs 1.0 for Phase 80 AMA) -- CTF has limited 2-asset coverage, lower bar appropriate; all 7 active features are genuinely high-IC
- save_ctf_to_db() uses ON CONFLICT upsert (not TRUNCATE like Phase 80) -- CTF table is separate from dim_feature_selection to avoid interference
- pruned config retains all 6 base_tfs regardless -- per Phase 92 context decision ("Keep all 6 base TFs regardless of results")
- 0 ref_tfs pruned from config because only 7D ref_tf data exists in ic_results -- other ref_tfs absent due to limited CTF sweep coverage
- reports/ dir gitignored -- used `git add -f` to include comparison reports as persistent project artifacts
- --skip-stationarity + --skip-ljungbox used for initial run (CTF data from 2 assets only, tests would be based on insufficient cross-sectional coverage)
- redundancy analysis: Spearman rho=0.19 between CTF IC-IR and base indicator AMA IC-IR across 54 matched pairs -> LOW redundancy verdict (rho < 0.4)

## Deviations from Plan

None - plan executed exactly as written. The pruning producing 0 prunes is expected behavior given limited data coverage (only 7D ref_tf in ic_results).

## Issues Encountered
- reports/ directory is gitignored -- resolved with `git add -f` (standard pattern for generated artifacts that should be tracked)
- Pre-commit hook reformatted run_ctf_feature_selection.py (ruff-format) and fixed line endings on output files -- both standard pattern, re-staged and committed clean

## Next Phase Readiness
- Phase 92 complete: CTF IC analysis pipeline is fully operational
- Active CTF features (macd_*_7d_agreement IC-IR=1.29, close_fracdiff IC-IR=0.73) ready for inclusion in Phase 93+ model training
- Full coverage requires run_ctf_ic_sweep --all after run_ctf_refresh --all (currently 2 assets x 1 ref_tf = 7D only)
- dim_ctf_feature_selection is queryable for tier context in downstream pipelines

---
*Phase: 92-ctf-ic-analysis-feature-selection*
*Completed: 2026-03-24*
