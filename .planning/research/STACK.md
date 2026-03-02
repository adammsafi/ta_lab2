# Technology Stack: v1.0.1 Macro Regime Infrastructure

**Project:** ta_lab2
**Milestone:** v1.0.1 -- Macro Regime Infrastructure
**Researched:** 2026-03-01
**Overall confidence:** HIGH (existing stack verified from installed packages; new additions verified via PyPI/official docs)

---

## Scope: What This Document Covers

This STACK.md covers ONLY the technology decisions for adding macro regime infrastructure to ta_lab2. The existing validated stack (Python 3.12, PostgreSQL, SQLAlchemy 2.0, pandas 2.3, numpy 2.4, scipy 1.17, scikit-learn 1.8, polars, etc.) is NOT re-researched. See the v0.9.0 STACK.md for those decisions.

**The question:** What libraries/tools are needed to transform 39 FRED series (already in PostgreSQL) into macro regime labels that feed into the existing L0-L4 tighten-only policy resolver?

---

## Confirmed Existing Stack (Relevant to Macro Regimes)

| Package | Installed Version | Relevance |
|---------|------------------|-----------|
| numpy | 2.4.1 | Array math for derived series, threshold logic |
| scipy | 1.17.0 | Already used in 14 files; z-scores, statistical tests |
| pandas | 2.3.3 | Time-series alignment, resampling, rolling windows |
| scikit-learn | 1.8.0 | Model infrastructure (clone, pipelines) used by RegimeRouter |
| SQLAlchemy | 2.0+ | DB reads/writes for FRED data and regime tables |
| PyYAML | installed | Already used by policy_loader.py for regime config |

**Key insight:** The existing stack already covers 90% of what macro regime labeling needs. The derived series computation (rate spreads, yield curve slope, carry proxies) is straightforward pandas/numpy arithmetic on data already in PostgreSQL. The question is whether we need NEW libraries at all.

---

## Decision 1: Regime Detection Approach

### Question: Rule-based vs. HMM vs. Hybrid for Macro Regimes?

**Recommendation: Rule-based with threshold hysteresis. Do NOT add HMM.**

**Confidence: HIGH**

### Rationale

The existing per-asset regime system (L0-L3) uses a purely rule-based approach: EMA stack position, ATR percentile buckets, and spread thresholds, combined through `label_trend_basic()`, `label_vol_bucket()`, and `label_liquidity_bucket()`. It has proven reliable and interpretable.

Macro regime classification is an even stronger case for rule-based thresholds than per-asset regimes:

1. **Domain knowledge is the signal.** Yield curve inversion (T10Y2Y < 0) is a regime boundary defined by economics, not statistics. The Fed Funds rate has discrete states (hiking, paused, cutting) observable from the data. VIX has well-established threshold bands (sub-15 = complacent, 15-25 = normal, 25-35 = elevated, 35+ = crisis). These are not latent states that need discovery -- they are known.

2. **Frequency mismatch kills HMM.** FRED data is daily-to-monthly. An HMM with 3-4 states fitted on 10-20 years of monthly data has ~120-240 observations. The Baum-Welch EM algorithm needs hundreds to thousands of observations per state to converge reliably. The carry trade regime (Japan rate differential, USD/JPY vol) updates weekly at best. HMM would overfit.

3. **Interpretability is non-negotiable.** The tighten-only policy resolver (`resolver.py`) maps regime keys like "Up-Normal-Normal" to position sizing rules. An HMM-derived "State 2" has no semantic meaning that maps to policy. You would need a post-hoc mapping from HMM states to policy keys anyway, which is just a threshold classifier with extra steps.

4. **Consistency with existing architecture.** The L0-L4 system already has hysteresis tracking (`HysteresisTracker`), tighten-only composition (`_tighten()`), and YAML-configurable policy tables. Macro regimes as L4 inputs slot directly into this. An HMM would require a parallel inference pipeline that duplicates logic.

5. **HMM adds complexity without value.** hmmlearn 0.3.3 is in "limited maintenance mode" per its PyPI page. Adding a new dependency with uncertain maintenance for marginal benefit is not justified when simple thresholds on well-understood economic indicators work.

