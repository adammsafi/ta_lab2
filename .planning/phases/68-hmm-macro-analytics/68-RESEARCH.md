# Phase 68: HMM & Macro Analytics - Research

**Researched:** 2026-03-02
**Domain:** GaussianHMM (hmmlearn), cross-correlation lead-lag analysis, Markov transition matrices, PostgreSQL schema design, Alembic migrations, daily refresh integration
**Confidence:** HIGH

---

## Summary

Phase 68 adds three secondary analytical tools on top of the Phase 67 macro regime infrastructure: a GaussianHMM secondary classifier, a macro-crypto lead-lag scanner, and regime transition probability matrices. All three are analytical supplements -- none replace the rule-based regimes from Phase 67.

The codebase already has the critical building blocks. `lead_lag_max_corr()` in `ta_lab2/regimes/comovement.py` is the exact function to extend for macro-crypto cross-correlations. `sklearn.metrics.cohen_kappa_score` and `confusion_matrix` are available (scikit-learn 1.8.0). `hmmlearn 0.3.3` is NOT yet installed but is a clean `pip install hmmlearn` (no conflicts). The Alembic head is `c4d5e6f7a8b9` (Phase 66 migration); Phase 67 migration will chain from this, and Phase 68 migration chains from whatever Phase 67 produces.

The `fred.fred_macro_features` table has been confirmed via migration files. The available numeric float columns for HMM input are: `walcl`, `wtregen`, `rrpontsyd`, `dff`, `dgs10`, `t10y2y`, `vixcls`, `dtwexbgs`, `ecbdfr`, `irstci01jpm156n`, `irltlt01jpm156n`, `net_liquidity`, `us_jp_rate_spread`, `us_ecb_rate_spread`, `us_jp_10y_spread`, `yc_slope_change_5d`, `dtwexbgs_5d_change`, `dtwexbgs_20d_change`, `hy_oas_level`, `hy_oas_5d_change`, `hy_oas_30d_zscore`, `nfci_level`, `m2_yoy_pct`, `dexjpus_level`, `dexjpus_5d_pct_change`, `dexjpus_20d_vol`, `dexjpus_daily_zscore`, `net_liquidity_365d_zscore`, `target_mid`, `target_spread`, `cpi_surprise_proxy`, `carry_momentum`, `m2sl`, `bamlh0a0hym2`, `nfci`, `dexjpus`, `cpiaucsl`, `dfedtaru`, `dfedtarl`. Text columns (`vix_regime`, `nfci_4wk_direction`, `fed_regime_structure`, `fed_regime_trajectory`, `net_liquidity_trend`, `source_freq_*`) are NOT numeric and must be excluded from HMM input.

**Key correction from Phase 67 research:** `net_liquidity_30d_zscore` and `net_liquidity_30d_change` do NOT exist in `fred_macro_features`. The actual columns are `net_liquidity_365d_zscore` and `net_liquidity_trend`. Any Phase 68 code that references the 30d variants will fail silently or with NaN.

**Primary recommendation:** Module goes in `ta_lab2/macro/hmm_classifier.py` for HMM, `ta_lab2/macro/lead_lag_analyzer.py` for cross-correlation, and `ta_lab2/macro/transition_probs.py` for transition matrices. All three are wired through a single `refresh_macro_analytics.py` script integrated into `run_daily_refresh.py` as a `--macro-analytics` flag.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hmmlearn | 0.3.3 | GaussianHMM: fit, predict, bic(), aic(), transmat_ | Official Python HMM library, scikit-learn compatible API |
| scikit-learn | 1.8.0 (installed) | StandardScaler for HMM input scaling; cohen_kappa_score, confusion_matrix | Already installed, no new dep |
| pandas | 2.x (installed) | DataFrame ops, date alignment, rolling cross-correlation loops | All existing feature/regime code |
| sqlalchemy | 2.x (installed) | Engine, text(), upsert pattern | Project-wide DB convention |
| numpy | installed | Array shape for hmmlearn X input, dropna patterns | Already used everywhere |
| alembic | installed | Schema migrations for 4 new tables | All schema changes go through Alembic |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sklearn.preprocessing.StandardScaler | 1.8.0 | Scale HMM inputs to zero-mean unit-variance | Always before fit(); HMM is sensitive to feature scale |
| sklearn.metrics.cohen_kappa_score | 1.8.0 | HMM vs rule-based agreement measurement | Cohen's kappa for categorical label agreement |
| sklearn.metrics.confusion_matrix | 1.8.0 | HMM state vs rule-based regime cross-tabulation | Produces the N x N comparison matrix |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hmmlearn GaussianHMM | pomegranate HMM | pomegranate has richer distributions but is a larger dep; hmmlearn is lighter and already decided by CONTEXT.md |
| Bartlett significance threshold | Bootstrap significance | Bootstrap is more robust for autocorrelated macro data but slower; Bartlett is a fast analytical approximation sufficient for flagging |

**Installation (new dep only):**
```bash
pip install hmmlearn==0.3.3
```
Also add to `pyproject.toml` under a new `[project.optional-dependencies]` group:
```toml
[project.optional-dependencies]
macro_analytics = [
  "hmmlearn>=0.3.3",
]
```
Do not add to core `dependencies` -- it is an optional analytics tool.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/macro/
├── __init__.py                  # Add HMMClassifier, LeadLagAnalyzer, TransitionProbMatrix exports
├── feature_computer.py          # Phase 65 (unchanged)
├── forward_fill.py              # Phase 65 (unchanged)
├── fred_reader.py               # Phase 65 (unchanged)
├── regime_classifier.py         # Phase 67 (MacroRegimeClassifier)
├── hmm_classifier.py            # NEW: GaussianHMM wrapper, expanding window, BIC/AIC selection
├── lead_lag_analyzer.py         # NEW: macro-crypto cross-correlation scanner
└── transition_probs.py          # NEW: static + rolling transition matrices

