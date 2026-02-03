---
title: "CoreComponents"
author: "Adam Safi"
created: 2025-11-08T17:38:00+00:00
modified: 2025-11-08T17:39:00+00:00
original_path: "C:\Users\asafi\Documents\ProjectTT\Foundational\CoreComponents.docx"
original_size_bytes: 18383
---
**Core Components (and what they do)**

1. **Capital Policy Engine**

   * Encodes allocation rules (strategic bands, ERC/HRP/optimizer,
     constraints).
   * Produces target weights; triggers rebalances.
2. **Firmwide Risk Engine**

   * Aggregates risk across Pools: gross/net, factor/venue/asset
     exposure, VaR/ES, DD.
   * Enforces **global kill gates** (e.g., firm DD hard
     stop, venue bans).
3. **Treasury & Collateral Manager**

   * Cash routing between accounts/venues; margin buffers for perps;
     settlement calendars.
   * Optimizes idle cash (sweep rules) within risk
     constraints.
4. **Governance & Change Control**

   * Approvals for Pool creation/retirement, parameter band changes,
     overrides.
   * Audit logs, roles/permissions, incident workflows.
5. **Performance & Attribution Layer**

   * Daily/weekly/monthly P&L, vol, DD; **Pool and Sleeve
     attribution**; fees/slippage audit.
   * Tracks live vs model drift at Pool and firm levels.
6. **Compliance & Limits**

   * KYC/ToS venue checks; restricted lists; leverage/position caps;
     regional rules.
7. **Data & Reference Catalog**

   * Canonical sources for prices, fees, funding, calendars, lot
     sizes, trading hours.
   * Versioning and SLAs for downstream Pools.
8. **Monitoring & Alerting**

   * Health of allocators, reconciliations, cash breaks, limit
     breaches.
   * “Stoplight” status (Green/Yellow/Red) for firm and each
     Pool.
9. **Reporting & Communications**

   * Firm one-pager, risk dashboard, allocation memos, incident
     reports.
   * (Later) investor-grade reports if external capital.

**Who owns what**

**Program (firm-top)**

* **Capital Policy Engine** → global allocation across
  pools (not per sleeve).
* **Firmwide Risk Engine** → aggregates risk from all
  pools/sleeves; enforces *firm* kill gates.
* **Treasury & Collateral** → one function for
  cash/margin across venues and pools.
* **Governance & Change Control** → single
  ruleset; roles/approvals apply to all.
* **Compliance & Limits** → master restricted
  lists, leverage ceilings, venue rules.
* **Data/Reference Catalog** → canonical
  prices/fees/funding calendars for everyone.
* **Monitoring & Alerting** → single system with
  drill-downs to pools/sleeves.
* **Performance & Reporting** → firm one-pager;
  pool and sleeve roll-ups underneath.

**Pool (mandate level)**

* **Risk policy specialization** (DD/vol targets,
  leverage caps) derived from Program.
* **Allocation to sleeves** (e.g., ERC/HRP within the
  pool).
* **Pool dashboards** (PnL, vol, DD, sleeve
  attribution).
* **Pool kill switch** (stricter than firm where
  needed).

**Sleeve (strategy bucket inside a pool)**

* **Strategy logic & params** (signals,
  entry/exit).
* **Sizing & stops** (ATR/vol targeting, per-trade
  loss caps).
* **Eligible instruments/venues** (a subset of
  Program-approved).
* **Local monitors** (live/backtest drift, latency,
  hit rate).
* **Incident hooks** (bubble up to
  pool/program).

**Mental model**

* **Shared services at the top; configuration and limits
  specialize as you go down.**
* Program sets **global rules** → Pools set
  **mandates** → Sleeves implement **tactics**
  within those mandates.

**Example of inheritance/overrides**

* Program: “Firm max DD 25%, no single venue >40%, no leverage
  >1.5×.”
* Core Pool: “Pool max DD 20%, target vol 20%, perps allowed ≤30%
  exposure.”
* Trend Sleeve (in Core): “Max sleeve DD 12%, BTC/ETH only, ATR
  stop 2.5×, vol-target to 10% sleeve vol.”
* If the sleeve breaches drift/DD → sleeve halts; if pool DD
  breaches → pool halts; if firm gate breaches → everything
  halts.

**For V1 (practical)**

* Implement **Program services once** (risk,
  monitoring, reporting, data).
* Give each pool/sleeve a **namespace/config**
  in those services (e.g.,
  program/core\_pool/trend\_sleeve).
* Start with one pool and 1–2 sleeves; add more by adding
  configs, **not** new services.
