# Phase 69: L4 Resolver Integration - Research

**Researched:** 2026-03-02
**Domain:** Regime resolver chain, policy table, YAML overlays, executor logging, RiskEngine gross_cap, Telegram alerts, cmc_macro_regimes schema
**Confidence:** HIGH

---

## Summary

Phase 69 wires the macro regime composite key (from Phase 67's `cmc_macro_regimes` table) into the existing L0-L4 resolver chain as L4. The resolver already has an L4 slot -- `resolve_policy_from_table(..., L4=None)` is already called with `L4=None` in `refresh_cmc_regimes.py`. All the infrastructure to accept L4 is in place and tested. The work is connecting the macro regime read to refresh and policy table entries.

The critical state: **Phase 67 is not yet complete.** The plans exist (67-01/02/03-PLAN.md) but there are no summary files and the implementation files do not exist yet:
- `src/ta_lab2/macro/regime_classifier.py` does NOT exist
- `cmc_macro_regimes` table does NOT exist in the DB (no alembic migration for it yet)
- `src/ta_lab2/scripts/macro/refresh_macro_regimes.py` does NOT exist

This means Phase 69 depends on Phase 67's output, and its planner must build around the fact that Phase 67 will create these artifacts before Phase 69 executes.

**Primary recommendation:** Phase 69 is purely wiring. It reads the latest `cmc_macro_regimes` row (keyed on `date` and `profile='default'`), passes `regime_key` as L4 to `resolve_policy_from_table()`, adds L4 policy entries to `DEFAULT_POLICY_TABLE` with glob-style matching via the existing substring matcher, adds YAML overlay support by adding macro entries to `regime_policies.yaml`, adds `l4_label` population to `cmc_regimes` rows, adds `l4_regime` / `l4_size_mult` columns to `cmc_executor_run_log`, applies adaptive `gross_cap` via the resolved policy's existing `gross_cap` field, and adds Telegram staleness alerts.

---

## Standard Stack

All tools are existing project dependencies. No new packages.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| sqlalchemy | 2.x | DB reads (cmc_macro_regimes, cmc_executor_run_log writes) | Project-wide convention |
| pandas | 2.x | DataFrame ops in refresh_cmc_regimes.py | All regime code uses pandas |
| alembic | installed | Schema migration for cmc_executor_run_log extension | All schema changes go through Alembic |
| PyYAML | installed | YAML overlay in policy_loader.py | Already in use |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| requests | installed | Telegram HTTP calls in send_critical_alert | Telegram notifications |
| fnmatch | stdlib | Glob pattern matching for `*-RiskOff-*` patterns | Alternative to substring matching |

**Installation:** No new packages needed.

---

## Architecture Patterns

### Existing Resolver Chain (CONFIRMED)

`resolver.py::resolve_policy_from_table()` already accepts L0/L1/L2/L3/L4. The processing order is `(L2, L1, L0, L3, L4)` -- L4 is processed last and can only tighten:

```python
# Source: src/ta_lab2/regimes/resolver.py line 125
for key in (L2, L1, L0, L3, L4):
    if key:
        policy = _tighten(policy, _match_policy(key, policy_table))
    if key and "Stressed" in key:
        policy.orders = "passive"
```

The `_tighten()` function enforces tighten-only semantics:
```python
# Source: src/ta_lab2/regimes/resolver.py lines 96-106
def _tighten(dst: TightenOnlyPolicy, src: Dict[str, object]) -> TightenOnlyPolicy:
    return TightenOnlyPolicy(
        size_mult=min(dst.size_mult, float(src.get("size_mult", dst.size_mult))),
        stop_mult=max(dst.stop_mult, float(src.get("stop_mult", dst.stop_mult))),
        gross_cap=min(dst.gross_cap, float(src.get("gross_cap", dst.gross_cap))),
        pyramids=dst.pyramids and bool(src.get("pyramids", True)),
        ...
    )
```

**L4 `size_mult <= 1.0` invariant is enforced by `_tighten()`** -- `min(dst.size_mult, ...)` means L4 can never increase size. However, the phase requirement (MINT-02) calls for an explicit `assert`. That assert must be in the policy-loading code or the `_match_policy()` call path for macro entries.

### Policy Table Matching (CONFIRMED)

`_match_policy()` uses a simple token-based substring check:
```python
# Source: src/ta_lab2/regimes/resolver.py lines 64-78
def _match_policy(regime_key, table):
    for k, v in table.items():
        tokens = [t for t in k.split("-") if t]  # split on hyphen, skip empty
        if all(t in regime_key for t in tokens):
            return dict(v)
    # fallback: size_mult=0.8
```

The CONTEXT.md decision says **full glob patterns** (`*-RiskOff-*`) for maximum flexibility. The current `_match_policy()` does substring token matching, NOT Python `fnmatch` glob matching. A key like `*-RiskOff-*` would be split into `['*', 'RiskOff', '*']` and all three tokens would need to be substrings of the regime_key -- which `*` never is.

**Conclusion:** `_match_policy()` needs extension to support glob-style patterns, OR the L4 policy entries should use hyphen-prefixed patterns that work with existing token matching. The CONTEXT.md says "glob patterns", so a new glob-matching code path for macro entries is needed.

**Practical approach:** Extend `_match_policy()` to use `fnmatch.fnmatch()` before falling back to token matching. OR add L4-specific entries keyed as plain strings like `RiskOff` (no glob) and rely on substring matching. The simplest extension that satisfies the requirement is to add a `fnmatch` check first.

### cmc_regimes l4_label Column (CONFIRMED)

The `cmc_regimes` table already has `l4_label TEXT NULL` (see `sql/regimes/080_cmc_regimes.sql` line 18). The `refresh_cmc_regimes.py` already writes `l4_label: None` in every row (lines 486-487). The `write_regimes_to_db()` function includes `l4_label` in its `_SCHEMA_COLS` set (line 563). **No schema migration needed for cmc_regimes.l4_label -- it already exists.**

### refresh_cmc_regimes.py L4 Injection Point (CONFIRMED)

The injection point is in `compute_regimes_for_id()` at line 447-454, where `resolve_policy_from_table()` is called with `L3=None, L4=None`. The L4 value must come from a global macro regime query made once at the start of each run (not per-asset, since macro regime is the same for all assets).

The macro regime load must happen in `main()` before the per-asset loop, and be passed into `compute_regimes_for_id()` as a parameter.

### cmc_executor_run_log Schema (CONFIRMED)

Current columns from alembic/versions/225bf8646f03_paper_trade_executor.py:
- `run_id` UUID PK
- `started_at`, `finished_at` TIMESTAMPTZ
- `config_ids` TEXT (JSON array)
- `dry_run`, `replay_historical` BOOLEAN
- `status` TEXT
- `signals_read`, `orders_generated`, `fills_processed`, `skipped_no_delta` INTEGER
- `error_message` TEXT

L4 logging requires adding two new columns:
- `l4_regime` TEXT NULL -- the macro regime composite key used for this run
- `l4_size_mult` NUMERIC NULL -- the size_mult derived from L4 for audit

These require an Alembic migration.

The `_write_run_log()` in `paper_executor.py` must be extended to accept and write these.

### Adaptive gross_cap (CONFIRMED)

`TightenOnlyPolicy` already has `gross_cap: float = 1.0`. The `_tighten()` function already applies `gross_cap = min(dst.gross_cap, ...)`. When L4 entries in the policy table include a `gross_cap` field (e.g., `0.5` for risk-off), the resolver will automatically reduce gross_cap.

The RiskEngine's `check_order()` method uses `max_portfolio_pct` from `dim_risk_limits`, NOT the resolved policy's `gross_cap`. **The `gross_cap` from TightenOnlyPolicy is NOT currently wired into the RiskEngine.**

The `gross_cap` is stored in `cmc_regimes` (line 492 in refresh_cmc_regimes.py -- `"gross_cap": policy.gross_cap`) and it is read into the dashboard via `cmc_regimes`, but it is not read by the executor's RiskEngine for portfolio-level capping.

**For MINT-07**, two approaches exist:
1. Have the executor read `gross_cap` from the latest `cmc_regimes` row for each asset and pass it as a soft cap on the order quantity (before the RiskEngine gates)
2. Have the RiskEngine load an adaptive `max_portfolio_pct` from the macro regime and apply it in Gate 4 (portfolio utilization cap)

The cleaner approach (avoids modifying RiskEngine) is to apply `gross_cap` in the PositionSizer before the RiskEngine gate -- scale down `target_qty` by `gross_cap` before delta computation.

### Telegram Staleness Alert (CONFIRMED)

`send_critical_alert(error_type, error_message, context=None)` in `src/ta_lab2/notifications/telegram.py`. It is already used in `paper_executor.py` via `_try_telegram_alert()` pattern (lines 647-661) which wraps the call in try/except to prevent crash on alerting failure.

For L4 staleness (macro regime is stale), the pattern to follow:
```python
# Source: src/ta_lab2/executor/paper_executor.py lines 647-661
def _try_telegram_alert(self, message: str) -> None:
    try:
        from ta_lab2.notifications.telegram import send_critical_alert
        send_critical_alert("executor", message)
    except Exception as exc:
        self.logger.warning("_try_telegram_alert: alerting unavailable (%s). Message: %s", exc, message)
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tighten-only semantics for L4 | Custom size_mult gating logic | `_tighten()` in resolver.py -- already applies `min(size_mult)` | L4 is just another layer in the existing chain |
| gross_cap application | Custom portfolio cap check | TightenOnlyPolicy.gross_cap field + `_tighten()` min semantics | Already implemented; wires through the resolver |
| YAML policy overlay | New loading mechanism | `load_policy_table()` in policy_loader.py | Already supports `match` key with all policy fields |
| Telegram alert failure handling | try/except around send | `_try_telegram_alert()` pattern from paper_executor.py | Proven pattern; alerting must never crash executor |
| Substring matching | Hand-written string scan | `_match_policy()` token-based matching | Already handles hyphen-tokenized keys |
| Staleness check | Date arithmetic | Compare `MAX(date)` from cmc_macro_regimes to `current_date - staleness_threshold_days` | Simple SQL, no custom library needed |

**Key insight:** The resolver chain was designed for this extension. L4 is already in the `resolve_policy_from_table()` signature -- it just needs to be given a non-None value. Zero architectural changes required; only data-wiring.

---

## Common Pitfalls

### Pitfall 1: Phase 67 Not Complete -- cmc_macro_regimes Does Not Exist
**What goes wrong:** Phase 69 plans assume `cmc_macro_regimes` exists. It does not yet.
**Why it happens:** Phase 67 PLAN files exist but no implementation was committed. The alembic migration for `cmc_macro_regimes` is not in the migration chain.
**How to avoid:** Phase 69 must either (a) depend strictly on Phase 67 being completed first, or (b) include a graceful fallback where L4 is disabled if `cmc_macro_regimes` does not exist. The CONTEXT.md states "Stale regime: Fall back to L0-L2 only (disable L4 entirely when macro regime is stale)" -- this same logic handles missing table gracefully with a try/except on the initial query.
**Warning signs:** `psycopg2.errors.UndefinedTable` on the macro regime query.

### Pitfall 2: glob Patterns Don't Work with Current _match_policy()
**What goes wrong:** Policy table entries with `*-RiskOff-*` pattern never match because `_match_policy()` splits on `-` and checks if each token is a substring of the regime_key. The token `*` would need to be literally in the regime_key.
**Why it happens:** `_match_policy()` does token-based substring matching, not glob matching.
**How to avoid:** Either (a) extend `_match_policy()` to check `fnmatch.fnmatch(regime_key, k)` before the token check, or (b) use plain token-matching patterns like `-RiskOff-` which work with the existing matcher. The CONTEXT.md explicitly says "Full glob patterns" -- use `fnmatch`.
**Warning signs:** Policy entries never match; `_match_policy()` always returns the fallback `size_mult=0.8`.

### Pitfall 3: Macro Regime is Per-Date, Not Per-Asset/Ts
**What goes wrong:** `refresh_cmc_regimes.py` iterates per-asset per-date. If L4 is loaded inside the per-asset loop, it would generate N DB queries per run instead of 1.
**Why it happens:** The current code structure is asset-centric; macro data is calendar-centric.
**How to avoid:** Load the latest macro regime ONCE in `main()` before the per-asset loop. Pass `l4_label: Optional[str]` as a parameter to `compute_regimes_for_id()`. Apply the same L4 label to all assets on the same day.

### Pitfall 4: cmc_executor_run_log Status CHECK Constraint
**What goes wrong:** Adding new status values or columns requires updating the CHECK constraint. The current constraint is `status IN ('running', 'success', 'failed', 'stale_signal')`. L4 staleness generates `status='l4_disabled'` log entries if that is the chosen design.
**Why it happens:** Schema has a strict CHECK constraint on status values.
**How to avoid:** Log L4 staleness via `error_message` (nullable field) rather than adding a new status. Use `status='success'` with `error_message='L4 disabled: macro regime stale'`. No schema change to CHECK constraint needed.

### Pitfall 5: size_mult > 1.0 from Policy Table Fallback
**What goes wrong:** If a macro regime key doesn't match any L4 policy entry, `_match_policy()` returns the fallback `{"size_mult": 0.8, ...}` which is < 1.0. But this fallback applies to ALL unmatched keys including data/loading errors, not just intentional "unknown" macro regimes.
**Why it happens:** `_match_policy()` fallback is a conservative default (0.8), but may not be the right behavior for unmatched macro regime keys.
**How to avoid:** Add a catch-all L4 policy entry (e.g. key `"Unknown"` with `size_mult=1.0`) so unmatched/unknown macro regimes do NOT tighten. Only explicit RiskOff/Cautious/Adverse entries should tighten. The MINT-02 assertion only needs to apply to intentionally-added macro entries.

### Pitfall 6: gross_cap Not Wired into Executor Portfolio Gate
**What goes wrong:** The resolved `TightenOnlyPolicy.gross_cap` is stored in `cmc_regimes.gross_cap` but the RiskEngine's Gate 4 (portfolio utilization cap) reads from `dim_risk_limits.max_portfolio_pct`. They are separate paths.
**Why it happens:** The resolver and the RiskEngine were built independently; no bridge connects policy `gross_cap` to the risk gate.
**How to avoid:** Apply `gross_cap` as a per-order quantity scale factor in `_process_asset_signal()` BEFORE calling `risk_engine.check_order()`. Specifically: look up the L4-derived `gross_cap` from the current resolved policy, and scale `target_qty` down by `gross_cap` before computing delta. This is simpler than modifying the RiskEngine.

### Pitfall 7: _write_run_log() INSERT Has Fixed Column List
**What goes wrong:** The current `_write_run_log()` in `paper_executor.py` has a hard-coded INSERT statement. Adding `l4_regime` and `l4_size_mult` requires both a schema migration AND updating the INSERT.
**Why it happens:** Hard-coded SQL in the executor.
**How to avoid:** Alembic migration adds columns as NULLABLE with no defaults. The INSERT statement is extended to include the new columns. Since they are nullable, old runs log NULL for them automatically (no backfill needed).

---

## Code Examples

### Load Latest Macro Regime from cmc_macro_regimes
```python
# Source: informed by refresh_macro_features.py SQL patterns

def _load_latest_macro_regime(engine: Engine, profile: str = "default") -> Optional[str]:
    """
    Load the latest macro regime composite key from cmc_macro_regimes.

    Returns the regime_key string (e.g. 'Cutting-Expanding-RiskOn-Stable'),
    or None if the table doesn't exist, is empty, or the latest row is stale.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("""
                    SELECT regime_key, date
                    FROM public.cmc_macro_regimes
                    WHERE profile = :profile
                    ORDER BY date DESC
                    LIMIT 1
                """),
                {"profile": profile},
            ).fetchone()
        if row is None:
            return None
        regime_key, regime_date = row
        # Staleness check: disable L4 if data is older than threshold
        return regime_key
    except Exception as exc:
        logger.warning("_load_latest_macro_regime: failed (%s), L4 disabled", exc)
        return None
```

### Adding Glob Pattern Matching to _match_policy()
```python
# Source: modification to src/ta_lab2/regimes/resolver.py

import fnmatch

def _match_policy(
    regime_key: str, table: Mapping[str, Mapping[str, object]]
) -> Dict[str, object]:
    for k, v in table.items():
        # Check glob pattern first (e.g. '*-RiskOff-*')
        if '*' in k or '?' in k or '[' in k:
            if fnmatch.fnmatch(regime_key, k):
                return dict(v)
            continue
        # Fall back to existing token-based substring matching
        tokens = [t for t in k.split("-") if t]
        if all(t in regime_key for t in tokens):
            return dict(v)
    return {
        "size_mult": 0.8,
        "stop_mult": 1.5,
        "setups": ["pullback"],
        "orders": "mixed",
    }
```

### L4 DEFAULT_POLICY_TABLE Entries (Recommended)
```python
# Source: to be added to src/ta_lab2/regimes/resolver.py DEFAULT_POLICY_TABLE
# These entries use glob patterns that require the fnmatch extension above.

L4_MACRO_POLICY_ENTRIES = {
    # Adverse macro: maximum tightening -- risk-off + liquidity stress
    "*-Strongly_Contracting-RiskOff*": {
        "size_mult": 0.30,
        "gross_cap": 0.40,
        "orders": "passive",
    },
    # Cautious: contraction + risk-off combo
    "*-Contracting-RiskOff*": {
        "size_mult": 0.50,
        "gross_cap": 0.50,
        "orders": "conservative",
    },
    # Pure risk-off (any monetary/liquidity): moderate tightening
    "*-RiskOff-*": {
        "size_mult": 0.60,
        "gross_cap": 0.60,
        "orders": "conservative",
    },
    # Cautious (no risk-off): mild tightening
    "*-Contracting-*": {
        "size_mult": 0.80,
        "gross_cap": 0.80,
    },
    "*-Strongly_Contracting-*": {
        "size_mult": 0.65,
        "gross_cap": 0.65,
    },
    # Hiking + risk-off (cautious combo)
    "Hiking-*-RiskOff*": {
        "size_mult": 0.55,
        "gross_cap": 0.55,
        "orders": "conservative",
    },
    # Catch-all for unknown/missing macro regime (no tightening)
    "Unknown*": {
        "size_mult": 1.0,
        "gross_cap": 1.0,
    },
}
# ASSERT: all macro entries have size_mult <= 1.0
for _k, _v in L4_MACRO_POLICY_ENTRIES.items():
    assert _v.get("size_mult", 1.0) <= 1.0, f"L4 entry {_k!r} has size_mult > 1.0"
    assert _v.get("gross_cap", 1.0) <= 1.0, f"L4 entry {_k!r} has gross_cap > 1.0"
```

### YAML Overlay for L4 Macro Entries (MINT-04)
```yaml
# configs/regime_policies.yaml -- extend with L4 macro entries
# Matching is substring-based for non-glob, fnmatch for glob patterns.
rules:
  # ... existing L0-L2 rules ...

  # L4 macro regime overrides (glob patterns, tighten-only)
  - match: "*-RiskOff-*"
    size_mult: 0.60
    gross_cap: 0.60
    orders: conservative

  - match: "*-Contracting-RiskOff*"
    size_mult: 0.50
    gross_cap: 0.50
    orders: conservative

  - match: "*-Strongly_Contracting-RiskOff*"
    size_mult: 0.30
    gross_cap: 0.40
    orders: passive
```

### Executor Run Log with L4 (MINT-06)
```python
# Source: extension to src/ta_lab2/executor/paper_executor.py

def _write_run_log(
    self,
    config: ExecutorConfig,
    status: str,
    signals_read: int = 0,
    orders: int = 0,
    fills: int = 0,
    skipped: int = 0,
    error: Optional[str] = None,
    l4_regime: Optional[str] = None,       # NEW: macro regime key
    l4_size_mult: Optional[float] = None,   # NEW: resulting size_mult from L4
) -> None:
    try:
        with self.engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO public.cmc_executor_run_log (
                        run_id, config_ids, status,
                        signals_read, orders_generated, fills_processed,
                        skipped_no_delta, error_message, finished_at,
                        l4_regime, l4_size_mult
                    ) VALUES (
                        :run_id, :config_ids, :status,
                        :signals_read, :orders_generated, :fills_processed,
                        :skipped_no_delta, :error_message, now(),
                        :l4_regime, :l4_size_mult
                    )
                """),
                {
                    "run_id": str(uuid.uuid4()),
                    "config_ids": json.dumps([config.config_id]),
                    "status": status,
                    "signals_read": signals_read,
                    "orders_generated": orders,
                    "fills_processed": fills,
                    "skipped_no_delta": skipped,
                    "error_message": error,
                    "l4_regime": l4_regime,
                    "l4_size_mult": l4_size_mult,
                },
            )
    except Exception as exc:
        self.logger.warning("_write_run_log: failed: %s", exc)
