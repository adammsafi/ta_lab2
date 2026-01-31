# Phase 10: Release Validation - Context

**Gathered:** 2026-01-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Final validation and documentation checkpoint for v0.4.0 release. Ensures all three validation types pass (time alignment, data consistency, backtest reproducibility), complete documentation suite is delivered (README, DESIGN, ARCHITECTURE, API, deployment guide), and release artifacts are properly published to GitHub. This is a quality gate, not feature development.

</domain>

<decisions>
## Implementation Decisions

### Validation execution strategy
- Hybrid approach: CI runs critical blockers, manual script generates comprehensive validation report
- All three validations (time alignment, data consistency, backtest reproducibility) are CI blockers - must pass before merge
- Validations require real database (TARGET_DB_URL) - no mock mode for CI
- Multiple output formats: both JSON (machine-readable) and markdown (human-readable) reports generated

### Documentation scope & format
- README: Tiered structure with quick start at top, collapsible detailed sections for each component (memory, orchestrator, ta_lab2)
- Separate DESIGN.md (high-level concepts, system overview, data flow) and ARCHITECTURE.md (implementation details, schemas, APIs)
- API reference: Interactive Swagger/OpenAPI documentation for REST endpoints
- Deployment guide: Full deployment documentation included - infrastructure setup, environment variables, database migrations, monitoring setup

### Release artifacts & versioning
- GitHub release with release notes (not PyPI package yet, not just git tag)
- Documentation attached as release assets (PDF/HTML bundle)
- No migration guide needed - v0.4.0 is first formal release
- Automated release when CI green - once all checks pass, create release tag and publish

### Claude's Discretion
- CHANGELOG format (Keep a Changelog vs Conventional Commits vs narrative)
- Test coverage threshold for release (70% vs 85% vs no requirement)
- Validation pass criteria strictness (zero tolerance vs warnings allowed vs threshold-based)
- Performance benchmark requirements (comprehensive vs smoke test vs defer)

</decisions>

<specifics>
## Specific Ideas

- CI must have real database access for validations - no shortcuts with mocks
- Three blockers strategy reflects high quality bar: time alignment (most critical), data consistency (data integrity), backtest reproducibility (scientific rigor)
- Dual report format enables both automated processing (JSON for metrics tracking) and human review (markdown for release notes)
- Swagger/OpenAPI provides interactive try-it-out functionality for API exploration
- Automated release reduces friction - no manual approval bottleneck when CI proves quality

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope

</deferred>

---

*Phase: 10-release-validation*
*Context gathered: 2026-01-30*
