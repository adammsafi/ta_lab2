# Requirements: v0.8.0 Polish & Hardening

**Defined:** 2026-02-22
**Core Value:** Build trustworthy quant trading infrastructure 3x faster through AI coordination with persistent memory
**Milestone Goal:** Close out partially-complete infrastructure gaps — production-harden before v0.9.0 research features

---

## v0.8.0 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Stats/QA Orchestration

- [x] **STAT-01**: Stats runners wired into run_daily_refresh.py via --stats flag, included in --all as final stage after regimes
- [x] **STAT-02**: Weekly QC digest aggregates PASS/WARN/FAIL counts across all stats tables and sends summary via Telegram
- [x] **STAT-03**: Pipeline gates on FAIL status — halts and alerts on FAIL, continues with alert on WARN
- [x] **STAT-04**: All existing subprocess.run() calls (15+) have timeout= parameter to prevent silent hangs

### Code Quality

- [x] **QUAL-01**: Ruff lint blocking in CI — existing violations fixed, || true removed from ci.yml
- [x] **QUAL-02**: mypy added to CI as non-blocking job, scoped to features/ and regimes/ with [tool.mypy] config in pyproject.toml
- [x] **QUAL-03**: Ruff version upgraded from v0.1.14 to v0.9+ in pre-commit, --output-format=github added for PR annotations
- [x] **QUAL-04**: Stale tool references fixed — black removed from README, mkdocstrings version constraint corrected

### Documentation

- [x] **DOCS-01**: Version strings synchronized across pyproject.toml, mkdocs.yml, and README.md to v0.8.0
- [x] **DOCS-02**: Pipeline flow mermaid diagram (.mmd) showing bars→EMAs→features→signals→backtest data flow added to docs/diagrams/
- [x] **DOCS-03**: Stale references and TODOs resolved — aspirational alembic/black refs removed, [TODO:] placeholders in ops docs filled
- [x] **DOCS-04**: mkdocs build --strict passes with no broken nav links or missing pages

### Runbooks

- [ ] **RUNB-01**: Regime pipeline runbook documenting how to run, debug, and recover regime refresh (matches DAILY_REFRESH.md format)
- [ ] **RUNB-02**: Backtest pipeline runbook documenting signals→backtest→DB storage end-to-end workflow
- [ ] **RUNB-03**: New-asset onboarding SOP as standalone ops doc (extracted from Phase 21 analysis)
- [ ] **RUNB-04**: Disaster recovery guide covering backup strategy, restore from snapshot, and rebuild from scratch

### Alembic Migrations

- [ ] **MIGR-01**: Alembic framework bootstrapped — alembic.ini, env.py configured for existing DB without ORM models
- [ ] **MIGR-02**: Existing DB stamped as baseline — no-op baseline migration written, alembic stamp head executed on production
- [ ] **MIGR-03**: Future workflow documented — all new schema changes must go through alembic revision, not raw SQL
- [ ] **MIGR-04**: Existing 16 SQL migrations cataloged — ordered by git log date, purpose documented, archived as historical reference

---

## v0.9.0 Requirements (Deferred)

Tracked but not in current roadmap. Planned for next milestone.

### Feature Enrichment
- **FEAT-01**: KAMA, DEMA, TEMA, HMA, zero-lag EMA implementations
- **FEAT-02**: Feature experimentation framework with lifecycle (experimental→promoted→deprecated)
- **FEAT-03**: IC/feature importance evaluation pipeline

### Stress Testing
- **STRE-01**: Purged K-fold and Combinatorial Purged CV
- **STRE-02**: Adaptive walk-forward optimization (re-optimize per IS window)
- **STRE-03**: Multi-asset and multi-strategy parameter sweeps
- **STRE-04**: Probabilistic Sharpe Ratio (replace psr_placeholder stub)

### Visualization
- **VIZ-01**: Streamlit dashboard with summary views
- **VIZ-02**: Parameter sweep heatmaps and correlation heatmaps
- **VIZ-03**: Interactive plots (Plotly/Altair)

### Notebooks
- **NOTE-01**: End-to-end demo notebooks (load→compute→plot→backtest)

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| ORM model creation for all tables | Alembic autogenerate requires ORM models; too large for this milestone — stamp and move forward |
| mypy strict mode globally | ~250 functions across 400+ files; scope to features/regimes first, expand in v0.9.0 |
| Full test suite expansion | 70% coverage threshold is enforced; deeper testing is a v0.9.0 concern |
| CI/CD pipeline changes beyond lint/mypy | Release automation, deployment pipelines out of scope |
| New schema migrations | Only framework setup; no actual schema changes in this milestone |
| mkdocs site deployment (gh-pages) | Build validation only; hosting/deployment deferred |

---

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| STAT-01 | Phase 29 | Complete |
| STAT-02 | Phase 29 | Complete |
| STAT-03 | Phase 29 | Complete |
| STAT-04 | Phase 29 | Complete |
| QUAL-01 | Phase 30 | Complete |
| QUAL-02 | Phase 30 | Complete |
| QUAL-03 | Phase 30 | Complete |
| QUAL-04 | Phase 30 | Complete |
| DOCS-01 | Phase 31 | Complete |
| DOCS-02 | Phase 31 | Complete |
| DOCS-03 | Phase 31 | Complete |
| DOCS-04 | Phase 31 | Complete |
| RUNB-01 | Phase 32 | Pending |
| RUNB-02 | Phase 32 | Pending |
| RUNB-03 | Phase 32 | Pending |
| RUNB-04 | Phase 32 | Pending |
| MIGR-01 | Phase 33 | Pending |
| MIGR-02 | Phase 33 | Pending |
| MIGR-03 | Phase 33 | Pending |
| MIGR-04 | Phase 33 | Pending |

**Coverage:**
- v0.8.0 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-23 (DOCS-01..04 marked Complete after Phase 31 verification)*
