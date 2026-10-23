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

$PanelAssetDir = Join-Path $RepoRoot "assets\order_panels"
$PanelAssetNames = @(
    "apex_panel.png",
    "lol_panel.png",
    "steam_panel.png",
    "valorant_panel.png"
)
$PanelAssetPaths = @()
foreach ($PanelAssetName in $PanelAssetNames) {
    $PanelAssetPath = Join-Path $PanelAssetDir $PanelAssetName
    if (-not (Test-Path -LiteralPath $PanelAssetPath -PathType Leaf)) {
        throw "Missing order panel image: $PanelAssetPath"
    }
    $PanelAssetPaths += $PanelAssetPath
}

# First complete the normal safe source deployment. The target commit includes a
# gitignore rule for the generated website static copies, so future deploy
# prechecks remain clean after the artwork is synchronized below.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"

ssh $Vps $RemoteCommand

if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

Write-Host ""
Write-Host "=== SYNC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
ssh $Vps "mkdir -p /opt/dc-bot/web/app/static/order_panels"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare VPS order panel static directory."
}

& scp @PanelAssetPaths "${Vps}:/opt/dc-bot/web/app/static/order_panels/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order panel images to VPS."
}
Write-Host "PASS: order panel images uploaded to web static" -ForegroundColor Green

# StaticFiles serves directly from disk, so the web process does not need another
# restart. Restart only the bot so it rebuilds the four Discord panels after the
# public image URLs are guaranteed to exist.
ssh $Vps "systemctl restart dc-bot.service && systemctl is-active --quiet dc-bot.service"
if ($LASTEXITCODE -ne 0) {
    throw "Bot restart after order panel image sync failed."
}
Write-Host "PASS: bot restarted after order panel image sync" -ForegroundColor Green

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
