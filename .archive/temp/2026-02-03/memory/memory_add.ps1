# Add entries to ta_lab2 memory system
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("architecture", "features", "regimes", "data", "goal", "blocker", "insight")]
    [string]$Type,

    [Parameter(Mandatory=$true)]
    [string]$Description,

    [string]$Rationale = "",
    [string]$Platform = "PowerShell",
    [string]$Status = "active",
    [string]$Priority = "medium"
)

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Determine target file
$targetFile = switch ($Type) {
    "architecture" { ".memory/decisions/architecture.json" }
    "features"     { ".memory/decisions/features.json" }
    "regimes"      { ".memory/decisions/regimes.json" }
    "data"         { ".memory/decisions/data.json" }
    "goal"         { ".memory/goals/active.json" }
    "blocker"      { ".memory/context/blockers.json" }
    "insight"      { ".memory/context/insights.json" }
}

# Load existing data
$data = Get-Content $targetFile | ConvertFrom-Json

# Create new entry
$entry = @{
    id = [System.Guid]::NewGuid().ToString().Substring(0, 8)
    timestamp = $timestamp
    description = $Description
    rationale = $Rationale
    platform = $Platform
    status = $Status
}

if ($Type -eq "goal") {
    $entry.priority = $Priority
}

# Add to appropriate array
if ($Type -in @("architecture", "features", "regimes", "data")) {
    $data.decisions += $entry
} elseif ($Type -eq "goal") {
    $data.goals += $entry
} elseif ($Type -eq "blocker") {
    $data.blockers += $entry
} else {
    $data.insights += $entry
}

# Save updated data
$data | ConvertTo-Json -Depth 10 | Set-Content $targetFile

Write-Host "✓ Added $Type entry [ID: $($entry.id)]" -ForegroundColor Green
Write-Host "  Description: $Description" -ForegroundColor White
if ($Rationale) {
    Write-Host "  Rationale: $Rationale" -ForegroundColor Gray
}

# Update platform state
$platformState = Get-Content ".memory/sync/platform_state.json" | ConvertFrom-Json
$platformState.last_platform = $Platform
$platformState.last_sync = $timestamp
$platformState | ConvertTo-Json -Depth 10 | Set-Content ".memory/sync/platform_state.json"
