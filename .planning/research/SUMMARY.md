# Project Research Summary

**Project:** ta_lab2 v1.0.1 -- Macro Regime Infrastructure
**Domain:** Adding FRED-sourced macro regime overlay to an existing multi-layer per-asset regime system in a crypto trading platform
**Researched:** 2026-03-01
**Confidence:** HIGH

## Executive Summary

v1.0.1 adds a macro regime layer to ta_lab2's existing L0-L4 tighten-only policy resolver. The architecture is overwhelmingly in our favor: the resolver already accepts an L4 parameter (currently hardcoded to None), the `cmc_regimes` table already has an `l4_label` column (always NULL), and `data_budget.py` already sets L4's threshold to 1 (always enabled). The FRED data is already local in PostgreSQL (`fred.series_values`, 39 series, 208K rows) with a working incremental sync pipeline. This is a "fill the empty slot" problem, not a redesign. Zero new pip dependencies are needed -- the entire macro regime pipeline is built on existing numpy, pandas, scipy, and SQLAlchemy.

The recommended approach is rule-based macro regime classification across four dimensions -- monetary policy, liquidity, risk appetite, and carry trade stability -- using structural economic thresholds (yield curve sign, VIX consensus bands, net liquidity direction) rather than fitted parameters. This avoids the critical overfitting pitfall: with macro regimes changing every 2-6 months, 5 years of history produces only 10-30 regime transitions, far too few to fit a statistical model. The rule-based approach is consistent with the existing per-asset regime system, plugs directly into the resolver's L4 slot, and preserves tighten-only semantics automatically.

The primary risks are: (1) forward-filled monthly FRED data masking fast events like carry trade unwinds (August 2024: 15% BTC drop in 48 hours, but Japan rate data arrives 30+ days late), mitigated by using daily proxy indicators (USD/JPY, VIX) for detection and monthly data only for confirmation; (2) FRED holiday/weekend gaps creating 31% NULL joins with 24/7 crypto data, mitigated by a two-table design (raw observations + calendar-daily filled table with explicit fill limits); and (3) look-ahead bias from revised FRED data in backtests, mitigated by using ALFRED vintage data for point-in-time replay. The carry trade risk is the most consequential: the yen carry trade is estimated at up to $14 trillion, roughly 3x the entire crypto market cap, and unwinds happen in hours, not months.

## Key Findings

### Recommended Stack

No new pip dependencies. The existing stack (numpy 2.4, scipy 1.17, pandas 2.3, scikit-learn 1.8, SQLAlchemy 2.0+, PyYAML, Alembic) covers 100% of the macro regime infrastructure needs. The `integrations/economic/` FredProvider (1,766 LOC) should be bypassed -- it is an API client, but the data already lives locally via the SSH sync pipeline.

**Core technologies (all existing):**
- **pandas/numpy**: Derived series computation (rate spreads, yield curve slope, carry proxies, rolling z-scores) -- simple arithmetic on time-aligned DataFrames
- **SQLAlchemy + Alembic**: New `fred_macro_features` table (PK: date), schema migration, and direct SQL reads from `fred.series_values`
- **PyYAML**: YAML-configurable thresholds for macro regime domains (extends existing `policy_loader.py` pattern)
- **Existing HysteresisTracker**: Reused for macro regime transition filtering with separate `min_bars_hold=15-21` (vs 3 for per-asset)

**Explicitly rejected:**
- hmmlearn (limited maintenance, needs 500+ observations per state, macro data is too low-frequency)
- statsmodels (regime labeling needs classification, not forecasting)
- FedTools (unmaintained FOMC scraper; static YAML for 8 dates/year is simpler)
- arch/GARCH (VIX already provides vol; no need to estimate it)

### Expected Features

**Must have (table stakes):**
- FRED series sync to `fred_macro_daily` table with forward-fill alignment (mixed-frequency daily/weekly/monthly to calendar-daily)
- Net liquidity proxy (`WALCL - TGA - RRP`) -- the single most-correlated macro feature to BTC price
- Rate spreads (US-Japan, US-ECB), yield curve slope + momentum, VIX regime, dollar strength, credit stress z-score, carry trade features
- Rule-based 4-dimensional macro regime classifier (monetary policy, liquidity, risk appetite, carry) with hysteresis
- L4 integration in policy resolver -- macro regime key passed via existing L4 slot, tighten-only semantics preserved
- FOMC event gate (+/-24h size reduction) and VIX spike gate (>30 = REDUCE, >40 = FLATTEN)
- Data freshness gate (alert if FRED sync stale >48h)
- Macro regime display in Streamlit dashboard and Telegram alerts on regime transitions
- Macro regime as drift attribution source in DriftMonitor

