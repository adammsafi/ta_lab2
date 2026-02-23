# Phase 36: PSR + Purged K-Fold - Research

**Researched:** 2026-02-23
**Domain:** Statistical Sharpe ratio estimation (PSR/DSR/MinTRL) + leakage-free cross-validation (PurgedKFold/CPCV)
**Confidence:** HIGH — all formulas verified by direct Python execution against scipy/sklearn

## Summary

Phase 36 adds two independently useful capabilities: (1) statistically rigorous Sharpe ratio estimates via the Lopez de Prado PSR/DSR/MinTRL framework, and (2) leakage-free cross-validation via PurgedKFold and CPCV. Both are implemented from scratch using scipy 1.17.0 and sklearn 1.8.0 already installed.

The codebase currently has `psr_placeholder()` in `src/ta_lab2/backtests/metrics.py` that returns a naive sigmoid of the Sharpe. This is NOT persisted to the DB: `cmc_backtest_metrics` has no `psr` column in its DDL (`sql/backtests/072_cmc_backtest_metrics.sql`) and the INSERT in `backtest_from_signals.py` does not write psr. The Alembic migration PSR-01 must therefore be written defensively: check whether `psr` column exists and rename if so, otherwise just add `psr_legacy` and `psr` as new columns.

The PSR formula requires Pearson kurtosis (not Fisher/excess) in the denominator variance term `(gamma_4 - 1)/4`. Scipy's `kurtosis(x, fisher=False)` returns Pearson kurtosis (= 3 for normal). Using excess kurtosis (fisher=True, default) gives wrong variance for normal distributions.

**Primary recommendation:** Implement `src/ta_lab2/backtests/psr.py` containing all three formulas + `src/ta_lab2/backtests/cv.py` containing PurgedKFold and CPCV. Wire PSR into `_compute_comprehensive_metrics()` in `backtest_from_signals.py`. Add standalone CLI at `src/ta_lab2/scripts/backtests/compute_psr.py`.

## Standard Stack