src/ta_lab2/scripts/macro/
├── refresh_macro_features.py    # Phase 65/66 (unchanged)
├── refresh_macro_regimes.py     # Phase 67 (unchanged)
└── refresh_macro_analytics.py   # NEW: CLI for HMM + lead-lag + transition probs

alembic/versions/
└── XXXX_hmm_macro_analytics_tables.py  # NEW: 4 new tables
```

**Import-linter note:** `ta_lab2.macro` is not yet in the layers contract. It is treated as a peer to `ta_lab2.features` (base layer), only imported by scripts. Do not import `ta_lab2.macro` from `ta_lab2.regimes`, `ta_lab2.signals`, or `ta_lab2.analysis` -- this would require updating the import-linter contract. Keep all macro analytics in `ta_lab2.macro.*` and consumed by `ta_lab2.scripts.macro.*`.

---

### Pattern 1: GaussianHMM with Expanding Window

The core HMM fitting loop runs from a `min_train_date` (ensure at least 2 years of data for stability) up to each refit date. Use `covariance_type="full"` for multivariate macro data. Multiple random restarts (10) guard against local optima.

```python
# Source: hmmlearn 0.3.3 official docs (https://hmmlearn.readthedocs.io/en/latest/api.html)

from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
import numpy as np

_N_RESTARTS = 10
_N_ITER = 200
_COVARIANCE_TYPE = "full"   # multivariate macro features -- full covariance
_MIN_TRAIN_ROWS = 504       # ~2 calendar years of daily data (minimum viable)

def fit_best_hmm(X: np.ndarray, n_states: int, random_seed: int = 42) -> GaussianHMM:
    """Fit GaussianHMM with multiple restarts, return best by log-likelihood.

    X: shape (n_samples, n_features), NO NaNs, pre-scaled.
    """
    best_model = None
    best_score = -np.inf
    rng = np.random.RandomState(random_seed)
    for i in range(_N_RESTARTS):
        model = GaussianHMM(
            n_components=n_states,
            covariance_type=_COVARIANCE_TYPE,
            n_iter=_N_ITER,
            tol=1e-4,
            random_state=rng.randint(0, 2**31),
            verbose=False,
        )
        try:
            model.fit(X)
            s = model.score(X)
            if not np.isfinite(s):
                continue
            if s > best_score:
                best_score = s
                best_model = model
        except Exception:
            continue
    return best_model


def fit_expanding_window(
    df: pd.DataFrame,
    feature_cols: list[str],
    n_states_options: list[int],
    refit_dates: list[pd.Timestamp],
) -> pd.DataFrame:
    """
    Expanding window HMM: for each date in refit_dates,
    fit on all history up to that date. Pick winner by BIC.

    Returns DataFrame with columns: [date, n_states, hmm_state, bic, aic, is_winner, model_run_date]
    """
    all_rows = []
    scaler = StandardScaler()

    for refit_date in refit_dates:
        window = df[df.index <= refit_date][feature_cols].dropna(how="any")
        if len(window) < _MIN_TRAIN_ROWS:
            continue  # not enough data

        X = scaler.fit_transform(window.values.astype(float))

        model_by_n = {}
        for n in n_states_options:
            model = fit_best_hmm(X, n_states=n)
            if model is None:
                continue
            model_by_n[n] = {
                "model": model,
                "bic": model.bic(X),
                "aic": model.aic(X),
            }

        if not model_by_n:
            continue

        # Winner = lowest BIC
        winner_n = min(model_by_n, key=lambda n: model_by_n[n]["bic"])

        for n, info in model_by_n.items():
            states = info["model"].predict(X)
            for ts, state in zip(window.index, states):
                all_rows.append({
                    "date": ts.date(),
                    "n_states": n,
                    "hmm_state": int(state),
                    "bic": float(info["bic"]),
                    "aic": float(info["aic"]),
                    "is_winner": (n == winner_n),
                    "model_run_date": refit_date.date(),
                })

    return pd.DataFrame(all_rows)
```

**Critical:** The refit loop runs daily but re-uses the winner model for the SAME DATE's prediction (no look-ahead). The `model_run_date` column records when the model was fit, separate from the `date` of the prediction. Since daily refitting of an expanding window is expensive, consider `refit_dates` to be month-ends in production (refit monthly, predict with most recent model daily between refits).

### Pattern 2: lead_lag_max_corr Extension for Macro-Crypto

The existing `lead_lag_max_corr()` in `ta_lab2/regimes/comovement.py` accepts a wide DataFrame and two column names. For macro-crypto analysis, align daily macro features with daily crypto returns (1D bars from `cmc_price_bars_multi_tf`), then call the function for each macro feature x asset pair.

```python
# Source: ta_lab2/regimes/comovement.py (confirmed implementation, lines 109-144)

from ta_lab2.regimes.comovement import lead_lag_max_corr

