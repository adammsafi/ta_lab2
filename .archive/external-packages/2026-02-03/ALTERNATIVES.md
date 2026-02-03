# Economic Data Package Alternatives Guide

**Archived:** 2026-02-03
**Applies to:** fredtools2, fedtools2
**Recommended replacements:** fredapi, fedfred

## 1. Feature Mapping

| fredtools2/fedtools2 Feature | Modern Equivalent | Package | Notes |
|------------------------------|-------------------|---------|-------|
| `fred_api.get_releases(api_key)` | `fred.get_releases()` | fredapi | Returns DataFrame, handles pagination |
| `fred_api.get_series_observations(api_key, series_id)` | `fred.get_series(series_id)` | fredapi | Returns pandas Series with datetime index |
| `jobs.releases.pull_releases()` | `fred.search(text)` + custom DB insert | fredapi | Search replaces release browsing |
| `jobs.series.pull_series()` | `fred.get_series()` + `df.to_sql()` | fredapi + pandas | More flexible storage options |
| `etl.build_dataset()` (Fed targets consolidation) | Custom logic + `fred.get_series()` | fredapi | TARGET_MID logic must be replicated |
| `utils.consolidation.combine_timeframes()` | `pd.merge()` + `ffill()` | pandas | Standard pandas operations |
| `sql_sink_example.write_dataframe_and_log()` | `df.to_sql()` + manual log | pandas + SQLAlchemy | Standard pattern |
| PostgreSQL schema management | Alembic migrations | alembic | Industry standard |
| Rate limiting (none) | Built-in (120/min) | fedfred | Major improvement |
| Caching (none) | Built-in TTL cache | fedfred | Major improvement |
| Data revisions (none) | ALFRED support | fredapi | Access historical vintages |

## 2. API Comparison

### Fetching Series Data

**fredtools2 (archived):**
```python
from fredtools2.config import fred_api_key
from fredtools2 import fred_api as client

api = fred_api_key()
obs = client.get_series_observations(api, "FEDFUNDS")
# Returns list of dicts: [{"date": "2024-01-01", "value": "5.33"}, ...]
```

**fredapi (recommended):**
```python
from fredapi import Fred
import os

fred = Fred(api_key=os.getenv("FRED_API_KEY"))
series = fred.get_series("FEDFUNDS")
# Returns pandas Series with DatetimeIndex, float values
```

**fedfred (async alternative):**
```python
from fedfred import Fred
import asyncio

fred = Fred(api_key=os.getenv("FRED_API_KEY"))
# Sync
series = fred.get_series("FEDFUNDS")
# Async (high-volume)
series = asyncio.run(fred.get_series_async("FEDFUNDS"))
```

### Storing to Database

**fredtools2 (archived):**
```python
from fredtools2.db import connect
from psycopg2.extras import execute_values

conn = connect()
with conn.cursor() as cur:
    execute_values(cur, "INSERT INTO fred_series_values ...", rows)
conn.commit()
```

**Modern approach:**
```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine("postgresql://user:pass@host/db")
series.to_frame("value").to_sql("fred_series_values", engine, if_exists="append")
```

### Fed Targets Consolidation (fedtools2 unique logic)

**fedtools2 (archived):**
```python
from fedtools2.etl import build_dataset

df = build_dataset(cfg)
# Merges FEDFUNDS, DFEDTAR, DFEDTARL, DFEDTARU
# Computes TARGET_MID, TARGET_SPREAD, regime labels
```

**Modern equivalent (must replicate logic):**
```python
from fredapi import Fred
import pandas as pd
import numpy as np

fred = Fred(api_key=os.getenv("FRED_API_KEY"))

# Fetch all series
fedfunds = fred.get_series("FEDFUNDS")
dfedtar = fred.get_series("DFEDTAR")
dfedtarl = fred.get_series("DFEDTARL")
dfedtaru = fred.get_series("DFEDTARU")

# Merge and compute TARGET_MID
df = pd.DataFrame({
    "FEDFUNDS": fedfunds,
    "DFEDTAR": dfedtar,
    "DFEDTARL": dfedtarl,
    "DFEDTARU": dfedtaru
})
df["TARGET_MID"] = df["DFEDTAR"].where(
    df["DFEDTAR"].notna(),
    (df["DFEDTARL"] + df["DFEDTARU"]) / 2
)
df["TARGET_SPREAD"] = df["DFEDTARU"] - df["DFEDTARL"]
```

## 3. Migration Effort Estimates

| Migration Scenario | Effort | Notes |
|--------------------|--------|-------|
| Basic FRED series fetch | 5 min | Direct fredapi replacement |
| Series with DB storage | 30 min | Replace custom schema with pandas to_sql |
| Full fredtools2 workflow | 2 hours | Replace PostgreSQL schema, update all queries |
| Full fedtools2 workflow | 4 hours | Replicate TARGET_MID logic, regime labels, SQL sink |
| High-volume async | 1 hour | Switch to fedfred, add asyncio |
| Add caching/rate limiting | 0 min | Built into fedfred |

**Complexity factors:**
- Schema migration: If using fredtools2's PostgreSQL schema (fred_series_values, releases, pull_log), need to either keep schema or migrate to new structure
- TARGET_MID logic: fedtools2's TARGET_MID calculation handles pre-2008 (single target) vs post-2008 (target range) - must preserve this logic
- Regime labels: fedtools2 assigns "pre-target", "single-target", "target-range" labels based on date ranges

## 4. Ecosystem Maturity

| Package | First Release | Last Update | GitHub Stars | Maintenance | Production Ready |
|---------|---------------|-------------|--------------|-------------|------------------|
| **fredapi** | 2014 | 2024 | 700+ | Active | Yes (10+ years) |
| **fedfred** | 2024 | 2025 | 50+ | Active | Yes (modern) |
| fredtools2 | 2024 | 2024 | 0 | Archived | No (custom, unmaintained) |
| fedtools2 | 2024 | 2024 | 0 | Archived | No (custom, unmaintained) |

### fredapi Stability
- Maintained by original author (mortada)
- Handles all FRED API edge cases (pagination, file_type, revision dates)
- ALFRED support for historical data vintages
- Used by quantitative finance community
- No breaking changes in 5+ years

### fedfred Modernity
- Async support for concurrent requests
- Built-in rate limiting (120 calls/min FRED limit)
- Automatic caching with configurable TTL
- Pandas, Polars, Dask, GeoPandas output formats
- Modern Python 3.10+ design

### Why Archive Custom Packages?
1. **Zero usage:** No imports in ta_lab2 codebase
2. **Maintenance burden:** Custom wrappers require updates for FRED API changes
3. **Missing features:** No caching, rate limiting, revision handling
4. **Ecosystem coverage:** fredapi/fedfred handle 99% of use cases
5. **Single maintainer:** Custom packages have bus factor of 1

## Decision Summary

**For ta_lab2 economic data needs:**
- Use **fredapi** for standard FRED access (most mature, battle-tested)
- Use **fedfred** for high-volume/async workflows (modern, performant)
- Replicate **fedtools2 TARGET_MID logic** in ta_lab2.utils.economic if needed

**Do not restore archived packages unless:**
- Ecosystem alternatives cannot handle a specific edge case
- Domain-specific logic (TARGET_MID, regime labels) is needed AND cannot be replicated
