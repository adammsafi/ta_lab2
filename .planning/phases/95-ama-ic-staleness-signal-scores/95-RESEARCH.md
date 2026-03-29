# Phase 95: AMA-Aware IC Staleness & Real Signal Scores - Research

**Researched:** 2026-03-28
**Domain:** IC staleness monitoring, AMA feature loading, Black-Litterman signal_scores
**Confidence:** HIGH (all findings from direct codebase inspection)

## Summary

Phase 95 has two tightly scoped problems identified by the v1.2.0 audit. The first
is that `ICStalenessMonitor.run()` only ever checks 2 features (not 20), because
`_load_close_and_feature()` checks `information_schema.columns` for the `features`
table and all 18 AMA features (`_ama` suffix) live in `ama_multi_tf_u.ama`, not in
`features`. This makes the BL weight-halving mechanism inoperative for 90% of active
features.

The second problem is that `refresh_portfolio_allocations.py` constructs
`signal_scores = pd.DataFrame(1.0, ...)` — a uniform matrix — before passing it to
`BLAllocationBuilder.run()`. The code even has a `# TODO(Phase 87)` comment
acknowledging this. The fix is to load the most recent `ama` column value (and
bar-level feature values) per asset and use those as actual signal scores.

**Primary recommendation:** Plan 01 adds an AMA-aware data loader to
`run_ic_staleness_check.py` that mirrors the `parse_active_features()` +
`load_strategy_data_with_ama()` pattern from `bakeoff_orchestrator.py`. Plan 02
replaces the uniform signal_scores stub in `refresh_portfolio_allocations.py` with
latest feature values from `features` + `ama_multi_tf_u`.

## Standard Stack

All components are existing project modules. No new libraries are needed.

### Core
| Module | Location | Purpose | Why Standard |
|--------|----------|---------|--------------|
| `parse_active_features()` | `ta_lab2.backtests.bakeoff_orchestrator` | Parse YAML into feature list with source routing | Already handles `_ama` vs bar-level split |
| `load_strategy_data_with_ama()` | `ta_lab2.backtests.bakeoff_orchestrator` | Batch-load AMA feature values from `ama_multi_tf_u` | Proven pattern, joins on `(id, venue_id, tf, indicator, params_hash_prefix)` |
| `ICStalenessMonitor` | `ta_lab2.scripts.analysis.run_ic_staleness_check` | The monitor class being extended | Phase target |
| `_load_close_and_feature()` | `run_ic_staleness_check` | Current non-AMA data loader — will need AMA counterpart | Existing pattern to adapt |
| `BLAllocationBuilder.run()` | `ta_lab2.portfolio.black_litterman` | BL portfolio optimizer | Accepts `signal_scores` DataFrame |
| `compute_rolling_ic()` | `ta_lab2.analysis.ic` | Vectorized Spearman IC | Already used in staleness check |

### Supporting
| Module | Location | Purpose | When to Use |
|--------|----------|---------|-------------|
| `load_per_asset_ic_weights()` | `ta_lab2.backtests.bakeoff_orchestrator` | Load IC-IR from `ic_results` table | Already called in BL pipeline |
| `_write_weight_override()` | `run_ic_staleness_check` | Insert decay override into `dim_ic_weight_overrides` | Triggered for decaying AMA features |
| `_send_decay_alert()` | `run_ic_staleness_check` | Throttled Telegram + pipeline_alert_log | Already wired |

## Architecture Patterns

### Recommended Change: AMA-Aware Data Loader in run_ic_staleness_check.py

Add a new `_load_close_and_ama_feature()` function that loads an AMA feature from
`ama_multi_tf_u` and close price from `features`, mirroring the SQL in
`_load_ama_data_with_close()` in `run_ic_sweep.py`.

The key SQL pattern (from `run_ic_sweep.py` line 306):
```sql
SELECT a.ts, a.ama, f.close
FROM public.ama_multi_tf_u a
INNER JOIN public.features f
    ON f.id = a.id AND f.ts = a.ts AND f.tf = a.tf
WHERE a.id = :asset_id
  AND a.tf = :tf
  AND a.indicator = :indicator
  AND a.params_hash = :params_hash
  AND a.alignment_source = 'multi_tf'
  AND a.roll = FALSE
ORDER BY a.ts
```

Add venue_id filter: `AND a.venue_id = 1` (venue_id = 1 is CMC_AGG, matches `features` table default).

### Feature Name Parsing Convention

