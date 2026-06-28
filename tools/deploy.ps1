param(
    [switch]$BotOnly,
    [switch]$DashboardOnly
)

$ErrorActionPreference = "Stop"

$Server = "root@178.128.85.16"
$RemoteDir = "/opt/dc-bot"
$Branch = "web-dashboard"

Write-Host "Checking local git status..." -ForegroundColor Cyan
$dirty = git status --porcelain
if ($dirty) {
    Write-Host "本機還有未 commit 的變更，請先 commit 後再部署：" -ForegroundColor Yellow
    git status
    exit 1
}

Write-Host "Pushing $Branch..." -ForegroundColor Cyan
git push origin $Branch

$restart = @()
if (-not $DashboardOnly) { $restart += "dc-bot.service" }
if (-not $BotOnly) { $restart += "dc-bot-dashboard.service" }

$restartCmd = ($restart | ForEach-Object { "systemctl restart $_" }) -join " && "
$statusCmd = ($restart | ForEach-Object { "systemctl status $_ --no-pager -l | head -20" }) -join " && "

$remoteCmd = @"
cd $RemoteDir &&
git pull --ff-only origin $Branch &&
python3 -m py_compile core/vip_levels.py bot.py services/rewards.py views/voice.py web/app/routers/order_history.py web/app/routers/admin.py &&
$restartCmd &&
$statusCmd
"@

Write-Host "Deploying to VPS..." -ForegroundColor Cyan
ssh $Server $remoteCmd

