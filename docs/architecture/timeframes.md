---
title: "TimeFrames"
author: "Adam Safi"
created: 2025-11-10T14:19:00+00:00
modified: 2025-11-10T15:10:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\TimeFrames.docx"
original_size_bytes: 26916
---
**Time frames**

1. **Definition**

   1. A time frame (TF) is the bar interval on which you measure
      features, label regimes, and bind a policy. Each TF has its own regime
      because behavior is scale-dependent.
2. **Hierarchy (L0 → L4)**

   1. L0 — Cycle (Monthly or Quarterly)

      * Purpose: long-horizon backdrop, “build or harvest”.
      * Typical inputs: 24–48 month MAs or 200-week slope, drawdown from
        ATH, 6–12M realized vol percentile, broad breadth proxies.
      * Decisions: net exposure caps, max leverage, pyramiding allowed or
        not, rebalance cadence.
      * Persistence: very slow, require 2 monthly closes to
        flip.
      * Data requirement: ≥ 60 monthly bars (≈ 5 years). If less, skip
        L0.
   2. L1 — Macro (Weekly)

      * Purpose: primary trend and volatility lane.
      * Inputs: weekly EMA stack (20/50/200), ADX(14w), weekly ATR%
        percentile, liquidity stress vs 26w medians.
      * Decisions: base position size, stop multiple on daily risk, setup
        whitelist (trend vs mean-revert).
      * Persistence: slow, require 2 weekly closes or ADX
        persistence.
      * Data requirement: ≥ 100 weekly bars ideal; 52–100 use reduced
        features; < 52 collapse into Daily macro-lite.
   3. L2 — Meso (Daily)

      * Purpose: choose the playbook inside the weekly lane.
      * Inputs: 20/50/100D EMAs, HH/HL structure, Bollinger width
        percentile, daily ATR% percentile.
      * Decisions: breakout vs pullback vs range fade, target style
        (trail vs structure), frequency cap, stacking rules.
      * Persistence: moderate, confirm with 2 daily closes.
      * Data requirement: ≥ 250 daily bars ideal; 120–250 use trimmed
        features; < 120 run simplified rules.
   4. L3 — Micro (4H/1H)

      * Purpose: find the moment, assess local context.
      * Inputs: 34/89 EMA, pullback depth, compression and expansion
        markers, short-horizon ATR%, intraday event risk.
      * Decisions: exact trigger logic, add-on rules, pre-filter by
        liquidity.
      * Persistence: short, require at least 2–3 bars to confirm
        state.
      * Data requirement: a few months of bars is enough.
   5. L4 — Execution (15–60m)

      * Purpose: get filled well, control cost.
      * Inputs: spread, slippage, depth, intraday ATR%, upcoming
        headlines.
      * Decisions: order type (limit ladder, stop-limit, IOC), order rate
        limits, minimum spacing, cancel-replace behavior.
      * Persistence: very short, reacts bar-to-bar.
      * Data requirement: minimal; fall back to conservative defaults if
        sparse.
   6. Inheritance and governance

      * Tighten-only rule: higher layers can only tighten risk set by
        lower layers, never loosen it.
      * Alignment gates: example, do not take Daily longs if Weekly trend
        is Down; if Cycle is Contraction, cap gross regardless of lower-TF
        signals.
      * Hysteresis: slower TFs need slower confirmations; L0 months, L1
        weeks, L2 days.
      * Data-aware enablement: turn layers on only if the asset meets the
        bar minimums; otherwise use proxy context to tighten caps, not to add
        risk.
   7. Quick reference table:

![](./media/image1.emf)

3. **Minimal API sketch for your codebase:**

   1. Python:

# assess what layers we can run

ctx = assess\_data\_budget(symbol, dfs\_by\_tf) # returns enabled\_layers,
feature\_tier

# label per enabled TF

labels = compute\_labels(dfs\_by\_tf, mode=ctx.feature\_tier) # dict {tf:
regime\_key}

# apply hysteresis and inheritance

labels = confirm\_and\_align(labels, prev\_labels)

policy = resolve\_policy(labels,
enabled\_layers=ctx.enabled\_layers)

# policy -> size, stops, allowed setups, order types, caps

2. That’s the hierarchy in one place: what each time frame means,
   what it decides, how sticky it is, and when to enable it based on
   history.
