# Domain Pitfalls: v1.0.1 Macro Regime Infrastructure

**Domain:** Adding macro regime infrastructure to an existing per-asset regime system in a crypto trading platform (ta_lab2)
**Researched:** 2026-03-01
**Scope:** Integration pitfalls specific to adding FRED-sourced macro signals (39 series, 208K rows) as a new regime layer to an existing tighten-only resolver (L0-L4), 5-gate risk engine, and paper executor with drift monitoring

---

## 1. FRED Data Pipeline: Gaps, Forward-Fill, and Staleness

### Critical: Naive Forward-Fill of Monthly FRED Series Creates Phantom Stability That Masks Regime Transitions

**What goes wrong:** Monthly series (Japan policy rate IRSTCI01JPM156N, US CPI CPIAUCSL, unemployment UNRATE) are published once per month. To use them in a daily pipeline, the natural impulse is `ffill()` to carry the last observation forward until the next release. This creates 20-30 days of identical values between publications. When a macro regime classifier uses these forward-filled values, the regime appears "stable" for 20-30 days regardless of what is actually happening in the economy.

The real danger: a carry trade unwind (like August 2024 when BTC dropped 15% against JPY in a single day after the BoJ rate hike) happens in hours/days, but the monthly Japan rate data that would signal the shift arrives 30+ days late. The forward-filled value shows the old rate throughout the entire crisis. The macro regime remains in "favorable" while the market is in turmoil.

**Why it matters for this system:** The existing per-asset regime system (L2 daily, L1 weekly) reacts within 1-3 bars to price-based regime changes. If a macro overlay is forward-filling monthly data and showing "all clear" while per-asset regimes are already flashing "Down-High-Stressed", the macro layer adds false confidence rather than additional information. Worse, if the macro layer's "favorable" classification is used to *loosen* constraints (which the tighten-only resolver prevents, but the temptation will arise to bypass it), positions could be held into a crash.

**Consequences:** Macro regime lags reality by weeks during fast events. The lag is invisible because the forward-filled data "looks" like a continuous daily series. Backtest performance appears good because the monthly data point that eventually reveals the crisis is used retroactively in the backtest (see Pitfall 2 on look-ahead bias).

**Prevention:**
- Forward-fill is acceptable for daily pipeline continuity, but **the regime classifier must know the data age**. Add a `days_since_publication` column to every forward-filled macro series. The macro regime classifier should treat data older than `1.5x publication_frequency` as "stale" and flag uncertainty.
- For fast-moving risks (carry trade unwind, BoJ announcements), use **daily proxy indicators** rather than monthly rates. The DXY (US Dollar Index) moves daily and reflects dollar-yen dynamics. VIX moves daily (albeit US equity focused). Use these as leading indicators; use monthly rates only for confirmation of longer-term trends.
- Implement a **staleness guard**: if a monthly series has not updated in >45 days (normal gap is ~30 days), escalate to a warning. If >60 days, flag the macro regime as "uncertain" and fall back to per-asset-only regime resolution.
- Store the `last_publication_date` and `expected_next_publication_date` per series in a `dim_fred_series_metadata` table. The daily refresh pipeline should check whether expected publications have arrived.

**Warning signs:**
- Macro regime showing "favorable" or "neutral" while per-asset L2 regimes for BTC and ETH are both "Down-High-Stressed"
- Forward-filled macro series with identical values for 35+ consecutive days without a staleness alert
- No `days_since_publication` or equivalent column in the macro regime input data

**Detection:** Add a daily assertion: `max(days_since_publication) < 2 * expected_frequency_days` for all macro series used in regime classification. If this fails, log a WARNING and flag the macro regime as stale.

**Phase:** Data pipeline design phase. The staleness tracking must be designed before any forward-fill logic is written.

---

### Critical: FRED Holiday and Weekend Gaps Create Misaligned Joins with 24/7 Crypto Data

**What goes wrong:** FRED daily series (VIX via VIXCLS, DXY via DTWEXBGS, 10Y yield via DGS10) have no observations on US holidays and weekends. Crypto trades 24/7/365. A naive `LEFT JOIN macro ON macro.date = crypto.date` will produce NULLs for every Saturday, Sunday, and US holiday. At approximately 252 vs 365 trading days per year, ~31% of crypto trading days have no FRED data.

The downstream effect depends on how NULLs are handled. If `dropna()`, 31% of data is lost. If `ffill()`, Friday's VIX is used for Saturday and Sunday, which is defensible for weekends but problematic for multi-day holidays (Thanksgiving: 2 consecutive missing days; Christmas to New Year: potentially 3-5 days gap). During holiday gaps, crypto markets can move significantly (the 2024 Christmas-New Year period saw 8% BTC volatility) while the FRED indicators show frozen values.

**Why it matters for this system:** The existing data pipeline uses `(id, ts, tf)` as the primary key pattern. Crypto price bars exist for every calendar day. If macro series are stored in a table with daily granularity, the join will silently produce NULLs or stale values for 31% of rows unless explicitly handled. The `cmc_features` pattern (scoped DELETE + INSERT per batch) will either insert NULLs or skip the gaps, creating inconsistent feature coverage.

**Prevention:**
- Design the macro data storage with an explicit **two-step fill strategy**:
  1. Store raw FRED observations with their actual publication dates in a `cmc_fred_observations` table.
  2. Generate a separate `cmc_fred_daily` table that fills to calendar-daily frequency using a documented fill strategy: `ffill(limit=5)` for daily series (covers weekends + short holidays), `ffill(limit=45)` for monthly series (covers one full publication gap).
