# Phase 62: Operational Completeness - Research

**Researched:** 2026-02-28
**Domain:** Operational execution — IC sweep completion, feature promotion, ML CLI execution, orphaned code cleanup
**Confidence:** HIGH

## Summary

Phase 62 is a pure execution phase. No new features are built. All four tasks close known gaps from Phases 55, 58, and 60 by running existing scripts against the live database.

The IC sweep infrastructure (run_ic_sweep.py) is complete and works with `--workers N` for parallel execution. The 55-VERIFICATION.md explicitly states the command needed to close the 100-TF gap. The feature promotion script (promote_feature.py) exists and calls FeaturePromoter.promote_feature() with `--yes` for non-interactive use. The 4 ML CLI scripts (run_feature_importance, run_regime_routing, run_double_ensemble, run_optuna_sweep) are verified complete with `--log-experiment` flags and full DB wiring. RebalanceScheduler has zero callers outside its own file and the portfolio __init__.py — it should be removed.

**Primary recommendation:** Run existing scripts in the documented order; delete RebalanceScheduler with a companion test deletion; no code changes required except the deletion.

---

## Task 1: Complete IC Sweep Across All 109 TFs

### What Exists

`src/ta_lab2/scripts/analysis/run_ic_sweep.py` is the complete implementation. The 55-VERIFICATION.md explicitly documents the closure command:

```bash
python -m ta_lab2.scripts.analysis.run_ic_sweep --all --skip-ama --no-overwrite --output-dir reports/evaluation
```

### Current State (from 55-VERIFICATION.md)

- 9 TFs already covered (1D, 3D, 5D, 7D, 10D, 14D, 21D, 30D, 90D) = 82,110 rows in cmc_ic_results
- 100 TFs remaining
- `asset_data_coverage` table provides fast pair discovery — no direct query of cmc_features required

### CLI Flags Reference (HIGH confidence — read directly from source)

| Flag | Purpose | Default |
|------|---------|---------|
| `--all` | Full sweep: all qualifying asset-TF pairs | required for complete sweep |
| `--skip-ama` | Skip AMA table sweep (cmc_ama_multi_tf_u does not exist) | False |
| `--no-overwrite` | Append-only semantics (ON CONFLICT DO NOTHING) | default is overwrite |
| `--workers N` | Parallel processes for cmc_features sweep | 1 (sequential) |
| `--min-bars N` | Minimum bars for a pair to qualify | 500 |
| `--horizons N...` | Forward return horizons in bars | 1 2 3 5 10 20 60 |
| `--return-types T...` | arith and/or log | arith log |
| `--rolling-window N` | Rolling IC window size in bars | 63 |
| `--dry-run` | List qualifying pairs without computing | False |
| `--output-dir DIR` | Output directory for feature ranking CSV | reports/bakeoff/ |

### Parallelism

`_run_cmc_features_sweep()` supports `--workers N` via `multiprocessing.Pool.imap_unordered`. Each worker creates its own NullPool engine (picklable). Recommended: `--workers 4` to `--workers 8` for the full 100-TF run. The AMA sweep does NOT support workers (sequential only) but AMA is skipped here.

**Windows spawn requirement:** `_ic_worker` is module-level (not a lambda or nested function) for Windows `spawn` pickling — this is already correct in the code.

### Success Verification

```sql
SELECT COUNT(DISTINCT tf) FROM cmc_ic_results;
-- Must return 109
```

Post-sweep, the script automatically writes updated ranking to `reports/evaluation/feature_ic_ranking.csv`.

### AMA Gap Note

`cmc_ama_multi_tf_u` does not exist in the DB (confirmed by 55-VERIFICATION.md Gap 2). Use `--skip-ama` flag. Do not attempt to populate this table in Phase 62 — it is a future-phase dependency.

---

## Task 2: Populate dim_feature_registry with Promoted Features

### What Exists

Two-layer promotion system:
1. `src/ta_lab2/experiments/promoter.py` — `FeaturePromoter` class with `promote_feature()` method
2. `src/ta_lab2/scripts/experiments/promote_feature.py` — CLI wrapper

### dim_feature_registry Schema (HIGH confidence — from Alembic migration 6f82e9117c58)

Table: `public.dim_feature_registry`
- PK: `feature_name TEXT`
- `lifecycle TEXT` CHECK IN ('experimental', 'promoted', 'deprecated')
- `description`, `yaml_digest`, `compute_mode`, `compute_spec` — metadata from features.yaml
- `input_tables TEXT[]`, `input_columns TEXT[]`, `tags TEXT[]`
- `promoted_at TIMESTAMPTZ`, `promoted_by TEXT`
- `promotion_alpha NUMERIC`, `promotion_min_pass_rate NUMERIC`
- `best_ic NUMERIC`, `best_horizon INTEGER`
- `migration_stub_path TEXT` — path to Alembic stub generated on promotion
- `registered_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ`

