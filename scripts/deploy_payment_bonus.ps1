param(
    [string]$Vps = "root@178.128.85.16",
    [string]$Target = ""
)

$ErrorActionPreference = "Stop"
$ReleaseRef = "release/payment-qr-tips-bonus-no-price-20261110"
$PriceBase = "d637f16412d15bb8bc77229d105c7816b35da06d"

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

Write-Host "=== SAFE ISOLATED QR + BONUS DEPLOY PRECHECK ===" -ForegroundColor Yellow

if (git status --porcelain) {
    git status --short
    throw "Local working tree has changes. Commit or stash them before deployment."
}

git fetch origin "+refs/heads/${ReleaseRef}:refs/remotes/origin/${ReleaseRef}"
if ($LASTEXITCODE -ne 0) { throw "git fetch isolated release failed" }

git checkout -B $ReleaseRef "origin/$ReleaseRef"
if ($LASTEXITCODE -ne 0) { throw "git checkout isolated release failed" }

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
    $Target = (git rev-parse "origin/$ReleaseRef").Trim()
}

$LocalHead = (git rev-parse HEAD).Trim()
if ($LocalHead -ne $Target) {
    throw "Local HEAD ($LocalHead) does not match target ($Target)."
}

# Price guard compares ONLY business-logic source, not the new QR or bonus code.
$PricePaths = @(
    "services/order_rules.py",
    "services/quick_order_v2_price_lists.py",
    "services/one_companion_one_guard_catalog.py",
    "services/one_companion_one_guard_payout.py",
    "services/orders.py",
    "services/vip_timer_roster_payout.py",
    "services/self_service_point_benefit_policy.py",
    "web/app/services/order_groups.py",
    "web/app/services/order_service.py",
    "web/app/services/checkout_preview.py"
)
& git diff --quiet $PriceBase $Target -- @PricePaths
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED: this release includes Delta pricing changes; deployment refused."
}
Write-Host "PASS: Delta desktop prices remain unchanged." -ForegroundColor Green

Write-Host ""
Write-Host "Target: $Target" -ForegroundColor Cyan
Write-Host "VPS:    $Vps" -ForegroundColor Cyan
Write-Host ""

# The repository is public, so the exact main/push Actions result can be checked
# without storing another credential on the deployment machine. Fail closed when
# GitHub cannot be reached, no run exists yet, the run is still active, or it failed.
Write-Host "=== VERIFY TARGET CI ===" -ForegroundColor Yellow
$GitHubRepo = "leonhu2001/dc-bot"
$CiRunsUri = "https://api.github.com/repos/$GitHubRepo/actions/runs?event=push&head_sha=$Target&per_page=20"
$GitHubHeaders = @{
    "Accept" = "application/vnd.github+json"
    "User-Agent" = "dc-bot-safe-deploy"
    "X-GitHub-Api-Version" = "2022-11-28"
}

try {
    $CiResponse = Invoke-RestMethod -Uri $CiRunsUri -Headers $GitHubHeaders -Method Get -TimeoutSec 15
} catch {
    throw "Unable to verify GitHub CI for target $Target. Deployment blocked. $($_.Exception.Message)"
}

$CiRun = @($CiResponse.workflow_runs) |
    Where-Object {
        $_.name -eq "CI" -and
        $_.event -eq "push" -and
        $_.head_branch -eq $ReleaseRef -and
        $_.head_sha -eq $Target
    } |
    Sort-Object { [datetime]$_.created_at } -Descending |
    Select-Object -First 1

if ($null -eq $CiRun) {
    throw "No isolated-release push CI found for target $Target. Deployment blocked until CI passes."
}
if ($CiRun.status -ne "completed") {
    throw "CI for target $Target is '$($CiRun.status)'. Deployment blocked until it completes successfully."
}
if ($CiRun.conclusion -ne "success") {
    throw "CI for target $Target concluded '$($CiRun.conclusion)'. Deployment blocked."
}

Write-Host "PASS: GitHub CI succeeded for target $Target" -ForegroundColor Green
Write-Host ""

