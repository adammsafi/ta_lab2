# Feature Landscape: v0.8.0 Polish & Hardening

**Domain:** Python quant/data platform hardening
**Researched:** 2026-02-22
**Scope:** 5 hardening areas on existing infrastructure

---

## Context: What Already Exists

This milestone hardens existing infrastructure, not builds new features. All 5 areas have partial
implementations already in place. Understanding what exists shapes what "table stakes" means here —
the bar is "what must be true of a mature platform in each area", measured against what already exists.

| Area | Already Built | Gap |
|------|--------------|-----|
| Stats/QA | 5 stats runners + 17 audit scripts + orchestrator | Runners not wired to refresh pipeline; no gate pattern |
| mypy | Listed as dev dep, no config, not in CI | Config file, CI job, per-module strategy |
| Documentation | mkdocs-material site, 2 mermaid diagrams, 2 runbooks | Stale version (v0.4.0 in mkdocs.yml vs v0.7.0 actual), no pipeline flow diagram, runbooks missing incident sections |
| Runbooks | DAILY_REFRESH.md + STATE_MANAGEMENT.md | No SLA section, no incident escalation, no on-call contact, no rollback procedures |
| Alembic | 16 raw SQL files in sql/migration/ (no framework) | No Alembic init, no version tracking, no stamp of current state |

---

## Area 1: Stats/QA Integration

### Table Stakes

Features a mature Python data platform always has in this area.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Stats runners emit non-zero exit codes on FAIL | Without this, failures are invisible to orchestration | Low | Currently runners log FAIL rows but exit 0 |
| Post-refresh QA gate (blocking) | Critical issues must stop downstream; stale data worse than no data | Medium | Add gate call after each refresh step in run_daily_refresh.py |
| Stats stored in DB with PASS/WARN/FAIL severity | Enables querying history, trending, dashboards | Low | Already implemented in price_bars_multi_tf_stats schema |
| Incremental stats (watermark pattern) | Full re-check on every refresh is too slow at scale | Medium | Already implemented in bars stats runner; pattern established |
| Global audit orchestrator with exit code | run_all_audits.py must return non-zero if any audit fails | Low | Orchestrator exists; exit code logic needs verification |
| Stats coverage for all major tables | All 4 table families (bars, EMA, returns, features) need coverage | Medium | Bars + features done; EMA and returns stats runners may be incomplete |

### Differentiators

Features beyond basics that mature quant platforms add.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| WARN-only gate (non-blocking) | Allows pipeline to continue while surfacing minor issues via Telegram | Low | Separate FAIL threshold vs WARN threshold at gate check |
| Stats trend view (PASS rate over time) | Shows data quality trajectory, detects slow degradation | Medium | SQL view over existing stats tables; no new infrastructure |
| Freshness SLA check in stats | Automated staleness check embedded in stats (not just runbook) | Low | Already done in bar stats (max_ts_lag_vs_price test) |
| Per-asset FAIL counts in summary | Pinpoint which assets are consistently problematic | Low | Aggregation query over existing stats tables |
| Stats runner wired into run_all_feature_refreshes | Feature refresh also has QA gate, not just bar/EMA | Medium | Mirror pattern from run_daily_refresh |

### Anti-Features

Things to deliberately NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Full stats recompute on every run | At 2.1M rows, this becomes multi-minute blocking step | Use existing incremental watermark pattern; gate only checks latest batch |
| Stats as a separate scheduled job | Defeats the purpose of gating — QA must run before downstream proceeds | Wire QA gate inline with refresh, not as cron afterthought |
| Blocking on WARN | WARN = tolerable anomaly; blocking on WARN kills operational velocity | Block only on FAIL; alert on WARN via Telegram |
| Custom assertion DSL | Reinventing Great Expectations in this codebase | Use existing PASS/WARN/FAIL SQL pattern already established |
| Replacing audit scripts with stats runners | Both serve different purposes: audits are ad-hoc exploratory, stats are incremental operational | Keep both; wire stats runners into pipeline, audits remain manual |

