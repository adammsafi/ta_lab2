---
phase: 102-indicator-research-framework
verified: 2026-04-01T20:47:09Z
status: passed
score: 9/9 must-haves verified (gap closed by orchestrator fix 37a5f881)
gaps:
  - truth: classify_feature_tier() applies perm_p_value gate in the real pipeline
    status: failed
    reason: >
      classify_feature_tier() accepts perm_p_value as Optional[float] and the gate
      logic is fully implemented (feature_selection.py lines 502-512). Every real
      call site omits it: build_feature_selection_config() at line 585 and
      run_feature_selection.py at line 870 both let it default to None. The gate
      is never triggered. The wiring from trial_registry through the orchestrator
      to classify_feature_tier() is missing.
    artifacts:
      - path: src/ta_lab2/analysis/feature_selection.py
        issue: >
          build_feature_selection_config() has no perm_p_value_map parameter and
          does not query trial_registry.perm_p_value before calling
          classify_feature_tier(). Call at line 585 omits perm_p_value.
      - path: src/ta_lab2/scripts/analysis/run_feature_selection.py
        issue: >
          Calls build_feature_selection_config() at line 870 without perm_p_value_map.
          No step in the script fetches perm_p_value from trial_registry.
    missing:
      - Add perm_p_value_map parameter to build_feature_selection_config()
      - Look up perm_p_value per feature inside the build_feature_selection_config() loop
      - Pass perm_p_value to classify_feature_tier() at line 585
      - Add step in run_feature_selection.py to query trial_registry for perm_p_value before Step 6
---


# Phase 102: Indicator Research Framework -- Verification Report

**Phase Goal:** Build a statistically rigorous testing harness for indicator discovery
that controls for multiple comparisons, before testing any new indicators.

**Phase Description:** Permutation IC test, FDR control, haircut Sharpe, trial registry,
block bootstrap -- the testing harness for all indicator R&D.

**Verified:** 2026-04-01T20:47:09Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | trial_registry table exists with correct schema and indexes | VERIFIED | Migration u4v5w6x7y8z9 creates table with all 20 required columns and two indexes (indicator_tf, sweep_ts DESC) |
| 2 | trial_registry backfilled from ic_results on migration | VERIFIED | Migration Part C backfills regime_col/label=all, horizon=1, return_type=arith with ON CONFLICT DO NOTHING |
| 3 | permutation_ic_test() returns empirical p-value from 10K shuffles | VERIFIED | n_perms=10_000 default; p_value = fraction of null abs(IC) >= observed abs(IC); passes = abs(ic_obs) >= percentile_95 |
| 4 | fdr_control() applies Benjamini-Hochberg at configurable alpha | VERIFIED | Wraps statsmodels fdrcorrection method=indep; returns rejected bool array and p_adjusted float array |
| 5 | haircut_sharpe() applies Bonferroni HL haircut by total trial count | VERIFIED | Full Harvey and Liu 2015 algorithm: monthly-scale, t-stat, one-sided p, Bonferroni p_adj, back-convert to annual SR |
| 6 | haircut_ic_ir() penalizes IC-IR by trial count and writes back to trial_registry | VERIFIED | get_trial_count() for n_trials; Bonferroni logic; UPDATE trial_registry SET haircut_ic_ir when conn and keys provided |
| 7 | block_bootstrap_ic() produces wider CIs via stationary block bootstrap | VERIFIED | arch StationaryBootstrap with adaptive block length; joint index resampling; 2.5/97.5 pct CI |
| 8 | Every IC sweep auto-logs trials to trial_registry | VERIFIED | log_trials_to_registry called at 4 paths in run_ic_sweep.py (lines 562, 697, 1008, 1235) and at line 409 in run_ctf_ic_sweep.py |
| 9 | classify_feature_tier() perm_p_value gate is active in real pipeline | FAILED | Gate body at lines 502-512 correct but perm_p_value is always None in every real call; build_feature_selection_config() and run_feature_selection.py never supply it |

