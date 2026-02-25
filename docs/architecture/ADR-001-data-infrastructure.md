# ADR-001: Data Infrastructure Architecture Choice

**Date:** 2026-02-25
**Status:** Accepted

---

## Context and Problem Statement

ta_lab2 currently uses local PostgreSQL (46 GB across 171 tables, ~70.3M live rows) backed by manually downloaded CoinMarketCap JSON files and manual TradingView CSV exports. The project tracks 17 assets (8 crypto + 9 equities) with daily bars across 109 timeframes.

The project plans to expand from 17 assets to ~30 assets including additional equities within 6 months (2x scale), and to 50+ assets with hourly data within 18 months (5x scale).

We need to decide whether to:
1. Stay on local PostgreSQL with manual data loads (current model)
2. Migrate to a cloud data lake (S3/GCS + Parquet + DuckDB)
3. Adopt a managed time-series platform (TimescaleDB Cloud)

---

## Decision Drivers

* Current data API cost is **$0/month** — all data comes from file-based manual loads and free-tier APIs
* Developer time is **99%+** of current total cost of ownership ($200-800/month)
* PostgreSQL handles current scale (**70.3M rows, 46 GB**) comfortably — no performance issues observed
* **2x scale (~235M rows, ~80 GB)** is viable with basic table partitioning
* **5x scale (~2.8B rows, ~500-700 GB)** exceeds PostgreSQL's comfortable operating range
* CMC bulk download process is **fragile and undocumented** — single point of failure for all historical data
* Equities expansion requires **new data vendor integration** regardless of infrastructure choice
* TimescaleDB Cloud migration is **PostgreSQL-compatible** (1-2 weeks, no code rewrites)
* DIY data lake migration is **high effort** (4-8 weeks, dual-store complexity)

---

## Considered Options

* **Option A:** Stay on local PostgreSQL with file-based ingestion (current model — no migration)
* **Option B:** Migrate to DIY cloud data lake (S3/GCS + Parquet + DuckDB + PostgreSQL for ops)
* **Option C:** Migrate to managed time-series platform (TimescaleDB Cloud)

Snowflake and Databricks were evaluated and excluded — minimum viable tiers exceed current total TCO and are not cost-effective below 500 assets or 10 TB.

---

## Decision Outcome

**Chosen option: Option A (Stay on local PostgreSQL) through 2x scale.**

Rationale:

1. **Lowest TCO at current and 2x scale** — no infrastructure cost, no migration cost. Current TCO is $200-805/month (developer time only). At 2x, TCO rises to $529-1,362/month regardless of infrastructure choice; Option A adds no infrastructure premium.

2. **PostgreSQL handles 2x scale** — at ~235M rows and ~80 GB, PostgreSQL remains viable with table partitioning on the 5 largest table families. Partitioning is a 2-4 day effort, one-time.

3. **Low-cost migration option preserved** — when quantitative triggers are met, migrating to TimescaleDB Cloud (Option C) costs $400-800 one-time and takes 1-2 weeks. There is no lock-in penalty for staying on Option A now.

4. **Developer time dominates costs** — switching infrastructure does not reduce the dominant cost driver (maintenance hours). Migrating to the cloud does not make the pipeline cheaper to operate.

**When to re-evaluate:** When any trigger from the Decision Trigger Matrix is met (see [reports/data-economics/tco-model.md](../../reports/data-economics/tco-model.md), section "Decision Trigger Matrix"), or on calendar schedule every 6 months. Next scheduled review: 2026-08-25.

**If migration is triggered:** Migrate to Option C (TimescaleDB Cloud) first. It is PostgreSQL-compatible, requires no code rewrites, and takes 1-2 weeks. Option B (DIY Data Lake) is more cost-efficient at 5x scale but requires 4-8 weeks and dual-store operational complexity.

### Consequences

* **Good:** Zero migration cost — developer time stays focused on feature development, signal evaluation, and paper trading validation rather than infrastructure migration
* **Good:** Zero infrastructure cost — $0/month for storage and compute continues
* **Good:** Full local control — no vendor dependency for infrastructure; data remains on local machine
* **Bad:** Manual CMC bulk download remains fragile — process is undocumented, path-dependent, and may break without warning. **Mitigation:** Document the exact CMC download steps in a runbook; verify account tier; identify CoinGecko Analyst ($129/mo) as the ready fallback
* **Bad:** No cloud backup of database — local machine is a single point of failure. **Mitigation:** Schedule periodic `pg_dump` exports to an external drive or cloud storage bucket
* **Neutral:** Equities vendor decision (Alpaca vs Polygon.io) is independent of infrastructure choice — this ADR does not constrain that decision

---

## Dissenting View: Migrate to TimescaleDB Cloud Now

Arguments in favor of early migration to Option C:

**1. Reduce operational risk early**
The local machine is a single point of failure. A disk failure, Windows Update failure, or power outage loses all 46 GB of processed data with no automated backup. TimescaleDB Cloud provides automated backups, point-in-time recovery, and high availability. The value of data integrity is not captured in the monthly TCO calculation.

**2. Replace CMC file loads with CoinGecko API now**
Migrating to CoinGecko Analyst ($129/mo) alongside TimescaleDB Cloud produces a fully API-driven, automated daily pipeline. The operational risk of the current CMC manual process is rated CRITICAL in cost-audit.md. Eliminating it now prevents a future outage.

**3. Migration cost is low enough to absorb**
1-2 weeks of migration effort, PostgreSQL-compatible — the switching cost is low enough to "just do it" rather than accumulate operational debt that grows with each new table family added.

**4. Avoid manual partitioning work at 2x scale**
TimescaleDB hypertables handle time-series partitioning automatically. Manual PostgreSQL partitioning at 2x scale (~235M rows) is 2-4 days of developer time that could be entirely avoided by migrating to TimescaleDB now.

**5. Establish cloud infrastructure muscle early**
Building the cloud migration capability while stakes are low reduces risk when a migration is eventually forced under production pressure or time constraints.

**Counter-argument to the dissenting view:** The additional $50-150/month cloud hosting cost plus $129/month CoinGecko API represents a 16-65% increase in cash TCO for a project that currently costs $0 in infrastructure. The current model works. The triggers that justify migration have not been crossed. Developer time is better spent on signal evaluation and paper trading validation — the project's actual open problems.

---

## Links

* Full TCO analysis: [reports/data-economics/tco-model.md](../../reports/data-economics/tco-model.md) — three-way architecture comparison at current/2x/5x scale, PostgreSQL scaling analysis, weighted decision matrix
* Cost audit: [reports/data-economics/cost-audit.md](../../reports/data-economics/cost-audit.md) — measured DB size (46 GB), table breakdown, monthly TCO
* Vendor comparison: [reports/data-economics/vendor-comparison.md](../../reports/data-economics/vendor-comparison.md) — crypto + equities vendor matrix, tiered recommendations
* Phase report index: [reports/data-economics/README.md](../../reports/data-economics/README.md) — executive summary
