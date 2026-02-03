---
title: "new_12wk_plan_doc"
author: "Adam Safi"
created: 2025-11-26T21:33:00+00:00
modified: 2025-11-26T21:38:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Plans&Status\new_12wk_plan_doc.docx"
original_size_bytes: 26588
---
combine the two into a go forward 12 week plan and give me a few easy
wins to complete before now and 12/1

**ChatGPT said:**

Thought for 19s

Nice, this is a good moment to reset the clock and be
intentional.

I’ll give you:

1. **A handful of easy wins between now and
   12/1**
2. **A fresh 12-week plan** that merges the original
   12-week roadmap with the “weekly features” doc and what you actually got
   done (EMAs, stats, cal-aligned table, etc.).

---

**1️⃣ Easy wins before 12/1 (low effort, high morale
bump)**

Aim for 3–5 hours total over the next few days.

**✅ EW1 – Cutoff & trust ranges doc**

* **What to do**

  + Run 2–3 simple MAX(ts) and row-count queries for:

    - cmc\_price\_histories7
    - cmc\_ema\_daily
    - cmc\_ema\_multi\_tf
    - cmc\_ema\_multi\_tf\_cal
  + Create docs/cutoff\_dates.md with a tiny table:

| **table** | **last\_ts** | **trusted\_through** | **notes** |
| --- | --- | --- | --- |
| cmc\_price\_histories7 | 2025-11-24 … | 2025-11-24 | CMC daily close |
| cmc\_ema\_multi\_tf | 2025-11-24 … | 2025-11-24 | trading calendars |
| cmc\_ema\_multi\_tf\_cal | 2025-11-24 … | 2025-11-24 | calendar aligned |

* **Win:** You convert all the mental state you just
  used into one canonical reference.

---

**✅ EW2 – “Refresh EMAs” quickstart in README**

* **What to do**

  + Add a **short** section in README.md like:
  + # Refresh daily + multi-TF EMAs for core ids
  + python -m ta\_lab2.scripts.emas.refresh\_cmc\_emas --ids
    all
  + # Only multi-TF (trading-aligned)
  + python -m ta\_lab2.scripts.emas.refresh\_cmc\_ema\_multi\_tf\_only
    --ids all
  + # Only calendar-aligned multi-TF
  + python -m ta\_lab2.scripts.emas.refresh\_cmc\_ema\_multi\_tf\_cal\_only
    --ids all
* **Win:** Someone (future you) can run the full EMA
  stack without remembering script names.

---

**✅ EW3 – Stub the EMA refresh process doc**

* **What to do**

  + Create docs/ema\_refresh\_process.md with just:

    - Inputs required (tables, env vars, DB URL)
    - 3–5 bullet steps you *actually* just ran
    - A “TODO: add troubleshooting + flowchart later” line.
* **Win:** You don’t need the full glossy process doc
  yet, but you capture the skeleton while it’s fresh.

---

**✅ EW4 – Minimal GitHub hygiene**

* **What to do**

  + On GitHub:

    - Create **one** Project (e.g. “ta\_lab2 –
      2025Q1”).
    - Create ~6 issues that align with the 12-week plan below (one per
      “big week theme”).
  + Link one issue to your EMA incremental work and mark it
    done.
* **Win:** You get visible progress and a light
  structure without going down a PM rabbit hole.

---

**2️⃣ Go-forward 12-week plan**

Assume Week 1 = **Dec 1–7**.  
Theme: keep it realistic for “new job + evenings/weekends,” so ~8–10
focused hours/week.

I’ll break each week into **Code**,
**Ops/Infra**, and **Docs**, merging both
earlier plans and what’s already done.

---

**Week 1 (Dec 1–7) – Lock in EMA stack & state**

**Code**

* Finalize schemas and semantics for:

  + cmc\_ema\_daily
  + cmc\_ema\_multi\_tf
  + cmc\_ema\_multi\_tf\_cal