AMA feature names in `feature_selection.yaml` follow the pattern
`{INDICATOR}_{PARAMS_HASH_8CHARS}_ama`. The `parse_active_features()` function in
`bakeoff_orchestrator.py` already handles this:

```python
# Source: src/ta_lab2/backtests/bakeoff_orchestrator.py line 508-570
if name.endswith("_ama"):
    body = name[:-4]               # strip "_ama"
    last_underscore = body.rfind("_")
    indicator = body[:last_underscore]     # e.g. "TEMA"
    params_hash = body[last_underscore + 1:]  # e.g. "0fca19a1" (8 chars)
    source = "ama_multi_tf_u"
else:
    source = "features"            # e.g. ret_is_outlier, bb_ma_20
```

### MAX_ACTIVE_FEATURES Change

Current constant in `run_ic_staleness_check.py`:
```python
MAX_ACTIVE_FEATURES = 10  # Limit to top N by IC-IR mean to reduce runtime
```

Phase 95 success criterion 2 requires checking "all 20 active features". Change this
to 20. The YAML has exactly 20 entries with `ic_ir_mean >= 1.0` (verified by
`grep "^- ic_ir_mean: 1\." configs/feature_selection.yaml | wc -l` = 20).

### signal_scores Replacement Pattern

The uniform stub in `refresh_portfolio_allocations.py` (lines 684-688):
```python
signal_scores = pd.DataFrame(
    1.0,
    index=list(prices.columns),
    columns=ic_ir_matrix.columns,
)
```

Replace with a function that loads the latest feature value per asset per feature:
- For `_ama` features: query `ama_multi_tf_u` for the latest `ama` value per asset
- For bar-level features: query `features` table for the latest value per asset
- Result: DataFrame indexed by asset_id, columns = feature names, values = raw feature values

The BL pipeline already handles normalization via z-scoring in
`BLAllocationBuilder.signals_to_mu()`, so raw feature values are appropriate.

### Recommended Project Structure

No new files needed. Changes are in:
```
src/ta_lab2/scripts/analysis/
    run_ic_staleness_check.py     # Add AMA data loader + bump MAX_ACTIVE_FEATURES to 20

src/ta_lab2/scripts/portfolio/
    refresh_portfolio_allocations.py  # Replace uniform signal_scores with real values
```

### Anti-Patterns to Avoid

- **Don't query `features` for AMA columns**: They do not exist there. The
  `information_schema` check returns None, so AMA features silently skip.
- **Don't filter `ama_multi_tf_u` without `alignment_source = 'multi_tf'`**: Multiple
  rows exist per `(id, ts, tf, indicator, params_hash)` differing only by
  `alignment_source`. Without this filter, duplicate timestamps cause rolling failures.
- **Don't forget `roll = FALSE`**: `ama_multi_tf_u` has `roll` BOOLEAN column. The
  false rows are the "real" AMA values; true rows are rolling-calendar variants.
- **Don't use `venue_id` without filtering**: The features table and `ama_multi_tf_u`
  both have venue_id in their PKs. Omitting the filter causes duplicate ts rows and
  rolling correlation failures. Use `venue_id = 1` (CMC_AGG default).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| AMA feature name parsing | Custom regex | `parse_active_features()` in bakeoff_orchestrator | Already handles edge cases, source routing |
| Loading AMA values for an asset | Raw SQL | Adapt `load_strategy_data_with_ama()` pattern | Proven join pattern with proper venue/alignment filters |
| IC-IR computation | Custom | `compute_rolling_ic()` from `ta_lab2.analysis.ic` | Vectorized 30x faster than per-window spearmanr |
| Per-asset IC weight loading | Custom | `load_per_asset_ic_weights()` from bakeoff_orchestrator | Already handles fallback to universal weights |

**Key insight:** All the AMA loading infrastructure already exists in
`bakeoff_orchestrator.py` for the bakeoff pipeline. The staleness check and
signal_scores need to adopt the same patterns.

## Common Pitfalls

### Pitfall 1: AMA feature columns missing from features table silently skip
**What goes wrong:** `_load_close_and_feature()` checks `information_schema.columns`
for column existence in `features`. All 18 AMA features (`TEMA_xxx_ama`, etc.) are
NOT columns in `features` — they live in `ama_multi_tf_u.ama`. The check returns None,
logs a DEBUG message, and the feature is silently skipped. With `MAX_ACTIVE_FEATURES=10`
and the top 10 features being 1 non-AMA + 9 AMA, only 1 feature actually gets checked.
**Why it happens:** The original staleness monitor was built before AMA feature
dominance was established (Phase 80 finding).
**How to avoid:** Route features through `parse_active_features()` to determine source,
then dispatch to the appropriate loader.
**Warning signs:** "Skipping feature='TEMA_..._ama' -- no data" in DEBUG logs.

