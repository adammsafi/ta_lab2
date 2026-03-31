# Phase 98: CTF Feature Graduation - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Materialize top CTF (cross-timeframe) features into the main `features` table for downstream consumers (BL optimizer, signals, ML). Add asset-specific selection tiers, cross-asset composite signals (sentiment, relative-value, leader-follower), and lead-lag IC analysis. CTF infrastructure (Phase 89-92) is complete; this phase graduates the best features into production.

</domain>

<decisions>
## Implementation Decisions

### Feature Promotion Criteria
- IC threshold: **IC > 0.02** (active tier), matching existing dim_feature_selection convention from Phase 80/92
- Count: **All passing features** — no artificial cap at 15-20. Promote every CTF feature that passes IC > 0.02
- Selection mode: **Static snapshot, re-run manually** — run IC sweep, lock promoted set in feature_selection.yaml. Re-run when desired
- IC aggregation: **Cross-asset median IC** — features must work broadly across tier-1 assets, not just BTC

### Asset-Specific Tier Design
- Per-asset threshold: **Same IC > 0.02**, evaluated per individual asset
- Sparse assets: **Empty is fine** — if no features pass per-asset, that asset just has no asset-specific features. Global set still applies
- Tier relationship: **Superset** — every asset gets the global promoted set PLUS any additional features that pass per-asset IC
- Storage: **One row per (feature, asset_id) with tier='asset_specific'** in dim_feature_selection. asset_id=NULL for global tier, populated for asset-specific

### Cross-Asset Composite Definitions
- **Sentiment composite:** Both methods — cross-asset mean as primary actionable signal, PCA first component as secondary research column. TODO: study the difference between mean and PCA approaches after initial data is available
- **Relative-value composite:** Cross-sectional z-score of CTF features across assets per timestamp. Shows which assets are rich/cheap relative to peers
- **Leader-follower composite:** Lagged cross-correlation as primary metric (fast, intuitive lead/lag score), Granger causality test as validation check on top leaders
- **Storage:** Both — dedicated `ctf_composites` table for normalized storage, materialize top composites into `features` table for BL/signal consumers

### Lead-Lag IC Scope & Persistence
- Asset pairs: **All-vs-all tier-1** (~109 x 109 pairs). Comprehensive
- Horizons: **[1, 3, 5] bars** as specified in SC. TODO: test adding 10/21 or longer horizons at a later time
- Persistence: **Both DB + CSV** — `lead_lag_ic` table for programmatic access, CSV report for human review
- Significance: **FDR correction (Benjamini-Hochberg)** — store all results in DB, flag which pass FDR. Essential given ~11K pairs to control false discovery rate

### Claude's Discretion
- Exact PCA sign-correction method
- ctf_composites table schema details
- Granger test lag order selection
- Materialization frequency for composites in features table

</decisions>

<specifics>
## Specific Ideas

- Sentiment mean + PCA comparison is explicitly a research item — build both, compare, decide which to keep based on IC analysis
- FDR correction is a one-liner via scipy.stats.false_discovery_control or statsmodels multipletests
- Leader-follower Granger validation only runs on top leaders identified by lagged correlation (not all 11K pairs)

</specifics>

<deferred>
## Deferred Ideas

- Study mean vs PCA sentiment composite effectiveness — todo after Phase 98 data available
- Expand lead-lag horizons to [1, 3, 5, 10, 21] — todo after initial [1,3,5] results reviewed
- Rolling re-selection of promoted features (quarterly/monthly) — future enhancement if feature churn is observed

</deferred>

---

*Phase: 98-ctf-feature-graduation*
*Context gathered: 2026-03-31*
