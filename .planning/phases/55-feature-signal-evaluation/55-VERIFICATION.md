---
phase: 55-feature-signal-evaluation
verified: 2026-02-26T23:34:45Z
status: gaps_found
score: 10/13 must-haves verified
gaps:
  - truth: "IC scores exist in cmc_ic_results for all qualifying (asset, tf) pairs at all 109 TFs"
    status: partial
    reason: "IC sweep ran only 9 TFs (5 from Phase 42 + 4 new: 3D, 5D, 10D, 21D). Full 109-TF sweep estimated at 9-10 hours was explicitly deferred. EVAL-01 requires all assets x all TFs."
    artifacts:
      - path: "reports/evaluation/ic_ranking_full.csv"
        issue: "Contains 97 features ranked from 9-TF data, not 109-TF data as required"
    missing:
      - "Run remaining 100 TFs: python -m ta_lab2.scripts.analysis.run_ic_sweep --all --skip-ama --no-overwrite --output-dir reports/evaluation"
      - "No code changes needed -- infrastructure is complete"
  - truth: "AMA variants scored via ExperimentRunner with BH gate"
    status: failed
    reason: "cmc_ama_multi_tf_u does not exist in DB. All 31 AMA entries in features.yaml returned 0 experiment rows."
    artifacts:
      - path: "reports/evaluation/experiment_results.csv"
        issue: "0 rows for any AMA feature (feature_name starting with ama_)"
      - path: "reports/evaluation/bh_gate_results.csv"
        issue: "0 AMA features in BH gate summary"
    missing:
      - "Run AMA refresh pipeline to populate cmc_ama_multi_tf_u"
      - "Re-run ExperimentRunner sweep for AMA features after table is populated"
  - truth: "Feature lifecycle decisions executed in dim_feature_registry"
    status: partial
    reason: "60 features have action_taken=promote_recommended in CSV but FeaturePromoter.promote_feature() was NOT called. dim_feature_registry has 0 rows."
    artifacts:
      - path: "reports/evaluation/promotion_decisions.csv"
        issue: "action_taken column has only promote_recommended (60) and none (59) -- no actual promoted entries"
    missing:
      - "Execute FeaturePromoter for the 60 recommended features to populate dim_feature_registry"
      - "Update promotion_decisions.csv action_taken to promoted after execution"
---

# Phase 55: Feature and Signal Evaluation Verification Report

**Phase Goal:** Close the evaluation gap -- run the v0.9.0 IC and experimentation infrastructure on real data, score all existing features and AMA variants, validate signal quality, and populate dashboards with empirical results.
**Verified:** 2026-02-26T23:34:45Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Phase 42 IC methodology verified as identical (delta < 1e-6) | VERIFIED | methodology_verification.csv: 9/9 MATCH, max delta 4.761e-9 |
| 2 | IC scores exist for all qualifying pairs at all 109 TFs | PARTIAL | 9 TFs covered (1D,3D,5D,7D,10D,14D,21D,30D,90D); 100 of 109 TFs deferred |
| 3 | Regime-conditional IC breakdown for BTC and ETH at 1D | VERIFIED | EVALUATION_FINDINGS.md has trend_state + vol_state tables with real IC-IR values |
| 4 | Feature ranking CSV written with all features ranked by IC-IR | VERIFIED | reports/evaluation/ic_ranking_full.csv: 97 features, 98 lines |
| 5 | features.yaml expanded to 130+ entries (canonical, AMA, adaptive RSI) | VERIFIED | 135 experimental entries; FeatureRegistry.load() validates 135; KAMA hash fixed |
| 6 | All features.yaml entries pass FeatureRegistry.load() validation | VERIFIED | 135 features loaded, no ValueError |
| 7 | cmc_feature_experiments populated with >=100 features, BH p-values stored | VERIFIED | 100 distinct feature_names, 67,788 rows, 5 TFs, ic_p_value_bh present |
| 8 | AMA variants scored via ExperimentRunner with BH gate | FAILED | 0 AMA rows in experiment_results.csv; cmc_ama_multi_tf_u not in DB |
| 9 | Experiments dashboard page shows non-empty results | VERIFIED | 5_experiments.py wired to cmc_feature_experiments; DB has 67,788 rows |
| 10 | Adaptive vs static RSI A/B comparison complete (IC + walk-forward Sharpe) | VERIFIED | 28-row IC comparison, 5-fold bakeoff, formal A/B report with Decision section |
| 11 | generate_signals_rsi.py default reflects A/B winner with decision comment | VERIFIED | use_adaptive=False (line 315); 4-line comment at lines 310-314 citing Phase 55 A/B |
| 12 | Evaluation findings documented: IC rankings, regime breakdown, lifecycle decisions | VERIFIED | EVALUATION_FINDINGS.md 309 lines; regime tables, BH summary, lifecycle lists |
| 13 | Feature lifecycle decisions executed in dim_feature_registry | PARTIAL | 60 features recommended; FeaturePromoter NOT called; dim_feature_registry has 0 rows |

