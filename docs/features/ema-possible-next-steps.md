---
title: "ema_possible_next_steps"
author: "Adam Safi"
created: 2025-12-07T10:55:00+00:00
modified: 2025-12-07T10:56:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Features\EMAs\DesriptiveDocuments\ema_possible_next_steps.docx"
original_size_bytes: 21168
---
**Exponential Moving Average (“EMA”) Possible Next
Steps**

**1. The core design axes (what you’re already
varying)**

You’ve already identified the correct independent dimensions:

**A. Time grid definition**

* **tf\_days** (fixed-length, no calendar)
* **calendar-observed**
* **anchored-fixed**

**B. Update granularity**

* **daily (time-space)**
* **bar-only (bar-space)**

**C. Seeding rules**

* **allow partial initial periods**
* **require first full period**

**D. Alpha regime**

* **daily alpha**
* **bar alpha**
* **hybrid (daily intra-bar, bar alpha at close)** ✅
  (you already have this)

Your current five cover the *main diagonal* of this
matrix.

**2. Combinations you already have (sanity check)**

| **Variant** | **Grid** | **Update** | **Alpha** | **Purpose** |
| --- | --- | --- | --- | --- |
| multi\_tf | fixed days | daily | daily | math / TF purity |
| \_cal | calendar | daily | daily | reporting / macro |
| \_cal\_bar | calendar | hybrid | daily+bar | calendar bar signals |
| \_anchor | anchored | daily | daily | chart-aligned daily |
| \_anchor\_bar | anchored | hybrid | daily+bar | ✅ TradingView parity |

This is a **very strong, almost complete basis**.

**3. Additional combinations worth
*considering***

**✅ 1. Pure bar EMA with no daily intra-bar
updates**

(**bar-only / sparse EMA**)

* **Grid:** anchored or calendar
* **Updates:** bar close only
* **Alpha:** bar alpha only
* **Ignores:** all intra-bar prices

This is *not* TradingView-style, but it is:

* simpler
* sometimes used in academic factor research
* common in discrete-time regime models

📌 Recommendation:

* **Document it**
* Don’t implement unless needed
* If implemented: name it clearly (e.g.,
  \_anchor\_bar\_sparse)

**✅ 2. Session-aware anchored bars
(equities-style)**

* **Grid:** anchored to *trading sessions*, not
  calendar days
* **Updates:** daily inside session
* **Alpha:** hybrid
* **Example:** NYSE Mon–Fri weeks, ignoring
  holidays

Not useful for BTC, but very relevant for:

* futures
* equities
* multi-asset systems

📌 Recommendation:

* Worth mentioning as a **future extension**
* Not needed now

**✅ 3. Timezone-anchored bars**

* **Grid:** anchored, but explicitly tied to
  timezone

  + UTC
  + New York
  + Exchange-local
* **Everything else:** same as \_anchor\_bar

TradingView differences often come from **timezone
anchoring**, not EMA math.

📌 Recommendation:

* Keep this as a **parameter**, not a new
  table
* Still worth calling out explicitly in docs

**✅ 4. Volume-weighted EMA variants (VWEMA-like)**

* **Grid:** any
* **Update:** daily or bar
* **Alpha:** daily / bar
* **Weighting:** price × volume

This is *conceptually* another EMA family but orthogonal to
your time logic.

📌 Recommendation:

* Out of scope for EMA tables
* Belongs in a separate indicator family

**❌ 5. Mixing calendar grid + bar alpha + no canonical
boundaries**

This combination:

* has no stable interpretation
* produces ambiguous results
* breaks reproducibility

You’re **right not to include it**.

**4. The one combination people *think* they want — but
shouldn’t**

“Calendar EMA using bar alpha but updating daily”

This:

* double-counts smoothing
* distorts period meaning
* is mathematically incoherent

✅ You correctly avoided this.

**5. Final verdict (important)**

You are **not missing anything essential**.

What you have is:

* ✅ institutionally defensible
* ✅ TradingView-compatible
* ✅ internally consistent
* ✅ explainable to auditors and collaborators

The only additions worth mentioning (not necessarily building):

1. **Pure bar-only EMA (sparse)**
2. **Session-aware anchoring**
3. **Explicit timezone anchoring**

Everything else is either:

* redundant
* incoherent
* or a different indicator class entirely

**One-sentence close you can put in the docs**

The EMA variants implemented here span all materially distinct
combinations of time-grid definition, update granularity, and smoothing
regime used in professional technical analysis; additional variants
either reduce to these cases or sacrifice interpretability.