### Features to Promote (HIGH confidence — from promotion_decisions.csv)

60 features with `action_taken=promote_recommended`. The promotion script reads from `cmc_feature_experiments` (not `cmc_ic_results`) using a Benjamini-Hochberg gate.

**CRITICAL DISTINCTION:** `promote_feature.py` reads from `cmc_feature_experiments` table (ExperimentRunner output), NOT from `cmc_ic_results` (IC sweep output). These are separate tables with different data.

### Promote CLI Reference

```bash
# Non-interactive promotion (--yes skips confirmation prompt)
python -m ta_lab2.scripts.experiments.promote_feature \
    --feature <feature_name> \
    --yes \
    --registry configs/experiments/features.yaml

# Dry-run to check BH gate before promoting
python -m ta_lab2.scripts.experiments.promote_feature \
    --feature <feature_name> \
    --dry-run
```

### Side Effect: Migration Stubs

`FeaturePromoter.promote_feature()` generates an Alembic migration stub in `alembic/versions/` for each feature. This is a known behavior. For the 60-feature batch, this means 60 stub files will be created. The stubs add NUMERIC nullable columns to cmc_features — they are not automatically applied. The plan must decide: run stubs or just populate dim_feature_registry without running alembic upgrade.

**Recommendation for Phase 62:** Populate dim_feature_registry (the registry record) for all 60 features. Alembic stubs are documentation artifacts only — do not run `alembic upgrade head` as part of this phase unless explicitly required.

### Batch Promotion Pattern

There is no batch-promotion script. Phase 62 needs either:
1. A shell loop calling `promote_feature.py --yes` for each of the 60 features, OR
2. A short Python script that calls `FeaturePromoter.promote_feature()` directly in a loop

The loop approach reading from `promotion_decisions.csv` is the cleanest pattern:

```python
# Conceptual pattern (to be implemented in a task)
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ta_lab2.experiments import FeaturePromoter, PromotionRejectedError
from ta_lab2.scripts.refresh_utils import resolve_db_url

df = pd.read_csv("reports/evaluation/promotion_decisions.csv")
to_promote = df[df["action_taken"] == "promote_recommended"]["feature_name"].tolist()

engine = create_engine(resolve_db_url(), poolclass=NullPool)
promoter = FeaturePromoter(engine)
for feature_name in to_promote:
    try:
        promoter.promote_feature(feature_name, confirm=False)
    except PromotionRejectedError as exc:
        print(f"SKIP {feature_name}: {exc.reason}")
```

### Verification

```sql
SELECT COUNT(*) FROM public.dim_feature_registry WHERE lifecycle = 'promoted';
-- Must return >= 60
```

---

## Task 3: Run 4 ML CLI Scripts with --log-experiment

### What Exists (HIGH confidence — read directly from source)

All 4 scripts are in `src/ta_lab2/scripts/ml/`:
- `run_feature_importance.py` — MDA/SFI feature importance
- `run_regime_routing.py` — RegimeRouter vs global model comparison
- `run_double_ensemble.py` — DoubleEnsemble vs static LGBM
- `run_optuna_sweep.py` — Optuna TPE hyperparameter sweep

All verified as complete in 60-VERIFICATION.md with status `human_needed` — infrastructure verified, live DB runs not yet executed.

### Script-by-Script CLI Reference

#### run_feature_importance.py

```bash
python -m ta_lab2.scripts.ml.run_feature_importance \
    --asset-ids 1,1027 \
    --tf 1D \
    --start 2023-01-01 \
    --end 2025-12-31 \
    --n-splits 5 \
    --mode both \
    --model rf \
    --output-csv reports/ml/feature_importance_1d.csv \
    --log-experiment
```

Key args: `--asset-ids` (comma-separated), `--mode` (mda/sfi/both), `--model` (rf/lgbm), `--log-experiment`

**Dependency:** `cmc_features` with `ret_arith` column and qualifying rows for given tf/date range.

#### run_regime_routing.py

```bash
python -m ta_lab2.scripts.ml.run_regime_routing \
    --asset-ids 1,1027 \
    --tf 1D \
    --start 2023-01-01 \
    --end 2025-12-31 \
    --n-splits 5 \
    --min-regime-samples 30 \
    --model lgbm \
    --log-experiment
```

