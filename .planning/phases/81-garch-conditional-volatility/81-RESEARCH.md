# Phase 81: GARCH & Conditional Volatility - Research

**Researched:** 2026-03-22
**Domain:** Conditional volatility modeling (GARCH family), Python arch package, PostgreSQL storage, vol-sizing integration
**Confidence:** HIGH (arch package, FIGARCH confirmed); MEDIUM (fallback strategies, refit cadence)

---

## Summary

GARCH family models for conditional volatility forecasting are well-supported in Python via the `arch` package (current version: 8.0.0, released October 2025). The package provides GARCH(1,1), EGARCH, GJR-GARCH, and FIGARCH as named volatility processes; all four are confirmed to be implemented and support the `forecast()` API with multi-horizon outputs. The standard fit/forecast API is stable and consistent across model variants: `arch_model(returns, vol='GARCH'|'EGARCH'|'FIGARCH', p=1, q=1, o=1)`, then `res.fit()`, then `res.forecast(horizon=N)`. The `arch` package also provides `res.convergence_flag` (scipy OptimizeResult flag; 0 = success), `res.aic`, `res.bic`, `res.std_resid`, and `res.conditional_volatility` for diagnostics.

Convergence issues are common for FIGARCH and for short series (< 400 observations). The project has a 126-day minimum history threshold, which falls below the ideal 400-obs recommendation for GARCH(1,1); FIGARCH requires more. Rescaling inputs (multiply returns by 100) is the primary convergence aid. The fallback chain should be: (1) try all four variants, (2) carry forward last valid forecast with a configurable decay window (e.g., 5 days), (3) after N failures, fall back to Garman-Klass/Parkinson from existing vol estimators.

The standard evaluation framework uses RMSE (squared errors) and QLIKE (quasi-likelihood, more robust per Patton 2011) against a realized volatility proxy (5-day rolling squared returns). Mincer-Zarnowitz R-squared measures calibration. Inverse-RMSE-weighted forecast blending (Bates-Granger 1969, extended by Timmermann 2006) is the standard literature approach for combining GARCH variants with range-based estimators.

**Primary recommendation:** Use `arch>=8.0.0` as the sole GARCH library. Store GARCH forecasts in a dedicated `garch_forecasts` table (PK: id, venue_id, ts, tf, model_type, horizon). Diagnostics in `garch_diagnostics` linked by `model_run_id`. FIGARCH is the highest-risk variant (convergence failures common) -- implement it last and gate it behind a minimum 250-obs check. The vol_sizer.py blending should use inverse-RMSE weights computed on a trailing 63-day window.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `arch` | 8.0.0 | GARCH, EGARCH, GJR-GARCH, FIGARCH fitting & forecasting | The definitive Python ARCH/GARCH library by Kevin Sheppard (Oxford); no competing library covers all four variants; actively maintained, Production/Stable on PyPI |
| `statsmodels` | >=0.14.0 | Ljung-Box test (`acorr_ljungbox`), OLS for Mincer-Zarnowitz regression | Already installed (Phase 80 added it to [analysis] group) |
| `numpy` | (core dep) | Realized vol proxy computation, RMSE/QLIKE loss functions | Already present |
| `scipy.stats` | (via scipy) | Normal/t-distribution quantiles for GARCH-VaR | Already present as transitive dep |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas` | (core dep) | Time series indexing for forecast DataFrames, rolling window evaluation | All forecast storage/evaluation |
| `SQLAlchemy` | >=2.0 | Temp-table upsert pattern for garch_forecasts | Consistent with project pattern |
| `streamlit` | (existing) | Dashboard panel for vol forecast visualization | Already installed in dashboard |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `arch` | `statsmodels.tsa.statespace` | statsmodels has GARCH but not GJR-GARCH or FIGARCH; arch is purpose-built and superior for this domain |
| `arch` | `pmdarima` / `pyflux` | pyflux is unmaintained; arch is the clear ecosystem choice |
| Custom blend weights | Static config weights | Static is simpler but inferior to inverse-RMSE auto-weighting; literature-backed |

**Installation (add to [analysis] optional group in pyproject.toml):**
```bash
pip install "arch>=8.0.0"
```

Add to `pyproject.toml` under `[project.optional-dependencies]` section `analysis`:
```toml
analysis = [
  "statsmodels>=0.14.0",
  "arch>=8.0.0",
]
```

---

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── analysis/
│   ├── vol_sizer.py           # EXTEND: add GARCH blend mode
│   ├── garch_engine.py        # NEW: fitting, forecasting, diagnostics per asset
│   ├── garch_evaluator.py     # NEW: RMSE, QLIKE, MZ regression, OOS eval
│   └── garch_blend.py         # NEW: inverse-RMSE weight computation and blending
├── scripts/
│   └── garch/
│       ├── refresh_garch_forecasts.py   # NEW: daily refresh script
│       ├── garch_state_manager.py       # NEW: tracks last refit per asset
│       └── run_garch_comparison.py      # NEW: comparison report generator
alembic/versions/
    i3j4k5l6m7n8_garch_tables.py        # NEW migration
```

