---
phase: 15-economic-data-strategy
created: 2026-02-03
status: ready-for-planning
areas_discussed:
  - Integration decision criteria
  - Archive approach
  - Memory tracking strategy
  - Future integration path
---

# Phase 15: Economic Data Strategy - Implementation Context

**Phase Goal:** Archive fredtools2/fedtools2, extract valuable utilities, prepare for future economic data integration

**Discussed:** 2026-02-03

## Integration Decision Criteria

**Archive vs Integrate Decision Framework:**

Decision factors (in order of priority):
1. **Future value for quant work** - Does this support trading decisions?
2. **Code quality and maintenance burden** - Is it worth maintaining?
3. **Ecosystem alternatives** - Are there better modern options?

**Handling low quality code with unique functionality:**
- **Extract just the unique parts** - Rewrite cleanly into ta_lab2.utils.economic, archive the rest
- This applies to fredtools2/fedtools2: archive packages, extract valuable logic

**Economic data priorities:**
Both are important for trading context:
- **Fed policy data** (monetary policy decisions, rates)
- **FRED economic indicators** (CPI, employment, yields, etc.)

**Decision:** fredtools2 (167 lines) and fedtools2 (659 lines) should be **archived** (not integrated) based on:
- Zero usage in ta_lab2 codebase
- Better alternatives exist (fredapi, fedfred)
- Unique functionality will be extracted to utils.economic

---

## Archive Approach

**Documentation depth:**
- **Comprehensive (+ alternatives guide)**
- Manifest.json + README with restoration instructions + ALTERNATIVES.md documenting modern replacements
- Helps future developers understand context and migrate to better tools

**Restoration strategy:**
- **Quick restore (preserve in .archive/)**
- Keep source code in .archive/external-packages/ for easy restoration
- Enables recovery if assumptions were wrong or extraction missed something

**ALTERNATIVES.md content priorities:**
Include all four dimensions:
1. **Feature mapping** - Map each fredtools2/fedtools2 feature to modern equivalent
2. **API comparison** - Side-by-side code examples (old vs new)
3. **Migration effort estimate** - Rough time estimates for different use cases
4. **Ecosystem maturity notes** - Which alternatives are battle-tested, maintenance status

**Pre-archive verification:**
- **Trust research findings** - No additional audit needed
- Research already confirmed zero usage in ta_lab2

**Provenance tracking:**
- **Full provenance chain** - Track original source + how it entered ta_lab2 + any modifications
- Maximum traceability for compliance and context

**File tracking granularity:**
- **Hybrid (package + key files)** - Package-level entry + individual entries for important files
- Enables selective restoration of specific algorithms

**Dependency handling:**
- **Full dependency snapshot** - Capture complete dependency tree (pip freeze style)
- Maximum reproducibility if restoration ever needed

**Extraction strategy:**
- **Extract to ta_lab2.utils.economic** - Create new utils module with cleaned-up versions of valuable functions
- Archive the original packages after extraction
- Aligns with "extract unique parts" decision from Integration Criteria

---

## Memory Tracking Strategy

**Memory granularity:**
Combine two approaches:
1. **Full operation tracking** - Track archival, extraction, manifest creation, alternatives documentation
2. **Semantic relationship focus** - Track 'replaced_by' relationships for queryability

This enables both complete audit trail AND meaningful "what should I use instead?" queries.

**Extracted utilities memory:**
- **Dual attribution**
  - `extracted_from` metadata (provenance: where it came from)
  - `implements` metadata (purpose: what it does)
- Full context for future queries

**Archive rationale tracking:**
- **Decision + alternatives** - Detailed reasoning PLUS links to recommended replacements
- Makes memory actionable: "why archived" + "use this instead"

**ALTERNATIVES.md memory structure:**
- **Full alternatives graph** - Semantic network showing old_package → feature → new_package
- Enables complex queries like "all alternatives to fedtools2" or "how to get FRED series data"

**Example memory relationships:**
```
fredtools2 --[archived_for]--> "zero usage, better alternatives exist"
fredtools2 --[replaced_by]--> fredapi
fredtools2.get_series() --[equivalent_to]--> fredapi.get_series()
ta_lab2.utils.economic.fetch_fred --[extracted_from]--> fredtools2
ta_lab2.utils.economic.fetch_fed --[extracted_from]--> fedtools2
```

---

## Future Integration Path

**Groundwork preparation:**
- **Create integration skeleton + add dependencies** (option 4: both)
  - Create `ta_lab2.integrations.economic` stub module
  - Add fredapi/fedfred as optional dependencies in pyproject.toml

**Skeleton module contents:**
Include all four components:
1. **Base classes/protocols** - Abstract interfaces for economic data providers
2. **Adapter pattern stub** - Stub adapters for fredapi/fedfred conforming to ta_lab2 patterns
3. **Configuration structure** - Config schema for API keys, endpoints, rate limits
4. **Usage examples in docstrings** - Self-documenting vision of intended usage

**Optional dependencies structure:**
- **Flexible + combined** (option 4: maximum flexibility)
  - Individual extras: `[fred]`, `[fed]`
  - Combined extra: `[economic]` installs both
  - Enables `pip install ta_lab2[fred]` or `pip install ta_lab2[economic]`

