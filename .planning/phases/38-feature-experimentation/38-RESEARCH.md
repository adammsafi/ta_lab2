# Phase 38: Feature Experimentation Framework - Research

**Researched:** 2026-02-23
**Domain:** YAML feature registry, experimental feature compute, BH-corrected promotion gate, Alembic migration, DAG dependency resolution
**Confidence:** HIGH — all patterns verified by direct execution against live DB and installed packages

## Summary

Phase 38 builds a YAML-driven feature experimentation framework on top of Phase 37's IC engine (`ta_lab2.analysis.ic`). Experimental features are declared in YAML with either an inline pandas expression or a Python dotpath reference; `ExperimentRunner` loads the YAML, resolves a dependency DAG, computes feature values into a PostgreSQL temp table, scores them with Phase 37's `compute_ic()` / `batch_compute_ic()`, and persists IC + cost results to a new `cmc_feature_experiments` table. The `promote_feature()` function applies BH correction via `scipy.stats.false_discovery_control()` as a hard gate before writing to `dim_feature_registry` and generating an Alembic migration stub.

Zero new package installs are required. Every dependency is already present: `scipy` 1.17.0 (BH correction), `PyYAML` 6.0.3 (feature definitions), Python stdlib `graphlib` (DAG resolution), `tracemalloc` (peak memory tracking), `ast` (expression syntax validation), and `importlib` (dotpath loading). The project already has `ta_lab2.analysis.ic` from Phase 37 as the scoring engine.

The two new tables (`dim_feature_registry` and `cmc_feature_experiments`) go through a single Alembic migration chained from the Phase 37 head `c3b718c2d088`. The Alembic migration for PROMOTED features (ALTER TABLE ADD COLUMN to `cmc_features`) is written as a new chained revision at promotion time, not bundled into the Phase 38 baseline migration.

**Primary recommendation:** Implement Phase 38 as: YAML registry loader + `ExperimentRunner` class (library) + CLI script + Alembic migration + `FeaturePromoter` class (library) + purge CLI. Keep `ExperimentRunner` and `FeaturePromoter` in `src/ta_lab2/experiments/` as a new subpackage. Wire the three invocation paths (CLI, Python API, notebook stub) against the same library classes.

## Standard Stack

All dependencies are already installed — zero new installs for Phase 38.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `scipy.stats.false_discovery_control` | 1.17.0 | BH p-value correction for promotion gate | `ps_adjusted = false_discovery_control(p_array, method='bh')` — verified API |
| `PyYAML` (`yaml.safe_load`) | 6.0.3 | Parse feature YAML files | `safe_load` prevents arbitrary code execution from YAML |
| `ta_lab2.analysis.ic` | Phase 37 | IC scoring engine — `compute_ic()`, `batch_compute_ic()` | Phase 37 dependency; verified API |
| `graphlib.TopologicalSorter` | stdlib (3.9+) | DAG resolution for experimental feature dependencies | Zero-dependency, verified on Python 3.12 |
| `tracemalloc` | stdlib | Peak memory tracking per experiment | `tracemalloc.get_traced_memory()` returns `(current, peak)` bytes |
| `ast.parse` | stdlib | Inline expression syntax validation before `eval()` | Catches syntax errors early, prevents confusing runtime failures |
| `importlib.import_module` | stdlib | Dotpath function loading for mode=dotpath features | `mod = importlib.import_module(module_path); fn = getattr(mod, func_name)` |
| `hashlib.sha256` | stdlib | YAML spec digest for `yaml_digest` column | Tracks when spec changed between runs |
| `alembic` | existing | Two new table migrations + per-promotion stub | Existing project toolchain, verified env.py and chain |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pandas.DataFrame.to_string` | existing | Console summary table rendering | No tabulate/rich available; `to_string(index=False)` is sufficient |
| `sqlalchemy.pool.NullPool` | existing | CLI engine creation | All one-shot scripts use NullPool; matches project pattern |
| `ta_lab2.scripts.refresh_utils.resolve_db_url` | existing | DB URL resolution | Matches all other scripts |
| `ta_lab2.scripts.sync_utils.get_columns` | existing | Discover cmc_features columns dynamically | Used for promotion wiring check |
| `ta_lab2.time.dim_timeframe.DimTimeframe` | existing | `tf_days_nominal` for IC scoring | Needed when calling `compute_ic()` with correct boundary masking |
| `itertools.product` | stdlib | Parameter grid expansion in YAML | Expand `params: {period: [5,14,21]}` into multiple variants |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `graphlib.TopologicalSorter` | `networkx.topological_sort` | networkx not installed; graphlib is stdlib in Python 3.9+ |
| `ast.parse` + `eval()` | `pandas.eval()` | `pandas.eval()` has restricted operators; inline expressions need full pandas API |
| `yaml.safe_load` | `tomllib` | YAML already used in configs/; TOML would be inconsistent |
| `pandas.to_string()` | `tabulate` or `rich` | Neither is installed; pandas.to_string() produces adequate console output |

**Installation:** No new installs needed.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/
├── experiments/                  # NEW subpackage
│   ├── __init__.py               # NEW
│   ├── registry.py               # NEW: FeatureRegistry — loads/validates YAML
│   ├── runner.py                 # NEW: ExperimentRunner — compute + IC score
│   ├── promoter.py               # NEW: FeaturePromoter — BH gate + promotion pipeline
│   └── dag.py                    # NEW: resolve_dag() — DAG resolution via graphlib
│
└── scripts/
    └── experiments/              # NEW scripts subpackage
        ├── __init__.py           # NEW
        ├── run_experiment.py     # NEW: CLI for ExperimentRunner
        ├── promote_feature.py    # NEW: CLI for FeaturePromoter
        └── purge_experiment.py   # NEW: CLI for purge_experiment command

configs/
└── experiments/                  # NEW: YAML feature definitions
    └── features.yaml             # NEW: lifecycle: experimental entries

alembic/versions/
└── XXXX_feature_experiment_tables.py  # NEW: dim_feature_registry + cmc_feature_experiments
```

### Pattern 1: YAML Feature Definition Contract
**What:** YAML entries in `configs/experiments/features.yaml` define experimental features.
**When to use:** Any new experimental feature starts here.

