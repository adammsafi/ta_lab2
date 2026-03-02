# Architecture Patterns: Macro Regime Integration

**Domain:** Macro regime infrastructure for existing quant trading platform (ta_lab2)
**Researched:** 2026-03-01
**Confidence:** HIGH (based on direct source code analysis of all integration points)

---

## Executive Summary

The existing ta_lab2 regime infrastructure was designed with macro expansion in mind. The `cmc_regimes` table already has `l3_label` and `l4_label` columns (always NULL today). The resolver already accepts `L3` and `L4` keyword arguments and processes them in its tighten-only chain (`L2 -> L1 -> L0 -> L3 -> L4`). The `data_budget.py` already has `L4: 1` (always enabled) in its threshold table. This means macro regime integration is fundamentally a "fill in the empty slot" problem, not a "redesign the architecture" problem.

The integration requires: (1) a macro feature computation layer that reads FRED data and produces numeric features, (2) a macro labeler that converts features into L4-shaped regime keys, (3) wiring the L4 label into the existing refresh pipeline, and (4) new risk gates that consume macro signals. The existing `integrations/economic/` module (1,766 LOC) should be bypassed -- it is an API client for FRED, but the data already lives locally in `fred.series_values` (208K rows, 39 series). No API calls needed.

---

## Current Architecture (As-Is)

### Component Map

```
                    FRED VM (GCP)
                        |
              sync_fred_from_vm.py (SSH+COPY)
                        |
                        v
              fred.series_values (208K rows, 39 series)
              fred.releases
              fred.sync_log
                        |
                        | (currently: NO consumers)
                        v
                    [DEAD END]


    cmc_price_bars_multi_tf
            |
            v
    load_regime_input_data()          <- regime_data_loader.py
            |
            v
    label_layer_monthly()  (L0)       <- labels.py
    label_layer_weekly()   (L1)       <- labels.py
    label_layer_daily()    (L2)       <- labels.py
            |
            v
    HysteresisTracker.update()        <- hysteresis.py
            |
            v
    resolve_policy_from_table()       <- resolver.py
    (chain: L2 -> L1 -> L0 -> L3=None -> L4=None)
            |
            v
    write_regimes_to_db()             <- refresh_cmc_regimes.py
            |
            v
    cmc_regimes  (PK: id, ts, tf)
    cmc_regime_flips
    cmc_regime_stats
    cmc_regime_comovement
            |
            +-------> position_sizer.py  (reads regime_key, applies size_mult)
            +-------> regime_router.py   (reads l2_label, routes ML sub-models)
            +-------> risk_engine.py     (reads tail_risk_state, not regime labels directly)
            +-------> drift/attribution.py (Step 6: regime delta comparison)
```

### Key Files and Their Roles

| File | Path | Role | Integration Point |
|------|------|------|-------------------|
| `resolver.py` | `src/ta_lab2/regimes/resolver.py` | Tighten-only policy combiner | `resolve_policy_from_table(L0=, L1=, L2=, L3=, L4=)` -- L4 slot is ready |
| `labels.py` | `src/ta_lab2/regimes/labels.py` | Per-asset labelers (L0-L3) | Add L4 labeler or create separate macro labeler |
| `hysteresis.py` | `src/ta_lab2/regimes/hysteresis.py` | Tighten-immediate, loosen-after-N | Works with any layer key string -- no changes needed |
| `data_budget.py` | `src/ta_lab2/regimes/data_budget.py` | Layer enablement thresholds | L4 threshold already set to 1 (always enabled) |
| `proxies.py` | `src/ta_lab2/regimes/proxies.py` | BTC weekly fallback for young assets | No changes needed (macro is asset-agnostic) |
| `refresh_cmc_regimes.py` | `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` | Main refresh orchestrator | Must add L4 label computation + pass to resolver |
| `policy_loader.py` | `src/ta_lab2/regimes/policy_loader.py` | YAML policy overlay | Add macro-regime policy rules to YAML |
| `risk_engine.py` | `src/ta_lab2/risk/risk_engine.py` | 7-gate order risk engine | Add new macro-triggered gates |
| `position_sizer.py` | `src/ta_lab2/executor/position_sizer.py` | Regime-adjusted sizing | Already reads regime_key -- tighten-only propagation sufficient |
| `regime_router.py` | `src/ta_lab2/ml/regime_router.py` | Per-regime ML model dispatch | Could add macro-regime routing dimension |
| `sync_fred_from_vm.py` | `src/ta_lab2/scripts/etl/sync_fred_from_vm.py` | FRED data sync from GCP VM | Working, incremental, 39 series -- needs to run before macro features |
| `run_daily_refresh.py` | `src/ta_lab2/scripts/run_daily_refresh.py` | Pipeline orchestrator | Must add macro_features stage before regimes |
| `fred_provider.py` | `src/ta_lab2/integrations/economic/fred_provider.py` | FRED API client (UNUSED) | BYPASS -- data already local via sync pipeline |
| `attribution.py` | `src/ta_lab2/drift/attribution.py` | 6-source drift decomposition | Step 6 (regime) already exists -- macro adds a new attribution dimension |

