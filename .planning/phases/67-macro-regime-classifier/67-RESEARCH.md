# Phase 67: Macro Regime Classifier - Research

**Researched:** 2026-03-01
**Domain:** Rule-based macro regime labeling, hysteresis, YAML config, Alembic migration, daily refresh orchestration
**Confidence:** HIGH

---

## Summary

Phase 67 builds a rule-based macro regime labeler that reads daily macro features from `fred.fred_macro_features` (populated by Phase 65-66) and produces 4-dimensional composite regime labels stored in `cmc_macro_regimes`. All required infrastructure is in place: `HysteresisTracker` exists and is reusable, the `policy_loader.py` YAML-loading pattern is established, Alembic migration structure is well-understood, and `run_daily_refresh.py` already has the correct pipeline slot for macro regime refresh (after `--macro`, before `--regimes`).

The codebase already has the exact tools needed:

1. `HysteresisTracker` in `ta_lab2/regimes/hysteresis.py` — per-layer state, hold-on-loosening / tighten-immediately semantics, works with arbitrary string layer keys
2. `policy_loader.py` with `load_policy_table()` — YAML-to-dict loading with project_root discovery, extensible pattern
3. `compose_regime_key()` in `regimes/labels.py` — dash-joined string composition (model for the macro composite key)
4. `resolve_policy_from_table()` in `regimes/resolver.py` — substring-based matching on composite keys (the downstream L4 resolver uses this same API)
5. Alembic migration chain: newest revision is `b3c4d5e6f7a8` (Phase 65 fred_macro_features). Phase 66 will add its own revision. Phase 67 migration must revise Phase 66's revision ID.

Phase 66 delivers the following columns to `fred.fred_macro_features` that Phase 67 needs:
- Monetary policy: `dff` (raw), `fed_regime_trajectory` ('hiking'/'holding'/'cutting')
- Liquidity: `net_liquidity`, `net_liquidity_30d_change`, `net_liquidity_30d_zscore`
- Risk appetite: `vixcls` (raw), `hy_oas_level`, `hy_oas_30d_zscore`, `nfci_level`
- Carry: `dexjpus_level`, `dexjpus_daily_zscore`, `dexjpus_20d_vol`, `dexjpus_5d_pct_change`, `us_jp_rate_spread`

**Primary recommendation:** Build `ta_lab2/macro/regime_classifier.py` as the core module, persist hysteresis state to a `cmc_macro_hysteresis_state` table (keyed on `(profile, dimension)`), store results in `cmc_macro_regimes` (public schema), use `configs/macro_regime_config.yaml` for all thresholds + profiles, and wire the refresh into `run_daily_refresh.py` via a new `run_macro_regimes()` function between `run_macro_features()` and `run_regime_refresher()`.

---

## Standard Stack

All tools are already present in the project. No new dependencies.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pandas | 2.x | DataFrame ops, rolling windows, z-score computation | All existing feature/regime code uses pandas |
| sqlalchemy | 2.x | Engine, text(), upsert patterns | Project-wide DB convention |
| PyYAML | installed | YAML config loading | Already used in `policy_loader.py` |
| alembic | installed | Schema migration | All schema changes go through Alembic |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| numpy | installed | NaN checks, scalar coercion (`hasattr(v, 'item')`) | `_to_python()` pattern in `refresh_macro_features.py` |

**Installation:** No new packages needed.

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/macro/
├── __init__.py                  # Add MacroRegimeClassifier to exports
├── feature_computer.py          # (Phase 65-66, unchanged)
├── forward_fill.py              # (Phase 65-66, unchanged)
├── fred_reader.py               # (Phase 65-66, unchanged)
└── regime_classifier.py         # NEW: MacroRegimeClassifier + dimension labelers

src/ta_lab2/scripts/macro/
├── refresh_macro_features.py    # (Phase 65-66, unchanged)
└── refresh_macro_regimes.py     # NEW: CLI for macro regime refresh