- The `limit` parameter on `ffill()` is critical. Without it, a series that stops updating (FRED discontinuation, API failure) will silently forward-fill indefinitely. With `limit=5` for daily series, any gap longer than 5 days produces an explicit NULL, which the pipeline can detect and alert on.
- Add a `fill_method` column: `'observed'` for actual FRED observation dates, `'ffill'` for forward-filled values. Downstream code can then distinguish real observations from fills.
- Never join crypto data directly to raw FRED tables. Always join through the `cmc_fred_daily` table which guarantees calendar-daily coverage.

**Warning signs:**
- Any SQL join between crypto bars and FRED series that does not use the filled daily table
- Feature table rows with NULL macro columns on weekends (indicates missing fill step)
- `ffill()` without a `limit` parameter on any FRED series

**Phase:** FRED data ingestion phase. The two-table design (raw + daily-filled) must be the first schema decision.

---

### Moderate: FRED API Rate Limits and Sync Failures Will Cause Partial Macro State During Daily Refresh

**What goes wrong:** The existing `FredProvider` has rate limiting (token bucket), a circuit breaker (5 failures = 60s recovery), and caching. With 39 series to refresh daily, a partial failure (API timeout on series 23 of 39) leaves the macro state table with some series at today's values and others at yesterday's. If the macro regime classifier runs on this partial state, it uses a mix of current and stale data to produce a regime label.

This is particularly dangerous when the failure occurs on a high-impact series (VIX, DXY, yield curve) and succeeds on low-impact series (Japan monthly rates that have not changed). The macro regime looks "updated" because most series have today's timestamp, but the critical daily inputs are stale.

**Prevention:**
- Add an **atomic refresh marker**: the daily macro refresh writes a `refresh_status` record to a `cmc_fred_refresh_log` table with `{run_date, total_series, success_count, failed_series[], status}`. The status is `'complete'` only if all series succeed. The macro regime classifier checks `refresh_status == 'complete'` before running; if `'partial'`, it logs a WARNING and uses the previous day's complete regime label.
- Implement **retry with exponential backoff** for failed series (the circuit breaker already handles this partially, but add a second retry pass specifically for series that failed in the first pass).
- Order series refresh by importance: daily high-impact series first (VIX, DXY, DGS10, DGS2), then weekly/monthly series. If the API quota is exhausted, at least the most critical series are current.
- The existing `CircuitBreaker` with `failure_threshold=5` is reasonable for individual series but should be separate per-series, not global. One bad series (e.g., discontinued FRED ID) should not trip the breaker for all 39 series.

**Warning signs:**
- Macro regime classifier running without checking refresh completeness
- Circuit breaker tripping globally and blocking all series after one failure
- Daily refresh logs showing 35/39 series refreshed but no alert about the missing 4

**Phase:** Data pipeline orchestration phase. Build the refresh log and completeness check before connecting the regime classifier.

---

## 2. Backtest Reproducibility: Data Revisions and Look-Ahead Bias

### Critical: Using Current FRED Data in Backtests Introduces Look-Ahead Bias for Revised Series

**What goes wrong:** FRED economic series are revised after initial publication. CPI, GDP, unemployment, and non-farm payrolls are all subject to revisions. The first release of CPI on a given date may differ from the revised value available today. FRED stores the current (latest-revised) value by default. When a backtest queries `SELECT cpi_value FROM cmc_fred_daily WHERE date = '2024-06-01'`, it gets the revised value, not the value that was known on June 1, 2024.

This is classic look-ahead bias: the backtest regime classifier sees data that the live system would not have seen. A macro regime that correctly identifies "tightening" using revised CPI data may have been ambiguous using the first-release data.

**Why it matters for this system:** The existing drift monitor (`DriftMonitor`) compares paper executor P&L against backtest replays. If the backtest uses revised FRED data but the paper executor used first-release data, drift will be attributed to "execution differences" when it is actually "data revision differences." This contaminates the drift signal.

**Magnitude of the problem:** CPI revisions are typically small (0.1-0.2 percentage points) but can shift the YoY rate by enough to cross a regime threshold. GDP revisions can be large (the advance estimate for Q1 2024 was revised by 0.3 percentage points in the final release). For regime classifiers using threshold-based rules, even small revisions at boundary values flip regime labels.

**Prevention:**
- Use ALFRED (Archival FRED) for backtesting. The `fredapi` library (already installed in the project) provides `get_series_first_release()` which returns only the first-published value for each observation date, and `get_series_as_of_date(date)` which returns the data as it was known on a specific date. Both are essential for point-in-time backtesting.
- Store vintage data in a `cmc_fred_vintages` table with schema `(series_id, observation_date, vintage_date, value)`. For any backtest, the query becomes `WHERE observation_date = :date AND vintage_date <= :backtest_as_of_date ORDER BY vintage_date DESC LIMIT 1`.
- For the daily live pipeline, continue using the standard FRED API (current values). For backtesting, switch to the ALFRED-sourced vintage table.
- Add a **data_source flag** to the regime classifier: `source='live'` uses `cmc_fred_daily` (current values), `source='backtest'` uses `cmc_fred_vintages` (point-in-time values). The classifier logic is identical; only the data source changes.
- NOT all 39 series need vintage storage. Prioritize series that are revised: CPI, GDP, unemployment, non-farm payrolls, PCE. Daily market series (VIX, DXY, yields) are not revised and can use standard FRED data for backtesting.

**Warning signs:**
- Backtest reading FRED data without specifying a vintage/as-of date
- Macro regime backtest results that differ from paper trading results in ways that correlate with known revision dates
- No `cmc_fred_vintages` table in the schema

**Phase:** Backtest infrastructure phase. The vintage table and data-source flag should be built alongside the macro regime classifier, not as an afterthought.

