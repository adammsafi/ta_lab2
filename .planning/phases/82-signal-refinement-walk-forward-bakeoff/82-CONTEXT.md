# Phase 82: Signal Refinement & Walk-Forward Bake-off - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Top features (20 active from Phase 80) combined into composite signals via expression engine, validated through walk-forward bake-off with statistical gates (DSR/PSR/PBO). Includes regime router training, multi-exchange cost matrices, and strategy selection for paper trading. Does NOT include portfolio construction (Phase 86), dashboard visualization (Phase 83), or live pipeline wiring (Phase 87).

</domain>

<decisions>
## Implementation Decisions

### Strategy archetypes & signal construction
- **All three archetypes:** Momentum/trend-following, mean-reversion, AND regime-conditional
- **Swing trading emphasis:** Signals should target swing trading timeframes (researcher determines optimal holding period based on IC decay and signal characteristics)
- **Experiment count:** Research decides optimal number of YAML expression engine experiments (roadmap minimum is 3)
- **Feature combination approach:** Test BOTH linear combinations (IC-IR weighted average) AND rule-based expression engine experiments -- let data decide which performs better
- **Regime router architecture:** Research decides whether regime router wraps expression engine (unified) or runs as separate experiments (independent comparison)
- **Data loading:** Expression engine and regime router MUST load from BOTH features table AND ama_multi_tf table (Phase 80 learning: 18/20 active features are AMA-derived)

### Walk-forward methodology
- **Window approach:** Test BOTH expanding AND rolling windows -- compare performance to determine which works better for crypto
- **Cost matrix:** Reuse existing 12-scenario Kraken cost matrix from Phase 42 bakeoff_orchestrator. ALSO create a Hyperliquid cost matrix and set up a framework for adding other exchange matrices
- **Fold count:** Research decides optimal number of walk-forward folds based on available data depth (~3 years)
- **Refit policy:** Test BOTH refit-at-each-fold AND train-once-evaluate-forward -- compare to see if refitting adds value vs overfitting risk

### Statistical gates & strategy selection
- **DSR threshold:** Research calibrates optimal DSR threshold based on the distribution of results (roadmap says 0.95 but researcher may adjust)
- **PBO gate:** Include PBO < 0.50 from existing CPCV infrastructure (Phase 42)
- **Additional gates:** Research decides what else to apply (drawdown cap, min trade count, etc.)
- **Survivor policy:** ALL strategies that pass the gates go to paper trading (not capped at top N)
- **Documentation:** Markdown report + DB persistence (backtest_metrics with experiment lineage)

### Per-asset customization depth
- **Feature weights:** Research decides whether per-asset IC-IR weights add value vs universal weights
- **Strategy assignment:** Test BOTH uniform (same strategy, all assets) AND per-asset strategy assignment -- compare in bake-off
- **Asset scope:** All 99 assets included in the bake-off (full universe)
- **Holding period:** Research decides optimal holding period per strategy based on signal characteristics and IC decay analysis

### Claude's Discretion
- Exact YAML experiment definitions (feature combinations, thresholds, interaction terms)
- Regime router architecture (TRA training details, per-regime model structure)
- Walk-forward fold size and refit frequency
- Report formatting and visualization
- How to handle assets with insufficient history for walk-forward evaluation
- Expression engine syntax and rule complexity

</decisions>

<specifics>
## Specific Ideas

- Swing trading is the primary use case -- signals should not be too short-term (day trading) or too long (position trading). The IC decay analysis from Phase 80 and signal holding period analysis should inform this.
- Per-asset IC-IR variation was the key Phase 80 finding -- the bake-off must surface whether per-asset customization improves results or just overfits.
- AMA features dominate the active tier (18/20) -- signal construction must not be limited to the features table; ama_multi_tf is the primary data source.
- Conditional tier (160 features) contains traditional TA features (RSI, MACD, ADX, Bollinger) -- regime router should evaluate these as regime specialists.
- Hyperliquid cost matrix is needed alongside Kraken -- both exchanges are relevant for live trading.

</specifics>

<deferred>
## Deferred Ideas

- Per-asset GARCH variant auto-selection (best GARCH model per asset) -- future phase
- Intraday signal generation (sub-daily) -- not in scope, daily/swing only
- Strategy-specific vol targeting (momentum vs mean-reversion use vol differently) -- Phase 86
- Cost matrices for additional exchanges beyond Kraken and Hyperliquid -- add as needed when new exchanges are onboarded

</deferred>

---

*Phase: 82-signal-refinement-walk-forward-bakeoff*
*Context gathered: 2026-03-22*
