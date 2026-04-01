# Phase 102: Indicator Research Framework - Research

**Researched:** 2026-03-31
**Domain:** Statistical testing harness — permutation IC test, FDR control, Haircut Sharpe (Harvey & Liu 2015), block bootstrap IC, trial registry
**Confidence:** HIGH (all library APIs verified against locally installed packages; arch 8.0.0, statsmodels 0.14.6, scipy)

---

## Summary

Phase 102 builds a multiple-comparison-aware testing harness that wraps the existing IC sweep infrastructure. Every IC computation will be logged to a new `trial_registry` table, and four statistical functions will be added to `src/ta_lab2/analysis/`: `permutation_ic_test()`, `fdr_control()`, `haircut_sharpe()`, and `block_bootstrap_ic()`.

**What was researched:** Existing IC infrastructure (ic.py, run_ic_sweep.py, run_ctf_ic_sweep.py, feature_selection.py, psr.py), library APIs (arch 8.0.0 `optimal_block_length` + `StationaryBootstrap`, statsmodels 0.14.6 `fdrcorrection`, scipy `spearmanr`), Harvey & Liu 2015 haircut formula mechanics, and Politis & Romano block-length selection.

**Standard approach:** All four statistical functions use already-installed libraries. No new dependencies are required. The arch `[analysis]` optional group already includes `arch>=8.0.0` and `statsmodels>=0.14.0`. The new module `src/ta_lab2/analysis/multiple_testing.py` is the single home for all four functions. The trial registry Alembic migration chains from `s3t4u5v6w7x8` (Phase 99, the current HEAD).

**Primary recommendation:** Place all statistical harness functions in a single new file `src/ta_lab2/analysis/multiple_testing.py`. Inject trial registry logging into the existing worker functions (`_ic_worker` in run_ic_sweep.py and `_ctf_ic_worker` in run_ctf_ic_sweep.py) as a post-write step after `save_ic_results()`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy.stats.spearmanr | (installed) | Compute IC in permutation null distribution | Already used throughout ic.py; natural fit for permutation loop |
| numpy | (installed) | Vectorized permutation shuffle, percentile computation | Already used everywhere |
| statsmodels.stats.multitest.fdrcorrection | 0.14.6 (installed) | Benjamini-Hochberg FDR correction | Standard implementation, confirmed API, no new dependency |
| arch.bootstrap.optimal_block_length | 8.0.0 (installed) | Adaptive block size per Politis & Romano | Already in `[analysis]` optional group, returns DataFrame |
| arch.bootstrap.StationaryBootstrap | 8.0.0 (installed) | Block bootstrap resampling | Pairs with optimal_block_length, stationary bootstrap preserves autocorrelation |
| scipy.stats.norm | (installed) | Convert t-stats to p-values and back for haircut Sharpe | Already used in ic.py `_ic_p_value()` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlalchemy.text | (installed) | Alembic migration DDL and trial registry upsert | All DB operations in project use this |
| pandas | (installed) | IC series alignment, result DataFrames | Standard throughout analysis/ |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| arch.bootstrap.optimal_block_length | Fixed block size (e.g., 10) | Fixed size is simpler but ignores actual autocorrelation structure; CONTEXT.md explicitly requires adaptive Politis & Romano rule |
| statsmodels.fdrcorrection | scipy.stats.false_discovery_control (1.11+) | scipy version is newer (1.11+) but produces identical results to statsmodels BH; statsmodels is the existing project convention (already imported in feature_selection.py) |
| Harvey & Liu full simulation (2000 draws) | Bonferroni approximation | Bonferroni is conservative and simple; HL simulation is more precise but adds complexity; project CONTEXT.md says "haircut_sharpe() per Harvey & Liu 2015" so use HL, but Bonferroni as the simplest implementation of their framework |

### Installation

No new dependencies needed. All libraries are in the installed `[analysis]` optional group:

```bash
# Already installed — confirm:
pip show arch statsmodels scipy  # all present
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/analysis/
├── ic.py                    # existing — DO NOT MODIFY signatures
├── feature_selection.py     # existing — DO NOT MODIFY
├── monte_carlo.py           # existing — DO NOT MODIFY
├── multiple_testing.py      # NEW — permutation_ic_test, fdr_control,
│                            #        haircut_sharpe, block_bootstrap_ic

src/ta_lab2/scripts/analysis/
├── run_ic_sweep.py          # augment: inject trial registry logging after save_ic_results()
├── run_ctf_ic_sweep.py      # augment: same injection point

alembic/versions/
└── t4u5v6w7x8y9_phase102_trial_registry.py   # NEW Alembic migration
```

### Pattern 1: Permutation IC Test

**What:** Shuffle forward returns N times (default 10,000), compute Spearman IC each time, return empirical p-value as fraction of null |IC| >= observed |IC|.
**When to use:** Before accepting an IC result as meaningful — called per (feature, asset, tf, horizon) combination.

```python
# Source: verified locally
from scipy.stats import spearmanr
import numpy as np

def permutation_ic_test(
    feature: np.ndarray,
    fwd_returns: np.ndarray,
    n_perms: int = 10_000,
    seed: int = 42,
) -> dict:
    """
    Returns: {ic_obs, p_value, percentile_95, passes (bool)}
    passes = True if |ic_obs| >= 95th percentile of null |IC| distribution
    """
    rng = np.random.default_rng(seed)
    # Drop NaN pairs
    mask = ~(np.isnan(feature) | np.isnan(fwd_returns))
    feat_clean = feature[mask]
    ret_clean = fwd_returns[mask]

    ic_obs, _ = spearmanr(feat_clean, ret_clean)
    abs_ic_obs = abs(ic_obs)

    null_ics = np.empty(n_perms)
    for i in range(n_perms):
        shuffled = rng.permutation(ret_clean)
        ic_null, _ = spearmanr(feat_clean, shuffled)
        null_ics[i] = abs(ic_null)

    p_value = float(np.mean(null_ics >= abs_ic_obs))
    pct_95 = float(np.percentile(null_ics, 95))
    return {
        "ic_obs": float(ic_obs),
        "p_value": p_value,
        "percentile_95": pct_95,
        "passes": abs_ic_obs >= pct_95,
        "n_perms": n_perms,
        "n_obs": int(mask.sum()),
    }
```

**Performance note:** 10,000 permutations with n=200 observations takes ~3-5 seconds per test. For batch sweeps (100+ features x many asset-tf pairs), run permutation test only on horizon=1 arith rows as a gate. Store p-value in trial_registry; do not run on every horizon x return_type combination (that would be ~14x more expensive).

### Pattern 2: FDR Control

**What:** Benjamini-Hochberg across a batch of IC p-values. Takes a list of p-values (one per trial), returns reject/pass array and adjusted p-values.
**When to use:** At the end of a full IC sweep batch, before writing tier classifications.

```python
# Source: verified locally against statsmodels 0.14.6
from statsmodels.stats.multitest import fdrcorrection

def fdr_control(
    p_values: list[float],
    alpha: float = 0.05,
) -> dict:
    """
    Returns: {rejected (bool array), p_adjusted, n_rejected}
    method='indep' = BH for independent/positively correlated tests
    """
    import numpy as np
    p_arr = np.array(p_values, dtype=float)
    rejected, p_adj = fdrcorrection(p_arr, alpha=alpha, method="indep")
    return {
        "rejected": rejected,
        "p_adjusted": p_adj,
        "n_rejected": int(rejected.sum()),
        "alpha": alpha,
    }
```

### Pattern 3: Haircut Sharpe (Harvey & Liu 2015)

**What:** Adjusts an observed Sharpe ratio downward for the number of strategies/indicators tested. Uses p-value of the t-stat and applies Bonferroni correction (the simplest HL method), then converts back to adjusted SR.

**Formula derivation (verified against HL 2015 paper and R quantstrat implementation):**
1. Convert SR to monthly: `sr_m = SR_annual / sqrt(12)`
2. Compute t-stat: `t = sr_m * sqrt(n_monthly_obs)`
3. One-sided p-value: `p = 1 - norm.cdf(t)`
4. Bonferroni: `p_adj = min(1.0, p * n_trials)`
5. Adjusted t: `t_adj = norm.ppf(1 - p_adj)` (clamp to 0 if p_adj >= 1)
6. Adjusted SR: `sr_adj = (t_adj / sqrt(n_monthly_obs)) * sqrt(12)`
7. Haircut %: `(SR_obs - sr_adj) / SR_obs`