**Should have (differentiators):**
- Carry unwind velocity gate (2-sigma USD/JPY daily move + positive spread = REDUCE)
- Credit stress gate (HY OAS 5d z-score > 1.5 = size reduction)
- Net liquidity z-score (365d rolling) for normalized regime signal
- Fed regime classification (hiking/holding/cutting from DFF trajectory)
- CPI/NFP release date gates (monthly event risk reduction)
- Composite macro stress score (0-100 weighted blend of VIX, credit, carry, financial conditions)
- BTC/ETH rolling correlation as explicit macro health feature (already computed for tail risk; expose as column)

**Defer to post-v1.0.1:**
- HMM regime detection (model risk on top of model risk; rule-based must work first)
- Blended global liquidity proxy (US/ECB/BOJ; validate US-only first)
- CPI surprise proxy (without consensus data, proxy is low confidence)
- ETF flow proxy (requires external data source not yet integrated)
- On-chain metrics (requires Glassnode/CryptoQuant subscription)
- Macro regime in backtest replay (requires full historical FRED regime labels; significant data engineering)
- ALFRED vintage data for backtests (valuable but not blocking for MVP daily pipeline)

### Architecture Approach

The macro regime system is a three-layer addition -- data, classification, integration -- that plugs into four existing extension points: (1) the resolver's L4 parameter, (2) the daily refresh pipeline's stage ordering, (3) the risk engine's gate chain, and (4) the drift monitor's attribution steps. A new `fred_macro_features` table (PK: date) stores market-wide macro features separately from per-asset `cmc_features` (PK: id, ts, tf), correctly modeling the domain. The macro labeler (`regimes/macro_labels.py`) produces a 3-dimensional string key (Growth-Liquidity-Stress) that the resolver matches via substring, enabling both broad (`"Contraction-"`) and precise (`"Contraction-TightMoney-HighStress"`) policy rules.

**Major components:**
1. **`fred_macro_features` table** -- Single-row-per-date macro feature store; yield spreads, rate deltas, credit z-scores, vol levels, composite scores, and L4 label. Source: `fred.series_values` via direct SQL.
2. **`regimes/macro_features.py` + `macro_labels.py`** -- Feature computation (transforms, z-scores, composites) and rule-based labeler producing L4-shaped regime keys.
3. **`scripts/macro/refresh_macro_features.py`** -- CLI script wired into daily refresh as new stage between `desc_stats` and `regimes`. Reads FRED, computes features, writes table, computes L4 label.
4. **Modified `refresh_cmc_regimes.py`** -- Loads latest L4 from `fred_macro_features` once, passes to resolver for all assets. Change is minimal: one query + pass L4 to existing function call.
5. **Risk gate integration** -- Macro regime feeds through resolver (primary path for daily policy adjustment) and optionally through risk engine Gate 1.7 (secondary path for acute macro stress blocking).
6. **Observability** -- Macro regime card in Streamlit dashboard, Telegram alerts on regime transitions, drift attribution for macro regime changes.

### Critical Pitfalls

1. **Forward-fill monthly data masks fast events** -- Japan rate data arrives 30+ days late; the August 2024 carry unwind was invisible to monthly FRED data. Prevention: use daily proxy indicators (USD/JPY, VIX) for detection; monthly data for confirmation only. Add `days_since_publication` tracking.

2. **FRED holiday/weekend gaps create 31% NULL joins** -- Crypto trades 24/7/365 but FRED has ~252 business days. Prevention: two-table design (raw observations + calendar-daily filled table); `ffill(limit=5)` for daily series, `limit=45` for monthly; explicit `fill_method` column.

3. **Overfitting macro classifier to <60 regime transitions** -- 5 years of history with 2-6 month regime cycles = 10-30 transitions. Even 3-4 parameters can overfit trivially. Prevention: structural thresholds from economic literature, not fitted to backtest; 3-or-fewer input dimensions; require economic justification for every threshold.

4. **Tighten-only bypass temptation** -- The macro layer will create pressure to "loosen when macro is favorable." Prevention: assert `size_mult <= 1.0` for ALL macro policy entries. Favorable macro = neutral (1.0), not expansionary (>1.0). The system never takes more risk because macro is favorable.

