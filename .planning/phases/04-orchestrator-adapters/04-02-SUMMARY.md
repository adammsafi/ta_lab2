---
phase: 04-orchestrator-adapters
plan: 02
subsystem: orchestrator
tags: [async, chatgpt, openai, retry, streaming, testing]
completed: 2026-01-29
duration: 16 min

# Dependencies
requires:
  - 04-01  # AsyncBasePlatformAdapter base class

provides:
  - AsyncChatGPTAdapter with OpenAI API integration
  - Retry logic with exponential backoff
  - Token tracking and cost calculation
  - Streaming support

affects:
  - 04-04  # Gemini async adapter (will use same retry patterns)
  - 05-*   # Orchestrator manager will route tasks to ChatGPT

# Tech Stack
tech-stack:
  added:
    - tenacity: "Retry library with exponential backoff"
  patterns:
    - "Async context manager for resource cleanup"
    - "Retry decorator with jitter per AWS/OpenAI best practices"
    - "Token usage tracking from API responses"
    - "Cost calculation based on model pricing"

# File Tracking
key-files:
  created:
    - src/ta_lab2/tools/ai_orchestrator/retry.py
    - tests/orchestrator/test_chatgpt_adapter.py
  modified:
    - src/ta_lab2/tools/ai_orchestrator/adapters.py

# Decisions
decisions:
  - id: D-04-02-01
    what: "Use tenacity library for retry logic"
    why: "Mature library with exponential backoff, jitter, and before_sleep logging"
    alternatives: ["Manual retry implementation", "backoff library"]
    chosen: "tenacity"

  - id: D-04-02-02
    what: "Default model: gpt-4o-mini"
    why: "Cost efficiency - Input $0.15/1M, Output $0.60/1M vs gpt-4 $30/$60 per 1M"
    impact: "20x cost savings for most tasks"

  - id: D-04-02-03
    what: "Retry on RateLimitError and APIError"
    why: "Rate limits are transient; APIError may include retryable 5xx errors"
    pattern: "5 attempts, 1s->32s exponential backoff with 3s jitter"

  - id: D-04-02-04
    what: "Store pending tasks as asyncio.Task objects"
    why: "Enables status tracking (RUNNING/COMPLETED/CANCELLED) and cancellation"
    tradeoff: "Slightly more memory overhead vs dict of futures"
---

# Phase 4 Plan 2: ChatGPT Async Adapter Summary

**One-liner:** OpenAI AsyncChatGPTAdapter with retry on rate limits, token tracking, streaming, and 13 comprehensive tests

## What Was Built

Implemented complete async ChatGPT adapter with:

1. **retry.py module**
   - `retry_on_rate_limit` decorator (5 attempts, exponential backoff with jitter)
   - `retry_on_transient` decorator for network errors
   - Handles OpenAI RateLimitError and APIError gracefully

2. **AsyncChatGPTAdapter class**
   - Full lifecycle: submit_task, get_status, get_result, stream_result, cancel_task
   - Async context manager (`async with`) for client initialization and cleanup
   - Token usage tracking from API response
   - Cost calculation: Input $0.15/1M, Output $0.60/1M tokens
   - execute_streaming method for direct streaming responses
   - Proper CancelledError handling (always re-raised)

3. **Comprehensive test suite**
   - 13 test cases covering all scenarios
   - Mocked AsyncOpenAI client (no real API calls)
   - Tests: init, execution, timeout, cancellation, context manager, constraints, unknown tasks

## Technical Decisions Made

### Retry Strategy
- **Max attempts:** 5 (per OpenAI best practices)
- **Backoff:** Exponential jitter (1s->32s with 3s jitter)
- **Exceptions:** RateLimitError, APIError
- **Logging:** Warning level before each retry via tenacity before_sleep_log

### Token Tracking
- Extract from `response.usage.total_tokens`
- Store input/output tokens separately in metadata
- Calculate cost: `(input * 0.15 + output * 0.60) / 1_000_000`

### Streaming
- Two approaches:
  1. `stream_result(task_id)` - fallback yields complete result
  2. `execute_streaming(task)` - direct streaming via API stream=True
- Stream options include usage tracking: `stream_options={"include_usage": True}`

### Task Management
- Pending tasks stored as `dict[str, asyncio.Task]`
- Status derived from asyncio.Task state: done()/cancelled()/exception()
- Cancellation propagates to underlying asyncio task

## Implementation Highlights

**Async context manager pattern:**
```python
async with AsyncChatGPTAdapter(api_key="...") as adapter:
    task_id = await adapter.submit_task(task)
    result = await adapter.get_result(task_id)
# Client automatically closed on exit
```

**Retry decorator usage:**
```python
@retry_on_rate_limit()
async def make_request():
    return await self._client.chat.completions.create(...)
```