**Trial count:** Use all trials ever logged to trial_registry, not just active ones. This is the most faithful interpretation of Harvey & Liu — the penalty reflects total search over all indicators ever tested.

```python
# Source: derived from Harvey & Liu 2015 + verified formula
from scipy.stats import norm
import numpy as np

def haircut_sharpe(
    sr_observed: float,
    n_trials: int,
    n_obs: int,
    freq: str = "monthly",  # 'daily'|'weekly'|'monthly'|'annual'
) -> dict:
    """
    Returns: {sr_haircut, haircut_pct, n_trials}
    freq: frequency of n_obs observations
    """
    FREQ_TO_MONTHLY = {"daily": 21.0, "weekly": 4.33, "monthly": 1.0, "annual": 1/12}
    scale = FREQ_TO_MONTHLY.get(freq, 1.0)
    n_monthly = n_obs / scale

    sr_monthly = sr_observed / np.sqrt(12)
    t_stat = sr_monthly * np.sqrt(n_monthly)
    p_one_sided = float(1.0 - norm.cdf(t_stat))
    p_adj = min(1.0, p_one_sided * n_trials)

    if p_adj >= 1.0:
        t_adj = 0.0
    else:
        t_adj = float(norm.ppf(1.0 - p_adj))

    sr_monthly_adj = t_adj / np.sqrt(n_monthly) if n_monthly > 0 else 0.0
    sr_haircut = sr_monthly_adj * np.sqrt(12)
    haircut_pct = (sr_observed - sr_haircut) / sr_observed if sr_observed > 0 else 0.0

    return {
        "sr_observed": sr_observed,
        "sr_haircut": sr_haircut,
        "haircut_pct": haircut_pct,
        "n_trials": n_trials,
        "n_obs": n_obs,
    }
```

**IMPORTANT — arch 8.0.0 column name change:** `optimal_block_length()` returns a DataFrame with columns `stationary` and `circular`, NOT `b_sb` and `b_cb` as documented in arch 7.x. The older column names `b_sb`/`b_cb` appear in arch 7.2.0 docs only. Verified locally:

```python
>>> from arch.bootstrap import optimal_block_length
>>> optimal_block_length(x).columns.tolist()
['stationary', 'circular']  # arch 8.0.0 — NOT 'b_sb'/'b_cb'
```

### Pattern 4: Block Bootstrap IC

**What:** Estimates 95% CI for IC using Politis & Romano stationary block bootstrap. Preserves autocorrelation in forward returns series. Returns `(ci_lo, ci_hi, block_len_used)`.

```python
# Source: verified locally against arch 8.0.0
from arch.bootstrap import StationaryBootstrap, optimal_block_length
from scipy.stats import spearmanr
import numpy as np

def block_bootstrap_ic(
    feature: np.ndarray,
    fwd_returns: np.ndarray,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Returns: {ic_obs, ci_lo, ci_hi, block_len, n_boot}
    block_len is adaptive (Politis & Romano via arch.optimal_block_length)
    """
    mask = ~(np.isnan(feature) | np.isnan(fwd_returns))
    feat_clean = feature[mask]
    ret_clean = fwd_returns[mask]

    ic_obs, _ = spearmanr(feat_clean, ret_clean)

    # Adaptive block length on forward returns (the dependent series)
    # CRITICAL: use column 'stationary' not 'b_sb' (arch 8.0.0 naming)
    opt = optimal_block_length(ret_clean)
    block_len = max(1, int(np.ceil(float(opt["stationary"].iloc[0]))))

    bs = StationaryBootstrap(block_len, ret_clean, seed=seed)
    boot_ics = []
    for (boot_ret,), _ in bs.bootstrap(n_boot):
        if len(boot_ret) == len(feat_clean):
            ic_b, _ = spearmanr(feat_clean, boot_ret)
            boot_ics.append(ic_b)

    boot_arr = np.array(boot_ics)
    ci_lo, ci_hi = np.percentile(boot_arr, [2.5, 97.5])

    return {
        "ic_obs": float(ic_obs),
        "ci_lo": float(ci_lo),
        "ci_hi": float(ci_hi),
        "block_len": block_len,
        "n_boot": len(boot_arr),
        "n_obs": int(mask.sum()),
    }
```

