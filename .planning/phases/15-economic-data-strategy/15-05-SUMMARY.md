---
phase: 15-economic-data-strategy
plan: 05
subsystem: integration
tags: [fredapi, packaging, pyproject, migration, configuration]

# Dependency graph
requires:
  - phase: 15-03
    provides: "FredProvider integration skeleton with working fredapi passthrough"
  - phase: 15-04
    provides: "Reliability features (rate limiting, caching, circuit breaker, quality validation)"
provides:
  - "Optional dependency extras [fred], [fed], [economic] in pyproject.toml"
  - "Configuration template economic_data.env.example"
  - "Migration documentation and scanning tool"
affects: [16-users, 17-deployment, future-economic-integration]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Optional dependency group pattern", "Migration tool using AST scanning"]

key-files:
  created:
    - pyproject.toml
    - economic_data.env.example
    - docs/migration/ECONOMIC_DATA.md
    - src/ta_lab2/integrations/economic/migration_tool.py
  modified:
    - pyproject.toml

key-decisions:
  - "Three-tier optional dependency structure ([fred], [fed], [economic]) for maximum flexibility"
  - "Configuration follows existing ta_lab2 .env pattern (db_config.env, openai_config.env)"
  - "AST-based migration tool for accurate import detection (not regex)"
  - "11 migration mappings covering fredtools2 and fedtools2 packages"

patterns-established:
  - "Optional dependency extras pattern: individual + combined group"
  - "Environment configuration template with comprehensive documentation"
  - "Migration tool architecture: scan_file → scan_directory → format_report"

# Metrics
duration: 2min
completed: 2026-02-03
---

# Phase 15 Plan 05: Migration Support - Summary

**Optional dependencies configured with [fred]/[fed]/[economic] extras, config template, migration guide, and AST-based import scanning tool**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-03T13:34:32Z
- **Completed:** 2026-02-03T13:36:41Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added optional dependency extras to pyproject.toml enabling flexible installation
- Created comprehensive configuration template following ta_lab2 patterns
- Built complete migration support (documentation + tool) for fredtools2/fedtools2 migration

## Task Commits

Each task was committed atomically:

1. **Task 1: Update pyproject.toml with economic optional dependencies** - `1670be1` (chore)
2. **Task 2: Create economic_data.env.example configuration template** - `c2a68c3` (chore)
3. **Task 3: Create migration documentation and tool** - `a6c656c` (feat)

## Files Created/Modified
- `pyproject.toml` - Added [fred], [fed], [economic] optional dependency extras and updated [all] group
- `economic_data.env.example` - Configuration template with API keys, cache, rate limiting, circuit breaker, and quality settings
- `docs/migration/ECONOMIC_DATA.md` - Comprehensive migration guide with before/after examples, feature comparison, and detailed usage
- `src/ta_lab2/integrations/economic/migration_tool.py` - AST-based tool that scans Python files for fredtools2/fedtools2 imports and suggests replacements

## Decisions Made

**1. Three-tier optional dependency structure**
- Individual provider extras: `[fred]`, `[fed]` (future)
- Combined extra: `[economic]` installs all providers
- Enables `pip install ta_lab2[fred]` or `pip install ta_lab2[economic]` based on user needs

**2. Configuration template follows existing patterns**
- Named `economic_data.env.example` matching `db_config.env`, `openai_config.env` pattern
- Comprehensive documentation with three usage options (dotenv, env vars, direct pass)
- Includes optional settings for cache, rate limiting, circuit breaker, quality validation

**3. AST-based migration tool**
- Uses Python's ast module for accurate import detection (not regex-based)
- Scans for both `import fredtools2` and `from fredtools2 import ...` patterns
- 11 migration mappings covering both archived packages
- Excludes directories like __pycache__, .venv, .git, .archive

**4. Migration guide covers all support dimensions**
- Quick migration examples (before/after code)
- Feature comparison table
- Installation and configuration instructions
- Detailed examples for common use cases
- References to archived packages and alternatives

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all tasks completed without issues.

## User Setup Required

None - no external service configuration required. Users who want to use economic data integrations should:
1. Copy `economic_data.env.example` to `economic_data.env`
2. Add their FRED_API_KEY (get free key from https://fred.stlouisfed.org/docs/api/api_key.html)
3. Install optional dependencies: `pip install ta_lab2[fred]` or `pip install ta_lab2[economic]`

## Next Phase Readiness

**Ready for:**
- Phase 16 (users): Economic integrations packaged and documented
- Phase 17 (deployment): Optional dependencies properly configured
- Future economic integration work: Foundation and migration support complete

**Migration support complete:**
- Documentation guides users from fredtools2/fedtools2 to new integrations
- Tool scans code to identify required changes
- Configuration template simplifies setup

**No blockers or concerns.**

---
*Phase: 15-economic-data-strategy*
*Completed: 2026-02-03*