configs/
└── macro_regime_config.yaml     # NEW: thresholds + hysteresis + profiles

alembic/versions/
└── XXXX_macro_regime_tables.py  # NEW: cmc_macro_regimes + cmc_macro_hysteresis_state
```

### Pattern 1: MacroRegimeClassifier (core module)

The classifier loads from `fred.fred_macro_features`, applies dimension-by-dimension rules, runs `HysteresisTracker` per dimension, composes the composite key, and returns a DataFrame ready for upsert.

```python
# Source: ta_lab2/regimes/hysteresis.py pattern (direct reuse)
from ta_lab2.regimes.hysteresis import HysteresisTracker

class MacroRegimeClassifier:
    def __init__(self, config: dict, engine: Engine):
        self.config = config          # loaded from YAML
        self.engine = engine
        self.tracker = HysteresisTracker(
            min_bars_hold=config["hysteresis"]["min_bars_hold"]
        )

    def classify(self, df: pd.DataFrame) -> pd.DataFrame:
        """df: fred.fred_macro_features rows (date index, daily).
        Returns: cmc_macro_regimes-shaped DataFrame."""
        rows = []
        for date, row in df.iterrows():
            raw = {
                "monetary_policy": self._label_monetary(row),
                "liquidity": self._label_liquidity(row),
                "risk_appetite": self._label_risk_appetite(row),
                "carry": self._label_carry(row),
            }
            # Apply hysteresis per dimension
            effective = {}
            for dim, raw_label in raw.items():
                if raw_label is not None:
                    effective[dim] = self.tracker.update(dim, raw_label)
                else:
                    effective[dim] = self.tracker.get_current(dim)
            ...
```

### Pattern 2: Dimension labeling functions (pure functions, threshold-driven)

Each dimension labeler takes a row (pandas Series from `fred.fred_macro_features`) and a thresholds dict from the loaded YAML profile. Returns a string label.

```python
# Source: informed by MREG-02 through MREG-05 requirements

def _label_monetary(row, thresholds) -> str | None:
    # Uses fed_regime_trajectory column from Phase 66 (already computed)
    # OR falls back to DFF 90d change computation if trajectory col absent
    traj = row.get("fed_regime_trajectory")
    if pd.isna(traj):
        return None
    # Trajectory is already 'hiking'/'holding'/'cutting' from Phase 66 FRED-13
    return traj  # "Hiking", "Cutting", or "Holding" (normalize capitalization)

def _label_liquidity(row, thresholds) -> str | None:
    # net_liquidity_30d_change and net_liquidity_30d_zscore from Phase 66
    zscore = row.get("net_liquidity_30d_zscore")
    change = row.get("net_liquidity_30d_change")
    if pd.isna(change):
        return None
    # 5-state: strongly_expanding, expanding, neutral, contracting, strongly_contracting
    if not pd.isna(zscore) and zscore > thresholds["strongly_expanding_z"]:
        return "Strongly_Expanding"
    elif change > thresholds["expanding_min"]:
        return "Expanding"
    elif change < thresholds["contracting_max"]:
        return "Contracting"
    ...

def _label_risk_appetite(row, thresholds) -> str | None:
    # VIX absolute + HY OAS z-score + NFCI absolute (MREG-04)
    vix = row.get("vixcls")
    hy_z = row.get("hy_oas_30d_zscore")
    nfci = row.get("nfci_level")
    ...

def _label_carry(row, thresholds) -> str | None:
    # DEXJPUS daily_zscore + 20d_vol (MREG-05)
    daily_z = row.get("dexjpus_daily_zscore")
    vol_z = row.get("dexjpus_20d_vol")  # compared to threshold
    ...
```

### Pattern 3: YAML config with named profiles

Follow the `policy_loader.py` pattern for file discovery. The YAML uses named profiles with a default selector.

```yaml
# configs/macro_regime_config.yaml
active_profile: default