### What About HMM Later?

If the project evolves to need latent state discovery (e.g., "which combinations of macro variables best predict crypto drawdowns?"), that is a Phase 2+ research question. At that point, the macro feature store built in v1.0.1 provides the input data for HMM experimentation. The rule-based labeler and HMM labeler can coexist as alternative labeling strategies, similar to how `labeling/` has both triple-barrier and trend-scanning approaches.

### Alternative Considered: hmmlearn

| Criterion | Rule-Based | hmmlearn HMM |
|-----------|-----------|--------------|
| New dependency | None | hmmlearn>=0.3.3 (limited maintenance) |
| Data requirement | Works with any history length | Needs 500+ observations per state for stability |
| Interpretability | Direct: "yield curve inverted" = policy X | Opaque: "State 2" needs post-hoc interpretation |
| Integration | Direct plug into L4 resolver slot | Requires wrapper to map states to policy keys |
| Latency | Instant (threshold comparison) | Viterbi decode pass per update |
| Maintenance | Zero -- thresholds are economics | Requires retraining, state monitoring, drift detection |
| Regime transition handling | Uses existing `HysteresisTracker` | Has its own transition matrix (duplicates logic) |

---

## Decision 2: New Dependencies

### Required: NONE for Core Macro Regimes

The macro regime infrastructure can be built with **zero new pip dependencies**. Here is why:

| Capability | Implementation | Library |
|-----------|---------------|---------|
| Derived series (rate spreads, yield curve slope) | `pandas` arithmetic on `fred.series_values` | Already installed |
| Rolling z-scores, percentiles | `pandas.rolling()` + `numpy` | Already installed |
| VIX regime thresholds | Simple comparison operators | Already installed |
| Carry trade proxy (rate differential, USD/JPY vol) | `pandas` arithmetic + rolling std | Already installed |
| Macro feature store (DB tables) | `SQLAlchemy` + Alembic migration | Already installed |
| Regime labeling | Pure Python/numpy threshold logic | Already installed |
| YAML-configurable thresholds | `PyYAML` via existing `policy_loader.py` | Already installed |
| Hysteresis filtering | Existing `HysteresisTracker` class | Already built |
| L4 integration into policy resolver | Existing `resolve_policy(L4=...)` parameter | Already built |
| Risk gate integration | Existing `RiskEngine` + `dim_risk_state` | Already built |

### Optional: FOMC Calendar Data

**Recommendation: Static YAML file, NOT a library dependency.**

**Confidence: HIGH**

FOMC meets 8 times per year on pre-announced dates. The dates are published years in advance on the Fed website. The total data is ~16 dates over 2 years. A dynamic library to scrape these dates is massive overkill.

| Option | Verdict | Why |
|--------|---------|-----|
| FedTools (PyPI) | REJECT | Unmaintained (no release in 12+ months per Snyk health analysis), scrapes HTML which is fragile, adds dependency for 8 dates/year |
| pandas_market_calendars | REJECT | Designed for exchange trading calendars, not economic event calendars; does not include FOMC dates |
| Static YAML/JSON in `configs/` | USE THIS | Trivial to maintain (update once per year), zero dependency, version-controlled, deterministic |
| FRED release calendar API | REJECT | Requires API call for data that changes once per year |

**Implementation:** A `configs/fomc_calendar.yaml` file with meeting dates, statement release times, and a flag for "dot plot" meetings (March, June, September, December SEP meetings). Updated manually when the Fed publishes the next year's calendar (typically in June). The macro regime labeler reads this at startup to compute "days to next FOMC" and "FOMC blackout window" features.

```yaml
# configs/fomc_calendar.yaml
fomc_meetings:
  2025:
    - date: "2025-01-29"
      type: statement_only
    - date: "2025-03-19"
      type: sep  # Summary of Economic Projections (dot plot)
    # ... etc
  2026:
    - date: "2026-01-28"
      type: statement_only
    - date: "2026-03-18"
      type: sep
    # ... 6 more
```

