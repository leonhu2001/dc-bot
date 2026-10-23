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
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }

git checkout main
if ($LASTEXITCODE -ne 0) { throw "git checkout main failed" }

git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "git pull --ff-only failed" }

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

# Deploy source first using the existing safe rollback flow.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"
ssh $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

Write-Host ""
Write-Host "=== SYNC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
# Remove the obsolete website-static rollout from the previous implementation.
ssh $Vps "rm -rf /opt/dc-bot/web/app/static/order_panels && mkdir -p /opt/dc-bot/assets/order_panels"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare VPS order panel asset directory."
}

& scp @PanelAssetPaths "${Vps}:/opt/dc-bot/assets/order_panels/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order panel images to VPS."
}

ssh $Vps "chmod 0644 /opt/dc-bot/assets/order_panels/*.png"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to set order panel image permissions."
}
Write-Host "PASS: order panel images uploaded beside bot" -ForegroundColor Green

# Restart only the bot after the real PNG files are in place. On startup the
# quick-order image layer sends each panel as one embed+file request, then removes
# the previous panel message.
ssh $Vps "systemctl restart dc-bot.service && systemctl is-active --quiet dc-bot.service"
if ($LASTEXITCODE -ne 0) {
    throw "Bot restart after order panel image sync failed."
}
Write-Host "PASS: bot restarted after order panel image sync" -ForegroundColor Green

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