**Dependency:** `cmc_features` + `cmc_regimes` (L2 labels via `l2_label` column). If cmc_regimes returns empty, script uses 'Unknown' for all rows — still runs but per-regime breakdown is trivial.

#### run_double_ensemble.py

```bash
python -m ta_lab2.scripts.ml.run_double_ensemble \
    --asset-ids 1,1027 \
    --tf 1D \
    --start 2023-01-01 \
    --end 2025-12-31 \
    --window-size 60 \
    --stride 15 \
    --n-splits 5 \
    --log-experiment
```

**Dependency:** `cmc_features` only. No regime data needed.

#### run_optuna_sweep.py

```bash
python -m ta_lab2.scripts.ml.run_optuna_sweep \
    --asset-ids 1,1027 \
    --tf 1D \
    --start 2023-01-01 \
    --end 2025-12-31 \
    --n-trials 50 \
    --n-splits 5 \
    --study-name lgbm_1d_sweep \
    --grid-comparison \
    --log-experiment
```

**Dependency:** `optuna` package must be installed. The script checks at startup and exits with clear error if missing. `lightgbm` is also required.

### Experiment Storage

All 4 scripts call `ExperimentTracker.ensure_table()` before logging. The `cmc_ml_experiments` table is created by Alembic migration `3caddeff4691`. Tracker uses `ON CONFLICT DO UPDATE` (upsert) via UUID PK.

### Output Documentation Requirement

The Success Criteria requires results to be IN `cmc_ml_experiments`. The plan must include capturing console output (stdout) and storing it alongside the experiment log entry for human documentation. The `--output-csv` flag on `run_feature_importance.py` writes ranked importance to CSV — use `reports/ml/` directory.

### Package Dependencies to Verify Before Running

| Script | Required Packages |
|--------|-------------------|
| run_feature_importance.py | sklearn (always available), lightgbm (optional with RF fallback) |
| run_regime_routing.py | sklearn, lightgbm (optional with RF fallback) |
| run_double_ensemble.py | sklearn, lightgbm (optional) |
| run_optuna_sweep.py | optuna (required, no fallback), lightgbm (required) |

Check: `python -c "import optuna; import lightgbm"` before running Optuna sweep.

---

## Task 4: Resolve RebalanceScheduler Orphan

### What Exists (HIGH confidence — read directly from source)

`src/ta_lab2/portfolio/rebalancer.py` (185 lines):
- `RebalanceScheduler` class with `should_rebalance()`, `parse_frequency()`, `_drift_triggered()`
- Three trigger modes: `time_based`, `signal_driven`, `threshold_based`
- No external callers — confirmed by grep across all `.py` files in `src/`

**Callers found:**
- `src/ta_lab2/portfolio/__init__.py` — imports `RebalanceScheduler` and re-exports it in `__all__`
- `src/ta_lab2/portfolio/rebalancer.py` — defines it

**Zero callers** in any script, signal generator, portfolio orchestrator, or backtest runner.

### Decision Guidance

The ROADMAP Success Criteria says: "RebalanceScheduler either wired into a calling script or removed (no orphaned code)."

**Remove is the correct choice** because:
1. Phase 58 VERIFICATION (passed 5/5) documents portfolio construction as complete, with `run_portfolio_backtest.py` as the primary orchestrator. That script does not call RebalanceScheduler.
2. Portfolio rebalancing in the existing backtest uses a simple time-based loop — no dynamic trigger logic needed.
3. Wiring it would require modifying `run_portfolio_backtest.py` with non-trivial integration work and a re-test of Phase 58 truths.
4. The class has full test coverage (it works as designed) but is disconnected from the portfolio pipeline by design gap, not an active need.

### Removal Scope

1. Delete `src/ta_lab2/portfolio/rebalancer.py`
2. Remove `from ta_lab2.portfolio.rebalancer import RebalanceScheduler` from `src/ta_lab2/portfolio/__init__.py`
3. Remove `RebalanceScheduler` from `__all__` list in `src/ta_lab2/portfolio/__init__.py`
4. Delete any test file for rebalancer if one exists

Check for test file:

```bash
find src tests -name "*rebalancer*" -o -name "*rebalance*"
```

### Verification

```bash
grep -r "RebalanceScheduler" src/ tests/
# Should return no matches after deletion
```

---

## Architecture Patterns

### This Phase Has No Architecture

Phase 62 is operational execution only. The patterns are:

1. **Run existing script** — verify preconditions, execute with documented flags, capture output
2. **Write to existing table** — verify count, do not modify schema
3. **Delete orphaned code** — remove file + __init__ import, verify no remaining references

