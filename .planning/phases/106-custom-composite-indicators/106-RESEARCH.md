# Phase 106: Custom Composite Indicators - Research

**Researched:** 2026-04-01
**Domain:** Proprietary composite indicator construction, full validation gauntlet (CPCV + permutation IC + FDR + held-out), dim_feature_registry promotion with source_type
**Confidence:** HIGH (all codebase patterns read directly; schemas verified from Alembic migrations; CPCV/CV splitters verified from cv.py; feature write patterns verified from base_feature.py and cross_timeframe.py)

---

## Summary

Phase 106 builds 6 proprietary composite indicators that combine AMA ER state, CTF
agreement, Hyperliquid OI/funding data, cross-asset lead-lag signals, and multi-TF
alignment into novel features not available in any single source table. Each composite
is validated with the strictest test battery in this project: permutation IC (p<0.05),
FDR across all 6 composites, CPCV with purge+embargo, and held-out validation on the
most recent 20% of data. Survivors are promoted to `dim_feature_registry` with
`source_type='proprietary'`.

**Critical dependency caveat:** Phases 102-105 are fully planned but their code
deliverables do not yet exist in the codebase. Specifically, `multiple_testing.py`
(permutation_ic_test, fdr_control, block_bootstrap_ic), `trial_registry` DB table,
`indicators_extended.py`, `indicators_derivatives.py`, `derivatives_input.py`, and
`param_optimizer.py` are all absent as of the research date. Phase 106 depends on
these artifacts. The plan MUST declare this dependency explicitly and treat Phase
102-105 as prerequisite work that must be complete before Phase 106 executes.

**What was researched:** AMA ER availability in `ama_multi_tf` (`er` column, KAMA
only); CTF table schema and column naming convention; `lead_lag_ic` table (Phase 98,
confirmed present in migrations); `ctf_composites` table (Phase 98, confirmed
present); `hl_funding_rates` and `hl_open_interest` schemas (Hyperliquid schema);
`CPCVSplitter` and `PurgedKFoldSplitter` interfaces in `cv.py`; `dim_feature_registry`
schema (no `source_type` column — needs Alembic migration to add it); `FeaturePromoter`
class in `experiments/promoter.py`; `features` table write patterns; `ic.py` API;
Phase 102 research document (library choices and trial_registry schema); Phase 105
research document (Optuna sweep pattern, sweep_id); Alembic HEAD `t4u5v6w7x8y9`.

**Primary recommendation:** Build Phase 106 as two plans: (1) implement all 6
composite indicator computation functions in a new `composite_indicators.py` and wire
them into the features write pipeline; (2) run the full 4-tier validation gauntlet and
promote survivors. All infrastructure (testing harness, CPCV, IC sweep) already exists
in the codebase. The only new code is the composite formulas themselves plus a thin
Alembic migration to add `source_type` to `dim_feature_registry`.

---

## Standard Stack

### Core (all already installed — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.4.1 | Rolling math, vectorized composite formulas | Used everywhere in features/ |
| pandas | 2.3.3 | DataFrame operations, rolling windows, groupby per (id, venue_id) | Standard throughout features/ |
| scipy.stats.spearmanr | (installed) | IC computation for permutation tests and CPCV folds | Already used in ic.py and (planned) multiple_testing.py |
| statsmodels.stats.multitest.fdrcorrection | 0.14.6 (installed) | FDR across 6 composite p-values | Same library as Phase 102 plan |
| sklearn.model_selection.BaseCrossValidator | (installed) | Base class; CPCVSplitter already subclasses it | cv.py already implements CPCVSplitter |
| sqlalchemy.text | (installed) | All DB reads (ama_multi_tf, ctf, lead_lag_ic, hl_funding_rates) and feature writes | Project convention |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| arch.bootstrap.StationaryBootstrap | 8.0.0 (installed) | Block bootstrap IC CI in validation gauntlet | Via block_bootstrap_ic() from Phase 102's multiple_testing.py |
| itertools | stdlib | Cross-timeframe pair enumeration, CPCV fold combination generation | Already used in cv.py CPCVSplitter |

### No New Dependencies

All required library functions are already installed. The only new code artifact is
`composite_indicators.py` (new module) and thin additions to analysis scripts.

**Installation:**
```bash
# Nothing to install
python -c "import numpy, pandas, scipy, statsmodels, sklearn, arch; print('all present')"
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/features/
├── composite_indicators.py     # NEW Phase 106 — 6 composite formulas

src/ta_lab2/scripts/features/
├── run_composite_refresh.py    # NEW Phase 106 — orchestrate composite computation

src/ta_lab2/scripts/analysis/
├── run_composite_validation.py # NEW Phase 106 — CPCV + permutation + FDR + held-out

alembic/versions/
└── u5v6w7x8y9z0_phase106_composite_source_type.py  # NEW — adds source_type to dim_feature_registry

docs/
└── COMPOSITES.md               # NEW Phase 106 — construction logic documentation
```

### Pattern 1: Input Loading for Composite Formulas

