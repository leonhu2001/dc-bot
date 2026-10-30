param(
    [string]$Vps = "root@178.128.85.16"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

$SshTransportArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2"
)

if (git status --porcelain) {
    git status --short
    throw "Local working tree has changes. Commit or stash them first."
}

git fetch origin main
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

git checkout main
if ($LASTEXITCODE -ne 0) { throw "git checkout main failed" }

git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "git pull --ff-only failed" }

$Target = (git rev-parse HEAD).Trim()
$RemoteHead = (& ssh @SshTransportArgs $Vps "cd /opt/dc-bot && git rev-parse HEAD").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read VPS HEAD."
}
if ($RemoteHead -ne $Target) {
    throw "VPS HEAD ($RemoteHead) does not match local main ($Target). Run SAFE DEPLOY for this commit first."
}

Write-Host "=== MARKET PRODUCTION SETUP ===" -ForegroundColor Yellow
Write-Host "Commit: $Target" -ForegroundColor Cyan
Write-Host "VPS:    $Vps" -ForegroundColor Cyan
Write-Host ""

$RemoteCommand = "cd /opt/dc-bot && bash scripts/setup_market_production.sh"
& ssh @SshTransportArgs $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "Market production setup failed. Review the VPS output above; the .env backup path is printed before changes."
}

Write-Host ""
Write-Host "MARKET PRODUCTION SETUP COMPLETED" -ForegroundColor Green
