param(
    [string]$Vps = "root@178.128.85.16",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

Write-Host "=== SAFE DEPLOY PRECHECK ===" -ForegroundColor Yellow

if (git status --porcelain) {
    git status --short
    throw "Local working tree has changes. Commit or stash them before deployment."
}

git fetch origin main

if ($LASTEXITCODE -ne 0) {
    throw "git fetch failed"
}

git checkout main

if ($LASTEXITCODE -ne 0) {
    throw "git checkout main failed"
}

git pull --ff-only origin main

if ($LASTEXITCODE -ne 0) {
    throw "git pull --ff-only failed"
}

if (-not $Target) {
    $Target = (git rev-parse origin/main).Trim()
}

$LocalHead = (git rev-parse HEAD).Trim()

if ($LocalHead -ne $Target) {
    throw "Local HEAD ($LocalHead) does not match target ($Target)."
}

Write-Host ""
Write-Host "Target: $Target" -ForegroundColor Cyan
Write-Host "VPS:    $Vps" -ForegroundColor Cyan
Write-Host ""

$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '\${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"

ssh $Vps $RemoteCommand

if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
