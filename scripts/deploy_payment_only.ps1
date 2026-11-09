param(
    [string]$Vps = "root@178.128.85.16",
    [Parameter(Mandatory=$true)][string]$Target
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$Ref = "feat/payment-qrs-profile-tips-only-20261109"
$Base = "d637f16412d15bb8bc77229d105c7816b35da06d"
$SshArgs = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")

git fetch origin $Ref
if ($LASTEXITCODE -ne 0) { throw "git fetch failed" }
$BranchHead = (git rev-parse "FETCH_HEAD").Trim()
if ($BranchHead -ne $Target) { throw "Target is not feature branch HEAD" }

$PricingPaths = @(
    "services/order_rules.py", "services/orders.py",
    "services/quick_order_v2_price_lists.py",
    "services/one_companion_one_guard_payout.py",
    "web/app/services/checkout_preview.py"
)
$Changed = @(git diff --name-only "$Base" "$Target")
if ($LASTEXITCODE -ne 0) { throw "Failed to compare feature release" }
foreach ($FileName in $Changed) {
    if ($PricingPaths -contains $FileName) {
        throw "Deployment blocked: price change detected: $FileName"
    }
}

$RunUrl = "https://api.github.com/repos/leonhu2001/dc-bot/actions/runs?head_sha=$Target&per_page=20"
$Runs = Invoke-RestMethod -Uri $RunUrl -Headers @{"Accept"="application/vnd.github+json"}
$Passed = @($Runs.workflow_runs | Where-Object {
    $_.name -eq "CI" -and $_.conclusion -eq "success"
})
if ($Passed.Count -eq 0) {
    throw "No successful CI found for isolated release $Target"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "sync_payment_qr_images.ps1") -Vps $Vps
if ($LASTEXITCODE -ne 0) { throw "QR image sync failed; code not deployed" }

$Source = @(git show "${Target}:scripts/deploy_payment_only.sh")
if ($LASTEXITCODE -ne 0 -or $Source.Count -eq 0) {
    throw "Missing audited isolated release shell"
}
$Source | & ssh @SshArgs $Vps "bash -s -- '$Target'"
if ($LASTEXITCODE -ne 0) { throw "Isolated VPS deployment failed or rolled back" }
Write-Host "PAYMENT-ONLY DEPLOY COMPLETE (Delta prices untouched)" -ForegroundColor Green