---

### Moderate: FOMC Calendar is Irregular and Announcement Times Create Intraday Look-Ahead Bias in Daily Backtests

**What goes wrong:** FOMC statements are released at 2:00 PM ET on the second day of each meeting. In a daily-bar backtest, the daily close (midnight UTC for crypto, or 4:00 PM ET for equities) occurs after the FOMC announcement. But the daily FRED series (like DFEDTAR for the fed funds target rate) is timestamped as that date. A daily backtest bar that uses this date's FRED value has the announcement information available for the full trading day, when in reality it was only known for the last ~2 hours of the US session.

For crypto (24/7 markets), BTC often moves 3-5% in the minutes after an FOMC statement. A daily backtest that uses the post-FOMC rate for the entire day's regime calculation benefits from ~22 hours of "future" data within that day.

Additionally, FOMC meetings are irregularly scheduled (8 per year, with occasional emergency meetings). The dates shift year to year. Any macro regime system that tries to "anticipate" FOMC by calendar must dynamically load the schedule.

**Prevention:**
- For the daily pipeline, accept the intraday look-ahead as an inherent limitation of daily granularity. Document this explicitly: "FOMC day regime labels use the post-announcement FRED value. In live trading, the regime label will only reflect the FOMC outcome on the bar that closes after the announcement."
- For event-aware backtesting (future enhancement), store FOMC dates in a `dim_calendar_events` table with `(event_date, event_type, announcement_time_utc)`. The regime classifier can use the previous day's FRED value for bars that close before the announcement time.
- Store FOMC meeting dates programmatically. The Federal Reserve publishes tentative meeting schedules ~18 months in advance. Scrape or manually enter these dates annually. Do NOT hardcode dates in source code.
- Consider a **FOMC-day regime override**: on FOMC announcement days, do not change the macro regime until the next daily bar. This avoids intraday look-ahead entirely at the cost of a 1-day lag.

**Warning signs:**
- FOMC dates hardcoded in Python source files
- Macro regime flipping on FOMC days in backtest but not in paper trading (because paper executor processes the FOMC bar in real-time)
- No `dim_calendar_events` or equivalent table for scheduled economic releases

**Phase:** Calendar event infrastructure phase. Can be deferred to v1.0.2 if daily granularity is acceptable for MVP, but the design should anticipate event-aware granularity.

---

## 3. Macro Regime Classifier: Overfitting and Frequency Mismatch

### Critical: Fitting a Macro Regime Model to Monthly Data Yields Fewer Than 60 Independent Regime Transitions in 5 Years

**What goes wrong:** If the macro regime changes once every 2-6 months (typical for business cycle regimes like expansion/contraction or risk-on/risk-off), then 5 years of history produces approximately 10-30 regime transitions. A classifier with even 3-4 parameters (e.g., thresholds for VIX, yield curve slope, DXY strength, and Japan rate differential) can be overfit to 10-30 transitions trivially.

The danger is that the macro regime appears to "work" in backtest because each parameter was (consciously or unconsciously) calibrated to match the known regime transitions. Out-of-sample, the regime labels are noise.

**Why it matters for this system:** The existing per-asset regime system is rule-based (EMA crossovers, ATR percentile buckets), which is transparent and difficult to overfit because the rules are structural (price above/below moving average), not fitted. Adding a macro regime that uses fitted thresholds introduces a new category of overfitting risk that the system has not previously faced.

**Prevention:**
- Prefer **structural indicators over fitted thresholds**. Examples:
  - Yield curve slope: positive = expansion signal, negative = contraction signal (structural, not fitted)
  - VIX: above 30 = high fear (a widely-used structural threshold, not fitted to this dataset)
  - DXY: 200-day moving average crossover (same structural approach as the existing per-asset regime labelers)
- Keep the macro regime classifier to **3 or fewer input dimensions** for rule-based classification. With monthly effective frequency, there is not enough data to justify more.
- If using a quantitative threshold (e.g., "yield curve slope below -X basis points"), set the threshold from economic literature or a historical distribution across many countries/cycles, NOT from optimization on the 5-year backtest window.
- Require any threshold to be justified by an economic mechanism, not just by backtest performance. "VIX > 30 is stressed because options market pricing reflects elevated hedging demand" is justified. "VIX > 27.3 optimized our Sharpe" is overfitting.
- Use the ICIR (Information Coefficient / std) framework from the existing feature experimentation system to evaluate macro regime label stability. An ICIR below 0.3 on the macro regime label signals it is noise.

**Warning signs:**
- Macro regime classifier with more than 5 parameters
- Threshold values that are not round numbers or derived from economic literature (e.g., yield curve threshold of -0.127% rather than -0.1%)
- Macro regime that flips more than 8 times per year (suggests sensitivity to noise) or fewer than 2 times per year (suggests it is not responsive enough to matter)
- Backtest Sharpe improvement of >0.3 from adding the macro regime (suspiciously large for a slow-moving overlay)

**Phase:** Macro regime classifier design phase. The "3-or-fewer dimensions, structural thresholds" constraint should be a design requirement, not a post-hoc simplification.

---

### Critical: The Tighten-Only Resolver Currently Iterates L2, L1, L0, L3, L4 -- Adding a Macro Layer Must Not Bypass Tighten-Only Semantics

**What goes wrong:** The existing `resolve_policy_from_table()` in `resolver.py` iterates `(L2, L1, L0, L3, L4)` and applies `_tighten()` at each step. The `_tighten()` function takes `min(size_mult)`, `max(stop_mult)`, and `AND(pyramids)` -- it can only make the policy more conservative, never less.

