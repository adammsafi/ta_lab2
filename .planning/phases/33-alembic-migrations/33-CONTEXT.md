# Phase 33: Alembic Migrations - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Bootstrap Alembic migration framework for the existing 50+ table PostgreSQL database. Stamp the current schema as baseline (no DDL executed on live DB). Catalog all legacy SQL files as historical reference. Document the forward workflow so all future schema changes go through Alembic.

</domain>

<decisions>
## Implementation Decisions

### Legacy catalog format
- Detailed metadata per file: filename, git creation date, purpose, tables affected
- Claude's discretion on catalog location (docs/ vs sql/ vs alembic baseline) and whether to move files to sql/legacy/ or keep in place
- Claude determines which files qualify as "migrations" vs "initial DDL" for the catalog scope

### Workflow documentation
- Claude's discretion on location (CONTRIBUTING.md section vs standalone ops doc)
- Claude's discretion on depth (quick reference vs full walkthrough) — audience is future-me in 3 months
- Must include a "gotchas" section with known pitfalls (no autogenerate without ORM, Windows encoding, etc.)

### Stamp execution scope
- Plan RUNS `alembic stamp head` on the live DB (DB must be available during execution)
- After stamp, verify with `alembic current` and include output in SUMMARY.md
- Update DISASTER_RECOVERY.md to mention alembic_version table (add note about verifying `alembic current` after restore)

### Future migration conventions
- Claude's discretion on: descriptive slugs vs auto-generated hash, upgrade+downgrade vs upgrade-only, online-only vs online+offline modes, CI integration scope
- These are framework decisions Claude can make based on what's practical for this project

### Claude's Discretion
- Catalog location and file organization
- Workflow doc location and depth (within "future-me" audience constraint)
- Revision naming convention
- downgrade() policy
- env.py online/offline mode support
- Whether to add alembic to CI pipeline

</decisions>

<specifics>
## Specific Ideas

- MEMORY.md already captures key decisions: no autogenerate (write by hand), stamp-then-forward only, encoding='utf-8' in env.py, resolve_db_url() from refresh_utils
- DR guide already mentions "alembic stamp head" — extend with alembic_version table awareness
- Gotchas section should capture the Windows encoding pitfall and the autogenerate trap

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 33-alembic-migrations*
*Context gathered: 2026-02-23*
