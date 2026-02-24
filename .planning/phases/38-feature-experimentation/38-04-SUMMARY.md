---
phase: 38-feature-experimentation
plan: "04"
subsystem: experimentation
tags: [scipy, benjamini-hochberg, alembic, migration-stub, feature-promotion, lifecycle]

# Dependency graph
requires:
  - phase: 38-01
    provides: dim_feature_registry and cmc_feature_experiments Alembic migration
  - phase: 38-02
    provides: FeatureRegistry YAML loader and resolve_experiment_dag
  - phase: 38-03
    provides: ExperimentRunner IC engine and scripts/experiments/__init__.py

provides:
  - FeaturePromoter class with BH gate, promotion pipeline, and migration stub generation
  - PromotionRejectedError exception with reason + bh_results attributes
  - promote_feature.py CLI with --dry-run, --yes, --alpha, --min-pass-rate, --registry
  - purge_experiment.py CLI with --dry-run, --yes, --force (deprecate vs hard-delete)

affects:
  - 38-05 (evaluation dashboard reads dim_feature_registry for promoted features)
  - future phases using promoted features in cmc_features refresh pipeline

# Tech tracking
tech-stack:
  added: [scipy.stats.false_discovery_control (BH correction)]
  patterns:
    - "BH gate pattern: filter NaN p-values before false_discovery_control(), use n_pass > 0 as default threshold"
    - "Live Alembic head query: SELECT version_num FROM alembic_version to avoid hardcoding down_revision"
    - "Non-destructive deprecation: lifecycle='deprecated' in registry, column stays in cmc_features"
    - "NullPool + resolve_db_url() for all CLI scripts"

key-files:
  created:
    - src/ta_lab2/experiments/promoter.py
    - src/ta_lab2/scripts/experiments/promote_feature.py
    - src/ta_lab2/scripts/experiments/purge_experiment.py
  modified:
    - src/ta_lab2/experiments/__init__.py

key-decisions:
  - "BH gate default: min_pass_rate=0.0 means at least one combo must pass (not all). Caller can raise via --min-pass-rate 0.5."
  - "Migration stub queries live alembic_version for down_revision (not hardcoded) -- avoids chain breaks when new migrations added"
  - "Deprecation is non-destructive: column stays in cmc_features, experiment rows stay in cmc_feature_experiments (audit trail)"
  - "purge_experiment default: deprecate registry entry (not delete). --force required for hard delete."
  - "_to_python() used for numpy scalar normalization before psycopg2 binding"

patterns-established:
  - "BH correction pattern: filter NaN first (false_discovery_control raises ValueError on NaN)"
  - "Migration stub pattern: UTF-8 encoding when writing (Windows cp1252 safety), live alembic_version query"

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 38 Plan 04: FeaturePromoter with BH Gate and Migration Stub Generation Summary

**BH-corrected promotion pipeline using scipy.stats.false_discovery_control, Alembic migration stub auto-generation from live DB head, and non-destructive deprecation via dim_feature_registry lifecycle column**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-24T12:26:15Z
- **Completed:** 2026-02-24T12:31:01Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- FeaturePromoter class (594 lines) with BH gate, promotion pipeline writing to dim_feature_registry, Alembic migration stub generation, and non-destructive deprecation
- PromotionRejectedError exception with descriptive reason string and bh_results DataFrame for diagnostics
- promote_feature.py CLI (167 lines) with --dry-run, --yes, --alpha, --min-pass-rate, --registry, --db-url
- purge_experiment.py CLI (145 lines) with --dry-run, --yes, --force (deprecate vs hard-delete), --db-url
- Updated __init__.py exports FeaturePromoter and PromotionRejectedError

## Task Commits

Each task was committed atomically:

1. **Task 1: FeaturePromoter class with BH gate and migration stub generation** - `af6459f2` (feat)
2. **Task 2: promote_feature.py and purge_experiment.py CLI scripts** - `2e4c5b7b` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/ta_lab2/experiments/promoter.py` - FeaturePromoter class: check_bh_gate(), promote_feature(), deprecate_feature(), _generate_migration_stub()
- `src/ta_lab2/experiments/__init__.py` - Updated exports: FeaturePromoter, PromotionRejectedError added
- `src/ta_lab2/scripts/experiments/promote_feature.py` - CLI for BH gate check + promotion with dry-run support
- `src/ta_lab2/scripts/experiments/purge_experiment.py` - CLI for purging experiment results with audit trail preservation

## Decisions Made

- **BH gate threshold**: min_pass_rate=0.0 by default (at least one combo must pass). Callers use --min-pass-rate 0.5 for stricter gates. This is more practical than requiring all combos to pass (many legitimate features have horizon-specific significance).
- **Live Alembic head**: Migration stub queries `SELECT version_num FROM alembic_version LIMIT 1` at runtime. Never hardcodes down_revision. Falls back to None if alembic_version table unavailable.
- **Non-destructive deprecation**: deprecate_feature() sets lifecycle='deprecated' in dim_feature_registry but does NOT remove the cmc_features column (requires downtime) and does NOT delete experiment rows (audit trail). purge_experiment.py also defaults to deprecate, not delete.
- **NaN filtering in BH**: false_discovery_control() raises ValueError on NaN inputs. check_bh_gate() filters NaN p-values before calling it, sets ic_p_value_bh=NaN for filtered rows, and returns (False, df, reason) when zero valid p-values exist.

## Deviations from Plan

None - plan executed exactly as written. One minor adaptation: the pre-commit hook (ruff format + mixed-line-ending) reformatted files after initial staging, requiring re-staging on both task commits. This is the normal Windows line-ending workflow for this project.

## Issues Encountered

- Pre-commit hook stash/restore behavior: after first commit attempt failed, it restored the pre-staged version of `__init__.py` (which contained the 38-03 content without FeaturePromoter exports). This was discovered when `promote_feature --help` failed on import. Fixed by re-editing `__init__.py` before staging Task 2 files.

## Next Phase Readiness

- FeaturePromoter ready for use in Plan 38-05 (evaluation dashboard / report generation)
- promote_feature CLI end-to-end flow requires live DB with cmc_feature_experiments data (generated by ExperimentRunner from Plan 38-03)
- Migration stubs are generated but not applied -- user must run `alembic upgrade head` after promotion
- promoted_features.py compute wiring is a manual step (documented in stub + CLI output)

---
*Phase: 38-feature-experimentation*
*Completed: 2026-02-24*