### Feature Dependencies

```
Stats runners (already exist)
  -> Gate check function reads latest stats for batch
  -> Gate called from run_daily_refresh after each major step
  -> Gate called from run_all_feature_refreshes after feature refresh

Telegram alerting (already exists)
  -> Gate sends WARN-level alert on WARN rows
  -> Gate raises exception / non-zero exit on FAIL rows
```

---

## Area 2: mypy Strict Adoption

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| mypy config in pyproject.toml | Without config, mypy behavior is inconsistent across devs | Low | [tool.mypy] section; currently absent |
| mypy in CI (non-blocking initially) | Prevents regression of typed modules; catch new errors | Low | Add mypy job to ci.yml with continue-on-error: true initially |
| check_untyped_defs = true (global) | Checks bodies of untyped functions; catches runtime bugs even without annotations | Low | Most important flag for partial codebases |
| Per-module overrides for legacy files | Global strict breaks everything; overrides let you ratchet gradually | Low | [mypy-ta_lab2.scripts.*] sections with ignore_errors = True |
| ignore_missing_imports for third-party stubs | vectorbt, sqlalchemy, pandas all have stubs; others don't — must configure | Low | Prevents noise from missing type stubs |
| Pinned mypy version in dev deps | mypy errors change between versions; unpinned = non-reproducible CI | Low | Already listed as mypy>=1.8; pin to exact version |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Strict mode on new-code modules (features/, time/) | Higher-value modules get immediate type safety | Medium | Enable disallow_untyped_defs = True per module selectively |
| type: ignore[code] policy (no bare ignores) | Forces precision; prevents ignoring unknown future errors | Low | Add ruff rule or mypy flag to warn on bare type: ignore |
| mypy CI job becomes blocking (future milestone) | Once error count < threshold, flip continue-on-error: false | Low | Set threshold; document the ratchet plan |
| Typed protocols for core abstractions | Signal generators, feature refreshers, stats runners have common shapes | High | Retroactively annotating scripts is low value; protocols for new code only |
| MonkeyType for auto-annotation of hot paths | Automated stub generation for highest-traffic legacy modules | High | Research tool; deferred to future milestone |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| --strict globally on day one | Will produce hundreds of errors on a codebase this size; CI unusable | Start with check_untyped_defs only; ratchet per module |
| Annotating sql/migration scripts and scripts/baseline | These are one-shot migration files; not worth annotating | Exclude from mypy via per-module ignore_errors = True |
| Ignoring mypy output entirely (current state) | mypy listed as dep but never run = false confidence | Must at minimum run and report; blocking comes later |
| Retrofitting type annotations to all 80+ .py files in one PR | Unreviewable PR; will introduce bugs | Annotate incrementally by module, highest-import modules first |
| Using pyright instead of mypy | Pyright is not in existing toolchain; switching adds complexity | Continue with mypy; it is already in pyproject.toml |

### Feature Dependencies

```
[tool.mypy] in pyproject.toml (new)
  -> Per-module overrides in same file
  -> CI job in ci.yml calls: mypy src/ta_lab2 --config-file pyproject.toml
  -> Pre-commit hook optional (adds latency; evaluate against <5s target)
```

### Module Priority for Annotation

Based on codebase structure, annotation priority order:

1. `ta_lab2/features/` — widely imported by scripts; high leverage
2. `ta_lab2/time/` — dim_timeframe.py is critical shared utility
3. `ta_lab2/scripts/bars/stats/` — new stats runner code; annotate as written
4. `ta_lab2/scripts/run_daily_refresh.py` — orchestrator; high visibility
5. Everything else — covered by check_untyped_defs passively

---