def compute_macro_lead_lag(
    macro_df: pd.DataFrame,           # index=date, columns=macro feature cols
    returns_df: pd.DataFrame,         # index=date, columns=asset return cols (e.g. 'ret_btc', 'ret_eth')
    macro_cols: list[str],
    asset_cols: list[str],
    lag_range: range = range(-60, 61), # [-60, +60] daily lags
) -> pd.DataFrame:
    """
    Run lead_lag_max_corr for every (macro_feature x asset) pair.

    Positive lag in lead_lag_max_corr means col_b is shifted forward
    (col_b leads col_a). Here col_a = macro feature, col_b = returns.
    So positive best_lag means returns leads macro (macro lags behind returns).
    Negative best_lag means macro leads returns (macro is predictive).

    Returns: long-format DataFrame with one row per (macro_col, asset_col) pair.
    """
    # Align on common dates (inner join)
    aligned = macro_df.join(returns_df, how="inner")
    rows = []
    for mc in macro_cols:
        if mc not in aligned.columns:
            continue
        for ac in asset_cols:
            if ac not in aligned.columns:
                continue
            pair_df = aligned[[mc, ac]].dropna()
            if len(pair_df) < max(abs(lag_range.start), lag_range.stop) + 30:
                continue  # not enough obs for the lag range
            result = lead_lag_max_corr(pair_df, mc, ac, lags=lag_range)
            # Significance via Bartlett approximation: |r| > 2/sqrt(N)
            n = len(pair_df)
            bartlett_threshold = 2.0 / (n ** 0.5)
            is_significant = abs(result["best_corr"]) > bartlett_threshold

            # Full cross-correlation series (all lags)
            corr_series = result["corr_by_lag"]  # pd.Series indexed by lag int

            rows.append({
                "macro_feature": mc,
                "asset_col": ac,
                "best_lag": result["best_lag"],
                "best_corr": result["best_corr"],
                "is_significant": is_significant,
                "n_obs": n,
                "lag_range_min": lag_range.start,
                "lag_range_max": lag_range.stop - 1,
                # Store all lags as JSON blob or compute separately
                "corr_at_lag_0": float(corr_series.get(0, float("nan"))),
            })

    return pd.DataFrame(rows)
```

**Convention note:** In `lead_lag_max_corr`, `col_a` is the reference and `col_b` is shifted. When `col_a = macro_feature` and `col_b = returns`:
- `best_lag < 0`: macro leads returns (macro is predictive of future returns)
- `best_lag > 0`: returns leads macro (macro is lagging indicator)

This convention must be documented in the DB column description.

**Bartlett threshold:** For i.i.d. series, the 95% significance boundary is `|r| > 2/sqrt(N)` where N is the number of observations. This is an approximation; macro and crypto returns both have autocorrelation, which reduces effective N. The threshold is a first-order flag, not a rigorous test. Store `is_significant` as a boolean flag; downstream consumers can apply stricter tests.

### Pattern 3: Transition Probability Matrix

Transition matrices count (from_state, to_state) pairs in a sequence of daily regime labels, then row-normalize. Both static (all history) and rolling versions use the same counting logic.

```python
# Source: informed by regime_eval.py:regime_transition_pnl() pattern (existing code)

import pandas as pd
import numpy as np

def compute_transition_matrix(
    regime_series: pd.Series,
    states: list[str] | None = None,
) -> pd.DataFrame:
    """
    Compute row-normalized transition probability matrix from a daily regime label series.

    Args:
        regime_series: pd.Series with string (or int) regime labels, daily cadence.
        states: ordered list of states. If None, derived from unique values.

    Returns:
        Square DataFrame (from_state x to_state), row sums = 1.0.
        NaN rows mean that state was never observed (avoid division by zero).
    """
    s = regime_series.dropna()
    if states is None:
        states = sorted(s.unique().tolist())

    counts = pd.DataFrame(0, index=states, columns=states, dtype=float)
    prev = s.iloc[:-1].values
    curr = s.iloc[1:].values

    for p, c in zip(prev, curr):
        if p in counts.index and c in counts.columns:
            counts.loc[p, c] += 1

    # Row-normalize (each row sums to 1.0)
    row_sums = counts.sum(axis=1)
    probs = counts.div(row_sums, axis=0)  # NaN where row_sum == 0
    return probs


def compute_rolling_transition_matrix(
    regime_series: pd.Series,
    window_days: int,
    states: list[str] | None = None,
) -> dict[pd.Timestamp, pd.DataFrame]:
    """
    Compute transition matrix for each date using a rolling window of window_days.
    Returns dict: end_date -> transition matrix DataFrame.
    Only computed for dates where at least window_days/2 observations are available.
    """
    result = {}
    idx = regime_series.dropna().index
    for i, end_date in enumerate(idx):
        start_idx = max(0, i - window_days + 1)
        window = regime_series.iloc[start_idx:i + 1]
        if len(window) < window_days // 2:
            continue
        result[end_date] = compute_transition_matrix(window, states=states)
    return result
```

**Rolling window size decision:** 252 days (1 trading year) is the recommended default for daily macro regime data. Rationale: macro regimes persist for weeks to months (not days), so a 1-year window contains enough transitions to estimate meaningful probabilities while being responsive to structural changes. 90-day windows are too short for macro data with long regime durations (will have sparse off-diagonal entries). Expose as a configurable constant `ROLLING_WINDOW_DAYS = 252`.

### Pattern 4: DB Schema (1-table vs 3-table decision)

**Decision: 1 table for transition probabilities (not 3).**

One table `cmc_macro_transition_probs` with `window_type` (TEXT: 'static' or 'rolling'), `regime_source` (TEXT: 'rule_based' or 'hmm'), `window_end_date` (DATE, NULL for static), and `from_state`/`to_state`/`probability` columns. This is simpler to query and upsert, avoids table proliferation, and is the right choice given 4 combinations (2 regime sources x 2 window types) would each be a separate table.

**Total new tables: 3**
1. `cmc_hmm_regimes` -- one row per (date, n_states, run_date)
2. `cmc_macro_lead_lag_results` -- one row per (macro_feature, asset_col, computed_at)
3. `cmc_macro_transition_probs` -- one row per (regime_source, window_type, window_end_date, from_state, to_state)

Note: CONTEXT.md names the first two tables `hmm_regimes` and `macro_lead_lag_results` (without `cmc_` prefix). Use `cmc_` prefix as the project convention states, matching CONTEXT.md spirit of the naming.

### Pattern 5: Alembic Migration Chaining

Phase 68 migration chains from whatever Phase 67 migration produces. Phase 67 migration does NOT yet exist (confirmed: `alembic heads` returns `c4d5e6f7a8b9`). Phase 68 plan must:
1. In Wave 1, first verify current head by running `alembic heads`
2. If Phase 67 migration has been applied, use Phase 67's revision as `down_revision`
3. If Phase 67 migration has NOT been applied yet (Phase 68 executes before Phase 67), use `c4d5e6f7a8b9`

**Safe approach:** Wave 1 task should run `alembic heads` and use the confirmed head dynamically, not hardcode a planned Phase 67 revision ID.

### Pattern 6: Daily Refresh Integration

Add `run_macro_analytics()` to `run_daily_refresh.py` matching the `run_macro_features()` pattern exactly. Position: after `run_macro_regimes()` (Phase 67) and before `run_regimes()` (per-asset).

```
... -> macro_features -> macro_regimes (Phase 67) -> macro_analytics (Phase 68, NEW) -> regimes -> ...
```

```python
# Source: run_daily_refresh.py:run_macro_features() pattern (lines 1629-1738)

