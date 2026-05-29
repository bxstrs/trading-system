<#
.SYNOPSIS
    Monthly cleanup utility for completed intent files on disk.

.DESCRIPTION
    Deletes all FILLED or ABANDONED intent JSON files in the checkpoints/ 
    directory that are older than 30 days to free up disk space.
    Never touches PENDING intents.
#>

$ProjectRoot = Resolve-Path "$PSScriptRoot\.."
$CheckpointDir = Join-Path $ProjectRoot "checkpoints"
$LimitDate = (Get-Date).AddDays(-30)

Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "         INTENT CLEANUP MAINTENANCE          " -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "Checkpoint Dir: $CheckpointDir"
Write-Host "Deleting files older than: $LimitDate"

if (-not (Test-Path $CheckpointDir)) {
    Write-Host "[OK] Checkpoints directory does not exist yet. Nothing to clean." -ForegroundColor Green
    Exit 0
}

$IntentFiles = Get-ChildItem -Path $CheckpointDir -Filter "intent_*.json"

$DeletedCount = 0
$PendingCount = 0
$SkippedCount = 0

foreach ($File in $IntentFiles) {
    # Verify it is not a PENDING intent (read JSON status safely)
    try {
        $Content = Get-Content -Raw -Path $File.FullName | ConvertFrom-Json
        if ($Content.status -eq "PENDING") {
            $PendingCount++
            continue
        }
    } catch {
        # File is unparseable or locked, skip it
        $SkippedCount++
        continue
    }

    # Delete if older than 30 days
    if ($File.LastWriteTime -lt $LimitDate) {
        Remove-Item -Path $File.FullName -Force
        $DeletedCount++
    } else {
        $SkippedCount++
    }
}

Write-Host "---------------------------------------------" -ForegroundColor Gray
Write-Host "Cleanup Completed Successfully!" -ForegroundColor Green
Write-Host "  - Deleted Completed Intents (>30 days old): $DeletedCount" -ForegroundColor Yellow
Write-Host "  - Retained Active/Recent Completed Intents: $SkippedCount" -ForegroundColor White
Write-Host "  - Preserved PENDING recovery records:      $PendingCount" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan
