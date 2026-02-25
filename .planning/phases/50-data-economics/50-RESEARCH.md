# Phase 50: Data Economics - Research

**Researched:** 2026-02-25
**Domain:** Data infrastructure cost audit, build-vs-buy analysis, vendor comparison, decision framework
**Confidence:** MEDIUM-HIGH (vendor pricing from official sources; storage/compute cost models use verified unit costs with extrapolation)

---

## Summary

This research supports a comprehensive cost audit and build-vs-buy analysis for the ta_lab2 data infrastructure. The current architecture is a local PostgreSQL database (~50+ tables, ~40M total rows) backed by manually downloaded CoinMarketCap JSON files, with exchange APIs used only for live price feeds. The architecture has zero ongoing API cost for the primary data source (CoinMarketCap OHLCV is loaded from bulk downloads, not live API calls), modest but growing PostgreSQL storage costs, and significant developer time as the dominant cost component.

The three-way comparison reveals: (1) current model (local PostgreSQL + manual data loads) is the lowest TCO option at current scale, (2) DIY cloud data lake (S3 + Parquet + DuckDB/Athena) saves on compute at the cost of migration complexity, and (3) managed platforms (TimescaleDB Cloud, Snowflake) add vendor cost but reduce operational burden. At 2x scale (equities expansion), the current model remains viable with partitioning. At 5x scale (minute bars, multi-asset-class), PostgreSQL hits real limits and migration becomes justified.

**Primary recommendation:** Stay on local PostgreSQL through 2x scale. Prepare a migration playbook for the 5x trigger. Evaluate CoinGecko API as the primary data vendor upgrade path when CMC bulk access becomes insufficient.

---

## Infrastructure Inventory (Current State)

### Data Sources — CRITICAL FINDING

**CoinMarketCap OHLCV data is loaded from local JSON files, NOT from live API calls.**

