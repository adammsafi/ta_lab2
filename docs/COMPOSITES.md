# Proprietary Composite Indicators

## Overview

This document describes the six proprietary composite indicators developed in Phase 106
of ta_lab2. Each composite combines multiple data sources into a single feature that
captures interactions invisible to any single-source indicator.

**Validation methodology:** 4-layer statistical gauntlet:
1. Permutation IC test (1000 shuffles, empirical p-value)
2. FDR correction (Benjamini-Hochberg, alpha=0.05 across all 6 composites)
3. CPCV (Combinatorial Purged Cross-Validation: 6 splits, 2 test splits, 15 paths)
4. Held-out 20% gate (touched exactly once as terminal gate)

**Date computed:** 2026-04-01 (run_composite_refresh.py)
**Date validated:** 2026-04-02 (run_composite_validation.py)
**Validation config:** tf=10D, venue_id=1 (CMC_AGG), horizon=1 bar, alpha=0.05, held_out_frac=0.20

---

## Composites

### 1. AMA ER Regime Signal (`ama_er_regime_signal`)

**Intuition:** The Kaufman Efficiency Ratio (ER) measures how directional price movement
is relative to total path length. High ER = trending; low ER = choppy/ranging. Combining
ER quantile rank with the sign of the price-vs-KAMA spread gives a composite that is
positive when the market is efficiently trending upward and negative when efficiently
trending downward.

**Formula:**
```
er_rank = rolling_quantile_rank(er, window=60)  # range [0, 1]
kama_spread_sign = sign(close - KAMA)
ama_er_regime_signal = er_rank * kama_spread_sign  # range [-1, +1]
```

**Range:** [-1, +1]
**Data source:** `ama_multi_tf` (indicator='KAMA' rows only)
**Warmup:** 70 bars (60-bar ER quantile window + KAMA convergence buffer)
**Local DB coverage:** 0% (requires `ama_multi_tf` base partitioned table, not available locally)
**Validation results:** insufficient_data (0 qualifying assets on local DB)

---

### 2. OI-Divergence x CTF Agreement (`oi_divergence_ctf_agreement`)

**Intuition:** Open interest (OI) divergence from price captures when smart money is
positioning against trend (bearish OI divergence) or with trend (bullish). Combining
this with cross-timeframe (CTF) agreement gives a signal that is strongest when both
structure and flow agree on direction.

**Formula:**
```
oi_mom_14 = rolling_zscore(oi_rate_of_change, window=14)  # from hl_oi_snapshots
price_mom_14 = rolling_zscore(close_pct_change, window=14)  # from price_bars_multi_tf
oi_div_z = oi_mom_14 - price_mom_14  # negative = OI growing faster than price (bullish divergence by convention)
ctf_agreement = mean(adx_14_*d_agreement columns)  # multi-horizon CTF agreement score
oi_divergence_ctf_agreement = -oi_div_z * ctf_agreement  # range approximately [-3, +3]
```

**Range:** Approximately [-3, +3]
**Data source:** `hyperliquid.hl_oi_snapshots` (OI), `price_bars_multi_tf` (close), `features` (CTF agreement cols)
**Warmup:** 14 bars for rolling z-score
**Local DB coverage:** 0% (requires HL sync + price_bars_multi_tf base table)
**Validation results:** insufficient_data (0 qualifying assets on local DB)

---

### 3. Funding-Adjusted Momentum (`funding_adjusted_momentum`)

**Intuition:** In perpetual futures markets, extreme positive funding rates indicate
crowded longs (bearish contrarian signal); extreme negative rates indicate crowded shorts
(bullish contrarian signal). Adjusting price momentum by the funding rate z-score
penalizes momentum signals that exist primarily due to funding-driven crowding.

**Formula:**
```
price_mom_14 = rolling_zscore(close_pct_change, window=14)
funding_z = rolling_zscore(funding_rate, window=14)  # from hyperliquid.hl_funding_rates
funding_adjusted_momentum = price_mom_14 - 0.5 * funding_z  # range approximately [-4, +4]
```