hysteresis:
  min_bars_hold: 5        # >= 5 per MREG-07; applies per-dimension
  # tighten-immediately semantics are dimension-agnostic (risk-off = tighten)

profiles:
  default:
    monetary_policy:
      hiking_threshold: 0.25      # DFF 90d change > this -> Hiking
      cutting_threshold: -0.25    # DFF 90d change < this -> Cutting
    liquidity:
      strongly_expanding_z: 1.0   # net_liquidity_30d_zscore
      strongly_contracting_z: -1.0
      expanding_min: 0.0          # net_liquidity_30d_change > 0 -> Expanding
      contracting_max: 0.0
    risk_appetite:
      vix_risk_off: 25.0
      vix_risk_on: 15.0
      hy_oas_z_risk_off: 1.5
      hy_oas_z_risk_on: -0.5
      nfci_risk_off: 0.5
      nfci_risk_on: -0.5
    carry:
      unwind_zscore: 2.0          # dexjpus_daily_zscore > this + spread narrowing
      stress_vol_zscore: 1.5      # dexjpus_20d_vol z-score > this
  conservative:
    # All thresholds tighter (triggers regime change sooner)
    monetary_policy:
      hiking_threshold: 0.15
      cutting_threshold: -0.15
    ...
  aggressive:
    monetary_policy:
      hiking_threshold: 0.50
      cutting_threshold: -0.50
    ...

macro_state_rules:
  # Bucketing from composite key to 5-state macro_state
  favorable:
    - "Cutting-Expanding-RiskOn"
    - "Cutting-Strongly_Expanding-RiskOn"
    - "Holding-Expanding-RiskOn"
  constructive:
    - "Hiking-Expanding-RiskOn"
    - "Cutting-Neutral-RiskOn"
    - "Holding-Neutral-RiskOn"
  neutral:
    - "Holding-Neutral-Neutral"
    - "Hiking-Neutral-Neutral"
    - "Cutting-Neutral-Neutral"
  cautious:
    - "Hiking-Contracting-RiskOn"
    - "Cutting-Expanding-RiskOff"
    - "Holding-Contracting-Neutral"
  adverse:
    - "Hiking-Contracting-RiskOff"
    - "Cutting-Contracting-RiskOff"
    - "Holding-Contracting-RiskOff"
  # Default if no rule matches
  _default: neutral
```

### Pattern 4: Hysteresis state persistence in DB

The `HysteresisTracker` is in-memory only. For incremental resume across daily runs, persist the tracker's internal state (`_current`, `_pending`, `_pending_count`) to `cmc_macro_hysteresis_state`.

```python
# Source: informed by dim_risk_state single-row pattern (b5178d671e38_risk_controls.py)

def save_hysteresis_state(engine, tracker: HysteresisTracker, profile: str) -> None:
    """Persist tracker._current, _pending, _pending_count to DB per dimension."""
    rows = []
    for layer in tracker._current:
        rows.append({
            "profile": profile,
            "dimension": layer,
            "current_label": tracker._current[layer],
            "pending_label": tracker._pending.get(layer),
            "pending_count": tracker._pending_count.get(layer, 0),
            "updated_at": pd.Timestamp.now("UTC"),
        })
    # Upsert via temp table + ON CONFLICT (profile, dimension) DO UPDATE

def load_hysteresis_state(engine, tracker: HysteresisTracker, profile: str) -> None:
    """Restore tracker state from DB. Skips unknown dimensions."""
    rows = query_cmc_macro_hysteresis_state(engine, profile)
    for row in rows:
        tracker._current[row.dimension] = row.current_label
        tracker._pending[row.dimension] = row.pending_label
        tracker._pending_count[row.dimension] = row.pending_count
```

### Pattern 5: DB write pattern (upsert via ON CONFLICT)

Follow the `upsert_macro_features()` pattern from `refresh_macro_features.py` exactly.

```python
# Source: ta_lab2/scripts/macro/refresh_macro_features.py

