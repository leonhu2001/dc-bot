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
        $_.head_branch -eq "main" -and
        $_.head_sha -eq $Target
    } |
    Sort-Object { [datetime]$_.created_at } -Descending |
    Select-Object -First 1

if ($null -eq $CiRun) {
    throw "No main/push CI run found for target $Target. Deployment blocked until CI runs."
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
    "delta_fun_panel.png"
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

# Run the existing safe deployment. deploy_main.sh owns the single bot/web restart.
$RemoteCommand = "cd /opt/dc-bot && git fetch origin main && git show '${Target}:scripts/deploy_main.sh' | bash -s -- '$Target'"
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
Write-Host "DEPLOY COMPLETED" -ForegroundColor Green
Write-Host "Commit: $Target" -ForegroundColor Cyan