Evidence from codebase:
- `seed_data_sources.py`: `source_type: "file_load"` for `cmc_price_histories`
- `db-keys.md`: `cmc_price_histories7` source is `C:\Users\asafi\Downloads\cmc_price_histories\`
- `update_cmc_history.py`: calls `upsert_cmc_history(source_file="C:/Users/Adam/Downloads/cmc_XXXX.json")`

This means the CMC API is used only for reference data (asset IDs, exchange maps) and the historical OHLCV is sourced from bulk downloads. This fundamentally changes the cost audit: CMC API is currently free tier (10,000 credits/month for reference endpoints) or possibly zero ongoing cost.

**Active API calls by type:**
| Source | Type | Endpoint | Frequency | Tier/Cost |
|--------|------|----------|-----------|-----------|
| CoinMarketCap | Reference (asset IDs, exchange info) | `/cryptocurrency/map`, `/exchange/map` | Infrequent | Free Basic (10k credits/month) |
| CoinMarketCap | OHLCV bulk download | Manual JSON file | Manual/ad-hoc | Unknown — possibly free account download |
| alternative.me | Fear & Greed Index | `api.alternative.me/fng/` | Daily | Free (no key required) |
| Coinbase Advanced Trade | Live price spot | REST GET | On-demand | Free (public endpoint, 10 req/sec) |
| Kraken | Live price spot | REST GET | On-demand | Free (public endpoint) |
| companiesmarketcap.com | Asset universe scrape | Web scrape | Daily | Free (scrape) |
| TradingView | OHLCV for equities/ETFs | CSV export | Manual | Free (export from TradingView account) |

**Current API cost: $0/month** — all primary data is either file-based, scraped, or free public endpoints.

### Database Tables — Complete Inventory

| Table Family | Tables | Approx Rows | Notes |
|-------------|--------|-------------|-------|
| Price Bars | cmc_price_bars_1d + 5 multi-TF variants + _u | ~4.1M | Primary bar data |
| Bar Returns | 5 variants + _u | ~4.1M | Derived from bars |
| EMA Values | cmc_ema_multi_tf + 4 calendar variants + _u | ~14.8M | 109 TFs x N periods |
| EMA Returns | 4 variants + _u | ~16M | EMA-based returns |
| AMA Tables | 4 families x 3 variants = 12 tables | ~1-2M est. | Adaptive MAs |
| cmc_features | 1 table | ~2.1M | 112 columns |
| Regime Tables | cmc_regimes, flips, stats, comovement | ~100k est. | Policy outputs |
| Signal Tables | cmc_signals + backtest tables | ~50k est. | Strategy outputs |
| Reference/Dim | dim_assets, dim_timeframe, dim_sessions, etc. | ~50k est. | Lookup tables |
| Source Data | cmc_price_histories7, tvc_price_histories | ~2-3M est. | Raw OHLCV source |
| State Tables | pipeline state, bar state, EMA state | ~10k est. | Watermark tracking |
| Observability | QC stats, coverage, backtest runs | ~100k est. | Audit trail |
| **TOTAL** | **~55+ tables** | **~47M rows** | 2 assets, 109 TFs |

### Storage Estimate (Current)

Using ~50-100 bytes/row average (mixed wide tables up to 112 cols and narrow reference tables):
- Raw data: ~47M rows x 75 bytes avg = ~3.5 GB data
- Index overhead: ~2-3x multiplier for PostgreSQL index-heavy schema = ~7-10 GB total DB size
- **Estimated current DB size: 8-12 GB on local Windows 11 machine**

This is a rough estimate. The planner should include a task to run actual `pg_database_size()` and `pg_total_relation_size()` queries as part of the audit.

### Compute (Daily Refresh Pipeline)

From `run_daily_refresh.py` timeout definitions and STATE.md:
- Bar builders: up to 2 hours (full rebuild), ~5-15 min incremental
- EMA refreshers: up to 1 hour, ~10-20 min incremental
- AMA refreshers: up to 1 hour, ~5-10 min incremental
- Desc stats, regimes, signals, executor, stats: 30 min each max

**Estimated daily incremental refresh: 20-45 minutes of Python/PostgreSQL compute on a local Windows 11 laptop**

Infrastructure cost is $0 — running locally, no cloud compute charges.

### Developer Time (Dominant Cost)

From STATE.md performance metrics:
- 235 plans completed at average 7 min per plan = ~28 hours total execution time
- These are AI-executed plans; human oversight/review adds multiplier
- Pipeline maintenance (debugging, schema changes, new assets): estimated 2-5 hours/month at current scale
- Asset onboarding: 15-40 minutes per asset (Phase 21-04 checklist, 6 steps)

**Developer time is the #1 cost driver.** At even $50/hr, 4 hrs/month maintenance = $200/month, dwarfing any API or storage cost at current scale.

---

## Standard Stack

### Core Technologies
| Library/Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PostgreSQL | 12+ | Primary data store | ACID, SQL, mature ecosystem |
| SQLAlchemy | 2.0.44 | ORM + DB abstraction | Standard Python DB toolkit |
| pandas | 2.2.3 | Data processing | Universal data science tool |
| psycopg2/psycopg3 | 2.9+/3.x | PostgreSQL driver | Standard Pg adapter |
| pyarrow | 19.0.1 | Parquet read/write | Already installed in project |

### Supporting (Already Installed, Underutilized)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| DuckDB | (not installed) | OLAP query engine on Parquet | At 5x scale with data lake |
| yfinance | 0.2.53 | Yahoo Finance data | Alternative to manual TVC CSV downloads |
| fredapi | 0.5.2 | FRED economic data | Macro indicators already available |

---

## Data Vendor Landscape

### Crypto Data Vendors

| Vendor | Free Tier | Entry Paid | Key Strength | Historical Depth | OHLCV Access |
|--------|-----------|------------|--------------|-----------------|--------------|
| **CoinMarketCap** (current) | 10k credits/month, no historical | $29/mo (Hobbyist) = 12mo hist | Brand recognition, wide coverage | Free: none; $29: 12mo; $79: 24mo | Manual bulk download (current) or $79/mo API |
| **CoinGecko** | 50 calls/min, 1yr history | $129/mo (Analyst) = full history to 2013 | 18k+ coins, widest coverage, DEX data | Free: 1yr; $129: full since 2013 | Yes, via API |
| **Kaiko** | None | Enterprise only (contact sales) | Institutional, SOC-2, tick data to 2010 | Full since 2010, tick-level | Enterprise pricing only |
| **CryptoCompare** | Limited free | ~$99-500/mo | Consumer apps | Moderate | Yes |
| **CoinAPI** | 100 req/day | ~$79/mo | Multi-exchange aggregation | Moderate | Yes |
| **Binance API** | Free | Free | BTC/ETH spot, minute bars | ~1yr for minute | Free public endpoint |
| **Kraken API** (current) | Free public | Free | BTC/ETH spot OHLCV | Limited: 720 candles per call | Free but 720-candle limit |

**Recommendation for crypto data upgrade:** CoinGecko Analyst ($129/mo) provides the best value — full history to 2013 for 18k+ coins via API, replacing manual CMC JSON downloads. Kaiko only makes sense at institutional scale with compliance requirements.

### Equities/ETF Data Vendors (For 2x Scale Expansion)

| Vendor | Free Tier | Entry Paid | Coverage | Historical Depth | Notes |
|--------|-----------|------------|---------|-----------------|-------|
| **Polygon.io** (now Massive) | 5 calls/min, 2yr history | $29/mo Starter = 5yr, unlimited calls | Stocks, options, crypto | Free: 2yr; $29: 5yr; $79: 10yr | US equities focus |
| **Alpha Vantage** | 25 calls/day | $50/mo = 1200 req/min | Stocks, FX, crypto | Varies | Developer-friendly |
| **Yahoo Finance (yfinance)** | Free | Free | US equities | ~30+ years | No API key, but ToS restrictions, may break |
| **Alpaca** | Free for most data | Free with account | US equities + crypto | 6+ years | Includes trading API, good for paper trading |
| **EODHD** | Limited | $20/mo | Multi-market | Deep history | Good value for small scale |
| **IEX Cloud** | DISCONTINUED | - | - | - | Shut down Aug 31, 2024 |

**Recommendation for equities expansion:** Alpaca free tier for US equities (BTC/ETH spot + stocks, 6yr history, trading API included). Supplement with yfinance for older history where needed. Polygon.io Starter ($29/mo) if you need real data quality SLAs.

---

## Architecture Alternatives

### Option A: Current Model (Local PostgreSQL + File-Based Ingestion)

**Architecture:**
```
CoinMarketCap bulk download (manual) -> JSON files -> PostgreSQL
TradingView CSV (manual) -> cmc_price_histories7 / tvc_price_histories -> PostgreSQL
Exchange APIs (live) -> exchange_price_feed -> PostgreSQL
Daily refresh pipeline (Python) -> 55+ derived tables
```

**Costs (Current Scale, 2 assets, 109 TFs, daily bars):**
| Category | Monthly Cost | Notes |
|----------|-------------|-------|
| API fees | $0 | No live paid APIs |
| Storage | $0 | Local machine, no cloud |
| Compute | $0 | Local machine |
| Developer time (pipeline maint.) | ~$200-400 | 4-8 hrs @ $50/hr |
| **Total** | **~$200-400/month** | Developer time dominates |

**Costs at 2x Scale (10 assets, equities added, still daily bars):**
| Category | Monthly Cost | Notes |
|----------|-------------|-------|
| API fees | $29-129/mo | Polygon.io Starter or CoinGecko Analyst |
| Storage | $0 | Local machine |
| Compute | $0 | Local machine, longer run times |
| Developer time | ~$400-800 | More assets = more maintenance |
| **Total** | **~$430-930/month** | |

**Costs at 5x Scale (50+ assets, hourly/minute bars, multi-asset-class):**
| Category | Monthly Cost | Notes |
|----------|-------------|-------|
| API fees | $200-700/mo | Multiple vendors for crypto + equities |
| Storage | $50-200 | PostgreSQL may need cloud hosting or SSD upgrades |
| Compute | $100-500 | Larger machine or cloud VM for pipeline |
| Developer time | ~$1,000-2,000 | Schema complexity, data quality, multi-vendor |
| **Total** | **~$1,350-3,400/month** | |

**Migration LOE:** 0 (no migration needed)

**PostgreSQL limits at scale (see Pitfalls section):**
- Current: 47M rows, ~8-12GB — fully capable
- 2x (daily, 10 assets): ~235M rows, ~60GB — still viable with partitioning
- 5x (hourly, 50 assets): ~2.8B rows, ~700GB — PostgreSQL approaching limits; partitioning required, query latency degrades

---

### Option B: DIY Cloud Data Lake (S3/GCS + Parquet + Query Engine)

**Architecture:**
```
APIs -> Python ingestion -> Parquet files on S3/GCS
DuckDB (local) or AWS Athena / BigQuery -> analytics queries
PostgreSQL (reduced) -> operational tables (signals, orders, state)
```

**Costs (2x Scale, ~10 assets, daily bars):**
| Category | Monthly Cost | Notes |
|----------|-------------|-------|
| API fees | $129/mo | CoinGecko Analyst |
| S3 storage (50GB Parquet) | ~$1.15 | $0.023/GB |
| Athena queries (moderate use) | ~$5-20 | $5/TB scanned, well-partitioned Parquet |
| PostgreSQL (still needed for ops) | $0 local or $30-50 cloud | Operational tables only |
| Developer time | ~$600-1,000 | Higher: dual infrastructure to maintain |
| **Total** | **~$736-1,200/month** | More expensive than current at 2x |

**Costs (5x Scale, ~50 assets, hourly bars):**
| Category | Monthly Cost | Notes |
|----------|-------------|-------|
| API fees | $500-1,000/mo | Multiple vendors |
| S3 storage (500GB Parquet) | ~$11.50 | Well-compressed Parquet |
| Athena/DuckDB queries | ~$20-100 | Cheap with good partitioning |
| PostgreSQL (ops only) | $50-100 | Small cloud instance |
| Developer time | ~$800-1,200 | More predictable than PostgreSQL at this scale |
| **Total** | **~$1,382-2,412/month** | Comparable to PostgreSQL option |

**Migration LOE:** 4-8 weeks
- 2 weeks: Set up S3 bucket, write Parquet ingestion pipeline, partition strategy (asset/date/tf)
- 2-4 weeks: Rewrite read paths to query Parquet instead of PostgreSQL tables
- 2 weeks: Testing, validation, cutover

**Key advantage:** Parquet + columnar query engines scale much better for analytical read workloads. DuckDB can read S3 Parquet files directly from local machine — no server needed.

---

### Option C: Managed Platform

#### Option C1: TimescaleDB Cloud (Tiger Cloud)

**Architecture:**
```
APIs -> Python ingestion -> TimescaleDB (hypertables with auto-partitioning)
Continuous aggregates -> pre-computed views
Same Python pipeline, but cloud-hosted PostgreSQL
```

**Costs (2x Scale):**
| Category | Monthly Cost | Notes |
|----------|-------------|-------|
| API fees | $129/mo | CoinGecko Analyst |
| TimescaleDB Performance plan | ~$50-100 | $30/mo compute + $0.177/GB storage |
| Storage (60GB) | ~$11 | $0.177/GB effective |
| Developer time | ~$300-500 | Less maintenance vs self-hosted |
| **Total** | **~$490-740/month** | |

**Key advantage:** PostgreSQL-compatible (zero code changes), automatic time-series partitioning (hypertables), 10x compression, continuous aggregates for fast analytics. Free trial available.

**Migration LOE:** 1-2 weeks (just change connection string, apply TimescaleDB-specific DDL for hypertables)

#### Option C2: Snowflake / Databricks

These are enterprise platforms designed for 100TB+ workloads. Not cost-effective at current or 2x scale.

At 5x scale:
- Snowflake: $25,000-40,000/month for financial services analytics at 200TB
- Databricks: Higher, not justified for quant research at this scale

**Verdict:** Skip Snowflake/Databricks. Not relevant until assets > 500 and data > 10TB.

#### Option C3: MotherDuck (Managed DuckDB)

**Architecture:** DuckDB SaaS, SQL interface, stores data in cloud, queryable from Python

**Costs:**
- $0 free tier: 10GB storage, community support
- $49/mo plan: higher limits
- Good fit for analytics, not operational writes

**Migration LOE:** 2-3 weeks to port read queries; write path remains PostgreSQL

---

## PostgreSQL Scaling Analysis

### Current Baseline

| Metric | Current | 2x (10 assets, daily) | 5x (50 assets, hourly) |
|--------|---------|----------------------|------------------------|
| Row count | ~47M | ~235M | ~2.8B |
| DB size | ~8-12GB | ~60GB | ~700GB |
| Unique assets | 2 | 10 | 50 |
| Bar frequency | Daily | Daily | Hourly |
| EMA table rows | ~14.8M | ~74M | ~880M |

### PostgreSQL Performance Thresholds

| Scale | Query Latency | Index Size | Concern |
|-------|-------------|-----------|---------|
| Current (47M rows) | <100ms for indexed queries | Small, fits in RAM | None |
| 2x (235M rows) | 100-500ms | Moderate | Consider partitioning |
| 5x (2.8B rows) | Multi-second without partitioning | Large, doesn't fit in RAM | Partitioning required, VACUUM slow |

**PostgreSQL starts hurting at 100M+ rows per table without partitioning.** The current cmc_ema_multi_tf tables (~14.8M rows total across multiple tables) are well within limits. At 5x scale with hourly bars, individual tables would exceed 100M rows and need range partitioning by asset+date.

**TimescaleDB hypertables** solve this automatically — PostgreSQL-compatible but auto-partitions time-series tables into "chunks" for efficient queries and VACUUM.

### Partitioning Strategy (If Staying on PostgreSQL)

```sql
-- Example: Partition cmc_ema_multi_tf by (id, date range)
CREATE TABLE cmc_ema_multi_tf (
    id INTEGER,
    ts TIMESTAMPTZ,
    tf TEXT,
    period INTEGER,
    ema DOUBLE PRECISION
) PARTITION BY RANGE (ts);

-- Create monthly partitions
CREATE TABLE cmc_ema_multi_tf_2024_01
    PARTITION OF cmc_ema_multi_tf
    FOR VALUES FROM ('2024-01-01') TO ('2024-02-01');
```

**Implementation effort:** 2-4 weeks to convert existing tables to partitioned tables without downtime.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Time-series partitioning | Custom partition management | TimescaleDB hypertables | Auto-chunks, handles VACUUM, continuous aggregates |
| Parquet query engine | Custom Parquet reader | DuckDB | Orders of magnitude faster, single binary, Python API |
| API rate limiting | Custom rate limiter | tenacity + time.sleep | Edge cases in backoff logic |
| Multi-vendor data normalization | Custom schema mapping | Vendor SDK + thin adapter | Each vendor has quirks; their SDK handles them |
| Cost allocation | Manual spreadsheet | Actual DB query + time tracking | pg_stat_user_tables gives real sizes |
| TCO template | Custom framework | Multi-factor scoring matrix | Use established 5-factor build-vs-buy framework |

---

## Common Pitfalls

### Pitfall 1: Underestimating Developer Time in TCO

**What goes wrong:** Cost audits compare API cost ($0 vs $129/mo) while ignoring that developer time to maintain the pipeline is 5-10x any vendor cost.
**Why it happens:** Developer time is invisible in month-to-month spending.
**How to avoid:** Charge developer time at market rate ($50-150/hr) in every TCO comparison. Use STATE.md phase execution times as proxy.
**Warning signs:** TCO analysis shows alternatives cost "2x more" when the calculation excludes maintenance hours.

### Pitfall 2: CoinMarketCap Bulk Download Dependency Risk

**What goes wrong:** Current model relies on manually downloading JSON files from CMC's website. If CMC changes their export mechanism or requires paid access for bulk downloads, the entire pipeline breaks.
**Why it happens:** Bulk downloads are not a documented API feature; they're a UI convenience.
**How to avoid:** Document the current CMC bulk download process in the cost audit. Verify whether it requires any account tier. Identify CoinGecko API as the fallback.
**Warning signs:** Manual process, no API key used, file path hardcoded to `C:\Users\Adam\Downloads\`.

### Pitfall 3: Minute Bar Storage Shock

**What goes wrong:** Moving from daily to hourly bars increases rows by 24x. Moving to minute bars = 1440x. A table with 4.1M rows becomes 5.9 BILLION rows.
**Why it happens:** Linear thinking about data growth when frequency increase is multiplicative.
**How to avoid:** Calculate projected row counts explicitly. 50 assets x 10 TFs x 5 years x 1440 minutes/day = 131.4B rows — PostgreSQL cannot handle this without extreme engineering.
**Warning signs:** Any discussion of "let's add minute bars" should trigger immediate architecture review.

### Pitfall 4: PostgreSQL as OLAP Engine

**What goes wrong:** Using PostgreSQL for heavy analytical queries (feature engineering across all TFs, backtesting, IC calculation) gets progressively slower as data grows.
**Why it happens:** PostgreSQL is OLTP (row-store); analytical reads of wide tables are inefficient.
**How to avoid:** Separate the transactional workload (pipeline state, signals, orders) from analytical workload (feature computation, IC evaluation). At 5x scale, analytical queries should move to DuckDB/Parquet.
**Warning signs:** Feature refresh scripts taking >30 minutes, `run_all_feature_refreshes --all-tfs` becoming a multi-hour operation.

### Pitfall 5: Exchange API Rate Limits for Historical Data

**What goes wrong:** Assuming exchange APIs (Coinbase, Kraken) can backfill years of historical minute data. Kraken OHLCV API returns max 720 candles per call and cannot retrieve data older than that window.
**Why it happens:** Exchange APIs are designed for live trading, not historical research.
**How to avoid:** Use dedicated data vendors (CoinGecko, Kaiko, Binance) for historical data. Exchanges are only for live price feeds.
**Warning signs:** Any plan to "get historical data from Coinbase/Kraken" for more than recent data.

### Pitfall 6: Free Tier Fragility

**What goes wrong:** Dependency on free tiers that can change terms (fear greed index, web scraping companiesmarketcap.com, TradingView CSV exports) creates operational risk.
**Why it happens:** "It's free now" ignores vendor relationship risk.
**How to avoid:** Document all free-tier dependencies. For each: assess what happens if it goes away, and what the paid alternative costs.
**Warning signs:** More than 2 critical data sources on free tiers with no fallback.

---

## Code Examples

### Measuring Actual PostgreSQL Table Sizes

```sql
-- Source: PostgreSQL official docs (pg_total_relation_size)
SELECT
    relname AS table_name,
    pg_size_pretty(pg_total_relation_size(relid)) AS total_size,
    pg_size_pretty(pg_relation_size(relid)) AS table_size,
    pg_size_pretty(pg_indexes_size(relid)) AS index_size,
    n_live_tup AS live_rows
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC;

