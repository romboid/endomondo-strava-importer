# Bundles endomondo-strava-importer.py into a standalone .exe in dist/
# Usage:  .\build.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "1/3 Installing dependencies..." -ForegroundColor Cyan
python -m pip install --quiet --requirement requirements.txt

python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller is missing, installing..." -ForegroundColor Yellow
    python -m pip install --quiet pyinstaller
}

Write-Host "2/3 Building..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean endomondo-strava-importer.spec

$exe = Join-Path $PSScriptRoot "dist\endomondo-strava-importer.exe"
if (-not (Test-Path $exe)) {
    throw "Build failed, $exe does not exist."
}

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "3/3 Done: $exe ($sizeMb MB)" -ForegroundColor Green
