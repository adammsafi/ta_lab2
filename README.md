# ta_lab2 — Multi-timescale Technical Analysis Lab

A small, modular package for:

- Resampling OHLCV into flexible bins (days, weeks, months, quarters, years, seasons, and n-sized variants)
- Computing features (calendar metadata, EMAs and derivatives, returns, volatility estimators)
- Building regimes / segments and comparing behavior across timeframes
- Producing simple “policy” objects that can guide sizing and risk for strategies

> **Status:** Early preview. Expect breaking changes and sharp edges.

---

## Project layout

High level structure (conceptual):

- `src/ta_lab2/`
  - `io.py` – load/save helpers, partition helpers
  - `resample.py` – calendar and seasonal binning
  - `features/` – calendar (exact seasons, lunar calendar), EMA, returns, volatility, and related utilities
  - `regimes/` – regime / segment labeling utilities and helpers to plug in your own logic  
    - `feature_utils.py` – helpers to ensure required regime features exist
  - `signals/` – signal definitions and registry (for example RSI/EMA-style strategies)
  - `compare.py` – helpers to run the same pipeline on multiple timeframes and compare
  - `cli.py` – command line entry point (multi-command CLI)
- `tests/` – pytest suite, including lightweight smoke tests
- `.github/` – CI, issue templates, PR templates, CODEOWNERS, etc.

Over time this will grow into a more opinionated stack around BTC and related assets; the core is intentionally modular.

---

## Installation

From a clone of the repo:

```bash
git clone https://github.com/<your-username>/ta_lab2.git
cd ta_lab2

# Create and activate a virtualenv however you prefer, then:
pip install --upgrade pip
pip install -e .
```

For development, you will also want pytest:

```bash
pip install pytest
```

---

## Environment / configuration

If you are using a Postgres database for data (CoinMarketCap, FRED, etc.), configure the database URL via an environment variable:

```bash
export TA_LAB2_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"
```

On Windows (PowerShell):

```powershell
$env:TA_LAB2_DB_URL="postgresql://user:pass@localhost:5432/ta_lab2"
```

Many scripts and pipelines will fall back gracefully if this is not set, but anything that needs DB access will expect it.

---

## Quickstart

This is intentionally minimal. The idea is:

1. Load time series data into a DataFrame (for example BTC daily and weekly bars).
2. Ensure the required features for regimes exist.
3. Assess how much data you have at each timeframe.
4. Label regimes at each layer.
5. Resolve a “policy” object that can guide position sizing and risk.

### Example: regime policy from weekly + daily data

```python
import pandas as pd

from ta_lab2.regimes import (
    assess_data_budget,
    label_layer_monthly,
    label_layer_weekly,
    label_layer_daily,
    label_layer_intraday,
    resolve_policy,
)
from ta_lab2.regimes.feature_utils import ensure_regime_features

# Suppose df_w and df_d are your weekly and daily OHLCV DataFrames
# with at least: index as Timestamp, columns: ["open", "high", "low", "close", "volume"]

df_w = ensure_regime_features(df_w, tf="W")
df_d = ensure_regime_features(df_d, tf="D")

ctx = assess_data_budget(weekly=df_w, daily=df_d)

L1 = label_layer_weekly(df_w, mode=ctx.feature_tier).iloc[-1] if ctx.enabled_layers["L1"] else None
L2 = label_layer_daily(df_d,  mode=ctx.feature_tier).iloc[-1] if ctx.enabled_layers["L2"] else None

policy = resolve_policy(L1=L1, L2=L2)

print("Size multiplier:", policy.size_mult)
print("Stop multiplier:", policy.stop_mult)
print("Allowed orders:", policy.orders)
print("Setups:", policy.setups)
print("Gross cap:", policy.gross_cap)
print("Pyramids:", policy.pyramids)
```

The `policy` object is meant to be a thin adapter between the regime stack and whatever execution / backtest engine you use.

---

## CLI usage

There is a small CLI focused on repeatable pipelines and inspection.

From the repo root:

```bash
python -m ta_lab2.cli --help
```

Example subcommands you might expose (names may evolve):

```bash
# Run a data or feature pipeline over a given asset / timeframe
python -m ta_lab2.cli pipeline --asset BTC --tf D --start 2017-01-01

# Inspect current regime labels or policies for a given dataset
python -m ta_lab2.cli regime-inspect --asset BTC --tf D --limit 100
```

If you add a console script entry point in `pyproject.toml`, you can instead run:

```bash
ta-lab2 pipeline ...
ta-lab2 regime-inspect ...
```

For now, the CLI is mainly for personal workflows and is not considered stable.

---

## Development

### Running tests

From the repo root:

```bash
pytest
```

If you have smoke tests marked with `@pytest.mark.smoke`, you can run a fast subset:

```bash
pytest -m "smoke" -q
```

Try to keep smoke tests lightweight and representative; CI is usually configured to run them first.

### Style and design

There is no strict formatter requirement yet. General preferences:

- Small, composable functions.
- Indicator and feature logic as pure as possible (minimal side effects).
- Explicit timeframe names (`tf="D"`, `"W"`, `"H1"`, etc.).
- Avoid baking exchange-specific assumptions into core features or regimes.

---

## Contributing

This project is primarily a personal research lab, but contributions, issue reports, and design discussion are welcome.

- See `CONTRIBUTING.md` for:
  - Branch and commit style
  - How to propose and structure changes
  - How to run tests and CLI commands before opening a PR
- Use the GitHub issue templates:
  - **Bug report** – for broken behavior or unclear errors
  - **Feature request** – for new signals, regimes, CLI enhancements, or data utilities

Keep issues focused and small when possible. Larger design questions are better captured as “meta” issues or GitHub Discussions.

---

## Security

If you believe you have found a security issue (for example around credential handling, database connections, or deployment configs), do not open a public GitHub issue.

Instead, follow the process in `SECURITY.md` to report it privately.

Never commit secrets, private keys, or real API tokens. Use `.env` files and environment variables, and make sure `.gitignore` excludes them.

---

## License

TBD. Until an explicit license is added, treat this as **source-available for personal research use only**.

If you want to use this in a commercial setting, reach out first so terms can be clarified once the project is more mature.

```perl
 ​:contentReference[oaicite:0]{index=0}​
```