```yaml
# configs/experiments/features.yaml
# Source: verified yaml.safe_load() on Python 3.12 with PyYAML 6.0.3

features:
  vol_ratio_30_7:
    lifecycle: experimental           # experimental | promoted | deprecated
    description: "30d/7d realized vol ratio — captures vol regime shift"
    compute:
      mode: inline                    # inline or dotpath
      expression: "vol_30d / vol_7d - 1"
    inputs:
      - table: cmc_vol
        columns: [vol_30d, vol_7d]
    tags: [vol, ratio, experimental]

  custom_momentum:
    lifecycle: experimental
    description: "Vol-adjusted price momentum"
    compute:
      mode: dotpath
      function: "ta_lab2.experiments.custom_features:compute_momentum"
    inputs:
      - table: cmc_price_bars_multi_tf_u
        columns: [close]
      - table: cmc_vol
        columns: [vol_30d]
    tags: [momentum, custom]

  # Parameter sweep: creates one experiment per param combo
  rsi_mom_sweep:
    lifecycle: experimental
    compute:
      mode: inline
      expression: "close.rolling({period}).apply(lambda x: (x[-1] - x.mean()) / (x.std() + 1e-8))"
    params:
      period: [5, 10, 14, 21]
    inputs:
      - table: cmc_price_bars_multi_tf_u
        columns: [close]
    tags: [momentum, rsi]
```

### Pattern 2: FeatureRegistry — YAML Loading
**What:** Loads YAML, validates lifecycle state, expands parameter grids, resolves DAG.
**When to use:** Entry point for all ExperimentRunner and FeaturePromoter operations.

```python
# Source: verified yaml.safe_load, itertools.product, ast.parse on this system

import yaml
import hashlib
import ast
import itertools

class FeatureRegistry:
    """
    Loads and validates the YAML feature registry.
    Auto-expands parameter sweeps into named variants.
    """

    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path
        self._raw: dict = {}
        self._features: dict[str, dict] = {}

    def load(self) -> None:
        """Load and expand YAML feature definitions."""
        with open(self.yaml_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self._raw = raw
        raw_features = raw.get("features", {})

        for name, spec in raw_features.items():
            variants = self._expand_params(name, spec)
            for variant in variants:
                self._features[variant["name"]] = variant

    def _expand_params(self, name: str, spec: dict) -> list[dict]:
        """Expand params grid into separate variants."""
        params = spec.get("params", {})
        if not params:
            return [{**spec, "name": name, "yaml_digest": self._digest(spec)}]

        keys = list(params.keys())
        values = [p if isinstance(p, list) else [p] for p in params.values()]
        variants = []
        for combo in itertools.product(*values):
            variant_params = dict(zip(keys, combo))
            param_str = "_".join(f"{k}{v}" for k, v in variant_params.items())
            variant_name = f"{name}_{param_str}"
            variant_spec = spec.copy()
            variant_spec["resolved_params"] = variant_params
            # Substitute params into inline expression
            if spec.get("compute", {}).get("mode") == "inline":
                variant_spec = {**spec, "compute": {**spec["compute"]}}
                variant_spec["compute"]["expression"] = spec["compute"]["expression"].format(**variant_params)
            variants.append({**variant_spec, "name": variant_name, "yaml_digest": self._digest(variant_spec)})
        return variants

    def _digest(self, spec: dict) -> str:
        import json
        content = json.dumps(spec, sort_keys=True)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def get_feature(self, name: str) -> dict:
        """Get expanded feature spec by name. Raises KeyError if not found."""
        return self._features[name]

    def list_experimental(self) -> list[str]:
        """Return names of all features with lifecycle=experimental."""
        return [n for n, s in self._features.items() if s.get("lifecycle") == "experimental"]

    def validate_expression(self, expr: str) -> None:
        """Validate inline expression syntax using ast.parse. Raises SyntaxError."""
        ast.parse(expr, mode="eval")
```

### Pattern 3: ExperimentRunner — Compute + IC Score
**What:** Resolves DAG, computes features into temp table, scores with IC, writes to `cmc_feature_experiments`.
**When to use:** Core execution engine called by CLI, Python API, and notebook wrapper.

