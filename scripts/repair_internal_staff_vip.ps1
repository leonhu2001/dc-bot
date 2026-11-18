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
    Write-Host "=== READ-ONLY VERIFIED VIP AUDIT (WALLET POINTS UNTOUCHED) ===" -ForegroundColor Yellow
    & ssh @SshArgs $Vps "cd /opt/dc-bot && ./venv/bin/python scripts/repair_internal_staff_vip_20261119.py --vip-only"
    if ($LASTEXITCODE -ne 0) { throw "Preview failed. Nothing was changed." }
    Write-Host "Preview complete. No database changes." -ForegroundColor Green
    return
}

# Invoke an already-committed VPS script via SSH; never pipe PowerShell lines
# through Windows CRLF conversion to bash (can corrupt --apply as --apply\r).
# The remote runner performs a read-only strict preflight before stopping services.
Write-Host "=== APPLY VERIFIED VIP-ONLY REVERSAL ===" -ForegroundColor Yellow
& ssh @SshArgs $Vps "cd /opt/dc-bot && bash scripts/repair_internal_staff_vip_remote.sh"
if ($LASTEXITCODE -ne 0) {
    throw "Correction aborted; read the remote audit/errors. Do not retry blindly."
}
Write-Host "VIP-only correction completed. Verify balances and service status." -ForegroundColor Green