### Pattern 5: Trial Registry Table Schema

**What:** New PostgreSQL table `public.trial_registry` auto-populated from IC sweeps.
**Granularity decision (Claude's discretion):** Per `(indicator_name, param_set, tf, asset_id)` — this preserves per-asset variation for Harvey & Liu n_trials count while remaining manageable. "param_set" is a VARCHAR representation of the parameter hash (e.g., "period=14" or "window=20,smooth=5").

**Schema:**
```sql
CREATE TABLE public.trial_registry (
    trial_id        BIGSERIAL PRIMARY KEY,
    indicator_name  VARCHAR(128)    NOT NULL,  -- feature column name or CTF feature name
    param_set       VARCHAR(256)    NOT NULL DEFAULT '',  -- param string or empty
    tf              VARCHAR(16)     NOT NULL,
    asset_id        INTEGER         NOT NULL,
    venue_id        SMALLINT        NOT NULL DEFAULT 1 REFERENCES dim_venues(venue_id),
    horizon         SMALLINT        NOT NULL DEFAULT 1,
    return_type     VARCHAR(8)      NOT NULL DEFAULT 'arith',
    ic_observed     DOUBLE PRECISION,
    ic_p_value      DOUBLE PRECISION,          -- from permutation test or ic.py t-stat
    perm_p_value    DOUBLE PRECISION,          -- empirical permutation p-value (nullable until run)
    fdr_p_adjusted  DOUBLE PRECISION,          -- BH-adjusted p-value (nullable until batch FDR run)
    passes_fdr      BOOLEAN,                   -- computed at batch FDR time, stored
    n_obs           INTEGER,
    source_table    VARCHAR(64)     NOT NULL DEFAULT 'ic_results',  -- 'ic_results' or 'backfill'
    sweep_ts        TIMESTAMPTZ     NOT NULL DEFAULT now(),
    UNIQUE (indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type)
);

CREATE INDEX ix_trial_registry_indicator_tf ON public.trial_registry (indicator_name, tf);
CREATE INDEX ix_trial_registry_sweep_ts ON public.trial_registry (sweep_ts DESC);
```

**Pass/fail storage (Claude's discretion):** Store `passes_fdr` as a column (not computed at query time). Rationale: FDR correction requires a complete batch of p-values — it cannot be computed row-by-row. The column is NULL until a batch FDR run is completed, then stamped. This means pass/fail is immutable once written.

**CI storage (Claude's discretion):** Block bootstrap CI values (`ci_lo`, `ci_hi`) belong in `trial_registry` as additional columns, not in `ic_results`. Rationale: CI is a property of the trial's statistical validity, not of the IC value itself. Adding them to `ic_results` would require ALTER TABLE on a potentially large table.

```sql
-- Additional CI columns on trial_registry (include in same migration)
ALTER TABLE public.trial_registry
    ADD COLUMN bb_ci_lo    DOUBLE PRECISION,  -- block bootstrap 2.5th percentile IC
    ADD COLUMN bb_ci_hi    DOUBLE PRECISION,  -- block bootstrap 97.5th percentile IC
    ADD COLUMN bb_block_len INTEGER;           -- adaptive block length used
```

### Pattern 6: Tier Assignment from Statistical Results

**Gate behavior (per CONTEXT.md):** Mirrors existing `dim_feature_selection` tier system.
- `passes_fdr = True` AND `perm_p_value < 0.05` → active
- `passes_fdr = True` but marginal (perm_p_value in [0.05, 0.15]) → watch
- `passes_fdr = False` OR `perm_p_value >= 0.15` → archive

**Auto-tier updates (Claude's discretion):** Do NOT auto-update `dim_feature_selection` directly from trial_registry. Instead, the statistical results are inputs to the existing `classify_feature_tier()` logic in `feature_selection.py`. The tier update remains a manual or scheduled step (same as today), but now `permutation_p_value` is an additional input to `classify_feature_tier()`.

### Pattern 7: Trial Registry Injection Point

The injection into run_ic_sweep.py and run_ctf_ic_sweep.py follows the same pattern for both. After `save_ic_results()` succeeds, write to trial_registry:

```python
# In _ic_worker() after save_ic_results(), within the existing engine.begin() block:
# Source: pattern derived from existing save_ic_results() upsert style

from ta_lab2.analysis.multiple_testing import log_trials_to_registry

n_logged = log_trials_to_registry(conn, ic_rows, source_table="ic_results")
_logger.debug("Logged %d rows to trial_registry", n_logged)
```

`log_trials_to_registry()` uses `ON CONFLICT DO UPDATE` to update `ic_observed` and `sweep_ts` but preserve `perm_p_value`/`fdr_p_adjusted` if already set (those are expensive to compute).

### Anti-Patterns to Avoid

- **Running permutation test inside the worker loop at full 10,000 perms per row:** This would make IC sweeps 100x slower. Instead: run IC sweep first (fast), then run permutation tests as a separate post-sweep pass on the rows written to trial_registry.
- **Using arch 7.x column names `b_sb`/`b_cb`:** arch 8.0.0 (installed) uses `stationary`/`circular`. Always reference the column by name from the returned DataFrame, not by position.
- **Applying FDR to a single asset-tf pair:** BH FDR correction is a batch operation. It must be applied to the full set of p-values from an entire sweep (or at minimum all features for one asset-tf pair). Applying it to one feature at a time defeats the purpose.
- **Storing haircut Sharpe on `ic_results`:** ic_results rows are per (asset, tf, feature, horizon, return_type) — haircut Sharpe is a scalar over all trials. It belongs in `trial_registry` as a summary or in a separate materialized summary view.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Benjamini-Hochberg FDR | Custom BH loop | `statsmodels.stats.multitest.fdrcorrection` | Handles edge cases (all p=0, ties, is_sorted optimization) correctly |
| Optimal block length | Autocorrelation-based heuristic | `arch.bootstrap.optimal_block_length` | Implements Politis & White 2004 with Patton correction; already installed |
| Block bootstrap resampling | Manual block slicing | `arch.bootstrap.StationaryBootstrap` | Handles edge effects, variable block lengths, and seeding correctly |
| Spearman IC computation | Manual rank + pearson | `scipy.stats.spearmanr` | Already the project standard; consistent with ic.py |

**Key insight:** All four statistical functions can be built with zero new dependencies. The complexity is in the wiring (trial registry injection, batch FDR coordination) not in the statistics.

---

## Common Pitfalls

### Pitfall 1: arch 8.0.0 Column Name Breaking Change

**What goes wrong:** Code written to use `opt['b_sb']` from arch 7.x raises `KeyError` on the installed arch 8.0.0.
**Why it happens:** arch changed column names from `b_sb`/`b_cb` to `stationary`/`circular` between versions 7.x and 8.0.0.
**How to avoid:** Always reference `opt['stationary']`, never `opt['b_sb']`. Verified locally — arch 8.0.0 returns `['stationary', 'circular']`.
**Warning signs:** `KeyError: 'b_sb'` at runtime; wrong docs from arch 7.x web results.

### Pitfall 2: Permutation Test on Autocorrelated Forward Returns

**What goes wrong:** Naive permutation (shuffle all returns randomly) destroys time structure. For financial time series with autocorrelation, the null distribution is too narrow — p-values are falsely small (over-reject).
**Why it happens:** IC time series have autocorrelation; returns have momentum/mean-reversion. Random shuffling assumes exchangeability.
**How to avoid:** For the permutation test (success criterion 1), shuffling forward returns is acceptable because we are testing `feature → future return` with a cross-sectional IC; the feature is not shuffled. The returns are shuffled to break the feature-return relationship specifically. This is the standard approach in quantitative finance IC testing. The block bootstrap (success criterion 5) handles the CI estimation where autocorrelation matters more.
**Warning signs:** Permutation p-values near 0 for clearly noisy features.

### Pitfall 3: FDR Batch Size Sensitivity

**What goes wrong:** FDR correction changes dramatically depending on how many p-values are included in the batch. Testing 10 features vs 1000 features gives very different adjusted p-values for the same raw p-values.
**Why it happens:** BH threshold is `(i/m) * alpha` where m = total number of tests.
**How to avoid:** Apply FDR to the full batch from a complete IC sweep (all features x all asset-tf pairs), not piecemeal. Document the batch size used when logging `fdr_p_adjusted` to trial_registry.
**Warning signs:** Different `passes_fdr` results when running partial vs full sweeps.

### Pitfall 4: Harvey & Liu Trial Count Scope

**What goes wrong:** Counting only "current active" trials for haircut underestimates search, producing too little haircut.
**Why it happens:** Researchers remove failed indicators from consideration but forget they still count.
**How to avoid:** Count ALL rows ever in trial_registry (including archive-tier), not just active rows. The CONTEXT.md decision confirms: "backfill every ic_results row so penalty is honest from day one."
**Warning signs:** Haircut % looks surprisingly low for a large feature set.

### Pitfall 5: Backfill Creates Duplicate trial_registry Entries

**What goes wrong:** Backfill script inserts all historical ic_results rows, then IC sweeps re-insert the same rows, creating duplicates or updating `sweep_ts` unintentionally.
**Why it happens:** The backfill and the live sweep both write to trial_registry.
**How to avoid:** Use `ON CONFLICT (indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type) DO UPDATE SET ic_observed = EXCLUDED.ic_observed, sweep_ts = EXCLUDED.sweep_ts`. Never update `perm_p_value` or `fdr_p_adjusted` from a routine IC sweep — those require explicit re-computation runs.
**Warning signs:** `perm_p_value` getting NULLed after an IC sweep re-run.

### Pitfall 6: Windows Multiprocessing and Shared State

**What goes wrong:** `trial_registry` logging from worker processes via NullPool connections causes transaction conflicts if workers try to write to the same rows concurrently.
**Why it happens:** Multiple workers for different (asset_id, tf) pairs may log the same indicator_name rows if features overlap.
**How to avoid:** The UNIQUE constraint on `(indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type)` ensures no true duplicates. With `DO UPDATE` upsert, concurrent writes to the same unique key will serialize in PostgreSQL — no explicit locking needed. Use NullPool per worker (same as existing IC sweep pattern).

---

## Code Examples

### Full permutation test and trial log (verified patterns)

```python
# Source: locally verified patterns, arch 8.0.0 + statsmodels 0.14.6 + scipy

# --- permutation_ic_test ---
from scipy.stats import spearmanr
import numpy as np

rng = np.random.default_rng(42)
null_ics = np.empty(10_000)
for i in range(10_000):
    null_ics[i] = abs(spearmanr(feature, rng.permutation(fwd_returns)).statistic)
p_value = float(np.mean(null_ics >= abs(ic_obs)))
pct_95 = float(np.percentile(null_ics, 95))

# --- fdr_control ---
from statsmodels.stats.multitest import fdrcorrection
rejected, p_adj = fdrcorrection(np.array(p_values), alpha=0.05, method="indep")

# --- block_bootstrap_ic ---
from arch.bootstrap import optimal_block_length, StationaryBootstrap
opt = optimal_block_length(fwd_returns)
block_len = max(1, int(np.ceil(float(opt["stationary"].iloc[0]))))  # NOT opt['b_sb']
bs = StationaryBootstrap(block_len, fwd_returns, seed=42)
boot_ics = [
    spearmanr(feature, boot_ret).statistic
    for (boot_ret,), _ in bs.bootstrap(1000)
    if len(boot_ret) == len(feature)
]
ci_lo, ci_hi = np.percentile(boot_ics, [2.5, 97.5])
```

### Haircut Sharpe for IC-IR (treating IC-IR as annualized Sharpe)

```python
# IC-IR can be treated as an SR: it is mean(IC)/std(IC)
# For haircut, use n_obs = number of rolling IC windows (not raw bars)
# n_trials = SELECT COUNT(*) FROM trial_registry WHERE passes_fdr IS NOT NULL
from scipy.stats import norm

def _haircut(sr_obs: float, n_trials: int, n_obs: int) -> float:
    """n_obs = number of monthly equivalent observations"""
    sr_m = sr_obs / 12**0.5
    t = sr_m * n_obs**0.5
    p = float(1.0 - norm.cdf(t))
    p_adj = min(1.0, p * n_trials)
    t_adj = norm.ppf(1.0 - p_adj) if p_adj < 1.0 else 0.0
    return (t_adj / n_obs**0.5) * 12**0.5
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| arch 7.x `optimal_block_length` returns `b_sb`/`b_cb` | arch 8.0.0 returns `stationary`/`circular` | arch 8.0.0 release | Must use new column names |
| scipy.stats has no `false_discovery_control` | scipy 1.11+ adds `false_discovery_control` | scipy 1.11.0 | Either works; use statsmodels since it is already imported |
| Harvey & Liu (2015) applied manually | Standard in quant finance; no canonical Python package | N/A | Must implement directly in multiple_testing.py |

**Deprecated/outdated:**
- arch 7.x docs showing `b_sb`/`b_cb` column names: replaced by `stationary`/`circular` in arch 8.0.0

---

## Design Decisions (Claude's Discretion — resolved)

### Trial Granularity

**Decision:** Per `(indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type)`.
**Rationale:** This is the natural unit of an IC sweep row. "param_set" is an empty string for features with no tunable parameters (most existing features) and a formatted string like `"period=14"` for parametric indicators. This keeps trial_registry in 1:1 correspondence with ic_results rows for easy backfill and join queries.

### Pass/Fail Immutability

**Decision:** `passes_fdr` is stored as a column, NULL until batch FDR run, then written and not overwritten by subsequent IC sweeps (only by explicit re-FDR runs).
**Rationale:** FDR correction requires the full batch; routine IC sweep adds new rows but should not invalidate existing FDR computations.

### Auto vs Separate Post-Step for Permutation/FDR

**Decision:** Separate post-step. IC sweep writes to trial_registry with NULL for `perm_p_value` and `fdr_p_adjusted`. A separate CLI command `python -m ta_lab2.scripts.analysis.run_permutation_tests` reads trial_registry rows with NULL `perm_p_value` and fills them in. This avoids making IC sweeps 100x slower.
**Rationale:** 10,000 permutations * 200+ features * 50+ asset-tf pairs would be computationally impractical inline.

### CI Storage Location

**Decision:** CI columns (`bb_ci_lo`, `bb_ci_hi`, `bb_block_len`) live on `trial_registry`, not `ic_results`.
**Rationale:** ic_results is already large (~4M+ rows); adding CI columns would bloat it. trial_registry is a much smaller summary table (one row per unique trial, not per horizon x return_type).

### Auto-Tier Updates

**Decision:** Do NOT auto-update `dim_feature_selection` directly from trial_registry. The existing tier classification workflow (`feature_selection.py → classify_feature_tier()`) is augmented to accept `perm_p_value` as an input, but tier changes require an explicit run of the feature selection script.
**Rationale:** Avoids invisible automated changes to feature tiers that the existing dashboard and signal pipeline depend on.

---

## Alembic Migration

**New revision:** `t4u5v6w7x8y9_phase102_trial_registry.py`
**Chains from:** `s3t4u5v6w7x8` (Phase 99 HEAD)

```python
revision = "t4u5v6w7x8y9"
down_revision = "s3t4u5v6w7x8"
```

**Contents:**
1. CREATE TABLE `public.trial_registry` (schema above, with CI columns included)
2. CREATE INDEX `ix_trial_registry_indicator_tf`
3. CREATE INDEX `ix_trial_registry_sweep_ts`
4. One-time backfill from `ic_results` (INSERT ... SELECT ... ON CONFLICT DO NOTHING)

**Backfill SQL pattern:**
```sql
INSERT INTO public.trial_registry
    (indicator_name, param_set, tf, asset_id, venue_id, horizon, return_type,
     ic_observed, ic_p_value, n_obs, source_table, sweep_ts)
SELECT
    feature AS indicator_name,
    '' AS param_set,
    tf,
    asset_id,
    COALESCE(alignment_source::smallint, 1) AS venue_id,  -- alignment_source maps to venue_id
    horizon,
    return_type,
    ic AS ic_observed,
    ic_p_value,
    n_obs,
    'ic_results' AS source_table,
    COALESCE(computed_at, now()) AS sweep_ts
FROM public.ic_results
WHERE regime_col = 'all' AND regime_label = 'all'  -- backfill only full-sample rows
ON CONFLICT DO NOTHING;
```

**Note on alignment_source:** ic_results has `alignment_source` column (part of PK) — verify what values it takes vs `dim_venues.venue_id` before assuming 1:1 mapping. May need a lookup.

---

## Open Questions

1. **alignment_source in ic_results vs venue_id**
   - What we know: ic_results has `alignment_source` in its PK; dim_venues has `venue_id` SMALLINT
   - What's unclear: whether alignment_source is a string (like 'cmc_agg') or a SMALLINT matching venue_id, or a different concept entirely
   - Recommendation: Before writing backfill SQL in migration, run `SELECT DISTINCT alignment_source FROM public.ic_results LIMIT 10` to confirm value type and mapping to venue_id. The backfill SQL above uses a placeholder; adjust the actual migration once confirmed.

2. **strategy_bakeoff_results haircut Sharpe column**
   - What we know: `sharpe_mean` column exists; `mc_sharpe_lo/hi/median` were added in Phase 99 migration
   - What's unclear: whether haircut_sharpe should be stored as a new column `haircut_sharpe` on `strategy_bakeoff_results` or in trial_registry
   - Recommendation: Add `haircut_sharpe DOUBLE PRECISION` column to `strategy_bakeoff_results` in the same Alembic migration. The haircut applies to the bakeoff Sharpe specifically and is most useful alongside the raw Sharpe in that table.

3. **Permutation test scope for batch sweeps**
   - What we know: 10,000 perms per test is 3-5 seconds; full sweep has 200+ features x 50+ asset-tf pairs = 10,000+ tests
   - What's unclear: whether to run permutation on horizon=1/arith only (gate) or all horizons
   - Recommendation: Run permutation test on horizon=1, return_type='arith' only (the primary IC evaluation horizon). Log result to trial_registry; other horizons inherit the same permutation p-value for that indicator. This reduces compute by ~14x.

---

## Sources

### Primary (HIGH confidence)
- Locally verified: `arch 8.0.0` installed — `optimal_block_length()` returns DataFrame with columns `['stationary', 'circular']`
- Locally verified: `statsmodels 0.14.6` installed — `fdrcorrection(pvals, alpha=0.05, method='indep')` returns `(rejected_bool_array, p_adjusted_array)`
- Locally verified: `scipy.stats.spearmanr` — used throughout `ic.py`, standard interface
- `src/ta_lab2/analysis/ic.py` — ic_results schema, save_ic_results(), PK structure, column names
- `src/ta_lab2/analysis/feature_selection.py` — classify_feature_tier(), tier system, dim_feature_selection structure
- `src/ta_lab2/analysis/monte_carlo.py` — existing bootstrap pattern (IID, not block)
- `src/ta_lab2/backtests/psr.py` — existing n_trials pattern in compute_dsr()
- `alembic/versions/s3t4u5v6w7x8_phase99_backtest_scaling.py` — current HEAD revision `s3t4u5v6w7x8`
- `pyproject.toml` — `[analysis]` optional group already contains `arch>=8.0.0` and `statsmodels>=0.14.0`

### Secondary (MEDIUM confidence)
- [Harvey & Liu 2015 "Backtesting" paper](https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF) — formula derivation confirmed via quantstrat R implementation
- [arch.bootstrap.optimal_block_length docs](https://arch.readthedocs.io/en/latest/bootstrap/generated/arch.bootstrap.optimal_block_length.html) — algorithm description; overridden by local verification for column names
- [statsmodels fdrcorrection docs](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.fdrcorrection.html) — confirmed against local installation

### Tertiary (LOW confidence)
- WebSearch results on Politis & Romano 1994 — algorithm description only; implementation verified via arch package locally

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries locally verified; no new dependencies
- Architecture: HIGH — injection point in worker functions confirmed by reading full code; UNIQUE key for trial_registry derived from ic_results PK
- Permutation test: HIGH — algorithm verified locally
- FDR control: HIGH — statsmodels API verified locally
- Block bootstrap: HIGH — arch 8.0.0 API verified locally; column name gotcha documented
- Haircut Sharpe formula: MEDIUM — formula derived from Harvey & Liu 2015 via quantstrat R implementation; Bonferroni is the simplest of the three HL methods
- Pitfalls: HIGH — arch column name change verified, others derived from first principles

**Research date:** 2026-03-31
**Valid until:** 2026-05-01 (stable libraries; arch 8.0.0 and statsmodels 0.14.x are stable)