### Pattern 1: GARCH Model Fitting (per asset)
**What:** Fit all four variants for a single asset. Capture convergence status, AIC/BIC, Ljung-Box on standardized residuals.
**When to use:** Daily or regime-triggered refit.
**Example:**
```python
# Source: arch 8.0.0 documentation + verified API
from arch import arch_model
import numpy as np

MODEL_SPECS = {
    "garch_1_1":    dict(vol="GARCH",  p=1, q=1),
    "egarch_1_1":   dict(vol="EGARCH", p=1, o=1, q=1),
    "gjr_garch_1_1": dict(vol="GARCH",  p=1, o=1, q=1),  # o=1 activates GJR/threshold
    "figarch_1_d_1": dict(vol="FIGARCH", p=1, q=1),
}

def fit_garch_variant(returns: np.ndarray, model_type: str) -> dict:
    """Fit a single GARCH variant. Returns dict with result or convergence failure info."""
    spec = MODEL_SPECS[model_type]
    # Scale returns to % to aid optimizer convergence (avoid very small magnitudes)
    returns_scaled = returns * 100.0
    try:
        am = arch_model(
            returns_scaled,
            dist="StudentsT",   # captures fat tails; better than Normal for crypto
            rescale=True,       # auto-rescale if scale is problematic
            **spec,
        )
        res = am.fit(disp="off", options={"maxiter": 500})
        converged = (res.convergence_flag == 0)
        return {
            "result": res,
            "converged": converged,
            "aic": res.aic,
            "bic": res.bic,
            "loglik": res.loglikelihood,
        }
    except Exception as exc:
        return {"result": None, "converged": False, "error": str(exc)}
```

### Pattern 2: Multi-Horizon Forecast Extraction
**What:** Produce 1-day and 5-day ahead conditional vol forecasts from a fitted model.
**When to use:** After every successful model fit.
**Example:**
```python
# Source: arch 8.0.0 documentation (forecast API verified)
def extract_forecasts(res, horizon: int = 5) -> dict:
    """Extract variance forecasts for h.1 through h.N.

    For GARCH/GJR-GARCH: use method='analytic' (closed-form for any horizon).
    For EGARCH: use method='simulation' for h > 1 (no analytic multi-step form).
    For FIGARCH: use method='simulation' (analytic only for h=1).
    """
    vol_name = res.model.volatility.__class__.__name__
    method = "analytic"
    if vol_name in ("EGARCH", "FIGARCH") and horizon > 1:
        method = "simulation"

    forecasts = res.forecast(horizon=horizon, method=method, reindex=False)
    variance_df = forecasts.variance  # DataFrame with columns h.1 ... h.N
    # Convert variance to annualized vol: sqrt(h.1 variance * 252)
    h1_var = float(variance_df.iloc[-1]["h.1"])
    h5_var = float(variance_df.iloc[-1]["h.5"]) if horizon >= 5 else None
    # Variance was on scaled (x100) returns; unscale: divide by 100^2
    h1_vol_daily = (h1_var / 10000.0) ** 0.5
    h5_vol_daily = (h5_var / 10000.0) ** 0.5 if h5_var else None
    return {"h1_vol": h1_vol_daily, "h5_vol": h5_vol_daily}
```

### Pattern 3: GARCH-VaR Computation
**What:** Conditional VaR using GARCH volatility forecast.
**Formula:** `VaR_{t+1} = -(mu + sigma_forecast * q_alpha)` where `q_alpha` is the distribution quantile.
**Example:**
```python
# Source: verified from arch documentation + Patton/Sheppard framework
from scipy.stats import norm, t as student_t

def garch_var(mu: float, sigma_forecast: float, confidence: float = 0.95,
              dist: str = "normal", df: float = 6.0) -> float:
    """
    Compute GARCH conditional VaR.

    sigma_forecast: daily conditional vol from GARCH (fraction, e.g. 0.03 = 3%)
    Returns negative float (loss), consistent with existing var_simulator.py convention.
    """
    if dist == "normal":
        q = float(norm.ppf(1.0 - confidence))
    else:  # studentst
        q = float(student_t.ppf(1.0 - confidence, df=df))
    return mu + q * sigma_forecast  # negative for loss
```