Each composite draws from different source tables. Load per (id, venue_id, tf) batch,
merge on (id, ts) index.

**AMA ER** (from `ama_multi_tf`, KAMA rows only):
```python
# Source: verified from ama_computations.py and base_ama_feature.py
# er column is non-NULL for KAMA rows, NULL for DEMA/TEMA/HMA
SELECT id, venue_id, ts, tf, er
FROM public.ama_multi_tf
WHERE id = :id AND venue_id = :venue_id AND tf = :tf
  AND indicator = 'KAMA'
  AND er IS NOT NULL
ORDER BY ts
```

**CTF agreement/divergence** (from `public.ctf`):
```python
# Source: verified from r2s3t4u5v6w7 migration and cross_timeframe.py
# Use load_ctf_features() — already exists at cross_timeframe.py:221
from ta_lab2.features.cross_timeframe import load_ctf_features
ctf_df = load_ctf_features(conn, asset_id, base_tf, train_start, train_end)
# Columns: e.g., rsi_14_7d_slope, rsi_14_7d_agreement, rsi_14_7d_divergence
```

**Lead-lag IC** (from `public.lead_lag_ic`):
```python
# Source: verified from r2s3t4u5v6w7 migration
# PK: (asset_a_id, asset_b_id, feature, horizon, tf, venue_id)
# is_significant boolean; ic NUMERIC; ic_p_bh NUMERIC (BH-adjusted)
SELECT asset_a_id, asset_b_id, feature, ic, ic_p_bh, is_significant
FROM public.lead_lag_ic
WHERE tf = :tf AND horizon = :horizon AND is_significant = true
```

**OI** (from `hyperliquid.hl_open_interest` via CMC id -> HL asset_id mapping):
```python
# Source: verified from f7a8b9c0d1e2 migration
# hl_open_interest PK: (asset_id, ts) — asset_id is HL SmallInteger namespace
# Columns: open, high, low, close (OI in base asset), ts TIMESTAMPTZ
# CRITICAL: must map CMC id -> HL asset_id via dim_asset_identifiers or hl_assets
```

**Funding rates** (from `hyperliquid.hl_funding_rates`):
```python
# Source: verified from f7a8b9c0d1e2 migration
# PK: (asset_id, ts) — hourly snapshots
# Columns: funding_rate NUMERIC, premium NUMERIC
# Same CMC id -> HL asset_id mapping required
```

### Pattern 2: Feature Write Pipeline (UPDATE pattern for supplemental columns)

Phase 98's research established: use UPDATE pattern (not DELETE+INSERT) when adding
supplemental columns to existing features rows. Verified in 98-RESEARCH.md.

```python
# Source: Pattern B from 98-RESEARCH.md, cross_timeframe.py line patterns
UPDATE public.features
SET composite_col = :value
WHERE id = :id AND venue_id = :venue_id AND ts = :ts
  AND tf = :tf AND alignment_source = :alignment_source
```

Alembic migration MUST add each composite column before writing. Follow pattern from
`d4e5f6a1b2c3` migration:

```python
op.add_column(
    "features",
    sa.Column("ama_er_regime_signal", sa.Float(), nullable=True),
    schema="public",
)
```

### Pattern 3: CPCV Validation with CPCVSplitter

**Source:** Verified from `src/ta_lab2/backtests/cv.py` (CPCVSplitter class).

CPCVSplitter requires a `t1_series` (label-end timestamps). For IC-based evaluation
the "label end" is `ts + horizon * tf_days`. Default parameters: `n_splits=6`,
`n_test_splits=2` (gives C(6,2)=15 path combinations).

```python
# Source: verified against cv.py CPCVSplitter.__init__ signature
from ta_lab2.backtests.cv import CPCVSplitter
import pandas as pd

# Build t1_series: index = label-start ts, value = label-end ts
t1 = feature_df.index + pd.Timedelta(days=horizon * tf_days_nominal)
t1_series = pd.Series(t1.values, index=feature_df.index)

splitter = CPCVSplitter(
    n_splits=6,
    n_test_splits=2,
    t1_series=t1_series,
    embargo_frac=0.01,
)

ic_results = []
for train_idx, test_idx in splitter.split(feature_arr):
    feat_train = feature_arr[train_idx]
    ret_train = fwd_ret_arr[train_idx]
    feat_test = feature_arr[test_idx]
    ret_test = fwd_ret_arr[test_idx]
    ic_test = spearmanr(feat_test, ret_test).statistic
    ic_results.append(ic_test)

cpcv_ic_mean = np.nanmean(ic_results)
```

**Key constraint:** `t1_series` index must be monotonically increasing — verify before
constructing. CPCVSplitter raises `ValueError` if not.

### Pattern 4: Held-Out Split

Use the most recent 20% of bars (by timestamp) as held-out. Train on the first 80%,
validate permutation IC and CPCV on the 80%, then evaluate IC and compare sign on
held-out 20%. Do not use held-out data during formula development — touch it once,
at the end, as a final gate.