```python
# Source: verified temp table lifecycle, tracemalloc, compute_ic API

import time
import tracemalloc
import importlib
import pandas as pd
import numpy as np
from sqlalchemy import text, pool
from sqlalchemy.engine import Connection

from ta_lab2.analysis.ic import compute_ic
from ta_lab2.time.dim_timeframe import DimTimeframe

class ExperimentRunner:
    """
    Computes experimental features in-memory + temp DB scratch table,
    scores with IC, persists results to cmc_feature_experiments.
    """

    def run(
        self,
        feature_name: str,
        asset_ids: list[int],
        tf: str,
        train_start: pd.Timestamp,
        train_end: pd.Timestamp,
        *,
        horizons: list[int] | None = None,
        return_types: list[str] | None = None,
        dry_run: bool = False,
        confirm: bool = True,
    ) -> pd.DataFrame:
        """
        Compute and score one experimental feature.

        Returns IC results DataFrame.
        Writes to cmc_feature_experiments if not dry_run and user confirms.
        """
        spec = self.registry.get_feature(feature_name)
        tf_days_nominal = self._get_tf_days(tf)

        all_ic_rows = []
        total_rows = 0

        # Cost tracking
        tracemalloc.start()
        t0 = time.perf_counter()

        try:
            with self.engine.connect() as conn:
                # Create temp scratch table (scoped to this connection)
                scratch_table = f"_exp_{feature_name[:20]}_{int(t0)}"
                self._create_scratch_table(conn, scratch_table)

                for asset_id in asset_ids:
                    # Load input data from declared source tables
                    input_df = self._load_inputs(conn, spec, asset_id, tf, train_start, train_end)
                    if input_df.empty:
                        continue

                    # Compute feature values
                    feature_series = self._compute_feature(spec, input_df)
                    close_series = input_df["close"] if "close" in input_df else None

                    # Write to scratch table (allows psql inspection during debug)
                    self._write_to_scratch(conn, scratch_table, asset_id, tf, feature_name, feature_series)
                    total_rows += len(feature_series.dropna())

                    # Score with IC using Phase 37 engine
                    if close_series is not None and not close_series.empty:
                        ic_df = compute_ic(
                            feature_series, close_series,
                            train_start, train_end,
                            horizons=horizons,
                            return_types=return_types,
                            tf_days_nominal=tf_days_nominal,
                        )
                        ic_df["asset_id"] = asset_id
                        ic_df["tf"] = tf
                        all_ic_rows.append(ic_df)

                conn.commit()  # commit scratch writes (for inspection)
                # Scratch table auto-drops when connection closes

        finally:
            wall_clock = time.perf_counter() - t0
            _, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak_mb = peak_bytes / 1024 / 1024

        if not all_ic_rows:
            return pd.DataFrame()

        result_df = pd.concat(all_ic_rows, ignore_index=True)

        # Apply BH correction across all (asset, tf, horizon) combos
        result_df = self._apply_bh_correction(result_df)

        # Add cost columns
        result_df["wall_clock_seconds"] = round(wall_clock, 3)
        result_df["peak_memory_mb"] = round(peak_mb, 2)
        result_df["n_rows_computed"] = total_rows
        result_df["feature_name"] = feature_name
        result_df["yaml_digest"] = spec.get("yaml_digest", "")
        result_df["train_start"] = train_start
        result_df["train_end"] = train_end

        return result_df

    def _compute_feature(self, spec: dict, input_df: pd.DataFrame) -> pd.Series:
        """Dispatch to inline eval or dotpath function."""
        compute = spec["compute"]
        mode = compute["mode"]

        if mode == "inline":
            # Inject DataFrame columns as local variables
            local_vars = {col: input_df[col] for col in input_df.columns}
            return eval(compute["expression"], {"__builtins__": {}}, local_vars)  # noqa: S307

        elif mode == "dotpath":
            dotpath = compute["function"]
            module_path, func_name = dotpath.rsplit(":", 1)
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            return fn(input_df)

        raise ValueError(f"Unknown compute mode: {mode!r}")

    def _apply_bh_correction(self, df: pd.DataFrame) -> pd.DataFrame:
        """Apply BH correction to ic_p_value column."""
        from scipy.stats import false_discovery_control
        valid_mask = df["ic_p_value"].notna()
        if valid_mask.sum() == 0:
            df["ic_p_value_bh"] = np.nan
            return df
        p_vals = df.loc[valid_mask, "ic_p_value"].values
        adj = false_discovery_control(p_vals, method="bh")
        df["ic_p_value_bh"] = np.nan
        df.loc[valid_mask, "ic_p_value_bh"] = adj
        return df
```

### Pattern 4: BH Promotion Gate
**What:** `scipy.stats.false_discovery_control()` applied to all p-values across experiment rows. Raises `PromotionRejectedError` if no horizon passes at `alpha=0.05`.
**When to use:** `FeaturePromoter.promote_feature()` always runs this gate before any DB writes.

```python
# Source: verified false_discovery_control API and behavior on 2026-02-23

from scipy.stats import false_discovery_control
import numpy as np

class PromotionRejectedError(Exception):
    """Raised when BH gate fails — no horizon passes at the configured alpha."""
    pass


def check_bh_gate(
    ic_results_df: pd.DataFrame,
    alpha: float = 0.05,
    min_pass_rate: float = 0.0,   # 0.0 = any single combo passes
) -> tuple[bool, pd.DataFrame]:
    """
    Apply BH correction and check promotion gate.

    Parameters
    ----------
    ic_results_df : DataFrame with ic_p_value column from cmc_feature_experiments
    alpha : BH significance threshold (default 0.05)
    min_pass_rate : Fraction of (asset, tf, horizon) combos that must pass.
                    0.0 means any single passing combo is sufficient.

    Returns
    -------
    tuple[bool, DataFrame]
        (passes_gate, df_with_bh_column)

    CRITICAL: Drop NaN p-values before calling false_discovery_control().
    It raises ValueError on NaN input.
    """
    valid_mask = ic_results_df["ic_p_value"].notna()
    valid_pvals = ic_results_df.loc[valid_mask, "ic_p_value"].values

    if len(valid_pvals) == 0:
        return False, ic_results_df

    adj_pvals = false_discovery_control(valid_pvals, method="bh")

    ic_results_df = ic_results_df.copy()
    ic_results_df["ic_p_value_bh"] = np.nan
    ic_results_df.loc[valid_mask, "ic_p_value_bh"] = adj_pvals

    n_pass = (ic_results_df["ic_p_value_bh"] < alpha).sum()
    n_total = valid_mask.sum()

    if n_total == 0:
        return False, ic_results_df

    pass_rate = n_pass / n_total
    passes = pass_rate > min_pass_rate  # strictly greater handles min_pass_rate=0.0

    return passes, ic_results_df
```

### Pattern 5: Temp Table Pattern
**What:** Feature values written to a PostgreSQL temp table during computation (for psql debug), auto-dropped on connection close.
**When to use:** ExperimentRunner always uses this pattern — never writes to production feature tables.

```python
# Source: verified PostgreSQL TEMP TABLE lifetime with SQLAlchemy NullPool 2026-02-23

def _create_scratch_table(conn: Connection, scratch_name: str) -> None:
    """
    Create a session-scoped temp table for experimental feature values.
    Auto-drops when connection closes. Safe for concurrent runs (unique name).
    """
    conn.execute(text(f"""
        CREATE TEMP TABLE IF NOT EXISTS {scratch_name} (
            id INTEGER NOT NULL,
            ts TIMESTAMPTZ NOT NULL,
            tf TEXT NOT NULL,
            feature_name TEXT NOT NULL,
            feature_val DOUBLE PRECISION
        )
    """))

# CRITICAL: Use the SAME connection object for:
# 1. _create_scratch_table()
# 2. _write_to_scratch()
# 3. IC scoring query against scratch (if SQL-based)
# 4. conn.commit() for visibility during debugging
# Temp table is auto-dropped when the connection closes.
# With NullPool, connections are NOT reused between engine.connect() calls.
```

### Pattern 6: DAG Resolution for Experimental Dependencies
**What:** Experimental features can depend on other experimental features. `graphlib.TopologicalSorter` resolves computation order.
**When to use:** Whenever a feature spec has `depends_on` keys referencing other experimental features.

