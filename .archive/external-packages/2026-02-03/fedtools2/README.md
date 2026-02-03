# fedtools2

ETL + utilities to consolidate FRED policy target series (DFEDTAR, DFEDTARL, DFEDTARU) with FEDFUNDS into a unified daily dataset, with a clean CLI.

## Install (editable)

```bash
python -m pip install -e .
```

## CLI

```bash
fedtools2
# or with custom config / diagnostics / plot
fedtools2 --config C:/path/to/my.yaml --verbose-missing --plot
```

Outputs:
- timestamped CSV in `output_dir`
- optional `FED_Merged_latest.csv`

See `fedtools2/config/default.yaml` for configuration.