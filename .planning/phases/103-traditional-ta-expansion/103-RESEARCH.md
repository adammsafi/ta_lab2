# Phase 103: Traditional TA Expansion - Research

**Researched:** 2026-04-01
**Domain:** Technical indicator implementation (20 indicators), indicator-to-features-table pipeline, Phase 102 harness integration
**Confidence:** HIGH (formulas verified against official sources; codebase patterns read directly)

---

## Summary

Phase 103 adds 20 well-known technical indicators to `src/ta_lab2/features/indicators.py` (or a new `indicators_extended.py`) and runs each through the Phase 102 harness to populate `trial_registry`. Survivors (FDR at 5%) go to `dim_feature_registry` with `is_active = true`; rejects are logged with `is_active = false`.

**What was researched:** (1) All 20 indicator formulas verified against authoritative sources (StockCharts ChartSchool, MetaTrader 5 docs, Wikipedia). (2) Existing codebase: `indicators.py` API conventions, `TAFeature`/`BaseFeature` pipeline, `dim_feature_registry` schema, `dim_indicators` table pattern, IC sweep integration. (3) Library availability: no `pandas-ta`, `ta-lib`, `ta`, or `finta` installed — all indicators must be hand-rolled in NumPy/pandas. (4) Phase 102 harness interface: `log_trials_to_registry`, `permutation_ic_test`, `fdr_control` in `multiple_testing.py`.

**Standard approach:** Implement all 20 indicators purely in NumPy/pandas, following the exact same API as existing `indicators.py` functions (accept Series or DataFrame, return named Series or DataFrame, support `inplace=True`, parameterized `out_col`/`out_cols`). Place Batch 1 (10 indicators) and Batch 2 (10 indicators) in a single new file `indicators_extended.py` to keep `indicators.py` focused on the original 8. Wire them into `TAFeature` for the features-table write. Run the IC sweep via existing `run_ic_sweep.py` (which already calls `log_trials_to_registry` after Phase 102) and apply FDR at the end.

**Primary recommendation:** Implement all 20 indicators hand-rolled in `indicators_extended.py` using NumPy/pandas only. No new library dependencies are needed. All formulas are straightforward vectorized operations except VIDYA, FRAMA, and Hurst, which require explicit Python loops or itertools.

---

## Standard Stack

### Core (already installed — no new deps)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | 2.4.1 | Vectorized math for all indicators | Already used everywhere in indicators.py |
| pandas | 2.3.3 | Rolling windows, EWM, groupby per (id, venue_id) | Already the frame type for all feature data |
| scipy.stats | 1.17.0 | Spearman IC for permutation test (Phase 102) | Already used in ic.py |
| statsmodels | 0.14.6 | FDR control (Phase 102) | Already installed |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy.text | (installed) | Upsert to dim_feature_registry | All DB writes use this |

### No New Dependencies

None of the 20 indicators require a new library. The project has no `pandas-ta`, `ta-lib`, `ta`, `finta`, `tulipy`, or `nolds` installed. All indicators must be implemented directly.

**Installation:**
```bash
# Nothing to install — all required libraries are already installed
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-roll all 20 | `pandas-ta` or `ta` library | Libraries handle edge cases but add a dependency, and the project pattern is to own indicator logic. Hurst and VIDYA/FRAMA are sufficiently niche that library implementations diverge between packages. Hand-rolling is the correct approach here. |
| R/S analysis for Hurst | Variance-scaling method | Both work. Variance-scaling (`polyfit` on log(lag) vs log(std of lagged diffs)) is simpler in NumPy and produces stable results on 200+ bar windows. R/S adds complexity with minimal benefit for rolling IC computation. Use variance-scaling. |
| New `indicators_extended.py` | Append to `indicators.py` | `indicators.py` is clean at 382 lines with 8 functions. Adding 20 more functions bloats it. The `__all__` in `indicators.py` remains unchanged; `indicators_extended.py` exports its own `__all__`. The Phase 103 plan imports from both. |

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/features/
├── indicators.py              # existing — DO NOT MODIFY (8 functions)
├── indicators_extended.py     # NEW — 20 functions (Batches 1+2)

src/ta_lab2/scripts/features/
├── ta_feature.py              # augment compute_features() for new indicator types
├── refresh_ta_daily.py        # no changes needed (delegates to TAFeature)

src/ta_lab2/scripts/analysis/
├── run_ic_sweep.py            # no changes needed (already logs to trial_registry)
├── run_phase103_ic.py         # NEW — Phase 103 IC sweep runner and FDR promotion
```

### Pattern 1: indicators_extended.py Function Convention

**What:** All new indicator functions follow the same API as `indicators.py`.
**When to use:** Every new indicator.

