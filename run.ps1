$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
}
$pilotDependencyHash = (Get-FileHash -LiteralPath 'requirements.txt' -Algorithm SHA256).Hash
$pilotHashPath = '.venv\requirements.sha256'
$pilotInstalledHash = if (Test-Path -LiteralPath $pilotHashPath) { (Get-Content -LiteralPath $pilotHashPath -Raw).Trim() } else { '' }
if ($pilotInstalledHash -ne $pilotDependencyHash) {
    & '.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    Set-Content -LiteralPath $pilotHashPath -Value $pilotDependencyHash
}
Write-Host 'LANCE: http://127.0.0.1:8765'
& '.venv\Scripts\python.exe' launch.py