```

### refresh_cmc_regimes.py L4 Injection Pattern
```python
# Source: modification to compute_regimes_for_id() in refresh_cmc_regimes.py

def compute_regimes_for_id(
    engine: Engine,
    asset_id: int,
    policy_table: Optional[Mapping[str, Any]] = None,
    cal_scheme: str = "iso",
    min_bars_overrides: Optional[Dict[str, int]] = None,
    hysteresis_tracker: Optional[HysteresisTracker] = None,
    l4_label: Optional[str] = None,   # NEW: macro regime key (same for all assets)
) -> pd.DataFrame:
    ...
    # Inside the row loop, pass l4_label through to resolve_policy_from_table:
    policy = resolve_policy_from_table(
        policy_table,
        L0=l0_val,
        L1=l1_val,
        L2=l2_val,
        L3=None,
        L4=l4_label,  # was hardcoded None
    )
    ...
    # Build the output row to include l4_label:
    rows.append({
        ...
        "l4_label": l4_label,  # was None
        ...
    })
```

### Staleness Check with Telegram Alert
```python
# Source: pattern from paper_executor.py _try_telegram_alert

_L4_STALENESS_DAYS = 7  # Disable L4 if macro regime not updated in 7 days

def _load_macro_regime_with_staleness_check(
    engine: Engine, logger, notify_fn, profile: str = "default"
) -> Optional[str]:
    """Load macro regime, return None + send Telegram if stale."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT regime_key, date FROM cmc_macro_regimes "
                     "WHERE profile = :p ORDER BY date DESC LIMIT 1"),
                {"p": profile},
            ).fetchone()
    except Exception as exc:
        logger.warning("L4 load failed (table may not exist): %s", exc)
        return None

    if row is None:
        logger.warning("L4 disabled: cmc_macro_regimes is empty for profile=%s", profile)
        notify_fn("L4 macro regime offline: cmc_macro_regimes is empty")
        return None

    regime_key, regime_date = row
    from datetime import date as _date, timedelta
    if isinstance(regime_date, str):
        from datetime import datetime
        regime_date = datetime.strptime(regime_date, "%Y-%m-%d").date()
    staleness = (_date.today() - regime_date).days
    if staleness > _L4_STALENESS_DAYS:
        logger.warning("L4 disabled: macro regime is %d days stale (threshold=%d)", staleness, _L4_STALENESS_DAYS)
        notify_fn(f"L4 macro regime offline: last update {staleness}d ago (threshold={_L4_STALENESS_DAYS}d)")
        return None

    logger.info("L4 macro regime: %s (date=%s, %d days old)", regime_key, regime_date, staleness)
    return regime_key
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| L4=None (hardcoded) in refresh_cmc_regimes.py | L4=macro_regime_key (loaded from cmc_macro_regimes) | Phase 69 change |
| cmc_executor_run_log has no regime columns | Add l4_regime, l4_size_mult columns | Requires Alembic migration |
| gross_cap computed but not enforced in executor | gross_cap applied as order quantity scale in executor | MINT-07 |
| _match_policy() uses token-only substring matching | Extended to support fnmatch glob patterns | Enables `*-RiskOff-*` matching |
| Policy table has no macro entries | DEFAULT_POLICY_TABLE extended with L4_MACRO_POLICY_ENTRIES | Plus YAML overlay support |

---

## Critical Finding: Phase 67 Completion Status

**Phase 67 has plans but no implementation.** The following artifacts do NOT yet exist:

| Artifact | Expected Path | Status |
|---------|--------------|--------|
| cmc_macro_regimes table | DB table (Alembic migration) | NOT EXISTS |
| cmc_macro_hysteresis_state | DB table (Alembic migration) | NOT EXISTS |
| MacroRegimeClassifier | src/ta_lab2/macro/regime_classifier.py | NOT EXISTS |
| refresh_macro_regimes.py | src/ta_lab2/scripts/macro/refresh_macro_regimes.py | NOT EXISTS |
| macro_regime_config.yaml | configs/macro_regime_config.yaml | NOT EXISTS |

Phase 69 planning must account for this: either Phase 67 must be completed first (preferred), or Phase 69 must include a robust fallback when the table doesn't exist (L4=None, Telegram alert, continue with L0-L2 only).

The CONTEXT.md says "Depends on Phase 67 (macro regime labels must exist)" -- so the planner should sequence Phase 67 completion before Phase 69 tasks.

---

## cmc_macro_regimes Schema (from Phase 67 Plan)

From the 67-01-PLAN.md (not yet applied):

| Column | Type | Notes |
|--------|------|-------|
| date | DATE NOT NULL | PK component |
| profile | TEXT NOT NULL | PK component, default 'default' |
| monetary_policy | TEXT NULL | Hiking/Holding/Cutting |
| liquidity | TEXT NULL | Strongly_Expanding/Expanding/Neutral/Contracting/Strongly_Contracting |
| risk_appetite | TEXT NULL | RiskOff/Neutral/RiskOn |
| carry | TEXT NULL | Unwind/Stress/Stable |
| regime_key | TEXT NULL | Composite: e.g. 'Cutting-Expanding-RiskOn-Stable' |
| macro_state | TEXT NULL | favorable/constructive/neutral/cautious/adverse |
| regime_version_hash | TEXT NULL | Config hash for provenance |
| ingested_at | TIMESTAMPTZ NOT NULL | server_default now() |

**PK: (date, profile)** -- to fetch the latest, query `ORDER BY date DESC LIMIT 1 WHERE profile = 'default'`.

---

## Open Questions

1. **Phase 67 completion prerequisite**
   - What we know: Phase 67 plans are written but not implemented
   - What's unclear: When will Phase 67 be complete before Phase 69 can run?
   - Recommendation: Phase 69 planning must list Phase 67 completion as an explicit hard dependency for Wave 1. All Phase 69 tasks should fail gracefully (L4=None) until Phase 67 is applied.

2. **Glob matching approach for _match_policy()**
   - What we know: Current matcher doesn't support glob; CONTEXT.md says "Full glob patterns"
   - What's unclear: Should the glob extension go in `_match_policy()` (breaks existing tests if not careful) or a separate L4 matching function?
   - Recommendation: Extend `_match_policy()` with fnmatch check as first branch (only triggers when key contains `*/?/[`). Existing token-matching tests are unaffected since those keys don't contain glob characters.

3. **Executor gross_cap application point**
   - What we know: RiskEngine doesn't read TightenOnlyPolicy.gross_cap; CONTEXT.md says adaptive gross_cap
   - What's unclear: Should gross_cap apply to per-asset size or portfolio-level cap?
   - Recommendation: Apply in `_process_asset_signal()` as a per-asset quantity scale BEFORE the RiskEngine gate. `target_qty *= min(1.0, gross_cap)` where `gross_cap` comes from the L4-resolved policy for the current macro regime. This is the minimal-change approach.

4. **Per-trade l4_regime on cmc_orders table**
   - What we know: CONTEXT.md says "Claude's discretion based on audit trail needs vs schema complexity"
   - What's unclear: Whether to add l4_regime to cmc_orders or keep it only on the run log
   - Recommendation: Keep L4 only on cmc_executor_run_log for now. The run log captures L4 at the run level (same L4 for all assets in a run), which is the correct granularity for a global macro regime. Adding to cmc_orders adds schema complexity for information that doesn't vary per order in a run.

5. **Staleness threshold days**
   - What we know: CONTEXT.md says "Claude's discretion based on FRED update frequency"
   - FRED macro data updates on business days; lag to cmc_macro_regimes is <= 2 business days normally
   - Recommendation: 7-day staleness threshold. FRED series update at most weekly; 7 days gives headroom for weekends + FRED release delays + VM sync failures. Alert at 7 days, fall back to L0-L2 only.

---

## Sources

### Primary (HIGH confidence)
- `src/ta_lab2/regimes/resolver.py` -- Full resolver chain, `_match_policy()`, `_tighten()`, `resolve_policy_from_table()`, L4 slot confirmed
- `src/ta_lab2/regimes/policy_loader.py` -- YAML overlay loading, `merged[match] = entry` pattern, all supported fields
- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` -- L4=None injection point (line 447-454), l4_label in schema cols (line 563), row builder (line 486-487)
- `src/ta_lab2/executor/paper_executor.py` -- `_write_run_log()` INSERT (lines 610-635), `_try_telegram_alert()` pattern (lines 647-661)
- `alembic/versions/225bf8646f03_paper_trade_executor.py` -- `cmc_executor_run_log` full schema
- `src/ta_lab2/risk/risk_engine.py` -- Gate 3/4 portfolio cap logic (lines 293-370), gross_cap NOT read from policy
- `src/ta_lab2/notifications/telegram.py` -- `send_critical_alert()` signature (lines 181-223)
- `sql/regimes/080_cmc_regimes.sql` -- `l4_label TEXT NULL` confirmed in schema
- `src/ta_lab2/regimes/hysteresis.py` -- `HysteresisTracker` API, `is_tightening_change()` pattern
- `configs/regime_policies.yaml` -- Existing YAML structure (6 rules, `match` key pattern)
- `.planning/phases/67-macro-regime-classifier/67-01-PLAN.md` -- cmc_macro_regimes schema
- `.planning/phases/67-macro-regime-classifier/67-02-PLAN.md` -- MacroRegimeClassifier design, dimension labels

### Secondary (MEDIUM confidence)
- `src/ta_lab2/executor/position_sizer.py` -- PositionSizer.compute_target_position(), where gross_cap could be applied
- `src/ta_lab2/dashboard/queries/executor.py` -- cmc_executor_run_log column list for dashboard impact

### Tertiary (LOW confidence)
- `.planning/phases/67-macro-regime-classifier/67-RESEARCH.md` -- Phase 67 research (medium confidence since Phase 67 not yet implemented)

---

## Metadata

**Confidence breakdown:**
- Resolver chain and L4 slot: HIGH -- confirmed by reading resolver.py source and tests
- cmc_regimes l4_label column: HIGH -- confirmed by SQL file and refresh script
- cmc_executor_run_log schema: HIGH -- confirmed by Alembic migration source
- Policy YAML loading: HIGH -- confirmed by policy_loader.py source
- cmc_macro_regimes schema: MEDIUM -- from Phase 67 plan docs, not yet applied to DB
- gross_cap executor integration: MEDIUM -- gap identified; recommended approach is pragmatic
- Phase 67 completion status: HIGH (confirmed NOT complete)

**Research date:** 2026-03-02
**Valid until:** 2026-04-02 (stable codebase; re-verify Phase 67 completion before Phase 69 executes)