### Pattern 4: Convergence Fallback Chain
**What:** Handle non-convergence systematically.
**When to use:** Any time `convergence_flag != 0` or an exception is raised.
**Logic:**
```python
# Source: research synthesis (no single authoritative source; industry practice)
FALLBACK_DECAY_DAYS = 5  # carry forward last valid forecast for up to 5 days

def get_forecast_with_fallback(
    asset_id: int,
    returns: np.ndarray,
    last_valid_forecasts: dict,  # {model_type: (ts, h1_vol, h5_vol)}
    today: date,
    gk_vol: float | None,        # Garman-Klass vol from existing estimator
) -> dict:
    """
    Attempt to fit and forecast. Falls back in order:
    1. Successful fit  -> use GARCH forecast
    2. Within decay window -> carry forward last valid forecast (decayed by sqrt(days_since/1))
    3. Beyond decay window -> fall back to GK/Parkinson
    4. No GK/Parkinson   -> return None (block trading advisory)
    """
    result = {}
    for model_type in ["garch_1_1", "gjr_garch_1_1", "egarch_1_1", "figarch_1_d_1"]:
        fit_result = fit_garch_variant(returns, model_type)
        if fit_result["converged"]:
            forecasts = extract_forecasts(fit_result["result"])
            result[model_type] = {
                "h1_vol": forecasts["h1_vol"],
                "h5_vol": forecasts["h5_vol"],
                "source": "garch",
                "converged": True,
            }
        else:
            # Check if we can carry forward
            if model_type in last_valid_forecasts:
                last_ts, last_h1, last_h5 = last_valid_forecasts[model_type]
                days_stale = (today - last_ts).days
                if days_stale <= FALLBACK_DECAY_DAYS:
                    # Vol grows with sqrt of time; decay is informational
                    decay_factor = (days_stale ** 0.5)
                    result[model_type] = {
                        "h1_vol": last_h1 * decay_factor,
                        "h5_vol": last_h5 * decay_factor if last_h5 else None,
                        "source": "carry_forward",
                        "converged": False,
                        "days_stale": days_stale,
                    }
                else:
                    # Fall back to range estimator
                    result[model_type] = {
                        "h1_vol": gk_vol,
                        "h5_vol": None,
                        "source": "fallback_gk",
                        "converged": False,
                    }
            else:
                result[model_type] = {
                    "h1_vol": gk_vol,
                    "h5_vol": None,
                    "source": "fallback_gk",
                    "converged": False,
                }
    return result
```

### Pattern 5: Inverse-RMSE Blend Weighting
**What:** Combine GARCH variants with existing estimators using performance-weighted blend.
**Literature:** Bates & Granger (1969) foundational; Timmermann (2006) review.
**Example:**
```python
# Source: research synthesis from Timmermann (2006) and forecast combination literature
def compute_blend_weights(rmse_dict: dict[str, float], min_weight: float = 0.05) -> dict[str, float]:
    """
    Compute inverse-RMSE weights, clipping minimum weight to avoid zero allocation.

    rmse_dict: {"garch_1_1": 0.012, "gjr_garch_1_1": 0.011, "parkinson": 0.015, ...}
    Returns normalized weights summing to 1.0.
    """
    inv_rmse = {k: 1.0 / v for k, v in rmse_dict.items() if v > 0}
    total = sum(inv_rmse.values())
    raw_weights = {k: v / total for k, v in inv_rmse.items()}
    # Apply minimum weight floor and renormalize
    floored = {k: max(v, min_weight) for k, v in raw_weights.items()}
    total_floored = sum(floored.values())
    return {k: v / total_floored for k, v in floored.items()}
```

### Pattern 6: Realized Vol Proxy for Evaluation
**What:** Use 5-day rolling realized vol (sqrt of mean squared returns over trailing 5 days) as the benchmark for RMSE/QLIKE evaluation. Do NOT use single-day squared returns (too noisy). Do NOT use Parkinson/GK as the proxy (that's what you're comparing against).
```python
# Source: verified from Patton (2011) and practical literature
def compute_realized_vol_proxy(returns: pd.Series, window: int = 5) -> pd.Series:
    """5-day rolling realized vol proxy (annualized daily)."""
    return returns.rolling(window).std()  # daily scale; multiply by sqrt(252) for annual
```