$PanelAssetDir = Join-Path $RepoRoot "assets\order_panels"
$RequiredPanelAssetNames = @(
    "apex_panel.png",
    "lol_panel.png",
    "steam_panel.png",
    "valorant_panel.png",
    "delta_fun_panel.png",
    "delta_farm_3x3.png"
)
$PanelAssets = @()
foreach ($PanelAssetName in $RequiredPanelAssetNames) {
    $PanelAssetPath = Join-Path $PanelAssetDir $PanelAssetName
    if (-not (Test-Path -LiteralPath $PanelAssetPath -PathType Leaf)) {
        throw "Missing order panel image: $PanelAssetPath"
    }

    $PanelAssets += [PSCustomObject]@{
        Name = $PanelAssetName
        Path = $PanelAssetPath
        Hash = (Get-FileHash -LiteralPath $PanelAssetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

# Price lists are text embeds now. Remove the obsolete local image folder so it
# cannot accidentally become a second source of truth again.
$ObsoletePriceListAssetDir = Join-Path $PanelAssetDir "pricelists"
if (Test-Path -LiteralPath $ObsoletePriceListAssetDir) {
    Remove-Item -LiteralPath $ObsoletePriceListAssetDir -Recurse -Force
    Write-Host "PASS: removed obsolete local price-list image directory" -ForegroundColor Green
}

# Compare both VPS copies against the local SHA256 before uploading. A file is
# synchronized when either the runtime source or the public static copy is missing
# or differs. This keeps normal code/CSS deploys from retransferring ~18 MB of
# unchanged panel artwork.
Write-Host "=== SYNC ORDER PANEL IMAGES ===" -ForegroundColor Yellow
$ChangedPanelAssets = @()
foreach ($PanelAsset in $PanelAssets) {
    $RemoteRuntimePath = "/opt/dc-bot/assets/order_panels/$($PanelAsset.Name)"
    $RemotePublicPath = "/opt/dc-bot/web/app/static/order_panels/$($PanelAsset.Name)"
    $RemoteHashCommand = "for p in '$RemoteRuntimePath' '$RemotePublicPath'; do if [ -f `"`$p`" ]; then sha256sum `"`$p`" | cut -d ' ' -f1; else echo MISSING; fi; done"

    $RemoteHashOutput = @(& ssh @SshTransportArgs $Vps $RemoteHashCommand)
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to compare order panel image hash on VPS: $($PanelAsset.Name)"
    }

    $RemoteHashes = @(
        $RemoteHashOutput |
            ForEach-Object { $_.ToString().Trim().ToLowerInvariant() } |
            Where-Object { $_ }
    )

    if (
        $RemoteHashes.Count -eq 2 -and
        $RemoteHashes[0] -eq $PanelAsset.Hash -and
        $RemoteHashes[1] -eq $PanelAsset.Hash
    ) {
        Write-Host "SKIP: $($PanelAsset.Name) unchanged" -ForegroundColor DarkGray
        continue
    }

    $ChangedPanelAssets += $PanelAsset
    Write-Host "CHANGE: $($PanelAsset.Name) will be synchronized" -ForegroundColor Cyan
}

$RemotePanelStage = "/tmp/dc-bot-order-panels"
if ($ChangedPanelAssets.Count -eq 0) {
    Write-Host "SKIP: order panel images unchanged" -ForegroundColor Green
} else {
    Write-Host "Preparing remote panel staging directory..." -ForegroundColor DarkGray
    & ssh @SshTransportArgs $Vps "rm -rf '$RemotePanelStage' && mkdir -p '$RemotePanelStage'"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to prepare remote order-panel staging directory."
    }

    $ChangedPanelAssetPaths = @($ChangedPanelAssets | ForEach-Object { $_.Path })
    Write-Host "Uploading $($ChangedPanelAssets.Count) changed public panel image(s)..." -ForegroundColor DarkGray
    & scp @SshTransportArgs @ChangedPanelAssetPaths "${Vps}:${RemotePanelStage}/"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to upload changed order panel images to VPS staging."
    }

    Write-Host "Installing changed public panel images..." -ForegroundColor DarkGray
    $InstallPanelCommand = "mkdir -p /opt/dc-bot/web/app/static/order_panels /opt/dc-bot/assets/order_panels && install -m 0644 '$RemotePanelStage'/*.png /opt/dc-bot/web/app/static/order_panels/ && install -m 0644 '$RemotePanelStage'/*.png /opt/dc-bot/assets/order_panels/ && rm -rf /opt/dc-bot/web/app/static/order_panels/pricelists /opt/dc-bot/assets/order_panels/pricelists '$RemotePanelStage'"
    & ssh @SshTransportArgs $Vps $InstallPanelCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to install changed order panel images on VPS."
    }
    Write-Host "PASS: $($ChangedPanelAssets.Count) changed order panel image(s) synchronized before service restart" -ForegroundColor Green
}
Write-Host ""

