# Phase 59: Microstructural & Advanced Features - Context

**Gathered:** 2026-02-26
**Status:** Not started
**Depends on:** Phase 55 (Feature & Signal Evaluation), Phase 56 (Factor Analytics — needs IC/quintile analysis to validate new features)

<domain>
## Phase Boundary

Expand `cmc_features` with microstructural signals, stationarity-preserving transforms, bubble detection, and non-linear dependency measures. These are features unavailable in standard TA libraries, drawn primarily from MLFinLab's implementation of "Advances in Financial Machine Learning" techniques.

**Source:** `.planning/research/quant_finance_ecosystem_review.md` — Tier 2 (fractional diff, Kyle/Amihud, SADF) + Tier 3 (entropy, codependence) from MLFinLab (4.6k stars).

</domain>

<scope>
## Scope

### Fractional Differentiation (from MLFinLab — AFML Chapter 5)
- **Problem**: Returns (d=1) destroy memory. Raw prices (d=0) are non-stationary. Both are bad for ML features.
- **Solution**: `frac_diff_ffd(series, d=0.35)` — stationary with memory preserved
- d≈0.3-0.5 is the sweet spot; `plot_min_ffd(series)` finds minimum d that passes ADF stationarity test per asset
- Fixed-width window (FFD) variant for computational efficiency
- Store as feature columns in `cmc_features` (e.g., `close_fracdiff`)
- Can also use standalone `fracdiff` pip package

### Kyle/Amihud Lambda — Bar-Based Market Impact (from MLFinLab)
Microstructural features computable from existing OHLCV + volume (no tick data needed):

| Feature | Method | Meaning |
|---|---|---|
| Kyle lambda | `regress(delta_price, volume, window=20)` | Price impact per volume unit |
| Amihud lambda | `abs(return) / dollar_volume` | Illiquidity ratio |
| Hasbrouck lambda | `regress(delta_price, signed_sqrt(dollar_volume))` | Signed price impact |

- Add `kyle_lambda`, `amihud_lambda`, `hasbrouck_lambda` columns to `cmc_features`
- Computed from existing `cmc_price_bars_multi_tf` data
- Also available: Roll measure (effective bid-ask spread estimate), Corwin-Schultz spread estimator

### SADF Bubble Detection (from MLFinLab — AFML Chapter 17)
- Supremum Augmented Dickey-Fuller test: recursively expanding window ADF
- `get_sadf(price_series, model='linear', lags=5, min_length=50)`
- High SADF values indicate explosive/bubble price behavior
- Directly applicable to crypto bubble cycles (2017, 2021, etc.)
- Integration: feeds into `cmc_regimes` as additional regime signal (bubble/explosive flag)
- Also available: Chow-type Dickey-Fuller (unknown breakpoint detection), Chu-Stinchcombe-White CUSUM (mean-shift detection)

### Entropy Features (from MLFinLab)
Encode price series as discrete symbols, compute information-theoretic measures:

| Feature | Method | Meaning |
|---|---|---|
| Shannon entropy | `-sum(p * log(p))` | Classic information measure |
| Lempel-Ziv entropy | Compression-based complexity | Algorithmic randomness |
| Plug-in entropy | PMF-based | Probability distribution entropy |
| Kontoyiannis entropy | Match-length based | Sequential predictability |

- Encoding: `quantile_mapping(array, num_letters=26)` or `sigma_mapping(array, step)`
- Low entropy = predictable (potentially tradeable), High entropy = random (avoid)
- Novel signal class not in current `cmc_features` pipeline

### Non-Linear Codependence (from MLFinLab)
Beyond Pearson correlation — detect non-linear relationships:

| Measure | What It Captures |
|---|---|
| Distance correlation | Non-linear statistical dependence (zero iff independent) |
| Mutual information | Total shared information (linear + non-linear) |
| Variation of information | Information-theoretic distance metric |
| Wasserstein distance | Optimal transport distance between distributions |

- Compute for asset pairs and TF pairs
- Extends `cmc_regime_comovement` with non-linear dependency measures
- VI-based hierarchical clustering for grouping assets (alternative to correlation-based)

</scope>

<requirements>
## Requirements

- MICRO-01: Fractional differentiation with auto-tuned d per asset via ADF test
- MICRO-02: Kyle/Amihud/Hasbrouck lambda from OHLCV bars added to `cmc_features`
- MICRO-03: SADF bubble detection integrated into regime pipeline
- MICRO-04: Entropy features (Shannon + Lempel-Ziv minimum) computed and IC-evaluated
- MICRO-05: Non-linear codependence measures (distance correlation, mutual information) for asset/TF pairs

</requirements>

<success_criteria>
## Success Criteria

1. Fractionally differentiated prices computed for all assets with auto-tuned d via ADF test; stored as feature columns
2. Kyle/Amihud/Hasbrouck lambdas computed from OHLCV bars; added to `cmc_features` with IC scores showing predictive value
3. SADF series computed for all assets; integrated into regime pipeline as bubble/explosive flag
4. Entropy features (at least Shannon + Lempel-Ziv) computed and persisted; IC evaluated
5. Distance correlation and mutual information matrices computed; compared to Pearson for regime comovement

</success_criteria>