-- Database total size
SELECT pg_size_pretty(pg_database_size('marketdata'));
```

### Projecting Row Counts at Scale

```python
# Source: Internal calculation
ASSETS_CURRENT = 2
ASSETS_2X = 10  # crypto + equities expansion
ASSETS_5X = 50  # breadth AND depth

TRADING_DAYS_PER_YEAR = 365  # crypto is 24/7
YEARS_HISTORY = 5

# Current: daily bars
current_rows = ASSETS_CURRENT * TRADING_DAYS_PER_YEAR * YEARS_HISTORY  # 3,650
# But we have 109 TFs, so multiply:
current_ema_rows = current_rows * 109 * 4  # ~1.6M per EMA period

# At 5x with hourly bars:
hours_per_year = 365 * 24  # 8,760 for crypto
projected_hourly = ASSETS_5X * hours_per_year * YEARS_HISTORY  # 2.19M
# With 109 TFs x 4 EMA periods: 956M rows for EMAs alone
```

### DuckDB Reading Parquet (Future Architecture)

```python
# Source: DuckDB documentation
import duckdb

# Directly query S3 Parquet from local Python
conn = duckdb.connect()
conn.execute("INSTALL httpfs; LOAD httpfs;")

result = conn.execute("""
    SELECT id, ts, close, volume
    FROM 's3://ta-lab2-data/bars/cmc/1D/*.parquet'
    WHERE id IN (1, 1027)
    AND ts >= '2020-01-01'
    ORDER BY id, ts
""").fetchdf()
```

### ADR Format (Standard MADR 4.0 Template)

```markdown
# ADR-001: Data Infrastructure Architecture Choice

