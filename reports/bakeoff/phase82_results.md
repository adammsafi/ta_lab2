# Phase 82 Walk-Forward Bake-off Results

Generated: 2026-03-23 07:56

## Overview

- **Total results**: 76,378
- **Unique strategies**: 13
- **Unique assets**: 109
- **Cost scenarios**: 16
- **Experiments**: phase82_ama_hl, phase82_ama_kraken, phase82_expression

## Gate Application

| Gate | Threshold | Remaining | Removed |
|------|-----------|-----------|---------|
| Initial | — | 76,378 | — |
| Min trades | >= 10 | 19,020 | 57,358 |
| Max drawdown | <= 80% | 15,916 | 3,104 |
| DSR | > 0.9500 | 687 | 15,229 |
| PBO | < 0.50 | 687 | 0 |

**Survivors**: 687 out of 76,378 (0.9%)

## Strategy Summary (Survivors)

| Strategy | Assets | Rows | Avg Sharpe | Avg DSR | Avg PSR | Avg DD | Avg Trades |
|----------|--------|------|------------|---------|---------|--------|------------|
| ama_kama_crossover | 3.0 | 54.0 | 0.9814 | 0.9706 | 1.0000 | -67.69% | 237 |
| ama_momentum | 4.0 | 52.0 | 0.9787 | 0.9815 | 1.0000 | -66.72% | 120 |
| ama_multi_agreement | 1.0 | 6.0 | 0.9758 | 0.9567 | 1.0000 | -74.23% | 94 |
| ama_momentum_perasset | 4.0 | 124.0 | 0.9065 | 0.9982 | 1.0000 | -62.37% | 150 |
| ema_trend | 24.0 | 268.0 | 0.9042 | 0.9901 | 0.9999 | -52.80% | 100 |
| ama_regime_conditional | 2.0 | 25.0 | 0.8920 | 0.9899 | 1.0000 | -71.74% | 859 |
| ama_kama_reversion_zscore | 2.0 | 30.0 | 0.8546 | 0.9774 | 1.0000 | -61.21% | 306 |
| breakout_atr | 5.0 | 64.0 | 0.7745 | 0.9847 | 1.0000 | -12.19% | 126 |
| rsi_mean_revert | 15.0 | 64.0 | 0.2725 | 0.9833 | 1.0000 | -0.13% | 121 |

## Composite Scoring

| Strategy | Balanced | Risk | Quality | Low-Cost | Top-2 Count | Robust |
|----------|----------|------|---------|----------|-------------|--------|
| ama_multi_agreement | #1 | #1 | #1 | #1 | 4 | YES |
| ama_kama_crossover | #2 | #2 | #3 | #2 | 3 | YES |
| ama_momentum | #3 | #3 | #2 | #3 | 1 | no |
| ama_momentum_perasset | #4 | #5 | #4 | #4 | 0 | no |
| ama_regime_conditional | #5 | #4 | #5 | #5 | 0 | no |
| ama_kama_reversion_zscore | #6 | #6 | #6 | #8 | 0 | no |
| ema_trend | #7 | #7 | #8 | #6 | 0 | no |
| breakout_atr | #8 | #8 | #7 | #7 | 0 | no |
| rsi_mean_revert | #9 | #9 | #9 | #9 | 0 | no |

## Per-Asset IC Weight Comparison

Per-asset IC weights: no improvement (mean Sharpe delta = -0.0002, Wilcoxon p-value = 0.2367, n=99 paired assets)
  Win/Loss/Tie: 1/6/92

## Top Strategy-Asset Combinations

| Strategy | Asset | Cost | Sharpe | DSR | PSR | MaxDD | Trades |
|----------|-------|------|--------|-----|-----|-------|--------|
| ema_trend | 100124 | spot_fee16_slip5 | 1.4624 | 1.0000 | 1.0000 | -55.07% | 24 |
| ema_trend | 100124 | spot_fee16_slip10 | 1.4590 | 1.0000 | 1.0000 | -55.10% | 24 |
| ema_trend | 100124 | spot_fee26_slip5 | 1.4557 | 1.0000 | 1.0000 | -55.12% | 24 |
| ema_trend | 100124 | spot_fee26_slip10 | 1.4523 | 1.0000 | 1.0000 | -55.14% | 24 |
| ema_trend | 100124 | spot_fee16_slip20 | 1.4523 | 1.0000 | 1.0000 | -55.14% | 24 |
| ema_trend | 100124 | perps_fee2_slip3 | 1.4465 | 0.9976 | 1.0000 | -55.00% | 24 |
| ema_trend | 100124 | spot_fee26_slip20 | 1.4455 | 1.0000 | 1.0000 | -55.19% | 24 |
| ema_trend | 100124 | perps_fee2_slip5 | 1.4452 | 0.9555 | 1.0000 | -55.01% | 24 |
| ema_trend | 100124 | perps_fee4_slip3 | 1.4445 | 0.9976 | 1.0000 | -55.01% | 24 |
| ema_trend | 100124 | perps_fee4_slip5 | 1.4432 | 0.9976 | 1.0000 | -55.02% | 24 |
| ema_trend | 100124 | perps_fee5_slip5 | 1.4420 | 0.9968 | 1.0000 | -55.02% | 24 |
| ema_trend | 100124 | perps_fee2_slip10 | 1.4419 | 0.9552 | 1.0000 | -55.03% | 24 |
| ema_trend | 100124 | perps_fee4_slip10 | 1.4399 | 0.9976 | 1.0000 | -55.04% | 24 |
| ema_trend | 100124 | perps_fee5_slip10 | 1.4387 | 0.9968 | 1.0000 | -55.05% | 24 |
| ema_trend | 100124 | perps_fee2_slip20 | 1.4340 | 0.9968 | 1.0000 | -55.08% | 24 |
| ema_trend | 100124 | perps_fee5_slip20 | 1.4320 | 0.9967 | 1.0000 | -55.09% | 24 |
| ema_trend | 1 | spot_fee16_slip5 | 1.3769 | 0.9984 | 1.0000 | -70.12% | 48 |
| ema_trend | 1 | spot_fee16_slip5 | 1.3698 | 0.9957 | 1.0000 | -70.12% | 69 |
| ema_trend | 1 | spot_fee16_slip10 | 1.3696 | 0.9981 | 1.0000 | -70.12% | 48 |
| ema_trend | 1 | spot_fee16_slip5 | 1.3652 | 0.9954 | 1.0000 | -75.04% | 38 |

## Paper Trading Candidates

All 9 surviving strategies advance to paper trading:

- **ama_kama_crossover**: 3 assets, avg Sharpe=0.9814
- **ama_kama_reversion_zscore**: 2 assets, avg Sharpe=0.8546
- **ama_momentum**: 4 assets, avg Sharpe=0.9787
- **ama_momentum_perasset**: 4 assets, avg Sharpe=0.9065
- **ama_multi_agreement**: 1 assets, avg Sharpe=0.9758
- **ama_regime_conditional**: 2 assets, avg Sharpe=0.8920
- **breakout_atr**: 5 assets, avg Sharpe=0.7745
- **ema_trend**: 24 assets, avg Sharpe=0.9042
- **rsi_mean_revert**: 15 assets, avg Sharpe=0.2725
