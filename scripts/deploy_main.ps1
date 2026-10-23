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

# Order-panel artwork is intentionally kept as local source PNGs instead of
# tracked Git binaries. Copy the four real files to the VPS before the safe
# deploy restarts the bot, so the startup panel refresh can attach them directly.
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

Write-Host "=== SYNC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
ssh $Vps "mkdir -p /opt/dc-bot/assets/order_panels"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare VPS order panel asset directory."
}

& scp @PanelAssetPaths "${Vps}:/opt/dc-bot/assets/order_panels/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order panel images to VPS."
}
Write-Host "PASS: order panel images uploaded" -ForegroundColor Green
Write-Host ""

$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"

ssh $Vps $RemoteCommand

if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
