---
phase: 33-alembic-migrations
verified: 2026-02-23T17:54:23Z
status: passed
score: 8/8 must-haves verified
---

# Phase 33: Alembic Migrations Verification Report

**Phase Goal:** Bootstrap Alembic migration framework -- install alembic, create baseline no-op revision, stamp production DB, catalog 17 legacy SQL files, document forward workflow in CONTRIBUTING.md, update DISASTER_RECOVERY.md, add alembic history CI job.
**Verified:** 2026-02-23T17:54:23Z
**Status:** PASSED
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | alembic command is available after pip install -e . | VERIFIED | alembic>=1.18 in core [project.dependencies] (pyproject.toml line 14); installed as core dep, not optional |
| 2  | alembic history runs without error from project root (filesystem only, no DB needed) | VERIFIED | CI job runs alembic history with no DB connection; env.py offline mode + filesystem revision scan are independent |
| 3  | env.py uses resolve_db_url(), NullPool, encoding=utf-8 in fileConfig, target_metadata=None | VERIFIED | Lines 17, 27, 33, 60 of alembic/env.py confirm all four properties exactly as specified |
| 4  | alembic.ini contains placeholder URL only -- no real credentials | VERIFIED | Line 68: sqlalchemy.url = driver://user:pass@localhost/dbname; comment explains real URL is in env.py |
| 5  | alembic history shows exactly one revision (baseline no-op) | VERIFIED | Single file in alembic/versions/: 25f2b3c90f65_baseline.py; down_revision=None, both upgrade/downgrade are pass |
| 6  | CONTRIBUTING.md explains the 5-step revision workflow and gotchas | VERIFIED | Lines 100-179: 5 numbered steps (# 1 through # 5), 4 gotchas section, alembic revision -m referenced |
| 7  | All 17 legacy SQL migration files are cataloged with git dates and purposes | VERIFIED | sql/migration/CATALOG.md: exactly 17 .sql files in directory, 17 rows in catalog table, 016_dim_timeframe listed |
| 8  | DISASTER_RECOVERY.md mentions alembic_version table and verification steps | VERIFIED | Lines 101-114: alembic_version mentioned twice, alembic stamp head twice, alembic current verification step present |

**Score:** 8/8 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alembic/env.py` | resolve_db_url, NullPool, utf-8 | VERIFIED | 73 lines, no stubs; resolve_db_url at line 17; pool.NullPool at line 60; encoding=utf-8 at line 27; target_metadata=None at line 33 |
| `alembic.ini` | placeholder URL, no credentials | VERIFIED | 112 lines; sqlalchemy.url = driver://user:pass@localhost/dbname; output_encoding=utf-8; ruff post-write hook configured |
| `alembic/script.py.mako` | revision template exists | VERIFIED | 28 lines; standard alembic mako template with upgrade/downgrade stubs |
| `pyproject.toml` | alembic>=1.18 in core deps | VERIFIED | Line 14 (core deps) and line 92 (all optional group) both contain alembic>=1.18 |
| `alembic/versions/25f2b3c90f65_baseline.py` | baseline no-op, 15+ lines | VERIFIED | 26 lines; down_revision=None; upgrade() and downgrade() both pass; explanatory comments; no stubs |
| `CONTRIBUTING.md` | Schema Migrations section | VERIFIED | 179 lines; ## Schema Migrations (Alembic) at line 95; 5-step workflow + 4 gotchas documented |
| `sql/migration/CATALOG.md` | 17 legacy files cataloged | VERIFIED | 51 lines; 17 .sql files confirmed in directory; 17 data rows in catalog table; 016_dim_timeframe present; git dates and purposes |
| `docs/operations/DISASTER_RECOVERY.md` | alembic_version mentioned | VERIFIED | 365 lines; alembic_version at lines 111, 114; alembic stamp head at lines 101, 167; alembic current verification step |
| `.github/workflows/ci.yml` | alembic-history job | VERIFIED | Lines 118-130: alembic-history job; pip install -e .[dev]; run: alembic history; triggered on push + pull_request |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `alembic/env.py` | `refresh_utils.resolve_db_url` | `from src.ta_lab2.scripts.refresh_utils import resolve_db_url` | WIRED | Import at line 17; called in both run_migrations_offline() and run_migrations_online() |
| `CONTRIBUTING.md` | `alembic revision -m` | Explicit command in 5-step code block | WIRED | Line 104: alembic revision -m shown in usage example |
| `.github/workflows/ci.yml` | `alembic history` | run step in alembic-history job | WIRED | Line 130: run: alembic history; alembic available via core deps in .[dev] install |
| `docs/operations/DISASTER_RECOVERY.md` | `alembic stamp head` | Explicit command in Alembic Migration State section | WIRED | Line 101: alembic stamp head; lines 107-108: alembic current with expected output 25f2b3c90f65 (head) |
| `sql/migration/CATALOG.md` | `016_dim_timeframe*.sql` | First row of catalog table | WIRED | Row 1 documents 016_dim_timeframe_partial_bounds_and_calendar_families.sql with 2025-12-20 date and purpose |

---

### Requirements Coverage

No requirements from REQUIREMENTS.md were mapped specifically to Phase 33 per the provided must-haves list. All phase deliverables verified directly against plan artifacts.

---

### Anti-Patterns Found

None. All scanned files show zero TODO, FIXME, placeholder, or not-implemented patterns:

- `alembic/env.py`: clean
- `alembic/versions/25f2b3c90f65_baseline.py`: clean
- `sql/migration/CATALOG.md`: clean
- `docs/operations/DISASTER_RECOVERY.md`: clean
- `.github/workflows/ci.yml`: clean

---

### Human Verification Required

#### 1. Production DB Stamp Confirmation

**Test:** Run `alembic current` against the live database from the project root.
**Expected:** Output shows `25f2b3c90f65 (head)`.
**Why human:** Requires live DB connection. SUMMARY.md reports this was confirmed at plan completion time (output showed: Running stamp_revision -> 25f2b3c90f65), but cannot be re-verified programmatically without DB access. This is the only deliverable that depends on live infrastructure state rather than filesystem artifacts.

---

### Verification Detail Notes

**pyproject.toml all group:** The `all` optional group (line 92) contains `alembic>=1.18`. Alembic is also in core `[project.dependencies]` (line 14), so any `pip install -e .` variant installs alembic regardless of optional group selection. The CI alembic-history job installs `.[dev]` which pulls alembic through core deps -- architecturally correct.

**Baseline revision line count:** 26 lines, exceeding the 15-line minimum for revision files. Contains proper revision identifiers, typed signatures, and explanatory comments on pass statements. No stubs.

**CATALOG.md row count:** Directory confirms exactly 17 .sql files in sql/migration/. The CATALOG.md table has 17 data rows. The catalog also includes a Notes section grouping files by era (v0.6.0 build-out, emergency recovery, Phase 26 bar schema, v0.7.0 features redesign).

**CI alembic dependency chain:** The alembic-history job installs `pip install -e ".[dev]"`. The `dev` optional group does not explicitly list alembic, but alembic is in core `[project.dependencies]`, which is always installed by any `pip install -e .` invocation. Architecturally correct -- alembic is a runtime dependency, not a dev-only tool.

---

## Gaps Summary

No gaps. All 8 observable truths are verified by codebase artifacts. Phase goal is fully achieved.

---

*Verified: 2026-02-23T17:54:23Z*
*Verifier: Claude (gsd-verifier)*