---

## Decision 3: Revive `integrations/economic/` or Bypass?

**Recommendation: Bypass for reads. The existing module stays dormant.**

**Confidence: HIGH**

### Current State

The `integrations/economic/` module (FredProvider, ~1,766 LOC) was built for Phase 15 to **fetch** FRED data via the fredapi API. It has rate limiting, circuit breaker, caching, and quality validation. It is well-engineered but has zero active consumers.

### Why Bypass

The FRED data is **already in PostgreSQL** (`fred.series_values`, 39 series, 208K rows). The sync pipeline (`sync_fred_from_vm.py`) handles incremental updates via SSH COPY from the GCP VM. The macro regime infrastructure needs to **read** this data, not **fetch** it from the FRED API.

The correct integration point is:

```python
# Read FRED data from PostgreSQL (what macro regimes need)
SELECT series_id, date, value
FROM fred.series_values
WHERE series_id IN ('DGS10', 'DGS2', 'FEDFUNDS', ...)
ORDER BY date
```

NOT:

```python
# Fetch FRED data from API (what integrations/economic/ does)
provider = FredProvider()
result = provider.get_series("DGS10")
```

### What Stays

- `integrations/economic/` remains as-is (deferred, not abandoned per project convention)
- If the project later needs to add NEW FRED series beyond the 39 already synced, the FredProvider and sync pipeline are ready
- The `FRED_SERIES` dictionary in `types.py` is a useful reference but not consumed at runtime

### What's New

A thin SQL reader module that queries `fred.series_values` and returns time-aligned pandas DataFrames. This is analogous to how `load_prices()` reads `cmc_price_bars_multi_tf` -- a simple query function, not a provider abstraction.

---

## Decision 4: Database Schema Additions

### New Tables (via Alembic migration)

| Table | Purpose | Schema |
|-------|---------|--------|
| `cmc_macro_derived_series` | Computed macro indicators (rate spreads, VIX bands, carry proxy) | `(series_id TEXT, date DATE, value FLOAT, computed_at TIMESTAMPTZ)` PK: `(series_id, date)` |
| `cmc_macro_regimes` | Macro regime labels per domain | `(date DATE, domain TEXT, label TEXT, sublabels JSONB, computed_at TIMESTAMPTZ)` PK: `(date, domain)` |
| `cmc_macro_features` | Time-series features derived from FRED data | `(date DATE, feature_name TEXT, value FLOAT, computed_at TIMESTAMPTZ)` PK: `(date, feature_name)` |
| `dim_macro_regime_config` | Threshold configuration for macro regime labeler | `(domain TEXT PK, config JSONB, updated_at TIMESTAMPTZ)` |

### Existing Tables Used (Read-Only)

| Table | Usage |
|-------|-------|
| `fred.series_values` | Source data for derived series computation |
| `fred.releases` | FOMC release dates (supplementary) |
| `cmc_regimes` | Per-asset L0-L3 labels (for cross-regime aggregation) |
| `dim_risk_state` | Macro risk gate writes (tail_risk_state escalation) |
| `dim_risk_limits` | Macro-driven limit adjustments |

### Existing Tables Modified

| Table | Change | Why |
|-------|--------|-----|
| `cmc_regimes` | Add `l4_label` column (nullable TEXT) | Stores the macro regime label per asset-date, fed into resolver as L4 |
| `dim_risk_state` | Add `macro_regime_state` column (nullable TEXT) | Tracks current aggregate macro regime for risk engine reads |

---

## Decision 5: Configuration Architecture

### Recommendation: YAML config per macro regime domain

**Confidence: HIGH**

The project already uses YAML for regime policy configuration (`configs/regime_policies.yaml` via `policy_loader.py`). Extend this pattern for macro regime thresholds.

