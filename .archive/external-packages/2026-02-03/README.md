# External Packages Archive

**Archived:** 2026-02-03
**Phase:** 15-economic-data-strategy
**Decision:** Archive (not integrate)

## Contents

### fredtools2 (167 lines)
PostgreSQL-backed FRED data ingestion with CLI.
- **Entry point:** `fred [init|releases|series]`
- **Dependencies:** requests, psycopg2-binary, python-dotenv

### fedtools2 (659 lines)
ETL consolidation of Federal Reserve policy target datasets.
- **Entry point:** `fedtools2 [--config] [--plot]`
- **Dependencies:** pandas, numpy, pyyaml, matplotlib, sqlalchemy, python-dotenv
- **Unique logic:** TARGET_MID, TARGET_SPREAD, regime labels

## Archive Rationale

1. **Zero usage:** No imports from either package in ta_lab2 codebase
2. **Ecosystem alternatives:** fredapi and fedfred are superior (see ALTERNATIVES.md)
3. **Maintenance burden:** Custom wrappers add technical debt
4. **Preservation:** Archive preserves code for reference without cost

## Restoration

To restore for use:

1. Copy package directory: `cp -r .archive/external-packages/2026-02-03/fredtools2 ./lib/`
2. Install: `pip install -e ./lib/fredtools2`
3. Configure environment variables (see package README or dependencies_snapshot.txt)
4. Run: `fred init` or `fedtools2`

## Files

- `manifest.json` - Complete file listing with SHA256 checksums
- `ALTERNATIVES.md` - Ecosystem alternatives comparison (4 dimensions)
- `dependencies_snapshot.txt` - Full dependency tree for reproducibility
- `fredtools2/` - Preserved package source
- `fedtools2/` - Preserved package source

## Ecosystem Alternatives

For new economic data integration, use:
- **fredapi** (https://pypi.org/project/fredapi/) - Most established FRED client
- **fedfred** (https://pypi.org/project/fedfred/) - Modern alternative with async/caching

See ALTERNATIVES.md for detailed comparison.
