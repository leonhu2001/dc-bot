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
$RequiredPanelAssetNames = @(
    "apex_panel.png",
    "lol_panel.png",
    "steam_panel.png",
    "valorant_panel.png",
    "delta_fun_panel.png"
)
$PanelAssetPaths = @()
foreach ($PanelAssetName in $RequiredPanelAssetNames) {
    $PanelAssetPath = Join-Path $PanelAssetDir $PanelAssetName
    if (-not (Test-Path -LiteralPath $PanelAssetPath -PathType Leaf)) {
        throw "Missing order panel image: $PanelAssetPath"
    }
    $PanelAssetPaths += $PanelAssetPath
}

$PriceListAssetDir = Join-Path $PanelAssetDir "pricelists"
$RequiredPriceListAssetNames = @(
    "lol_pricelist.png",
    "valorant_pricelist.png"
)
$PriceListAssetPaths = @()
foreach ($PriceListAssetName in $RequiredPriceListAssetNames) {
    $PriceListAssetPath = Join-Path $PriceListAssetDir $PriceListAssetName
    if (-not (Test-Path -LiteralPath $PriceListAssetPath -PathType Leaf)) {
        throw "Missing order price-list image: $PriceListAssetPath"
    }
    $PriceListAssetPaths += $PriceListAssetPath
}

# Upload root artwork before the safe deployment. These files are already part of
# the established runtime-artwork flow and are needed when public panels refresh
# during bot startup.
Write-Host "=== SYNC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
$RemotePanelStage = "/tmp/dc-bot-order-panels"
ssh $Vps "rm -rf '$RemotePanelStage' && mkdir -p '$RemotePanelStage'"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare remote order-panel staging directory."
}

& scp @PanelAssetPaths "${Vps}:${RemotePanelStage}/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order panel images to VPS staging."
}

ssh $Vps "mkdir -p /opt/dc-bot/web/app/static/order_panels /opt/dc-bot/assets/order_panels && install -m 0644 '$RemotePanelStage'/*.png /opt/dc-bot/web/app/static/order_panels/ && install -m 0644 '$RemotePanelStage'/*.png /opt/dc-bot/assets/order_panels/ && rm -rf '$RemotePanelStage'"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install order panel images on VPS."
}
Write-Host "PASS: order panel images synchronized before service restart" -ForegroundColor Green
Write-Host ""

# Run the existing safe deployment. deploy_main.sh owns the single bot/web restart.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"
ssh $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

# Price-list images are only resolved when a customer presses the price-list
# button, so they can be installed after the safe deployment without another bot
# restart. The target .gitignore is active by this point, so nested runtime artwork
# does not dirty the VPS working tree.
Write-Host ""
Write-Host "=== SYNC ORDER PRICE-LIST IMAGES ===" -ForegroundColor Yellow
ssh $Vps "mkdir -p /opt/dc-bot/web/app/static/order_panels/pricelists"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare VPS price-list image directory."
}

& scp @PriceListAssetPaths "${Vps}:/opt/dc-bot/web/app/static/order_panels/pricelists/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order price-list images to VPS."
}

ssh $Vps "chmod 0644 /opt/dc-bot/web/app/static/order_panels/pricelists/*.png"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to set price-list image permissions."
}
Write-Host "PASS: order price-list images uploaded without extra service restart" -ForegroundColor Green

Write-Host ""
Write-Host "=== VERIFY PUBLIC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
$RequiredPublicAssetRelativePaths = @()
$RequiredPublicAssetRelativePaths += $RequiredPanelAssetNames
foreach ($PriceListAssetName in $RequiredPriceListAssetNames) {
    $RequiredPublicAssetRelativePaths += "pricelists/$PriceListAssetName"
}
$PanelAssetNameList = ($RequiredPublicAssetRelativePaths -join " ")

# Query the public URL exactly as Discord will. Nginx serves this PNG-only
# directory with an explicit image/png MIME mapping. When validation fails, print
# the real response headers so the next diagnosis has concrete data.
$VerifyCommand = "set -e; for name in $PanelAssetNameList; do url=`"https://mowanentertainment.com/static/order_panels/`$name?deploy=$Target`"; headers=`$(curl --fail --silent --show-error --max-time 10 -I `"`$url`"); echo `"`$headers`" | grep -Eqi '^content-type:[[:space:]]*image/png([;[:space:]]|$)' || { echo `"--- headers for `$name ---`"; echo `"`$headers`"; echo `"Invalid image content-type for `$name`"; exit 1; }; echo `"`$headers`" | grep -Eqi '^cross-origin-resource-policy:[[:space:]]*cross-origin([[:space:]]|$)' || { echo `"--- headers for `$name ---`"; echo `"`$headers`"; echo `"Missing cross-origin image policy for `$name`"; exit 1; }; done"
ssh $Vps $VerifyCommand
if ($LASTEXITCODE -ne 0) {
    throw "One or more public order panel image URLs failed Discord-safe HTTP verification."
}
Write-Host "PASS: public order panel and price-list image URLs are reachable" -ForegroundColor Green

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
