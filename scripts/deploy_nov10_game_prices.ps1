param(
    [string]$Vps = "root@178.128.85.16",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$ReleaseRef = "fix/retire-mouth-organ-and-old-halfcoin-20261111"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=== SAFE LEGACY DELTA FARM RETIREMENT DEPLOY ===" -ForegroundColor Yellow

if (git status --porcelain) {
    git status --short
    throw "Local working tree contains edits. Commit or stash before deploying."
}

git fetch origin "+refs/heads/$($ReleaseRef):refs/remotes/origin/$($ReleaseRef)"
if ($LASTEXITCODE -ne 0) { throw "Failed to fetch isolated game price release." }

git checkout -B $ReleaseRef "origin/$ReleaseRef"
if ($LASTEXITCODE -ne 0) { throw "Failed to switch to isolated game price release." }

$RemoteHead = (git rev-parse "origin/$ReleaseRef").Trim()
if (-not $Target) {
    $Target = $RemoteHead
}
$LocalHead = (git rev-parse HEAD).Trim()
if ($LocalHead -ne $Target -or $RemoteHead -ne $Target) {
    throw "Target mismatch. Local=$LocalHead Remote=$RemoteHead Expected=$Target."
}

Write-Host "=== VERIFY GITHUB CI ===" -ForegroundColor Yellow
$Headers = @{
    "Accept" = "application/vnd.github+json"
    "User-Agent" = "dc-bot-nov10-game-price-deploy"
    "X-GitHub-Api-Version" = "2022-11-28"
}
$CiUri = "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?event=push&head_sha=$Target&per_page=20"
$CiResponse = Invoke-RestMethod -Uri $CiUri -Headers $Headers -Method Get -TimeoutSec 20
$CiRun = @($CiResponse.workflow_runs) |
    Where-Object {
        $_.name -eq "CI" -and
        $_.event -eq "push" -and
        $_.head_sha -eq $Target -and
        $_.head_branch -eq $ReleaseRef
    } |
    Sort-Object { [datetime]$_.created_at } -Descending |
    Select-Object -First 1

if ($null -eq $CiRun -or $CiRun.status -ne "completed" -or $CiRun.conclusion -ne "success") {
    throw "BLOCKED: the exact isolated release CI has not passed; no VPS deployment."
}

Write-Host "PASS: CI success for $Target" -ForegroundColor Green
Write-Host "VPS: $Vps" -ForegroundColor Cyan

$SshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=12",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3"
)

# The live VPS fetches the same commit, then runs its audited deployment script.
# This does not merge the new prices into main or invoke the Delta repricing.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin '$ReleaseRef' && git show '$($Target):scripts/deploy_nov10_game_prices.sh' | bash -s -- '$Target'"
& ssh @SshArgs $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS game-price deploy failed or was safely blocked. See output above."
}

Write-Host ""
Write-Host "DEPLOY COMPLETED - old mouth organ and halfcoin blocked, new farming and historical wages retained." -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