### Anti-Patterns to Avoid
- **Fitting GARCH on unscaled returns (e.g., 0.001-0.03):** Causes optimizer convergence failures. Always multiply returns by 100 before fitting, then unscale the output variance.
- **Using EGARCH with analytic multi-step forecasts:** EGARCH does NOT have a closed-form forecast for horizon > 1. Must use `method='simulation'` for h.5.
- **Fitting FIGARCH on < 200 observations:** FIGARCH requires more data than GARCH(1,1). Apply a minimum 200-obs guard (project uses 126-day minimum; FIGARCH should require 200+ days).
- **Storing variance instead of vol in the DB:** Store conditional vol (sqrt of variance) for consistency with existing Parkinson/GK/ATR values which are in vol (std dev) space.
- **Single-row upserts for 99 assets x 4 models x 2 horizons:** Use temp-table + ON CONFLICT batch upsert per the project standard.
- **Fitting on the `_u` (union) table directly for returns:** Load from `returns_bars_multi_tf` filtered to venue_id=1, tf='1D' instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GARCH variance process | Custom MLE loop | `arch.arch_model()` | arch handles parameter constraints (non-negativity, stationarity), gradient computation, residual extraction, and all four volatility process variants |
| Ljung-Box test | Manual chi-square | `statsmodels.stats.diagnostic.acorr_ljungbox()` | Already installed; handles lags, p-value computation correctly |
| Mincer-Zarnowitz R2 | Custom OLS | `statsmodels.api.OLS()` | Already installed; MZ is just `realized_vol ~ 1 + forecast_vol` OLS; use `.rsquared` |
| QLIKE loss computation | Custom formula | Custom (3 lines; no library needed) | QLIKE = mean(log(sigma^2) + realized^2/sigma^2); simple NumPy expression but NO standard library |
| Multi-horizon variance | Custom recursion | `res.forecast(horizon=5)` | arch handles the recursion for GARCH/GJR-GARCH analytically; handles simulation for EGARCH/FIGARCH |
| Student-t quantiles for VaR | Custom inverse CDF | `scipy.stats.t.ppf()` | Already available via scipy |

**Key insight:** GARCH MLE has non-trivial parameter constraints (alpha + beta < 1 for GARCH stationarity; log-variance parameterization for EGARCH). Never attempt to replicate the optimizer or constraint handling.

---

## Common Pitfalls

### Pitfall 1: FIGARCH Forecast Method
**What goes wrong:** Calling `res.forecast(horizon=5, method='analytic')` on a FIGARCH result raises an error or returns incorrect values because FIGARCH only has analytic h=1 forecasts.
**Why it happens:** FIGARCH uses fractional differencing which does not admit a simple closed-form multi-step recursion.
**How to avoid:** Always dispatch to `method='simulation'` for FIGARCH (and EGARCH) when horizon > 1. Add a per-model-type dispatch map.
**Warning signs:** TypeError or NotImplementedError in the forecast() call on FIGARCH.

### Pitfall 2: Scale of Returns
**What goes wrong:** Optimizer fails to converge with returns in decimal form (e.g., 0.001-0.03). Convergence warnings, NaN parameters.
**Why it happens:** The constant term omega in GARCH variance equation becomes very small (e.g., 1e-7) when returns are in decimal form, causing numerical gradient instability.
**How to avoid:** Scale `returns_pct = returns * 100` before fitting. The extracted conditional_volatility and forecast variance must then be divided by 100^2 = 10000 to return to decimal vol space.
**Warning signs:** `convergence_flag != 0` for GARCH(1,1) even on 500+ observation series that should converge.

### Pitfall 3: All-Variant Failure for an Asset
**What goes wrong:** All four variants fail to converge for a specific asset (e.g., a newly-listed asset with 130 days of data and a regime break mid-series).
**Why it happens:** Minimum history of 126 days is below the threshold where GARCH(1,1) converges reliably (literature: ~400 obs for reliable estimates). Regime breaks also destabilize MLE.
**How to avoid:** Track per-asset `last_successful_fit_ts` in `garch_diagnostics`. If all variants fail, emit a WARNING log event and fall back to GK vol entirely. Do NOT block the daily pipeline -- GARCH failure should be non-fatal.
**Warning signs:** `garch_diagnostics` rows where ALL four `converged = FALSE` for the same asset on the same date.

### Pitfall 4: EGARCH Asymmetry Interpretation
**What goes wrong:** Treating EGARCH as identical to GJR-GARCH for reporting. EGARCH models log(sigma^2) while GJR-GARCH models sigma^2 directly.
**Why it happens:** Both capture leverage effects but via different mechanisms.
**How to avoid:** In the comparison report, note that EGARCH captures proportional asymmetry while GJR-GARCH captures additive asymmetry. Both are valid for crypto (which shows strong leverage effects). Report both without merging their results.
**Warning signs:** Comparison table claiming "EGARCH and GJR-GARCH are equivalent."