```python
# Source: pattern from src/ta_lab2/features/indicators.py
from __future__ import annotations
import numpy as np
import pandas as pd
from ta_lab2.features.indicators import _ema, _sma, _tr, _ensure_series, _return

# Single-output indicator example:
def williams_r(
    obj,              # DataFrame (high/low/close required)
    window: int = 14,
    *,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_col: str | None = None,
    inplace: bool = False,
) -> pd.Series | pd.DataFrame:
    if out_col is None:
        out_col = f"willr_{window}"
    high = _ensure_series(obj, col=high_col)
    low = _ensure_series(obj, col=low_col)
    close = _ensure_series(obj, col=close_col)
    hh = high.rolling(window, min_periods=window).max()
    ll = low.rolling(window, min_periods=window).min()
    result = -100.0 * (hh - close) / (hh - ll).replace(0.0, np.nan)
    return _return(obj, result.astype(float), out_col, inplace=inplace)

# Multi-output indicator example:
def ichimoku(
    obj,
    *,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    out_cols: tuple | None = None,
    inplace: bool = False,
) -> pd.DataFrame:
    ...  # returns DataFrame with tenkan, kijun, span_a, span_b, chikou columns
```

**Key rule:** Reuse `_ema`, `_sma`, `_tr`, `_ensure_series`, `_return` from `indicators.py`. Import them directly.

### Pattern 2: TAFeature Extension for New Indicator Types

**What:** `TAFeature.compute_features()` dispatches on `indicator_type`. New indicators need new type strings.
**When to use:** When wiring `indicators_extended.py` functions into the TAFeature pipeline.

```python
# In ta_feature.py compute_features(), add elif branches:
elif ind_type == "ichimoku":
    self._compute_ichimoku(df_id, params)
elif ind_type == "willr":
    self._compute_willr(df_id, params)
elif ind_type == "keltner":
    self._compute_keltner(df_id, params)
# ... etc for all 20 new types
```

Each `_compute_X()` method calls the corresponding function from `indicators_extended.py` with `inplace=True`.

### Pattern 3: dim_feature_registry Write for Survivors/Rejects

**What:** After FDR batch, write to `dim_feature_registry` directly using upsert (same pattern as `promoter.py`).
**When to use:** In `run_phase103_ic.py` after FDR sweep.

```python
# Source: pattern from src/ta_lab2/experiments/promoter.py lines 514-566
# dim_feature_registry columns: feature_name, lifecycle, promoted_at, promotion_alpha, ...
# Use lifecycle = 'promoted' for survivors (is_active = true equivalent)
# Use lifecycle = 'deprecated' for rejects (is_active = false equivalent)
# NOTE: dim_feature_registry does NOT have an is_active column.
#       The Success Criteria says "is_active = true" but this maps to lifecycle = 'promoted'.
#       Confirm by running: SELECT column_name FROM information_schema.columns
#       WHERE table_name = 'dim_feature_registry';
```

**CRITICAL FINDING:** The `dim_feature_registry` table uses a `lifecycle` column (values: `'promoted'`, `'deprecated'`) NOT an `is_active` boolean. The success criterion states "is_active = true" but looking at `promoter.py` and `feature_selection.py`, the actual column is `lifecycle`. Verify before implementing Phase 103-03.

### Pattern 4: IC Sweep for New Indicators

**What:** New indicators must first appear in the `features` table before `run_ic_sweep.py` can compute IC. The sweep reads from `features` and `price_bars_multi_tf_u`, both of which are populated.
**When to use:** After writing new indicator values to `features` table.

```python
# Run: python -m ta_lab2.scripts.analysis.run_ic_sweep --features willr_14,cci_20,...
# This auto-logs to trial_registry (Phase 102 wiring already in place)
```

### Anti-Patterns to Avoid

- **Adding all 20 functions to `indicators.py`:** Bloats the file. Use `indicators_extended.py`.
- **Implementing VIDYA/FRAMA as vectorized pandas operations:** Both have recursive recurrence relations (each value depends on the previous computed value). These MUST use explicit Python loops (or `numba` if speed is needed, but that is a new dep). Do not attempt to vectorize — the result will be wrong.
- **Computing VWAP as a cumulative sum across all time:** VWAP must reset per trading session or use a rolling window. For crypto bar data without session boundaries, use a rolling window VWAP (e.g., 14-period rolling TP*V / rolling V). Do NOT cumsum across the entire asset history.
- **Computing Ichimoku Senkou Span A/B shifted forward 26 bars:** For IC testing, use the non-shifted values (Span A and B at the current bar). Shifting forward is for visualization only and causes look-ahead bias in IC computation.
- **Using the Hurst exponent on fewer than 100 bars:** Variance-scaling requires meaningful lag range. Use `min_periods=100` when computing rolling Hurst. Results with fewer bars are unreliable.
- **Running full permutation tests inline during the IC sweep:** The Phase 102 decision was to populate `trial_registry` with NULL `perm_p_value` during the IC sweep, then run permutation tests as a separate post-sweep pass. Phase 103 follows the same pattern.