def upsert_macro_regimes(engine, df: pd.DataFrame) -> int:
    """Upsert cmc_macro_regimes using temp table + ON CONFLICT (date, profile) DO UPDATE."""
    df = df.reset_index()
    df = _sanitize_dataframe(df)  # NaN->None, numpy->Python
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TEMP TABLE _macro_regime_staging "
            "(LIKE cmc_macro_regimes INCLUDING DEFAULTS) ON COMMIT DROP"
        ))
        df.to_sql("_macro_regime_staging", conn, if_exists="append", index=False, method="multi")
        conn.execute(text(
            "INSERT INTO cmc_macro_regimes (...) SELECT ... FROM _macro_regime_staging "
            "ON CONFLICT (date, profile) DO UPDATE SET ..."
        ))
```

### Pattern 6: Composite key composition

Follow `compose_regime_key()` from `regimes/labels.py` (dash-jointed, title-cased parts).

```python
# Source: ta_lab2/regimes/labels.py
def compose_macro_regime_key(monetary: str, liquidity: str, risk: str, carry: str) -> str:
    """E.g. 'Cutting-Expanding-RiskOn-Stable'"""
    return f"{monetary}-{liquidity}-{risk}-{carry}"
```

Dimension ordering (fixed): `monetary_policy` - `liquidity` - `risk_appetite` - `carry`
This matches the MREG-06 example: `Cutting-Expanding-RiskOn-Stable`.

### Pattern 7: Daily refresh integration

Add `run_macro_regimes()` to `run_daily_refresh.py` in the same subprocess-call style as `run_macro_features()`. Insert between macro features and per-asset regimes:

```
... -> macro_features -> macro_regimes (NEW) -> regimes -> features -> signals -> ...
```

Add `--macro-regimes` flag and `--no-macro-regimes` skip flag. Include in `--all` mode.

### Anti-Patterns to Avoid

- **Hardcoding thresholds in Python:** All numeric thresholds must live in YAML. If threshold is hardcoded, changing it requires a code deploy and does not satisfy MREG-08.
- **In-memory-only hysteresis:** If the daily process restarts, pure in-memory state is lost. Always persist to `cmc_macro_hysteresis_state` after computing each day's regimes.
- **Full-recompute on every run:** The `cmc_macro_regimes` PK is `(date, profile)`. Only recompute from the watermark minus a warmup window (same pattern as `refresh_macro_features.py`). Full-recompute is only needed on `--full` flag or first run.
- **Using `_u` (unified) tables for z-scores:** Z-scores are pre-computed in `fred.fred_macro_features` by Phase 66. Read them directly, do not recompute.
- **Dimensions with `is_tightening` from the asset-regime policy table:** The macro classifier does NOT use `is_tightening_change()` from `resolver.py` (that function reads `DEFAULT_POLICY_TABLE` which maps per-asset regime keys, not macro keys). Instead, define simple tighten-direction logic: risk-off / cautious / adverse transitions tighten immediately; risk-on / favorable transitions require hold.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hysteresis tracking | Custom counter dict | `HysteresisTracker` from `ta_lab2/regimes/hysteresis.py` | Already exists, tested, works with arbitrary layer keys |
| YAML loading with project root discovery | Custom path search | `load_policy_table()` pattern from `regimes/policy_loader.py` | Project root discovery logic is already solved |
| Temp table upsert | Direct INSERT with loop | `CREATE TEMP TABLE (LIKE ...) + ON CONFLICT DO UPDATE` pattern | Exact pattern in `upsert_macro_features()` in `refresh_macro_features.py` |
| NaN / numpy scalar safety | Custom type checks | `_to_python()` + `_sanitize_dataframe()` from `refresh_macro_features.py` | Copy these helpers directly; psycopg2 binding breaks without them |
| Watermark-based incremental refresh | Timestamp comparison in app | Query `MAX(date) FROM cmc_macro_regimes` + subtract warmup days | Exact pattern in `get_compute_window()` |
| Pipeline integration | New orchestration mechanism | Subprocess call pattern in `run_daily_refresh.py` | All other pipeline stages use the same `subprocess.run()` approach |

---

## Common Pitfalls

### Pitfall 1: Phase 66 column names may differ from plan
**What goes wrong:** Research identified expected Phase 66 column names (`fed_regime_trajectory`, `net_liquidity_30d_zscore`, `hy_oas_30d_zscore`, `nfci_level`, `dexjpus_daily_zscore`, `dexjpus_20d_vol`) from the Phase 66 PLAN.md. If Phase 66 chose different names, Phase 67's SELECT queries will return NaN/NULL.
**Why it happens:** Phase 66 is not yet verified complete (no 66-VERIFICATION.md found). The implementation may deviate from plan.
**How to avoid:** In Wave 1 of Phase 67, query `fred.fred_macro_features` column list from information_schema before writing classifier logic. Fail hard (raise) if required columns are absent (per CONTEXT.md strict dependency rule).
**Warning signs:** Classifier produces only None/NULL labels; query returns empty result for expected columns.

### Pitfall 2: Alembic revision chain gap
**What goes wrong:** Phase 67 migration must revise Phase 66's revision ID. If Phase 66 migration is not yet committed (its revision ID is unknown), Phase 67 migration cannot be written.
**Why it happens:** Phase 66's migration file (`c4d5e6f7a8b9_fred_phase66_derived_columns.py`) was planned but its revision ID `c4d5e6f7a8b9` is from the plan doc, not yet confirmed as the actual head.
**How to avoid:** In Wave 1, run `alembic heads` to confirm current migration head before writing Phase 67 migration. The Phase 67 migration's `down_revision` must match the actual Phase 66 head revision.

### Pitfall 3: HysteresisTracker layer key conflict
**What goes wrong:** `HysteresisTracker` uses a dict keyed by layer string. If Phase 67 uses layer keys 'monetary_policy', 'liquidity', 'risk_appetite', 'carry' and the asset regime system uses 'L0', 'L1', 'L2', there is no conflict since they are separate instances. But if the same tracker instance is accidentally shared, state bleeds across dimension types.
**Why it happens:** The existing `refresh_cmc_regimes.py` creates one `HysteresisTracker` per asset run and calls `tracker.reset()` between assets. The macro classifier creates one tracker for the entire macro timeline and must NOT reset it between daily runs.
**How to avoid:** Create a dedicated `HysteresisTracker` instance in `MacroRegimeClassifier.__init__()`, never share with per-asset regime code.

### Pitfall 4: is_tightening semantics for macro dimensions
**What goes wrong:** Using `is_tightening_change()` from `hysteresis.py` for macro dimensions will read `DEFAULT_POLICY_TABLE` (per-asset market regimes), compare `size_mult` values on keys like 'Cutting-Expanding-RiskOn-Stable' which will NOT match any entry in `DEFAULT_POLICY_TABLE`, causing the function to always return `True` (the fallback), meaning every macro regime change is treated as tightening (accepted immediately).
**Why it happens:** `is_tightening_change()` resolves policy from `DEFAULT_POLICY_TABLE` which has per-asset market regime keys like 'Up-Normal-Normal', 'Down-'. Macro composite keys do not match.
**How to avoid:** Define a simple macro-specific tighten function: risk-off/adverse transitions tighten immediately; risk-on/favorable transitions require hold. Pass `is_tightening=True` for adverse transitions explicitly.

### Pitfall 5: Profile selector and DB uniqueness
**What goes wrong:** If the table PK is only `(date)`, running with profile='conservative' will conflict with profile='default' rows for the same date.
**Why it happens:** Named profiles (from CONTEXT.md decision) mean multiple rows can exist per date.
**How to avoid:** PK must be `(date, profile)` on `cmc_macro_regimes`. The hysteresis state table PK is `(profile, dimension)`.

### Pitfall 6: NaN propagation on missing Phase 66 inputs
**What goes wrong:** If `dexjpus_daily_zscore` is NaN (not yet computed or missing for a date), the carry dimension returns None, the composite key becomes something like 'Cutting-Expanding-RiskOn-None', breaking downstream string matching.
**Why it happens:** Phase 66 derives z-scores from rolling windows that need warmup. Early dates in the history have NaN z-scores.
**How to avoid:** Dimension labelers must return None (not 'None' the string) on NaN inputs. Composite key builder must skip None dimensions or substitute a sentinel like 'Unknown'. Hysteresis tracker handles `None` as "no update" (return current state).

---

## Code Examples

### Loading macro features for classification

```python
# Source: informed by feature_computer.py and refresh_macro_features.py patterns