* Add 2–3 unit / integration tests that:

  + Verify row-count vs tf\_days around a known window for 1
    asset.
  + Assert roll/d1/d2 behave as expected for a long-period TF (like
    100D 10-period).

**Ops/Infra**

* Add a simple **SQL view** that joins price + EMAs,
  e.g. cmc\_price\_with\_emas.

**Docs**

* Flesh out docs/ema\_refresh\_process.md with:

  + When to use --start vs incremental
  + What the stats scripts are checking.

**Acceptance:** You can explain the EMA tables and
refresh process to someone in 2–3 minutes and prove it with one test run
+ stats.

---

**Week 2 (Dec 8–14) – Returns & volatility features
v1**

**Code**

* Create features/returns.py (or equivalent) and a
  cmc\_returns\_daily table:

  + Basic log/percent returns for 1D, 2D, 5D, 10D.
* Add a small cmc\_vol\_daily or embed simple realized vol in the
  same table.

**Ops/Infra**

* Add a script like scripts/returns/refresh\_cmc\_returns.py with the
  **same incremental pattern** as EMAs.

**Docs**

* Short docs/returns\_notes.md: formulas, lookback windows, and any
  data quirks.

**Acceptance:** You can query “BTC 1D and 5D returns vs
close price” for any date range with a single SQL.

---

**Week 3 (Dec 15–21) – Core TA indicators (RSI, MACD, BB,
ADX)**

**Code**

* Implement a cmc\_ta\_daily table with:

  + RSI (14)
  + MACD (fast/slow/signal)
  + Bollinger Bands (e.g. 20-period, 2σ)
  + ADX (14) or similar.
* Reuse your EMA engine for the EMA bits where possible.

**Ops/Infra**

* scripts/ta/refresh\_cmc\_ta\_daily.py with incremental update
  logic.

**Docs**

* Extend README with a “Daily Indicators” section explaining which
  indicators and default params exist.

**Acceptance:** One query returns close, ema\_20, rsi\_14,
macd, bb\_up, bb\_dn, adx for BTC for a month.

---

**Week 4 (Dec 22–28) – Unified daily feature
pipeline**

**Code**

* Combine EMAs, returns, and TA into a **single view**
  or materialized table:

  + e.g. cmc\_daily\_features over ts,id.
* Add a thin Python wrapper build\_daily\_features(ids, start,
  end=None) that orchestrates the underlying refreshes/views.

**Ops/Infra**

* One CLI entry (or script) that runs “all daily features” for a
  given id set and window.

**Docs**

* A short “Architecture: daily features” diagram (markdown text is
  fine).

**Acceptance:** A single CLI call (or function) produces
a feature-complete daily dataset suitable for backtests.

---

**Week 5 (Dec 29–Jan 4) – Scheduling & environment
sanity**

**Code**

* Add a **config file** (YAML or TOML) for:

  + default ids
  + default trusted-through dates
  + DB connection alias (prod/dev).

**Ops/Infra**

* Set up a basic scheduler on the VM (cron / Task Scheduler)
  that:

  + Runs price ingest (if separate) and
  + Runs EMA + daily feature refresh once per day.

**Docs**

* docs/scheduling.md describing when jobs run and where logs
  go.

**Acceptance:** EMAs and features update automatically
overnight without you touching anything on at least one environment.

---

**Week 6 (Jan 5–11) – Observability & sanity
checks**

**Code**

* Formalize your stats scripts into a small ta\_lab2.stats
  module:

  + row-count vs tf\_days
  + max gap checks
  + simple “no weird NaN/inf” checks.

**Ops/Infra**

* Make stats runnable as a daily/weekly job:

  + Write results to a cmc\_stats table + optionally email/print a
    simple report.

**Docs**

* docs/stats\_and\_quality\_checks.md listing each test, what it
  means, and how to interpret FAIL/WARN/PASS.

