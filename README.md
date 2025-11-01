
# ta_lab — Multi-timescale Technical Analysis Lab

A small, modular package for:
- Resampling OHLCV into flexible bins (days, weeks, months, quarters, years, seasons, and n-sized variants)
- Computing features (calendar metadata, EMAs and derivatives, returns, volatility estimators)
- Building regimes/segments and comparing across timeframes

## Layout
- `io.py` — load/save + partition helpers
- `resample.py` — calendar & season binning
- `features/` — calendar (exact seasons + moon), ema, returns, vol
- `regimes/` — comovement & flip segments (thin stubs to plug your own logic)
- `compare.py` — helpers to run the same pipeline on multiple timeframes and compare
