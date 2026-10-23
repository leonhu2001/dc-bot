param(
    [string]$Vps = "root@178.128.85.16",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot
$ScriptPath = $PSCommandPath
$ScriptHashBeforePull = (Get-FileHash -LiteralPath $ScriptPath -Algorithm SHA256).Hash

# Keep SSH/SCP from hanging forever on a dead transport. ConnectTimeout covers
# connection establishment; the keepalive pair terminates a session when the
# remote stops responding after it has connected.
$SshTransportArgs = @(
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2"
)

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

# PowerShell parses the current script before execution. If git pull replaces this
# file, continuing this process would still run the stale in-memory version. Relaunch
# once from disk so the rest of deployment always uses the newly pulled script.
$ScriptHashAfterPull = (Get-FileHash -LiteralPath $ScriptPath -Algorithm SHA256).Hash
if ($ScriptHashAfterPull -ne $ScriptHashBeforePull) {
    Write-Host "Deploy script updated during precheck; relaunching updated script..." -ForegroundColor Yellow
    $RelaunchArgs = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $ScriptPath,
        "-Vps", $Vps
    )
    if ($Target) {
        $RelaunchArgs += @("-Target", $Target)
    }
    & powershell.exe @RelaunchArgs
    exit $LASTEXITCODE
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
Write-Host "Preparing remote panel staging directory..." -ForegroundColor DarkGray
& ssh @SshTransportArgs $Vps "rm -rf '$RemotePanelStage' && mkdir -p '$RemotePanelStage'"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare remote order-panel staging directory."
}

Write-Host "Uploading 5 public panel images..." -ForegroundColor DarkGray
& scp @SshTransportArgs @PanelAssetPaths "${Vps}:${RemotePanelStage}/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order panel images to VPS staging."
}

Write-Host "Installing public panel images..." -ForegroundColor DarkGray
& ssh @SshTransportArgs $Vps "mkdir -p /opt/dc-bot/web/app/static/order_panels /opt/dc-bot/assets/order_panels && install -m 0644 '$RemotePanelStage'/*.png /opt/dc-bot/web/app/static/order_panels/ && install -m 0644 '$RemotePanelStage'/*.png /opt/dc-bot/assets/order_panels/ && rm -rf '$RemotePanelStage'"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install order panel images on VPS."
}
Write-Host "PASS: order panel images synchronized before service restart" -ForegroundColor Green
Write-Host ""

# Run the existing safe deployment. deploy_main.sh owns the single bot/web restart.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"
& ssh @SshTransportArgs $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

# Price-list images are only resolved when a customer presses the price-list
# button, so they can be installed after the safe deployment without another bot
# restart. Stage first, then install with the final mode in a single remote command.
# This avoids opening a second SSH session just for chmod, which can leave Windows
# OpenSSH waiting even though the file transfer has already completed.
Write-Host ""
Write-Host "=== SYNC ORDER PRICE-LIST IMAGES ===" -ForegroundColor Yellow
$RemotePriceListStage = "/tmp/dc-bot-order-pricelists"
Write-Host "Preparing remote price-list staging directory..." -ForegroundColor DarkGray
& ssh @SshTransportArgs $Vps "rm -rf '$RemotePriceListStage' && mkdir -p '$RemotePriceListStage'"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to prepare VPS price-list staging directory."
}
Write-Host "PASS: remote price-list staging directory ready" -ForegroundColor Green

Write-Host "Uploading 2 price-list images..." -ForegroundColor DarkGray
& scp @SshTransportArgs @PriceListAssetPaths "${Vps}:${RemotePriceListStage}/"
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upload order price-list images to VPS staging."
}
Write-Host "PASS: price-list image transfer complete" -ForegroundColor Green

Write-Host "Installing price-list images..." -ForegroundColor DarkGray
$InstallPriceListCommand = "mkdir -p /opt/dc-bot/web/app/static/order_panels/pricelists && install -m 0644 '$RemotePriceListStage'/*.png /opt/dc-bot/web/app/static/order_panels/pricelists/ && rm -rf '$RemotePriceListStage'"
& ssh @SshTransportArgs $Vps $InstallPriceListCommand
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install order price-list images."
}
Write-Host "PASS: order price-list images uploaded without extra service restart" -ForegroundColor Green

Write-Host ""
Write-Host "=== VERIFY PUBLIC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
$RequiredPublicAssetRelativePaths = @()
$RequiredPublicAssetRelativePaths += $RequiredPanelAssetNames
foreach ($PriceListAssetName in $RequiredPriceListAssetNames) {
    $RequiredPublicAssetRelativePaths += "pricelists/$PriceListAssetName"
}

# Verify the same GET request shape that Discord uses instead of HEAD. Cloudflare
# returns CRLF-delimited response headers; parsing them after storing the raw block
# in a shell variable can make carriage returns overwrite console output and cause
# false negatives. Ask curl for the effective content type directly, and normalize
# CRLF only for the header-specific CORP check.
foreach ($AssetRelativePath in $RequiredPublicAssetRelativePaths) {
    $PublicAssetUrl = "https://mowanentertainment.com/static/order_panels/${AssetRelativePath}?deploy=$Target"
    $VerifyAssetCommand = "curl --fail --silent --show-error --max-time 10 -o /dev/null -w '%{content_type}\n' '$PublicAssetUrl' | grep -Eqi '^image/png([;[:space:]]|$)' || { echo '--- response headers for $AssetRelativePath ---'; curl --silent --show-error --max-time 10 -o /dev/null -D - '$PublicAssetUrl' | tr -d '\r'; echo 'Invalid image content-type for $AssetRelativePath'; exit 1; }; curl --fail --silent --show-error --max-time 10 -o /dev/null -D - '$PublicAssetUrl' | tr -d '\r' | grep -Eqi '^cross-origin-resource-policy:[[:space:]]*cross-origin([[:space:]]|$)' || { echo '--- response headers for $AssetRelativePath ---'; curl --silent --show-error --max-time 10 -o /dev/null -D - '$PublicAssetUrl' | tr -d '\r'; echo 'Missing cross-origin image policy for $AssetRelativePath'; exit 1; }"

    & ssh @SshTransportArgs $Vps $VerifyAssetCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Public order panel image verification failed: $AssetRelativePath"
    }

    Write-Host "PASS: $AssetRelativePath" -ForegroundColor Green
}
Write-Host "PASS: public order panel and price-list image URLs are reachable" -ForegroundColor Green

Write-Host ""
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