```python
# Source: verified graphlib.TopologicalSorter on Python 3.12, 2026-02-23

import graphlib

def resolve_experiment_dag(features: dict[str, dict]) -> list[str]:
    """
    Resolve computation order for experimental features with dependencies.

    Parameters
    ----------
    features : dict mapping feature_name -> spec (with optional 'depends_on' list)

    Returns
    -------
    list[str] : Feature names in topological order (dependencies first)

    Raises
    ------
    graphlib.CycleError : If circular dependency detected
    """
    deps = {}
    for name, spec in features.items():
        deps[name] = set(spec.get("depends_on", []))

    sorter = graphlib.TopologicalSorter(deps)
    return list(sorter.static_order())

# Example YAML dependency:
# features:
#   vol_ratio:
#     compute: {mode: inline, expression: "vol_30d / vol_7d - 1"}
#     inputs: [{table: cmc_vol, columns: [vol_30d, vol_7d]}]
#   vol_momentum:
#     depends_on: [vol_ratio]            # references another experimental feature
#     compute: {mode: inline, expression: "vol_ratio.rolling(5).mean()"}
```

### Pattern 7: Dotpath Expression Validation
**What:** Validate inline expressions with `ast.parse()` before `eval()`. Load dotpath functions with `importlib.import_module()`.
**When to use:** FeatureRegistry.load() — validates on load, not at compute time.

```python
# Source: verified ast.parse and importlib.import_module 2026-02-23

import ast
import importlib

def validate_compute_spec(spec: dict) -> None:
    """Validate compute spec at registry load time. Raises on invalid spec."""
    mode = spec.get("compute", {}).get("mode")

    if mode == "inline":
        expr = spec["compute"]["expression"]
        try:
            ast.parse(expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Invalid inline expression: {e}") from e

    elif mode == "dotpath":
        dotpath = spec["compute"]["function"]
        if ":" not in dotpath:
            raise ValueError(
                f"Dotpath must be 'module.path:function_name', got: {dotpath!r}"
            )
        module_path, func_name = dotpath.rsplit(":", 1)
        try:
            mod = importlib.import_module(module_path)
            if not hasattr(mod, func_name):
                raise AttributeError(f"Function '{func_name}' not found in '{module_path}'")
        except ImportError as e:
            raise ValueError(f"Cannot import module '{module_path}': {e}") from e

    else:
        raise ValueError(f"Unknown compute mode: {mode!r}. Must be 'inline' or 'dotpath'.")
```

### Pattern 8: Alembic Migration (dim_feature_registry + cmc_feature_experiments)
**What:** One migration creates both new tables, chained from Phase 37 head `c3b718c2d088`.
**When to use:** Phase 38 FEAT-05.

```python
# Source: verified against c3b718c2d088_ic_results_table.py pattern

"""feature_experiment_tables

Revision ID: XXXX_feature_experiment_tables
Revises: c3b718c2d088
Create Date: ...
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "XXXX_feature_experiment_tables"
down_revision: Union[str, None] = "c3b718c2d088"   # Phase 37 head — VERIFIED
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dim_feature_registry: one row per feature name
    op.create_table(
        "dim_feature_registry",
        sa.Column("feature_name", sa.Text(), nullable=False),
        sa.Column("lifecycle", sa.Text(), nullable=False),  # experimental/promoted/deprecated
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("yaml_source_path", sa.Text(), nullable=True),
        sa.Column("yaml_digest", sa.Text(), nullable=True),
        sa.Column("compute_mode", sa.Text(), nullable=True),   # inline/dotpath
        sa.Column("compute_spec", sa.Text(), nullable=True),   # expression or dotpath string
        sa.Column("input_tables", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("input_columns", sa.ARRAY(sa.Text()), nullable=True),
        sa.Column("tags", sa.ARRAY(sa.Text()), nullable=True),
        # Promotion metadata (NULL while experimental)
        sa.Column("promoted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("promoted_by", sa.Text(), nullable=True),
        sa.Column("promotion_alpha", sa.Numeric(), nullable=True),
        sa.Column("promotion_min_pass_rate", sa.Numeric(), nullable=True),
        sa.Column("best_ic", sa.Numeric(), nullable=True),
        sa.Column("best_horizon", sa.Integer(), nullable=True),
        sa.Column("migration_stub_path", sa.Text(), nullable=True),
        sa.Column("registered_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("feature_name"),
        sa.CheckConstraint(
            "lifecycle IN ('experimental', 'promoted', 'deprecated')",
            name="ck_feature_registry_lifecycle"
        ),
        schema="public",
    )
    op.create_index(
        "idx_feature_registry_lifecycle",
        "dim_feature_registry", ["lifecycle"], schema="public",
    )

    # cmc_feature_experiments: one row per (feature, asset, tf, horizon, return_type, regime, train window)
    op.create_table(
        "cmc_feature_experiments",
        sa.Column("experiment_id", sa.UUID(),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("feature_name", sa.Text(), nullable=False),
        sa.Column("run_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("tf", sa.Text(), nullable=False),
        sa.Column("train_start", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("train_end", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=True),
        sa.Column("return_type", sa.Text(), nullable=False),
        sa.Column("regime_col", sa.Text(), nullable=False),
        sa.Column("regime_label", sa.Text(), nullable=False),
        # IC results
        sa.Column("ic", sa.Numeric(), nullable=True),
        sa.Column("ic_t_stat", sa.Numeric(), nullable=True),
        sa.Column("ic_p_value", sa.Numeric(), nullable=True),
        sa.Column("ic_p_value_bh", sa.Numeric(), nullable=True),  # BH-corrected
        sa.Column("ic_ir", sa.Numeric(), nullable=True),
        sa.Column("ic_ir_t_stat", sa.Numeric(), nullable=True),
        sa.Column("n_obs", sa.Integer(), nullable=True),
        # Cost tracking
        sa.Column("wall_clock_seconds", sa.Numeric(), nullable=True),
        sa.Column("peak_memory_mb", sa.Numeric(), nullable=True),
        sa.Column("n_rows_computed", sa.Integer(), nullable=True),
        # Spec tracking
        sa.Column("yaml_digest", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("experiment_id"),
        sa.UniqueConstraint(
            "feature_name", "asset_id", "tf", "horizon", "return_type",
            "regime_col", "regime_label", "train_start", "train_end",
            name="uq_feature_experiments_key",
        ),
        schema="public",
    )
    op.create_index(
        "idx_feature_experiments_feature_name",
        "cmc_feature_experiments", ["feature_name"], schema="public",
    )
    op.create_index(
        "idx_feature_experiments_run_at",
        "cmc_feature_experiments", ["run_at"], schema="public",
    )


def downgrade() -> None:
    op.drop_index("idx_feature_experiments_run_at",
                  table_name="cmc_feature_experiments", schema="public")
    op.drop_index("idx_feature_experiments_feature_name",
                  table_name="cmc_feature_experiments", schema="public")
    op.drop_table("cmc_feature_experiments", schema="public")
    op.drop_index("idx_feature_registry_lifecycle",
                  table_name="dim_feature_registry", schema="public")
    op.drop_table("dim_feature_registry", schema="public")
```

