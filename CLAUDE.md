# ta_lab2 -- Project Instructions for Claude Code

## Project Overview

ta_lab2 is a quantitative trading research and paper-trading system built in Python.
It includes 90+ PostgreSQL tables, 266+ scripts, and covers price bars, features,
signals, regimes, backtesting, paper execution, risk management, and drift monitoring.
See `.memory/MEMORY.md` for the full module map, table families, and critical gotchas.

## MCP Memory Server

The `ta-lab2-memory` MCP server provides semantic search over 3,763+ project memories
stored in Qdrant. It is registered in `.mcp.json` and available when Docker is running.

### Prerequisites

Start the server before your session:

```bash
docker compose -f docker/docker-compose.yml up -d
```

### Available Tools

| Tool | Purpose |
|------|---------|
| `memory_search` | Semantic search over project memories. Returns text, metadata, similarity scores. |
| `memory_context` | Pre-formatted markdown context for prompt injection. |
| `memory_store` | Store new memories (decisions, patterns, bug fixes) for future sessions. |
| `memory_stats` | Collection statistics (total memories, categories, staleness). |
| `memory_health` | Health check for Qdrant connectivity and embedding service. |
| `list_categories` | Discover available memory categories for filtered searches. |

### When to Use memory_search

- Before starting work in an unfamiliar area of the codebase
- When encountering unknown patterns or conventions
- When you need historical context about why a decision was made
- When debugging an issue that may have been solved before
- Example queries: "How does EMA calculation work?", "vectorbt gotchas",
  "Why did we choose Qdrant over ChromaDB?"

### When to Use memory_store

- After discovering important patterns or conventions
- After making architectural decisions with non-obvious rationale
- After resolving tricky bugs (store the root cause and fix)
- Always include a `source` tag (e.g., `source='claude_code'`) in metadata

### When NOT to Query

- For routine tasks in well-understood areas (standard CRUD, simple refactors)
- For simple code changes following existing patterns visible in the file
- When the answer is already in the current file or its imports

## Key Conventions

- **Database:** PostgreSQL + SQLAlchemy. Connection via `db_config.env` or `TARGET_DB_URL`.
- **PKs:** Data tables use `(id, venue_id, ts, tf)`, EMA tables add `period`, `_u` tables add `alignment_source`.
- **venue_id:** `dim_venues` maps SMALLINT venue_id to venue names (1=CMC_AGG, 2=HYPERLIQUID, etc.). All analytics tables include `venue_id` in their PK. Default=1 (CMC_AGG).
- **Table names:** No `cmc_` prefix — tables are `price_bars_multi_tf`, `ema_multi_tf`, etc. Exceptions: `cmc_da_ids`, `cmc_da_info`, `cmc_exchange_map`, `cmc_exchange_info`, `cmc_price_histories7` (genuinely CMC-only).
- **Upsert pattern:** Temp table + `ON CONFLICT DO UPDATE/NOTHING`.
- **Large tables:** Always batch by `id` to avoid multi-hour single transactions.
- **dim_timeframe:** Column is `tf_days_nominal` (NOT `tf_days`).
- **Pandas tz-aware:** `series.values` returns tz-NAIVE numpy. Fix: `.tz_localize("UTC")`.
- **No deletion:** Always archive (files, data, columns).

For the full list of gotchas, table families, CLI entry points, and module map,
see `.memory/MEMORY.md`.