### Pitfall 2: alignment_source duplication in ama_multi_tf_u
**What goes wrong:** Querying `ama_multi_tf_u` without `alignment_source = 'multi_tf'`
returns multiple rows per timestamp (one per alignment variant). This inflates the
time series and causes IC/rolling correlation to fail with duplicate index errors.
**Why it happens:** The `_u` unified table combines multiple alignment sources.
**How to avoid:** Always add `AND alignment_source = 'multi_tf'` to queries.
**Warning signs:** `ValueError: cannot reindex from a duplicate axis` or IC-IR values
that are far outside normal range.

### Pitfall 3: roll = TRUE rows in ama_multi_tf_u
**What goes wrong:** `ama_multi_tf_u` contains rows with `roll = TRUE` (calendar-roll
variants). Including them doubles the row count for the same `(id, indicator, params_hash, tf)`.
**How to avoid:** Always add `AND roll = FALSE` to queries that want the canonical
multi-tf AMA values.

### Pitfall 4: venue_id filter missing
**What goes wrong:** Both `features` and `ama_multi_tf_u` have `venue_id` in their PKs.
Without `venue_id = 1`, multiple venues can return rows for the same timestamp,
causing duplicate index errors and wrong IC values.
**How to avoid:** Always filter `venue_id = 1` (CMC_AGG).

### Pitfall 5: signal_scores scale mismatch with IC weights
**What goes wrong:** Raw AMA values are absolute price-relative numbers (not in [-1,1]).
Using them directly as signal scores will produce extreme z-scores.
**Why it happens:** AMA `ama` column contains actual AMA price values, not normalized scores.
**How to avoid:** Use `d1` (first derivative: `ama.diff(1)`) rather than `ama` directly,
OR use `d1_roll` (diff over unified timeline). These are stationary and bounded.
Alternatively, use `ama / close - 1` to get the percentage displacement. The
`bakeoff_orchestrator` uses `ama` directly because `BLAllocationBuilder` z-scores
internally — this should be verified.

Actually: looking at `BLAllocationBuilder.signals_to_mu()`, it applies z-scoring via
`(composite - composite.mean()) / std` across the cross-section. So raw `ama` values
will produce a cross-sectional z-score that reflects relative position. This works
correctly as long as values are not all identical. The `d1` column (momentum) is more
semantically appropriate as a "signal" (positive d1 = AMA rising = bullish), but `ama`
works as a cross-sectional rank signal.

**Recommendation:** Use `d1` column (first AMA derivative) as signal_scores. It is
stationary and directly measures momentum. This requires loading `d1` from `ama_multi_tf_u`
instead of `ama`. The staleness check, however, should use `ama` directly (matching
what ic_results stores IC scores for — the ic_sweep evaluates the `ama` column).

### Pitfall 6: ic_results may lack entries for AMA features if sweep not run recently
**What goes wrong:** `load_per_asset_ic_weights()` returns empty DataFrame if
`ic_results` has no rows matching the requested features. The signal_scores function
falls back to the prior-only BL path.
**How to avoid:** This is already handled gracefully. Document in plan that Phase 95's
signal_scores loader should log a WARNING (not ERROR) when ic_results is empty for
specific features, and fall back gracefully to uniform 1.0 for that feature.

## Code Examples

Verified patterns from existing codebase:

### Loading AMA feature + close for staleness check (new _load_close_and_ama_feature)
```python
# Source: adapted from src/ta_lab2/scripts/analysis/run_ic_sweep.py line 284-355
def _load_close_and_ama_feature(
    conn,
    asset_id: int,
    indicator: str,
    params_hash: str,
    feature_name: str,
    tf: str = "1D",
    venue_id: int = 1,
) -> tuple[pd.Series, pd.Series] | None:
    sql = text("""
        SELECT a.ts, a.ama, f.close
        FROM public.ama_multi_tf_u a
        INNER JOIN public.features f
            ON f.id = a.id AND f.ts = a.ts AND f.tf = a.tf AND f.venue_id = a.venue_id
        WHERE a.id = :asset_id
          AND a.venue_id = :venue_id
          AND a.tf = :tf
          AND a.indicator = :indicator
          AND LEFT(a.params_hash, 8) = :params_hash
          AND a.alignment_source = 'multi_tf'
          AND a.roll = FALSE
        ORDER BY a.ts
    """)
    df = pd.read_sql(sql, conn, params={
        "asset_id": asset_id, "venue_id": venue_id,
        "tf": tf, "indicator": indicator, "params_hash": params_hash,
    })
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()
    return df["ama"].astype(float), df["close"].astype(float)
```