TIMEOUT_MACRO_ANALYTICS = 600  # 10 minutes -- HMM refit + lead-lag scan is heavier

def run_macro_analytics(args) -> ComponentResult:
    """Run HMM classifier + lead-lag analysis + transition matrix update via subprocess."""
    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.scripts.macro.refresh_macro_analytics",
    ]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")
    # ... subprocess.run() boilerplate identical to run_macro_features() ...
```

Add `--macro-analytics` flag and `--no-macro-analytics` skip flag. Include in `--all` mode.

### Anti-Patterns to Avoid

- **Fitting HMM on raw unscaled macro features:** Net liquidity is in billions USD, VIX is in ~10-100 range, z-scores are in ~(-3,3). GaussianHMM assumes equal-scale Gaussian emissions; fitting on unscaled data produces garbage covariance matrices. Always StandardScaler before fit.
- **Fitting HMM including NaN rows:** `GaussianHMM.fit()` does NOT handle NaN -- it silently produces NaN means and zero-row transition matrices. Always `dropna(how="any")` before passing to fit(). Log how many rows were dropped.
- **Look-ahead bias in expanding window:** The labels assigned to historical dates during a refit that uses future data are look-ahead biased. The correct approach: labels for date T are assigned only using models fit on data up to T. Store `model_run_date` separately from `date` to make this auditable.
- **Using text macro columns as HMM input:** `vix_regime`, `fed_regime_trajectory`, `nfci_4wk_direction`, `net_liquidity_trend` are string categoricals. Never pass these to StandardScaler or GaussianHMM. Select only float columns.
- **Hardcoding `net_liquidity_30d_zscore`:** This column does not exist. Use `net_liquidity_365d_zscore`. The Phase 67 research docs incorrectly reference `net_liquidity_30d_zscore` and `net_liquidity_30d_change` -- these were planned but not implemented in the migration.
- **Running transition matrix on un-aligned rule-based vs HMM dates:** The rule-based regime labels come from `cmc_macro_regimes` (date index). The HMM labels come from `cmc_hmm_regimes` (date index). These must be matched by date before comparison or transition computation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HMM fitting | Custom EM algorithm | `hmmlearn.hmm.GaussianHMM` | Numerically stable Baum-Welch, handles convergence; hand-rolled EM diverges |
| HMM model selection | Custom BIC formula | `model.bic(X)`, `model.aic(X)` | hmmlearn 0.3.3 provides these directly; formula for HMM BIC is subtle (must account for transition matrix params + emission params) |
| Feature scaling for HMM | Mean-centering by hand | `sklearn.preprocessing.StandardScaler` | Handles fit/transform separation cleanly, prevents data leakage |
| Cohen's kappa | Custom agreement formula | `sklearn.metrics.cohen_kappa_score` | Handles chance-agreement correction; already available |
| Cross-correlation sweep | For-loop over pandas .corr() | `lead_lag_max_corr()` from `ta_lab2.regimes.comovement` | Already exists, tested, correct shift convention documented |
| Transition counting | Nested dict counting | pandas `shift()` + `groupby()` on consecutive pairs | 2-3 lines; no need for a class |
| Upsert | Direct INSERT in loop | Temp table + ON CONFLICT pattern from `upsert_macro_features()` | Project-wide convention; copy pattern exactly |
| NaN/numpy scalar safety | Custom type checks | `_to_python()` + `_sanitize_dataframe()` from `refresh_macro_features.py` | Copy these directly; psycopg2 breaks without them |

---

## Common Pitfalls

### Pitfall 1: HMM NaN Columns Silently Corrupt the Model
**What goes wrong:** `fred_macro_features` has many early-history NaN values (warmup periods for rolling features, missing FRED observations). If these NaN rows are included in `X`, `GaussianHMM.fit()` produces `means_ = [NaN, ...]` and `transmat_ = [[0, 0, ...], ...]` -- the model appears to "succeed" but all predictions are garbage.
**Why it happens:** hmmlearn does not validate or reject NaN inputs; it computes forward/backward passes that propagate NaN through all probability computations.
**How to avoid:** Before calling `fit()`, always: `X = feature_df.dropna(how='any').values`. Log the number of dropped rows. Fail hard if more than 50% of rows are dropped (indicates a structural data problem).
**Warning signs:** `model.means_` contains NaN, `model.monitor_.converged == False` after max iterations.

### Pitfall 2: Local Optima in GaussianHMM EM
**What goes wrong:** Single-restart HMM fitting converges to a poor local optimum -- states that don't match intuitive macro regimes (e.g., one state captures 95% of observations, the other 5%).
**Why it happens:** The EM algorithm for HMMs is not convex; initialization strongly affects convergence.
**How to avoid:** Always use `_N_RESTARTS = 10` random initializations, keep the model with highest `model.score(X)`. Verify that state occupancy is not degenerate (no state should have < 5% of observations in the training set).
**Warning signs:** One state has >90% occupancy in `model.predict(X)`.

### Pitfall 3: BIC Favors Fewer States for Short Histories
**What goes wrong:** BIC penalizes complexity more heavily than AIC. On 2-3 years of daily data, BIC may always select 2 states even when 3 states better capture the macro cycle, because the BIC penalty dominates.
**Why it happens:** BIC penalty = `k * log(n)` where `k` is number of parameters (large for GaussianHMM with full covariance) and `n` is number of observations.
**How to avoid:** Store both BIC and AIC winners; flag both in `cmc_hmm_regimes.is_winner`. Use BIC as the tiebreaker but log when AIC and BIC disagree. Treat model selection as informational, not definitive.
**Warning signs:** BIC always selects 2 states regardless of training window size.

### Pitfall 4: Lead-Lag Convention Confusion
**What goes wrong:** Reporting `best_lag = -20` without documenting that this means "macro leads returns by 20 days" -- consumers interpret the sign incorrectly.
**Why it happens:** The `lead_lag_max_corr()` function shifts `col_b` (returns) relative to `col_a` (macro). Negative lag means returns are shifted backward in time (i.e., macro at time T correlates with returns at time T+|lag|), which means macro leads.
**How to avoid:** Document the convention explicitly in the DB column description and in the `cmc_macro_lead_lag_results` table as `best_lag_convention TEXT DEFAULT 'negative_means_macro_leads'`.
**Warning signs:** None at runtime -- this is a documentation/interpretation failure.

### Pitfall 5: Alembic Chain Gap (Phase 67 Not Yet Applied)
**What goes wrong:** Phase 68 migration is written with `down_revision` pointing to a planned Phase 67 revision ID that hasn't been applied yet. `alembic upgrade head` fails or creates a branched history.
**Why it happens:** Phase 68 may execute before Phase 67 migration exists.
**How to avoid:** Wave 1 task must run `alembic heads` to discover current head; write Phase 68 migration with `down_revision` pointing to actual runtime head, not a planned ID.
**Warning signs:** `alembic check` shows multiple heads or detects a missing revision.

### Pitfall 6: HMM State Labels Are Arbitrary (Not Semantic)
**What goes wrong:** The HMM assigns integer labels (0, 1, or 2 for 3-state). State 0 in one run may correspond to "risk-on" and in another run it may correspond to "risk-off" -- the label is just an index.
**Why it happens:** HMM EM initialization is random; state ordering is not guaranteed.
**How to avoid:** For the comparison with rule-based regimes (confusion matrix + kappa), use the intersection of dates and compare numerically. For human consumption, annotate each HMM state with its `mean_` values (mean of each feature in that state) rather than relying on the integer label. Store `state_means_json` (JSON blob) in the model metadata table.
**Warning signs:** Confusion matrix rows/columns show near-uniform distributions.

### Pitfall 7: Rolling Window Too Small for Macro Regimes
**What goes wrong:** Using a 90-day rolling window for transition probabilities. Macro regimes last months. A 90-day window covering 1-2 complete cycles will have extremely sparse transition counts -- many cells will be 0 or will oscillate wildly.
**Why it happens:** Borrowing rolling-window intuitions from financial returns (daily VIX regime) to macro regimes.
**How to avoid:** Use 252-day rolling window (1 year) as minimum. Compute it but annotate with confidence = low if fewer than 3 observed transitions in the window.
**Warning signs:** Transition matrix diagonal near 1.0 for all states (no transitions observed in the window).

---

## Code Examples

### GaussianHMM Model Selection (official docs pattern)

```python
# Source: https://hmmlearn.readthedocs.io/en/latest/auto_examples/plot_gaussian_model_selection.html