---

## Don't Hand-Roll

Problems that look simple but have existing solutions or patterns already in the codebase:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| FDR correction | Custom BH loop | `statsmodels.stats.multitest.fdrcorrection` (Phase 102, already in `multiple_testing.py`) | Edge cases handled |
| IC computation | Custom Spearman | `scipy.stats.spearmanr` (already in `ic.py`) | Project standard |
| Trial registry logging | Custom INSERT | `log_trials_to_registry()` from `multiple_testing.py` (Phase 102) | Already wired into IC sweep |
| dim_feature_registry promotion | Custom upsert | `promoter.py` `_write_to_registry()` pattern | Lifecycle management, migration stubs |
| Typical price | (H+L+C)/3 inline | Extract to `_tp()` helper in `indicators_extended.py` | Used by CMF, CCI, MFI, Force Index — avoid repeating |
| ATR reuse | Re-implement TR | Import `_tr()` from `indicators.py` | Already the project standard |
| EMA reuse | Re-implement EWM | Import `_ema()` from `indicators.py` | Already the project standard |

**Key insight:** The hard work is the IC sweep → trial_registry → FDR → dim_feature_registry pipeline. Phase 102 already built this. Phase 103 only needs to (1) implement indicator functions, (2) write values to features table, (3) trigger existing IC sweep machinery.

---

## Indicator Formulas Reference

Verified formulas for all 20 indicators:

### Batch 1 (Plan 103-01)

#### 1. Ichimoku Cloud
Four output columns (skip forward-shift for IC testing):
- `tenkan = (rolling_max(high, 9) + rolling_min(low, 9)) / 2`
- `kijun = (rolling_max(high, 26) + rolling_min(low, 26)) / 2`
- `span_a = (tenkan + kijun) / 2`
- `span_b = (rolling_max(high, 52) + rolling_min(low, 52)) / 2`
- `chikou = close.shift(26)` (but for IC: use `close` lagged backward, i.e., past close at current index)

IC note: Test `tenkan`, `kijun`, `span_a`, `span_b` as separate features. `chikou` at bar T is close at T-26 — this is historical information and valid as a feature (no look-ahead).

#### 2. Williams %R
```
willr_N = -100 * (highest_high_N - close) / (highest_high_N - lowest_low_N)
```
Default N=14. Range [-100, 0].

