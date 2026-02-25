---
phase: 49-tail-risk-policy
plan: 04
subsystem: analysis
tags: [tail-risk, policy, vol-sizing, escalation, yaml-config, plotly, cli, TAIL-01, TAIL-02, TAIL-03]

# Dependency graph
requires:
  - phase: 49-01
    provides: vol_sizer library + Alembic migration (dim_risk_state.tail_risk_state + cmc_risk_events extended CHECK)
  - phase: 49-02
    provides: flatten_trigger.py + RiskEngine Gate 1.5 + evaluate_tail_risk_state with 21d/14d cooldown
  - phase: 49-03
    provides: run_tail_risk_comparison.py + SIZING_COMPARISON.md (Summary Recommendations embedded)
provides:
  - TAIL-03 deliverable: generate_tail_risk_policy.py CLI
  - TAIL_RISK_POLICY.md: human-readable policy memo (7964 chars) covering all 3 TAIL requirements
  - tail_risk_config.yaml: machine-readable config for RiskEngine with vol_clear_consecutive_days=3
  - charts/vol_spike_history.html: BTC 20d rolling vol chart with REDUCE/FLATTEN threshold lines and crash annotations
affects: [paper-trading, executor, tail-risk-policy-deployment, daily-refresh-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Policy generator pattern: reads optional upstream report (SIZING_COMPARISON.md), embeds if found, falls back to research defaults"
    - "Machine-readable YAML config pattern: version+generated_at+source metadata alongside operational thresholds"
    - "Dry-run gate: --dry-run prints planned outputs and exits 0 with no DB connection or file I/O"
    - "Crash annotation pattern: Plotly vrect with rgba fill color (opacity=1) + crash_events list"
    - "E741 fix: ambiguous variable `l` in list comprehension renamed to `ln`"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/generate_tail_risk_policy.py
  modified: []

key-decisions:
  - "SIZING_COMPARISON.md embedding conditional: read Summary Recommendations section via string markers; fall back to research calibration when not found"
  - "SQL-based manual override: dim_risk_state UPDATE + cmc_risk_events INSERT; explicitly no CLI flag references (no kill_switch --set-tail-risk-state)"
  - "Regime interaction multiplicative: down_regime (0.55x) * reduce_state (0.50x) = 0.275x combined sizing"
  - "BTC as market proxy for vol chart: first asset_id in --asset-ids list (default id=1)"
  - "chart_path.parent.mkdir(parents=True) in _build_vol_spike_chart: charts/ subdirectory created on demand"
  - "NullPool for one-shot DB query (BTC returns for vol chart only)"

patterns-established:
  - "Phase 49 capstone: policy document generator ties together TAIL-01, TAIL-02, TAIL-03 into single CLI"

# Metrics
duration: 7min
completed: 2026-02-25
---

# Phase 49 Plan 04: Tail-Risk Policy Document Generator Summary

**TAIL-03 capstone: generate_tail_risk_policy.py CLI producing TAIL_RISK_POLICY.md (human memo covering all 3 TAIL requirements with COVID/FTX/May 2021 crash validation), tail_risk_config.yaml (machine config for RiskEngine), and vol_spike_history.html (BTC rolling vol chart with REDUCE/FLATTEN threshold lines)**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-02-25T21:38:35Z
- **Completed:** 2026-02-25T21:45:30Z
- **Tasks:** 1/1
- **Files modified:** 1 (created)

## Accomplishments

- Created `generate_tail_risk_policy.py` (697 lines): TAIL-03 policy document generator CLI
- TAIL_RISK_POLICY.md: 7964 chars, 5 major sections (sizing, flatten criteria, escalation, regime interaction, implementation reference + override appendix)
- SIZING_COMPARISON.md embedding: reads "## Summary Recommendations" section and embeds in policy Section 1 when found (Plan 03 output present); falls back to research calibration values with note when absent
- tail_risk_config.yaml: 8-section machine-readable config including vol_sizing, escalation_thresholds, re_entry (vol_clear_consecutive_days=3), regime_interaction, trigger_priority list
- vol_spike_history.html: BTC 20d rolling vol chart (5,613 bars), REDUCE (9.23%) + FLATTEN (11.94%) dashed threshold lines, 3 crash event vrect annotations (COVID, May 2021, FTX)
- Dry-run mode: prints planned outputs and exits 0 with no file I/O or DB connection
- Manual override section uses direct SQL commands (UPDATE dim_risk_state + INSERT INTO cmc_risk_events) -- no nonexistent CLI flags

## Task Commits

Each task was committed atomically:

1. **Task 1: Policy document and YAML config generator** - `6ab5c613` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/generate_tail_risk_policy.py` - TAIL-03 policy generator: _read_sizing_comparison_recommendations(), _build_vol_spike_chart(), _build_tail_risk_policy(), _build_tail_risk_config(), main() with argparse; dry-run support; all 3 output files

## Decisions Made

- **Conditional SIZING_COMPARISON.md embedding**: Script reads the "## Summary Recommendations" section using string marker search (not regex) -- robust to whitespace variations. Falls back to research calibration values with explicit note when file absent.
- **SQL-based manual override only**: Policy override section uses direct SQL (UPDATE dim_risk_state + INSERT cmc_risk_events). Plan verification requires no reference to nonexistent kill_switch CLI flag. SQL pattern matches actual dim_risk_state schema from Phase 49-01 migration.
- **NullPool for vol chart only**: DB connection is one-shot for BTC returns load (5,613 rows). Chart generation is the only DB-dependent step; policy and YAML are fully offline.
- **vrect opacity=1 with rgba alpha**: Plotly vrect opacity multiplies rgba channel -- opacity=1 + rgba(r,g,b,0.10) gives correct 10% transparency. Consistent with Phase 39 dashboard pattern.
- **E741 fix (Rule 1 - Bug)**: Ambiguous variable `l` in list comprehension renamed to `ln` during pre-commit hook cycle. Ruff E741 enforced across the codebase per Phase 30.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] E741 ambiguous variable name `l` in list comprehension**

- **Found during:** Task 1 commit (ruff pre-commit hook)
- **Issue:** `[l for l in lines[1:] if l.strip()]` uses `l` which ruff E741 flags as ambiguous (looks like `1`)
- **Fix:** Renamed loop variable to `ln` (line, not liquidity -- `l` -> `ln` per project convention from Phase 30)
- **Files modified:** src/ta_lab2/scripts/analysis/generate_tail_risk_policy.py
- **Verification:** ruff lint passes, all checks green on second commit attempt
- **Committed in:** 6ab5c613 (re-committed after fix)

---

**Total deviations:** 1 auto-fixed (1 Rule 1 - Bug: ruff E741 ambiguous variable)
**Impact on plan:** Zero scope change. The fix is a rename-only with no behavior change.

## Issues Encountered

Pre-commit ruff hook also reformatted 4 other style issues (long f-strings, trailing whitespace) in the first commit attempt; these were reformatted automatically before the second commit attempt.

## User Setup Required

None. CLI connects to existing DB via TARGET_DB_URL for vol chart data only. Policy and YAML are fully offline (no DB needed). Output files written to reports/tail_risk/ (gitignored).

## Next Phase Readiness

- Phase 49 is now COMPLETE (all 4 plans done: 49-01 migration, 49-02 flatten_trigger, 49-03 comparison CLI, 49-04 policy generator)
- TAIL_RISK_POLICY.md is the capstone deliverable tying together TAIL-01, TAIL-02, TAIL-03
- tail_risk_config.yaml is ready for RiskEngine integration in paper trading
- evaluate_tail_risk_state() (49-02) is ready to be wired into run_daily_refresh.py --tail-risk in a follow-on phase
- V1 paper trading can proceed with full tail-risk policy documented and enforced

---
*Phase: 49-tail-risk-policy*
*Completed: 2026-02-25*