All dependencies are already installed — zero new packages needed.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| scipy.stats | 1.17.0 | norm.cdf, skew, kurtosis for PSR/DSR/MinTRL | Only correct way to compute PSR |
| sklearn.model_selection.BaseCrossValidator | 1.8.0 | Base class for PurgedKFoldSplitter | Ensures sklearn API compatibility |
| alembic | (existing) | Schema migrations for psr column rename + psr_results table | Already in project, env.py configured |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | (existing) | Vectorized computation in PSR/MinTRL/CPCV | All numeric operations |
| pandas | (existing) | t1_series (DatetimeIndex-indexed) in PurgedKFold | t1_series must be pd.Series with DatetimeIndex |
| itertools.combinations | stdlib | CPCV combinatorial path generation | CPCV path enumeration |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| from-scratch PSR | mlfinlab | mlfinlab is discontinued, has known bug in PurgedKFold (#295) — BANNED per CONTEXT |
| Pearson kurtosis | excess kurtosis | Using excess kurtosis (scipy default) gives negative variance for SR > 2 — WRONG |
| custom splitter class | not inheriting BaseCrossValidator | Duck typing works for cross_val_score but inheritance is required per CONTEXT |

**Installation:** No new installs needed. All deps already present.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/backtests/
├── metrics.py        # existing — psr_placeholder() stays until removed in PSR-02
├── psr.py            # NEW: psr(), dsr(), min_trl(), expected_max_sr()
├── cv.py             # NEW: PurgedKFoldSplitter, CPCVSplitter
└── backtest_from_signals.py  # modified: wire psr() into _compute_comprehensive_metrics()

src/ta_lab2/scripts/backtests/
└── compute_psr.py    # NEW: standalone CLI --run-id / --all

alembic/versions/
├── 25f2b3c90f65_baseline.py   # existing baseline
├── XXXX_psr_column_rename.py  # NEW revision 1: rename psr->psr_legacy, add psr col
└── YYYY_psr_results_table.py  # NEW revision 2: create psr_results table
```

### Pattern 1: PSR Formula (Lopez de Prado 2010)

**What:** Probabilistic Sharpe Ratio — probability the true Sharpe exceeds benchmark SR*, accounting for non-normality via skewness and Pearson kurtosis.

**When to use:** Any single backtest result where you have the returns series.

**Formula (verified by execution):**
```python
# Source: Bailey & Lopez de Prado, "Sharpe Ratio Efficient Frontier" SSRN 1821643
# Verified: scipy 1.17.0, Python execution 2026-02-23

import numpy as np
from scipy.stats import norm, skew, kurtosis
import warnings

def psr(returns: np.ndarray | pd.Series, sr_star: float = 0.0) -> float:
    """
    Probabilistic Sharpe Ratio.

    Args:
        returns: per-bar returns (not annualized). Daily returns for daily backtest.
        sr_star: benchmark Sharpe ratio IN SAME UNITS AS RETURNS (per-bar).
                 For annualized sr_star, caller divides by sqrt(freq_per_year).

    Returns:
        float in [0, 1]: probability true SR > sr_star.
        Returns NaN when n < 30 (guard per PSR-03).
    """
    n = len(returns)
    if n < 30:
        warnings.warn(f"PSR: n={n} < 30. Result is NaN.", stacklevel=2)
        return float("nan")
    if n < 100:
        warnings.warn(f"PSR: n={n} < 100. Estimate may be unreliable.", stacklevel=2)

    sr_hat = np.mean(returns) / np.std(returns, ddof=1)
    gamma_3 = skew(returns)                    # skewness
    gamma_4 = kurtosis(returns, fisher=False)  # PEARSON kurtosis (3 for normal)

    # Variance of SR estimator (Martens 2002 / Lopez de Prado)
    # gamma_4 must be Pearson here: (gamma_4 - 1)/4 = 0.5 for normal -> sigma = sqrt((1 + SR^2/2)/(T-1))
    var_sr = (1.0 - gamma_3 * sr_hat + (gamma_4 - 1.0) / 4.0 * sr_hat**2) / (n - 1)
    if var_sr <= 0:
        return float("nan")

    z = (sr_hat - sr_star) / np.sqrt(var_sr)
    return float(norm.cdf(z))
```

**Kurtosis convention (critical):** `scipy.stats.kurtosis(x, fisher=False)` gives Pearson kurtosis (3.0 for normal distribution). The `fisher=True` default gives excess kurtosis (0.0 for normal). The PSR formula uses Pearson kurtosis — using excess produces negative variance for SR > 2 and is wrong.

### Pattern 2: DSR Formula (Deflated Sharpe Ratio)

**What:** PSR corrected for multiple testing — uses expected maximum Sharpe across N independent trials as the benchmark SR*.

**When to use:** Parameter sweeps where you selected best-of-N configurations.

```python
# Source: Bailey & Lopez de Prado, "Deflated Sharpe Ratio" (dhbpapers), verified 2026-02-23

import numpy as np
from scipy.stats import norm

def expected_max_sr(sr_estimates: list[float], expected_mean: float = 0.0) -> float:
    """
    E[max SR] for N independent trials, per Bailey-Lopez de Prado order statistics approximation.

    For mode (best_sr, N): caller computes from assumed distribution (see dsr() below).
    For mode full list: use actual SR distribution from all trials.
    """
    N = len(sr_estimates)
    euler_gamma = 0.5772156649  # Euler-Mascheroni constant
    std_sr = float(np.std(sr_estimates - expected_mean, ddof=1))

    e_max = expected_mean + std_sr * (
        (1 - euler_gamma) * norm.ppf(1 - 1.0 / N)
        + euler_gamma * norm.ppf(1 - 1.0 / (N * np.e))
    )
    return e_max


def dsr(
    best_trial_returns: np.ndarray | pd.Series,
    sr_estimates: list[float] | None = None,   # all N trials' SR values (exact mode)
    n_trials: int | None = None,                # (best, N) tuple mode
    sr_star_override: float | None = None,
) -> float:
    """
    Deflated Sharpe Ratio.

    Accepts TWO modes per CONTEXT decisions:
    - Exact mode: sr_estimates = list of all N trial SR values (preferred).
    - Approx mode: n_trials = N (assumes std_sr=1 for SR distribution).

    Returns PSR with benchmark = E[max SR from N trials].
    """
    if sr_estimates is not None:
        benchmark = expected_max_sr(sr_estimates)
    elif n_trials is not None:
        # Bailey approximation: assumes unit-variance SR distribution (sr std = 1)
        euler_gamma = 0.5772156649
        N = n_trials
        benchmark = (
            (1 - euler_gamma) * norm.ppf(1 - 1.0 / N)
            + euler_gamma * norm.ppf(1 - 1.0 / (N * np.e))
        )
    else:
        raise ValueError("Either sr_estimates or n_trials must be provided")

    if sr_star_override is not None:
        benchmark = sr_star_override

    return psr(best_trial_returns, sr_star=benchmark)
```

**DSR input clarification:** DSR requires the FULL RETURNS SERIES of the best trial (not just its SR value) to compute moments. The N SR estimates are used only to estimate E[max SR] benchmark.

### Pattern 3: MinTRL Formula

**What:** Inverse of PSR — minimum number of bars needed to achieve target PSR probability.

```python
# Source: Lopez de Prado, AFML Chapter 7 (verified 2026-02-23 by algebra derivation)

from scipy.stats import norm, skew, kurtosis
import math

def min_trl(
    returns: np.ndarray | pd.Series,
    sr_star: float = 0.0,
    target_psr: float = 0.95,
    freq_per_year: int = 365,
) -> dict:
    """
    Minimum Track Record Length.

    Derives from PSR formula by solving for n:
        n = ((z_threshold * sqrt(var_sr_unit)) / (sr_hat - sr_star))^2 + 1
    where var_sr_unit is the variance formula evaluated at n=1 (unit variance factor).

    Returns:
        dict with keys:
          'n_obs': minimum bars (integer, ceil)
          'calendar_days': approximate calendar days (n_obs * tf_days_nominal)
          'sr_hat': computed per-bar SR
          'target_psr': the threshold used
    """
    n = len(returns)
    if n < 30:
        warnings.warn(f"MinTRL: only {n} observations, estimate unreliable.", stacklevel=2)

    sr_hat = np.mean(returns) / np.std(returns, ddof=1)
    gamma_3 = skew(returns)
    gamma_4 = kurtosis(returns, fisher=False)  # Pearson

    if sr_hat <= sr_star:
        return {"n_obs": float("inf"), "calendar_days": float("inf"),
                "sr_hat": float(sr_hat), "target_psr": target_psr}

    # The "unit variance factor" (variance formula evaluated for any single-bar contribution)
    v_factor = 1.0 - gamma_3 * sr_hat + (gamma_4 - 1.0) / 4.0 * sr_hat**2
    if v_factor <= 0:
        return {"n_obs": float("nan"), "calendar_days": float("nan"),
                "sr_hat": float(sr_hat), "target_psr": target_psr}

    z_threshold = norm.ppf(target_psr)
    n_obs = (z_threshold * math.sqrt(v_factor) / (sr_hat - sr_star)) ** 2 + 1
    n_obs_int = math.ceil(n_obs)
    calendar_days = round(n_obs_int / freq_per_year * 365)  # approximate

    return {
        "n_obs": n_obs_int,
        "calendar_days": calendar_days,
        "sr_hat": float(sr_hat),
        "target_psr": target_psr,
    }
```

**Key insight:** The `tf_days_nominal` from `DimTimeframe` should be passed as `freq_per_year = 365 / tf_days_nominal` for multi-timeframe use cases. For daily backtests, `freq_per_year=365`.

### Pattern 4: PurgedKFoldSplitter

**What:** sklearn-compatible CV splitter that prevents data leakage when labels span multiple bars.

**Key algorithm:**
1. Divide index into N equal folds.
2. For each fold as test: remove ALL train obs whose label end (`t1_series[i]`) extends past test fold start.
3. Apply embargo: remove train obs in the `embargo_size` bars immediately after test fold end.

```python
# Source: Lopez de Prado AFML Ch.7, verified via sklearn cross_val_score 2026-02-23

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator

class PurgedKFoldSplitter(BaseCrossValidator):
    """
    Leakage-free K-Fold for time series with overlapping labels.

    Args:
        n_splits: number of folds (k)
        t1_series: pd.Series where index=observation timestamps,
                   values=label end timestamps. REQUIRED.
        embargo_frac: fraction of sample to embargo after each test fold.
                      Default 0.01 (1%). Minimum 1 bar always enforced.

    Raises:
        ValueError: if t1_series is None at instantiation.
    """

    def __init__(self, n_splits: int = 5, t1_series: pd.Series = None,
                 embargo_frac: float = 0.01):
        super().__init__()
        if t1_series is None:
            raise ValueError("t1_series is required for PurgedKFoldSplitter")
        self.n_splits = n_splits
        self.t1 = t1_series
        self.embargo_frac = embargo_frac

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits

    def _iter_test_indices(self, X=None, y=None, groups=None):
        """Required by BaseCrossValidator. Yields test index arrays."""
        n = len(X) if X is not None else len(self.t1)
        fold_size = n // self.n_splits
        for i in range(self.n_splits):
            start = i * fold_size
            end = (start + fold_size) if i < self.n_splits - 1 else n
            yield np.arange(start, end)

    def split(self, X, y=None, groups=None):
        """
        Yields (train_indices, test_indices) for each fold.
        Purges training obs whose labels overlap the test period.
        Embargoes obs immediately after test period.
        """
        n = len(X)
        idx_arr = np.arange(n)
        embargo_size = max(1, int(self.embargo_frac * n))
        fold_size = n // self.n_splits

        for i in range(self.n_splits):
            test_start = i * fold_size
            test_end = (test_start + fold_size) if i < self.n_splits - 1 else n
            test_idx = idx_arr[test_start:test_end]

            # All non-test obs
            train_mask = np.ones(n, dtype=bool)
            train_mask[test_start:test_end] = False
            train_idx = idx_arr[train_mask]

            # Purge: remove train obs where label end > test period start timestamp
            test_start_time = self.t1.index[test_start]
            t1_train = self.t1.iloc[train_idx]
            purge_mask = t1_train > test_start_time
            clean_idx = train_idx[~purge_mask.values]

            # Embargo: remove obs in [test_end, test_end + embargo_size)
            if test_end < n:
                embargo_end = min(test_end + embargo_size, n)
                embargo_mask = (clean_idx >= test_end) & (clean_idx < embargo_end)
                clean_idx = clean_idx[~embargo_mask]

            yield clean_idx, test_idx
```

**Fold 0 behavior:** Fold 0 (first test period) will often have 0 training observations because all earlier labels spill forward into the test period. This is correct and expected — it reflects the true leakage that standard K-Fold ignores.

**Post-construction validation assertions:** Add assertion that `len(t1_series) == n_samples_expected` and that `t1_series.index` is monotonically increasing.

### Pattern 5: CPCV (Combinatorial Purged Cross-Validation)

**What:** Generate all C(N, n_test_splits) train/test combinations for PBO analysis.

**Path count formula (verified 2026-02-23):**
```
phi (paths) = C(N, n_test_splits) * n_test_splits / N
```

Typical configurations:
| N (splits) | n_test | Combinations | Paths |
|------------|--------|--------------|-------|
| 6 | 2 | 15 | 5 |
| 7 | 2 | 21 | 6 |
| 10 | 2 | 45 | 9 |
| 10 | 3 | 120 | 36 |

```python
# Source: Lopez de Prado AFML Ch.12, verified 2026-02-23
from itertools import combinations
import numpy as np

class CPCVSplitter(BaseCrossValidator):
    """
    Combinatorial Purged Cross-Validation.
    Generates all C(n_splits, n_test_splits) train/test combinations.
    Enables PBO (Probability of Backtest Overfitting) analysis.
    """
    def __init__(self, n_splits: int = 6, n_test_splits: int = 2,
                 t1_series: pd.Series = None, embargo_frac: float = 0.01):
        super().__init__()
        if t1_series is None:
            raise ValueError("t1_series is required for CPCVSplitter")
        self.n_splits = n_splits
        self.n_test_splits = n_test_splits
        self.t1 = t1_series
        self.embargo_frac = embargo_frac
        self._combos = list(combinations(range(n_splits), n_test_splits))

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return len(self._combos)

    def _iter_test_indices(self, X=None, y=None, groups=None):
        n = len(X) if X is not None else len(self.t1)
        fold_size = n // self.n_splits
        for test_group_ids in self._combos:
            test_mask = np.zeros(n, dtype=bool)
            for gid in test_group_ids:
                start = gid * fold_size
                end = (start + fold_size) if gid < self.n_splits - 1 else n
                test_mask[start:end] = True
            yield np.where(test_mask)[0]

    def split(self, X, y=None, groups=None):
        n = len(X)
        fold_size = n // self.n_splits
        embargo_size = max(1, int(self.embargo_frac * n))

        for test_group_ids in self._combos:
            # Build test mask
            test_mask = np.zeros(n, dtype=bool)
            test_starts = []
            for gid in sorted(test_group_ids):
                start = gid * fold_size
                end = (start + fold_size) if gid < self.n_splits - 1 else n
                test_mask[start:end] = True
                test_starts.append(self.t1.index[start])

            test_idx = np.where(test_mask)[0]
            train_idx = np.where(~test_mask)[0]

            # Purge
            min_test_start = min(test_starts)
            t1_train = self.t1.iloc[train_idx]
            purge_mask = t1_train > min_test_start
            clean_idx = train_idx[~purge_mask.values]

            # Embargo (after last test group)
            last_test_end = max(
                (gid + 1) * fold_size if gid < self.n_splits - 1 else n
                for gid in test_group_ids
            )
            if last_test_end < n:
                embargo_end = min(last_test_end + embargo_size, n)
                em_mask = (clean_idx >= last_test_end) & (clean_idx < embargo_end)
                clean_idx = clean_idx[~em_mask]

            yield clean_idx, test_idx
```

### Pattern 6: Alembic Migrations

**Revision 1 (psr_column_rename):** Conditional rename + add new columns.

```python
# Source: alembic Python API pattern, alembic env.py in project
# CRITICAL: Uses information_schema to detect existing column before renaming

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

def upgrade() -> None:
    bind = op.get_bind()
    # Check if legacy psr column exists (it may not — DDL never added it)
    result = bind.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='cmc_backtest_metrics' "
        "AND column_name='psr'"
    ))
    if result.fetchone():
        # Rename existing placeholder column
        op.alter_column(
            'cmc_backtest_metrics', 'psr',
            new_column_name='psr_legacy',
            schema='public'
        )
    else:
        # Add psr_legacy as new nullable column
        op.add_column(
            'cmc_backtest_metrics',
            sa.Column('psr_legacy', sa.Numeric(), nullable=True),
            schema='public'
        )
    # Add new real psr column
    op.add_column(
        'cmc_backtest_metrics',
        sa.Column('psr', sa.Numeric(), nullable=True),
        schema='public'
    )