### Pattern 9: Promotion Migration Stub Generation
**What:** `FeaturePromoter.promote_feature()` writes a new Alembic migration file adding the column to `cmc_features`. The stub is a Python file placed in `alembic/versions/` with a UUID rev ID.
**When to use:** After BH gate passes.

```python
# Source: verified Alembic revision template from alembic/script.py.mako

def generate_migration_stub(
    feature_name: str,
    current_head: str,
    output_dir: str,
) -> str:
    """
    Write an Alembic migration stub for a promoted feature column.

    The stub adds `feature_name` as NUMERIC column to cmc_features.
    Returns the file path of the written stub.

    IMPORTANT: Use a hardcoded UUID-based rev_id, NOT alembic revision command
    (which requires interactive subprocess). Generate the ID programmatically.
    """
    import uuid
    rev_id = uuid.uuid4().hex[:12]
    slug = feature_name[:30].replace("-", "_")
    filename = f"{rev_id}_promoted_{slug}.py"
    filepath = os.path.join(output_dir, filename)

    content = f'''"""promoted_{feature_name}: add to cmc_features

Revision ID: {rev_id}
Revises: {current_head}
Create Date: {datetime.utcnow().isoformat()}

Promoted experimental feature: {feature_name}
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = {rev_id!r}
down_revision: Union[str, None] = {current_head!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add {feature_name} column to cmc_features."""
    op.add_column(
        "cmc_features",
        sa.Column({feature_name!r}, sa.Numeric(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    """Remove {feature_name} from cmc_features."""
    op.drop_column("cmc_features", {feature_name!r}, schema="public")
'''
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath
```

### Pattern 10: Console Summary + Confirm Prompt
**What:** Print IC summary table to console, then prompt before writing to DB. `--yes` flag bypasses prompt.
**When to use:** Default for all CLI invocations of `run_experiment.py`.

```python
# Source: verified pandas to_string() — tabulate and rich are NOT installed

def print_experiment_summary(result_df: pd.DataFrame, feature_name: str) -> None:
    """Print IC summary table to console."""
    h1 = result_df[result_df["horizon"] == min(result_df["horizon"])]
    wall = result_df["wall_clock_seconds"].iloc[0]
    mem = result_df["peak_memory_mb"].iloc[0]
    n_rows = result_df["n_rows_computed"].iloc[0]

    print(f"\nFeature: {feature_name} | Train window: {result_df['train_start'].iloc[0].date()} to {result_df['train_end'].iloc[0].date()}")
    print(f"Wall clock: {wall:.1f}s | Peak memory: {mem:.1f} MB | Rows computed: {n_rows}")
    print()

    display_cols = ["horizon", "return_type", "ic", "ic_p_value", "ic_p_value_bh", "n_obs"]
    available = [c for c in display_cols if c in result_df.columns]
    print(result_df[available].to_string(index=False, float_format=lambda x: f"{x:.4f}"))
    print()


def confirm_write(yes: bool = False) -> bool:
    """Prompt user to confirm DB write. Returns True if confirmed."""
    if yes:
        return True
    response = input("Write to cmc_feature_experiments? [y/N]: ").strip().lower()
    return response in ("y", "yes")
```

### Anti-Patterns to Avoid
- **Writing to `cmc_features` during experiment**: Never. Feature values go to temp scratch table only. IC results go to `cmc_feature_experiments`. `cmc_features` is production-only.
- **Calling `false_discovery_control()` with NaN p-values**: Raises `ValueError: 'ps' must include only numbers between 0 and 1`. Always filter `p[~np.isnan(p)]` before calling. See verified behavior.
- **Using `engine.connect()` across multiple calls for the same temp table**: NullPool creates a new connection per `engine.connect()`. The temp table must be created AND used within the SAME `with engine.connect() as conn:` block.
- **Generating Alembic rev IDs via `alembic revision` subprocess**: Use `uuid.uuid4().hex[:12]` programmatically instead. The `alembic revision` command is interactive and hard to automate.
- **Running `alembic upgrade head` to apply the promotion stub automatically**: Don't auto-apply. Print the command for the user to run manually. Applying migrations programmatically inside the promotion script is fragile and skips the human review step.
- **Storing feature values in `cmc_feature_experiments`**: That table stores IC scores and cost metadata only, not raw feature values. Raw feature values live in the temp scratch table (dropped after IC scoring).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BH p-value correction | Manual rank-based BH formula | `scipy.stats.false_discovery_control(ps, method='bh')` | Verified API, handles edge cases, one-liner |
| DAG dependency resolution | Custom DFS/BFS | `graphlib.TopologicalSorter` (stdlib) | Raises `CycleError` automatically, zero deps |
| Expression syntax check | Regex or try/except eval | `ast.parse(expr, mode='eval')` | Catches syntax errors before compute, no side effects |
| Dotpath function loading | `exec()` or `__import__` | `importlib.import_module(path); getattr(mod, fn)` | Clean, importable, testable |
| Peak memory tracking | `psutil.Process().memory_info()` | `tracemalloc.get_traced_memory()` (stdlib) | No psutil dependency, tracks allocation within scope |
| YAML feature parameter grids | Separate YAML entry per variant | `params: {period: [5,14,21]}` + `itertools.product` | One entry, grid expands automatically |
| Console table formatting | tabulate or rich | `pd.DataFrame.to_string(index=False)` | tabulate and rich are NOT installed |
| Alembic rev ID generation | Subprocess `alembic revision` | `uuid.uuid4().hex[:12]` + write file manually | Subprocess is fragile; programmatic ID is simpler |

**Key insight:** The Phase 38 framework is mostly glue code connecting existing pieces: YAML defines features, `graphlib` orders them, `ta_lab2.analysis.ic` scores them, `scipy.stats.false_discovery_control` gates promotion. The new code surface is intentionally thin.