**Score:** 10/13 truths fully verified (2 partial counted as gaps, 1 failed)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|--------|
| `src/ta_lab2/scripts/analysis/run_ic_sweep.py` | venue exclusion, output-dir support | VERIFIED | venue in _EXTRA_NON_FEATURE_COLS (line 64); --output-dir arg (line 909); save_ic_results + batch_compute_ic wired |
| `configs/experiments/features.yaml` | 130+ entries: canonical, AMA, adaptive RSI | VERIFIED | 135 experimental features; 97 canonical_; 30 ama_; 1 adaptive_rsi_normalized; EMA crossover skip documented |
| `src/ta_lab2/experiments/runner.py` | Bug fixes: timestamp alias, None guard, _TABLES_WITH_TIMESTAMP_COL | VERIFIED | _TABLES_WITH_TIMESTAMP_COL (line 73); ts_col AS ts in _load_inputs (line 430); None guard (lines 673-674) |
| `src/ta_lab2/experiments/registry.py` | Public features property | VERIFIED | @property features() at lines 115-116 |
| `src/ta_lab2/scripts/signals/generate_signals_rsi.py` | use_adaptive default + decision comment | VERIFIED | use_adaptive=False (line 315); 4-line decision comment at lines 310-314 |
| `reports/evaluation/methodology_verification.csv` | 9/9 MATCH, delta < 1e-6 | VERIFIED | 9 rows, all status=MATCH, max delta 4.761e-9 |
| `reports/evaluation/ic_ranking_full.csv` | Feature ranking across all TFs | VERIFIED | 97 features, 98 lines |
| `reports/evaluation/experiment_results.csv` | 67,788+ IC rows with BH p-values | VERIFIED | 67,789 lines; ic_p_value_bh column confirmed |
| `reports/evaluation/bh_gate_results.csv` | Per-feature BH gate pass/fail | VERIFIED | 101 lines; 79 True and 21 False in bh_passes |
| `reports/evaluation/adaptive_rsi_ic_comparison.csv` | 28 rows, BTC+ETH, 7 horizons | VERIFIED | 29 lines; asset_id=[1,1027]; all 28 winner=static |
| `reports/evaluation/adaptive_rsi_bakeoff.csv` | 5-fold walk-forward results | VERIFIED | 6 lines; static_sharpe and adaptive_sharpe populated for all 5 folds |
| `reports/evaluation/adaptive_rsi_ab_comparison.md` | Formal report with Decision section | VERIFIED | 132 lines; all sections present; clear winner declared |
| `reports/evaluation/promotion_decisions.csv` | Per-feature lifecycle with action_taken | PARTIAL | 120 lines; action_taken=promote_recommended (not promoted); FeaturePromoter not called |
| `reports/evaluation/EVALUATION_FINDINGS.md` | Comprehensive 100+ line report | VERIFIED | 309 lines; IC ranking tables, regime breakdown, BH gate, adaptive RSI, lifecycle decisions |
| `notebooks/04_evaluation_findings.ipynb` | 25+ cells, Plotly charts | VERIFIED | 39 cells confirmed via nbformat; IC rankings, decay, regime heatmap, BH gate, RSI comparison, lifecycle |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|--------|
| run_ic_sweep.py | cmc_ic_results | save_ic_results upsert | WIRED | save_ic_results called at lines 536 and 676 |
| run_ic_sweep.py | cmc_features | batch_compute_ic | WIRED | batch_compute_ic called at lines 469 and 648 |
| features.yaml | FeatureRegistry.load() | YAML parsing + lifecycle validation | WIRED | 135 features load cleanly, no ValueError |
| features.yaml | ExperimentRunner | runner.run() consumes feature definitions | WIRED | 100 features produced 67,788 experiment rows |
| ExperimentRunner | cmc_feature_experiments | save_experiment_results | WIRED | 67,788 rows confirmed in CSV export |
| cmc_feature_experiments | 5_experiments.py | load_experiment_summary query | WIRED | 5_experiments.py imports and calls load_experiment_summary at line 49 |
| cmc_ic_results | adaptive_rsi_ic_comparison.csv | SQL query WHERE feature=rsi_14 | WIRED | 28 rows from cmc_ic_results for asset_id=[1,1027] |
| adaptive_rsi_ab_comparison.md | generate_signals_rsi.py | winner updates use_adaptive default | WIRED | use_adaptive=False comment at lines 310-314 cites the report |
| cmc_ic_results | EVALUATION_FINDINGS.md | SQL aggregation for feature rankings | WIRED | Real IC-IR values in tables (97 features, 82,110 rows cited) |
| cmc_feature_experiments | promotion_decisions.csv | BH gate check per feature | WIRED | promotion_decisions.csv uses bh_passes from bh_gate_results.csv |
| FeaturePromoter | dim_feature_registry | promote_feature() | NOT WIRED | FeaturePromoter.promote_feature() exists but was not called; dim_feature_registry has 0 rows |

