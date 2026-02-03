# ta_lab2 Memory System Health Check
param(
    [switch]$Fix
)

Write-Host "🔍 Checking ta_lab2 Memory System Health..." -ForegroundColor Cyan
Write-Host "=" * 60

$issues = @()
$warnings = @()

# Check if .memory directory exists
if (-not (Test-Path ".memory")) {
    $issues += ".memory directory not found"
    Write-Host "❌ .memory directory missing" -ForegroundColor Red
    if ($Fix) {
        Write-Host "   Running setup_memory_system.ps1..." -ForegroundColor Yellow
        .\setup_memory_system.ps1
    }
} else {
    Write-Host "✓ .memory directory exists" -ForegroundColor Green
}

# Check required subdirectories
$requiredDirs = @(
    ".memory/decisions",
    ".memory/goals",
    ".memory/context",
    ".memory/sync"
)

foreach ($dir in $requiredDirs) {
    if (-not (Test-Path $dir)) {
        $issues += "Missing directory: $dir"
        Write-Host "❌ $dir missing" -ForegroundColor Red
        if ($Fix) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-Host "   Created $dir" -ForegroundColor Yellow
        }
    } else {
        Write-Host "✓ $dir exists" -ForegroundColor Green
    }
}

# Check required JSON files
$requiredFiles = @(
    ".memory/decisions/architecture.json",
    ".memory/decisions/features.json",
    ".memory/decisions/regimes.json",
    ".memory/decisions/data.json",
    ".memory/goals/active.json",
    ".memory/goals/completed.json",
    ".memory/goals/backlog.json",
    ".memory/context/sessions.json",
    ".memory/context/blockers.json",
    ".memory/context/insights.json",
    ".memory/sync/platform_state.json",
    ".memory/sync/schema_version.json"
)

foreach ($file in $requiredFiles) {
    if (-not (Test-Path $file)) {
        $issues += "Missing file: $file"
        Write-Host "❌ $file missing" -ForegroundColor Red
    } else {
        # Validate JSON syntax
        try {
            Get-Content $file | ConvertFrom-Json | Out-Null
            Write-Host "✓ $file valid" -ForegroundColor Green
        } catch {
            $issues += "Invalid JSON: $file"
            Write-Host "❌ $file has invalid JSON" -ForegroundColor Red
        }
    }
}

# Check mem0 installation
Write-Host "`n📦 Checking Dependencies..." -ForegroundColor Cyan
try {
    python -c "import mem0" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "✓ mem0 installed" -ForegroundColor Green
    } else {
        throw
    }
} catch {
    $warnings += "mem0 not installed (semantic search unavailable)"
    Write-Host "⚠️  mem0 not installed" -ForegroundColor Yellow
    if ($Fix) {
        Write-Host "   Installing mem0..." -ForegroundColor Yellow
        pip install mem0ai --break-system-packages
    }
}

# Check helper scripts
Write-Host "`n📜 Checking Helper Scripts..." -ForegroundColor Cyan
$helperScripts = @(
    "setup_memory_system.ps1",
    "memory_add.ps1",
    "memory_view.ps1",
    "memory_sync.ps1",
    "ta_lab2_memory.py"
)

foreach ($script in $helperScripts) {
    if (-not (Test-Path $script)) {
        $warnings += "Helper script missing: $script"
        Write-Host "⚠️  $script not found" -ForegroundColor Yellow
    } else {
        Write-Host "✓ $script exists" -ForegroundColor Green
    }
}

# Check .gitignore
Write-Host "`n🔒 Checking Git Configuration..." -ForegroundColor Cyan
if (Test-Path ".gitignore") {
    $gitignoreContent = Get-Content ".gitignore" -Raw
    if ($gitignoreContent -like "*memory/sync/platform_state.json*") {
        Write-Host "✓ .gitignore configured correctly" -ForegroundColor Green
    } else {
        $warnings += ".gitignore missing memory configuration"
        Write-Host "⚠️  .gitignore doesn't exclude platform_state.json" -ForegroundColor Yellow
    }
} else {
    $warnings += ".gitignore not found"
    Write-Host "⚠️  .gitignore not found" -ForegroundColor Yellow
}

# Statistics
Write-Host "`n📊 Memory Statistics..." -ForegroundColor Cyan

$stats = @{
    decisions = 0
    goals = 0
    sessions = 0
    blockers = 0
}

try {
    Get-ChildItem ".memory/decisions" -Filter "*.json" -ErrorAction SilentlyContinue | ForEach-Object {
        $data = Get-Content $_.FullName | ConvertFrom-Json
        $stats.decisions += $data.decisions.Count
    }

    $activeGoals = Get-Content ".memory/goals/active.json" -ErrorAction SilentlyContinue | ConvertFrom-Json
    $stats.goals = $activeGoals.goals.Count

    $sessions = Get-Content ".memory/context/sessions.json" -ErrorAction SilentlyContinue | ConvertFrom-Json
    $stats.sessions = $sessions.sessions.Count

    $blockers = Get-Content ".memory/context/blockers.json" -ErrorAction SilentlyContinue | ConvertFrom-Json
    $activeBlockers = $blockers.blockers | Where-Object { $_.status -eq "active" }
    $stats.blockers = $activeBlockers.Count

    Write-Host "  Total Decisions: $($stats.decisions)" -ForegroundColor White
    Write-Host "  Active Goals: $($stats.goals)" -ForegroundColor White
    Write-Host "  Total Sessions: $($stats.sessions)" -ForegroundColor White
    Write-Host "  Active Blockers: $($stats.blockers)" -ForegroundColor $(if ($stats.blockers -gt 0) { "Yellow" } else { "Green" })
} catch {
    Write-Host "  Unable to calculate statistics" -ForegroundColor Red
}

# Summary
Write-Host "`n" + ("=" * 60)
if ($issues.Count -eq 0 -and $warnings.Count -eq 0) {
    Write-Host "✅ Memory system is healthy!" -ForegroundColor Green
} else {
    if ($issues.Count -gt 0) {
        Write-Host "❌ Found $($issues.Count) issue(s):" -ForegroundColor Red
        foreach ($issue in $issues) {
            Write-Host "   • $issue" -ForegroundColor Red
        }
    }

    if ($warnings.Count -gt 0) {
        Write-Host "⚠️  Found $($warnings.Count) warning(s):" -ForegroundColor Yellow
        foreach ($warning in $warnings) {
            Write-Host "   • $warning" -ForegroundColor Yellow
        }
    }

    if (-not $Fix) {
        Write-Host "`n💡 Run with -Fix flag to auto-repair issues" -ForegroundColor Cyan
    }
}

Write-Host ""
