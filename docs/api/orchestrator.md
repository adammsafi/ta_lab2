# Orchestrator CLI Reference

The ta_lab2 orchestrator provides command-line tools for AI task coordination and quota management across multiple LLM platforms.

## Installation

```bash
# Install with orchestrator dependencies
pip install -e ".[orchestrator]"
```

This includes OpenAI, Anthropic, and Google AI SDKs.

## Commands

### Submit Task

Submit a single task to the AI orchestrator with automatic platform routing.

```bash
ta-lab2 orchestrator submit \
  --prompt "Analyze BTC price trends for Q1 2026" \
  --type data_analysis \
  --platform gemini \
  --timeout 300 \
  --output results/btc_analysis.json
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| --prompt, -p | string | (required) | Task prompt text |
| --type, -t | string | code_generation | Task type (see Task Types) |
| --platform | string | auto | Target platform (claude_code/chatgpt/gemini) |
| --chain-id | string | - | Workflow chain ID for tracking |
| --timeout | int | 300 | Timeout in seconds |
| --output, -o | string | - | Output file path for results |

**Task Types:**
- `code_generation`: Generate new code
- `research`: Research and analysis
- `data_analysis`: Data analysis tasks
- `refactoring`: Code refactoring
- `documentation`: Documentation writing
- `code_review`: Code review tasks
- `sql_db_work`: Database queries and migrations
- `testing`: Test generation
- `debugging`: Debug and fix issues
- `planning`: Planning and design

**Platform Options:**
- `claude_code`: Anthropic Claude (best for reasoning)
- `chatgpt`: OpenAI GPT-4o-mini (cost-efficient default)
- `gemini`: Google Gemini (free tier: 1500 req/day)
- (default): Auto-route using cost optimization

**Example Output:**
```
Task ID: gemini_20260201_abc123
Platform: gemini
Success: True
Duration: 8.45s
Cost: $0.0000

--- Output ---
BTC price trends for Q1 2026 show...

Result saved to: results/btc_analysis.json
```

### Batch Submit

Submit multiple tasks from JSON file with parallel execution.

```bash
ta-lab2 orchestrator batch \
  --input batch_tasks.json \
  --output results/ \
  --parallel 5 \
  --fallback
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| --input, -i | string | (required) | Input JSON file with tasks |
| --output, -o | string | - | Output JSON file for results |
| --parallel | int | 5 | Max parallel tasks (concurrency limit) |
| --fallback | flag | false | Enable automatic platform fallback on failures |

**Input JSON Format:**

```json
[
  {
    "prompt": "Analyze asset 1",
    "type": "data_analysis",
    "platform": "gemini",
    "timeout": 300,
    "metadata": {"asset_id": 1}
  },
  {
    "prompt": "Analyze asset 2",
    "type": "data_analysis"
  }
]
```

**Output JSON Format:**

```json
{
  "total_tasks": 2,
  "success_count": 2,
  "failure_count": 0,
  "success_rate": 1.0,
  "total_cost": 0.0045,
  "total_duration": 15.23,
  "results": [
    {
      "task_id": "gemini_20260201_abc123",
      "platform": "gemini",
      "success": true,
      "output": "Analysis results...",
      "error": null,
      "cost": 0.0000
    }
  ]
}
```

**Example Output:**
```
Loaded 3 tasks from batch_tasks.json

=== Batch Complete ===
Total: 3 tasks
Success: 3
Failed: 0
Success Rate: 100.0%
Total Cost: $0.0045
Total Duration: 12.34s

By Platform:
  gemini: 2/2 success, $0.0000
  chatgpt: 1/1 success, $0.0045

Results saved to: results/batch_20260201.json
```

### Status

Show orchestrator and platform status.

```bash
ta-lab2 orchestrator status
ta-lab2 orchestrator status --format json
```

**Options:**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| --format | string | text | Output format (text/json) |

**Example Output (text):**
```
=== Orchestrator Status ===

Adapters:
  [OK] claude_code: ready
  [OK] chatgpt: ready
  [OK] gemini: ready

=== Quota Status ===
Platform      Used    Limit    Remaining    Reset
-----------   -----   ------   ----------   ---------------
Gemini        450     1500     1050         2026-02-02 00:00 UTC
```

**Example Output (json):**
```json
{
  "adapters": {
    "claude_code": {
      "is_implemented": true,
      "status": "ready"
    },
    "chatgpt": {
      "is_implemented": true,
      "status": "ready"
    },
    "gemini": {
      "is_implemented": true,
      "status": "ready"
    }
  },
  "quota": {
    "gemini": {
      "used": 450,
      "limit": 1500,
      "remaining": 1050,
      "reset_at": "2026-02-02T00:00:00Z"
    }
  }
}
```

### Quota Management

View and manage API quota across platforms.

#### View Quota

```bash
ta-lab2 orchestrator quota
ta-lab2 orchestrator quota --format json
```