## Area 3: Documentation Freshness

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| mkdocs.yml version matches actual project version | mkdocs.yml says v0.4.0; pyproject.toml says v0.5.0; actual is v0.7.0 | Low | Single-line fix; represents systematic staleness |
| CHANGELOG.md exists and is current | Standard Python project expectation; documents what changed per version | Medium | File exists in nav but needs v0.5/0.6/0.7 entries |
| Pipeline flow diagram (Mermaid) | DAILY_REFRESH.md describes execution order in prose; diagram makes it scannable | Medium | bars -> EMAs -> regimes -> features flow; component boxes with arrows |
| mkdocstrings auto-generation for public APIs | Plugin installed but underutilized; public classes should have docstring-based API docs | Medium | Requires Google-style docstrings on key classes |
| Nav in mkdocs.yml reflects current docs/ structure | Current nav references files that may not exist or are stale | Low | Audit nav entries vs actual files |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Mike-based versioned docs (v0.8.0 alias) | latest always points to current; old versions archived | Medium | mike is already configured as provider in mkdocs.yml extra.version |
| Architecture decision records (ADRs) | Documents WHY key decisions were made; avoids re-litigating the past | Medium | Lightweight ADR format; one per major design decision |
| Automated CHANGELOG from release-please | .github/release-please-config.json exists; wire to auto-generate CHANGELOG entries | Medium | release-please already configured; may already be generating CHANGELOG |
| Per-phase pipeline diagram | Each refresh sub-pipeline (bars, EMAs, regimes, features) as separate diagram | Medium | More granular than single flow diagram |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Manually maintaining API reference docs | API docs go stale immediately on any code change | Use mkdocstrings auto-generation from docstrings |
| Documenting every internal private function | Creates noise and maintenance burden | Document public interfaces and entry points only |
| PDF export or multiple output formats | Adds complexity; mkdocs HTML is sufficient for this project | Keep single HTML target |
| Separate docs repo | Docs-as-code lives in same repo; keeps docs and code in sync | Keep docs/ in same repo |
| Requiring docs update before every commit | Too heavy for frequent data pipeline commits | Gate docs update on version bump / milestone completion |

### Feature Dependencies

```
mkdocs.yml version fix (prerequisite for all)
  -> Pipeline flow diagram (Mermaid in docs/operations/)
  -> CHANGELOG.md update with v0.5 through v0.7 entries
  -> Nav audit (verify all referenced files exist)
  -> mkdocstrings docstrings on public classes

release-please-config.json (existing)
  -> May already generate CHANGELOG; audit first before building
```

---

## Area 4: Operational Runbooks

### Table Stakes

Mature data pipeline runbooks always include these sections.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| SLA definition section | How fresh is acceptable? must be written down; ops makes judgment calls without it | Low | Define: bars < 48h stale; features < 72h; EMAs < 48h |
| Incident severity classification | Not all failures are equal; ops needs a triage framework | Low | P1: data corruption / P2: staleness > SLA / P3: partial failure |
| Escalation contacts / on-call section | Who to call for what; runbooks are useless during incident if this is missing | Low | Even if single-person team: define escalation path for self |
| Rollback procedure per component | How do I undo a bad refresh? must be explicit; STATE_MANAGEMENT.md hints at this | Medium | DELETE from state table + backfill pattern; per-component procedures |
| Recovery validation steps | After recovery, how do you verify the fix worked? | Low | Run relevant stats runner + audit script; check Telegram for alerts |
| Maintenance window definition | When is it safe to run schema migrations, full rebuilds? | Low | Define: daily refresh window (UTC time), migration window |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Symptom-first index | Ops searches by what they observe, not by component | Low | Seeing X? Go to section Y index at top of DAILY_REFRESH.md |
| Copy-paste SQL diagnostics | No one memorizes SQL during an incident; pre-written diagnostic queries | Low | STATE_MANAGEMENT.md has some; extend with common patterns |
| Alert code to runbook section mapping | Each Telegram alert code maps to a runbook section | Medium | OHLC_CORRUPTION -> see DAILY_REFRESH.md#ohlc-corruption |
| Known issue registry | Documents recurring issues with known root causes and mitigations | Medium | Prevents re-diagnosis of the same problems |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Single monolithic runbook | 400-line DAILY_REFRESH.md is already getting unwieldy | Keep operational guide (what to do daily) separate from incident guide (what to do when broken) |
| Runbook stored only in docs/ with no DB context | Ops needs to know what tables are affected | Include table names and SQL fragments inline |
| Runbook updated separately from code changes | Runbooks go stale this way | Document runbook update requirement in PR template |
| Over-specifying every edge case | Reduces usability; runbooks should be scannable not encyclopedic | Cover P1 and P2 scenarios; leave P3 to judgment |

