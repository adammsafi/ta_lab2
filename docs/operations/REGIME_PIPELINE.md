# Regime Pipeline Operations Guide

This guide covers how to run, debug, and recover the regime refresh pipeline. Regimes classify market conditions (e.g., trending, mean-reverting, volatile) per asset and timeframe, and feed directly into signal generation. An operator can complete any procedure here without reading source code.

## Quick Start

```bash
# Full pipeline — bars -> EMAs -> regimes (run from project root)
python -m ta_lab2.scripts.run_daily_refresh --all --ids all

# Regimes only (bars and EMAs already fresh)
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids all

# Regime refresh for a single asset
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1

# Check current regime for an asset (BTC = id 1)
python -m ta_lab2.scripts.regimes.regime_inspect --id 1
```

## Prerequisites

Before running regime refresh, confirm:

1. **Database is reachable** — `TARGET_DB_URL` must be set:
   ```bash
   export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
   ```
2. **Bars are fresh** — `price_bars_multi_tf` must have recent data for each asset. Regimes read M/W/D bars; stale bars produce stale regimes with no error raised.
3. **EMAs are fresh** — `ema_multi_tf_u` must be populated. EMA values are the primary input to regime labeling.
4. **dim_assets populated** — Assets must be registered before refresh can run.

See [DAILY_REFRESH.md](DAILY_REFRESH.md) for how to run bars and EMAs if they are out of date.

## Entry Points

### Via Orchestrator (Recommended)

The orchestrator handles dependency ordering and subprocess isolation.

```bash
# Regimes only (assumes bars+EMAs already fresh)
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids all

# Full pipeline: bars -> EMAs -> regimes
python -m ta_lab2.scripts.run_daily_refresh --all --ids all

# Specific assets
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids 1,2,52

# Dry run — shows commands without executing
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids 1 --dry-run --verbose

# Disable hysteresis smoothing via orchestrator
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids all --no-regime-hysteresis
```

Regime subprocess timeout: **1800 seconds** (30 minutes).

### Direct Script (Fine-Grained Control)

Use when you need specific flags not exposed through the orchestrator, or when debugging a single asset.

```bash
# All active assets
python -m ta_lab2.scripts.regimes.refresh_regimes --all

# Specific IDs
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1,2

# Dry run — compute but do not write to DB
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1 --dry-run

# Verbose (DEBUG logging)
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1 -v

# Disable hysteresis (raw labels, no smoothing)
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1 --no-hysteresis

# Custom minimum bar thresholds
python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1 --min-bars-l0 30 --min-bars-l1 26

# Custom policy file
python -m ta_lab2.scripts.regimes.refresh_regimes --all --policy-file configs/my_policies.yaml

# ISO or US calendar scheme
python -m ta_lab2.scripts.regimes.refresh_regimes --all --cal-scheme us
```

### All Flags for `refresh_regimes`

| Flag | Default | Purpose |
|------|---------|---------|
| `--ids ID[,ID...]` | (mutually exclusive with `--all`) | Specific asset IDs to process |
| `--all` | (mutually exclusive with `--ids`) | All active assets from `dim_assets` |
| `--cal-scheme` | `iso` | Calendar scheme: `iso` or `us` |
| `--policy-file PATH` | `configs/regime_policies.yaml` | YAML policy overlay path |
| `--dry-run` | `False` | Compute but do not write to DB |
| `-v` / `--verbose` | `False` | Enable DEBUG logging |
| `--db-url URL` | `$TARGET_DB_URL` | PostgreSQL connection URL override |
| `--min-bars-l0 N` | (uses default) | Override monthly bars threshold for L0 labeling |
| `--min-bars-l1 N` | (uses default) | Override weekly bars threshold for L1 labeling |
| `--min-bars-l2 N` | (uses default) | Override daily bars threshold for L2 labeling |
| `--no-hysteresis` | `False` | Disable hysteresis smoothing (raw labels only) |
| `--min-hold-bars N` | `3` | Bars required before a loosening regime change is accepted |

## Execution Flow

For each asset, the pipeline runs these 10 steps:

1. **Load bars + EMAs** — Reads M/W/D timeframe bars from `price_bars_multi_tf` and EMA values from `ema_multi_tf_u` via `regime_data_loader.py`. EMAs are pivoted from long format to wide (`close_ema_9`, `close_ema_21`, etc.).

2. **Assess data budget** — Determines `feature_tier` (`full` or `lite`) and which labeling layers (L0/L1/L2) have enough bars to run. Layers below threshold are disabled and either proxy-filled or left NULL.

3. **Label enabled layers** — Runs each enabled labeler:
   - L0: Monthly timeframe (trend)
   - L1: Weekly timeframe (intermediate)
   - L2: Daily timeframe (short-term)
   - L3, L4: Always NULL in current implementation.

4. **Proxy fallback** — For disabled layers, uses BTC (id=1) as a market proxy. When computing regimes for BTC itself, proxy loading is skipped to avoid circular self-reference.