**Example Output:**
```
=== Quota Status ===
Platform      Used    Limit    Remaining    Reset
-----------   -----   ------   ----------   ---------------
Gemini        450     1500     1050         2026-02-02 00:00 UTC
ChatGPT       $2.50   $100     $97.50       2026-03-01 00:00 UTC
Claude        $1.20   $50      $48.80       2026-03-01 00:00 UTC

Warnings:
  - Gemini at 30% (450/1500)
```

**Alert Thresholds:**
- 50%: Daily checkpoint warning
- 80%: High usage warning
- 90%: Critical threshold warning

### Cost Tracking

View cost summaries by date, chain, or platform.

#### Session Summary

```bash
ta-lab2 orchestrator costs
ta-lab2 orchestrator costs --date 2026-02-01
ta-lab2 orchestrator costs --format json
```

**Example Output:**
```
=== Cost Summary (2026-02-01) ===
Total Cost: $4.35
Total Tasks: 47

By Platform:
  Gemini:  15 tasks, $0.00
  ChatGPT: 28 tasks, $3.45
  Claude:   4 tasks, $0.90

By Task Type:
  code_generation: 20 tasks, $2.10
  data_analysis:   15 tasks, $1.50
  documentation:   12 tasks, $0.75
```

#### Chain-Specific Costs

```bash
ta-lab2 orchestrator costs --chain-id workflow_123
ta-lab2 orchestrator costs --chain-id workflow_123 --format json
```

**Example Output:**
```
Chain: workflow_123
Total Cost: $1.25
Tasks: 8

Task Breakdown:
  gemini_20260201_abc123: $0.00 (gemini)
  chatgpt_20260201_def456: $0.45 (chatgpt)
  chatgpt_20260201_ghi789: $0.35 (chatgpt)
  ...
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| OPENAI_API_KEY | For ChatGPT | OpenAI API key |
| ANTHROPIC_API_KEY | For Claude | Anthropic API key |
| GOOGLE_API_KEY | For Gemini | Google AI API key |
| ORCHESTRATOR_DB_PATH | No | SQLite path for cost tracking (default: .orchestrator/costs.db) |

**Setup:**

```bash
# Linux/macOS
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GOOGLE_API_KEY="AIza..."

# Windows (PowerShell)
$env:OPENAI_API_KEY="sk-..."
$env:ANTHROPIC_API_KEY="sk-ant-..."
$env:GOOGLE_API_KEY="AIza..."

# Or use .env file (recommended)
cat > .env << EOF
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=AIza...
EOF
```

### Cost Tiers

The orchestrator automatically routes tasks based on cost optimization:

1. **Tier 1 (Free)**: Gemini free tier (1500 requests/day, priority=1)
2. **Tier 2 (Subscription)**: ChatGPT Plus, Claude Pro (priority=2)
3. **Tier 3 (Paid API)**: Direct API calls with per-token billing (priority=3)

**Routing Logic:**
- Try Gemini free tier first (lowest cost)
- Fall back to subscriptions if free tier exhausted
- Fall back to paid APIs if all else exhausted
- Raise RuntimeError if all platforms exhausted

**Platform Hints:**
- If you specify `--platform gemini`, it honors the hint if quota available
- Automatic fallback to cost tiers when specified platform exhausted

## Advanced Usage

### Parallel Batch Processing

Process multiple tasks concurrently with semaphore-based concurrency control:

```bash
# Create batch file
cat > batch.json << EOF
[
  {"prompt": "Analyze asset 1", "metadata": {"asset_id": 1}},
  {"prompt": "Analyze asset 2", "metadata": {"asset_id": 2}},
  {"prompt": "Analyze asset 3", "metadata": {"asset_id": 3}},
  {"prompt": "Analyze asset 4", "metadata": {"asset_id": 4}},
  {"prompt": "Analyze asset 5", "metadata": {"asset_id": 5}}
]
EOF

