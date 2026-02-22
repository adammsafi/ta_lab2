# Research Summary: v0.8.0 Polish & Hardening

**Project:** ta_lab2
**Domain:** Python quant data platform — hardening existing infrastructure
**Researched:** 2026-02-22
**Confidence:** HIGH (all findings from direct codebase inspection + verified official sources)

---

## Executive Summary

v0.8.0 is a hardening milestone, not a feature milestone. The codebase already has ~50
tables, 22M+ rows, 408 Python source files, 5 stats runners, 3 signal generators, and a
working subprocess-based orchestrator. Every area of this milestone has partial
infrastructure already in place — the work is completing the last-mile connections, not
building from scratch. The recommended approach is narrow, sequential, and conservative:
wire existing components together, clean up tooling debt, document what was already built,
and establish schema migration tracking before any new schema changes land.

The highest-leverage action in v0.8.0 is wiring the 5 existing stats runners into
`run_daily_refresh.py` as a final stage. All the hard work (watermark logic, PASS/WARN/FAIL
schema, incremental patterns) is already done — only orchestration wiring is missing.
Alembic bootstrapping (stamp-then-move-forward) is the second priority: it has zero risk
when done correctly (no DDL runs on the live DB) but prevents schema drift from becoming
unmanageable. Code quality (ruff blocking + mypy non-blocking) and documentation (version
sync + new runbooks) round out the milestone.

The primary risk in this milestone is not technical complexity — it is sequencing errors.
Removing `|| true` from ruff CI before achieving zero violations will break all open PRs.
Using `alembic --autogenerate` before ORM models exist will try to recreate all 50 tables.
Running mypy globally on day one will produce thousands of errors. Each area has a specific
"do this first" precondition that must be satisfied before the enforcement step; respecting
that sequence is the entire risk management strategy for this milestone.

---

## Key Findings

### Recommended Stack

The stack for v0.8.0 requires minimal additions: `alembic>=1.15` (migration framework),
`pandas-stubs>=2.2` (mypy type stubs for pandas, dev-only), `ruff>=0.9.0` (version
upgrade from 0.1.5), and `mypy>=1.14` (version upgrade from 1.8). Documentation deps
need `mkdocs-material>=9.5`, `mkdocstrings[python]>=0.26`, and `mike>=2.1` (explicitly
pinned for the first time). No new runtime libraries are needed. The stats/QA digest
report uses only stdlib + existing Telegram notification module — no Jinja2, no
APScheduler, no Celery.

**Core additions:**

- `alembic>=1.15` — migration framework; bootstrapped via wrap-then-stamp strategy; use
  `NullPool` in `env.py` (consistent with existing codebase pattern)
- `ruff>=0.9.0` — upgrade from v0.1.5; pin to prevent CI/local version drift; add
  `ruff format --check` alongside `ruff check` in CI; pre-commit hook updated from
  `v0.1.14` to `v0.9.0`
- `mypy>=1.14` + `pandas-stubs>=2.2` (dev group only) — `ignore_missing_imports = true`
  required due to conditional imports (vectorbt, fredapi, astronomy-engine); no SQLAlchemy
  stubs needed (SA 2.0 is natively PEP-484 compliant)
- `mkdocs-material>=9.5` — native mermaid support via `pymdownx.superfences`; no separate
  mermaid plugin needed (third-party plugin conflicts with dark mode)
- `mike>=2.1` — explicitly pinned; currently referenced in `mkdocs.yml` but absent from
  `pyproject.toml` deps

**What not to add:** Jinja2, APScheduler, Celery, mkdocs-mermaid2-plugin, sqlalchemy-stubs,
data-science-types (unmaintained since 2021), Flask-Alembic, Liquibase/Flyway (JVM tools),
Black (replaced by ruff format), pylint (replaced by ruff).

### Expected Features

This milestone hardens 5 existing areas. "Table stakes" means what a mature platform in
each area requires, measured against what currently exists.

**Must have (v0.8.0):**

