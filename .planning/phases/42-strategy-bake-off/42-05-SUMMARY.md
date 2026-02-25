---
phase: 42-strategy-bake-off
plan: "05"
subsystem: backtests
tags: [scorecard, plotly, ic-ranking, strategy-selection, walk-forward, composite-scoring, markdown-report, bakeoff]

# Dependency graph
requires:
  - phase: 42-04
    provides: STRATEGY_SELECTION.md, final_validation.csv, select_strategies.py
  - phase: 42-03
    provides: composite_scores.csv, sensitivity_analysis.csv
  - phase: 42-01
    provides: feature_ic_ranking.csv, cmc_ic_results DB table
provides:
  - generate_bakeoff_scorecard.py: Scorecard generation script — reads CSVs + DB, builds 6-section markdown + 5 Plotly charts
  - BAKEOFF_SCORECARD.md: Formal 20KB self-contained scorecard document in reports/bakeoff/
  - charts/: 5 HTML charts (ic_ranking, strategy_comparison, sensitivity_heatmap, cost_sensitivity x2)
affects:
  - 53 (V1 Validation references BAKEOFF_SCORECARD.md as baseline)
  - 54 (V1 Results Memo compares against scorecard expected performance ranges)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Scorecard generation: reads from CSV files + DB, builds structured markdown with 6 sections, saves Plotly charts as HTML (kaleido fallback from PNG)"
    - "Path resolution: parents[4] for project root from scripts/analysis/ depth"
    - "Chart filename sanitization: re.sub(r'[^a-zA-Z0-9_]', '_', fragment) for Windows-safe filenames"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py
    - reports/bakeoff/BAKEOFF_SCORECARD.md (gitignored, regeneratable)
    - reports/bakeoff/charts/ (5 HTML charts, gitignored)
  modified: []

key-decisions:
  - "reports/ is gitignored — scorecard and charts not committed to git; script is rerunnable to regenerate"
  - "HTML charts used throughout (kaleido not installed); script will auto-upgrade to PNG when kaleido available"
  - "parents[4] is correct depth for scripts/analysis/ path relative to project root (not parents[5])"

patterns-established:
  - "Scorecard generation pattern: load_*() functions for each CSV source, load_bakeoff_results() for DB with graceful fallback, build_scorecard() assembles all sections"
  - "Chart filename sanitization: always apply re.sub before using user-supplied string fragments as filenames"

# Metrics
duration: 7min
completed: 2026-02-25
---

# Phase 42 Plan 05: Bake-Off Scorecard Summary

**generate_bakeoff_scorecard.py produces 20KB self-contained BAKEOFF_SCORECARD.md with 6 sections (IC ranking, walk-forward results, composite scoring, cost sensitivity, strategy selection, appendix) and 5 Plotly charts — permanent reference document for Phase 53 V1 Validation**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-25T03:01:06Z
- **Completed:** 2026-02-25T03:08:10Z
- **Tasks:** 2/2
- **Files modified:** 1 created (script), 1 generated (scorecard), 5 charts

## Accomplishments

- `generate_bakeoff_scorecard.py` built: data loading from 4 CSV files + DB, 5 Plotly chart generators (all using `plotly.graph_objects`), 6-section markdown builder, CLI with `--output/--no-charts/--asset-id/--tf/--charts-dir/--db-url`
- `BAKEOFF_SCORECARD.md` generated: 20,745-byte self-contained document covering full Phase 42 bake-off methodology and results; readable without DB access; all 6 required sections present with tables and chart embeds
- Chart files created: 5 HTML charts in `reports/bakeoff/charts/` (ic_ranking, strategy_comparison, sensitivity_heatmap, cost_sensitivity_ema_17, cost_sensitivity for ema_21/50)
- Phase 42 complete: all 5 plans executed, strategy bake-off documented from IC sweep through strategy selection to formal scorecard

## Task Commits

1. **Task 1: Build generate_bakeoff_scorecard.py** - `2d5c7e21` (feat)
2. **Task 1 fixes (path + sanitization)** - `d0fedce5` (fix)