### Execution Order

Tasks are independent but the IC sweep is the most time-intensive. Recommended order:

1. Start IC sweep first (background, 9-10 hours estimated)
2. Run 4 ML CLI scripts (parallel, each takes minutes to hours)
3. Execute feature promotions (sequential, ~60 iterations)
4. Delete RebalanceScheduler (instantaneous, needs test verification)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Batch feature promotion | New batch promotion logic | Loop over promotion_decisions.csv calling existing FeaturePromoter |
| IC sweep parallelism | Custom parallel IC | `--workers N` flag built into run_ic_sweep.py |
| Experiment logging | New logging layer | `--log-experiment` flag built into all 4 ML CLI scripts |
| BH gate logic | Custom significance test | FeaturePromoter.check_bh_gate() already implements this |

---

## Common Pitfalls

### Pitfall 1: promote_feature reads cmc_feature_experiments, NOT cmc_ic_results

**What goes wrong:** Developer assumes promoter reads the IC sweep output (cmc_ic_results). It reads `cmc_feature_experiments` (ExperimentRunner output). These are separate tables.

**How to avoid:** Verify `cmc_feature_experiments` is populated (67,788 rows from Phase 55) before running promotions. The 60 recommend-promote features already have rows there.

**Warning signs:** `ValueError: No experiment results found for feature 'X' in cmc_feature_experiments` — feature is not in cmc_feature_experiments, not cmc_ic_results.

### Pitfall 2: promote_feature.py generates Alembic migration stubs on every promotion

**What goes wrong:** 60 promotions generate 60 files in `alembic/versions/`. Running `alembic upgrade head` afterward applies all 60 stubs and adds 60 columns to cmc_features (not the intent of this phase).

**How to avoid:** Be explicit that migration stubs are created but NOT applied in this phase. The dim_feature_registry population is the goal, not the DDL migrations.

### Pitfall 3: IC sweep --no-overwrite flag for resumability

**What goes wrong:** Using `--overwrite` (default) on a restarted sweep recalculates and overwrites the 9 TFs already done. Using `--no-overwrite` skips already-computed (asset_id, tf, feature, horizon, return_type, regime) combinations.

**How to avoid:** Use `--no-overwrite` for the Phase 62 run to preserve the 82,110 existing rows. The 55-VERIFICATION.md explicitly specifies `--no-overwrite` in its closure command.

### Pitfall 4: optuna not installed

**What goes wrong:** `run_optuna_sweep.py` exits immediately with `SystemExit(1)` if optuna is not installed.

**How to avoid:** Verify `python -c "import optuna"` succeeds before executing the Optuna task. Install if missing: `pip install optuna`.

### Pitfall 5: Deleting RebalanceScheduler breaks tests

**What goes wrong:** Test files importing `RebalanceScheduler` fail to import after deletion.

**How to avoid:** Search `tests/` for rebalancer references before deletion:
```bash
grep -r "RebalanceScheduler\|rebalancer" tests/ 2>/dev/null
```

---

## Code Examples

### IC Sweep Dry Run (before full run)

```bash
# Source: run_ic_sweep.py --dry-run
python -m ta_lab2.scripts.analysis.run_ic_sweep --all --skip-ama --dry-run --min-bars 500
# Output: prints qualifying (asset_id, tf, n_rows) pairs
```

### Full IC Sweep Command (verified from 55-VERIFICATION.md)

```bash
python -m ta_lab2.scripts.analysis.run_ic_sweep \
    --all \
    --skip-ama \
    --no-overwrite \
    --workers 4 \
    --output-dir reports/evaluation
```

### Verify IC Sweep Count

```sql
-- Source: success criterion SC-1
SELECT COUNT(DISTINCT tf) FROM cmc_ic_results;
SELECT COUNT(*) FROM cmc_ic_results;
```

### Batch Promote Features (conceptual, to be written as task)

```python
# Source: promote_feature.py and promoter.py
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from ta_lab2.experiments import FeaturePromoter, PromotionRejectedError
from ta_lab2.scripts.refresh_utils import resolve_db_url

df = pd.read_csv("reports/evaluation/promotion_decisions.csv")
to_promote = df[df["action_taken"] == "promote_recommended"]["feature_name"].tolist()
# 60 features

engine = create_engine(resolve_db_url(), poolclass=NullPool)
promoter = FeaturePromoter(engine)
promoted, rejected, errors = [], [], []
for name in to_promote:
    try:
        promoter.promote_feature(name, confirm=False)
        promoted.append(name)
    except PromotionRejectedError as exc:
        rejected.append((name, exc.reason))
    except Exception as exc:
        errors.append((name, str(exc)))
print(f"Promoted: {len(promoted)}, Rejected: {len(rejected)}, Errors: {len(errors)}")
```

