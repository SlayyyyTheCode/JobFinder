# JobPilot launcher.
#   .\start.ps1          build UI if needed, run app at http://localhost:8000
#   .\start.ps1 -Dev     backend on :8000 + Vite dev server with hot reload on :5173
#   .\start.ps1 -Setup   (re)install dependencies only
param([switch]$Dev, [switch]$Setup)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"

if ($Setup -or -not (Test-Path $py)) {
    Write-Host "Setting up Python environment..." -ForegroundColor Cyan
    py -3.13 -m venv (Join-Path $root "backend\.venv")
    & $py -m pip install -q --upgrade pip
    & $py -m pip install -q -r (Join-Path $root "backend\requirements.txt")
    & $py -m playwright install chromium
}
if ($Setup -or -not (Test-Path (Join-Path $root "frontend\node_modules"))) {
    Write-Host "Installing frontend packages..." -ForegroundColor Cyan
    Push-Location (Join-Path $root "frontend"); npm install --no-audit --no-fund; Pop-Location
}
if (-not (Test-Path (Join-Path $root ".env"))) {
    Copy-Item (Join-Path $root ".env.example") (Join-Path $root ".env")
    Write-Host "Created .env - add your GEMINI_API_KEY to it, then run start.ps1 again." -ForegroundColor Yellow
    notepad (Join-Path $root ".env")
    exit 0
}
if ($Setup) { exit 0 }

if ($Dev) {
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"
    Start-Process "http://localhost:5173"
} else {
    $dist = Join-Path $root "frontend\dist\index.html"
    $src = Get-ChildItem (Join-Path $root "frontend\src") -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not (Test-Path $dist) -or $src.LastWriteTime -gt (Get-Item $dist).LastWriteTime) {
        Write-Host "Building UI..." -ForegroundColor Cyan
        Push-Location (Join-Path $root "frontend"); npm run build; Pop-Location
    }
    Start-Job -ScriptBlock { Start-Sleep 3; Start-Process "http://localhost:8000" } | Out-Null
}
Write-Host "JobPilot running at http://localhost:8000  (Ctrl+C to stop)" -ForegroundColor Green
Push-Location (Join-Path $root "backend")
& $py -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Pop-Location
