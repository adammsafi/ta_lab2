# Daily Refresh Operations Guide

This guide covers how to run and troubleshoot the daily data refresh workflow.

## Quick Start

```bash
# Full daily refresh (bars + EMAs)
make daily-refresh

# Or with Python directly
python src/ta_lab2/scripts/run_daily_refresh.py --all --verbose
```

## Entry Points

### Unified Script (Recommended)

`run_daily_refresh.py` - Single command for complete refresh

```bash
# Full refresh
python src/ta_lab2/scripts/run_daily_refresh.py --all

# Bars only
python src/ta_lab2/scripts/run_daily_refresh.py --bars

# EMAs only (checks bar freshness first)
python src/ta_lab2/scripts/run_daily_refresh.py --emas

# Specific IDs
python src/ta_lab2/scripts/run_daily_refresh.py --all --ids 1,52,825
```

**Flags:**
- `--all` - Run bars then EMAs
- `--bars` - Run bar builders only
- `--emas` - Run EMA refreshers only
- `--ids X,Y,Z` - Specific asset IDs (or "all")
- `--dry-run` - Show commands without executing
- `--verbose` - Show detailed output
- `--continue-on-error` - Don't stop on failures
- `--skip-stale-check` - Skip bar freshness check for EMAs
- `--staleness-hours N` - Max hours for bar freshness (default: 48.0)

### Separate Scripts

For fine-grained control:

```bash
# Bar builders
python src/ta_lab2/scripts/bars/run_all_bar_builders.py --ids all

# EMA refreshers
python src/ta_lab2/scripts/emas/run_all_ema_refreshes.py --ids all
```

**Bar builder flags:**
- `--ids X,Y,Z` - Specific asset IDs or "all"
- `--builders NAME,NAME` - Run only specific builders (1d, multi_tf, cal_iso, etc.)
- `--skip NAME,NAME` - Skip specific builders
- `--full-rebuild` - Force full rebuild (ignore state)
- `--continue-on-error` - Continue even if a builder fails
- `--verbose` - Show detailed output
- `--dry-run` - Show what would execute

**EMA refresher flags:**
- `--ids X,Y,Z` - Specific asset IDs or "all"
- `--only NAME,NAME` - Run only specific refreshers (multi_tf, cal, cal_anchor, v2)
- `--dry-run` - Show what would execute
- `--verbose` - Show detailed output
- `--continue-on-error` - Continue even if a refresher fails

### Makefile Targets

```bash
make bars              # Run all bar builders
make emas              # Run all EMA refreshers
make daily-refresh     # Full bars + EMAs with logging
make dry-run           # Show what would execute
make validate          # Run validation only
make clean-logs        # Remove logs older than 30 days
```

## Execution Order

### Bars (run_all_bar_builders.py)
1. **1d** - Canonical daily bars from price_histories7
2. **multi_tf** - Multi-timeframe rolling bars (7d, 14d, 30d, ...)
3. **cal_iso** - Calendar-aligned ISO (week, month, quarter, year)
4. **cal_us** - Calendar-aligned US (Sunday week start)
5. **cal_anchor_iso** - Calendar-anchored with partial snapshots (ISO)
6. **cal_anchor_us** - Calendar-anchored with partial snapshots (US)

### EMAs (run_all_ema_refreshes.py)
1. **multi_tf** - Multi-TF EMAs (tf_day based)
2. **cal** - Calendar-aligned EMAs (us/iso)
3. **cal_anchor** - Calendar-anchored EMAs
4. **v2** - Daily-space EMAs (v2)

## Logs and Monitoring

### Log Files

Logs are written to `.logs/refresh-YYYY-MM-DD.log`:

```bash
# View today's log (Linux/Mac)
cat .logs/refresh-$(date +%Y-%m-%d).log

# View today's log (Windows PowerShell)
cat .logs/refresh-$(Get-Date -Format "yyyy-MM-dd").log

# Follow log in real-time
tail -f .logs/refresh-$(date +%Y-%m-%d).log
```

**Log rotation:** Logs older than 30 days are automatically removed by `make clean-logs`.

### Summary Metrics

Each run produces a summary with:
- **Counts:** Bars written, EMAs written, rows processed
- **Timing:** Duration per component
- **Quality:** Gaps flagged, repairs logged, rejects counted
- **Status:** Success/failure per builder/refresher

Example summary output:
```
======================================================================
DAILY REFRESH SUMMARY
======================================================================

Total components: 2
Successful: 2
Failed: 0
Total time: 45.3s

[OK] Successful components:
  - bars: 28.5s
  - emas: 16.8s

======================================================================

[OK] All components completed successfully!
```

### Telegram Alerts

Configure alerts for critical errors:

```bash
export TELEGRAM_BOT_TOKEN="your-token"
export TELEGRAM_CHAT_ID="your-chat-id"

# Alerts configured in scripts/telegram_notifier.py
```

Alerts fire on:
- Database connection errors
- OHLC corruption above threshold
- Validation failures (gaps, duplicates)

**Alert severity levels:**
- `CRITICAL` - Database/corruption errors (always sent)
- `ERROR` - Validation failures, missing data (default threshold)
- `WARNING` - Minor issues (not sent by default)
- `INFO` - Normal operations (not sent)

## Troubleshooting

### Common Issues

**"Bars stale for IDs: [825]"**
- Bar refresh failed or hasn't run for these IDs
- Solution: Run `--all` to refresh bars first, or `--skip-stale-check` if intentional

**"Too many database connections"**
- Multiple parallel processes exhausted connection pool
- Solution: Close other DB clients, or increase max_connections in PostgreSQL