5. **VIX is a proxy, not a signal, for crypto** -- VIX measures S&P 500 implied vol, not crypto risk. It misses crypto-specific events and only covers US market hours. Prevention: combine VIX with DXY, yield curve, and crypto-native vol (already computed in per-asset regimes); weight crypto vol higher.

6. **Risk gate without override = unreachable lock** -- A hard macro gate that cannot be bypassed during misclassification freezes all trading. Prevention: feed macro through resolver (preferred), not a new hard gate. If a gate is added, integrate with existing `dim_risk_overrides` and provide CLI bypass.

7. **Alert fatigue from over-sensitive macro gates** -- If "cautious" fires 30%+ of days, operators will ignore all macro alerts within weeks. Prevention: calibrate "stressed" to fire 10-15% of days; three-tier alerting (log-only / Telegram / critical); track alert hit rate monthly.

## Implications for Roadmap

Based on combined research, the build order is dictated by a strict dependency chain: data first (nothing works without macro features in the database), then classification (regimes depend on features), then integration (resolver and risk engine depend on regime labels), then observability (dashboards and alerts depend on all of the above).

### Phase 1: FRED Data Pipeline and Macro Feature Store

**Rationale:** Every other phase depends on macro features being available in the `marketdata` database. This is the critical path and must be complete and tested before anything downstream starts.
**Delivers:** `fred_macro_features` table with calendar-daily coverage; derived series (net liquidity, rate spreads, yield curve metrics, carry features, credit stress, VIX regime, dollar strength); forward-fill with staleness tracking; data freshness monitoring.
**Addresses:** Feature Area 1 (table stakes): FRED sync, forward-fill alignment, net liquidity proxy, rate spreads, yield curve, VIX, dollar strength, credit stress, carry features, sync automation.
**Avoids:** Pitfall 1 (forward-fill without staleness tracking), Pitfall 2 (holiday/weekend gaps), Pitfall 7 (publication lag misalignment), Pitfall 8 (series discontinuation).
**Key decisions:** Two-table design (raw + daily-filled); `fill_method` column; `dim_fred_series_metadata` with publication schedules; `ffill(limit=N)` with per-frequency limits.

### Phase 2: Macro Regime Classifier and Hysteresis

**Rationale:** The regime classifier consumes Phase 1's features and produces L4 labels that Phase 3 wires into the resolver. Must be designed with overfitting constraints and appropriate hysteresis before integration.
**Delivers:** `regimes/macro_labels.py` with 4-dimensional rule-based classifier (monetary policy, liquidity, risk appetite, carry); composite regime key (e.g., "Cutting-Expanding-RiskOn-Stable"); separate hysteresis config (`min_bars_hold=15-21`); storage in `cmc_macro_regimes` table.
**Addresses:** Feature Area 2 (table stakes): all four regime dimensions, composite key, hysteresis.
**Avoids:** Pitfall 3 (overfitting to <60 transitions), Pitfall 5 (VIX as sole volatility input), Pitfall 6 (carry trade detected from monthly data only).
**Key decisions:** 3-or-fewer input dimensions per regime dimension; structural thresholds from economic literature; separate HysteresisTracker instance with macro-appropriate `min_bars_hold`.

### Phase 3: L4 Resolver Integration and Policy Table

**Rationale:** The resolver's L4 slot is ready and waiting. This phase wires the macro label into the existing tighten-only chain and adds policy table entries. It is the architectural core: connecting macro state to trading decisions.
**Delivers:** Modified `refresh_cmc_regimes.py` passing L4; new macro policy rules in `configs/regime_policies.yaml`; `cmc_regimes.l4_label` column populated; `fred_sync` and `macro_features` stages in daily refresh pipeline.
**Addresses:** Feature Area 3 (table stakes): L4 integration, tighten-only preservation, daily refresh wiring, executor logging.
**Avoids:** Pitfall 4 (tighten-only bypass), Pitfall 3.5 (separate resolver chain for macro).
**Key decisions:** L4 for macro (not L3); assert `size_mult <= 1.0` for all macro entries; macro regime computed once per day, broadcast to all assets.

### Phase 4: Macro Risk Gates and Event Calendar

