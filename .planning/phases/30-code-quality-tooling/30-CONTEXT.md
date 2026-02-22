# Phase 30: Code Quality Tooling - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Make ruff lint a hard CI gate (zero violations can merge), add scoped mypy as non-blocking CI job, upgrade tooling versions, remove dead tool references. This phase does NOT fix mypy errors or add type annotations -- it sets up configuration only.

</domain>

<decisions>
## Implementation Decisions

### Ruff violation strategy
- Auto-fix all violations via `ruff check --fix` + `ruff format`. Trust ruff's auto-fixes for unused imports, formatting, etc. Review diff as a batch.
- For non-auto-fixable violations: Claude decides per-rule -- prefer manual fix if tractable, disable the rule if it produces many unfixable violations, suppress with `# noqa` as last resort.
- Both `ruff check` AND `ruff format --check` become hard CI gates (blocking).
- Sequence: fix violations first, verify zero-exit locally, THEN remove `|| true` in a separate commit. Never remove escape hatch while violations exist.

### mypy strictness scope
- Configure only -- do NOT fix mypy errors in this phase. Set up `[tool.mypy]` config, run it, log baseline error count.
- Scope: `src/ta_lab2/features/` and `src/ta_lab2/regimes/` only. Non-blocking CI (`continue-on-error: true`).
- `check_untyped_defs = true` -- check function bodies even without type annotations.
- `ignore_missing_imports = true` -- required for vectorbt, psycopg2, etc.
- Leave existing 106 bare `# type: ignore` comments untouched. Clean up incrementally in v0.9.0.

### Tooling version pinning
- Minimum floor pins: `ruff>=0.9.0`, `mypy>=1.14`, `pandas-stubs>=2.2` (dev group only).
- Let ruff migrate deprecated rule codes automatically (`ruff check --fix` handles renames).
- Pre-commit ruff mirror version must match pyproject.toml floor -- developers see same rules locally as CI.
- Remove ALL dead tool references: black, isort, and any other tools ruff replaces from pre-commit config, README, and pyproject.toml.

### CI integration approach
- Separate CI jobs: ruff lint, ruff format, mypy as independent jobs. Each reports independently, runs in parallel.
- `--output-format=github` on ruff for inline PR annotations (violations shown on diff lines).
- Quality checks run on every PR (not path-filtered). ruff and mypy are fast enough.
- Add CI version-consistency check: verify pyproject.toml version matches README heading. Prevents the 3-file drift that already happened.
- mypy job is non-blocking (`continue-on-error: true`). Ruff lint and format are blocking.

### Claude's Discretion
- Which ruff rule categories to enable/disable based on violation count after running `ruff check src --statistics`
- Per-module mypy overrides if needed (e.g., relaxing rules for scripts/ or baseline/)
- Exact CI job names and step ordering
- Whether to add ruff cache configuration for CI speed

</decisions>

<specifics>
## Specific Ideas

- Research identified that pyproject.toml shows 0.5.0, mkdocs.yml shows v0.4.0, README shows v0.5.0 -- all need updating (handled in Phase 31, but version-consistency CI check goes in this phase)
- The `|| true` in ci.yml must be removed AFTER zero violations achieved, not before
- pandas-stubs must be dev-only to avoid numpy version conflicts with vectorbt 0.28.1
- mkdocstrings version constraint needs correction (QUAL-04) alongside the other stale ref fixes

</specifics>

<deferred>
## Deferred Ideas

- mypy strict blocking mode (flip `continue-on-error: false`) -- requires annotating enough library layer first, v0.9.0
- Converting bare `# type: ignore` to specific error codes -- mechanical work for v0.9.0
- MonkeyType automated annotation -- separate research/milestone
- Global mypy enforcement beyond features/regimes -- expand scope incrementally in future milestones

</deferred>

---

*Phase: 30-code-quality-tooling*
*Context gathered: 2026-02-22*