**Date:** YYYY-MM-DD
**Status:** Proposed | Accepted | Deprecated | Superseded

## Context and Problem Statement

[Describe the context and the problem being solved]

## Decision Drivers

* [driver 1]
* [driver 2]

## Considered Options

* Option A: [name]
* Option B: [name]
* Option C: [name]

## Decision Outcome

Chosen option: "[option]", because [justification].

### Consequences

* Good: [positive consequence]
* Bad: [negative consequence]
* Neutral: [neutral consequence]

## Alternatives Considered

### Option A: [title]
[description, pros, cons]

### Dissenting View
[Documented arguments for the alternative path]
```

### TCO Decision Matrix (Multi-Factor Scoring)

```python
# Source: Adapted from standard build-vs-buy framework
factors = {
    "monthly_cost_usd": {
        "current": 300,   # developer time only
        "data_lake": 800, # includes migration amortized
        "managed": 600,
        "weight": 3
    },
    "migration_weeks": {
        "current": 0,
        "data_lake": 6,
        "managed": 2,
        "weight": 2
    },
    "asset_count_capacity": {
        "current": 20,  # before performance degrades
        "data_lake": 200,
        "managed": 100,
        "weight": 2
    },
    "query_latency_ms_at_scale": {
        "current": 5000,  # at 5x scale, unpartitioned
        "data_lake": 500,
        "managed": 200,
        "weight": 2
    },
    "operational_complexity": {
        "current": 2,  # low: all local
        "data_lake": 4,  # high: dual infrastructure
        "managed": 3,   # medium: vendor dependency
        "weight": 1
    }
}
# Score each option; lower is better (for cost/latency) or higher for capacity
```

---

## Decision Trigger Framework

### Quantitative Triggers for Migration

The ADR should define migration as triggered when ANY of these conditions are met:

| Trigger | Threshold | Why |
|---------|-----------|-----|
| Monthly data API cost | >$300/month | API now significant relative to TCO |
| Asset count | >20 assets | PostgreSQL queries degrade; asset onboarding time compounds |
| Daily bar count | >500M rows | Index maintenance becomes slow (>1hr for VACUUM/ANALYZE) |
| Bar frequency | Hourly or finer | Row projection exceeds 1B rows within 2 years |
| Refresh pipeline time | >2 hours incremental | Daily refresh becomes operational risk |
| Query latency p95 | >30 seconds for feature queries | Research/backtest iteration slows |
| Developer maintenance time | >20 hrs/month | Operational burden exceeds feature development |

### Weighted Decision Matrix

When evaluating migration, score each option 1-5 on these dimensions and apply weights:

| Dimension | Weight | Why Important |
|-----------|--------|--------------|
| 5-year TCO | 3 | Long-term cost dominates |
| Migration effort (weeks) | 2 | Opportunity cost is high |
| Asset count capacity | 2 | Determines how long option lasts |
| Query performance | 2 | Research iteration speed |
| Vendor lock-in risk | 1 | Data portability |
| Team operational burden | 2 | Hidden cost |

---

## Architecture Patterns

### For the Analysis Report (`reports/data-economics/`)

```
reports/data-economics/
├── README.md          # Executive summary + links
├── cost-audit.md      # Current state, per-asset breakdown
├── vendor-comparison.md  # Crypto + equities vendor matrix
└── tco-model.md       # Three-way architecture comparison at 2x/5x scale
```

### For the ADR (`docs/architecture/`)

```
docs/architecture/
└── ADR-001-data-infrastructure.md   # Formal ADR in MADR 4.0 format
```

### Recommended Approach for Developer Time Estimation

Use GSD execution times from STATE.md as proxy:
- 235 plans at avg 7 min AI execution = 28 hours AI time
- Apply 1.5x human oversight multiplier = ~42 hours human-equivalent over project lifetime
- Monthly maintenance at current scale: 4-8 hours/month (estimated, not measured)
- Per-asset onboarding: 15-40 minutes (measured from Phase 21-04 checklist)

**For the report:** Use a cost range, not a single number. Low estimate: 4 hrs/month maintenance x $50/hr = $200. High estimate: 8 hrs/month x $100/hr = $800. Present as range.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact for ta_lab2 |
|--------------|------------------|--------------|-------------------|
| IEX Cloud | Discontinued Aug 2024 | Aug 2024 | Cannot use; crossed off vendor list |
| CoinMarketCap direct API | File-based bulk loads | Always | Zero API cost, but manual process |
| Snowflake as default managed DB | Snowflake + Databricks + TimescaleDB comparison | 2024-2025 | More options; TimescaleDB best fit for this use case |
| PostgreSQL only | PostgreSQL + DuckDB hybrid possible | 2023-2025 | DuckDB can read Parquet on same machine; no server needed |
| Custom time-series partitioning | TimescaleDB hypertables | Ongoing | Drop-in replacement |
| Polygon.io | Polygon.io rebranded to Massive | 2025 | Same API, new name |

**Deprecated/outdated:**
- IEX Cloud: Shut down, do not reference
- CryptoCompare: Being absorbed into CCData; brand in flux
- yfinance: Still works but violates Yahoo ToS; not suitable for commercial/production use

---

## Open Questions

1. **CoinMarketCap bulk download mechanism**
   - What we know: Data is loaded from local JSON files; source_type is "file_load"
   - What's unclear: Whether this is a free account feature or requires a paid plan; exact URL used to download bulk files
   - Recommendation: Include a task in the plan to document the exact download process and verify it works with free CMC account

2. **Current actual DB size**
   - What we know: Estimated 8-12GB based on row counts and bytes/row
   - What's unclear: Actual size including all indexes, toast, and dead tuples
   - Recommendation: Include `pg_database_size()` query as first task in cost audit

3. **PostgreSQL hosting option for 2x scale**
   - What we know: Currently local-only; at 10 assets with daily bars, ~60GB is manageable locally
   - What's unclear: Whether the project will remain on local dev machine or move to cloud at 2x
   - Recommendation: Treat "cloud hosting" as a separate trigger, not tied to asset count

4. **CoinGecko free tier coverage of BTC/ETH history**
   - What we know: Free tier gives 1yr history; $129/mo Analyst gives full history to 2013
   - What's unclear: Whether BTC history before 2013 is available at any tier
   - Recommendation: Document exactly what CMC bulk download provides vs CoinGecko API, as the two would need to be directly comparable for a switch

5. **TradingView CSV dependency**
   - What we know: Equities/ETF data comes from manual TradingView CSV exports
   - What's unclear: This is a manual process — is it sustainable, and what does paid TV cost?
   - Recommendation: Treat TradingView as a source to migrate away from at 2x scale; Alpaca or Polygon.io preferred

---

## Sources

### Primary (HIGH confidence)
- CoinMarketCap API Pricing page (fetched 2026-02-25): https://coinmarketcap.com/api/pricing/
- PostgreSQL official docs on limits: https://www.postgresql.org/docs/current/limits.html
- TigerData (TimescaleDB Cloud) pricing (fetched 2026-02-25): https://www.tigerdata.com/pricing
- MADR 4.0.0 ADR standard: https://adr.github.io/madr/
- AWS S3 pricing: $0.023/GB standard storage
- Google Cloud Storage pricing: $0.020/GB standard storage

### Secondary (MEDIUM confidence)
- CoinGecko API pricing tiers: https://www.coingecko.com/en/api/pricing (403 on direct fetch; confirmed from search results matching multiple sources)
- Polygon.io pricing: https://massive.com/pricing (confirmed $29 Starter, $79 Developer)
- Coinbase Advanced Trade API rate limits: https://docs.cdp.coinbase.com/advanced-trade/docs/rest-api-rate-limits (30 req/sec private, 10 req/sec public)
- Kraken OHLCV rate limits: https://docs.kraken.com/api/docs/rest-api/get-ohlc-data/ (720 candle limit, public endpoint)
- Alpaca Market Data API: https://docs.alpaca.markets/docs/about-market-data-api (free for most data)

### Secondary (MEDIUM confidence) — Architecture Comparisons
- PostgreSQL billion-row scaling: https://www.tigerdata.com/blog/handling-billions-of-rows-in-postgresql
- DuckDB vs PostgreSQL OLAP: https://www.influxdata.com/comparison/duckdb-vs-postgres
- MotherDuck/DuckDB for Postgres analytics: https://motherduck.com/blog/postgres-duckdb-options/
- Snowflake vs Databricks pricing 2026: https://www.revefi.com/snowflake-databricks-bigquery-pricing-guide-2026

### Tertiary (LOW confidence — single source, unverified exact numbers)
- Kaiko pricing: Enterprise only, no public pricing (confirmed from multiple sources that sales contact required)
- Developer time rate estimates ($50-100/hr) — based on standard market rates, not measured
- PostgreSQL bytes/row estimate (75 bytes avg) — approximation from row estimation examples, actual varies widely by schema
- CoinMarketCap bulk download being free — inferred from file_load source_type and hardcoded local path; needs direct verification

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tools are documented in codebase, versions known
- Architecture: HIGH — PostgreSQL limits are well-documented, cost models use verified unit prices
- Pitfalls: HIGH — derived from actual codebase inspection and industry-documented PostgreSQL scaling behavior
- Vendor pricing: MEDIUM — fetched from official sources but prices change; verify before finalizing report
- Developer time costs: LOW — estimated, not measured; use ranges in report

**Research date:** 2026-02-25
**Valid until:** 2026-08-25 (vendor pricing stable for ~6 months; PostgreSQL scaling is stable)

**Key action for planner:** The biggest research gap is the actual current DB size and the exact CMC bulk download mechanism. Both should be first tasks in the plan (run SQL queries, document CMC download URL). Everything else in the report can be built from the findings above.
