param(
    [string]$Target = "https://app.852941.xyz/",
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $RepoRoot

if (-not $Output) {
    $Output = Join-Path ([System.IO.Path]::GetTempPath()) "market_source_probe_852941.json"
}

$Candidates = @(
    (Join-Path $RepoRoot "venv\Scripts\python.exe"),
    (Join-Path $RepoRoot ".venv\Scripts\python.exe")
)
$Python = $null
foreach ($Candidate in $Candidates) {
    if (Test-Path -LiteralPath $Candidate -PathType Leaf) {
        $Python = $Candidate
        break
    }
}
if (-not $Python) {
    $Command = Get-Command python -ErrorAction SilentlyContinue
    if ($Command) {
        $Python = $Command.Source
    }
}
if (-not $Python) {
    throw "Python executable not found. Expected venv\\Scripts\\python.exe, .venv\\Scripts\\python.exe, or python on PATH."
}

Write-Host "=== PUBLIC MARKET SOURCE PROBE ===" -ForegroundColor Yellow
Write-Host "Target: $Target" -ForegroundColor Cyan
Write-Host "Mode:   public GET-only discovery" -ForegroundColor DarkGray
Write-Host "Output: $Output" -ForegroundColor DarkGray
Write-Host ""

& $Python "tools/probe_public_market_source.py" --target $Target --output $Output
if ($LASTEXITCODE -ne 0) {
    throw "Public market source probe failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "PROBE COMPLETED" -ForegroundColor Green
Write-Host "Paste the JSON report back into ChatGPT; candidate URLs are discovery-only and were not invoked." -ForegroundColor Cyan