The temptation when adding a macro layer is to use it to *loosen* constraints: "Macro is favorable, so we should allow larger positions." This would require either:
1. Bypassing the tighten-only resolver (breaking the safety guarantee), or
2. Using the macro layer to set a more generous *base* policy that is then tightened by per-asset layers.

Option 1 is unacceptable -- it destroys the safety invariant that every additional layer can only reduce risk. Option 2 is subtle: if the macro layer sets `size_mult=1.2` as the base, and all per-asset layers return `size_mult=1.0`, the final policy is `min(1.2, 1.0, 1.0, ...) = 1.0`. The macro loosening has no effect. But if a developer sees this and adjusts the per-asset defaults to `1.2` to "let the macro layer through," the tighten-only guarantee is nominally preserved but the effective baseline has shifted upward.

**Consequences:** Position sizing quietly creeps upward. The system appears to "follow the rules" (tighten-only resolver is still in use) but the baseline has been inflated to accommodate macro optimism. When the macro regime is wrong, positions are larger than they should be.

**Prevention:**
- The macro regime should be implemented as an **additional tightening layer**, not a base-modifying layer. Use it in the existing L3 or L4 slot (currently unused), or add a new "L_macro" slot that feeds into `resolve_policy_from_table()`.
- The macro layer's policy table should have `size_mult <= 1.0` for ALL entries. "Favorable macro" should map to `size_mult=1.0` (neutral, no tightening), not `size_mult > 1.0` (loosening). "Unfavorable macro" should map to `size_mult=0.5` or lower. "Stressed macro" should force `orders='passive'`.
- Add an **assertion in `_tighten()`** or in the policy table loader: `assert all(entry['size_mult'] <= 1.0 for entry in macro_policy_table.values())`. This makes it mechanically impossible for the macro layer to loosen position sizing.
- Do NOT change the existing `TightenOnlyPolicy` default `size_mult=1.0`. This is the maximum any layer can start from.
- Document the design principle explicitly: "Macro regimes can only REDUCE position sizing and WIDEN stops. Favorable macro = no penalty. Unfavorable macro = penalty applied. The system never takes more risk because macro is favorable."

**Warning signs:**
- Any macro policy entry with `size_mult > 1.0`
- Suggestion to "increase position sizes when macro is favorable" (this is the core anti-pattern)
- `TightenOnlyPolicy` default `size_mult` changed from 1.0 to a higher value
- Macro layer bypassing `resolve_policy_from_table()` to directly set position sizes

**Phase:** Macro-resolver integration phase. The assertion `size_mult <= 1.0` for macro entries should be the first line of defense.

---

### Moderate: Macro Regime Changes Slowly (Weeks/Months) but Hysteresis Is Calibrated for Per-Asset Regime Speed (3 Daily Bars)

**What goes wrong:** The existing `HysteresisTracker` uses `min_bars_hold=3` for per-asset regime layers. This means a loosening regime change requires 3 consecutive identical daily bars before acceptance. For per-asset regimes that change every few days to weeks, this provides good noise filtering.

For a macro regime that changes every 2-6 months, 3-day hysteresis is essentially no filter at all. If the macro regime classifier outputs noise (flickers between "neutral" and "cautious" due to a VIX value oscillating near a threshold), the 3-day hysteresis will accept the change after just 3 days. The macro regime will flip-flop at a frequency that is meaningless for a macro overlay.

**Prevention:**
- Use a **separate hysteresis configuration for the macro layer**: `min_bars_hold=15` to `min_bars_hold=21` (3-4 weeks of daily bars). This ensures that a macro regime change must persist for 3-4 weeks before being accepted as a loosening transition.
- Alternatively, run the macro regime classifier on **weekly bars** rather than daily bars, and use `min_bars_hold=3` (3 weeks) at the weekly frequency. This is cleaner because it prevents the daily noise from even reaching the classifier.
- The `HysteresisTracker` already supports per-layer state tracking (it keys on the layer string). Use a different layer key for macro (e.g., `"L_macro"`) and instantiate a separate tracker with different `min_bars_hold`.
- Consider using the existing `is_tightening_change()` function to determine whether a macro regime change is tightening or loosening. Tightening changes (macro worsening) should bypass hysteresis and be applied immediately, consistent with the existing per-asset behavior.

**Warning signs:**
- Macro regime layer using the same `HysteresisTracker` instance (and therefore the same `min_bars_hold=3`) as per-asset layers
- Macro regime flipping more than once per month in live data (indicates insufficient hysteresis)
- Macro regime changing exactly 3 days after a VIX spike and then reverting 3 days later (noise passing through too-short hysteresis)

**Phase:** Macro-hysteresis integration phase. Decide the macro hysteresis period before implementing the regime classifier, because the hysteresis period constrains how sensitive the classifier inputs should be.

---

## 4. Cross-Asset and VIX Mapping Pitfalls

### Critical: VIX Measures US Equity Implied Volatility, Not Crypto Risk -- It Is a Proxy, Not a Signal

**What goes wrong:** VIX (CBOE Volatility Index) measures 30-day implied volatility of S&P 500 options. It is the most popular "fear gauge." The temptation is to use VIX directly as a macro regime input for crypto: "VIX > 30 = stressed macro = reduce crypto positions."

This worked imperfectly through 2024 but broke significantly in 2025, when crypto underperformed traditional assets despite a relatively benign VIX environment. The institutional maturation of crypto (ETFs, risk-parity inclusion) has changed the VIX-crypto relationship. As of late 2025, BTC implied volatility indices and S&P 500 VIX show a record-high 90-day correlation of 0.88, but this correlation itself is unstable and can break during crypto-specific events (exchange failures, regulatory actions, stablecoin de-pegs) that do not affect the S&P 500.