**"Backfill detected for ID X"**
- Historical data was added to source (price_histories7)
- Solution: Run with `--full-rebuild --ids X` to rebuild from scratch

**"EMA validation failed: price bounds violated"**
- EMA values outside 0.5x-2x price range (corruption detected)
- Solution: Check bar data quality, review ema_rejects table for details

**"Mixed line endings" in git pre-commit**
- Windows/Unix line ending differences
- Solution: Let pre-commit hook fix it automatically, re-commit

### Force Full Rebuild

```bash
# Single ID
python src/ta_lab2/scripts/run_daily_refresh.py --all --full-rebuild --ids 825

# All IDs (slow!)
python src/ta_lab2/scripts/run_daily_refresh.py --all --full-rebuild --ids all
```

**Warning:** Full rebuild processes entire history. For 100+ assets, this can take hours.

### Check State

```sql
-- Bar state
SELECT id, last_src_ts, last_run_ts, last_upserted
FROM cmc_price_bars_1d_state
ORDER BY last_run_ts DESC;

-- EMA state
SELECT id, last_load_ts_multi, last_load_ts_cal
FROM cmc_ema_refresh_state
ORDER BY id;
```

### Reset State for ID

```sql
-- Reset bar state (next run will rebuild)
DELETE FROM cmc_price_bars_1d_state WHERE id = 825;

-- Reset EMA state
DELETE FROM cmc_ema_refresh_state WHERE id = 825;
```

### Check for Stale Data

```sql
-- Find IDs with stale bars (> 48 hours)
SELECT id, last_src_ts,
       EXTRACT(EPOCH FROM (now() - last_src_ts)) / 3600 as staleness_hours
FROM cmc_price_bars_1d_state
WHERE EXTRACT(EPOCH FROM (now() - last_src_ts)) / 3600 > 48
ORDER BY staleness_hours DESC;
```

### Verify Data Quality

```bash
# Run validation queries
python src/ta_lab2/scripts/validate_bars.py --ids all

# Check for gaps in 1D bars
SELECT id, COUNT(*) FILTER (WHERE is_missing_days) as gap_count
FROM cmc_price_bars_1d
GROUP BY id
HAVING COUNT(*) FILTER (WHERE is_missing_days) > 0;

# Check EMA rejects
SELECT id, COUNT(*) as reject_count
FROM cmc_ema_multi_tf_rejects
GROUP BY id
ORDER BY reject_count DESC;
```

## Workflow Patterns

### Standard Daily Refresh

```bash
# 1. Run full refresh
make daily-refresh

# 2. Check log for errors
cat .logs/refresh-$(date +%Y-%m-%d).log | grep -E "ERROR|FAILED"

# 3. If errors, investigate specific IDs
python src/ta_lab2/scripts/run_daily_refresh.py --all --ids 825 --verbose
```

### Incremental ID Addition

When adding a new asset to tracking:

```bash
# 1. Ensure asset in dim_assets
# 2. Run full refresh for new ID
python src/ta_lab2/scripts/run_daily_refresh.py --all --ids 1234

# 3. Verify data
SELECT COUNT(*) FROM cmc_price_bars_1d WHERE id = 1234;
SELECT COUNT(*) FROM cmc_ema_multi_tf_u WHERE id = 1234;

# 4. Add to regular rotation (include in "all")
```

### Recovery After Failure

If refresh fails mid-execution:

```bash
# 1. Check which component failed
cat .logs/refresh-$(date +%Y-%m-%d).log | tail -50

# 2. If bars failed, retry bars only
python src/ta_lab2/scripts/run_daily_refresh.py --bars --ids all

# 3. If EMAs failed, retry EMAs only
python src/ta_lab2/scripts/run_daily_refresh.py --emas --ids all

# 4. Or use --continue-on-error to skip past failures
python src/ta_lab2/scripts/run_daily_refresh.py --all --continue-on-error
```

## Cron Setup

For automated daily refresh:

```bash
# crontab -e
# Run at 6 AM UTC daily
0 6 * * * cd /path/to/ta_lab2 && make daily-refresh >> .logs/cron.log 2>&1

# Or with explicit Python path
0 6 * * * cd /path/to/ta_lab2 && /usr/bin/python3 src/ta_lab2/scripts/run_daily_refresh.py --all >> .logs/cron.log 2>&1
```

**Best practices:**
- Run during low-activity hours (e.g., 6 AM UTC)
- Use absolute paths for Python and project directory
- Redirect output to log file for debugging
- Set up email alerts via cron MAILTO or Telegram notifier

## Performance

### Typical Execution Times

| Component | IDs | Time |
|-----------|-----|------|
| 1D bars | 10 | ~5s |
| Multi-TF bars | 10 | ~8s |
| All bar builders | 10 | ~25s |
| All EMA refreshers | 10 | ~15s |
| Full refresh (bars + EMAs) | 10 | ~40s |

**Scaling:** Time scales roughly linearly with number of IDs. 100 IDs ≈ 6-8 minutes total.

### Optimization Tips

1. **Use incremental refresh** - Don't use `--full-rebuild` unless necessary
2. **Run during off-hours** - Reduces database contention
3. **Specific IDs** - Process critical assets first, others later
4. **Continue on error** - Use `--continue-on-error` to process all IDs even if some fail
5. **Parallel execution** - For many IDs, consider sharding across multiple processes

## See Also

- [STATE_MANAGEMENT.md](STATE_MANAGEMENT.md) - State table schemas and patterns
- `src/ta_lab2/scripts/run_daily_refresh.py` - Unified refresh script
- `src/ta_lab2/scripts/bars/run_all_bar_builders.py` - Bar orchestrator
- `src/ta_lab2/scripts/emas/run_all_ema_refreshes.py` - EMA orchestrator