from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler
import numpy as np

def select_hmm_by_bic(X_scaled: np.ndarray, n_states_list: list[int]) -> dict:
    """
    For each n_states, fit 10 models (random inits), keep best by score.
    Compare best models across n_states using BIC.
    Returns dict with keys: winner_n_states, models, bics, aics.
    """
    models = {}
    bics = {}
    aics = {}
    rng = np.random.RandomState(42)

    for n in n_states_list:
        best_model = None
        best_score = -np.inf
        for _ in range(10):  # multiple random initializations
            m = GaussianHMM(
                n_components=n,
                covariance_type="full",
                n_iter=200,
                tol=1e-4,
                random_state=rng.randint(0, 2**31),
            )
            m.fit(X_scaled)
            s = m.score(X_scaled)
            if np.isfinite(s) and s > best_score:
                best_score = s
                best_model = m

        if best_model is not None:
            models[n] = best_model
            bics[n] = best_model.bic(X_scaled)
            aics[n] = best_model.aic(X_scaled)

    winner_n = min(bics, key=bics.get)  # lowest BIC wins
    return {
        "winner_n_states": winner_n,
        "models": models,
        "bics": bics,
        "aics": aics,
    }
```

### Full Column List for HMM Input (from confirmed migration files)

```python
# Source: alembic/versions/a1b2c3d4e5f6_fred_macro_features.py (Phase 65)
#       + alembic/versions/c4d5e6f7a8b9_fred_phase66_derived_columns.py (Phase 66)

