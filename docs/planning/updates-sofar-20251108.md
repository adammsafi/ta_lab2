---
title: "updates_soFar_20251108 "
author: "Adam Safi"
created: 2025-12-28T21:14:00+00:00
modified: 2026-01-07T11:50:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Plans&Status\updates_soFar_20251108 .docx"
original_size_bytes: 26048
---
**Project Evolution Summary (Updated)**

This document updates *soFar\_20251108* to reflect the current
state of the project after the SQL re-organization, DB tooling
hardening, and pipeline/CLI maturation.

**Timeline — Genesis to Present**

This timeline captures the *actual sequence of development*,
highlighting inflection points where the project’s direction or
architectural assumptions materially changed.

**Genesis — Exploratory Research Phase**

**State**: CSV files, notebooks, and ad-hoc Python
scripts

* Initial BTC price analysis using flat files
* Rapid experimentation with returns, volatility, EMAs, regimes,
  and visualizations
* Logic lived directly in notebooks and standalone scripts

**Key Insight Gained**:

* EMA slopes, regime transitions, and multi-timeframe context
  mattered more than single indicators

**Limitation Exposed**:

* Growing complexity made reuse, correctness, and repeatability
  fragile

**Transition 1 — From Scripts to a Package (ta\_lab →
ta\_lab2)**

**State**: Structured Python package with modules

* Core analytics refactored into importable modules
* Clear separation between features, transformations, and
  visualization
* Backward-compatibility shims added to preserve older
  workflows

**Inflection Point**:

* Decision to treat analytics code as a *product*, not an
  experiment

**Transition 2 — Persistence & Pipelines (DB
Introduction)**

**State**: Database-backed analytics

* Postgres introduced as the source of truth
* Early ingestion pipelines replace CSV-based workflows
* Incremental refresh logic and auditability become design
  goals

**Inflection Point**:

* Data is no longer disposable; historical correctness
  matters

**Transition 3 — Dimensional Modeling (Time Becomes
First-Class)**

**State**: Explicit time modeling emerges

* Realization that implicit timeframe logic does not scale
* Divergence between tf-day logic and calendar-aligned logic
  becomes visible
* Multiple EMA systems coexist, revealing architectural
  debt

**Inflection Point**:

* Time semantics identified as *foundational*, not a helper
  utility

**Transition 4 — SQL Governance & Schema
Discipline**

**State**: SQL treated as first-class code

* Canonical /sql directory structure established
* All legacy root-level SQL files migrated and categorized
* Deterministic categorization methodology documented and
  enforced

**Inflection Point**:

* Schema, checks, metrics, and migrations become explicitly
  governed assets

**Transition 5 — Safe DB Tooling &
Observability**

**State**: Production-safe database inspection

* Read-only DB tooling with hard guardrails
* Snapshotting, diffing, and integrity checks implemented
* CLI access standardized for safe introspection

**Inflection Point**:

* Database state becomes observable and auditable by
  default

**Present — Time-Aware Refactor Phase**

**State**: Foundations complete, core refactor
underway

* SQL governance and DB tooling considered complete
* Analytical layer entering unification around dim\_timeframe and
  dim\_sessions
* EMA systems slated for consolidation into a single, time-aware
  model

**Current Focus**:

* Correctness over expansion
* Unification before feature growth
* Ensuring all downstream analytics reference formal time
  dimensions

**Executive Summary**

The project has progressed from exploratory, file‑based analysis to a
structured, database‑backed analytics platform with disciplined SQL
taxonomy, read‑only DB tooling, and a maturing Python package (ta\_lab2).
The focus has shifted decisively from experimentation to
**correctness, reproducibility, and long‑term
maintainability**.

Key outcomes to date:

* Canonical SQL taxonomy established and enforced
* Read‑only Postgres inspection and snapshot tooling
  completed
* Multi‑timeframe EMA infrastructure aligned with TradingView
  semantics
* Clear separation between ingestion, schema, checks, metrics, and
  migrations

**Phase 1 — Exploratory Analysis (Historical)**

**State**

* CSV‑based BTC OHLCV
* Ad‑hoc scripts and notebooks

**Value Gained**

* Rapid ideation (returns, EMAs, regimes)
* Visual intuition

**Limitations Identified**

* No persistence guarantees
* Duplicated logic
* Fragile workflows

This phase is now *complete* and intentionally left
behind.

**Phase 2 — Package Formation (ta\_lab2)**

**State**

* Modular Python package
* Feature‑centric layout (returns, vol, EMA, regimes)
* Backward‑compatibility shims

**Key Improvements**

* Stable import surfaces
* Testable components
* Versioned releases

