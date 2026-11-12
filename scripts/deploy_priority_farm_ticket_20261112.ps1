param(
    [string]$Vps = "root@178.128.85.16",
    [Parameter(Mandatory=$true)]
    [string]$Target
)
$ErrorActionPreference = "Stop"
$ReleaseRef = "feat/farm-priority-worker-only-and-ticket-idempotency-20261112"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=== SAFE FARM PRIORITY + ORDER TICKET DEDUPE DEPLOY ===" -ForegroundColor Yellow

if (git status --porcelain) {
    git status --short
    throw "Local working tree has edits. Commit or stash them before deploying."
}
git fetch origin "+refs/heads/$($ReleaseRef):refs/remotes/origin/$($ReleaseRef)"
if ($LASTEXITCODE -ne 0) { throw "Failed to fetch farm priority release." }

git checkout -B $ReleaseRef "origin/$ReleaseRef"
if ($LASTEXITCODE -ne 0) { throw "Failed to switch to farm priority release." }

$LocalHead = (git rev-parse HEAD).Trim()
$RemoteHead = (git rev-parse "origin/$ReleaseRef").Trim()
if ($LocalHead -ne $Target -or $RemoteHead -ne $Target) {
    throw "BLOCKED: pinned target mismatch. Local=$LocalHead Remote=$RemoteHead Target=$Target"
}

Write-Host "=== VERIFY PINNED CI ===" -ForegroundColor Yellow
$Headers = @{
    Accept = "application/vnd.github+json"
    "User-Agent" = "mw-safe-priority-deploy"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$Uri = "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$Target&per_page=20"
$Response = Invoke-RestMethod -Uri $Uri -Headers $Headers -Method Get -TimeoutSec 25
$Passed = @($Response.workflow_runs) | Where-Object {
    $_.name -eq "CI" -and $_.event -eq "push" -and
    $_.head_sha -eq $Target -and $_.head_branch -eq $ReleaseRef -and
    $_.status -eq "completed" -and $_.conclusion -eq "success"
}
if (@($Passed).Count -lt 1) {
    throw "BLOCKED: no successful exact-SHA GitHub CI."
}
Write-Host "PASS: CI success for $Target" -ForegroundColor Green

$SshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=12",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3"
)
$Remote = "cd /opt/dc-bot && git fetch origin '$ReleaseRef' && git show '$($Target):scripts/deploy_priority_farm_ticket_20261112.sh' | bash -s -- '$Target'"
Write-Host "VPS: $Vps" -ForegroundColor Cyan
& ssh @SshArgs $Vps $Remote
if ($LASTEXITCODE -ne 0) {
    throw "VPS priority/ticket deploy failed or was safely blocked; inspect output above."
}
Write-Host ""
Write-Host "DEPLOY COMPLETED - rush fees 100% worker; duplicate ticket panels prevented." -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