def load_macro_features_for_classification(
    engine: Engine,
    start_date: str,
    end_date: str,
    profile: str,
) -> pd.DataFrame:
    """Load fred.fred_macro_features rows for the given date range."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT date,
                   dff, fed_regime_trajectory,
                   net_liquidity, net_liquidity_30d_change, net_liquidity_30d_zscore,
                   vixcls, hy_oas_level, hy_oas_30d_zscore, nfci_level,
                   dexjpus_level, dexjpus_daily_zscore, dexjpus_20d_vol,
                   dexjpus_5d_pct_change, us_jp_rate_spread
            FROM fred.fred_macro_features
            WHERE date >= :start AND date <= :end
            ORDER BY date ASC
        """), {"start": start_date, "end": end_date})
        rows = result.fetchall()
    df = pd.DataFrame(rows, columns=result.keys())
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")
```

### Failing hard on missing Phase 66 columns

```python
# Source: strict dependency per 67-CONTEXT.md decisions

_REQUIRED_COLUMNS = {
    "monetary_policy": ["dff", "fed_regime_trajectory"],
    "liquidity": ["net_liquidity_30d_change", "net_liquidity_30d_zscore"],
    "risk_appetite": ["vixcls", "hy_oas_30d_zscore", "nfci_level"],
    "carry": ["dexjpus_daily_zscore", "dexjpus_20d_vol"],
}