- Stats runners wired into `run_daily_refresh.py --all` as the final `--stats` stage;
  `run_all_stats_refreshers.py` new top-level orchestrator
- Non-zero exit codes from stats runners on FAIL (currently exit 0; failures invisible
  to orchestration)
- `[tool.mypy]` section in `pyproject.toml` with `ignore_missing_imports = true`,
  `check_untyped_defs = true`, per-module overrides for `scripts/` and `scripts/baseline/`
- Non-blocking mypy CI job scoped to `features/` and `regimes/` only (two most
  annotation-complete layers)
- Alembic initialized, empty baseline stamp migration written by hand, `alembic stamp head`
  applied to production DB after verification on staging
- All three version strings (`pyproject.toml`, `mkdocs.yml`, `README.md`) updated to `0.8.0`
  in a single commit
- `mkdocs build --strict` passes (missing nav files stubbed or removed)
- Pipeline flow diagram in `docs/diagrams/data_flow.mmd` updated to v0.7.0+ topology
- Two new runbooks: `docs/operations/STATS_RUNNERS.md` and `docs/operations/FEATURES_PIPELINE.md`
- SLA section, incident severity classification, and escalation procedures added to
  `DAILY_REFRESH.md`

**Should have (differentiators for this milestone):**

- Ruff blocking in CI (`|| true` removed from `ruff check src`) — requires zero violations
  achieved first; do in a separate PR from the violation-fix PR
- `ruff format --check` added to CI alongside lint check
- `timeout=` parameter added to all existing `subprocess.run()` calls before adding new
  stats runner subprocess steps
- Version consistency CI check comparing `pyproject.toml` version vs `README.md` heading
- `run_all_stats_refreshers.py` with runtime profiling of each runner before wiring

**Defer to post-v0.8.0:**

- mypy strict blocking (flip `continue-on-error: false`) — requires annotating enough of
  the library layer to reduce error count near zero
- Alembic autogenerate — requires creating SQLAlchemy Table objects for all 24+ tables;
  high effort, low value given the raw-SQL pattern in this codebase
- Mike-based versioned docs with `gh-pages` branch — operations overhead; defer until
  there are external consumers
- Architecture decision records — write as new decisions are made, not retroactively
- Stats trend SQL view — deferred until runners have multi-week history
- MonkeyType automated annotation — research tool; separate milestone

### Architecture Approach

v0.8.0 changes only orchestration topology, not data flow. The subprocess isolation
pattern in `run_daily_refresh.py` is intentional and must be preserved — stats runners
wire via subprocess, not in-process function calls. The current `--all` chain is
`bars -> EMAs -> regimes`; the target is `bars -> EMAs -> regimes -> stats`. Stats is
last because it validates freshness of data written by all prior stages. Import-linter
contracts (5 contracts defined in `pyproject.toml`) constrain module placement: the new
`run_all_stats_refreshers.py` belongs in `ta_lab2.scripts` (the allowed top orchestration
layer) and must invoke child processes, not import across layer boundaries.

**Major components and their v0.8.0 changes:**

1. `run_daily_refresh.py` — modified: add `run_stats_refreshers()`, `--stats` flag,
   include stats in `--all` chain as final stage
2. `run_all_stats_refreshers.py` — new: top-level orchestrator aggregating 5 existing
   stats runner scripts via `subprocess.run()` + `ComponentResult` pattern (same pattern
   as the existing `emas/stats/run_all_stats_refreshes.py`)
3. `alembic/` + `alembic.ini` + `alembic/versions/0001_baseline_stamp.py` — new:
   migration framework bootstrap; `env.py` wired to `resolve_db_url()` from `refresh_utils`
4. `pyproject.toml` — modified: `[tool.mypy]` section, version bump to `0.8.0`, dep
   version upgrades (ruff, mypy, mkdocs-material), new deps (alembic, pandas-stubs, mike)
5. `.github/workflows/ci.yml` — modified: ruff blocking (after violations fixed), add
   non-blocking mypy job scoped to library layer
