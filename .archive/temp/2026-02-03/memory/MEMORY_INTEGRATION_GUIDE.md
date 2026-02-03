# ta_lab2 Memory System Integration Guide

## Quick Start

### 1. Initialize the Memory System

```powershell
# In your ta_lab2 project root
.\setup_memory_system.ps1
```

This creates:
- `.memory/` directory structure
- JSON schema files
- Helper scripts
- Installs mem0 Python package

### 2. Document Your First Decision

```powershell
.\memory_add.ps1 -Type "architecture" `
    -Description "Using PostgreSQL views for EMA calculations" `
    -Rationale "Improves query performance and reduces code duplication" `
    -Platform "Claude Code"
```

### 3. Sync Before AI Session

```powershell
.\memory_sync.ps1 -Platform "Claude Code" -SessionNote "Working on regime labeling optimization"
```

Copy the generated context summary and paste it into your AI session.

---

## Platform-Specific Integration

### Claude Code (CLI)

**Before starting a session:**
```powershell
.\memory_sync.ps1 -Platform "Claude Code"
```

**In Claude Code prompt:**
```
Context: I'm working on ta_lab2 (see .memory/ for project history)

Recent decisions and active goals are in:
- .memory/decisions/*.json
- .memory/goals/active.json

[Your specific question/task here]
```

**After session:**
```powershell
.\memory_add.ps1 -Type "features" `
    -Description "Implemented seasonal resampling for EMAs" `
    -Rationale "Needed for analyzing crypto seasonality patterns" `
    -Platform "Claude Code"
```

---

### Claude UI (Web/Desktop)

**Start of session:**
Upload `.memory/` directory structure or paste this context:

```
Project: ta_lab2 (Multi-timeframe TA Lab)
Tech: Python, PostgreSQL, pandas
Location: https://github.com/adammsafi/ta_lab2

Current context (from .memory/):
[Copy output from .\memory_view.ps1 -Category recent -Limit 5]

I'm working on: [your current task]
```

**During session:**
Reference decisions naturally:
- "Based on our earlier decision to use PostgreSQL views..."
- "This relates to the goal we set about optimizing EMA calculations..."

**After session:**
```powershell
# Log decisions made during the session
.\memory_add.ps1 -Type "architecture" -Description "..." -Platform "Claude UI"
```

---

### ChatGPT / OpenAI Codex

**Custom Instructions (Settings):**
```
Project Context:
I'm working on ta_lab2, a Python package for multi-timeframe crypto technical analysis.
Key decisions and goals are tracked in .memory/ directory.

When I reference "our previous discussion" or "the decision we made", 
check these files for context:
- .memory/decisions/architecture.json
- .memory/decisions/features.json
- .memory/goals/active.json

Tech stack: Python 3.11, PostgreSQL, pandas, pytest
```

**In prompts:**
```python
# Before asking for help, sync memory:
from ta_lab2_memory import TA_Lab2_Memory

memory = TA_Lab2_Memory()
context = memory.get_context_summary()

# Then paste context into ChatGPT
print(json.dumps(context, indent=2))
```

**Or use CLI:**
```bash
python ta_lab2_memory.py summary
```

---

### Google Gemini

**Start of session:**
```
I'm working on ta_lab2 (github.com/adammsafi/ta_lab2).

Project memory is tracked in .memory/ directory:
[Paste recent decisions and goals from memory_view.ps1]

Current focus: [your task]
```

**Using Python API:**
```python
from ta_lab2_memory import TA_Lab2_Memory

memory = TA_Lab2_Memory()
memory.sync_platform("Gemini", "Working on regime signal optimization")

# Get context for Gemini prompt
context = memory.get_context_summary()
```

---

## Python Integration Examples

### Basic Usage

```python
from ta_lab2_memory import TA_Lab2_Memory

# Initialize
memory = TA_Lab2_Memory()

# Add a decision
memory.add_decision(
    category="features",
    description="Added lunar calendar feature to regime labeling",
    rationale="Captures cyclical patterns in crypto markets",
    platform="Python"
)

# Add a goal
memory.add_goal(
    description="Implement backtesting framework for regime policies",
    priority="high"
)

# Search memory semantically (requires mem0)
results = memory.search("How did we decide to handle multi-timeframe alignment?")
for result in results:
    print(result['memory'])

# Get recent context
recent = memory.get_recent_decisions(category="architecture", limit=5)
active_goals = memory.get_active_goals(priority="high")
```

### Integration with ta_lab2 Scripts

```python
# In your ta_lab2 scripts, add at the top:
from ta_lab2_memory import TA_Lab2_Memory

memory = TA_Lab2_Memory()
memory.sync_platform("Python Script", "Running EMA refresh pipeline")

# Later, log important decisions
if new_feature_added:
    memory.add_decision(
        category="features",
        description=f"Added {feature_name}",
        rationale=f"Needed for {use_case}",
        platform="Python Script"
    )
```

---

## Memory System Architecture

### Directory Structure
```
.memory/
├── decisions/
│   ├── architecture.json    # System design choices
│   ├── features.json        # Feature engineering decisions
│   ├── regimes.json         # Regime logic decisions
│   └── data.json            # Data pipeline choices
├── goals/
│   ├── active.json          # Current objectives
│   ├── completed.json       # Achieved milestones
│   └── backlog.json         # Future work
├── context/
│   ├── sessions.json        # AI session log
│   ├── blockers.json        # Current obstacles
│   └── insights.json        # Key learnings
└── sync/
    ├── platform_state.json  # Last platform used
    └── schema_version.json  # Memory format version
```

### Schema Example (decisions/architecture.json)

```json
{
  "schema_version": "1.0",
  "decisions": [
    {
      "id": "a3f9c2b1",
      "timestamp": "2024-12-31 14:30:00",
      "description": "Migrated EMA calculations to PostgreSQL views",
      "rationale": "Reduces Python processing overhead and leverages database query optimization",
      "platform": "Claude Code",
      "status": "active"
    }
  ]
}
```

---

## Best Practices

### 1. Always Sync Before Sessions
```powershell
.\memory_sync.ps1 -Platform "Claude Code"
```

### 2. Document Key Decisions Immediately
Don't wait until the end of the day. Log decisions right after making them:
```powershell
.\memory_add.ps1 -Type "architecture" -Description "..." -Rationale "..."
```

### 3. Use Semantic Search
When you can't remember where a decision was made:
```python
memory.search("Why did we use PostgreSQL views instead of pandas?")
```

### 4. Review Memory Weekly
```powershell
.\memory_view.ps1 -Category all -Limit 20
```

### 5. Keep Goals Updated
Move completed goals:
```powershell
# Manually edit .memory/goals/completed.json
# Or create a helper script
```

### 6. Platform-Specific Context
Each platform has different strengths:
- **Claude Code**: Best for architecture decisions, code refactoring
- **ChatGPT**: Good for algorithm design, optimization strategies
- **Gemini**: Strong for data analysis, visualization ideas

Track which platform you used for each decision to know where to go back.

---

## Troubleshooting

### mem0 not installing
```powershell
pip install mem0ai --break-system-packages --upgrade
```

### JSON syntax errors
Validate your memory files:
```powershell
Get-Content .memory/decisions/architecture.json | ConvertFrom-Json
```

### Memory files not syncing
Check `.gitignore` - should include:
```
.memory/sync/platform_state.json
```

But NOT the rest of `.memory/` (you want to version control decisions/goals).

---

## Advanced: Git Integration

### Pre-commit Hook
Create `.git/hooks/pre-commit`:
```bash
#!/bin/bash
# Validate memory JSON files before commit
for file in .memory/**/*.json; do
    python -m json.tool "$file" > /dev/null
    if [ $? -ne 0 ]; then
        echo "❌ Invalid JSON: $file"
        exit 1
    fi
done
```

### Commit Messages
Reference memory IDs in commits:
```
git commit -m "Implement seasonal resampling (decision: a3f9c2b1)"
```

---

## Future Enhancements

- [ ] Web dashboard for memory visualization
- [ ] Auto-sync to cloud (Supabase/Firebase)
- [ ] GitHub Actions integration
- [ ] Slack notifications for memory updates
- [ ] Memory expiration/archival policies
- [ ] Cross-project memory linking

---

## Support

Questions or issues? Check:
1. `.memory/README.md` for quick reference
2. GitHub Issues: https://github.com/adammsafi/ta_lab2/issues
3. Memory system logs: `.memory/context/sessions.json`
