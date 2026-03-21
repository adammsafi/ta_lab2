# Phase 80: IC Analysis & Feature Selection - Context

**Gathered:** 2026-03-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Reduce the 112-feature universe to ~15-25 validated features with persistent alpha, backed by statistical rigor. Add stationarity and autocorrelation tests to the analysis toolkit. Produce a tiered feature selection config consumed by downstream phases (expression engine, regime router, bake-off). Nothing is permanently discarded — features not selected remain accessible for future regimes or market conditions.

</domain>

<decisions>
## Implementation Decisions

### Selection Criteria & Thresholds
- **IC-IR cutoff:** |IC-IR| > 0.3 for the active set (moderate threshold — captures meaningful signal without being too permissive)
- **IC decay:** Informational only — document decay profiles across horizons but do NOT use decay as a filter criterion
- **Regime-conditional IC:** Tiered approach — universal features form a "core" set (good IC across regimes), regime-specialist features form a "conditional" set (strong IC in specific regimes, used by regime router)
- **Soft archive philosophy:** Nothing is permanently discarded. Features that don't make the active set remain documented and accessible. The system should support re-evaluation as market conditions evolve.

### Statistical Test Battery
- **Stationarity (ADF/KPSS):** Soft gate — non-stationary features need stronger IC evidence (higher threshold) to stay in the active set; they are NOT auto-excluded since some non-stationary features (momentum, trend) are deliberately trending
- **Ljung-Box (autocorrelation):** Claude's discretion on p-value threshold — flag features where IC signal may be inflated by serial correlation
- **Turnover filter:** Enabled — compute_feature_turnover() already exists; flag low-turnover features that may be capturing slow-moving state rather than alpha
- **Test scope:** Both per-asset AND aggregated — per-asset tests stored in DB, aggregate summary drives selection decisions

### Feature Set Output Format
- **Storage:** YAML config as source of truth (version-controlled, human-readable, editable) + mirrored to DB table (dim_feature_selection or similar) for runtime queries by other scripts
- **Asset granularity:** Universal core set + per-asset conditional extras if IC warrants it
- **Timeframe granularity:** Claude's discretion based on what the IC data reveals
- **Re-evaluation cadence:** Manual on-demand + monthly automated re-evaluation with alerts when the set changes significantly (feature promotions/demotions)

### Claude's Discretion
- Feature archival tier design (e.g., Active / Watch / Archive or similar)
- Concordance methodology — how to reconcile IC-IR vs MDA rankings when they disagree (IC-IR primary or ensemble vote — Claude designs the best approach based on data)
- Correlated feature cluster handling — pick 1 best per cluster, keep 2-3 per cluster, or adapt based on cluster size and correlation strength
- Quintile spread as concordance signal — whether to use it as a selection vote or validation-only
- Concordance reporting format (table, Venn diagram, ranked list with scores — whatever is most informative)
- Per-timeframe vs universal feature set — decide based on IC data patterns
- Ljung-Box p-value threshold — pick what's appropriate for the data

</decisions>

<specifics>
## Specific Ideas

- "Things change over time — I don't want to necessarily throw away things that could have use during certain circumstances in the future" — this is the driving principle. The feature selection system must be a living document, not a one-time purge.
- The IC sweep infrastructure is already built (run_ic_sweep.py, run_ic_eval.py, run_ic_decay.py, run_quintile_sweep.py) — this phase adds statistical rigor on top and produces the curated output.
- MDA, SFI, and clustered MDA are already implemented in ml/feature_importance.py — this phase runs them and integrates results with IC analysis.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 80-ic-analysis-feature-selection*
*Context gathered: 2026-03-21*