### Pitfall 5: Forecast Alignment in Rolling OOS Evaluation
**What goes wrong:** Forecast for bar `t` is evaluated against realized vol on bar `t` instead of bar `t+1`. This is look-ahead bias.
**Why it happens:** `forecasts.variance.iloc[-1]` after fitting through `last_obs=t` gives a forecast for `t+1`. Aligning this to `t` in a DataFrame causes off-by-one bias.
**How to avoid:** Use `align='target'` in `res.forecast()` or explicitly shift the forecast series one bar forward before joining to realized vol.
**Warning signs:** RMSE values that look suspiciously low (too-good-to-be-true).

### Pitfall 6: QLIKE Loss Undefined at Zero Realized Vol
**What goes wrong:** `QLIKE = mean(log(sigma^2) + realized^2 / sigma^2)` produces NaN or -inf when either sigma or realized vol is zero.
**Why it happens:** log(0) = -inf; realized vol proxy can be near-zero for very stable assets.
**How to avoid:** Clip both forecast and realized vol to a minimum of 1e-8 before computing QLIKE. Flag assets where the proxy is zero for > 20% of evaluation period as "insufficient proxy quality."
**Warning signs:** QLIKE values of -inf or NaN in the comparison table.

### Pitfall 7: Windows spawn issue with NullPool
**What goes wrong:** If the GARCH refresh script uses SQLAlchemy engine created in the main process and then tries to pass it to a subprocess.run call with multiprocessing, connection state is corrupted.
**Why it happens:** Windows cannot fork processes; SQLAlchemy connection pools are not picklable.
**How to avoid:** Follow existing project pattern: GARCH refresh runs as a standalone script invoked via `subprocess.run()` from `run_daily_refresh.py`. No multiprocessing within the GARCH script itself (99 assets x 4 models = ~400 fits, each ~1-5 seconds; total ~30-60 min; acceptable for daily batch).
**Warning signs:** "Can't pickle..." or "connection already closed" errors.

---

## Code Examples

### Fitting All Four Variants for One Asset
```python
# Source: arch 8.0.0 API (verified via official docs + PyPI)
from arch import arch_model
import numpy as np

def fit_all_variants(returns_decimal: np.ndarray, min_obs: int = 126) -> dict:
    """
    Fit GARCH(1,1), EGARCH(1,1), GJR-GARCH(1,1,1), FIGARCH(1,d,1) for one asset.

    returns_decimal: array of arithmetic daily returns (not percentages)
    min_obs: minimum observations required (project threshold: 126 days)

    Returns: dict[model_type -> {converged, aic, bic, loglik, conditional_volatility, result}]
    """
    if len(returns_decimal) < min_obs:
        raise ValueError(f"Insufficient observations: {len(returns_decimal)} < {min_obs}")

    returns = returns_decimal * 100.0  # scale to percent for optimizer stability

    specs = {
        "garch_1_1":     dict(vol="GARCH",  p=1, o=0, q=1),
        "gjr_garch_1_1": dict(vol="GARCH",  p=1, o=1, q=1),
        "egarch_1_1":    dict(vol="EGARCH", p=1, o=1, q=1),
        "figarch_1_d_1": dict(vol="FIGARCH", p=1, q=1),
    }
    # FIGARCH needs more obs to converge reliably
    figarch_min_obs = 200

    results = {}
    for model_type, spec in specs.items():
        if model_type == "figarch_1_d_1" and len(returns) < figarch_min_obs:
            results[model_type] = {
                "converged": False,
                "error": f"Insufficient obs for FIGARCH ({len(returns)} < {figarch_min_obs})",
            }
            continue
        try:
            am = arch_model(returns, dist="StudentsT", rescale=True, **spec)
            res = am.fit(disp="off", options={"maxiter": 500})
            converged = (res.convergence_flag == 0)
            # Conditional vol is in % space; convert back to decimal
            cond_vol = res.conditional_volatility / 100.0
            results[model_type] = {
                "converged": converged,
                "aic": res.aic,
                "bic": res.bic,
                "loglik": res.loglikelihood,
                "conditional_volatility": cond_vol,
                "result": res,  # keep for forecasting
            }
        except Exception as exc:
            results[model_type] = {"converged": False, "error": str(exc)}
    return results
```