Additionally, VIX is only available during US market hours (9:30 AM - 4:15 PM ET). Crypto trades 24/7. A VIX reading from Friday close tells you nothing about crypto weekend risk.

**Prevention:**
- Use VIX as ONE input to the macro regime, not THE input. Combine it with at least:
  - DXY (US Dollar Index) -- measures dollar strength, directly relevant to crypto as an inverse-dollar trade
  - Yield curve slope (DGS10 - DGS2) -- measures term premium and recession risk
  - A crypto-native vol measure: 20-day rolling realized volatility of BTC (already computed in the existing pipeline as part of the tail risk evaluation in `flatten_trigger.py`)
- Weight crypto-native vol more heavily than VIX in the macro regime classifier. Use VIX for "is the broader risk environment deteriorating?" and crypto vol for "is crypto specifically stressed?"
- When VIX and crypto vol diverge (VIX low, crypto vol high = crypto-specific event; VIX high, crypto vol low = equity-specific event), the macro regime should flag uncertainty rather than picking one signal.
- Consider the BTC implied volatility index (BVIV/DVOL from Deribit) as a crypto-native alternative to VIX, though it has shorter history (~2019) and less liquidity. It cannot be sourced from FRED.

**Warning signs:**
- Macro regime classifier that uses VIX as the sole volatility input
- VIX-based regime showing "calm" while BTC is down 10% in a weekend (VIX has not updated)
- Macro regime that correctly identifies every equity selloff but misses crypto-specific events (stablecoin de-pegs, exchange collapses)

**Phase:** Macro regime classifier design phase. The input selection should combine VIX with crypto-native indicators from the start.

---

### Moderate: Cross-Asset Aggregation with 17 Assets at Different History Depths Creates Survivorship Bias

**What goes wrong:** The existing system manages 17 crypto assets with varying history depths (BTC since 2010, some altcoins since 2021 or later). When computing a "macro regime impact" score that aggregates how all assets respond to a macro signal, newer assets are underrepresented in the historical record. This creates survivorship bias: the macro regime's effectiveness appears to be whatever it is for BTC and ETH (long history), because the altcoins with short history are either excluded or weighted down.

Furthermore, assets that existed during the 2022 crypto winter but were later delisted (or stopped trading) are absent from the universe. The macro regime's "hit rate" during that period only counts assets that survived, overstating its effectiveness.

**Prevention:**
- When evaluating macro regime effectiveness, compute metrics **per asset tier** separately: BTC, major alts (ETH, SOL, etc.), and smaller alts. Do not aggregate across tiers.
- For regime labels, apply the macro regime uniformly across all assets (it is a macro-level signal, not asset-specific). But for backtesting the regime's P&L impact, only include assets that existed during the test period (use `asset_data_coverage` table to filter by `source_table` and `granularity`).
- Do not fit macro regime thresholds on BTC-only data and then apply to the full universe. BTC's response to macro signals is stronger (higher beta) than altcoin responses, which are dominated by idiosyncratic factors (token economics, airdrop events, protocol upgrades).
- Document which assets contributed to each macro regime evaluation period.

**Warning signs:**
- Macro regime backtest that runs on all 17 assets but only has data for 3 assets before 2021
- Macro regime metrics that are suspiciously good for 2022 (the regime correctly called risk-off for all assets, but only tested on survivors)
- BTC-fitted macro thresholds applied to altcoins without separate validation

**Phase:** Macro regime evaluation phase. The per-tier evaluation should be designed before any macro regime backtest is run.

---

## 5. Risk Integration Pitfalls

### Critical: Adding a Macro Regime Gate to the Risk Engine Without a Configurable Bypass Creates a "Macro Kill Switch" That Cannot Be Overridden

**What goes wrong:** The existing risk engine has 7 gates (kill switch, tail risk, circuit breaker, position cap, portfolio cap, margin check, all-pass). If a new "macro regime gate" is added (e.g., "block all buys when macro regime = stressed"), it becomes a hard gate that cannot be bypassed without code changes.

During a macro regime misclassification (which WILL happen given the limitations described in Pitfall 3), all trading stops. Unlike the kill switch (which has a CLI override in `kill_switch_cli.py`) and the circuit breaker (which has `reset_circuit_breaker()`), a macro gate without an override mechanism becomes an unreachable lock.

**Why it matters for this system:** The existing risk override system (`cmc_risk_overrides`, `override_manager.py`) allows manual overrides for kill switch and circuit breaker. A macro gate that does not integrate with the override system is an orphan gate.

**Prevention:**
- Do NOT add a hard gate to the risk engine for macro regime. Instead, integrate the macro regime through the **existing resolver pathway**: macro regime -> policy table -> `size_mult` and `orders` -> resolver output -> position sizing. The risk engine already enforces position caps based on the resolver's output.
- If a "macro stressed" state should block trading, implement it as an **escalation to tail risk state** rather than a new gate. The tail risk system already has NORMAL/REDUCE/FLATTEN states, de-escalation cooldowns, and override paths. Set `tail_risk_state = 'reduce'` when macro is stressed and `tail_risk_state = 'flatten'` when macro is critical. This reuses the existing infrastructure.
- If a separate macro gate is truly needed, ensure it:
  - Has an override in `dim_risk_overrides` (`override_type = 'macro_gate'`)
  - Has a CLI command for emergency bypass (`macro_gate_override_cli.py`)
  - Has an auto-expiry: overrides expire after 24 hours unless renewed
  - Logs all activations and overrides to `cmc_risk_events`
- Add a Telegram alert when the macro gate blocks an order, with an inline command to override.

**Warning signs:**
- New gate added to `RiskEngine.check_order()` without a corresponding override in `dim_risk_overrides`
- Macro gate that blocks orders with no CLI or API to bypass it
- Macro gate that fires frequently (>2x per week) -- this will be ignored within a month (alert fatigue)

**Phase:** Risk integration phase. Decide BEFORE implementation whether macro regime feeds through the resolver (preferred) or through a new risk gate (requires override infrastructure).

---

### Moderate: Alert Fatigue -- Risk Gates That Fire Too Frequently Become Ignored

**What goes wrong:** If the macro regime gate fires warnings on 30% of trading days ("macro caution: yield curve inverted"), operators will start ignoring all macro alerts within 2-4 weeks. Research shows that when false positive rates exceed 30-40%, humans stop responding to alerts entirely. The security operations center (SOC) literature documents this extensively: 51% of SOC teams report being overwhelmed by alert volume, with analysts spending >25% of their time on false positives.

In a trading context, a macro regime that is "cautious" 30% of the time is not providing useful information -- it is providing noise. The per-asset regime system already captures most risk reduction. The macro overlay should fire rarely (5-10% of days) and be correct when it fires.

**Prevention:**
- Set the macro regime alert threshold so that the "stressed" or "cautious" state activates on no more than 10-15% of historical trading days. If the threshold must be set higher, it is not a macro regime -- it is a baseline condition.
- Implement **tiered alerting**:
  - Macro "cautious" = log to database + dashboard indicator (no Telegram notification)
  - Macro "stressed" = Telegram notification + size reduction via resolver
  - Macro "crisis" = Telegram critical alert + tail risk escalation
- Track the **alert hit rate**: what fraction of macro alerts preceded an actual drawdown within 5 trading days? If the hit rate is below 30%, the threshold is too sensitive. Log this in a monthly report.
- Use the existing Telegram notification system's throttling to prevent alert storms. Set macro alerts to a maximum of one notification per 8 hours.

**Warning signs:**
- Macro regime in "cautious" or "stressed" state for >50 days in a 252-day trading year
- Operator response time to macro alerts increasing over time (indicating desensitization)
- Macro alert followed by no drawdown within 10 days in >70% of cases (false positive rate too high)

**Phase:** Alert integration phase. Calibrate alert frequency using historical data before enabling Telegram notifications.

---

## 6. Carry Trade and Fast-Event Detection

### Critical: Japan Carry Trade Unwind Happens in Hours but FRED Japan Rate Data Is Monthly -- You Must Use Proxy Signals

**What goes wrong:** The August 2024 yen carry trade unwind is the canonical example. The BoJ raised rates on July 31, 2024. BTC dropped 15% against JPY within 48 hours. The FRED monthly Japan policy rate (IRSTCI01JPM156N) would not reflect this until the August observation was published in September. The forward-filled monthly rate showed no change during the entire crisis.

The carry trade is estimated at up to $14 trillion in yen-denominated positions (BIS data), roughly 3x the entire crypto market capitalization. When it unwinds, the speed is measured in hours, not months. Monthly data is structurally incapable of detecting this.

**Why it matters for this system:** If the macro regime system relies on FRED Japan rate data to detect carry trade risk, it will be 30-60 days late on the most consequential macro event for crypto markets.

**Prevention:**
- Use **daily proxy indicators** for carry trade risk:
  - USD/JPY exchange rate (available daily or real-time from exchange APIs, not FRED)
  - Japan 10Y government bond (JGB) yield (available from FRED as DGS10-equivalent, but check availability)
  - The VIX-yen correlation: when VIX spikes and JPY strengthens simultaneously, carry trade unwind is likely
- The monthly FRED Japan rate data should be used for **trend confirmation**, not detection. Use it to determine whether the carry trade is building (low rates, weakening yen = building) or unwinding (rate hikes, strengthening yen = unwinding), but use daily proxies for timing.
- Add a **yen-strength alert**: if USD/JPY drops more than 3% in a 5-day rolling window, escalate macro regime to "cautious" regardless of the monthly rate data. This would have caught the August 2024 event.
- Consider adding a daily USD/JPY or DXY data feed that is NOT from FRED (FRED's exchange rate series update with a 1-day lag). A direct API feed from an exchange data provider gives real-time data.

**Warning signs:**
- Macro regime system that relies solely on FRED monthly Japan data for carry trade risk assessment
- No daily proxy indicator for yen strength in the macro input set
- Macro regime that does not detect the August 2024 carry trade unwind when backtested

**Phase:** Macro regime classifier design phase. The carry trade detection strategy must use daily proxies from day one; monthly FRED data is a confirmation layer only.

---

## 7. Data Quality and Edge Cases

### Moderate: Some FRED Series Have Publication Delays That Create Artificial Gaps After Weekends and Holidays

**What goes wrong:** Not all daily FRED series are published at the same time. VIX (VIXCLS) is typically available the next morning. The 10-year yield (DGS10) may appear slightly later. The DXY (DTWEXBGS) updates weekly, not daily. A pipeline that runs at 06:00 UTC may find VIX updated but DGS10 not yet available, and DXY stale for 5 days.

If the pipeline treats "not yet published" the same as "gap," it will forward-fill from the previous day's value, which is correct for VIX (yesterday's close is the most recent data) but wrong for DXY (which has been stale for a week and will suddenly jump when the weekly observation appears).

**Prevention:**
- Document the expected publication schedule for each of the 39 series in `dim_fred_series_metadata`:
  - `publication_frequency`: daily, weekly, monthly
  - `typical_publication_lag_hours`: how long after the reference period the data appears in FRED
  - `observation_frequency`: how often a new data point is expected
- The daily refresh should distinguish between "series has not published yet today" (normal for the first hours after midnight) and "series is missing an expected observation" (abnormal, trigger alert).
- For weekly series (DXY, some yield curves), do not attempt daily forward-fill. Instead, store at weekly frequency and let the `cmc_fred_daily` fill step handle the interpolation with an explicit `fill_method='ffill_from_weekly'` tag.

**Warning signs:**
- All 39 series treated as if they publish daily
- DXY showing a 5-day gap followed by a jump on the weekly publication day
- Alerts firing every Saturday and Sunday for "missing" daily series (they do not publish on weekends)

**Phase:** Data pipeline design phase. The metadata table should be populated before writing any refresh logic.

---

### Moderate: Yield Curve Slope Computation Can Produce Misleading Values When Short-End and Long-End Series Have Different Publication Lags

**What goes wrong:** The yield curve slope (DGS10 - DGS2) is a critical macro regime input. Both series are published daily, but publication times may differ by hours. If the pipeline reads DGS10 at a time when it has today's value but DGS2 still shows yesterday's value, the computed slope is a mix of two different days. This is usually harmless (daily changes are small) but on days with large yield curve moves (Fed announcement days), the mixed-day slope can be significantly wrong.

Additionally, during government shutdowns or FRED maintenance periods, one series may update while the other does not, creating multi-day misalignment.

**Prevention:**
- Always compute yield curve slope from series that share the same `observation_date`. The SQL should be:
  ```sql
  SELECT a.value - b.value AS slope
  FROM cmc_fred_daily a
  JOIN cmc_fred_daily b ON a.observation_date = b.observation_date
  WHERE a.series_id = 'DGS10' AND b.series_id = 'DGS2'
  AND a.fill_method = 'observed' AND b.fill_method = 'observed'
  ORDER BY a.observation_date DESC LIMIT 1
  ```
  This ensures both values are from the same actual FRED observation, not a mix of observed and forward-filled.
- If only one series has updated, use the previous day's slope rather than computing a mixed-day value.
- Store the computed slope as a derived series (`yield_curve_10y_2y`) in `cmc_fred_daily` with its own `fill_method` and `observation_date`.

**Warning signs:**
- Yield curve slope computed by joining series on calendar date without checking whether both are actual observations
- Slope showing sudden jumps that do not correspond to market events (artifact of publication-lag mismatch)

**Phase:** Derived indicator computation phase. Build the slope computation after the base series pipeline is stable.

---

### Minor: FRED Series Can Be Discontinued or Changed Without Warning

**What goes wrong:** FRED occasionally discontinues series, changes their methodology (seasonal adjustment formula), or renames them. The daily pipeline will silently fail (API returns empty for the series) or silently change behavior (seasonally adjusted series switches methodology, causing a level shift).

**Prevention:**
- The `dim_fred_series_metadata` table should include `last_known_observation_date`. If this date is more than `2 * expected_frequency_days` in the past, flag the series as potentially discontinued.
- Monitor the `last_updated` field from `get_series_info()` on each refresh. If it has not changed in `2 * expected_frequency_days`, log a WARNING.
- Maintain a list of backup series for critical inputs (e.g., if VIXCLS is discontinued, use an alternative VIX source).

**Phase:** Data pipeline robustness phase. Add the staleness monitor early; the backup series list can be deferred.

---

## 8. Integration with Existing Drift and Validation Systems

### Moderate: Macro Regime Changes Will Cause Drift Between Paper Executor and Backtest Replay Unless Both Use the Same Regime Source

