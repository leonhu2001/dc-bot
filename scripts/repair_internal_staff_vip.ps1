param(
    [switch]$Apply,
    [string]$Vps = "root@178.128.85.16"
)

$ErrorActionPreference = "Stop"
$SshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2"
)

if (-not $Apply) {
    Write-Host "=== READ-ONLY INTERNAL VIP AUDIT ===" -ForegroundColor Yellow
    & ssh @SshArgs $Vps "cd /opt/dc-bot && python3 scripts/repair_internal_staff_vip_20261119.py"
    if ($LASTEXITCODE -ne 0) { throw "Preview failed. Nothing was changed." }
    Write-Host "Preview complete. Review affected orders, then rerun with -Apply." -ForegroundColor Green
    return
}

# The explicit -Apply switch is the only path that changes historic VIP data.
# Stop both writers first; always attempt to restart even if repair fails.
$RemoteScript = @'
set -euo pipefail
cd /opt/dc-bot
test -f scripts/repair_internal_staff_vip_20261119.py
restore_services() {
    systemctl start dc-bot-dashboard.service || echo "WARNING: Web service restart failed" >&2
    systemctl start dc-bot.service || echo "WARNING: Bot service restart failed" >&2
}
trap restore_services EXIT
systemctl stop dc-bot.service dc-bot-dashboard.service
python3 scripts/repair_internal_staff_vip_20261119.py --apply
'@

Write-Host "=== APPLY AUDITED VIP REPAIR (backup first) ===" -ForegroundColor Yellow
$RemoteScript = $RemoteScript -replace "`r`n", "`n"
$RemoteScript | & ssh @SshArgs $Vps "bash -s"
if ($LASTEXITCODE -ne 0) {
    throw "Repair failed; review remote output and service status. Do not retry blindly."
}
Write-Host "Correction complete. Verify affected VIP progress and service status." -ForegroundColor Green