# Image assets are not committed to Git. Verify the owner's exact local
# bank QR codes and transfer the real images before restarting bot/web.
Write-Host "=== SYNC PAYMENT QR IMAGES ===" -ForegroundColor Yellow
$QrAssetDirectory = Join-Path $RepoRoot "web\app\static\images\payment"
$QrNames = @("cathay_qr.jpg", "jkopay_qr.jpg")
$QrPaths = @()
foreach ($QrName in $QrNames) {
    $QrPath = Join-Path $QrAssetDirectory $QrName
    if (-not (Test-Path -LiteralPath $QrPath -PathType Leaf)) {
        throw "Missing original customer-supplied payment image: $QrPath"
    }
    if ((Get-Item -LiteralPath $QrPath).Length -lt 1024) {
        throw "Invalid payment QR image: $QrPath"
    }
    $QrPaths += $QrPath
}

$RemoteQrDir = "/opt/dc-bot/web/app/static/images/payment"
& ssh @SshTransportArgs $Vps "mkdir -p '$RemoteQrDir'"
if ($LASTEXITCODE -ne 0) { throw "Failed to create payment QR folder on VPS." }
& scp @SshTransportArgs @QrPaths "${Vps}:${RemoteQrDir}/"
if ($LASTEXITCODE -ne 0) { throw "Failed to transfer payment QR image(s)." }

foreach ($QrPath in $QrPaths) {
    $QrName = [IO.Path]::GetFileName($QrPath)
    $LocalQrHash = (Get-FileHash -LiteralPath $QrPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $RemoteQrHash = (& ssh @SshTransportArgs $Vps "sha256sum '$RemoteQrDir/$QrName' | cut -d ' ' -f1").Trim().ToLowerInvariant()
    if ($LASTEXITCODE -ne 0 -or $RemoteQrHash -ne $LocalQrHash) {
        throw "QR upload checksum mismatch: $QrName. Aborting deployment."
    }
    Write-Host "PASS: $QrName verified on VPS" -ForegroundColor Green
}
Write-Host ""

# Use only the CI-tested release branch, NEVER origin/main, which already
# contains the deferred Delta price update.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin '$ReleaseRef' && git show '${Target}:scripts/deploy_payment_bonus.sh' | bash -s -- '$Target'"
& ssh @SshTransportArgs $Vps $RemoteCommand
if ($LASTEXITCODE -ne 0) {
    throw "VPS deployment failed. Check rollback output above."
}

Write-Host ""
Write-Host "=== VERIFY PUBLIC ORDER PANEL IMAGES ===" -ForegroundColor Yellow

# Only public assets changed during this deployment need a network verification.
# Use one GET per changed image and inspect the captured response headers for both
# image content type and the Discord-required cross-origin resource policy.
if ($ChangedPanelAssets.Count -eq 0) {
    Write-Host "SKIP: no changed public panel images to verify" -ForegroundColor Green
} else {
    foreach ($PanelAsset in $ChangedPanelAssets) {
        $AssetRelativePath = $PanelAsset.Name
        $PublicAssetUrl = "https://mowanentertainment.com/static/order_panels/${AssetRelativePath}?deploy=$Target"
        $VerifyAssetCommand = "headers=`$(mktemp); trap 'rm -f `"`$headers`"' EXIT; curl --fail --silent --show-error --max-time 20 -o /dev/null -D `"`$headers`" '$PublicAssetUrl' && tr -d '\r' < `"`$headers`" | grep -Eqi '^content-type:[[:space:]]*image/png([;[:space:]]|$)' && tr -d '\r' < `"`$headers`" | grep -Eqi '^cross-origin-resource-policy:[[:space:]]*cross-origin([[:space:]]|$)'"

        & ssh @SshTransportArgs $Vps $VerifyAssetCommand
        if ($LASTEXITCODE -ne 0) {
            throw "Public order panel image verification failed: $AssetRelativePath"
        }

        Write-Host "PASS: $AssetRelativePath" -ForegroundColor Green
    }
    Write-Host "PASS: changed public order panel image URLs are reachable" -ForegroundColor Green
}

Write-Host ""
Write-Host "DEPLOY COMPLETED - prices unchanged" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
Write-Host ""
Write-Host "=== READ-ONLY NOVEMBER BONUS AUDIT ===" -ForegroundColor Yellow
& ssh @SshTransportArgs $Vps "cd /opt/dc-bot && ./venv/bin/python scripts/audit_november_bonus_20261109.py"
if ($LASTEXITCODE -ne 0) {
    Write-Warning "November audit failed; no bonus payments were changed."
}
Write-Host "=== VERIFIED BONUS RESTORATION PREVIEW (NO WRITES) ===" -ForegroundColor Yellow
& ssh @SshTransportArgs $Vps "cd /opt/dc-bot && ./venv/bin/python scripts/restore_approved_bonus_payouts_20261108.py --all-november --auto-archives"
if ($LASTEXITCODE -ne 0) {
    Write-Warning "No safe restoration candidates, or preview failed. Check output."
}
Write-Host "NOTE: actual payout restoration is not automatically applied." -ForegroundColor Yellow