**Rationale:** Risk gates are the acute-stress complement to the resolver's daily policy adjustment. FOMC dates are static and can be seeded immediately. VIX and carry gates consume features already available from Phase 1.
**Delivers:** FOMC event gate (+/-24h size reduction); VIX spike gate (>30 REDUCE, >40 FLATTEN); carry unwind velocity gate (2-sigma USD/JPY + positive spread); credit stress gate (HY OAS z-score); `dim_macro_events` table with FOMC/CPI/NFP dates; data freshness gate.
**Addresses:** Feature Area 5 (table stakes + should-haves).
**Avoids:** Pitfall 6 (macro gate without override -- integrate with existing `dim_risk_overrides`), Pitfall 7 (alert fatigue -- three-tier alerting, calibrate frequency).
**Key decisions:** Feed acute stress through existing tail risk escalation (NORMAL/REDUCE/FLATTEN) rather than adding a new hard gate; or if new gate, integrate with override system.

### Phase 5: Observability, Drift, and Validation

**Rationale:** Read-only display of other phases' outputs. Last in build order because it depends on macro data, regime labels, and risk gate state all being available.
**Delivers:** Macro regime card in Streamlit dashboard; Telegram alerts on regime transitions; macro regime as drift attribution source; FRED data freshness in pipeline monitor; macro regime logged per order for drift replay.
**Addresses:** Feature Area 6 (table stakes).
**Avoids:** Pitfall 8 (drift from regime label divergence between paper executor and backtest replay -- log L4 label per order).
**Key decisions:** Manual-refresh dashboard (FRED data is daily, not real-time); throttle Telegram macro alerts to 1 per 8 hours; log macro regime label in `cmc_orders` for PIT replay.

### Phase Ordering Rationale

- **Strict dependency chain:** Data (P1) -> Classification (P2) -> Integration (P3) -> Risk Gates (P4) -> Observability (P5). Each phase consumes outputs from the previous phase.
- **Phases 2 and 3 are tightly coupled** but should be separate because the classifier design (threshold selection, dimensionality) should be validated with unit tests before wiring into the live resolver.
- **Phase 4 is partially parallelizable with Phase 3:** the FOMC calendar seeding and `dim_macro_events` DDL can start during Phase 3, but the risk gate logic depends on the resolver integration being stable.
- **Phase 5 is fully independent of Phase 4** and could run in parallel, but observability is less urgent than risk gating.
- **Pitfall avoidance drives ordering:** Data quality pitfalls (staleness, gaps, publication lags) are addressed in Phase 1 before any downstream consumer exists. Overfitting constraints are baked into Phase 2's design. Tighten-only assertion is enforced in Phase 3. Risk gate override integration is required in Phase 4.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1 (Data Pipeline):** The two-table design, forward-fill limits, and `dim_fred_series_metadata` schema need careful specification. The publication schedules for all 39 FRED series need to be documented. The sync pipeline from the GCP VM needs verification that all 39 series are actually being collected (VM-STRATEGY.md lists them, but only 3 were confirmed as actively collecting).
- **Phase 2 (Classifier):** Threshold calibration for the four regime dimensions needs historical validation. The carry trade dimension is novel (no existing codebase pattern to follow) and the August 2024 event is the only major reference point.
- **Phase 4 (Risk Gates):** The carry unwind velocity gate's thresholds need calibration from the August 2024 event data specifically. The interaction between macro risk gates and existing tail risk gates needs careful ordering specification.

Phases with standard patterns (skip research-phase):
- **Phase 3 (Resolver Integration):** The L4 slot is ready, the resolver code is well-understood, and the change is minimal (one query + pass L4). This is a straightforward code change following established patterns.
- **Phase 5 (Observability):** Streamlit cards, Telegram alerts, and drift attribution all follow patterns established in v0.9.0 and v1.0.0. No novel architecture needed.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new dependencies; all existing packages verified from installed versions; hmmlearn/statsmodels rejection well-reasoned |
| Features | HIGH (table stakes), MEDIUM (differentiators) | FRED series formulas are simple arithmetic verified against official docs; carry trade thresholds need calibration against limited event data |
| Architecture | HIGH | Direct source code analysis of all integration points; L4 slot verified as ready; resolver chain, hysteresis tracker, risk engine gates all inspected |
| Pitfalls | HIGH | 8 critical/moderate pitfalls identified with specific prevention strategies; grounded in BIS research (carry trade), FRED docs (revisions/ALFRED), and codebase inspection |

**Overall confidence:** HIGH