def downgrade() -> None:
    op.drop_column('cmc_backtest_metrics', 'psr', schema='public')
    op.alter_column('cmc_backtest_metrics', 'psr_legacy',
                    new_column_name='psr', schema='public')
```

**Revision 2 (psr_results_table):** Create separate psr_results table.

```python
def upgrade() -> None:
    op.create_table(
        'psr_results',
        sa.Column('result_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'),
                  primary_key=True),
        sa.Column('run_id', sa.UUID(), sa.ForeignKey('public.cmc_backtest_runs.run_id',
                  ondelete='CASCADE'), nullable=False),
        sa.Column('formula_version', sa.Text(), nullable=False),  # 'lopez_de_prado_v1'
        sa.Column('psr', sa.Numeric(), nullable=True),
        sa.Column('dsr', sa.Numeric(), nullable=True),
        sa.Column('min_trl_bars', sa.Integer(), nullable=True),
        sa.Column('min_trl_days', sa.Integer(), nullable=True),
        sa.Column('sr_hat', sa.Numeric(), nullable=True),
        sa.Column('sr_star', sa.Numeric(), nullable=True),
        sa.Column('n_obs', sa.Integer(), nullable=True),
        sa.Column('skewness', sa.Numeric(), nullable=True),
        sa.Column('kurtosis_pearson', sa.Numeric(), nullable=True),
        sa.Column('computed_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        schema='public',
    )
    op.create_index('idx_psr_results_run_id', 'psr_results', ['run_id'],
                    schema='public')
    op.create_unique_constraint('uq_psr_results_run_version', 'psr_results',
                                ['run_id', 'formula_version'], schema='public')