5. **Forward-fill sparse labels** — Monthly and weekly labels are sparse (one row per period). They are forward-filled to the daily index so every daily bar has all three layer labels.

6. **Resolve policy with hysteresis** — Row-by-row: looks up the matching policy in `regime_policies.yaml` for each (l0, l1, l2) combination. `HysteresisTracker` enforces a 3-bar hold before accepting a loosening change (larger size_mult, smaller stop_mult). Tightening changes are accepted immediately. Disable with `--no-hysteresis` for raw labels.

7. **Detect flips** — `detect_regime_flips` records every regime key transition, including the first assignment (where `old_regime=None`) for a complete audit trail.

8. **Compute stats** — Aggregates per-regime statistics (bar counts, return statistics) into `regime_stats`.

9. **Compute comovement** — Calculates EMA comovement metrics for the asset relative to the market. Written to `regime_comovement`; prior snapshots for the same (ids, tf) are deleted before insert.

10. **Write to DB** — All 4 regime tables are written via scoped DELETE + INSERT per (id, tf). This is a full recompute with no watermark — every run replaces all data for the processed assets.

**Performance:** Regime computation is fast — under 1 second per asset. The main bottleneck is DB I/O.

## Regime Tables

Four tables store regime output. All are written together on each run.

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `regimes` | Per-bar regime labels and resolved policy. PK: (id, ts, tf) | id, ts, tf, l0_label, l1_label, l2_label, regime_key, size_mult, stop_mult, orders, gross_cap, pyramids, feature_tier, l0_enabled, l1_enabled, l2_enabled, regime_version_hash |
| `regime_flips` | Regime transition events | id, ts, tf, layer, old_regime, new_regime, duration_bars |
| `regime_stats` | Aggregated statistics per regime key | id, tf, regime_key, n_bars, avg_ret, std_ret |
| `regime_comovement` | EMA comovement metrics (one snapshot per refresh) | id, tf, computed_at (part of PK), comovement metrics |

DDL source files: `sql/regimes/080_regimes.sql`, `081_regime_flips.sql`, `082_regime_stats.sql`, `084_regime_comovement.sql`.

## Debugging with regime_inspect

`regime_inspect` is the primary debugging tool. It reads from the DB by default; use `--live` to recompute without writing.

### Default Mode — Latest stored regime

```bash
python -m ta_lab2.scripts.regimes.regime_inspect --id 1
```

Shows: asset symbol, latest regime timestamp, feature tier, L0/L1/L2 labels with enabled/disabled status, resolved policy (regime_key, size_mult, stop_mult, orders, pyramids, gross_cap), version hash, and last updated timestamp.

### History Mode — Recent regime rows

```bash
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --history 30
```

Shows a table of the last 30 rows: Date, Regime Key, Size Mult, Stop Mult, Cap, Orders (oldest-first). Use this to see if the regime has been stable or oscillating.

### Flips Mode — Recent transitions

```bash
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --flips
```

Shows the last 20 transitions from `regime_flips`: Date, Layer, Old Regime, New Regime, Bars Held (oldest-first). The first assignment appears with `old_regime=None`.

### Live Mode — Recompute without writing

```bash
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --live
```

Calls `compute_regimes_for_id` directly and prints results without writing to DB. Use this to test policy or bar changes before committing them. Combine with `--verbose` for full DEBUG output.

### Additional Flags

```bash
# Specific timeframe (default: 1D)
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --tf 1D

# Verbose / DEBUG
python -m ta_lab2.scripts.regimes.regime_inspect --id 1 --verbose
```

## Verification Queries

Run these in psql or any SQL client to confirm regime data is correct and fresh.

```sql
-- 1. Check regime data is fresh (latest row per asset)
SELECT id, MAX(ts) as latest_regime, MIN(ts) as earliest_regime, COUNT(*) as n_rows
FROM public.regimes
WHERE tf = '1D'
GROUP BY id
ORDER BY latest_regime DESC
LIMIT 10;

-- 2. Check regime distribution for BTC (id=1)
SELECT regime_key, COUNT(*) as n_bars, AVG(size_mult) as avg_size
FROM public.regimes
WHERE id = 1 AND tf = '1D'
GROUP BY regime_key
ORDER BY n_bars DESC;

-- 3. Check recent regime flips (last 20 transitions)
SELECT id, ts, layer, old_regime, new_regime, duration_bars
FROM public.regime_flips
WHERE tf = '1D'
ORDER BY ts DESC
LIMIT 20;

-- 4. Check version hash consistency (all same = consistent run)
SELECT DISTINCT regime_version_hash, COUNT(*) as n_rows
FROM public.regimes
WHERE tf = '1D'
GROUP BY regime_version_hash;

-- 5. Check how many assets have regimes
SELECT COUNT(DISTINCT id) as n_assets_with_regimes
FROM public.regimes
WHERE tf = '1D';
```

If query 4 returns multiple distinct hashes, regimes were written by different script versions. Re-run `--all` to unify.

## Troubleshooting