```yaml
# configs/macro_regimes.yaml
domains:
  monetary_policy:
    series:
      fed_funds: FEDFUNDS
      t10y2y: T10Y2Y
      dgs2: DGS2
      dgs10: DGS10
    thresholds:
      yield_curve_inverted: -0.01  # T10Y2Y below this = inverted
      rate_hiking: 0.25  # consecutive increase in FEDFUNDS >= this
      rate_cutting: -0.25  # consecutive decrease
    labels: [hiking, paused, cutting, inverted]
    hysteresis_days: 5

  vix_regime:
    series:
      vix: VIXCLS
    thresholds:
      complacent: 15.0
      normal_high: 25.0
      elevated: 35.0
    labels: [complacent, normal, elevated, crisis]
    hysteresis_days: 3

  carry_trade:
    series:
      fed_funds: FEDFUNDS
      japan_rate: IRSTCI01JPM156N  # or BOJ policy rate proxy
      usd_jpy_vol: null  # computed from derived series
    thresholds:
      spread_compressed_bps: 200  # below this = stress signal
      vol_spike_zscore: 2.0  # JPY vol z-score above this = unwind risk
    labels: [favorable, neutral, stress, unwind]
    hysteresis_days: 5
```

This follows the existing pattern but extends it:
- `policy_loader.py` loads regime-to-policy mappings (what to DO given a regime)
- `macro_regimes.yaml` defines regime-detection thresholds (how to DETECT a regime)

Both are YAML, both support hot-reload, both have in-code defaults as fallbacks.

---

## Decision 6: What NOT to Add

These are libraries or approaches I explicitly evaluated and rejected for v1.0.1.

| Library/Approach | Why NOT |
|-----------------|---------|
| **hmmlearn** | Macro data is too low-frequency for HMM; thresholds are known from domain knowledge; adds unmaintained dependency. See Decision 1. |
| **pomegranate** | Same reasoning as hmmlearn; faster but even more complex API. Not needed when thresholds work. |
| **statsmodels** | Tempting for time-series decomposition (STL, ARIMA), but macro regime labeling does not need forecasting -- it needs classification of current state. Rolling z-scores via pandas/scipy cover the feature engineering. |
| **fredapi** | Already installed as optional (`pip install ta_lab2[fred]`), but the macro regime pipeline reads from PostgreSQL, not the FRED API. No change needed. |
| **FedTools** | Unmaintained scraper for FOMC dates. Static YAML is simpler, more reliable, and zero-dependency. |
| **pandas_market_calendars** | Exchange trading calendars, not economic event calendars. Does not include FOMC meetings. |
| **arch** (GARCH) | Already installed (7.2.0) but not needed. VIX is already a volatility measure -- no need to estimate conditional volatility from returns when the market's own estimate (VIX) is available as a FRED series. |
| **ecocal** | Economic calendar scraper. Same reasoning as FedTools -- static YAML for 8 FOMC dates/year. |
| **requests** | Already available in the environment but not needed. All data reads are from PostgreSQL. |

---

## Recommended Stack Delta: v1.0.0 -> v1.0.1

### pyproject.toml Changes

**None required for core dependencies.**

The macro regime infrastructure is built entirely on existing dependencies. No new entries in `[project.dependencies]` or `[project.optional-dependencies]`.

### New Files (Code, Not Dependencies)

| File | Purpose |
|------|---------|
| `src/ta_lab2/macro/__init__.py` | New package for macro regime infrastructure |
| `src/ta_lab2/macro/derived_series.py` | Compute rate spreads, yield curve metrics, carry proxies from `fred.series_values` |
| `src/ta_lab2/macro/feature_store.py` | Build time-series features (rolling z-scores, momentum, regime duration) |
| `src/ta_lab2/macro/labeler.py` | Rule-based macro regime labeler (monetary policy, VIX, carry) |
| `src/ta_lab2/macro/aggregator.py` | Cross-domain regime aggregation (composite macro regime key) |
| `src/ta_lab2/macro/risk_gate.py` | FOMC blackout window, VIX spike, carry unwind risk gates |
| `src/ta_lab2/macro/fred_reader.py` | Thin SQL reader for `fred.series_values` -> pandas |
| `configs/macro_regimes.yaml` | Threshold configuration for all macro regime domains |
| `configs/fomc_calendar.yaml` | Static FOMC meeting dates |
| Alembic migration | Schema additions (see Decision 4) |
| `src/ta_lab2/scripts/macro/refresh_macro_regimes.py` | Daily refresh script |

