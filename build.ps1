# Zabali endomondo-strava-importer.py do samostatneho .exe v dist/
# Pouzitie:  .\build.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "1/3 Instalujem zavislosti..." -ForegroundColor Cyan
python -m pip install --quiet --requirement requirements.txt

python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyInstaller chyba, instalujem..." -ForegroundColor Yellow
    python -m pip install --quiet pyinstaller
}

Write-Host "2/3 Buildujem..." -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean endomondo-strava-importer.spec

$exe = Join-Path $PSScriptRoot "dist\endomondo-strava-importer.exe"
if (-not (Test-Path $exe)) {
    throw "Build zlyhal, $exe neexistuje."
}

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host "3/3 Hotovo: $exe ($sizeMb MB)" -ForegroundColor Green