**Skeleton functionality:**
- **Passthrough to fredapi** - FRED provider actually works by wrapping fredapi
- Provides immediate utility and demonstrates pattern for other providers
- Fed provider remains stub (NotImplementedError) until future phase

**Authentication approach:**
- **Config file support** (option 2: economic_data.env)
- Follows ta_lab2 pattern (db_config.env, openai_config.env already exist)
- File format: `economic_data.env` with FRED_API_KEY, FED_API_KEY, etc.

**Performance features:**
- **Rate limit + cache layer** (production-ready from start)
  - Rate limiter: max N requests per minute (prevent API abuse)
  - TTL cache: avoid repeated queries for same data
  - Both features working, not stubs

**Pipeline integration:**
- **Multiple integration points** (maximum flexibility)
  1. Standalone use - Import and use directly
  2. Pipeline plugins - Conform to existing pipeline interfaces
  3. Feature factory integration - Feed into feature engineering pipeline
- Support all three patterns from day one

**FRED data priorities:**
Include all four categories in working fredapi passthrough:
1. **Fed policy rates** - Federal funds rate, discount rate
2. **Treasury yields** - 10Y, 2Y, yield curve data
3. **Inflation indicators** - CPI, PCE, core inflation
4. **Employment data** - Unemployment rate, payrolls

**Data quality framework:**
- **Comprehensive quality framework** (production-grade)
  - Validation (nulls, data types, impossible values)
  - Statistical checks (outliers, range validation based on historical norms)
  - Logging and quality metrics
  - Alerts for suspicious data

**Frequency handling:**
- **Hybrid (default daily + API)** - Best of both worlds
  - Default to daily frequency with forward-fill (simplifies downstream)
  - Support `freq` parameter for those who want different frequencies
  - Automatic resampling based on user request

**Reliability features:**
- **Smart retry + circuit breaker** (production-grade resilience)
  - Exponential backoff for failed requests (1s, 2s, 4s)
  - Circuit breaker to stop retrying if service is down
  - Prevents cascade failures

**Migration support:**
- **All three approaches** (comprehensive)
  1. README migration guide - "If you used fredtools2, now use..."
  2. Deprecation warnings in code - If old patterns detected, point to new approach
  3. Interactive migration tool - Script that scans code and suggests replacements

---

## Key Files Created in This Phase

Based on decisions above, this phase will create:

1. **Archive artifacts:**
   - `.archive/external-packages/2026-02-03/fredtools2/` (source code)
   - `.archive/external-packages/2026-02-03/fedtools2/` (source code)
   - `.archive/external-packages/manifest.json` (hybrid tracking: package + key files)
   - `.archive/external-packages/README.md` (restoration guide)
   - `.archive/external-packages/ALTERNATIVES.md` (comprehensive guide with all 4 priorities)
   - `.archive/external-packages/dependencies_snapshot.txt` (pip freeze output)

2. **Extracted utilities:**
   - `src/ta_lab2/utils/economic/` (new module)
   - Functions extracted from fredtools2/fedtools2 with clean rewrites

3. **Future integration skeleton:**
   - `src/ta_lab2/integrations/economic/` (new module with working fredapi passthrough)
   - `pyproject.toml` (updated with [fred], [fed], [economic] extras)
   - `economic_data.env.example` (template for API keys)

4. **Documentation:**
   - Migration guide in README
   - Deprecation warnings in code
   - Interactive migration tool script

5. **Memory updates:**
   - Archive relationships (fredtools2/fedtools2 archived with rationale + alternatives)
   - Extraction relationships (utils.economic functions extracted_from packages)
   - Alternatives graph (old → new mappings for queryability)

---

## Implementation Notes for Planner

**Phase boundaries:**
- This phase is **cleanup + preparation**, not full integration
- Archive legacy, extract valuable, prepare skeleton
- Actual economic data integration (full Fed provider, production workflows) is future work

**Quality gates:**
- Working fredapi passthrough must pass smoke tests
- ALTERNATIVES.md must cover all 4 priorities (feature mapping, API comparison, effort estimates, ecosystem maturity)
- Memory system must support "what replaced fredtools2?" queries
- Migration tool must successfully detect old package imports

**Dependencies:**
- fredapi (for working FRED integration)
- python-dotenv (for economic_data.env loading)
- Standard library for rate limiting, caching, circuit breaker

**Success criteria:**
- [ ] fredtools2 and fedtools2 archived in .archive/external-packages/
- [ ] Manifest.json tracks packages with full provenance and dependency snapshot
- [ ] ALTERNATIVES.md created with comprehensive guidance
- [ ] ta_lab2.utils.economic created with extracted functions (dual attribution in memory)
- [ ] ta_lab2.integrations.economic created with working fredapi passthrough
- [ ] pyproject.toml updated with [fred], [fed], [economic] extras
- [ ] Rate limiting, caching, and circuit breaker working in skeleton
- [ ] Data quality framework validates FRED data
- [ ] Memory relationships track archive, extraction, and alternatives
- [ ] Migration guide, warnings, and tool created
- [ ] Phase memories created for queryability

---

**Ready for planning:** Yes - all implementation decisions captured

**Additional research needed:** No - existing research (15-RESEARCH.md) covers domain, context provides implementation decisions

---

_Created: 2026-02-03_
_Discussion areas: 4/4 completed_
_Next step: `/gsd:plan-phase 15` to create executable plans_
