$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pilotMailUser = Read-Host 'Gmail address (must match your LANCE profile email)'
$pilotMailSecret = Read-Host 'Gmail app password (hidden; not your normal password)' -AsSecureString
$pilotMailPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pilotMailSecret)
try {
    $env:SMTP_USER = $pilotMailUser
    $env:SMTP_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pilotMailPointer)
    $env:SMTP_HOST = 'smtp.gmail.com'
    $env:SMTP_PORT = '465'
    $env:IMAP_HOST = 'imap.gmail.com'
    & (Join-Path $PSScriptRoot 'run.ps1')
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pilotMailPointer)
    Remove-Item Env:SMTP_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:SMTP_USER -ErrorAction SilentlyContinue
}