### Parsing active features with source routing (existing, already importable)
```python
# Source: src/ta_lab2/backtests/bakeoff_orchestrator.py line 508
from ta_lab2.backtests.bakeoff_orchestrator import parse_active_features

features = parse_active_features()
# Each entry: {"name": "TEMA_0fca19a1_ama", "indicator": "TEMA",
#              "params_hash": "0fca19a1", "source": "ama_multi_tf_u"}
```

### Loading latest feature values for signal_scores (new helper needed in refresh_portfolio_allocations.py)
```python
# Source: pattern derived from load_strategy_data_with_ama()
# in src/ta_lab2/backtests/bakeoff_orchestrator.py line 581
def _load_latest_feature_values(
    asset_ids: list[int],
    feature_list: list[dict],  # from parse_active_features()
    tf: str,
    engine,
) -> pd.DataFrame:
    """
    Load the most recent feature value per asset for signal_scores construction.

    Returns DataFrame: index=asset_id, columns=feature names.
    Falls back to 0.0 for missing values.
    """
    # Separate AMA vs bar-level features
    ama_features = [f for f in feature_list if f["source"] == "ama_multi_tf_u"]
    bar_features = [f for f in feature_list if f["source"] == "features"]

    result = pd.DataFrame(
        float("nan"), index=asset_ids,
        columns=[f["name"] for f in feature_list]
    )

    # Load AMA features: latest ama value per (asset, indicator, params_hash)
    if ama_features:
        pairs_values = ...  # build VALUES clause for (indicator, hash_prefix) IN filter
        sql = text("""
            SELECT DISTINCT ON (id, indicator, LEFT(params_hash, 8))
                id, indicator, LEFT(params_hash, 8) AS ph, ama
            FROM public.ama_multi_tf_u
            WHERE id = ANY(:ids)
              AND venue_id = 1
              AND tf = :tf
              AND alignment_source = 'multi_tf'
              AND roll = FALSE
              AND (indicator, LEFT(params_hash, 8)) IN <values_clause>
            ORDER BY id, indicator, LEFT(params_hash, 8), ts DESC
        """)
        # ... load and pivot into result

    # Load bar-level features: latest value per asset
    # ... similar DISTINCT ON query from features table

    return result.fillna(0.0)
```