### Resolver Chain Detail

The resolver processes layers in this order (line 125 of `resolver.py`):

```python
for key in (L2, L1, L0, L3, L4):
    if key:
        policy = _tighten(policy, _match_policy(key, policy_table))
    if key and "Stressed" in key:
        policy.orders = "passive"
```

**Critical insight:** L4 is processed LAST, meaning it has the final tighten-only pass. A macro "Recession" or "Tightening" label in L4 can override everything below it by tightening size_mult, widening stops, and forcing passive orders. This is exactly the desired behavior -- macro conditions should be the final override.

### cmc_regimes Table Schema

```sql
CREATE TABLE public.cmc_regimes (
    id                  INTEGER         NOT NULL,
    ts                  TIMESTAMPTZ     NOT NULL,
    tf                  TEXT            NOT NULL DEFAULT '1D',
    l0_label            TEXT            NULL,       -- Monthly (cycle)
    l1_label            TEXT            NULL,       -- Weekly (primary trend)
    l2_label            TEXT            NULL,       -- Daily (tactical)
    l3_label            TEXT            NULL,       -- Intraday (UNUSED)
    l4_label            TEXT            NULL,       -- Execution/Macro (UNUSED)
    regime_key          TEXT            NOT NULL,
    size_mult           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    stop_mult           DOUBLE PRECISION NOT NULL DEFAULT 1.5,
    orders              TEXT            NOT NULL DEFAULT 'mixed',
    gross_cap           DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    pyramids            BOOLEAN         NOT NULL DEFAULT TRUE,
    feature_tier        TEXT            NOT NULL DEFAULT 'lite',
    l0_enabled          BOOLEAN         NOT NULL DEFAULT FALSE,
    l1_enabled          BOOLEAN         NOT NULL DEFAULT FALSE,
    l2_enabled          BOOLEAN         NOT NULL DEFAULT FALSE,
    regime_version_hash TEXT            NULL,
    updated_at          TIMESTAMPTZ     DEFAULT now(),
    PRIMARY KEY (id, ts, tf)
);
```

**Important:** The schema has `l3_label` and `l4_label` columns but no `l3_enabled`/`l4_enabled` columns. Adding `l4_enabled` would require a migration. However, since `data_budget.py` already has `L4: 1` (always enabled), and the column can simply be populated, a new boolean column is optional but recommended for consistency.

---

## Recommended Architecture (To-Be)

### Decision 1: Where Do Macro Features Live?

**Recommendation: New `fred_macro_features` table (NOT extension of `cmc_features`).**

Rationale:
- `cmc_features` is PK'd on `(id, ts, tf)` -- it is per-asset, per-timeframe. Macro features are NOT per-asset. They are market-wide indicators (yield curve slope, MOVE index, CLI diffusion, etc.) that apply identically to all crypto assets.
- Stuffing macro columns into `cmc_features` would duplicate the same macro row across all 100+ assets, wasting storage and creating confusion about which `id` to read.
- A separate table with PK `(date)` is clean, simple, and correctly models the domain: macro features are a time series, not per-asset.

