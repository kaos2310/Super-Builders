[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$oldPythonPath=$env:PYTHONPATH
$env:PYTHONPATH=Join-Path $root '.build-deps'
Push-Location -LiteralPath $root
try {
    $webData=(Join-Path $root 'web')+';web'
    $configData=(Join-Path $root 'config.json')+';.'
    $iconPath=Join-Path $PSScriptRoot 'icon.ico'
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name 'SukiSU-Build-Center-1.0.0' --icon $iconPath --add-data $webData --add-data $configData --distpath dist --workpath build/windows --specpath build desktop.py
    if($LASTEXITCODE -ne 0){throw 'Windows-Build fehlgeschlagen.'}
    Get-FileHash -LiteralPath (Join-Path $root 'dist\SukiSU-Build-Center-1.0.0.exe') -Algorithm SHA256
} finally { Pop-Location; $env:PYTHONPATH=$oldPythonPath }