### Import-Linter Implications

The existing layering contract in `pyproject.toml` places `regimes` at the same level as `signals` and `analysis`. The new `macro` package should be at the same level:

```
ta_lab2.scripts > ta_lab2.pipelines | ta_lab2.backtests > ta_lab2.signals | ta_lab2.regimes | ta_lab2.analysis | ta_lab2.macro > ta_lab2.features | ta_lab2.tools
```

`macro` can import from `features` and `tools` (lower layers) but NOT from `scripts`, `pipelines`, or `backtests` (higher layers). `regimes` can import from `macro` (same level, no cycle since macro does not import regimes).

---

## Integration Points Summary

| Existing Component | How Macro Regimes Connect |
|-------------------|--------------------------|
| `resolver.py` L4 parameter | Macro composite regime key passed as `L4=...` to `resolve_policy()` |
| `HysteresisTracker` | Reused for macro regime transitions (same min_bars_hold logic) |
| `policy_loader.py` | Extended to load macro-specific policy rules from YAML |
| `RiskEngine` gates | New macro risk gate reads `dim_risk_state.macro_regime_state` |
| `DriftMonitor` | New drift source: "macro regime changed" attribution |
| `RegimeRouter` | Can route by macro regime (L4) in addition to per-asset regime (L2) |
| Daily refresh pipeline | New step: bars -> EMAs -> regimes -> **macro regimes** -> stats |

---

## Version Pinning Summary

No new version pins needed. For reference, the existing relevant pins:

| Package | Version | Notes |
|---------|---------|-------|
| numpy | >=1.24 (installed: 2.4.1) | No macro-specific constraints |
| scipy | >=1.10 (installed: 1.17.0) | Used for z-score computation in macro features |
| pandas | >=2.0 (installed: 2.3.3) | DatetimeIndex resampling for daily alignment |
| PyYAML | >=5.0 (installed) | YAML config loading |
| SQLAlchemy | >=2.0 (installed) | DB reads/writes |
| Alembic | >=1.18 (installed) | Schema migrations |
| scikit-learn | >=1.4 (installed: 1.8.0) | Only if HMM experimentation added later |

---

## Sources

### Verified (HIGH confidence)
- hmmlearn PyPI page: https://pypi.org/project/hmmlearn/ (version 0.3.3, limited maintenance mode)
- hmmlearn docs: https://hmmlearn.readthedocs.io/en/latest/api.html (GaussianHMM API)
- FedTools PyPI page: https://pypi.org/project/Fedtools/ (no release in 12+ months)
- FedTools Snyk health: https://snyk.io/advisor/python/fedtools (project health concerns)
- pandas_market_calendars docs: https://pandas-market-calendars.readthedocs.io/en/latest/calendars.html (exchange calendars only)
- Fed FOMC calendar: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (official dates)
- Existing codebase: `regimes/resolver.py` L4 parameter, `regimes/hysteresis.py` HysteresisTracker, `integrations/economic/` FredProvider, `scripts/etl/sync_fred_from_vm.py`, `risk/risk_engine.py`

### Research (MEDIUM confidence)
- Macrosynergy regime classification research: https://macrosynergy.com/research/classifying-market-regimes/
- Tree-based macro regime switching (arXiv): https://arxiv.org/html/2408.12863v1
- QuantStart HMM regime detection: https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/

### Market Context (MEDIUM confidence)
- Carry trade unwind mechanics and detection signals: https://www.quantvps.com/blog/yen-carry-trade-unwind-explained
- USD/JPY carry trade risk assessment: https://www.investing.com/analysis/assessing-usdjpy-carry-trade-risks-in-a-changing-2025-monetary-landscape-200663982
- BOJ rate normalization timeline: https://seekingalpha.com/article/4853187-boj-may-finally-trigger-yen-carry-trade-unwind