### Generating Forecasts After Successful Fit
```python
# Source: arch 8.0.0 documentation (verified)
def generate_forecasts(res, model_type: str) -> dict:
    """
    Generate 1-day and 5-day ahead conditional vol forecasts.

    EGARCH and FIGARCH require simulation for h > 1.
    Returns vol in DECIMAL space (not percent).
    """
    egarch_figarch = {"egarch_1_1", "figarch_1_d_1"}
    method_h1 = "analytic"
    method_h5 = "simulation" if model_type in egarch_figarch else "analytic"

    try:
        fc_h1 = res.forecast(horizon=1, method=method_h1, reindex=False)
        h1_var_pct2 = float(fc_h1.variance.iloc[-1]["h.1"])
        h1_vol = (h1_var_pct2 / 10000.0) ** 0.5  # unscale from %^2 to decimal^2

        fc_h5 = res.forecast(horizon=5, method=method_h5, reindex=False,
                              simulations=500 if method_h5 == "simulation" else 0)
        h5_var_pct2 = float(fc_h5.variance.iloc[-1]["h.5"])
        h5_vol = (h5_var_pct2 / 10000.0) ** 0.5

        return {"h1_vol": h1_vol, "h5_vol": h5_vol, "method_h5": method_h5}
    except Exception as exc:
        return {"h1_vol": None, "h5_vol": None, "error": str(exc)}
```

### Ljung-Box Diagnostic on Standardized Residuals
```python
# Source: statsmodels 0.14 documentation (already installed)
from statsmodels.stats.diagnostic import acorr_ljungbox

def compute_ljung_box_pvalue(res, lags: int = 10) -> float:
    """
    Ljung-Box test on std_resid to check if GARCH model fully captured autocorrelation.
    p > 0.05 means residuals are white noise (good model fit).
    Returns the minimum p-value across all lags (conservative).
    """
    std_resid = res.std_resid.dropna()
    lb_result = acorr_ljungbox(std_resid, lags=lags, return_df=True)
    return float(lb_result["lb_pvalue"].min())
```

### QLIKE Loss Computation (custom, 3 lines)
```python
# Source: Patton (2011) "Volatility forecast comparison using imperfect volatility proxies"
import numpy as np

def qlike_loss(sigma_forecast: np.ndarray, realized_vol_proxy: np.ndarray) -> float:
    """
    QLIKE = E[log(sigma^2) + realized^2/sigma^2].
    Robust to noise in realized vol proxy (Patton 2011).
    Both inputs must be in the same scale (e.g., decimal daily vol).
    """
    sigma2 = np.maximum(sigma_forecast ** 2, 1e-16)
    realized2 = np.maximum(realized_vol_proxy ** 2, 1e-16)
    return float(np.mean(np.log(sigma2) + realized2 / sigma2))
```

### Mincer-Zarnowitz R-Squared (calibration)
```python
# Source: Mincer & Zarnowitz (1969), implemented via statsmodels OLS
import statsmodels.api as sm

def mincer_zarnowitz_r2(sigma_forecast: np.ndarray, realized_vol_proxy: np.ndarray) -> float:
    """
    MZ regression: realized = alpha + beta * forecast + epsilon
    Perfect forecast: alpha=0, beta=1.
    R-squared measures how much variation in realized vol is explained.
    """
    X = sm.add_constant(sigma_forecast)
    model = sm.OLS(realized_vol_proxy, X)
    result = model.fit()
    return float(result.rsquared)
```

---

## Database Schema

### Table: garch_forecasts
```sql
CREATE TABLE public.garch_forecasts (
    id                  INTEGER        NOT NULL,
    venue_id            SMALLINT       NOT NULL REFERENCES public.dim_venues(venue_id),
    ts                  TIMESTAMPTZ    NOT NULL,
    tf                  TEXT           NOT NULL,
    model_type          TEXT           NOT NULL
        CONSTRAINT chk_garch_forecasts_model_type
        CHECK (model_type IN ('garch_1_1', 'gjr_garch_1_1', 'egarch_1_1', 'figarch_1_d_1')),
    horizon             SMALLINT       NOT NULL
        CONSTRAINT chk_garch_forecasts_horizon
        CHECK (horizon IN (1, 5)),
    cond_vol            NUMERIC(18, 8) NOT NULL,       -- daily conditional vol (decimal)
    forecast_source     TEXT           NOT NULL DEFAULT 'garch'
        CONSTRAINT chk_garch_forecasts_source
        CHECK (forecast_source IN ('garch', 'carry_forward', 'fallback_gk', 'fallback_parkinson')),
    model_run_id        BIGINT,                        -- FK to garch_diagnostics.run_id
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT now(),
    PRIMARY KEY (id, venue_id, ts, tf, model_type, horizon)
);

CREATE INDEX ix_garch_forecasts_ts ON public.garch_forecasts (ts DESC);
CREATE INDEX ix_garch_forecasts_id_model ON public.garch_forecasts (id, venue_id, model_type, horizon, ts DESC);
```

**PK rationale:** Follows project convention `(id, venue_id, ts, tf)` plus `model_type` and `horizon` to uniquely identify each forecast.