def validate_feature_columns(df: pd.DataFrame) -> None:
    """Raise ValueError if any required dimension columns are absent."""
    for dim, cols in _REQUIRED_COLUMNS.items():
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise ValueError(
                f"Dimension '{dim}' requires columns {missing} which are absent "
                f"from fred.fred_macro_features. Run Phase 66 refresh first."
            )
```

### Hysteresis state load/save

```python
# Source: pattern informed by dim_risk_state (b5178d671e38_risk_controls.py)

def load_hysteresis_state(engine, tracker: HysteresisTracker, profile: str) -> None:
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT dimension, current_label, pending_label, pending_count "
            "FROM cmc_macro_hysteresis_state WHERE profile = :profile"
        ), {"profile": profile})
        for row in result:
            d = row.dimension
            tracker._current[d] = row.current_label
            tracker._pending[d] = row.pending_label
            tracker._pending_count[d] = row.pending_count or 0

def save_hysteresis_state(engine, tracker: HysteresisTracker, profile: str) -> None:
    rows = [
        {
            "profile": profile,
            "dimension": d,
            "current_label": tracker._current[d],
            "pending_label": tracker._pending.get(d),
            "pending_count": tracker._pending_count.get(d, 0),
            "updated_at": pd.Timestamp.now("UTC"),
        }
        for d in tracker._current
    ]
    if not rows:
        return
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM cmc_macro_hysteresis_state WHERE profile = :p"),
                     {"p": profile})
        conn.execute(text(
            "INSERT INTO cmc_macro_hysteresis_state "
            "(profile, dimension, current_label, pending_label, pending_count, updated_at) "
            "VALUES (:profile, :dimension, :current_label, :pending_label, :pending_count, :updated_at)"
        ), rows)
