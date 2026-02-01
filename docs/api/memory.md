# Memory API Reference

The Memory API provides REST endpoints for interacting with the ta_lab2 memory system (Mem0 + Qdrant).

## Base URL

```
http://localhost:8000/api/v1/memory
```

## Authentication

Currently no authentication required (internal use). Future versions may add API key authentication.

## Endpoints

### Search Memories

**POST** `/api/v1/memory/search`

Search for semantically similar memories.

**Request Body:**
```json
{
  "query": "EMA crossover strategy",
  "max_results": 10,
  "min_similarity": 0.7,
  "memory_type": "signal"
}
```

**Parameters:**
| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | Yes | - | Search query text |
| max_results | integer | No | 5 | Maximum results to return (1-20) |
| min_similarity | float | No | 0.7 | Minimum similarity threshold (0.0-1.0) |
| memory_type | string | No | null | Filter by memory type |

**Response:**
```json
{
  "query": "EMA crossover strategy",
  "memories": [
    {
      "memory_id": "mem_abc123",
      "content": "EMA crossover signals trigger when fast EMA crosses above slow EMA",
      "similarity": 0.89,
      "metadata": {
        "created_at": "2026-01-15T10:30:00Z",
        "tags": ["signal", "ema"]
      }
    }
  ],
  "count": 1,
  "threshold_used": 0.7
}
```

### Get Memory Context

**POST** `/api/v1/memory/context`

Get formatted context for AI prompt injection.

**Request Body:**
```json
{
  "query": "How to calculate multi-timeframe EMAs",
  "max_memories": 5,
  "min_similarity": 0.7,
  "max_length": 4000
}
```

**Parameters:**
| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| query | string | Yes | - | Query for context retrieval |
| max_memories | integer | No | 5 | Maximum memories (1-10) |
| min_similarity | float | No | 0.7 | Minimum similarity (0.0-1.0) |
| max_length | integer | No | 4000 | Maximum context length (100-10000) |

**Response:**
```json
{
  "query": "How to calculate multi-timeframe EMAs",
  "context": "--- Relevant Context ---\n1. Multi-timeframe EMAs use dim_timeframe for alignment\n2. ...",
  "memory_count": 3,
  "estimated_tokens": 256
}
```

### Get Memory Statistics

**GET** `/api/v1/memory/stats`

Get memory store statistics.

**Response:**
```json
{
  "total_memories": 3763,
  "collection_name": "orchestrator_mem0",
  "distance_metric": "cosine",
  "is_valid": true
}
```

### Get Memory Types

**GET** `/api/v1/memory/types`

List available memory types for filtering.

**Response:**
```json
{
  "types": ["feature", "signal", "orchestrator", "system"],
  "count": 4
}
```

### Health Check

**GET** `/api/v1/memory/health`

Check memory system health with detailed component status.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| staleness_days | int | 90 | Days threshold for stale detection |

**Response:**
```json
{
  "total_memories": 3763,
  "healthy": 3500,
  "stale": 200,
  "deprecated": 50,
  "missing_metadata": 13,
  "age_distribution": {
    "0-30d": 1200,
    "30-60d": 800,
    "60-90d": 600,
    "90+d": 1163
  },
  "scan_timestamp": "2026-02-01T23:00:00Z"
}
```

### Get Stale Memories

**GET** `/api/v1/memory/health/stale`

List memories not verified in 90+ days for review.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| staleness_days | int | 90 | Days threshold for stale detection |
| limit | int | 50 | Maximum results to return |

**Response:**
```json
[
  {
    "id": "mem_abc123",
    "content_preview": "Old memory content that needs verification...",
    "last_verified": "2025-10-15T10:30:00Z",
    "age_days": 109
  }
]
```

### Refresh Verification

**POST** `/api/v1/memory/health/refresh`

Mark memories as verified (refreshes last_verified timestamp).

**Request Body:**
```json
{
  "memory_ids": ["mem_abc123", "mem_def456"]
}
```

**Response:**
```json
{
  "refreshed": 2,
  "memory_ids": ["mem_abc123", "mem_def456"]
}
```

### Check Conflicts

**POST** `/api/v1/memory/conflict/check`

Check if content conflicts with existing memories using semantic similarity.

**Request Body:**
```json
{
  "content": "RSI below 30 indicates oversold conditions",
  "user_id": "orchestrator",
  "similarity_threshold": 0.85
}
```

**Response:**
```json
{
  "has_conflicts": true,
  "conflicts": [
    {
      "memory_id": "mem_xyz789",
      "content": "RSI values under 30 suggest oversold market",
      "similarity": 0.92,
      "metadata": {
        "component": "signals"
      }
    }
  ]
}
```

### Add with Conflict Resolution

**POST** `/api/v1/memory/conflict/add`

Add memory with automatic LLM-powered conflict detection and resolution.

**Request Body:**
```json
{
  "content": "ATR expansion indicates increased volatility",
  "user_id": "orchestrator",
  "metadata": {
    "component": "signals",
    "tags": ["atr", "volatility"]
  },
  "role": "user"
}
```

**Response:**
```json
{
  "memory_id": "mem_new123",
  "operation": "added",
  "confidence": 0.95,
  "reason": "No conflicts detected with existing memories"
}
```

**Operations:**
- `added`: New memory added (no conflicts)
- `updated`: Existing memory updated (conflict resolved)
- `merged`: Multiple memories merged (duplicate detected)
- `skipped`: Not added (conflict unresolved)

## Error Responses

All endpoints return standard error format on failure:

```json
{
  "detail": "Memory not found"
}
```

**Status Codes:**
- 200: Success
- 400: Bad request (invalid parameters)
- 404: Resource not found
- 500: Internal server error

## Running the API

### Development Mode

```bash
# Start the Memory API server
uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --host 0.0.0.0 --port 8000

# With auto-reload for development
uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --reload
```

### Production Mode

```bash
# With multiple workers (requires gunicorn)
gunicorn ta_lab2.tools.ai_orchestrator.memory.api:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| QDRANT_SERVER_MODE | No | Set to "true" for server mode (default: true) |
| QDRANT_URL | No | Qdrant server URL (default: http://localhost:6333) |
| OPENAI_API_KEY | Yes | OpenAI API key for embeddings |

### Prerequisites

Before starting the API, ensure Qdrant server is running:

```bash
# Using Docker (recommended)
docker run -d -p 6333:6333 \
  -v qdrant_data:/qdrant/storage \
  --name qdrant \
  qdrant/qdrant

# Verify Qdrant is running
curl http://localhost:6333/health
```

## Interactive Documentation

FastAPI provides automatic interactive API documentation:

- **Swagger UI**: `http://localhost:8000/docs` - Try endpoints interactively
- **ReDoc**: `http://localhost:8000/redoc` - Alternative documentation view
- **OpenAPI JSON**: `http://localhost:8000/openapi.json` - Machine-readable spec

## Python Client Usage

For programmatic access from Python:

```python
from ta_lab2.tools.ai_orchestrator.memory import MemoryService

# Initialize service
memory = MemoryService()

# Add memory
memory.add(
    "Multi-timeframe EMAs use dim_timeframe for alignment",
    metadata={"component": "features"}
)

# Search memories
results = memory.search("How are EMAs calculated?", limit=5)
for result in results:
    print(f"{result.similarity:.2f}: {result.content}")

# Health check
is_healthy = memory.health_check()
print(f"Memory system healthy: {is_healthy}")
```

## API Versioning

Current version: **v1** (base path: `/api/v1/memory`)

Future versions will maintain backward compatibility or provide migration paths when breaking changes are necessary.