### Bump MAX_ACTIVE_FEATURES constant
```python
# Source: src/ta_lab2/scripts/analysis/run_ic_staleness_check.py line 53
# Change from:
MAX_ACTIVE_FEATURES = 10  # Limit to top N by IC-IR mean to reduce runtime
# Change to:
MAX_ACTIVE_FEATURES = 20  # Cover all 20 active features (18 AMA + 2 bar-level)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Universal IC-IR for BL | Per-asset IC-IR from ic_results | Phase 86 | BL views reflect per-asset signal heterogeneity |
| Uniform signal_scores=1.0 | To be replaced in Phase 95 | Phase 95 | BL views driven by actual feature values |
| Staleness check on 2 features | To be fixed to 20 in Phase 95 | Phase 95 | Weight-halving mechanism becomes operative |

**Deprecated/outdated:**
- `TODO(Phase 87)` comment at refresh_portfolio_allocations.py line 681-682: the comment says "Wire real feature values as signal_scores from features table + ama_multi_tf_u for fully live signal-weighted BL". Phase 95 implements this.

## Open Questions

1. **Signal score column: `ama` vs `d1`**
   - What we know: `ic_results` stores IC scores computed against `ama` column (per ic_sweep). The BL pipeline z-scores internally.
   - What's unclear: Whether `ama` (price-level) or `d1` (momentum/derivative) is more semantically correct as a "signal score".
   - Recommendation: Use `d1` (first derivative of AMA). It is stationary, momentum-oriented, and more appropriate as a signal score. Document the choice in the plan. The BL z-scoring handles normalization regardless.

2. **Close price source for staleness AMA check**
   - What we know: The SQL joins `ama_multi_tf_u` with `features` on `(id, ts, tf, venue_id)`. The `features` table has a `close` column.
   - What's unclear: Whether the join will always find matching rows (features might have gaps or coverage differences from AMA data).
   - Recommendation: Use LEFT JOIN; when `close` is NULL, compute forward returns from the price bars directly. OR accept that assets missing from `features` are simply skipped (same behavior as current non-AMA path).

3. **signal_scores for non-AMA features (ret_is_outlier, bb_ma_20, close_fracdiff)**
   - What we know: These 2 features are in `features` table. They are ranked 1st and 13th by IC-IR.
   - What's unclear: `ret_is_outlier` is a boolean (0/1). Using it directly as a score is valid but semantically asymmetric.
   - Recommendation: Use as-is. The cross-sectional z-score normalizes the values. Plan should note this.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `src/ta_lab2/scripts/analysis/run_ic_staleness_check.py` — full file read
- Direct codebase inspection: `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` — full file read
- Direct codebase inspection: `src/ta_lab2/portfolio/black_litterman.py` — full file read
- Direct codebase inspection: `src/ta_lab2/backtests/bakeoff_orchestrator.py` (lines 508-695) — parse_active_features and load_strategy_data_with_ama patterns
- Direct codebase inspection: `src/ta_lab2/scripts/analysis/run_ic_sweep.py` (lines 78-355) — AMA column names, _load_ama_data_with_close pattern
- Direct codebase inspection: `configs/feature_selection.yaml` — 20 active features confirmed (ic_ir_mean >= 1.0: 18 `_ama` + ret_is_outlier + bb_ma_20)
- Direct codebase inspection: `alembic/versions/h2i3j4k5l6m7_dim_feature_selection.py` — dim_feature_selection schema (no source_table column)

### Secondary (MEDIUM confidence)
- `.planning/phases/80-ic-analysis-feature-selection/80-05-SUMMARY.md` — "18 AMA + ret_is_outlier + close_fracdiff + bb_ma_20" active tier composition
- `.planning/phases/86-portfolio-construction-pipeline/86-02-PLAN.md` — "uniform signal_scores=1.0 for Phase 86" decision

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all patterns from direct codebase inspection
- Architecture: HIGH — exact SQL and function signatures verified
- Pitfalls: HIGH — all discovered from direct code inspection (not hypothetical)

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable domain, no fast-moving deps)

---

## Phase-Specific Decision Reference

### Plan 01 (AMA-aware IC staleness data loader) scope

Files to modify: `src/ta_lab2/scripts/analysis/run_ic_staleness_check.py`

Changes:
1. Add `_load_close_and_ama_feature(conn, asset_id, indicator, params_hash, feature_name, tf, venue_id)` function
2. Change `_check_one()` to call `parse_active_features()` for routing, dispatch to correct loader
3. Bump `MAX_ACTIVE_FEATURES = 20`
4. Update `_load_active_features()` to return structured dicts (name + source) OR keep returning names and do routing inside `_check_one()`

Simplest approach: keep `_load_active_features()` returning name strings. Add a `_route_feature_load(conn, feature_name, asset_id, tf)` dispatcher that calls `parse_active_features()` internally to resolve source, then calls the appropriate loader.

### Plan 02 (Real signal_scores from IC-IR weights) scope

Files to modify: `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py`

Changes:
1. Add `_load_latest_signal_scores(engine, asset_ids, feature_list, tf)` function
2. Replace the `pd.DataFrame(1.0, ...)` stub with call to new function
3. Remove the `TODO(Phase 87)` comment
4. Handle fallback: if latest values unavailable for an asset, use 0.0 (neutral)

The existing `ic_ir_matrix` columns define which features to load. The `feature_list` can be built by calling `parse_active_features()` (already used via `active_features = parse_active_features()` at line 614).

### ic_results feature name format (CRITICAL for Plan 02)

`ic_results.feature` values for AMA features follow the pattern
`{INDICATOR}_{hash_8chars}_{col}` where col is `ama`, `d1`, etc. So
`"TEMA_0fca19a1_ama"` in the YAML corresponds to `feature="TEMA_0fca19a1_ama"` in
`ic_results` (the ic_sweep writes the full disambiguated name directly as the feature column).
The `load_per_asset_ic_weights()` function queries `ic_results` using the YAML feature names
directly — this works because the ic_sweep stored them with those exact names.
