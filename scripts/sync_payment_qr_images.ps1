param(
    [string]$Vps = "root@178.128.85.16"
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LocalFolder = Join-Path $RepoRoot "web\app\static\images\payment"
$RemoteFolder = "/opt/dc-bot/web/app/static/images/payment"
$SshArgs = @("-o", "BatchMode=yes", "-o", "ConnectTimeout=10")

$Files = @(
    "cathay_qr.jpg",
    "jkopay_qr.jpg"
)

foreach ($FileName in $Files) {
    $LocalFile = Join-Path $LocalFolder $FileName
    if (-not (Test-Path -LiteralPath $LocalFile -PathType Leaf)) {
        throw "找不到付款 QR 檔案：$LocalFile"
    }
    if ((Get-Item -LiteralPath $LocalFile).Length -le 0) {
        throw "付款 QR 檔案為空白：$LocalFile"
    }
}

Write-Host "=== COPY PAYMENT QR ASSETS ONLY ==="
& ssh @SshArgs $Vps "mkdir -p '$RemoteFolder'"
if ($LASTEXITCODE -ne 0) { throw "VPS 無法建立 QR 資料夾" }

foreach ($FileName in $Files) {
    $LocalFile = Join-Path $LocalFolder $FileName
    & scp @SshArgs "$LocalFile" "${Vps}:$RemoteFolder/$FileName"
    if ($LASTEXITCODE -ne 0) { throw "上傳 $FileName 失敗" }

    $LocalSha = (Get-FileHash -LiteralPath $LocalFile -Algorithm SHA256).Hash.ToLowerInvariant()
    $RemoteHash = (& ssh @SshArgs $Vps "sha256sum '$RemoteFolder/$FileName'").Trim()
    if ($LASTEXITCODE -ne 0) { throw "無法驗證 VPS $FileName" }
    $RemoteSha = ($RemoteHash -split "\s+")[0].ToLowerInvariant()
    if ($LocalSha -ne $RemoteSha) { throw "VPS $FileName SHA256 不一致" }
    Write-Host "PASS: $FileName" -ForegroundColor Green
}
Write-Host "PAYMENT QR ASSET SYNC COMPLETED (no code or prices deployed)" -ForegroundColor Green