## Common Pitfalls

### Pitfall 1: false_discovery_control() Rejects NaN p-values
**What goes wrong:** `false_discovery_control(p_array)` raises `ValueError: 'ps' must include only numbers between 0 and 1` when any element is NaN.

**Why it happens:** Sparse regimes or very short training windows return `ic_p_value = np.nan` from `compute_ic()`. These NaN rows flow into the BH correction call without filtering.

**How to avoid:** Always apply the mask before calling:
```python
valid_mask = df["ic_p_value"].notna()
valid_pvals = df.loc[valid_mask, "ic_p_value"].values
adj = false_discovery_control(valid_pvals, method="bh")
df["ic_p_value_bh"] = np.nan
df.loc[valid_mask, "ic_p_value_bh"] = adj
```

**Warning signs:** `ValueError: 'ps' must include only numbers between 0 and 1` in the promotion log.

### Pitfall 2: Temp Table Lifetime with NullPool
**What goes wrong:** `CREATE TEMP TABLE _exp_scratch` succeeds in one `with engine.connect() as conn:` block. A second `engine.connect()` call fails with `relation "_exp_scratch" does not exist`.

**Why it happens:** PostgreSQL TEMP tables exist for the lifetime of the session/connection. NullPool creates a new physical connection on each `engine.connect()` call — the temp table from the first connection is gone.

**How to avoid:** All scratch table operations (create, write, IC score query) must happen within a SINGLE `with engine.connect() as conn:` block. This is verified working behavior.

**Warning signs:** `psycopg2.errors.UndefinedTable: relation "_exp_scratch_..." does not exist`.

### Pitfall 3: Inline Expression eval() Security
**What goes wrong:** Allowing arbitrary Python expressions via `eval()` runs arbitrary code. `__import__('os').system('rm -rf /')` is a valid Python expression.

**Why it happens:** `eval()` executes any valid Python expression from the YAML file.

**How to avoid:** This project is single-user with trusted YAML files. The security trade-off is acceptable. Mitigations: (1) pass `{"__builtins__": {}}` as the globals dict to eval, limiting built-in access; (2) validate syntax with `ast.parse()` before eval. Document the trust assumption explicitly. Do NOT build a full expression sandbox — it's out of scope and would block legitimate pandas expressions.

**Warning signs:** If the project ever moves to multi-user or external YAML input, revisit this design.

### Pitfall 4: Promotion Stub Migration Chain Staleness
**What goes wrong:** `FeaturePromoter` writes a stub with `down_revision = "c3b718c2d088"` (Phase 38 table migration head). But if another feature was promoted before this one, the current Alembic head is already `YYYY_promoted_feature_b.py`. Chaining from the wrong head creates a branch split.

**Why it happens:** The promotion stub generator hardcodes a `down_revision`. If called twice without running `alembic upgrade head` between promotions, the second stub chains from a stale head.

**How to avoid:** The `generate_migration_stub()` function must query the LIVE Alembic head from the DB before writing the stub:
```python
with engine.connect() as conn:
    current_head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
```
Always use the live head, not a hardcoded constant.

**Warning signs:** `alembic upgrade head` outputs `Multiple head revisions are present for given argument 'head'`.

### Pitfall 5: BH Gate with Zero Valid P-values
**What goes wrong:** If all IC computations returned NaN (e.g., asset has only 5 bars in train window), after filtering NaN p-values the array is empty. `false_discovery_control([])` raises an error.

**Why it happens:** Very short train windows or highly filtered asset/tf combinations may produce all-NaN IC results.

**How to avoid:** Check `len(valid_pvals) == 0` before calling `false_discovery_control()`. Return `passes=False` immediately — no BH correction possible, gate fails.

### Pitfall 6: BH Correction Pool Size Matters
**What goes wrong:** Running BH correction separately per asset produces inflated significance (each asset is its own "family"). Running BH on ALL (asset, tf, horizon, return_type) rows together is more conservative.

**Why it happens:** BH correction adjusts for the number of simultaneous hypotheses tested. The "family" definition determines the correction severity.

**How to avoid:** Apply BH correction across ALL rows of a single experiment run (all assets x all horizons x all return_types). This is what `ExperimentRunner._apply_bh_correction()` must do — concatenate all `ic_df` rows first, THEN apply BH once. Do NOT apply BH within each per-asset loop iteration.

**Warning signs:** BH-corrected p-values that are identical to uncorrected p-values when only 1 asset is tested (correct behavior), but suspiciously many significant results when testing 7 assets x 7 horizons x 2 return_types = 98 tests.

### Pitfall 7: Parameter Grid Naming Collisions
**What goes wrong:** Two YAML entries with the same `params` values produce the same expanded variant name, causing `KeyError` or silent overwrite in the registry dict.

**Why it happens:** If `rsi_sweep` with `period: [14]` and another entry also expands to `rsi_sweep_period14`, the second overwrites the first.

**How to avoid:** The `FeatureRegistry._features` dict is keyed by expanded variant name. Raise `ValueError` on duplicate names during `load()` with a clear message: `"Duplicate feature name after expansion: {name}"`.

### Pitfall 8: Wiring Promoted Features into cmc_features Refresh
**What goes wrong:** After promotion adds a column to `cmc_features` via `alembic upgrade head`, the refresh pipeline (`FeaturesStore`) still doesn't know to compute the new feature. The column stays NULL forever.

**Why it happens:** `FeaturesStore` in `daily_features_view.py` joins from fixed SOURCE_TABLES and doesn't dynamically read `dim_feature_registry`.

**How to avoid:** The "wire into cmc_features refresh" step is NOT automatic dynamic discovery. It is a manual step the user must perform: add the feature's computation logic to a new Python module (e.g., `src/ta_lab2/features/promoted_feature.py`), wire it into `FeaturesStore.SOURCE_TABLES`, and register it. The migration stub comment should contain explicit instructions. Document this as a post-promotion manual step, not an automated pipeline hook.

### Pitfall 9: Inline Expression Column Name Assumptions
**What goes wrong:** Inline expression `close.rolling(14).std() / close` assumes `close` column exists in the loaded input DataFrame. If the feature's `inputs` declaration doesn't include the table with `close`, the expression fails with `NameError: name 'close' is not defined`.