# All numeric (FLOAT) columns available in fred.fred_macro_features.
# Exclude text columns (regime categoricals) and metadata (ingested_at, source_freq_*).
_HMM_CANDIDATE_COLUMNS = [
    # Phase 65 raw FRED series
    "walcl", "wtregen", "rrpontsyd",
    "dff", "dgs10", "t10y2y",
    "vixcls", "dtwexbgs", "ecbdfr",
    "irstci01jpm156n", "irltlt01jpm156n",
    # Phase 65 derived
    "net_liquidity",
    "us_jp_rate_spread", "us_ecb_rate_spread", "us_jp_10y_spread",
    "yc_slope_change_5d",
    "dtwexbgs_5d_change", "dtwexbgs_20d_change",
    # Phase 66 raw FRED series (lowercase)
    "bamlh0a0hym2", "nfci", "m2sl", "dexjpus", "dfedtaru", "dfedtarl", "cpiaucsl",
    # Phase 66 derived features
    "hy_oas_level", "hy_oas_5d_change", "hy_oas_30d_zscore",
    "nfci_level",
    "m2_yoy_pct",
    "dexjpus_level", "dexjpus_5d_pct_change", "dexjpus_20d_vol", "dexjpus_daily_zscore",
    "net_liquidity_365d_zscore",   # NOTE: 30d variant does NOT exist
    "carry_momentum",
    "cpi_surprise_proxy",
    "target_mid", "target_spread",
]
# Excluded (TEXT columns, not float):
# vix_regime, nfci_4wk_direction, fed_regime_structure, fed_regime_trajectory,
# net_liquidity_trend, source_freq_walcl, source_freq_wtregen,
# source_freq_irstci01jpm156n, source_freq_irltlt01jpm156n
```

### Confusion Matrix and Cohen's Kappa (sklearn pattern)

```python
# Source: sklearn 1.8.0 (confirmed installed, cohen_kappa_score available)
from sklearn.metrics import cohen_kappa_score, confusion_matrix

def compare_hmm_to_rule_based(
    hmm_labels: pd.Series,      # integer HMM states (0..n_states-1)
    rule_labels: pd.Series,     # string or int rule-based macro_state labels
) -> dict:
    """Align on common dates and compute agreement metrics."""
    aligned = pd.DataFrame({"hmm": hmm_labels, "rule": rule_labels}).dropna()
    if len(aligned) < 10:
        return {"error": "insufficient overlap"}

    kappa = cohen_kappa_score(aligned["hmm"], aligned["rule"])
    cm = confusion_matrix(aligned["rule"], aligned["hmm"])
    return {
        "kappa": float(kappa),
        "n_aligned": len(aligned),
        "confusion_matrix": cm.tolist(),  # list of lists for JSON storage
    }
```

### Alembic Migration (Phase 68 tables)

```python
# Source: modeled on a1b2c3d4e5f6_fred_macro_features.py and c4d5e6f7a8b9_fred_phase66_derived_columns.py