# Run batch with 3 parallel workers
ta-lab2 orchestrator batch batch.json --parallel 3 --output results/
```

**Concurrency Control:**
- Default: 10 concurrent tasks maximum
- Adaptive scaling: `min(max_concurrent, available_quota // 2)` prevents mid-batch quota exhaustion
- Minimum: 1 concurrent task (always makes progress)

### Task with Memory Context

Leverage the memory system for context-aware tasks:

```bash
# Python API (memory integration built-in)
from ta_lab2.tools.ai_orchestrator import Orchestrator, Task
from ta_lab2.tools.ai_orchestrator.memory import MemoryService

memory = MemoryService()
context = memory.search("EMA crossover BTC", limit=5)

task = Task(
    prompt=f"Continue the EMA analysis. Context: {context}",
    type="data_analysis"
)

orchestrator = Orchestrator()
result = await orchestrator.execute_task(task)
```

### AI-to-AI Handoffs

Chain tasks together with context passing via memory:

```python
from ta_lab2.tools.ai_orchestrator.handoff import create_handoff, load_handoff_context

# Task A creates handoff
handoff = create_handoff(
    summary="Analyzed BTC price trends for Q1 2026",
    full_context={
        "findings": "...",
        "data": {...}
    },
    metadata={"chain_id": "workflow_123"}
)

# Task B loads context
context = load_handoff_context(handoff.context_id)
```

**Handoff Pattern:**
- Full context stored in memory with unique ID
- Brief summary (max 500 chars) passed inline for quick reference
- Fail-fast: RuntimeError if context not found (Task B cannot proceed without Task A)

### Retry and Fallback

Automatic retry with exponential backoff and platform fallback:

```bash
# Single task with fallback
ta-lab2 orchestrator submit \
  --prompt "Complex analysis task" \
  --platform gemini
  # Automatically falls back to chatgpt/claude if gemini fails

# Batch with fallback enabled
ta-lab2 orchestrator batch tasks.json --fallback
```

**Retry Logic:**
- Max retries: 3 per platform
- Backoff: 1s → 2s → 4s (exponential with base delay 1s)
- Jitter: 3s random jitter to prevent thundering herd
- Retryable errors: Rate limits, timeouts, 5xx server errors
- Non-retryable: Auth errors, quota exhausted (fail-fast)

**Platform Fallback:**
- Try all platforms in COST_TIERS order on failure
- Each platform gets full retry cycle before moving to next
- Comprehensive error messages: "All platforms failed. Last error: {error}. Tried: {platforms}"

## Troubleshooting

### Quota Exhausted

**Error:**
```
Error: All platforms exhausted. Tried: gemini, chatgpt, claude
```

**Solution:**
- Wait for quota reset (check reset time with `ta-lab2 orchestrator quota`)
- Add API credits to pay-as-you-go accounts
- Use different platform with available quota

### Rate Limited

**Error:**
```
Error: Rate limited by OpenAI. Retrying in 32s...
```

**Solution:**
- Automatic retry with exponential backoff (no action needed)
- Reduce `--parallel` count for batch operations
- Wait for rate limit window to reset

### Platform Unavailable

**Error:**
```
Error: Platform claude not available. Routing to fallback.
```

**Solution:**
- Automatic fallback to next tier (no action needed)
- Check API key if persistent: `echo $ANTHROPIC_API_KEY`
- Verify platform status at provider's status page

### Authentication Failed

**Error:**
```
Error: Invalid API key for OpenAI
```

**Solution:**
- Verify API key is set: `echo $OPENAI_API_KEY`
- Check API key validity at provider dashboard
- Regenerate API key if compromised
- Update environment variable with new key

### Memory Service Unreachable

**Error:**
```
Error: Failed to connect to memory service
```

**Solution:**
- Verify Qdrant server is running: `curl http://localhost:6333/health`
- Start Qdrant: `docker run -d -p 6333:6333 qdrant/qdrant`
- Check QDRANT_URL environment variable

## Python API

For programmatic access from Python code:

```python
from ta_lab2.tools.ai_orchestrator import AsyncOrchestrator, Task, TaskType, Platform
from ta_lab2.tools.ai_orchestrator.adapters import (
    AsyncChatGPTAdapter,
    AsyncClaudeCodeAdapter,
    AsyncGeminiAdapter
)
from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker
from ta_lab2.tools.ai_orchestrator.routing import TaskRouter

# Initialize components
quota = QuotaTracker()
adapters = {
    Platform.CHATGPT: AsyncChatGPTAdapter(),
    Platform.CLAUDE_CODE: AsyncClaudeCodeAdapter(),
    Platform.GEMINI: AsyncGeminiAdapter(quota_tracker=quota),
}

# Create orchestrator
async with AsyncOrchestrator(
    adapters=adapters,
    router=TaskRouter(),
    quota_tracker=quota,
    max_concurrent=10
) as orchestrator:

    # Submit single task
    task = Task(
        type=TaskType.DATA_ANALYSIS,
        prompt="Analyze BTC price trends",
        platform_hint=Platform.GEMINI
    )
    result = await orchestrator.execute_with_fallback(task)

    # Submit batch with parallel execution
    tasks = [Task(type=TaskType.CODE_GENERATION, prompt=p) for p in prompts]
    aggregated = await orchestrator.execute_parallel_with_fallback(tasks)

    print(f"Success rate: {aggregated.success_rate:.1%}")
    print(f"Total cost: ${aggregated.total_cost:.4f}")
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (all tasks completed successfully) |
| 1 | Task/batch failure (one or more tasks failed) |
| 2 | Invalid arguments or configuration error |

## Version History

- **v0.4.0**: Initial orchestrator release with multi-platform routing, quota management, and cost tracking
- Future versions will add streaming support, custom adapters, and workflow orchestration

## See Also

- [Memory API Reference](memory.md) - REST API for memory system
- [Architecture Documentation](../ARCHITECTURE.md) - System implementation details
- [Deployment Guide](../deployment.md) - Infrastructure setup