**CancelledError propagation:**
```python
except asyncio.CancelledError:
    raise  # Always re-raise, never swallow
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed missing Task import in get_result**
- **Found during:** Task 3 test execution
- **Issue:** `NameError: name 'Task' is not defined` in get_result method for unknown tasks
- **Fix:** Changed import to `from .core import Task as CoreTask` to avoid naming conflict
- **Files modified:** src/ta_lab2/tools/ai_orchestrator/adapters.py
- **Commit:** fe505bb (included in test commit)

**2. [Rule 1 - Bug] Fixed async mock side effects in tests**
- **Found during:** Initial test run (4 failures)
- **Issue:** `AsyncMock(side_effect=lambda: asyncio.sleep(10))` returns unawaited coroutine
- **Fix:** Changed to proper async function: `async def slow_call(**kwargs): await asyncio.sleep(10)`
- **Files modified:** tests/orchestrator/test_chatgpt_adapter.py
- **Commit:** fe505bb

**3. [Rule 1 - Bug] Fixed patch path for AsyncOpenAI**
- **Found during:** test_context_manager_init_close failure
- **Issue:** Patching wrong module path `ta_lab2.tools.ai_orchestrator.adapters.AsyncOpenAI`
- **Fix:** Changed to `openai.AsyncOpenAI` (patch where imported from, not where used)
- **Files modified:** tests/orchestrator/test_chatgpt_adapter.py
- **Commit:** fe505bb

## Testing

**Test Coverage:**
- 13 test cases, all passing
- Mock-based (no real API calls)
- Test classes:
  - TestAsyncChatGPTAdapterInit (3 tests)
  - TestAsyncChatGPTAdapterExecution (5 tests)
  - TestAsyncChatGPTAdapterContextManager (2 tests)
  - TestTaskWithConstraints (1 test)
  - TestUnknownTask (2 tests)

**Key test scenarios:**
- Initialization with/without API key
- Task submission returns valid task_id
- Status tracking (RUNNING, COMPLETED, CANCELLED)
- Successful result retrieval with token tracking
- Timeout handling
- Task cancellation
- Context manager initialization and cleanup
- Constraints passed to API (model, max_tokens, temperature)
- Unknown task_id handling

## Verification Results

All verification checks passed:

1. Module imports: ✓
```python
from ta_lab2.tools.ai_orchestrator.retry import retry_on_rate_limit
from ta_lab2.tools.ai_orchestrator.adapters import AsyncChatGPTAdapter
```

2. Adapter status: ✓
```python
{
  'name': 'ChatGPT (Async)',
  'is_implemented': True,
  'status': 'working',
  'model': 'gpt-4o-mini',
  'capabilities': ['OpenAI API integration', 'Streaming responses', ...]
}
```

3. Tests: ✓ 13 passed, 13 warnings (deprecation warnings only)

## Commits

1. `aa90f92` - feat(04-02): create retry module with exponential backoff
2. `62de45f` - feat(04-02): implement AsyncChatGPTAdapter with OpenAI API
3. `fe505bb` - test(04-02): add comprehensive tests for AsyncChatGPTAdapter

## Integration Points

**Upstream dependencies:**
- Requires AsyncBasePlatformAdapter from 04-01
- Imports Task, TaskType, TaskStatus, Platform from core.py

**Downstream consumers:**
- Orchestrator manager (05-*) will route CODE_GENERATION tasks to ChatGPT
- Can be used standalone via async context manager
- Memory integration (06-*) will provide context dict for tasks

## Next Phase Readiness

**Ready for:**
- 04-03: Claude Code async adapter (can use same retry patterns)
- 04-04: Gemini async adapter (can use same retry/test patterns)
- 05-01: Orchestrator manager integration

**Provides:**
- Working ChatGPT task execution
- Token usage tracking for quota management
- Cost calculation for budget optimization
- Retry logic pattern for other adapters

**No blockers for next phase.**

## Performance Notes

- **Execution time:** ~16 minutes (3 tasks)
- **Test runtime:** 39 seconds (13 tests with async operations)
- **Default timeout:** 60s for API calls, 300s for get_result
- **Retry overhead:** Up to 32s backoff on 5th retry (rare)

## Lessons Learned

1. **AsyncMock side effects:** Must return proper async functions, not lambda returning coroutine
2. **Patch paths:** Patch where imported FROM (openai.AsyncOpenAI), not where used
3. **Import naming:** Use `as CoreTask` to avoid conflicts with TYPE_CHECKING imports
4. **CancelledError:** Always re-raise - swallowing causes silent task cancellation
5. **Token tracking:** API response.usage provides detailed breakdown for cost calculation
