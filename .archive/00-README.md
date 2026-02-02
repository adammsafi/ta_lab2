# .archive/ Directory

**Purpose:** Archive for files removed from active codebase during v0.5.0 reorganization.

**NO DELETION Policy:** Files in .archive/ are preserved in git history. Never use `rm -rf` on this directory. Files remain for audit trails, rollback capability, and historical reference.

## Directory Structure

```
.archive/
├── 00-README.md           # This file
├── deprecated/            # Code no longer needed
│   ├── manifest.json      # File inventory for this category
│   └── YYYY-MM-DD/        # Date subdirectories
│       └── *.py           # Archived files
├── refactored/            # Code replaced during refactor
│   ├── manifest.json
│   └── YYYY-MM-DD/
├── migrated/              # Code moved to new location
│   ├── manifest.json
│   └── YYYY-MM-DD/
└── documentation/         # Archived docs (Word, Excel, etc.)
    ├── manifest.json
    └── YYYY-MM-DD/
```

## Archive Categories

### deprecated
Code that is no longer needed. Includes:
- Backup artifacts
- Old implementations superseded by new approaches
- Experimental code that didn't work out
- Dead code identified during cleanup

### refactored
Code that was replaced by a refactored version. Includes:
- Original files when `*_refactored.py` versions exist
- Code rewritten for clarity or performance
- Legacy implementations before architectural changes

### migrated
Code that was moved to a new location within ta_lab2. Includes:
- Files relocated during reorganization
- Modules consolidated into new structure
- Code moved between packages

### documentation
Non-code files removed during cleanup. Includes:
- Word documents (.docx)
- Excel spreadsheets (.xlsx)
- Planning documents
- Research notes
- Legacy documentation

## Organization

**Category-first structure:** Files are organized by category (deprecated, refactored, migrated, documentation) first, then by date. This makes it easy to browse archives by type.

**Date subdirectories:** Within each category, files are organized into `YYYY-MM-DD` date directories representing when they were archived.

**Manifests:** Each category has a `manifest.json` file tracking all archived files in that category, with metadata including original paths, checksums, and archive reasons.

## History Verification

Git history is preserved through archive operations using `git mv`. To verify history preservation:

```bash
# Check that history follows through the move
git log --follow --oneline .archive/category/YYYY-MM-DD/filename.py
```

**Expected output:** 2+ commits visible (the original creation commit(s) AND the archive move commit)

**Warning:** If `git log --follow` shows only 1 commit (the move), the operation was NOT a pure move and history may be lost. Pure moves must not include content changes in the same commit.

## Test Verification

A permanent test artifact exists at `.archive/test_git_history/test_file.py` demonstrating history preservation. Check it:

```bash
git log --follow --oneline .archive/test_git_history/test_file.py
```

This test file should show at least 2 commits, proving that `git mv` correctly preserves history.

## Usage Guidelines

1. **Never delete files manually** - Always use `git mv` for archiving
2. **One category per file** - Each file goes in exactly one category
3. **Update manifests** - Keep manifest.json files current with archive operations
4. **Verify history** - After archiving, check that `git log --follow` works
5. **Document reason** - Include archive_reason in manifest entries

## Manifest Schema

Each category's manifest.json follows this schema:

```json
{
  "$schema": "https://ta_lab2.local/schemas/archive-manifest/v1.0.0",
  "version": "1.0.0",
  "category": "deprecated|refactored|migrated|documentation",
  "created_at": "ISO 8601 timestamp",
  "total_files": 0,
  "total_size_bytes": 0,
  "files": [
    {
      "original_path": "path/to/original/file.py",
      "archive_path": ".archive/category/YYYY-MM-DD/file.py",
      "action": "moved|deprecated|refactored",
      "timestamp": "ISO 8601 timestamp",
      "sha256_checksum": "hex string",
      "size_bytes": 12345,
      "commit_hash": "git commit hash",
      "phase_number": "12",
      "archive_reason": "Description of why archived"
    }
  ]
}
```

---

**Created:** 2026-02-02 (Phase 12-01: Archive Foundation)
**Version:** 1.0.0
