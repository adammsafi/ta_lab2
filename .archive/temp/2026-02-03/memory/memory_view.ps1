# View ta_lab2 memory system contents
param(
    [ValidateSet("all", "decisions", "goals", "context", "recent")]
    [string]$Category = "all",

    [int]$Limit = 10,

    [string]$Status = ""
)

function Format-Entry {
    param($entry, $type)

    Write-Host "`n[$($entry.id)] $($entry.timestamp)" -ForegroundColor Cyan
    Write-Host "  Type: $type" -ForegroundColor Gray
    Write-Host "  Description: $($entry.description)" -ForegroundColor White
    if ($entry.rationale) {
        Write-Host "  Rationale: $($entry.rationale)" -ForegroundColor Yellow
    }
    if ($entry.platform) {
        Write-Host "  Platform: $($entry.platform)" -ForegroundColor Gray
    }
    if ($entry.status) {
        Write-Host "  Status: $($entry.status)" -ForegroundColor $(if ($entry.status -eq "active") { "Green" } else { "Gray" })
    }
    if ($entry.priority) {
        Write-Host "  Priority: $($entry.priority)" -ForegroundColor $(
            switch ($entry.priority) {
                "high" { "Red" }
                "medium" { "Yellow" }
                "low" { "Gray" }
            }
        )
    }
}

Write-Host "🧠 ta_lab2 Memory System" -ForegroundColor Cyan
Write-Host "=" * 60

if ($Category -in @("all", "decisions")) {
    Write-Host "`n📋 DECISIONS" -ForegroundColor Magenta

    $decisionTypes = @("architecture", "features", "regimes", "data")
    foreach ($type in $decisionTypes) {
        $file = ".memory/decisions/$type.json"
        if (Test-Path $file) {
            $data = Get-Content $file | ConvertFrom-Json
            $entries = $data.decisions | Sort-Object timestamp -Descending | Select-Object -First $Limit

            if ($Status) {
                $entries = $entries | Where-Object { $_.status -eq $Status }
            }

            if ($entries.Count -gt 0) {
                Write-Host "`n  [$($type.ToUpper())]" -ForegroundColor Yellow
                foreach ($entry in $entries) {
                    Format-Entry $entry $type
                }
            }
        }
    }
}

if ($Category -in @("all", "goals")) {
    Write-Host "`n`n🎯 GOALS" -ForegroundColor Magenta

    $goalFiles = @{
        "active" = ".memory/goals/active.json"
        "completed" = ".memory/goals/completed.json"
        "backlog" = ".memory/goals/backlog.json"
    }

    foreach ($status in $goalFiles.Keys) {
        $file = $goalFiles[$status]
        if (Test-Path $file) {
            $data = Get-Content $file | ConvertFrom-Json
            $goals = $data.goals | Sort-Object timestamp -Descending | Select-Object -First $Limit

            if ($goals.Count -gt 0) {
                Write-Host "`n  [$($status.ToUpper())]" -ForegroundColor Yellow
                foreach ($goal in $goals) {
                    Format-Entry $goal "goal"
                }
            }
        }
    }
}

if ($Category -in @("all", "context")) {
    Write-Host "`n`n💭 CONTEXT" -ForegroundColor Magenta

    $contextFiles = @{
        "blockers" = ".memory/context/blockers.json"
        "insights" = ".memory/context/insights.json"
    }

    foreach ($type in $contextFiles.Keys) {
        $file = $contextFiles[$type]
        if (Test-Path $file) {
            $data = Get-Content $file | ConvertFrom-Json
            $items = $data.$type | Sort-Object timestamp -Descending | Select-Object -First $Limit

            if ($items.Count -gt 0) {
                Write-Host "`n  [$($type.ToUpper())]" -ForegroundColor Yellow
                foreach ($item in $items) {
                    Format-Entry $item $type
                }
            }
        }
    }
}

if ($Category -eq "recent") {
    Write-Host "`n`n⏰ RECENT ACTIVITY (Last $Limit entries)" -ForegroundColor Magenta

    $allEntries = @()

    # Collect all entries
    Get-ChildItem ".memory" -Recurse -Filter "*.json" | Where-Object { $_.Name -ne "platform_state.json" -and $_.Name -ne "schema_version.json" } | ForEach-Object {
        $content = Get-Content $_.FullName | ConvertFrom-Json
        $type = $_.Directory.Name

        if ($content.decisions) {
            $content.decisions | ForEach-Object {
                $allEntries += @{
                    entry = $_
                    type = "$type/$($_.Name -replace '.json','')"
                    timestamp = $_.timestamp
                }
            }
        }
        if ($content.goals) {
            $content.goals | ForEach-Object {
                $allEntries += @{
                    entry = $_
                    type = "goals"
                    timestamp = $_.timestamp
                }
            }
        }
        if ($content.blockers) {
            $content.blockers | ForEach-Object {
                $allEntries += @{
                    entry = $_
                    type = "blockers"
                    timestamp = $_.timestamp
                }
            }
        }
        if ($content.insights) {
            $content.insights | ForEach-Object {
                $allEntries += @{
                    entry = $_
                    type = "insights"
                    timestamp = $_.timestamp
                }
            }
        }
    }

    $allEntries | Sort-Object timestamp -Descending | Select-Object -First $Limit | ForEach-Object {
        Format-Entry $_.entry $_.type
    }
}

# Show sync status
Write-Host "`n`n🔄 SYNC STATUS" -ForegroundColor Magenta
$platformState = Get-Content ".memory/sync/platform_state.json" | ConvertFrom-Json
Write-Host "  Last Platform: $($platformState.last_platform)" -ForegroundColor White
Write-Host "  Last Sync: $($platformState.last_sync)" -ForegroundColor Gray
Write-Host "  Session ID: $($platformState.session_id)" -ForegroundColor Gray

Write-Host "`n" + ("=" * 60)