**Proposed schema:**

```sql
CREATE TABLE public.fred_macro_features (
    date                DATE            NOT NULL PRIMARY KEY,

    -- Yield curve
    yield_spread_10y2y  DOUBLE PRECISION NULL,   -- T10Y2Y (10yr - 2yr)
    yield_spread_10y3m  DOUBLE PRECISION NULL,   -- T10Y3M (10yr - 3mo)
    yield_curve_slope   DOUBLE PRECISION NULL,   -- Derived: normalized spread

    -- Rates
    fed_funds_rate      DOUBLE PRECISION NULL,   -- FEDFUNDS
    fed_funds_delta_3m  DOUBLE PRECISION NULL,   -- 3-month change

    -- Credit spreads
    baa_aaa_spread      DOUBLE PRECISION NULL,   -- BAA10Y - AAA10Y
    baa_aaa_zscore      DOUBLE PRECISION NULL,   -- Rolling z-score (252d)

    -- Money & liquidity
    m2_yoy_pct          DOUBLE PRECISION NULL,   -- M2 YoY growth
    m2_momentum         DOUBLE PRECISION NULL,   -- 3-month rate of change

    -- Volatility
    move_index          DOUBLE PRECISION NULL,   -- MOVE (bond vol) when available
    vix_level           DOUBLE PRECISION NULL,   -- VIXCLS when available

    -- Labor market
    unemployment_rate   DOUBLE PRECISION NULL,   -- UNRATE
    nfp_mom             DOUBLE PRECISION NULL,   -- PAYEMS month-over-month

    -- Inflation
    cpi_yoy             DOUBLE PRECISION NULL,   -- CPIAUCSL YoY
    pce_yoy             DOUBLE PRECISION NULL,   -- PCEPI YoY

    -- Leading indicators
    cli_oecd            DOUBLE PRECISION NULL,   -- OECD CLI
    sahm_indicator      DOUBLE PRECISION NULL,   -- SAHMREALTIME
    pmi_manufacturing   DOUBLE PRECISION NULL,   -- ISM PMI proxy

    -- Composite scores (computed)
    macro_risk_score    DOUBLE PRECISION NULL,   -- Weighted composite [0..1]
    liquidity_score     DOUBLE PRECISION NULL,   -- M2 + rates composite
    growth_score        DOUBLE PRECISION NULL,   -- Employment + PMI composite
    stress_score        DOUBLE PRECISION NULL,   -- Spreads + vol composite

    -- L4 regime label (derived from composites)
    l4_macro_label      TEXT            NULL,     -- e.g. "Expansion-EasyMoney-LowStress"

    -- Metadata
    computed_at         TIMESTAMPTZ     DEFAULT now(),
    source_freshness    DATE            NULL      -- Latest FRED observation used
);

-- Index for range queries
CREATE INDEX idx_fred_macro_features_date
    ON public.fred_macro_features (date DESC);
```

### Decision 2: Where Does the Macro Labeler Live?

**Recommendation: New `regimes/macro_labels.py` (NOT extension of `labels.py`).**

Rationale:
- The existing labelers in `labels.py` all share the same pattern: they operate on a per-asset DataFrame with price/EMA/ATR columns. Macro labeling is fundamentally different -- it reads from `fred_macro_features`, not from price bars.
- The output is still a string label compatible with the resolver's `_match_policy()` pattern matching, so it plugs in seamlessly.
- Keeping it separate makes testing easier (mock FRED data, not price data).

**Proposed module:**

```python
# src/ta_lab2/regimes/macro_labels.py

def label_macro_regime(macro_df: pd.DataFrame) -> pd.Series:
    """
    Classify macro environment into regime labels for L4.

    Returns Series of labels like:
    - "Expansion-EasyMoney-LowStress"
    - "Contraction-TightMoney-HighStress"
    - "Transition-NeutralMoney-RisingStress"

    Format: "{growth}-{liquidity}-{stress}" to match resolver pattern.
    """
```

