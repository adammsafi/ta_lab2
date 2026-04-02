---
created: 2026-03-15T11:30
title: Consolidate three 1D bar builder scripts into one unified builder
area: refactor
files:
  - src/ta_lab2/scripts/bars/refresh_price_bars_1d.py (CMC, 822 lines)
  - src/ta_lab2/scripts/bars/refresh_tvc_price_bars_1d.py (TVC, 511 lines)
  - src/ta_lab2/scripts/bars/refresh_hl_price_bars_1d.py (HL, 572 lines)
  - src/ta_lab2/scripts/bars/run_all_bar_builders.py
  - src/ta_lab2/scripts/bars/base_bar_builder.py (reference, no changes)
  - src/ta_lab2/scripts/bars/bar_builder_config.py (reference, no changes)
priority: medium
---

# Consolidate Three 1D Bar Builders Into One

## Problem

Three separate 1D bar builder scripts are ~80% identical code. Each writes to
the same `price_bars_1d` table, shares the same state table, and has the same
output column schema. ~600 lines of duplicated code across the three files
(psycopg helpers, state operations, coverage tracking, CLI parsing).

Adding a new exchange source today means copying an entire file and modifying ~20%.

## Current Differences Per Source

| Aspect | CMC | TVC | HL |
|--------|-----|-----|-----|
| Source table | `cmc_price_histories7` | `tvc_price_histories` | `hyperliquid.hl_candles` |
| Source JOINs | none | `dim_listings` | `dim_asset_identifiers` + `dim_listings` |
| time_high/low | real columns — needs OHLC repair | synthesized as `ts` | synthesized as `ts` |
| market_cap | `s.marketcap` | NULL | NULL |
| venue / venue_id | CMC_AGG / 1 | from source / lookup | HYPERLIQUID / 2 |
| ID loading | `SELECT DISTINCT id FROM source` | same | CSV filter + dim_asset_identifiers |
| src_name | `'CMC'` | `'TradingView'` | `'Hyperliquid'` |
| OHLC repair CTEs | yes (base → repaired, 6 total CTEs) | no (4 CTEs) | no (4 CTEs) |
| Backfill detection | yes | **missing** (should have it) | **missing** (should have it) |
| Post-build sync | no | `_sync_1d_to_multi_tf` | `_sync_1d_to_multi_tf` |
| Extra CLI args | `--keep-rejects` | `--venue` | `--csv` |

### OHLC Repair (CMC-only, correctly so)
CMC's `cmc_price_histories7` has independent `timehigh`/`timelow` columns that
sometimes have bad values (outside the `[timeopen, timeclose]` range). The repair
logic (2 extra CTEs: `base` + `repaired`) detects and fixes these. TVC and HL
don't need repair because they don't HAVE real timehigh/timelow — they synthesize
them as the bar's timestamp, so they're always valid by construction.

### Backfill Detection (CMC-only, should be all)
Detects when historical data is added before the earliest previously-processed date.
If detected, triggers automatic full rebuild. Currently only in CMC builder but
should apply to all sources for data quality.

### 6 CTEs vs 4 CTEs
- CMC: `ranked_all → src_rows → base → repaired → final → ins` (6 steps)
- TVC/HL: `src_filtered → ranked → final → ins` (4 steps)
- The extra 2 CMC CTEs are for OHLC time_high/time_low repair logic

## Proposed Design

### 1. SourceSpec dataclass
```python
@dataclass
class SourceSpec:
    name: str                     # "cmc", "tvc", "hl"
    src_name: str                 # "CMC", "TradingView", "Hyperliquid"
    source_table: str             # fully qualified table name
    venue: str | None             # None = from source data, or hardcoded string
    venue_id: int | None          # None = lookup, or hardcoded int
    has_real_time_highlow: bool   # True = include repair CTEs
    has_market_cap: bool
    sync_to_multi_tf: bool
    source_cte_sql: str           # SQL template for the source CTE
    id_loader: Callable           # (db_url, cli_args) -> list[int]
    extra_cli_args: Callable | None  # optional extra CLI args
```

### 2. Source registry dict
```python
SOURCE_REGISTRY = {"cmc": SourceSpec(...), "tvc": SourceSpec(...), "hl": SourceSpec(...)}
```
Adding a new source = adding one entry here.

### 3. Unified OneDayBarBuilder class
Single class that:
- Takes `--source cmc|tvc|hl` CLI arg to select SourceSpec
- Assembles SQL CTE chain by composing fragments:
  - Source CTE (from spec.source_cte_sql, source-specific)
  - Repair CTEs (conditional, only if spec.has_real_time_highlow)
  - Ranked/final/ins CTEs (shared across all sources)
- Applies backfill detection to ALL sources
- Runs post-build sync if spec.sync_to_multi_tf

### 4. File changes
- **REWRITE** `refresh_price_bars_1d.py` as unified builder
- **DELETE** `refresh_tvc_price_bars_1d.py`
- **DELETE** `refresh_hl_price_bars_1d.py`
- **EDIT** `run_all_bar_builders.py` — update builder configs to pass `--source`
- No changes to `run_daily_refresh.py` (already has `--source cmc|tvc|hl|all`)

## Verification

1. Run each source and compare row counts to pre-refactor baseline:
   ```bash
   python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source cmc --ids 1 --full-rebuild
   python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source tvc --ids 100002 --full-rebuild
   python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source hl --ids all --full-rebuild
   ```
2. `SELECT src_name, count(*) FROM price_bars_1d GROUP BY src_name;` — counts match
3. Orchestrator dry-run: `python -m ta_lab2.scripts.bars.run_all_bar_builders --ids 1 --dry-run`
4. Backfill detection works for TVC/HL (not just CMC)

## Pre-refactor Baseline (March 2026)

```sql
-- Run BEFORE refactoring to capture baseline:
SELECT src_name, venue, count(*), count(DISTINCT id), min(timestamp), max(timestamp)
FROM price_bars_1d
GROUP BY src_name, venue
ORDER BY src_name, venue;
```
