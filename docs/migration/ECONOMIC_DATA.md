# Economic Data Migration Guide

This guide helps migrate from archived `fredtools2`/`fedtools2` packages to the new `ta_lab2.integrations.economic` module.

## Quick Migration

### Before (fredtools2)
```python
from fredtools2.config import fred_api_key
from fredtools2 import fred_api as client

api = fred_api_key()
obs = client.get_series_observations(api, "FEDFUNDS")
```

### After (ta_lab2.integrations.economic)
```python
from ta_lab2.integrations.economic import FredProvider

provider = FredProvider()  # Uses FRED_API_KEY env var
result = provider.get_series("FEDFUNDS")
if result.success:
    data = result.series.data  # pandas Series
```

## Installation

```bash
# Install FRED integration
pip install ta_lab2[fred]

# Or install all economic integrations
pip install ta_lab2[economic]
```

## Configuration

1. Get a FRED API key: https://fred.stlouisfed.org/docs/api/api_key.html
2. Copy `economic_data.env.example` to `economic_data.env`
3. Add your API key

```bash
cp economic_data.env.example economic_data.env
# Edit economic_data.env and set FRED_API_KEY
```

## Migration Mapping

| Old Import | New Import |
|------------|------------|
| `from fredtools2.config import fred_api_key` | `os.getenv("FRED_API_KEY")` |
| `from fredtools2 import fred_api` | `from ta_lab2.integrations.economic import FredProvider` |
| `from fedtools2.etl import build_dataset` | `from ta_lab2.utils.economic import combine_timeframes` |
| `from fedtools2.utils.consolidation import combine_timeframes` | `from ta_lab2.utils.economic import combine_timeframes` |

## Feature Comparison

| Feature | fredtools2 | ta_lab2.integrations.economic |
|---------|------------|-------------------------------|
| Series fetch | Yes | Yes |
| Search | No | Yes |
| Metadata | Limited | Full |
| Caching | No | Yes (TTL) |
| Rate limiting | No | Yes (120/min) |
| Circuit breaker | No | Yes |
| Data quality | No | Yes |
| Type hints | Partial | Full |
| Documentation | Minimal | Comprehensive |

## Detailed Examples

### Fetching a Single Series

```python
from ta_lab2.integrations.economic import FredProvider

provider = FredProvider()

# Basic fetch
result = provider.get_series("UNRATE")
if result.success:
    series = result.series
    print(f"Unemployment Rate: {series.data.iloc[-1]:.1f}%")
    print(f"Last updated: {series.last_updated}")
```

### Fetching Multiple Series

```python
# Fetch multiple series
series_ids = ["FEDFUNDS", "DGS10", "DGS2", "UNRATE"]
results = provider.get_multiple_series(series_ids)

for result in results:
    if result.success:
        print(f"{result.series.series_id}: {result.series.data.iloc[-1]:.2f}")
```

### Using Extracted Utilities

```python
from ta_lab2.utils.economic import combine_timeframes, missing_ranges
import pandas as pd

# Combine multiple time series
df1 = pd.DataFrame({"date": ["2024-01-01"], "value": [100]})
df2 = pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "value": [200, 201]})

merged = combine_timeframes([df1, df2], ["series1", "series2"])
print(merged.columns)  # ['series1_value', 'has_series1', 'series2_value', 'has_series2']

# Detect gaps
gaps = missing_ranges(merged["has_series1"] == False)
for start, end in gaps:
    print(f"Gap: {start} to {end}")
```

## Migration Tool

Use the migration tool to scan your code for old imports:

```bash
python -m ta_lab2.integrations.economic.migration_tool /path/to/your/code
```

This will identify files using old `fredtools2`/`fedtools2` imports and suggest replacements.

## Archived Packages

The original packages are preserved in `.archive/external-packages/2026-02-03/`:
- `fredtools2/` - Original FRED API wrapper
- `fedtools2/` - Original Fed data ETL
- `ALTERNATIVES.md` - Ecosystem comparison
- `manifest.json` - File inventory with checksums

See `ALTERNATIVES.md` for detailed comparison with ecosystem alternatives (fredapi, fedfred).

## Support

- Issues: Open a GitHub issue
- Questions: Check the codebase or contact the maintainer
