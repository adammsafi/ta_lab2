# v0.5.0 Ecosystem Reorganization Guide

**Version:** 1.0.0
**Reorganization period:** 2026-02-02 to 2026-02-04
**Phases covered:** 11-17

This document provides a comprehensive record of the v0.5.0 ecosystem reorganization, which consolidated four external directories (ProjectTT, Data_Tools, fredtools2, fedtools2) into the unified ta_lab2 structure.

## Executive Summary

| Source Directory | Files | Action | Destination |
|------------------|-------|--------|-------------|
| ProjectTT | 62 | Archive + Convert | .archive/documentation/ + docs/ |
| Data_Tools | 51 | Migrate + Archive | src/ta_lab2/tools/data_tools/ + .archive/data_tools/ |
| fredtools2 | 13 | Archive | .archive/external-packages/ |
| fedtools2 | 29 | Archive | .archive/external-packages/ |
| **Total** | **155** | | |

## Key Principles

1. **NO DELETION** - All files preserved in git history and/or .archive/
2. **Memory-first** - All moves tracked in Mem0 memory system
3. **Manifest tracking** - Every archive category has manifest.json with SHA256 checksums
4. **Import continuity** - Migration guide enables updating old imports

## Directory Structure Diagrams

See [docs/diagrams/](diagrams/) for visual representations:
- `before_tree.txt` - Pre-reorganization structure (v0.4.0)
- `after_tree.txt` - Post-reorganization structure (v0.5.0)
- `data_flow.mmd` - Mermaid diagram showing file flow
- `package_structure.mmd` - Internal ta_lab2 organization

## Decision Tracking

All major decisions documented in [docs/manifests/](manifests/):
- `decisions.json` - Structured decision data with $schema validation
- `decisions-schema.json` - JSON Schema for validation
- `DECISIONS.md` - Human-readable rationale

---

## Table of Contents

1. [ProjectTT Migration](#projecttt-migration)
2. [Data_Tools Migration](#data_tools-migration)
3. [fredtools2 Archive](#fredtools2-archive)
4. [fedtools2 Archive](#fedtools2-archive)
5. [Migration Guide](#migration-guide)
6. [Verification](#verification)

---
