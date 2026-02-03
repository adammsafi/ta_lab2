---
title: "review_refreshMethods_20251201"
author: "Adam Safi"
created: 2025-11-19T10:43:00+00:00
modified: 2025-12-01T12:43:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\review_refreshMethods_20251201.docx"
original_size_bytes: 22895
---
I’ll break it into three pieces:

1. Pros/cons of **Option A (incremental logic in refresh() /
   runner layer)**
2. Pros/cons of **Option B (incremental logic in build\_\*
   functions)**
3. **Drift** in incremental EMAs and how a periodic
   full recompute (every ≤3 months) addresses it

**1. Option A – Incremental logic in refresh() (or similar
orchestration layer)**

**Idea:**  
Leave build\_daily\_ema\_frame() and build\_multi\_timeframe\_ema\_frame() as
“full-history from prices” builders. Put all incremental logic in
refresh() (or a new helper), which:

* Reads last EMA rows from DB
* Reads only new prices
* Either:

  + Calls full-history builder on a *truncated* slice (e.g.,
    last N days + tail), or
  + Manually stitches outputs (e.g., drop early rows, keep only new
    timestamps)

**Pros**

* **No big changes to existing core builders.**  
  You keep build\_\* as pure, stateless “given prices → give full series”
  functions. Less risk of introducing bugs in complex multi-TF
  logic.
* **Easier to experiment and iterate.**  
  If you don’t like your incremental strategy or want to change how you
  read seeds from DB, you tweak the refresh/orchestration layer without
  touching EMA math.
* **Clear, layered responsibility.**

  + EMA math & roll/d1/d2 logic: in build\_\*.
  + “What’s new?” + DB queries + seeds + writing: in
    refresh().
* **Short-term implementation is
  straightforward.**  
  A basic version could be:

  + Look up max(ts) per (id, tf, period) in the EMA tables,
  + Load prices only after that,
  + Call the builders on a window that overlaps a bit with the past
    (e.g., last 200 days) and then drop duplicates with ON CONFLICT DO
    NOTHING.

**Cons**

* **Can get messy / ad-hoc over time.**  
  The orchestration layer might accumulate special cases:

  + “For daily, do X; for multi-TF 3D/10D/1W, do Y; for monthly, do
    Z…”
  + Harder to reason about when you’re debugging a specific
    EMA.
* **You’re still recomputing more than strictly
  necessary.**  
  Even with a truncation window like “last 200 days,” you’re recomputing a
  bunch of EMAs every day. Better than full history, but not
  minimal.
* **Incremental logic may be duplicated for daily vs
  multi-TF.**  
  If each path gets its own incremental hack, you can end up with two
  subtly different ways of handling seeds/resampling, etc.

**2. Option B – Incremental APIs inside build\_\***

**Idea:**  
Teach build\_daily\_ema\_frame() and build\_multi\_timeframe\_ema\_frame()
about incremental state. For example:

build\_daily\_ema\_frame(

prices\_df,

period,

seed\_ema=None,

seed\_ts=None,

mode="full" | "incremental"

)

and something similar for multi-TF with seeds for:

* last canonical bar EMA (roll = FALSE)
* last rolling EMA (roll = TRUE)
* last diffs

**Pros**

* **Single source of truth for EMA math and state
  transition.**  
  The same place that defines the EMA recursion also defines how you carry
  it forward incrementally. Much easier to reason about
  correctness.
* **Maximum performance upside.**  
  If the builders accept seeds and “new price rows only,” you can compute
  the exact tail and never touch old rows again.
* **Cleaner orchestration code.**  
  refresh() just:

  + Reads seeds from DB,
  + Reads new prices,
  + Calls build\_\* in incremental mode,
  + Writes the results.
* **Reusability.**  
  If you ever do streaming / “per-bar” updates, backtesting with
  incremental updates, or other tooling, incremental builders are directly
  usable.

**Cons**

* **Higher complexity inside already complex
  functions.**  
  build\_multi\_timeframe\_ema\_frame() is already doing resampling, canonical
  vs preview, d1/d2 vs d1\_roll/d2\_roll. Adding seed management can make it
  harder to maintain.
* **More careful testing required.**  
  You’ll want tests like:

  + “Full-history vs incremental for the same id/tf/period over N
    days must match to within epsilon.”
  + “Incremental across TF boundaries (e.g., when a new 10D or 1M bar
    closes) matches full-history.”
* **Refactor cost now vs later.**  
  It’s a bigger up-front investment. If you change multi-TF logic again,
  you’re touching both full and incremental code paths.

**3. Drift with incremental EMAs and periodic full
recompute**

