# Installs JobPilot as a desktop app: builds the UI, creates the icon, and adds
# "JobPilot" shortcuts to your Desktop and Start menu. Safe to re-run.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
$pyw = Join-Path $root "backend\.venv\Scripts\pythonw.exe"

if (-not (Test-Path $py)) { & (Join-Path $root "start.ps1") -Setup }

if (-not (Test-Path (Join-Path $root "frontend\dist\index.html"))) {
    Write-Host "Building UI..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend"); npm run build; Pop-Location
}

$ico = Join-Path $root "assets\jobpilot.ico"
if (-not (Test-Path $ico)) { & $py (Join-Path $root "backend\make_icon.py") $ico }

$ws = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "JobPilot.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "JobPilot.lnk")
)
foreach ($t in $targets) {
    $s = $ws.CreateShortcut($t)
    $s.TargetPath = $pyw
    $s.Arguments = '"' + (Join-Path $root "backend\launcher.py") + '"'
    $s.WorkingDirectory = $root
    $s.IconLocation = $ico
    $s.Description = "JobPilot - AI job application assistant"
    $s.Save()
    Write-Host "Created $t" -ForegroundColor Green
}
Write-Host "Done. Double-click JobPilot on your Desktop (or search 'JobPilot' in Start). Logs: $env:LOCALAPPDATA\JobPilot\data\jobpilot.log"
