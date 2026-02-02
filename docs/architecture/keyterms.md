---
title: "KeyTerms"
author: "Adam Safi"
created: 2025-11-08T17:13:00+00:00
modified: 2025-11-20T14:00:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\KeyTerms.docx"
original_size_bytes: 26386
---
**Key Terms**

1. **Program / Master Portfolio (Capital
   Allocator)**

   1. The Program (a.k.a. Master Portfolio or Capital Allocator) is the
      top-level portfolio that owns firmwide capital and allocates it across
      Pools (mandates). It sets global risk guardrails, treasury rules, and
      governance; it rebalances capital among Pools and aggregates firmwide
      P&L and risk.
   2. Purpose:

      1. Convert firm vision and constraints into capital policy and risk
         limits.
      2. Decide how much capital each Pool runs and when to
         add/remove/resize Pools.
      3. Ensure Pool behavior rolls up to a coherent, controlled firmwide
         exposure profile.
   3. Inputs → Decisions → Outputs

      1. Inputs: pool KPIs, capacity & liquidity, correlations, firm
         DD/vol caps, cash needs.
      2. Decisions: pool weights, funding/defunding, rebalance cadence,
         firmwide risk gates.
      3. Outputs: allocation plan, firm exposure/risk state, treasury
         movements, roll-up reports.
   4. KPIs

      1. Firm Sharpe/MAR, max drawdown, vol vs target, contribution by
         Pool, drift vs policy, cash efficiency.
   5. Policies (examples)

      1. Firm max DD: e.g., 25% hard stop.
      2. Pool weight bands: e.g., Core 50–70%, Conservative 20–40%,
         Opportunistic 0–20%.
      3. Rebalance: monthly or >25% weight drift.
      4. Pause rules: auto-defund a Pool breaching risk or failing
         QA.
2. **Pool (Mandate-Level Portfolio)**

   1. A pool is a self-contained portfolio with a clearly stated
      objective (return/volatility/drawdown), constraints (leverage, assets,
      venues), and governance (risk limits, overrides). Capital is committed
      to the pool, and the pool allocates that capital across one or more
      sleeves to meet its mandate.

      1. Scope: objective, risk budget, eligible instruments/venues,
         reporting.
      2. Examples: Conservative Pool, Core Pool, Opportunistic
         Pool.
      3. Accountability: pool-level P&L, volatility, max drawdown,
         compliance with limits.
3. **Sleeve (Strategy Allocation Inside a Pool)**

   1. A sleeve is a distinct strategy bucket within a pool—defined by
      its signal/process (e.g., EMA trend, RSI mean-reversion, basis), its
      sizing rules, and its risk budget granted by the pool. Sleeves are
      components; they don’t exist independently of a pool unless promoted to
      their own product.

      1. Scope: entry/exit logic, parameters, data, sizing & stop
         rules.
      2. Examples: Trend Sleeve, Mean-Reversion Sleeve, Staking/Yield
         Sleeve, Basis Sleeve.
      3. Accountability: sleeve-level P&L, hit rate, Sharpe, drawdown,
         capacity, and drift vs backtest.
4. **Component**

   1. A Component is a modular, reusable building block of the platform
      that delivers a single, well-bounded capability (e.g., risk aggregation,
      capital allocation, execution, data catalog). Components are shared
      services: one implementation serves all Programs, Pools, and Sleeves via
      clear interfaces and per-entity configuration.
   2. Key properties

      1. Single responsibility: one capability, one owner.
      2. Explicit interfaces: typed inputs/outputs (APIs, events,
         schemas).
      3. Stateless or stateful by design: state handling (stores, caches)
         is defined and observable.
      4. Config-driven, multi-tenant: behavior specializes by
         Program/Pool/Sleeve config, not by forking code.
      5. Testable & observable: unit/contract tests, metrics, logs,
         alerts, SLOs.
      6. Versioned & governed: change control, rollbacks, audit
         trails.
   3. Examples

      1. Capital Policy Engine (computes target weights across
         Pools)
      2. Firmwide Risk Engine (aggregates exposures, enforces
         limits)
      3. Treasury/Collateral Manager (cash, margin, sweeps)
      4. Data & Reference Catalog (prices, fees, calendars, lot
         sizes)
      5. Monitoring & Alerting (health, limits, drift)
      6. Performance & Attribution (firm→pool→sleeve P&L
         breakdown)
      7. Execution Adapter (venue/broker interface, orders/fills)
   4. Non-examples

      1. A specific strategy (that’s a Sleeve).
      2. A Pool (that’s a mandate-level portfolio).
      3. An ad-hoc script or notebook without interfaces, tests, or
         SLOs.