**Where drift can come from**

A *mathematically correct* incremental EMA
**should** match a full-history recompute *exactly*
(up to floating-point noise) *if*:

* You use the same alpha (2/(p+1)),
* You use the same price series in the same order, and
* You start from the same initial condition (first EMA).

In the real world, drift shows up because:

1. **Different seeding/initialization.**

   * Full-history version might:

     + seed with the first close, or
     + use an SMA over the first p bars.
   * Incremental version might:

     + seed from a DB row that was itself rounded or computed
       differently,
     + or accidentally treat a later EMA as if it were the
       initial.
2. **Rounding + persistence.**

   * If you store EMAs rounded to, say, 6 decimals in Postgres, but
     full-history computation uses higher precision in Python, then:

     + Every incremental step uses slightly rounded input,
     + Over thousands of bars, those tiny differences
       accumulate.
3. **Schema / logic evolution.**

   * You may change how you handle:

     + TF resampling boundaries,
     + How d1/d2/d1\_roll/d2\_roll are defined,
     + What constitutes a canonical close,
   * And some older rows in the DB may still reflect the old rule
     while new incremental steps use the new rule.
4. **Partial/failed runs.**

   * If an incremental job failed halfway and was rerun, you
     might:

     + Double-apply some days in the logic (even if DB conflict stops
       duplicate rows), or
     + Miss a bar, depending on how you select ranges.

For **multi-TF**, small conceptual mismatches can create
bigger drift, because:

* The rolling series depends on canonical EMA values and TF
  boundaries.
* A tiny change in which day counts as “close of bar” or in the
  seed for the bar can ripple across months of preview EMAs.

**How periodic full recomputes help**

Think of EMAs as **derived artifacts**, not ground
truth. Ground truth is:

* cmc\_price\_histories7 (prices),
* plus config (periods, TFs, alpha definition).

A robust pattern:

1. **Daily (or per-ingest) job:**

   * Use incremental logic (Option A or B) to append EMAs for new
     bars.
   * Only touch new timestamps:

     + update\_existing=False (or equivalent “no overwrite”).
2. **Periodic “reconciliation” job, every ≤3 months (or more
   frequently if cheap):**

   * Run a full-history recompute:

     + write\_daily\_emas.py → recompute all daily EMAs from day 1 for
       each id.
     + write\_multi\_tf\_emas.py → recompute all multi-TF EMAs.
   * Use update\_existing=True (or a DELETE + INSERT strategy) so the
     recompute:

     + corrects any drift,
     + normalizes all history to the latest logic.
3. **Optionally: recompute only recent history.**

   * If performance is a concern, you can:

     + Recompute last N years (or last K TF bars) fully and overwrite
       that window.
     + For older history, drift is usually less operationally
       important.

**Why this works well in practice**

* **Incremental gives you daily efficiency.**  
  You’re not recomputing 10+ years of data every time you ingest one new
  day.
* **Periodic full refresh gives you correctness over the long
  run.**  
  Even if:

  + you change logic slightly,
  + rounding in DB accumulates,
  + or a subtle bug lurks in the incremental path,

the next full recompute “snaps” EMAs back to the canonical values
that result from:

* current logic,
* full price history,
* pure in-memory calculation with maximum precision.

* **You can monitor drift.**  
  For example, once in a while:

  + Take one id/tf/period,
  + Recompute full-history in memory (without writing),
  + Compare vs DB EMA for some recent window,
  + Track max absolute diff. If it’s larger than a tolerance, trigger
    a full recompute sooner.

**How this maps back to your code / scripts**

For your specific stack:

* **Incremental layer:**

  + upsert\_new\_emas\_canUpdate.py / refresh\_cmc\_emas.py
  + We’d adjust to:

    - Read seeds from cmc\_ema\_daily and cmc\_ema\_multi\_tf,
    - Pull only new prices,
    - Use Option A or B to compute a tail,
    - Write with update\_existing=False.
* **Reconciliation layer:**

  + write\_daily\_emas.py:

    - Rebuild *all* tf='1D' EMAs for all ids,
      update\_existing=True.
  + write\_multi\_tf\_emas.py:

    - Rebuild *all* multi-TF EMAs,
      update\_existing=True.

Run those “full” scripts:

* On any schema/logic change to EMA computation, and
* On a schedule (e.g., quarterly, or even monthly if runtime is
  acceptable).

If you want, next step we can pick **one path** (A or B)
and sketch:

* Exact DB queries for “seed state” (for daily and multi-TF),
  and
* A concrete signature for an incremental builder, plus
* A simple drift-checking query/utility to compare full vs
  incremental over a sample window.