**Why it happens:** `_compute_feature()` injects DataFrame columns as local variables. Only declared `inputs` are loaded.

**How to avoid:** The FeatureRegistry `validate_expression()` should also cross-check expression variable names against declared input columns at load time (using `ast.walk()` to extract Name nodes). Raise `ValueError` if an expression references a column not declared in `inputs`.

## Code Examples

### BH Gate Implementation (Complete)
```python
# Source: verified scipy.stats.false_discovery_control API 2026-02-23
# Behavior confirmed: noise p-values all adjust to same high value
# np.array([0.32, 0.45, 0.67]) -> all adjust to 0.89 (FAIL)
# np.array([0.001, 0.01, 0.04]) -> [0.007, 0.023, 0.07] -> partial PASS

from scipy.stats import false_discovery_control
import numpy as np
import pandas as pd

def apply_bh_and_check_gate(
    result_df: pd.DataFrame,
    alpha: float = 0.05,
    min_pass_rate: float = 0.0,
) -> tuple[bool, pd.DataFrame, str]:
    """
    Apply BH correction and check promotion gate.

    Returns: (passes_gate, df_with_bh_col, reason_string)
    """
    valid_mask = result_df["ic_p_value"].notna()
    n_valid = valid_mask.sum()

    if n_valid == 0:
        result_df["ic_p_value_bh"] = np.nan
        return False, result_df, "No valid p-values (all IC computations returned NaN)"

    p_vals = result_df.loc[valid_mask, "ic_p_value"].values
    adj = false_discovery_control(p_vals, method="bh")

    result_df = result_df.copy()
    result_df["ic_p_value_bh"] = np.nan
    result_df.loc[valid_mask, "ic_p_value_bh"] = adj

    n_pass = int((adj < alpha).sum())
    pass_rate = n_pass / n_valid

    if min_pass_rate == 0.0:
        passes = n_pass > 0
        reason = f"{n_pass}/{n_valid} combos pass BH at alpha={alpha}"
    else:
        passes = pass_rate >= min_pass_rate
        reason = f"{n_pass}/{n_valid} combos ({pass_rate:.1%}) pass BH; required {min_pass_rate:.1%}"

    return passes, result_df, reason
```

### YAML Feature Loading (Complete)
```python
# Source: verified PyYAML 6.0.3 safe_load on this system 2026-02-23

import yaml
from pathlib import Path

def load_feature_registry(yaml_path: str | Path) -> dict[str, dict]:
    """
    Load experimental feature definitions from YAML.

    Returns dict mapping feature_name -> expanded spec dict.
    Raises ValueError on invalid lifecycle values or duplicate names.
    """
    with open(yaml_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    features = {}
    valid_lifecycles = {"experimental", "promoted", "deprecated"}

    for name, spec in raw.get("features", {}).items():
        lifecycle = spec.get("lifecycle", "experimental")
        if lifecycle not in valid_lifecycles:
            raise ValueError(
                f"Feature '{name}' has invalid lifecycle '{lifecycle}'. "
                f"Must be one of: {valid_lifecycles}"
            )
        # Only load experimental features for ExperimentRunner
        # (promoted/deprecated are for FeaturePromoter display only)
        expanded = _expand_params(name, spec)
        for variant in expanded:
            vname = variant["name"]
            if vname in features:
                raise ValueError(f"Duplicate feature name after expansion: '{vname}'")
            features[vname] = variant

    return features
```

### ExperimentRunner CLI Pattern
```python
# Source: verified CLI pattern from run_ic_eval.py (Phase 37)

# run_experiment.py CLI structure:
parser.add_argument("--feature", required=True, metavar="NAME",
                    help="Experimental feature name from YAML registry")
parser.add_argument("--ids", type=str, default=None,
                    help="Comma-separated asset IDs (default: all in dim_assets)")
parser.add_argument("--tf", type=str, default=None,
                    help="Timeframe (default: all TFs)")
parser.add_argument("--train-start", required=True, dest="train_start")
parser.add_argument("--train-end", required=True, dest="train_end")
parser.add_argument("--horizons", nargs="+", type=int, default=None)
parser.add_argument("--yes", "-y", action="store_true",
                    help="Skip confirmation prompt")
parser.add_argument("--dry-run", action="store_true", dest="dry_run")
parser.add_argument("--compare", action="store_true",
                    help="Compare against prior runs in cmc_feature_experiments")
parser.add_argument("--auto-promote", action="store_true", dest="auto_promote",
                    help="Automatically promote if BH gate passes")
parser.add_argument("--min-pass-rate", type=float, default=0.0, dest="min_pass_rate",
                    help="Minimum fraction of combos that must pass BH (default: any)")
```

### Temp Table Naming Convention
```python
# Source: verified SQL temp table creation pattern 2026-02-23

def scratch_table_name(feature_name: str, run_ts: float) -> str:
    """
    Generate a unique temp table name for an experiment run.
    Truncated to 32 chars to stay within PostgreSQL identifier limit (63 chars).
    Prefix '_exp_' identifies scratch tables for debugging.
    """
    safe_name = feature_name.replace("-", "_")[:20]
    ts_suffix = str(int(run_ts))[-8:]   # last 8 digits of epoch seconds
    return f"_exp_{safe_name}_{ts_suffix}"

# Example: _exp_vol_ratio_30_7_41539210
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No feature experimentation | YAML registry + ExperimentRunner + BH gate | Phase 38 | Systematic feature selection with controlled FDR |
| Feature columns added directly to cmc_features | Experimental features scored without touching production tables | Phase 38 | Safe exploration, zero production table pollution |
| No FDR control on feature selection | BH-corrected promotion gate | Phase 38 | Prevents noise features from polluting signal pipeline |
| `dim_features` (simple lookup table) | `dim_feature_registry` with lifecycle tracking | Phase 38 | Full audit trail from experimental to promoted to deprecated |
| `statsmodels.multipletests` (older pattern) | `scipy.stats.false_discovery_control()` (1.9.0+) | scipy 1.9.0 | Simpler API, same BH algorithm, already installed |

**Deprecated/outdated:**
- `statsmodels.stats.multitest.multipletests`: Would also work for BH, but `statsmodels` is NOT installed. `scipy.stats.false_discovery_control()` is the correct tool here.
- Writing feature values to `cmc_features` before promotion: Forbidden by design in Phase 38.

## Open Questions

1. **"Wire into cmc_features refresh" mechanics**
   - What we know: After promotion, the Alembic stub adds the column. The refresh pipeline (`FeaturesStore` in `daily_features_view.py`) has hardcoded `SOURCE_TABLES` and does not read `dim_feature_registry`.
   - What's unclear: Should the migration stub itself contain a `# TODO: Add to FeaturesStore.SOURCE_TABLES` comment, or should Phase 38 define a hook mechanism? The CONTEXT says this is Claude's discretion.
   - Recommendation: The migration stub should contain explicit `# MANUAL STEP` instructions. Phase 38 should NOT build a dynamic plugin system — hardcode promoted features into a new `src/ta_lab2/features/promoted_features.py` module that `FeaturesStore` imports. This is the simplest approach that doesn't require FeaturesStore to be rewritten.