---

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| EVAL-01: IC sweep covers all assets x all TFs x canonical features + AMA variants | PARTIAL | 9 of 109 TFs swept; remaining 100 TFs deferred (estimated 9-10 hours) |
| EVAL-02: AMA variants scored via ExperimentRunner with BH gate | PARTIAL | AMA YAML entries correct; cmc_ama_multi_tf_u missing from DB; 0 AMA rows |
| EVAL-03: Adaptive vs static RSI A/B with IC + Sharpe; default updated | SATISFIED | Full comparison complete; use_adaptive=False retained per inconclusive result |
| EVAL-04: cmc_feature_experiments populated; Experiments dashboard shows results | SATISFIED | 67,788 rows; dashboard wired to cmc_feature_experiments; non-empty results confirmed |
| EVAL-05: Evaluation findings documented with rankings, regime breakdown, lifecycle decisions | SATISFIED | EVALUATION_FINDINGS.md 309 lines; promotion_decisions.csv 119 rows; notebook 39 cells |

---


### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|---------
| promotion_decisions.csv | all | action_taken=promote_recommended not promoted | Warning | Lifecycle decisions documented but not executed; dim_feature_registry unpopulated |
| EVALUATION_FINDINGS.md | 4 | Scope header claims AMA variants but AMA was not scored | Info | Header inaccurate; body correctly describes 100 non-AMA features |

No blocker anti-patterns. Both items are documentation and execution gaps, not code stubs.

---

## Gaps Summary

Three gaps prevent full goal achievement:

Gap 1 -- IC sweep TF coverage (EVAL-01 partial, Truth 2 partial). The plan and ROADMAP success criterion require IC scores across all 109 timeframes. Execution ran 9 TFs. The 55-01 SUMMARY explicitly acknowledges this as a time constraint. The code, DB schema, and infrastructure are complete. Closing this gap requires only a background job with no code changes.

Command to close: python -m ta_lab2.scripts.analysis.run_ic_sweep --all --skip-ama --no-overwrite --output-dir reports/evaluation

Gap 2 -- AMA variants not scored (EVAL-02 partial, Truth 8 failed). The YAML registry has 31 correctly-specified AMA entries with verified params_hash values. ExperimentRunner code paths are correct (3 bugs fixed in 55-03). But cmc_ama_multi_tf_u does not exist in the database; all AMA features return 0 experiment rows. EVALUATION_FINDINGS.md scope header says all canonical features + AMA variants but the body reports on 100 non-AMA features only. Closing requires running the AMA refresh pipeline (future phase dependency) then re-running the ExperimentRunner sweep for AMA features.

Gap 3 -- Feature promotions not executed (Truth 13 partial). The 55-05 plan Task 1 verification criterion required at least some features have action_taken = promoted (written to dim_feature_registry). The actual state: 60 features have action_taken=promote_recommended, but FeaturePromoter.promote_feature() was not called. The implementation agent explicitly deferred this. dim_feature_registry has 0 rows. Closing requires running FeaturePromoter for the 60 recommended features.

The 10 passing truths represent substantial achievement: IC methodology verified, 82,110 IC rows across 9 TFs with regime breakdown, 67,788 BH-corrected experiment rows for 100 features, full A/B comparison for adaptive RSI, 309-line findings document, and a 39-cell interactive notebook.

---

*Verified: 2026-02-26T23:34:45Z*
*Verifier: Claude (gsd-verifier)*