### Delete RebalanceScheduler

```bash
# 1. Delete the module
rm src/ta_lab2/portfolio/rebalancer.py
# 2. Edit src/ta_lab2/portfolio/__init__.py to remove:
#    from ta_lab2.portfolio.rebalancer import RebalanceScheduler
#    "RebalanceScheduler" in __all__
# 3. Verify
grep -r "RebalanceScheduler" src/
```

---

## State of the Art

| Old State | Current State | Notes |
|-----------|---------------|-------|
| 9/109 TFs in cmc_ic_results | Target: 109/109 TFs | Infrastructure complete; execution gap only |
| 0 rows in dim_feature_registry | Target: 60 rows (promoted lifecycle) | FeaturePromoter exists; needs to be called |
| 0 live ML experiments in cmc_ml_experiments | Target: >= 4 runs logged | 4 CLI scripts wired and verified structurally |
| RebalanceScheduler orphaned (0 callers) | Target: deleted | No wiring path identified |

---

## Open Questions

1. **Alembic stubs from batch promotion**
   - What we know: Each `promote_feature()` call generates one stub file in `alembic/versions/`
   - What's unclear: Should 60 stubs be immediately applied or left as artifacts?
   - Recommendation: Leave stubs unapplied in Phase 62. Document this explicitly in the plan. Running 60 migrations adds 60 columns to cmc_features without any compute logic wired — not useful.

2. **Some of the 60 features may fail BH gate**
   - What we know: `promoter.promote_feature()` raises `PromotionRejectedError` if BH gate fails
   - What's unclear: The promotion_decisions.csv already used BH gate results to set action_taken — but the promoter re-checks from live cmc_feature_experiments data at promotion time. There may be differences.
   - Recommendation: Use `--dry-run` for a sample feature before batch run. Log rejected features as exceptions rather than errors.

3. **run_feature_importance timing with mode=both and rf model**
   - What we know: MDA + SFI with 5 folds on ~100 features with RandomForest can be slow
   - What's unclear: Exact runtime with real 1D data for assets 1 and 1027
   - Recommendation: Start with `--mode mda` first to get a quick result, then `--mode sfi` separately if time allows.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/scripts/analysis/run_ic_sweep.py` — complete IC sweep implementation, all CLI args read directly
- `src/ta_lab2/scripts/experiments/promote_feature.py` — promotion CLI, all args read directly
- `src/ta_lab2/experiments/promoter.py` — FeaturePromoter implementation, full promotion pipeline
- `src/ta_lab2/portfolio/rebalancer.py` — RebalanceScheduler (185 lines, no external callers)
- `src/ta_lab2/scripts/ml/run_feature_importance.py` — MDA/SFI CLI, all args read directly
- `src/ta_lab2/scripts/ml/run_regime_routing.py` — regime routing CLI
- `src/ta_lab2/scripts/ml/run_double_ensemble.py` — DoubleEnsemble CLI
- `src/ta_lab2/scripts/ml/run_optuna_sweep.py` — Optuna CLI
- `alembic/versions/6f82e9117c58_feature_experiment_tables.py` — dim_feature_registry DDL
- `.planning/phases/55-feature-signal-evaluation/55-VERIFICATION.md` — current IC state, gap closure commands
- `.planning/phases/60-ml-infrastructure-experimentation/60-VERIFICATION.md` — ML CLI state (human_needed)
- `.planning/phases/58-portfolio-construction-sizing/58-VERIFICATION.md` — portfolio phase passed 5/5
- `reports/evaluation/promotion_decisions.csv` — 60 features with action_taken=promote_recommended

### Secondary (MEDIUM confidence)
- Grep across `src/` for `RebalanceScheduler` callers — confirmed 0 callers outside rebalancer.py and __init__.py

---

## Metadata

**Confidence breakdown:**
- IC sweep (Task 1): HIGH — implementation read directly, flags verified, gap closure command documented in VERIFICATION.md
- Feature promotions (Task 2): HIGH — promoter.py and promote_feature.py read directly; dim_feature_registry DDL from Alembic migration
- ML CLI scripts (Task 3): HIGH — all 4 scripts read directly; verified complete in 60-VERIFICATION.md
- RebalanceScheduler removal (Task 4): HIGH — grep confirms 0 callers; removal scope is clear

**Research date:** 2026-02-28
**Valid until:** 2026-03-28 (stable — no external dependencies)
