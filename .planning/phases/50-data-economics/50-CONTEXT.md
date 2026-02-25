# Phase 50: Data Economics - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the build-vs-buy decision for data infrastructure. Audit current costs (all categories including developer time), compare against cloud data lake and managed platform alternatives, project costs at 2x/5x scale, and define a quantitative trigger for when migration becomes justified. Also evaluate alternative data vendors alongside infrastructure alternatives. This is Research Track #5 from the Vision Draft.

</domain>

<decisions>
## Implementation Decisions

### Cost audit scope
- **Total cost of ownership**: Include API fees, DB storage/hosting, compute costs, network, AND developer time maintaining pipelines
- **Per-asset granularity**: Break down costs attributed to each asset (BTC, ETH) and each table family; shows marginal cost of adding an asset
- **Developer time estimation**: Claude's discretion on method — use GSD execution times from STATE.md as proxy, or rough monthly estimates, whichever is more practical given available data
- **Free tier dependencies**: Researcher should investigate actual tier/pricing for CoinMarketCap API and exchange APIs (Coinbase, Kraken); document current tier, rate limits, and what paid tiers cost

### Architecture alternatives
- **Three-way comparison**: Current model (vendor API + local PostgreSQL) vs DIY cloud data lake (S3/GCS + Parquet + query engine) vs managed platform (Snowflake/Databricks or similar)
- **Include migration LOE**: Each alternative includes a rough level-of-effort estimate (weeks/months) for migration; helps weigh switching cost against steady-state savings
- **Managed platform selection**: Claude's discretion on which managed platform(s) are most relevant to a crypto quant data use case
- **Data vendor comparison included**: Also compare alternative data vendors (CoinGecko, Kaiko, CryptoCompare, exchange native APIs) alongside infrastructure alternatives; not just how we store data but where we source it

### Scale projection assumptions
- **2x scale = more assets + equities**: Expanding beyond BTC/ETH crypto into equities/ETFs; different data sources, different market hours
- **5x scale = breadth AND depth**: More assets across asset classes AND higher frequency data (hourly or minute bars); the full scaling challenge
- **Timeline: 6 months and 18 months**: 2x within 6 months, 5x within 18 months (more aggressive than vision document's Year 1-3)
- **Include DB performance analysis**: Project row counts, storage size, and expected query latency at 2x/5x; identify where PostgreSQL hits limits

### Output format and decision criteria
- **Dual deliverable**: Full analysis report in `reports/data-economics/` + concise ADR (Architecture Decision Record) in `docs/architecture/`
- **Decision matrix trigger**: Multi-factor matrix weighing cost, complexity, asset count, frequency; weighted score determines when data lake investment becomes justified
- **Recommendation with dissent**: Report concludes with a primary recommendation AND documented arguments for the alternative path; shows both sides, picks one
- **Review mechanism**: Claude's discretion — either fixed calendar review or trigger-based re-evaluation, whichever is more practical

### Claude's Discretion
- Developer time estimation methodology (logged hours vs rough monthly estimate)
- Which specific managed platforms to include in comparison (Snowflake vs Databricks vs others)
- Review mechanism type (calendar-based vs trigger-based checkpoint)
- Level of detail on vendor API feature comparison
- Performance benchmark methodology for PostgreSQL scaling projections

</decisions>

<specifics>
## Specific Ideas

- Per-asset cost attribution is important — need to understand marginal cost of adding the next asset
- Equities expansion is on the 6-month horizon, so the comparison must account for multi-asset-class data sourcing (not just crypto vendors)
- Higher frequency data (minute bars) at 5x scale means dramatic storage growth — this should be a prominent factor in the comparison
- The trigger should be a decision matrix, not a single threshold — multiple factors can independently justify the switch

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 50-data-economics*
*Context gathered: 2026-02-25*