```

### Alembic migration pattern for cmc_macro_regimes

```python
# Source: modeled on a1b2c3d4e5f6_fred_macro_features.py and b5178d671e38_risk_controls.py

def upgrade() -> None:
    # Table 1: cmc_macro_regimes -- one row per (date, profile)
    op.create_table(
        "cmc_macro_regimes",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("profile", sa.Text(), nullable=False, server_default=sa.text("'default'")),
        # Per-dimension labels
        sa.Column("monetary_policy", sa.Text(), nullable=True),
        sa.Column("liquidity", sa.Text(), nullable=True),
        sa.Column("risk_appetite", sa.Text(), nullable=True),
        sa.Column("carry", sa.Text(), nullable=True),
        # Composite key (e.g., 'Cutting-Expanding-RiskOn-Stable')
        sa.Column("regime_key", sa.Text(), nullable=True),
        # Bucketed 5-state macro state
        sa.Column("macro_state", sa.Text(), nullable=True),
        # Provenance / audit
        sa.Column("regime_version_hash", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("date", "profile"),
    )
    op.create_index("idx_cmc_macro_regimes_date", "cmc_macro_regimes",
                    [sa.text("date DESC")])

    # Table 2: cmc_macro_hysteresis_state -- persisted tracker state
    op.create_table(
        "cmc_macro_hysteresis_state",
        sa.Column("profile", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("current_label", sa.Text(), nullable=True),
        sa.Column("pending_label", sa.Text(), nullable=True),
        sa.Column("pending_count", sa.Integer(), nullable=False,
                  server_default=sa.text("0")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("profile", "dimension"),
    )
```

### Macro state bucketing

```python
# Source: CONTEXT.md decision -- 5 states, YAML rule-based

def compute_macro_state(regime_key: str, rules: dict) -> str:
    """Map composite key to 5-state macro_state using prefix-match rules from YAML."""
    for state in ("favorable", "constructive", "neutral", "cautious", "adverse"):
        patterns = rules.get(state, [])
        for pat in patterns:
            if regime_key.startswith(pat):
                return state
    return rules.get("_default", "neutral")
```

### run_daily_refresh.py integration

```python
# Source: run_daily_refresh.py -- add this function in the same style as run_macro_features()

def run_macro_regimes(args) -> ComponentResult:
    """Run macro regime classification via subprocess.
    Runs after macro features, before per-asset regime refresh."""
    cmd = [sys.executable, "-m", "ta_lab2.scripts.macro.refresh_macro_regimes"]
    if getattr(args, "dry_run", False):
        cmd.append("--dry-run")
    if getattr(args, "verbose", False):
        cmd.append("--verbose")
    # profile selector propagation
    if getattr(args, "macro_regime_profile", None):
        cmd.extend(["--profile", args.macro_regime_profile])
    ...
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| Hardcoded VIX bins in feature_computer.py (`_VIX_BINS = [0.0, 15.0, 25.0]`) | YAML-configurable thresholds per profile | Phase 67 externalizes all thresholds |
| HysteresisTracker in-memory only (per-asset reset) | DB-persisted state for incremental resume | New requirement per 67-CONTEXT.md |
| Per-asset L0/L1/L2 composite key (trend-vol-liq) | Per-macro-date 4-dimensional key (mon-liq-risk-carry) | Parallel structure, different domain |

**Note on Phase 66 completion status:** Phase 66 does NOT have a VERIFICATION.md yet. The column names (`fed_regime_trajectory`, `net_liquidity_30d_zscore`, etc.) are from the Phase 66 PLAN.md but may not be confirmed. Wave 1 of Phase 67 must verify actual DB schema before writing classifier logic.

---

## Open Questions

1. **Phase 66 completion status**
   - What we know: Phase 66 has PLAN.md files but no VERIFICATION.md
   - What's unclear: Whether `fred.fred_macro_features` has all Phase 66 columns in DB
   - Recommendation: Wave 1 task queries `information_schema.columns WHERE table_name = 'fred_macro_features'` and fails hard if required columns are absent. Do NOT assume Phase 66 is complete.

2. **Phase 66 Alembic revision ID**
   - What we know: Phase 66 planned revision `c4d5e6f7a8b9` but may not be applied
   - What's unclear: Actual current alembic head
   - Recommendation: Wave 1 migration task runs `alembic heads` first; hardcode the confirmed head as `down_revision`.

3. **Tighten-direction semantics for macro dimensions**
   - What we know: `HysteresisTracker` supports `is_tightening` boolean per `update()` call
   - What's unclear: Which macro transitions should bypass hold (tighten-immediately)
   - Recommendation (Claude's discretion): Risk-off/adverse transitions always tighten immediately. Risk-on/favorable transitions require full hold period. This is consistent with the asset-regime pattern where risk-reducing changes bypass hold.

4. **Additional Phase 66 features for carry dimension**
   - What we know: MREG-05 requires `DEXJPUS daily > 2 sigma AND spread narrowing`
   - What's unclear: "spread narrowing" operationalization -- `us_jp_rate_spread` 5d change? `hy_oas_5d_change`?
   - Recommendation: Use `us_jp_rate_spread` 5d change < 0 as "spread narrowing" proxy for carry unwind signal. Document the interpretation in code comments.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/regimes/hysteresis.py` — `HysteresisTracker` API, update() signature, layer key mechanics
- `src/ta_lab2/regimes/resolver.py` — `resolve_policy_from_table()`, `_match_policy()` substring matching
- `src/ta_lab2/regimes/policy_loader.py` — YAML loading pattern, `project_root()` discovery
- `src/ta_lab2/regimes/labels.py` — `compose_regime_key()`, dimension labeler function signatures
- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` — Full pattern: per-layer labeling, hysteresis loop, scoped DELETE+INSERT write
- `src/ta_lab2/macro/feature_computer.py` — Available Phase 65 columns, `compute_macro_features()` return shape
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` — `upsert_macro_features()`, `get_compute_window()`, `_to_python()`, `_sanitize_dataframe()`
- `src/ta_lab2/scripts/run_daily_refresh.py` — Pipeline order, `run_macro_features()` function pattern, TIMEOUT constants
- `configs/regime_policies.yaml` — YAML structure for existing regime policies
- `alembic/versions/a1b2c3d4e5f6_fred_macro_features.py` (revision b3c4d5e6f7a8) — fred schema migration pattern
- `alembic/versions/b5178d671e38_risk_controls.py` — Single-row state table pattern (`dim_risk_state`)
- `.planning/phases/67-macro-regime-classifier/67-CONTEXT.md` — Locked decisions

### Secondary (MEDIUM confidence)
- `.planning/phases/66-fred-derived-features-automation/66-01-PLAN.md` — Phase 66 planned column names and FRED series IDs (not yet verified against DB)
- `.planning/phases/66-fred-derived-features-automation/66-02-PLAN.md` — Phase 66 computation logic for `hy_oas_*`, `nfci_*`, `dexjpus_*`, `fed_regime_trajectory`

### Tertiary (LOW confidence)
- None — all findings grounded in direct codebase inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing libraries, confirmed by direct file inspection
- Architecture: HIGH — directly modeled on confirmed existing patterns in the codebase
- Pitfalls: HIGH — identified from actual code paths (HysteresisTracker internals, policy_loader, alembic chain)
- Phase 66 column names: MEDIUM — from plan docs, not yet confirmed in DB schema

**Research date:** 2026-03-01
**Valid until:** 2026-04-01 (stable codebase; re-verify Phase 66 completion status before planning)
