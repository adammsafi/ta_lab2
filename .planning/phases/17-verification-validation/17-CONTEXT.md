# Phase 17: Verification & Validation - Context

**Gathered:** 2026-02-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Validate all imports work and no data was lost during reorganization (Phases 11-16). Detect circular dependencies. Set up CI tests for organization rules. Install pre-commit hooks to prevent future disorganization. Verify file counts match pre-reorganization baseline.

</domain>

<decisions>
## Implementation Decisions

### Import Validation Scope
- Scope: **Public API + tools** — validate ta_lab2.* plus ta_lab2.tools.* subpackages
- Test files: **Yes - all test files** — validate tests/ directory imports work
- Optional dependencies: **Separate test groups** — run core imports first, optional deps (chromadb, mem0) in separate test group
- Circular dependencies: **Strict - zero cycles allowed** — any circular import is a validation failure

### CI Test Strictness
- Failure mode: **Fail only on critical** — block CI on import failures, warn on organization rules
- Organization rules: Claude's discretion based on what's practical to enforce
- Manifest validation: **No - too slow** — skip manifest validation in CI, run manually
- CI system: **GitHub Actions** — use existing .github/workflows/ setup

### Pre-commit Hook Behavior
- Hook mode: **Block critical, warn others** — block import issues, warn on org rules
- File placement rules: Claude's discretion on what to enforce
- Linting: **Ruff only** — fast linting on staged files, skip slower mypy
- Duplicate detection: Claude's discretion on practicality for hooks

### Data Loss Validation
- Verification method: **Both counts and checksums** — file counts plus checksum verification for critical files
- Baseline source: Claude's discretion based on available data (likely Phase 12 snapshot)
- Memory validation: **Yes - query moved_to relationships** — verify memory can answer "where did file X go?" for all moved files
- Missing file handling: **Investigate automatically** — try to find files in .archive/, git history before failing

### Claude's Discretion
- Which organization rules CI should validate (practical enforcement)
- File placement rules for pre-commit hooks
- Whether duplicate detection is practical in hooks
- Baseline source for pre-reorganization counts
- Specific error handling for validation failures

</decisions>

<specifics>
## Specific Ideas

- User wants separate test groups for optional dependencies — allows running core validation without all deps installed
- Strict zero circular dependency policy — no exceptions even for TYPE_CHECKING blocks
- CI should fail on critical issues but only warn on organizational rules
- Pre-commit hooks should be fast (ruff only, no mypy)
- Memory should be able to answer file location queries as part of validation

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 17-verification-validation*
*Context gathered: 2026-02-03*
