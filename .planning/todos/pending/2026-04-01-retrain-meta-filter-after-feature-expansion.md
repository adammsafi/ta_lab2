---
title: Retrain XGBoost meta-label filter after feature expansion (Phases 103-106)
priority: medium
created: 2026-04-01
context: Phase 100 ML-03 evidentiary gap
---

## What

Retrain the XGBoost meta-label filter (`run_meta_filter.py --evaluate-thresholds`) after
Phases 103-106 populate the feature store with 20-30+ indicators. The current model was
trained on only 2 features (bb_ma_20, close_fracdiff) and achieved AUC=0.49 (near random).

## Why

Phase 100 verification found the meta-filter infrastructure complete but the risk-adjusted
return evidence missing. With a fuller feature store, the model should achieve meaningful
AUC and the threshold analysis should demonstrate Sharpe improvement on filtered trades.

## How

```bash
# After Phases 103-106 complete:
python -m ta_lab2.scripts.ml.run_meta_filter --evaluate-thresholds --tf 1D
```

Compare filtered vs unfiltered Sharpe ratios at the optimal threshold. If AUC > 0.55 and
filtered Sharpe >= unfiltered Sharpe, enable via:

```sql
UPDATE dim_executor_config
SET meta_filter_enabled = true,
    meta_filter_threshold = <optimal>,
    meta_filter_model_path = 'models/xgb_meta_filter_latest.json'
WHERE is_active = true;
```

## Acceptance

- AUC > 0.55 on purged CV
- Filtered Sharpe >= unfiltered Sharpe at chosen threshold
- ML-03 evidentiary gap in 100-VERIFICATION.md resolved
