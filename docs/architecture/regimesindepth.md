---
title: "RegimesInDepth"
author: "Adam Safi"
created: 2025-11-10T14:02:00+00:00
modified: 2025-11-10T15:10:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\RegimesInDepth.docx"
original_size_bytes: 26256
---
**Regimes**

1. **Definitions:**

   1. A regime is a persistent market state, defined on a specific time
      frame, in which the distribution of key behaviors—trend, volatility, and
      liquidity, plus any flow or microstructure features you track—is
      sufficiently stable that a distinct trading playbook and risk policy
      outperform reasonable alternatives.
   2. A regime is a time-frame–scoped latent state 𝑠 ∈ 𝑆 such that,
      conditional on s, the joint distribution of behaviors you care about is
      stable enough to warrant a distinct trading policy.
   3. Data at time t: features 𝑥t (trend, vol, liquidity,
      flow, microstructure).
   4. Labeler: 𝑔TF: 𝑥t ↦ 𝑠t maps
      features to a regime on a given time frame (TF).
   5. Policy: πTF(st) → playbook & risk
      (entries, exits, sizing, order types, exposure caps).
   6. Stability condition (intuition): within a regime, distributional
      drift is “small”: 𝐷(𝑃t|s∥𝑃𝑡+Δ∣𝑠) < 𝜖 for
      practical Δ (measured via rolling KS/KL/PSI or performance
      stability).
   7. Persistence: expected dwell time 𝐸[𝜏𝑠] exceeds a
      minimum so policy differences can pay for costs.
2. **What a regime implies:**

   1. Time-frame scoped: every regime is labeled per TF, e.g., Weekly
      Uptrend+Normal Vol, Daily Pullback.
   2. Feature-based: identified by measurable inputs, for example EMA
      stacks for trend, ATR% or realized vol for volatility, spread and
      slippage for liquidity, basis or funding for flow.
   3. Persistent, not static: lasts long enough to justify different
      tactics; includes hysteresis rules to avoid flip-flopping.
   4. Actionable: each regime maps to concrete changes in entries,
      exits, sizing, order types, and portfolio caps.
   5. Testable: you can evaluate PnL, Sharpe, MAR, MAE/MFE by regime to
      confirm the edge.
   6. Hierarchical: higher layers (cycle, weekly) set guardrails; lower
      layers (daily, intraday) refine tactics as sub-regimes.
3. **What a regime is not:**

   1. Not a one-bar signal or a pattern; signals fire inside
      regimes.

      * Signal: a momentary trigger inside a regime, e.g., “4H pullback
        to 34 EMA.”
   2. Not a fixed calendar era; regimes transition via a state process
      𝑠𝑡−1 → 𝑠𝑡.

      * Setup: a template pattern that may be allowed or blocked
        depending on the current regime
4. **Regime anatomy (on any TF):**

   1. Scope: the time frame (Monthly/Weekly/Daily/4H/…).
   2. Axes (feature families):

      * Trend: EMA stacks, HH/HL vs LH/LL structure, ADX.
      * Volatility: ATR% of price, realized vol percentiles,
        vol-of-vol.
      * Liquidity/Cost: spread, market impact/slippage, depth.
      * Flow (optional): basis/funding, ETF/mutual fund flows, net
        issuance/burn.
      * Event risk (optional): scheduled catalysts (FOMC,
        earnings).
   3. Label: discrete state like Uptrend-HighVol-NormalLiq.
   4. Hysteresis: confirmation rules to avoid flip-flopping (e.g.,
      require 2 closes or percentile gaps).
   5. Policy binding: a concrete config
      (size/stop/whitelist/tactics/caps).
5. **Ways to label regimes:**

   1. Rule-based (deterministic, transparent)

      * Trend: Up if close > slow EMA and fast > mid for *k*bars; Down if inverse; else
        Sideways.
      * Vol bucket: ATR(14)/Close percentile bands on that TF.
      * Liquidity: spread & slip vs rolling medians.
      * Pros: simple, debuggable, few parameters. Cons: can be brittle
        near thresholds.
   2. Unsupervised (clustering on features)

      * k-means/GM on [*r*,  vol, 
        skew,  kurt,  acf,  spread,  slip].
      * Pros: finds natural groupings.
      * Cons: clusters may drift; needs care for
        costs/interpretability.
   3. State-space (HMM/Markov-switching)

      * Hidden regimes with transition matrix *P*.
      * Pros: explicit persistence & transition
        probabilities.
      * Cons: data-hungry; sensitive to misspecification.
   4. Online change-point + bands

      * Detect distributional breaks; between breaks use rule-based
        buckets.
      * Pros: adapts to shifts.
      * Cons: parameter tuning matters.
   5. Practical pattern: start rule-based; add HMM for L1/L0 once
      history is sufficient; use clusters as diagnostics.
