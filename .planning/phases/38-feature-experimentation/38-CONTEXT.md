# Phase 38: Feature Experimentation Framework - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Register experimental features in YAML, score them with IC on demand without writing to production tables, and promote statistically significant features through a BH-corrected gate into `dim_feature_registry`. Includes deprecation workflow and computation cost tracking.

Requirements: FEAT-01, FEAT-02, FEAT-03, FEAT-04, FEAT-05

Does NOT include IC evaluation itself (Phase 37), dashboard visualization (Phase 39), or notebook walkthroughs (Phase 40).

</domain>

<decisions>
## Implementation Decisions

### Feature Definition Contract
- **Dual compute mode**: Simple features use inline pandas expressions in YAML (e.g., `close.rolling(14).std() / close`); complex features reference a Python dotpath (e.g., `ta_lab2.experiments.my_feature:compute`). Runner auto-detects which mode from the YAML entry.
- **Data inputs**: Features can reference ANY persisted table (bars, EMAs, AMAs, vol, TA, regimes). No restrictions to bar data only.
- **Parameter sweeps**: Claude's discretion — grid expansion in YAML or one-entry-per-variant.
- **YAML location**: Claude's discretion — pick based on existing project config conventions.

### Experiment Execution Model
- **Three invocation paths**: CLI script for batch runs, Python API (`ExperimentRunner.run()`) for programmatic use, plus a thin notebook wrapper that renders results inline with Plotly.
- **Default scope**: If `--ids` omitted, run all assets in `dim_assets`. If `--tf` omitted, run all TFs. Matches daily refresh "all" behavior.
- **Results presentation**: Console summary table + confirm prompt before DB write (`Write to cmc_feature_experiments? [y/N]`). Batch mode can bypass with `--yes` flag.
- **Comparison mode**: Auto-compare against prior runs is supported via `--compare` flag, but default is standalone results (no comparison). When enabled, shows delta IC and significance improvement/regression.

### Promotion Workflow
- **Promotion confirmation**: Interactive confirm by default; `--auto-promote` CLI flag for batch workflows.
- **Full promotion pipeline**: On promotion, create (1) `dim_feature_registry` entry with `lifecycle: promoted`, (2) Alembic migration stub (ALTER TABLE ADD COLUMN), AND (3) wire the feature into `cmc_features` refresh pipeline.
- **Breadth gate**: Configurable `--min-pass-rate` threshold (default: any single (asset, TF, horizon) passes BH at alpha=0.05). Can be set stricter (e.g., 0.5 for majority-of-assets).
- **Deprecation**: Claude's discretion — should mirror promotion workflow symmetry.

### Production Boundary
- **Experimental feature dependencies**: Yes — ExperimentRunner resolves a DAG of experimental feature dependencies and computes them in order. Experimental features can reference other experimental features.
- **Compute space**: Feature values written to a DB scratch/temp table during computation, dropped after IC scoring. Allows SQL-based inspection during debugging. Only IC results persist in `cmc_feature_experiments`.
- **Cost tracking**: Track wall-clock time, peak memory, and row count per experiment run. Stored in `cmc_feature_experiments` alongside IC results.
- **Cleanup policy**: Results persist by default when YAML entry is removed. Explicit `purge_experiment --feature my_rsi` CLI command removes all traces from DB when needed.

### Claude's Discretion
- Parameter sweep approach (grid expansion vs one-entry-per-variant)
- YAML file location (configs/ vs src/)
- Deprecation workflow symmetry with promotion
- DAG resolution strategy for experimental feature dependencies
- Temp table naming convention and cleanup timing
- Exact cmc_feature_experiments schema (columns beyond IC results + cost)
- dim_feature_registry schema design
- How "wire into cmc_features refresh" works mechanically after promotion

</decisions>

<specifics>
## Specific Ideas

- Three-mode invocation (CLI + API + notebook) mirrors the IC evaluation pattern from Phase 37
- Confirm-before-write pattern with `--yes` bypass is consistent with existing destructive-action patterns in the codebase
- Temp table approach allows debugging via psql during long experimental runs without polluting production tables
- BH correction uses `scipy.stats.false_discovery_control()` — already a project dependency
- DAG resolution for experimental feature dependencies is an ambitious choice — keeps the framework powerful for compositional features

</specifics>

<deferred>
## Deferred Ideas

- Automated scheduled experiment re-evaluation (cron-like) — separate infrastructure concern
- Cross-asset pooled experiments — depends on ADV-01 quantile returns architecture (v1.0+)
- IC-driven automated feature selection without human review — contradicts the confirm-before-promote philosophy

</deferred>

---

*Phase: 38-feature-experimentation*
*Context gathered: 2026-02-23*
