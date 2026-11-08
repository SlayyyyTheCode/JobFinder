# Creates the 3 secrets an online JobPilot needs and saves them OUTSIDE this project
# (not in git, not in OneDrive): %LOCALAPPDATA%\JobPilot\hosted-secrets.txt
#   .\make-secrets.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Run .\start.ps1 -Setup first." -ForegroundColor Yellow; exit 1 }

Push-Location (Join-Path $root "backend")
try {
    Write-Host "Choose the password you will use to sign in to your ONLINE JobPilot (12+ characters)." -ForegroundColor Cyan
    $hash = & $py -m app.auth hash
    if ($LASTEXITCODE -ne 0 -or -not $hash) { Write-Host "Cancelled." -ForegroundColor Yellow; exit 1 }
    $secret = & $py -m app.auth secret
    $fernet = & $py -m app.auth fernet-key
} finally { Pop-Location }

$out = Join-Path $env:LOCALAPPDATA "JobPilot\hosted-secrets.txt"
New-Item -ItemType Directory -Force (Split-Path $out) | Out-Null
@("APP_PASSWORD_HASH=$hash", "SESSION_SECRET=$secret", "TOKEN_ENCRYPTION_KEY=$fernet") | Set-Content $out -Encoding ascii

Write-Host ""
Write-Host "Saved to: $out" -ForegroundColor Green
Write-Host "Copy it into your password manager, paste the lines into Railway, then delete the file." -ForegroundColor Green
Write-Host "Your sign-in password is NOT in the file - remember it (or save it in your password manager)."
notepad $out
