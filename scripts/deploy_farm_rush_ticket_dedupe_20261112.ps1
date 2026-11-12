param(
    [string]$Vps = "root@178.128.85.16",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$ReleaseRef = "fix/quick-ticket-duplicate-and-farm-rush-fees-20261112"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=== SAFE QUICK-TICKET DEDUPE + COIN-WASH RUSH DEPLOY ===" -ForegroundColor Yellow

if (git status --porcelain) {
    git status --short
    throw "Local working tree contains edits; commit or stash first."
}

git fetch origin "+refs/heads/$($ReleaseRef):refs/remotes/origin/$($ReleaseRef)"
if ($LASTEXITCODE -ne 0) { throw "Failed to fetch pinned release." }

git switch -C $ReleaseRef "origin/$ReleaseRef"
if ($LASTEXITCODE -ne 0) { throw "Failed to switch to pinned release." }

$RemoteHead = (git rev-parse "origin/$ReleaseRef").Trim()
if (-not $Target) { $Target = $RemoteHead }
$LocalHead = (git rev-parse HEAD).Trim()
if ($LocalHead -ne $Target -or $RemoteHead -ne $Target) {
    throw "BLOCKED: target mismatch. Local=$LocalHead Remote=$RemoteHead Expected=$Target."
}

Write-Host "=== VERIFY EXACT GITHUB CI ===" -ForegroundColor Yellow
$Headers = @{
    "Accept" = "application/vnd.github+json"
    "User-Agent" = "dc-bot-safe-rush-ticket-dedupe-deploy"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$Uri = "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$Target&per_page=20"
$Response = Invoke-RestMethod -Uri $Uri -Headers $Headers -Method Get -TimeoutSec 20
$Run = @($Response.workflow_runs) |
    Where-Object {
        $_.name -eq "CI" -and $_.event -eq "push" -and
        $_.head_sha -eq $Target -and $_.head_branch -eq $ReleaseRef
    } |
    Sort-Object { [datetime]$_.created_at } -Descending |
    Select-Object -First 1
if ($null -eq $Run -or $Run.status -ne "completed" -or $Run.conclusion -ne "success") {
    throw "BLOCKED: exact rush and ticket release CI has not passed. VPS not touched."
}
Write-Host "PASS: pinned release CI successful" -ForegroundColor Green

$SshArgs = @(
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
    "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3"
)
$RemoteCommand = "cd /opt/dc-bot && git fetch origin '$ReleaseRef' && git show '$($Target):scripts/deploy_farm_rush_ticket_dedupe_20261112.sh' | bash -s -- '$Target'"

Write-Host "VPS: $Vps" -ForegroundColor Cyan
& ssh @SshArgs $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS rush/ticket deployment failed or was safely blocked. Inspect output, no forced retry."
}

Write-Host ""
Write-Host "DEPLOY COMPLETED - duplicate ticket panel prevented; internal +260T/public +280T rush to workers." -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