def upgrade() -> None:
    # Table 1: cmc_hmm_regimes
    # PK: (date, n_states, model_run_date) -- allows storing all runs and winner flag
    op.create_table(
        "cmc_hmm_regimes",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("n_states", sa.Integer(), nullable=False),
        sa.Column("hmm_state", sa.Integer(), nullable=True),     # 0..n_states-1
        sa.Column("model_run_date", sa.Date(), nullable=False),  # when model was fit
        sa.Column("bic", sa.Float(), nullable=True),
        sa.Column("aic", sa.Float(), nullable=True),
        sa.Column("is_winner", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("state_means_json", sa.Text(), nullable=True),  # JSON blob of model.means_
        sa.Column("n_train_rows", sa.Integer(), nullable=True),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("date", "n_states", "model_run_date"),
    )
    op.create_index("idx_cmc_hmm_regimes_date", "cmc_hmm_regimes", [sa.text("date DESC")])
    op.create_index("idx_cmc_hmm_regimes_winner", "cmc_hmm_regimes",
                    ["is_winner", sa.text("date DESC")])

    # Table 2: cmc_macro_lead_lag_results
    # PK: (macro_feature, asset_col, computed_at) -- re-runs produce new rows dated by run
    op.create_table(
        "cmc_macro_lead_lag_results",
        sa.Column("macro_feature", sa.Text(), nullable=False),
        sa.Column("asset_col", sa.Text(), nullable=False),      # e.g. 'ret_btc', 'ret_eth'
        sa.Column("asset_id", sa.Integer(), nullable=True),     # e.g. 1 for BTC, 2 for ETH
        sa.Column("best_lag", sa.Integer(), nullable=True),
        sa.Column("best_corr", sa.Float(), nullable=True),
        sa.Column("is_significant", sa.Boolean(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        sa.Column("lag_range_min", sa.Integer(), nullable=True),
        sa.Column("lag_range_max", sa.Integer(), nullable=True),
        sa.Column("corr_at_lag_0", sa.Float(), nullable=True),
        sa.Column("bartlett_threshold", sa.Float(), nullable=True),
        # Convention documentation embedded in the table
        sa.Column("lag_convention", sa.Text(), nullable=True,
                  server_default=sa.text("'negative_means_macro_leads'")),
        sa.Column("computed_at", sa.Date(), nullable=False),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("macro_feature", "asset_col", "computed_at"),
    )
    op.create_index("idx_macro_lead_lag_feature", "cmc_macro_lead_lag_results",
                    ["macro_feature"])
    op.create_index("idx_macro_lead_lag_significant", "cmc_macro_lead_lag_results",
                    ["is_significant", sa.text("computed_at DESC")])

    # Table 3: cmc_macro_transition_probs
    # PK: (regime_source, window_type, window_end_date, from_state, to_state)
    op.create_table(
        "cmc_macro_transition_probs",
        sa.Column("regime_source", sa.Text(), nullable=False),  # 'rule_based' | 'hmm'
        sa.Column("window_type", sa.Text(), nullable=False),    # 'static' | 'rolling'
        sa.Column("window_days", sa.Integer(), nullable=True),  # NULL for static; 252 for rolling
        sa.Column("window_end_date", sa.Date(), nullable=True), # NULL for static; date for rolling
        sa.Column("from_state", sa.Text(), nullable=False),
        sa.Column("to_state", sa.Text(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("transition_count", sa.Integer(), nullable=True),
        sa.Column("n_state_observations", sa.Integer(), nullable=True),
        sa.Column("computed_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint(
            "regime_source", "window_type", "window_end_date", "from_state", "to_state"
        ),
    )
    op.create_index("idx_macro_trans_probs_source_date",
                    "cmc_macro_transition_probs",
                    ["regime_source", "window_type", sa.text("window_end_date DESC")])
```

### Python Wrapper for Transition Matrix Query

```python
# Source: informed by CONTEXT.md decision: "Python wrapper function for programmatic access"

from sqlalchemy import Engine, text

def get_transition_probability(
    engine: Engine,
    from_state: str,
    to_state: str,
    regime_source: str = "rule_based",  # 'rule_based' | 'hmm'
    window_type: str = "static",        # 'static' | 'rolling'
    window_end_date: str | None = None, # required for rolling; None for static
) -> float | None:
    """
    Query the transition probability from from_state to to_state.

    Returns probability (0.0-1.0) or None if not found.
    """
    if window_type == "rolling" and window_end_date is None:
        raise ValueError("window_end_date required for rolling window queries")

    query = """
        SELECT probability
        FROM cmc_macro_transition_probs
        WHERE regime_source = :regime_source
          AND window_type = :window_type
          AND from_state = :from_state
          AND to_state = :to_state
    """
    params: dict = {
        "regime_source": regime_source,
        "window_type": window_type,
        "from_state": from_state,
        "to_state": to_state,
    }
    if window_type == "rolling":
        query += " AND window_end_date = :wed"
        params["wed"] = window_end_date
    else:
        query += " AND window_end_date IS NULL"

    with engine.connect() as conn:
        result = conn.execute(text(query), params).scalar()
    return float(result) if result is not None else None
```

---

## DB Schema Summary

### `cmc_hmm_regimes`
```sql
-- PK: (date, n_states, model_run_date)
date             DATE NOT NULL
n_states         INTEGER NOT NULL        -- 2 or 3
hmm_state        INTEGER                 -- 0-based HMM state index
model_run_date   DATE NOT NULL           -- expanding window run date
bic              FLOAT                   -- BIC for this n_states model
aic              FLOAT                   -- AIC for this n_states model
is_winner        BOOLEAN DEFAULT FALSE   -- TRUE for lowest-BIC n_states
state_means_json TEXT                    -- JSON: model.means_.tolist()
n_train_rows     INTEGER                 -- training set size at model_run_date
ingested_at      TIMESTAMPTZ DEFAULT now()
```

### `cmc_macro_lead_lag_results`
```sql
-- PK: (macro_feature, asset_col, computed_at)
macro_feature    TEXT NOT NULL           -- e.g. 'net_liquidity', 'vixcls'
asset_col        TEXT NOT NULL           -- e.g. 'ret_btc', 'ret_eth'
asset_id         INTEGER                 -- e.g. 1 (BTC), 2 (ETH)
best_lag         INTEGER                 -- lag in days at max |corr|
best_corr        FLOAT                   -- Pearson r at best_lag
is_significant   BOOLEAN                 -- |best_corr| > 2/sqrt(n_obs)
n_obs            INTEGER                 -- aligned observations used
lag_range_min    INTEGER DEFAULT -60
lag_range_max    INTEGER DEFAULT 60
corr_at_lag_0    FLOAT                   -- contemporaneous correlation
bartlett_threshold FLOAT                 -- 2/sqrt(n_obs) used for flag
lag_convention   TEXT DEFAULT 'negative_means_macro_leads'
computed_at      DATE NOT NULL           -- date of analysis run
ingested_at      TIMESTAMPTZ DEFAULT now()
```

### `cmc_macro_transition_probs`
```sql
-- PK: (regime_source, window_type, window_end_date, from_state, to_state)
regime_source    TEXT NOT NULL           -- 'rule_based' | 'hmm'
window_type      TEXT NOT NULL           -- 'static' | 'rolling'
window_days      INTEGER                 -- NULL for static; 252 for rolling
window_end_date  DATE                    -- NULL for static; end of rolling window
from_state       TEXT NOT NULL           -- state label or HMM state int as TEXT
to_state         TEXT NOT NULL
probability      FLOAT                   -- row-normalized; NULL if from_state never seen
transition_count INTEGER                 -- raw count of (from->to) transitions
n_state_observations INTEGER            -- total observations in from_state
computed_at      TIMESTAMPTZ DEFAULT now()
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `sklearn.hmm.GaussianHMM` (removed ~2014) | `hmmlearn.hmm.GaussianHMM` | hmmlearn was extracted from scikit-learn; current stable is 0.3.3 |
| Manual BIC formula | `model.bic(X)` direct method | hmmlearn 0.3+ added bic/aic as first-class methods |
| Single random init | Multiple restarts (10), keep best score | Official docs recommend multiple restarts to avoid local optima |
| Fixed window refit | Expanding window | No look-ahead bias, maximizes training data |

**Deprecated/outdated:**
- `sklearn.hmm` module: removed in scikit-learn 0.22; anyone referencing it in training data is using 10-year-old documentation
- `hmmlearn 0.2.x`: missing `bic()` and `aic()` methods; must use 0.3.x

---

## Open Questions

1. **Phase 67 migration and table names**
   - What we know: Phase 67 migration (`cmc_macro_regimes`, `cmc_macro_hysteresis_state`) is planned but not yet applied to the DB. The current Alembic head is `c4d5e6f7a8b9`.
   - What's unclear: Whether Phase 67 executes before Phase 68 in the work sequence. If not, Phase 68 migration cannot reference `cmc_macro_regimes`.
   - Recommendation: Phase 68 Wave 1 (migration) must run `alembic heads` and chain from the actual head at execution time. If Phase 67 is not yet applied, Phase 68 migration creates its tables independently. The foreign key from `cmc_macro_transition_probs` to `cmc_macro_regimes` should be deferred or omitted (no FK constraint needed -- queried by join at runtime).

2. **HMM refit cadence for production (daily is expensive)**
   - What we know: Daily refit of an expanding window with 10 restarts x 2 n_states x N features can take 30-120 seconds per run depending on N and training size.
   - What's unclear: Whether 600-second timeout is sufficient as data grows (years of daily macro data = 5000+ rows).
   - Recommendation: Implement `--force-refit` flag for full refit; daily mode refits only when `MAX(model_run_date)` is more than 7 days old (weekly refit cadence). Update `TIMEOUT_MACRO_ANALYTICS = 600` to `900` (15 minutes) for safety.

3. **HMM input column selection strategy (all 38 float columns vs subset)**
   - What we know: CONTEXT.md says "let the model see everything." All 38 numeric float columns are available.
   - What's unclear: GaussianHMM with `covariance_type="full"` and 38 features needs to estimate a 38x38 covariance matrix per state. With n_states=3 and n_train=2000 rows, this is ~2220 parameters vs 2000 observations -- the model may be underdetermined.
   - Recommendation: Start with a subset of ~15 most interpretable features (net_liquidity, vixcls, dff, hy_oas_level, t10y2y, dexjpus_level, m2_yoy_pct, nfci_level, us_jp_rate_spread, dtwexbgs, dgs10, net_liquidity_365d_zscore, hy_oas_30d_zscore, dexjpus_daily_zscore, cpi_surprise_proxy). If underdetermined, use `covariance_type="diag"` instead of `"full"` (diagonal covariance -- far fewer parameters). Make `covariance_type` and `feature_set` configurable.

4. **Asset columns for lead-lag (which returns to use)**
   - What we know: `cmc_price_bars_multi_tf` has daily bars. BTC is id=1, ETH is id=2. Returns are close-to-close percentage changes.
   - What's unclear: Whether Phase 67/68 scripts have direct access to `cmc_price_bars_multi_tf` or if they should use `cmc_returns_bars_multi_tf`. Also, which timeframe (tf='1D' or tf='1d')?
   - Recommendation: Load daily returns from `cmc_returns_bars_multi_tf` (precomputed returns table) for BTC (id=1) and ETH (id=2) at tf='1D'. The macro features are daily; matching 1D returns avoids frequency mismatch. Use `ret_1_pct` column from that table (deprecated warning: check actual column name in `cmc_returns_bars_multi_tf`).

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/regimes/comovement.py` lines 109-144 -- `lead_lag_max_corr()` exact implementation, shift convention
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` -- `get_compute_window()`, `upsert_macro_features()`, `_to_python()`, `_sanitize_dataframe()`, `WARMUP_DAYS=60` constant
- `src/ta_lab2/scripts/run_daily_refresh.py` -- `run_macro_features()` pattern (lines 1629-1738), `TIMEOUT_MACRO=300`
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` (revision `b3c4d5e6f7a8`) -- confirmed Phase 65 float column list
- `alembic/versions/c4d5e6f7a8b9_fred_phase66_derived_columns.py` (revision `c4d5e6f7a8b9`) -- confirmed Phase 66 float column list; confirmed `net_liquidity_365d_zscore` (NOT 30d); confirmed Alembic head
- `src/ta_lab2/backtests/splitters.py` -- `expanding_walk_forward()` pattern
- `src/ta_lab2/analysis/regime_eval.py` -- `regime_transition_pnl()` transition counting pattern
- `pyproject.toml` -- confirmed hmmlearn NOT in deps; scikit-learn 1.8.0 and scipy 1.17.0 installed; import-linter layer contracts
- `pip show scikit-learn scipy` -- confirmed sklearn 1.8.0, scipy 1.17.0 installed
- `python -c "from sklearn.metrics import cohen_kappa_score"` -- confirmed available
- `python -m alembic heads` -- confirmed current head = `c4d5e6f7a8b9`
- [hmmlearn 0.3.3 API Reference](https://hmmlearn.readthedocs.io/en/latest/api.html) -- GaussianHMM constructor, fit(), predict(), score(), bic(), aic(), transmat_ (confirmed via WebFetch)
- [hmmlearn Model Selection Example](https://hmmlearn.readthedocs.io/en/latest/auto_examples/plot_gaussian_model_selection.html) -- multi-restart fitting pattern, BIC/AIC comparison (confirmed via WebFetch)

### Secondary (MEDIUM confidence)
- `.planning/phases/67-macro-regime-classifier/67-RESEARCH.md` -- confirms codebase patterns but contains one error: references `net_liquidity_30d_zscore` which does not exist (Phase 66 migration confirmed `net_liquidity_365d_zscore`)
- `.planning/phases/66-fred-derived-features-automation/66-RESEARCH.md` -- Phase 66 computation logic code examples (cross-referenced with actual migration file)

### Tertiary (LOW confidence)
- WebSearch: hmmlearn NaN handling -- confirmed NaN in input causes silent model failure (unverified beyond GitHub issues)
- WebSearch: 252-day rolling window for transition matrices -- literature suggests 1-year windows for macro data; no authoritative source found

---

## Metadata

**Confidence breakdown:**
- Standard stack (libraries): HIGH -- hmmlearn pip install verified, sklearn confirmed installed, all helpers confirmed in codebase
- HMM API (fit, bic, aic, transmat_): HIGH -- verified against official hmmlearn docs via WebFetch
- Column names (fred_macro_features): HIGH -- verified from actual Alembic migration files (not plan docs)
- Architecture patterns: HIGH -- directly modeled on confirmed existing patterns
- DB schema design (3 tables): HIGH -- schema columns derived from CONTEXT.md requirements
- Lead-lag convention: HIGH -- read directly from `lead_lag_max_corr()` source (lines 109-144)
- Rolling window size (252 days): MEDIUM -- common financial convention, no authoritative macro-specific source found
- HMM feature subset recommendation: MEDIUM -- based on parameter-count reasoning, not empirical validation

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (hmmlearn 0.3.3 is stable; macro infrastructure assumptions valid until Phase 67 executes and may change Alembic head)
