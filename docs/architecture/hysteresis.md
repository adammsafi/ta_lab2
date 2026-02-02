---
title: "Hysteresis"
author: "Adam Safi"
created: 2025-11-10T15:47:00+00:00
modified: 2025-11-10T15:55:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\Hysteresis.docx"
original_size_bytes: 22823
---
**Hysteresis**

1. **Definition**

   1. Hysteresis = don’t flip states the instant a threshold is
      crossed; require extra confirmation or a buffer so you don’t ping-pong.
      It’s a “stickiness” rule for regimes.
   2. Plain idea (thermostat analogy)

      * Without hysteresis: heater turns on at 70.0°F and off at 70.0°F →
        rapid on/off jitter.
      * With hysteresis: turn on below 69°F, turn off above 71°F → stable
        behavior.
2. **Hierarchy In trading regimes:**

   1. You apply hysteresis to trend/vol/liquidity labels so they don’t
      change on tiny wiggles.
3. **Typical forms:**

   1. Band hysteresis (two thresholds):

      * Uptrend → Sideways only if fast EMA drops below mid EMA by more
        than δ.
      * Sideways → Uptrend only if fast EMA rises above mid EMA by more
        than δ. (δ is a buffer, e.g., 0.3–0.7 ATR or 0.5–1.0% of
        price.)
   2. Time hysteresis (confirm bars):

      * A new label must hold for k bars (e.g., 2 daily closes, 2 weekly
        closes).
   3. Percentile gaps (for vol buckets):

      * Move from Normal→High only if vol percentile > 70; return to
        Normal only if < 60.
   4. Cooldowns / dwell times:

      * After any flip, enforce a minimum dwell (e.g., no new flip for 3
        bars).
   5. Cost-aware hysteresis:

      * Require a stronger condition to flip into a costlier regime
        (e.g., from Up to Down) than to flip back (asymmetry).
4. **Why it matters**

   1. Cuts whipsaw and transaction costs.
   2. Stabilizes playbook and sizing (fewer policy thrashes).
   3. Makes backtests more realistic: labels don’t change on
      noise.
5. **Quick math sketch**

   1. Let 𝑠𝑡∈{Up, Down, Sideways}. Define a score
      𝑧𝑡 (e.g., EMA distance in ATR units).
   2. Transition rules with band + time hysteresis:

      * If 𝑠𝑡−1 = Up and 𝑧𝑡 < −𝛿 for k bars ⇒
        𝑠𝑡 = Sideways.
      * If 𝑠𝑡−1 = Sideways and 𝑧𝑡 > +𝛿 for k
        bars ⇒ 𝑠𝑡 = Up.
      * Similar for Down; set 𝛿up, 𝛿down
        differently if you want asymmetry.
6. **Practical defaults (good starting points)**

   1. Daily trend: δ = 0.5–1.0 ATR(14) of price; k = 2 closes.
   2. Weekly trend: δ = 0.5 ATR(14w); k = 2 weekly closes.
   3. Vol buckets: 33/67 percentiles to classify; need a 10-pt
      percentile gap to revert.
   4. Liquidity: mark “Stressed” only if spread/slip > 2× 60-bar
      median for 2–3 bars.
7. **Minimal pseudo-logic**

   1. Python

def apply\_hysteresis(prev\_label, candidate\_label, counters,
k\_required=2):

if prev\_label == candidate\_label:

counters[candidate\_label] = counters.get(candidate\_label, 0) + 1

return prev\_label, counters

# label changed; start confirmation counter

counters[candidate\_label] = counters.get(candidate\_label, 0) + 1

if counters[candidate\_label] >= k\_required:

# accept flip; reset others

return candidate\_label, {candidate\_label: 0}

# not confirmed yet: keep previous

return prev\_label, counters

8. **Where to use it in your stack**

   1. L0/L1 (Monthly/Weekly): strongest hysteresis (bigger δ, larger
      k).
   2. L2 (Daily): moderate hysteresis.
   3. L3/L4 (Intraday/Execution): light or none (you want
      responsiveness).
9. **Common pitfalls**

   1. Too tight (δ small, k=1): flips constantly; costs rise; policies
      thrash.
   2. Too wide (δ huge, k big): reacts late; you miss regime
      transitions.
   3. Symmetric when costs are asymmetric: consider larger buffer to
      flip into “risk-on” than to flip into “defensive.”
10. **TL;DR**

    1. Hysteresis makes regime labels sticky on purpose—by adding
       buffers, confirmations, and dwell times—so strategies don’t overreact to
       noise and your risk/playbook changes only when the change is truly
       meaningful.