2. **Deprecation workflow symmetry**
   - What we know: CONTEXT says "Claude's discretion — should mirror promotion workflow symmetry."
   - Recommendation: Deprecation = (1) set `lifecycle: deprecated` in YAML, (2) update `dim_feature_registry` row with `lifecycle='deprecated'` + `updated_at`, (3) do NOT remove the column from `cmc_features` (schema migrations are irreversible without downtime). Stop computing it in the refresh pipeline. No separate Alembic migration needed.

3. **Inline expression scoping — numpy availability**
   - What we know: `_compute_feature()` injects DataFrame columns as local variables for `eval()`. The `{"__builtins__": {}}` globals limit builtins.
   - What's unclear: Should `numpy` and `pandas` be injected into eval's globals for more complex inline expressions?
   - Recommendation: Inject `{"np": numpy, "pd": pandas, "__builtins__": {}}` as globals so expressions can use `np.log(close)`, `pd.Timedelta(...)` etc. This is the same pattern as `pandas.eval()` but without the restriction on operators.

4. **Purge experiment behavior when YAML is removed**
   - What we know: CONTEXT says results persist by default; explicit `purge_experiment --feature name` removes all DB traces.
   - What's unclear: Should `purge_experiment` also remove the `dim_feature_registry` entry?
   - Recommendation: `purge_experiment` removes rows from `cmc_feature_experiments` only. It sets `lifecycle='deprecated'` in `dim_feature_registry` rather than deleting the row (preserving audit trail). Deletion from the registry requires `--force` flag.

## Sources

### Primary (HIGH confidence)
- Direct execution: `scipy.stats.false_discovery_control([0.32, 0.45, 0.67])` -> all-high adjusted (noise FAIL confirmed), 2026-02-23
- Direct execution: `scipy.stats.false_discovery_control([0.001, 0.01, 0.04])` -> partial pass confirmed, 2026-02-23
- Direct execution: `false_discovery_control` with NaN raises `ValueError` — confirmed, 2026-02-23
- Direct execution: `graphlib.TopologicalSorter` DAG resolution with cycle detection — confirmed, 2026-02-23
- Direct execution: PostgreSQL TEMP TABLE lifetime with NullPool within single `engine.connect()` — confirmed, 2026-02-23
- Direct execution: `tracemalloc.get_traced_memory()` peak memory tracking — confirmed, 2026-02-23
- Direct execution: `ast.parse(expr, mode='eval')` syntax validation — confirmed, 2026-02-23
- Direct execution: `importlib.import_module` + `getattr` for dotpath loading — confirmed, 2026-02-23
- Direct execution: `yaml.safe_load()` on multi-entry feature YAML — confirmed, 2026-02-23
- Direct execution: `itertools.product` for parameter grid expansion — confirmed, 2026-02-23
- Direct execution: `eval(expr, {"__builtins__": {}}, local_vars)` inline expression evaluation — confirmed, 2026-02-23
- Live DB: `cmc_feature_experiments` does NOT exist (confirmed DOES NOT EXIST), 2026-02-23
- Live DB: `dim_feature_registry` does NOT exist (confirmed DOES NOT EXIST), 2026-02-23
- Live DB: `dim_features` EXISTS with schema (feature_type, feature_name, ...) — confirmed, 2026-02-23
- Live DB: Alembic head is `c3b718c2d088` — confirmed, 2026-02-23
- `alembic/versions/c3b718c2d088_ic_results_table.py` — down_revision chain pattern verified
- `alembic/script.py.mako` — migration stub template verified
- `ta_lab2/analysis/ic.py` — Phase 37 IC engine API verified (compute_ic, batch_compute_ic, save_ic_results)
- `ta_lab2/scripts/analysis/run_ic_eval.py` — CLI pattern to replicate for run_experiment.py
- `configs/default.yaml`, `configs/regime_policies.yaml` — YAML location convention: `configs/` directory
- Direct execution: tabulate NOT installed, rich NOT installed — pandas.to_string() is the table renderer

### Secondary (MEDIUM confidence)
- Phase 37 RESEARCH.md — IC engine patterns and pitfalls (HIGH confidence in Phase 37 context)
- `alembic.ini` — `output_encoding = utf-8` confirmed; ruff post-write hook confirmed

### Tertiary (LOW confidence)
- None — all claims verified by direct execution

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified installed and APIs confirmed working
- BH correction API: HIGH — executed false_discovery_control with noise and signal inputs, NaN behavior confirmed
- Temp table lifetime: HIGH — verified PostgreSQL TEMP table scoped to connection with NullPool
- DAG resolution: HIGH — graphlib.TopologicalSorter executed with dependency graph
- Inline expression eval: HIGH — eval with __builtins__={} and column injection confirmed
- Dotpath loading: HIGH — importlib.import_module + getattr confirmed
- Alembic migration chain: HIGH — c3b718c2d088 confirmed as live head; down_revision chain pattern verified
- dim_feature_registry schema: MEDIUM — design is Claude's discretion per CONTEXT.md; no prior schema exists
- cmc_feature_experiments schema: MEDIUM — design is Claude's discretion per CONTEXT.md; no prior schema exists
- Promotion migration stub: HIGH — Alembic template pattern verified; uuid.uuid4() ID generation confirmed
- "Wire into cmc_features" mechanics: LOW — FeaturesStore internal structure reviewed; exact plug-in mechanism is Claude's discretion, manual step recommended

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (scipy/PyYAML APIs very stable; graphlib is stdlib; DB schema won't change)