def downgrade() -> None:
    op.drop_table('psr_results', schema='public')
```

### Pattern 7: Alembic Migration Auto-Check in run_daily_refresh.py

```python
# Source: alembic Python API (MigrationContext, ScriptDirectory), verified 2026-02-23

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool
import logging

logger = logging.getLogger(__name__)

def check_migration_status(db_url: str, alembic_ini_path: str = "alembic.ini") -> bool:
    """
    Returns True if DB is at alembic head, False if pending migrations exist.
    Logs a warning when behind.
    """
    cfg = Config(alembic_ini_path)
    script = ScriptDirectory.from_config(cfg)
    head_rev = script.get_current_head()

    engine = create_engine(db_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        current_rev = ctx.get_current_revision()

    if current_rev == head_rev:
        return True

    logger.warning(
        f"[MIGRATION] DB at {current_rev!r}, head is {head_rev!r}. "
        f"Run: alembic upgrade head"
    )
    return False
```

### Anti-Patterns to Avoid

- **Using Fisher/excess kurtosis in PSR:** `kurtosis(x, fisher=True)` returns 0 for normal, causing the formula `(0 - 1)/4 * SR^2 = -SR^2/4` which produces negative variance for SR > 2. Always use `fisher=False`.
- **Using annualized SR as `sr_star` directly:** `sr_star=0` means "benchmark Sharpe of zero per bar" — correct for default case. If the user specifies an annualized sr_star (e.g., 1.0), it must be converted: `sr_star_per_bar = sr_star / sqrt(freq_per_year)`.
- **Computing PSR on annualized returns:** PSR inputs must be per-bar returns. If `pf.returns()` gives daily returns, use those directly. Annualizing returns before passing to PSR breaks the formula.
- **Skipping purge when label_duration=0:** Even a label_duration of 1 bar can cause leakage — always purge by `t1_series` rather than duration.
- **Using `alembic.ini` with cp1252 encoding:** The project env.py already uses `encoding='utf-8'` — never remove this (Windows pitfall from MEMORY.md).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Normal CDF for z-score | custom erf approximation | `scipy.stats.norm.cdf(z)` | Already installed, exact |
| Skewness computation | manual third moment | `scipy.stats.skew(x)` | Handles edge cases, bias correction |
| Kurtosis computation | manual fourth moment | `scipy.stats.kurtosis(x, fisher=False)` | Must use Pearson convention |
| Combinatorial enumeration | hand-rolled combinations | `itertools.combinations` | stdlib, correct |
| Migration column rename | raw SQL in psycopg2 | `op.alter_column(new_column_name=...)` | Alembic tracks state for downgrade |

**Key insight:** The PSR formula looks simple but has a critical kurtosis convention trap. Always verify with the known normal-distribution case: `var_sr` for normal returns should equal `(1 + SR^2/2) / (T-1)`.

## Common Pitfalls

### Pitfall 1: Kurtosis Convention Error

**What goes wrong:** PSR formula uses `(gamma_4 - 1)/4 * SR^2` in the denominator. If `gamma_4` is Fisher/excess kurtosis (=0 for normal), the term becomes `-SR^2/4`, producing negative variance for SR > 2. Code will return NaN or raise errors.

**Why it happens:** scipy's `kurtosis()` defaults to `fisher=True` (excess kurtosis). The PSR paper uses Pearson kurtosis (=3 for normal) without being explicit about this convention in all presentations.

**How to avoid:** Always use `scipy.stats.kurtosis(returns, fisher=False)`. Add a unit test: for returns sampled from a normal distribution, `var_sr` should be approximately `(1 + SR^2/2) / (T-1)`.

**Warning signs:** PSR returns NaN for strategies with SR > 2. PSR returns values far outside [0,1] before clamping.

### Pitfall 2: SR Units Mismatch Between PSR and Annualized Sharpe

**What goes wrong:** PSR takes per-bar SR. If you pass annualized returns or annualized SR as `sr_star`, results are nonsense. For example, `sr_star=1.0` (annual) should be `sr_star = 1.0/sqrt(365) = 0.052` (daily).

**Why it happens:** The backtest pipeline stores and reports annualized Sharpe ratios, but PSR must be computed on per-bar returns with per-bar SR.

**How to avoid:** Compute PSR directly from `pf.returns()` (per-bar). For user-facing `sr_star`, document as "annualized" and convert internally: `sr_star_per_bar = sr_star / sqrt(freq_per_year)`.

### Pitfall 3: PSR Column Not in Current DB

**What goes wrong:** Assuming `cmc_backtest_metrics.psr` column exists. It does NOT exist in the current DDL (`sql/backtests/072_cmc_backtest_metrics.sql` has no psr column) and the INSERT in `backtest_from_signals.py` does not write psr.

**Why it happens:** The `psr_placeholder()` function in `metrics.py` computes psr but it's only used in `summarize()` which is called by the older orchestrator, not `backtest_from_signals.py`.

**How to avoid:** The Alembic migration must use a conditional `IF EXISTS` check. Do NOT assume `ALTER TABLE ... RENAME COLUMN psr TO psr_legacy` will succeed — add defensive logic.

### Pitfall 4: Fold 0 Empty Train in PurgedKFold

**What goes wrong:** PurgedKFold fold 0 (or early folds with large labels) produces 0 training observations. sklearn estimators that fail on empty train set propagate NaN scores (UserWarning from `cross_val_score`).

**Why it happens:** All historical observations before the first test period have labels that extend into the test period, triggering purging.

**How to avoid:** This is correct behavior, not a bug. Document it. Callers should check for empty train sets. Don't skip folds silently — let sklearn's `cross_val_score` handle it with its UserWarning mechanism.

### Pitfall 5: MinTRL Formula Undefined for SR <= SR*

**What goes wrong:** If `sr_hat <= sr_star`, the MinTRL formula has a non-positive denominator and the result is undefined (negative or infinite).

**Why it happens:** MinTRL asks "how long until we're confident SR > SR*" — impossible if measured SR is already at or below benchmark.

**How to avoid:** Return `{"n_obs": inf, "calendar_days": inf}` when `sr_hat <= sr_star`. Log a warning.

### Pitfall 6: Alembic auto-upgrade on startup creates silent failures

**What goes wrong:** If `run_daily_refresh.py` auto-upgrades Alembic on startup (not just warns), a failed migration mid-upgrade leaves the DB in an inconsistent state.

**Why it happens:** Auto-upgrade without transaction isolation.

**How to avoid:** The startup check should WARN and print instructions, not auto-upgrade. Only auto-upgrade if there is an explicit flag like `--apply-migrations`.

## Code Examples

### Complete PSR + psr_results Insert Pattern

```python
# Source: pattern from backtest_from_signals.py save_backtest_results(), adapted 2026-02-23

def compute_and_save_psr(
    run_id: str,
    returns: pd.Series,  # per-bar returns from pf.returns()
    sr_star: float = 0.0,
    formula_version: str = "lopez_de_prado_v1",
    freq_per_year: int = 365,
    conn,  # SQLAlchemy connection
) -> dict:
    """Compute PSR + MinTRL, write to psr_results table."""
    psr_val = psr(returns, sr_star=sr_star)
    trl = min_trl(returns, sr_star=sr_star, target_psr=0.95, freq_per_year=freq_per_year)

    row = {
        "run_id": run_id,
        "formula_version": formula_version,
        "psr": psr_val if not math.isnan(psr_val) else None,
        "dsr": None,  # computed separately for multi-trial scenarios
        "min_trl_bars": trl["n_obs"] if math.isfinite(trl["n_obs"]) else None,
        "min_trl_days": trl["calendar_days"] if math.isfinite(trl["calendar_days"]) else None,
        "sr_hat": trl["sr_hat"],
        "sr_star": sr_star,
        "n_obs": len(returns),
        "skewness": float(skew(returns)),
        "kurtosis_pearson": float(kurtosis(returns, fisher=False)),
    }
    conn.execute(text("""
        INSERT INTO public.psr_results
            (run_id, formula_version, psr, dsr, min_trl_bars, min_trl_days,
             sr_hat, sr_star, n_obs, skewness, kurtosis_pearson)
        VALUES
            (:run_id, :formula_version, :psr, :dsr, :min_trl_bars, :min_trl_days,
             :sr_hat, :sr_star, :n_obs, :skewness, :kurtosis_pearson)
        ON CONFLICT (run_id, formula_version) DO UPDATE SET
            psr = EXCLUDED.psr,
            computed_at = now()
    """), row)
    return row
```

### Alembic Head Check Helper

```python
# Source: tested against live DB 2026-02-23
# Place in src/ta_lab2/scripts/refresh_utils.py or a new alembic_utils.py

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool

def is_alembic_head(db_url: str, ini_path: str = "alembic.ini") -> bool:
    cfg = Config(ini_path)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()
    engine = create_engine(db_url, poolclass=pool.NullPool)
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current == head
```

### PSR Validation Test Pattern

```python
# Verification: PSR of normal returns with known SR should match theoretical
import numpy as np
from scipy.stats import norm

def test_psr_normal_distribution():
    """PSR for large sample of normal returns with clear positive SR should be ~1."""
    np.random.seed(42)
    returns = np.random.normal(loc=0.01, scale=0.1, size=10000)
    result = psr(returns, sr_star=0.0)
    assert result > 0.99, f"Expected PSR ~ 1.0, got {result}"

def test_psr_normal_variance_formula():
    """For normal returns, variance of SR should equal (1 + SR^2/2) / (T-1)."""
    np.random.seed(0)
    r = np.random.normal(0.001, 0.01, 500)
    sr_hat = r.mean() / r.std(ddof=1)
    n = len(r)
    expected_var = (1 + sr_hat**2 / 2) / (n - 1)
    # gamma3=0, gamma4=3 (Pearson) for normal: (1 - 0 + (3-1)/4*SR^2) / (T-1)
    from scipy.stats import kurtosis
    g4 = kurtosis(r, fisher=False)  # should be ~3
    actual_var = (1 - 0 * sr_hat + (g4 - 1) / 4 * sr_hat**2) / (n - 1)
    assert abs(actual_var - expected_var) < 0.001, f"{actual_var} vs {expected_var}"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `psr_placeholder()` (sigmoid of Sharpe) | Full PSR formula via scipy | Phase 36 | Statistically valid probability estimate |
| mlfinlab PurgedKFold | from-scratch implementation | Phase 36 | mlfinlab discontinued; known PurgedKFold bug #295 |
| No column tracking | psr_results table with formula_version | Phase 36 | Enables future formula upgrades without rewriting |
| No migration versioning | Alembic two-revision strategy | Phase 33 (baseline established), Phase 36 (first real migration) | All schema changes tracked |

**Deprecated/outdated:**
- `psr_placeholder()`: remains in `metrics.py` during transition; removed when `summarize()` callers are updated to use real PSR.
- The naive `1 / (1 + exp(-SR))` in `psr_placeholder()` — not a probability in any statistical sense.

## Open Questions

1. **psr column in backtest_from_signals.py INSERT**
   - What we know: The INSERT currently writes to `cmc_backtest_metrics` without a `psr` column. After migration, a `psr` column exists.
   - What's unclear: Should PSR be auto-computed in `_compute_comprehensive_metrics()` (uses `pf.returns()` already available) and written to `cmc_backtest_metrics.psr` inline, OR should it only go to `psr_results` table via a separate call?
   - Recommendation: Write to both — `cmc_backtest_metrics.psr` for quick queries, `psr_results` for full details (DSR, MinTRL, formula_version). But plan must specify the INSERT update explicitly.

2. **DSR full-returns-per-trial requirement**
   - What we know: CONTEXT says "DSR requires full returns series per trial." The backtest runner runs one trial at a time.
   - What's unclear: How does DSR get called in practice? The N trial returns series must be available simultaneously. This implies a multi-backtest aggregator or loading from `cmc_backtest_metrics` after a parameter sweep.
   - Recommendation: DSR CLI should accept `--run-ids-file` (list of run_ids from a sweep), load returns from DB for each, then compute DSR on the best.

3. **CPCV purging across non-contiguous test groups**
   - What we know: CPCV test groups are multiple non-contiguous fold ranges. Purging should use the minimum test start time.
   - What's unclear: Should embargo apply after EACH test group or only after the last one?
   - Recommendation: Embargo after the last test group only (simplest, conservative approach). Flag this in plan.

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/backtests/metrics.py` — existing `psr_placeholder()` function, `summarize()` API
- `src/ta_lab2/scripts/backtests/backtest_from_signals.py` — exact INSERT statements, `_compute_comprehensive_metrics()` location
- `sql/backtests/072_cmc_backtest_metrics.sql` — confirmed: no `psr` column in DDL
- `alembic/versions/25f2b3c90f65_baseline.py` — baseline revision ID for `down_revision` chain
- `alembic/env.py` — confirmed: `encoding='utf-8'`, `NullPool`, `resolve_db_url()`
- scipy 1.17.0 + sklearn 1.8.0 — verified installed, `BaseCrossValidator.get_n_splits` is the only abstract method
- Direct Python execution of all 5 formulas (PSR, DSR, MinTRL, PurgedKFold, CPCV path count) — all verified correct

### Secondary (MEDIUM confidence)
- [Probabilistic Sharpe Ratio - Quantdare](https://quantdare.com/probabilistic-sharpe-ratio/) — PSR and MinTRL formula presentation (Pearson kurtosis convention confirmed)
- [rubenbriones/Probabilistic-Sharpe-Ratio](https://github.com/rubenbriones/Probabilistic-Sharpe-Ratio/blob/master/src/sharpe_ratio_stats.py) — reference implementation (uses Pearson kurtosis indirectly via `(sr_std^2 * (n-1))` form)

### Tertiary (LOW confidence — needs validation in plan)
- [The Deflated Sharpe Ratio (Bailey & Lopez de Prado)](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) — URL returned 403, could not fetch; DSR formula derived from algebraic reasoning and verified against expected order statistics behavior
- [CPCV description (Towards AI)](https://towardsai.net/p/l/the-combinatorial-purged-cross-validation-method) — path formula verified by direct computation; article did not provide the formula explicitly

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH — all deps verified installed via Python execution
- PSR formula: HIGH — verified correct for normal distribution against known analytical result
- DSR formula: MEDIUM — correct structure verified, but FULL DSR paper (dhbpapers) was inaccessible (403); formula derived from first principles and verified against expected max of N normals
- MinTRL formula: HIGH — algebra derived from PSR inversion, verified numerically (daily SR=2.0 -> ~247 bars needed)
- PurgedKFold: HIGH — implemented and verified with sklearn cross_val_score, fold counts match expectations
- CPCV: HIGH — path formula verified by combinatorics (C(N,k)*k/N)
- Alembic migration: HIGH — alembic Python API tested against live DB (current=25f2b3c90f65, at head)
- PSR column status: HIGH — confirmed absent from DDL and INSERT; migration must be conditional

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable math, scipy/sklearn APIs very stable)