### Table: garch_diagnostics
```sql
CREATE TABLE public.garch_diagnostics (
    run_id              BIGSERIAL      PRIMARY KEY,
    id                  INTEGER        NOT NULL,
    venue_id            SMALLINT       NOT NULL REFERENCES public.dim_venues(venue_id),
    ts                  TIMESTAMPTZ    NOT NULL,
    tf                  TEXT           NOT NULL,
    model_type          TEXT           NOT NULL,
    converged           BOOLEAN        NOT NULL,
    convergence_flag    SMALLINT,                      -- scipy convergence flag (0=success)
    aic                 NUMERIC,
    bic                 NUMERIC,
    loglikelihood       NUMERIC,
    ljung_box_pvalue    NUMERIC,                       -- min p-value across 10 lags
    n_obs               INTEGER,                       -- observations used in fit
    refit_reason        TEXT,                          -- 'daily' | 'weekly' | 'regime_break'
    error_msg           TEXT,                          -- NULL if converged
    created_at          TIMESTAMPTZ    NOT NULL DEFAULT now()
);

CREATE INDEX ix_garch_diagnostics_lookup ON public.garch_diagnostics (id, venue_id, model_type, ts DESC);
```

### Materialized View: garch_forecasts_latest
```sql
CREATE MATERIALIZED VIEW public.garch_forecasts_latest AS
SELECT DISTINCT ON (id, venue_id, tf, model_type, horizon)
    id, venue_id, tf, model_type, horizon, cond_vol, forecast_source, ts
FROM public.garch_forecasts
ORDER BY id, venue_id, tf, model_type, horizon, ts DESC;

CREATE UNIQUE INDEX ON public.garch_forecasts_latest (id, venue_id, tf, model_type, horizon);
```
**Refresh:** CONCURRENTLY after every daily GARCH run.

---

## Re-fit Cadence Decision

**Research finding (MEDIUM confidence):** No single authoritative source establishes an optimal daily-vs-weekly cadence for crypto GARCH. The literature shows:
- Rolling window with 45-day lookback outperforms expanding window for crypto (Taylor et al. 2024)
- Daily refit is computationally feasible (99 assets x 4 models x ~2s/fit = ~13 minutes)
- Weekly refit misses intra-week regime breaks

**Recommendation:** Start with **daily refit** for all assets. Track `garch_diagnostics.convergence_flag` over time. After 30 days, compare per-asset fit quality between daily and rolling-window approaches. Implement a `refit_cadence` config (default: 'daily') in the GARCH state manager to allow switching without code changes.

The `garch_state_manager.py` should track:
- `last_refit_ts` per asset
- `consecutive_convergence_failures` per asset
- Whether a regime break was detected (trigger immediate refit)

---

## Integration with vol_sizer.py

**Three modes to build (all stored in config, selectable):**

| Mode | Description | When to Use |
|------|-------------|-------------|
| `sizing_only` | GARCH vol replaces rolling std in `compute_realized_vol_position()` | Default; no risk engine changes |
| `sizing_and_limits` | GARCH vol used in sizing AND fed to VaR gates | When GARCH shows better OOS accuracy |
| `advisory` | GARCH generates a risk signal but sizing unchanged | Testing/validation period |

**Blend approach:** Auto-weighted (inverse RMSE over trailing 63-day window). Weights stored in `garch_diagnostics` or a separate `garch_blend_weights` table. vol_sizer.py calls `garch_blend.get_blended_vol(asset_id, venue_id, tf, today)` which reads from `garch_forecasts_latest` and applies the current weights.

