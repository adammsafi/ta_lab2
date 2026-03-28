# Phase 92: CTF IC Analysis & Feature Selection - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Score CTF features through the existing IC pipeline, identify which cross-timeframe indicators have genuine predictive power, compare against AMA features, classify into tiers, and prune ctf_config.yaml to retain only high-IC combinations. CTF data is already populated (Phase 91). IC analysis tools exist (Phase 80).

</domain>

<decisions>
## Implementation Decisions

### Pivot loader design
- Include ALL 6 values per indicator x ref_tf: ref_value, base_value, slope, divergence, agreement, crossover
- Pivot ALL combinations (22 indicators x 6 ref_tfs x 6 values = 792 potential columns) -- let IC sort out which matter, prune after
- Column naming: `{indicator_name}_{ref_tf}_{composite}` (e.g., `rsi_14_7d_slope`)
- Include NULL composites (agreement/crossover for non-directional indicators) -- IC pipeline handles NULLs naturally

### IC analysis scope
- Analyze ALL 109 assets (full universe, not just BTC)
- Analyze ALL 6 base TFs (1D, 2D, 3D, 7D, 14D, 30D)
- Forward return horizons: match Phase 80 (1d, 5d, 10d, 21d)
- No pre-filtering -- comprehensive analysis first, prune based on results

### Comparison & pruning criteria
- IC-IR cutoff: 0.5 (lower than Phase 80's 1.0 -- CTF is new, give room to prove value)
- Comparison: BOTH redundancy check (correlation between CTF and AMA IC series) AND head-to-head IC-IR comparison
- Pruning approach: tiered (active/conditional/watch/archive) matching Phase 80 tier system -- only archive truly dead combos
- Keep all 6 base TFs regardless of results -- cheap to maintain, preserve optionality

### Output & persistence
- Persist CTF feature scores to a SEPARATE table (not dim_feature_selection) -- keep CTF analysis independent from Phase 80 entries
- Write structured comparison report to file (not just stdout) -- detailed JSON/markdown in .planning/ or reports/
- Pruned config written as NEW file (ctf_config_pruned.yaml) -- preserve original ctf_config.yaml for reference
- Run script should also print summary to terminal for quick review

### Claude's Discretion
- Pivot loader location (cross_timeframe.py vs analysis/ module) -- pick based on codebase patterns
- Memory handling for large pivots (per-asset vs batch) -- pick based on IC pipeline requirements
- Whether to prune indicators section (remove dead indicators) or only ref_tf pairs -- recommend based on what the data shows

</decisions>

<specifics>
## Specific Ideas

- Phase 80 established the tier system (active/conditional/watch/archive) with IC-IR and stationarity gates -- reuse that exact framework for CTF features
- The key question for the comparison report: "Does CTF add NON-REDUNDANT alpha beyond what AMA features already provide?"
- 18/20 active features from Phase 80 are AMA-derived -- CTF's value proposition is diversifying away from AMA dominance

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 92-ctf-ic-analysis-feature-selection*
*Context gathered: 2026-03-23*