### "No DB URL provided. Set TARGET_DB_URL or pass --db-url."

```
No DB URL provided. Set TARGET_DB_URL or pass --db-url.
```

- **Cause:** `TARGET_DB_URL` environment variable is not set.
- **Fix:**
  ```bash
  export TARGET_DB_URL="postgresql://user:pass@host:5432/dbname"
  ```
  The script also checks `$DB_URL` and `$MARKETDATA_DB_URL` as fallbacks.

---

### "No daily data for asset_id=X, returning empty"

```
No daily data for asset_id=1, returning empty
```

- **Cause:** No 1D bars exist in `price_bars_multi_tf` for this asset ID.
- **Fix:** Run bars refresh first:
  ```bash
  python -m ta_lab2.scripts.run_daily_refresh --bars --ids 1
  ```
  Then re-run regimes.

---

### "No regime data found for id=X tf=1D" (from regime_inspect)

```
No regime data found for id=1 tf=1D
```

- **Cause:** Regime refresh has never run successfully for this asset, or the run failed silently.
- **Fix:** Run with verbose to see what happened:
  ```bash
  python -m ta_lab2.scripts.regimes.refresh_regimes --ids 1 -v
  ```

---

### "L0/L1/L2 labeler failed: [exception]"

```
L2 labeler failed: not enough values to unpack
```

- **Cause:** Insufficient EMA data or too few bars for this layer. The layer falls back to proxy or stays NULL — this is not a hard failure. Other layers continue.
- **Check:** Use `regime_inspect --id X -v` to see which layers are enabled and which are disabled.
- **Fix:** Ensure EMAs are populated for this asset:
  ```bash
  python -m ta_lab2.scripts.run_daily_refresh --emas --ids X
  ```

---

### "Failed: [exception]" per-asset error in summary

```
Summary: 5 succeeded, 1 failed
  Failed: [3] ValueError: ...
```

- **Behavior:** The script continues to the next asset by default. Failed assets are listed at end of summary.
- **Exit code:** Non-zero when any asset errors (useful for cron alerting).
- **Fix:** Run with `--ids [failed_id] -v` to see the specific error:
  ```bash
  python -m ta_lab2.scripts.regimes.refresh_regimes --ids 3 -v
  ```

---

### Assets errored > 0 / exit code 1

- **Cause:** One or more assets failed during the run.
- **Check:** Re-run the failed IDs individually with `-v` to isolate.
- **Recovery:** After fixing the underlying issue, re-run just the failed IDs:
  ```bash
  python -m ta_lab2.scripts.regimes.refresh_regimes --ids 3,7 -v
  ```

---

### "No module named ta_lab2.scripts.regimes"

```
No module named ta_lab2.scripts.regimes
```

- **Cause:** Package not installed in development mode, or wrong Python environment.
- **Fix:**
  ```bash
  pip install -e ".[all]"
  ```

## State and Recovery

Regimes use **full recompute** — there is no watermark or state table. Every run deletes and replaces all regime data for the processed assets. To force recompute, just re-run the script.

### Manual Reset for a Specific Asset

If you need to clear regime data for a specific asset before re-running:

```sql
-- Clear all regime tables for asset id=2, timeframe 1D
DELETE FROM public.regimes WHERE id = 2 AND tf = '1D';
DELETE FROM public.regime_flips WHERE id = 2 AND tf = '1D';
DELETE FROM public.regime_stats WHERE id = 2 AND tf = '1D';
DELETE FROM public.regime_comovement WHERE id = 2 AND tf = '1D';
```

Then re-run refresh. The DELETE + INSERT pattern means re-running without the manual DELETE is equally safe — the result is the same.

### Regime Freshness vs. Signal Freshness

Regimes do not have an automated freshness gate before signal generation. If regimes are stale, signals will use stale `regime_key` values silently. When in doubt, run regimes before signals:

```bash
python -m ta_lab2.scripts.run_daily_refresh --regimes --ids all
python -m ta_lab2.scripts.signals.run_all_signal_refreshes
```

### A/B Testing: Regime-Enabled vs. Regime-Disabled Signals

To compare signal performance with and without regime context:

```bash
# With regime context (default)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes

# Without regime context (treats all bars as regime-unknown)
python -m ta_lab2.scripts.signals.run_all_signal_refreshes --no-regime
```

All 3 signal generators accept `regime_enabled` as a parameter. The `--no-regime` flag disables it globally for an explicit A/B comparison run.

## See Also

- [DAILY_REFRESH.md](DAILY_REFRESH.md) — How to run bars and EMA refreshes (prerequisite for regime refresh)
- [STATE_MANAGEMENT.md](STATE_MANAGEMENT.md) — State table schemas for bars and EMAs
- `src/ta_lab2/scripts/regimes/refresh_regimes.py` — Regime refresh script (argparse source of truth)
- `src/ta_lab2/scripts/regimes/regime_inspect.py` — Inspect tool
- `configs/regime_policies.yaml` — Policy lookup table for regime key -> size/stop/orders mapping
