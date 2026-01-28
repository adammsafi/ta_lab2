# Multi-AI Orchestrator Design

**Purpose**: Maximize AI subscription utilization by intelligently routing tasks to Claude Code, ChatGPT, and Gemini based on strengths, cost, and availability.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Task Dispatcher                          │
│  - Analyzes task type, complexity, required capabilities    │
│  - Routes to optimal AI platform                            │
│  - Manages quota and cost optimization                      │
└─────────────────────────────────────────────────────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
┌─────────────┐      ┌─────────────┐      ┌─────────────┐
│ Claude Code │      │  ChatGPT    │      │   Gemini    │
│             │      │             │      │             │
│ - GSD tasks │      │ - Research  │      │ - Analysis  │
│ - Code gen  │      │ - Writing   │      │ - Code rev  │
│ - Refactor  │      │ - Brainstorm│      │ - Data proc │
└─────────────┘      └─────────────┘      └─────────────┘
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                     ┌─────────────────┐
                     │  Result Merger  │
                     │  - Consolidates │
                     │  - Deduplicates │
                     └─────────────────┘
```

---

## Component 1: Task Dispatcher

### Core Responsibilities
1. **Task Classification**: Categorize incoming requests by type and complexity
2. **Platform Selection**: Choose optimal AI based on task requirements
3. **Quota Management**: Track free tier limits, API usage, subscription caps
4. **Cost Optimization**: Prefer free CLI > free API > paid API

### Task Routing Matrix

| Task Type | Primary | Secondary | Fallback | Rationale |
|-----------|---------|-----------|----------|-----------|
| **Code Generation** | Claude Code | ChatGPT Code | Gemini | Claude excels at code, has GSD |
| **Refactoring** | Claude Code | Gemini | ChatGPT | Claude + GSD system best for large refactors |
| **Research** | ChatGPT | Gemini | Claude | GPT-4 has better web search, general knowledge |
| **Data Analysis** | Gemini | Claude | ChatGPT | Gemini 2.0 has strong analytical capabilities |
| **Documentation** | ChatGPT | Claude | Gemini | GPT-4 has best natural language |
| **Code Review** | Gemini | Claude | ChatGPT | Gemini excels at finding issues |
| **SQL/DB Work** | Claude Code | Gemini | ChatGPT | Claude with dbtool is strongest |
| **Testing** | Claude Code | ChatGPT | Gemini | Claude has best test generation |
| **Debugging** | Claude Code | Gemini | ChatGPT | Claude + GSD debugger agent |
| **Planning** | Claude Code | ChatGPT | Gemini | GSD planner agent |

### Cost Tiers (Priority Order)

```python
COST_PRIORITY = [
    # Tier 1: Free CLI quota (use first)
    {"platform": "gemini", "method": "cli", "quota": "1500_req/day", "cost": 0},

    # Tier 2: Included in subscriptions (already paid)
    {"platform": "claude_code", "method": "desktop", "quota": "unlimited", "cost": 0},
    {"platform": "chatgpt", "method": "web", "quota": "unlimited_plus", "cost": 0},

    # Tier 3: Free API tiers
    {"platform": "gemini", "method": "api_free", "quota": "1500_req/day", "cost": 0},

    # Tier 4: Paid APIs (last resort for batch/automation)
    {"platform": "claude", "method": "api", "quota": "pay_per_use", "cost": "variable"},
    {"platform": "openai", "method": "api", "quota": "pay_per_use", "cost": "variable"},
]
```

---

## Component 2: Platform Adapters

### Claude Code Adapter
- **Method**: Subprocess execution via `claude` CLI
- **Input**: Markdown-formatted prompts + GSD commands
- **Output**: Parse stdout/files for results
- **Strengths**: GSD agents, codebase context, tool use
- **Integration**: Already running (this session!)

```python
class ClaudeCodeAdapter:
    def execute(self, task: Task) -> Result:
        if task.requires_gsd:
            return self._execute_gsd_command(task)
        else:
            return self._execute_interactive(task)

    def _execute_gsd_command(self, task: Task) -> Result:
        """Execute via GSD system (/gsd:plan-phase, etc.)"""
        pass
