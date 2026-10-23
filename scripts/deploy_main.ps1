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

# Upload artwork before the safe deployment. The files live in ignored runtime
# directories, so git reset/checkout does not remove them. Keeping a compatibility
# copy under assets/order_panels also lets the previous attachment-based build keep
# working if the safe deploy rolls back.
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

# Run the existing safe deployment after artwork is already in place. deploy_main.sh
# owns the single bot/web restart, so image support no longer adds a second restart.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"
ssh $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

Write-Host ""
Write-Host "=== VERIFY PUBLIC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
$PanelAssetNameList = ($RequiredPanelAssetNames -join " ")
# Verify a fresh query-string URL so Cloudflare cannot satisfy this check from a
# response cached before the cross-origin image headers were installed.
$VerifyCommand = "set -e; for name in $PanelAssetNameList; do url=`"https://mowanentertainment.com/static/order_panels/`$name?deploy=$Target`"; headers=`$(curl --fail --silent --show-error --max-time 10 -I `"`$url`"); echo `"`$headers`" | tr -d '' | grep -qi '^content-type: image/png' || { echo `"Invalid image content-type for `$name`"; exit 1; }; echo `"`$headers`" | tr -d '' | grep -qi '^cross-origin-resource-policy: cross-origin' || { echo `"Missing cross-origin image policy for `$name`"; exit 1; }; done"
ssh $Vps $VerifyCommand
if ($LASTEXITCODE -ne 0) {
    throw "One or more public order panel image URLs failed Discord-safe HTTP verification."
}
Write-Host "PASS: public order panel image URLs are reachable with cross-origin image headers" -ForegroundColor Green

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