### Feature Dependencies

```
Existing runbooks (DAILY_REFRESH.md, STATE_MANAGEMENT.md)
  -> Add SLA section to DAILY_REFRESH.md
  -> Add incident severity + escalation to DAILY_REFRESH.md
  -> Add rollback procedures (referencing STATE_MANAGEMENT.md patterns)
  -> Add recovery validation steps (referencing stats runners and audits)

Telegram alerting module (existing)
  -> Alert codes should map to runbook sections
  -> Severity levels (CRITICAL/ERROR/WARNING) map to incident severity (P1/P2/P3)
```

---

## Area 5: Alembic for Existing Projects

### Table Stakes

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Alembic initialized (alembic init) | Without this, migrations remain ad-hoc; impossible to track schema version | Low | Creates alembic/ dir, env.py, alembic.ini |
| Baseline stamp of current schema | Tells Alembic the current schema is the starting point; prevents it from regenerating all tables | Medium | alembic stamp head after creating initial migration |
| Initial migration from existing schema | One migration that represents current state; not the raw SQL files | Medium | Hand-write from existing DDL; do NOT use autogenerate as first step |
| alembic upgrade head in CI | Validates that migrations apply cleanly; catches drift before production | Medium | Add to validation.yml after postgres service setup |
| Connection configured from env var | alembic.ini uses environment variable; env.py reads TARGET_DB_URL | Low | Consistent with existing db_config.env pattern |

