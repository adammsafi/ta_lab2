# Phase 27: Regime Integration - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Connect existing regime module (labels, policy resolver, hysteresis, data budget) to DB-backed feature pipeline. Write refresh_cmc_regimes.py that reads from cmc_features and calendar bar tables, runs L0-L2+ labeling, resolves policy, writes to regime tables. Wire regime context into all 3 signal generators with full policy enforcement.

</domain>

<decisions>
## Implementation Decisions

### Regime Layer Scope
- Wire ALL layers (L0-L4) with graceful skip via data_budget auto-disable
- CLI overrides for min bar thresholds (--min-bars-l0, etc.) for experimentation
- Implement real hysteresis (not just the stub) to prevent rapid regime flipping
- Simplified DB flow: query bars/EMAs from DB, map columns, run labelers, resolve — skip resampling/enrichment since bars and EMAs already exist
- Use proxies for young assets without enough bar history (infer_cycle_proxy, infer_weekly_macro_proxy)
- Include labels + flips + stats — full regime analytics, not just labels
- Include comovement stats (EMA alignment, sign agreement, lead-lag) in the refresh pipeline
- Support YAML overlay for policy table via --policy-file flag
- DB-only telemetry — no separate CSV logging, query regime table for analysis
- Incremental refresh with watermarks — track last-computed timestamp per asset, match feature pipeline pattern
- regime_inspect.py: default reads from DB, add --live flag for ad-hoc on-the-fly computation
- Wire into run_daily_refresh.py orchestrator AND work as standalone script

### EMA Period Mapping
- Add EMA period 20 to the pipeline (don't map 20→21)
- Column renaming in Python after loading (df.rename before passing to labelers), not in SQL
- Pre-compute weekly ATR in feature pipeline (add to cmc_ta for weekly TF via existing TAFeature class)
- Calendar EMA tables (cmc_ema_multi_tf_cal_iso, _cal_us) already exist with weekly/monthly EMAs — query those
- **IMPORTANT**: During planning, researcher must review ALL DB tables and relevant ta_lab2 files thoroughly

### Signal Integration Depth
- Full policy enforcement: apply all TightenOnlyPolicy fields (size_mult, stop_mult, orders, setups, gross_cap, pyramids)
- Wire all 3 signal generators at once (RSI mean revert, EMA crossover, ATR breakout)
- Add regime_key column to signal tables — record which regime was active at signal entry
- Add --no-regime flag to signal refreshers for A/B comparison backtesting
- Detailed per-signal logging when regime filters or resizes a signal
- Review DEFAULT_POLICY_TABLE values during planning/research against quant sizing conventions
- Implement pyramiding logic — signal generators support multi-add when regime allows
- Regime transitions mid-position: note but don't force exit (needs more study)
- Per-signal regime config in dim_signals params (regime_enabled flag) — some signals can opt out

### Claude's Discretion
- SQL join vs separate load+merge for signal generators querying regime context
- Order type handling (record as metadata vs enforce in signal records) given current backtest infrastructure
- Comovement table placement (separate cmc_regime_comovement vs added to cmc_regimes)
- SQL DDL file organization (new sql/regimes/ directory vs flat in sql/)
- Write pattern for regime tables (scoped DELETE+INSERT vs upsert ON CONFLICT)
- Whether to create a convenience view joining cmc_regimes + cmc_features

### Output Table Design
- PK: (id, ts, tf) — match feature table pattern
- Full denormalized columns: individual layer labels (l0_trend, l1_vol, l2_liquidity, l3_spread), regime_key, plus all policy fields as columns
- Separate cmc_regime_flips table (id, ts, tf, old_regime, new_regime, duration_bars)
- Materialized cmc_regime_stats summary table (pre-computed stats per asset, refreshed alongside regimes)
- Include regime_version_hash column for reproducibility and drift detection

</decisions>

<specifics>
## Specific Ideas

- Existing old_run_btc_pipeline.py provides a working end-to-end reference — simplified for DB-backed flow
- Regime module is 13 files, fully built — this is integration work, not greenfield
- Calendar-anchored weekly/monthly bars already exist in 4 table variants (cal_iso, cal_us, cal_anchor_iso, cal_anchor_us)
- Data budget graceful degradation is already built in — auto-disables layers without sufficient bar history
- Tighten-only semantics mean regime can only reduce risk, never increase it — important safety property

</specifics>

<deferred>
## Deferred Ideas

- Regime-forced exits on transitions (needs more study on hysteresis interaction)
- Intraday regime classification (L3/L4 will be auto-disabled until intraday data is available)
- Regime-aware order execution (limit vs market) — depends on Phase 28 backtest pipeline working first

</deferred>

---

*Phase: 27-regime-integration*
*Context gathered: 2026-02-20*
