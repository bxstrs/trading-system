<#
.SYNOPSIS
    Auto-restart wrapper for the trading bot.

.DESCRIPTION
    Runs `python -m src --mode forward --strategy bb_squeeze` in an infinite loop.
    If the process exits (crash, unhandled exception, OOM), it logs the event,
    waits a cooldown period, and restarts. If the process keeps dying before
    surviving past the cooldown threshold, it halts after MAX_CONSECUTIVE_CRASHES
    to avoid a tight restart loop (e.g. missing .env, broken venv).

.NOTES
    Place this file at:  trading-system/scripts/start_trading.ps1
    Run from project root:  powershell -ExecutionPolicy Bypass -File scripts\start_trading.ps1
#>

# ── Configuration ────────────────────────────────────────────────────────────
$ProjectRoot       = Split-Path -Parent $PSScriptRoot          # one level up from scripts/
$VenvPython        = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$CrashLogFile      = Join-Path $ProjectRoot "logs\crash_restarts.log"
$CooldownSeconds   = 15                                        # wait before restarting
$MinUptimeSeconds  = 60                                        # if process lives longer than this, reset crash counter
$MaxConsecutive    = 5                                          # halt after N rapid crashes

# ── Validate prerequisites ───────────────────────────────────────────────────
if (-not (Test-Path $VenvPython)) {
    Write-Host "[FATAL] venv python not found at: $VenvPython" -ForegroundColor Red
    Write-Host "        Run:  python -m venv venv && venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# Ensure logs directory exists
$LogDir = Split-Path $CrashLogFile
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# ── Helper: append to crash log ──────────────────────────────────────────────
function Write-CrashLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$timestamp] $Message"
    Add-Content -Path $CrashLogFile -Value $line
    Write-Host $line -ForegroundColor Yellow
}

# ── Main loop ────────────────────────────────────────────────────────────────
$consecutiveCrashes = 0

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Trading Bot — Auto-Restart Wrapper"     -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Project  : $ProjectRoot"
Write-Host "  Python   : $VenvPython"
Write-Host "  Cooldown : ${CooldownSeconds}s"
Write-Host "  Max rapid: $MaxConsecutive"
Write-Host "  Crash log: $CrashLogFile"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

while ($true) {
    $startTime = Get-Date

    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Starting trading bot..." -ForegroundColor Green
    Write-CrashLog "STARTING bot process"

    # Run the bot — blocks until it exits
    & $VenvPython -m src --mode forward --strategy bb_squeeze 2>&1 | Tee-Object -Append -FilePath (Join-Path $ProjectRoot "logs\bot_stdout.log")
    $exitCode = $LASTEXITCODE

    $endTime   = Get-Date
    $uptime    = ($endTime - $startTime).TotalSeconds
    $uptimeFmt = "{0:N0}" -f $uptime

    # ── Classify the exit ────────────────────────────────────────────────
    if ($exitCode -eq 0) {
        Write-CrashLog "CLEAN EXIT after ${uptimeFmt}s (exit code 0). User-initiated shutdown — not restarting."
        Write-Host ""
        Write-Host "[STOPPED] Bot exited cleanly. Wrapper shutting down." -ForegroundColor Cyan
        exit 0
    }
    else {
        Write-CrashLog "CRASH exit code=$exitCode after ${uptimeFmt}s uptime"

        if ($uptime -ge $MinUptimeSeconds) {
            # Survived long enough — it was a real runtime error, not a boot failure
            $consecutiveCrashes = 0
        }
        else {
            $consecutiveCrashes++
            Write-CrashLog "Rapid crash #$consecutiveCrashes / $MaxConsecutive (uptime < ${MinUptimeSeconds}s)"
        }

        if ($consecutiveCrashes -ge $MaxConsecutive) {
            Write-CrashLog "HALTED — $MaxConsecutive consecutive rapid crashes. Fix the root cause and restart manually."
            Write-Host ""
            Write-Host "[FATAL] Too many rapid crashes. Bot halted." -ForegroundColor Red
            Write-Host "        Check logs\crash_restarts.log and logs\bot_stdout.log" -ForegroundColor Red
            exit 1
        }
    }

    # ── Cooldown ─────────────────────────────────────────────────────────
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Waiting ${CooldownSeconds}s before restart..." -ForegroundColor DarkYellow
    Start-Sleep -Seconds $CooldownSeconds
}
