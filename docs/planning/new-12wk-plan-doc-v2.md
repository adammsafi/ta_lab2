---
title: "new_12wk_plan_doc_v2"
author: "Adam Safi"
created: 2025-11-27T20:16:00+00:00
modified: 2025-11-28T18:59:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Plans&Status\new_12wk_plan_doc_v2.docx"
original_size_bytes: 28295
---
**✅ PART 1 — How the “Time Discussion” Fits Into the
Plan**

After reviewing the zip AND the time-handling summary, the conclusion
is:

**Your previous plan assumed a much simpler concept of "time"
than what ta\_lab2 actually needs.**

The time discussion reveals that your system must treat
*timeframes, trading sessions, calendar alignment, business days, and
cross-market time propagation* as first-class architectural
components—not convenience utilities.

The attached summary makes several critical points that the old plan
did **not** account for:

**1. The entire system must be built around a formal, explicit
model of time**

The summary states clearly that:

* Crypto is 24/7
* Equities are session-based
* ADRs adjust after underlying markets move
* Futures and FX operate 24/5 with overlapping sessions
* Cross-market reaction timing matters
* DST affects session opens/closings differently
* Calendar alignment and tf\_day alignment require different
  logic
* EMA calculations using calendar windows behave differently than
  tf\_day windows
* You currently have *two EMA multi-TF systems* because of
  this missing unification

This fundamentally affects the architecture.

**2. A formal dim\_timeframe table is no longer optional — it's
required**

The summary explicitly shows:

* Current TF definitions are implicit
* Calendar logic isn't consistently used
* Multi-TF and calendar-TF EMAs are split in two tables
* There is no authoritative source of truth for what “1M”, “3M”,
  “45D”, “EOM roll”, or “tf\_day=45” actually *mean*

Your previous plan said:

“Build dim\_timeframe table week 3–4.”

That is **now too late**.  
The time model needs to be built **before** returns, vol,
indicators, and unified feature pipelines.

**3. Multi-market implications mean your system must support
session-aware pipelines**

While you're only ingesting crypto right now, the summary makes
clear:

* The system architecture must be designed to eventually
  support:

  + NYSE opens
  + after-hours sessions
  + FX continuous trading
  + futures rollover times
  + international timezone reactions
* Even crypto EMA/returns calculations should use the correct TF
  definitions so they generalize later.

This means that before building returns/vol/TA pipelines, you must
define:

1. **dim\_timeframe (canonical TFs + rules)**
2. **dim\_sessions (per-asset trading hours and session
   rules)** — even if initially empty

Your old plan had *no concept of sessions* anywhere.  
This is a significant oversight corrected by the time discussion.

**4. Multi-TF EMAs (tf\_day vs calendar) should be unified into
a single table**

The summary explicitly identifies:

* Two separate EMA multi-TF systems
* Overlapping semantics
* Hard to maintain
* Confusing future expansion

The previous plan did not call for unifying these.  
It simply assumed you could stabilize “multi-TF EMA” as-is.

Now we know that’s impossible without:

* dim\_timeframe
* a unified schema
* a unified calculation model

**5. DST must be handled abstractly—not in EMA
logic**

DST does not affect:

* tf\_day windows
* calendar anchors
* EMA formulas

But it *does* affect:

* trading session boundaries
* session alignment
* cross-market propagation

Your old plan didn't allocate any time for DST/session handling.

Now it must.

**❗ PART 2 — What Must Change in the Plan**

Here are the **required changes**, directly derived from
the summary:

**Change 1 — Move dim\_timeframe to the front of the plan (Week
1–2)**

This is now foundational.  
The entire EMA, returns, vol, and indicator logic must reference
dim\_timeframe.

**Change 2 — Add a new Week 1 objective: Define dim\_sessions
(even if partially empty)**

You need trading-session semantics defined now so later work doesn’t
break.

**Change 3 — Unify cmc\_ema\_multi\_tf and cmc\_ema\_multi\_tf\_cal
into one table**

This requires a refactor of:

* schema
* scripts
* roll logic
* tf\_days logic
* calendar anchors
* flags

This must happen **before** returns/vol/TA.

**Change 4 — Calendar alignment must be explicitly defined
using the new dimension tables**

No more “in-code magic.”

**Change 5 — All downstream features (returns, vol, indicators)
must reference dim\_timeframe**

This ensures portability and multi-asset scaling.

**Change 6 — Scheduling and stats must be updated to use the
time dimension model**

Your old plan scheduled refreshes based purely on prices.  
Now scheduling depends on:

* tf\_day windows
* calendar windows
* session boundaries

**🔁 PART 3 — Updated Plan (Summary Only)**

**What changed in the plan:**

1. **Week 1–2 now dedicated to the time model (dim\_timeframe +
   dim\_sessions)**
2. **EMA unification moved up to Week 2–3**
3. **Returns/vol/indicators pushed back to Weeks
   4–7**