#### 3. Keltner Channels
```
kc_mid = EMA(close, 20)
kc_upper = kc_mid + 2 * ATR(10)
kc_lower = kc_mid - 2 * ATR(10)
kc_width = (kc_upper - kc_lower) / kc_mid
```
Source: StockCharts (verified). ATR uses rolling mean of TR (same as project's `atr()` function).

#### 4. CCI (Commodity Channel Index)
```
tp = (high + low + close) / 3
sma_tp = SMA(tp, 20)
mean_dev = SMA(|tp - sma_tp|, 20)   # mean absolute deviation, NOT std
cci_20 = (tp - sma_tp) / (0.015 * mean_dev)
```
Lambert's constant = 0.015. Source: StockCharts (verified).

#### 5. Elder Ray (Bull/Bear Power)
```
ema_13 = EMA(close, 13)
bull_power_13 = high - ema_13
bear_power_13 = low - ema_13
```
Two output columns. Source: Elder (1993). Positive bull power = high above EMA (bullish), negative bear power = low below EMA (bearish).

#### 6. Force Index
```
fi_1 = (close - close.shift(1)) * volume
fi_13 = EMA(fi_1, 13)
```
Default smooth period = 13. Two outputs: `fi_1` and `fi_13`. Source: StockCharts (verified).

#### 7. VWAP (Rolling Window)
```
tp = (high + low + close) / 3
vwap_N = rolling_sum(tp * volume, N) / rolling_sum(volume, N)
```
Default N=14 (rolling, not cumulative). For IC testing, rolling VWAP avoids regime-change contamination from cumulative sums. Source: verified via multiple implementations.

**Note on VWAP output:** Also useful as `(close / vwap_14) - 1` for IC (price deviation from VWAP). Consider outputting both `vwap_14` and `vwap_dev_14`.

#### 8. Chaikin Money Flow (CMF)
```
mfm = ((close - low) - (high - close)) / (high - low)   # Money Flow Multiplier
mfv = mfm * volume                                         # Money Flow Volume
cmf_20 = rolling_sum(mfv, 20) / rolling_sum(volume, 20)
```
Default N=20. Range approximately [-1, 1]. Source: StockCharts (verified).

#### 9. Chaikin Oscillator
```
adl = cumsum(mfv)                   # Accumulation/Distribution Line
chaikin_osc = EMA(adl, 3) - EMA(adl, 10)
```
Where `mfv` is the same Money Flow Volume as CMF. Source: StockCharts (verified).

#### 10. Hurst Exponent (Rolling)
```
def _hurst(close_series, max_lag=20):
    """Variance-scaling method. Returns H in [0,1]."""
    lags = range(2, max_lag)
    tau = [np.std(np.subtract(close_series[lag:], close_series[:-lag])) for lag in lags]
    return np.polyfit(np.log(lags), np.log(tau), 1)[0]

# Rolling Hurst with min_periods=100:
hurst_100 = close.rolling(100, min_periods=100).apply(_hurst, raw=True)
```
Output: `hurst_100`. H < 0.5 = mean-reverting, H = 0.5 = random walk, H > 0.5 = trending. Source: Robot Wealth, TowardDataScience (multiple sources agree).

**Performance warning:** Rolling Hurst with `max_lag=20` over 100-bar window takes ~50µs per bar in pure Python. For 4M rows it will be slow. Profile before committing to `apply(raw=True)` — may need to batch or use `np.lib.stride_tricks`.

### Batch 2 (Plan 103-02)

#### 11. VIDYA (Variable Index Dynamic Average)
Recurrence — must use explicit loop:
```python
def vidya(close, cmo_period=9, vidya_period=9):
    k = 2.0 / (vidya_period + 1.0)   # base EMA smoothing factor
    # CMO: UpSum = sum of positive diffs, DnSum = sum of abs negative diffs
    diff = close.diff()
    up = diff.clip(lower=0).rolling(cmo_period).sum()
    dn = diff.clip(upper=0).abs().rolling(cmo_period).sum()
    cmo = (up - dn) / (up + dn).replace(0, np.nan)   # in [-1, 1]

    result = np.full(len(close), np.nan)
    # Initialize at first valid CMO bar
    start = cmo.first_valid_index()
    if start is None:
        return pd.Series(result, index=close.index)
    i0 = close.index.get_loc(start)
    result[i0] = float(close.iloc[i0])
    for i in range(i0 + 1, len(close)):
        vi = abs(float(cmo.iloc[i])) if not np.isnan(cmo.iloc[i]) else 0.0
        alpha = vi * k
        result[i] = alpha * float(close.iloc[i]) + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=close.index, dtype=float)
```
Source: MetaTrader5 docs + TradingPedia (formulas agree). `F * |CMO|` is the adaptive alpha.

#### 12. FRAMA (Fractal Adaptive Moving Average)
Recurrence — must use explicit loop. Period N must be even:
```python
def frama(close, period=16):
    """period must be even. Half-period = period // 2."""
    half = period // 2
    result = np.full(len(close), np.nan)
    i0 = period - 1
    if i0 >= len(close):
        return pd.Series(result, index=close.index)
    result[i0] = float(close.iloc[:period].mean())

    for i in range(i0, len(close)):
        window = close.iloc[i - period + 1 : i + 1]
        v1 = window.iloc[:half]
        v2 = window.iloc[half:]
        n1 = (v1.max() - v1.min()) / half
        n2 = (v2.max() - v2.min()) / half
        n3 = (window.max() - window.min()) / period
        if n1 + n2 > 0 and n3 > 0:
            dimen = (np.log(n1 + n2) - np.log(n3)) / np.log(2)
        else:
            dimen = 1.0
        alpha = np.exp(-4.6 * (dimen - 1.0))
        alpha = np.clip(alpha, 0.01, 1.0)
        result[i] = alpha * float(close.iloc[i]) + (1 - alpha) * result[i - 1]
    return pd.Series(result, index=close.index, dtype=float)
```
Source: MetaTrader5 FRAMA docs (fractal dimension formula verified). When D=1: alpha=1 (trending, fast); when D=2: alpha=exp(-4.6)≈0.01 (choppy, slow).

#### 13. Aroon
```
aroon_up = 100 * (window - (window - 1 - argmax_over_window(high))) / window
aroon_dn = 100 * (window - (window - 1 - argmin_over_window(low))) / window
aroon_osc = aroon_up - aroon_dn
```
In pandas:
```python
aroon_up_25 = 100 * high.rolling(26).apply(lambda x: (25 - x[:-1].argmax()) / 25, raw=True)
aroon_dn_25 = 100 * low.rolling(26).apply(lambda x: (25 - x[:-1].argmin()) / 25, raw=True)
```
Note: window size in rolling must be N+1 to include the "N periods before" logic. Standard N=25. Source: StockCharts.

#### 14. Trix
```
ema1 = EMA(close, N)
ema2 = EMA(ema1, N)
ema3 = EMA(ema2, N)
trix_N = (ema3 - ema3.shift(1)) / ema3.shift(1) * 100   # percent change
```
Default N=15. Optional signal = EMA(trix, 9). Source: StockCharts (verified).

#### 15. Ultimate Oscillator
```
prev_close = close.shift(1)
bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)   # Buying Pressure
tr = pd.concat([high, prev_close], axis=1).max(axis=1) - pd.concat([low, prev_close], axis=1).min(axis=1)

avg7  = bp.rolling(7).sum()  / tr.rolling(7).sum()
avg14 = bp.rolling(14).sum() / tr.rolling(14).sum()
avg28 = bp.rolling(28).sum() / tr.rolling(28).sum()

uo = 100 * (4 * avg7 + 2 * avg14 + avg28) / 7.0
```
Source: StockCharts (verified).

#### 16. Vortex Indicator
```
vm_plus  = (high - low.shift(1)).abs()
vm_minus = (low  - high.shift(1)).abs()
tr_sum_14   = _tr(high, low, close).rolling(14).sum()
vip_14 = vm_plus.rolling(14).sum()  / tr_sum_14
vim_14 = vm_minus.rolling(14).sum() / tr_sum_14
```
Two outputs: `vi_plus_14` and `vi_minus_14`. Source: StockCharts (verified).

#### 17. Ease of Movement (EMV)
```
midpoint_move = ((high + low) / 2) - ((high.shift(1) + low.shift(1)) / 2)
box_ratio     = (volume / 1e8) / (high - low)
emv_1         = midpoint_move / box_ratio
emv_14        = SMA(emv_1, 14)
```
**Volume scaling:** `/ 1e8` (100 million) is StockCharts' convention. This scale factor is only for display; for IC testing, the relative value is what matters. Keep it for convention consistency.
Source: StockCharts (verified).

#### 18. Mass Index
```
hl = high - low
ema_hl1 = EMA(hl, 9)
ema_hl2 = EMA(ema_hl1, 9)
ratio    = ema_hl1 / ema_hl2.replace(0, np.nan)
mass_idx = ratio.rolling(25).sum()
```
Standard parameters: single EMA=9, double EMA=9, sum window=25. Source: StockCharts (verified).

#### 19. KST Oscillator
```
def roc(close, n): return (close / close.shift(n) - 1) * 100

rcma1 = SMA(roc(close, 10), 10)
rcma2 = SMA(roc(close, 15), 10)
rcma3 = SMA(roc(close, 20), 10)
rcma4 = SMA(roc(close, 30), 15)

kst = 1*rcma1 + 2*rcma2 + 3*rcma3 + 4*rcma4
kst_signal = SMA(kst, 9)
```
ROC periods: 10, 15, 20, 30. SMA periods: 10, 10, 10, 15. Weights: 1, 2, 3, 4.
Source: KST oscillator Wikipedia + TradingTechnologies docs (multiple sources agree).

#### 20. Coppock Curve
```
def wma(series, n):
    """Weighted Moving Average."""
    weights = np.arange(1, n+1, dtype=float)
    return series.rolling(n).apply(lambda x: np.dot(x, weights)/weights.sum(), raw=True)

roc14 = (close / close.shift(14) - 1) * 100
roc11 = (close / close.shift(11) - 1) * 100
coppock = wma(roc14 + roc11, 10)
```
Source: StockCharts (verified). Edwin Coppock's original formula.

---

## Common Pitfalls

### Pitfall 1: VIDYA and FRAMA Vectorization Attempts

**What goes wrong:** Trying to implement VIDYA/FRAMA without explicit loops using `pandas.ewm` or `rolling.apply` — the alpha changes per bar, making standard EWM inapplicable.
**Why it happens:** Both look EMA-like but the smoothing factor is state-dependent.
**How to avoid:** Use explicit `for` loops iterating over the index. Accept O(n) Python loop speed. For production performance, wrap with `numba.njit` if needed (but that would be a new dep). For Phase 103 research, pure Python is acceptable.
**Warning signs:** VIDYA values converge too quickly or show non-adaptive behavior.

### Pitfall 2: Ichimoku Span A/B Look-Ahead in IC Testing

**What goes wrong:** Plotting Ichimoku shifts Span A and B forward 26 bars. If that shift is in the IC feature, the feature sees future data.
**Why it happens:** Ichimoku is defined with forward displacement for chart visualization.
**How to avoid:** Use the unshifted values of Span A and B as features. The formula for Span A at bar T is `(tenkan_T + kijun_T) / 2` — no shift. Never use `shift(-26)` in indicator functions.
**Warning signs:** IC values suspiciously high for Ichimoku features; IC not decaying properly with horizon.

### Pitfall 3: VWAP Cumulative Sum Contaminating Asset-Level Features

**What goes wrong:** Using `cumsum()` across the entire asset history makes VWAP of BTC in 2024 include all volume since 2017 — meaningless for IC.
**Why it happens:** VWAP is traditionally reset daily (intraday) but crypto daily bars have no intraday session to reset against.
**How to avoid:** Use rolling window VWAP: `rolling(N).sum(tp*vol) / rolling(N).sum(vol)` with N=14. Additionally, compute `vwap_dev_14 = close / vwap_14 - 1` as the IC-relevant feature.
**Warning signs:** VWAP column monotonically increasing with price over years.

### Pitfall 4: CCI Mean Deviation vs Standard Deviation

**What goes wrong:** Using `rolling.std()` instead of mean absolute deviation in CCI denominator.
**Why it happens:** "deviation" is ambiguous; Lambert's original formula uses mean absolute deviation (not std).
**How to avoid:** `mean_dev = (tp - sma_tp).abs().rolling(20).mean()` NOT `rolling(20).std()`.
**Warning signs:** CCI values outside ±200 range (too large) or artificially compressed.

### Pitfall 5: Hurst Exponent on Short Windows

**What goes wrong:** Rolling Hurst with small windows (e.g., 30 bars) produces degenerate H estimates (all near 0.5 or all near 0/1).
**Why it happens:** Variance-scaling requires enough lags to fit the log-log relationship reliably.
**How to avoid:** Use `min_periods=100` and `window=100`. Filter out H values outside [0.05, 0.95] as degenerate before IC computation.
**Warning signs:** H distribution is bimodal near 0 and 1, not centered around 0.5.

### Pitfall 6: Aroon Rolling Window Size

**What goes wrong:** Using `rolling(25)` when Aroon(25) needs to find the position of the high/low among the last 25 bars (plus the current), so rolling size should be 26.
**Why it happens:** The formula says "25-period" but the argmax/argmin needs 25 prior bars plus the current = 26 total.
**How to avoid:** Use `rolling(N+1)` and apply `lambda x: (N - x[:-1].argmax()) / N * 100`. The `x[:-1]` drops the current bar from the argmax search per the Aroon convention.
**Warning signs:** Aroon Up = 100 far more often than expected (always finds max at most recent bar).

### Pitfall 7: dim_feature_registry lifecycle vs is_active

**What goes wrong:** Plan 103-03 writes `is_active = true` to a column that does not exist.
**Why it happens:** The success criterion uses "is_active" but the actual table column is `lifecycle` (values: `'promoted'`, `'deprecated'`).
**How to avoid:** Check the actual schema: `SELECT column_name FROM information_schema.columns WHERE table_name = 'dim_feature_registry'` before writing. Use `lifecycle = 'promoted'` for survivors and `lifecycle = 'deprecated'` for rejects.
**Warning signs:** `ProgrammingError: column "is_active" of relation "dim_feature_registry" does not exist`.

### Pitfall 8: Force Index and Chaikin Oscillator Scaling

**What goes wrong:** Force Index raw values vary by 8-10 orders of magnitude across assets (BTC volume in millions, altcoin volume in thousands). IC test on raw FI gives nonsensical results.
**Why it happens:** FI is price * volume, so it inherits huge cross-asset scale differences.
**How to avoid:** For IC testing, compute a z-scored or log-transformed version as the actual feature. Force Index 13-bar EMA is already smoothed — additionally z-score it over a 252-bar window (same as existing zscore pattern in TAFeature).

---

## Code Examples

Verified patterns from official sources and codebase:

### Importing helpers from indicators.py

```python
# Source: src/ta_lab2/features/indicators.py
from ta_lab2.features.indicators import _ema, _sma, _tr, _ensure_series, _return
```

### TAFeature dispatch extension (src/ta_lab2/scripts/features/ta_feature.py)

```python
# Source: pattern from ta_feature.py lines 203-218
from ta_lab2.features import indicators_extended as indx

# In compute_features():
elif ind_type == "willr":
    period = ind["params"].get("period", 14)
    indx.williams_r(df_id, window=period, inplace=True)
elif ind_type == "cci":
    window = ind["params"].get("window", 20)
    indx.cci(df_id, window=window, inplace=True)
elif ind_type == "ichimoku":
    indx.ichimoku(df_id, inplace=True)
# ... etc
```

### Upsert to dim_feature_registry for Phase 103-03

```python
# Source: pattern from src/ta_lab2/experiments/promoter.py lines 515-566
# For Phase 103 survivors:
conn.execute(text("""
    INSERT INTO public.dim_feature_registry
        (feature_name, lifecycle, promoted_at, promotion_alpha,
         best_ic, best_horizon, updated_at)
    VALUES
        (:feature_name, 'promoted', now(), :alpha,
         :best_ic, :best_horizon, now())
    ON CONFLICT (feature_name) DO UPDATE SET
        lifecycle = 'promoted',
        promoted_at = EXCLUDED.promoted_at,
        promotion_alpha = EXCLUDED.promotion_alpha,
        best_ic = EXCLUDED.best_ic,
        best_horizon = EXCLUDED.best_horizon,
        updated_at = EXCLUDED.updated_at
"""), {...})

# For rejects:
conn.execute(text("""
    INSERT INTO public.dim_feature_registry
        (feature_name, lifecycle, updated_at)
    VALUES (:feature_name, 'deprecated', now())
    ON CONFLICT (feature_name) DO UPDATE SET
        lifecycle = 'deprecated', updated_at = EXCLUDED.updated_at
"""), {...})
```

### WMA helper for Coppock Curve

```python
# Source: derived from StockCharts formula
def _wma(s: pd.Series, n: int) -> pd.Series:
    """Weighted Moving Average. Weights are 1, 2, ..., n."""
    weights = np.arange(1, n + 1, dtype=float)
    return s.rolling(n, min_periods=n).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )
```

### Typical Price helper

```python
# Shared across CMF, CCI, VWAP — put in indicators_extended.py
def _tp(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    return (high.astype(float) + low.astype(float) + close.astype(float)) / 3.0
```

---

## Indicator-to-Column Mapping

The following output column names follow the project naming convention `{indicator}_{period}`:

| Indicator | Output Columns | Indicator Type Key |
|-----------|---------------|-------------------|
| Ichimoku | `ichimoku_tenkan`, `ichimoku_kijun`, `ichimoku_span_a`, `ichimoku_span_b`, `ichimoku_chikou` | `ichimoku` |
| Williams %R | `willr_14` | `willr` |
| Keltner Channels | `kc_mid_20`, `kc_upper_20`, `kc_lower_20`, `kc_width_20` | `keltner` |
| CCI | `cci_20` | `cci` |
| Elder Ray | `elder_bull_13`, `elder_bear_13` | `elder_ray` |
| Force Index | `fi_1`, `fi_13` | `force_index` |
| VWAP | `vwap_14`, `vwap_dev_14` | `vwap` |
| Chaikin MF | `cmf_20` | `cmf` |
| Chaikin Osc | `chaikin_osc` | `chaikin_osc` |
| Hurst | `hurst_100` | `hurst` |
| VIDYA | `vidya_9` | `vidya` |
| FRAMA | `frama_16` | `frama` |
| Aroon | `aroon_up_25`, `aroon_dn_25`, `aroon_osc_25` | `aroon` |
| Trix | `trix_15`, `trix_signal_9` | `trix` |
| Ultimate Osc | `uo_7_14_28` | `ultimate_osc` |
| Vortex | `vi_plus_14`, `vi_minus_14` | `vortex` |
| EMV | `emv_1`, `emv_14` | `emv` |
| Mass Index | `mass_idx_25` | `mass_index` |
| KST | `kst`, `kst_signal` | `kst` |
| Coppock | `coppock` | `coppock` |

**Total unique IC-testable scalars:** ~35 columns from 20 indicators (multi-output indicators produce multiple features for IC sweep).

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `pandas-ta` / `ta-lib` for indicator calculation | Hand-rolled NumPy/pandas (project standard) | No TA library installed; hand-rolling is the enforced pattern |
| Cumulative VWAP | Rolling-window VWAP (N=14) | Cumulative VWAP is meaningless for daily bar IC testing |
| TA indicators without statistical testing | IC sweep + permutation test + FDR (Phase 102 harness) | Phase 102 infrastructure must exist before Phase 103 runs |

**Deprecated/outdated:**
- Any approach using `import talib` — not installed, not a dependency
- Ichimoku Span A/B forward-shifted by 26 bars as features — look-ahead bias

---

## Open Questions

1. **dim_feature_registry schema confirmation**
   - What we know: `promoter.py` uses `lifecycle` column (not `is_active`); the success criterion says "is_active = true"
   - What's unclear: Whether a separate `is_active` boolean was added in a later migration (Phase 80+)
   - Recommendation: Before writing Phase 103-03, run `SELECT column_name FROM information_schema.columns WHERE table_name = 'dim_feature_registry' ORDER BY ordinal_position;` to confirm actual columns. If `is_active` exists, use it. If not, use `lifecycle = 'promoted'`.

2. **Features table column capacity**
   - What we know: `features` table has 112 columns; new indicators add ~35 more
   - What's unclear: Whether the features table is wide (ALTER TABLE ADD COLUMN) or whether indicators write to a separate table
   - Recommendation: Look at how existing TA indicators (RSI, MACD, etc.) write to the features table vs. the `ta` table in TAFeature. If `features` and `ta` are separate, Phase 103 writes to `ta` (or a new `ta_extended`), not to `features` directly. The IC sweep reads from `features` — confirm whether `ta` feeds into `features` automatically or via a join.

3. **Hurst rolling performance**
   - What we know: `rolling.apply` with Python function for 4M rows will be slow
   - What's unclear: Whether Hurst is computed only for 1D bars (manageable) or all timeframes
   - Recommendation: Start with 1D bars only for the Hurst IC sweep. The Phase 103 plan says "run through Phase 102 harness" — confirm which timeframes are in scope before optimizing.

4. **Phase 102 completion status**
   - What we know: Phase 102 plans exist (102-01, 102-02, 102-03); Phase 103 depends on Phase 102
   - What's unclear: Whether `multiple_testing.py` and `trial_registry` are actually implemented and running
   - Recommendation: Before starting 103-01, verify `SELECT COUNT(*) FROM trial_registry` returns a row count (not an error), and `from ta_lab2.analysis.multiple_testing import log_trials_to_registry` imports without error. If Phase 102 is not complete, Phase 103 cannot proceed.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/features/indicators.py` — API conventions, helper functions (`_ema`, `_sma`, `_tr`, `_ensure_series`, `_return`)
- `src/ta_lab2/scripts/features/ta_feature.py` — `TAFeature.compute_features()` dispatch pattern, `dim_indicators` loading
- `src/ta_lab2/scripts/features/base_feature.py` — `BaseFeature` template, `SOURCE_TABLE = "public.price_bars_multi_tf_u"`
- `src/ta_lab2/experiments/promoter.py` — `_write_to_registry()` pattern, `dim_feature_registry` INSERT/ON CONFLICT SQL
- `.planning/phases/102-indicator-research-framework/102-RESEARCH.md` — Phase 102 harness API: `log_trials_to_registry`, `permutation_ic_test`, `fdr_control`
- [StockCharts ChartSchool — Williams %R](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/williams-r) — formula verified
- [StockCharts ChartSchool — CCI](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/commodity-channel-index-cci) — Lambert's constant verified
- [StockCharts ChartSchool — Force Index](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/force-index) — formula verified
- [StockCharts ChartSchool — Chaikin Money Flow](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/chaikin-money-flow-cmf) — formula verified
- [StockCharts ChartSchool — Chaikin Oscillator](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/chaikin-oscillator) — ADL + EMA formula verified
- [StockCharts ChartSchool — Keltner Channels](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels) — EMA(20) + 2*ATR(10) verified
- [StockCharts ChartSchool — Ichimoku Cloud](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/ichimoku-cloud) — 5 components verified
- [StockCharts ChartSchool — Ultimate Oscillator](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ultimate-oscillator) — BP/TR/weights verified
- [StockCharts ChartSchool — Vortex Indicator](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/vortex-indicator) — VM+/VM-/TR14 formula verified
- [StockCharts ChartSchool — Ease of Movement](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ease-of-movement-emv) — midpoint move + box ratio verified
- [StockCharts ChartSchool — Mass Index](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/mass-index) — 4-step formula verified
- [StockCharts ChartSchool — Coppock Curve](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/coppock-curve) — WMA(ROC14+ROC11, 10) verified
- [StockCharts ChartSchool — TRIX](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/trix) — triple EMA + pct change verified
- [MetaTrader 5 — FRAMA](https://www.metatrader5.com/en/terminal/help/indicators/trend_indicators/fama) — fractal dimension formula, alpha = exp(-4.6*(D-1)) verified
- [MetaTrader 5 — VIDYA](https://www.metatrader5.com/en/terminal/help/indicators/trend_indicators/vida) — CMO-adaptive EMA formula verified
- [KST Oscillator — Wikipedia](https://en.wikipedia.org/wiki/KST_oscillator) — ROC periods 10/15/20/30, SMA 10/10/10/15, weights 1/2/3/4 verified

### Secondary (MEDIUM confidence)
- [Robot Wealth — Hurst Exponent](https://robotwealth.com/demystifying-the-hurst-exponent-part-1/) — variance-scaling method code pattern
- [TradingTechnologies — KST](https://library.tradingtechnologies.com/trade/chrt-ti-prings-know-sure-thing.html) — KST parameters cross-verified

### Tertiary (LOW confidence)
- [EOD HD — Aroon in Python](https://eodhd.com/financial-academy/backtesting-strategies-examples/algorithmic-trading-with-aroon-indicator-in-python) — Aroon rolling window size gotcha (N+1); not independently verified from official source

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps, all libraries verified locally (`numpy 2.4.1`, `pandas 2.3.3`)
- Indicator formulas (15 of 20): HIGH — verified against StockCharts or MetaTrader5 authoritative docs
- Indicator formulas (VIDYA, FRAMA): HIGH — MetaTrader5 official docs
- Indicator formulas (Hurst, Aroon rolling window, KST): MEDIUM — multiple sources agree but no single authoritative primary
- Architecture patterns: HIGH — read directly from codebase (indicators.py, ta_feature.py, promoter.py)
- dim_feature_registry schema (is_active vs lifecycle): MEDIUM — read from promoter.py, but Phase 80+ migrations may have added is_active; verify before 103-03

**Research date:** 2026-04-01
**Valid until:** 2026-05-01 (stable; numpy/pandas APIs are unchanged; StockCharts formulas are canonical)
