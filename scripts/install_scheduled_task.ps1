<#
.SYNOPSIS
    Register (or remove) a Windows Scheduled Task that launches the trading bot
    automatically when the current user logs in.

.DESCRIPTION
    Creates a Scheduled Task named "TradingBot_AutoStart" that runs
    scripts\start_trading.ps1 at user logon. Because MT5 requires a desktop
    session, "AtLogon" is used instead of "AtStartup".

    Run with -Uninstall to remove the task.

.EXAMPLE
    # Install (run as Administrator)
    powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_task.ps1

    # Uninstall
    powershell -ExecutionPolicy Bypass -File scripts\install_scheduled_task.ps1 -Uninstall

.NOTES
    Requires Administrator privileges to register the task.
#>

param(
    [switch]$Uninstall
)

# ── Configuration ────────────────────────────────────────────────────────────
$TaskName        = "TradingBot_AutoStart"
$TaskDescription = "Auto-start the trading bot (with restart wrapper) on user logon."
$ProjectRoot     = Split-Path -Parent $PSScriptRoot
$WrapperScript   = Join-Path $ProjectRoot "scripts\start_trading.ps1"

# ── Uninstall path ───────────────────────────────────────────────────────────
if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "[OK] Scheduled task '$TaskName' removed." -ForegroundColor Green
    }
    else {
        Write-Host "[INFO] Task '$TaskName' does not exist. Nothing to remove." -ForegroundColor Yellow
    }
    exit 0
}

# ── Validate prerequisites ───────────────────────────────────────────────────
if (-not (Test-Path $WrapperScript)) {
    Write-Host "[FATAL] Wrapper script not found: $WrapperScript" -ForegroundColor Red
    exit 1
}

# Check for admin privileges
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host "[FATAL] This script must be run as Administrator." -ForegroundColor Red
    Write-Host "        Right-click PowerShell -> 'Run as administrator', then retry." -ForegroundColor Yellow
    exit 1
}

# ── Remove existing task if re-installing ────────────────────────────────────
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] Task '$TaskName' already exists — replacing it." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# ── Build the task ───────────────────────────────────────────────────────────
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Normal -File `"$WrapperScript`"" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)       # no time limit — run indefinitely

$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Highest

# ── Register ─────────────────────────────────────────────────────────────────
Register-ScheduledTask `
    -TaskName    $TaskName `
    -Description $TaskDescription `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -Principal   $principal

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Scheduled Task Installed"               -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Task name : $TaskName"
Write-Host "  Trigger   : At logon ($env:USERNAME)"
Write-Host "  Action    : $WrapperScript"
Write-Host "  Work dir  : $ProjectRoot"
Write-Host "  Time limit: None (runs indefinitely)"
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  To test now:    schtasks /run /tn `"$TaskName`""
Write-Host "  To remove:      powershell -File scripts\install_scheduled_task.ps1 -Uninstall"
Write-Host ""