4. **Daily features + signals pushed back
   accordingly**
5. **Everything now references the time dimension
   tables**
6. **Session-awareness and DST-awareness added to the
   architecture**
7. **Rolling vs calendar logic standardized**
8. **Statistical validation updated to leverage dimension
   tables**

Now here is the new full plan:

**🧠 PART 4 — Updated Full 12-Week Plan (Incorporating Time
Model)**

This replaces the previous plan entirely.

**Week 1 (Dec 1–7): Build the Time Model –
dim\_timeframe**

**Deliverables:**

* Create dim\_timeframe table
* Define every timeframe as rows (1D, 3D, 5D, 10D, 21D, 45D, 1W,
  1M, 3M, 6M, 1Y, etc.)
* Fields include:

  + tf
  + base\_unit
  + tf\_days\_nominal
  + alignment\_type (tf\_day | calendar)
  + calendar\_anchor (EOM, EOQ, EOY)
  + roll\_policy
  + is\_canonical
* Add Python wrapper to load this dimension

**Why?**  
Because every EMA/return/vol/TA must reference it.  
()

**Week 2 (Dec 8–14): Build Trading Sessions –
dim\_sessions**

**Deliverables:**

* Create trading session reference table
* Fields:

  + asset\_id
  + timezone
  + session\_open\_local
  + session\_close\_local
  + is\_24h
* Implement DST-safe logic for sessions
* Connect calendar.py to session logic

**Why?**  
Cross-market propagation and multi-asset EMAs require
session-awareness.

**Week 3 (Dec 15–21): Unify EMA Multi-TF Into One
Table**

**Deliverables:**

* Merge cmc\_ema\_multi\_tf + cmc\_ema\_multi\_tf\_cal into:

  + cmc\_ema\_multi\_tf\_unified
* Schema includes:

  + tf referencing dim\_timeframe
  + roll logic consistent with alignment\_type + roll\_policy
* Remove duplication
* Update all refresh scripts to use unified logic
* Add rowcount + spacing validation tests

**Why?**  
Two EMA models = permanent inconsistency.  
This is the biggest structural fix.  
()

**Week 4 (Dec 22–28): Stabilize EMA Pipeline + Incremental
Logic**

**Deliverables:**

* Make EMA refresh scripts incremental by default
* Ensure only NEW rows are computed
* Validate using new dimension tables
* Confirm tf\_day intervals line up
* Confirm calendar anchors line up
* Build stats script comparing actual vs tf-defined
  rowcounts

**Week 5 (Dec 29–Jan 4): Implement Returns Table Using Time
Model**

**Deliverables:**

* Create cmc\_returns\_daily
* All lookbacks come from dim\_timeframe (e.g., 1D, 2D, 5D,
  21D)
* Incremental refresh script
* Add SQL view for debugging

**Week 6 (Jan 5–11): Implement Volatility Table**

**Deliverables:**

* Create cmc\_vol\_daily
* Use vol functions (Parkinson, GK, etc.)
* Windows come from dim\_timeframe
* Incremental refresh script

**Week 7 (Jan 12–18): Implement TA Indicators (RSI, MACD,
etc.)**

**Deliverables:**

* Create cmc\_ta\_daily
* Use features.indicators
* Respect session boundaries and tf definitions
* Incremental refresh script

**Week 8 (Jan 19–25): Unified Daily Feature View**

**Deliverables:**

* Create cmc\_daily\_features view/table joining:

  + price
  + EMAs
  + returns
  + vol
  + TA
* Validate joins against time dimension
* Null-handling strategy finalized

**Week 9 (Jan 26–Feb 1): Signals Layer v1**

**Deliverables:**

* Implement cmc\_signals\_daily
* Use unified features
* Basic signal types:

  + EMA crossovers
  + RSI MR
  + ATR breakout
* Incremental refresh script

**Week 10 (Feb 2–8): Backtest Integration v1**

**Deliverables:**

* Write backtest orchestration referencing
  cmc\_daily\_features
* Integrate signals from DB
* Store backtest results in DB

**Week 11 (Feb 9–15): Observability, Stats & Data
Quality**

**Deliverables:**

* Formal stats suite referencing time dimension
* Gap tests
* TF alignment tests
* Roll alignment tests
* Null/NaN tests
* Weekly QC report

**Week 12 (Feb 16–22): Documentation, Release,
Cleanup**

**Deliverables:**

* Full docs rewrite
* Architecture diagrams
* Time model documentation
* EMA model documentation
* Data pipeline documentation
* Tag release v0.4.0

**✅ Final Notes**

This updated plan is:

* More realistic
* More aligned with actual code
* More aligned with your future goal (multi-market, multi-asset
  pipeline)
* Better architected
* More maintainable
* Higher leverage

It transforms ta\_lab2 from “EMA engine + features” into a
**true time-aware quant research framework**.