### Differentiators

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| include_name filter in env.py | Prevents Alembic from dropping tables it does not know about (system tables, manually-created stats tables) | Low | Critical safety measure for existing-schema onboarding |
| Autogenerate with SQLAlchemy metadata | Future schema changes auto-detected by comparing Python models to DB | High | Requires creating SQLAlchemy Table objects for all 24+ tables |
| Raw SQL support in migration scripts | Alembic supports op.execute(raw_sql) for complex DDL | Low | Existing sql/migration/*.sql files can be wrapped in op.execute() |
| Migration squash after baseline | Once all developers are on Alembic, squash 16 raw SQL files into one baseline revision | Medium | Deferred: do after Alembic is adopted by whole team |

### Anti-Features

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Autogenerate as first step without stamping | Without stamping current state, autogenerate will generate DROP statements for every existing table | Stamp first, then autogenerate for new changes only |
| Replacing all 16 raw SQL files with Alembic migrations immediately | Creates a massive PR that is hard to review; risks data loss if wrong | Create baseline stamp, keep existing files in sql/migration/, only NEW changes go through Alembic |
| Running migrations in run_daily_refresh.py | Schema migrations during data refresh creates dangerous coupling | Keep migrations separate, run manually or in dedicated CI job |
| Using autogenerate without reviewing output | Autogenerate is not perfect; table renames appear as drop+add | Always review autogenerated migration files before committing |
| Forcing ORM model creation for all tables | This project uses raw SQL heavily; creating 24 SQLAlchemy Table objects is high effort, low value | Use include_name filter with reflection for autogenerate filtering |

### Feature Dependencies

```
alembic init (new)
  -> env.py configured with TARGET_DB_URL
  -> alembic.ini configured
  -> include_name filter in env.py (safety for existing tables)

Baseline migration (new)
  -> Created from existing DDL (hand-written, not autogenerated)
  -> alembic stamp head applied to existing production DB
  -> All future migrations through Alembic only

CI integration (builds on validation.yml)
  -> Postgres service already exists in validation.yml
  -> Add alembic upgrade head step
  -> Gate: migrations must apply cleanly before tests run
```

---

## MVP Recommendation

For v0.8.0, prioritize in this order:

### Must Have (v0.8.0)

1. **Stats/QA gate** — Wire existing stats runners into run_daily_refresh.py; emit non-zero exit on FAIL. All infrastructure already exists; this is the last-mile connection.

2. **mypy baseline config** — Add [tool.mypy] to pyproject.toml with check_untyped_defs = true, per-module overrides for legacy files, and a non-blocking CI job. Zero runtime changes; pure tooling.

3. **Runbook hardening** — Add SLA section, severity classification, and escalation procedures to DAILY_REFRESH.md. Pure docs work; immediate operational value.

4. **Alembic baseline stamp** — Initialize Alembic, create baseline migration representing current schema, stamp the production database. Establishes the framework without changing any schema.

5. **Docs version fix** — Update mkdocs.yml to v0.8.0, add pipeline flow Mermaid diagram, update CHANGELOG.md. Low effort, high visibility signal of project health.

### Defer to Post-MVP

- **mypy strict adoption** (per-module ratchet): Time-intensive annotation work. Establish CI baseline first.
- **Alembic autogenerate** (ORM models): Requires creating SQLAlchemy models for 24+ tables. Separate milestone.
- **Mike versioned docs**: Operations overhead; valuable when there are external consumers of docs.
- **ADRs**: Valuable but not urgent; write them as new decisions are made, not retroactively.
- **Stats trend views**: SQL view work; deferred until stats runners have multi-week history.

---

## Sources

- mypy documentation — existing codebase adoption: [Using mypy with an existing codebase](https://mypy.readthedocs.io/en/stable/existing_code.html)
- Wolt Engineering — professional mypy configuration: [Professional-grade mypy configuration](https://careers.wolt.com/en/blog/tech/professional-grade-mypy-configuration)
- Alembic documentation — autogenerate: [Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
- Alembic documentation — cookbook (stamping): [Cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
- Dagster — data quality at every stage: [How to Enforce Data Quality at Every Stage](https://dagster.io/blog/how-to-enforce-data-quality-at-every-stage)
- dbt Labs — data pipeline quality checks: [How to build reliable data pipelines with data quality checks](https://www.getdbt.com/blog/data-pipeline-quality-checks)
- dbt Labs — data SLAs best practices: [What are data SLAs?](https://www.getdbt.com/blog/data-slas-best-practices)
- Material for MkDocs — versioning: [Setting up versioning](https://squidfunk.github.io/mkdocs-material/setup/setting-up-versioning/)
- Rootly — incident runbooks guide: [Incident Response Runbooks](https://rootly.com/incident-response/runbooks)
- Start Data Engineering — pipeline testing: [How to add tests to your data pipelines](https://www.startdataengineering.com/post/how-to-add-tests-to-your-data-pipeline/)

---

## Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| Stats/QA gate pattern | HIGH | Verified against Dagster docs + dbt pattern; aligns with existing PASS/WARN/FAIL schema already in codebase |
| mypy adoption strategy | HIGH | Official mypy docs + Wolt production config; well-established pattern |
| Documentation freshness | HIGH | Standard practice; mkdocs.yml version staleness observed directly in codebase |
| Runbook standard sections | MEDIUM | Multiple authoritative sources (AWS, Atlassian, runbook guides) agree on structure; SLA specifics are project-dependent |
| Alembic baseline stamp | MEDIUM | Alembic docs describe the approach; existing table handling (include_name) verified against autogenerate docs |
| Alembic autogenerate with 24 tables | LOW | Complex; ORM model creation required; autogenerate pitfalls well-documented but project-specific impact unverified |