**Range:** Approximately [-4, +4]
**Data source:** `hyperliquid.hl_funding_rates` (funding rates), `price_bars_multi_tf` (close)
**Warmup:** 14 bars for rolling z-score
**Local DB coverage:** 0% (requires HL sync + price_bars_multi_tf base table)
**Validation results:** insufficient_data (0 qualifying assets on local DB)

---

### 4. Cross-Asset Lead-Lag Composite (`cross_asset_lead_lag_composite`)

**Intuition:** When BTC or ETH consistently leads an altcoin (i.e., their returns
predict the altcoin's returns with lag), the lead-lag IC score is high. Combining this
with the current lagged return of the leader creates a signal: if BTC leads coin X,
and BTC just rose significantly, X is likely to follow.

**Formula:**
```
lead_lag_ic = IC(leader_return[t-lag], coin_return[t]) for each (leader, lag) pair
# from the lead_lag_ic table populated by run_ctf_lead_lag_ic.py
best_ic = max(lead_lag_ic) where ic_pct > 0.6  # requires consistent predictive power
lagged_return = leader_close_return[t-lag]
cross_asset_lead_lag_composite = sign(best_ic) * lagged_return  # range unbounded, typically [-0.2, +0.2]
```

**Range:** Approximately [-0.2, +0.2] (bounded by lagged returns)
**Data source:** `lead_lag_ic` table (populated by run_ctf_lead_lag_ic.py), `price_bars_multi_tf`
**Warmup:** Requires sufficient data for IC estimation (typically 252+ bars for leader)
**Local DB coverage:** 0% (lead_lag_ic table has no rows with ic_pct > 0.6 for tf=10D locally)
**Validation results:** insufficient_data (0 qualifying assets on local DB)

---

### 5. Multi-Timeframe Alignment Score (`tf_alignment_score`)

**Intuition:** When multiple timeframes (daily, weekly, monthly) all agree on trend
direction, the signal is more likely to persist. The alignment score averages the
directional agreement across CTF pairs, giving +1 when all timeframes agree bullish,
-1 when all agree bearish, and 0 when mixed/conflicted.

**Formula:**
```
ctf_agreement_cols = [adx_14_7d_agreement, adx_14_14d_agreement, adx_14_30d_agreement,
                      adx_14_90d_agreement, adx_14_180d_agreement, adx_14_365d_agreement]
tf_alignment_score = mean(available_ctf_agreement_cols)  # range [-1, +1]
```

**Range:** [-1, +1]
**Data source:** `features` table (CTF agreement columns computed by Phase 103)
**Warmup:** Longest CTF window (365 bars)
**Local DB coverage:** 100% (22,280 rows, 7 assets, tf=10D)
**Validation results:** Passed permutation + FDR + CPCV; FAILED held-out (sign flip)

---

### 6. Volume-Regime Gated Trend (`volume_regime_gated_trend`)

**Intuition:** Volume confirmation of price moves is a classic filter. High-volume
breakouts are more likely to sustain than low-volume ones. Gating the trend signal
(KAMA direction) by a volume-regime flag (whether volume is above its long-term baseline)
produces a signal that is on only when volume confirms the trend.

**Formula:**
```
kama_trend = sign(close - KAMA)  # +1 up, -1 down
vol_regime_z = rolling_zscore(volume, window=60)
vol_gate = 1.0 if vol_regime_z > 0 else 0.5  # partial signal in low-volume regime
volume_regime_gated_trend = kama_trend * vol_gate  # range {-1.0, -0.5, +0.5, +1.0}
```

**Range:** {-1.0, -0.5, +0.5, +1.0}
**Data source:** `ama_multi_tf` (KAMA rows), `price_bars_multi_tf` (volume + close)
**Warmup:** 70 bars (KAMA + volume z-score window)
**Local DB coverage:** 0% (requires `ama_multi_tf` base partitioned table)
**Validation results:** insufficient_data (0 qualifying assets on local DB)

---

## Validation Results Summary

Results from `composite_validation_results.json` (run 2026-04-02T00:42:29Z):

| Composite                    | Perm IC | Perm p | FDR  | CPCV mean IC | CPCV pos% | HOut IC | HOut Status    | Overall      |
|------------------------------|---------|--------|------|-------------|-----------|---------|----------------|--------------|
| ama_er_regime_signal         | N/A     | 1.000  | FAIL | N/A          | N/A       | N/A     | skipped        | INSUFFICIENT |
| oi_divergence_ctf_agreement  | N/A     | 1.000  | FAIL | N/A          | N/A       | N/A     | skipped        | INSUFFICIENT |
| funding_adjusted_momentum    | N/A     | 1.000  | FAIL | N/A          | N/A       | N/A     | skipped        | INSUFFICIENT |
| cross_asset_lead_lag_composite | N/A   | 1.000  | FAIL | N/A          | N/A       | N/A     | skipped        | INSUFFICIENT |
| tf_alignment_score           | +0.0300 | 0.0000 | PASS | +0.0300      | 86.7%     | -0.0075 | failed_sign_flip | failed     |
| volume_regime_gated_trend    | N/A     | 1.000  | FAIL | N/A          | N/A       | N/A     | skipped        | INSUFFICIENT |

**Detailed results for tf_alignment_score:**
- Layer 1 (Permutation IC): IC = +0.0300, p = 0.0000, n_obs = 17,813 — PASSED
- Layer 2 (FDR): Rejected (FDR pass with alpha=0.05) — PASSED
- Layer 3 (CPCV): mean IC = +0.0300, IC std = 0.0245, pos_frac = 86.7%, 15 paths — PASSED
- Layer 4 (Held-out): IC = -0.0075, n_obs = 4,460, status = failed_sign_flip — FAILED

**Sign flip analysis:** Training period (2010-2022) showed IC = +0.030 for tf_alignment_score
against 1-bar-ahead returns on tf=10D. The held-out period (2022-2025, post-crypto-winter)
showed IC = -0.008, a sign reversal. This suggests the composite's predictive power is
regime-dependent and weakened significantly during the 2022 bear market and recovery
period. This is a legitimate finding, not a data quality issue.

---

## Promoted Composites

**None promoted on local DB validation.**

All 3 fallback options were applied in sequence:
- **Option A (strict):** 0 composites passed all 4 layers.
- **Option B (relaxed held-out: same-sign only):** tf_alignment_score failed sign
  flip (held-out IC was negative vs positive training IC), so no marginal survivors.
- **Option C (1 strong survivor: |IC|>0.03, p<0.01):** tf_alignment_score has
  IC = +0.03000 which fails the `|IC| > 0.03` threshold (exactly equal, not greater).

**Promotion intent for production run:**
When the full dataset is available (ama_multi_tf, price_bars_multi_tf, HL sync),
run `run_composite_validation.py` on the production server. Composites that pass
the 4-layer gauntlet on the full dataset will be promoted to `dim_feature_registry`
with `source_type='proprietary'` and `lifecycle='promoted'` automatically.

---

## Coverage Notes

### Why 5/6 composites have 0 local coverage

The local development database contains only the `_u` (unified) view tables, not the
base partitioned tables:

- **`ama_multi_tf`:** Not present locally (base table). Only `ama_multi_tf_u` exists.
  Affects: `ama_er_regime_signal`, `volume_regime_gated_trend`.
- **`price_bars_multi_tf`:** Not present locally (base table). Only `price_bars_multi_tf_u` exists.
  Affects: `oi_divergence_ctf_agreement`, `funding_adjusted_momentum`.
- **Hyperliquid perp data:** OI and funding rate data not available for local CMC_AGG assets
  (venue_id=1). Affects: `oi_divergence_ctf_agreement`, `funding_adjusted_momentum`.
- **`lead_lag_ic` table:** Has no rows with ic_pct > 0.6 significance for tf=10D locally.
  Affects: `cross_asset_lead_lag_composite`.

### What was validated

Only `tf_alignment_score` had sufficient data on the local database (22,280 rows, 7
assets, tf=10D, venue_id=1). All other composites are marked `insufficient_data`.

### FDR with insufficient_data composites

When 5/6 composites have p=1.0 (insufficient_data sentinel), the FDR correction is
applied to a batch dominated by null results. This is mathematically conservative and
gives tf_alignment_score's true p=0.000 appropriate recognition without inflation.
Acknowledged: FDR with batch_size=6 has limited power and is primarily a statistical
hygiene safeguard here.

### Production validation expected results

On the production server (Oracle Singapore VM with full data):
- `ama_er_regime_signal`: Expected to have data for all 7 assets
- `oi_divergence_ctf_agreement`: Expected for HL-listed perp assets (~5 of 7)
- `funding_adjusted_momentum`: Expected for HL-listed perp assets (~5 of 7)
- `cross_asset_lead_lag_composite`: Depends on lead_lag_ic population (requires
  run_ctf_lead_lag_ic.py to have been run with ic_pct > 0.6 threshold)
- `tf_alignment_score`: 22,280 rows confirmed (may improve with sign flip in full data)
- `volume_regime_gated_trend`: Expected for all 7 assets

---

## Reproduction

### Compute composites (refresh all 6 formulas into features table)

```bash
# On local DB (only tf_alignment_score will write; others need missing tables)
python -m ta_lab2.scripts.features.run_composite_refresh --tf 10D --venue-id 1

# On production server (all 6 composites will compute)
python -m ta_lab2.scripts.features.run_composite_refresh --tf 1D --venue-id 1
```

### Run validation gauntlet (4-layer)

```bash
# Local validation (default tf=10D, venue_id=1)
python -m ta_lab2.scripts.analysis.run_composite_validation --tf 10D --venue-id 1

# With verbose output showing per-asset breakdown
python -m ta_lab2.scripts.analysis.run_composite_validation --tf 10D --venue-id 1 --verbose

# Production validation (once all composites populated)
python -m ta_lab2.scripts.analysis.run_composite_validation --tf 1D --venue-id 1 --alpha 0.05

# Custom horizon (2-bar forward return)
python -m ta_lab2.scripts.analysis.run_composite_validation --tf 1D --horizon 2
```

### Check promoted composites in registry

```sql
SELECT feature_name, lifecycle, source_type, best_ic, best_horizon, promoted_at
FROM public.dim_feature_registry
WHERE source_type = 'proprietary'
ORDER BY feature_name;
```

### View validation results JSON

```bash
cat reports/composites/composite_validation_results.json
```

---

## Interpretation Guide

### IC magnitude interpretation

| IC magnitude | Interpretation |
|-------------|---------------|
| < 0.01 | Negligible / noise |
| 0.01 - 0.03 | Marginal signal |
| 0.03 - 0.05 | Moderate signal |
| > 0.05 | Strong signal |

tf_alignment_score sits at IC=0.030, borderline moderate/marginal. Its permutation
test significance (p=0.000 from 1000 shuffles, n=17,813 observations) indicates the
training IC is not a sampling artifact. The held-out sign flip is the disqualifying factor.

### CPCV path interpretation

With CPCV (6 splits, 2 test splits), the splitter generates C(6,2)=15 paths. A composite
passing CPCV must have mean_IC > 0 AND > 60% of paths with positive IC. tf_alignment_score
achieved 86.7% positive paths (13/15) in training, indicating robust within-training consistency.
The sign flip only appears in the held-out period (2022-2025).

### Regime dependency note

The held-out period (2022-2025) coincides with the crypto bear market (2022), recovery
(2023), and BTC ETF-driven bull market (2024-2025). Multi-timeframe alignment may behave
differently in these regimes compared to the pre-2022 bull market that dominates the
training window. This is a known limitation of composite indicators that combine technical
signals without explicit regime conditioning.

---

*Phase: 106-custom-composite-indicators*
*Plans: 106-01 (formulas + migration), 106-02 (refresh orchestrator), 106-03 (validation)*
*Completed: 2026-04-02*