**What goes wrong:** The existing `DriftMonitor` replays backtests against paper executor fills to compute drift metrics. If the paper executor used a live macro regime label (computed from today's FRED data) but the backtest replay uses a recomputed macro regime label (from potentially revised FRED data or a different computation timestamp), the two will produce different regime labels on boundary days. This creates drift that is attributed to "execution issues" when it is actually "regime label divergence."

**Prevention:**
- The paper executor must **log the macro regime label** it used for each order decision, in `cmc_orders` or a new `cmc_order_regime_context` table. The drift monitor replay must use these logged labels, not recompute them.
- For the backtest replay side, the drift monitor already loads executor configs from `dim_executor_config`. Add a `macro_regime_source` field: `'logged'` (use the logged label from the order) or `'recomputed'` (recompute from current data). Default to `'logged'` for drift monitoring, `'recomputed'` for fresh backtests.
- This is the same pattern as point-in-time (PIT) vs current-data backtesting, which the `DriftMonitor` already supports. The macro regime label is just another data input that can differ between PIT and current views.

**Warning signs:**
- Paper executor not logging which macro regime label was active when each order was placed
- Drift monitor showing unexplained drift on days when the macro regime label changed
- No `macro_regime_label` column in order or fill tables

**Phase:** Executor-drift integration phase. The logging should be implemented when the macro regime is first wired into the executor.

---

## Phase-Specific Warnings Summary

| Phase Topic | Likely Pitfall | Severity | Mitigation |
|---|---|---|---|
| FRED data storage design | Forward-fill without staleness tracking masks regime lag | Critical | Two-table design: raw observations + daily-filled with `days_since_publication` |
| FRED data storage design | Holiday/weekend gaps create 31% NULL joins with crypto data | Critical | Forward-fill with `limit` parameter; `fill_method` column; join through filled table only |
| FRED daily refresh | Partial refresh leaves mixed-vintage macro state | Moderate | Atomic refresh marker; retry failed series; priority ordering by impact |
| Backtest infrastructure | Current FRED data in backtest = look-ahead bias for revised series | Critical | ALFRED vintage data via `fredapi`; `cmc_fred_vintages` table; data-source flag |
| Calendar events | FOMC intraday announcement time vs daily bar timing | Moderate | `dim_calendar_events` table; FOMC-day override option; document the limitation |
| Macro regime classifier | Overfitting to <60 regime transitions in 5 years | Critical | 3-or-fewer dimensions; structural thresholds from literature; ICIR evaluation |
| Resolver integration | Macro layer used to loosen position sizing (bypass tighten-only) | Critical | Assertion: `size_mult <= 1.0` for all macro entries; use existing L3/L4 slot |
| Hysteresis calibration | 3-bar daily hysteresis too short for monthly-frequency macro changes | Moderate | Separate hysteresis config: `min_bars_hold=15-21` for macro layer |
| VIX as crypto proxy | VIX only covers US equity hours; misses crypto-specific events | Critical | Combine VIX with DXY, yield curve, and crypto-native vol; weight crypto vol higher |
| Cross-asset evaluation | Survivorship bias from unequal asset history depths | Moderate | Per-tier evaluation (BTC, majors, alts); use `asset_data_coverage` to filter |
| Risk engine integration | New macro gate without override = unreachable lock on misclassification | Critical | Feed macro through resolver (preferred) or integrate with existing override system |
| Alert system | Macro alerts firing >30% of days = alert fatigue within weeks | Moderate | Three-tier alerting; calibrate "stressed" to fire 10-15% of days; track hit rate |
| Carry trade detection | Monthly Japan rate data is 30-60 days late for unwind events | Critical | Daily proxy indicators (USD/JPY, DXY, VIX-yen correlation); monthly data for confirmation only |
| Publication schedule | Series have different publication lags; mixed-day computations | Moderate | `dim_fred_series_metadata` with per-series publication schedule; aligned-day joins |
| Derived indicators | Yield curve slope from mixed-day observations on announcement days | Moderate | Join on `observation_date` with `fill_method = 'observed'` filter |
| Series continuity | FRED can discontinue series without warning | Minor | Staleness monitor; `last_known_observation_date`; backup series list |
| Drift monitoring | Macro regime label divergence between paper executor and backtest replay | Moderate | Log macro regime label per order; drift monitor uses logged labels |

---

## Sources

- [BIS Bulletin No 90: The market turbulence and carry trade unwind of August 2024](https://www.bis.org/publ/bisbull90.pdf) -- HIGH confidence (primary institutional source documenting the yen carry trade unwind mechanism, scale, and timing)
- [CoinDesk: Bitcoin drops 15% against Japanese Yen as carry trades unwind (August 2024)](https://www.coindesk.com/markets/2024/08/05/bitcoin-drops-15-against-japanese-yen-outpacing-declines-versus-usd-as-yen-carry-trades-unwind/) -- HIGH confidence (contemporaneous reporting of the actual event)
- [CoinDesk: BTC Volatility Index and S&P 500 VIX boast record 90-day correlation (July 2025)](https://www.coindesk.com/markets/2025/07/24/btc-volatility-index-and-the-s-and-p-500-vix-boast-record-90-day-correlation) -- MEDIUM confidence (market reporting, verifiable)
- [BingX: How to Use VIX in Crypto Trading -- Limitations](https://bingx.com/en/learn/article/what-is-volatility-index-vix-in-crypto-trading) -- MEDIUM confidence (practitioner source, consistent with academic findings)
- [FRED ALFRED: Real-Time Period Documentation](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html) -- HIGH confidence (official FRED documentation)
- [fredapi GitHub: ALFRED vintage methods (get_series_first_release, get_series_as_of_date)](https://github.com/mortada/fredapi) -- HIGH confidence (library source code and README)
- [St. Louis Fed: Data Revisions with FRED](https://www.stlouisfed.org/publications/page-one-economics/2022/08/01/data-revisions-with-fred) -- HIGH confidence (official FRED publication explaining revision process)
- [arXiv: Tactical Asset Allocation with Macroeconomic Regime Detection (2025)](https://arxiv.org/html/2503.11499v2) -- MEDIUM confidence (preprint, peer review status unknown)
- [FactSet: Mapping Asset Returns to Economic Regimes](https://insight.factset.com/mapping-asset-returns-to-economic-regimes-a-practical-investors-guide) -- MEDIUM confidence (institutional practitioner guide)
- [Ghysels et al.: The MIDAS Touch -- Mixed Data Sampling Regression Models](https://rady.ucsd.edu/_files/faculty-research/valkanov/midas-touch.pdf) -- HIGH confidence (foundational academic paper on mixed-frequency data)
- [Federal Reserve: FOMC Meeting Calendar and Blackout Periods](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm) -- HIGH confidence (official Federal Reserve source)
- [CryptoTicker: Why Crypto Underperformed in 2025](https://cryptoticker.io/en/crypto-2025-disconnect-what-went-wrong-2026-outlook/) -- LOW confidence (analysis article, useful for context but not authoritative)
- Codebase direct inspection: `regimes/resolver.py` (L0-L4 tighten-only iteration, `_tighten()` function), `regimes/hysteresis.py` (HysteresisTracker with `min_bars_hold=3`), `regimes/labels.py` (per-asset labelers L0-L3), `regimes/data_budget.py` (minimum bars per layer), `risk/risk_engine.py` (7-gate risk engine), `risk/flatten_trigger.py` (tail risk thresholds calibrated from BTC 2010-2025), `integrations/economic/fred_provider.py` (FredProvider with rate limiter, circuit breaker, cache), `drift/drift_monitor.py` (PIT vs current-data replay) -- HIGH confidence (observed directly in codebase)