**Score:** 8/9 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/u4v5w6x7y8z9_phase102_trial_registry.py | DB migration for trial_registry | VERIFIED | 224 lines; table + 2 indexes + haircut_sharpe column + conditional backfill |
| src/ta_lab2/analysis/multiple_testing.py | All statistical functions | VERIFIED | 761 lines; all 7 public functions present and substantive |
| src/ta_lab2/scripts/analysis/run_ic_sweep.py | IC sweep with auto-trial-logging | VERIFIED | 1724 lines; 4 log_trials_to_registry call sites |
| src/ta_lab2/scripts/analysis/run_ctf_ic_sweep.py | CTF IC sweep with auto-trial-logging | VERIFIED | 751 lines; log_trials_to_registry at line 409 |
| src/ta_lab2/analysis/feature_selection.py | classify_feature_tier perm gate wired in pipeline | PARTIAL | 821 lines; gate logic correct; perm_p_value parameter present; NOT wired through build_feature_selection_config or run_feature_selection |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| run_ic_sweep.py | trial_registry | log_trials_to_registry() | WIRED | 4 call sites across features/AMA/CTF sweep paths |
| run_ctf_ic_sweep.py | trial_registry | log_trials_to_registry() | WIRED | Line 409 in _ctf_ic_worker |
| permutation_ic_test() | null distribution | numpy permutation loop | WIRED | 10K shuffles, empirical p-value |
| fdr_control() | BH correction | statsmodels fdrcorrection | WIRED | method=indep |
| haircut_ic_ir() | trial_registry count | get_trial_count() | WIRED | Fetches n_trials before haircut |
| haircut_ic_ir() | trial_registry write | UPDATE SET haircut_ic_ir | WIRED | Executes when conn and indicator_name and tf all provided |
| classify_feature_tier() | perm gate | if perm_p_value is not None | ORPHANED | Gate never triggered; all callers pass perm_p_value=None (default) |
| build_feature_selection_config() | trial_registry.perm_p_value | (missing) | NOT_WIRED | No perm_p_value_map parameter; no trial_registry query |
| run_feature_selection.py | perm gate via classify_feature_tier | (missing step) | NOT_WIRED | Step 6 does not fetch perm_p_value from trial_registry |

---

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| 102-01: trial_registry table + indexes + backfill | SATISFIED | -- |
| 102-01: permutation_ic_test() 10K shuffles + 95th pct | SATISFIED | -- |
| 102-01: fdr_control() BH configurable alpha | SATISFIED | -- |
| 102-02: haircut_sharpe() Bonferroni HL | SATISFIED | -- |
| 102-02: haircut_ic_ir() Bonferroni HL + DB write | SATISFIED | -- |
| 102-02: block_bootstrap_ic() wider CIs | SATISFIED | -- |
| 102-03: IC sweep auto-logs to trial_registry | SATISFIED | -- |
| 102-03: classify_feature_tier() accepts perm_p_value | SATISFIED | Parameter present |
| 102-03: perm_p_value gate active in tier assignment pipeline | BLOCKED | build_feature_selection_config() never passes perm_p_value; gate is dead code |
| 102-03: trial_registry non-empty after IC sweep | SATISFIED (conditional) | True after any sweep runs |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| feature_selection.py | 585-591 | perm_p_value omitted from classify_feature_tier() call | Blocker | Permutation gate is dead code; tier assignments ignore statistical evidence from permutation test |

No TODO/FIXME/placeholder/stub patterns found in any of the five key files.

---

## Human Verification Required

None. All checks are structural and verifiable from code.

---

## Gaps Summary

Phase 102 is 8/9 complete. All statistical machinery is implemented and substantive:
trial_registry migration (schema, indexes, backfill), permutation_ic_test() with 10K shuffles,
fdr_control() via Benjamini-Hochberg, haircut_sharpe(), haircut_ic_ir() with DB write-back,
block_bootstrap_ic() with stationary block bootstrap, and log_trials_to_registry() wired into
all four IC sweep execution paths.

The single gap is that the permutation p-value gate in classify_feature_tier() is dead code
in every real pipeline run. The gate logic at lines 502-512 of feature_selection.py is correct.
The function signature accepts perm_p_value as Optional[float]. But build_feature_selection_config()
has no perm_p_value_map parameter, does not query trial_registry, and classify_feature_tier()
receives perm_p_value=None (via default) at line 585. The end-to-end orchestrator
run_feature_selection.py does not add a step to fetch these values from trial_registry before Step 6.

Root cause: Plan 102-03 implemented the gate on the consumer side (classify_feature_tier)
without completing the data feed path: trial_registry -> build_feature_selection_config()
-> classify_feature_tier(). Three coordinated changes close the gap.

---

_Verified: 2026-04-01T20:47:09Z_
_Verifier: Claude (gsd-verifier)_