**Current Status**

* Package structure stable
* CLI entrypoints defined
* Public APIs converging

**Phase 3 — Database‑First Architecture**

**State**

* Postgres as source of truth
* Dimension tables (dim\_timeframe, dim\_sessions)
* Canonical bar logic (calendar vs bar‑space)

**Critical Decisions**

* Insert‑only facts + stats tables
* Explicit state/watermark tracking
* No silent mutation

**Outcome**

* Deterministic analytics
* Auditable history

**Phase 4 — SQL Taxonomy & Governance
(Completed)**

A major milestone has now been **fully completed**: SQL
is treated as first-class, governed code.

**What Was Planned**

* Formal SQL categorization
* Clear separation between validation, metrics, schema, and
  migrations
* Elimination of ad-hoc root-level SQL

**What Is Now Implemented**

* Canonical /sql directory with enforced taxonomy
* Deterministic categorization methodology codified in
  sql\_folder\_structure.md
* All legacy standalone SQL files migrated into correct
  subfolders
* Explicit invariants (checks vs metrics, DDL vs migration, dev
  quarantine)

**Final SQL Structure (Authoritative)**

sql/

├── checks/ # Data integrity & validation

├── ddl/ # Tables, indexes, constraints

├── dev/ # Ad-hoc / exploratory SQL

├── dim/ # Dimension seeds & maintenance

├── features/ # Feature engineering logic

├── gates/ # Pipeline guardrails

├── lookups/ # Reference & mapping tables

├── metrics/ # Quantitative health & comparison metrics

├── migration/ # Ordered schema/data changes

├── qa/ # Manual audit & QA queries

├── snapshots/ # Point-in-time snapshots & diffs

├── templates/ # Reusable SQL skeletons

├── views/ # Stable views & materialized views

└── sql\_folder\_structure.md

This phase is **done** and now acts as a constraint on
all future work.

**Phase 5 — DB Tooling & CLI (Completed)**

This phase has moved from active development to **stable
foundation**.

**What Was Planned**

* Safe database inspection
* Snapshotting and schema diffs
* CLI access without mutation risk

**What Is Now Implemented**

* Read-only Postgres DB tool with hard guardrails
* Keyword and multi-statement blocking
* Statement and idle transaction timeouts
* Row limiting and safe aggregation
* Snapshot generation (JSON + Markdown)
* Snapshot diffing and integrity checks
* Fully integrated CLI commands (ta-lab2 db ...)

**Outcome**

* Database state is inspectable, diffable, and auditable
* Schema drift is visible instead of silent
* Tooling is safe enough to use against production data

This phase is **complete** and should only receive
incremental polish.

**Analytical Infrastructure (In Progress, Time-Aware
Refactor)**

The analytical layer is mid-transition from feature-first logic to a
**time-dimension–driven architecture**.

**What Has Been Completed**

* Multi-timeframe EMA systems implemented
* Canonical vs preview row semantics established
* Calendar-aligned and anchor-aligned EMA variants exist
* Extensive stats and QA coverage for EMA tables

**What Changed the Plan**

* The formal time model discussion revealed architectural gaps:

  + Implicit timeframe semantics
  + Split EMA systems (tf-day vs calendar)
  + Missing session-awareness

**Current Direction (Locked-In)**

* dim\_timeframe becomes the authoritative source of truth
* dim\_sessions introduced for session and DST awareness
* EMA systems will be unified into a single, time-aware
  table
* All downstream features (returns, vol, TA, signals) must
  reference time dimensions

This phase is **actively being refactored** and gates
all downstream analytics work.

**Operating Principles (Locked‑In)**

1. **Data correctness beats speed**
2. **Everything auditable** (tables, stats,
   snapshots)
3. **Explicit > implicit** (no magic
   defaults)
4. **SQL is code** (reviewed, categorized,
   versioned)
5. **Bounded mutability** (only migrations change
   facts)

**What’s Next (Near‑Term)**

**Technical**

* Expand stats coverage to returns & volatility tables
* Formalize bar‑space EMA variants
* Add lightweight orchestration (cron/systemd)

**Documentation**

* Promote sql\_folder\_structure.md → README.md
* Add DB runbooks (restore, rebuild, verify)

**Analytics**

* Signal registry
* Backtest result tables
* Regime transition analytics

**Bottom Line**

The project has crossed the line from *personal research* to a
**disciplined analytics platform**. The foundations
(schema, SQL taxonomy, tooling, and package structure) are now strong
enough to support rapid feature work without accumulating hidden
debt.

This document supersedes *soFar\_20251108* and should be
treated as the new reference point going forward.
