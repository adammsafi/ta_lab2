# ta_lab2 Memory System Setup
# Initializes mem0 + custom memory structure for cross-platform AI usage

param(
    [string]$ProjectPath = ".",
    [switch]$Force
)

Write-Host "🧠 Setting up ta_lab2 Memory System..." -ForegroundColor Cyan

# Navigate to project root
Set-Location $ProjectPath

# 1. Create memory directory structure
$memoryRoot = ".memory"
$directories = @(
    "$memoryRoot/decisions",
    "$memoryRoot/goals",
    "$memoryRoot/context",
    "$memoryRoot/sync"
)

foreach ($dir in $directories) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
        Write-Host "✓ Created $dir" -ForegroundColor Green
    } else {
        Write-Host "→ $dir already exists" -ForegroundColor Yellow
    }
}

# 2. Initialize schema files with templates
$schemas = @{
    "$memoryRoot/decisions/architecture.json" = @{
        schema_version = "1.0"
        decisions = @()
    }
    "$memoryRoot/decisions/features.json" = @{
        schema_version = "1.0"
        decisions = @()
    }
    "$memoryRoot/decisions/regimes.json" = @{
        schema_version = "1.0"
        decisions = @()
    }
    "$memoryRoot/decisions/data.json" = @{
        schema_version = "1.0"
        decisions = @()
    }
    "$memoryRoot/goals/active.json" = @{
        schema_version = "1.0"
        goals = @()
    }
    "$memoryRoot/goals/completed.json" = @{
        schema_version = "1.0"
        goals = @()
    }
    "$memoryRoot/goals/backlog.json" = @{
        schema_version = "1.0"
        goals = @()
    }
    "$memoryRoot/context/sessions.json" = @{
        schema_version = "1.0"
        sessions = @()
    }
    "$memoryRoot/context/blockers.json" = @{
        schema_version = "1.0"
        blockers = @()
    }
    "$memoryRoot/context/insights.json" = @{
        schema_version = "1.0"
        insights = @()
    }
    "$memoryRoot/sync/platform_state.json" = @{
        last_platform = "unknown"
        last_sync = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        session_id = [System.Guid]::NewGuid().ToString()
    }
    "$memoryRoot/sync/schema_version.json" = @{
        version = "1.0"
        created = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    }
}

foreach ($file in $schemas.Keys) {
    if (-not (Test-Path $file) -or $Force) {
        $schemas[$file] | ConvertTo-Json -Depth 10 | Set-Content $file
        Write-Host "✓ Created $file" -ForegroundColor Green
    } else {
        Write-Host "→ $file already exists (use -Force to overwrite)" -ForegroundColor Yellow
    }
}

# 3. Install mem0 if not already installed
Write-Host "`n📦 Checking mem0 installation..." -ForegroundColor Cyan
try {
    python -c "import mem0" 2>$null
    Write-Host "✓ mem0 already installed" -ForegroundColor Green
} catch {
    Write-Host "Installing mem0..." -ForegroundColor Yellow
    pip install mem0ai --break-system-packages
    Write-Host "✓ mem0 installed" -ForegroundColor Green
}

# 4. Create .gitignore entry if not present
$gitignorePath = ".gitignore"
$memoryIgnore = "`n# Memory system (sensitive project context)`n.memory/sync/platform_state.json`n"

if (Test-Path $gitignorePath) {
    $content = Get-Content $gitignorePath -Raw
    if ($content -notlike "*memory/sync/platform_state.json*") {
        Add-Content $gitignorePath $memoryIgnore
        Write-Host "✓ Updated .gitignore" -ForegroundColor Green
    }
} else {
    Set-Content $gitignorePath $memoryIgnore
    Write-Host "✓ Created .gitignore" -ForegroundColor Green
}

# 5. Create README for memory system
$readmeContent = @"
# ta_lab2 Memory System

This directory contains the project's memory system for tracking decisions, goals, and context across multiple AI platforms (Claude, ChatGPT, Gemini, etc.).

## Structure

- **decisions/** - Architecture, features, regimes, and data pipeline decisions
- **goals/** - Active, completed, and backlog goals
- **context/** - Session tracking, blockers, and insights
- **sync/** - Platform state and synchronization metadata

## Usage

### Adding a Decision
```powershell
.\memory_add.ps1 -Type "architecture" -Description "Switched to PostgreSQL views for EMA calculations" -Rationale "Improves query performance and reduces code duplication" -Platform "Claude Code"
```

### Viewing Current State
```powershell
.\memory_view.ps1 -Category "decisions"
```

### Syncing Before AI Session
```powershell
.\memory_sync.ps1 -Platform "ChatGPT"
```

## Integration with AI Platforms

When starting a session with any AI tool, reference this context:
"Before we begin, please review the project memory in .memory/ to understand past decisions and current goals."

## Schema Version
Current: 1.0
"@

Set-Content "$memoryRoot/README.md" $readmeContent
Write-Host "✓ Created memory README" -ForegroundColor Green

Write-Host "`n✅ Memory system initialized successfully!" -ForegroundColor Green
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Review .memory/README.md" -ForegroundColor White
Write-Host "2. Run .\memory_add.ps1 to document your first decision" -ForegroundColor White
Write-Host "3. Configure AI platforms to reference .memory/ directory" -ForegroundColor White