```

### ChatGPT Adapter
- **Method 1**: Selenium/Playwright automation of web UI
- **Method 2**: OpenAI API for batch tasks
- **Input**: Text prompts
- **Output**: Parse responses
- **Strengths**: Research, writing, general reasoning

```python
class ChatGPTAdapter:
    def __init__(self, prefer_web: bool = True):
        self.web_driver = SeleniumDriver() if prefer_web else None
        self.api_client = OpenAI() if not prefer_web else None
```

### Gemini Adapter
- **Method 1**: `gcloud ai` CLI (free quota)
- **Method 2**: Gemini API
- **Input**: Text/multimodal prompts
- **Output**: Parse JSON responses
- **Strengths**: Analysis, code review, data processing

```python
class GeminiAdapter:
    def execute_cli(self, prompt: str) -> str:
        """Use free CLI quota first"""
        result = subprocess.run([
            "gcloud", "ai", "models", "generate-content",
            "--model=gemini-2.0-flash-exp",
            f"--prompt={prompt}"
        ], capture_output=True)
        return result.stdout.decode()
```

---

## Component 3: GSD Integration Layer

### Workflow Mapping

Map ta_lab2 workflows to GSD commands:

| ta_lab2 Task | GSD Command | Notes |
|--------------|-------------|-------|
| New feature development | `/gsd:new-project` → `/gsd:plan-phase` → `/gsd:execute-phase` | Full workflow |
| Refactor existing code | `/gsd:map-codebase` → `/gsd:plan-phase` | Brownfield mode |
| Add tests | `/gsd:execute-plan` with test plan | Single-plan mode |
| Debug issues | `/gsd:debug` | Uses debugger agent |
| Research best practices | `/gsd:research-project` | Parallel research agents |
| Code review | Custom script calling GSD verifier agent | - |

### Integration Points

1. **Direct GSD Usage** (this Claude Code session)
   - Install GSD: `npx get-shit-done-cc --local` to `.claude/`
   - Use commands interactively: `/gsd:help`

2. **Automated GSD Dispatch** (orchestrator calls Claude Code CLI)
   ```bash
   echo "/gsd:execute-plan .planning/plans/add-polars-optimization.md" | claude --dangerously-skip-permissions
   ```

3. **Custom GSD Extensions** (add ta_lab2-specific commands)
   - Create `.claude/commands/ta-lab2/` with custom commands
   - Example: `/ta-lab2:refresh-bars`, `/ta-lab2:run-audits`

---

## Component 4: Cost Optimization Engine

### Quota Tracking

```python
class QuotaTracker:
    def __init__(self):
        self.daily_limits = {
            "gemini_cli": {"limit": 1500, "used": 0, "resets_at": "midnight_utc"},
            "gemini_api_free": {"limit": 1500, "used": 0, "resets_at": "midnight_utc"},
        }
        self.subscription_usage = {
            "claude_code": {"unlimited": True},
            "chatgpt_plus": {"unlimited": True},
        }

    def can_use(self, platform: str, method: str) -> bool:
        """Check if quota available for platform/method"""
        pass

    def record_usage(self, platform: str, method: str, tokens: int):
        """Track usage for quota management"""
        pass
```

### Smart Routing Logic

```python
def route_task(task: Task) -> Platform:
    """
    Priority routing:
    1. Check task type for platform strengths
    2. Check quota availability (prefer free)
    3. Check current load (avoid overloading one platform)
    4. Return best available option
    """

    # Get candidates from routing matrix
    candidates = ROUTING_MATRIX[task.type]

    # Filter by quota availability
    available = [p for p in candidates if quota_tracker.can_use(p)]

    # Prefer free tier
    for tier in COST_PRIORITY:
        if tier["platform"] in available and tier["cost"] == 0:
            return tier["platform"]

    # Fall back to paid if necessary
    return available[0] if available else "claude_code"  # Default
