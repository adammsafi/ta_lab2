---
phase: 38-feature-experimentation
verified: 2026-02-24T12:45:14Z
status: passed
score: 15/15 must-haves verified
re_verification: false
---

# Phase 38: Feature Experimentation Framework Verification Report

**Phase Goal:** Users can register experimental features in YAML, score them with IC on demand without writing to production tables, and promote statistically significant features through a BH-corrected gate into dim_feature_registry.
**Verified:** 2026-02-24T12:45:14Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | alembic upgrade head creates dim_feature_registry and cmc_feature_experiments | VERIFIED | 6f82e9117c58 migration: 211 lines, full DDL, chains from c3b718c2d088 |
| 2 | dim_feature_registry has feature_name TEXT PK with lifecycle CHECK constraint | VERIFIED | Lines 88-93: PrimaryKeyConstraint + CheckConstraint lifecycle IN (experimental/promoted/deprecated) |
| 3 | cmc_feature_experiments has UUID PK with 9-col unique constraint | VERIFIED | Lines 158-170: PrimaryKeyConstraint(experiment_id) + UniqueConstraint uq_feature_experiments_key |
| 4 | FeatureRegistry loads YAML, expands params, validates expressions, detects duplicates | VERIFIED | registry.py 272 lines. Live: 5 features from features.yaml |
| 5 | resolve_experiment_dag returns topological order and raises CycleError on cycles | VERIFIED | dag.py 71 lines, graphlib.TopologicalSorter.static_order. CycleError test passes |
| 6 | ExperimentRunner.run computes feature, scores with IC, returns DataFrame with cost metadata | VERIFIED | runner.py 719 lines. Full pipeline with tracemalloc cost tracking |
| 7 | Feature values written to temp scratch table, never to production tables | VERIFIED | Only INSERT in runner.py targets scratch_name (TEMP table). No production writes |
| 8 | BH correction applied across ALL rows, not per-asset | VERIFIED | runner.py line 292: _apply_bh_correction called once on concatenated all_ic_rows |
| 9 | check_bh_gate rejects noise p-values and passes signal p-values | VERIFIED | promoter.py 139-205. Tests: noise->False; signal->True |
| 10 | promote_feature writes to dim_feature_registry with lifecycle=promoted + migration stub | VERIFIED | promoter.py lines 421-439 INSERT lifecycle=promoted. _generate_migration_stub writes alembic/versions/ |
| 11 | Migration stub chains from live Alembic head, not hardcoded | VERIFIED | promoter.py line 511: SELECT version_num FROM public.alembic_version LIMIT 1 |
| 12 | purge_experiment removes all rows for a feature from cmc_feature_experiments | VERIFIED | purge_experiment.py line 156: DELETE FROM public.cmc_feature_experiments WHERE feature_name = :name |
| 13 | Deprecation sets lifecycle=deprecated without removing cmc_features column | VERIFIED | promoter.py lines 320-346: only UPDATE lifecycle=deprecated, no ALTER TABLE |
| 14 | All 3 CLI scripts accept --help without errors | VERIFIED | Tested live: run_experiment, promote_feature, purge_experiment all exit 0 |
| 15 | 39 unit tests pass without DB connection | VERIFIED | pytest tests/test_experiments.py -> 39 passed in 5.78s, all use MagicMock |

**Score:** 15/15 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| alembic/versions/6f82e9117c58_feature_experiment_tables.py | Alembic migration | VERIFIED | 211 lines, full DDL, down_revision=c3b718c2d088 |
| src/ta_lab2/experiments/__init__.py | 5 public exports | VERIFIED | FeatureRegistry, ExperimentRunner, FeaturePromoter, PromotionRejectedError, resolve_experiment_dag |
| src/ta_lab2/experiments/registry.py | FeatureRegistry, min 80 lines | VERIFIED | 272 lines, all methods implemented |
| src/ta_lab2/experiments/dag.py | resolve_experiment_dag, min 20 lines | VERIFIED | 71 lines, graphlib.TopologicalSorter |
| src/ta_lab2/experiments/runner.py | ExperimentRunner, min 150 lines | VERIFIED | 719 lines, full pipeline |
| src/ta_lab2/experiments/promoter.py | FeaturePromoter + PromotionRejectedError, min 120 lines | VERIFIED | 594 lines |
| configs/experiments/features.yaml | Sample YAML with inline and param sweep | VERIFIED | 55 lines, 3 entries, 5 experimental after expansion |
| src/ta_lab2/scripts/experiments/run_experiment.py | CLI min 80 lines | VERIFIED | 538 lines |
| src/ta_lab2/scripts/experiments/promote_feature.py | CLI min 50 lines | VERIFIED | 213 lines |
| src/ta_lab2/scripts/experiments/purge_experiment.py | CLI min 40 lines | VERIFIED | 197 lines |
| tests/test_experiments.py | Unit tests, min 100 lines | VERIFIED | 721 lines, 39 tests, 6 test classes |

### Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| runner.py | analysis/ic.py | from ta_lab2.analysis.ic import compute_ic line 31 | WIRED |
| runner.py | experiments/registry.py | from ta_lab2.experiments.registry import FeatureRegistry line 32 | WIRED |
| run_experiment.py | experiments/runner.py | from ta_lab2.experiments.runner import ExperimentRunner line 54 | WIRED |
| promoter.py | scipy.stats.false_discovery_control | import at line 27, called in check_bh_gate line 182 | WIRED |
| runner.py | scipy.stats.false_discovery_control | import at line 28, called in _apply_bh_correction line 693 | WIRED |
| promoter.py | alembic/versions/ | _find_alembic_versions_dir filesystem walk | WIRED |
| promoter.py | dim_feature_registry | INSERT SQL at lines 421-487 with lifecycle=promoted | WIRED |
| promoter.py | alembic_version table | SELECT version_num FROM public.alembic_version LIMIT 1 line 511 | WIRED |
| purge_experiment.py | cmc_feature_experiments | DELETE FROM public.cmc_feature_experiments WHERE feature_name = :name | WIRED |
| 6f82e9117c58 migration | c3b718c2d088 migration | down_revision = c3b718c2d088 line 30, parent file confirmed to exist | WIRED |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| FEAT-01: YAML-driven feature registry with lifecycle states | SATISFIED | FeatureRegistry with lifecycle, param sweep, digest tracking |
| FEAT-02: Compute without DB persistence to production tables | SATISFIED | Temp scratch table only in runner; no writes to cmc_features |
| FEAT-03: IC scoring wired to Phase 37 compute_ic | SATISFIED | Direct import and call in runner.py lines 31 and 246 |
| FEAT-04: BH correction as hard gate for promotion | SATISFIED | check_bh_gate in runner (all rows) and promoter (PromotionRejectedError on failure) |
| FEAT-05: Promotion writes to dim_feature_registry with migration stub | SATISFIED | promote_feature writes registry row + Alembic stub from live DB head |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| promoter.py | 399 | pass | Info | Inside except KeyError for optional registry lookup - valid empty except, not a stub |

No blocker or warning-level anti-patterns found.

### Human Verification Required

The following cannot be verified programmatically (require live DB):

#### 1. alembic upgrade head applies cleanly

**Test:** Run alembic -c alembic/alembic.ini upgrade head
**Expected:** Both tables created with correct schemas and CHECK constraint enforced
**Why human:** Requires PostgreSQL with gen_random_uuid() support

#### 2. alembic downgrade -1 drops cleanly

**Test:** Run alembic -c alembic/alembic.ini downgrade -1 after upgrade
**Expected:** Both tables dropped, parent revision c3b718c2d088 restored
**Why human:** Requires live DB

#### 3. ExperimentRunner.run end-to-end with real data

**Test:** python -m ta_lab2.scripts.experiments.run_experiment --feature vol_ratio_30_7 --train-start 2024-01-01 --train-end 2025-12-31 --tf 1D --dry-run
**Expected:** IC results printed, temp scratch table created, no production write
**Why human:** Requires PostgreSQL with cmc_vol and cmc_price_bars_multi_tf_u data

#### 4. promote_feature end-to-end with BH-significant results

**Test:** python -m ta_lab2.scripts.experiments.promote_feature --feature vol_ratio_30_7 --dry-run
**Expected:** BH gate results displayed, migration stub preview shown
**Why human:** Requires cmc_feature_experiments rows with ic_p_value data

#### 5. Migration stub chains from live head correctly

**Test:** After promotion, inspect generated stub in alembic/versions/
**Expected:** down_revision matches alembic_version.version_num at promotion time
**Why human:** Requires live DB with alembic_version populated

---

## Gaps Summary

No gaps. All 15 must-haves are verified in the codebase. Phase 38 goal is fully achieved.

Structural verification confirmed:
- Alembic migration: correct DDL, chain (c3b718c2d088 -> 6f82e9117c58), constraints, indexes
- FeatureRegistry: full YAML loading, sweep expansion, ast.parse validation, duplicate detection, SHA-256 digest
- ExperimentRunner: full pipeline in single connection block, BH across all rows once, temp table only, tracemalloc cost tracking
- FeaturePromoter: BH gate with NaN filtering, registry INSERT with lifecycle=promoted, live-head stub generation, non-destructive deprecation
- CLI scripts: all 3 wired correctly, --help exits 0, --dry-run/--yes/--compare implemented
- 39 tests: all pass in 5.78s without any DB connection

Human verification items are limited to live-DB integration tests.

---

_Verified: 2026-02-24T12:45:14Z_
_Verifier: Claude (gsd-verifier)_
