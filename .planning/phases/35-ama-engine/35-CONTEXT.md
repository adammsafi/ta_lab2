# Phase 35: AMA Engine - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Compute and refresh Adaptive Moving Averages (KAMA, DEMA, TEMA, HMA) across all timeframes, with derivatives, z-scores, and unified table sync wired into the daily refresh pipeline. Full calendar parity with the existing EMA table family.

Requirements: AMA-01, AMA-02, AMA-03, AMA-04, AMA-05, AMA-06, AMA-07

</domain>

<decisions>
## Implementation Decisions

### Parameter Sets
- **KAMA**: Ship 2-3 parameter sets from day one — canonical (10/2/30), fast (5/2/15), slow (20/2/50). Each set has its own params_hash.
- **DEMA/TEMA/HMA**: Match existing EMA periods (9, 10, 21, 50, 200). These are straightforward — period is the only parameter.
- **Efficiency Ratio (ER)**: Store ER for all parameter sets that have a unique er_period. Each KAMA row already has a unique er_period, so ER gets stored for all of them.

### Table Structure
- **AMA returns**: Own returns table family — `cmc_returns_ama_multi_tf` (not shared with EMA returns). Different PK structure (indicator + params_hash) means different table.
- **Full calendar parity**: 12 AMA tables total — 6 value tables (multi_tf + 4 calendar variants + _u) and 6 returns tables (same pattern). Matches the EMA table family exactly.
- **_u unified table**: Uses `alignment_source` column from day one (even though multi_tf is the only source initially). Values slot in from calendar variants without schema changes.
- **Sync pattern**: Same as EMA _u — INSERT ... ON CONFLICT DO NOTHING with ingested_at watermark via existing sync_utils.py.

### Pipeline Integration
- **Own CLI flag**: `--amas` is a separate stage in `run_daily_refresh.py`, not bundled with `--emas`. Clean separation, can run independently.
- **Execution order**: AMAs run AFTER EMAs complete. DEMA/TEMA are compositional EMAs and need EMA values as input.
- **All 109 TFs from day one**: Full parity with EMAs — no subset. Same timeframe coverage.
- **All-in-one stage**: `--amas` computes values + returns + z-scores + _u sync in one pass. No separate stages for AMA returns or AMA z-scores.
- **Incremental from day one**: Same watermark-based refresh pattern as EMAs. No separate bulk backfill script — just run refresh.
- **Parallel workers**: Match EMA pattern with NullPool workers per asset. Required for 109 TFs x multiple assets.
- **Include in --all**: AMAs are first-class in `run_daily_refresh --all` from day one. Pipeline order: bars -> EMAs -> AMAs -> regimes -> features.
- **No cmc_features expansion**: Signal generators JOIN AMA tables directly (same as EMA pattern via LEFT JOIN on `cmc_ama_multi_tf_u`). No new columns in cmc_features.

### Calendar Variants Scope
- **Full calendar parity confirmed**: All 5 alignment variants (multi_tf, cal_us, cal_eu, cal_asia, cal_anchor) plus _u for both value and returns tables.
- **alignment_source column**: Present on _u tables from day one, matching EMA _u pattern.
- **12 tables total**: This is a scope expansion from what REQUIREMENTS.md originally listed (which deferred calendar variants). User confirmed: "same pattern, just more DDL."

### Claude's Discretion
- Shared vs. separate value tables for different AMA types (KAMA/DEMA/TEMA/HMA) — single `cmc_ama_multi_tf` with `indicator` column vs. separate tables per indicator
- Whether to create a `dim_ama_params` lookup table mapping params_hash to readable parameter values, or store params inline
- BaseAMAFeature class hierarchy design (sibling of BaseEMAFeature, not subclass — per research findings)
- DDL file organization (one file per table vs. grouped by family)
- Exact warmup guard thresholds per indicator type

</decisions>

<specifics>
## Specific Ideas

- AMAs follow the same pattern as EMAs — same table families, same sync utilities, same refresh pattern. "Just more DDL."
- KAMA's Efficiency Ratio is a standalone signal candidate for IC evaluation — store it queryable independently, not buried in params.
- DEMA = 2*EMA - EMA(EMA), TEMA = 3*EMA - 3*EMA(EMA) + EMA(EMA(EMA)) — compositional, not custom smoothing. HMA uses WMA (not EWM).
- PK pattern: `(id, ts, tf, indicator, params_hash)` — the params_hash is critical to avoid signal generator corruption when multiple parameter sets exist.

</specifics>

<deferred>
## Deferred Ideas

- KAMA crossover signal generator — compute and evaluate AMA values with IC first; signals come after validation (ADV-02, v1.0+)
- Calendar alignment variants were originally deferred but user pulled them into v0.9.0 scope during this discussion

</deferred>

---

*Phase: 35-ama-engine*
*Context gathered: 2026-02-23*
