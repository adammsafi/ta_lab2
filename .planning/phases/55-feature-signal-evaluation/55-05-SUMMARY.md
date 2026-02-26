---
phase: 55-feature-signal-evaluation
plan: "05"
subsystem: evaluation
tags: [ic, bh-gate, feature-lifecycle, promotion, jupyter, plotly, evaluation-findings]

# Dependency graph
requires:
  - phase: 55-01
    provides: IC sweep results (82,110 rows in cmc_ic_results), ic_ranking_full.csv
  - phase: 55-03
    provides: ExperimentRunner sweep (67,788 rows in cmc_feature_experiments), bh_gate_results.csv
  - phase: 55-04
    provides: Adaptive RSI A/B results, adaptive_rsi_ab_comparison.md, static RSI retained as default
provides:
  - reports/evaluation/promotion_decisions.csv (119 rows, lifecycle decisions per feature)
  - reports/evaluation/EVALUATION_FINDINGS.md (310-line comprehensive evaluation report)
  - notebooks/04_evaluation_findings.ipynb (39-cell interactive findings notebook with Plotly charts)
affects: [56-signal-integration, future-promotion-execution, dim_feature_registry-population]

# Tech tracking
tech-stack:
  added: [nbformat (notebook creation programmatic)]
  patterns: [evaluation-synthesis pattern, lifecycle-decision threshold pattern]

key-files:
  created:
    - notebooks/04_evaluation_findings.ipynb
    - reports/evaluation/promotion_decisions.csv (gitignored)
    - reports/evaluation/EVALUATION_FINDINGS.md (gitignored)
  modified: []

key-decisions:
  - "Auto-promote threshold: BH pass + IC-IR > 0.03; no keep_experimental tier emerged (all BH-pass features exceeded 0.03)"
  - "60 features recommended for promotion, 59 deprecation candidates; dim_feature_registry is empty -- promotion is documented but not executed yet"
  - "Outlier flag features (*_is_outlier) rank top by IC-IR but fail BH -- classified as deprecate_candidate despite high IC-IR; likely too few observations to pass BH"
  - "delta_ret_* family (8 features): all BH-fail; deprecation recommended"
  - "Adaptive RSI result from 55-04 documented: static retained (INCONCLUSIVE, IC-IR dimension static wins 14/14)"

patterns-established:
  - "Lifecycle decision pattern: BH gate + IC-IR threshold → promote/keep_experimental/deprecate_candidate"
  - "Notebook programmatic creation: use nbformat.v4.new_markdown_cell/new_code_cell, write with nbformat.write()"

# Metrics
duration: 16min
completed: 2026-02-26
---

# Phase 55 Plan 05: Evaluation Findings Summary

**60 features recommended for promotion (BB, RSI, ATR, MACD top tier); 310-line EVALUATION_FINDINGS.md with IC rankings, regime heatmap, BH gate summary, and adaptive RSI decision; 39-cell Plotly notebook created**

## Performance

- **Duration:** 16 min
- **Started:** 2026-02-26T23:08:24Z
- **Completed:** 2026-02-26T23:24:34Z
- **Tasks:** 2 completed
- **Files modified:** 1 committed (notebook); 2 gitignored (CSV + MD)

## Accomplishments

- Feature lifecycle decision table built: 119 rows spanning all evaluated features; 60 promote, 0 keep_experimental, 59 deprecate_candidate
- EVALUATION_FINDINGS.md: 310 lines with real DB data — IC ranking tables, regime-conditional IC breakdown (BTC 1D trend_state + vol_state), BH gate summary (79/97 pass, 81.4%), adaptive RSI A/B results, lifecycle decisions, recommendations, appendix
- 04_evaluation_findings.ipynb: 39 cells with Plotly charts — top-20 bar chart, bottom-20 bar, IC decay line chart, regime heatmap, BH gate pie + scatter, adaptive RSI side-by-side bars, lifecycle donut + scatter
- Phase 55 capstone complete: EVAL-04 and EVAL-05 objectives met

## Task Commits

1. **Tasks 1+2: Feature lifecycle decisions, findings report, and notebook** - `270edfb3` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `notebooks/04_evaluation_findings.ipynb` - 39-cell interactive findings notebook; IC rankings, regime heatmap, BH gate viz, adaptive RSI comparison, lifecycle summary charts
- `reports/evaluation/promotion_decisions.csv` - 119 rows: feature_name, ic_rank, mean_abs_ic_ir, bh_passes, recommendation, action_taken, notes (gitignored)
- `reports/evaluation/EVALUATION_FINDINGS.md` - 310-line comprehensive report (gitignored)

## Decisions Made

1. **Auto-promote threshold at IC-IR > 0.03**: All BH-passing features in the 97-feature IC ranking exceed 0.03, so the "keep_experimental" bucket ended up empty. The threshold is appropriate — features either clearly signal (>0.03) or fail BH.

2. **Outlier flags classified as deprecate_candidate despite high IC-IR**: `vol_rs_126_is_outlier` (IC-IR=1.11), `vol_gk_126_is_outlier` (IC-IR=0.88), etc. rank #1-#12 by IC-IR but all have `bh_passes=False` — they have only 4-40 observations (too rare to pass BH). Documented as deprecation candidates with note about sparse data.

3. **DB promotion deferred**: `dim_feature_registry` has 0 rows. `FeaturePromoter` exists but actual `promote_feature()` calls were not executed — recommendations documented in CSV for manual review. This is intentional per the plan ("Do NOT auto-deprecate") and because promoting all 60 features without review is overly aggressive.

4. **Notebook uses programmatic creation via nbformat**: Consistent with prior notebooks in the project (01-03). Mixed line endings pre-commit hook fixed automatically.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed unclosed parenthesis in report generation script**
- **Found during:** Task 2 (script execution)
- **Issue:** `report_lines.extend([...])` list was closed with `]` only, missing `)` — SyntaxError on execution
- **Fix:** Changed `]` to `])` at line 564 of generation script
- **Files modified:** `.planning/gen_artifacts_55_05.py` (temp script, not committed)
- **Verification:** `python -m py_compile` passed; script executed successfully
- **Committed in:** N/A (temp script not committed)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug in generation script)
**Impact on plan:** Trivial fix, no scope impact. All planned artifacts delivered.

## Issues Encountered

- `keep_experimental` recommendation bucket is empty (0 features): All BH-passing features exceeded the IC-IR > 0.03 auto-promote threshold. This means the three-tier system collapsed to effectively two tiers (promote vs deprecate). Not a problem — reflects the data.
- `nbformat` not installed in system Python; installed with `pip install --user nbformat` (one-time setup).

## Next Phase Readiness

- Phase 55 COMPLETE: All 5 plans done. IC sweep, feature registry expansion, ExperimentRunner, adaptive RSI A/B, evaluation findings all delivered.
- Ready for Phase 56+: Signal pipeline integration with promoted features
- Action needed: Execute `FeaturePromoter.promote_feature()` for the 60 recommended features to populate `dim_feature_registry`
- Action needed: Remove `delta_ret_*` 8 features from `features.yaml` (deprecation candidates)

---
*Phase: 55-feature-signal-evaluation*
*Completed: 2026-02-26*