**Label taxonomy for L4 (compatible with resolver's substring matching):**

| Dimension | Values | Source Features |
|-----------|--------|----------------|
| Growth | Expansion / Transition / Contraction | CLI, employment, PMI |
| Liquidity | EasyMoney / NeutralMoney / TightMoney | M2, fed funds rate/delta |
| Stress | LowStress / RisingStress / HighStress | Credit spreads, MOVE, VIX |

This produces 27 possible L4 labels. The resolver matches via substring, so policy rules can target:
- `"Contraction-"` -- any contraction (broad match)
- `"-HighStress"` -- any stress state (broad match)
- `"Contraction-TightMoney-HighStress"` -- exact (most restrictive)

### Decision 3: How Does L4 Connect to the Resolver?

**Recommendation: Use the existing L4 slot -- no new chain, no overlay, no pre-L0 bypass.**

The resolver already processes `L4` as the final tighten-only pass. This is the correct architecture because:

1. Macro conditions should tighten, never loosen. If per-asset regimes say "Up-Normal-Normal" (full size), but macro says "Contraction-TightMoney-HighStress", the final policy should be tightened. The resolver's `_tighten()` function guarantees this:
   - `size_mult = min(current, macro_suggested)`
   - `stop_mult = max(current, macro_suggested)`
   - `orders` can only degrade toward "passive"
   - `gross_cap = min(current, macro_suggested)`

2. L4 is processed last, so it is the ultimate override. No per-asset layer can undo a macro tightening.

**Required changes to `refresh_cmc_regimes.py` (lines ~446-454):**

```python
# CURRENT (line 447-454):
policy = resolve_policy_from_table(
    policy_table,
    L0=l0_val,
    L1=l1_val,
    L2=l2_val,
    L3=None,
    L4=None,  # <-- Currently hardcoded None
)

# PROPOSED:
policy = resolve_policy_from_table(
    policy_table,
    L0=l0_val,
    L1=l1_val,
    L2=l2_val,
    L3=None,
    L4=l4_val,  # <-- From macro labeler, same for all assets
)
```

**Required policy table additions (in `configs/regime_policies.yaml`):**

```yaml
rules:
  # Macro L4 tightening rules
  - match: "Contraction-TightMoney-HighStress"
    size_mult: 0.20
    stop_mult: 2.50
    orders: "passive"
    gross_cap: 0.30
    pyramids: false

  - match: "Contraction-"
    size_mult: 0.40
    stop_mult: 2.00
    orders: "conservative"
    gross_cap: 0.50

  - match: "-HighStress"
    size_mult: 0.50
    stop_mult: 2.00
    orders: "passive"

  - match: "-TightMoney-"
    size_mult: 0.70
    stop_mult: 1.75
    orders: "conservative"

  - match: "Expansion-EasyMoney-LowStress"
    size_mult: 1.00  # no tightening in benign macro
    stop_mult: 1.25
    orders: "mixed"
```

### Decision 4: Cross-Asset Aggregation

**Recommendation: Store in `fred_macro_features` composite scores; no separate aggregation table.**

Cross-asset aggregation (e.g., "what percentage of assets are in a down regime?") is a second-order concern. The primary value of macro regimes is the exogenous signal from FRED data. Cross-asset regime consensus can be computed from `cmc_regimes` on-the-fly:

```sql
SELECT
    ts,
    COUNT(*) FILTER (WHERE l2_label LIKE 'Down%') AS n_down,
    COUNT(*) FILTER (WHERE l2_label LIKE 'Up%') AS n_up,
    COUNT(*) AS n_total,
    COUNT(*) FILTER (WHERE l2_label LIKE 'Down%')::float / NULLIF(COUNT(*), 0) AS pct_down
FROM cmc_regimes
WHERE tf = '1D' AND ts = (SELECT MAX(ts) FROM cmc_regimes WHERE tf = '1D')
GROUP BY ts;
```

If this query becomes a bottleneck (unlikely with ~100 assets), materialize it as a view. But do not create a separate table now -- YAGNI.

The `fred_macro_features.macro_risk_score` column serves as the primary cross-signal aggregation point. It combines yield curve, credit spreads, and growth indicators into a single 0-to-1 score. This is sufficient for V1.

### Decision 5: New Risk Gates

**Recommendation: Add a "Macro Override" gate to `risk_engine.py` as Gate 1.7, after tail risk but before circuit breaker.**

The existing risk engine has this gate order:
1. Kill switch
1.5. Tail risk (FLATTEN/REDUCE)
1.6. Margin/liquidation check
2. Circuit breaker
3. Per-asset position cap
4. Portfolio utilization cap
5. All pass

**Proposed new gate:**

```
1.   Kill switch
1.5  Tail risk
1.6  Margin/liquidation
1.7  MACRO REGIME OVERRIDE (NEW)
2.   Circuit breaker
3.   Per-asset position cap (now macro-adjusted)
4.   Portfolio utilization cap (now macro-adjusted)
5.   All pass
```

Gate 1.7 reads the latest macro risk score from `fred_macro_features` and:
- **macro_risk_score > 0.8**: Block all new buy orders (similar to tail risk FLATTEN but macro-driven)
- **macro_risk_score > 0.6**: Halve max_position_pct and max_portfolio_pct
- **macro_risk_score > 0.4**: Reduce gross_cap by 20%
- **macro_risk_score <= 0.4**: Pass (no additional tightening)

This is separate from the L4 tighten-only policy overlay because:
1. L4 adjusts the per-bar regime policy in `cmc_regimes` (slow signal, changes daily)
2. Gate 1.7 reads the live macro score at order time (fast signal, could react to intra-day FRED releases)

**Implementation in `risk_engine.py`:**

```python
def _check_macro_gate(self, order_side: str) -> Optional[str]:
    """Gate 1.7: Macro regime override."""
    if order_side.lower() == "sell":
        return None  # Sells always allowed (reducing exposure)

    try:
        with self._engine.connect() as conn:
            row = conn.execute(text("""
                SELECT macro_risk_score, stress_score
                FROM fred_macro_features
                WHERE date <= CURRENT_DATE
                ORDER BY date DESC LIMIT 1
            """)).fetchone()

        if row is None:
            return None  # No macro data -> pass

        macro_score = float(row[0]) if row[0] is not None else 0.0

        if macro_score > 0.8:
            self._log_event(
                event_type="macro_regime_blocked",
                trigger_source="macro_regime",
                reason=f"Macro risk score {macro_score:.3f} > 0.8 -- new buys blocked",
            )
            return "blocked"

        if macro_score > 0.6:
            # Not blocking, but caller should halve limits
            return "reduce"

    except Exception as exc:
        logger.debug("Gate 1.7 macro check failed: %s -- passing", exc)
        return None

    return None
```

### Decision 6: Daily Refresh Pipeline Changes

**Recommendation: Insert `macro_features` stage between `desc_stats` and `regimes` in the pipeline.**

Current pipeline order (from `run_daily_refresh.py` line 2097):
```
bars -> EMAs -> AMAs -> desc_stats -> regimes -> features -> signals -> portfolio -> executor -> drift -> stats
```

Proposed pipeline order:
```
bars -> EMAs -> AMAs -> desc_stats -> fred_sync -> macro_features -> regimes -> features -> signals -> portfolio -> executor -> drift -> stats
                                      ^^^^^^^^    ^^^^^^^^^^^^^^^
                                      NEW STAGE    NEW STAGE
```

**Stage: `fred_sync`**
- Runs `sync_fred_from_vm.py --incremental` (already exists)
- Timeout: 120s (fast SSH COPY, existing TIMEOUT_EXCHANGE_PRICES = 120 is a good model)
- Failure mode: warn-and-continue (regime pipeline can still run with stale FRED data)

**Stage: `macro_features`**
- New script: `scripts/macro/refresh_macro_features.py`
- Reads from `fred.series_values`, computes features, writes to `fred_macro_features`
- Computes L4 label and stores it for use by the regime refresh stage
- Timeout: 300s (simple computation, ~39 series, ~208K rows)
- Failure mode: warn-and-continue (regimes still work with L4=None)

The regime refresh stage (`refresh_cmc_regimes.py`) then reads the latest L4 label from `fred_macro_features` once, and passes it to every asset's `compute_regimes_for_id()` call. Since macro features are asset-agnostic, the L4 label is computed ONCE and reused for all assets (no per-asset macro computation).

### Decision 7: Should `integrations/economic/` Be Revived or Bypassed?

**Recommendation: BYPASS. Use direct SQL reads from `fred.series_values`.**

Rationale:
1. The data is already local. `fred.series_values` has 208K rows across 39 series, synced incrementally via `sync_fred_from_vm.py`. No API calls to FRED are needed.
2. `FredProvider` is an API client with rate limiting, circuit breaker, and caching -- infrastructure for live API calls. Macro feature computation reads historical data from a local table. These are different use cases.
3. The existing sync pipeline (`sync_fred_from_vm.py`) handles data freshness, integrity verification, and even VM purging. It is production-tested and working.
4. Reviving 1,766 LOC of API client code for a use case that does not need API calls creates unnecessary coupling and test surface.

The `integrations/economic/` module remains deferred (not abandoned). If a future phase needs live API calls (e.g., intra-day economic releases, custom series not on the VM), it can be revived then.

---

## New Components Needed

### New Files

| File | Purpose | Est. LOC |
|------|---------|----------|
| `src/ta_lab2/regimes/macro_labels.py` | L4 macro regime labeler | ~150 |
| `src/ta_lab2/regimes/macro_features.py` | FRED-to-features computation (transforms, z-scores, composites) | ~300 |
| `src/ta_lab2/scripts/macro/refresh_macro_features.py` | CLI script: read FRED, compute features, write table, compute L4 | ~200 |
| `src/ta_lab2/scripts/macro/__init__.py` | Package init | ~1 |
| `sql/macro/100_fred_macro_features.sql` | DDL for `fred_macro_features` table | ~80 |
| `alembic/versions/xxx_macro_regime_tables.py` | Migration: create table + add l4_enabled column | ~60 |
| `configs/macro_regime_policies.yaml` | L4 policy rules for resolver | ~50 |
| `tests/test_macro_labels.py` | Unit tests for macro labeler | ~200 |
| `tests/test_macro_features.py` | Unit tests for feature computation | ~200 |

### Modified Files

| File | Change | Risk |
|------|--------|------|
| `src/ta_lab2/regimes/resolver.py` | Add macro-specific policy patterns to DEFAULT_POLICY_TABLE | LOW -- additive only, substring matching is backwards-compatible |
| `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` | Load L4 label from fred_macro_features, pass to resolver | MEDIUM -- core regime pipeline, but change is minimal (add 1 query + pass L4) |
| `src/ta_lab2/risk/risk_engine.py` | Add Gate 1.7 (macro override) | MEDIUM -- new gate in existing chain, must not break existing gates |
| `src/ta_lab2/scripts/run_daily_refresh.py` | Add `fred_sync` and `macro_features` stages | LOW -- pattern is well-established (copy from existing stages) |
| `src/ta_lab2/regimes/__init__.py` | Export macro_labels | LOW -- additive only |
| `configs/regime_policies.yaml` | Add L4 macro rules | LOW -- YAML overlay, existing rules untouched |

---

## Data Flow Diagram (To-Be)

```
    GCP VM (freddata DB)
         |
         | sync_fred_from_vm.py (SSH+COPY, incremental)
         v
    fred.series_values (39 series, 208K rows)
    PK: (series_id, date)
         |
         | refresh_macro_features.py (NEW)
         | 1. Read relevant series (yield curve, credit, M2, employment...)
         | 2. Compute transforms (spreads, z-scores, momentum, YoY)
         | 3. Compute composite scores (macro_risk, liquidity, growth, stress)
         | 4. Compute L4 label from composites
         | 5. Write to fred_macro_features
         v
    fred_macro_features (NEW)
    PK: (date)
    Cols: yield_spread_10y2y, baa_aaa_spread, m2_yoy_pct,
          macro_risk_score, l4_macro_label, ...
         |
         |    +--- cmc_price_bars_multi_tf
         |    |        |
         |    |        v
         |    |    label_layer_monthly/weekly/daily() (L0, L1, L2)
         |    |        |
         v    v        v
    refresh_cmc_regimes.py (MODIFIED)
         |
         | 1. Load latest L4 from fred_macro_features (1 row, same for all assets)
         | 2. Per asset: compute L0/L1/L2 (existing)
         | 3. Apply hysteresis (existing)
         | 4. resolve_policy_from_table(L0=, L1=, L2=, L3=None, L4=l4_val)
         | 5. Write to cmc_regimes with l4_label populated
         v
    cmc_regimes (l4_label NOW POPULATED)
         |
         +-------> position_sizer.py (regime_key now includes L4 tightening)
         +-------> regime_router.py  (l2_label unchanged, optionally add L4 dimension)
         +-------> risk_engine.py    (Gate 1.7: reads fred_macro_features.macro_risk_score)
         +-------> drift/attribution.py (new: macro regime delta attribution step)
```

---

## Pipeline Ordering (Daily Refresh)

```
Stage 1:  bars              (existing, no change)
Stage 2:  EMAs              (existing, no change)
Stage 3:  AMAs              (existing, no change)
Stage 4:  desc_stats        (existing, no change)
Stage 5:  fred_sync         (NEW -- run sync_fred_from_vm.py --incremental)
Stage 6:  macro_features    (NEW -- run refresh_macro_features.py)
Stage 7:  regimes           (MODIFIED -- now reads L4 from fred_macro_features)
Stage 8:  features          (existing, no change)
Stage 9:  signals           (existing, no change)
Stage 10: portfolio         (existing, no change)
Stage 11: executor          (MODIFIED -- risk engine now has Gate 1.7)
Stage 12: drift             (MODIFIED -- macro attribution step added)
Stage 13: stats             (existing, add macro feature QC checks)
```

**Dependency constraints:**
- Stage 5 (fred_sync) must run before Stage 6 (macro_features)
- Stage 6 (macro_features) must run before Stage 7 (regimes)
- Stage 7 (regimes) must run before Stage 9 (signals) -- existing constraint
- All other ordering constraints are unchanged

---

## Suggested Build Order

### Phase 1: Foundation -- Macro Feature Table + Computation

**Build:**
1. DDL for `fred_macro_features` table (Alembic migration)
2. `regimes/macro_features.py` -- transform FRED series into features
3. `scripts/macro/refresh_macro_features.py` -- CLI entrypoint
4. Tests for feature computation (unit tests with mock FRED data)

**Validates:** Can we compute meaningful macro features from the existing 39 FRED series?

**No downstream impact** -- nothing reads `fred_macro_features` yet.

### Phase 2: Macro Labeler + L4 Integration

**Build:**
1. `regimes/macro_labels.py` -- classify features into L4 labels
2. Modify `refresh_cmc_regimes.py` -- load L4, pass to resolver
3. Add L4 policy rules to `configs/regime_policies.yaml`
4. Add `fred_sync` + `macro_features` stages to `run_daily_refresh.py`
5. Tests: L4 label propagation through resolver, policy tightening

**Validates:** Does L4 tighten-only semantics work correctly? Are policy rules calibrated?

**Downstream impact:** `cmc_regimes.l4_label` now populated, `size_mult`/`stop_mult`/`orders`/`gross_cap` now reflect macro tightening. Position sizer automatically picks this up.

### Phase 3: Risk Gate + Observability

**Build:**
1. Gate 1.7 in `risk_engine.py` -- macro regime override
2. `dim_risk_limits` extension for macro thresholds (configurable)
3. Macro attribution step in `drift/attribution.py`
4. Dashboard panel for macro regime state
5. Telegram alerts for macro regime transitions

**Validates:** Does macro risk gating work in live paper trading? Does drift attribution correctly separate macro vs micro regime effects?

### Phase 4: Backtesting + Calibration

**Build:**
1. Historical macro regime backtest (apply L4 labels retroactively)
2. Calibrate composite weights (macro_risk_score formula)
3. Compare performance: with vs without macro regime overlay
4. Cross-validate L4 label transitions against known macro events

**Validates:** Does macro regime overlay improve risk-adjusted returns historically?

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Macro Features as Per-Asset Columns

**What:** Adding `yield_curve_slope`, `credit_spread` columns to `cmc_features` (PK: id, ts, tf).
**Why bad:** Duplicates identical macro values across 100+ assets. Makes it unclear whether macro features are asset-specific. Breaks the feature pipeline's per-asset write pattern.
**Instead:** Separate `fred_macro_features` table with PK `(date)`. One row per day, shared by all assets.

### Anti-Pattern 2: Separate Resolver Chain for Macro

**What:** Creating a new `resolve_macro_policy()` function that runs in parallel with the existing resolver.
**Why bad:** Two policies that must be reconciled. Risk of conflicting signals. Duplicates tighten-only logic.
**Instead:** Use the existing L4 slot. The resolver already handles 5 layers in a single tighten-only chain.

### Anti-Pattern 3: Reviving FredProvider for Local Data

**What:** Instantiating `FredProvider` to read data that already lives in `fred.series_values`.
**Why bad:** API key required, rate limiting overhead, network dependency for local data reads. The API client was designed for fetching from FRED servers, not for reading from a local Postgres table.
**Instead:** Direct SQL reads from `fred.series_values`. Simple, fast, no external dependencies.

### Anti-Pattern 4: Real-Time Macro Regime Updates

**What:** Trying to update macro regime labels intra-day based on economic releases.
**Why bad:** FRED data is published with variable delays (employment: 1st Friday, CPI: 2-3 week lag). Intra-day updates would mostly be noise. The daily refresh cadence is appropriate.
**Instead:** Daily macro feature computation, aligned with the daily refresh pipeline. The risk engine's Gate 1.7 can optionally read the latest score at order time for a "fast path" if needed later.

### Anti-Pattern 5: Over-Fitting Macro Labels to Crypto Price History

**What:** Training a classifier to predict crypto regime from FRED data (supervised learning).
**Why bad:** Crypto-FRED relationship is non-stationary and regime-dependent itself. Overfitting guaranteed with short history. Rule-based labeling with economic priors is more robust.
**Instead:** Rule-based macro labeler with economically motivated thresholds. Validate via backtest, but do not train on crypto returns.

---

## Scalability Considerations

| Concern | Current Scale | At Scale | Approach |
|---------|--------------|----------|----------|
| FRED data volume | 208K rows, 39 series | ~500K rows, 50+ series | Fine -- single table, daily append |
| Macro feature computation | ~39 series, trivial | ~50 series, trivial | Pure pandas, <1 second |
| L4 label per-asset | 1 label, broadcast to all | Same | L4 is global, no per-asset cost |
| Risk gate DB read | 1 query per order | Same | Single row read, <1ms |
| Daily refresh pipeline | +2 stages (~5 seconds) | Same | SSH COPY + pandas transforms |

---

## Sources

- Direct code analysis of all files listed in the Component Map section
- `cmc_regimes` DDL: `C:/Users/asafi/Downloads/ta_lab2/sql/regimes/080_cmc_regimes.sql`
- Resolver chain: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/regimes/resolver.py`, lines 124-130
- Data budget L4 threshold: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/regimes/data_budget.py`, line 21
- FRED sync pipeline: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/etl/sync_fred_from_vm.py`
- Risk engine gates: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/risk/risk_engine.py`, lines 1-34 (docstring)
- Daily refresh ordering: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/run_daily_refresh.py`, line 2097
- FRED data status from MEMORY.md: 208K rows, 39 series, PK: series_id, date
- Refresh script integration: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py`, lines 446-454
- Position sizer regime usage: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/executor/position_sizer.py`, lines 190-193
- ML regime router: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/ml/regime_router.py`, lines 45-110
- Drift attribution: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/drift/attribution.py`, lines 296-309
- Policy loader: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/regimes/policy_loader.py`
- Hysteresis tracker: `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/regimes/hysteresis.py`
- FredProvider (bypassed): `C:/Users/asafi/Downloads/ta_lab2/src/ta_lab2/integrations/economic/fred_provider.py`