```

---

## Implementation Plan

### Phase 1: Foundation (1-2 days)
- [ ] Install GSD to ta_lab2: `npx get-shit-done-cc --local`
- [ ] Verify `/gsd:help` works in Claude Code
- [ ] Create `ta_lab2/tools/ai_orchestrator/` module
- [ ] Implement `Task` and `Platform` dataclasses
- [ ] Build basic `TaskDispatcher` with routing matrix

### Phase 2: Platform Adapters (2-3 days)
- [ ] Implement `ClaudeCodeAdapter` (subprocess + file parsing)
- [ ] Implement `GeminiAdapter` (gcloud CLI integration)
- [ ] Implement `ChatGPTAdapter` (web UI automation OR API)
- [ ] Add quota tracking for free tiers
- [ ] Test each adapter independently

### Phase 3: Orchestration (1-2 days)
- [ ] Build `route_task()` logic with cost optimization
- [ ] Implement parallel task execution (asyncio)
- [ ] Add result merging and deduplication
- [ ] Create CLI interface: `python -m ta_lab2.tools.ai_orchestrator`

### Phase 4: GSD Integration (1 day)
- [ ] Map common ta_lab2 tasks to GSD workflows
- [ ] Create custom GSD commands in `.claude/commands/ta-lab2/`
- [ ] Document GSD best practices for ta_lab2

### Phase 5: Testing & Optimization (2 days)
- [ ] End-to-end test: parallel task execution
- [ ] Measure cost savings vs single-platform usage
- [ ] Tune routing matrix based on results
- [ ] Add monitoring and logging

---

## Usage Examples

### Example 1: Parallel Development

```python
from ta_lab2.tools.ai_orchestrator import Orchestrator

orchestrator = Orchestrator()

# Route different tasks to different platforms simultaneously
tasks = [
    Task(type="code_generation", prompt="Add multiprocessing to bar refresh scripts", platform_hint="claude_code"),
    Task(type="research", prompt="Research best practices for Polars optimization", platform_hint="chatgpt"),
    Task(type="code_review", prompt="Review ema_multi_tf_v2.py for performance issues", platform_hint="gemini"),
]

results = orchestrator.execute_parallel(tasks)
```

### Example 2: GSD Workflow Automation

```python
# Automate full GSD workflow for new feature
orchestrator.execute_gsd_workflow(
    workflow="new-feature",
    steps=[
        "/gsd:new-project",
        "/gsd:define-requirements",
        "/gsd:create-roadmap",
        "/gsd:plan-phase 1",
        "/gsd:execute-phase 1",
    ],
    interactive=False  # Walk away and let it run
)
```

### Example 3: Cost-Optimized Batch Processing

```python
# Process 100 code reviews using free Gemini quota first
reviews = [Task(type="code_review", file=f) for f in changed_files]

orchestrator.execute_batch(
    tasks=reviews,
    optimize_cost=True,  # Will use Gemini CLI free tier
    max_parallel=10,
)
```

---

## Key Benefits

1. **Maximize Subscription Value**: Use all 3 platforms instead of just one
2. **Cost Optimization**: Free CLI/API tiers before paid APIs
3. **Task Specialization**: Route to each AI's strengths
4. **Parallel Execution**: 3x throughput vs sequential
5. **GSD Power**: Meta-prompting + subagent orchestration in Claude Code
6. **Brownfield Ready**: GSD's codebase mapper for existing ta_lab2 code

---

## Next Steps

**Immediate**: Install GSD and test basic commands
```bash
cd C:\Users\asafi\Downloads\ta_lab2
npx get-shit-done-cc --local
# Then in Claude Code: /gsd:help
```

**Short-term**: Build TaskDispatcher + routing logic

**Medium-term**: Implement all 3 platform adapters

**Long-term**: Full orchestration with parallel execution