5. **Regime — working definition**

   1. A regime is a persistent market state, defined on a specific time
      frame, in which the distribution of key behaviors—trend, volatility, and
      liquidity, plus any flow or microstructure features you track—is
      sufficiently stable that a distinct trading playbook and risk policy
      outperform reasonable alternatives.
   2. A regime is a time-frame–scoped latent state 𝑠 ∈ 𝑆 such that,
      conditional on s, the joint distribution of behaviors you care about is
      stable enough to warrant a distinct trading policy.

      1. Data at time t: features 𝑥t (trend, vol, liquidity,
         flow, microstructure).
      2. Labeler: 𝑔TF: 𝑥t ↦ 𝑠t maps
         features to a regime on a given time frame (TF).
      3. Policy: πTF(st) → playbook & risk
         (entries, exits, sizing, order types, exposure caps).
      4. Stability condition (intuition): within a regime, distributional
         drift is “small”: 𝐷(𝑃t|s∥𝑃𝑡+Δ∣𝑠) < 𝜖 for
         practical Δ (measured via rolling KS/KL/PSI or performance
         stability).
      5. Persistence: expected dwell time 𝐸[𝜏𝑠] exceeds a
         minimum so policy differences can pay for costs.
   3. What a regime implies:

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
   4. What a regime is not:

      1. Not a one-bar signal or a pattern; signals fire inside
         regimes.

         * Signal: a momentary trigger inside a regime, e.g., “4H pullback
           to 34 EMA.”
      2. Not a fixed calendar era; regimes transition via a state process
         𝑠𝑡−1 → 𝑠𝑡.

         * Setup: a template pattern that may be allowed or blocked
           depending on the current regime
6. **Time Frames**

   1. Definition

      1. A time frame (TF) is the bar interval on which you measure
         features, label regimes, and bind a policy. Each TF has its own regime
         because behavior is scale-dependent.
   2. Hierarchy

      1. L0 — Cycle (Monthly or Quarterly)
      2. L1 — Macro (Weekly)
      3. L2 — Meso (Daily)
      4. L3 — Micro (4H/1H)
      5. L4 — Execution (15–60m)
7. **Hysteresis**

   1. Definition

      1. Hysteresis = don’t flip states the instant a threshold is
         crossed; require extra confirmation or a buffer so you don’t ping-pong.
         It’s a “stickiness” rule for regimes.
      2. Plain idea (thermostat analogy)

         * Without hysteresis: heater turns on at 70.0°F and off at 70.0°F →
           rapid on/off jitter.
         * With hysteresis: turn on below 69°F, turn off above 71°F → stable
           behavior.
   2. In trading regimes:

      1. You apply hysteresis to trend/vol/liquidity labels so they don’t
         change on tiny wiggles.
   3. Typical forms:

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
   4. Why it matters

      1. Cuts whipsaw and transaction costs.
      2. Stabilizes playbook and sizing (fewer policy thrashes).
      3. Makes backtests more realistic: labels don’t change on
         noise.
   5. Quick math sketch

      1. Let 𝑠𝑡∈{Up, Down, Sideways}. Define a score
         𝑧𝑡 (e.g., EMA distance in ATR units).
      2. Transition rules with band + time hysteresis:

         * If 𝑠𝑡−1 = Up and 𝑧𝑡 < −𝛿 for k bars ⇒
           𝑠𝑡 = Sideways.
         * If 𝑠𝑡−1 = Sideways and 𝑧𝑡 > +𝛿 for k
           bars ⇒ 𝑠𝑡 = Up.
         * Similar for Down; set 𝛿up, 𝛿down
           differently if you want asymmetry.
   6. Practical defaults (good starting points)

      1. Daily trend: δ = 0.5–1.0 ATR(14) of price; k = 2 closes.
      2. Weekly trend: δ = 0.5 ATR(14w); k = 2 weekly closes.
      3. Vol buckets: 33/67 percentiles to classify; need a 10-pt
         percentile gap to revert.
      4. Liquidity: mark “Stressed” only if spread/slip > 2× 60-bar
         median for 2–3 bars. Minimal pseudo-logic