**Acceptance:** After a nightly job, you can quickly
answer, “Is the data healthy?” by checking one stats table.

---

**Week 7 (Jan 12–18) – First simple signals &
flips**

**Code**

* Implement a first-pass signal layer:

  + e.g., EMA crossovers, RSI overbought/oversold flags, or price vs
    band signals.
* Optionally revive your “flip segments” logic on top of
  EMAs/returns.

**Ops/Infra**

* A cmc\_signals\_daily table populated from daily features.

**Docs**

* docs/signals\_v1.md: what signals exist, their parameters, and a
  couple of example charts/queries.

**Acceptance:** You can run a query for “all dates where
BTC flipped from downtrend to uptrend” according to an EMA or signal
rule.

---

**Week 8 (Jan 19–25) – Backtest skeleton**

**Code**

* Stand up a minimal backtest runner, even if very simple:

  + Input: feature view + signal definition.
  + Output: trades, PnL, basic metrics (CAGR, max drawdown,
    Sharpe).

**Ops/Infra**

* Save backtest results to a table or to versioned CSVs in a
  backtests/ folder.

**Docs**

* docs/backtest\_v1.md describing assumptions (no slippage/fees at
  first, etc.).

**Acceptance:** You can run a toy strategy (like “long
when price > 100D EMA”) and see a performance summary.

---

**Week 9 (Jan 26–Feb 1) – Testing & CI**

**Code**

* Increase automated tests around:

  + EMA + multi-TF logic
  + daily feature calculations
* Introduce pytest configuration improvements, fixtures for DB,
  etc.

**Ops/Infra**

* Set up GitHub Actions (or other CI) to:

  + Run tests on push/PR
  + Optionally run formatting or linting.

**Docs**

* A short section in README: “How to run tests & CI.”

**Acceptance:** Every push runs tests automatically, and
failures are obvious.

---

**Week 10 (Feb 2–8) – Packaging & CLI polish**

**Code**

* Clean up CLI structure:

  + Move to ta\_lab2.cli.main if you haven’t fully yet.
  + Add subcommands like pipeline, refresh-emas,
    refresh-daily-features, run-backtest.
* Tighten pyproject.toml and ensure pip install -e . works cleanly
  on a fresh machine.

**Ops/Infra**

* Sanity-check install on a clean environment (e.g., new venv or a
  small cloud instance).

**Docs**

* Update README’s “Installation & CLI” sections.

**Acceptance:** On a brand-new machine you can: clone
repo → install → run a CLI command end-to-end without manual tweaks.

---

**Week 11 (Feb 9–15) – Documentation sprint**

**Code**

* Tiny refactors only; no big new features.

**Docs**

* Clean, cohesive documentation set:

  + Overview / architecture
  + Data model and tables
  + EMA + multi-TF
  + Daily features and signals
  + Backtest usage
* Maybe one or two Jupyter notebooks as usage examples.

**Ops/Infra**

* Make sure docs are versioned and easy to browse (even if just
  markdown in /docs).

**Acceptance:** You could hand the repo to a future
analyst version of you and they’d be able to onboard themselves from the
docs.

---

**Week 12 (Feb 16–22) – v0.3.x “internal release”**

**Code**

* Tag a version (e.g. v0.3.1 or v0.4.0) representing:

  + Stable DB schema
  + Working EMA + features + basic signals
  + Tests passing.

**Ops/Infra**

* Snapshot of the DB or at least schema + a handful of example
  export files.

**Docs**

* CHANGELOG summarizing the journey.
* Short “State of ta\_lab2” note for yourself (what’s next, what to
  revisit later).

**Acceptance:** You have a clearly tagged, reproducible
state of the project that you can build on in the next cycle.

---

If you like, next step we can pick **2–3 of those “easy
wins”**, write the exact SQL/markdown skeletons, and you can
knock them out in one sitting before 12/1.