6. **Persistence & hysteresis (make it
   tradeable)**

   1. Minimum dwell: require average dwell  ≥ *D*minfor that TF (e.g.,
      ≥ 3–5 bars on 4H; ≥ 4–8 bars on Daily; ≥ 6–12 bars on Weekly).
   2. Confirmation: 2 closes beyond a threshold or a band gap (e.g.,
      vol percentile must move 10 points to change buckets).
   3. Cooldown: after a flip, restrict immediate re-flip unless a
      stronger condition hits.
7. **Policy: binding regimes to actions**

   1. A policy is just a mapping table per TF:

      * Allowed setups: breakout/pullback/mean-revert.
      * Stops/targets: ATR multiples or structure breaks.
      * Sizing: base × *f*(vol)×
        *g*(liq)× *h*(alignment).
      * Order types: limit ladder vs stop-limit, max order rate, min
        spacing.
      * Portfolio caps: net/gross exposure, pyramiding allowed?, max
        concurrent.
   2. Invariant: higher-level regimes (Monthly/Weekly) can only
      tighten, not loosen, lower-level risk.
8. **Validation: prove a regime is useful**

   1. Uplift vs baseline: conditional performance (Sharpe/MAR/PPM) by
      regime vs unconditional.
   2. Cost realism: include realized slippage per regime (it differs a
      lot).
   3. Stability: rolling-window stats inside regimes; PSI/KS tests on
      features.
   4. Transitions: measure edge around entries/exits of regimes (often
      strong).
9. **Data sufficiency & adaptation**

   1. Deep history: enable richer methods (percentiles/HMM), stricter
      hysteresis.
   2. Mid history: rule-based + percentiles with shorter
      lookbacks.
   3. Short history: fixed cutoffs (cohort priors), disable top layers;
      proxies can tighten caps.
10. **Examples (simplified)**

    1. Weekly Uptrend, Normal Vol, Normal Liquidity → allow breakouts
       and pullbacks, base size 1.0×, stops 1.5× ATR.
    2. Daily Sideways, High Vol, Stressed Liquidity → stand down or run
       mean reversion with half size, wider stops, limit orders only.
11. **Examples (condensed/more detailed)**

    1. Weekly Up + Normal Vol:

       * size=1.0×, stops=1.5×ATR(14D), setups = breakout & pullback,
         pyramids allowed, gross cap 100%.
    2. Daily Sideways + High Vol + Stressed Liq:

       * size=0.4×, mean-revert only, limit-only orders, max orders/hour
         halved, no pyramids.
    3. Transition: Daily Pullback → Daily Impulse within Weekly Up:

       * A-setup: add on retest; raise stop to trail 1.0×ATR; partial take at prior swing
         high.
12. **Implementation sketch (fits ta\_lab2)**

    1. Features: compute per TF (Monthly/Weekly/Daily/4H/…).
    2. Labelers: label\_trend\_tf, label\_vol\_tf, label\_liq\_tf
       (rule-based), optional hmm\_weekly.
    3. Compose: compose\_regime(trend, vol, liq) → string key.
    4. Hysteresis: confirm\_flip(prev\_state, new\_state,
       buffers).
    5. Policy resolver: resolve(tf\_states) → {size\_mult, stop\_mult,
       setups, order\_types, caps}.
    6. Telemetry: log (regime\_key, tf, pnl, slip, mae/mfe) per
       trade/day; monthly report by regime.
13. **Governance (so it doesn’t drift silently)**

    1. Version regimes & policies: regimes\_v1.2.yaml; store hash in
       backtests/live runs.
    2. Drift monitors: alert on regime occupancy mix shifts; slip >
       threshold inside any regime; Sharpe by regime < floor.
    3. Change control: only update thresholds/policies with walk-forward
       evidence.
14. **Tiny pseudo-API:**

    1. Python:

> state = {
>
> "W": compose\_regime(label\_trend(W), label\_vol(W), label\_liq(W)),
>
> "D": compose\_regime(label\_trend(D), label\_vol(D), label\_liq(D)),
>
> "4H": compose\_regime(label\_trend(H4), label\_vol(H4),
> label\_liq(H4)),
>
> }
>
> state = apply\_hysteresis(prev\_state, state)
>
> policy = resolve\_policy(state) # enforces tighten-only
> inheritance
>
> orders = execute\_playbook(policy, signals)