6. `docs/operations/STATS_RUNNERS.md` + `docs/operations/FEATURES_PIPELINE.md` — new
   runbooks following the established section structure from `DAILY_REFRESH.md`
7. `docs/diagrams/data_flow.mmd` + `docs/operations/DAILY_REFRESH.md` + `mkdocs.yml`
   — updated to reflect v0.7.0+ reality (regimes wired since v0.7.0 but runbook never
   updated; nav has broken references)

### Critical Pitfalls

1. **Alembic autogenerate without ORM models recreates all 50 tables** — with no
   SQLAlchemy MetaData populated, `--autogenerate` compares an empty model against the
   live DB and generates `op.create_table()` for every existing table. Running the result
   fails with `DuplicateTable`. Prevention: write the baseline migration as a no-op by
   hand; do not invoke `--autogenerate` in v0.8.0.

2. **Removing `|| true` from ruff CI before reaching zero violations blocks all open PRs**
   — ruff checks the entire `src/` on every run; pre-existing violations in unrelated files
   block every PR. Prevention: run `ruff check src --statistics` first, fix or suppress all
   violations, achieve zero-exit locally, then remove the flag in a separate PR from the
   fix PR.

3. **`subprocess.run()` calls with no `timeout=` hang the orchestrator overnight** — 15+
   existing subprocess calls have no timeout. A hanging stats runner blocks the pipeline
   indefinitely; `capture_output=True` on Windows can exacerbate the hang (CPython
   issue #88693). Prevention: add `timeout=` to all existing calls before adding new steps;
   handle `subprocess.TimeoutExpired` explicitly.

4. **mypy run globally on day one produces thousands of errors** — 35% of ~2,722 functions
   are unannotated; vectorbt, psycopg2, conditional imports all generate noise. Prevention:
   scope initial CI check to `features/` and `regimes/` only; add `ignore_missing_imports`
   and per-library overrides before running; do not attempt global strict enforcement in
   v0.8.0.

5. **Three version strings in three files already out of sync** — `pyproject.toml` shows
   `0.5.0`, `mkdocs.yml` shows `v0.4.0`, `README.md` shows `v0.5.0`. Future readers and
   tools that read `importlib.metadata.version("ta_lab2")` get wrong values. Prevention:
   fix all three in the first commit of the milestone; add a CI version-consistency check
   to prevent future drift.

---

## Implications for Roadmap

The 5 hardening areas have a natural dependency ordering. Some must precede others to
avoid the pitfalls identified above. The suggested structure is 4 phases that can be
partially parallelized:

### Phase 29: Orchestrator Hardening — Stats Wiring + Subprocess Timeouts

**Rationale:** Highest-leverage change in the milestone. All 5 stats runners are fully
built and tested; only the orchestration wire is missing. This phase should come first
because the stats runbook (Phase 32) cannot be written until the integrated workflow
exists, and adding `timeout=` to existing subprocess calls is a prerequisite for adding
any new subprocess steps safely.

**Delivers:** `run_all_stats_refreshers.py` top-level orchestrator + `--stats` flag in
`run_daily_refresh.py` + stats as the final `--all` stage + `timeout=` on all existing
subprocess calls + runtime profile of each stats runner before wiring.

**Addresses:** Stats/QA gate (must-have); subprocess hang risk (critical pitfall #3).

**Avoids:** Concurrent orchestrator runs producing duplicate rows (profile runtime before
wiring; add lockfile consideration); QC digest reporting stale data under
`--continue-on-error` (add `ingested_at` staleness check as first operation in digest).

**Research flag:** Standard patterns; no deeper research needed. The `ComponentResult` +
subprocess pattern is established in the codebase (existing EMA stats orchestrator is the
direct template).

---

### Phase 30: Alembic Bootstrap — Stamp Existing Schema

**Rationale:** Must be done before any v0.8.0 schema changes land. The stamp is a
read-only DB operation — no DDL executes on the live database. Establishing migration
tracking now means every subsequent schema change in this milestone and future milestones
can go through Alembic rather than ad-hoc SQL files.

**Delivers:** `alembic/` directory + `alembic.ini` (using `%(here)s` for portable paths)
+ `alembic/env.py` wired to `resolve_db_url()` + `alembic/versions/0001_baseline_stamp.py`
(empty upgrade/downgrade with comments) + `alembic stamp head` applied to production DB
after verification on staging.

**Addresses:** Alembic baseline stamp (must-have); schema drift prevention for future
milestones.

**Avoids:** Autogenerate pitfall (no `--autogenerate` invoked; baseline is hand-written
no-op); Windows path mixing (use `%(here)s` in `alembic.ini`, `encoding='utf-8'` in any
file reads per existing MEMORY.md guidance); application order ambiguity (keep existing
16 SQL files as historical reference, do not import them into Alembic).

**Research flag:** Standard patterns; well-documented in official Alembic cookbook. No
deeper research needed for the stamp approach. Autogenerate path (deferred) would need
separate research on ORM model creation for 24+ tables.

---

### Phase 31: Code Quality — Ruff Blocking + mypy Baseline

**Rationale:** Should come after Phase 29 so the new stats orchestrator code is included
in the ruff clean sweep. Must be done as a two-step sequence: (1) audit and fix violations,
(2) flip enforcement. Doing these in separate PRs makes rollback easier.

**Delivers:** Zero ruff violations in `src/`; `ruff check` and `ruff format --check`
blocking in CI; `[tool.mypy]` config in `pyproject.toml`; non-blocking mypy CI job
scoped to `features/` and `regimes/`; `ruff>=0.9.0` and `mypy>=1.14` version pins;
`pandas-stubs>=2.2` in dev group; pre-commit updated from `v0.1.14` to `v0.9.0`.

**Addresses:** ruff blocking (should-have); mypy baseline config (must-have); ruff version
drift prevention.

**Avoids:** Breaking all open PRs (achieve zero violations first, remove `|| true` in
separate PR); numpy version conflict from pandas-stubs install (pin stubs to dev group
only; run backtest smoke test after installation to catch any numpy version resolution
that breaks vectorbt 0.28.1 numerics).

**Research flag:** Well-documented patterns; specific version pins verified against PyPI.
No deeper research needed.

---

### Phase 32: Documentation — Version Sync + Diagram + Runbooks

**Rationale:** Documentation is strictly last because it describes what was built. The
pipeline diagram and stats runbook depend on Phase 29 being complete. The Alembic runbook
(if added) depends on Phase 30. The version bump should be the first commit within this
phase — do not write new v0.8.0 content under a `v0.4.0` site name.

**Delivers:** All three version strings updated to `0.8.0` in one commit; `data_flow.mmd`
replaced with v0.7.0+ topology diagram; `DAILY_REFRESH.md` updated with regimes and stats
sections; `STATS_RUNNERS.md` new runbook; `FEATURES_PIPELINE.md` new runbook; `mkdocs.yml`
nav updated and validated; `mkdocs build --strict` passes; SLA + incident severity +
escalation procedures added to `DAILY_REFRESH.md`; CI version consistency check added.

**Addresses:** Docs version fix (must-have); pipeline diagram (must-have); new runbooks
(must-have); mkdocs nav broken references (must-have).

**Avoids:** Writing new content under a stale version label; breaking `mkdocs build` on
missing nav files (run `mkdocs build --strict` locally before merging any docs PR); leaving
mike in a broken intermediate state (either activate the `gh-pages` branch or remove the
mike provider from `mkdocs.yml` — do not leave it in limbo).

**Research flag:** Standard markdown and mkdocs patterns; no deeper research needed.

---

### Phase Ordering Rationale

- Phases 29 and 30 can run in parallel on separate branches because they are fully isolated
  (Phase 29 touches orchestration Python; Phase 30 touches Alembic infrastructure).
- Phase 31 should wait for Phase 29 to be merged so the new orchestrator code is included
  in the ruff sweep.
- Phase 32 is strictly last — the pipeline diagram and runbooks describe the final
  wired state.
- Within Phase 29, subprocess timeouts must be added before the new stats subprocess step
  is wired in; this is a task-level ordering constraint within the phase.
- Within Phase 31, violation-fix PR must merge before the `|| true` removal PR; enforce
  this as a PR dependency.

### Research Flags

Phases with well-documented patterns (no deeper research needed):
- **Phase 29:** ComponentResult + subprocess pattern is established in the codebase;
  direct replication of existing EMA stats orchestrator pattern.
- **Phase 30:** Alembic stamp approach is documented in official Alembic cookbook; no-op
  baseline migration is the correct path for codebases without ORM models.
- **Phase 31:** ruff and mypy configurations are well-documented; specific version pins
  verified against PyPI.
- **Phase 32:** mkdocs-material mermaid, nav structure, and runbook format are all
  established patterns in the codebase.

Phases requiring empirical investigation during execution (not external research):
- **Phase 29 (stats runtime profiling):** Profile each of the 5 runners against the full
  production asset universe before wiring. If combined serial runtime exceeds 20 minutes,
  parallel execution via the existing `num_processes` pattern may be needed. This is an
  empirical question resolved by running `time python -m ta_lab2.scripts.<runner> --all`.
- **Phase 30 (ad-hoc migration ordering):** Reconstruct confirmed application order of the
  8 unnumbered `sql/migration/` files from `git log --follow --diff-filter=A --
  sql/migration/` before assigning Alembic revision numbers. No external research needed —
  this is codebase archaeology.
- **Phase 31 (ruff violation count):** Run `ruff check src --statistics` as the first
  action to set the scope of violation-fix work. Count is unknown at research time.
- **Phase 31 (mypy error count):** Run `mypy src/ta_lab2/features/ src/ta_lab2/regimes/`
  with the proposed config to get the baseline error count before committing to remediation
  scope.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All package versions verified against PyPI (February 2026); SQLAlchemy 2.0 native typing confirmed against official docs; mermaid native support confirmed against mkdocs-material docs; no experimental packages recommended |
| Features | HIGH | All gaps identified from direct codebase inspection of actual files; table-stakes analysis validated against Dagster/dbt/Alembic official sources; all must-have items are last-mile connections on existing infrastructure |
| Architecture | HIGH | All findings from direct codebase inspection of `run_daily_refresh.py`, `pyproject.toml`, `ci.yml`, `mkdocs.yml`, `sql/migration/`; subprocess/ComponentResult pattern confirmed in existing code |
| Pitfalls | HIGH | Critical pitfalls verified against official sources (Alembic issue tracker, CPython issue tracker, mypy official docs); moderate pitfalls from community engineering blogs consistent with official docs; Windows-specific pitfalls directly observed in MEMORY.md |

**Overall confidence:** HIGH

### Gaps to Address

- **Stats runner runtime on full asset universe:** No timing baseline captured for any of
  the 5 stats runners against the full production dataset (~22M rows of EMA data). Profile
  before wiring. If any single runner exceeds 10 minutes, or the combined serial total
  exceeds 20 minutes, consider parallelism using the existing `num_processes` pattern from
  bar builders.

- **Ad-hoc SQL migration application order:** The 8 unnumbered files in `sql/migration/`
  have no canonical ordering visible from the filesystem. Reconstruct from
  `git log --follow --diff-filter=A -- sql/migration/` before creating Alembic revision
  numbers. Files that applied data transformations no longer meaningful on the current schema
  should be represented as no-ops with documentation comments.

- **Current ruff violation count:** `ruff check src --statistics` has not been run at
  research time. The baseline count is unknown. Run this as the first action of Phase 31
  to determine scope. The `|| true` in CI suggests violations exist; severity is unknown.

- **mypy error count on features/ and regimes/:** The two target modules for initial mypy
  enforcement have not been checked. Run `mypy src/ta_lab2/features/ src/ta_lab2/regimes/`
  with the proposed config before committing to a remediation scope. The 106 existing bare
  `# type: ignore` comments will need gradual conversion to specific error codes.

- **mike / gh-pages branch status:** `mkdocs.yml` has `extra.version.provider: mike`
  configured but a `gh-pages` branch may not exist. Confirm before Phase 32. Either
  activate mike properly (create the branch, wire the CI deploy job) or remove the provider
  config to avoid broken version-switcher UI in the deployed docs.

---

## Sources

### Primary (HIGH confidence)

- Codebase direct inspection: `run_daily_refresh.py`, `pyproject.toml`,
  `.github/workflows/ci.yml`, `mkdocs.yml`, `README.md`, `sql/migration/` — all findings
  directly observed in code
- [Alembic PyPI](https://pypi.org/project/alembic/) — version 1.18.4 confirmed
- [Alembic autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
  — autogenerate-recreates-all-tables pitfall confirmed
- [Alembic cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html) — stamp
  approach for existing databases confirmed
- [Alembic Issue #590: Windows path mixing in script_location](https://github.com/sqlalchemy/alembic/issues/590)
  — path pitfall confirmed
- [mypy PyPI](https://pypi.org/project/mypy/) — version 1.19.1 confirmed
- [mypy: Using mypy with an existing codebase](https://mypy.readthedocs.io/en/stable/existing_code.html)
  — ramp-up strategy and narrow-scope approach confirmed
- [ruff PyPI](https://pypi.org/project/ruff/) — version 0.15.2 confirmed
- [mkdocs-material PyPI](https://pypi.org/project/mkdocs-material/) — version 9.7.2 confirmed
- [Material for MkDocs: native mermaid diagrams](https://squidfunk.github.io/mkdocs-material/reference/diagrams/)
  — native mermaid support confirmed; no third-party plugin needed
- [SQLAlchemy 2.0 mypy support](https://docs.sqlalchemy.org/en/20/orm/extensions/mypy.html)
  — confirms no separate stubs package needed for SA 2.0
- [CPython issue #88693: subprocess.run hangs on Windows with capture_output](https://github.com/python/cpython/issues/88693)
  — subprocess timeout pitfall confirmed
- [mike PyPI](https://pypi.org/project/mike/) — version 2.1.3 confirmed
- [pandas-stubs PyPI](https://pypi.org/project/pandas-stubs/) — version 3.0.0.260204 confirmed

### Secondary (MEDIUM confidence)

- [Alembic Discussion #1425: Existing PostgreSQL DB bootstrapping](https://github.com/sqlalchemy/alembic/discussions/1425)
  — stamp strategy for existing DBs; consistent with official docs
- [Wolt Engineering: Professional-grade mypy configuration](https://careers.wolt.com/en/blog/tech/professional-grade-mypy-configuration)
  — per-module override strategy for large codebases
- [Dagster: How to Enforce Data Quality at Every Stage](https://dagster.io/blog/how-to-enforce-data-quality-at-every-stage)
  — QA gate pattern; consistent with existing PASS/WARN/FAIL schema
- [dbt Labs: data pipeline quality checks](https://www.getdbt.com/blog/data-pipeline-quality-checks)
  — incremental QA gate vs full recompute trade-off
- [Airbus: Python code quality with Ruff, one step at a time](https://cyber.airbus.com/en/newsroom/stories/2025-10-python-code-quality-with-ruff-one-step-at-a-time-part-1)
  — ruff incremental adoption on large codebase; two-PR strategy for zero-then-enforce
- [Quantlane: Type-checking a large Python codebase](https://quantlane.com/blog/type-checking-large-codebase/)
  — mypy scoping strategy for large codebases; narrow-then-expand approach
- [Rootly: Incident Response Runbooks](https://rootly.com/incident-response/runbooks)
  — SLA section and incident severity structure

---

*Research completed: 2026-02-22*
*Ready for roadmap: yes*