The high confidence stems from this being an extension of a well-understood existing system rather than greenfield development. The resolver's L4 slot, the FRED data already in PostgreSQL, and the established patterns for regime labeling, hysteresis, and risk gating all reduce architectural uncertainty. The main uncertainty is in threshold calibration (MEDIUM confidence) and carry trade detection from daily proxies (MEDIUM confidence, limited reference events).

### Gaps to Address

- **VM FRED collection status:** VM-STRATEGY.md lists 39 series, but only 3 were confirmed as actively collecting. Phase 1 planning must verify how many of the 39 are actually syncing to `fred.series_values` today. If only 3 are live, expanding to 39 is a prerequisite that could significantly increase Phase 1 scope.
- **Carry trade proxy validation:** The carry unwind velocity gate is calibrated from a single event (August 2024). Before going live, the thresholds should be tested against at least the 2019 flash crash, the 2020 COVID crash, and any other JPY-correlated crypto drawdowns. Limited event data = limited confidence in threshold selection.
- **BTC dominance data availability:** Listed as a table-stakes cross-asset feature but may not be available from current data sources. Needs verification during Phase 1 planning.
- **ALFRED vintage data scope:** The PITFALLS research identifies look-ahead bias from revised FRED data as critical, but the FEATURES research defers ALFRED integration to post-v1.0.1. This is acceptable for the daily pipeline MVP but creates a known backtest accuracy gap. Document this limitation explicitly.
- **Macro-crypto lead-lag quantification:** The claim that liquidity leads BTC by ~6 weeks comes from a single source (TraderHC). This lag should be validated against ta_lab2's own data during Phase 2 or as a Phase 5 analysis task.
- **NFCI threshold validation:** The threshold of NFCI > 0.5 for "tight conditions" is from the Chicago Fed's documentation, but its predictive power for crypto specifically has not been validated. Flag for IC evaluation during Phase 2.

## Sources

### Primary (HIGH confidence)
- Codebase direct inspection: `resolver.py` (L4 slot ready, tighten-only chain), `hysteresis.py` (HysteresisTracker), `labels.py` (per-asset labelers), `data_budget.py` (L4 threshold = 1), `risk_engine.py` (7-gate architecture), `flatten_trigger.py` (tail risk thresholds), `refresh_cmc_regimes.py` (L4=None hardcoded), `position_sizer.py` (reads regime_key), `drift/attribution.py` (regime delta step), `sync_fred_from_vm.py` (incremental FRED sync)
- FRED official documentation: series pages for VIXCLS, BAMLH0A0HYM2, WALCL, NFCI, T10Y2Y, DTWEXBGS, DEXJPUS
- FRED ALFRED vintage data documentation: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- fredapi library (ALFRED methods): https://github.com/mortada/fredapi
- Federal Reserve FOMC calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- BIS Bulletin No 90: carry trade unwind mechanics and scale: https://www.bis.org/publ/bisbull90.pdf
- hmmlearn PyPI (limited maintenance mode): https://pypi.org/project/hmmlearn/
- Chicago Fed NFCI documentation: https://www.chicagofed.org/research/data/nfci/about

### Secondary (MEDIUM confidence)
- Net liquidity formula (WALCL - TGA - RRP): TradingView, DurdenBTC, Reflexivity Research (multiple sources agree)
- BTC/equity correlation tightening (0.70-0.77 30d correlation): AInvest, MEXC Blog
- VIX threshold consensus (calm <15, elevated 15-25, crisis >25): DozenDiamonds, CFA Institute
- Carry trade detection signals: QuantVPS, Investing.com
- BTC-VIX record 90-day correlation (0.88): CoinDesk July 2025
- Macrosynergy regime classification research: https://macrosynergy.com/research/classifying-market-regimes/
- FactSet: Mapping Asset Returns to Economic Regimes (practitioner guide)
- Ghysels et al.: MIDAS Touch (foundational paper on mixed-frequency data)

### Tertiary (LOW confidence)
- 1% liquidity rise = 5% crypto rise: Single source (TraderHC). Direction plausible, magnitude needs validation.
- NFCI threshold of -50/-63 for alt season: Single TradingView indicator. Needs backtesting.
- BTC dominance as risk-on/off signal: Commonly stated but mechanism unclear in post-ETF market.
- Crypto underperformance in 2025 relative to VIX: CryptoTicker analysis, useful for context but not authoritative.

---
*Research completed: 2026-03-01*
*Ready for roadmap: yes*