```python
# Source: principle verified from cv.py design; split logic is straightforward
n = len(feature_df)
cutoff_idx = int(n * 0.80)
train_df = feature_df.iloc[:cutoff_idx]
held_out_df = feature_df.iloc[cutoff_idx:]

# Permutation IC and CPCV on train_df only
# Final held-out IC computed once after all composite design is frozen
held_out_ic = spearmanr(
    held_out_df["composite"].values,
    held_out_df["fwd_ret_1"].values,
).statistic
```

**Hold-out failure handling (Claude's discretion):** If held-out IC sign disagrees
with train IC sign (opposite direction), treat as fail. If |held-out IC| < 0.01 but
same sign as train, treat as inconclusive — include in FDR batch but flag as marginal.
Do not redesign composites based on held-out results; held-out is a one-shot gate.

### Pattern 5: FDR Across 6 Composites

Apply FDR to the 6 composite p-values as a batch. This uses the same
`fdr_control()` function planned in Phase 102 (`multiple_testing.py`).
If Phase 102's `multiple_testing.py` is not yet built, implement inline
using `statsmodels.stats.multitest.fdrcorrection` directly.

```python
# Source: 102-RESEARCH.md fdr_control() pattern; statsmodels 0.14.6 verified
from statsmodels.stats.multitest import fdrcorrection
import numpy as np

p_values = [p1, p2, p3, p4, p5, p6]  # one per composite, horizon=1 arith
rejected, p_adj = fdrcorrection(np.array(p_values), alpha=0.05, method="indep")
# rejected[i] = True means composite i survives FDR gate
```

### Pattern 6: dim_feature_registry Promotion with source_type

`dim_feature_registry` does NOT currently have a `source_type` column. The column
must be added via Alembic migration `u5v6w7x8y9z0` before promotion writes.

```python
# Alembic migration fragment
op.add_column(
    "dim_feature_registry",
    sa.Column("source_type", sa.Text(), nullable=True),
    schema="public",
)
# Optional CHECK constraint to enforce valid values
op.create_check_constraint(
    "ck_feature_registry_source_type",
    "dim_feature_registry",
    "source_type IN ('standard', 'proprietary', 'derived', 'ctf', 'macro')",
    schema="public",
)
```

Promotion INSERT (extends existing FeaturePromoter pattern):
```python
# Source: verified from experiments/promoter.py _write_to_registry() at line 518
# Add source_type to the INSERT column list and VALUES binding
INSERT INTO public.dim_feature_registry (
    feature_name, lifecycle, source_type, description,
    promoted_at, best_ic, best_horizon, updated_at
) VALUES (
    :feature_name, 'promoted', 'proprietary', :description,
    now(), :best_ic, :best_horizon, now()
) ON CONFLICT (feature_name) DO UPDATE SET
    lifecycle = 'promoted',
    source_type = EXCLUDED.source_type,
    ...
```

**Alternative:** Use the existing `FeaturePromoter.promote_feature()` and patch
`source_type` with a follow-up UPDATE. This avoids modifying `promoter.py` but is
less clean. Prefer extending `_write_to_registry()` to accept `source_type` param.

### Anti-Patterns to Avoid

- **Computing composite columns with DELETE+INSERT on features:** This would delete
  all other feature columns for the same (id, ts, tf) row. Use UPDATE pattern.
- **Using HL `asset_id` as the join key instead of CMC `id`:** The IC sweep, features
  table, and `load_feature_series()` all use CMC `id`. Resolve HL `asset_id` -> CMC
  `id` before joining OI/funding data. Verified in 104-RESEARCH.md.
- **Running CPCV on held-out data:** CPCV uses only the 80% training window.
  Held-out is a separate one-shot final gate.
- **Applying FDR across permutation runs (not just across 6 composites):** FDR is
  applied once, to the 6 composite p-values. Do not re-apply FDR per asset or per TF.
- **Expecting ER for non-KAMA AMA indicators:** The `er` column is NULL for DEMA,
  TEMA, and HMA. Filter `WHERE indicator = 'KAMA'` before reading the ER column.

---

## The 6 Composite Designs

Specific formula design is Claude's full discretion. Research establishes the data
availability, input signals, and formula constraints for each.

### Composite 1: AMA ER Regime Signal

**Goal:** Single feature summarizing whether the current market is in trending vs
choppy regime, using KAMA's efficiency ratio as the primary signal.

**Data sources confirmed available:**
- `ama_multi_tf.er` — KAMA ER value, range [0, 1]; higher = trending; NULL for non-KAMA
- `ama_multi_tf.ama` — KAMA value for slope computation (close - KAMA) / ATR
- Use KAMA with default er_period=10, fast_period=2, slow_period=30 unless Phase 105
  optimized parameters indicate different values

**Formula guidance (Claude's discretion):**
- Multi-threshold approach over binary gate gives more information: ER quantile rank
  over rolling N-bar window (e.g., 60 bars) produces a bounded continuous signal [0,1]
  that is more predictive than a hard threshold
- Combine with direction: ER * sign(close - KAMA) gives a directional regime signal
- Output column name: `ama_er_regime_signal`

**Warmup:** `er_period` bars (default 10) before first valid ER; add rolling quantile
window (60 bars) for warmup of 70 bars total before first composite value.

### Composite 2: OI-Divergence x CTF Agreement Interaction

**Goal:** Combine open interest divergence (from price) with CTF cross-timeframe
agreement to create a signal that fires when price and OI are confirming or diverging
across timeframes simultaneously.

**Data sources confirmed available:**
- `hyperliquid.hl_open_interest.close` — OI in base asset at each timestamp
- `public.ctf.agreement` for base_tf=1D and ref_tf=7D, indicator=ret_arith — verified
  present in dim_ctf_indicators (22 seeded indicators include `ret_arith`)
- CTF agreement column name convention: `ret_arith_7d_agreement`

**Critical complication:** HL OI is in `hyperliquid` schema, keyed by HL `asset_id`
(SmallInteger). The CMC-keyed features table uses `id` (Integer). Need HL->CMC mapping.
Query: `SELECT asset_id FROM hyperliquid.hl_assets WHERE symbol = :symbol`. Only
assets present in both HL and CMC will produce values; others get NULL.

**Formula guidance:**
- OI change rate: `(OI[t] - OI[t-N]) / OI[t-N]` over 5-bar window (OI momentum)
- OI-price divergence: normalize OI momentum and price momentum, compute sign difference
- Interaction: `oi_divergence_zscore * ctf_agreement` — multiplies two bounded signals
- Output column name: `oi_divergence_ctf_agreement`

### Composite 3: Funding-Adjusted Momentum

**Goal:** Standard price momentum (e.g., 20-bar returns) adjusted by cumulative
funding rate to capture the net momentum signal after accounting for carry cost.

**Data sources confirmed available:**
- `hyperliquid.hl_funding_rates.funding_rate` — hourly snapshots, needs resampling to
  daily (1D) by summing 8 hourly rates per day (8h funding period on Hyperliquid)
- `price_bars_multi_tf.close` — for momentum computation
- Funding rates in `hl_funding_rates` are per 8h; multiply by 3 for daily rate

**Formula guidance:**
- Raw momentum: `(close[t] - close[t-N]) / close[t-N]` with N from Phase 105 results
- Funding adjustment: `raw_momentum - cumsum(daily_funding_rate, N)`
- Z-score normalize both components before combining for comparability
- Output column name: `funding_adjusted_momentum`

**Data coverage caveat:** Only Hyperliquid-listed perps have funding rate data. The
composite will be NULL for CMC assets not listed on Hyperliquid. Document this in
COMPOSITES.md. Validate IC only on assets with >=50% non-NULL coverage.

### Composite 4: Cross-Asset Lead-Lag Composite

**Goal:** Aggregate the IC-weighted lead signals from tier-1 assets into a composite
predictor for each target asset.

**Data sources confirmed available:**
- `public.lead_lag_ic` — Phase 98 table; PK (asset_a_id, asset_b_id, feature, horizon,
  tf, venue_id); columns `ic`, `ic_p_bh`, `is_significant`
- Default tier-1 fallback IDs: [1, 1027, 5426, 52, 1839, 1975, 32196] (from
  run_ctf_lead_lag_ic.py line 49 — BTC, ETH, SOL, XRP, BNB, LINK, HYPE)

**Decision: use Phase 98 results, not recompute.** The `lead_lag_ic` table already
holds BH-significant pairs. Recomputing would duplicate work. If the table is empty
or has no significant rows, log a warning and skip this composite.

**Formula guidance:**
- For target asset B: collect all rows where `asset_b_id = B` and `is_significant = true`
- For each significant predictor A: look up A's CTF feature value at time `t - lag`
  where lag is the horizon stored in the lead_lag_ic row
- IC-weighted combination: `sum(ic_A * feature_A[t-lag]) / sum(abs(ic_A))`
- This is a runtime computation — read lead_lag_ic metadata once, apply as a
  weighted sum formula per bar
- Output column name: `cross_asset_lead_lag_composite`

**Fallback for empty lead_lag_ic:** If no significant rows exist for a target asset,
the composite is NaN for all bars of that asset. Do not impute.

### Composite 5: TF Alignment Score

**Goal:** Score how aligned the trend direction is across multiple timeframes for
an asset, using CTF slope or agreement columns.

**Data sources confirmed available:**
- `public.ctf` table with slope and agreement columns per (base_tf, ref_tf, indicator)
- CTF base TFs: 1D, 2D, 3D, 7D, 14D, 30D — all present in dim_ctf_indicators

**Selected timeframes (Claude's discretion):** 1D base with ref_tfs 7D, 14D, 30D,
plus 7D base with ref_tf 30D. This gives 4 (base_tf, ref_tf) pairs. Use `ret_arith`
indicator (directional) for maximum signal content.

**Formula guidance:**
- Agreement fraction: for each (base_tf, ref_tf) pair, read `agreement` column
  (rolling fraction of sign-matching bars, already computed in ctf table)
- TF alignment score: mean of 4 agreement values at each timestamp
  `(agreement_1d_7d + agreement_1d_14d + agreement_1d_30d + agreement_7d_30d) / 4`
- Range: [0, 1]; 0.5 = random; >0.6 = bullish alignment; <0.4 = bearish alignment
- Optionally: subtract 0.5 to center on zero, then z-score for IC computation
- Output column name: `tf_alignment_score`

**Implementation note:** Load via `load_ctf_features()` — it already returns these
columns with the naming convention `ret_arith_{ref_tf_lower}_agreement`.

### Composite 6: Volume-Regime Gated Trend

**Goal:** Trend signal (e.g., close vs KAMA distance, normalized) gated by whether
volume is expanding (regime = confirmed trend) vs contracting (regime = noise).

**Data sources confirmed available:**
- `price_bars_multi_tf.volume` and `price_bars_multi_tf.close`
- `ama_multi_tf.ama` (KAMA values) — same table used for Composite 1
- No external tables needed — fully self-contained from bars + AMA tables

**Formula guidance:**
- Price trend signal: `(close - kama) / (atr_N)` — ATR-normalized distance from KAMA,
  where ATR is computed inline (rolling 14-bar TR average)
- Volume regime gate: `vol_ratio = volume / rolling_mean(volume, 20)`; gate = 1 if
  `vol_ratio > 1.2`, else 0 (or continuous: tanh of vol_ratio - 1)
- Gated trend: `trend_signal * vol_gate` (continuous) or
  `trend_signal * (vol_ratio > 1.2).astype(float)` (binary)
- Output column name: `volume_regime_gated_trend`

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Purged K-Fold CV | Custom time-series split | `PurgedKFoldSplitter` from `cv.py` | Already implements purge + embargo per Lopez de Prado Ch7 |
| CPCV path generation | Custom fold combination loop | `CPCVSplitter` from `cv.py` | Already implements C(n,k) fold combination, purge, embargo |
| Block bootstrap CI | Custom bootstrap loop | `block_bootstrap_ic()` from Phase 102's `multiple_testing.py` | Handles adaptive block length via arch 8.0.0 |
| FDR correction | Custom BH loop | `statsmodels.stats.multitest.fdrcorrection` | Phase 102 already chose this; use same |
| IC computation | Manual rank correlation | `scipy.stats.spearmanr` via `ic.py` functions | Project standard; consistent |
| CTF feature loading | Direct SQL join over ctf table | `load_ctf_features()` in `cross_timeframe.py:221` | Already built, handles alignment and column naming |
| Feature write | Direct INSERT to features | UPDATE pattern (see Pattern 2) | DELETE+INSERT would destroy other feature columns |
| HL->CMC ID mapping | Ad hoc JOIN | `hyperliquid.hl_assets JOIN dim_asset_identifiers` or the adapter pattern from Phase 104 research | Namespace difference is critical; HL asset_id != CMC id |

**Key insight:** All statistical infrastructure for this phase (permutation, FDR, CPCV,
bootstrap CI) is either already built or fully specified in Phase 102's research
document. The novel work is exclusively the 6 composite formula implementations.

---

## Common Pitfalls

### Pitfall 1: Phase 102-105 Prerequisites May Not Exist

**What goes wrong:** Phase 106 plans reference `multiple_testing.py`,
`trial_registry` table, `indicators_extended.py`, `indicators_derivatives.py`,
`param_optimizer.py` — none of these currently exist in the codebase (verified by
Grep search returning no results).

**Why it happens:** Phases 102-105 are planned but not yet executed.

**How to avoid:** Plan 106-01 must explicitly depend on Phases 102-105 completion.
If `multiple_testing.py` is absent, implement the permutation and FDR steps inline
using `scipy.stats.spearmanr` and `statsmodels.stats.multitest.fdrcorrection` directly
(same libraries, same logic). Do not import from a non-existent module.

**Warning signs:** `ImportError: cannot import name 'permutation_ic_test' from
'ta_lab2.analysis.multiple_testing'` — means Phase 102 hasn't run.

### Pitfall 2: ER Column is NULL for Non-KAMA Rows

**What goes wrong:** Query returns NULL ER values and composite computation produces
all-NaN output.

**Why it happens:** `ama_multi_tf.er` is only populated for KAMA indicator rows.
DEMA, TEMA, and HMA have `er = NULL`.

**How to avoid:** Always filter `WHERE indicator = 'KAMA'` when loading ER.
Verified in `ama_computations.py` — `compute_kama()` returns `(kama_arr, er_arr)`;
other compute functions return `(ama_arr, None)` which writes NULL.

**Warning signs:** Composite 1 returns all-NaN for an asset that has AMA data.
Check: `SELECT COUNT(*) FROM ama_multi_tf WHERE id=:id AND er IS NOT NULL`.

### Pitfall 3: Hyperliquid Asset ID Namespace Mismatch

**What goes wrong:** OI or funding composites produce wrong values or silent misjoins
because `hl_assets.asset_id` (SmallInteger) does not match CMC `id` (Integer).

**Why it happens:** HL uses its own sequential integer IDs for perp assets. CMC uses
a different integer namespace. `asset_id=1` in HL is not BTC; `id=1` in CMC is BTC.

**How to avoid:** Join via `hl_assets.symbol` -> CMC asset lookup. Verified in Phase
104 research document as "the most critical technical challenge in Phase 104." The
mapping query:
```sql
SELECT ha.asset_id AS hl_asset_id, :cmc_id AS cmc_id
FROM hyperliquid.hl_assets ha
WHERE ha.symbol = :symbol AND ha.asset_type = 'perp'
```
Then use `hl_asset_id` for all HL table joins.

**Warning signs:** BTC composite shows ETH's funding rate values.

### Pitfall 4: CTF Table Has No Data for Non-Active Indicator-TF Combinations

**What goes wrong:** `load_ctf_features()` returns empty DataFrame for some (asset,
tf) combinations that appear valid.

**Why it happens:** `refresh_ctf` only computes combinations in `ctf_config.yaml`.
Not all 22 indicators x 27 TF pairs are active; only the seeded combinations exist.

**How to avoid:** Before designing Composite 5, verify the 4 TF pairs
(1D/7D, 1D/14D, 1D/30D, 7D/30D) with `ret_arith` indicator are actually in
`ctf_config.yaml`. Check:
```bash
grep -A3 "ret_arith" configs/ctf_config.yaml | head -30
```
If a pair is missing, either add it to the config and re-run `refresh_ctf`, or use a
different TF pair that is already computed.

**Warning signs:** `load_ctf_features()` returns DataFrame with zero rows or missing
expected columns.

### Pitfall 5: features Table Column Must Exist Before Writing

**What goes wrong:** Feature write silently drops composite values because
`_get_table_columns()` doesn't see the column in `information_schema.columns`.

**Why it happens:** The `BaseFeature` write pattern introspects actual DB columns
and silently drops DataFrame columns not present. If the Alembic migration hasn't
run, the composite column doesn't exist and no values are written — no error raised.

**How to avoid:** Run Alembic migration `u5v6w7x8y9z0` BEFORE running the composite
refresh script. Verify column existence:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema='public' AND table_name='features'
AND column_name = 'ama_er_regime_signal';
```

**Warning signs:** Script runs without error but `SELECT ama_er_regime_signal FROM
features LIMIT 5` returns all NULL.

### Pitfall 6: CPCVSplitter Requires Monotonically Increasing t1_series Index

**What goes wrong:** `ValueError: t1_series index must be monotonically increasing`
at CPCVSplitter construction.

**Why it happens:** Feature DataFrame may have duplicate timestamps (if two alignment
sources are loaded) or unsorted index.

**How to avoid:** Sort by index and verify before constructing:
```python
assert feature_df.index.is_monotonic_increasing, "Sort by ts before CPCV"
feature_df = feature_df.sort_index()
```

**Warning signs:** ValueError at runtime during CPCV setup.

### Pitfall 7: FDR Batch Size Is Only 6

**What goes wrong:** BH FDR with only 6 p-values applies very mild correction;
almost all composites pass. This is technically correct but statistically weak.

**Why it happens:** FDR is most powerful with large batches. With 6 tests, the BH
threshold is lenient.

**How to avoid:** This is by design — we have exactly 6 composites. Accept the
statistical limitation and document it in COMPOSITES.md. The held-out gate and
permutation IC test (independent of FDR) provide the complementary rigor.

---

## Code Examples

### Loading AMA ER for a Single (asset_id, tf) Pair

```python
# Source: verified from ama_computations.py and base_ama_feature.py patterns
from sqlalchemy import text

def load_ama_er(conn, asset_id: int, tf: str, venue_id: int = 1) -> pd.DataFrame:
    """Load KAMA ER series for composite construction."""
    sql = text("""
        SELECT ts, er
        FROM public.ama_multi_tf
        WHERE id = :id
          AND venue_id = :venue_id
          AND tf = :tf
          AND indicator = 'KAMA'
          AND er IS NOT NULL
        ORDER BY ts
    """)
    df = pd.read_sql(sql, conn, params={"id": asset_id, "venue_id": venue_id, "tf": tf})
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")
```

### AMA ER Regime Signal Formula

```python
# Source: designed from verified ama_computations.py ER semantics
import numpy as np
import pandas as pd

def compute_ama_er_regime_signal(
    er: pd.Series,
    kama: pd.Series,
    close: pd.Series,
    er_quantile_window: int = 60,
) -> pd.Series:
    """
    ER quantile rank in rolling window, directional-signed.
    Range: [-1, +1]; positive = trending upward, negative = trending downward.
    """
    er_rank = er.rolling(er_quantile_window, min_periods=20).rank(pct=True)
    direction = np.sign(close - kama)
    return (er_rank * direction).rename("ama_er_regime_signal")
```

### CPCV Fold IC Evaluation

```python
# Source: verified from cv.py CPCVSplitter interface
from ta_lab2.backtests.cv import CPCVSplitter
from scipy.stats import spearmanr
import numpy as np
import pandas as pd

def run_cpcv_ic(
    feature_arr: np.ndarray,
    fwd_ret_arr: np.ndarray,
    ts_index: pd.DatetimeIndex,
    tf_days_nominal: int,
    horizon: int = 1,
    n_splits: int = 6,
) -> dict:
    """Run CPCV over a composite feature, return mean IC and per-path ICs."""
    # Build t1_series: label ends at ts + horizon bars ahead
    t1_values = ts_index + pd.Timedelta(days=horizon * tf_days_nominal)
    t1_series = pd.Series(t1_values, index=ts_index)

    splitter = CPCVSplitter(
        n_splits=n_splits,
        n_test_splits=2,
        t1_series=t1_series,
        embargo_frac=0.01,
    )

    path_ics = []
    for train_idx, test_idx in splitter.split(feature_arr):
        test_feat = feature_arr[test_idx]
        test_ret = fwd_ret_arr[test_idx]
        valid = ~(np.isnan(test_feat) | np.isnan(test_ret))
        if valid.sum() < 10:
            continue
        ic, _ = spearmanr(test_feat[valid], test_ret[valid])
        path_ics.append(ic)

    return {
        "cpcv_ic_mean": float(np.nanmean(path_ics)),
        "cpcv_ic_std": float(np.nanstd(path_ics)),
        "n_paths": len(path_ics),
    }
```

### dim_feature_registry Promotion with source_type

```python
# Source: extends experiments/promoter.py _write_to_registry() pattern
# verified at promoter.py line 518

def promote_composite(conn, feature_name: str, best_ic: float, best_horizon: int) -> None:
    conn.execute(
        text("""
            INSERT INTO public.dim_feature_registry (
                feature_name, lifecycle, source_type,
                description, best_ic, best_horizon,
                promoted_at, updated_at
            ) VALUES (
                :feature_name, 'promoted', 'proprietary',
                :description, :best_ic, :best_horizon,
                now(), now()
            )
            ON CONFLICT (feature_name) DO UPDATE SET
                lifecycle     = 'promoted',
                source_type   = EXCLUDED.source_type,
                best_ic       = EXCLUDED.best_ic,
                best_horizon  = EXCLUDED.best_horizon,
                updated_at    = now()
        """),
        {
            "feature_name": feature_name,
            "description": f"Proprietary composite: {feature_name}",
            "best_ic": best_ic,
            "best_horizon": best_horizon,
        },
    )
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| IS/OOS split with arbitrary cutoff | CPCV (Lopez de Prado AFML Ch12) | Phase 36-37 | Unbiased backtest statistics; CPCVSplitter already built in cv.py |
| Single-test IC p-value | FDR + permutation IC + block bootstrap | Phase 102 planned | Reduces false discovery from multiple comparisons |
| dim_feature_registry with lifecycle TEXT | Same, but needs `source_type` column | Phase 106 (new) | Allows downstream filtering by 'proprietary' vs 'standard' |

**Deprecated/outdated:**
- Using `t_test` IC p-value alone to judge significance: replaced by permutation test
  + FDR (Phase 102). Do not use the `ic_p_value` column in `ic_results` as the sole
  gate.

---

## Alembic Migration Requirements

**New revision:** `u5v6w7x8y9z0_phase106_composite_source_type.py`
**Chains from:** `t4u5v6w7x8y9` (Phase 107 pipeline_stage_log — current HEAD)

```python
revision = "u5v6w7x8y9z0"
down_revision = "t4u5v6w7x8y9"
```

**Contents:**

1. `op.add_column("dim_feature_registry", sa.Column("source_type", sa.Text(), nullable=True), schema="public")`

2. Add 6 composite columns to `public.features`:
   - `ama_er_regime_signal FLOAT NULL`
   - `oi_divergence_ctf_agreement FLOAT NULL`
   - `funding_adjusted_momentum FLOAT NULL`
   - `cross_asset_lead_lag_composite FLOAT NULL`
   - `tf_alignment_score FLOAT NULL`
   - `volume_regime_gated_trend FLOAT NULL`

3. Optional CHECK constraint on `source_type` (values: standard/proprietary/derived/ctf/macro)

**CRITICAL:** Phases 102-105 will also need Alembic migrations chaining through
`s3t4u5v6w7x8`. Phase 106 migration must chain from the Phase 105 HEAD, whatever
revision ID that produces. If Phases 102-105 migrations are applied first (with IDs
like `t4u5v6w7x8y9` being taken by Phase 107), Phase 106 must chain from the
Phase 105 migration, not from `t4u5v6w7x8y9`. Determine the actual Alembic HEAD at
execution time with `alembic current` before writing the `down_revision`.

---

## Open Questions

1. **Phase 102-105 Alembic HEAD at Phase 106 execution time**
   - What we know: Current HEAD is `t4u5v6w7x8y9` (Phase 107). Phases 102-105 have
     not yet created migrations.
   - What's unclear: What revision IDs Phases 102-105 will use; how they chain around
     the existing `t4u5v6w7x8y9` HEAD.
   - Recommendation: Run `alembic current` before creating Phase 106 migration. Use
     the actual HEAD as `down_revision`.

2. **lead_lag_ic table data availability**
   - What we know: `lead_lag_ic` table was created by Phase 98 migration (confirmed).
   - What's unclear: Whether Phase 98's run_ctf_lead_lag_ic.py script has been
     executed and whether significant rows exist in the table.
   - Recommendation: Before implementing Composite 4, run:
     `SELECT COUNT(*) FROM public.lead_lag_ic WHERE is_significant = true`
     If zero, fall back to using `ctf_composites` table data instead.

3. **CTF config.yaml coverage of the 4 TF pairs needed for Composite 5**
   - What we know: 6 base TFs and multiple ref TFs are configured; `ret_arith`
     is one of the 22 seeded indicators.
   - What's unclear: Whether all 4 pairs (1D/7D, 1D/14D, 1D/30D, 7D/30D) with
     `ret_arith` are in `ctf_config.yaml` and have data in the `ctf` table.
   - Recommendation: `grep -A3 "ret_arith" configs/ctf_config.yaml` before
     finalizing the 4 TF pairs. Adjust selection to pairs with confirmed data.

4. **Funding rate coverage for assets in IC sweep**
   - What we know: HL funding rates exist only for Hyperliquid-listed perp assets.
   - What's unclear: What fraction of the IC sweep's asset set has HL coverage.
   - Recommendation: `SELECT DISTINCT symbol FROM hyperliquid.hl_assets WHERE
     asset_type='perp'` and cross-reference with the IC sweep's standard asset set.
     If coverage < 30% of assets, Composite 3 may have insufficient IC power — note
     in COMPOSITES.md and run IC evaluation on HL-covered assets only.

---

## Sources

### Primary (HIGH confidence)

- `src/ta_lab2/features/ama/ama_computations.py` — verified: `er` column only for KAMA; NULL for DEMA/TEMA/HMA
- `src/ta_lab2/features/ama/base_ama_feature.py` — verified: `er` column written to `ama_multi_tf`; column listed in build_frame at line 280
- `src/ta_lab2/backtests/cv.py` — verified: CPCVSplitter constructor params (n_splits=6, n_test_splits=2, t1_series REQUIRED, embargo_frac=0.01); PurgedKFoldSplitter (n_splits=5, embargo_frac=0.01)
- `src/ta_lab2/features/cross_timeframe.py` — verified: `load_ctf_features()` at line 221; CTF column naming convention `{indicator}_{ref_tf_lower}_{composite}`
- `src/ta_lab2/experiments/promoter.py` — verified: `dim_feature_registry` INSERT schema; `lifecycle='promoted'` is the target state; `source_type` column does NOT exist in current schema
- `alembic/versions/6f82e9117c58_feature_experiment_tables.py` — verified: full `dim_feature_registry` column list; no `source_type` column present; lifecycle CHECK constraint values ('experimental','promoted','deprecated')
- `alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py` — verified: `lead_lag_ic` table (PK, columns including `is_significant`, `ic`, `ic_p_bh`); `ctf_composites` table schema
- `alembic/versions/f7a8b9c0d1e2_hyperliquid_tables.py` — verified: `hl_funding_rates` (asset_id, ts, funding_rate, premium); `hl_open_interest` (asset_id, ts, open/high/low/close OI); `hl_candles` (open_oi, close_oi)
- `alembic/versions/t4u5v6w7x8y9_phase107_pipeline_stage_log.py` — verified: current Alembic HEAD is `t4u5v6w7x8y9`
- `.planning/phases/102-indicator-research-framework/102-RESEARCH.md` — permutation_ic_test, fdr_control, block_bootstrap_ic, trial_registry schema; arch 8.0.0 column name gotcha
- `.planning/phases/98-ctf-feature-graduation/98-RESEARCH.md` — CTF feature write pattern (UPDATE not DELETE+INSERT); load_ctf_features() API

### Secondary (MEDIUM confidence)

- Grep search for `multiple_testing`, `trial_registry`, `indicators_extended`,
  `indicators_derivatives`, `param_optimizer` across full src/ tree: all returned zero
  matches, confirming Phases 102-105 code does not yet exist in codebase

### Tertiary (LOW confidence)

- HL->CMC asset ID mapping approach: derived from Phase 104 research document finding
  (not yet implemented in code; approach is verified as the correct design, not tested
  against live DB)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries locally installed; no new dependencies
- Composite formula designs: HIGH for data availability; MEDIUM for specific formula
  choices (Claude's discretion, but verified input signal availability)
- CPCV pattern: HIGH — CPCVSplitter API verified directly from cv.py
- FDR pattern: HIGH — statsmodels 0.14.6 verified, same as Phase 102
- dim_feature_registry promotion: HIGH — promoter.py read directly; source_type column
  confirmed absent (needs migration)
- Phase 102-105 prerequisite status: HIGH confidence that they are NOT yet built
- lead_lag_ic data availability: MEDIUM — table exists in schema, but data population
  depends on whether Phase 98 scripts were run

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable codebase patterns; library versions stable)
