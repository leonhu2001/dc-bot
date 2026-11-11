param(
    [string]$Vps = "root@178.128.85.16",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$ReleaseRef = "fix/support-panel-order-guide-recruit-examiner-20261111"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "=== SAFE SUPPORT PANEL ORDER NOTICE + RECRUIT EXAMINER DEPLOY ===" -ForegroundColor Yellow

if (git status --porcelain) {
    git status --short
    throw "Local working tree has edits. Commit or stash before deploying."
}

git fetch origin "+refs/heads/$($ReleaseRef):refs/remotes/origin/$($ReleaseRef)"
if ($LASTEXITCODE -ne 0) { throw "Failed to fetch support panel release." }

git checkout -B $ReleaseRef "origin/$ReleaseRef"
if ($LASTEXITCODE -ne 0) { throw "Failed to switch to support panel release." }

$RemoteHead = (git rev-parse "origin/$ReleaseRef").Trim()
if (-not $Target) { $Target = $RemoteHead }
$LocalHead = (git rev-parse HEAD).Trim()
if ($LocalHead -ne $Target -or $RemoteHead -ne $Target) {
    throw "Pinned panel target mismatch. Local=$LocalHead Remote=$RemoteHead Expected=$Target."
}

Write-Host "=== VERIFY PINNED GITHUB CI ===" -ForegroundColor Yellow
$Headers = @{
    "Accept" = "application/vnd.github+json"
    "User-Agent" = "dc-bot-safe-panel-links-deploy"
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
    throw "BLOCKED: the exact panel release CI is not successful."
}
Write-Host "PASS: exact release CI success" -ForegroundColor Green

$SshArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=12",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3"
)
$RemoteCommand = "cd /opt/dc-bot && git fetch origin '$ReleaseRef' && git show '$($Target):scripts/deploy_support_panel_links_20261111.sh' | bash -s -- '$Target'"
Write-Host "VPS: $Vps" -ForegroundColor Cyan
& ssh @SshArgs $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED: support panel was not verified on Discord. See rollback output."
}

Write-Host ""
Write-Host "DEPLOY COMPLETED - order notice linked, emojis removed, recruiter examiner authorized; four buttons retained." -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