**Note:** Task 2 output (BAKEOFF_SCORECARD.md) is gitignored (`reports/` in .gitignore) — consistent with all prior Phase 42 CSV/MD report outputs. The script is rerunnable.

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/generate_bakeoff_scorecard.py` — Scorecard generator: 7 data loading functions, 5 Plotly chart generators (go.Bar, go.Scatter, go.Heatmap), 6 section builders, build_scorecard() orchestrator, CLI entrypoint
- `reports/bakeoff/BAKEOFF_SCORECARD.md` — Generated document (gitignored): 20KB formal scorecard with IC ranking (20 features), walk-forward results (10-fold per-strategy breakdown), composite scoring (4-scheme robustness table), cost sensitivity (12-scenario tables per strategy), strategy selection rationale + V1 deployment config, appendix with glossary and data sources
- `reports/bakeoff/charts/` — 5 HTML charts (gitignored)

## Decisions Made

1. **`reports/` gitignored, script is rerunnable**: Consistent with all prior Phase 42 plans. No attempt to force-add reports to git. The generate_bakeoff_scorecard.py script is committed and serves as the reproducibility artifact.

2. **HTML charts as primary format (kaleido fallback)**: Kaleido is not installed in this environment. All 5 charts saved as HTML with `write_html()`. The kaleido fallback path is already coded — when kaleido is installed, charts will export as PNG automatically without code changes.

3. **Hardcoded per-fold data from STRATEGY_SELECTION.md**: Per-fold Sharpe/MaxDD breakdown for the 2 selected strategies is hardcoded from prior plan's results rather than re-queried from DB (DB not required at scorecard generation time for the key V1 reference data).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed incorrect project root path (parents[5] -> parents[4])**

- **Found during:** Task 2 (execution) — scorecard was writing to wrong directory
- **Issue:** `Path(__file__).resolve().parents[5]` points to `Downloads/` not `ta_lab2/`; correct depth for `scripts/analysis/` is 4 (file -> analysis -> scripts -> ta_lab2 -> src -> ta_lab2)
- **Fix:** Changed to `parents[4]`
- **Files modified:** `generate_bakeoff_scorecard.py`
- **Verification:** Scorecard now writes to correct `reports/bakeoff/BAKEOFF_SCORECARD.md`
- **Committed in:** d0fedce5

**2. [Rule 3 - Blocking] Fixed Windows-invalid filename from label_fragment containing quotes/colons**

- **Found during:** Task 2 (execution) — OSError on `write_html()` with filename `cost_sensitivity_slow_ema":_"ema_50.html`
- **Issue:** Label fragment `slow_ema": "ema_50` used directly in filename via `.replace()` — quotes and colons are invalid filename characters on Windows
- **Fix:** Applied `re.sub(r'[^a-zA-Z0-9_]', '_', label_fragment)[:30]` to produce safe filename
- **Files modified:** `generate_bakeoff_scorecard.py`
- **Verification:** All 5 charts generate without OSError
- **Committed in:** d0fedce5

**3. [Rule 1 - Bug] Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`**

- **Found during:** Task 2 (execution) — DeprecationWarning visible in output
- **Issue:** `datetime.utcnow()` is deprecated in Python 3.12
- **Fix:** `from datetime import datetime, timezone`; `datetime.now(timezone.utc)`
- **Files modified:** `generate_bakeoff_scorecard.py`
- **Committed in:** d0fedce5

---

**Total deviations:** 3 auto-fixed (1 Rule 3 path, 1 Rule 3 Windows blocking, 1 Rule 1 deprecation)
**Impact on plan:** All 3 auto-fixes were necessary for correct execution. No scope creep.

## Issues Encountered

- Pre-commit hook (ruff-format) reformatted the file on both commits — standard Windows CRLF pattern. Re-staged and committed on second attempt each time.
- `reports/` gitignored — scorecard not committed to git. Consistent with prior Phase 42 plans (all CSVs and markdown reports in reports/ are gitignored). No action needed.

## Next Phase Readiness

- **Phase 53 (V1 Validation) ready**: `BAKEOFF_SCORECARD.md` at `reports/bakeoff/BAKEOFF_SCORECARD.md` documents expected performance ranges (Sharpe [0.29-2.51], MaxDD range per fold) and V1 deployment config for the paper trading validator
- **Phase 54 (V1 Results Memo) ready**: Scorecard has formal selection rationale, V1 gate status (Sharpe PASS / MaxDD FAIL), and ensemble analysis documented
- **Phase 45 (Paper-Trade Executor) already has**: V1 deployment config in `STRATEGY_SELECTION.md` (signal_type, params, 10% position fraction, 15% circuit breaker)
- **Phase 42 complete**: All 5 plans executed — IC sweep, walk-forward backtest, composite scoring, strategy selection, formal scorecard

---
*Phase: 42-strategy-bake-off*
*Completed: 2026-02-25*
