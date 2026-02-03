# Sync ta_lab2 memory before starting AI session
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Claude UI", "Claude Code", "ChatGPT", "OpenAI Codex", "Gemini")]
    [string]$Platform,
    
    [string]$SessionNote = ""
)

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$sessionId = [System.Guid]::NewGuid().ToString()

# Update platform state
$platformState = @{
    last_platform = $Platform
    last_sync = $timestamp
    session_id = $sessionId
} | ConvertTo-Json -Depth 10

Set-Content ".memory/sync/platform_state.json" $platformState

# Log session
$sessionsFile = ".memory/context/sessions.json"
$sessions = Get-Content $sessionsFile | ConvertFrom-Json

$sessionEntry = @{
    id = $sessionId.Substring(0, 8)
    timestamp = $timestamp
    platform = $Platform
    note = $SessionNote
}

$sessions.sessions += $sessionEntry
$sessions | ConvertTo-Json -Depth 10 | Set-Content $sessionsFile

Write-Host "✓ Synced memory for $Platform session" -ForegroundColor Green
Write-Host "  Session ID: $($sessionEntry.id)" -ForegroundColor Gray
Write-Host "  Timestamp: $timestamp" -ForegroundColor Gray

# Generate context summary
Write-Host "`n📝 Context Summary for AI Platform" -ForegroundColor Cyan
Write-Host "=" * 60

# Recent decisions
Write-Host "`nRecent Decisions:" -ForegroundColor Yellow
$allDecisions = @()
Get-ChildItem ".memory/decisions" -Filter "*.json" | ForEach-Object {
    $data = Get-Content $_.FullName | ConvertFrom-Json
    $allDecisions += $data.decisions | Select-Object -Last 3
}
$allDecisions | Sort-Object timestamp -Descending | Select-Object -First 5 | ForEach-Object {
    Write-Host "  • $($_.description)" -ForegroundColor White
}

# Active goals
Write-Host "`nActive Goals:" -ForegroundColor Yellow
$activeGoals = Get-Content ".memory/goals/active.json" | ConvertFrom-Json
$activeGoals.goals | Sort-Object priority | Select-Object -First 5 | ForEach-Object {
    Write-Host "  • [$($_.priority.ToUpper())] $($_.description)" -ForegroundColor White
}

# Current blockers
Write-Host "`nCurrent Blockers:" -ForegroundColor Yellow
$blockers = Get-Content ".memory/context/blockers.json" | ConvertFrom-Json
$activeBlockers = $blockers.blockers | Where-Object { $_.status -eq "active" }
if ($activeBlockers.Count -gt 0) {
    $activeBlockers | ForEach-Object {
        Write-Host "  • $($_.description)" -ForegroundColor Red
    }
} else {
    Write-Host "  • None" -ForegroundColor Green
}

Write-Host "`n" + ("=" * 60)
Write-Host "`n💡 Copy this context to your AI session:" -ForegroundColor Cyan
Write-Host @"

Project: ta_lab2 (Multi-timeframe Technical Analysis Lab)
Session: $($sessionEntry.id)
Platform: $Platform

Quick Context:
- Python package for BTC/crypto technical analysis
- Multi-timeframe regime labeling (monthly/weekly/daily/intraday)
- PostgreSQL backend with EMA views
- Key directories: src/ta_lab2/, tests/, sql/, docs/

Recent work focuses on:
$($allDecisions | Sort-Object timestamp -Descending | Select-Object -First 3 | ForEach-Object { "• $($_.description)" } | Out-String)

Active priorities:
$($activeGoals.goals | Sort-Object priority | Select-Object -First 3 | ForEach-Object { "• $($_.description)" } | Out-String)

For full context, reference: .memory/ directory structure
"@ -ForegroundColor Gray

Write-Host "`n✅ Ready to start AI session!" -ForegroundColor Green
