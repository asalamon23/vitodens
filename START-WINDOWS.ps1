# Run this script from the same folder as VitodensSmart.exe.
# You can also follow BUILD-WINDOWS.md to start manually.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (!(Test-Path '.\VitodensSmart.exe')) { Write-Host 'Place VitodensSmart.exe next to this script.'; Read-Host 'Press Enter'; exit 1 }
$client = Read-Host 'Paste your Viessmann OAuth Client ID (not your password)'
if ([string]::IsNullOrWhiteSpace($client)) { Write-Host 'Client ID is required.'; Read-Host 'Press Enter'; exit 1 }
$env:VIESSMANN_CLIENT_ID = $client.Trim()
$env:FLASK_SECRET_KEY = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
try { & '.\VitodensSmart.exe' } finally { Read-Host 'App stopped. Press Enter to close this window' }