**Key extension points in vol_sizer.py:**
```python
# Extend compute_realized_vol_position() to accept an optional garch_vol override:
def compute_realized_vol_position(
    rolling_std: float,
    close: float,
    init_cash: float,
    risk_budget: float,
    max_position_pct: float = 0.30,
    garch_vol: float | None = None,           # NEW
    garch_mode: str = "sizing_only",           # NEW: 'sizing_only'|'sizing_and_limits'|'advisory'
    blend_weight: float = 1.0,                 # NEW: weight for GARCH (0=pure rolling, 1=pure GARCH)
) -> float:
    # If GARCH available, blend:
    effective_vol = rolling_std
    if garch_vol is not None and garch_mode != "advisory":
        effective_vol = blend_weight * garch_vol + (1 - blend_weight) * rolling_std
    if effective_vol <= 0:
        return 0.0
    ...
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| GARCH(1,1) only | Full suite: GARCH + EGARCH + GJR-GARCH + FIGARCH | Captures leverage, asymmetry, long memory |
| Normal errors | Student's t errors | Better tail calibration for crypto |
| In-sample only evaluation | Rolling OOS with RMSE + QLIKE + MZ R2 | Avoids overfit; QLIKE more robust per Patton (2011) |
| Static vol sizer (ATR or realized vol) | Blended GARCH + range estimators | Dynamic weighting adapts to forecast quality |
| arch 4.x / 5.x | arch 8.0.0 | Requires Python >=3.9; consistent API for all four variants |

**Deprecated/outdated:**
- `PyFlux`: Unmaintained as of ~2019. Do NOT use.
- `rugarch` (R package): Excellent but R-only. The `arch` Python package is equivalent.
- GARCH with normal errors for crypto: Substantially underestimates tail risk. Always use `dist='StudentsT'`.

---

## Open Questions

1. **Refit cadence -- daily vs regime-triggered**
   - What we know: Daily is feasible (~13 min); regime breaks destabilize MLE.
   - What's unclear: Whether GARCH quality degrades meaningfully between daily and weekly refits for the 99 specific assets in this universe.
   - Recommendation: Build infrastructure that records `refit_reason` in `garch_diagnostics`; implement daily default; add regime_break trigger later (Phase 82+).

2. **FIGARCH forecast method for horizon=5**
   - What we know: arch docs state FIGARCH forecast method; GitHub source confirms FIGARCH is in `volatility.py`.
   - What's unclear: Whether FIGARCH's `forecast(horizon=5, method='simulation')` in arch 8.0.0 produces numerically stable results or has known bugs.
   - Recommendation: Test FIGARCH h.5 forecast with known returns series in a unit test before relying on it. The GitHub issue #295 ("Computing variance from FIGARCH") and #572 suggest past bugs; verify the current behavior.

3. **ALL-convergence-failure handling per asset**
   - What we know: Assets with 126-200 observations and regime breaks may fail all four variants.
   - What's unclear: Whether to block trading or use purely range-based vol.
   - Recommendation: Use range-based GK/Parkinson as fallback. Do NOT block trading. Log `forecast_source='fallback_gk'` in `garch_forecasts`.

4. **Blending GARCH with existing estimators for VaR**
   - What we know: Blended VaR (GARCH + historical/CF) is supported in the schema design.
   - What's unclear: Whether to expose GARCH-VaR as a new column in `var_simulator.py` or as a separate lookup.
   - Recommendation: Add `garch_var` as a new method in `var_simulator.py` that reads from `garch_forecasts_latest`.

---

## Sources

### Primary (HIGH confidence)
- `arch` 8.0.0 official documentation at `arch.readthedocs.io` -- model variants, fit/forecast API, convergence_flag, AIC/BIC, std_resid
- PyPI `arch` page -- version 8.0.0, Python >=3.9 requirement, dependencies
- GitHub `bashtage/arch` repo -- FIGARCH confirmed in `arch/univariate/volatility.py` class list
- statsmodels 0.14 (installed) -- `acorr_ljungbox`, `OLS` for MZ regression

### Secondary (MEDIUM confidence)
- Patton (2011) "Volatility forecast comparison using imperfect volatility proxies" (Journal of Econometrics) -- QLIKE loss robustness property; verified via abstract from ScienceDirect
- Bates & Granger (1969) / Timmermann (2006) "Forecast Combinations" review -- inverse-RMSE weighting; verified via Aiolfi-Capistrán-Timmermann working paper at econstor.eu
- Small sample GARCH literature (bayes.citystgeorges.ac.uk WP-CEA-10-2004) -- 400-obs convergence threshold
- WebSearch results on EGARCH multi-step analytic limitation -- multiple sources agree; verified against arch docs noting "simulation or bootstrapping required"

### Tertiary (LOW confidence)
- Crypto GARCH refit cadence -- no authoritative single paper; synthesized from multiple WebSearch results about rolling vs expanding windows
- Fallback carry-forward decay strategy -- industry practice synthesis, not from a single published source

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- arch 8.0.0 confirmed on PyPI; all four model types confirmed in volatility.py source
- Architecture: HIGH -- follows established project patterns (upsert, temp table, venue_id FK, subprocess-based daily refresh)
- Pitfalls: HIGH for convergence/scaling; MEDIUM for FIGARCH multi-step stability; LOW for exact decay parameters
- Evaluation methodology: HIGH for RMSE/QLIKE; MEDIUM for exact rolling window size choice

**Research date:** 2026-03-22
**Valid until:** 2026-06-22 (stable library, 90 days)

**arch 8.0.0 breaking changes vs earlier versions:** Not fully documented in available sources. The API (`arch_model()`, `.fit()`, `.forecast()`) is unchanged from 7.x. Verify Python >=3.9 requirement is met (project uses >=3.10, so fine).
